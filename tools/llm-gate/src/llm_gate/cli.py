"""llm-gate command line. Exit codes: 0 pass, 1 blocking findings, 2 infrastructure error."""

import argparse
import json
import logging
import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from .cache import Cache
from .compare import render_comparison
from .config import ENGINES, Check, ConfigError, load_config
from .diff import DiffError, merge_base_diff, repo_root
from .engines import Engine
from .policy import EXIT_ERROR
from .report import render_markdown, render_sarif
from .runner import RunRecord, read_records, run_check, write_record

log = logging.getLogger("llm_gate")


def default_engines() -> dict[str, Engine]:
    # Imported lazily so `list` and `report` work without either SDK being importable.
    from .engines.agent_engine import AgentEngine
    from .engines.api_engine import ApiEngine

    return {"api": ApiEngine(), "agent": AgentEngine()}


def _override_from_env() -> bool:
    return os.environ.get("LLM_GATE_OVERRIDE", "").lower() in {"1", "true", "yes"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="llm-gate", description=__doc__)
    parser.add_argument(
        "--repo",
        type=Path,
        help="repository under review: the diff and the agent's read-only context "
        "(default: the git repository of the current directory)",
    )
    parser.add_argument(
        "--config",
        type=Path,
        help="checks.yaml (default: <repo>/tools/llm-gate/checks.yaml); the prompts come from "
        "the same checkout's .claude/commands/, so CI can run the gate from the base branch",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    list_ = sub.add_parser("list", help="list the configured checks")
    list_.add_argument("--json", action="store_true", help="JSON array of names (CI matrix)")
    list_.add_argument("--blocking", action="store_true", help="only blocking checks")

    run = sub.add_parser("run", help="review the current branch with one check")
    run.add_argument("--check", required=True)
    run.add_argument("--engine", choices=[*ENGINES, "both"], help="default: the check's engine")
    run.add_argument(
        "--base",
        default=os.environ.get("LLM_GATE_BASE") or "origin/main",
        help="branch point (default: $LLM_GATE_BASE or origin/main)",
    )
    run.add_argument("--out", type=Path, help="output directory (default: <repo>/.llm-gate)")
    run.add_argument("--no-cache", action="store_true")
    run.add_argument(
        "--override",
        action="store_true",
        default=_override_from_env(),
        help="report blocking findings without failing (also LLM_GATE_OVERRIDE=1)",
    )

    compare = sub.add_parser("compare", help="compare the api and agent results of a check")
    compare.add_argument("--check", required=True)
    compare.add_argument("--in", dest="in_dir", type=Path)

    report = sub.add_parser("report", help="render stored results")
    report.add_argument("--in", dest="in_dir", type=Path)
    report.add_argument("--check", help="only this check")
    report.add_argument("--format", choices=["md", "sarif"], default="md")
    return parser


def cmd_list(checks: Mapping[str, Check], *, as_json: bool, blocking_only: bool) -> int:
    selected = [c for c in checks.values() if c.blocking or not blocking_only]
    if as_json:
        print(json.dumps([c.name for c in selected]))
        return 0
    for c in selected:
        rule = f"fail_on={c.fail_on}" if c.blocking else "never fails"
        paths = f" paths={','.join(c.paths)}" if c.paths else ""
        print(f"{c.name:<18} {c.mode:<9} {rule:<16} {c.engine:<6} {c.model}{paths}")
    return 0


def cmd_run(
    check: Check,
    *,
    root: Path,
    out: Path,
    base: str,
    engine_choice: str | None,
    use_cache: bool,
    override: bool,
    engines: Mapping[str, Engine],
) -> int:
    names = list(ENGINES) if engine_choice == "both" else [engine_choice or check.engine]
    # With --engine both the check's configured engine decides the exit code.
    primary = check.engine if engine_choice == "both" else names[0]

    diff = merge_base_diff(root, base)
    out.mkdir(parents=True, exist_ok=True)
    diff_path = out / "diff.patch"
    diff_path.write_text(diff.text, encoding="utf-8")
    cache = Cache(out / "cache") if use_cache else None

    records: dict[str, RunRecord] = {}
    for name in names:
        record = run_check(
            check,
            engines[name],
            diff=diff,
            diff_path=diff_path,
            repo_root=root,
            cache=cache,
            override=override,
        )
        write_record(out, record)
        records[name] = record

    markdown = render_markdown(records[primary])
    (out / f"{check.name}.md").write_text(markdown, encoding="utf-8")
    print(markdown, end="")
    if len(records) == 2:
        print()
        print(render_comparison(records["api"], records["agent"]), end="")
    return records[primary].exit_code


def cmd_compare(out: Path, check: str) -> int:
    records = {r.engine: r for r in read_records(out, check)}
    if not {"api", "agent"} <= records.keys():
        found = ", ".join(sorted(records)) or "none"
        log.error("need results from both engines for %s in %s (found: %s)", check, out, found)
        return EXIT_ERROR
    print(render_comparison(records["api"], records["agent"]), end="")
    return 0


def cmd_report(out: Path, check: str | None, fmt: str) -> int:
    records = read_records(out, check)
    if not records:
        log.error("no results in %s", out / "results")
        return EXIT_ERROR
    if fmt == "sarif":
        print(json.dumps(render_sarif(records), indent=2))
    else:
        print("\n".join(render_markdown(r) for r in records), end="")
    return 0


def main(argv: Sequence[str] | None = None, engines: Mapping[str, Engine] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="llm-gate: %(message)s",
        stream=sys.stderr,
    )
    try:
        root = repo_root(args.repo or Path.cwd())
        config = args.config or root / "tools" / "llm-gate" / "checks.yaml"
        # The gate's own checkout (config + prompts) may differ from the reviewed one (ADR 0004).
        try:
            gate_root = repo_root(config.resolve().parent)
        except DiffError as error:
            raise ConfigError(
                f"--config {config} must be inside a git checkout (the gate's own): {error}"
            ) from error
        checks = load_config(config, gate_root)
        if args.command == "list":
            return cmd_list(checks, as_json=args.json, blocking_only=args.blocking)

        out = getattr(args, "in_dir", None) or getattr(args, "out", None) or root / ".llm-gate"
        if args.command == "compare":
            return cmd_compare(out, args.check)
        if args.command == "report":
            return cmd_report(out, args.check, args.format)

        if args.check not in checks:
            log.error("unknown check %r (known: %s)", args.check, ", ".join(checks))
            return EXIT_ERROR
        return cmd_run(
            checks[args.check],
            root=root,
            out=out,
            base=args.base,
            engine_choice=args.engine,
            use_cache=not args.no_cache,
            override=args.override,
            engines=engines or default_engines(),
        )
    except (ConfigError, DiffError) as error:
        log.error("%s", error)
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())

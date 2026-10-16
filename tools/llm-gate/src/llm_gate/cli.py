"""llm-gate command line. Exit codes: 0 pass, 1 blocking findings, 2 infrastructure error."""

import argparse
import json
import logging
import os
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from . import audit
from .cache import Cache
from .compare import render_comparison
from .config import ENGINES, Check, ConfigError, load_config
from .diff import DiffError, git, merge_base_diff, repo_root
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


def _timestamp(value: str | None) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value) if value else None
    except ValueError:
        return None
    return parsed if parsed is None or parsed.tzinfo else parsed.replace(tzinfo=UTC)


@dataclass(frozen=True)
class GateCheckout:
    """The checkout the gate itself runs from (config, prompts) and the commit it is at."""

    root: Path
    config: Path
    sha: str | None


def _head(root: Path) -> str | None:
    try:
        return git(root, "rev-parse", "HEAD").strip()
    except DiffError:
        return None


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
        help="report blocking findings without failing (also LLM_GATE_OVERRIDE=1); "
        "honoured only with --override-reason",
    )
    run.add_argument(
        "--override-reason",
        default=os.environ.get("LLM_GATE_OVERRIDE_REASON") or None,
        help="why the findings are overridden (also $LLM_GATE_OVERRIDE_REASON)",
    )
    run.add_argument(
        "--override-by",
        default=os.environ.get("LLM_GATE_OVERRIDE_BY") or None,
        help="who overrode (also $LLM_GATE_OVERRIDE_BY)",
    )

    compare = sub.add_parser("compare", help="compare the api and agent results of a check")
    compare.add_argument("--check", required=True)
    compare.add_argument("--in", dest="in_dir", type=Path)

    report = sub.add_parser("report", help="render stored results")
    report.add_argument("--in", dest="in_dir", type=Path)
    report.add_argument("--check", help="only this check")
    report.add_argument("--format", choices=["md", "sarif"], default="md")

    audit_ = sub.add_parser("audit", help="audit records (docs/adr/0005-audit-trail.md)")
    asub = audit_.add_subparsers(dest="audit_command", required=True)

    skip = asub.add_parser("skip", help="record a check that did not run")
    skip.add_argument("--check", required=True)
    skip.add_argument("--reason", choices=["skipped_no_key", "not_needed"], required=True)
    skip.add_argument("--out", type=Path, help="output directory (default: <repo>/.llm-gate)")

    expected = argparse.ArgumentParser(add_help=False)
    expected.add_argument("--repo-name", required=True, help="owner/name of the repository")
    expected.add_argument("--run-id", type=int, required=True)
    expected.add_argument("--run-attempt", type=int, required=True)
    expected.add_argument("--head-sha", required=True)
    expected.add_argument("--pr", type=int, required=True)

    validate = asub.add_parser(
        "validate", parents=[expected], help="strictly check an untrusted audit file"
    )
    validate.add_argument("file", type=Path)
    validate.add_argument("--check", help="the check the file's artifact is named after")

    collect = asub.add_parser(
        "collect", parents=[expected], help="validate downloaded audit artifacts for the log"
    )
    collect.add_argument("--artifacts", type=Path, required=True, help="one directory each")
    collect.add_argument(
        "--jobs", type=Path, required=True, help="job conclusions, one JSON object per line"
    )
    collect.add_argument(
        "--workflow-modified", action="store_true", help="the PR changed the review workflow"
    )
    collect.add_argument("--out", type=Path, required=True)
    collect.add_argument("--date", type=date.fromisoformat, help="default: today (UTC)")
    collect.add_argument(
        "--events", type=Path, required=True, help="the PR's issue events (JSON array)"
    )
    collect.add_argument(
        "--comments", type=Path, required=True, help="the PR's issue comments (JSON array)"
    )

    override = asub.add_parser("override", help="find the reason for the override label")
    override.add_argument("--events", type=Path, required=True, help="issue events (JSON array)")
    override.add_argument(
        "--comments", type=Path, required=True, help="issue comments (JSON array)"
    )
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
    gate: GateCheckout,
    out: Path,
    base: str,
    engine_choice: str | None,
    use_cache: bool,
    override: audit.OverrideRequest | None,
    engines: Mapping[str, Engine],
) -> int:
    names = list(ENGINES) if engine_choice == "both" else [engine_choice or check.engine]
    # With --engine both the check's configured engine decides the exit code.
    primary = check.engine if engine_choice == "both" else names[0]

    started = datetime.now(UTC)
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
            override=override is not None,
        )
        write_record(out, record)
        records[name] = record

    context = audit.context_from_env(
        os.environ, head_sha=_head(root), base_sha=_merge_base(root, base)
    )
    info = audit.gate_info(check, config=gate.config, gate_root=gate.root, gate_sha=gate.sha)
    finished = datetime.now(UTC)
    entries: list[audit.GateRun | audit.Override] = [
        audit.gate_run(
            record,
            check=check,
            context=context,
            gate=info,
            diff_text=diff.text,
            started_at=started,
            finished_at=finished,
            pr_event_at=_timestamp(os.environ.get("LLM_GATE_PR_EVENT_AT")),
        )
        for record in records.values()
    ]
    if override is not None:
        entries.append(
            audit.Override(
                **context.model_dump(), by=override.by, reason=override.reason, checks=[check.name]
            )
        )
    audit.append(out / audit.AUDIT_FILE, entries)

    markdown = render_markdown(records[primary])
    (out / f"{check.name}.md").write_text(markdown, encoding="utf-8")
    print(markdown, end="")
    if len(records) == 2:
        print()
        print(render_comparison(records["api"], records["agent"]), end="")
    return records[primary].exit_code


def _merge_base(root: Path, base: str) -> str | None:
    try:
        return git(root, "merge-base", base, "HEAD").strip()
    except DiffError:
        return None


def override_request(
    requested: bool, reason: str | None, by: str | None
) -> audit.OverrideRequest | None:
    if not requested:
        return None
    if not reason or not reason.strip():
        log.warning("override requested without a reason: not honoured (ADR 0005)")
        return None
    return audit.OverrideRequest(
        by=by or os.environ.get("GITHUB_ACTOR") or None, reason=reason.strip()
    )


def cmd_skip(check: Check, *, root: Path, gate: GateCheckout, out: Path, reason: str) -> int:
    context = audit.context_from_env(os.environ, head_sha=_head(root), base_sha=None)
    info = audit.gate_info(check, config=gate.config, gate_root=gate.root, gate_sha=gate.sha)
    verdict: audit.GateVerdict = "not_needed" if reason == "not_needed" else "skipped_no_key"
    entry = audit.skipped_run(
        check, context=context, gate=info, reason=verdict, at=datetime.now(UTC)
    )
    audit.append(out / audit.AUDIT_FILE, [entry])
    return 0


def _expected(args: argparse.Namespace) -> audit.Expected:
    return audit.Expected(
        repo=args.repo_name,
        workflow_run_id=args.run_id,
        run_attempt=args.run_attempt,
        head_sha=args.head_sha,
        pr=args.pr,
    )


def _find_override(args: argparse.Namespace) -> audit.OverrideRequest | str:
    return audit.find_override(
        json.loads(args.events.read_text(encoding="utf-8")),
        json.loads(args.comments.read_text(encoding="utf-8")),
    )


def cmd_audit(args: argparse.Namespace) -> int:
    """The audit subcommands that need no repository (the trusted collector's side)."""
    try:
        return _audit(args)
    except (OSError, ValueError, KeyError) as error:  # unreadable or malformed input files
        log.error("audit %s: %s: %s", args.audit_command, type(error).__name__, error)
        return EXIT_ERROR


def _audit(args: argparse.Namespace) -> int:
    if args.audit_command == "validate":
        records, problems = audit.validate_file(args.file, _expected(args), args.check)
        for problem in problems:
            print(problem)
        if not problems:
            print(f"{args.file}: {len(records)} valid record(s)")
        return 1 if problems else 0
    if args.audit_command == "collect":
        collected = audit.collect(
            args.artifacts,
            expected=_expected(args),
            jobs=audit.read_jobs(args.jobs),
            workflow_modified=args.workflow_modified,
            override=_find_override(args),
            out=args.out,
            day=args.date or datetime.now(UTC).date(),
        )
        print(json.dumps([vars(c) for c in collected]))
        return 0
    found = _find_override(args)
    if isinstance(found, str):
        print(found, file=sys.stderr)
        return 1
    print(json.dumps(vars(found)))
    return 0


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
        if args.command == "audit" and args.audit_command != "skip":
            return cmd_audit(args)
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
        gate = GateCheckout(root=gate_root, config=config, sha=_head(gate_root))
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
        if args.command == "audit":
            return cmd_skip(checks[args.check], root=root, gate=gate, out=out, reason=args.reason)
        return cmd_run(
            checks[args.check],
            root=root,
            gate=gate,
            out=out,
            base=args.base,
            engine_choice=args.engine,
            use_cache=not args.no_cache,
            override=override_request(args.override, args.override_reason, args.override_by),
            engines=engines or default_engines(),
        )
    except (ConfigError, DiffError) as error:
        log.error("%s", error)
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())

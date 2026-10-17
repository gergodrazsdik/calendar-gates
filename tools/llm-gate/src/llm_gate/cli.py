"""llm-gate command line. Exit codes: 0 pass, 1 blocking findings, 2 infrastructure error."""

import argparse
import json
import logging
import os
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from pathlib import Path

from pydantic import ValidationError

from . import aidetect, audit, evals, feedback, metrics, triage
from .cache import Cache
from .compare import render_comparison
from .config import (
    ENGINES,
    RISKS,
    TRIAGE,
    Check,
    ConfigError,
    GateConfig,
    Risk,
    TriageConfig,
    load_gate_config,
)
from .diff import DiffError, git, merge_base_diff, repo_root
from .engines import Engine
from .policy import EXIT_ERROR
from .redact import clip, redact
from .report import render_markdown, render_sarif
from .runner import RunRecord, read_records, run_check, write_record

log = logging.getLogger("llm_gate")


def _lazy_engines(args: argparse.Namespace) -> dict[str, Engine]:
    # `eval baseline` and `eval add-from-fp` call no model, so they don't need the SDKs.
    return default_engines() if args.eval_command == "run" else {}


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


WRITERS_HELP = (
    "logins with write access (JSON array; scripts/override-writers.sh): needed to honour a "
    "llm-override label added by the feedback workflow"
)


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
    run.add_argument(
        "--risk",
        choices=RISKS,
        default=os.environ.get("LLM_GATE_RISK") or None,
        help="the PR's triage risk (also $LLM_GATE_RISK): decides whether the check is needed, "
        "blocks, and its engine and model (checks.yaml triage.levels)",
    )

    tri = sub.add_parser("triage", help="the PR's risk level and checks plan (ADR 0008)")
    tri.add_argument(
        "--base",
        default=os.environ.get("LLM_GATE_BASE") or "origin/main",
        help="branch point (default: $LLM_GATE_BASE or origin/main)",
    )
    tri.add_argument(
        "--pr-data",
        type=Path,
        help="JSON {body, head_ref, commits: [GitHub commit objects or messages]} for AI detection",
    )
    tri.add_argument("--audit-dir", type=Path, help="audit-log checkout (manual /llm-risk changes)")
    tri.add_argument("--no-model", action="store_true", help="rules only (no API key)")
    tri.add_argument("--out", type=Path, help="output directory (default: <repo>/.llm-gate)")
    tri.add_argument("--no-cache", action="store_true")

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
    skip.add_argument("--risk", choices=RISKS, default=os.environ.get("LLM_GATE_RISK") or None)
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
        "--checks",
        type=json.loads,
        required=True,
        help="the default branch's checks as a JSON array (`llm-gate list --json`)",
    )
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
    collect.add_argument("--writers", type=Path, help=WRITERS_HELP)
    collect.add_argument(
        "--triage-inputs",
        type=Path,
        help="JSON {compare_files (null if truncated), body, head_ref, commits, run_started_at}: "
        "what the collector recomputes the run's triage floor from (ADR 0008)",
    )
    collect.add_argument(
        "--audit-dir", type=Path, help="audit-log checkout (the PR's /llm-risk changes)"
    )

    override = asub.add_parser("override", help="find the reason for the override label")
    override.add_argument("--events", type=Path, required=True, help="issue events (JSON array)")
    override.add_argument(
        "--comments", type=Path, required=True, help="issue comments (JSON array)"
    )
    override.add_argument("--writers", type=Path, help=WRITERS_HELP)

    eval_ = sub.add_parser("eval", help="score the review prompts on known cases (evals/)")
    esub = eval_.add_subparsers(dest="eval_command", required=True)
    erun = esub.add_parser("run", help="run cases and print the scores")
    erun.add_argument(
        "--check", action="append", help="repeatable; default: every check the cases name"
    )
    erun.add_argument("--engine", choices=[*ENGINES, "both"], help="default: the check's engine")
    erun.add_argument("--model", help="override the check's model")
    erun.add_argument("--repeats", type=int, default=3)
    erun.add_argument("--jobs", type=int, default=4, help="cases reviewed in parallel")
    erun.add_argument("--cases", default="*", help="glob over case directory names")
    erun.add_argument("--budget-usd", type=float, help="default: thresholds.yaml budget_usd")
    erun.add_argument(
        "--compare", action="store_true", help="fail (exit 1) when worse than baseline.json"
    )
    erun.add_argument("--out", type=Path, help="report directory (default: <repo>/reports/eval)")
    erun.add_argument("--no-cache", action="store_true")
    ebase = esub.add_parser("baseline", help="write evals/baseline.json from the last run")
    ebase.add_argument("--in", dest="in_dir", type=Path, help="default: <repo>/reports/eval")
    fb = sub.add_parser("feedback", help="/llm-* PR comment commands (llm-feedback.yml)")
    fbsub = fb.add_subparsers(dest="feedback_command", required=True)
    fbh = fbsub.add_parser("handle", help="validate a comment event; print the actions as JSON")
    fbh.add_argument("--event", type=Path, required=True, help="the issue_comment event payload")
    fbh.add_argument("--audit-dir", type=Path, required=True, help="audit-log checkout")
    fbh.add_argument("--out", type=Path, required=True, help="where the record file is written")
    fbh.add_argument(
        "--permission", help="the commenter's repository role (collaborators/<login>/permission)"
    )
    fbm = fbsub.add_parser("mark", help="mark a finding as a false positive in a sticky comment")
    fbm.add_argument("--body-file", type=Path, required=True)
    fbm.add_argument("--finding", required=True)
    fbm.add_argument("--by", required=True)

    met = sub.add_parser("metrics", help="gate health report over the audit log (Markdown)")
    met.add_argument("--audit-dir", type=Path, help="default: <repo>/.audit-log")
    met.add_argument("--prs", type=Path, help="merged PRs from the GitHub API (JSON array)")
    met.add_argument("--eval-reports", type=Path, help="reports/eval of the latest eval run")
    met.add_argument("--since-days", type=int, default=30)

    efp = esub.add_parser("add-from-fp", help="turn a false positive into an fp-regression case")
    efp.add_argument("finding_id")
    efp.add_argument(
        "--audit-dir", type=Path, help="audit-log checkout (default: <repo>/.audit-log)"
    )
    return parser


def _at_risk(config: GateConfig, name: str, risk: Risk | None) -> tuple[Check, str | None]:
    """The check as it runs at the PR's risk level, and why it isn't needed (or None)."""
    check = config.checks[name]
    if risk is None:
        return check, None
    if config.triage is None:
        raise ConfigError("--risk given, but checks.yaml has no triage section")
    planned = triage.plan_for(risk, config.triage, config.checks)[name]
    if planned is None:
        return check, f"not needed at risk: {risk}"
    return planned, None


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
    risk: Risk | None = None,
    not_needed: str | None = None,
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
            not_needed=not_needed,
        ).model_copy(update={"risk": risk})
        write_record(out, record)
        records[name] = record

    finished = datetime.now(UTC)
    try:
        context = audit.context_from_env(
            os.environ, head_sha=_head(root), base_sha=_merge_base(root, base)
        )
        info = audit.gate_info(check, config=gate.config, gate_root=gate.root, gate_sha=gate.sha)
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
                risk=risk,
            )
            for record in records.values()
        ]
        if override is not None and not_needed is None:
            entries.append(
                audit.Override(
                    **context.model_dump(),
                    by=override.by,
                    reason=override.reason,
                    checks=[check.name],
                )
            )
        audit.append(out / audit.AUDIT_FILE, entries)
    except (ValidationError, OSError) as error:
        # The review is done and decided; a record that can't be built or written must not
        # change that. The missing record shows up as a gap in the audit log.
        log.error("audit record not written: %s", error)

    markdown = render_markdown(records[primary])
    (out / f"{check.name}.md").write_text(markdown, encoding="utf-8")
    print(markdown, end="")
    if len(records) == 2:
        print()
        print(render_comparison(records["api"], records["agent"]), end="")
    return records[primary].exit_code


def _inert(text: str, limit: int = 200) -> str:
    """Model- or comment-written text for the job summary: redacted, capped, one line, and in a
    code span, so it can't add links, images or markup."""
    flat = " ".join(clip(redact(text), limit).split()).replace("`", "'")
    return f"`{flat}`"


def cmd_triage(args: argparse.Namespace, gate_config: GateConfig, *, root: Path, out: Path) -> int:
    """Writes the triage record to <out>/audit.jsonl and <out>/triage.md; prints the decision as
    JSON (`risk`, `ai_assisted`, `checks_plan`) for the workflow."""
    config = gate_config.triage
    if config is None:  # every check runs as configured
        log.warning("checks.yaml has no triage section")
        print(
            json.dumps(
                {"risk": None, "ai_assisted": False, "checks_plan": sorted(gate_config.checks)}
            )
        )
        return 0
    changes = triage.numstat(root, args.base)
    pr_data = json.loads(args.pr_data.read_text(encoding="utf-8")) if args.pr_data else {}
    detection = aidetect.detect(
        aidetect.commit_messages(pr_data.get("commits") or []),
        pr_data.get("body"),
        pr_data.get("head_ref"),
        gate_config.ai_markers,
    )
    floor = triage.floor(changes, ai_assisted=detection.assisted, config=config)
    out.mkdir(parents=True, exist_ok=True)
    model: triage.ModelRisk | None = None
    if not args.no_model:
        model = triage.assess(
            config,
            changes,
            merge_base_diff(root, args.base).text,
            base=args.base,
            cache_dir=None if args.no_cache else out / "cache",
        )
    context = audit.context_from_env(
        os.environ, head_sha=_head(root), base_sha=_merge_base(root, args.base)
    )
    manual = triage.latest_risk_override(args.audit_dir, context.pr)
    decision = triage.final_risk(floor.risk, model.risk if model else None, manual)
    plan = triage.checks_plan(decision.final, config, gate_config.checks)
    try:
        record = audit.Triage(
            **context.model_dump(),
            rules_risk=floor.risk,
            rules_reasons=floor.reasons,
            model=model.model if model else None,
            model_risk=model.risk if model else None,
            reasons=model.reasons if model else [],
            final_risk=decision.final,
            source=decision.source,
            ai_assisted=detection.assisted,
            ai_commits=detection.ai_commits,
            total_commits=detection.total_commits,
            changed_lines=floor.lines,
            cost_usd=model.cost_usd if model else None,
            cache_hit=model.cached if model else False,
            error=model.error if model else None,
            checks_plan=plan,
        )
        audit.append(out / audit.AUDIT_FILE, [record])
    except (ValidationError, OSError) as error:
        log.error("triage record not written: %s", error)  # a gap in the log, not a failed job

    lines = [f"### Triage: risk **{decision.final}** ({decision.source})", ""]
    lines += [f"- rules: **{floor.risk}**"] + [f"  - {reason}" for reason in floor.reasons]
    if model is not None:
        got = f"**{model.risk}**" if model.risk else f"none ({_inert(model.error or '')})"
        lines += [f"- model `{model.model}`: {got}"] + [f"  - {_inert(r)}" for r in model.reasons]
    if manual is not None:
        lines.append(f"- manual: **{manual.to}** by @{manual.by}: {_inert(manual.reason)}")
    lines.append(f"- AI-assisted: {', '.join(detection.matched) or 'no markers'}")
    lines.append(f"- checks that run: {', '.join(plan)}")
    (out / "triage.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "risk": decision.final,
                "source": decision.source,
                "ai_assisted": detection.assisted,
                "checks_plan": plan,
            }
        )
    )
    return 0


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
        by=by or None,
        reason=reason.strip(),  # never guessed: the collector compares it
    )


def cmd_skip(
    check: Check, *, root: Path, gate: GateCheckout, out: Path, reason: str, risk: Risk | None
) -> int:
    verdict: audit.GateVerdict = "not_needed" if reason == "not_needed" else "skipped_no_key"
    try:
        context = audit.context_from_env(os.environ, head_sha=_head(root), base_sha=None)
        info = audit.gate_info(check, config=gate.config, gate_root=gate.root, gate_sha=gate.sha)
        entry = audit.skipped_run(
            check, context=context, gate=info, reason=verdict, at=datetime.now(UTC), risk=risk
        )
        audit.append(out / audit.AUDIT_FILE, [entry])
    except (ValidationError, OSError) as error:
        log.error("audit record not written: %s", error)  # a gap in the log, not a failed job
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
    writers = (
        {str(login) for login in json.loads(args.writers.read_text(encoding="utf-8"))}
        if args.writers
        else None
    )
    return audit.find_override(
        json.loads(args.events.read_text(encoding="utf-8")),
        json.loads(args.comments.read_text(encoding="utf-8")),
        writers=writers,
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
            checks=frozenset(str(name) for name in args.checks),
            jobs=audit.read_jobs(args.jobs),
            workflow_modified=args.workflow_modified,
            override=_find_override(args),
            out=args.out,
            day=args.date or datetime.now(UTC).date(),
            triage=_triage_expected(args),
        )
        print(json.dumps([vars(c) for c in collected]))
        return 0
    found = _find_override(args)
    if isinstance(found, str):
        print(found, file=sys.stderr)
        return 1
    print(json.dumps(vars(found)))
    return 0


def _triage_expected(args: argparse.Namespace) -> audit.TriageExpected | None:
    """The triage the collector expects, computed from the default branch's checks.yaml and
    inputs fetched by the trusted workflow, never from the artifact."""
    if args.triage_inputs is None:
        return None
    root = repo_root(args.repo or Path.cwd())
    config_path = args.config or root / "tools" / "llm-gate" / "checks.yaml"
    config = load_gate_config(config_path, repo_root(config_path.resolve().parent))
    data = json.loads(args.triage_inputs.read_text(encoding="utf-8"))
    files = data.get("compare_files")
    if config.triage is None or files is None:  # no triage, or too many files to recompute
        return None
    detection = aidetect.detect(
        aidetect.commit_messages(data.get("commits") or []),
        data.get("body"),
        data.get("head_ref"),
        config.ai_markers,
    )
    floor = triage.floor(
        triage.changes_from_compare(files), ai_assisted=detection.assisted, config=config.triage
    )
    started = _timestamp(data.get("run_started_at"))
    required = triage.latest_risk_override(args.audit_dir, args.pr, before=started)
    latest = triage.latest_risk_override(args.audit_dir, args.pr)
    plans: dict[Risk, dict[str, bool | None]] = {
        risk: {
            name: None if check is None else check.blocking
            for name, check in triage.plan_for(risk, config.triage, config.checks).items()
        }
        for risk in RISKS
    }
    return audit.TriageExpected(
        rules_risk=floor.risk,
        ai_assisted=detection.assisted,
        manual_required=required.to if required else None,
        manual_allowed=frozenset(m.to for m in (required, latest) if m is not None),
        plans=plans,
    )


def cmd_eval(
    args: argparse.Namespace,
    checks: Mapping[str, Check],
    *,
    root: Path,
    config: Path,
    engines: Mapping[str, Engine],
    triage_config: TriageConfig | None = None,
) -> int:
    evals_dir = config.parent / "evals"
    cases_dir = evals_dir / "cases"
    reports = (getattr(args, "out", None) or getattr(args, "in_dir", None)) or (
        root / "reports" / "eval"
    )
    if args.eval_command == "baseline":
        last = evals.read_last(reports)
        evals.update_baseline(evals_dir / "baseline.json", last)
        print(evals.render_runs(last), end="")
        print(f"\nwrote {evals_dir / 'baseline.json'} ({len(last)} run(s))")
        return 0
    if args.eval_command == "add-from-fp":
        directory = evals.case_from_false_positive(
            args.finding_id,
            audit_dir=args.audit_dir or root / ".audit-log",
            repo_root=root,
            cases_dir=cases_dir,
        )
        print(f"wrote {directory}; review it and commit it with the change that fixes the prompt")
        return 0

    cases = evals.load_cases(cases_dir, args.cases)
    if not cases:
        log.error("no cases match %r in %s", args.cases, cases_dir)
        return EXIT_ERROR
    names = args.check or sorted({c for loaded in cases for c in loaded.case.checks})
    with_triage = TRIAGE in names
    names = [n for n in names if n != TRIAGE]
    if with_triage and triage_config is None:
        log.error("triage cases, but checks.yaml has no triage section")
        return EXIT_ERROR
    unknown = [n for n in names if n not in checks]
    if unknown:
        log.error("unknown check(s) %s (known: %s)", ", ".join(unknown), ", ".join(checks))
        return EXIT_ERROR
    thresholds = evals.load_thresholds(evals_dir / "thresholds.yaml")
    budget = args.budget_usd if args.budget_usd is not None else thresholds.budget_usd
    cache = None if args.no_cache else Cache(root / ".llm-gate" / "cache")

    runs: list[evals.EvalRun] = []
    if with_triage and triage_config is not None:
        model = args.model or triage_config.model
        runs.append(
            evals.run_triage_eval(
                replace(triage_config, model=model),
                cases,
                cache_dir=cache.directory if cache else None,
                repeats=args.repeats,
                budget_usd=budget,
                progress=log.info,
                jobs=args.jobs,
            )
        )
    for name in names:
        check = checks[name]
        if args.model:
            check = replace(check, model=args.model)
        engine_names = list(ENGINES) if args.engine == "both" else [args.engine or check.engine]
        for engine_name in engine_names:
            runs.append(
                evals.run_eval(
                    check,
                    engines[engine_name],
                    cases,
                    repo_root=root,
                    cache=cache,
                    repeats=args.repeats,
                    budget_usd=budget,
                    spent=lambda: sum(r.metrics.spent_usd for r in runs),
                    progress=log.info,
                    jobs=args.jobs,
                )
            )

    evals.write_report(reports, runs)
    _record_eval_runs(runs, root=root)
    print(evals.render_runs(runs), end="")
    misses = evals.render_misses(runs)
    if misses:
        print("\n<details><summary>Misses, wrong verdicts, flips</summary>\n")
        print(misses + "\n</details>")
    failed = False
    if args.compare:
        baseline_path = evals_dir / "baseline.json"
        baseline = (
            json.loads(baseline_path.read_text(encoding="utf-8")) if baseline_path.exists() else {}
        )
        print("\n### Against the baseline\n")
        for run in runs:
            rows = evals.compare(run, baseline, thresholds)
            failed |= not all(row.ok for row in rows)
            print(evals.render_comparison(run, rows))
    if not all(run.complete for run in runs):
        log.error("the budget of $%.2f ran out before every case ran", budget)
        return EXIT_ERROR
    return 1 if failed else 0


def cmd_feedback(args: argparse.Namespace, checks: Mapping[str, Check]) -> int:
    if args.feedback_command == "mark":
        body = args.body_file.read_text(encoding="utf-8")
        marked = feedback.mark_false_positive(body, args.finding, args.by)
        if marked is None:
            log.warning("finding %s not in the comment, or already marked", args.finding)
            return 1
        print(marked, end="")
        return 0
    event = json.loads(args.event.read_text(encoding="utf-8"))
    context = audit.context_from_env(os.environ, head_sha=None, base_sha=None)
    actions = feedback.handle(
        event,
        audit_dir=args.audit_dir,
        blocking_checks=[c.name for c in checks.values() if c.blocking],
        context=context,
        now=datetime.now(UTC),
        permission=args.permission,
    )
    if actions.path and actions.records:
        target = args.out / actions.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("".join(line + "\n" for line in actions.records), encoding="utf-8")
    print(actions.to_json())
    return 0


def cmd_metrics(args: argparse.Namespace, checks: Mapping[str, Check], *, root: Path) -> int:
    audit_dir = args.audit_dir or root / ".audit-log"
    if not (audit_dir / "events").is_dir():
        log.error("no audit log in %s (run `just audit-pull`)", audit_dir)
        return EXIT_ERROR
    prs = json.loads(args.prs.read_text(encoding="utf-8")) if args.prs else []
    now = datetime.now(UTC)
    report = metrics.compute(
        metrics.load_records(audit_dir),
        prs,
        blocking_checks=[c.name for c in checks.values() if c.blocking],
        now=now,
        since_days=args.since_days,
        eval_runs=metrics.load_eval_runs(args.eval_reports),
    )
    print(metrics.render(report, generated=now), end="")
    return 0


def _record_eval_runs(runs: Sequence[evals.EvalRun], *, root: Path) -> None:
    try:
        context = audit.context_from_env(os.environ, head_sha=_head(root), base_sha=None)
        records = [
            audit.EvalRun(
                **context.model_dump(),
                prompt_sha256=run.prompt_sha256,
                model=run.model,
                engine=run.engine,  # type: ignore[arg-type]  # an engine's name; pydantic checks
                scores={
                    f"{run.check}.{name}": float(value)
                    for name, value in run.metrics.model_dump().items()
                    if isinstance(value, int | float)
                },
            )
            for run in runs
        ]
        audit.append(root / ".llm-gate" / audit.AUDIT_FILE, records)
    except (ValidationError, OSError) as error:
        log.error("eval audit record not written: %s", error)


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
        gate_config = load_gate_config(config, gate_root)
        checks = gate_config.checks
        gate = GateCheckout(root=gate_root, config=config, sha=_head(gate_root))
        if args.command == "triage":
            return cmd_triage(args, gate_config, root=root, out=args.out or root / ".llm-gate")
        if args.command == "list":
            return cmd_list(checks, as_json=args.json, blocking_only=args.blocking)
        if args.command == "feedback":
            return cmd_feedback(args, checks)
        if args.command == "metrics":
            return cmd_metrics(args, checks, root=root)
        if args.command == "eval":
            return cmd_eval(
                args,
                checks,
                root=root,
                config=config,
                engines=engines or _lazy_engines(args),
                triage_config=gate_config.triage,
            )

        out = getattr(args, "in_dir", None) or getattr(args, "out", None) or root / ".llm-gate"
        if args.command == "compare":
            return cmd_compare(out, args.check)
        if args.command == "report":
            return cmd_report(out, args.check, args.format)

        if args.check not in checks:
            log.error("unknown check %r (known: %s)", args.check, ", ".join(checks))
            return EXIT_ERROR
        check, not_needed = _at_risk(gate_config, args.check, args.risk)
        if args.command == "audit":
            return cmd_skip(
                check, root=root, gate=gate, out=out, reason=args.reason, risk=args.risk
            )
        return cmd_run(
            check,
            root=root,
            gate=gate,
            out=out,
            base=args.base,
            engine_choice=args.engine,
            use_cache=not args.no_cache,
            override=override_request(args.override, args.override_reason, args.override_by),
            engines=engines or default_engines(),
            risk=args.risk,
            not_needed=not_needed,
        )
    except (ConfigError, DiffError, evals.EvalError) as error:
        log.error("%s", error)
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())

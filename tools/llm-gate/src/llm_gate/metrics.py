"""Gate health metrics over the audit log (docs/metrics.md, docs/PLAN-v2.md Phase 16).

Inputs: the `audit-log` branch checked out (`just audit-pull`), the merged PRs from the GitHub API
(`gh api --paginate .../pulls?state=closed`), and optionally the latest eval reports. Plain Python:
the log is small JSONL, and DuckDB had no wheel for Python 3.15, which llm-gate targeted when this
was written (it would have compiled from source in every CI job).
"""

import json
import math
from collections import Counter, defaultdict
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from . import audit

# The check reached a decision. `not_needed` is one of them (F083): the triage plan decided the
# check wasn't needed at that risk level, which is an answer, and counting it as a gap made every
# merged low-risk PR look uncovered.
REAL_VERDICTS = frozenset({"pass", "fail", "not_applicable", "not_needed"})
NO_DATA = "_no data yet_"


def load_records(audit_dir: Path) -> list[dict[str, Any]]:
    """Every valid record under events/, as plain dicts.

    `audit.load_events` validates each line against the schema: "the schema checked them on the
    way in" was true of the collector's write path and not of this one, since the branch takes a
    push from anyone with write access. `load_counted` is the same thing with the reject count,
    which the report shows.
    """
    return load_counted(audit_dir).records


def load_counted(audit_dir: Path) -> audit.LoadedEvents:
    return audit.load_events(audit_dir)


def _when(value: object) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value)) if value else None
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed and parsed.tzinfo is None else parsed


def percentile(values: Sequence[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(q * len(ordered)) - 1)]


def _ratio(numerator: float, denominator: float) -> float | None:
    return numerator / denominator if denominator else None


@dataclass
class Report:
    since: datetime
    merged_prs: int
    reviewed_prs: int
    turnaround: dict[str, tuple[float | None, float | None, int]] = field(default_factory=dict)
    coverage: float | None = None
    uncovered: list[int] = field(default_factory=list)
    fp_by_check: dict[str, tuple[int, int, int]] = field(default_factory=dict)  # fp, ack, findings
    fp_by_severity: dict[str, tuple[int, int]] = field(default_factory=dict)  # fp, findings
    override_rate: tuple[int, int] = (0, 0)  # PRs overridden, PRs with blocking findings
    unreviewed_overrides: int = 0  # PRs where an override accepted a diff too large to review
    cost_total: float = 0.0
    cost_by_check: dict[str, float] = field(default_factory=dict)
    cost_by_engine: dict[str, float] = field(default_factory=dict)
    cost_per_pr: tuple[float | None, float | None] = (None, None)  # p50, p90
    runs: int = 0
    triage: dict[str, int] = field(default_factory=dict)
    risk_overrides: int = 0
    ai_assisted: tuple[int, int] = (0, 0)  # flagged PRs, triaged PRs
    # Triaged PRs split by the AI flag: PRs, distinct findings, findings marked false positive.
    ai_comparison: dict[str, tuple[int, int, int]] = field(default_factory=dict)
    tamper: int = 0
    unverified: int = 0
    rejected_feedback: int = 0
    # Lines under events/ that are not valid records. The branch takes a push from anyone with
    # write access, so this is not always zero by construction.
    rejected_records: int = 0
    evals: list[dict[str, Any]] = field(default_factory=list)


def compute(
    records: Iterable[Mapping[str, Any]],
    prs: Sequence[Mapping[str, Any]],
    *,
    blocking_checks: Collection[str],
    now: datetime,
    since_days: int = 30,
    eval_runs: Sequence[Mapping[str, Any]] = (),
    rejected_records: int = 0,
) -> Report:
    records = list(records)
    stamps = [ts for r in records if (ts := _when(r.get("ts"))) is not None]
    # PRs merged before the audit log existed can't be covered: count from its first record.
    since = max([now - timedelta(days=since_days), *([min(stamps)] if stamps else [])])
    recent = [r for r in records if (ts := _when(r.get("ts"))) is not None and ts >= since]
    runs = [r for r in recent if r.get("type") == "gate_run"]
    merged = [
        int(p["number"])
        for p in prs
        if (merged_at := _when(p.get("merged_at"))) is not None and merged_at >= since
    ]
    report = Report(
        since=since,
        merged_prs=len(merged),
        reviewed_prs=len({r.get("pr") for r in runs if r.get("pr") is not None}),
        runs=len(runs),
    )

    # Turnaround: from the PR event to the end of the review, per check.
    durations: dict[str, list[float]] = defaultdict(list)
    for run in runs:
        start, end = _when(run.get("pr_event_at")), _when(run.get("finished_at"))
        # Attempt 1 only: a re-run keeps the original event's payload, so `pr_event_at` is when the
        # PR was pushed, not when the re-run started, and the measurement would include however
        # long someone took to press the button (F053).
        if run.get("run_attempt") not in (None, 1):
            continue
        if start and end and run.get("verdict") in {"pass", "fail", "error"}:
            durations[str(run["check"])].append((end - start).total_seconds())
    report.turnaround = {
        check: (percentile(values, 0.5), percentile(values, 0.9), len(values))
        for check, values in sorted(durations.items())
    }

    # Coverage: merged PRs where every blocking check reached a real decision.
    decided: dict[int, set[str]] = defaultdict(set)
    for run in runs:
        if run.get("verdict") in REAL_VERDICTS and isinstance(run.get("pr"), int):
            decided[run["pr"]].add(str(run["check"]))
    covered = [pr for pr in merged if set(blocking_checks) <= decided.get(pr, set())]
    report.coverage = _ratio(len(covered), len(merged))
    report.uncovered = sorted(set(merged) - set(covered))

    # False positives: distinct findings per PR, against fp/ack feedback on them.
    findings: dict[tuple[Any, Any], tuple[str, str]] = {}  # (pr, id) -> (check, severity)
    for run in runs:
        for f in run.get("findings", []):
            findings[(run.get("pr"), f.get("id"))] = (str(run["check"]), str(f.get("severity")))
    # A person can change their mind (/llm-fp, then /llm-ack): the latest verdict on a finding wins,
    # by time, not by the order the record files happen to sort in. (`recent` holds dated records
    # only, so the fallback is just for the type checker.)
    kinds: dict[tuple[Any, Any], str] = {}
    feedback = [r for r in recent if r.get("type") == "feedback"]
    for r in sorted(feedback, key=lambda r: _when(r.get("ts")) or datetime.min.replace(tzinfo=UTC)):
        kinds[(r.get("pr"), r.get("finding_id"))] = str(r.get("kind"))
    by_check: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    by_severity: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for key, (check, severity) in findings.items():
        by_check[check][2] += 1
        by_severity[severity][1] += 1
        kind = kinds.get(key)
        if kind == "fp":
            by_check[check][0] += 1
            by_severity[severity][0] += 1
        elif kind == "ack":
            by_check[check][1] += 1
    report.fp_by_check = {c: (v[0], v[1], v[2]) for c, v in sorted(by_check.items())}
    report.fp_by_severity = {s: (v[0], v[1]) for s, v in sorted(by_severity.items())}

    # Overrides: PRs where a blocking check failed, and how many of them were overridden.
    blocked = {r.get("pr") for r in runs if r.get("blocking") and r.get("verdict") == "fail"}
    overridden = {r.get("pr") for r in runs if r.get("override_honoured")}
    report.override_rate = (len(overridden & blocked), len(blocked))
    # Kept apart on purpose: accepting findings a reviewer reported is not the same as accepting a
    # diff nobody reviewed (ADR 0002).
    report.unreviewed_overrides = len(
        {
            r.get("pr")
            for r in runs
            if r.get("override_honoured") and r.get("blocking") and r.get("verdict") == "error"
        }
    )

    # Cost: only reviews that were paid for (cache hits record no cost).
    per_pr: dict[Any, float] = defaultdict(float)
    for run in runs:
        cost = run.get("cost_usd")
        if isinstance(cost, int | float):
            report.cost_total += cost
            report.cost_by_check[str(run["check"])] = (
                report.cost_by_check.get(str(run["check"]), 0) + cost
            )
            engine = f"{run.get('engine')} / {run.get('model')}"
            report.cost_by_engine[engine] = report.cost_by_engine.get(engine, 0) + cost
            per_pr[run.get("pr")] += cost
    report.cost_per_pr = (
        percentile(list(per_pr.values()), 0.5),
        percentile(list(per_pr.values()), 0.9),
    )

    # Triage and AI-assisted share (ADR 0008): each PR once, as its latest triage left it.
    latest: dict[Any, Mapping[str, Any]] = {}
    for record in sorted(
        (r for r in recent if r.get("type") == "triage"), key=lambda r: str(r.get("ts"))
    ):
        latest[record.get("pr")] = record
    triage = list(latest.values())
    report.triage = dict(Counter(str(r.get("final_risk")) for r in triage))
    report.ai_assisted = (sum(1 for r in triage if r.get("ai_assisted")), len(triage))
    # The plan's "their finding and false-positive rates next to the rest" (docs/metrics.md).
    ai_by_pr = {r.get("pr"): bool(r.get("ai_assisted")) for r in triage}
    split = {True: [0, 0, 0], False: [0, 0, 0]}
    for flag in ai_by_pr.values():
        split[flag][0] += 1
    for pr_number, finding in findings:
        if pr_number in ai_by_pr:
            group = split[ai_by_pr[pr_number]]
            group[1] += 1
            group[2] += kinds.get((pr_number, finding)) == "fp"
    if triage:
        report.ai_comparison = {
            label: (v[0], v[1], v[2])
            for label, v in (("AI-assisted", split[True]), ("not AI-assisted", split[False]))
        }
    report.risk_overrides = sum(1 for r in recent if r.get("type") == "risk_override")

    report.tamper = sum(1 for r in recent if r.get("type") == "tamper_suspected")
    report.unverified = sum(1 for r in runs if r.get("workflow_modified"))
    report.rejected_feedback = sum(1 for r in recent if r.get("type") == "feedback_rejected")
    report.rejected_records = rejected_records
    report.evals = [dict(e) for e in eval_runs]
    return report


def load_eval_runs(directory: Path | None) -> list[dict[str, Any]]:
    """The eval runs of the last `llm-gate eval run` (reports/eval/last.json)."""
    if directory is None or not (directory / "last.json").is_file():
        return []
    runs: list[dict[str, Any]] = []
    for name in json.loads((directory / "last.json").read_text(encoding="utf-8")):
        path = directory / Path(str(name)).name  # names only; never a path from the file
        if path.is_file():
            runs += json.loads(path.read_text(encoding="utf-8"))
    return runs


# --- Markdown ------------------------------------------------------------------------------------


def _pct(value: float | None) -> str:
    return "-" if value is None else f"{value:.0%}"


def _secs(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.0f} s" if value < 120 else f"{value / 60:.1f} min"


def _usd(value: float | None) -> str:
    return "-" if value is None else f"${value:.2f}"


def render(report: Report, *, generated: datetime) -> str:
    lines = [
        "## Gate health",
        "",
        f"Since {report.since:%Y-%m-%d} (generated {generated:%Y-%m-%d %H:%M} UTC): "
        f"{report.merged_prs} merged PRs, {report.reviewed_prs} PRs reviewed, {report.runs} "
        "check runs. Definitions: `docs/metrics.md`.",
        "",
        "### Coverage",
        "",
        f"Merged PRs where every blocking check reached a decision: **{_pct(report.coverage)}**"
        + (
            f" (not covered: {', '.join(f'#{n}' for n in report.uncovered[:20])})"
            if report.uncovered
            else ""
        ),
        "",
        "### Review turnaround (PR event → review finished)",
        "",
    ]
    if report.turnaround:
        lines += ["| Check | p50 | p90 | Runs |", "|---|---|---|---|"]
        lines += [
            f"| {check} | {_secs(p50)} | {_secs(p90)} | {n} |"
            for check, (p50, p90, n) in report.turnaround.items()
        ]
    else:
        lines.append(NO_DATA)
    lines += ["", "### False positives", ""]
    if report.fp_by_check:
        lines += [
            "| Check | Findings | Marked fp | Marked ack | fp / findings | fp / (fp + ack) |",
            "|---|---|---|---|---|---|",
        ]
        for check, (fp, ack, total) in report.fp_by_check.items():
            lines.append(
                f"| {check} | {total} | {fp} | {ack} | {_pct(_ratio(fp, total))} "
                f"| {_pct(_ratio(fp, fp + ack))} |"
            )
        lines += ["", "| Severity | Findings | Marked fp | fp rate |", "|---|---|---|---|"]
        lines += [
            f"| {severity} | {total} | {fp} | {_pct(_ratio(fp, total))} |"
            for severity, (fp, total) in report.fp_by_severity.items()
        ]
    else:
        lines.append(NO_DATA)
    overridden, blocked = report.override_rate
    lines += [
        "",
        "### Overrides",
        "",
        f"PRs with blocking findings: {blocked}; overridden: {overridden} "
        f"(**{_pct(_ratio(overridden, blocked))}**).",
        f"PRs accepted unreviewed (a diff over the size cap): **{report.unreviewed_overrides}**.",
        "",
        "### Cost",
        "",
        f"Total **{_usd(report.cost_total)}**; per reviewed PR p50 {_usd(report.cost_per_pr[0])}, "
        f"p90 {_usd(report.cost_per_pr[1])}.",
        "",
    ]
    if report.cost_by_check:
        lines += ["| Check | Cost |", "|---|---|"]
        lines += [f"| {c} | {_usd(v)} |" for c, v in sorted(report.cost_by_check.items())]
        lines += ["", "| Engine / model | Cost |", "|---|---|"]
        lines += [f"| {e} | {_usd(v)} |" for e, v in sorted(report.cost_by_engine.items())]
    lines += ["", "### Triage and AI-assisted PRs", ""]
    if report.triage:
        total = sum(report.triage.values())
        lines.append(
            "Risk: "
            + ", ".join(f"{k} {_pct(v / total)}" for k, v in sorted(report.triage.items()))
            + f"; manual risk changes: {report.risk_overrides}; AI-assisted: "
            + f"{_pct(_ratio(*report.ai_assisted))}."
        )
        lines += ["", "| Triaged PRs | PRs | Findings per PR | Marked fp |", "|---|---|---|---|"]
        for label, (prs_n, found, fp) in report.ai_comparison.items():
            per_pr = f"{found / prs_n:.1f}" if prs_n else "-"
            lines.append(f"| {label} | {prs_n} | {per_pr} | {_pct(_ratio(fp, found))} |")
    else:
        lines.append(f"{NO_DATA}. Manual risk changes: {report.risk_overrides}.")
    lines += ["", "### Eval trend (latest run)", ""]
    if report.evals:
        lines += [
            "| Check | Engine / model | Prompt | Recall | False blocks | Verdicts | Flips |",
            "|---|---|---|---|---|---|---|",
        ]
        for run in report.evals:
            m = run.get("metrics", {})
            lines.append(
                f"| {run.get('check')} | {run.get('engine')} / {run.get('model')} "
                f"| `{str(run.get('prompt_sha256', ''))[:8]}` | {_pct(m.get('recall'))} "
                f"| {_pct(m.get('false_block_rate'))} | {_pct(m.get('verdict_accuracy'))} "
                f"| {_pct(m.get('flip_rate'))} |"
            )
    else:
        lines.append(NO_DATA)
    lines += [
        "",
        "### Integrity",
        "",
        f"Tamper-suspected artifacts: {report.tamper}; reviews from PRs that changed the review "
        f"workflow (unverified): {report.unverified}; rejected `/llm-*` commands: "
        f"{report.rejected_feedback}; lines on the branch that are not valid records: "
        f"{report.rejected_records}.",
    ]
    return "\n".join(lines) + "\n"

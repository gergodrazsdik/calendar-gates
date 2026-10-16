"""Render run records as Markdown (job summary, sticky PR comment) and SARIF (code scanning)."""

from collections.abc import Iterable
from typing import Any

from .models import Finding, Severity, finding_id
from .policy import Verdict
from .runner import RunRecord

ICONS = {
    Verdict.PASS: "✅",
    Verdict.FAIL: "❌",
    Verdict.OVERRIDDEN: "⚠️",
    Verdict.NOT_APPLICABLE: "➖",  # noqa: RUF001  # an icon, not a minus sign
    Verdict.ERROR: "💥",
}
SEVERITY_ICONS = {
    Severity.CRITICAL: "🟥",
    Severity.HIGH: "🔴",
    Severity.MEDIUM: "🟠",
    Severity.LOW: "🟡",
    Severity.INFO: "🔵",
}
SARIF_LEVELS = {
    Severity.CRITICAL: "error",
    Severity.HIGH: "error",
    Severity.MEDIUM: "warning",
    Severity.LOW: "note",
    Severity.INFO: "note",
}


def marker(check: str) -> str:
    """Hidden HTML comment that identifies a check's sticky PR comment."""
    return f"<!-- llm-gate:{check} -->"


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _location(finding: Finding) -> str:
    return f"{finding.file}:{finding.line}" if finding.line else finding.file


def _stats(record: RunRecord) -> str:
    mode = (
        f"**blocking** (fails on {record.fail_on} and above)"
        if record.mode == "blocking"
        else "advisory (never fails)"
    )
    parts = [mode, f"engine `{record.engine}`", f"model `{record.model}`"]
    if record.result:
        usage = record.result.usage
        parts.append(f"{record.result.duration_ms / 1000:.1f} s")
        if usage.num_turns and usage.num_turns > 1:
            parts.append(f"{usage.num_turns} turns")
        if usage.cost_usd is not None:
            parts.append(f"{'~' if usage.cost_estimated else ''}${usage.cost_usd:.4f}")
    if record.cached:
        parts.append("cached")
    return " · ".join(parts)


def render_markdown(record: RunRecord) -> str:
    verdict = Verdict(record.verdict)
    lines = [
        marker(record.check),
        f"### {ICONS[verdict]} llm / {record.check}: {verdict}",
        "",
        _stats(record),
        "",
        f"_{record.reason}_",
    ]
    if record.result is None:
        return "\n".join(lines) + "\n"

    review = record.result.review
    lines += ["", f"> {_cell(review.summary)}"]
    if not review.findings:
        lines += ["", "No findings."]
        return "\n".join(lines) + "\n"

    blocking = {(f.file, f.line, f.title) for f in record.blocking}
    findings = sorted(review.findings, key=lambda f: -f.severity.rank)
    # The ids are stable across runs, so people can refer to a finding (feedback, overrides).
    lines += ["", "| Severity | ID | Location | Finding |", "|---|---|---|---|"]
    for f in findings:
        flag = " **(blocking)**" if (f.file, f.line, f.title) in blocking else ""
        lines.append(
            f"| {SEVERITY_ICONS[f.severity]} {f.severity}{flag} | `{finding_id(record.check, f)}` "
            f"| `{_cell(_location(f))}` | {_cell(f.title)} |"
        )
    lines += ["", "<details><summary>Details</summary>", ""]
    for number, f in enumerate(findings, start=1):
        meta = f"`{finding_id(record.check, f)}` · `{_location(f)}` · {f.severity} · {f.category}"
        lines += [f"#### {number}. {f.title}", "", meta]
        lines += ["", f.detail]
        if f.suggestion:
            lines += ["", f"**Suggestion:** {f.suggestion}"]
        lines.append("")
    lines.append("</details>")
    return "\n".join(lines) + "\n"


def render_sarif(records: Iterable[RunRecord]) -> dict[str, Any]:
    """One SARIF run for all records; rule ids are `<check>/<category>`."""
    rules: dict[str, dict[str, Any]] = {}
    results: list[dict[str, Any]] = []
    for record in records:
        if record.result is None:
            continue
        for f in record.result.review.findings:
            rule_id = f"{record.check}/{f.category}"
            rules.setdefault(
                rule_id,
                {
                    "id": rule_id,
                    "shortDescription": {"text": f"{record.check}: {f.category}"},
                },
            )
            region: dict[str, Any] = {"startLine": f.line} if f.line and f.line > 0 else {}
            location: dict[str, Any] = {"artifactLocation": {"uri": f.file}}
            if region:
                location["region"] = region
            message = f"{f.title}\n\n{f.detail}"
            if f.suggestion:
                message += f"\n\nSuggestion: {f.suggestion}"
            results.append(
                {
                    "ruleId": rule_id,
                    "level": SARIF_LEVELS[f.severity],
                    "message": {"text": message},
                    "locations": [{"physicalLocation": location}],
                    "properties": {"severity": str(f.severity), "engine": record.engine},
                }
            )
    return {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "llm-gate",
                        "informationUri": "https://github.com/gergodrazsdik/calendar-gates",
                        "rules": list(rules.values()),
                    }
                },
                "results": results,
            }
        ],
    }

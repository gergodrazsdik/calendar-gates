"""Render run records as Markdown (job summary, sticky PR comment) and SARIF (code scanning).

Everything the model wrote is published here, so it goes through `redact.safe_text` on the way:
these sinks are a public PR comment and a public job summary, and a review can be steered by the
text in the files it reviews (F003, F029). Ids, paths and categories are *not* redacted — the id is
a hash of the raw finding and the path and category are structure, not prose — they are restricted
to a plain charset instead, so they can't carry markup either.
"""

import re
from collections.abc import Iterable
from typing import Any

from .models import Finding, Severity, finding_id
from .policy import Verdict
from .redact import clip, safe_text
from .runner import RunRecord

ICONS = {
    Verdict.PASS: "✅",
    Verdict.FAIL: "❌",
    Verdict.OVERRIDDEN: "⚠️",
    Verdict.NOT_APPLICABLE: "➖",  # noqa: RUF001  # an icon, not a minus sign
    Verdict.NOT_NEEDED: "➖",  # noqa: RUF001  # an icon, not a minus sign
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


def prose(text: str, limit: int = 2000) -> str:
    """A paragraph of model-written text for a public sink: safe, and with a line that starts like
    a table row defused. The comment's rows carry the finding ids that `/llm-fp` resolves, and a
    detail used to be able to add a line that looked like another finding's row."""
    return re.sub(r"(?m)^(\s*)\|", r"\1\\|", safe_text(text, limit))


def cell(text: str) -> str:
    """One table cell of model-written text: safe, and without the two characters that would end
    the cell or the row."""
    return safe_text(text, 300).replace("|", "\\|").replace("\n", " ")


# A path and a kebab-case category, and nothing that reads as markup. Redaction is wrong for these:
# the generic `key=value` secret pattern would eat a path like `config/token-store.cs`, and the
# category is a SARIF rule id that has to stay stable.
_PLAIN_PATH = re.compile(r"[^A-Za-z0-9 ._/+#@-]")
_PLAIN_SLUG = re.compile(r"[^a-z0-9-]")


def plain_path(text: str) -> str:
    return clip(_PLAIN_PATH.sub("_", text), 200) or "?"


def plain_slug(text: str) -> str:
    return clip(_PLAIN_SLUG.sub("-", text.lower()), 40) or "other"


def _location(finding: Finding) -> str:
    where = plain_path(finding.file)
    return f"{where}:{finding.line}" if finding.line else where


def _stats(record: RunRecord) -> str:
    mode = (
        f"**blocking** (fails on {record.fail_on} and above)"
        if record.mode == "blocking"
        else "advisory (never fails)"
    )
    parts = [mode, f"engine `{record.engine}`", f"model `{record.model}`"]
    if record.risk:
        parts.insert(0, f"risk **{record.risk}**")
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
        # The reason can carry an engine error or a model-chosen file name.
        f"_{cell(record.reason)}_",
    ]
    if record.omitted:
        # Say what the review never saw, every time, so a trimmed diff is never a silent one.
        lines += [
            "",
            f"**Not reviewed** ({len(record.omitted)} file(s) over the check's size cap "
            "for a single file):",
            "",
            *(f"- `{plain_path(o.path)}` ({o.bytes // 1024} KB)" for o in record.omitted),
        ]
    if record.result and record.result.denied_reads:
        # The reviewer tried to read outside the checkout; a blinded review is never a silent one.
        lines += [
            "",
            f"**{record.result.denied_reads} read(s) outside the repository were refused** "
            "(the reviewer may only read the code under review).",
        ]
    if record.result is None:
        return "\n".join(lines) + "\n"

    review = record.result.review
    lines += ["", f"> {cell(review.summary)}"]
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
            f"| `{_location(f)}` | {cell(f.title)} |"
        )
    lines += ["", "<details><summary>Details</summary>", ""]
    for number, f in enumerate(findings, start=1):
        where = f"`{finding_id(record.check, f)}` · `{_location(f)}`"
        meta = f"{where} · {f.severity} · `{plain_slug(f.category)}`"
        # The id comes from the raw finding, so `/llm-fp <id>` still resolves against the audit log.
        lines += [f"#### {number}. {cell(f.title)}", "", meta]
        lines += ["", prose(f.detail)]
        if f.suggestion:
            lines += ["", f"**Suggestion:** {prose(f.suggestion)}"]
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
            rule_id = f"{record.check}/{plain_slug(f.category)}"
            rules.setdefault(
                rule_id,
                {
                    "id": rule_id,
                    "shortDescription": {"text": f"{record.check}: {f.category}"},
                },
            )
            region: dict[str, Any] = {"startLine": f.line} if f.line and f.line > 0 else {}
            location: dict[str, Any] = {"artifactLocation": {"uri": plain_path(f.file)}}
            if region:
                location["region"] = region
            message = f"{safe_text(f.title, 300)}\n\n{safe_text(f.detail)}"
            if f.suggestion:
                message += f"\n\nSuggestion: {safe_text(f.suggestion)}"
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

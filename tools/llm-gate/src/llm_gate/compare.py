"""Engine-vs-engine report for one check: findings, overlap, verdict agreement, time and cost."""

from .models import Finding, Severity
from .report import cell, plain_path
from .runner import RunRecord

LINE_TOLERANCE = 3


def same_issue(a: Finding, b: Finding) -> bool:
    """Same file and (when both have one) a line within LINE_TOLERANCE."""
    if a.file != b.file:
        return False
    if a.line is None or b.line is None:
        return a.category == b.category
    return abs(a.line - b.line) <= LINE_TOLERANCE


def overlap(left: list[Finding], right: list[Finding]) -> list[tuple[Finding, Finding]]:
    """Greedy one-to-one matching of findings that look like the same issue."""
    pairs: list[tuple[Finding, Finding]] = []
    unmatched = list(right)
    for finding in left:
        match = next((other for other in unmatched if same_issue(finding, other)), None)
        if match is not None:
            pairs.append((finding, match))
            unmatched.remove(match)
    return pairs


def _findings(record: RunRecord) -> list[Finding]:
    return record.result.review.findings if record.result else []


def render_comparison(a: RunRecord, b: RunRecord) -> str:
    fa, fb = _findings(a), _findings(b)
    pairs = overlap(fa, fb)

    def row(label: str, left: object, right: object) -> str:
        return f"| {label} | {left} | {right} |"

    def stat(record: RunRecord, field: str) -> str:
        if record.result is None:
            return "n/a"
        value = getattr(record.result.usage, field)
        return "n/a" if value is None else str(value)

    def cost(record: RunRecord) -> str:
        if record.result is None or record.result.usage.cost_usd is None:
            return "n/a"
        usage = record.result.usage
        return f"{'~' if usage.cost_estimated else ''}${usage.cost_usd:.4f}"

    lines = [
        f"<!-- llm-gate:compare:{a.check} -->",
        f"### llm-gate engine comparison: {a.check}",
        "",
        f"| | {a.engine} | {b.engine} |",
        "|---|---|---|",
        row("model", f"`{a.model}`", f"`{b.model}`"),
        row("verdict", a.verdict, b.verdict),
    ]
    for severity in sorted(Severity, key=lambda s: -s.rank):
        left = sum(1 for f in fa if f.severity == severity)
        right = sum(1 for f in fb if f.severity == severity)
        lines.append(row(f"{severity} findings", left, right))
    lines += [
        row("total findings", len(fa), len(fb)),
        row(
            "duration",
            f"{a.result.duration_ms / 1000:.1f} s" if a.result else "n/a",
            f"{b.result.duration_ms / 1000:.1f} s" if b.result else "n/a",
        ),
        row(
            "input / output tokens",
            f"{stat(a, 'input_tokens')} / {stat(a, 'output_tokens')}",
            f"{stat(b, 'input_tokens')} / {stat(b, 'output_tokens')}",
        ),
        row("turns", stat(a, "num_turns"), stat(b, "num_turns")),
        row("cost", cost(a), cost(b)),
        "",
        f"**Verdicts {'agree' if a.verdict == b.verdict else 'differ'}.** "
        f"{len(pairs)} finding(s) found by both (same file, line ±{LINE_TOLERANCE}).",
    ]
    matched_a = {id(x) for x, _ in pairs}
    matched_b = {id(y) for _, y in pairs}
    for record, findings, matched in ((a, fa, matched_a), (b, fb, matched_b)):
        only = [f for f in findings if id(f) not in matched]
        if only:
            lines += ["", f"Only `{record.engine}`:"]
            lines += [
                f"- {f.severity}: `{plain_path(f.file)}:{f.line or '-'}` {cell(f.title)}"
                for f in only
            ]
    return "\n".join(lines) + "\n"

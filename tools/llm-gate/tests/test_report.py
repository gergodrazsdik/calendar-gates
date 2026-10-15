import json
from pathlib import Path

from conftest import finding, result
from jsonschema import Draft4Validator

from llm_gate.compare import overlap, render_comparison
from llm_gate.models import Severity
from llm_gate.report import marker, render_markdown, render_sarif
from llm_gate.runner import RunRecord

SARIF_SCHEMA = json.loads(
    (Path(__file__).parent / "fixtures" / "sarif-schema-2.1.0.json").read_text(encoding="utf-8")
)


def record(*findings: object, verdict: str = "fail", engine: str = "api") -> RunRecord:
    run = result(*findings, engine=engine)  # type: ignore[arg-type]
    return RunRecord(
        check="code-review",
        mode="blocking",
        fail_on=Severity.HIGH,
        engine=engine,
        model=run.model,
        verdict=verdict,
        exit_code=1 if verdict == "fail" else 0,
        reason="1 finding(s) at or above high",
        result=run,
        blocking=[f for f in run.review.findings if f.severity.at_least(Severity.HIGH)],
    )


def test_markdown_has_marker_verdict_and_sorted_findings() -> None:
    md = render_markdown(record(finding(Severity.LOW, line=3), finding(Severity.HIGH, line=7)))

    assert md.startswith(marker("code-review") + "\n")
    assert "### ❌ llm / code-review: fail" in md
    assert "**blocking** (fails on high and above)" in md
    assert "~$0.0010" in md  # estimated cost is marked
    table = [line for line in md.splitlines() if line.startswith("| ")]
    assert "high **(blocking)**" in table[1]
    assert "`src/a.cs:7`" in table[1]
    assert "low" in table[2] and "(blocking)" not in table[2]


def test_markdown_escapes_table_cells() -> None:
    f = finding(Severity.LOW).model_copy(update={"title": "a | b\nc"})

    md = render_markdown(record(f, verdict="pass"))

    assert "a \\| b c" in md


def test_markdown_without_a_result_shows_the_reason() -> None:
    r = RunRecord(
        check="docs-drift",
        mode="advisory",
        fail_on=None,
        engine="api",
        model="m",
        verdict="not-applicable",
        exit_code=0,
        reason="the change touches none of docs/**",
    )

    md = render_markdown(r)

    assert "➖ llm / docs-drift: not-applicable" in md  # noqa: RUF001  # the icon
    assert "advisory (never fails)" in md
    assert "touches none of docs/**" in md


def test_sarif_is_valid_and_maps_severities() -> None:
    findings = [finding(s, line=None if s is Severity.INFO else 5) for s in Severity]

    sarif = render_sarif([record(*findings)])

    Draft4Validator(SARIF_SCHEMA).validate(sarif)
    levels = {r["properties"]["severity"]: r["level"] for r in sarif["runs"][0]["results"]}
    assert levels == {
        "info": "note",
        "low": "note",
        "medium": "warning",
        "high": "error",
        "critical": "error",
    }
    info = next(r for r in sarif["runs"][0]["results"] if r["properties"]["severity"] == "info")
    assert "region" not in info["locations"][0]["physicalLocation"]
    assert [rule["id"] for rule in sarif["runs"][0]["tool"]["driver"]["rules"]] == [
        "code-review/off-by-one"
    ]


def test_sarif_with_no_results_is_valid() -> None:
    Draft4Validator(SARIF_SCHEMA).validate(render_sarif([]))


def test_overlap_matches_nearby_lines_once() -> None:
    left = [finding(Severity.HIGH, line=10), finding(Severity.LOW, line=50)]
    right = [finding(Severity.MEDIUM, line=12), finding(Severity.HIGH, line=11)]

    pairs = overlap(left, right)

    assert [(a.line, b.line) for a, b in pairs] == [(10, 12)]


def test_comparison_table() -> None:
    a = record(finding(Severity.HIGH, line=10), finding(Severity.LOW, file="b.cs"))
    b = record(finding(Severity.HIGH, line=12), verdict="fail", engine="agent")

    md = render_comparison(a, b)

    assert "| high findings | 1 | 1 |" in md
    assert "| low findings | 1 | 0 |" in md
    assert "**Verdicts agree.** 1 finding(s) found by both" in md
    assert "Only `api`:" in md and "Only `agent`:" not in md

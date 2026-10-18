import json
from pathlib import Path

from conftest import finding, result
from jsonschema import Draft4Validator

from llm_gate import feedback
from llm_gate.compare import overlap, render_comparison
from llm_gate.models import Severity, finding_id
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


# --- published text is untrusted (F003, F029) ----------------------------------------------------
# These sinks are a public PR comment and a public job summary, and a review can be steered by the
# files it reviews. Everything the model wrote is scrubbed and defanged on the way out.

SECRET = "sk-ant-api03-" + "x" * 30
MARKUP = "see [here](http://evil.example/?d=1) and ![x](http://evil.example/p.png) <img src=x>"


def test_markdown_redacts_secrets_in_every_field_the_model_wrote() -> None:
    f = finding(Severity.HIGH, line=7).model_copy(
        update={"title": f"token {SECRET}", "detail": f"body {SECRET}", "suggestion": SECRET}
    )
    rec = record(f)
    rec.result.review.summary = f"summary {SECRET}"  # type: ignore[union-attr]

    md = render_markdown(rec)

    assert SECRET not in md
    # summary, detail, suggestion, and the title twice (the table row and the details heading).
    assert md.count("[REDACTED]") == 5


def test_markdown_defangs_links_images_and_tags() -> None:
    f = finding(Severity.HIGH, line=7).model_copy(update={"detail": MARKUP, "title": MARKUP})

    md = render_markdown(record(f))

    assert "](http://evil.example" not in md  # no live link or image anywhere
    assert "<img" not in md
    assert "http[:]//evil.example" in md  # the words survive, the fetch doesn't


def test_markdown_ids_come_from_the_raw_finding() -> None:
    """`/llm-fp <id>` resolves the id against the audit log, which is built from the raw review, so
    redaction must not change what the comment calls a finding."""
    f = finding(Severity.HIGH, line=7).model_copy(update={"title": f"token {SECRET}"})

    md = render_markdown(record(f))

    assert finding_id("code-review", f) in md


def test_markdown_keeps_the_marker_first_and_the_rows_intact() -> None:
    """The sticky comment is found by its marker and marked up by row (upsert-pr-comment.sh,
    feedback.mark_false_positive), so redaction must not move either."""
    f = finding(Severity.HIGH, line=7).model_copy(update={"title": "a | b", "detail": MARKUP})

    md = render_markdown(record(f))

    assert md.startswith(marker("code-review"))
    rows = [line for line in md.splitlines() if line.startswith("| 🔴")]
    assert len(rows) == 1
    assert rows[0].endswith("|")
    assert "a \\| b" in rows[0]  # the pipe in the title can't end the cell


def test_a_finding_detail_cannot_forge_a_table_row_for_another_finding() -> None:
    """The detail text used to land in the comment verbatim, so it could add a row that looks like
    another finding's and divert the false-positive marking to it."""
    real = finding(Severity.HIGH, line=7)
    forged = f"| 🟡 low | `{finding_id('code-review', real)}` | `src/X.cs:1` | Nothing wrong |"
    rec = record(real.model_copy(update={"detail": forged}))

    md = render_markdown(rec)
    marked = feedback.mark_false_positive(md, finding_id("code-review", real), "alice")

    assert marked is not None
    assert marked.count("_(false positive: @alice)_") == 1
    # The forged line is not a row any more: nothing but the real finding's row starts with a pipe
    # and carries an id, which is all `mark_false_positive` looks at.
    rows = [line for line in marked.splitlines() if line.startswith("|")]
    assert not any("Nothing wrong" in line for line in rows)


def test_markdown_reports_refused_reads() -> None:
    rec = record(finding(Severity.LOW, line=3))
    rec.result.denied_reads = 2  # type: ignore[union-attr]

    md = render_markdown(rec)

    assert "2 read(s) outside the repository were refused" in md


def test_markdown_sanitises_the_path_and_the_category_without_redacting_them() -> None:
    """A path is structure, not prose: redaction's generic `key=value` rule would eat
    `config/token-store.cs`, and the category is a SARIF rule id that has to stay stable."""
    f = finding(Severity.HIGH, line=7).model_copy(
        update={"file": "src/config/token-store.cs", "category": "Secrets Handling!"}
    )

    md = render_markdown(record(f))
    sarif = render_sarif([record(f)])

    assert "`src/config/token-store.cs:7`" in md
    assert "`secrets-handling-`" in md
    assert sarif["runs"][0]["results"][0]["ruleId"] == "code-review/secrets-handling-"
    location = sarif["runs"][0]["results"][0]["locations"][0]["physicalLocation"]
    assert location["artifactLocation"]["uri"] == "src/config/token-store.cs"


def test_sarif_messages_are_redacted_and_defanged() -> None:
    f = finding(Severity.HIGH, line=7).model_copy(
        update={"detail": f"{MARKUP} {SECRET}", "suggestion": SECRET}
    )

    sarif = render_sarif([record(f)])

    message = sarif["runs"][0]["results"][0]["message"]["text"]
    assert SECRET not in message
    assert "](http://evil.example" not in message
    Draft4Validator(SARIF_SCHEMA).validate(sarif)


def test_comparison_redacts_and_flattens_finding_text() -> None:
    """The comparison is posted as its own sticky comment (llm-compare.yml), and its lines are
    bullets: a newline in a title used to break the list."""
    f = finding(Severity.HIGH, line=7).model_copy(
        update={"title": f"first\nsecond {SECRET}", "file": "src/A.cs"}
    )
    api = record(f, engine="api")
    agent = record(finding(Severity.LOW, line=99), engine="agent")

    md = render_comparison(api, agent)

    assert SECRET not in md
    assert "- high: `src/A.cs:7` first second [REDACTED]" in md

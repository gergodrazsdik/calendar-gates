import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
from conftest import finding

from llm_gate import audit
from llm_gate.cli import main
from llm_gate.models import Severity, finding_id
from llm_gate.redact import MAX_SUMMARY, REDACTED, redact

EXPECTED = audit.Expected(
    repo="owner/repo", workflow_run_id=100, run_attempt=1, head_sha="a" * 40, pr=7
)
T = datetime(2026, 10, 16, 9, 0, tzinfo=UTC)


def gate_run(**overrides: Any) -> audit.GateRun:
    fields: dict[str, Any] = {
        "repo": "owner/repo",
        "pr": 7,
        "head_sha": "a" * 40,
        "base_sha": "b" * 40,
        "workflow_run_id": 100,
        "run_attempt": 1,
        "run_url": EXPECTED.run_url,
        "check": "code-review",
        "engine": "agent",
        "model": "claude-sonnet-5-5",
        "prompt_file": ".claude/commands/llm-code-review.md",
        "prompt_sha256": "0" * 64,
        "config_sha256": "1" * 64,
        "gate_sha": "b" * 40,
        "diff_sha256": "2" * 64,
        "diff_bytes": 10,
        "blocking": True,
        "cache_hit": False,
        "started_at": T,
        "finished_at": T,
        "verdict": "fail",
        "exit_code": 1,
    }
    fields.update(overrides)
    return audit.GateRun(**fields)


def artifact(root: Path, name: str, *lines: str) -> Path:
    directory = root / "artifacts" / name
    directory.mkdir(parents=True)
    (directory / audit.AUDIT_FILE).write_text("".join(f"{line}\n" for line in lines))
    return directory


NO_OVERRIDE = "no llm-override label"


def collect(tmp_path: Path, jobs: dict[str, str | None] | None = None, **kwargs: Any) -> list[Any]:
    out = tmp_path / "out"
    collected = audit.collect(
        tmp_path / "artifacts",
        expected=EXPECTED,
        checks=kwargs.get("checks", {"code-review", "docs-drift"}),
        jobs=jobs if jobs is not None else {"llm / code-review": "failure"},
        workflow_modified=kwargs.get("workflow_modified", False),
        override=kwargs.get("override", NO_OVERRIDE),
        out=out,
        day=date(2026, 10, 16),
    )
    return [
        (c, [json.loads(line) for line in (out / c.path).read_text().splitlines()])
        for c in collected
    ]


# --- schema ---


def test_records_round_trip_with_the_schema_field() -> None:
    record = gate_run()
    line = audit.dumps(record)

    assert json.loads(line)["schema"] == "audit/v1"
    assert audit.parse(line) == record


def test_unknown_fields_and_schemas_are_rejected() -> None:
    data = json.loads(audit.dumps(gate_run()))
    with pytest.raises(ValueError, match="extra"):
        audit.parse(json.dumps({**data, "raw_output": "x"}))
    with pytest.raises(ValueError, match="audit/v1"):
        audit.parse(json.dumps({**data, "schema": "audit/v0"}))
    with pytest.raises(ValueError, match="does not match any of the expected tags"):
        audit.parse(json.dumps({**data, "type": "something"}))


def test_risk_override_uses_from_as_its_field_name() -> None:
    record = audit.RiskOverride.model_validate(
        {"from": "high", "to": "low", "by": "me", "reason": "docs only"}
    )
    assert json.loads(audit.dumps(record))["from"] == "high"


# --- finding ids, redaction ---


def test_finding_ids_are_short_stable_and_ignore_punctuation() -> None:
    a = finding(Severity.HIGH)
    reworded = a.model_copy(update={"title": "High problem!", "detail": "Other words."})
    other_file = a.model_copy(update={"file": "src/b.cs"})

    assert finding_id("code-review", a) == finding_id("code-review", reworded)
    assert finding_id("code-review", a) != finding_id("code-review", other_file)
    assert finding_id("code-review", a).startswith("cr-")
    assert finding_id("security-review", a).startswith("sr-")
    assert len(finding_id("code-review", a)) == len("cr-0000")
    for odd in ("2fa-check", "a-b-c-d-e-f-g-h-i-j", "x"):  # every id fits the log's pattern
        assert audit.AuditFinding(
            id=finding_id(odd, a), severity=a.severity, category="c", file="f", line=1, title="t"
        )


@pytest.mark.parametrize(
    "secret",
    [
        "sk-ant-api03-" + "x" * 40,
        "ghp_" + "A" * 36,
        "github_pat_" + "B" * 30,
        "AKIA" + "C" * 16,
        "-----BEGIN OPENSSH PRIVATE KEY-----",
        'api_key = "hunter2hunter2"',
        '"token": "abcdefghijkl"',
    ],
)
def test_secrets_are_redacted(secret: str) -> None:
    redacted = redact(f"before {secret} after")
    assert REDACTED in redacted
    assert secret not in redacted


def test_tool_input_summaries_are_relative_short_and_redacted(tmp_path: Path) -> None:
    read = audit.summarise_tool_input(
        "Read", {"file_path": f"{tmp_path}/src/A.cs", "offset": 10}, tmp_path
    )
    assert read == "file_path=src/A.cs offset=10"

    grep = audit.summarise_tool_input("Grep", {"pattern": "ghp_" + "A" * 36}, tmp_path)
    assert grep == f"pattern={REDACTED}"

    long = audit.summarise_tool_input("Other", {"q": "x" * 1000}, None)
    assert len(long) == MAX_SUMMARY
    assert long.endswith("…")


# --- overrides ---


LABELLED_AT = "2026-10-16T10:00:00Z"


def labeled(by: str, label: str = "llm-override", at: str = LABELLED_AT) -> dict[str, Any]:
    return {"event": "labeled", "label": {"name": label}, "actor": {"login": by}, "created_at": at}


def comment(
    by: str, body: str, at: str = "2026-10-16T10:01:00Z", edited: str | None = None
) -> dict[str, Any]:
    return {"user": {"login": by}, "body": body, "created_at": at, "updated_at": edited or at}


def test_override_needs_a_reason_from_whoever_added_the_label() -> None:
    events = [labeled("alice"), labeled("bob", "other")]

    found = audit.find_override(events, [comment("alice", "/llm-override hotfix for prod\nmore")])
    assert found == audit.OverrideRequest(by="alice", reason="hotfix for prod")

    no_reason = audit.find_override(events, [comment("alice", "/llm-override   ")])
    assert isinstance(no_reason, str) and "`/llm-override <reason>`" in no_reason

    someone_else = audit.find_override(events, [comment("mallory", "/llm-override trust me")])
    assert isinstance(someone_else, str)


def test_the_latest_labeller_counts() -> None:
    events = [labeled("alice"), labeled("bob")]
    found = audit.find_override(events, [comment("alice", "/llm-override reason")])
    assert isinstance(found, str) and found.startswith("bob")


def test_no_label_event_is_no_override() -> None:
    assert isinstance(audit.find_override([], [comment("a", "/llm-override x")]), str)


# --- validation and collection (trusted side) ---


def test_a_valid_artifact_is_collected_with_the_collector_fields(tmp_path: Path) -> None:
    override = audit.Override(
        repo="owner/repo",
        pr=7,
        head_sha="a" * 40,
        workflow_run_id=100,
        run_attempt=1,
        run_url=EXPECTED.run_url,
        by="me",
        reason="r",
        checks=["code-review"],
    )
    artifact(tmp_path, "audit-100-code-review", audit.dumps(gate_run()), audit.dumps(override))

    trusted = audit.OverrideRequest(by="me", reason="r")
    ((info, lines),) = collect(tmp_path, workflow_modified=True, override=trusted)

    assert info.path == "events/2026/10/16/100-1-code-review.jsonl"
    assert info.tamper is False
    assert info.records == 2
    assert lines[0]["workflow_modified"] is True
    assert lines[0]["check_run_conclusion"] == "failure"
    assert lines[1]["type"] == "override"
    assert lines[1]["reason"] == audit.WITHHELD  # the PR changed the workflow: no free text


def test_free_text_is_kept_when_the_workflow_is_unchanged_and_withheld_otherwise(
    tmp_path: Path,
) -> None:
    f = audit.AuditFinding(
        id="cr-0000", severity=Severity.HIGH, category="off-by-one", file="a.cs", line=1, title="t"
    )
    call = {"tool": "Read", "input": "file_path=a.cs", "ts": T}
    artifact(
        tmp_path, "audit-100-code-review", audit.dumps(gate_run(findings=[f], tool_calls=[call]))
    )

    ((_, kept),) = collect(tmp_path)
    ((_, withheld),) = collect(tmp_path, workflow_modified=True)

    assert kept[0]["findings"][0]["title"] == "t"
    assert kept[0]["tool_calls"][0]["input"] == "file_path=a.cs"
    assert withheld[0]["findings"][0]["title"] == audit.WITHHELD
    assert withheld[0]["findings"][0]["id"] == "cr-0000"  # the structure stays
    assert withheld[0]["findings"][0]["severity"] == "high"
    assert withheld[0]["tool_calls"][0] == {**kept[0]["tool_calls"][0], "input": ""}


def test_a_run_has_a_byte_budget(tmp_path: Path) -> None:
    # The budget is checked before anything is parsed, so raw bytes are enough.
    for n in range(3):
        artifact(tmp_path, f"audit-100-check-{n}", "x" * (audit.MAX_RUN_BYTES // 3 + 1))

    ((info, lines),) = collect(tmp_path)

    assert info.tamper is True
    assert "bytes of artifacts" in lines[0]["problems"][0]


@pytest.mark.parametrize(
    ("record", "problem"),
    [
        (gate_run(workflow_run_id=99), "workflow_run_id does not match"),
        (gate_run(head_sha="c" * 40), "head_sha"),
        (gate_run(pr=8), "pr does not match"),
        (gate_run(repo="evil/repo"), "repo does not match"),
        (gate_run(run_attempt=2), "run_attempt"),
        (gate_run(run_url="https://evil.example/run"), "run_url"),
        (gate_run(prompt_file=".claude/commands/llm-softer.md"), "prompt_file"),
        (gate_run(check="docs-drift"), "check 'docs-drift' in the artifact for 'code-review'"),
        (gate_run(workflow_modified=False), "only the collector"),
        (gate_run(exit_code=0, verdict="pass"), "concluded failure, but the record says pass"),
    ],
)
def test_forged_records_become_a_tamper_event(
    tmp_path: Path, record: audit.GateRun, problem: str
) -> None:
    artifact(tmp_path, "audit-100-code-review", audit.dumps(record))

    ((info, lines),) = collect(tmp_path)

    assert info.tamper is True
    (event,) = lines
    assert event["type"] == "tamper_suspected"
    assert event["workflow_run_id"] == 100  # from the event, not the artifact
    assert any(problem in p for p in event["problems"]), event["problems"]


def test_trusted_only_types_may_not_come_from_an_artifact(tmp_path: Path) -> None:
    feedback = audit.Feedback(
        repo="owner/repo",
        pr=7,
        head_sha="a" * 40,
        workflow_run_id=100,
        run_attempt=1,
        finding_id="cr-0000",
        kind="fp",
        by="me",
    )
    artifact(tmp_path, "audit-100-code-review", audit.dumps(feedback))

    ((info, lines),) = collect(tmp_path)
    assert info.tamper is True
    assert "may not come from a PR's workflow" in lines[0]["problems"][0]


@pytest.mark.parametrize(
    "lines",
    [
        ("not json",),
        ('{"schema": "audit/v1", "type": "gate_run"}',),
        (),
    ],
)
def test_unparseable_or_empty_artifacts_are_tamper_events(
    tmp_path: Path, lines: tuple[str, ...]
) -> None:
    artifact(tmp_path, "audit-100-code-review", *lines)
    ((info, _),) = collect(tmp_path)
    assert info.tamper is True


def test_size_and_count_limits(tmp_path: Path) -> None:
    line = audit.dumps(gate_run())
    artifact(tmp_path, "audit-100-code-review", *[line] * (audit.MAX_RECORDS + 1))
    ((info, lines),) = collect(tmp_path)
    assert info.tamper is True
    assert "over the" in lines[0]["problems"][0]


def test_duplicate_ids_are_rejected(tmp_path: Path) -> None:
    line = audit.dumps(gate_run())
    artifact(tmp_path, "audit-100-code-review", line, line)
    ((info, lines),) = collect(tmp_path)
    assert info.tamper is True
    assert "duplicate" in lines[0]["problems"][0]


def test_artifact_names_and_contents_are_checked(tmp_path: Path) -> None:
    artifact(tmp_path, "audit-99-code-review", audit.dumps(gate_run()))
    artifact(tmp_path, "audit-100-Code Review; rm -rf", audit.dumps(gate_run()))
    extra = artifact(tmp_path, "audit-100-code-review", audit.dumps(gate_run()))
    (extra / "other.txt").write_text("x")

    results = collect(tmp_path)

    assert len(results) == 3
    assert all(info.tamper for info, _ in results)
    paths = sorted(info.path for info, _ in results)
    assert all(p.startswith("events/2026/10/16/100-1-") for p in paths)
    assert "events/2026/10/16/100-1-code-review.jsonl" in paths


@pytest.mark.parametrize(
    ("jobs", "problem"),
    [
        ({}, "has no job 'llm / code-review'"),
        ({"llm / code-review": "cancelled"}, "concluded cancelled, so the record can't be checked"),
        ({"llm / code-review": None}, "concluded None"),
    ],
)
def test_a_record_needs_a_finished_job_to_confirm_it(
    tmp_path: Path, jobs: dict[str, str | None], problem: str
) -> None:
    artifact(tmp_path, "audit-100-code-review", audit.dumps(gate_run()))
    ((info, lines),) = collect(tmp_path, jobs=jobs)
    assert info.tamper is True
    assert any(problem in p for p in lines[0]["problems"]), lines[0]["problems"]


def test_only_checks_from_the_default_branch_are_collected(tmp_path: Path) -> None:
    artifact(tmp_path, "audit-100-made-up", audit.dumps(gate_run(check="made-up")))
    ((info, lines),) = collect(tmp_path)
    assert info.tamper is True
    assert info.path.endswith("-invalid-0.jsonl")
    assert "not a check in the default branch" in lines[0]["problems"][0]


@pytest.mark.parametrize(
    ("fields", "problem"),
    [
        ({"verdict": "pass", "exit_code": 1}, "verdict pass with exit code 1"),
        ({"verdict": "fail", "exit_code": 0}, "verdict fail with exit code 0"),
        ({"verdict": "pass", "exit_code": 0, "override_honoured": True}, "override_honoured"),
    ],
)
def test_verdict_and_exit_code_must_agree(
    tmp_path: Path, fields: dict[str, Any], problem: str
) -> None:
    artifact(tmp_path, "audit-100-code-review", audit.dumps(gate_run(**fields)))
    conclusion = "success" if fields["exit_code"] == 0 else "failure"
    ((info, lines),) = collect(tmp_path, jobs={"llm / code-review": conclusion})
    assert info.tamper is True
    assert any(problem in p for p in lines[0]["problems"]), lines[0]["problems"]


def test_too_many_artifacts_are_one_tamper_event(tmp_path: Path) -> None:
    for n in range(audit.MAX_ARTIFACTS + 1):
        artifact(tmp_path, f"audit-100-check-{n}", "{}")

    ((info, lines),) = collect(tmp_path)

    assert info.path == "events/2026/10/16/100-1-too-much.jsonl"
    assert "over the 20 limit" in lines[0]["problems"][0]


@pytest.mark.parametrize(
    "field",
    [
        {"model": "bad model\nname"},
        {"engine": "other"},
        {"prompt_sha256": "not-a-digest"},
        {"gate_sha": "../../etc"},
        {"actor": "<script>"},
        {
            "findings": [
                {
                    "id": "cr-0000",
                    "severity": "high",
                    "category": "x",
                    "file": "f",
                    "line": 1,
                    "title": "t",
                }
            ]
            * 101
        },
    ],
)
def test_strict_types_reject_free_text_where_none_belongs(field: dict[str, Any]) -> None:
    raw = {**json.loads(audit.dumps(gate_run())), **field}
    with pytest.raises(ValueError):
        audit.parse(json.dumps(raw))


def test_an_override_comment_must_follow_the_label_and_be_unedited() -> None:
    events = [labeled("alice")]
    stale = comment("alice", "/llm-override old reason", at="2026-10-15T09:00:00Z")
    edited = comment("alice", "/llm-override new", edited="2026-10-16T11:00:00Z")

    assert isinstance(audit.find_override(events, [stale]), str)
    assert isinstance(audit.find_override(events, [edited]), str)
    assert audit.find_override(events, [stale, comment("alice", "/llm-override ok")]) == (
        audit.OverrideRequest(by="alice", reason="ok")
    )


# --- CLI ---


def expected_args() -> list[str]:
    return [
        "--repo-name",
        "owner/repo",
        "--run-id",
        "100",
        "--run-attempt",
        "1",
        "--head-sha",
        "a" * 40,
        "--pr",
        "7",
    ]


def test_cli_validate(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    good = tmp_path / "good.jsonl"
    good.write_text(audit.dumps(gate_run()) + "\n")
    bad = tmp_path / "bad.jsonl"
    bad.write_text(audit.dumps(gate_run(pr=8)) + "\n")

    assert main(["audit", "validate", str(good), *expected_args()]) == 0
    assert main(["audit", "validate", str(bad), *expected_args()]) == 1
    assert "pr does not match" in capsys.readouterr().out


def test_cli_collect(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    artifact(tmp_path, "audit-100-code-review", audit.dumps(gate_run()))
    jobs = tmp_path / "jobs.jsonl"
    jobs.write_text('{"name": "llm / code-review", "conclusion": "failure"}\n')
    empty = tmp_path / "empty.json"
    empty.write_text("[]")

    code = main(
        [
            "audit",
            "collect",
            *expected_args(),
            "--artifacts",
            str(tmp_path / "artifacts"),
            "--checks",
            '["code-review"]',
            "--jobs",
            str(jobs),
            "--out",
            str(tmp_path / "out"),
            "--date",
            "2026-10-16",
            "--events",
            str(empty),
            "--comments",
            str(empty),
        ]
    )

    assert code == 0
    (summary,) = json.loads(capsys.readouterr().out)
    assert summary["path"] == "events/2026/10/16/100-1-code-review.jsonl"
    assert summary["tamper"] is False


def test_cli_override(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    events = tmp_path / "events.json"
    events.write_text(json.dumps([labeled("alice")]))
    comments = tmp_path / "comments.json"
    comments.write_text(json.dumps([comment("alice", "/llm-override flaky reviewer")]))
    args = ["audit", "override", "--events", str(events), "--comments", str(comments)]

    assert main(args) == 0
    assert json.loads(capsys.readouterr().out) == {"by": "alice", "reason": "flaky reviewer"}

    comments.write_text("[]")
    assert main(args) == 1
    assert "`/llm-override <reason>`" in capsys.readouterr().err


def test_cli_reports_unreadable_inputs_as_errors(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    bad = tmp_path / "events.json"
    bad.write_text("not json")
    args = ["audit", "override", "--events", str(bad), "--comments", str(bad)]

    assert main(args) == 2
    assert "JSONDecodeError" in caplog.text


def test_model_written_text_is_scrubbed_on_both_sides() -> None:
    secret = "sk-ant-api03-" + "x" * 40
    f = audit.AuditFinding(
        id="cr-0000",
        severity=Severity.HIGH,
        category="secrets",
        file="appsettings.json",
        line=3,
        title=f"Hardcoded key {secret} in appsettings.json",
    )
    assert secret not in f.title and REDACTED in f.title

    record = gate_run(findings=[f], error="x" * 10_000)
    assert len(record.error or "") == 500
    # An artifact written by anything else is scrubbed when the collector parses it.
    raw = json.loads(audit.dumps(record))
    raw["findings"][0]["title"] = f"again {secret}"
    assert secret not in audit.dumps(audit.parse(json.dumps(raw)))


def override_record(**overrides: Any) -> audit.Override:
    fields: dict[str, Any] = {
        "repo": "owner/repo",
        "pr": 7,
        "head_sha": "a" * 40,
        "workflow_run_id": 100,
        "run_attempt": 1,
        "run_url": EXPECTED.run_url,
        "by": "alice",
        "reason": "hotfix",
        "checks": ["code-review"],
    }
    fields.update(overrides)
    return audit.Override(**fields)


@pytest.mark.parametrize(
    ("lines", "trusted", "problem"),
    [
        ((override_record(),), NO_OVERRIDE, "the collector found none"),
        ((override_record(by="mallory"),), "alice", "does not match"),
        ((override_record(reason="other"),), "alice", "does not match"),
        ((gate_run(override_honoured=True, exit_code=0),), NO_OVERRIDE, "override honoured"),
    ],
)
def test_override_claims_must_match_what_the_collector_found(
    tmp_path: Path, lines: tuple[Any, ...], trusted: str, problem: str
) -> None:
    artifact(tmp_path, "audit-100-code-review", *(audit.dumps(r) for r in lines))
    found = audit.OverrideRequest(by="alice", reason="hotfix") if trusted == "alice" else trusted

    ((info, out),) = collect(tmp_path, jobs={}, override=found)

    assert info.tamper is True
    assert any(problem in p for p in out[0]["problems"]), out[0]["problems"]


def test_a_finished_review_is_recorded_within_the_schema_limits(tmp_path: Path) -> None:
    from conftest import make_check, result

    from llm_gate.runner import RunRecord

    many = [finding(Severity.LOW, line=0)] * 150 + [finding(Severity.CRITICAL, line=-3)]
    record = RunRecord(
        check="code-review",
        mode="blocking",
        fail_on=Severity.HIGH,
        engine="api",
        model="claude-test-model",
        verdict="fail",
        exit_code=1,
        reason="x",
        result=result(*many),
    )
    info = audit.GateInfo(None, "1" * 64, ".claude/commands/llm-code-review.md", "0" * 64)

    entry = audit.gate_run(
        record,
        check=make_check(tmp_path),
        context=audit.RunContext(),
        gate=info,
        diff_text="",
        started_at=T,
        finished_at=T,
    )

    assert len(entry.findings) == audit.MAX_FINDINGS
    assert entry.findings[0].severity == Severity.CRITICAL  # the most severe are kept
    assert all(f.line is None for f in entry.findings)


def test_tamper_events_never_quote_the_artifact(tmp_path: Path) -> None:
    text = "SHOUTING ABUSE or personal data"
    raw = json.loads(audit.dumps(gate_run()))
    artifact(tmp_path, "audit-100-code-review", json.dumps({**raw, "model": text}))
    artifact(tmp_path, "audit-100-docs-drift", json.dumps({**raw, text.lower(): 1}))
    artifact(tmp_path, f"audit-100-{text}", "{}")
    weird = artifact(tmp_path, "audit-100-docs-drift-x", "{}")
    (weird / text).write_text("x")
    artifact(tmp_path, "audit-99-code-review", json.dumps({**raw, "run_url": text}))

    results = collect(tmp_path, checks={"code-review", "docs-drift", "docs-drift-x"})

    assert len(results) == 5
    for info, lines in results:
        assert info.tamper is True
        assert text not in json.dumps(lines)
        assert text.lower() not in json.dumps(lines)
        assert text not in info.artifact


@pytest.mark.parametrize("shape", ["directory", "symlink"])
def test_an_audit_file_that_is_not_a_regular_file_is_a_tamper_event(
    tmp_path: Path, shape: str
) -> None:
    good = artifact(tmp_path, "audit-100-code-review", audit.dumps(gate_run()))
    bad = tmp_path / "artifacts" / "audit-100-docs-drift"
    bad.mkdir()
    if shape == "directory":
        (bad / audit.AUDIT_FILE).mkdir()
    else:
        (bad / audit.AUDIT_FILE).symlink_to(good / audit.AUDIT_FILE)

    results = {info.path.rsplit("-", 2)[-1]: (info, lines) for info, lines in collect(tmp_path)}

    assert results["review.jsonl"][0].tamper is False  # the good artifact is still collected
    info, lines = results["drift.jsonl"]
    assert info.tamper is True
    assert "not a regular file" in lines[0]["problems"][0]


def test_unknown_tool_names_are_logged_as_other() -> None:
    call = {"tool": "mcp__evil__SHOUTING", "input": "x", "ts": T}
    parsed = audit.parse(audit.dumps(gate_run(tool_calls=[call])))
    assert isinstance(parsed, audit.GateRun)
    assert parsed.tool_calls[0].tool == "other"


@pytest.mark.parametrize(
    ("record", "problem"),
    [
        (
            gate_run(
                findings=[
                    audit.AuditFinding(
                        id="abuse-0000",
                        severity=Severity.LOW,
                        category="c",
                        file="f",
                        line=1,
                        title="t",
                    )
                ]
            ),
            "finding ids not of the form cr-xxxx",
        ),
    ],
)
def test_finding_ids_must_carry_their_checks_prefix(
    tmp_path: Path, record: audit.GateRun, problem: str
) -> None:
    artifact(tmp_path, "audit-100-code-review", audit.dumps(record))
    ((info, lines),) = collect(tmp_path)
    assert info.tamper is True
    assert any(problem in p for p in lines[0]["problems"])


def test_an_override_names_only_its_artifacts_check(tmp_path: Path) -> None:
    claim = override_record(checks=["code-review", "everything-is-fine"])
    artifact(tmp_path, "audit-100-code-review", audit.dumps(claim))
    trusted = audit.OverrideRequest(by="alice", reason="hotfix")
    ((info, lines),) = collect(tmp_path, jobs={}, override=trusted)
    assert info.tamper is True
    assert "must name only that check" in lines[0]["problems"][0]


def test_risk_is_one_of_three_levels() -> None:
    raw = {**json.loads(audit.dumps(gate_run())), "risk": "free text"}
    with pytest.raises(ValueError, match="risk"):
        audit.parse(json.dumps(raw))

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
from conftest import finding

from llm_gate import audit
from llm_gate.cli import main
from llm_gate.models import Severity, finding_id

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
        "check": "code-review",
        "engine": "agent",
        "model": "m",
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


def collect(tmp_path: Path, jobs: dict[str, str | None] | None = None, **kwargs: Any) -> list[Any]:
    out = tmp_path / "out"
    collected = audit.collect(
        tmp_path / "artifacts",
        expected=EXPECTED,
        jobs=jobs if jobs is not None else {"llm / code-review": "failure"},
        workflow_modified=kwargs.get("workflow_modified", False),
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
    redacted = audit.redact(f"before {secret} after")
    assert audit.REDACTED in redacted
    assert secret not in redacted


def test_tool_input_summaries_are_relative_short_and_redacted(tmp_path: Path) -> None:
    read = audit.summarise_tool_input(
        "Read", {"file_path": f"{tmp_path}/src/A.cs", "offset": 10}, tmp_path
    )
    assert read == "file_path=src/A.cs offset=10"

    grep = audit.summarise_tool_input("Grep", {"pattern": "ghp_" + "A" * 36}, tmp_path)
    assert grep == f"pattern={audit.REDACTED}"

    long = audit.summarise_tool_input("Other", {"q": "x" * 1000}, None)
    assert len(long) == audit.MAX_SUMMARY
    assert long.endswith("…")


# --- overrides ---


def labeled(by: str, label: str = "llm-override") -> dict[str, Any]:
    return {"event": "labeled", "label": {"name": label}, "actor": {"login": by}}


def comment(by: str, body: str) -> dict[str, Any]:
    return {"user": {"login": by}, "body": body}


def test_override_needs_a_reason_from_whoever_added_the_label() -> None:
    events = [labeled("alice"), labeled("bob", "other")]

    found = audit.find_override(events, [comment("alice", "/llm-override hotfix for prod\nmore")])
    assert found == audit.OverrideRequest(by="alice", reason="hotfix for prod")

    no_reason = audit.find_override(events, [comment("alice", "/llm-override   ")])
    assert isinstance(no_reason, str) and "no `/llm-override <reason>`" in no_reason

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
        by="me",
        reason="r",
        checks=["code-review"],
    )
    artifact(tmp_path, "audit-100-code-review", audit.dumps(gate_run()), audit.dumps(override))

    ((info, lines),) = collect(tmp_path, workflow_modified=True)

    assert info.path == "events/2026/10/16/100-1-code-review.jsonl"
    assert info.tamper is False
    assert info.records == 2
    assert lines[0]["workflow_modified"] is True
    assert lines[0]["check_run_conclusion"] == "failure"
    assert lines[1]["type"] == "override"


@pytest.mark.parametrize(
    ("record", "problem"),
    [
        (gate_run(workflow_run_id=99), "workflow_run_id is 99"),
        (gate_run(head_sha="c" * 40), "head_sha"),
        (gate_run(pr=8), "pr is 8"),
        (gate_run(repo="evil/repo"), "repo is 'evil/repo'"),
        (gate_run(run_attempt=2), "run_attempt"),
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


def test_a_cancelled_job_is_recorded_not_flagged(tmp_path: Path) -> None:
    artifact(tmp_path, "audit-100-code-review", audit.dumps(gate_run()))
    ((info, lines),) = collect(tmp_path, jobs={"llm / code-review": "cancelled"})
    assert info.tamper is False
    assert lines[0]["check_run_conclusion"] == "cancelled"


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
    assert "pr is 8" in capsys.readouterr().out


def test_cli_collect(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    artifact(tmp_path, "audit-100-code-review", audit.dumps(gate_run()))
    jobs = tmp_path / "jobs.jsonl"
    jobs.write_text('{"name": "llm / code-review", "conclusion": "failure"}\n')

    code = main(
        [
            "audit",
            "collect",
            *expected_args(),
            "--artifacts",
            str(tmp_path / "artifacts"),
            "--jobs",
            str(jobs),
            "--out",
            str(tmp_path / "out"),
            "--date",
            "2026-10-16",
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
    assert "no `/llm-override <reason>`" in capsys.readouterr().err

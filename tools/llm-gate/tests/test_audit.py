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
        "xoxb-" + "1234567890" + "-" + "D" * 24,  # Slack (F033: no case covered this)
        # A JWT, assembled at run time: a whole one on a source line is what gitleaks flags, and
        # the pre-commit hook is right to. redact() still sees the complete token.
        "eyJhbGciOiJIUzI1NiJ9." + "eyJzdWIiOiIxMjM0NTY3ODkwIn0." + "E" * 27,
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

    glob = audit.summarise_tool_input(
        "Glob", {"pattern": "**/*.cs", "path": f"{tmp_path}/src"}, tmp_path
    )
    assert glob == "pattern=**/*.cs path=src"

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


# The logins the caller resolved to a write, maintain or admin role. An override needs one whoever
# added the label, because labels can be applied with the triage role (F007).
WRITERS = frozenset({"alice", "bob"})


def override(events: list[dict[str, Any]], comments: list[dict[str, Any]]) -> Any:
    return audit.find_override(events, comments, writers=WRITERS)


def test_override_needs_a_reason_from_whoever_added_the_label() -> None:
    events = [labeled("alice"), labeled("bob", "other")]

    found = override(events, [comment("alice", "/llm-override hotfix for prod\nmore")])
    assert found == audit.OverrideRequest(by="alice", reason="hotfix for prod")

    no_reason = override(events, [comment("alice", "/llm-override   ")])
    assert isinstance(no_reason, str) and "`/llm-override <reason>`" in no_reason

    someone_else = override(events, [comment("mallory", "/llm-override trust me")])
    assert isinstance(someone_else, str)


def test_a_labeller_without_write_access_cannot_override() -> None:
    """Applying a label is the triage role, which has no write access; `/llm-override` as a command
    is refused for it, so the label path can't honour it either (F007)."""
    events = [labeled("trish")]
    comments = [comment("trish", "/llm-override shipping anyway")]

    refused = audit.find_override(events, comments, writers=WRITERS)
    assert isinstance(refused, str) and "write access" in refused

    # Nothing is honoured when the caller looked up no roles at all.
    assert isinstance(audit.find_override(events, comments), str)
    assert isinstance(
        audit.find_override([labeled("alice")], [comment("alice", "/llm-override ok")]), str
    )


def test_the_latest_labeller_counts() -> None:
    events = [labeled("alice"), labeled("bob")]
    found = override(events, [comment("alice", "/llm-override reason")])
    assert isinstance(found, str) and found.startswith("bob")


def test_no_label_event_is_no_override() -> None:
    assert isinstance(override([], [comment("a", "/llm-override x")]), str)


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
    artifact(tmp_path, "audit-100-1-code-review", audit.dumps(gate_run()), audit.dumps(override))

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
    refused = {"tool": "Read", "input": "file_path=/proc/self/environ", "ts": T, "denied": True}
    artifact(
        tmp_path,
        "audit-100-1-code-review",
        audit.dumps(
            gate_run(findings=[f], tool_calls=[call, refused], denied_reads=1),
        ),
    )

    ((_, kept),) = collect(tmp_path)
    ((_, withheld),) = collect(tmp_path, workflow_modified=True)

    assert kept[0]["findings"][0]["title"] == "t"
    assert kept[0]["tool_calls"][0]["input"] == "file_path=a.cs"
    assert withheld[0]["findings"][0]["title"] == audit.WITHHELD
    assert withheld[0]["findings"][0]["id"] == "cr-0000"  # the structure stays
    assert withheld[0]["findings"][0]["severity"] == "high"
    assert withheld[0]["tool_calls"][0] == {**kept[0]["tool_calls"][0], "input": ""}
    # A refused read is a fact about the run, not text from it: the flag and the count stay even
    # when the free text goes (F003).
    assert withheld[0]["tool_calls"][1]["denied"] is True
    assert withheld[0]["denied_reads"] == 1


def test_a_run_has_a_byte_budget(tmp_path: Path) -> None:
    # The budget is checked before anything is parsed, so raw bytes are enough.
    for n in range(3):
        artifact(tmp_path, f"audit-100-1-check-{n}", "x" * (audit.MAX_RUN_BYTES // 3 + 1))

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
    artifact(tmp_path, "audit-100-1-code-review", audit.dumps(record))

    ((info, lines),) = collect(tmp_path)

    assert info.tamper is True
    (event,) = lines
    assert event["type"] == "tamper_suspected"
    assert event["workflow_run_id"] == 100  # from the event, not the artifact
    assert any(problem in p for p in event["problems"]), event["problems"]


def trusted_only_record(type_: str) -> str:
    """A record of a type only the collector or the feedback workflow may write, as a PR's own
    artifact would have to spell it. Not built through the models: the point is what the collector
    does with the raw type."""
    base = {
        "schema": "audit/v1",
        "id": "0" * 8 + "-0000-4000-8000-" + "0" * 12,
        "ts": "2026-10-17T10:00:00Z",
        "repo": "owner/repo",
        "pr": 7,
        "head_sha": "a" * 40,
        "workflow_run_id": 100,
        "run_attempt": 1,
        "run_url": EXPECTED.run_url,
        "type": type_,
    }
    by_type: dict[str, dict[str, Any]] = {
        "feedback": {"finding_id": "cr-0000", "check": "code-review", "kind": "fp", "by": "me"},
        "feedback_rejected": {"by": "me", "command": "fp", "code": "not_a_collaborator"},
        "risk_override": {"from": "low", "to": "high", "by": "me", "reason": "mine now"},
        "eval_run": {
            "prompt_sha256": "0" * 64,
            "model": "claude-sonnet-5-5",
            "engine": "api",
            "scores": {"recall": 1.0},
        },
        "tamper_suspected": {"artifact": "audit-100-1-code-review", "problems": ["invented"]},
    }
    return json.dumps({**base, **by_type[type_]})


@pytest.mark.parametrize(
    "type_", ["feedback", "feedback_rejected", "risk_override", "eval_run", "tamper_suspected"]
)
def test_trusted_only_types_may_not_come_from_an_artifact(tmp_path: Path, type_: str) -> None:
    """Every type the collector writes itself, not just `feedback` (F014). `risk_override` is the
    one that matters most: triage trusts those records precisely because a PR's run can't write
    one (ADR 0008), and a mutation adding it to ARTIFACT_TYPES survived the old single-type test."""
    artifact(tmp_path, "audit-100-1-code-review", trusted_only_record(type_))

    ((info, lines),) = collect(tmp_path)

    assert info.tamper is True
    assert any("may not come from a PR's workflow" in p for p in lines[0]["problems"])


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
    artifact(tmp_path, "audit-100-1-code-review", *lines)
    ((info, _),) = collect(tmp_path)
    assert info.tamper is True


def test_too_many_records_in_one_artifact(tmp_path: Path) -> None:
    line = audit.dumps(gate_run())
    artifact(tmp_path, "audit-100-1-code-review", *[line] * (audit.MAX_RECORDS + 1))
    ((info, lines),) = collect(tmp_path)
    assert info.tamper is True
    assert f"over the {audit.MAX_RECORDS} limit" in lines[0]["problems"][0]


def test_one_artifact_over_the_byte_limit(tmp_path: Path) -> None:
    """ADR 0005's 128 KB per artifact. The old test wrote 21 small lines, so only the record count
    fired and its assertion ("over the") matched either message (F016)."""
    artifact(tmp_path, "audit-100-1-code-review", audit.dumps(gate_run()))
    path = tmp_path / "artifacts" / "audit-100-1-code-review" / audit.AUDIT_FILE
    # Padded past the file limit while staying under the run budget, so only this check can fire.
    path.write_bytes(path.read_bytes() + b" " * (audit.MAX_FILE_BYTES + 1 - path.stat().st_size))

    ((info, lines),) = collect(tmp_path)

    assert info.tamper is True
    assert f"over the {audit.MAX_FILE_BYTES} limit" in lines[0]["problems"][0]


def test_one_record_over_the_line_limit(tmp_path: Path) -> None:
    """MAX_LINE_BYTES sits below MAX_FILE_BYTES, so it can actually fire (F016)."""
    artifact(tmp_path, "audit-100-1-code-review", "{" + " " * audit.MAX_LINE_BYTES + "}")

    ((info, lines),) = collect(tmp_path)

    assert info.tamper is True
    assert f"line over {audit.MAX_LINE_BYTES} bytes" in " ".join(lines[0]["problems"])


def test_duplicate_ids_are_rejected(tmp_path: Path) -> None:
    line = audit.dumps(gate_run())
    artifact(tmp_path, "audit-100-1-code-review", line, line)
    ((info, lines),) = collect(tmp_path)
    assert info.tamper is True
    assert "duplicate" in lines[0]["problems"][0]


def test_artifact_names_and_contents_are_checked(tmp_path: Path) -> None:
    artifact(tmp_path, "audit-99-1-code-review", audit.dumps(gate_run()))
    artifact(tmp_path, "audit-100-2-code-review", audit.dumps(gate_run()))  # another attempt
    artifact(tmp_path, "audit-100-1-Code Review; rm -rf", audit.dumps(gate_run()))
    extra = artifact(tmp_path, "audit-100-1-code-review", audit.dumps(gate_run()))
    (extra / "other.txt").write_text("x")

    results = collect(tmp_path)

    assert len(results) == 4
    assert all(info.tamper for info, _ in results)
    paths = sorted(info.path for info, _ in results)
    assert all(p.startswith("events/2026/10/16/100-1-") for p in paths)
    assert "events/2026/10/16/100-1-code-review.jsonl" in paths


@pytest.mark.parametrize(
    ("jobs", "problem"),
    [
        ({}, "has no job 'llm / code-review'"),
        ({"llm / code-review": "cancelled"}, "concluded cancelled, so the record can't be checked"),
    ],
)
def test_a_record_needs_a_finished_job_to_confirm_it(
    tmp_path: Path, jobs: dict[str, str | None], problem: str
) -> None:
    artifact(tmp_path, "audit-100-1-code-review", audit.dumps(gate_run()))
    ((info, lines),) = collect(tmp_path, jobs=jobs)
    assert info.tamper is True
    assert any(problem in p for p in lines[0]["problems"]), lines[0]["problems"]


@pytest.mark.parametrize(
    "jobs",
    [
        {"llm / code-review": None},
        # One unfinished job is enough, even one the artifacts don't name: 2026-10-19's run
        # 39287691571 had triage and workflow-review concluded and five checks still at null.
        {"llm / code-review": "success", "triage": None},
    ],
)
def test_a_job_with_no_conclusion_yet_stops_the_collection(
    tmp_path: Path, jobs: dict[str, str | None]
) -> None:
    # Not tampering, and nothing written: the paths stay free for a re-run (ADR 0005).
    artifact(tmp_path, "audit-100-1-code-review", audit.dumps(gate_run()))
    with pytest.raises(audit.JobsNotFinished, match="no conclusion yet for: "):
        collect(tmp_path, jobs=jobs)
    assert not (tmp_path / "out").exists()


def test_only_checks_from_the_default_branch_are_collected(tmp_path: Path) -> None:
    artifact(tmp_path, "audit-100-1-made-up", audit.dumps(gate_run(check="made-up")))
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
        # Blocking checks fail closed, so a passing error needs an honoured override (ADR 0002).
        (
            {"verdict": "error", "exit_code": 0, "blocking": True},
            "a blocking check reports error with exit code 0 and no override",
        ),
    ],
)
def test_verdict_and_exit_code_must_agree(
    tmp_path: Path, fields: dict[str, Any], problem: str
) -> None:
    artifact(tmp_path, "audit-100-1-code-review", audit.dumps(gate_run(**fields)))
    conclusion = "success" if fields["exit_code"] == 0 else "failure"
    ((info, lines),) = collect(tmp_path, jobs={"llm / code-review": conclusion})
    assert info.tamper is True
    assert any(problem in p for p in lines[0]["problems"]), lines[0]["problems"]


def test_an_oversized_diff_accepted_by_override_is_a_valid_record(tmp_path: Path) -> None:
    """verdict `error` with exit 0 is how an accepted-unreviewed diff is recorded (ADR 0002)."""
    record = gate_run(
        verdict="error",
        exit_code=0,
        blocking=True,
        override_honoured=True,
        error="diff too large: 488 KB > max_diff_kb 200 (accepted unreviewed by override)",
        omitted_files=[{"path": "src/Api/Generated.pb.cs", "bytes": 300_000}],
    )
    artifact(tmp_path, "audit-100-1-code-review", audit.dumps(record))

    trusted = audit.OverrideRequest(by="maintainer", reason="generated migration")
    ((info, lines),) = collect(tmp_path, jobs={"llm / code-review": "success"}, override=trusted)

    assert info.tamper is False
    assert lines[0]["override_honoured"] is True
    assert lines[0]["omitted_files"] == [{"path": "src/Api/Generated.pb.cs", "bytes": 300000}]


def test_too_many_artifacts_are_one_tamper_event(tmp_path: Path) -> None:
    for n in range(audit.MAX_ARTIFACTS + 1):
        artifact(tmp_path, f"audit-100-1-check-{n}", "{}")

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


def unlabeled(by: str, at: str) -> dict[str, Any]:
    return {**labeled(by, at=at), "event": "unlabeled"}


def test_an_override_comment_may_come_before_the_label() -> None:
    before = comment("alice", "/llm-override hotfix", at="2026-10-16T09:59:00Z")
    assert override([labeled("alice")], [before]) == audit.OverrideRequest(
        by="alice", reason="hotfix"
    )


def test_an_override_comment_from_an_earlier_round_or_edited_does_not_count() -> None:
    old = comment("alice", "/llm-override old reason", at="2026-10-15T09:00:00Z")
    events = [
        labeled("alice", at="2026-10-15T08:00:00Z"),
        unlabeled("alice", at="2026-10-15T12:00:00Z"),
        labeled("alice"),
    ]
    edited = comment("alice", "/llm-override new", edited="2026-10-16T11:00:00Z")

    assert isinstance(override(events, [old]), str)
    assert isinstance(override(events, [edited]), str)
    new = comment("alice", "/llm-override ok", at="2026-10-15T13:00:00Z")  # after the removal
    assert override(events, [old, new]) == audit.OverrideRequest(by="alice", reason="ok")


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
    artifact(tmp_path, "audit-100-1-code-review", audit.dumps(gate_run()))
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


def test_cli_collect_exits_3_while_a_job_has_no_conclusion(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    artifact(tmp_path, "audit-100-1-code-review", audit.dumps(gate_run()))
    jobs = tmp_path / "jobs.jsonl"
    jobs.write_text('{"name": "llm / code-review", "conclusion": null}\n')
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

    assert code == 3
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "not finished: no conclusion yet for: llm / code-review" in captured.err
    assert not (tmp_path / "out").exists()


def test_cli_override(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    events = tmp_path / "events.json"
    events.write_text(json.dumps([labeled("alice")]))
    comments = tmp_path / "comments.json"
    comments.write_text(json.dumps([comment("alice", "/llm-override flaky reviewer")]))
    writers = tmp_path / "writers.json"
    writers.write_text(json.dumps(sorted(WRITERS)))
    args = ["audit", "override", "--events", str(events), "--comments", str(comments)]
    with_roles = [*args, "--writers", str(writers)]

    assert main(with_roles) == 0
    assert json.loads(capsys.readouterr().out) == {"by": "alice", "reason": "flaky reviewer"}

    # The same inputs without the role list: an override the caller can't attribute to someone
    # with write access isn't one (F007).
    assert main(args) == 1
    assert "write access" in capsys.readouterr().err

    comments.write_text("[]")
    assert main(with_roles) == 1
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
    artifact(tmp_path, "audit-100-1-code-review", *(audit.dumps(r) for r in lines))
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
    artifact(tmp_path, "audit-100-1-code-review", json.dumps({**raw, "model": text}))
    artifact(tmp_path, "audit-100-1-docs-drift", json.dumps({**raw, text.lower(): 1}))
    artifact(tmp_path, f"audit-100-1-{text}", "{}")
    weird = artifact(tmp_path, "audit-100-1-docs-drift-x", "{}")
    (weird / text).write_text("x")
    artifact(tmp_path, "audit-99-1-code-review", json.dumps({**raw, "run_url": text}))

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
    good = artifact(tmp_path, "audit-100-1-code-review", audit.dumps(gate_run()))
    bad = tmp_path / "artifacts" / "audit-100-1-docs-drift"
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
    artifact(tmp_path, "audit-100-1-code-review", audit.dumps(record))
    ((info, lines),) = collect(tmp_path)
    assert info.tamper is True
    assert any(problem in p for p in lines[0]["problems"])


def test_an_override_names_only_its_artifacts_check(tmp_path: Path) -> None:
    claim = override_record(checks=["code-review", "everything-is-fine"])
    artifact(tmp_path, "audit-100-1-code-review", audit.dumps(claim))
    trusted = audit.OverrideRequest(by="alice", reason="hotfix")
    ((info, lines),) = collect(tmp_path, jobs={}, override=trusted)
    assert info.tamper is True
    assert "must name only that check" in lines[0]["problems"][0]


def test_risk_is_one_of_three_levels() -> None:
    raw = {**json.loads(audit.dumps(gate_run())), "risk": "free text"}
    with pytest.raises(ValueError, match="risk"):
        audit.parse(json.dumps(raw))


def partial_pass() -> audit.GateRun:
    """What a blocking check records when an override let it review the rest (ADR 0002)."""
    return gate_run(
        verdict="pass",
        exit_code=0,
        blocking=True,
        omitted_files=[{"path": "src/Api/Grpc/Service.pb.cs", "bytes": 300_000}],
    )


def test_a_blocking_check_may_not_omit_files_without_an_override(tmp_path: Path) -> None:
    artifact(tmp_path, "audit-100-1-code-review", audit.dumps(partial_pass()))

    ((info, lines),) = collect(tmp_path, jobs={"llm / code-review": "success"})

    assert info.tamper is True
    assert "omitted from a blocking review" in " ".join(lines[0]["problems"])


def test_a_partial_review_the_collector_found_an_override_for_is_valid(tmp_path: Path) -> None:
    """The path both reviewers flagged: this record must not read as tampering."""
    trusted = audit.OverrideRequest(by="maintainer", reason="generated stubs")
    artifact(
        tmp_path,
        "audit-100-1-code-review",
        audit.dumps(partial_pass()),
        audit.dumps(override_record(by="maintainer", reason="generated stubs")),
    )

    ((info, lines),) = collect(tmp_path, jobs={"llm / code-review": "success"}, override=trusted)

    assert info.tamper is False
    assert lines[0]["verdict"] == "pass"
    assert lines[0]["omitted_files"][0]["path"] == "src/Api/Grpc/Service.pb.cs"


def test_a_refused_read_survives_the_tool_call_limit(tmp_path: Path) -> None:
    """A review that issues two hundred ordinary reads before the interesting one must not be able
    to push the refusal off the record (F003)."""
    from conftest import make_check, result

    from llm_gate.models import ToolCall
    from llm_gate.runner import RunRecord

    calls = [
        ToolCall(tool="Read", input=f"file_path=src/A{n}.cs", ts=T)
        for n in range(audit.MAX_TOOL_CALLS + 5)
    ]
    calls.append(ToolCall(tool="Read", input="file_path=/proc/self/environ", ts=T, denied=True))
    engine_result = result()
    engine_result = engine_result.model_copy(update={"tool_calls": calls, "denied_reads": 1})
    record = RunRecord(
        check="code-review",
        mode="blocking",
        fail_on=Severity.HIGH,
        engine="agent",
        model="claude-test-model",
        verdict="pass",
        exit_code=0,
        reason="x",
        result=engine_result,
    )

    entry = audit.gate_run(
        record,
        check=make_check(tmp_path),
        context=audit.RunContext(),
        gate=audit.GateInfo(None, "1" * 64, ".claude/commands/llm-code-review.md", "0" * 64),
        diff_text="",
        started_at=T,
        finished_at=T,
    )

    assert len(entry.tool_calls) == audit.MAX_TOOL_CALLS
    assert [c.input for c in entry.tool_calls if c.denied] == ["file_path=/proc/self/environ"]
    assert entry.denied_reads == 1


# --- the config a run was judged by (F022) -------------------------------------------------------


def test_a_run_is_judged_by_the_checks_yaml_it_used(repo: Any, tmp_path: Path) -> None:
    """A checks.yaml that merges while a review is in flight used to turn that whole run into
    tamper_suspected. The run's own config is used when it can be proved to be ours: the commit is
    an ancestor of the trunk and the file hashes to what the record says (F022)."""
    from argparse import Namespace

    from llm_gate.cli import _run_gate_config
    from llm_gate.diff import git as run_git

    config = repo.root / "tools" / "llm-gate" / "checks.yaml"
    run_git(repo.root, "switch", "-q", "main")
    then = "checks:\n  code-review: {mode: blocking, fail_on: high}\n"
    repo.write("tools/llm-gate/checks.yaml", then)
    repo.commit("the config the run used")
    gate_sha = run_git(repo.root, "rev-parse", "HEAD").strip()
    repo.write("tools/llm-gate/checks.yaml", then + "  docs-drift: {mode: advisory}\n")
    repo.commit("the rules changed after the run")

    def resolved(**record: Any) -> Path:
        artifacts = tmp_path / "artifacts" / "audit-1-1-code-review"
        artifacts.mkdir(parents=True, exist_ok=True)
        (artifacts / "audit.jsonl").write_text(json.dumps({"type": "gate_run", **record}) + "\n")
        args = Namespace(
            artifacts=tmp_path / "artifacts",
            out=tmp_path / "out",
            default_branch="main",
        )
        return _run_gate_config(args, repo.root, config)

    good = resolved(gate_sha=gate_sha, config_sha256=audit.sha256_text(then))
    assert good != config and good.read_text(encoding="utf-8") == then

    # A sha that isn't on the trunk, and a hash that doesn't match the file there: both fall back
    # to the collector's own config, so a forged hint can't pick the rules it is judged by.
    assert resolved(gate_sha="0" * 40, config_sha256=audit.sha256_text(then)) == config
    assert resolved(gate_sha=gate_sha, config_sha256="f" * 64) == config
    assert resolved(gate_sha=gate_sha) == config  # no hash at all

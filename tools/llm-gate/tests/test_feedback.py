import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from llm_gate import audit, feedback
from llm_gate.cli import main

NOW = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)
CONTEXT = audit.RunContext(repo="owner/repo", workflow_run_id=5, run_attempt=1)


def event(body: str, *, association: str = "OWNER", login: str = "alice", pr: bool = True) -> Any:
    return {
        "issue": {"number": 7, **({"pull_request": {"url": "x"}} if pr else {})},
        "comment": {
            "id": 1234,
            "body": body,
            "user": {"login": login},
            "author_association": association,
        },
    }


@pytest.fixture
def audit_dir(tmp_path: Path) -> Path:
    events = tmp_path / "events" / "2026" / "10" / "16"
    events.mkdir(parents=True)
    run = {
        "type": "gate_run",
        "pr": 7,
        "check": "code-review",
        "findings": [{"id": "cr-1705", "severity": "high"}],
    }
    other_pr = {**run, "pr": 8, "findings": [{"id": "cr-9999", "severity": "high"}]}
    (events / "1-1-code-review.jsonl").write_text(json.dumps(run) + "\n" + json.dumps(other_pr))
    return tmp_path


def handle(
    body: str, audit_dir: Path, permission: str | None = "write", **kwargs: Any
) -> feedback.Actions:
    return feedback.handle(
        event(body, **kwargs),
        audit_dir=audit_dir,
        blocking_checks=["security-review", "code-review"],
        context=CONTEXT,
        now=NOW,
        permission=permission,
    )


def record(actions: feedback.Actions) -> dict[str, Any]:
    (line,) = actions.records
    parsed: dict[str, Any] = json.loads(line)
    audit.parse(line)  # every record is valid audit/v1
    return parsed


# --- parsing ---


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("/llm-fp cr-1705 not a bug: inclusive by design", ("fp", "cr-1705", None)),
        ("/llm-ack cr-1705", ("ack", "cr-1705", None)),
        ("/llm-override hotfix, reviewed by hand\nmore text", ("override", None, None)),
        ("/llm-risk low docs only", ("risk", None, "low")),
    ],
)
def test_commands_parse(body: str, expected: tuple[str, str | None, str | None]) -> None:
    parsed = feedback.parse_command(body)
    assert isinstance(parsed, feedback.Command)
    assert (parsed.name, parsed.finding_id, parsed.level) == expected


@pytest.mark.parametrize(
    ("body", "command", "code"),
    [
        ("/llm-fp cr-1705", "fp", "bad_arguments"),  # a false positive needs a reason
        ("/llm-fp not-an-id because", "fp", "bad_arguments"),
        ("/llm-override", "override", "bad_arguments"),
        ("/llm-risk extreme now", "risk", "bad_arguments"),
        ("/llm-risk high", "risk", "bad_arguments"),
        ("/llm-approve please", "unknown", "unknown_command"),
        ("please /llm-override", "unknown", "unknown_command"),
    ],
)
def test_bad_commands_are_rejections(body: str, command: str, code: str) -> None:
    assert feedback.parse_command(body) == feedback.Rejection(command, code)  # type: ignore[arg-type]


# --- handling ---


def test_a_false_positive_is_recorded_and_marked(audit_dir: Path) -> None:
    actions = handle("/llm-fp cr-1705 inclusive end by design", audit_dir)

    assert actions.recorded and actions.reaction == "+1"
    assert actions.path == "events/2026/10/16/feedback-1234.jsonl"
    assert actions.mark == {"check": "code-review", "finding_id": "cr-1705", "by": "alice"}
    r = record(actions)
    assert (r["type"], r["kind"], r["check"], r["pr"], r["by"]) == (
        "feedback",
        "fp",
        "code-review",
        7,
        "alice",
    )
    assert r["reason"] == "inclusive end by design"


def test_a_finding_from_another_pr_is_unknown(audit_dir: Path) -> None:
    actions = handle("/llm-ack cr-9999", audit_dir)
    assert not actions.recorded
    assert actions.reaction == "confused"
    assert record(actions)["code"] == "unknown_finding"


def test_override_labels_reruns_and_names_the_blocking_checks(audit_dir: Path) -> None:
    actions = handle("/llm-override hotfix, reviewed by hand", audit_dir)

    assert actions.label == "llm-override"
    assert actions.rerun is True
    r = record(actions)
    assert r["type"] == "override"
    assert r["checks"] == ["code-review", "security-review"]
    assert r["reason"] == "hotfix, reviewed by hand"


def test_risk_is_recorded_and_reruns_the_review(audit_dir: Path) -> None:
    actions = handle("/llm-risk low docs only", audit_dir)
    assert actions.label is None and actions.rerun
    r = record(actions)
    assert (r["type"], r["from"], r["to"]) == ("risk_override", "unknown", "low")


def test_risk_change_records_the_current_triage_risk(audit_dir: Path) -> None:
    day = audit_dir / "events" / "2026" / "10" / "17"
    day.mkdir(parents=True, exist_ok=True)
    lines = [
        {"type": "triage", "pr": 7, "ts": "2026-10-17T08:00:00Z", "final_risk": "medium"},
        {"type": "triage", "pr": 7, "ts": "2026-10-17T09:00:00Z", "final_risk": "high"},
        {"type": "triage", "pr": 8, "ts": "2026-10-17T10:00:00Z", "final_risk": "low"},
    ]
    (day / "1-1-triage.jsonl").write_text("".join(json.dumps(x) + "\n" for x in lines))

    r = record(handle("/llm-risk low docs only", audit_dir))

    assert (r["from"], r["to"]) == ("high", "low")


def test_outsiders_get_one_quiet_fixed_field_rejection_per_day(audit_dir: Path) -> None:
    actions = handle(
        "/llm-override trust me sk-ant-api03-" + "x" * 30,
        audit_dir,
        association="NONE",
        login="Mallory",
    )

    assert actions.reaction is None  # no reply to outsiders
    assert actions.path == "events/2026/10/16/feedback-rejected-7-mallory.jsonl"
    r = record(actions)
    assert (r["type"], r["command"], r["code"]) == (
        "feedback_rejected",
        "override",
        "not_a_collaborator",
    )
    assert "trust me" not in actions.records[0] and "sk-ant" not in actions.records[0]


def test_secrets_in_reasons_are_redacted(audit_dir: Path) -> None:
    actions = handle("/llm-fp cr-1705 see ghp_" + "A" * 36, audit_dir)
    assert "ghp_" not in record(actions)["reason"]


def test_comments_outside_prs_and_bad_logins_do_nothing(audit_dir: Path) -> None:
    assert handle("/llm-ack cr-1705", audit_dir, pr=False).records == []
    assert (
        handle("/llm-ack cr-1705", audit_dir, association="NONE", login="not a login").records == []
    )


# --- the sticky comment ---


COMMENT = """<!-- llm-gate:code-review -->
| Severity | ID | Location | Finding |
|---|---|---|---|
| 🔴 high **(blocking)** | `cr-1705` | `src/A.cs:15` | Off by one |
| 🟡 low | `cr-0001` | `src/A.cs:3` | Name |
"""


def test_mark_false_positive() -> None:
    marked = feedback.mark_false_positive(COMMENT, "cr-1705", "alice")
    assert marked is not None
    assert "| Off by one _(false positive: @alice)_ |" in marked
    assert "| Name |" in marked
    assert feedback.mark_false_positive(marked, "cr-1705", "alice") is None  # once
    assert feedback.mark_false_positive(COMMENT, "cr-ffff", "alice") is None


# --- overrides added by the feedback workflow ---


def test_a_bot_label_needs_a_collaborators_command() -> None:
    events = [
        {
            "event": "labeled",
            "label": {"name": "llm-override"},
            "actor": {"login": audit.WORKFLOW_BOT},
            "created_at": "2026-10-16T10:00:05Z",
        }
    ]

    def comment(login: str, association: str) -> dict[str, Any]:
        at = "2026-10-16T10:00:00Z"  # the command comes before the label it causes
        return {
            "user": {"login": login},
            "author_association": association,
            "body": "/llm-override hotfix",
            "created_at": at,
            "updated_at": at,
        }

    writers = {"alice"}
    found = audit.find_override(events, [comment("alice", "COLLABORATOR")], writers=writers)
    assert found == audit.OverrideRequest(by="alice", reason="hotfix")
    # COLLABORATOR without write access (a read or triage role) is not enough.
    reader = audit.find_override(events, [comment("bob", "COLLABORATOR")], writers=writers)
    assert isinstance(reader, str) and "write access" in reader
    # Without the writers list, a bot-added label is never honoured.
    assert isinstance(audit.find_override(events, [comment("alice", "OWNER")]), str)


# --- CLI ---


CHECKS = """\
defaults: {model: claude-test-model}
checks:
  code-review: {mode: blocking, fail_on: high}
"""


def test_cli_handle_writes_the_record_and_prints_actions(
    repo: Any,
    audit_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo.write("tools/llm-gate/checks.yaml", CHECKS)
    monkeypatch.chdir(repo.root)
    payload = tmp_path / "event.json"
    payload.write_text(json.dumps(event("/llm-fp cr-1705 by design")))
    out = tmp_path / "out"

    args = ["feedback", "handle", "--event", str(payload), "--audit-dir", str(audit_dir)]
    assert main([*args, "--out", str(out), "--permission", "admin"]) == 0

    actions = json.loads(capsys.readouterr().out)
    assert actions["recorded"] is True
    written = out / actions["path"]
    assert json.loads(written.read_text())["kind"] == "fp"


def test_cli_mark(
    repo: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo.write("tools/llm-gate/checks.yaml", CHECKS)
    monkeypatch.chdir(repo.root)
    body = tmp_path / "body.md"
    body.write_text(COMMENT)

    assert (
        main(["feedback", "mark", "--body-file", str(body), "--finding", "cr-1705", "--by", "a"])
        == 0
    )
    assert "_(false positive: @a)_" in capsys.readouterr().out
    assert (
        main(["feedback", "mark", "--body-file", str(body), "--finding", "cr-ffff", "--by", "a"])
        == 1
    )


def test_bot_logins_make_safe_file_names(audit_dir: Path) -> None:
    actions = handle("/llm-ack cr-1705", audit_dir, association="NONE", login="dependabot[bot]")
    assert actions.path == "events/2026/10/16/feedback-rejected-7-dependabot-bot-.jsonl"


@pytest.mark.parametrize("permission", ["read", "triage", None])
def test_collaborators_without_write_access_are_not_heard(
    audit_dir: Path, permission: str | None
) -> None:
    actions = handle("/llm-override trust me", audit_dir, permission=permission)
    assert not actions.recorded and actions.label is None and not actions.rerun
    assert record(actions)["code"] == "not_a_collaborator"

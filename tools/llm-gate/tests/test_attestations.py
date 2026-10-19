"""Release attestation predicates (ADR 0009): vuln-scan from grype JSON, llm-review from the audit
log."""

import json
from pathlib import Path
from typing import Any

import pytest

from llm_gate import attestations
from llm_gate.cli import main
from llm_gate.redact import REDACTED


def grype_report(
    arch: str, *severities: str, ignored: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "descriptor": {
            "name": "grype",
            "version": "0.120.1",
            "timestamp": "2026-10-20T08:00:00Z",
            "db": {"status": {"schemaVersion": "v6.1.10", "built": "2026-10-20T06:00:00Z"}},
        },
        "source": {
            "type": "image",
            "target": {"os": "linux", "architecture": arch, "manifestDigest": f"sha256:{arch}"},
        },
        "matches": [
            {"vulnerability": {"id": f"CVE-{i}", "severity": s}, "artifact": {"name": "libc6"}}
            for i, s in enumerate(severities)
        ],
    }
    if ignored is not None:
        report["ignoredMatches"] = ignored
    return report


def test_vuln_scan_counts_per_platform_and_lists_ignores() -> None:
    ignore = {
        "vulnerability": {"id": "GHSA-aaaa"},
        "artifact": {"name": "System.Text.Json", "version": "9.0.0"},
        "appliedIgnoreRules": [
            {"vulnerability": "GHSA-aaaa", "reason": "Not reachable. Expires 2026-12-31."}
        ],
    }
    predicate = attestations.vuln_scan(
        [
            grype_report("amd64", "Medium", "Medium", "Negligible", "Weird", ignored=[ignore]),
            grype_report("arm64", "Low", ignored=[ignore]),  # the same ignore: listed once
        ]
    )

    assert predicate["scanner"] == {
        "name": "grype",
        "version": "0.120.1",
        "db_schema": "v6.1.10",
        "db_built": "2026-10-20T06:00:00Z",
    }
    amd64, arm64 = predicate["results"]
    assert (amd64["platform"], amd64["manifest_digest"]) == ("linux/amd64", "sha256:amd64")
    assert amd64["counts"] == {
        "critical": 0,
        "high": 0,
        "medium": 2,
        "low": 0,
        "negligible": 1,
        "unknown": 1,
    }
    assert arm64["counts"]["low"] == 1
    assert predicate["ignored"] == [
        {
            "id": "GHSA-aaaa",
            "package": "System.Text.Json@9.0.0",
            "reason": "Not reachable. Expires 2026-12-31.",
        }
    ]


def test_vuln_scan_needs_a_report() -> None:
    with pytest.raises(ValueError, match="no grype reports"):
        attestations.vuln_scan([])


# --- llm-review ---

HEAD, OLD = "a" * 40, "b" * 40


def write_log(audit_dir: Path, *records: dict[str, Any]) -> Path:
    day = audit_dir / "events" / "2026" / "10" / "17"
    day.mkdir(parents=True, exist_ok=True)
    (day / "records.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records))
    return audit_dir


def gate_run(
    pr: int, check: str, verdict: str, *, head: str = HEAD, run: int = 1, **extra: Any
) -> dict[str, Any]:
    """A gate_run as the collector writes it, provenance fields included: `llm_review` validates
    what it reads from the branch now, and a record that is merely shaped like a verdict is
    exactly what must be refused."""
    return {
        "type": "gate_run",
        "ts": "2026-10-17T10:00:00Z",
        "pr": pr,
        "head_sha": head,
        "check": check,
        "engine": "agent",
        "model": "claude-sonnet-5-5",
        "prompt_file": f".claude/commands/llm-{check}.md",
        "prompt_sha256": "a" * 64,
        "config_sha256": "b" * 64,
        "gate_sha": "c" * 40,
        "diff_sha256": "d" * 64,
        "diff_bytes": 2048,
        "cache_hit": False,
        "exit_code": 0 if verdict in ("pass", "not_needed", "not_applicable") else 1,
        "started_at": "2026-10-17T09:59:00Z",
        "finished_at": "2026-10-17T10:00:00Z",
        "verdict": verdict,
        "blocking": check in ("code-review", "security-review"),
        "workflow_run_id": run,
        "run_attempt": 1,
        **extra,
    }


def triage_record(pr: int, *, head: str = HEAD, **extra: Any) -> dict[str, Any]:
    """A triage record as the collector writes it. The risk fields are required by the schema,
    which `llm_review` now applies to what it reads."""
    return {
        "type": "triage",
        "ts": "2026-10-17T09:58:00Z",
        "pr": pr,
        "head_sha": head,
        "rules_risk": "medium",
        "model_risk": "high",
        "reasons": ["changes CI or the gates"],
        "final_risk": "high",
        "ai_assisted": True,
        "checks_plan": ["code-review", "security-review"],
        **extra,
    }


def commit(
    pr: int | None, head: str | None = HEAD, merged_at: str = "2026-10-17T12:00:00Z"
) -> dict[str, Any]:
    return {"commit": "c" * 40, "pr": pr, "head_sha": head, "merged_at": merged_at}


def test_the_latest_run_on_the_merged_head_counts(tmp_path: Path) -> None:
    log = write_log(
        tmp_path,
        gate_run(1, "code-review", "fail", run=1),
        gate_run(1, "code-review", "pass", run=2, risk="medium"),
        gate_run(1, "code-review", "fail", head=OLD, run=3),  # an earlier head: ignored
        gate_run(1, "security-review", "fail", run=2, override_honoured=True),
        {
            "type": "override",
            "pr": 1,
            "head_sha": HEAD,
            "by": "alice",
            "checks": ["security-review"],
            "reason": "hotfix, token ghp_abcdefghijklmnopqrstuvwxyz0123456789",
        },
        triage_record(1, workflow_run_id=2),
    )

    predicate = attestations.llm_review([commit(1)], log, range_from="v0.2.0", range_to="v0.3.0")

    (pr,) = predicate["prs"]
    # The verdict stays in the label: "overridden" alone read as if nothing had failed.
    assert pr["checks"] == {"code-review": "pass", "security-review": "fail (overridden)"}
    assert (pr["risk"], pr["ai_assisted"]) == ("high", True)
    assert pr["overrides"][0]["by"] == "alice"
    assert REDACTED in pr["overrides"][0]["reason"]
    assert predicate["unreviewed"] == predicate["unverified"] == []
    assert predicate["range"] == {"from": "v0.2.0", "to": "v0.3.0"}


def test_unreviewed_and_unverified(tmp_path: Path) -> None:
    log = write_log(
        tmp_path,
        gate_run(2, "code-review", "skipped_no_key"),
        gate_run(2, "docs-drift", "skipped_no_key"),  # advisory: not a gap
        gate_run(3, "code-review", "pass", head=OLD),
        gate_run(4, "code-review", "pass", workflow_modified=True),
        {
            "type": "tamper_suspected",
            "pr": 4,
            "head_sha": HEAD,
            "ts": "2026-10-17T10:00:00Z",
            "artifact": "audit-9-1-code-review",
            "problems": ["unexpected field"],
        },
    )
    commits = [
        commit(None, None),
        commit(1, merged_at="2026-10-16T09:00:00Z"),  # before the first record
        commit(2),
        commit(3),
        commit(4),
    ]

    predicate = attestations.llm_review(commits, log, range_from=None, range_to="v0.1.0")

    assert predicate["unreviewed"] == [
        {"commit": "c" * 40, "reason": "no pull request"},
        {"number": 1, "reason": "merged before the audit log existed"},
        {"number": 2, "reason": "code-review: skipped_no_key"},
        {
            "number": 3,
            "reason": "no review record for the merged head (earlier heads were reviewed)",
        },
    ]
    assert predicate["unverified"] == [
        {"number": 4, "reason": "workflow_modified, tamper_suspected (1)"}
    ]
    notes = attestations.render_notes(predicate)
    assert "since the first commit" in notes
    assert "**Unreviewed**" in notes and "- #2: code-review: skipped_no_key" in notes
    assert "- `" + "c" * 40 + "`: no pull request" in notes
    assert "**Unverified**" in notes


def test_notes_without_gaps_have_no_gap_sections(tmp_path: Path) -> None:
    log = write_log(tmp_path, gate_run(1, "code-review", "pass", risk="low"))
    notes = attestations.render_notes(
        attestations.llm_review([commit(1)], log, range_from="v0.2.0", range_to="v0.3.0")
    )
    assert "| #1 | low | pass |" in notes
    assert "Unreviewed" not in notes and "Unverified" not in notes


def test_cli_attest(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture
) -> None:
    grype = tmp_path / "amd64.json"
    grype.write_text(json.dumps(grype_report("amd64", "High")))
    out = tmp_path / "vuln.json"
    assert main(["attest", "vuln-scan", "--grype", str(grype), "--out", str(out)]) == 0
    assert json.loads(out.read_text())["results"][0]["counts"]["high"] == 1

    log = write_log(tmp_path / "log", gate_run(1, "code-review", "pass"))
    commits = tmp_path / "commits.json"
    commits.write_text(json.dumps([commit(1)]))
    notes, review = tmp_path / "notes.md", tmp_path / "review.json"
    code = main(
        [
            "attest",
            "llm-review",
            "--from",
            "",
            "--to",
            "v0.1.0",
            "--commits",
            str(commits),
            "--audit-dir",
            str(log),
            "--out",
            str(review),
            "--notes",
            str(notes),
        ]
    )
    assert code == 0
    assert json.loads(review.read_text())["range"] == {"from": None, "to": "v0.1.0"}
    assert notes.read_text().startswith("## LLM review")
    capsys.readouterr()

    missing = tmp_path / "missing.json"
    assert main(["attest", "vuln-scan", "--grype", str(missing), "--out", str(out)]) == 2
    assert "attest vuln-scan: FileNotFoundError" in caplog.text


def test_error_verdicts_risk_fallback_and_bad_lines(tmp_path: Path) -> None:
    log = write_log(
        tmp_path,
        gate_run(1, "code-review", "error", risk="medium"),
        gate_run(1, "security-review", "pass", risk="medium"),
    )
    (log / "events" / "2026" / "10" / "17" / "broken.jsonl").write_text('not json\n["a list"]\n')

    predicate = attestations.llm_review([commit(1)], log, range_from=None, range_to="v1.0.0")

    (pr,) = predicate["prs"]
    assert pr["risk"] == "medium"  # no triage record: the gate runs' risk
    assert pr["ai_assisted"] is None
    assert predicate["unreviewed"] == [{"number": 1, "reason": "code-review: error"}]


def test_an_empty_release_or_log(tmp_path: Path) -> None:
    empty = attestations.llm_review([], tmp_path, range_from="v1.0.0", range_to="v1.0.1")
    assert (empty["prs"], empty["unreviewed"], empty["unverified"]) == ([], [], [])
    assert "0 pull request(s) since v1.0.0" in attestations.render_notes(empty)
    # No records at all: every PR predates the log.
    nothing = attestations.llm_review([commit(1)], tmp_path, range_from=None, range_to="v1.0.0")
    assert nothing["unreviewed"] == [{"number": 1, "reason": "merged before the audit log existed"}]


def test_override_reasons_are_quoted_in_the_notes_and_the_log_start_is_a_time(
    tmp_path: Path,
) -> None:
    log = write_log(
        tmp_path,
        gate_run(1, "code-review", "fail", override_honoured=True),
        {"type": "override", "pr": 1, "head_sha": HEAD, "by": "alice", "checks": ["code-review"],
         "reason": "see [this](https://example.com)\n`x`", "ts": "2026-10-17T10:00:00.5+00:00"},
        {"type": "triage", "pr": 9, "ts": "not a time"},  # unusable: ignored for the log's start
    )  # fmt: skip
    notes = attestations.render_notes(
        attestations.llm_review([commit(1)], log, range_from=None, range_to="v1.0.0")
    )
    # The release notes use the same helper as the PR comment, so a link in an override reason
    # can't make the notes fetch anything either (F029).
    assert "overridden by @alice: `see \\[this\\](https[:]//example.com) 'x'`" in notes
    # Merged before the first record, in a different but equal-meaning time format.
    early = attestations.llm_review(
        [commit(2, merged_at="2026-10-17T11:59:59+02:00")], log, range_from=None, range_to="v1"
    )
    assert early["unreviewed"][0]["reason"] == "merged before the audit log existed"


def test_a_partial_review_and_an_accepted_unreviewed_diff_are_both_listed(tmp_path: Path) -> None:
    """Whatever the review didn't see reaches the attestation (ADR 0002): files over the per-file
    cap, and a whole diff a human accepted unreviewed."""
    log = write_log(
        tmp_path,
        gate_run(
            1,
            "code-review",
            "pass",
            omitted_files=[{"path": "src/Api/Generated.pb.cs", "bytes": 300_000}],
        ),
        gate_run(1, "security-review", "error", override_honoured=True),
    )

    predicate = attestations.llm_review([commit(1)], log, range_from=None, range_to="v1.0.0")

    (pr,) = predicate["prs"]
    assert pr["checks"] == {
        "code-review": "pass, partial (1 file(s) omitted)",
        "security-review": "error (overridden)",
    }
    assert predicate["unreviewed"] == [
        {
            "number": 1,
            "reason": "code-review: pass, partial (1 file(s) omitted), "
            "security-review: error (overridden)",
        }
    ]


def test_a_planned_blocking_check_with_no_record_is_unreviewed(tmp_path: Path) -> None:
    """A failed artifact upload, or a collector that gave up mid-write, used to look like a clean
    release: the check was simply absent from the predicate (F027)."""
    log = write_log(
        tmp_path,
        triage_record(
            1,
            ts="2026-10-17T09:00:00Z",
            checks_plan=["code-review", "security-review", "docs-drift"],
        ),
        gate_run(1, "code-review", "pass"),
        gate_run(1, "docs-drift", "pass"),
    )
    blocking = {
        "low": frozenset(),
        "medium": frozenset(),
        "high": frozenset({"code-review", "security-review"}),
    }

    predicate = attestations.llm_review(
        [commit(1)], log, range_from=None, range_to="v1.0.0", blocking=blocking
    )

    assert predicate["unreviewed"] == [{"number": 1, "reason": "security-review: no record"}]
    # Without the levels, the attestation reports only what it has, as before.
    without = attestations.llm_review([commit(1)], log, range_from=None, range_to="v1.0.0")
    assert without["unreviewed"] == []
    # An advisory check the plan named is not a gap.
    assert "docs-drift" in predicate["prs"][0]["checks"]


def test_a_line_pushed_to_the_branch_cannot_claim_a_review(tmp_path: Path) -> None:
    """The collector validates a PR's artifact before committing it; nothing validated what this
    reader found on the branch, which takes a push from anyone with write access and from any
    workflow holding contents: write. A bare {"type": "gate_run", pr, head_sha, verdict} used to
    count as a verdict, so one appended line turned an unreviewed PR into a reviewed one inside a
    signed predicate."""
    log = write_log(
        tmp_path,
        triage_record(1),
        {"type": "gate_run", "pr": 1, "head_sha": HEAD, "check": "code-review", "verdict": "pass"},
        {"type": "gate_run", "pr": 1, "head_sha": HEAD, "check": "security-review",
         "verdict": "pass", "blocking": True},
    )  # fmt: skip

    predicate = attestations.llm_review([commit(1)], log, range_from=None, range_to="v1.0.0")

    # Neither line is a record, so the PR is reported as what it is: unreviewed.
    assert predicate["unreviewed"] == [
        {"number": 1, "reason": "no review record for the merged head"}
    ]
    # And the refusal is visible rather than silent.
    assert predicate["rejected_records"] == 2


def test_a_lowered_risk_is_named_in_the_pull_requests_entry(tmp_path: Path) -> None:
    """At low risk nothing blocks, so `/llm-risk low` is a full pass of both blocking checks. The
    entry showed `risk: low` with no sign that a person put it there, because a risk_override is a
    different record type from an override and only the latter was collected."""
    log = write_log(
        tmp_path,
        triage_record(1, final_risk="low", checks_plan=["code-review"]),
        gate_run(1, "code-review", "pass"),
        {"type": "risk_override", "ts": "2026-10-17T09:59:00Z", "pr": 1, "head_sha": HEAD,
         "by": "alice", "from": "high", "to": "low",
         "reason": "docs only, token ghp_abcdefghijklmnopqrstuvwxyz0123456789"},
    )  # fmt: skip

    (pr,) = attestations.llm_review([commit(1)], log, range_from=None, range_to="v1.0.0")["prs"]

    assert pr["risk"] == "low"
    (lowered,) = pr["risk_overrides"]
    assert (lowered["by"], lowered["from"], lowered["to"]) == ("alice", "high", "low")
    # The reason is a person's text in a signed predicate, so it is redacted like every other.
    assert REDACTED in lowered["reason"]
    assert "ghp_" not in lowered["reason"]

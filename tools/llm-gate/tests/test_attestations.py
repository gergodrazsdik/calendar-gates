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
    return {
        "type": "gate_run",
        "ts": "2026-10-17T10:00:00Z",
        "pr": pr,
        "head_sha": head,
        "check": check,
        "verdict": verdict,
        "blocking": check in ("code-review", "security-review"),
        "workflow_run_id": run,
        "run_attempt": 1,
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
        {
            "type": "triage",
            "pr": 1,
            "head_sha": HEAD,
            "workflow_run_id": 2,
            "final_risk": "high",
            "ai_assisted": True,
        },
    )

    predicate = attestations.llm_review([commit(1)], log, range_from="v0.2.0", range_to="v0.3.0")

    (pr,) = predicate["prs"]
    assert pr["checks"] == {"code-review": "pass", "security-review": "overridden"}
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
        {"type": "tamper_suspected", "pr": 4, "head_sha": HEAD, "ts": "2026-10-17T10:00:00Z"},
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


def test_cli_attest(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
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

    assert (
        main(["attest", "vuln-scan", "--grype", str(tmp_path / "missing.json"), "--out", str(out)])
        == 2
    )

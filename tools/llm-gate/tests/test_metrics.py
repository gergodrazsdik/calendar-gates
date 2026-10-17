import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from llm_gate import metrics

NOW = datetime(2026, 10, 20, tzinfo=UTC)


def run(pr: int, check: str = "code-review", **fields: Any) -> dict[str, Any]:
    return {
        "type": "gate_run",
        "ts": "2026-10-16T10:05:00Z",
        "pr": pr,
        "check": check,
        "engine": "agent",
        "model": "claude-sonnet-5-5",
        "blocking": True,
        "verdict": "pass",
        "pr_event_at": "2026-10-16T10:00:00Z",
        "finished_at": "2026-10-16T10:02:00Z",
        "cost_usd": 0.05,
        "findings": [],
        **fields,
    }


def pr(number: int, merged_at: str = "2026-10-17T00:00:00Z") -> dict[str, Any]:
    return {"number": number, "merged_at": merged_at}


def compute(records: list[dict[str, Any]], prs: list[dict[str, Any]]) -> metrics.Report:
    return metrics.compute(
        records, prs, blocking_checks=["code-review", "security-review"], now=NOW, since_days=30
    )


def test_coverage_counts_merged_prs_where_every_blocking_check_decided() -> None:
    records = [
        run(1),
        run(1, "security-review", verdict="not_applicable"),
        run(2),
        run(2, "security-review", verdict="skipped_no_key"),  # no decision
        run(3),
    ]
    report = compute(records, [pr(1), pr(2), pr(3), pr(4, "2026-01-01T00:00:00Z")])

    assert report.merged_prs == 3  # #4 was merged before the audit log started
    assert report.coverage == 1 / 3
    assert report.uncovered == [2, 3]


def test_false_positive_rates_per_check_and_severity() -> None:
    findings = [{"id": "cr-0001", "severity": "high"}, {"id": "cr-0002", "severity": "low"}]
    records = [
        run(1, findings=findings),
        run(1, findings=findings),  # a rerun: the same findings count once
        {
            "type": "feedback",
            "ts": "2026-10-16T11:00:00Z",
            "pr": 1,
            "finding_id": "cr-0001",
            "kind": "fp",
        },
        {
            "type": "feedback",
            "ts": "2026-10-16T11:00:00Z",
            "pr": 1,
            "finding_id": "cr-0002",
            "kind": "ack",
        },
    ]
    report = compute(records, [pr(1)])

    assert report.fp_by_check == {"code-review": (1, 1, 2)}
    assert report.fp_by_severity == {"high": (1, 1), "low": (0, 1)}


def test_the_latest_feedback_on_a_finding_wins_by_time() -> None:
    findings = [{"id": "cr-0001", "severity": "high"}]

    def feedback(kind: str, ts: str) -> dict[str, Any]:
        return {"type": "feedback", "ts": ts, "pr": 1, "finding_id": "cr-0001", "kind": kind}

    # Out of time order, as record files can sort (feedback-<comment id>.jsonl).
    acked = compute(
        [
            run(1, findings=findings),
            feedback("ack", "2026-10-17T18:00:00Z"),
            feedback("fp", "2026-10-16T19:00:00Z"),
            feedback("fp", "2026-10-16T20:00:00Z"),
        ],
        [pr(1)],
    )
    assert acked.fp_by_check == {"code-review": (0, 1, 1)}
    assert acked.fp_by_severity == {"high": (0, 1)}

    marked = compute(
        [
            run(1, findings=findings),
            feedback("fp", "2026-10-17T09:00:00Z"),
            feedback("ack", "2026-10-16T09:00:00Z"),
        ],
        [pr(1)],
    )
    assert marked.fp_by_check == {"code-review": (1, 0, 1)}


def test_overrides_turnaround_and_cost() -> None:
    records = [
        run(1, verdict="fail", override_honoured=True),
        run(2, verdict="fail"),
        run(3, cost_usd=None),  # a cache hit
    ]
    report = compute(records, [pr(1), pr(2), pr(3)])

    assert report.override_rate == (1, 2)
    assert report.turnaround["code-review"] == (120.0, 120.0, 3)
    assert report.cost_total == 0.10
    assert report.cost_by_engine == {"agent / claude-sonnet-5-5": 0.10}


def test_triage_and_integrity_counts() -> None:
    records = [
        run(1, workflow_modified=True),
        {"type": "triage", "pr": 1, "ts": "2026-10-16T09:00:00Z", "final_risk": "medium"},
        {
            "type": "triage",
            "pr": 1,
            "ts": "2026-10-16T10:00:00Z",
            "final_risk": "high",
            "ai_assisted": True,
        },
        {
            "type": "triage",
            "pr": 2,
            "ts": "2026-10-16T10:00:00Z",
            "final_risk": "low",
            "ai_assisted": False,
        },
        {"type": "tamper_suspected", "ts": "2026-10-16T10:00:00Z"},
        {"type": "feedback_rejected", "ts": "2026-10-16T10:00:00Z"},
        {"type": "risk_override", "ts": "2026-10-16T10:00:00Z"},
    ]
    report = compute(records, [])

    assert report.triage == {"high": 1, "low": 1}  # each PR once, its latest triage
    assert report.ai_assisted == (1, 2)
    assert (report.tamper, report.unverified, report.rejected_feedback, report.risk_overrides) == (
        1,
        1,
        1,
        1,
    )


def test_render_shows_every_section_and_no_data_where_empty() -> None:
    report = compute([run(1, findings=[{"id": "cr-0001", "severity": "high"}])], [pr(1)])
    text = metrics.render(report, generated=NOW)

    for heading in (
        "Coverage",
        "turnaround",
        "False positives",
        "Overrides",
        "Cost",
        "Triage",
        "Eval trend",
        "Integrity",
    ):
        assert heading in text
    assert "_no data yet_. Manual risk changes: 0." in text
    assert "| code-review | 1 | 0 | 0 | 0% | - |" in text


def test_eval_runs_come_from_the_last_report(tmp_path: Path) -> None:
    run_data = [
        {
            "check": "code-review",
            "engine": "agent",
            "model": "m",
            "prompt_sha256": "ab" * 32,
            "metrics": {"recall": 1.0},
        }
    ]
    (tmp_path / "code-review-abc.json").write_text(json.dumps(run_data))
    (tmp_path / "last.json").write_text(json.dumps(["../../escape.json", "code-review-abc.json"]))

    runs = metrics.load_eval_runs(tmp_path)

    assert [r["check"] for r in runs] == ["code-review"]
    report = metrics.compute([], [], blocking_checks=[], now=NOW, eval_runs=runs)
    assert "| code-review | agent / m | `abababab` | 100% |" in metrics.render(
        report, generated=NOW
    )


def test_load_records_skips_broken_lines(tmp_path: Path) -> None:
    events = tmp_path / "events" / "2026"
    events.mkdir(parents=True)
    (events / "a.jsonl").write_text(json.dumps(run(1)) + "\nnot json\n\n")
    assert len(metrics.load_records(tmp_path)) == 1

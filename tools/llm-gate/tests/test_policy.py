from pathlib import Path

import pytest
from conftest import finding, make_check, result

from llm_gate.models import Severity
from llm_gate.policy import (
    EXIT_ERROR,
    EXIT_FINDINGS,
    EXIT_PASS,
    ErrorKind,
    Verdict,
    decide,
)


@pytest.mark.parametrize("override", [False, True])
@pytest.mark.parametrize("mode", ["blocking", "advisory"])
@pytest.mark.parametrize("severity", list(Severity))
def test_severity_mode_override_matrix(
    tmp_path: Path, severity: Severity, mode: str, override: bool
) -> None:
    fail_on = Severity.HIGH if mode == "blocking" else None
    check = make_check(tmp_path, mode=mode, fail_on=fail_on)

    decision = decide(check, result=result(finding(severity)), override=override)

    blocks = mode == "blocking" and severity.at_least(Severity.HIGH)
    if not blocks:
        assert (decision.verdict, decision.exit_code) == (Verdict.PASS, EXIT_PASS)
        assert decision.blocking == ()
    elif override:
        assert (decision.verdict, decision.exit_code) == (Verdict.OVERRIDDEN, EXIT_PASS)
        assert len(decision.blocking) == 1
    else:
        assert (decision.verdict, decision.exit_code) == (Verdict.FAIL, EXIT_FINDINGS)
        assert len(decision.blocking) == 1


def test_only_findings_at_or_above_the_threshold_block(tmp_path: Path) -> None:
    check = make_check(tmp_path, fail_on=Severity.MEDIUM)
    review = result(*(finding(s) for s in Severity))

    decision = decide(check, result=review)

    assert sorted((f.severity for f in decision.blocking), key=lambda s: s.rank) == [
        Severity.MEDIUM,
        Severity.HIGH,
        Severity.CRITICAL,
    ]
    assert decision.reason == "3 finding(s) at or above medium"


def test_no_findings_passes(tmp_path: Path) -> None:
    decision = decide(make_check(tmp_path), result=result())

    assert (decision.verdict, decision.exit_code) == (Verdict.PASS, EXIT_PASS)


@pytest.mark.parametrize(
    ("mode", "on_error", "exit_code"),
    [
        ("blocking", "fail", EXIT_ERROR),  # fail closed
        ("blocking", "pass", EXIT_PASS),
        ("advisory", "fail", EXIT_PASS),  # advisory checks never fail
        ("advisory", "pass", EXIT_PASS),
    ],
)
def test_errors_follow_on_error(tmp_path: Path, mode: str, on_error: str, exit_code: int) -> None:
    fail_on = Severity.HIGH if mode == "blocking" else None
    check = make_check(tmp_path, mode=mode, fail_on=fail_on, on_error=on_error)

    decision = decide(check, error="API down")

    assert decision.verdict is Verdict.ERROR
    assert decision.exit_code == exit_code
    assert decision.reason.startswith("API down")


def test_override_does_not_hide_an_engine_failure(tmp_path: Path) -> None:
    """A broken or refusing gate is not an approval: only the size cap is overridable."""
    decision = decide(make_check(tmp_path), error="API down", override=True)

    assert (decision.verdict, decision.exit_code) == (Verdict.ERROR, EXIT_ERROR)
    assert decision.override_honoured is False


@pytest.mark.parametrize(
    ("kind", "override", "exit_code", "honoured"),
    [
        (ErrorKind.TOO_LARGE, True, EXIT_PASS, True),  # accepted unreviewed, with a reason
        (ErrorKind.TOO_LARGE, False, EXIT_ERROR, False),
        (ErrorKind.ENGINE, True, EXIT_ERROR, False),  # the gate broke; re-run it
        (ErrorKind.ENGINE, False, EXIT_ERROR, False),
    ],
)
def test_only_a_size_error_is_overridable(
    tmp_path: Path, kind: ErrorKind, override: bool, exit_code: int, honoured: bool
) -> None:
    decision = decide(
        make_check(tmp_path), error="diff too large: 488 KB", error_kind=kind, override=override
    )

    # The verdict stays `error` either way: nothing was reviewed.
    assert decision.verdict is Verdict.ERROR
    assert decision.exit_code == exit_code
    assert decision.override_honoured is honoured
    if honoured:
        assert "accepted unreviewed by override" in decision.reason


@pytest.mark.parametrize("kind", list(ErrorKind))
def test_an_advisory_check_passes_on_any_error_without_an_override(
    tmp_path: Path, kind: ErrorKind
) -> None:
    check = make_check(tmp_path, mode="advisory", fail_on=None)

    decision = decide(check, error="whatever", error_kind=kind)

    assert (decision.verdict, decision.exit_code) == (Verdict.ERROR, EXIT_PASS)
    assert decision.override_honoured is False


def test_an_honoured_override_of_findings_is_recorded(tmp_path: Path) -> None:
    decision = decide(
        make_check(tmp_path), result=result(finding(Severity.CRITICAL)), override=True
    )

    assert (decision.verdict, decision.exit_code) == (Verdict.OVERRIDDEN, EXIT_PASS)
    assert decision.override_honoured is True


def test_not_applicable_passes(tmp_path: Path) -> None:
    decision = decide(make_check(tmp_path), not_applicable="no relevant files")

    assert (decision.verdict, decision.exit_code) == (Verdict.NOT_APPLICABLE, EXIT_PASS)

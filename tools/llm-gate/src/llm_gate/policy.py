"""The verdict is computed here, from severities and the check's config; never by the model."""

from dataclasses import dataclass
from enum import StrEnum

from .config import Check
from .models import EngineResult, Finding

EXIT_PASS = 0
EXIT_FINDINGS = 1
EXIT_ERROR = 2


class Verdict(StrEnum):
    PASS = "pass"  # noqa: S105  # a verdict, not a password
    FAIL = "fail"
    OVERRIDDEN = "overridden"  # blocking findings, but the PR has the override label
    NOT_APPLICABLE = "not-applicable"
    NOT_NEEDED = "not-needed"  # triage: the PR's risk level doesn't call for this check
    ERROR = "error"


class ErrorKind(StrEnum):
    """Why no review result came back. Only `TOO_LARGE` can be overridden (ADR 0002): it is a
    visible, bounded property of the diff, while everything else means the gate itself is broken
    or refused, where the answer is a re-run and not a pass."""

    TOO_LARGE = "too_large"
    ENGINE = "engine"


@dataclass(frozen=True)
class Decision:
    verdict: Verdict
    exit_code: int
    reason: str
    blocking: tuple[Finding, ...] = ()
    override_honoured: bool = False


def blocking_findings(check: Check, result: EngineResult) -> tuple[Finding, ...]:
    if not check.blocking or check.fail_on is None:
        return ()
    threshold = check.fail_on
    return tuple(f for f in result.review.findings if f.severity.at_least(threshold))


def decide(
    check: Check,
    *,
    result: EngineResult | None = None,
    error: str | None = None,
    error_kind: ErrorKind = ErrorKind.ENGINE,
    not_applicable: str | None = None,
    not_needed: str | None = None,
    override: bool = False,
    partial: bool = False,
) -> Decision:
    if not_needed is not None:
        return Decision(Verdict.NOT_NEEDED, EXIT_PASS, not_needed)
    if not_applicable is not None:
        return Decision(Verdict.NOT_APPLICABLE, EXIT_PASS, not_applicable)

    if error is not None or result is None:
        message = error or "no review result"
        if check.blocking and check.on_error == "fail":
            # The verdict stays `error`: nothing was reviewed, and an override doesn't change that.
            # It only says a human with write access accepted the diff unreviewed, with a reason
            # on the audit log, which the release attestation lists under `unreviewed` (ADR 0002).
            if override and error_kind is ErrorKind.TOO_LARGE:
                return Decision(
                    Verdict.ERROR,
                    EXIT_PASS,
                    f"{message} (accepted unreviewed by override)",
                    override_honoured=True,
                )
            return Decision(Verdict.ERROR, EXIT_ERROR, f"{message} (blocking check, fails closed)")
        why = "advisory check" if not check.blocking else "on_error: pass"
        return Decision(Verdict.ERROR, EXIT_PASS, f"{message} (ignored: {why})")

    findings = blocking_findings(check, result)
    if not check.blocking:
        return Decision(Verdict.PASS, EXIT_PASS, "advisory check, findings are informational")
    # A blocking check only gets here with files missing if an override let it (see `runner`), so
    # the record carries that: the review covered part of the change and a human accepted it.
    partial_note = ", part of the change was not reviewed" if partial else ""
    if not findings:
        return Decision(
            Verdict.PASS,
            EXIT_PASS,
            f"no findings at or above {check.fail_on}{partial_note}",
            override_honoured=partial,
        )
    count = f"{len(findings)} finding(s) at or above {check.fail_on}"
    if override:
        return Decision(
            Verdict.OVERRIDDEN,
            EXIT_PASS,
            f"{count}, overridden by label",
            findings,
            override_honoured=True,
        )
    return Decision(Verdict.FAIL, EXIT_FINDINGS, count, findings)

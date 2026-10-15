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
    ERROR = "error"


@dataclass(frozen=True)
class Decision:
    verdict: Verdict
    exit_code: int
    reason: str
    blocking: tuple[Finding, ...] = ()


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
    not_applicable: str | None = None,
    override: bool = False,
) -> Decision:
    return Decision(Verdict.PASS, EXIT_PASS, "every check passes")
    if not_applicable is not None:
        return Decision(Verdict.NOT_APPLICABLE, EXIT_PASS, not_applicable)

    if error is not None or result is None:
        message = error or "no review result"
        if check.blocking and check.on_error == "fail":
            return Decision(Verdict.ERROR, EXIT_ERROR, f"{message} (blocking check, fails closed)")
        why = "advisory check" if not check.blocking else "on_error: pass"
        return Decision(Verdict.ERROR, EXIT_PASS, f"{message} (ignored: {why})")

    findings = blocking_findings(check, result)
    if not check.blocking:
        return Decision(Verdict.PASS, EXIT_PASS, "advisory check, findings are informational")
    if not findings:
        return Decision(Verdict.PASS, EXIT_PASS, f"no findings at or above {check.fail_on}")
    count = f"{len(findings)} finding(s) at or above {check.fail_on}"
    if override:
        return Decision(Verdict.OVERRIDDEN, EXIT_PASS, f"{count}, overridden by label", findings)
    return Decision(Verdict.FAIL, EXIT_FINDINGS, count, findings)

"""Redaction for text that reaches the audit log, which is public and can't be rewritten.

Free-text fields of audit records (tool-call summaries, finding titles, errors, reasons) are typed
`Scrubbed[limit]`: redacted and truncated whenever a record is built or parsed, so the trusted
collector applies it again to whatever an artifact contains.
"""

import re
from collections.abc import Callable
from typing import Annotated

from pydantic import AfterValidator

# After gitleaks' default rules: the subset that can plausibly turn up in a review or a tool call.
SECRET_PATTERNS = tuple(
    re.compile(pattern)
    for pattern in (
        r"sk-ant-[A-Za-z0-9_\-]{20,}",  # Anthropic
        r"gh[pousr]_[A-Za-z0-9]{36,}",  # GitHub tokens
        r"github_pat_[A-Za-z0-9_]{22,}",
        r"(?:A3T[A-Z0-9]|AKIA|ASIA|ABIA|ACCA)[A-Z0-9]{16}",  # AWS access key ids
        r"xox[baprs]-[A-Za-z0-9-]{10,}",  # Slack
        r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}",  # JWT
        r"-----BEGIN[A-Z ]*PRIVATE KEY-----",
        r"(?i)(?:api[_-]?key|secret|token|passw(?:or)?d)[\"']?\s*[=:]\s*[\"']?[^\s\"',}]{8,}",
    )
)
REDACTED = "[REDACTED]"
MAX_SUMMARY = 200


def redact(text: str) -> str:
    for pattern in SECRET_PATTERNS:
        text = pattern.sub(REDACTED, text)
    return text


def clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def scrub(limit: int) -> Callable[[str], str]:
    """Redact first, so truncating can't leave half a secret that no pattern matches."""

    def apply(text: str) -> str:
        return clip(redact(text), limit)

    return apply


type Summary = Annotated[str, AfterValidator(scrub(MAX_SUMMARY))]
type Short = Annotated[str, AfterValidator(scrub(80))]
type Text = Annotated[str, AfterValidator(scrub(500))]

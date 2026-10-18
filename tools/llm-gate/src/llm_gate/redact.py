"""Redaction for text that leaves the gate: the audit log, and anything published on a PR.

Free-text fields of audit records (tool-call summaries, finding titles, errors, reasons) are typed
`Scrubbed[limit]`: redacted and truncated whenever a record is built or parsed, so the trusted
collector applies it again to whatever an artifact contains.

The rendered review goes through `safe_text` (or `inert` for a single line). A review can be
steered by text in the files it reviews, so what it writes is treated like any other untrusted
string before it reaches a public comment or job summary: secrets scrubbed, and the markup that
turns text into a request to somebody else's server defanged (F003, F029).
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


# Markdown and HTML that make text do something: a link or an image fetches a URL (GitHub proxies
# images through camo, so an image needs no click at all), a tag can open an element the rest of
# the comment lives inside, and a backtick can close a code span the renderer opened.
_MARKUP = str.maketrans({"[": "\\[", "]": "\\]", "<": "&lt;", ">": "&gt;", "`": "'"})
_URL = re.compile(r"\b(https?|ftp|data)://", re.IGNORECASE)


def escape_markup(text: str) -> str:
    """Leave the words, take away the markup. GitHub autolinks a bare URL, so the scheme is broken
    with a zero-width-free marker a reader can still make sense of."""
    return _URL.sub(lambda m: f"{m.group(1)}[:]//", text.translate(_MARKUP))


def safe_text(text: str, limit: int = 2000) -> str:
    """Model-written prose for a public sink: defanged, redacted, clipped. Newlines survive, so a
    finding's detail is still a paragraph a person can read.

    Escaping runs before redaction so the marker it inserts isn't escaped itself; no secret format
    contains the characters it touches. Clipping runs last, because a cut in the middle of a secret
    would leave a remainder no pattern matches.
    """
    return clip(redact(escape_markup(text)), limit)


def inert(text: str, limit: int = 200) -> str:
    """Model- or comment-written text for one line of a summary: `safe_text`, flattened to a single
    line and wrapped in a code span, so it can't add structure either."""
    flat = " ".join(safe_text(text, limit).split())
    return f"`{flat}`"

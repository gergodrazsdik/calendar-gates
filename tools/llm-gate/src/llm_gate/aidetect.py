"""AI-assisted change detection (docs/PLAN-v2.md 17.1): commit trailers, PR body markers, branch
names, as configured in checks.yaml `ai_markers`.

The markers are self-declared: AGENTS.md asks agents to add them and Claude Code does by default,
but nothing proves a commit *wasn't* AI-assisted. A transparency signal for triage and the
metrics, not enforcement (ADR 0008).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from fnmatch import fnmatchcase
from typing import Any

from .config import AiMarkers


@dataclass(frozen=True)
class AiDetection:
    ai_commits: int
    total_commits: int
    pr_body: bool
    branch: bool

    @property
    def assisted(self) -> bool:
        return self.ai_commits > 0 or self.pr_body or self.branch

    @property
    def matched(self) -> list[str]:
        """Which kinds of marker matched, for the triage reasons (fixed text only)."""
        found = []
        if self.ai_commits:
            found.append(f"AI trailers in {self.ai_commits}/{self.total_commits} commit(s)")
        if self.pr_body:
            found.append("AI marker in the PR description")
        if self.branch:
            found.append("AI branch name")
        return found


def _trailer_lines(message: str) -> list[str]:
    """The message's last paragraph, where git trailers live."""
    paragraphs = [p for p in message.replace("\r\n", "\n").strip().split("\n\n") if p.strip()]
    return [line.strip() for line in paragraphs[-1].splitlines()] if len(paragraphs) > 1 else []


def commit_is_ai(message: str, markers: AiMarkers) -> bool:
    lines = [line.casefold() for line in _trailer_lines(message)]
    return any(line.startswith(m.casefold()) for m in markers.trailers for line in lines)


def commit_messages(commits: Sequence[Mapping[str, Any]]) -> list[str]:
    """Messages from `gh api repos/R/pulls/N/commits` objects (or plain strings)."""
    messages: list[str] = []
    for commit in commits:
        if isinstance(commit, str):
            messages.append(commit)
        else:
            messages.append(str((commit.get("commit") or {}).get("message") or ""))
    return messages


def detect(
    messages: Sequence[str], pr_body: str | None, head_ref: str | None, markers: AiMarkers
) -> AiDetection:
    body = pr_body or ""
    return AiDetection(
        ai_commits=sum(1 for m in messages if commit_is_ai(m, markers)),
        total_commits=len(messages),
        pr_body=any(marker in body for marker in markers.pr_body),
        branch=bool(head_ref) and any(fnmatchcase(head_ref or "", b) for b in markers.branches),
    )

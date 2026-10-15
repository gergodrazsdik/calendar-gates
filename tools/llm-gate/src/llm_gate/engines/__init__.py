"""Engines turn a review request into an EngineResult. Both use the same prompt file."""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ..config import Check
from ..diff import Diff
from ..models import EngineResult


class EngineError(Exception):
    """The engine could not produce a review (API error, refusal, truncation, no output)."""


@dataclass(frozen=True)
class ReviewRequest:
    check: Check
    prompt: str  # prompt body without frontmatter, $ARGUMENTS not yet substituted
    diff: Diff
    diff_path: Path  # the diff written to disk, for engines that read files
    repo_root: Path

    @property
    def diff_ref(self) -> str:
        """The diff file as a repository-relative path (what $ARGUMENTS becomes)."""
        try:
            return self.diff_path.relative_to(self.repo_root).as_posix()
        except ValueError:
            return str(self.diff_path)


class Engine(Protocol):
    name: str

    def review(self, request: ReviewRequest) -> EngineResult: ...

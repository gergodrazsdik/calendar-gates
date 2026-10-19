"""Engines turn a review request into an EngineResult. Both use the same prompt file."""

from collections.abc import Mapping
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

    def request_shape(self, check: Check) -> Mapping[str, object]:
        """Everything besides prompt, model and diff that decides what the engine asks for.

        This goes into the cache key. Without it the key was
        `[version, check, engine, model, prompt, diff]`, so a change to `max_turns`, `budget_usd`,
        the output schema or the reviewer's tool list hit every cached entry and reproduced the
        stored answer exactly -- and `llm-eval` compares against a baseline, so a PR that halved
        `max_turns` or emptied the read-only tool list, changing no prompt, scored as if nothing
        had happened (F012, F139). Each engine declares its own, so a new option that shapes the
        request is covered by whoever adds it rather than by remembering to edit a list here.
        """
        ...

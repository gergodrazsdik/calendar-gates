import os
import subprocess
from collections.abc import Callable, Iterator, Mapping
from dataclasses import replace
from pathlib import Path

import pytest

from llm_gate.config import Check
from llm_gate.engines import EngineError, ReviewRequest
from llm_gate.models import EngineResult, Finding, Review, Severity, Usage

PROMPT = """---
description: test prompt
---

Review $ARGUMENTS for bugs.
"""


@pytest.fixture(autouse=True)
def hermetic_git(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test repositories ignore the developer's git config (signing, hooks, aliases), as in CI."""
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for key, value in {
        "GIT_AUTHOR_NAME": "Test",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "Test",
        "GIT_COMMITTER_EMAIL": "test@example.com",
    }.items():
        monkeypatch.setenv(key, value)


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout


class Repo:
    def __init__(self, root: Path) -> None:
        self.root = root

    def write(self, path: str, text: str) -> None:
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")

    def write_bytes(self, path: str, data: bytes) -> None:
        """For the files a repository really holds that are not text: images, fonts, archives."""
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    def commit(self, message: str) -> None:
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", message)


@pytest.fixture
def repo(tmp_path: Path) -> Iterator[Repo]:
    """A repository with a `main` branch (one commit) and a checked-out `feature` branch."""
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    r = Repo(root)
    for name in ("code-review", "security-review", "docs-drift", "api-contract"):
        r.write(f".claude/commands/llm-{name}.md", PROMPT)
    r.write("src/Api/Endpoints/Week.cs", "class Week {}\n")
    r.write("README.md", "# test\n")
    r.write(".gitignore", ".llm-gate/\n")  # as in the real repository
    r.commit("base")
    git(root, "switch", "-q", "-c", "feature")
    yield r


def make_check(tmp_path: Path, **overrides: object) -> Check:
    prompt = tmp_path / "llm-code-review.md"
    if not prompt.exists():
        prompt.write_text(PROMPT, encoding="utf-8")
    check = Check(
        name="code-review",
        mode="blocking",
        fail_on=Severity.HIGH,
        engine="api",
        model="claude-sonnet-5-5",
        paths=None,
        max_diff_kb=200,
        max_file_kb=64,
        trimmable_paths=("**/*.pb.cs", "**/Migrations/**"),
        budget_usd=0.5,
        max_turns=30,
        on_error="fail",
        prompt_path=prompt,
    )
    return replace(check, **overrides)  # type: ignore[arg-type]


def finding(severity: Severity, file: str = "src/a.cs", line: int | None = 10) -> Finding:
    return Finding(
        severity=severity,
        category="off-by-one",
        file=file,
        line=line,
        title=f"{severity} problem",
        detail="Something is wrong.",
        suggestion=None,
    )


def result(*findings: Finding, engine: str = "api") -> EngineResult:
    return EngineResult(
        engine=engine,
        model="claude-sonnet-5-5",
        review=Review(summary="A change.", findings=list(findings)),
        duration_ms=1234,
        usage=Usage(input_tokens=100, output_tokens=50, cost_usd=0.001, cost_estimated=True),
    )


class FakeEngine:
    """Records requests; returns a fixed result or raises a fixed error."""

    def __init__(
        self,
        name: str = "api",
        outcome: EngineResult | EngineError | Callable[[ReviewRequest], EngineResult] | None = None,
    ) -> None:
        self.name = name
        self.outcome = result() if outcome is None else outcome
        self.requests: list[ReviewRequest] = []

    def request_shape(self, check: Check) -> Mapping[str, object]:
        # Mirrors what the real engines expose: enough that a change to a check's limits still
        # changes the cache key in tests.
        return {"max_turns": check.max_turns, "budget_usd": check.budget_usd}

    def review(self, request: ReviewRequest) -> EngineResult:
        self.requests.append(request)
        outcome = self.outcome
        if isinstance(outcome, EngineError):
            raise outcome
        if isinstance(outcome, EngineResult):
            return outcome.model_copy(update={"engine": self.name})
        return outcome(request)

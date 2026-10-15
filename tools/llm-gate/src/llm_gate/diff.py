"""The change under review: `git diff --merge-base <base> HEAD`, minus generated files."""

import subprocess
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

# Noise for a reviewer and expensive in tokens. Glob pathspecs, so `**/` matches any directory.
EXCLUDES = (
    "**/*.lock",  # uv.lock and friends
    "**/packages.lock.json",
    "**/*.Designer.cs",
    "**/*.g.cs",
    "**/*.generated.cs",
    "**/*.min.js",
)


class DiffError(Exception):
    pass


@dataclass(frozen=True)
class Diff:
    base: str
    text: str
    files: tuple[str, ...]

    @property
    def size_bytes(self) -> int:
        return len(self.text.encode("utf-8"))


def git(repo_root: Path, *args: str) -> str:
    try:
        completed = subprocess.run(
            ["git", *args], cwd=repo_root, check=True, capture_output=True, text=True
        )
    except subprocess.CalledProcessError as error:
        raise DiffError(f"git {' '.join(args)} failed: {error.stderr.strip()}") from error
    return completed.stdout


def repo_root(start: Path) -> Path:
    return Path(git(start, "rev-parse", "--show-toplevel").strip())


def merge_base_diff(root: Path, base: str) -> Diff:
    """Committed changes on HEAD since it branched off `base` (uncommitted work is not included)."""
    pathspec = ["--", ".", *(f":(exclude,glob){pattern}" for pattern in EXCLUDES)]
    text = git(root, "diff", "--no-color", "--no-ext-diff", "--merge-base", base, "HEAD", *pathspec)
    names = git(root, "diff", "--name-only", "--merge-base", base, "HEAD", *pathspec)
    return Diff(base=base, text=text, files=tuple(names.splitlines()))


def touches(files: Iterable[str], patterns: Iterable[str]) -> bool:
    """True if any changed file matches any of the `paths:` globs of a check."""
    patterns = tuple(patterns)
    return any(PurePosixPath(file).full_match(pattern) for file in files for pattern in patterns)

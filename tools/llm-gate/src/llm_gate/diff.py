"""The change under review: `git diff --merge-base <base> HEAD`, minus generated files."""

import re
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath

# Noise for a reviewer and expensive in tokens. Glob pathspecs, so `**/` matches any directory.
EXCLUDES = (
    "**/*.lock",  # uv.lock and friends
    "**/packages.lock.json",
    "**/*.Designer.cs",
    "**/*.g.cs",
    "**/*.generated.cs",
    "**/*.min.js",
    # Eval fixtures (evals/README.md): diffs with planted bugs and injections, applied only in a
    # temporary export by llm-eval and never run. Reviewing them reports the planted problems as
    # findings and spends the size cap; their case.yaml is still reviewed.
    "tools/llm-gate/evals/cases/*/diff.patch",
)


# A file's diff starts here. `--no-ext-diff` keeps git's own format, so this is the only boundary.
_FILE_HEADER = re.compile(r"^diff --git a/(.*) b/(.*)$", re.MULTILINE)


class DiffError(Exception):
    pass


@dataclass(frozen=True)
class OmittedFile:
    """A file left out of what the model sees, because its own diff is over `max_file_kb`."""

    path: str
    bytes: int


@dataclass(frozen=True)
class Diff:
    base: str
    text: str
    files: tuple[str, ...]
    # Files whose own diff was over `max_file_kb` and was left out of `text` (`trim_large_files`).
    # They stay in `files`, so a check's `paths:` filter and triage's size rule still see them.
    omitted: tuple[OmittedFile, ...] = ()

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


def split_file_diffs(text: str) -> tuple[tuple[str, str], ...]:
    """The diff cut into one chunk per file: `(path, chunk)`, in git's order.

    The path comes from the `b/` side (the new name), which is what a reviewer reads; for a
    deletion that is the old name, as git repeats it. Anything before the first header (there is
    nothing in `git diff` output) is ignored.
    """
    headers = list(_FILE_HEADER.finditer(text))
    chunks = []
    for n, header in enumerate(headers):
        end = headers[n + 1].start() if n + 1 < len(headers) else len(text)
        chunks.append((header.group(2), text[header.start() : end]))
    return tuple(chunks)


def trim_large_files(diff: Diff, max_file_kb: int) -> Diff:
    """Drop the files whose own diff is over `max_file_kb` from the text the model sees.

    Generated code (gRPC stubs, EF migrations, SQL seed data) would otherwise crowd the
    hand-written part of the change out of the size cap, or push the whole diff over it. The
    omission is reported in the PR comment, the audit record and the release attestation
    (ADR 0002), never silent.
    """
    limit = max_file_kb * 1024
    chunks = split_file_diffs(diff.text)
    if not chunks or all(len(c.encode("utf-8")) <= limit for _, c in chunks):
        return diff
    kept, omitted = [], []
    for path, chunk in chunks:
        size = len(chunk.encode("utf-8"))
        if size > limit:
            omitted.append(OmittedFile(path=path, bytes=size))
        else:
            kept.append(chunk)
    return replace(diff, text="".join(kept), omitted=tuple(omitted))


def touches(files: Iterable[str], patterns: Iterable[str]) -> bool:
    """True if any changed file matches any of the `paths:` globs of a check."""
    patterns = tuple(patterns)
    return any(PurePosixPath(file).full_match(pattern) for file in files for pattern in patterns)

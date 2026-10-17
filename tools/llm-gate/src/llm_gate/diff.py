"""The change under review: `git diff --merge-base <base> HEAD`, minus generated files."""

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


# Only these may be left out when a single file's diff is over `max_file_kb`: generated code, where
# the bulk is machine-written and reviewing it would cost the whole size cap. The list is narrow
# and names file types, not directories, because a directory glob matches hand-written code too.
# It decides only what may be left out: a blocking check still needs an honoured override before it
# reviews a diff with anything missing (ADR 0002), so this list is never the only thing in the way.
TRIMMABLE = (
    "**/*.pb.cs",  # gRPC / protobuf stubs
    "**/*_pb2.py",
    "**/Migrations/*.cs",  # EF Core migrations and their model snapshot
    "**/*.seed.sql",  # seed data
)


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
    # One entry per changed file, as git produced it: `(path, that file's diff)`. The text is
    # assembled from these, so trimming never has to parse the diff back apart.
    chunks: tuple[tuple[str, str], ...] = ()
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
    """Committed changes on HEAD since it branched off `base` (uncommitted work is not included).

    The diff is fetched one file at a time, so each file's own diff is known exactly: splitting a
    single blob on `diff --git` headers would miss git's quoted form (non-ASCII paths) and silently
    attach that file's changes to the previous file's chunk. `core.quotepath=false` keeps paths
    literal, and `-z` separates names with NULs so even a newline in a path is unambiguous.
    """
    excludes = [f":(exclude,glob){pattern}" for pattern in EXCLUDES]
    common = ["-c", "core.quotepath=false", "diff", "--no-color", "--no-ext-diff"]
    names = git(
        root, *common, "--name-only", "-z", "--merge-base", base, "HEAD", "--", ".", *excludes
    )
    files = tuple(name for name in names.split("\0") if name)
    chunks = tuple(
        (
            path,
            git(root, *common, "--merge-base", base, "HEAD", "--", f":(literal){path}"),
        )
        for path in files
    )
    return Diff(base=base, text="".join(c for _, c in chunks), files=files, chunks=chunks)


def trim_large_files(diff: Diff, max_file_kb: int, trimmable: Iterable[str] = TRIMMABLE) -> Diff:
    """Drop generated files whose own diff is over `max_file_kb` from the text the model sees.

    Generated code (gRPC stubs, EF migrations, SQL seed data) would otherwise crowd the
    hand-written part of the change out of the size cap, or push the whole diff over it. Only
    paths matching `trimmable` are ever dropped: a file nobody generated stays under review
    however big it is, so padding one past the cap cannot hide it from a blocking check. The
    omission is reported in the PR comment, the audit record and the release attestation
    (ADR 0002), never silent.
    """
    limit = max_file_kb * 1024
    patterns = tuple(trimmable)
    kept, omitted = [], []
    for path, chunk in diff.chunks:
        size = len(chunk.encode("utf-8"))
        generated = any(PurePosixPath(path).full_match(pattern) for pattern in patterns)
        if size > limit and generated:
            omitted.append(OmittedFile(path=path, bytes=size))
        else:
            kept.append((path, chunk))
    if not omitted:
        return diff
    return replace(
        diff,
        text="".join(c for _, c in kept),
        omitted=tuple(omitted),
        chunks=tuple(kept),
    )


def touches(files: Iterable[str], patterns: Iterable[str]) -> bool:
    """True if any changed file matches any of the `paths:` globs of a check."""
    patterns = tuple(patterns)
    return any(PurePosixPath(file).full_match(pattern) for file in files for pattern in patterns)

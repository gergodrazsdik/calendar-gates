"""Run one check with one engine: applicability, size cap, cache, engine, policy, result file."""

import logging
from collections.abc import Mapping
from pathlib import Path

from pydantic import BaseModel

from .cache import Cache, cache_key
from .config import Check
from .diff import Diff, OmittedFile, touches
from .engines import Engine, EngineError, ReviewRequest
from .models import EngineResult, Finding, Severity
from .policy import Decision, ErrorKind, decide
from .prompts import load_prompt

log = logging.getLogger(__name__)


class RunRecord(BaseModel):
    """Everything about one check run; written to <out>/results/<check>.<engine>.json."""

    check: str
    mode: str
    fail_on: Severity | None
    engine: str
    model: str
    verdict: str
    exit_code: int
    reason: str
    cached: bool = False
    result: EngineResult | None = None
    blocking: list[Finding] = []
    diff_files: int = 0
    diff_bytes: int = 0
    omitted: list[OmittedFile] = []  # files over max_file_kb, left out of the reviewed diff
    override_honoured: bool = False  # a human accepted findings, or an unreviewable diff
    risk: str | None = None  # the PR's triage risk, when the run had one

    @staticmethod
    def path(out: Path, check: str, engine: str) -> Path:
        return out / "results" / f"{check}.{engine}.json"


def run_check(
    check: Check,
    engine: Engine,
    *,
    diff: Diff,
    diff_path: Path,
    repo_root: Path,
    cache: Cache | None,
    override: bool = False,
    cache_salt: str = "",
    not_needed: str | None = None,
) -> RunRecord:
    """`cache_salt` separates otherwise identical runs in the cache (eval repeats). `not_needed`
    (triage) decides without a review."""
    result: EngineResult | None = None
    cached = False
    error: str | None = None
    error_kind = ErrorKind.ENGINE
    not_applicable: str | None = None

    if not_needed is not None:
        pass
    elif not diff.files:
        not_applicable = f"no changes against {diff.base}"
    elif check.paths and not touches(diff.files, check.paths):
        not_applicable = f"the change touches none of {', '.join(check.paths)}"
    elif check.blocking and diff.omitted and not override:
        # Trimming is a hole in a blocking review, so a human has to accept it with a reason: the
        # size cap decides what *may* be left out, never that it passes unseen (ADR 0002).
        error_kind = ErrorKind.TOO_LARGE
        names = ", ".join(o.path for o in diff.omitted)
        error = (
            f"{len(diff.omitted)} file(s) over max_file_kb {check.max_file_kb} "
            f"({names}); a blocking check needs an llm-override to review the rest"
        )
    elif diff.size_bytes > check.max_diff_kb * 1024:
        # Reported per policy instead of spending tokens (gate drill 10). Overridable, unlike an
        # engine failure: the diff is simply too big to review, which a human can accept with a
        # reason (ADR 0002). `cli.py` has already dropped the files over max_file_kb.
        error_kind = ErrorKind.TOO_LARGE
        error = f"diff too large: {diff.size_bytes // 1024} KB > max_diff_kb {check.max_diff_kb}"
    else:
        prompt = load_prompt(check.prompt_path)
        key = cache_key(check.name + cache_salt, engine.name, check.model, prompt, diff.text)
        result = cache.get(key) if cache else None
        cached = result is not None
        if result is None:
            log.info("%s: reviewing with the %s engine (%s)", check.name, engine.name, check.model)
            request = ReviewRequest(check, prompt, diff, diff_path, repo_root)
            try:
                result = engine.review(request)
            except EngineError as failure:
                error = str(failure)
            except Exception as failure:  # an engine bug or SDK surprise
                # Still a verdict, not a crash: the policy decides (blocking fails closed,
                # advisory stays advisory). The traceback goes to the log for debugging.
                log.exception("%s: the %s engine raised", check.name, engine.name)
                error = (
                    f"unexpected {type(failure).__name__} in the {engine.name} engine: {failure}"
                )
            else:
                if cache:
                    cache.put(key, result)
        else:
            log.info("%s: cache hit for the %s engine", check.name, engine.name)

    decision: Decision = decide(
        check,
        result=result,
        error=error,
        error_kind=error_kind,
        not_applicable=not_applicable,
        not_needed=not_needed,
        override=override,
        partial=bool(diff.omitted) and check.blocking,
    )
    return RunRecord(
        check=check.name,
        mode=check.mode,
        fail_on=check.fail_on,
        engine=engine.name,
        model=result.model if result else check.model,
        verdict=decision.verdict,
        exit_code=decision.exit_code,
        reason=decision.reason,
        cached=cached,
        result=result,
        blocking=list(decision.blocking),
        diff_files=len(diff.files),
        diff_bytes=diff.size_bytes,
        omitted=list(diff.omitted),
        override_honoured=decision.override_honoured,
    )


def write_record(out: Path, record: RunRecord) -> Path:
    path = RunRecord.path(out, record.check, record.engine)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(record.model_dump_json(indent=2), encoding="utf-8")
    return path


def read_records(out: Path, check: str | None = None) -> list[RunRecord]:
    pattern = f"{check}.*.json" if check else "*.json"
    return [
        RunRecord.model_validate_json(path.read_text(encoding="utf-8"))
        for path in sorted((out / "results").glob(pattern))
    ]


def engines_by_name(engines: Mapping[str, Engine], names: list[str]) -> list[Engine]:
    return [engines[name] for name in names]

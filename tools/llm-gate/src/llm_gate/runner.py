"""Run one check with one engine: applicability, size cap, cache, engine, policy, result file."""

import logging
from collections.abc import Mapping
from pathlib import Path

from pydantic import BaseModel

from .cache import Cache, cache_key
from .config import Check
from .diff import Diff, touches
from .engines import Engine, EngineError, ReviewRequest
from .models import EngineResult, Finding, Severity
from .policy import Decision, decide
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
) -> RunRecord:
    result: EngineResult | None = None
    cached = False
    error: str | None = None
    not_applicable: str | None = None

    if not diff.files:
        not_applicable = f"no changes against {diff.base}"
    elif check.paths and not touches(diff.files, check.paths):
        not_applicable = f"the change touches none of {', '.join(check.paths)}"
    elif diff.size_bytes > check.max_diff_kb * 1024:
        # Reported per policy instead of spending tokens (gate drill 10).
        error = f"diff too large: {diff.size_bytes // 1024} KB > max_diff_kb {check.max_diff_kb}"
    else:
        prompt = load_prompt(check.prompt_path)
        key = cache_key(check.name, engine.name, check.model, prompt, diff.text)
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
        check, result=result, error=error, not_applicable=not_applicable, override=override
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

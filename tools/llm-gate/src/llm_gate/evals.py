"""Eval harness: run review prompts against known cases and score them (docs/PLAN-v2.md Phase 15).

A case is a directory under `evals/cases/` with `case.yaml` (what the reviewer should and
shouldn't find) and `diff.patch`, which applies to the case's `base` commit. Each case is reviewed
in a fresh export of that commit with the patch applied, through the same `run_check` the gate
uses, so prompts, policy and caching are the gate's own. Repeats are separate cache entries, so
re-running unchanged cases is free while repeats still measure non-determinism.
"""

import contextlib
import hashlib
import json
import math
import re
import subprocess
import tarfile
import tempfile
import threading
from collections.abc import Callable, Generator, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from . import triage
from .cache import Cache
from .config import TRIAGE, Check, Risk, TriageConfig
from .diff import EXCLUDES, Diff, git
from .engines import Engine
from .models import Finding, Severity
from .policy import Verdict
from .prompts import load_prompt
from .runner import RunRecord, run_check

LINE_SLACK = 3  # a finding may point a few lines away from the planted change

CaseKind = Literal["bug", "clean", "injection", "fp-regression", "triage"]


class EvalError(Exception):
    pass


# --- cases ------------------------------------------------------------------------------------


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Expectation(_Strict):
    """A finding the reviewer must report: this file, a line in range (± LINE_SLACK), at least
    `min_severity` (that counts as found: recall). `blocking` says whether the gate should fail
    on it (verdict accuracy); by default, when `min_severity` is at or above the check's
    `fail_on`. Keep the two apart where the right severity is a judgment call: "found it" and
    "rated it high enough to block" vary independently between runs. `category` documents the
    intent; it isn't matched (models name it freely)."""

    file: str
    lines: tuple[int, int]
    min_severity: Severity
    blocking: bool | None = None
    category: str | None = None


class Forbidden(_Strict):
    """A finding that must not come back (a confirmed false positive): file, and optionally a
    line range and category."""

    file: str
    lines: tuple[int, int] | None = None
    category: str | None = None


class Case(_Strict):
    id: str
    kind: CaseKind
    checks: list[str] = Field(min_length=1)
    source: str
    description: str
    base: str
    expect: list[Expectation] = Field(default_factory=list)
    forbid: list[Forbidden] = Field(default_factory=list)
    # Triage cases (ADR 0008): the risk triage should reach, and the AI markers the PR would carry.
    expect_risk: Risk | None = None
    ai_assisted: bool = False

    @model_validator(mode="after")
    def _triage(self) -> Case:
        if (self.kind == "triage") != (self.checks == [TRIAGE]):
            raise ValueError(f"triage cases, and only they, have checks: [{TRIAGE}]")
        if (self.kind == "triage") != (self.expect_risk is not None):
            raise ValueError("triage cases, and only they, have expect_risk")
        return self

    @field_validator("base")
    @classmethod
    def _sha(cls, value: str) -> str:
        if not re.fullmatch(r"[0-9a-f]{40}", value):
            raise ValueError("base must be a full commit SHA")
        return value


class LoadedCase(BaseModel):
    case: Case
    directory: Path

    @property
    def patch(self) -> str:
        return (self.directory / "diff.patch").read_text(encoding="utf-8")


def load_cases(directory: Path, pattern: str = "*") -> list[LoadedCase]:
    cases: list[LoadedCase] = []
    for case_dir in sorted(
        p for p in directory.glob(pattern) if p.is_dir() and not p.name.startswith(".")
    ):
        try:
            data = yaml.safe_load((case_dir / "case.yaml").read_text(encoding="utf-8"))
            case = Case.model_validate(data)
        except (OSError, yaml.YAMLError, ValidationError) as error:
            raise EvalError(f"{case_dir.name}: {error}") from error
        if case.id != case_dir.name:
            raise EvalError(f"{case_dir.name}: id {case.id!r} must match the directory name")
        if not (case_dir / "diff.patch").is_file():
            raise EvalError(f"{case_dir.name}: no diff.patch")
        cases.append(LoadedCase(case=case, directory=case_dir))
    return cases


class _IndentedDumper(yaml.SafeDumper):
    """Indents list items under their key, as the repository's yamllint config requires."""

    def increase_indent(self, flow: bool = False, indentless: bool = False) -> None:
        super().increase_indent(flow, False)


def dump_case(case: Case) -> str:
    data = case.model_dump(mode="json", exclude_defaults=True)
    data.setdefault("expect", [])
    text: str = yaml.dump(
        data,
        Dumper=_IndentedDumper,
        sort_keys=False,
        allow_unicode=True,
        width=100,
        default_flow_style=None,  # short scalar lists inline: lines: [15, 15]
    )
    return "---\n" + text


def patch_files(patch: str) -> tuple[str, ...]:
    """The new-side paths of a unified diff, in order."""
    files = re.findall(r"^diff --git a/\S+ b/(\S+)$", patch, flags=re.MULTILINE)
    return tuple(dict.fromkeys(files))


@contextlib.contextmanager
def workspace(repo_root: Path, case: LoadedCase) -> Generator[Path]:
    """The case's base commit exported to a temporary directory, with its patch applied: what the
    agent engine reads. No worktree and no commit, so nothing touches the repository."""
    with tempfile.TemporaryDirectory(prefix=f"llm-eval-{case.case.id}-") as tmp:
        root = Path(tmp)
        archive = subprocess.run(
            ["git", "archive", "--format=tar", case.case.base],
            cwd=repo_root,
            check=True,
            capture_output=True,
        ).stdout
        with tarfile.open(fileobj=BytesIO(archive)) as tar:
            tar.extractall(root, filter="data")  # git's own archive; the filter is belt and braces
        applied = subprocess.run(
            ["git", "apply", "--whitespace=nowarn", "-"],
            cwd=root,
            input=case.patch.encode("utf-8"),
            capture_output=True,
            check=False,
        )
        if applied.returncode != 0:
            raise EvalError(
                f"{case.case.id}: diff.patch does not apply to {case.case.base[:12]}: "
                f"{applied.stderr.decode(errors='replace').strip()}"
            )
        yield root


def case_diff(case: LoadedCase) -> Diff:
    files = patch_files(case.patch)
    kept = [f for f in files if not any(PurePosixPath(f).full_match(p) for p in EXCLUDES)]
    if len(kept) != len(files):
        raise EvalError(f"{case.case.id}: diff.patch contains files the gate excludes")
    return Diff(base=f"case:{case.case.base[:12]}", text=case.patch, files=tuple(kept))


# --- scoring ------------------------------------------------------------------------------------


def matches(finding: Finding, expectation: Expectation) -> bool:
    if finding.file != expectation.file or finding.line is None:
        return False
    low, high = expectation.lines
    in_range = low - LINE_SLACK <= finding.line <= high + LINE_SLACK
    return in_range and finding.severity.at_least(expectation.min_severity)


def forbidden_hit(finding: Finding, forbidden: Forbidden) -> bool:
    if finding.file != forbidden.file:
        return False
    if forbidden.category is not None and finding.category != forbidden.category:
        return False
    if forbidden.lines is None:
        return True
    low, high = forbidden.lines
    return finding.line is not None and low - LINE_SLACK <= finding.line <= high + LINE_SLACK


def expected_verdict(case: Case, check: Check) -> Literal["pass", "fail"]:
    """What the gate should decide: a blocking check fails when an expected finding is at or above
    its threshold. Advisory checks always pass."""
    if not check.blocking or check.fail_on is None:
        return "pass"
    threshold = check.fail_on

    def blocks(expectation: Expectation) -> bool:
        if expectation.blocking is not None:
            return expectation.blocking
        return expectation.min_severity.at_least(threshold)

    return "fail" if any(blocks(e) for e in case.expect) else "pass"


class Attempt(BaseModel):
    """One repeat of one case."""

    repeat: int
    verdict: str
    exit_code: int  # what the gate would have exited with: non-zero fails the PR
    found: list[bool]  # per expectation
    forbidden_hits: int
    below_threshold: int  # findings under fail_on (noise on clean cases)
    findings: int
    cost_usd: float | None  # what the review cost, also when it came from the cache
    spent_usd: float = 0.0  # what this run paid: 0 on a cache hit
    duration_ms: int | None
    cached: bool
    error: str | None = None
    locations: list[str] = Field(default_factory=list)  # "high src/A.cs:15", to explain misses

    @property
    def outcome(self) -> Literal["pass", "fail"]:
        return "fail" if self.exit_code != 0 else "pass"


class CaseResult(BaseModel):
    case: str
    kind: CaseKind
    expected_verdict: str
    attempts: list[Attempt]

    @property
    def flipped(self) -> bool:
        if self.kind == "triage":  # a different risk, right or wrong
            return len({a.verdict for a in self.attempts}) > 1
        return len({a.outcome for a in self.attempts}) > 1


def score_attempt(repeat: int, record: RunRecord, case: Case, check: Check) -> Attempt:
    findings = record.result.review.findings if record.result else []
    threshold = check.fail_on
    below = (
        sum(1 for f in findings if not f.severity.at_least(threshold))
        if threshold is not None
        else len(findings)
    )
    usage = record.result.usage if record.result else None
    verdict = record.verdict
    if verdict == Verdict.OVERRIDDEN:
        verdict = Verdict.FAIL  # evals never override; keep the decision itself
    return Attempt(
        repeat=repeat,
        verdict=verdict,
        exit_code=record.exit_code,
        found=[any(matches(f, e) for f in findings) for e in case.expect],
        forbidden_hits=sum(1 for f in findings for x in case.forbid if forbidden_hit(f, x)),
        below_threshold=below,
        findings=len(findings),
        cost_usd=usage.cost_usd if usage else None,
        spent_usd=0.0 if record.cached or not usage else usage.cost_usd or 0.0,
        duration_ms=record.result.duration_ms if record.result else None,
        cached=record.cached,
        error=record.reason if verdict == Verdict.ERROR else None,
        locations=[f"{f.severity} {f.file}:{f.line}" for f in findings],
    )


def _ratio(numerator: float, denominator: float) -> float | None:
    return numerator / denominator if denominator else None


def percentile(values: Sequence[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(q * len(ordered)) - 1)
    return ordered[index]


class Metrics(BaseModel):
    cases: int
    repeats: int
    recall: float | None
    false_block_rate: float | None
    noise: float | None
    verdict_accuracy: float | None
    flip_rate: float | None
    injection_resistance: float | None
    fp_regressions: int
    errors: int
    cost_usd: float  # what the reviews cost (cached ones included): comparable across runs
    spent_usd: float  # what this run paid
    cost_p50: float | None
    cost_p90: float | None
    latency_p50_ms: float | None
    latency_p90_ms: float | None
    # Triage runs only (check "triage"): final risk == expect_risk, and results below the rules'
    # floor (a hard failure: the model may only raise).
    risk_accuracy: float | None = None
    floor_violations: int = 0


def metrics(results: Sequence[CaseResult], repeats: int) -> Metrics:
    attempts = [(r, a) for r in results for a in r.attempts]
    expected = sum(len(a.found) for _, a in attempts)
    found = sum(sum(a.found) for _, a in attempts)
    clean = [a for r, a in attempts if r.kind == "clean"]
    injection = [(r, a) for r, a in attempts if r.kind == "injection"]
    costs = [a.cost_usd for _, a in attempts if a.cost_usd is not None]
    latencies = [float(a.duration_ms) for _, a in attempts if a.duration_ms is not None]
    return Metrics(
        cases=len(results),
        repeats=repeats,
        recall=_ratio(found, expected),
        false_block_rate=_ratio(sum(1 for a in clean if a.outcome == "fail"), len(clean)),
        noise=_ratio(sum(a.below_threshold for a in clean), len(clean)),
        verdict_accuracy=_ratio(
            sum(1 for r, a in attempts if a.outcome == r.expected_verdict), len(attempts)
        ),
        flip_rate=_ratio(sum(1 for r in results if r.flipped), len(results)),
        injection_resistance=_ratio(
            sum(1 for r, a in injection if all(a.found) and a.outcome == r.expected_verdict),
            len(injection),
        ),
        fp_regressions=sum(a.forbidden_hits for _, a in attempts),
        errors=sum(1 for _, a in attempts if a.error is not None),
        cost_usd=round(sum(costs), 6),
        spent_usd=round(sum(a.spent_usd for _, a in attempts), 6),
        cost_p50=percentile(costs, 0.5),
        cost_p90=percentile(costs, 0.9),
        latency_p50_ms=percentile(latencies, 0.5),
        latency_p90_ms=percentile(latencies, 0.9),
    )


# --- running ------------------------------------------------------------------------------------


class EvalRun(BaseModel):
    """One check, engine and model over the selected cases."""

    check: str
    engine: str
    model: str
    prompt_sha256: str
    metrics: Metrics
    results: list[CaseResult]
    complete: bool = True  # False when the budget ran out


def prompt_sha256(check: Check) -> str:
    return hashlib.sha256(check.prompt_path.read_bytes()).hexdigest()


def run_eval(
    check: Check,
    engine: Engine,
    cases: Sequence[LoadedCase],
    *,
    repo_root: Path,
    cache: Cache | None,
    repeats: int,
    budget_usd: float,
    spent: Callable[[], float] = lambda: 0.0,
    progress: Callable[[str], None] = lambda _: None,
    jobs: int = 1,
) -> EvalRun:
    """Review every case that names `check`, `repeats` times each, `jobs` cases at a time.
    `spent` reports what earlier runs of this invocation already cost: the budget is shared, and
    no new case starts once it is used up (cases already running finish)."""
    load_prompt(check.prompt_path)  # fail early on a missing prompt
    selected = [loaded for loaded in cases if check.name in loaded.case.checks]
    # Evals measure the prompt, not the size cap: a case is never "too large".
    review_check = replace(check, max_diff_kb=max(check.max_diff_kb, 1024))
    lock = threading.Lock()
    total = 0.0

    def run_case(loaded: LoadedCase) -> CaseResult | None:
        nonlocal total
        case = loaded.case
        with lock:
            if spent() + total >= budget_usd:
                return None
        diff = case_diff(loaded)
        attempts: list[Attempt] = []
        with workspace(repo_root, loaded) as root:
            diff_path = root / ".llm-gate" / "diff.patch"
            diff_path.parent.mkdir(parents=True, exist_ok=True)
            diff_path.write_text(diff.text, encoding="utf-8")
            for repeat in range(1, repeats + 1):
                record = run_check(
                    review_check,
                    engine,
                    diff=diff,
                    diff_path=diff_path,
                    repo_root=root,
                    cache=cache,
                    cache_salt=f"#eval:{case.id}#r{repeat}",
                )
                attempt = score_attempt(repeat, record, case, check)
                with lock:
                    total += attempt.spent_usd
                attempts.append(attempt)
                progress(
                    f"{check.name}/{engine.name} {case.id} r{repeat}: {attempt.verdict}"
                    f"{' (cached)' if attempt.cached else ''}"
                )
        return CaseResult(
            case=case.id,
            kind=case.kind,
            expected_verdict=expected_verdict(case, check),
            attempts=attempts,
        )

    with ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
        outcomes = list(pool.map(run_case, selected))  # in case order
    results = [r for r in outcomes if r is not None]
    return EvalRun(
        check=check.name,
        engine=engine.name,
        model=check.model,
        prompt_sha256=prompt_sha256(check),
        metrics=metrics(results, repeats),
        results=results,
        complete=len(results) == len(selected),
    )


def run_triage_eval(
    config: TriageConfig,
    cases: Sequence[LoadedCase],
    *,
    cache_dir: Path | None,
    repeats: int,
    budget_usd: float,
    spent: Callable[[], float] = lambda: 0.0,
    progress: Callable[[str], None] = lambda _: None,
    jobs: int = 1,
    client: Any | None = None,
) -> EvalRun:
    """Triage every `kind: triage` case: the rules' floor from the patch, then the model, as the
    triage job does (without a manual risk). An attempt passes when the final risk is the case's
    `expect_risk`; one below the floor counts as a floor violation (`forbidden_hits`)."""
    selected = [c for c in cases if c.case.kind == "triage"]
    lock = threading.Lock()
    total = 0.0

    def run_case(loaded: LoadedCase) -> CaseResult | None:
        nonlocal total
        case = loaded.case
        with lock:
            if spent() + total >= budget_usd:
                return None
        changes = triage.changes_from_patch(loaded.patch)
        floor = triage.floor(changes, ai_assisted=case.ai_assisted, config=config)
        attempts: list[Attempt] = []
        for repeat in range(1, repeats + 1):
            model = triage.assess(
                config,
                changes,
                loaded.patch,
                base=f"case:{case.base[:12]}",
                cache_dir=cache_dir,
                client=client,
                cache_salt=f"#eval:{case.id}#r{repeat}",
            )
            final = triage.final_risk(floor.risk, model.risk, None).final
            paid = 0.0 if model.cached else model.cost_usd or 0.0
            with lock:
                total += paid
            attempts.append(
                Attempt(
                    repeat=repeat,
                    verdict=final,
                    exit_code=0 if final == case.expect_risk else 1,
                    found=[],
                    forbidden_hits=int(triage.rank(final) < triage.rank(floor.risk)),
                    below_threshold=0,
                    findings=0,
                    cost_usd=model.cost_usd,
                    spent_usd=paid,
                    duration_ms=None,
                    cached=model.cached,
                    error=model.error,
                    locations=[f"rules {floor.risk}", f"model {model.risk}"],
                )
            )
            progress(
                f"triage {case.id} r{repeat}: {final} (rules {floor.risk}, model {model.risk})"
            )
        return CaseResult(
            case=case.id,
            kind=case.kind,
            expected_verdict=case.expect_risk or "",
            attempts=attempts,
        )

    with ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
        outcomes = list(pool.map(run_case, selected))
    results = [r for r in outcomes if r is not None]
    base = metrics(results, repeats)
    attempts = [a for r in results for a in r.attempts]
    m = base.model_copy(
        update={
            "recall": None,
            "verdict_accuracy": None,
            "fp_regressions": 0,
            "risk_accuracy": _ratio(sum(1 for a in attempts if a.exit_code == 0), len(attempts)),
            "floor_violations": sum(a.forbidden_hits for a in attempts),
        }
    )
    return EvalRun(
        check=TRIAGE,
        engine="api",
        model=config.model,
        prompt_sha256=hashlib.sha256(config.prompt_path.read_bytes()).hexdigest(),
        metrics=m,
        results=results,
        complete=len(results) == len(selected),
    )


# --- baseline and thresholds -------------------------------------------------------------------


class Thresholds(_Strict):
    max_recall_drop: float = 0.05  # absolute
    max_false_block_increase: float = 0.0  # absolute: no new false blocks
    max_verdict_accuracy_drop: float = 0.10  # absolute
    max_flip_rate: float = 0.10  # absolute, on the current run
    max_cost_increase: float = 0.25  # relative
    max_risk_accuracy_drop: float = 0.15  # absolute, triage
    budget_usd: float = 6.0  # per `eval run` invocation, all checks and engines together


def load_thresholds(path: Path) -> Thresholds:
    try:
        return Thresholds.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")) or {})
    except (OSError, yaml.YAMLError, ValidationError) as error:
        raise EvalError(f"{path}: {error}") from error


def run_key(run: EvalRun) -> str:
    return f"{run.engine}/{run.model}"


def baseline_entry(run: EvalRun) -> dict[str, Any]:
    return {
        "prompt_sha256": run.prompt_sha256,
        "cases": run.metrics.cases,
        "repeats": run.metrics.repeats,
        "metrics": run.metrics.model_dump(),
    }


def update_baseline(path: Path, runs: Sequence[EvalRun]) -> dict[str, Any]:
    baseline: dict[str, Any] = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    for run in runs:
        if not run.complete:
            raise EvalError(f"{run.check} {run_key(run)}: incomplete run (budget); not a baseline")
        baseline.setdefault(run.check, {})[run_key(run)] = baseline_entry(run)
    path.write_text(json.dumps(baseline, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return baseline


class Comparison(BaseModel):
    metric: str
    baseline: float | None
    current: float | None
    limit: str
    ok: bool


def compare(run: EvalRun, baseline: Mapping[str, Any], thresholds: Thresholds) -> list[Comparison]:
    """The run against its baseline entry (same check, engine and model). No entry: only the
    absolute limits apply."""
    entry = baseline.get(run.check, {}).get(run_key(run))
    old: dict[str, Any] = entry["metrics"] if entry else {}
    new = run.metrics
    rows: list[Comparison] = []

    def delta_row(name: str, current: float | None, limit: float, direction: int) -> None:
        before = old.get(name)
        if current is None or before is None:
            rows.append(
                Comparison(metric=name, baseline=before, current=current, limit="-", ok=True)
            )
            return
        change = (current - before) * direction  # positive = worse
        rows.append(
            Comparison(
                metric=name,
                baseline=before,
                current=current,
                limit=f"{'drop' if direction < 0 else 'rise'} ≤ {limit:g}",
                ok=change <= limit + 1e-9,
            )
        )

    if run.check == TRIAGE:
        delta_row("risk_accuracy", new.risk_accuracy, thresholds.max_risk_accuracy_drop, -1)
        rows.append(
            Comparison(
                metric="floor_violations",
                baseline=old.get("floor_violations"),
                current=float(new.floor_violations),
                limit="0",
                ok=new.floor_violations == 0,
            )
        )
    else:
        delta_row("recall", new.recall, thresholds.max_recall_drop, -1)
        delta_row("false_block_rate", new.false_block_rate, thresholds.max_false_block_increase, 1)
        delta_row(
            "verdict_accuracy", new.verdict_accuracy, thresholds.max_verdict_accuracy_drop, -1
        )
    rows.append(
        Comparison(
            metric="flip_rate",
            baseline=old.get("flip_rate"),
            current=new.flip_rate,
            limit=f"≤ {thresholds.max_flip_rate:g}",
            ok=new.flip_rate is None or new.flip_rate <= thresholds.max_flip_rate + 1e-9,
        )
    )
    before_cost = old.get("cost_usd")
    rows.append(
        Comparison(
            metric="cost_usd",
            baseline=before_cost,
            current=new.cost_usd,
            limit=f"rise ≤ {thresholds.max_cost_increase:.0%}",
            ok=not before_cost or new.cost_usd <= before_cost * (1 + thresholds.max_cost_increase),
        )
    )
    if run.check != TRIAGE:
        rows.append(
            Comparison(
                metric="fp_regressions",
                baseline=old.get("fp_regressions"),
                current=float(new.fp_regressions),
                limit="0",
                ok=new.fp_regressions == 0,
            )
        )
    return rows


# --- reports ------------------------------------------------------------------------------------


def _fmt(value: float | None, kind: str = "ratio") -> str:
    if value is None:
        return "-"
    if kind == "usd":
        return f"${value:.4f}"
    if kind == "ms":
        return f"{value / 1000:.1f} s"
    if kind == "int":
        return f"{value:g}"
    return f"{value:.2f}"


def render_runs(runs: Sequence[EvalRun]) -> str:
    lines = [
        "| Check | Engine / model | Cases x repeats | Recall | False blocks | Noise | Verdicts "
        "| Flips | Injection | Errors | Cost (paid this run) | p50 / p90 latency |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for run in runs:
        m = run.metrics
        incomplete = " (incomplete: budget)" if not run.complete else ""
        lines.append(
            f"| {run.check} | `{run.engine}` / `{run.model}`{incomplete} | {m.cases} x {m.repeats} "
            f"| {_fmt(m.recall)} | {_fmt(m.false_block_rate)} | {_fmt(m.noise)} "
            f"| {_fmt(m.risk_accuracy if run.check == TRIAGE else m.verdict_accuracy)} "
            f"| {_fmt(m.flip_rate)} | {_fmt(m.injection_resistance)} "
            f"| {m.errors} | {_fmt(m.cost_usd, 'usd')} ({_fmt(m.spent_usd, 'usd')} now) "
            f"| {_fmt(m.latency_p50_ms, 'ms')} / {_fmt(m.latency_p90_ms, 'ms')} |"
        )
    return "\n".join(lines) + "\n"


def render_misses(runs: Sequence[EvalRun]) -> str:
    """Per case: what was missed, falsely blocked or flipped, so a drop is explainable."""
    lines: list[str] = []
    for run in runs:
        for result in run.results:
            problems = []
            if result.kind == "triage":
                got = ", ".join(a.verdict for a in result.attempts)
                if any(a.outcome == "fail" for a in result.attempts):
                    problems.append(f"expected {result.expected_verdict}, got {got}")
                if any(a.forbidden_hits for a in result.attempts):
                    problems.append("**below the rules' floor**")
                if problems:
                    lines.append(f"- `triage` **{result.case}**: " + ", ".join(problems))
                continue
            missed = sum(1 for a in result.attempts for f in a.found if not f)
            if missed:
                problems.append(f"missed {missed}x")
            wrong = sum(1 for a in result.attempts if a.outcome != result.expected_verdict)
            if wrong:
                problems.append(f"verdict wrong {wrong}/{len(result.attempts)}")
            if any(a.verdict == Verdict.NOT_APPLICABLE for a in result.attempts):
                problems.append("not applicable (the check's `paths:` skipped it)")
            if missed:
                seen = sorted({loc for a in result.attempts for loc in a.locations})
                problems.append(
                    "found instead: " + (", ".join(f"`{x}`" for x in seen) or "nothing")
                )
            if result.flipped:
                problems.append("flipped")
            if problems:
                lines.append(
                    f"- `{run.check}` `{run.engine}` **{result.case}** ({result.kind}): "
                    + ", ".join(problems)
                )
    return "\n".join(lines) + ("\n" if lines else "")


def render_comparison(run: EvalRun, rows: Sequence[Comparison]) -> str:
    lines = [
        f"**{run.check}** `{run.engine}` / `{run.model}`",
        "",
        "| Metric | Baseline | Now | Limit | |",
        "|---|---|---|---|---|",
    ]
    for row in rows:
        kind = (
            "usd"
            if row.metric == "cost_usd"
            else "int"
            if row.metric in ("fp_regressions", "floor_violations")
            else "ratio"
        )
        lines.append(
            f"| {row.metric} | {_fmt(row.baseline, kind)} | {_fmt(row.current, kind)} "
            f"| {row.limit} | {'✅' if row.ok else '❌'} |"
        )
    return "\n".join(lines) + "\n"


def write_report(out: Path, runs: Sequence[EvalRun]) -> list[Path]:
    """reports/eval/<check>-<prompt sha>.json per check, plus last.json naming them."""
    out.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    by_check: dict[str, list[EvalRun]] = {}
    for run in runs:
        by_check.setdefault(run.check, []).append(run)
    for check, check_runs in by_check.items():
        path = out / f"{check}-{check_runs[0].prompt_sha256[:12]}.json"
        path.write_text(
            json.dumps([r.model_dump(mode="json") for r in check_runs], indent=2) + "\n",
            encoding="utf-8",
        )
        paths.append(path)
    (out / "last.json").write_text(
        json.dumps([p.name for p in paths], indent=2) + "\n", encoding="utf-8"
    )
    return paths


def read_last(out: Path) -> list[EvalRun]:
    try:
        names = json.loads((out / "last.json").read_text(encoding="utf-8"))
        return [
            EvalRun.model_validate(run)
            for name in names
            for run in json.loads((out / name).read_text(encoding="utf-8"))
        ]
    except (OSError, ValueError) as error:
        raise EvalError(f"no last eval run in {out}: {error}") from error


# --- fp-regression cases ------------------------------------------------------------------------


def case_from_false_positive(
    finding_id: str,
    *,
    audit_dir: Path,
    repo_root: Path,
    cases_dir: Path,
) -> Path:
    """Turn a finding from the audit log into an fp-regression case: the same diff, and the
    finding (file, line, category) must not come back."""
    found: tuple[dict[str, Any], dict[str, Any]] | None = None
    for path in sorted(audit_dir.glob("events/**/*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            record = json.loads(line)
            if record.get("type") != "gate_run":
                continue
            for finding in record.get("findings", []):
                if finding.get("id") == finding_id:
                    found = (record, finding)
    if found is None:
        raise EvalError(f"finding {finding_id} is not in {audit_dir} (run `just audit-pull`)")
    record, finding = found
    if record.get("workflow_modified"):
        raise EvalError(f"{finding_id} comes from a run whose workflow was modified; not usable")
    base, head = record.get("base_sha"), record.get("head_sha")
    if not base or not head:
        raise EvalError(f"{finding_id}: the record has no base or head commit")
    try:
        patch = git(
            repo_root,
            "diff",
            "--no-color",
            "--no-ext-diff",
            base,
            head,
            "--",
            ".",
            *(f":(exclude,glob){pattern}" for pattern in EXCLUDES),
        )
    except Exception as error:
        raise EvalError(
            f"{finding_id}: cannot diff {base[:12]}..{head[:12]}; fetch them first "
            f"(git fetch origin pull/{record.get('pr')}/head): {error}"
        ) from error
    case_id = f"fp-{finding_id}"
    directory = cases_dir / case_id
    if directory.exists():
        raise EvalError(f"{directory} exists already")
    finding_line = finding.get("line")
    case = Case(
        id=case_id,
        kind="fp-regression",
        checks=[record["check"]],
        source=f"false positive {finding_id} on PR #{record.get('pr')} ({head[:7]})",
        description=f"Must not report again: {finding.get('title')}",
        base=base,
        forbid=[
            Forbidden(
                file=finding["file"],
                lines=(finding_line, finding_line) if isinstance(finding_line, int) else None,
                category=finding.get("category") or None,
            )
        ],
    )
    directory.mkdir(parents=True)
    (directory / "diff.patch").write_text(patch, encoding="utf-8")
    (directory / "case.yaml").write_text(dump_case(case), encoding="utf-8")
    return directory

"""Audit records (`schema: audit/v1`): one JSON object per line, one record per gate decision.

Two sides (docs/adr/0005-audit-trail.md):

- **untrusted**: `llm-gate run` in the PR's workflow appends `gate_run` (and `override`) records to
  `.llm-gate/audit.jsonl`, which the workflow uploads as an artifact;
- **trusted**: `audit-collect.yml` (default branch, `workflow_run`) validates each artifact against
  the triggering run with `collect()` before anything reaches the `audit-log` branch.

Deliberately not stored: the diff (only its hash), raw model output, anything else from the
environment. Tool-call input summaries are truncated and redacted.
"""

import hashlib
import json
import re
import uuid
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Annotated, Any, Final, Literal, cast

from pydantic import (
    UUID4,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    TypeAdapter,
    ValidationError,
)

from .config import Check, EngineName
from .models import Severity, ToolCall, finding_id
from .policy import Verdict
from .redact import MAX_SUMMARY, Short, Text, clip, redact
from .runner import RunRecord

SCHEMA: Final = "audit/v1"
AUDIT_FILE = "audit.jsonl"

# Limits for artifacts the collector reads: they come from a workflow the PR controls.
MAX_FILE_BYTES = 1024 * 1024
MAX_LINE_BYTES = 256 * 1024
MAX_RECORDS = 20
MAX_ARTIFACTS = 20  # one per check; checks.yaml has six

# --- schema ---------------------------------------------------------------------------------


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, validate_by_name=True)


# Every string an artifact can carry is either a strict pattern or scrubbed text (redact.py): the
# PR's workflow writes the artifact, and the log is public and can't be rewritten.
type Sha = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{40}$")]
type Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
type RepoName = Annotated[
    str, StringConstraints(pattern=r"^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$")
]
type Login = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9-]{1,39}(\[bot\])?$")]
type CheckName = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]{0,40}$")]
type ModelName = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9.:@_-]{0,80}$")]
type FindingId = Annotated[str, StringConstraints(pattern=r"^[a-z]{1,8}-[0-9a-f]{4}$")]
type Count = Annotated[int, Field(ge=0)]
type Conclusion = Literal[
    "success", "failure", "cancelled", "skipped", "neutral", "timed_out", "action_required", "stale"
]


class RunContext(_Strict):
    """Where a record comes from. All empty for local runs."""

    repo: RepoName | None = None
    pr: Count | None = None
    head_sha: Sha | None = None
    base_sha: Sha | None = None
    actor: Login | None = None
    workflow_run_id: Count | None = None
    run_attempt: Count | None = None
    run_url: Text | None = None


def _now() -> datetime:
    return datetime.now(UTC)


class _Record(RunContext):
    schema_: Literal["audit/v1"] = Field(default=SCHEMA, alias="schema")
    id: UUID4 = Field(default_factory=uuid.uuid4)
    ts: AwareDatetime = Field(default_factory=_now)


class AuditFinding(_Strict):
    """A finding as the log keeps it: the model wrote these strings, so they are scrubbed."""

    id: FindingId
    severity: Severity
    category: Short
    file: Text
    line: Count | None
    title: Text


class TokenUsage(_Strict):
    input_tokens: Count | None = None
    output_tokens: Count | None = None
    num_turns: Count | None = None


GateVerdict = Literal["pass", "fail", "error", "not_needed", "not_applicable", "skipped_no_key"]

# The exit codes each verdict can come with (policy.py); anything else is a contradiction.
VERDICT_EXITS: dict[str, frozenset[int]] = {
    "pass": frozenset({0}),
    "not_applicable": frozenset({0}),
    "not_needed": frozenset({0}),
    "skipped_no_key": frozenset({0}),
    "error": frozenset({0, 2}),  # 0 for advisory checks and on_error: pass
    "fail": frozenset({1}),  # 0 only with override_honoured
}


class GateRun(_Record):
    type: Literal["gate_run"] = "gate_run"
    check: CheckName
    engine: EngineName
    model: ModelName
    prompt_file: Text
    prompt_sha256: Digest
    config_sha256: Digest
    gate_sha: Sha | None  # the commit the gate tooling ran from (the PR's base in CI)
    diff_sha256: Digest | None
    diff_bytes: Count
    risk: Short | None = None  # Phase 17 (triage)
    blocking: bool
    cache_hit: bool
    pr_event_at: AwareDatetime | None = None
    started_at: AwareDatetime
    finished_at: AwareDatetime
    usage: TokenUsage = Field(default_factory=TokenUsage)
    cost_usd: Annotated[float, Field(ge=0)] | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list, max_length=200)
    findings: list[AuditFinding] = Field(default_factory=list, max_length=100)
    verdict: GateVerdict
    exit_code: Annotated[int, Field(ge=0, le=2)]  # the job's exit code; compared with the job
    override_honoured: bool = False
    error: Text | None = None
    # Only the collector sets these; an artifact that sets them is rejected.
    workflow_modified: bool | None = None
    check_run_conclusion: Conclusion | None = None


class Triage(_Record):
    type: Literal["triage"] = "triage"
    rules_risk: Short
    model_risk: Short | None
    final_risk: Short
    reasons: list[Text] = Field(max_length=20)
    ai_assisted: bool
    checks_plan: list[CheckName] = Field(max_length=20)


class Override(_Record):
    type: Literal["override"] = "override"
    by: Login | None
    reason: Text
    checks: list[CheckName] = Field(min_length=1, max_length=20)


class Feedback(_Record):
    type: Literal["feedback"] = "feedback"
    finding_id: FindingId
    kind: Literal["fp", "ack"]
    by: Login
    reason: Text | None = None


class RiskOverride(_Record):
    type: Literal["risk_override"] = "risk_override"
    from_: Short = Field(alias="from")
    to: Short
    by: Login
    reason: Text


class EvalRun(_Record):
    type: Literal["eval_run"] = "eval_run"
    prompt_sha256: Digest
    model: ModelName
    engine: EngineName
    scores: dict[Short, float] = Field(max_length=50)


class TamperSuspected(_Record):
    """Written by the collector instead of an artifact's records when they don't check out."""

    type: Literal["tamper_suspected"] = "tamper_suspected"
    artifact: Short
    problems: list[Text] = Field(max_length=50)  # may quote the artifact, so scrubbed too


AuditRecord = Annotated[
    GateRun | Triage | Override | Feedback | RiskOverride | EvalRun | TamperSuspected,
    Field(discriminator="type"),
]
_ADAPTER: TypeAdapter[AuditRecord] = TypeAdapter(AuditRecord)

# What the untrusted side may write. Triage joins once Phase 17 produces it; feedback, risk
# overrides, evals and tamper events come from trusted workflows only.
ARTIFACT_TYPES = frozenset({"gate_run", "override"})


def dumps(record: BaseModel) -> str:
    return record.model_dump_json(by_alias=True)


def parse(line: str) -> AuditRecord:
    return _ADAPTER.validate_json(line)


def append(path: Path, records: Iterable[BaseModel]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        for record in records:
            file.write(dumps(record) + "\n")


# --- redaction --------------------------------------------------------------------------------

# The input fields worth keeping per tool; anything else is summarised as compact JSON.
_TOOL_FIELDS = {
    "Read": ("file_path", "offset", "limit"),
    "Grep": ("pattern", "path", "glob"),
    "Glob": ("pattern", "path"),
}


def summarise_tool_input(tool: str, tool_input: Mapping[str, Any], root: Path | None) -> str:
    fields = _TOOL_FIELDS.get(tool)
    if fields:
        text = " ".join(f"{k}={tool_input[k]}" for k in fields if tool_input.get(k) is not None)
    else:
        text = json.dumps(tool_input, sort_keys=True, separators=(",", ":"), default=str)
    if root is not None:
        # Repository-relative paths, so the record doesn't carry the runner's layout.
        text = text.replace(f"{root}/", "").replace(str(root), ".")
    return clip(redact(text), MAX_SUMMARY)  # redact first: a cut can't hide half a secret


# --- building records (untrusted side) ---------------------------------------------------------


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def context_from_env(
    env: Mapping[str, str], *, head_sha: str | None, base_sha: str | None
) -> RunContext:
    """The GitHub Actions context of this run; only these named variables are read."""

    def number(name: str) -> int | None:
        value = env.get(name, "")
        return int(value) if value.isdigit() else None

    repo = env.get("GITHUB_REPOSITORY") or None
    run_id = number("GITHUB_RUN_ID")
    attempt = number("GITHUB_RUN_ATTEMPT")
    server = env.get("GITHUB_SERVER_URL") or "https://github.com"
    run_url = (
        f"{server}/{repo}/actions/runs/{run_id}/attempts/{attempt or 1}"
        if repo and run_id
        else None
    )
    return RunContext(
        repo=repo,
        pr=number("LLM_GATE_PR"),
        head_sha=head_sha,
        base_sha=base_sha,
        actor=env.get("GITHUB_ACTOR") or None,
        workflow_run_id=run_id,
        run_attempt=attempt,
        run_url=run_url,
    )


@dataclass(frozen=True)
class GateInfo:
    """What the gate ran with: its own commit, config and prompt (ADR 0004)."""

    gate_sha: str | None
    config_sha256: str
    prompt_file: str
    prompt_sha256: str


def gate_info(check: Check, *, config: Path, gate_root: Path, gate_sha: str | None) -> GateInfo:
    try:
        prompt_file = check.prompt_path.resolve().relative_to(gate_root.resolve()).as_posix()
    except ValueError:
        prompt_file = str(check.prompt_path)
    return GateInfo(
        gate_sha=gate_sha,
        config_sha256=sha256_file(config),
        prompt_file=prompt_file,
        prompt_sha256=sha256_file(check.prompt_path),
    )


_VERDICTS: dict[Verdict, GateVerdict] = {
    Verdict.PASS: "pass",
    Verdict.FAIL: "fail",
    Verdict.OVERRIDDEN: "fail",  # with override_honoured: the findings stay on record
    Verdict.NOT_APPLICABLE: "not_applicable",
    Verdict.ERROR: "error",
}


def gate_run(
    record: RunRecord,
    *,
    check: Check,
    context: RunContext,
    gate: GateInfo,
    diff_text: str | None,
    started_at: datetime,
    finished_at: datetime,
    pr_event_at: datetime | None = None,
) -> GateRun:
    result = record.result
    verdict = Verdict(record.verdict)
    return GateRun(
        **context.model_dump(),
        check=record.check,
        engine=cast(EngineName, record.engine),  # an engine's name; pydantic checks it
        model=record.model,
        prompt_file=gate.prompt_file,
        prompt_sha256=gate.prompt_sha256,
        config_sha256=gate.config_sha256,
        gate_sha=gate.gate_sha,
        diff_sha256=sha256_text(diff_text) if diff_text is not None else None,
        diff_bytes=record.diff_bytes,
        blocking=check.blocking,
        cache_hit=record.cached,
        pr_event_at=pr_event_at,
        started_at=started_at,
        finished_at=finished_at,
        usage=TokenUsage(
            input_tokens=result.usage.input_tokens,
            output_tokens=result.usage.output_tokens,
            num_turns=result.usage.num_turns,
        )
        if result
        else TokenUsage(),
        cost_usd=result.usage.cost_usd if result and not record.cached else None,
        tool_calls=result.tool_calls if result and not record.cached else [],
        findings=[
            AuditFinding(
                id=finding_id(record.check, f),
                severity=f.severity,
                category=f.category,
                file=f.file,
                line=f.line,
                title=f.title,
            )
            for f in (result.review.findings if result else [])
        ],
        verdict=_VERDICTS[verdict],
        exit_code=record.exit_code,
        override_honoured=verdict is Verdict.OVERRIDDEN,
        error=record.reason if verdict is Verdict.ERROR else None,
    )


def skipped_run(
    check: Check,
    *,
    context: RunContext,
    gate: GateInfo,
    reason: GateVerdict,
    at: datetime,
) -> GateRun:
    """A check that did not run at all (no API key for this PR, or not needed after triage)."""
    return GateRun(
        **context.model_dump(),
        check=check.name,
        engine=check.engine,
        model=check.model,
        prompt_file=gate.prompt_file,
        prompt_sha256=gate.prompt_sha256,
        config_sha256=gate.config_sha256,
        gate_sha=gate.gate_sha,
        diff_sha256=None,
        diff_bytes=0,
        blocking=check.blocking,
        cache_hit=False,
        started_at=at,
        finished_at=at,
        verdict=reason,
        exit_code=0,
    )


# --- overrides with a reason --------------------------------------------------------------------

OVERRIDE_LABEL = "llm-override"
OVERRIDE_COMMAND = "/llm-override"


@dataclass(frozen=True)
class OverrideRequest:
    by: str | None
    reason: str


def find_override(
    events: Sequence[Mapping[str, Any]],
    comments: Sequence[Mapping[str, Any]],
    *,
    label: str = OVERRIDE_LABEL,
) -> OverrideRequest | str:
    """The reason for the PR's override label, or why there is none.

    `events` are the PR's issue events, `comments` its issue comments (GitHub REST shapes). The
    override counts only if whoever added the label most recently also wrote a
    `/llm-override <reason>` comment with a non-empty reason.
    """
    labelled = [
        e
        for e in events
        if e.get("event") == "labeled" and (e.get("label") or {}).get("name") == label
    ]
    if not labelled:
        return f"the {label} label was not added through the issue events API"
    by = (labelled[-1].get("actor") or {}).get("login")
    if not by:
        return f"cannot tell who added the {label} label"
    labelled_at = _when(labelled[-1].get("created_at"))
    if labelled_at is None:
        return f"cannot tell when the {label} label was added"
    for comment in reversed(comments):
        if (comment.get("user") or {}).get("login") != by:
            continue
        created = _when(comment.get("created_at"))
        # Only a comment written for this labelling counts, and only as written: an edit could
        # change the reason after the override was honoured.
        if created is None or created < labelled_at:
            continue
        if _when(comment.get("updated_at")) != created:
            continue
        body = str(comment.get("body") or "").strip()
        first, _, _ = body.partition("\n")
        command, _, reason = first.partition(" ")
        if command == OVERRIDE_COMMAND and reason.strip():
            return OverrideRequest(by=by, reason=reason.strip())
    return (
        f"{by} added {label} but wrote no unedited `{OVERRIDE_COMMAND} <reason>` comment after it"
    )


def _when(value: object) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value)) if value else None
    except ValueError:
        return None


# --- validating and collecting (trusted side) ---------------------------------------------------

_ARTIFACT_NAME = re.compile(r"audit-(?P<run_id>[0-9]+)-(?P<check>[a-z0-9][a-z0-9-]{0,40})")


@dataclass(frozen=True)
class Expected:
    """What the collector knows about the triggering run from the event, not from the artifact."""

    repo: str
    workflow_run_id: int
    run_attempt: int
    head_sha: str
    pr: int


def validate_file(
    path: Path, expected: Expected, check: str | None = None
) -> tuple[list[AuditRecord], list[str]]:
    """Strictly parse an untrusted audit file. Returns the records and the problems found; any
    problem means none of the records may be written."""
    problems: list[str] = []
    try:
        size = path.stat().st_size
    except OSError as error:
        return [], [f"cannot read {path.name}: {error}"]
    if size > MAX_FILE_BYTES:
        return [], [f"{path.name} is {size} bytes, over the {MAX_FILE_BYTES} limit"]
    lines = [line for line in path.read_bytes().split(b"\n") if line.strip()]
    if not lines:
        return [], [f"{path.name} has no records"]
    if len(lines) > MAX_RECORDS:
        return [], [f"{path.name} has {len(lines)} records, over the {MAX_RECORDS} limit"]

    records: list[AuditRecord] = []
    for number, raw in enumerate(lines, start=1):
        where = f"{path.name}:{number}"
        if len(raw) > MAX_LINE_BYTES:
            problems.append(f"{where}: line over {MAX_LINE_BYTES} bytes")
            continue
        try:
            record = parse(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValidationError) as error:
            problems.append(f"{where}: not a valid {SCHEMA} record: {_short(error)}")
            continue
        problems += [f"{where}: {p}" for p in _record_problems(record, expected, check)]
        records.append(record)
    ids = [r.id for r in records]
    if len(ids) != len(set(ids)):
        problems.append(f"{path.name}: duplicate record ids")
    return records, problems


def _short(error: Exception) -> str:
    text = str(error).replace("\n", " ")
    return text if len(text) <= 300 else text[:299] + "…"


def _record_problems(record: AuditRecord, expected: Expected, check: str | None) -> list[str]:
    problems: list[str] = []
    if record.type not in ARTIFACT_TYPES:
        problems.append(f"type {record.type!r} may not come from a PR's workflow")
    for field in ("repo", "workflow_run_id", "run_attempt", "head_sha", "pr"):
        got, want = getattr(record, field), getattr(expected, field)
        if got != want:
            problems.append(f"{field} is {got!r}, the triggering run has {want!r}")
    if isinstance(record, GateRun):
        if check is not None and record.check != check:
            problems.append(f"check {record.check!r} in the artifact for {check!r}")
        if record.workflow_modified is not None or record.check_run_conclusion is not None:
            problems.append("sets fields only the collector may set")
        exits = VERDICT_EXITS[record.verdict]
        if record.override_honoured:
            exits = frozenset({0}) if record.verdict == "fail" else frozenset()
        if record.exit_code not in exits:
            override = " with override_honoured" if record.override_honoured else ""
            problems.append(f"verdict {record.verdict}{override} with exit code {record.exit_code}")
    if isinstance(record, Override) and check is not None and check not in record.checks:
        problems.append(f"override for {record.checks} in the artifact for {check!r}")
    return problems


def expected_conclusion(record: GateRun) -> str:
    return "success" if record.exit_code == 0 else "failure"


@dataclass(frozen=True)
class Collected:
    path: str  # relative to the output directory, e.g. events/2026/10/16/123-1-code-review.jsonl
    artifact: str
    records: int
    tamper: bool


def collect(
    artifacts: Path,
    *,
    expected: Expected,
    checks: Collection[str],
    jobs: Mapping[str, str | None],
    workflow_modified: bool,
    override: OverrideRequest | str,
    out: Path,
    day: date,
) -> list[Collected]:
    """Validate every `audit-<run_id>-<check>` artifact directory under `artifacts` and write one
    file per artifact under `out/events/YYYY/MM/DD/`. `jobs` maps job names of the triggering run
    to their conclusions (Actions API); `checks` are the checks in the default branch's
    checks.yaml; `override` is `find_override` on the PR's issue events and comments as the
    collector fetched them (or why there is none)."""
    folder = Path("events", f"{day:%Y}", f"{day:%m}", f"{day:%d}")
    prefix = f"{expected.workflow_run_id}-{expected.run_attempt}"
    directories = sorted(p for p in artifacts.iterdir() if p.is_dir())
    if len(directories) > MAX_ARTIFACTS:
        problem = f"{len(directories)} artifacts, over the {MAX_ARTIFACTS} limit; none collected"
        target = folder / f"{prefix}-too-many.jsonl"
        _write(out / target, [_tamper(expected, "(all)", [problem])])
        return [Collected(target.as_posix(), "(all)", 1, tamper=True)]

    collected: list[Collected] = []
    for index, directory in enumerate(directories):
        name = directory.name
        match = _ARTIFACT_NAME.fullmatch(name)
        problems: list[str] = []
        records: list[AuditRecord] = []
        if match is None or int(match["run_id"]) != expected.workflow_run_id:
            check = f"invalid-{index}"
            want = f"audit-{expected.workflow_run_id}-<check>"
            problems.append(f"artifact name {name[:80]!r} is not {want}")
        elif match["check"] not in checks:
            check = f"invalid-{index}"
            problems.append(
                f"{match['check']!r} is not a check in the default branch's checks.yaml"
            )
        else:
            check = match["check"]
            files = sorted(p.name for p in directory.iterdir())
            if files != [AUDIT_FILE]:
                problems.append(f"expected only {AUDIT_FILE}, found {files[:10]}")
            else:
                records, problems = validate_file(directory / AUDIT_FILE, expected, check)

        finished: list[AuditRecord] = []
        if not problems:
            problems += _override_problems(records, override)
            for record in records:
                if isinstance(record, GateRun):
                    job = f"llm / {record.check}"
                    conclusion = jobs.get(job)
                    if job not in jobs:
                        problems.append(f"the triggering run has no job {job!r}")
                    elif conclusion not in {"success", "failure"}:
                        # Only a finished job can confirm the record; anything else is unverified.
                        problems.append(
                            f"{job} concluded {conclusion}, so the record can't be checked"
                        )
                    elif conclusion != expected_conclusion(record):
                        problems.append(
                            f"{job} concluded {conclusion}, but the record says "
                            f"{record.verdict} (exit {record.exit_code})"
                        )
                    record = record.model_copy(
                        update={
                            "workflow_modified": workflow_modified,
                            "check_run_conclusion": conclusion,
                        }
                    )
                finished.append(record)

        target = folder / f"{prefix}-{check}.jsonl"
        if problems:
            finished = [_tamper(expected, name, problems)]
        _write(out / target, finished)
        collected.append(
            Collected(target.as_posix(), name[:120], len(finished), tamper=bool(problems))
        )
    return collected


def _tamper(expected: Expected, artifact: str, problems: Sequence[str]) -> TamperSuspected:
    return TamperSuspected(
        repo=expected.repo,
        pr=expected.pr,
        head_sha=expected.head_sha,
        workflow_run_id=expected.workflow_run_id,
        run_attempt=expected.run_attempt,
        artifact=artifact,
        problems=list(problems[:50]),
    )


def _write(path: Path, records: Iterable[BaseModel]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(dumps(r) + "\n" for r in records), encoding="utf-8")


def _override_problems(records: Sequence[AuditRecord], trusted: OverrideRequest | str) -> list[str]:
    """Override claims in the artifact must match what the collector found itself."""
    problems: list[str] = []
    for record in records:
        if isinstance(record, Override):
            if isinstance(trusted, str):
                problems.append(f"override record, but the collector found none: {trusted}")
            elif (record.by, record.reason) != (trusted.by, clip(redact(trusted.reason), 500)):
                problems.append(
                    f"override by {record.by!r} does not match {trusted.by!r}'s /llm-override"
                )
        elif isinstance(record, GateRun) and record.override_honoured and isinstance(trusted, str):
            problems.append(f"{record.check}: override honoured, but the collector found none")
    return problems


def read_jobs(path: Path) -> dict[str, str | None]:
    """Job conclusions from `gh api .../jobs --paginate --jq '.jobs[] | {name, conclusion}'`
    (one JSON object per line)."""
    jobs: dict[str, str | None] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            job = json.loads(line)
            jobs[str(job["name"])] = job.get("conclusion")
    return jobs

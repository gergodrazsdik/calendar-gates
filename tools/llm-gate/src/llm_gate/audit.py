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
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Annotated, Any, Final, Literal, NamedTuple, cast

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

from .config import Check, EngineName, Risk
from .models import Severity, ToolCall, finding_id, finding_prefix
from .policy import Verdict
from .redact import MAX_SUMMARY, Short, Text, clip, redact
from .runner import RunRecord
from .triage import highest

SCHEMA: Final = "audit/v1"
AUDIT_FILE = "audit.jsonl"

# Limits for artifacts the collector reads: they come from a workflow the PR controls.
MAX_FILE_BYTES = 128 * 1024
MAX_RUN_BYTES = 256 * 1024  # all artifacts of one run together
# Below MAX_FILE_BYTES on purpose: at 256 KB the per-line check could never fire, because the file
# limit is checked first and is smaller (F016). A single record this big is a bug or an attempt to
# bury something in one line, and the per-record field limits are far smaller.
MAX_LINE_BYTES = 64 * 1024
MAX_RECORDS = 20
MAX_ARTIFACTS = 20  # one per check; checks.yaml has six
MAX_TOOL_CALLS = 200
MAX_FINDINGS = 100
MAX_OMITTED = 100

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
type ModelName = Annotated[str, StringConstraints(pattern=r"^claude-[a-z0-9.@-]{1,60}$")]
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


class OmittedAudit(_Strict):
    """A file the review never saw: its own diff was over the check's `max_file_kb`."""

    path: Text
    bytes: Count


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
    diff_sha256: Digest | None  # of the reviewed diff, after omitted_files were dropped
    diff_bytes: Count
    # Files over the check's max_file_kb, left out of the review (ADR 0002); the attestation
    # reports a blocking check that omitted any of them as a partial review.
    omitted_files: list[OmittedAudit] = Field(default_factory=list, max_length=MAX_OMITTED)
    risk: Risk | None = None  # the PR's triage risk (ADR 0008); None without triage
    blocking: bool
    cache_hit: bool
    pr_event_at: AwareDatetime | None = None
    started_at: AwareDatetime
    finished_at: AwareDatetime
    usage: TokenUsage = Field(default_factory=TokenUsage)
    cost_usd: Annotated[float, Field(ge=0)] | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list, max_length=MAX_TOOL_CALLS)
    # Reads the gate refused because they reached outside the reviewed checkout (F003). A count as
    # well as the flags on `tool_calls`, because that list is truncated and because a number has no
    # free text to withhold: a refusal stays visible even on a run whose text is held back.
    denied_reads: Count = 0
    findings: list[AuditFinding] = Field(default_factory=list, max_length=MAX_FINDINGS)
    verdict: GateVerdict
    exit_code: Annotated[int, Field(ge=0, le=2)]  # the job's exit code; compared with the job
    override_honoured: bool = False
    error: Text | None = None
    # Only the collector sets these; an artifact that sets them is rejected.
    workflow_modified: bool | None = None
    check_run_conclusion: Conclusion | None = None


class Triage(_Record):
    """The triage job's decision (ADR 0008). The collector recomputes `rules_risk` and
    `ai_assisted` from the GitHub API and checks every gate_run of the run against
    `final_risk`."""

    type: Literal["triage"] = "triage"
    rules_risk: Risk
    rules_reasons: list[Text] = Field(default_factory=list, max_length=20)
    model: ModelName | None = None
    model_risk: Risk | None
    reasons: list[Text] = Field(max_length=20)  # the model's (scrubbed, withheld if modified)
    final_risk: Risk
    source: Literal["rules", "model", "manual"] = "rules"
    ai_assisted: bool
    ai_commits: Count = 0
    total_commits: Count = 0
    changed_lines: Count = 0
    cost_usd: Annotated[float, Field(ge=0)] | None = None
    cache_hit: bool = False
    error: Text | None = None
    checks_plan: list[CheckName] = Field(max_length=20)
    # Only the collector sets this; an artifact that sets it is rejected. It says the record came
    # from an earlier attempt of the same run, because "Re-run failed jobs" doesn't re-run a
    # successful triage job (ADR 0008).
    reused_from_attempt: Count | None = None


class Override(_Record):
    type: Literal["override"] = "override"
    by: Login | None
    reason: Text
    checks: list[CheckName] = Field(min_length=1, max_length=20)


class Feedback(_Record):
    type: Literal["feedback"] = "feedback"
    finding_id: FindingId
    check: CheckName | None = None
    kind: Literal["fp", "ack"]
    by: Login
    reason: Text | None = None


FeedbackCommand = Literal["fp", "ack", "override", "risk", "unknown"]
RejectionCode = Literal[
    "not_a_collaborator", "unknown_command", "bad_arguments", "unknown_finding", "not_a_pr"
]


class FeedbackRejected(_Record):
    """A `/llm-*` comment that wasn't honoured. Fixed fields only: anyone can comment on a public
    repository's PRs, and the log is permanent."""

    type: Literal["feedback_rejected"] = "feedback_rejected"
    by: Login
    command: FeedbackCommand
    code: RejectionCode


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
    GateRun
    | Triage
    | Override
    | Feedback
    | FeedbackRejected
    | RiskOverride
    | EvalRun
    | TamperSuspected,
    Field(discriminator="type"),
]
_ADAPTER: TypeAdapter[AuditRecord] = TypeAdapter(AuditRecord)


class LoadedEvents(NamedTuple):
    records: list[dict[str, Any]]
    rejected: int  # lines under events/ that are not a valid record of a known type


def load_events(audit_dir: Path) -> LoadedEvents:
    """Every record under `events/`, validated against the schema the collector writes with.

    The collector's strictness protects the *write* path: a PR's artifact is parsed with
    `extra="forbid"`, size-capped and cross-checked against the API before anything is committed.
    It says nothing about the *read* path. The `audit-log` branch takes a push from anyone with
    write access and from any workflow holding `contents: write` (ADR 0005 accepts that), so a
    hand-appended line used to reach the release attestation and the metrics unchecked: both read
    every line with `json.loads` and treated any object carrying `"type": "gate_run"` as a verdict.

    Rejected lines are **counted, not skipped quietly**: the count reaches the attestation
    predicate and the metrics report, so a malformed or planted line is visible rather than
    absent. Records are returned as dicts because the readers index many record types loosely;
    validation is what this adds, not a change of shape.
    """
    records: list[dict[str, Any]] = []
    rejected = 0
    for path in sorted(audit_dir.glob("events/**/*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                _ADAPTER.validate_python(record)
            except ValueError, ValidationError:
                rejected += 1
                continue
            records.append(record)
    return LoadedEvents(records, rejected)


# What the untrusted side may write (each checked by the collector); feedback, risk overrides,
# evals and tamper events come from trusted workflows only.
ARTIFACT_TYPES = frozenset({"gate_run", "override", "triage"})
TRIAGE_ARTIFACT = "triage"  # audit-<run>-<attempt>-triage, from the `triage` job


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


def _kept_calls(calls: Sequence[ToolCall]) -> list[ToolCall]:
    """The calls that fit the record, refusals first in line. A plain head slice would let a review
    that issued two hundred ordinary reads before the interesting one leave no refusal at all."""
    if len(calls) <= MAX_TOOL_CALLS:
        return list(calls)
    denied = [i for i, call in enumerate(calls) if call.denied][:MAX_TOOL_CALLS]
    allowed = [i for i, call in enumerate(calls) if not call.denied]
    keep = sorted(denied + allowed[: MAX_TOOL_CALLS - len(denied)])
    return [calls[i] for i in keep]  # chronological order among the ones kept


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
    Verdict.NOT_NEEDED: "not_needed",
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
    risk: Risk | None = None,
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
        risk=risk,
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
        # Clamped to the schema's limits: a finished review must never fail to be recorded
        # because the model returned line 0 or a long list (the most severe findings are kept).
        tool_calls=_kept_calls(result.tool_calls) if result and not record.cached else [],
        denied_reads=result.denied_reads if result and not record.cached else 0,
        findings=[
            AuditFinding(
                id=finding_id(record.check, f),
                severity=f.severity,
                category=f.category,
                file=f.file,
                line=f.line if f.line and f.line > 0 else None,
                title=f.title,
            )
            for f in sorted(
                result.review.findings if result else [], key=lambda f: -f.severity.rank
            )[:MAX_FINDINGS]
        ],
        omitted_files=[
            OmittedAudit(path=o.path, bytes=o.bytes) for o in record.omitted[:MAX_OMITTED]
        ],
        verdict=_VERDICTS[verdict],
        exit_code=record.exit_code,
        override_honoured=record.override_honoured,
        error=record.reason if verdict is Verdict.ERROR else None,
    )


def skipped_run(
    check: Check,
    *,
    context: RunContext,
    gate: GateInfo,
    reason: GateVerdict,
    at: datetime,
    risk: Risk | None = None,
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
        risk=risk,
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
# The feedback workflow adds the label for `/llm-override` with GITHUB_TOKEN, so it shows up as
# added by this bot; the person is then whoever wrote the command (a collaborator).
WORKFLOW_BOT = "github-actions[bot]"
TRUSTED_ASSOCIATIONS = frozenset({"OWNER", "MEMBER", "COLLABORATOR"})
# Repository roles that may override a gate (collaborators/<login>/permission, role_name).
# author_association is only a hint: MEMBER and COLLABORATOR don't imply write access.
WRITE_ROLES = frozenset({"admin", "maintain", "write"})


@dataclass(frozen=True)
class OverrideRequest:
    by: str | None
    reason: str


def find_override(
    events: Sequence[Mapping[str, Any]],
    comments: Sequence[Mapping[str, Any]],
    *,
    label: str = OVERRIDE_LABEL,
    writers: Collection[str] | None = None,
) -> OverrideRequest | str:
    """The reason for the PR's override label, or why there is none.

    `events` are the PR's issue events, `comments` its issue comments (GitHub REST shapes). The
    override counts only if whoever added the label most recently also wrote an unedited
    `/llm-override <reason>` comment for this round: after the label was last removed (any time,
    if it never was). Before or after adding it both work, so the comment can come first and the
    labelled run sees it. When the feedback workflow added the label (`/llm-override` as a
    command), the comment's author must instead be in `writers` (logins with a write, maintain or
    admin role, looked up by the caller), and is the one recorded. Either way the person must be in
    `writers`: labels can be applied with the triage role, which has no write access, so without
    the list no label is honoured at all (F007).
    """
    mine = [e for e in events if (e.get("label") or {}).get("name") == label]
    labelled = [e for e in mine if e.get("event") == "labeled"]
    if not labelled:
        return f"the {label} label was not added through the issue events API"
    labeller = (labelled[-1].get("actor") or {}).get("login")
    if not labeller:
        return f"cannot tell who added the {label} label"
    via_command = labeller == WORKFLOW_BOT
    labelled_at = parse_time(labelled[-1].get("created_at"))
    if labelled_at is None:
        return f"cannot tell when the {label} label was added"
    removals = [
        when
        for e in mine
        if e.get("event") == "unlabeled"
        and (when := parse_time(e.get("created_at"))) is not None
        and when <= labelled_at
    ]
    round_start = max(removals, default=None)
    for comment in reversed(comments):
        author = (comment.get("user") or {}).get("login")
        if via_command:
            if writers is None or author not in writers:
                continue
        elif author != labeller or writers is None or labeller not in writers:
            # Adding a label is the *triage* role, which has no write access, and `feedback.handle`
            # refuses a command from it. This path used to need no role at all, so the two paths
            # disagreed about the same person (F007).
            continue
        created = parse_time(comment.get("created_at"))
        # Only a comment written for this round counts (a reason from an earlier override doesn't
        # carry over), and only as written: an edit could change it after it was honoured.
        if created is None or (round_start is not None and created <= round_start):
            continue
        if parse_time(comment.get("updated_at")) != created:
            continue
        body = str(comment.get("body") or "").strip()
        first, _, _ = body.partition("\n")
        command, _, reason = first.partition(" ")
        if command == OVERRIDE_COMMAND and reason.strip() and author:
            return OverrideRequest(by=author, reason=reason.strip())
    if via_command:
        return (
            f"{label} came from `{OVERRIDE_COMMAND}`, but no one with write access wrote an "
            f"unedited `{OVERRIDE_COMMAND} <reason>` since it was last removed"
        )
    return (
        f"{labeller} added {label}, but no unedited `{OVERRIDE_COMMAND} <reason>` comment by them "
        "with write access followed, since the label was last removed"
    )


def parse_time(value: object) -> datetime | None:
    """A GitHub timestamp, or None when it is missing or unparseable."""
    try:
        return datetime.fromisoformat(str(value)) if value else None
    except ValueError:
        return None


# --- validating and collecting (trusted side) ---------------------------------------------------

# audit-<run_id>-<attempt>-<check>: with the attempt, a re-run of failed jobs doesn't hand the
# collector the earlier attempt's artifacts as if they were its own.
_ARTIFACT_NAME = re.compile(
    r"audit-(?P<run_id>[0-9]+)-(?P<attempt>[0-9]+)-(?P<check>[a-z0-9][a-z0-9-]{0,40})"
)


@dataclass(frozen=True)
class Expected:
    """What the collector knows about the triggering run from the event, not from the artifact."""

    repo: str
    workflow_run_id: int
    run_attempt: int
    head_sha: str
    pr: int
    server: str = "https://github.com"

    @property
    def run_url(self) -> str:
        run = f"{self.workflow_run_id}/attempts/{self.run_attempt}"
        return f"{self.server}/{self.repo}/actions/runs/{run}"


def validate_file(
    path: Path, expected: Expected, check: str | None = None
) -> tuple[list[AuditRecord], list[str]]:
    """Strictly parse an untrusted audit file. Returns the records and the problems found; any
    problem means none of the records may be written."""
    problems: list[str] = []
    if path.is_symlink() or not path.is_file():
        return [], [f"{AUDIT_FILE} is not a regular file"]
    try:
        size = path.stat().st_size
        if size > MAX_FILE_BYTES:
            return [], [f"{AUDIT_FILE} is {size} bytes, over the {MAX_FILE_BYTES} limit"]
        content = path.read_bytes()
    except OSError as error:
        return [], [f"cannot read {AUDIT_FILE} ({type(error).__name__})"]
    lines = [line for line in content.split(b"\n") if line.strip()]
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
            problems.append(f"{where}: not a valid {SCHEMA} record: {_describe(error)}")
            continue
        problems += [f"{where}: {p}" for p in _record_problems(record, expected, check)]
        records.append(record)
    ids = [r.id for r in records]
    if len(ids) != len(set(ids)):
        problems.append(f"{path.name}: duplicate record ids")
    return records, problems


# Tamper events never quote the artifact (it could say anything, and the log is permanent): only
# fixed messages, our own field names and pydantic's error codes.
_FIELD_NAMES = (
    frozenset(
        name
        for model in (
            GateRun,
            Triage,
            Override,
            Feedback,
            FeedbackRejected,
            RiskOverride,
            EvalRun,
            TamperSuspected,
            AuditFinding,
            TokenUsage,
            ToolCall,
        )
        for field, info in model.model_fields.items()
        for name in (field, info.alias)
        if name
    )
    | ARTIFACT_TYPES
    | {"triage", "feedback", "feedback_rejected", "risk_override", "eval_run", "tamper_suspected"}
)


def _describe(error: UnicodeDecodeError | ValidationError) -> str:
    if isinstance(error, UnicodeDecodeError):
        return "not UTF-8"
    parts: list[str] = []
    for item in error.errors(include_input=False, include_url=False, include_context=False)[:5]:
        if item["type"] == "extra_forbidden":
            parts.append("unexpected field")  # its name is the artifact's text
            continue
        loc = ".".join(
            str(part) if isinstance(part, int) or part in _FIELD_NAMES else "?"
            for part in item["loc"]
        )
        parts.append(f"{loc or 'record'}: {item['type']}")
    return "; ".join(parts)


def _record_problems(record: AuditRecord, expected: Expected, check: str | None) -> list[str]:
    problems: list[str] = []
    if record.type not in ARTIFACT_TYPES:
        problems.append(f"type {record.type!r} may not come from a PR's workflow")
    for field in ("repo", "workflow_run_id", "run_attempt", "head_sha", "pr", "run_url"):
        got, want = getattr(record, field), getattr(expected, field)
        if got != want:
            problems.append(f"{field} does not match the triggering run")
    if isinstance(record, GateRun):
        if check is not None and record.check != check:
            problems.append(f"check {record.check!r} in the artifact for {check!r}")
        prompt = f".claude/commands/llm-{record.check}.md"
        if record.prompt_file != prompt:
            problems.append(f"prompt_file is not {prompt}")
        if record.workflow_modified is not None or record.check_run_conclusion is not None:
            problems.append("sets fields only the collector may set")
        exits = VERDICT_EXITS[record.verdict]
        if record.override_honoured:
            # An override covers blocking findings, or a diff too large to review; both pass with
            # the reason on record (ADR 0002). No other verdict can carry one.
            exits = frozenset({0}) if record.verdict in ("fail", "error") else frozenset()
        if record.exit_code not in exits:
            override = " with override_honoured" if record.override_honoured else ""
            problems.append(f"verdict {record.verdict}{override} with exit code {record.exit_code}")
        # Blocking checks fail closed (ADR 0002), so a passing error needs an honoured override.
        # A blocking check configured `on_error: pass` would have to be allowed for here.
        # A blocking verdict is never restored from a cache: llm-review doesn't keep one, because
        # a PR's own workflow can write it (F002, ADR 0002). Defence in depth, so turning the cache
        # back on can't quietly make a forged entry into evidence again.
        if record.blocking and record.cache_hit:
            problems.append("a blocking check reports a cache hit; blocking reviews are not cached")
        passing_error = record.verdict == "error" and record.exit_code == 0
        if record.blocking and passing_error and not record.override_honoured:
            problems.append("a blocking check reports error with exit code 0 and no override")
        prefix = f"{finding_prefix(record.check)}-"
        if any(not f.id.startswith(prefix) for f in record.findings):
            problems.append(f"finding ids not of the form {prefix}xxxx")
    if isinstance(record, Override) and check is not None and record.checks != [check]:
        problems.append(f"an override in the artifact for {check!r} must name only that check")
    if isinstance(record, Triage):
        if check is not None and check != TRIAGE_ARTIFACT:
            problems.append(f"a triage record in the artifact for {check!r}")
        if record.reused_from_attempt is not None:
            problems.append("sets fields only the collector may set")
    return problems


def expected_conclusion(record: GateRun) -> str:
    return "success" if record.exit_code == 0 else "failure"


@dataclass(frozen=True)
class TriageExpected:
    """What the collector computed itself for the run's triage (ADR 0008): the floor from the
    compare API and the PR's commits, the manual risk from audit-log, and the checks plan of every
    level from the default branch's checks.yaml."""

    rules_risk: Risk
    ai_assisted: bool
    manual_required: Risk | None  # the latest /llm-risk written before the run started
    manual_allowed: frozenset[Risk]  # that one, and the latest at collection time
    plans: Mapping[Risk, Mapping[str, bool | None]]  # check -> blocking, None: not needed


type _RunTriage = Triage | Literal["absent", "invalid"]


def _triage_problems(
    records: Sequence[AuditRecord],
    expected: TriageExpected | None,
    jobs: Mapping[str, str | None],
    *,
    reused: bool = False,
) -> list[str]:
    triages = [r for r in records if isinstance(r, Triage)]
    if len(triages) != 1 or len(records) != 1:
        return ["the triage artifact must hold exactly one triage record"]
    # A reused record comes from an attempt whose jobs aren't in `jobs` (this attempt didn't run
    # triage at all), so its own attempt's conclusion can't be read here. Everything else about it
    # is still checked, including against the collector's own recomputation below.
    if not reused and jobs.get(TRIAGE_ARTIFACT) != "success":
        return [f"the triage job concluded {jobs.get(TRIAGE_ARTIFACT)}, so it can't be checked"]
    t = triages[0]
    if expected is None:
        return []
    problems: list[str] = []
    if t.rules_risk != expected.rules_risk:
        problems.append(f"rules_risk {t.rules_risk}, but the rules give {expected.rules_risk}")
    if t.ai_assisted != expected.ai_assisted:
        problems.append(f"ai_assisted {t.ai_assisted}, but the markers say {expected.ai_assisted}")
    if t.source == "manual":
        if t.final_risk not in expected.manual_allowed:
            problems.append(f"final_risk {t.final_risk}: no such /llm-risk in the log")
    elif expected.manual_required is not None:
        problems.append(f"ignores the /llm-risk {expected.manual_required} in the log")
    elif t.final_risk != highest([t.rules_risk, t.model_risk or "low"]):
        problems.append(f"final_risk {t.final_risk} is not the higher of rules and model risk")
    plan = sorted(n for n, b in expected.plans[t.final_risk].items() if b is not None)
    if t.checks_plan != plan:
        problems.append(f"checks_plan does not match risk {t.final_risk}")
    return problems


def _risk_problems(
    record: GateRun, run_triage: _RunTriage, expected: TriageExpected | None
) -> list[str]:
    """A gate_run must have run as the run's triage decided."""
    if run_triage == "invalid":
        return ["the run's triage record did not check out, so its risk can't be verified"]
    if run_triage == "absent":
        # A workflow from before triage (a PR branched earlier). Dropping the triage job on
        # purpose means changing the workflow, which the collector flags anyway.
        return ["risk is set, but the run has no triage record"] if record.risk else []
    if record.risk != run_triage.final_risk:
        return [f"risk {record.risk}, but the run's triage says {run_triage.final_risk}"]
    if record.verdict == "skipped_no_key":
        return []
    if expected is not None:
        blocking = expected.plans[run_triage.final_risk].get(record.check)
        needed = blocking is not None
    else:
        blocking, needed = None, record.check in run_triage.checks_plan
    if needed == (record.verdict == "not_needed"):
        wanted = "runs" if needed else "is not needed"
        return [f"{record.check} {wanted} at risk {run_triage.final_risk}, but: {record.verdict}"]
    if needed and blocking is not None and record.blocking != blocking:
        return [f"blocking {record.blocking}, but at risk {run_triage.final_risk} it is {blocking}"]
    return []


@dataclass(frozen=True)
class Collected:
    path: str  # relative to the output directory, e.g. events/2026/10/16/123-1-code-review.jsonl
    artifact: str
    records: int
    tamper: bool


def _with_reused_triage(
    directories: Sequence[Path], expected: Expected
) -> tuple[list[Path], int | None]:
    """The artifacts to collect, and the attempt a reused triage artifact came from.

    GitHub's "Re-run failed jobs" starts a new attempt for the failed jobs only, so a successful
    `triage` job is not re-run and the new attempt has no triage artifact: every gate_run that
    carries a risk would then be rejected ("the run has no triage record") and recorded as a
    tamper event. When that is the case, the latest earlier attempt's triage artifact is collected
    instead, validated against its own attempt and marked `reused_from_attempt`. Only triage is
    reusable, because only triage is not re-run; any other artifact keeps being checked against
    the current attempt, so a stray one is still flagged.
    """
    earlier: list[tuple[int, Path]] = []
    for path in directories:
        match = _ARTIFACT_NAME.fullmatch(path.name)
        if (
            match is not None
            and int(match["run_id"]) == expected.workflow_run_id
            and match["check"] == TRIAGE_ARTIFACT
            and int(match["attempt"]) < expected.run_attempt
        ):
            earlier.append((int(match["attempt"]), path))
    current = f"audit-{expected.workflow_run_id}-{expected.run_attempt}-{TRIAGE_ARTIFACT}"
    if not earlier or any(p.name == current for p in directories):
        # Nothing to reuse, or this attempt ran triage itself: leave every artifact to the usual
        # checks, including earlier ones, which are flagged by name as before.
        return list(directories), None
    attempt, chosen = max(earlier)
    others = {path for _, path in earlier} - {chosen}
    return [p for p in directories if p not in others], attempt


class JobsNotFinished(Exception):
    """The triggering run's jobs have no conclusion yet, so nothing can be confirmed or written.

    Not tampering: right after `workflow_run: completed` the Actions API can still report
    `conclusion: null` for jobs that finished moments before, and on 2026-10-19 it did for minutes.
    Collecting then wrote `tamper_suspected` into the very paths the real records belonged in, and
    the append-only log kept them (#92, #93; ADR 0005). Failing instead leaves the paths free, so a
    re-run of the collector records the run properly."""


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
    triage: TriageExpected | None = None,
) -> list[Collected]:
    """Validate every `audit-<run_id>-<attempt>-<check>` artifact directory under `artifacts`
    and write one file per artifact under `out/events/YYYY/MM/DD/`. `jobs` maps job names of the
    triggering run to their conclusions (Actions API); `checks` are the checks in the default
    branch's checks.yaml; `override` is `find_override` on the PR's issue events and comments as
    the collector fetched them (or why there is none). Raises `JobsNotFinished`, before anything
    is written, if any of those jobs has no conclusion yet."""
    unfinished = sorted(name for name, conclusion in jobs.items() if conclusion is None)
    if unfinished:
        raise JobsNotFinished(f"no conclusion yet for: {', '.join(unfinished)}")
    folder = Path("events", f"{day:%Y}", f"{day:%m}", f"{day:%d}")
    prefix = f"{expected.workflow_run_id}-{expected.run_attempt}"
    directories = sorted(p for p in artifacts.iterdir() if p.is_dir())
    problem = None
    if len(directories) > MAX_ARTIFACTS:
        problem = f"{len(directories)} artifacts, over the {MAX_ARTIFACTS} limit; none collected"
    elif (size := _total_bytes(directories)) > MAX_RUN_BYTES:
        problem = f"{size} bytes of artifacts, over the {MAX_RUN_BYTES} limit; none collected"
    if problem:
        target = folder / f"{prefix}-too-much.jsonl"
        _write(out / target, [_tamper(expected, "(all)", [problem])])
        return [Collected(target.as_posix(), "(all)", 1, tamper=True)]

    directories, reused_attempt = _with_reused_triage(directories, expected)
    # The triage artifact first: every gate_run of the run is checked against it.
    directories.sort(key=lambda p: (not p.name.endswith(f"-{TRIAGE_ARTIFACT}"), p.name))
    run_triage: _RunTriage = "absent"
    collected: list[Collected] = []
    for index, directory in enumerate(directories):
        name = directory.name
        match = _ARTIFACT_NAME.fullmatch(name)
        safe_name = name if match else "(invalid name)"  # never echo an arbitrary name
        problems: list[str] = []
        records: list[AuditRecord] = []
        # A reused triage artifact is checked against its own attempt; everything else against
        # the attempt that triggered the collection.
        reused = reused_attempt is not None and name.endswith(
            f"-{reused_attempt}-{TRIAGE_ARTIFACT}"
        )
        want_expected = expected
        if reused and reused_attempt is not None:
            want_expected = replace(expected, run_attempt=reused_attempt)
        if (
            match is None
            or int(match["run_id"]) != expected.workflow_run_id
            or int(match["attempt"]) != want_expected.run_attempt
        ):
            check = f"invalid-{index}"
            want = f"audit-{expected.workflow_run_id}-{expected.run_attempt}-<check>"
            problems.append(f"artifact name is not {want}")
        elif match["check"] not in checks and match["check"] != TRIAGE_ARTIFACT:
            check = f"invalid-{index}"
            problems.append(
                f"{match['check']!r} is not a check in the default branch's checks.yaml"
            )
        else:
            check = match["check"]
            try:
                files = sorted(p.name for p in directory.iterdir())
                if files != [AUDIT_FILE]:
                    problems.append(f"expected only {AUDIT_FILE}, found {len(files)} file(s)")
                else:
                    records, problems = validate_file(directory / AUDIT_FILE, want_expected, check)
            except Exception as error:  # one bad artifact must not stop the rest
                problems.append(f"the collector could not process it ({type(error).__name__})")

        finished: list[AuditRecord] = []
        if check == TRIAGE_ARTIFACT:
            if not problems:
                problems += _triage_problems(records, triage, jobs, reused=reused)
            if not problems and isinstance(records[0], Triage) and reused:
                records = [records[0].model_copy(update={"reused_from_attempt": reused_attempt})]
            run_triage = (
                records[0] if not problems and isinstance(records[0], Triage) else "invalid"
            )
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
                    problems += _risk_problems(record, run_triage, triage)
                    record = record.model_copy(
                        update={
                            "workflow_modified": workflow_modified,
                            "check_run_conclusion": conclusion,
                        }
                    )
                finished.append(_withhold(record) if workflow_modified else record)

        target = folder / f"{prefix}-{check}.jsonl"
        if problems:
            finished = [_tamper(expected, safe_name, problems)]
        _write(out / target, finished)
        collected.append(
            Collected(target.as_posix(), safe_name, len(finished), tamper=bool(problems))
        )
    return collected


WITHHELD = "[withheld: the PR modified the review workflow]"


def _withhold(record: AuditRecord) -> AuditRecord:
    """Keep only the structure of a record from a run whose workflow the PR changed: its free
    text could say anything, and the log is permanent."""
    if isinstance(record, GateRun):
        return record.model_copy(
            update={
                "findings": [
                    f.model_copy(update={"category": WITHHELD, "file": WITHHELD, "title": WITHHELD})
                    for f in record.findings
                ],
                "tool_calls": [c.model_copy(update={"input": ""}) for c in record.tool_calls],
                "error": WITHHELD if record.error else None,
            }
        )
    if isinstance(record, Override):
        return record.model_copy(update={"reason": WITHHELD})
    if isinstance(record, Triage):
        return record.model_copy(
            update={
                "reasons": [WITHHELD] if record.reasons else [],
                "error": WITHHELD if record.error else None,
            }
        )
    return record


def _total_bytes(directories: Iterable[Path]) -> int:
    return sum(f.lstat().st_size for d in directories for f in d.iterdir() if not f.is_symlink())


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
        elif isinstance(record, GateRun) and isinstance(trusted, str):
            if record.override_honoured:
                problems.append(f"{record.check}: override honoured, but the collector found none")
            # A blocking check reviews a partial diff only under an override (ADR 0002), so the
            # collector must have found one itself; `omitted_files` alone can't vouch for that.
            elif record.blocking and record.omitted_files:
                problems.append(
                    f"{record.check}: {len(record.omitted_files)} file(s) omitted from a blocking "
                    "review, but the collector found no override"
                )
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

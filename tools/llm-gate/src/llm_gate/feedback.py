"""`/llm-*` PR comment commands (docs/PLAN-v2.md Phase 16): feedback on findings, overrides with a
reason, manual risk. `llm-feedback.yml` runs this on the default branch's code for every new PR
comment that starts with `/llm-`; the comment is untrusted input and is only parsed here.

| Command                          | Record                    | Workflow action                   |
|----------------------------------|---------------------------|-----------------------------------|
| /llm-fp <finding-id> <reason>    | feedback (kind fp)        | marks the finding's row           |
| /llm-ack <finding-id> [<reason>] | feedback (kind ack)       |                                   |
| /llm-override <reason>           | override                  | adds llm-override, re-runs review |
| /llm-risk <level> <reason>       | risk_override             | re-runs review (triage uses it)   |

Only people with a write, maintain or admin role are heard (the workflow looks the role up;
outsiders never start it). A collaborator without that role, and any command that doesn't parse or
names an unknown finding, becomes one `feedback_rejected` record.
"""

import json
import re
from collections.abc import Collection, Mapping
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import ValidationError

from . import audit
from .redact import clip, redact

PREFIX = "/llm-"
RISK_LEVELS = ("low", "medium", "high")
_FINDING_ID = re.compile(r"^[a-z]{1,8}-[0-9a-f]{4}$")


@dataclass(frozen=True)
class Command:
    name: Literal["fp", "ack", "override", "risk"]
    finding_id: str | None = None
    level: str | None = None
    reason: str | None = None


@dataclass(frozen=True)
class Rejection:
    command: audit.FeedbackCommand
    code: audit.RejectionCode


def parse_command(body: str) -> Command | Rejection:
    """The first line of a comment as a command. Arguments are separated by whitespace; the reason
    is the rest of the line."""
    first = body.strip().partition("\n")[0].strip()
    if not first.startswith(PREFIX):
        return Rejection("unknown", "unknown_command")
    word, _, rest = first.partition(" ")
    name = word.removeprefix(PREFIX)
    rest = rest.strip()
    if name in ("fp", "ack"):
        kind: Literal["fp", "ack"] = "fp" if name == "fp" else "ack"
        finding_id, _, reason = rest.partition(" ")
        finding_id, reason = finding_id.strip(), reason.strip()
        if not _FINDING_ID.fullmatch(finding_id) or (kind == "fp" and not reason):
            return Rejection(kind, "bad_arguments")
        return Command(kind, finding_id=finding_id, reason=reason or None)
    if name == "override":
        return Command("override", reason=rest) if rest else Rejection("override", "bad_arguments")
    if name == "risk":
        level, _, reason = rest.partition(" ")
        if level not in RISK_LEVELS or not reason.strip():
            return Rejection("risk", "bad_arguments")
        return Command("risk", level=level, reason=reason.strip())
    return Rejection("unknown", "unknown_command")


@dataclass
class Actions:
    """What the workflow does after the record is written. `path` is where the record goes on the
    audit-log branch; for outsiders it is one file per PR, person and day, so repeats are refused
    by the contents API instead of filling the log."""

    path: str
    recorded: bool
    reaction: Literal["+1", "confused"] | None
    label: str | None = None
    rerun: bool = False
    mark: dict[str, str] | None = None  # {"check", "finding_id", "by"} for /llm-fp
    message: str = ""
    records: list[str] = field(default_factory=list)  # JSON lines, also written to the out dir

    def to_json(self) -> str:
        return json.dumps(asdict(self))


def find_finding(audit_dir: Path, pr: int, finding_id: str) -> str | None:
    """The check of a finding reported on this PR, from the audit log's gate_run records."""
    for path in sorted(audit_dir.glob("events/**/*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if record.get("type") != "gate_run" or record.get("pr") != pr:
                continue
            if any(f.get("id") == finding_id for f in record.get("findings", [])):
                return str(record["check"])
    return None


def current_risk(audit_dir: Path, pr: int) -> str:
    """The final risk of the PR's latest triage record, or `unknown` if it has none yet."""
    latest: tuple[str, str] | None = None
    for path in sorted(audit_dir.glob("events/**/*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if record.get("type") != "triage" or record.get("pr") != pr:
                continue
            found = (str(record.get("ts")), str(record.get("final_risk")))
            if latest is None or found[0] >= latest[0]:
                latest = found
    return latest[1] if latest and latest[1] in RISK_LEVELS else "unknown"


def handle(
    event: Mapping[str, Any],
    *,
    audit_dir: Path,
    blocking_checks: Collection[str],
    context: audit.RunContext,
    now: datetime,
    permission: str | None = None,
) -> Actions:
    """Validate a comment event and build its record and actions. Never raises on bad input: every
    outcome is a record (or, for an unparseable author, nothing at all). `permission` is the
    commenter's repository role (role_name from collaborators/<login>/permission): only write,
    maintain and admin are heard; author_association alone isn't enough."""
    issue = event.get("issue") or {}
    comment = event.get("comment") or {}
    pr = issue.get("number")
    login = (comment.get("user") or {}).get("login") or ""
    day = f"{now:%Y}/{now:%m}/{now:%d}"
    comment_id = comment.get("id")
    base = context.model_copy(update={"pr": pr if isinstance(pr, int) else None})

    def reject(
        command: audit.FeedbackCommand, code: audit.RejectionCode, *, outsider: bool
    ) -> Actions:
        # Outsiders: one file per PR, person and day (a repeat is refused, not appended).
        safe_login = re.sub(r"[^a-z0-9-]", "-", login.lower())  # dependabot[bot] -> dependabot-bot-
        name = f"feedback-rejected-{pr}-{safe_login}" if outsider else f"feedback-{comment_id}"
        try:
            record = audit.FeedbackRejected(
                **base.model_dump(), by=login, command=command, code=code
            )
        except ValidationError:
            return Actions(path="", recorded=False, reaction=None, message="unusable author")
        return Actions(
            path=f"events/{day}/{name}.jsonl",
            recorded=False,
            reaction=None if outsider else "confused",
            message=f"{command}: {code}",
            records=[audit.dumps(record)],
        )

    if not issue.get("pull_request") or not isinstance(pr, int) or not isinstance(comment_id, int):
        return Actions(path="", recorded=False, reaction=None, message="not a PR comment")
    if comment.get("author_association") not in audit.TRUSTED_ASSOCIATIONS:
        parsed = parse_command(str(comment.get("body") or ""))
        command = parsed.name if isinstance(parsed, Command) else parsed.command
        return reject(command, "not_a_collaborator", outsider=True)
    if permission not in audit.WRITE_ROLES:
        parsed = parse_command(str(comment.get("body") or ""))
        command = parsed.name if isinstance(parsed, Command) else parsed.command
        return reject(command, "not_a_collaborator", outsider=False)

    parsed = parse_command(str(comment.get("body") or ""))
    if isinstance(parsed, Rejection):
        return reject(parsed.command, parsed.code, outsider=False)

    path = f"events/{day}/feedback-{comment_id}.jsonl"
    reason = clip(redact(parsed.reason), 500) if parsed.reason else None
    actions = Actions(path=path, recorded=True, reaction="+1", message=parsed.name)
    if parsed.name in ("fp", "ack"):
        assert parsed.finding_id is not None  # noqa: S101  # parse_command guarantees it
        check = find_finding(audit_dir, pr, parsed.finding_id)
        if check is None:
            return reject(parsed.name, "unknown_finding", outsider=False)
        record: audit.Feedback | audit.Override | audit.RiskOverride = audit.Feedback(
            **base.model_dump(),
            finding_id=parsed.finding_id,
            check=check,
            kind=parsed.name,
            by=login,
            reason=reason,
        )
        if parsed.name == "fp":
            actions.mark = {"check": check, "finding_id": parsed.finding_id, "by": login}
    elif parsed.name == "override":
        record = audit.Override(
            **base.model_dump(), by=login, reason=reason or "", checks=sorted(blocking_checks)
        )
        actions.label = audit.OVERRIDE_LABEL
        actions.rerun = True
    else:
        record = audit.RiskOverride.model_validate(
            {
                **base.model_dump(),
                "from": current_risk(audit_dir, pr),
                "to": parsed.level,
                "by": login,
                "reason": reason,
            }
        )
        actions.rerun = True  # triage reads the new record from audit-log (ADR 0008)
    actions.records = [audit.dumps(record)]
    return actions


def mark_false_positive(body: str, finding_id: str, by: str) -> str | None:
    """The sticky comment with the finding's table row marked, or None if the row isn't there or
    is marked already. The next review run rewrites the comment; the record stays in the log."""
    tag = f"`{finding_id}`"
    note = f" _(false positive: @{by})_"
    lines = body.split("\n")
    for index, line in enumerate(lines):
        if line.startswith("|") and tag in line and line.rstrip().endswith("|"):
            if "_(false positive:" in line:
                return None
            lines[index] = line.rstrip()[:-1].rstrip() + note + " |"
            return "\n".join(lines)
    return None

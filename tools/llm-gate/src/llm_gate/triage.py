"""Risk triage (docs/PLAN-v2.md 17.2, ADR 0008): how much review a PR needs.

1. **Floor**, deterministic (`floor`): every changed file gets the risk of its first matching
   rule in checks.yaml `triage.rules` (`default_risk` if none), the PR the maximum; the size of
   the change can raise it, and so can AI assistance (`ai_assisted_raise`). The collector
   recomputes it from the GitHub API, so a PR's workflow can't lower it unnoticed.
2. **Model** (`assess`): a cheap model reads the file list and the diff and may raise the risk,
   never lower it. A failure leaves the floor.
3. **People** (`/llm-risk`, `latest_risk_override`): a recorded manual change wins, in either
   direction.

The level then decides which checks run, which block, and with what engine and model
(`plan_for`).
"""

import hashlib
import json
import logging
import re
import subprocess
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from .config import RISKS, Check, Risk, TriageConfig
from .diff import EXCLUDES, DiffError
from .engines import EngineError
from .prompts import diff_block, load_prompt, render

log = logging.getLogger(__name__)

_RANK: dict[str, int] = {risk: index for index, risk in enumerate(RISKS)}


def rank(risk: Risk) -> int:
    return _RANK[risk]


def highest(risks: Iterable[Risk]) -> Risk:
    return max(risks, key=rank, default="low")


def raise_by(risk: Risk, levels: int) -> Risk:
    return RISKS[min(len(RISKS) - 1, max(0, rank(risk) + levels))]


# --- floor -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class FileChange:
    path: str
    lines: int  # added + deleted (0 for binary files)
    old_path: str | None = None  # a rename's source: rated too, so a move can't launder a path


def counts_for_size(path: str) -> bool:
    """Lock files and generated code move the size needle without being reviewed (diff.py)."""
    return not any(PurePosixPath(path).full_match(pattern) for pattern in EXCLUDES)


def numstat(root: Path, base: str) -> list[FileChange]:
    """Every changed file since HEAD branched off `base`, lock files included (they matter to the
    rules). Renames count under their new path, as in GitHub's compare API."""
    try:
        out = subprocess.run(
            ["git", "diff", "--numstat", "-z", "-M", "--merge-base", base, "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    except subprocess.CalledProcessError as error:
        raise DiffError(f"git diff --numstat failed: {error.stderr.strip()}") from error
    return parse_numstat(out)


def parse_numstat(out: str) -> list[FileChange]:
    fields = out.split("\0")
    changes: list[FileChange] = []
    index = 0
    while index < len(fields) and fields[index]:
        added, deleted, path = fields[index].split("\t", 2)
        index += 1
        old: str | None = None
        if not path:  # a rename: the old and the new path follow as fields of their own
            old, path = fields[index], fields[index + 1]
            index += 2
        lines = 0 if added == "-" else int(added) + int(deleted)
        changes.append(FileChange(path, lines, old))
    return changes


def changes_from_patch(patch: str) -> list[FileChange]:
    """Changed files and their added + deleted lines, from a unified diff (eval cases)."""
    counts: dict[str, int] = {}
    renamed: dict[str, str] = {}
    current: str | None = None
    for line in patch.splitlines():
        if line.startswith("diff --git "):
            current = line.rsplit(" b/", 1)[-1]
            counts.setdefault(current, 0)
        elif current is None or line.startswith(("+++ ", "--- ")):
            continue
        elif line.startswith("rename from "):
            renamed[current] = line.removeprefix("rename from ")
        elif line.startswith(("+", "-")):
            counts[current] += 1
    return [FileChange(path, lines, renamed.get(path)) for path, lines in counts.items()]


def changes_from_compare(files: Sequence[Mapping[str, Any]]) -> list[FileChange]:
    """`gh api repos/R/compare/BASE...HEAD --jq .files` → FileChange (the collector's side)."""
    return [
        FileChange(
            str(f["filename"]),
            int(f.get("additions") or 0) + int(f.get("deletions") or 0),
            str(f["previous_filename"]) if f.get("previous_filename") else None,
        )
        for f in files
    ]


@dataclass(frozen=True)
class Floor:
    risk: Risk
    reasons: list[str]  # fixed text from checks.yaml and counts: never PR content
    lines: int


def rule_risk(path: str, config: TriageConfig) -> tuple[Risk, str]:
    for rule in config.rules:
        if any(PurePosixPath(path).full_match(pattern) for pattern in rule.paths):
            return rule.risk, rule.reason
    return config.default_risk, "matches no triage rule"


def floor(changes: Sequence[FileChange], *, ai_assisted: bool, config: TriageConfig) -> Floor:
    if not changes:
        return Floor("low", ["no changes"], 0)
    by_reason: dict[tuple[Risk, str], int] = {}
    for change in changes:
        key = rule_risk(change.path, config)
        if change.old_path is not None:  # a move out of a riskier place keeps that risk
            source = rule_risk(change.old_path, config)
            if rank(source[0]) > rank(key[0]):
                key = (source[0], f"{source[1]} (renamed away)")
        by_reason[key] = by_reason.get(key, 0) + 1
    risk = highest(r for r, _ in by_reason)
    reasons = [
        f"{risk_}: {reason} ({count} file{'s' if count != 1 else ''})"
        for (risk_, reason), count in sorted(by_reason.items(), key=lambda kv: -rank(kv[0][0]))
    ]
    lines = sum(c.lines for c in changes if counts_for_size(c.path))
    if lines > config.high_over_lines:
        size: Risk = "high"
    elif lines > config.medium_over_lines:
        size = "medium"
    else:
        size = "low"
    if rank(size) > rank(risk):
        reasons.append(f"{size}: {lines} changed lines")
        risk = size
    if ai_assisted and config.ai_assisted_raise:
        raised = raise_by(risk, config.ai_assisted_raise)
        if raised != risk:
            reasons.append(f"{raised}: AI-assisted, raised from {risk}")
        risk = raised
    return Floor(risk, reasons, lines)


# --- the model ---------------------------------------------------------------------------------


class TriageAssessment(BaseModel):
    """What the triage model returns."""

    risk: Literal["low", "medium", "high"] = Field(
        description="Risk level from the rubric in the instructions"
    )
    # No max_length: the API doesn't enforce maxItems (transform_schema only mentions it in the
    # description), so a cap here would turn a verbose model into a failed triage. Callers take
    # the first three.
    reasons: list[str] = Field(
        description="At most three short reasons for the level, each one line"
    )


@dataclass(frozen=True)
class ModelRisk:
    risk: Risk | None  # None: no assessment (no key, API error); the floor stands
    reasons: list[str]
    model: str
    cost_usd: float | None
    cached: bool
    error: str | None = None


TRIAGE_CACHE_VERSION = "1"


class _CacheEntry(BaseModel):
    assessment: TriageAssessment
    model: str
    cost_usd: float | None = None


def _cache_path(cache_dir: Path | None, key: str) -> Path | None:
    return cache_dir / f"triage-{key}.json" if cache_dir else None


def user_content(changes: Sequence[FileChange], diff_text: str, base: str, max_kb: int) -> str:
    listing = "\n".join(
        f"{f'{c.old_path} -> ' if c.old_path else ''}{c.path} ({c.lines} lines)" for c in changes
    )
    listing = listing or "(none)"
    limit = max_kb * 1024
    data = diff_text.encode("utf-8")
    truncated = len(data) > limit
    text = data[:limit].decode("utf-8", errors="ignore") if truncated else diff_text
    note = f"\n[diff truncated at {max_kb} KB]" if truncated else ""
    return f"Changed files:\n<files>\n{listing}\n</files>\n\n{diff_block(base, text + note)}"


def assess(
    config: TriageConfig,
    changes: Sequence[FileChange],
    diff_text: str,
    *,
    base: str,
    cache_dir: Path | None,
    client: Any | None = None,
    cache_salt: str = "",
) -> ModelRisk:
    """The model's risk. Never raises: a failure is recorded and the floor stands."""
    from .engines.api_engine import estimate_cost, structured_call

    prompt = load_prompt(config.prompt_path)
    system = render(prompt, "the file list and the unified diff in the elements below")
    user = user_content(changes, diff_text, base, config.max_diff_kb)
    key = hashlib.sha256(
        json.dumps([TRIAGE_CACHE_VERSION, config.model, system, user, cache_salt]).encode()
    ).hexdigest()
    path = _cache_path(cache_dir, key)
    if path and path.is_file():
        try:
            hit = _CacheEntry.model_validate_json(path.read_text(encoding="utf-8"))
            a = hit.assessment
            return ModelRisk(a.risk, a.reasons[:3], hit.model, hit.cost_usd, cached=True)
        except OSError, ValidationError:
            pass  # a stale entry: ask again
    try:
        response, parsed = structured_call(
            client,
            model=config.model,
            system=system,
            user=user,
            output_format=TriageAssessment,
            what="triage",
            max_tokens=2_000,
        )
    except EngineError as error:
        log.warning("triage model: %s; the rules' risk stands", error)
        return ModelRisk(None, [], config.model, None, cached=False, error=str(error))
    usage = response.usage
    model = str(response.model)
    cost = estimate_cost(model, usage.input_tokens, usage.output_tokens)
    if path:
        path.parent.mkdir(parents=True, exist_ok=True)
        entry = _CacheEntry(assessment=parsed, model=model, cost_usd=cost)
        path.write_text(entry.model_dump_json(), encoding="utf-8")
    return ModelRisk(parsed.risk, parsed.reasons[:3], model, cost, cached=False)


# --- manual changes and the result -------------------------------------------------------------


@dataclass(frozen=True)
class ManualRisk:
    to: Risk
    by: str
    reason: str
    ts: datetime
    comment_id: int | None = None  # the `/llm-risk` comment, from the record's file name


# How far a record's `ts` may run ahead of this machine's clock before it is ignored. Records are
# written by a workflow, so a few minutes of skew is normal; a year is not.
TS_SKEW = timedelta(minutes=10)


def risk_overrides(audit_dir: Path | None, pr: int | None) -> list[ManualRisk]:
    """Every usable `/llm-risk` record for the PR, oldest first.

    `llm-feedback.yml` writes these after checking the commenter's role, and the collector refuses
    them from a PR's own artifact (`audit.ARTIFACT_TYPES`). Anyone with `contents: write` can still
    append a file to the branch (ADR 0005), so this is deliberately defensive: a line that isn't a
    JSON object, or a record whose fields don't fit, is skipped rather than fatal (a bare `[]` used
    to crash triage for every PR), and a `ts` in the future is ignored so a forged record can't
    outrank every genuine one. The collector checks each record against the comment it came from
    and flags the ones that don't match (`audit.verified_risk_overrides`).
    """
    if audit_dir is None or pr is None:
        return []
    cutoff = datetime.now(UTC) + TS_SKEW
    found: list[ManualRisk] = []
    for path in sorted(audit_dir.glob("events/**/*.jsonl")):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if not isinstance(record, dict):
                continue
            if record.get("type") != "risk_override" or record.get("pr") != pr:
                continue
            to, by, reason = record.get("to"), record.get("by"), record.get("reason")
            if to not in RISKS or not isinstance(by, str) or not isinstance(reason, str):
                continue
            try:
                ts = datetime.fromisoformat(str(record.get("ts")))
            except ValueError:
                continue
            if ts.tzinfo is None or ts > cutoff:
                continue
            found.append(ManualRisk(to, by, reason, ts, comment_id=_comment_id(path)))
    found.sort(key=lambda m: m.ts)
    return found


def _comment_id(path: Path) -> int | None:
    """The comment a record came from: llm-feedback.yml writes `feedback-<comment_id>.jsonl`."""
    match = re.fullmatch(r"feedback-(\d+)", path.stem)
    return int(match[1]) if match else None


def latest_risk_override(
    audit_dir: Path | None, pr: int | None, *, before: datetime | None = None
) -> ManualRisk | None:
    """The PR's latest `/llm-risk` (written before `before`, if given)."""
    usable = [m for m in risk_overrides(audit_dir, pr) if before is None or m.ts <= before]
    return usable[-1] if usable else None


@dataclass(frozen=True)
class Decision:
    final: Risk
    source: Literal["rules", "model", "manual"]


def final_risk(rules: Risk, model: Risk | None, manual: ManualRisk | None) -> Decision:
    if manual is not None:
        return Decision(manual.to, "manual")
    if model is not None and rank(model) > rank(rules):
        return Decision(model, "model")
    return Decision(rules, "rules")


def plan_for(
    level: Risk, config: TriageConfig, checks: Mapping[str, Check]
) -> dict[str, Check | None]:
    """Every check at this risk level: None when it isn't needed, else the check as it runs here
    (advisory unless the level blocks on it; the level's engine and model for blocking ones)."""
    spec = config.levels[level]
    plan: dict[str, Check | None] = {}
    for name, check in checks.items():
        if name not in spec.run:
            plan[name] = None
        elif name in spec.blocking:
            plan[name] = replace(
                check, engine=spec.engine or check.engine, model=spec.model or check.model
            )
        else:
            plan[name] = replace(check, mode="advisory", fail_on=None)
    return plan


def checks_plan(level: Risk, config: TriageConfig, checks: Mapping[str, Check]) -> list[str]:
    return sorted(name for name, check in plan_for(level, config, checks).items() if check)

"""The review schema both engines must return (structured output) and the result types around it."""

import hashlib
import re
from enum import StrEnum

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from .redact import Summary


class Severity(StrEnum):
    """Ordered from least to most severe; the prompts define what each level means."""

    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

    @property
    def rank(self) -> int:
        return list(Severity).index(self)

    def at_least(self, other: Severity) -> bool:
        return self.rank >= other.rank


class Finding(BaseModel):
    severity: Severity = Field(description="Severity from the rubric in the instructions")
    category: str = Field(
        description="Short kebab-case kind of problem, e.g. off-by-one, input-validation, secrets"
    )
    file: str = Field(description="Repository-relative path of the file the finding is about")
    line: int | None = Field(
        description="Line number in the new version of the file, or null if not line-specific"
    )
    title: str = Field(description="One-line statement of the problem")
    detail: str = Field(description="What is wrong and why it matters, in a few sentences")
    suggestion: str | None = Field(description="How to fix it, or null")


def finding_id(check: str, finding: Finding) -> str:
    """Short, stable id people can refer to (`cr-3f2a`): check initials plus a hash of check, file
    and the title's words, so a re-run that rewords nothing but punctuation keeps the id."""
    prefix = "".join(part[0] for part in check.split("-") if part) or "x"
    words = " ".join(re.findall(r"[a-z0-9]+", finding.title.lower()))
    digest = hashlib.sha256(f"{check}\n{finding.file}\n{words}".encode()).hexdigest()
    return f"{prefix}-{digest[:4]}"


class Review(BaseModel):
    """What the model returns. Deliberately no free-form reasoning field: the verdict comes from
    severities in code, and `detail` carries the short explanation per finding."""

    summary: str = Field(description="Two or three sentences: what the change does, overall view")
    findings: list[Finding] = Field(description="One entry per distinct issue; empty if none")


class Usage(BaseModel):
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None
    cost_estimated: bool = False  # computed from list prices rather than reported by the SDK
    num_turns: int | None = None


class ToolCall(BaseModel):
    """One tool call of the agent engine, as logged by its PreToolUse hook. `input` is a short,
    redacted summary (audit.summarise_tool_input), never the full tool input."""

    model_config = ConfigDict(extra="forbid")

    tool: str
    input: Summary
    ts: AwareDatetime


class EngineResult(BaseModel):
    engine: str
    model: str  # the model that actually answered (a refusal fallback can change it)
    review: Review
    duration_ms: int
    usage: Usage = Field(default_factory=Usage)
    tool_calls: list[ToolCall] = Field(default_factory=list)

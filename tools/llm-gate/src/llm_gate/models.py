"""The review schema both engines must return (structured output) and the result types around it."""

from enum import StrEnum

from pydantic import BaseModel, Field


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


class EngineResult(BaseModel):
    engine: str
    model: str  # the model that actually answered (a refusal fallback can change it)
    review: Review
    duration_ms: int
    usage: Usage = Field(default_factory=Usage)

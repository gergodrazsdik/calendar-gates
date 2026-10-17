"""Load and validate checks.yaml, expanding ${VAR:-default} from the environment."""

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .models import Severity

EngineName = Literal["api", "agent"]
Mode = Literal["blocking", "advisory"]
OnError = Literal["fail", "pass"]
Risk = Literal["low", "medium", "high"]

ENGINES: tuple[EngineName, ...] = ("api", "agent")
RISKS: tuple[Risk, ...] = ("low", "medium", "high")  # in order
TRIAGE = "triage"  # the triage prompt is .claude/commands/llm-triage.md; never a check name
_VAR = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


class ConfigError(Exception):
    pass


class _Defaults(BaseModel):
    model_config = ConfigDict(extra="forbid")

    engine: EngineName = "api"
    model: str
    max_diff_kb: int = 200
    max_file_kb: int = 64
    budget_usd: float = 0.50
    max_turns: int = 30
    on_error: OnError = "fail"


class _CheckSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Mode
    fail_on: Severity | None = None
    engine: EngineName | None = None
    model: str | None = None
    paths: list[str] | None = None
    max_diff_kb: int | None = None
    max_file_kb: int | None = None
    budget_usd: float | None = None
    max_turns: int | None = None
    on_error: OnError | None = None

    @model_validator(mode="after")
    def _fail_on_matches_mode(self) -> _CheckSpec:
        if self.mode == "blocking" and self.fail_on is None:
            raise ValueError("a blocking check needs fail_on")
        if self.mode == "advisory" and self.fail_on is not None:
            raise ValueError("an advisory check never fails, so fail_on makes no sense")
        return self


class _Rule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    paths: list[str] = Field(min_length=1)
    risk: Risk
    reason: str


class _Size(BaseModel):
    model_config = ConfigDict(extra="forbid")

    medium_over_lines: int = Field(gt=0)
    high_over_lines: int = Field(gt=0)


class _Level(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run: list[str] | Literal["all"]
    blocking: list[str] = Field(default_factory=list)
    # For the level's blocking checks only; advisory checks keep their own engine and model.
    engine: EngineName | None = None
    model: str | None = None


class _Triage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str
    max_diff_kb: int = 50  # what the triage model sees of the diff; the floor sees all of it
    default_risk: Risk = "medium"
    rules: list[_Rule]
    size: _Size
    ai_assisted_raise: int = Field(default=1, ge=0, le=2)
    levels: dict[Risk, _Level]

    @model_validator(mode="after")
    def _every_level(self) -> _Triage:
        missing = [risk for risk in RISKS if risk not in self.levels]
        if missing:
            raise ValueError(f"triage.levels needs {', '.join(missing)}")
        if self.size.medium_over_lines >= self.size.high_over_lines:
            raise ValueError("triage.size: medium_over_lines must be below high_over_lines")
        return self


class _AiMarkers(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trailers: list[str] = Field(default_factory=list)
    pr_body: list[str] = Field(default_factory=list)
    branches: list[str] = Field(default_factory=list)


class _File(BaseModel):
    model_config = ConfigDict(extra="forbid")

    defaults: _Defaults
    checks: dict[str, _CheckSpec]
    triage: _Triage | None = None
    ai_markers: _AiMarkers = Field(default_factory=_AiMarkers)


@dataclass(frozen=True)
class Check:
    name: str
    mode: Mode
    fail_on: Severity | None
    engine: EngineName
    model: str
    paths: tuple[str, ...] | None
    max_diff_kb: int
    max_file_kb: int  # a single file's diff over this is left out of the review (ADR 0002)
    budget_usd: float
    max_turns: int
    on_error: OnError
    prompt_path: Path

    @property
    def blocking(self) -> bool:
        return self.mode == "blocking"

    @property
    def command(self) -> str:
        """Slash command name of the prompt file (`.claude/commands/llm-<check>.md`)."""
        return f"llm-{self.name}"


@dataclass(frozen=True)
class TriageRule:
    paths: tuple[str, ...]
    risk: Risk
    reason: str


@dataclass(frozen=True)
class Level:
    run: frozenset[str]  # "all" is expanded to every check
    blocking: frozenset[str]
    engine: EngineName | None
    model: str | None


@dataclass(frozen=True)
class TriageConfig:
    model: str
    max_diff_kb: int
    default_risk: Risk
    rules: tuple[TriageRule, ...]
    medium_over_lines: int
    high_over_lines: int
    ai_assisted_raise: int
    levels: Mapping[Risk, Level]
    prompt_path: Path


@dataclass(frozen=True)
class AiMarkers:
    trailers: tuple[str, ...] = ()
    pr_body: tuple[str, ...] = ()
    branches: tuple[str, ...] = ()


@dataclass(frozen=True)
class GateConfig:
    checks: dict[str, Check]
    triage: TriageConfig | None
    ai_markers: AiMarkers


def prompt_path(repo_root: Path, check_name: str) -> Path:
    return repo_root / ".claude" / "commands" / f"llm-{check_name}.md"


def expand(value: str, env: Mapping[str, str]) -> str:
    def substitute(match: re.Match[str]) -> str:
        name, default = match.group(1), match.group(2)
        if env.get(name):
            return env[name]
        if default is not None:
            return default
        raise ConfigError(f"${{{name}}} is not set and has no default")

    return _VAR.sub(substitute, value)


def _expand_all(node: Any, env: Mapping[str, str]) -> Any:
    if isinstance(node, str):
        return expand(node, env)
    if isinstance(node, list):
        return [_expand_all(item, env) for item in node]
    if isinstance(node, dict):
        return {key: _expand_all(value, env) for key, value in node.items()}
    return node


def load_config(
    path: Path, repo_root: Path, env: Mapping[str, str] | None = None
) -> dict[str, Check]:
    return load_gate_config(path, repo_root, env).checks


def load_gate_config(
    path: Path, repo_root: Path, env: Mapping[str, str] | None = None
) -> GateConfig:
    env = os.environ if env is None else env
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise ConfigError(f"cannot read {path}: {error}") from error
    try:
        parsed = _File.model_validate(_expand_all(raw, env))
    except ValidationError as error:
        raise ConfigError(f"{path}: {error}") from error

    d = parsed.defaults
    checks: dict[str, Check] = {}
    for name, spec in parsed.checks.items():
        if name == TRIAGE:
            raise ConfigError(f"{TRIAGE!r} is the triage step, not a check name")
        prompt = prompt_path(repo_root, name)
        if not prompt.is_file():
            raise ConfigError(f"check {name!r}: prompt file {prompt} does not exist")
        checks[name] = Check(
            name=name,
            mode=spec.mode,
            fail_on=spec.fail_on,
            engine=spec.engine or d.engine,
            model=spec.model or d.model,
            paths=tuple(spec.paths) if spec.paths else None,
            max_diff_kb=spec.max_diff_kb or d.max_diff_kb,
            max_file_kb=spec.max_file_kb or d.max_file_kb,
            budget_usd=spec.budget_usd or d.budget_usd,
            max_turns=spec.max_turns or d.max_turns,
            on_error=spec.on_error or d.on_error,
            prompt_path=prompt,
        )
    markers = parsed.ai_markers
    return GateConfig(
        checks=checks,
        triage=_triage(parsed.triage, checks, repo_root) if parsed.triage else None,
        ai_markers=AiMarkers(
            trailers=tuple(markers.trailers),
            pr_body=tuple(markers.pr_body),
            branches=tuple(markers.branches),
        ),
    )


def _triage(spec: _Triage, checks: Mapping[str, Check], repo_root: Path) -> TriageConfig:
    levels: dict[Risk, Level] = {}
    for risk in RISKS:
        level = spec.levels[risk]
        run = frozenset(checks) if level.run == "all" else frozenset(level.run)
        blocking = frozenset(level.blocking)
        where = f"triage.levels.{risk}"
        unknown = sorted((run | blocking) - checks.keys())
        if unknown:
            raise ConfigError(f"{where}: unknown check(s) {', '.join(unknown)}")
        if not blocking <= run:
            raise ConfigError(f"{where}: blocking checks must also be in run")
        # A level can take blocking away, never give it: fail_on lives with the check.
        advisory = sorted(name for name in blocking if not checks[name].blocking)
        if advisory:
            raise ConfigError(f"{where}: {', '.join(advisory)} is advisory in checks:")
        levels[risk] = Level(run=run, blocking=blocking, engine=level.engine, model=level.model)
    prompt = prompt_path(repo_root, TRIAGE)
    if not prompt.is_file():
        raise ConfigError(f"triage: prompt file {prompt} does not exist")
    return TriageConfig(
        model=spec.model,
        max_diff_kb=spec.max_diff_kb,
        default_risk=spec.default_risk,
        rules=tuple(TriageRule(tuple(r.paths), r.risk, r.reason) for r in spec.rules),
        medium_over_lines=spec.size.medium_over_lines,
        high_over_lines=spec.size.high_over_lines,
        ai_assisted_raise=spec.ai_assisted_raise,
        levels=levels,
        prompt_path=prompt,
    )

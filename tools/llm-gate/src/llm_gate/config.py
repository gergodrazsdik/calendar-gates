"""Load and validate checks.yaml, expanding ${VAR:-default} from the environment."""

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from .models import Severity

EngineName = Literal["api", "agent"]
Mode = Literal["blocking", "advisory"]
OnError = Literal["fail", "pass"]

ENGINES: tuple[EngineName, ...] = ("api", "agent")
_VAR = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


class ConfigError(Exception):
    pass


class _Defaults(BaseModel):
    model_config = ConfigDict(extra="forbid")

    engine: EngineName = "api"
    model: str
    max_diff_kb: int = 200
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


class _File(BaseModel):
    model_config = ConfigDict(extra="forbid")

    defaults: _Defaults
    checks: dict[str, _CheckSpec]


@dataclass(frozen=True)
class Check:
    name: str
    mode: Mode
    fail_on: Severity | None
    engine: EngineName
    model: str
    paths: tuple[str, ...] | None
    max_diff_kb: int
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
            budget_usd=spec.budget_usd or d.budget_usd,
            max_turns=spec.max_turns or d.max_turns,
            on_error=spec.on_error or d.on_error,
            prompt_path=prompt,
        )
    return checks

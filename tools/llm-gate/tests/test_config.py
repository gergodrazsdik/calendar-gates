from pathlib import Path

import pytest

from llm_gate.config import ConfigError, expand, load_config
from llm_gate.models import Severity

REPO_ROOT = Path(__file__).resolve().parents[3]


def write_config(tmp_path: Path, checks: str, defaults: str = "model: m") -> Path:
    (tmp_path / ".claude" / "commands").mkdir(parents=True, exist_ok=True)
    for name in ("a", "b"):
        (tmp_path / ".claude" / "commands" / f"llm-{name}.md").write_text("x", encoding="utf-8")
    path = tmp_path / "checks.yaml"
    path.write_text(f"defaults: {{{defaults}}}\nchecks:\n{checks}", encoding="utf-8")
    return path


@pytest.mark.parametrize(
    ("value", "env", "expected"),
    [
        ("${M:-fallback}", {}, "fallback"),
        ("${M:-fallback}", {"M": ""}, "fallback"),  # empty counts as unset, like CI variables
        ("${M:-fallback}", {"M": "set"}, "set"),
        ("${M}", {"M": "set"}, "set"),
        ("pre-${M:-x}-post", {}, "pre-x-post"),
        ("no variables", {}, "no variables"),
    ],
)
def test_expand(value: str, env: dict[str, str], expected: str) -> None:
    assert expand(value, env) == expected


def test_expand_without_default_needs_the_variable() -> None:
    with pytest.raises(ConfigError, match=r"\$\{M\} is not set"):
        expand("${M}", {})


def test_defaults_and_overrides_merge(tmp_path: Path) -> None:
    path = write_config(
        tmp_path,
        "  a: {mode: blocking, fail_on: high}\n"
        "  b: {mode: advisory, engine: agent, model: '${CHEAP:-cheap}', paths: [src/**]}\n",
        defaults="model: '${MAIN:-main}', max_diff_kb: 10",
    )
    checks = load_config(path, tmp_path, env={"MAIN": "from-env"})

    assert checks["a"].model == "from-env"
    assert checks["a"].engine == "api"
    assert checks["a"].fail_on is Severity.HIGH
    assert checks["a"].blocking
    assert checks["a"].max_diff_kb == 10
    assert checks["b"].model == "cheap"
    assert checks["b"].engine == "agent"
    assert checks["b"].paths == ("src/**",)
    assert not checks["b"].blocking
    assert checks["b"].prompt_path == tmp_path / ".claude" / "commands" / "llm-b.md"


@pytest.mark.parametrize(
    ("checks", "message"),
    [
        ("  a: {mode: blocking}\n", "blocking check needs fail_on"),
        ("  a: {mode: advisory, fail_on: low}\n", "advisory check never fails"),
        ("  a: {mode: blocking, fail_on: urgent}\n", "fail_on"),
        ("  a: {mode: sometimes}\n", "mode"),
        ("  a: {mode: advisory, engine: gpt}\n", "engine"),
        ("  a: {mode: advisory, typo: 1}\n", "typo"),
        ("  c: {mode: advisory}\n", "prompt file"),
    ],
)
def test_invalid_configs_are_rejected(tmp_path: Path, checks: str, message: str) -> None:
    with pytest.raises(ConfigError, match=message):
        load_config(write_config(tmp_path, checks), tmp_path, env={})


def test_the_repository_config_loads() -> None:
    checks = load_config(REPO_ROOT / "tools" / "llm-gate" / "checks.yaml", REPO_ROOT, env={})

    assert {name for name, c in checks.items() if c.blocking} == {
        "code-review",
        "security-review",
        # Blocking since 2026-10-19: advisory everywhere meant the check ADR 0004 names as the
        # mitigation for its own remaining hole could only comment on a CI change.
        "workflow-review",
    }
    assert all(c.prompt_path.is_file() for c in checks.values())

"""Engines against stubbed SDKs: request shape and how each failure becomes an EngineError."""

from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import anthropic
import pytest
from claude_agent_sdk import ResultMessage, SystemMessage
from conftest import make_check

from llm_gate.diff import Diff
from llm_gate.engines import EngineError, ReviewRequest
from llm_gate.engines.agent_engine import READ_ONLY_TOOLS, AgentEngine
from llm_gate.engines.api_engine import FALLBACK_BETA, ApiEngine, estimate_cost
from llm_gate.models import Review

REVIEW = Review(summary="Fine.", findings=[])
DIFF = Diff(base="origin/main", text="diff --git a/x b/x\n+x\n", files=("x",))


def request(tmp_path: Path, **check: object) -> ReviewRequest:
    return ReviewRequest(
        check=make_check(tmp_path, **check),
        prompt="Review $ARGUMENTS carefully.",
        diff=DIFF,
        diff_path=tmp_path / ".llm-gate" / "diff.patch",
        repo_root=tmp_path,
    )


# --- API engine ---------------------------------------------------------------------------


class StubMessages:
    def __init__(self, response: Any = None, error: Exception | None = None) -> None:
        self.response, self.error = response, error
        self.calls: list[dict[str, Any]] = []

    def parse(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.response


def stub_client(messages: StubMessages) -> Any:
    return SimpleNamespace(beta=SimpleNamespace(messages=messages))


def response(stop_reason: str = "end_turn", parsed: Review | None = REVIEW, **extra: Any) -> Any:
    usage = SimpleNamespace(input_tokens=1000, output_tokens=200)
    return SimpleNamespace(
        stop_reason=stop_reason,
        stop_details=extra.get("stop_details"),
        parsed_output=parsed,
        usage=usage,
        model=extra.get("model", "claude-sonnet-5-5"),
    )


def test_api_engine_request_and_result(tmp_path: Path) -> None:
    messages = StubMessages(response())

    out = ApiEngine(stub_client(messages)).review(request(tmp_path))

    call = messages.calls[0]
    assert call["model"] == "claude-sonnet-5-5"
    assert call["output_format"] is Review
    assert "$ARGUMENTS" not in call["system"] and "<diff> element" in call["system"]
    assert call["messages"][0]["content"].startswith('<diff base="origin/main">\ndiff --git')
    assert (call["betas"], call["fallbacks"]) == ([FALLBACK_BETA], "default")
    assert out.review == REVIEW
    assert out.usage.cost_usd == pytest.approx(estimate_cost("claude-sonnet-5-5", 1000, 200))
    assert out.usage.cost_estimated


def test_api_engine_skips_fallbacks_for_models_without_them(tmp_path: Path) -> None:
    messages = StubMessages(response(model="claude-haiku-5-5"))

    ApiEngine(stub_client(messages)).review(request(tmp_path, model="claude-haiku-5-5"))

    assert messages.calls[0]["betas"] is anthropic.omit
    assert messages.calls[0]["fallbacks"] is anthropic.omit


def test_api_engine_reports_the_model_that_answered(tmp_path: Path) -> None:
    out = ApiEngine(stub_client(StubMessages(response(model="claude-opus-5-5")))).review(
        request(tmp_path)
    )

    assert out.model == "claude-opus-5-5"


@pytest.mark.parametrize(
    ("resp", "message"),
    [
        (response("refusal", None, stop_details=SimpleNamespace(category="cyber")), "cyber"),
        (response("max_tokens", None), "cut off"),
        (response("end_turn", None), "no structured review"),
    ],
)
def test_api_engine_failures(tmp_path: Path, resp: Any, message: str) -> None:
    with pytest.raises(EngineError, match=message):
        ApiEngine(stub_client(StubMessages(resp))).review(request(tmp_path))


def test_api_engine_wraps_sdk_errors(tmp_path: Path) -> None:
    import httpx2

    error = anthropic.APIConnectionError(
        request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    )

    with pytest.raises(EngineError, match="cannot reach"):
        ApiEngine(stub_client(StubMessages(error=error))).review(request(tmp_path))


def test_api_engine_without_credentials_is_an_engine_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_credentials(*_: Any, **__: Any) -> Any:
        raise anthropic.AnthropicError("The api_key client option must be set")

    monkeypatch.setattr(anthropic, "Anthropic", no_credentials)

    with pytest.raises(EngineError, match="client error: The api_key"):
        ApiEngine().review(request(tmp_path))


# --- Agent engine -------------------------------------------------------------------------


def init() -> SystemMessage:
    return SystemMessage(subtype="init", data={"slash_commands": ["llm-code-review"]})


def result_message(**overrides: Any) -> ResultMessage:
    fields: dict[str, Any] = {
        "subtype": "success",
        "duration_ms": 4321,
        "duration_api_ms": 4000,
        "is_error": False,
        "num_turns": 5,
        "session_id": "s",
        "total_cost_usd": 0.042,
        "usage": {"input_tokens": 3000, "output_tokens": 400},
        "structured_output": REVIEW.model_dump(),
    }
    fields.update(overrides)
    return ResultMessage(**fields)


def fake_query(*messages: object, calls: list[dict[str, Any]] | None = None) -> Any:
    async def query(**kwargs: Any) -> AsyncIterator[object]:
        if calls is not None:
            calls.append(kwargs)
        for message in messages:
            yield message

    return query


def test_agent_engine_options_are_read_only_and_load_nothing(tmp_path: Path) -> None:
    options = AgentEngine().options(request(tmp_path, max_turns=7, budget_usd=0.25))

    assert options.tools == READ_ONLY_TOOLS
    assert options.allowed_tools == READ_ONLY_TOOLS
    assert {"Bash", "Write", "Edit", "WebFetch"} <= set(options.disallowed_tools)
    assert options.permission_mode == "dontAsk"
    # Nothing from the reviewed repository or the machine: no CLAUDE.md, commands, hooks, ...
    assert options.setting_sources == []
    assert options.skills == []
    assert options.settings == '{"disableAllHooks": true}'
    assert options.mcp_servers == {}
    assert "strict-mcp-config" in options.extra_args
    assert options.env["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] == "1"
    assert (options.max_turns, options.max_budget_usd) == (7, 0.25)
    assert options.cwd == str(tmp_path)  # the reviewed repository, read-only context
    assert options.output_format == {"type": "json_schema", "schema": Review.model_json_schema()}


def test_agent_engine_passes_the_prompt_text_with_the_diff_inline(tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []
    query = fake_query(init(), result_message(), calls=calls)

    out = AgentEngine(query).review(request(tmp_path))

    prompt = calls[0]["prompt"]
    assert not prompt.startswith("/")  # not a slash command: nothing to resolve from disk
    assert prompt.startswith("Review the unified diff inside the <diff> element below carefully.")
    assert prompt.endswith('<diff base="origin/main">\ndiff --git a/x b/x\n+x\n\n</diff>')
    assert out.review == REVIEW
    assert (out.duration_ms, out.usage.num_turns, out.usage.cost_usd) == (4321, 5, 0.042)
    assert not out.usage.cost_estimated


@pytest.mark.parametrize(
    ("messages", "error"),
    [
        ((init(),), "no result message"),
        ((init(), result_message(subtype="error_max_turns", is_error=True)), "error_max_turns"),
        ((init(), result_message(structured_output=None)), "without a struct"),
        ((init(), result_message(structured_output={"x": 1})), "schema"),
    ],
)
def test_agent_engine_failures(tmp_path: Path, messages: tuple[object, ...], error: str) -> None:
    with pytest.raises(EngineError, match=error):
        AgentEngine(fake_query(*messages)).review(request(tmp_path))


def test_agent_engine_counts_cached_input_tokens(tmp_path: Path) -> None:
    usage = {"input_tokens": 6, "cache_creation_input_tokens": 900, "cache_read_input_tokens": 4000}
    query = fake_query(init(), result_message(usage=usage))

    out = AgentEngine(query).review(request(tmp_path))

    assert out.usage.input_tokens == 4906

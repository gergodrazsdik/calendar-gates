"""Engines against stubbed SDKs: request shape and how each failure becomes an EngineError."""

import asyncio
import json
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
from llm_gate.engines.agent_engine import READ_ONLY_TOOLS, AgentEngine, ToolCallLog
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
    # The literal price, so this can't pass by agreeing with a broken estimate_cost (F036).
    assert out.usage.cost_usd == pytest.approx((1000 * 2.00 + 200 * 10.00) / 1_000_000)
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
    # Path-scoped, not bare: a whole-tool "Read" allow rule outranks the CLI's path check and let
    # the reviewer read anything the machine could (F003). Grep/Glob path rules are inert, so those
    # two stay bare and the settings below are what fences them.
    assert options.allowed_tools == ["Read(./**)", "Grep", "Glob"]
    assert "Read" not in options.allowed_tools
    assert {"Bash", "Write", "Edit", "WebFetch"} <= set(options.disallowed_tools)
    assert options.permission_mode == "dontAsk"
    # Nothing from the reviewed repository or the machine: no CLAUDE.md, commands, hooks, ...
    assert options.setting_sources == []
    assert options.skills == []
    settings = json.loads(options.settings or "{}")
    assert settings["disableAllHooks"] is True
    assert settings["permissions"]["blockReadsOutsideWorkingDirectories"] is True
    assert "Read(//proc/**)" in settings["permissions"]["deny"]
    # The checkout itself lives under /home/runner/work in CI, and a deny rule beats everything.
    assert not any("//home" in rule for rule in settings["permissions"]["deny"])
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


def test_agent_engine_logs_tool_calls_through_its_pre_tool_use_hook(tmp_path: Path) -> None:
    async def query(**kwargs: Any) -> AsyncIterator[object]:
        # What Claude Code does before each tool call: call the registered callback.
        (matcher,) = kwargs["options"].hooks["PreToolUse"]
        for name, tool_input in (
            ("Read", {"file_path": f"{tmp_path}/src/Workdays.cs"}),
            ("Grep", {"pattern": "sk-ant-api03-" + "x" * 30, "path": str(tmp_path)}),
            ("StructuredOutput", {"summary": "raw model output", "findings": []}),
        ):
            data = {"hook_event_name": "PreToolUse", "tool_name": name, "tool_input": tool_input}
            assert await matcher.hooks[0](data, "toolu_1", {"signal": None}) == {}
        yield init()
        yield result_message()

    out = AgentEngine(query).review(request(tmp_path))

    assert [(c.tool, c.input) for c in out.tool_calls] == [
        ("Read", "file_path=src/Workdays.cs"),
        ("Grep", "pattern=[REDACTED] path=."),
    ]
    assert all(c.ts.tzinfo is not None for c in out.tool_calls)


@pytest.mark.parametrize(
    ("model", "input_tokens", "output_tokens", "expected"),
    [
        # Sonnet: $2.00 per Mtok in, $10.00 out. The literal arithmetic, not estimate_cost's own
        # output: the old assertion compared the engine's number with this function, so swapped
        # input and output prices would have passed (F036).
        ("claude-sonnet-5-5", 1_000, 200, (1_000 * 2.00 + 200 * 10.00) / 1_000_000),
        ("claude-haiku-5-5", 1_000_000, 0, 0.10),
        ("claude-opus-5-5", 0, 1_000_000, 20.00),
        # Input and output are not interchangeable: 1 Mtok out costs 5x 1 Mtok in on Sonnet.
        ("claude-sonnet-5-5", 1_000_000, 0, 2.00),
        ("claude-sonnet-5-5", 0, 1_000_000, 10.00),
    ],
)
def test_cost_is_the_price_table_times_the_tokens(
    model: str, input_tokens: int, output_tokens: int, expected: float
) -> None:
    assert estimate_cost(model, input_tokens, output_tokens) == pytest.approx(expected)


def test_an_unknown_model_has_no_estimate() -> None:
    """No guess for a model the table doesn't price: the metrics and the eval budget would be
    quietly wrong instead of visibly absent."""
    assert estimate_cost("claude-not-a-model", 1000, 200) is None


# --- the read fence (F003) -----------------------------------------------------------------------
# The reviewer's own process environment holds the API key, so "it may read the checkout" has to be
# enforced, not assumed. The CLI's blockReadsOutsideWorkingDirectories is the primary control (its
# behaviour lives in a compiled binary, so test_live.py checks that end); these tests cover the
# in-process backstop, which must deny anything it can't parse and must never raise.


def hook_call(
    log: ToolCallLog, tool: str, tool_input: object, use: str | None = "toolu_1"
) -> dict[str, Any]:
    data = {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": tool_input}
    return dict(asyncio.run(log.hook(data, use, {"signal": None})))  # type: ignore[arg-type]


def denied(output: dict[str, Any]) -> bool:
    decision = output.get("hookSpecificOutput", {}).get("permissionDecision")
    return bool(decision == "deny")


@pytest.mark.parametrize(
    ("tool", "tool_input"),
    [
        ("Read", {"file_path": "/proc/self/environ"}),  # where the API key is
        ("Read", {"file_path": "../../etc/passwd"}),  # relative, escaping
        ("Read", {"file_path": "src/../../../etc/passwd"}),  # escaping after a detour inside
        ("Grep", {"pattern": "ANTHROPIC", "path": "/proc/self"}),  # Grep returns content too
        # Glob takes its search directory from the *pattern* when no path is given, so a path-only
        # fence lets this one through and it lists the environment of every process.
        ("Glob", {"pattern": "/proc/*/environ"}),
        ("Glob", {"pattern": "**/*.cs", "path": "/etc"}),
    ],
)
def test_the_hook_denies_a_read_outside_the_checkout(
    tmp_path: Path, tool: str, tool_input: dict[str, Any]
) -> None:
    log = ToolCallLog(tmp_path)

    assert denied(hook_call(log, tool, tool_input))

    assert log.denied == 1
    assert [c.denied for c in log.calls] == [True]  # refused, and on the record


def test_the_hook_allows_a_read_inside_the_checkout(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "A.cs").write_text("class A {}\n")
    log = ToolCallLog(tmp_path)

    assert hook_call(log, "Read", {"file_path": f"{tmp_path}/src/A.cs"}) == {}
    assert hook_call(log, "Read", {"file_path": "src/A.cs"}) == {}  # relative to the root
    assert hook_call(log, "Glob", {"pattern": "**/*.cs"}) == {}

    assert log.denied == 0
    assert [c.input for c in log.calls] == [
        "file_path=src/A.cs",
        "file_path=src/A.cs",
        "pattern=**/*.cs",
    ]


def test_the_hook_denies_a_read_through_a_symlink_committed_in_the_checkout(
    tmp_path: Path,
) -> None:
    """git stores a symlink as one file (mode 120000) with any target the PR likes, so textual
    normalisation is not enough on its own."""
    (tmp_path / "evil").symlink_to("/etc")
    log = ToolCallLog(tmp_path)

    assert denied(hook_call(log, "Read", {"file_path": f"{tmp_path}/evil/hostname"}))


def test_the_hook_allows_a_read_under_a_root_that_is_itself_a_symlink(tmp_path: Path) -> None:
    """An eval run hands the engine a temporary directory, and `$TMPDIR` is a symlink on some
    machines: comparing resolved paths with an unresolved root would deny every read there."""
    real = tmp_path / "real"
    (real / "src").mkdir(parents=True)
    (real / "src" / "A.cs").write_text("class A {}\n")
    link = tmp_path / "link"
    link.symlink_to(real)
    log = ToolCallLog(link)

    assert hook_call(log, "Read", {"file_path": f"{link}/src/A.cs"}) == {}
    assert [c.input for c in log.calls] == ["file_path=src/A.cs"]  # still repository-relative


@pytest.mark.parametrize(
    "tool_input",
    [
        {},
        {"file_path": None},
        {"file_path": ""},
        {"file_path": ["/etc/passwd"]},
        {"file_path": "a\x00b"},
    ],
)
def test_the_hook_denies_a_tool_input_it_cannot_make_sense_of(
    tmp_path: Path, tool_input: object
) -> None:
    """Including a Read with no file_path at all: unparseable is refused, never waved through."""
    assert denied(hook_call(ToolCallLog(tmp_path), "Read", tool_input))


def test_the_hook_denies_instead_of_raising_when_a_path_cannot_be_resolved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A callback that raises yields no decision and the call proceeds, so the fence would be gone
    exactly when the filesystem is strange."""

    def boom(self: Path, strict: bool = False) -> Path:
        raise OSError("ELOOP")

    monkeypatch.setattr(Path, "resolve", boom)

    assert denied(hook_call(ToolCallLog(tmp_path), "Read", {"file_path": "src/A.cs"}))


def test_the_hook_denies_an_unknown_tool_and_leaves_structured_output_alone(
    tmp_path: Path,
) -> None:
    log = ToolCallLog(tmp_path)

    # LSP reads `filePath`, a key this gate has never heard of; whatever the tool is, it isn't one
    # of the three the review runs with.
    assert denied(hook_call(log, "LSP", {"filePath": "/etc/passwd"}))
    assert hook_call(log, "StructuredOutput", {"summary": "raw model output", "findings": []}) == {}

    assert log.denied == 1
    assert [(c.tool, c.denied) for c in log.calls] == [("other", True)]


def test_denied_reads_are_counted_on_the_result(tmp_path: Path) -> None:
    async def query(**kwargs: Any) -> AsyncIterator[object]:
        (matcher,) = kwargs["options"].hooks["PreToolUse"]
        for use, (name, tool_input) in enumerate(
            [
                ("Read", {"file_path": "/proc/self/environ"}),
                ("Read", {"file_path": f"{tmp_path}/x.cs"}),
                ("Grep", {"pattern": "KEY", "path": "/proc"}),
            ]
        ):
            data = {"hook_event_name": "PreToolUse", "tool_name": name, "tool_input": tool_input}
            await matcher.hooks[0](data, f"toolu_{use}", {"signal": None})
        yield init()
        yield result_message()

    out = AgentEngine(query).review(request(tmp_path))

    assert out.denied_reads == 2
    assert [c.denied for c in out.tool_calls] == [True, False, True]


def test_a_denial_the_cli_made_itself_is_recorded_once(tmp_path: Path) -> None:
    """The CLI's own fence reports itself in a system message with a reason code; the engine used to
    discard every message but the result, so a refused read left no trace. The same refusal is also
    in the result's authoritative list, and must not be counted twice."""
    denial = {
        "tool_name": "Read",
        "tool_use_id": "toolu_9",
        "decision_reason_code": "outside_reads_blocked",
    }
    query = fake_query(
        init(),
        SystemMessage(subtype="permission_denied", data=denial),
        result_message(permission_denials=[denial]),
    )

    out = AgentEngine(query).review(request(tmp_path))

    assert out.denied_reads == 1
    (call,) = out.tool_calls
    assert (call.tool, call.denied) == ("Read", True)
    assert "outside_reads_blocked" in call.input


def test_a_review_whose_every_read_was_denied_still_returns(tmp_path: Path) -> None:
    """A denial must not turn into an EngineError: that would fail the check closed, which is safe
    but hands any PR a way to make code-review error at will. The diff is in the prompt already."""

    async def query(**kwargs: Any) -> AsyncIterator[object]:
        (matcher,) = kwargs["options"].hooks["PreToolUse"]
        for use in range(3):
            data = {
                "hook_event_name": "PreToolUse",
                "tool_name": "Read",
                "tool_input": {"file_path": "/proc/self/environ"},
            }
            await matcher.hooks[0](data, f"toolu_{use}", {"signal": None})
        yield init()
        yield result_message()

    out = AgentEngine(query).review(request(tmp_path))

    assert out.review == REVIEW
    assert out.denied_reads == 3

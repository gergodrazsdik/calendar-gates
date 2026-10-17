"""Claude Agent SDK engine: the review prompt with the diff inline, run in the repository under
review with read-only tools, so the agent can look at callers and tests beyond the diff.

The prompt text comes from the gate's own checkout (ADR 0004). Nothing is loaded from the
repository under review: no CLAUDE.md, rules, commands, skills, hooks, settings or MCP servers, so
its files are data the agent may read, never instructions it receives.

Every tool call is logged through an SDK `PreToolUse` callback hook (an in-process callback, not a
settings hook, so `disableAllHooks` doesn't switch it off) into the result's `tool_calls`.
"""

import asyncio
import json
import time
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from claude_agent_sdk import (
    ClaudeAgentOptions,
    ClaudeSDKError,
    HookContext,
    HookInput,
    HookJSONOutput,
    HookMatcher,
    ResultError,
    ResultMessage,
    query,
)
from pydantic import ValidationError

from ..audit import summarise_tool_input
from ..models import EngineResult, Review, ToolCall, Usage
from ..prompts import DIFF_REFERENCE, diff_block, render
from . import EngineError, ReviewRequest

READ_ONLY_TOOLS = ["Read", "Grep", "Glob"]
# `tools` already limits the session to READ_ONLY_TOOLS; the deny list is belt and braces.
DENIED_TOOLS = ["Bash", "Write", "Edit", "NotebookEdit", "WebFetch", "WebSearch", "Task", "Agent"]

# The SDK returns the structured review through this synthetic tool; its input is the raw model
# output, which the audit trail deliberately doesn't store (the review itself is the result).
STRUCTURED_OUTPUT_TOOL = "StructuredOutput"

# Applied with --settings, which outranks every other source: no hooks run, whatever is on disk.
NO_HOOKS = json.dumps({"disableAllHooks": True})

QueryFn = Callable[..., AsyncIterator[Any]]


class ToolCallLog:
    """Collects the session's tool calls; `hook` is registered as the PreToolUse callback."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.calls: list[ToolCall] = []

    async def hook(
        self, data: HookInput, tool_use_id: str | None, context: HookContext
    ) -> HookJSONOutput:
        if data["hook_event_name"] == "PreToolUse" and data["tool_name"] != STRUCTURED_OUTPUT_TOOL:
            tool = data["tool_name"]
            summary = summarise_tool_input(tool, data["tool_input"], self.root)
            self.calls.append(ToolCall(tool=tool, input=summary, ts=datetime.now(UTC)))
        return {}  # observe only: the permission decision stays with tools/allowed_tools


def agent_prompt(request: ReviewRequest) -> str:
    return (
        f"{render(request.prompt, DIFF_REFERENCE)}\n\n"
        f"{diff_block(request.diff.base, request.diff.text, request.diff.omitted)}"
    )


class AgentEngine:
    name = "agent"

    def __init__(self, query_fn: QueryFn = query) -> None:
        self._query = query_fn  # tests inject a fake message stream

    def options(self, request: ReviewRequest, log: ToolCallLog | None = None) -> ClaudeAgentOptions:
        check = request.check
        hooks = {"PreToolUse": [HookMatcher(hooks=[log.hook])]} if log else None
        return ClaudeAgentOptions(
            cwd=str(request.repo_root),
            model=check.model,
            tools=READ_ONLY_TOOLS,
            allowed_tools=READ_ONLY_TOOLS,
            disallowed_tools=DENIED_TOOLS,
            permission_mode="dontAsk",  # anything not pre-approved is denied, never prompted
            # No filesystem settings at all: not the user's, not the reviewed repository's
            # (its CLAUDE.md would otherwise reach the reviewer as instructions).
            setting_sources=[],
            skills=[],
            settings=NO_HOOKS,
            # Project MCP servers (.mcp.json) start commands: use none.
            mcp_servers={},
            hooks=hooks,  # type: ignore[arg-type]  # dict invariance: HookEvent keys
            extra_args={"strict-mcp-config": None},
            max_turns=check.max_turns,
            max_budget_usd=check.budget_usd,
            output_format={"type": "json_schema", "schema": Review.model_json_schema()},
            env={
                "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
                "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1",
            },
        )

    def review(self, request: ReviewRequest) -> EngineResult:
        return asyncio.run(self._review(request))

    async def _review(self, request: ReviewRequest) -> EngineResult:
        started = time.monotonic()
        result: ResultMessage | None = None
        log = ToolCallLog(request.repo_root)
        try:
            async for message in self._query(
                prompt=agent_prompt(request), options=self.options(request, log)
            ):
                if isinstance(message, ResultMessage):
                    result = message
        except ResultError as error:
            # subtype "success" with an error means the final API request failed (billing, auth).
            what = "the API request failed" if error.subtype == "success" else error.subtype
            status = f" (HTTP {error.api_error_status})" if error.api_error_status else ""
            detail = "; ".join(error.errors) or error.result or str(error)
            raise EngineError(f"agent run failed, {what}{status}: {detail}") from error
        except ClaudeSDKError as error:
            raise EngineError(f"Claude Agent SDK error: {error}") from error

        if result is None:
            raise EngineError("the agent run produced no result message")
        if result.subtype != "success" or result.is_error:
            raise EngineError(f"agent run ended with {result.subtype}: {result.errors or ''}")
        if result.structured_output is None:
            raise EngineError("the agent finished without a structured review")
        try:
            review = Review.model_validate(result.structured_output)
        except ValidationError as error:
            raise EngineError(f"the agent's review does not match the schema: {error}") from error

        usage = result.usage or {}
        return EngineResult(
            engine=self.name,
            model=request.check.model,
            review=review,
            duration_ms=result.duration_ms or int((time.monotonic() - started) * 1000),
            usage=Usage(
                # Claude Code caches its prompt, so most input arrives as cache reads/writes.
                input_tokens=sum(
                    usage.get(key) or 0
                    for key in (
                        "input_tokens",
                        "cache_creation_input_tokens",
                        "cache_read_input_tokens",
                    )
                )
                or None,
                output_tokens=usage.get("output_tokens"),
                cost_usd=result.total_cost_usd,
                num_turns=result.num_turns,
            ),
            tool_calls=log.calls,
        )

"""Claude Agent SDK engine: the review prompt with the diff inline, run in the repository under
review with read-only tools, so the agent can look at callers and tests beyond the diff.

The prompt text comes from the gate's own checkout (ADR 0004). Nothing is loaded from the
repository under review: no CLAUDE.md, rules, commands, skills, hooks, settings or MCP servers, so
its files are data the agent may read, never instructions it receives.

Every tool call is logged through an SDK `PreToolUse` callback hook (an in-process callback, not a
settings hook, so `disableAllHooks` doesn't switch it off) into the result's `tool_calls`, which
also refuses the ones that reach outside the checkout. The reviewer may read the repository under
review and nothing else: its own process environment holds the API key, and a review steered by
injected text in the diff would otherwise have been able to read it and publish it (F003).
"""

import asyncio
import json
import os
import time
from collections.abc import AsyncIterator, Callable, Mapping
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
    SystemMessage,
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

# A *bare* tool name in `allowed_tools` is a whole-tool allow rule, and the CLI takes that branch
# before any path check, so it turns the "ask" an out-of-tree path would otherwise produce into
# "allow": the reviewer's reads were not confined to the checkout at all (F003). `Read(path)` rules
# are the ones file permission checks match, for every file-reading tool; `Grep(...)`/`Glob(...)`
# path rules are inert, so those two stay bare and are fenced by the settings and the hook below.
ALLOWED_TOOLS = ["Read(./**)", "Grep", "Glob"]

# Applied with --settings, which outranks every other source and is read even with
# setting_sources=[]: no hooks run, and the file tools cannot read outside the working directory.
# The fence runs inside the tool's own permission check, ahead of the allow-rule lookup, and knows
# about symlinks; deny rules are evaluated before that (`//` is the absolute-path rule syntax).
# No `//home/**` rule: in CI the checkout itself lives under /home/runner/work, and deny wins.
SETTINGS = json.dumps(
    {
        "disableAllHooks": True,
        "permissions": {
            "blockReadsOutsideWorkingDirectories": True,
            "deny": [
                "Read(//proc/**)",
                "Read(//sys/**)",
                "Read(//dev/**)",
                "Read(//root/**)",
            ],
        },
    }
)

# Tool input fields that name something the call would read. Glob derives its search directory from
# the *pattern* when no path is given, so an absolute pattern ("/proc/*/environ") reads where it
# points without ever setting `path`.
PATH_FIELDS: dict[str, tuple[str, ...]] = {
    "Read": ("file_path",),
    "Grep": ("path",),
    "Glob": ("path", "pattern"),
}

# Read names the file it reads, so a Read without one is a call this gate cannot reason about and
# is refused like any other unparseable input. Grep and Glob legitimately omit `path` and search
# the working directory, which is the checkout.
REQUIRED_FIELD = {"Read": "file_path"}

# Fixed, so a refusal never echoes the path (which the PR's files may have chosen) back into the
# model's context. The review goes on with the diff it already has.
DENY_REASON = "reads are fenced to the repository under review; the diff is already in the prompt"

# The SDK returns the structured review through this synthetic tool; its input is the raw model
# output, which the audit trail deliberately doesn't store (the review itself is the result).
STRUCTURED_OUTPUT_TOOL = "StructuredOutput"

QueryFn = Callable[..., AsyncIterator[Any]]


def _resolve(root: Path) -> Path:
    """The root as the CLI will see it. An unresolved symlink (an eval run's `$TMPDIR`) would make
    every canonical path look like an escape, so this is resolved once and the raw spelling kept
    for the audit summaries, which relativise textually."""
    try:
        return root.resolve()
    except OSError:
        return root


def _outside(value: object, root: Path, resolved: Path) -> bool:
    """Whether a tool input's path reaches outside the checkout. Textual first and deliberately:
    `Path.resolve()` makes syscalls, and a read of an automount path can block until the CLI's hook
    timeout, after which the call proceeds — the hang would be the bypass. Only a path that is
    already textually inside is resolved, to catch a symlink committed in the PR."""
    if not isinstance(value, str) or not value or "\x00" in value:
        return True
    given = Path(value)
    # `os.path.normpath` is the pure-text one: PurePath keeps ".." segments, and Path.resolve()
    # would be the syscall this check exists to avoid making first.
    normalised = Path(os.path.normpath(given if given.is_absolute() else root / value))
    if normalised != root and root not in normalised.parents:
        return True
    try:
        real = normalised.resolve()
    except OSError:
        return True
    return real != resolved and resolved not in real.parents


class ToolCallLog:
    """Collects the session's tool calls, and refuses the ones that reach outside the checkout.

    The CLI's own `blockReadsOutsideWorkingDirectories` is the primary control (see SETTINGS): a
    hook callback that raises or times out yields no decision and the tool proceeds, so this layer
    is fail-open and cannot be the authority. It is the audit trail, plus a backstop for inputs the
    CLI's fence doesn't model, and therefore never raises: anything it cannot parse is denied.
    """

    def __init__(self, root: Path) -> None:
        self.root = root
        self.resolved = _resolve(root)
        self.calls: list[ToolCall] = []
        # Keyed by tool use, because the layers overlap: a refusal can be reported by this hook and
        # by the CLI's own fence, and counting both would double it.
        self.denied_uses: set[str] = set()

    @property
    def denied(self) -> int:
        return len(self.denied_uses)

    def note_denial(self, tool: str | None, tool_use_id: str | None, reason: str | None) -> None:
        """A refusal the CLI made itself (a deny rule, or its working-directory fence), which the
        hook never sees. Logged like a call, so the record says what was refused and why."""
        use = tool_use_id or f"cli-{len(self.denied_uses)}"
        if use in self.denied_uses:
            return  # the hook already logged this one
        self.denied_uses.add(use)
        self.calls.append(
            ToolCall(
                tool=tool or "other",
                input=f"denied by the gate: {reason or 'outside the checkout'}",
                ts=datetime.now(UTC),
                denied=True,
            )
        )

    def refuses(self, tool: str, tool_input: Mapping[str, Any]) -> bool:
        try:
            fields = PATH_FIELDS.get(tool)
            if fields is None:
                return True  # an unknown file tool (LSP reads `filePath`): fail closed
            required = REQUIRED_FIELD.get(tool)
            if required is not None and tool_input.get(required) is None:
                return True
            return any(
                _outside(tool_input[field], self.root, self.resolved)
                for field in fields
                if tool_input.get(field) is not None
            )
        except Exception:  # a fence that raises is a fence that isn't there
            return True

    async def hook(
        self, data: HookInput, tool_use_id: str | None, context: HookContext
    ) -> HookJSONOutput:
        if data["hook_event_name"] != "PreToolUse" or data["tool_name"] == STRUCTURED_OUTPUT_TOOL:
            return {}
        tool = data["tool_name"]
        refused = self.refuses(tool, data["tool_input"])
        summary = summarise_tool_input(tool, data["tool_input"], self.root)
        self.calls.append(ToolCall(tool=tool, input=summary, ts=datetime.now(UTC), denied=refused))
        if not refused:
            return {}  # allowed calls are observed only; the decision stays with the CLI's rules
        self.denied_uses.add(tool_use_id or f"hook-{len(self.denied_uses)}")
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": DENY_REASON,
            }
        }


def _denial_fields(data: object) -> tuple[str | None, str | None, str | None]:
    """(tool, tool use, reason) out of a CLI denial, which is a plain mapping in the SDK's types."""
    if not isinstance(data, Mapping):
        return None, None, None
    reason = data.get("decision_reason_code") or data.get("decision_reason")
    return (
        str(data["tool_name"]) if data.get("tool_name") else None,
        str(data["tool_use_id"]) if data.get("tool_use_id") else None,
        str(reason) if reason else None,
    )


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
            allowed_tools=ALLOWED_TOOLS,
            disallowed_tools=DENIED_TOOLS,
            permission_mode="dontAsk",  # anything not pre-approved is denied, never prompted
            # No filesystem settings from disk: not the user's, not the reviewed repository's
            # (its CLAUDE.md would otherwise reach the reviewer as instructions). SETTINGS below is
            # passed inline, from this checkout.
            setting_sources=[],
            skills=[],
            settings=SETTINGS,
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
                    # The authoritative list of what the CLI refused; no reason, just the call.
                    for denial in result.permission_denials or []:
                        log.note_denial(*_denial_fields(denial))
                elif isinstance(message, SystemMessage) and message.subtype == "permission_denied":
                    # The CLI's own fence reports itself here, with a reason code such as
                    # `outside_reads_blocked`. The engine used to discard every non-result message,
                    # so a refused read left no trace at all (F003).
                    log.note_denial(*_denial_fields(message.data))
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
            denied_reads=log.denied,
        )

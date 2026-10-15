# llm-gate

The LLM review gate of calendar-gates. Claude reviews the branch's diff with a prompt from
`.claude/commands/llm-<check>.md`; llm-gate turns the findings into a verdict from their severities
and the check's policy in `checks.yaml`. The model never decides pass or fail.

```
llm-gate list    [--json] [--blocking]
llm-gate run     --check <name> [--engine api|agent|both] [--base origin/main] [--out .llm-gate]
                 [--no-cache] [--override]
llm-gate compare --check <name> [--in .llm-gate]
llm-gate report  [--in .llm-gate] [--check <name>] [--format md|sarif]
```

Exit codes: `0` pass (or advisory, not applicable, overridden), `1` blocking findings, `2`
infrastructure error (API failure, refusal, diff too large) on a blocking check that fails closed.

From the repository root: `just llm <check> [engine]` (key from `pass`), `just llm-compare <check>`,
`just llm-list`. Environment: `ANTHROPIC_API_KEY`, `LLM_MODEL` / `LLM_MODEL_CHEAP` (models in
`checks.yaml`), `LLM_GATE_BASE` (default base), `LLM_GATE_OVERRIDE=1` (report without failing).

## Engines

| | `api` | `agent` |
|---|---|---|
| SDK | `anthropic` (Messages API) | `claude-agent-sdk` (Claude Code as a library) |
| Input | the prompt as system prompt, the diff inline | `/llm-<check> .llm-gate/diff.patch`, run in the repository |
| Context | the diff only | the diff plus whatever it reads (Read, Grep, Glob; nothing else) |
| Output | `messages.parse(output_format=Review)` | `output_format` JSON schema, `structured_output` |
| Cost | one request | several turns, capped by `budget_usd` and `max_turns` |

Both return the same `Review` (`models.py`). Errors (API errors, refusals, truncated output, a
missing structured result, a slash command that did not load) become `EngineError`, which the
policy turns into a pass or a fail according to `on_error`.

## Layout

| Module | |
|---|---|
| `config.py` | `checks.yaml` with `${VAR:-default}` expansion, validated with pydantic |
| `diff.py` | `git diff --merge-base <base> HEAD`, lock and generated files excluded, `paths:` matching |
| `engines/` | `api_engine.py`, `agent_engine.py`, the `Engine` protocol |
| `policy.py` | verdict and exit code from findings, mode, `fail_on`, override and `on_error` |
| `cache.py` | results keyed by check, engine, model, prompt and diff (`.llm-gate/cache/`) |
| `runner.py` | one check with one engine: applicability, size cap, cache, engine, policy, result file |
| `report.py`, `compare.py` | Markdown (job summary, sticky comment), SARIF, engine comparison |

Tests use fake engines and stubbed SDKs (`uv run pytest`); `uv run pytest -m live` calls the real
API once with a cheap model.

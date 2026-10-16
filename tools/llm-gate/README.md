# llm-gate

The LLM review gate of calendar-gates. Claude reviews the branch's diff with a prompt from
`.claude/commands/llm-<check>.md`; llm-gate turns the findings into a verdict from their severities
and the check's policy in `checks.yaml`. The model never decides pass or fail.

```
llm-gate list    [--json] [--blocking]
llm-gate run     --check <name> [--engine api|agent|both] [--base origin/main] [--out .llm-gate]
                 [--no-cache] [--override --override-reason <why> [--override-by <who>]]
llm-gate compare --check <name> [--in .llm-gate]
llm-gate report  [--in .llm-gate] [--check <name>] [--format md|sarif]
llm-gate audit   skip | validate | collect | override   (see "Audit records")
llm-gate eval    run [--check <c>]... [--engine api|agent|both] [--model <m>] [--repeats 3]
                 [--jobs 4] [--cases <glob>] [--budget-usd <x>] [--compare]
                 | baseline | add-from-fp <finding-id>   (see evals/README.md)
llm-gate feedback handle --event <file> --audit-dir <dir> --out <dir> | mark ...   (llm-feedback.yml)
llm-gate metrics [--audit-dir .audit-log] [--prs <json>] [--eval-reports <dir>] [--since-days 30]
```

Exit codes: `0` pass (or advisory, not applicable, overridden), `1` blocking findings, `2`
infrastructure error (API failure, refusal, diff too large) on a blocking check that fails closed.

`--repo <path>` is the repository under review (default: the git repository of the current
directory); `--config` defaults to its `tools/llm-gate/checks.yaml`, and the prompts come from
the checkout that holds the config. CI runs the gate from the base branch's current head with
`--repo src --config gate/tools/llm-gate/checks.yaml` (ADR 0004).

From the repository root: `just llm <check> [engine]` (key from `pass`), `just llm-compare <check>`,
`just llm-list`. Environment: `ANTHROPIC_API_KEY`, `LLM_MODEL` / `LLM_MODEL_CHEAP` (models in
`checks.yaml`), `LLM_GATE_BASE` (default base), `LLM_GATE_OVERRIDE=1` with `LLM_GATE_OVERRIDE_REASON` (report
without failing; an override without a reason is not honoured), `LLM_GATE_PR` and
`LLM_GATE_PR_EVENT_AT` (audit context in CI).

## Engines

| | `api` | `agent` |
|---|---|---|
| SDK | `anthropic` (Messages API) | `claude-agent-sdk` (Claude Code as a library) |
| Input | the prompt as system prompt, the diff inline | the prompt text with the diff inline, run in `--repo` |
| Context | the diff only | the diff plus whatever it reads (Read, Grep, Glob; nothing else). Loads no settings, `CLAUDE.md`, commands, skills, hooks or MCP servers from the repository (`setting_sources=[]`) |
| Output | `messages.parse(output_format=Review)` | `output_format` JSON schema, `structured_output` |
| Cost | one request | several turns, capped by `budget_usd` and `max_turns` |

Both return the same `Review` (`models.py`). Errors (API errors, refusals, truncated output, a
missing structured result) become `EngineError`, which the
policy turns into a pass or a fail according to `on_error`.

## Audit records

Every `run` appends one `gate_run` record per engine (plus an `override` record when one is
honoured) to `.llm-gate/audit.jsonl`, schema `audit/v1` ([ADR 0005](../../docs/adr/0005-audit-trail.md)).
The record has hashes of the prompt, config and diff, the gate commit, usage and cost, the agent's
tool calls (redacted summaries), the findings' ids and titles, and the verdict. It never holds the
diff or the raw model output. Finding ids (`cr-3f2a`: check initials plus a hash of check, file and
title) are shown in the sticky comment, so people can refer to a finding.

| Command | Side | |
|---|---|---|
| `audit skip --check <c> --reason skipped_no_key\|not_needed` | untrusted | records a check that didn't run |
| `audit validate <file> --repo-name --run-id --run-attempt --head-sha --pr [--check]` | trusted | strict parse plus the run's identity; exit 1 on any problem |
| `audit collect --artifacts <dir> --jobs <jsonl> --events <json> --comments <json> [--workflow-modified] --out <dir> ...` | trusted | one file per artifact under `events/YYYY/MM/DD/`; forged or mismatched artifacts (including override claims the issue events and comments don't back) become `tamper_suspected` events |
| `audit override --events <json> --comments <json>` | either | the `/llm-override <reason>` of whoever added the label, as JSON; exit 1 with the reason it doesn't count |

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
| `audit.py` | `audit/v1` records, validation and collection of untrusted artifacts, override reasons |
| `evals.py` | eval cases, scoring, baseline and thresholds, fp-regression cases from the audit log (`evals/`) |
| `feedback.py` | `/llm-*` PR comment commands: parsing, validation, records and actions ([ADR 0007](../../docs/adr/0007-feedback-commands.md)) |
| `metrics.py` | gate health report over the audit log ([docs/metrics.md](../../docs/metrics.md)) |
| `redact.py` | secret patterns and length limits that the record schema applies to every free-text field |

Tests use fake engines and stubbed SDKs (`uv run pytest`); `uv run pytest -m live` calls the real
API once with a cheap model.

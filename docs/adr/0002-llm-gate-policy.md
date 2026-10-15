# 2. The LLM gate decides from severities, not from the model's verdict

- Status: accepted
- Date: 2026-10-15

## Context

An LLM review can block merges only if its outcome is predictable enough to trust and cheap enough
to run on every PR. Asking the model "should this merge?" gives a verdict that shifts with wording
and can be talked into passing by text in the diff itself. Models also refuse, time out, or return
truncated output, and the gate has to say what happens then.

## Decision

- The model returns structured findings only (`Review`: summary plus findings with a severity from
  a rubric written into each prompt). `llm-gate` computes the verdict in code.
- Each check in `tools/llm-gate/checks.yaml` is **blocking** (fails when a finding is at or above
  `fail_on`) or **advisory** (reports, never fails). Today `code-review` blocks on `high` and
  `security-review` on `medium`; everything else is advisory.
- Blocking checks **fail closed**: an API error, refusal, truncated or missing output, or a diff over
  `max_diff_kb` fails the check (exit 2) unless the check sets `on_error: pass`.
- A human can override blocking findings with the `llm-override` PR label (write access needed).
  The findings are still reported; errors are not overridable.
- Prompts are files in `.claude/commands/llm-<check>.md`, shared with interactive Claude Code, and
  treat the diff as untrusted data. They are reviewed like code.
- Two engines sit behind one interface: the Messages API (diff inline, one request) and the Claude
  Agent SDK (the same prompt with read-only tools in the repository; originally run as a slash
  command, superseded by [ADR 0004](0004-gate-tooling-from-base-branch.md)). The check chooses one;
  `--engine both` and `llm-compare` exist to compare them.
- Results are cached by check, engine, model, prompt and diff, so re-running a PR without changes
  costs nothing.

## Consequences

- A prompt or rubric change can change verdicts; it goes through review like any other gate change.
- Fork and Dependabot PRs have no API key; the CI workflow (Phase 8) reports that instead of failing.
- The prompt files are named `llm-<check>` rather than `<check>` so they don't shadow Claude Code's
  built-in `/code-review` and `/security-review`.

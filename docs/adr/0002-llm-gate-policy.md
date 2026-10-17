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
  The findings are still reported.
- **Amended 2026-10-18: a diff over the size cap is overridable; other errors are not.** A file
  whose own diff is over `max_file_kb` (64 by default) is left out of what the model sees, and
  named in the PR comment, the audit record and the release attestation. Generated code (gRPC
  stubs, EF Core migrations, SQL seed data) would otherwise crowd the hand-written part of a
  change out of `max_diff_kb`, or push the whole diff over it, and a PR carrying such a file had
  no way through the gate but editing the gate. If the trimmed diff is still over `max_diff_kb`,
  the `llm-override` label plus its `/llm-override <reason>` comment accepts it **unreviewed**:
  the verdict stays `error`, the exit code becomes 0, and the record carries
  `override_honoured`. An API error, refusal, truncated output or a crash stays non-overridable:
  a gate that broke or refused is not an approval, and a re-run is the answer. The metrics count
  unreviewed overrides apart from overridden findings.
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
- **What the gate skipped is on the record, never silent** (2026-10-18). A trimmed file and an
  accepted-unreviewed diff both reach the release attestation's `unreviewed` list, so "this
  release was reviewed" keeps meaning what it says. The collector enforces the pairing: a blocking
  check reporting `error` with exit 0 and no honoured override is a tamper event.

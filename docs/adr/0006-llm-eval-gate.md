# 6. Prompt and gate changes are scored against known cases before they merge

- Status: accepted
- Date: 2026-10-16

## Context

Since ADR 0004, a change to the review prompts or to llm-gate takes effect only after it merges,
and nothing measured whether it made the reviewer better or worse. A prompt edit that stops finding
off-by-one bugs, or that starts blocking clean PRs, would pass every gate and show up only as
missed bugs or annoyed authors later.

## Decision

- Known cases live in `tools/llm-gate/evals/cases/`, as a diff plus expected and forbidden
  findings. The first set is planted bugs from the v1 drills, injection variants, and clean
  merged PRs. `llm-gate eval run` reviews each one `--repeats` times through the gate's own
  `run_check`. It reports recall, false blocks, noise, verdict accuracy, flip rate, injection
  resistance, cost and latency.
- `evals/baseline.json` holds the scores to beat, per check and engine/model. Updating it is a
  deliberate, reviewed change (`just eval-baseline` in a PR). `evals/thresholds.yaml` says how much
  worse a PR may be: recall may drop by at most 0.05, no new false blocks are allowed, the flip rate
  must stay at or below 0.10, and cost may rise by at most 25 %.
- `llm-eval.yml` runs on every PR and passes as "not applicable" unless the PR touches
  `.claude/commands/llm-*` or `tools/llm-gate/`. When it applies, it runs **the PR's** prompts and
  code. This is the opposite of ADR 0004, because here the change is the thing under test. The
  eval job gets the API key and a read-only token. The sticky comment is posted by a second job
  that runs only the base branch's script, with the write token.
- Each run has a budget (`budget_usd`, $6 by default). No new case starts once it is spent, and
  an incomplete run fails and can't become a baseline.

## Consequences

- A PR that changes the gate pays about $2 for its eval (each check's configured engine, 3
  repeats); a rerun of an unchanged PR is free (cache).
- The PR's code runs with the API key. Only collaborators can open PRs here and fork PRs get no
  secrets; the key's exposure is the same as for v1's llm-review. A team repository would add
  CODEOWNERS review for `tools/llm-gate/`.
- The cases are only as good as their coverage: a reviewer can score well here and miss a new
  kind of bug. Confirmed false positives (Phase 16) and new drill bugs should become cases.
- `eval_run` records go into the run's `.llm-gate/audit.jsonl` and the report artifact. They don't
  reach the `audit-log` branch yet: the collector only collects `llm-review` runs.
- `llm-eval` becomes a required check (ruleset and consistency script) once it is stable.

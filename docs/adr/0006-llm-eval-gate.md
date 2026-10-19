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
- **Amended 2026-10-18: a missing baseline entry fails the comparison.** It used to mean "only the
  absolute limits apply", which made the gate vacuous for the change most worth checking: switch a
  check's engine or model and recall, false blocks and verdict accuracy were each compared against
  nothing, leaving only flips and fp-regressions (F008). The row now says which entry is missing,
  and the remedy is the one this ADR already prescribes for an intended trade-off: run
  `just eval-baseline` in the same PR, so the new scores are reviewed as part of the change.
- `llm-eval.yml` runs on every PR and passes as "not applicable" unless the PR touches
  `.claude/commands/llm-*` or `tools/llm-gate/`. When it applies, it runs **the PR's** prompts and
  code. This is the opposite of ADR 0004, because here the change is the thing under test. The
  eval job gets the API key and a read-only token. The sticky comment is posted by a second job
  that runs only the base branch's script, with the write token.
- Each run has a budget (`budget_usd`, $6 by default). No new case starts once it is spent, and
  an incomplete run fails and can't become a baseline.

## Consequences

- A PR that changes the gate pays only for the checks whose **prompt or engine settings** it
  changes: `llm-eval` also runs on pushes to `main` that touch the gate, and the cache it saves
  there is the one every PR restores (GitHub lets a PR read only its own branch's caches and
  `main`'s). Without it, each such PR re-reviewed every case cold, about $1.30. A rerun of an
  unchanged PR is free.

  **Amended 2026-10-19: "or code" was too generous a reading, and the gap mattered.** The cache
  key held check, engine, model, prompt and diff, so a change to anything else in the gate was a
  cache *hit*: a PR that halved `max_turns`, emptied the read-only tool list or changed the output
  schema -- touching no prompt -- reproduced the baseline exactly and passed (F012, F139). Each
  engine now declares its `request_shape` (limits, tool lists, schema) and that joins the key.
  What is still not covered is the rest of the gate's code -- the prompt assembly, the diff
  builder, `policy.decide` -- so `CACHE_VERSION` remains a hand-bumped constant, and a PR that
  changes how a request is *built* rather than what it contains still needs that bump. The eval
  gate's own review (code-review blocks at high risk on `tools/llm-gate/**`) is what is supposed
  to catch a missing bump.
- The PR's code runs with the API key. Only collaborators can open PRs here and fork PRs get no
  secrets; the key's exposure is the same as for v1's llm-review. A team repository would add
  CODEOWNERS review for `tools/llm-gate/`.
- Scores vary between runs even with unchanged prompts: a model can agree with itself on every
  repeat of one session and disagree in the next. With few expected findings per check, one case
  moves recall by about 0.17, more than the 0.05 the gate allows. So cases whose right severity
  is debatable expect "found at medium" plus `blocking: true`, and verdict accuracy carries the
  severity question with its own threshold (a drop of at most 0.10). More cases make every
  threshold less sensitive to one case.
- The cases are only as good as their coverage: a reviewer can score well here and miss a new
  kind of bug. Confirmed false positives (Phase 16) and new drill bugs should become cases.
- **Amended 2026-10-18: an expectation may be file-level** (`lines: null`). A case whose right
  answer is "nothing tests this behaviour" is about a file, and the models report it with a line one
  repeat and without one the next; the matcher required a line, so `te-001` scored 0.67 in CI on an
  unchanged prompt. File-level matching is weaker — any finding in that file at or above the
  severity counts — so it is for cases whose answer genuinely has no line, not for planted bugs.
- **Amended 2026-10-18 (F037): every check has at least one scored case.** `llm-eval` takes its
  check list from the cases, so a check no case names was never evaluated: `docs-drift` had no case
  at all, and `test-review` had only an fp-regression case, whose baseline recall was `null`. Both
  prompts could have been cut down to "report nothing" and the gate would have passed. They now
  have a bug case each (`dd-001-renamed-recipe-stale-doc`, `te-001-untested-month-filter`) with
  recall in the baseline; cutting either prompt down to "report nothing" takes recall to 0.00 and
  fails the gate, which is how both cases were checked.
- `eval_run` records go into the run's `.llm-gate/audit.jsonl` and the report artifact. They don't
  reach the `audit-log` branch yet: the collector only collects `llm-review` runs.
- `llm-eval` is a required check since 2026-10-16 (`main.json`, checked by
  `scripts/check-ruleset-consistency.py`), after it ran green on #37, #38 and `main` and red only
  for drill 14 (recall 1.00 → 0.17).

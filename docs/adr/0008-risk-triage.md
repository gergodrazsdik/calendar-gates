# 8. Risk triage: a deterministic floor that a model may raise and people may change

- Status: accepted
- Date: 2026-10-17

## Context

Every PR got the same LLM reviews at the same strength. A docs typo paid for a security review,
and a workflow change got no more scrutiny than a test. The plan (docs/PLAN-v2.md Phase 17) calls
this policy ADR-0006, but that number went to the eval gate.

Two constraints shape any fix:

- Required checks must always report. A skipped required job blocks every PR (v1 drill 8).
- Anything a PR controls can't decide how much the PR is reviewed.

## Decision

A `triage` job runs first in `llm-review.yml`, from the base branch's tooling (ADR 0004), and
gives the PR a risk of `low`, `medium` or `high`. `tools/llm-gate/checks.yaml` (`triage:`) holds
all of the policy.

1. **The floor is deterministic.** Every changed file gets the risk of the first rule it matches
   (`default_risk` if it matches none), and the PR gets the maximum. The rules:
   - **high:** `.github/`, the gate (`tools/llm-gate/`, the review prompts, `scripts/`), and
     deployment;
   - **medium:** agent instructions, dependencies and `src/`;
   - **low:** tests and docs.

   More than 200 or 800 changed lines (lock files excluded) raise the floor to medium or high.
2. **AI-assisted work raises the floor by one level.** It counts as AI-assisted when a commit
   trailer, the PR body or the branch name carries a marker (`ai_markers:`).
3. **A cheap model may raise the risk, never lower it.** It reads the file list and the first
   50 KB of the diff as data, with the same framing the reviews use. If it fails or refuses, the
   floor stands.
4. **People may change the risk in either direction, with a recorded reason:**
   `/llm-risk <level> <reason>` (ADR 0007).
   - The command writes a `risk_override` record to `audit-log`, and triage reads it from there.
     `llm-feedback.yml` writes these records only after checking the commenter's role, and the
     collector never accepts them from a PR's run.
   - Labels are never an input. Triage sets `risk:<level>` and `ai-assisted` itself with
     `GITHUB_TOKEN`, so its labels start no runs. A person changing a `risk:*` label starts a
     run, and triage puts its own label back.
5. **The level decides what runs.**
   - `low`: code-review and docs-drift, both advisory.
   - `medium`: everything but workflow-review. Code-review and security-review block.
   - `high`: everything. The blocking checks move to the agent engine, keeping their own model
     (amended 2026-10-17; see Consequences).

   Every `llm / <check>` job still runs and reports. A check outside the level's plan passes as
   "not needed at risk: <level>" (verdict `not_needed`), and one that is advisory at this level
   can't fail. `scripts/check-ruleset-consistency.py` requires every check that blocks at *any*
   level.
6. **The collector checks the triage.** `audit-collect.yml` recomputes the floor from data the PR's
   run doesn't control:
   - the compare API's files and commits for the head commit;
   - the PR description;
   - the default branch's `checks.yaml`;
   - the PR's `risk_override` records.

   It writes `tamper_suspected` when any of these doesn't hold:
   - the triage record's rules risk or AI flag matches the recomputed one;
   - its final risk is the higher of the rules' and the model's (unless a recorded `/llm-risk`
     set it);
   - every `gate_run` of the run has that risk;
   - every `gate_run` ran, or didn't, and blocked, or didn't, as the plan for that level says.

## Consequences

- **The markers are self-declared.** `AGENTS.md` asks agents to add trailers, and Claude Code adds
  them by default, but nothing proves a commit wasn't AI-assisted. The markers are a transparency
  signal for triage and the metrics, not enforcement.
- **Most PRs here will be rated high.** Most PRs in this repository are Claude-assisted and touch
  the gate, so code-review and security-review usually run on the agent engine. Each review is
  capped by `budget_usd`. Setting `ai_assisted_raise: 0` is a one-line policy change, and it goes
  through review like any other change to `checks.yaml`.
- **Amended 2026-10-17: Sonnet, not Opus, at high risk.** The high level first also switched the
  blocking checks to Opus (`LLM_MODEL_STRONG`). The model evals done for docs/WRITEUP.md then
  showed no gain. On the agent engine, Opus matched Sonnet's recall (1.00) but was noisier on
  clean cases (0.87 vs 0.23 findings per code-review case) and less consistent (verdict
  accuracy 0.96 vs 1.00). It cost 3 to 4 times more per review. The level now changes only the
  engine.
- **The model can only add review.** A prompt injection that talks the model down changes nothing,
  because the floor still holds. Talking it up costs money but weakens nothing. Eval case
  `tr-008` keeps checking that the model raises when the diff asks for a low rating.
- **The collector's comparison isn't perfect.** It uses the PR description at collection time, so
  an edit to the description between the run and the collection can show up as a mismatch on the
  AI flag. Runs from workflows older than triage have no triage record. Their records are accepted
  with no risk, and a record that claims a risk without a triage record is flagged.
- **The evals cover triage:** `kind: triage` cases with `expect_risk`, scored as risk accuracy.
  Any result below the floor fails the eval outright.

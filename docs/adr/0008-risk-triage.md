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

- **Amended 2026-10-18 (F021): the deterministic gates' own configuration is rated high.**
  `.grype.yaml`, `.yamllint.yaml`, `.editorconfig`, `lefthook.yml`, `justfile`, `global.json`,
  `uv.toml`, `.config/**` and `Directory.Build.props` decide what `lint`, `format`, `grype` and
  `build-test` accept, and used to fall through to `default_risk: medium` — so a PR adding a grype
  ignore got the cheap engine and no `workflow-review`, while the same change under `.github/`
  got the full set.
- **Amended 2026-10-18 (F022): a run is judged by the `checks.yaml` it used.** The collector
  recomputed the floor and the plans from the default branch's config *at collection time*, so a
  change to `triage.rules` or a level's plan that merged while a review was in flight made that
  run's records inconsistent with the recomputation and the whole run became `tamper_suspected`.
  It now reads the config at the run's own `gate_sha`, but only after proving that commit is an
  ancestor of the trunk and that the file there hashes to the `config_sha256` the records carry;
  anything else falls back to the current config, as before.
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
- **The writers list covers every command** (2026-10-18). The collector accepts a `/llm-risk`
  record only from someone with write access, and it got that list from
  `scripts/override-writers.sh`, which listed the authors of **`/llm-override`** comments only. A
  PR that used `/llm-risk` without an override therefore had an empty list, its record was refused,
  and its whole run became tamper events: v0.3.2's attestation shows that for #68 (one triage
  record rejected, then the six check records that depend on it). The script now lists the authors
  of any `/llm-*` command; `find_override` is unaffected, because it still requires an unedited
  `/llm-override <reason>` comment from the person. `tools/llm-gate/tests/test_scripts.py` pins it
  with a stubbed `gh`, which is also what F070 asked for.
- **A lowering is tied to its head** (2026-10-18). `/llm-risk low` used to decide every later
  push to the PR: the record carried no head, and a manual level won outright, so code pushed
  after the person had looked went unreviewed, at a level where nothing blocks. The record now
  carries the PR's head when the comment arrived, and a level at or below the rules' floor applies
  only to that head; a **raise** still persists, because it only ever adds review. Triage and the
  collector share one rule (`triage.manual_applies`), so a run that honoured a stale lowering is
  flagged instead of accepted. An older record with no head can no longer lower anything.
- **A size that can't be counted is high risk** (2026-10-18). `git diff --numstat` prints `-` for
  a file it won't diff, which used to count as 0 changed lines: a binary file, or a text file with
  a NUL byte in it, slipped past the size rule entirely. Such a file now raises the floor to high
  and is named in the reasons, on both sides — the collector reads the compare API's 0/0-with-no-
  patch the same way, so an honest PR with a binary file isn't flagged as tampering. `.gitattributes`
  is rated high with the rest of the gate configuration.
- **A partial re-run reuses the triage record** (2026-10-18). GitHub's "Re-run failed jobs"
  doesn't re-run a successful `triage` job, so the new attempt has no triage artifact and every
  re-run verdict carrying a risk was recorded as a tamper event, leaving the PR unreviewed and
  unverified in the release attestation. The collector now takes the latest earlier attempt's
  triage artifact, validates it against that attempt and marks it `reused_from_attempt`, which
  only it may set. Only triage is reusable, because only triage isn't re-run.
- **The model can't crash triage** (2026-10-18). The Messages SDK validates structured output
  inside `parse`, so output that doesn't fit the schema arrived as a `pydantic.ValidationError`
  and killed the job, and with it every `llm / <check>` of the run. It is an `EngineError` now,
  which is what `assess`'s "the floor stands" always meant. `TriageAssessment.reasons` no longer
  caps the list client-side: the API doesn't enforce `maxItems`, so the cap only turned a verbose
  model into a failed gate. Callers take the first three.
- **The evals cover triage:** `kind: triage` cases with `expect_risk`, scored as risk accuracy.
  Any result below the floor fails the eval outright.

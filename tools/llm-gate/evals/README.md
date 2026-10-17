# Evals for the review prompts

These evals answer two questions: "how good is the reviewer?" and "did this prompt change make it
worse?" (docs/PLAN-v2.md Phase 15, [ADR 0006](../../../docs/adr/0006-llm-eval-gate.md)). Every
case is a known diff with a known right answer. `llm-gate eval run` reviews each case through the
same `run_check` the gate uses and scores the results.

```
cases/<id>/case.yaml     what should (expect) and shouldn't (forbid) be found
cases/<id>/diff.patch    the change; applies to the case's `base` commit
baseline.json            the scores to beat, per check and engine/model (`just eval-baseline`)
thresholds.yaml          how much worse than the baseline a PR may be, and the budget per run
```

## A case

```yaml
id: cr-001-workdays-off-by-one     # = the directory name
kind: bug                          # bug | clean | injection | fp-regression | triage
checks: [code-review]
source: drill-5                    # where it came from
description: Workdays drop the inclusive end day.
base: 7e1faf97961a83dbc659b9b8f884d554790c7714   # diff.patch applies to this commit
expect:
  - file: src/CalendarGates.Api/Domain/WorkdaysCalculator.cs
    lines: [15, 15]                # new-file lines; a finding may be up to 3 lines off
    min_severity: high             # at least this severity counts as found (recall)
    blocking: true                 # optional: the gate should fail on it (verdict accuracy);
                                   # default: min_severity is at or above the check's fail_on
    category: correctness          # documents the intent; not matched
forbid: []                         # fp-regression: findings that must not come back
```

Each case is reviewed in a temporary export of `base` with the patch applied, so the agent engine
reads a consistent tree. The repository isn't touched. The gate's verdict for the case is expected
to be `fail` when an expected finding is blocking, and `pass` otherwise.

Keep "found" and "blocking" apart when the right severity is a judgment call. The first CI run of
`cr-002` (a wrong Easter date in about 1 year in 30) rated it medium in every repeat, where the
local baseline rated it high in every repeat. As `min_severity: high` that one case alone moved
recall by 0.17 and failed the gate on an unchanged prompt. As `min_severity: medium, blocking: true`
the drift shows up in verdict accuracy, which allows a drop of 0.10.

- **bug**: planted from the v1 gate drills, or written for the evals.
- **clean**: a merged PR (`git show <sha>`); any blocking finding is a false block.
- **injection**: a real bug plus text telling the reviewer to approve. The bug must still be found
  and the gate must still fail.
- **fp-regression**: `llm-gate eval add-from-fp <finding-id>` builds one from a finding in the
  audit log (`just audit-pull` first). It holds the same diff, and that finding must not come back.
- **triage** ([ADR 0008](../../../docs/adr/0008-risk-triage.md)): `checks: [triage]`,
  `expect_risk: low|medium|high`, optionally `ai_assisted: true`. The rules' floor comes from the
  patch, then the triage model (`.claude/commands/llm-triage.md`) may raise it. Scored as risk
  accuracy (`max_risk_accuracy_drop` in `thresholds.yaml`). A result below the floor is a floor
  violation and always fails the eval.

## Scores

| Metric | Meaning |
|---|---|
| recall | expected findings found / expected findings, over all repeats |
| false blocks | clean repeats the gate would have failed / clean repeats |
| noise | findings below `fail_on` per clean repeat |
| verdicts | repeats whose pass/fail is the expected one |
| flips | cases whose verdict changes between repeats |
| injection | injection repeats where the bug is found and the gate fails |
| errors, cost, latency | engine errors; total cost; p50/p90 per review |

`--compare` checks the run against `baseline.json` using `thresholds.yaml`. The report goes to
`reports/eval/<check>-<prompt sha>.json`. Repeats are separate cache entries and reruns of unchanged
cases are free, so changing one prompt only pays for that check's reviews.

```sh
just eval                                   # every check the cases name, its configured engine
just eval --check code-review --engine both --repeats 1   # quick, both engines
just eval-baseline                          # baseline.json from the last run; commit it in a PR
uv run --project tools/llm-gate llm-gate eval add-from-fp cr-3f2a
```

A full baseline with both engines costs about $4 (about 30 cases × 3 repeats, $0.01–0.04 per review).
`llm-eval` in CI uses each check's own engine. It starts from the cache that its run on `main` keeps
warm, so a PR pays only for the checks it changes: about $0.70 for a code-review prompt change, $0
for the rest.

# Gate health metrics

`llm-gate metrics` (`tools/llm-gate/src/llm_gate/metrics.py`) reports these over the `audit-log`
branch ([ADR 0005](adr/0005-audit-trail.md)), the merged PRs from the GitHub API and the latest
eval run ([ADR 0006](adr/0006-llm-eval-gate.md)). Locally: `just metrics [days]`. Weekly:
`metrics.yml` writes the report into the pinned "Gate health" issue (repository variable
`GATE_HEALTH_ISSUE`). To set that up once: open an issue (any title, "Gate health" by convention),
pin it, then `gh variable set GATE_HEALTH_ISSUE --body <number>`. With the variable unset the
weekly job still runs and leaves the report in its job summary, so nothing is lost.

The window is the last 30 days (`--since-days`), but never earlier than the first audit record:
PRs merged before the log existed can't be covered.

| Metric | Definition | Source |
|---|---|---|
| Coverage | merged PRs where every blocking check has a `gate_run` with a real verdict (`pass`, `fail`, `not_applicable`; not `skipped_no_key` or `error`) / merged PRs | `gate_run`, merged PRs |

| Review turnaround | `finished_at − pr_event_at` per check, p50/p90, for reviews that ran (`pass`, `fail`, `error`) | `gate_run` |
| False-positive rate | per check and severity: findings marked `/llm-fp` / distinct findings (a finding counts once per PR, however often it was re-reported; when people marked it more than once, the latest verdict by time wins); also fp / (fp + ack), over the findings people looked at | `gate_run` findings, `feedback` |
| Override rate | PRs with an honoured override / PRs where a blocking check failed | `gate_run` (`override_honoured`, `verdict`) |
| Cost | paid reviews only (cache hits record none): total, per check, per engine/model, p50/p90 per reviewed PR | `gate_run.cost_usd` |
| Triage mix | share of PRs per final risk; manual `/llm-risk` changes | `triage`, `risk_override` ([ADR 0008](adr/0008-risk-triage.md)) |
| AI-assisted share | triaged PRs flagged as AI-assisted / triaged PRs; and side by side for flagged and other triaged PRs: distinct findings per PR, and the share of findings marked `/llm-fp` | `triage`, `gate_run` findings, `feedback` |
| Eval trend | the latest eval run's recall, false blocks, verdict accuracy and flips per check, engine and prompt | `llm-eval` artifact (`reports/eval/`) |
| Integrity | `tamper_suspected` events, reviews from PRs that changed the review workflow, rejected `/llm-*` commands | `tamper_suspected`, `gate_run.workflow_modified`, `feedback_rejected` |

A metric without data says "no data yet". A record's `blocking` is what the check actually was for
that run: one the triage plan dropped records `blocking: false`, whatever its mode in `checks.yaml`
says, so a query for "blocking checks that didn't review" can't count every low-risk PR (F040).

## Feedback commands

People with write access feed the false-positive rate with PR comments (`llm-feedback.yml`,
[ADR 0007](adr/0007-feedback-commands.md)):

- `/llm-fp <finding-id> <reason>`: a false positive. The finding's row in the sticky comment gets
  marked, and `llm-gate eval add-from-fp <finding-id>` turns it into an eval case.
- `/llm-ack <finding-id>`: a true positive.
- `/llm-override <reason>`: overrides the blocking checks (the label is added and the review re-run).
- `/llm-risk <low|medium|high> <reason>`: a manual risk change; triage re-runs with it
  ([ADR 0008](adr/0008-risk-triage.md)).

Finding ids (`cr-1705`) are in each check's sticky comment.

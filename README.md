# audit-log

The audit trail of calendar-gates' LLM review gate ([ADR 0005](https://github.com/gergodrazsdik/calendar-gates/blob/main/docs/adr/0005-audit-trail.md)).
Nobody edits the records by hand. Two workflows append them through the contents API, so GitHub
signs the commits: `audit-collect.yml` one file per review run, check and attempt, and
`llm-feedback.yml` one file per `/llm-*` PR comment. The `audit-log` ruleset blocks deletion and
force pushes, so history only grows. This README is the one exception: no workflow maintains it,
so the owner updates it by hand when the record types change.

```
events/YYYY/MM/DD/<run_id>-<attempt>-<check>.jsonl              # a check's review
events/YYYY/MM/DD/<run_id>-<attempt>-triage.jsonl               # the triage job
events/YYYY/MM/DD/<run_id>-<attempt>-<check>-recollected.jsonl  # a run collected again
events/YYYY/MM/DD/feedback-<id>.jsonl                           # a /llm-* comment
```

Each line is one JSON record, `schema: audit/v1`. The models are in
`tools/llm-gate/src/llm_gate/audit.py` on `main`. Every record has `id`, `ts`, `type`, `repo`,
`pr`, `head_sha`, `base_sha`, `actor`, `workflow_run_id`, `run_attempt` and `run_url`.

| `type` | What |
|---|---|
| `gate_run` | One check's decision. It records the gate commit and the prompt, config and diff hashes. It also has the engine, model, usage, cost and tool calls, finding ids and titles, the verdict, the exit code and any override. The collector adds `workflow_modified` and `check_run_conclusion`. |
| `override` | An honoured `llm-override`: who did it and why. The collector checked it against the PR's label events and comments. |
| `tamper_suspected` | An artifact that didn't check out, with the problems found. The artifact's own records are not written. |
| `triage` | The triage job's risk decision (ADR 0008). The collector recomputes the rules' risk and the AI marker from the GitHub API, and checks every `gate_run` of the run against the final risk. |
| `feedback` | A `/llm-fp` or `/llm-ack` on a finding (ADR 0007). |
| `feedback_rejected` | A `/llm-*` comment that wasn't honoured. Fixed fields only, because anyone can comment on a public repository's PRs. |
| `risk_override` | A `/llm-risk` change to a PR's level (ADR 0008). |

`eval_run` records stay in `llm-eval`'s workflow artifacts and don't reach this branch (ADR 0006).

The log never stores the diff or the raw model output. Free text is redacted and truncated.
For runs whose PR changed `llm-review.yml` (`workflow_modified: true`), the free text is
withheld entirely, and those reviews don't count as verified.

## Querying

```sh
just audit-pull            # on main: fetches this branch into .audit-log/
cat .audit-log/events/*/*/*/*.jsonl | jq -c 'select(.type == "gate_run")
  | {pr, check, verdict, model, cost_usd, findings: [.findings[].id]}'
```

# audit-log

The audit trail of calendar-gates' LLM review gate ([ADR 0005](https://github.com/gergodrazsdik/calendar-gates/blob/main/docs/adr/0005-audit-trail.md)).
Nobody edits this branch by hand. `audit-collect.yml` appends one file per review run, check
and attempt, through the contents API, so GitHub signs the commits. The `audit-log` ruleset
blocks deletion and force pushes, so history only grows.

```
events/YYYY/MM/DD/<run_id>-<attempt>-<check>.jsonl
```

Each line is one JSON record, `schema: audit/v1`. The models are in
`tools/llm-gate/src/llm_gate/audit.py` on `main`. Every record has `id`, `ts`, `type`, `repo`,
`pr`, `head_sha`, `base_sha`, `actor`, `workflow_run_id`, `run_attempt` and `run_url`.

| `type` | What |
|---|---|
| `gate_run` | One check's decision. It records the gate commit and the prompt, config and diff hashes. It also has the engine, model, usage, cost and tool calls, finding ids and titles, the verdict, the exit code and any override. The collector adds `workflow_modified` and `check_run_conclusion`. |
| `override` | An honoured `llm-override`: who did it and why. The collector checked it against the PR's label events and comments. |
| `tamper_suspected` | An artifact that didn't check out, with the problems found. The artifact's own records are not written. |
| `triage`, `feedback`, `risk_override`, `eval_run` | Later phases. |

The log never stores the diff or the raw model output. Free text is redacted and truncated.
For runs whose PR changed `llm-review.yml` (`workflow_modified: true`), the free text is
withheld entirely, and those reviews don't count as verified.

## Querying

```sh
just audit-pull            # on main: fetches this branch into .audit-log/
cat .audit-log/events/*/*/*/*.jsonl | jq -c 'select(.type == "gate_run")
  | {pr, check, verdict, model, cost_usd, findings: [.findings[].id]}'
```

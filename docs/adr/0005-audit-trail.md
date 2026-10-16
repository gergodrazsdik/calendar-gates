# 5. Every gate decision is an audit record; a trusted workflow writes the log

- Status: accepted
- Date: 2026-10-16

## Context

Until v2 a gate decision lived in a sticky comment, a job summary and a workflow artifact that
expires after seven days. Nothing let you ask later "which prompt and model approved this commit,
what did the reviewer look at, who overrode it and why". The data that answers that is produced by
the `llm` jobs, which run a workflow file the PR can edit (ADR 0004, remaining hole), so their
output can't simply be trusted either.

## Decision

- **Schema `audit/v1`** (`tools/llm-gate/src/llm_gate/audit.py`, pydantic, unknown fields
  rejected): one JSON object per line with the run context (`repo`, `pr`, `head_sha`, `base_sha`,
  `actor`, `workflow_run_id`, `run_attempt`, `run_url`) and a `type`: `gate_run`, `triage`,
  `override`, `feedback`, `risk_override`, `eval_run`, `tamper_suspected`.
- A `gate_run` holds what the decision was made with and what came out: the gate commit, prompt
  and config hashes, the diff's hash and size, model, usage and cost, cache hit, the agent's tool
  calls, finding titles with stable ids, verdict, exit code, override. **Not stored**: the diff
  (it's in git), the raw model output (a 90-day workflow artifact), anything else from the
  environment. Every string field is either a strict pattern (SHAs, digests, repository, login,
  check, model and engine names) or free text that the schema itself redacts with gitleaks-style
  patterns and truncates (`redact.py`), and lists have caps. That happens when a record is built
  and again when the collector parses an artifact: the log is public and can't be rewritten. The SDK's `StructuredOutput` call (the raw
  review) isn't logged.
- **Untrusted side**: `llm-gate run` appends its records to `.llm-gate/audit.jsonl`, the `llm` job
  uploads it as `audit-<run_id>-<check>` with its read-only token. Checks that don't run record
  that too (`llm-gate audit skip`).
- **Trusted side**: `audit-collect.yml` runs on `workflow_run` (code from the default branch),
  never checks out the PR, downloads the artifacts and runs `llm-gate audit collect`. That parses
  strictly, enforces size and count limits (128 KB per artifact, 256 KB and 20 artifacts per
  run), accepts only `gate_run` and `override` records for
  checks in the default branch's `checks.yaml`, and compares every record with what the event says
  (run id, attempt, head SHA, PR, repository) and with its job: the job must exist and have
  finished with the conclusion the record's exit code implies, and verdict and exit code must
  agree. It sets
  `workflow_modified` when the PR changed the review workflow; such reviews never count as
  verified, and their free text (finding titles and files, tool-call inputs, errors, override
  reasons) is withheld: only ids, severities, verdicts, hashes and counts reach the log. It looks up the override itself (`find_override` on the PR's issue events and
  comments), and an `override` record or `override_honoured` that doesn't match is a problem.
  Anything that doesn't check out is written as one `tamper_suspected` event instead. Its
  problems are fixed messages with field names and pydantic error codes, never values or names
  from the artifact, so a deliberately invalid artifact can't smuggle text past the withholding.
- The log is the orphan branch **`audit-log`**: one file per run, check and attempt
  (`events/YYYY/MM/DD/<run_id>-<attempt>-<check>.jsonl`), written through the contents API
  (commits signed by GitHub), serialised by `concurrency: audit-log`. A ruleset blocks deletion and
  force pushes, so history only grows.
- **Overrides need a reason.** `llm-override` is honoured only with an unedited
  `/llm-override <reason>` comment by whoever added the label last, written after the label
  (issue events API); `llm-gate run` ignores an override without a reason and records one with it
  as an `override` event.

## Consequences

- An audit question is a `jq` over `just audit-pull`'s checkout, not an archaeology dig through
  expired runs.
- The PR's workflow can still write whatever it likes into its artifact. The collector can't prove
  a record true; it checks what it can verify independently (the run, the job conclusion, whether
  the workflow was modified) and records the rest as claimed. A collector bug is the weakest link,
  so its validation has its own tests (gate drill 22 forges an artifact).
- The file name includes the attempt, which the plan's `<run_id>-<check>` didn't: re-runs would
  otherwise overwrite the first attempt's record.
- **Accepted risk: free text in a permanent log.** Even with an unmodified workflow, finding titles
  and tool-call paths can be steered by the PR (prompt injection into the review, oddly named
  files). They are bounded, redacted and only as permanent as the ruleset makes them: removing an
  entry takes an admin bypassing the `audit-log` ruleset, which is itself visible in the ruleset's
  history. That is the price of a log that answers "what did the reviewer look at" with more than
  hashes. Only collaborators can open PRs here, and there is no budget per PR across runs; a
  public repository taking outside PRs should add one, or keep titles in a prunable store.
- A record whose job was cancelled or never finished is written as `tamper_suspected` too: the
  name means "couldn't be confirmed", not proof of an attack, and its `problems` say which.
- The collector compares the record with the job's conclusion from the Actions jobs API (the
  `llm / <check>` job *is* that check run), so it needs `actions: read` and no `checks: read`.

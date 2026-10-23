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
  uploads it as `audit-<run_id>-<attempt>-<check>`. That job's token is read-only on contents; it
  holds `pull-requests: write` so it can post the sticky review comment, which is why nothing it
  writes is trusted without the collector's checks. Checks that don't run record
  that too (`llm-gate audit skip`).
- **Trusted side**: `audit-collect.yml` runs on `workflow_run` (code from the default branch),
  never checks out the PR, downloads the artifacts and runs `llm-gate audit collect`. That parses
  strictly, enforces size and count limits (128 KB per artifact, 256 KB and 20 artifacts per
  run), accepts only `gate_run` and `override` records for checks in the default branch's `checks.yaml`
  (plus the `triage` artifact's single `triage` record, [ADR 0008](0008-risk-triage.md)), and compares every record with what the event says
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
  (commits signed by GitHub). A ruleset blocks deletion and force pushes for everyone, so history
  only grows.
- **Overrides need a reason.** `llm-override` is honoured only with an unedited
  `/llm-override <reason>` comment by whoever added the label last, written since the label was
  last removed, before or after adding it (issue events API); `llm-gate run` ignores an override without a reason and records one with it
  as an `override` event.
- **Amended 2026-10-18 (F007, F022, F039, F075).** Four things the collector and the override
  check got wrong, none of them exploitable in this one-owner repository and all of them wrong as
  soon as it isn't: an override added as a *label* skipped the write-role lookup that the
  `/llm-override` comment path enforces, although applying a label needs only the triage role, so
  both paths use the role list now and neither is honoured without it; a run is judged by the
  `checks.yaml` **it used**, read at its own `gate_sha` once that commit is proved to be an
  ancestor of the trunk and the file hashes to the record's `config_sha256`, so a config change
  that merges mid-review no longer turns the run into `tamper_suspected`; record paths follow the
  triggering event's day (`--date`, the comment's `created_at`) instead of the collector's clock,
  so a re-run hits the same path and the append-only guard sees it; and `GH_TOKEN` is set on the
  steps that call the API, not on the job, so the step that parses PR-written artifacts holds no
  token that can write to a branch.
- **Amended 2026-10-18 (F025): an `override` record means the override changed an
  outcome.** The label is PR-wide and every llm job reads it, so a record per job made one
  override read as six in the release notes and the attestation, including advisory, passing and
  not-applicable checks. `llm-gate run` now writes the record only for the three outcomes an
  override actually changes: findings reported without failing (`OVERRIDDEN`), an unreviewable
  diff accepted (`override_honoured` on an `error`), and a blocking check reviewing a diff with
  files omitted. The collector's pairing is unchanged, because every record it demands an override
  for is still one of those three.

- **Local AI session log** (14.6, local only): a project hook appends each tool call of a Claude
  Code session to `~/.local/state/calendar-gates/claude-audit/<session-id>.jsonl`. A commit made
  from the session gets a `Claude-Session: <session-id>` trailer, added by lefthook's
  `prepare-commit-msg` when `CLAUDECODE=1`. So for AI-assisted work, a commit leads back to what the
  session did.

## Consequences

- An audit question is a `jq` over `just audit-pull`'s checkout, not an archaeology dig through
  expired runs.
- The PR's workflow can still write whatever it likes into its artifact. The collector can't prove
  a record true; it checks what it can verify independently (the run, the job conclusion, whether
  the workflow was modified) and records the rest as claimed. A collector bug is the weakest link,
  so its validation has its own tests (gate drill 22 forges an artifact).
- No `concurrency` group, unlike the plan: GitHub keeps only one *pending* run per group and
  cancels the rest, which would silently drop records when several reviews finish together.
  Concurrent writes go to different files and retry with backoff when the branch head moved.
- Anyone with write access, and any workflow with `contents: write`, can still *add* commits to
  `audit-log`; they just can't rewrite or delete it. Restricting updates to the GitHub Actions app
  needs an organization: a personal repository's ruleset rejects the app as a bypass actor
  ("must be part of the ruleset source or owner organization"). Added commits stay visible, and
  the collector's own are signed by GitHub and made by `github-actions[bot]`.
- **Amended 2026-10-18: an appended record can't quietly steer a review.** Appending stays
  possible, so what changed is what reading does with it. `triage.risk_overrides` skips a line
  that isn't a JSON object or whose fields don't fit (a bare `[]` used to crash triage for every
  PR) and ignores a `ts` more than ten minutes in the future, so a forged record can no longer
  outrank every genuine `/llm-risk` by date. The collector goes further: `/llm-risk` records count
  only when the comment they name (`feedback-<comment_id>.jsonl`) still exists on the PR, is
  unedited, was written by the login in the record, and asks for the same level, the way
  `find_override` checks an override's reason. A record that fails is reported and can't explain
  the run's risk, so the run is flagged instead of accepted.
- **Amended 2026-10-19: reading the log is as strict as writing it.** The two bullets above are
  about the collector and about triage. The release attestation and the metrics were the readers
  nobody had revisited: both walked `events/**` with `json.loads` and accepted any object, so
  `llm_review()` treated anything carrying `"type": "gate_run"` with a matching PR and head as a
  verdict. One appended, well-formed line could therefore turn an unreviewed PR into a reviewed
  one inside a *signed* predicate — the artefact most likely to be shown to someone as evidence.
  Both now use `audit.load_events`, which validates every line against the same models the
  collector writes with, and **counts** what it refused: the count reaches the predicate
  (`rejected_records`) and the weekly report, so a planted or malformed line is visible instead of
  absent. Across the 700 record files in the log today it refuses nothing.
- **Amended 2026-10-18: `workflow_modified` covers what can steer a review**, not just the
  triggering workflow's own path: any `.github/workflows/**` or `.github/actions/**` change (a
  sibling workflow runs on the same event and shares the PR's cache scope) and `.gitattributes`
  (it decides what `git diff` shows). Such runs are recorded as unverified and their free text is
  withheld, so every PR that touches CI appears in the release attestation's `unverified` list.
  That is noisier and truer. The collector also refuses a blocking record claiming a cache hit,
  because `llm-review` keeps no review cache (ADR 0002).
- Artifact and file names include the attempt, which the plan's `<run_id>-<check>` didn't: a
  re-run of failed jobs keeps the first attempt's artifacts in the run, and its records would
  otherwise overwrite (or be mistaken for) the new attempt's.
- **Accepted risk: free text in a permanent log.** Even with an unmodified workflow, finding titles
  and tool-call paths can be steered by the PR (prompt injection into the review, oddly named
  files). They are bounded, redacted and only as permanent as the ruleset makes them: removing an
  entry takes an admin bypassing the `audit-log` ruleset, which is itself visible in the ruleset's
  history. That is the price of a log that answers "what did the reviewer look at" with more than
  hashes. Only collaborators can open PRs here, and there is no budget per PR across runs; a
  public repository taking outside PRs should add one, or keep titles in a prunable store.
- Model names must start with `claude-` and tool names outside Claude Code's built-in set are
  logged as `other`: both are text the run chose. A run with another model writes no record (the
  review itself is unaffected); widen the pattern when that becomes real.
- A record whose job was cancelled or never finished is written as `tamper_suspected` too: the
  name means "couldn't be confirmed", not proof of an attack, and its `problems` say which.
  **Amended 2026-10-24: "not finished yet" is no longer one of them.**
  - **What happened:** right after `workflow_run: completed`, the jobs API can still report
    `conclusion: null` for jobs that finished moments earlier. On 2026-10-19 it did for minutes.

    | Run | Marked complete | Collected | Null conclusions |
    |---|---|---|---|
    | 39283814132 (#92) | 13 min after its last job | 2 s later | all |
    | 39286007434 (#93) | 8 min after | 2 s later | all |
    | 39287691571 (#93's merged head) | 8 s after | 3 s later | five of seven |

    Each of those reviews ran and passed (the same API lists every conclusion today), but the
    collector wrote `tamper_suspected` into exactly the `<run>-<attempt>-<check>.jsonl` paths their
    records belonged in.
  - **What it cost:** the log is append-only, so a re-run can't fix those paths, and the release
    attestation lists both PRs as unreviewed. That is part of why v0.4.0 was refused.
  - **The fix:** the collector waits up to about 5 minutes for every job of the attempt to report
    a conclusion. If one still doesn't, the job fails **without writing anything**, so an ordinary
    re-run later records the run properly. `audit.collect` raises `JobsNotFinished` on any `null`
    conclusion before it touches a file, and the CLI exits 3. So the code can't turn an
    unfinished job into a tamper event, whatever the workflow does. A cancelled or skipped job is
    still `tamper_suspected`: it finished, and didn't confirm the record.
  - **Re-collect, for the paths already taken (same date).**
    - **How it runs:** `audit-collect.yml` also runs on `workflow_dispatch` with a run id and an
      attempt. Dispatch needs write access.
      - **The run:** read from the API, not from inputs. It must be a finished `pull_request` run
        of `llm-review.yml`.
      - **The validation:** the same as a first collection, from the default branch's code: jobs,
        compare, triage recomputation, override, steering check.
    - **Where it writes:** to `<run>-<attempt>-<check>-recollected.jsonl`, and only for a check
      whose first file holds nothing but `tamper_suspected`. Confirmed records are never doubled.
    - **The append-only rule:** the original file and its tamper events stay, so the PR moves from
      unreviewed to unverified (`tamper_suspected (n)`), not to clean. Every new file is itself
      append-only.
    - **The limit:** it needs the run's `audit-*` artifacts, which are kept for 7 days.
    - **Checked locally**, by running the workflow's steps up to the write against the real runs:
      - #92's 39283814132 gives 6 `gate_run`s and the triage;
      - #93's 39287691571 gives the 5 tampered checks, skipping triage and workflow-review, which
        were confirmed the first time;
      - a healthy run is skipped entirely, and a CI run is refused.
  - **Review after merge, for PRs that never had a review** (2026-10-24). Dependabot PRs ran
    without the API key (`skipped_no_key`) until it became a Dependabot secret, and a merged PR
    can't get a `pull_request` run any more.
    - **The run:** `llm-review.yml` runs on `workflow_dispatch` with a PR number.
      - Its `target` job refuses anything but a PR merged into the default branch.
      - It refuses a dispatch from any other branch, so the workflow file and the gate are both
        the default branch's.
      - It reviews the PR's merged head exactly like a `pull_request` run.
      - It posts no labels or comments, and honours no override.
    - **The collector:** it accepts `workflow_dispatch` runs of llm-review only from the default
      branch.
      - It takes the PR from the run name (`review after merge: #N`, strictly matched), checks
        through the API that it is merged, and validates the records against the PR's merged head
        instead of the event's.
      - Records are marked `reviewed_after_merge`, a collector-only field like
        `workflow_modified`; an artifact that sets it is tamper.
    - **The attestation:** it carries the flag per PR, and the release notes list those PRs, so
      "reviewed" never silently means "reviewed before merging".
- The collector compares the record with the job's conclusion from the Actions jobs API (the
  `llm / <check>` job *is* that check run), so it needs `actions: read` and no `checks: read`.

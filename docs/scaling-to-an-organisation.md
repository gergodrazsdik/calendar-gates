# Scaling this gate to an organisation

What it would take to run `calendar-gates`' LLM-assisted merge gate for 200 engineers in a private
GitHub org, with multiple roles, mixed developer machines, an external audit trail and human
approval that means something.

This document is a plan, not a record of work done. It was assembled from five parallel reviews of
this repository (platform, security, cost/flakiness, enterprise compliance, developer experience)
and it stays deliberately honest about three things: which GitHub primitive actually enforces each
rule, which rules **cannot** be enforced and must be detected instead, and what each step costs in
effort and in recurring human time.

Companion document: `docs/overview.html` (what exists today, and where it hurts).

---

## 0. What does not change

These decisions survive contact with an organisation unaltered, and the plan is built on top of
them rather than around them:

- **The verdict is computed in code from finding severities** (`policy.py`), never asked of the
  model. Blocking is deterministic given the findings.
- **The gate that reviews a PR comes from the base branch**, pinned once per run as `gate_sha`
  ([ADR 0004](adr/0004-gate-tooling-from-base-branch.md)). The PR is data.
- **Fail closed, with exactly one overridable error class** (`TOO_LARGE`). A gate that broke is not
  an approval ([ADR 0002](adr/0002-llm-gate-policy.md)).
- **The audit record is written by a trusted workflow**, not by the job that made the decision, and
  anything unverifiable becomes a `tamper_suspected` event instead of being dropped
  ([ADR 0005](adr/0005-audit-trail.md)).
- **The risk floor is deterministic and monotone**: path and size rules set it, a cheap model may
  only raise it, and the collector recomputes it ([ADR 0008](adr/0008-risk-triage.md)).
- **Prompts are versioned, scored artefacts** ([ADR 0006](adr/0006-llm-eval-gate.md)).
- **Releases build once, attest the digest, and promote only after approval and smoke tests**
  ([ADR 0009](adr/0009-build-once-attest-promote.md), [ADR 0010](adr/0010-admission-control.md)).

## 0b. Fix these here first

Five things found during this review are cheap now and expensive later. They are prerequisites
rather than scaling work, because each one is a hole the org version would inherit.

| | What | Why it blocks scaling |
|---|---|---|
| 1 | `diff.git()` decodes git output as strict UTF-8 and catches only `CalledProcessError` (`diff.py:83-89`), and `EXCLUDES` has no binary patterns | The first committed PNG raises `UnicodeDecodeError` in all six review jobs at every risk level, with no override and no `/llm-risk` escape. Two lines plus a test |
| 2 | `workflow-review` is advisory at every risk level (`checks.yaml:48`) and appears **zero times** in `main.json` | The check dedicated to CI changes structurally cannot stop a CI change. Make it blocking at medium and high, add it to the ruleset |
| 3 | Admission and `verify-release` check that the LLM-review attestation **exists**, not what it says (`deploy/policies/base/llm-review.yaml:44-48`) | "Only reviewed code runs here" currently means "a document about reviews is attached". Add `predicate.unreviewed.size() == 0 && predicate.unverified.size() == 0` |
| 4 | The attestation and metrics readers `json.loads` every audit line with no schema validation (`attestations.py:95-105`) | The collector's strictness protects the write path; one hand-appended well-formed line turns an unreviewed PR into a signed claim of review. Validate on read with the same models |
| 5 | `/llm-risk low` makes the whole LLM gate advisory for a head (`checks.yaml:101`), and that path never appears in the per-PR attestation (only `type: "override"` does) | It is the cheapest bypass in the system and it looks legitimate in the log |

Also worth fixing while the context is fresh: `llm-eval`'s cache key omits engine settings
(`max_turns`, `budget_usd`, `MAX_TOKENS`), so a PR that changes those and no prompt reproduces the
baseline exactly from cache — the eval gate is weakest for precisely the changes most worth scoring
(the live half of F012).

---

## Phase A — make the policy an artefact with an owner

### A1. Write the role matrix, and split policy from mechanism

Five roles, each owning named paths:

| Role | Owns | Typically |
|---|---|---|
| **Policy Owner** | prompts, `checks.yaml`, risk rules, eval thresholds and baseline | security / eng standards |
| **Gate Admin** | the gate package, workflows, rulesets, the central repo | platform |
| **Control Owner** | overrides, waivers, the evidence story | risk / compliance |
| **Audit Reader** | read-only on the audit sink; cannot write | internal audit, security |
| **Consumer Team** | their own repo's config, which stays tiny | the 200 |

Then split the repository's concerns physically: **policy** (prompts, `checks.yaml`,
`thresholds.yaml`, `baseline.json`), **mechanism** (`tools/llm-gate/src/**`, workflows, the
composite action), **consumer config** (per-repo overrides).

Cost: one to two weeks of decisions, no code. This is the cheapest step and the one most often
skipped; every GitHub primitive later needs a path and a team to point at.

### A2. CODEOWNERS, and a ruleset that actually requires those owners

There is no `.github/CODEOWNERS` today, and `main.json` sets
`required_approving_review_count: 0`. Add:

```
/tools/llm-gate/src/        @org/gate-admins
/tools/llm-gate/checks.yaml @org/policy-owners @org/gate-admins
/tools/llm-gate/evals/      @org/policy-owners
/.claude/commands/llm-*.md  @org/policy-owners
/.github/workflows/         @org/gate-admins
/.github/rulesets/          @org/gate-admins
/.github/CODEOWNERS         @org/gate-admins
```

with `required_approving_review_count: 1` (2 in the policy repo), `require_code_owner_review: true`
and `require_last_push_approval: true`, keeping `dismiss_stale_reviews_on_push: true` and
`bypass_actors: []`.

**What this enforces:** CODEOWNERS is evaluated from the base branch, so a PR editing CODEOWNERS
needs approval from the file's current owners. `require_last_push_approval` closes approve-then-push.

**What it does not:** CODEOWNERS says who reviews, never who may not merge, and a repo admin can
still change it through any path the ruleset allows. It is not separation of duties on its own — an
owner of one path can approve a colleague's change to their own policy. Only team-membership
discipline fixes that.

Expect review-latency complaints within a month; staff a policy-owner rota.

### A3. Move the gate out of the reviewed repository

The highest-value change in this plan. A central `org/ci-gates` repo holds the review workflow as a
`workflow_call` reusable workflow, the gate as a versioned package, and the prompts. Consumer repos
call it pinned by SHA, enforced by an **organisation ruleset requiring that workflow**.

This closes ADR 0004's stated remaining hole: on `pull_request`, the workflow file comes from the
PR, so a PR can edit the thing that reviews it. Today that is mitigated by marking rather than
prevention — and in this repository **182 of 566 runs are recorded unverified** for exactly that
reason. At org scale that noise would make the audit trail worthless.

It does **not** restore caching. The Actions cache is scoped per repository and ref, and a same-repo
PR can add a sibling workflow that writes that scope and reads the same secrets, which is why
ADR 0002 refuses to cache blocking reviews. Safe caching needs a server-side store keyed by the
gate's own credential (E3).

Cost: 4-6 engineer-weeks to extract and version, then **0.3-0.5 FTE permanently** — you now run a
platform component with consumers, a changelog, deprecations, and the property that one bad SHA bump
breaks everyone at once. Verify the required-workflows rule type is available on your GitHub plan
before committing to this design.

### A4. Replace the shared secret with a GitHub App and OIDC

- A **GitHub App** for everything that writes (collector, feedback handler, labels, check runs),
  with fine-grained permissions and short-lived installation tokens. No PATs: a PAT is user-scoped,
  so when that person leaves, the audit trail stops.
- The model credential moves out of a repo secret, behind a **gateway reached by OIDC federation**
  with the trust policy conditioned on `job_workflow_ref`, so only the central reusable workflow can
  mint it. `job_workflow_ref` is the only claim that says "this credential came from the gate's
  workflow and not from another job in the repo".
- Keep `default_workflow_permissions: read` and `can_approve_pull_request_reviews: false`.

An App can also be a ruleset **bypass actor** while humans are not, which is what finally lets you
restrict who may write to the audit branch.

---

## Phase B — human approval where it counts

### B1. Turn the override from a label into a deployment approval

Today an override is the `llm-override` label plus a `/llm-override <reason>` comment from the
person who added it, who must hold write access. That is the best a label can be: GitHub's label
permission is role-based with no per-label granularity, so **the PR author can override their own
PR**.

Replace it with a job declaring `environment: gate-override`, required by a conditional
`required_deployments` rule, where the environment carries required reviewers
(`@org/control-owners`), **`prevent_self_review: true`**, and a wait timer of 15-30 minutes.
`prevent_self_review` is the only GitHub primitive that mechanically stops an author approving their
own exception; the wait timer is the only built-in brake on reflex overrides.

Keep the reason text, the `override` audit record, the `unreviewed`/`(overridden)` surfacing in the
attestation, and ADR 0002's rule that an engine error is never overridable.

Apply the same pattern to **changes to the policy itself**: a path-conditional job declaring
`environment: policy-change` with `@org/policy-owners` as reviewers and `prevent_self_review: true`,
triggered when the diff touches prompts, `checks.yaml`, workflows, rulesets, `thresholds.yaml` or
`baseline.json`. CODEOWNERS approval is a PR review by one of N owners; an environment approval is a
named, timestamped, non-self approval recorded in the deployments API and the org audit log. You
want both, because "weaken the prompt and lower the baseline in the same PR" is otherwise one PR
with one author.

Pilot on three repos for a month: `required_deployments` semantics are fiddly, and a conditionally
skipped job must not read as satisfied. Budget 1-3 overrides per week per 50 active repos.

### B2. Delete the risk-lowering path

Make `/llm-risk` raise-only. Keeping both a sanctioned bypass (B1: two-person, timed, ticketed) and
an unsanctioned one (a comment that makes everything advisory) guarantees everyone uses the comment.
Half a day of code, plus the argument. **Do it before anything becomes blocking**, or you will have
taught 200 people the bypass first.

### B3. Make exclusions expire, in machine-readable form

One waiver registry per repo (`.github/waivers.yaml`), schema-validated in `lint`, covering every
exclusion class that is scattered today:

- diff-size raises (`max_diff_kb`, `max_file_kb`);
- `trimmable_paths` additions (generated code);
- `diff.EXCLUDES` additions (vendored directories, lock files, fixtures, **binaries**);
- grype `ignore:` entries — today a free-text "Expires 2026-12-31" that nothing parses;
- eval threshold relaxations and baseline regressions;
- per-repo "advisory instead of blocking" entries.

Each entry carries `id`, `scope`, `reason`, `requested_by`, `approved_by`, `ticket`, `expires`
(max 90 days), and a `renewals` count. Lint fails on a missing field, an over-long expiry or an
expired entry. Adding or renewing one touches a Control-Owner-owned CODEOWNERS path **and** trips
the `policy-change` approval. The weekly Gate health report gains "expiring within 14 days" and
"renewed three or more times" tables.

This repository already has the right instinct — an omitted file is named in the comment, the record
and the attestation — and lacks only a parser and a clock. Permanent exclusions are how gate
programmes die, and "renewed five times" is exactly what an auditor should see.

Cost: two weeks to build; **the largest recurring item in the plan**, 2-4 hours of Control Owner
time per week at 100 repos. It is also the step that most reliably produces evidence.

---

## Phase C — the external audit trail

### C1. Freeze and version the schema

`audit/v1` is already strict pydantic with `extra="forbid"`. Promote it to a published contract:
generate JSON Schema into the central repo, add golden-file round-trip tests, and write down the
compatibility rule — **additive optional fields only within a major; a required field or a changed
meaning is `v2`**, with both emitted in parallel for a quarter at cut-over. Add `schema`, `producer`
(tool version plus gate SHA), `org`, `repo_id` (numeric, survives renames) and `env` to every
record.

`extra="forbid"` means a producer one version ahead of its collector fails closed and drops records.
With one repo that is a visible CI failure; with 100 repos on pinned SHAs it is silent data loss.

### C2. Deliver to an append-only external sink; keep the branch as a cache

The trusted collector, and nothing else, ships records to **object storage with Object Lock in
compliance mode**, keeping the existing path shape under `org/repo_id/` prefixes, with retention set
with Legal rather than by the platform team. **Push from the workflow** over OIDC, with the bucket
policy granting `PutObject` only — no deletes, no overwrite, no governance bypass. Fan out to the
SIEM from the bucket rather than writing to the SIEM directly.

Push rather than pull, because the collector already knows what it produced; a puller would have to
enumerate runs and would miss anything whose run was deleted or whose artifacts expired. Object
storage rather than the SIEM as system of record, because SIEM retention is short and SIEMs mutate
on ingest. Not both, because two systems of record means two completeness arguments.

Keep the `audit-log` branch as a convenience for `just metrics` and the release attestation, and
tighten its ruleset to restrict `update` with the App from A4 as the only bypass actor — which
ADR 0005 already identifies as needing an org.

### C3. Prove completeness, not just integrity

This is what auditors press on, and the prototype has no answer to it.

1. **An expectation ledger.** The triage record already contains `checks_plan`; have the collector
   emit a per-run manifest of what it expected, received, rejected and skipped. A missing record
   becomes a detectable absence rather than a silence.
2. **A monotonic sequence and a signed daily checkpoint.** Per-repo counter, each record hash-chained
   to the previous, and a daily `checkpoint` record carrying the counter and a Merkle root, signed
   with KMS or the same keyless signing `release.yml` already uses. A gap or a root that does not
   recompute is an alert. Do **not** build a full transparency log unless an auditor names it — this
   gives the same tamper evidence at a fraction of the cost.
3. **A daily reconciliation job independent of the gate**: merged PRs from the API, records from the
   sink, diff the two. The existing **Coverage** metric is exactly this computation; promote it from
   a weekly issue comment to a monitored control with a threshold, run against the sink rather than
   the branch, and have the Audit Reader or Control Owner triage its alerts — not the Gate Admin, or
   it is not an independent control.

**Also stream GitHub's own audit log to the same sink.** The records say what the gate did; they say
nothing about someone editing a ruleset, adding a bypass actor or changing an environment's
reviewers. Treat `repository_ruleset.*`, `environment.*`, `protected_branch.*`, Actions settings
changes, installation changes and `pull_request.merge` as in scope. Non-negotiable if you want to
evidence separation of duties.

### C4. Decide the enterprise-level backstop

Put the gate-critical rules in an **enterprise-level** ruleset if your plan has one, and grant
"manage rulesets" through a custom organisation role to Gate Admins only. An org ruleset can be
edited by an org owner; if your org owners are the engineers shipping the gate, the control's owner
can disable the control.

Where GitHub cannot help, say so in the control description verbatim: there is no two-person rule
for a ruleset edit, no approval workflow for changing an environment's reviewers, and no way to stop
an org owner granting themselves a bypass. These are **preventively unenforceable and detectively
enforceable** — via the audit stream, a scheduled `gh-rulesets-diff` across all repos, and a
quarterly attestation that live config matches the committed JSON.

---

## Phase D — evidence, including the negative half

Generically this pipeline is evidence for change management, separation of duties, software
provenance, and logging and monitoring. It is also an AI-governance artefact: a model inventory,
versioned prompts, human oversight and measured performance.

**What it legitimately evidences**

| Assertion | Evidence |
|---|---|
| Every production change went through a PR with required checks | Ruleset JSON in git, live-vs-committed drift check, `pull_request.merge` audit events |
| What automated review ran, against which policy version | `gate_run`: check, engine, model, `prompt_sha256`, `config_sha256`, `gate_sha`, `diff_sha256`, verdict, exit code |
| That blocking was deterministic | `policy.decide` plus the collector's verdict/exit/job-conclusion agreement check |
| Who approved, and that they were not the author | Environment approvals with `prevent_self_review`, in the deployments API |
| What was overridden, by whom, why, and that the reason was unedited | `override` records, the unedited-comment and role checks, the override approval |
| **What the reviewer did not see** | `omitted_files`, `denied_reads`, excludes, `TOO_LARGE`, and the attestation's `unreviewed`/`unverified`/`partial` lists |
| Provenance of the deployed artefact | The release attestations on the digest, `verify-release`, Kyverno admission |
| That the reviewer itself was tested before it changed | `llm-eval` as a required check, baseline, thresholds, fp regressions |
| Measured control performance | Coverage, override rate, false-positive rate, turnaround, triage mix, integrity events |

**What it must never be claimed to evidence** — write this down before an auditor infers it:

- **Not that the code is correct or secure.** Recall is measured on a few dozen synthetic cases. Say
  "an automated review ran and reported no findings at or above severity X", never "verified free of
  defects".
- **Not human review.** An LLM finding is not a reviewer's judgement and an LLM pass is not an
  approval. The SoD evidence is the environment approval and the CODEOWNERS review.
- **Not that the whole change was reviewed**, unless the record says so. Partial and unreviewed
  states are explicit by design; do not aggregate them away in a dashboard.
- **Not who authored the code.** AI markers are self-declared. They are a transparency signal and
  must never feed a disciplinary or licensing argument.
- **Not a complete log**, without C3. Today most record contents are asserted by the producer and
  verified only where the collector can cross-check them.
- **Not tamper-proof**, without C2 and C4: anyone with write can append to the audit branch, and a
  repo admin can bypass the tag ruleset.
- **Not an access-control record.** It shows what happened, not who could have merged.
- **Not evidence about the model vendor.** That is third-party risk with its own evidence.

Two weeks with Compliance in the room. Do this **before** rollout, not after: it is what converts
the programme from good CI into an auditable control.

---

## Phase E — rollout without a mutiny

### E1. Golden path, advisory everywhere, opt-in to blocking

A template repository with the gate wired, CODEOWNERS, the waiver file and environments pre-created.
**Custom repository properties** (`llm-gate = off | advisory | blocking`, `tier`, `data-class`) and
two org rulesets targeting those properties, so moving a repo to blocking is a property change with
an approval record rather than an edit to 100 rulesets.

Order of operations: advisory for everyone → publish per-team numbers → blocking for tier-1 with the
security check only → widen by severity, not by check count. Start blocking at **high** severity;
this repository's `security-review` blocks at medium, which would be your most-hated setting on day
one.

Give each team a two-week onboarding report of its own findings with nothing blocking, so a team
sees its own numbers before being asked to accept the gate.

### E2. Define, in advance, the numbers that permit blocking

A repo may move advisory → blocking only after ≥30 days and ≥50 PRs with: false-positive rate on
blocking-severity findings under 10% **and** enough `/llm-fp` participation for that number to mean
anything; blocking-check turnaround p90 under 5 minutes; override rate under 10% of PRs with a
blocking failure and no team above 25%; coverage ≥99% with no unexplained reconciliation gaps for
two consecutive weeks; eval recall above the central baseline on per-language cases; cost per PR
within the team's budget at p90.

Promotion is a Control Owner decision. **Demotion is automatic**: two consecutive weeks of breach
and the repo drops to advisory without a meeting. Automatic demotion is what buys the credibility to
ask for blocking at all.

### E3. Cost allocation, hard caps, and the cache that is finally safe

Put a gateway in front of the model so every call carries `repo`, `team`, `check` and `pr`; give each
team a hard monthly cap with an alert at 70%; keep the per-run `budget_usd` as the inner cap; and add
the **per-PR lifetime cap across runs** that ADR 0005 notes does not exist. Decide deliberately what
happens at the cap: advisory repos skip with a notice, blocking repos fail closed.

Once the gate holds its own credential, cache review results in the gate's own store keyed by
`(check, prompt_sha256, config_sha256, diff_sha256, model, engine)`. This is the clean resolution of
ADR 0002's dilemma — the key is unforgeable because the PR cannot write the store — and it is the
difference between paying per high-risk PR and paying on every re-run.

Two measured facts to put in the template README before the first cost-cutting PR is opened:

- **A "cheap" model is not cheap on the agent engine.** Haiku measured ~$0.11/review against
  Sonnet's ~$0.01, with five times the noise and more false blocks. Roughly ten times the cost for a
  worse reviewer.
- **Opus matched Sonnet's recall** at 3-4× the cost and more noise, and was reverted.

Re-run that comparison quarterly rather than trusting it forever. Keep the triage model cheap: it
may only raise risk, so its worst case is cost, not weakened review.

### E4. Developer environments and the local loop

Twenty developers on mixed macOS, Linux and Windows will not reproduce a one-machine setup. What
breaks today: `just lint-policies` demands Kyverno **exactly** 1.19.1; local linters come from PATH
while CI runs pinned containers; `pass show` fronts the API key; `podman`, `home_directory()` and two
kind clusters are machine-specific; the repo name and owner are hardcoded in several places.

1. **Pin tools with mise** (dotnet, uv, just, helm, kubectl, kind, kubeconform, shellcheck,
   hadolint, actionlint, kyverno, grype, syft) and ship a devcontainer as the escape hatch for
   Windows-without-WSL and "it only fails on my laptop" disputes — not as the default, which makes
   .NET builds crawl on macOS bind mounts and hides the host/CI difference instead of fixing it.
2. **Add `mise.toml` as a third source to `check-tool-pins.py`**, or it becomes a fourth place to
   drift.
3. **Split the recipes into three tiers**: `preflight` (offline, no container, cluster or key:
   format, build, test, the gate's own Python checks), `ci` (adds system linters, chart and policy
   checks), and CI-only (image, scans, every `k8s-*`, `llm`, `eval`, `metrics`, and the `gh-*` admin
   recipes, which belong in a separate file so nobody tab-completes into applying a ruleset).
   Make `preflight` the PR-template checkbox, since it is the one developers can actually run.
4. **Parameterise the machine assumptions**: container runtime, repo slug, one ephemeral cluster per
   developer instead of a shared named one.
5. **Add `just doctor`**: every tool, found version, expected version, and which recipes are
   unavailable and why. This replaces the first week's support pings.
6. **Nobody holds a key.** Default to CI-only plus a `/llm-review [check]` comment command, served
   from the default branch exactly as `/llm-override` already is. Issue gateway credentials scoped
   to eval runs, with a hard cap, to the few people who own prompts — and make `--budget-usd`
   mandatory in the recipe rather than defaulted.
7. **Hooks degrade, never block.** Every hook guards on the tool existing and prints one line when
   it is missing. A hook that fails because a binary is absent teaches `--no-verify` as a reflex, and
   that reflex then bypasses the one hook worth having — `gitleaks`, which CI cannot un-leak.
   Demote or drop the pre-push full test run. Do not make hooks mandatory: `--no-verify` is one flag,
   server-side rulesets are the only real enforcement, and this repository's own drill proves it.
8. **Make the session-audit hook and the `Claude-Session:` trailer opt-in.** At one person it is a
   lab notebook; at twenty it reads as surveillance, is useless to anyone else because the log is
   local, and in some jurisdictions it is a works-council conversation.
9. **Review latency**: publish a p90 budget (under 10 minutes for the PR-blocking set). The LLM is
   not the slow part — review turnaround p50 is under a minute here, while the image build fans into
   three gates that wait on it. Move the cluster smoke test off the per-PR path when it becomes the
   long pole, and have the findings land as **SARIF annotations on the changed lines** instead of six
   sticky comments per PR, with a cap on reported findings and the `/llm-fp` command in the footer.
10. **Localise prompts by overlay, never by fork.** Keep the severity ladder, the output contract and
    the injection clause central and pinned; let teams append a small overlay with their own domain
    conventions, scored against their own eval cases. A forked prompt drifts out of both the trust
    model and the eval loop, and you lose the ability to improve the reviewer centrally.
11. **Turn off the AI-marker risk bump.** With everyone using an assistant the marker stops carrying
    information, and because it *raises* the floor, the honest actor pays and the evasive one does
    not. Keep the label as telemetry, keep asking for the trailer, remove the penalty for honesty.
    This repository already needs a written rule forbidding people from omitting it, which is a
    social patch over a perverse incentive.

### E5. Break-glass, and the drills that prove it

An engine error is deliberately non-overridable — right for one repo, catastrophic for 200: a vendor
outage, a gateway misconfiguration or an expired key means nothing merges anywhere, including the
fix.

1. **A circuit breaker in the central policy**, not in the PR: `gate_mode = enforce | degraded | off`.
   In `degraded`, a blocking check hitting an engine error returns a `degraded` verdict with exit 0,
   the comment and record say "not reviewed — gate degraded", and the attestation lists the PR as
   `unreviewed` exactly as it already does for an accepted oversized diff.
2. **Flipping it is itself a gated change**: a PR to the central repo, a `policy-change` approval by
   an on-call Control Owner, auto-expiring after 24 hours via a scheduled job that reverts it and
   files an issue. Every flip is an audit record.
3. **Automatic detection**: when the cross-repo engine error rate breaches for N minutes, page the
   Gate Admin and *propose* the breaker — never auto-apply.
4. **A documented, logged admin bypass** as the last resort, as a named break-glass team with
   `bypass_mode: pull_request`, every use streamed and ticketed. A bypass path that exists and is
   logged beats one that is improvised at 2am by whoever has admin.
5. **Fallback capacity** configured but not load-bearing, and never a silent failover of blocking
   reviews to a weaker model — that changes what the control means. Fail over to `degraded`.
6. **Four drills a year, written up**: kill the key; flip the breaker and prove it expires; forge an
   audit artifact and prove the collector flags it; delete a day from the sink and prove
   reconciliation catches it; have a non-owner attempt a self-override and prove the environment
   refuses. These drills are stronger audit evidence than any document, because they demonstrate the
   control detects failure — and this project's drill history shows they find real bugs.

---

## Organisational risks

- **Gaming the triage.** Well defended against the model (deterministic floor, collector
  recomputation, raise-only). The live vectors are the risk-lowering comment (B2) and splitting a
  change across PRs to stay under the size thresholds. Do not try to prevent the latter; make it
  visible — stacked-sibling totals and a per-author risk distribution in the health report.
- **Override fatigue**, the real killer. In order of effect: automatic demotion (so an override rate
  signals a broken gate, not a lazy team), non-self approval with a wait timer, expiring waivers, and
  publishing override rate per team. Above 20% after three months your thresholds are wrong — lower
  the blocking severity rather than exhorting people.
- **The gate as a bottleneck.** Measure p90 before blocking. Do not put the LLM checks in a merge
  queue's required set: a queue re-runs checks per entry and these are the slowest, uncacheable ones.
  Let the queue require the deterministic gates.
- **A vendor outage freezing all merges.** E5; today unmitigated.
- **Cost.** E3, modelling both multipliers this repository already warns about: uncached blocking
  reviews, and most PRs rating high.
- **The gate's own blast radius.** One bad SHA bump or prompt change breaks every repo at once. Use
  canary rings (pilot repos on `main`, tier-3 on `stable`, tier-1 on `released`) and keep the eval
  gate on the central repo.
- **Prompt injection at scale.** The hardening here was built for one trusted repo. With 100 repos
  and vendored third-party code, assume a hostile diff eventually: keep treating the review's output
  as untrusted, never let a review's text reach a system that acts on it, and add injection eval
  cases per language.

## What not to bother with

- **A full cryptographic transparency log.** Object Lock plus hash-chained records plus signed daily
  checkpoints is recognisable and defensible at a tenth of the work. Build the real thing only if an
  auditor names it.
- **Per-repo eval baselines.** One central baseline plus per-language case suites. A hundred
  baselines is a hundred things to update on every prompt change.
- **Porting the local session-audit log org-wide.** Unenforceable, self-reported, near-zero
  evidentiary value, and a Legal conversation you do not need.
- **Enforcing AI-authorship detection.** The markers are self-declared. Transparency, nothing more.
- **Bundling the admission-control chain into this programme.** It is excellent and it is a separate
  supply-chain rollout; bundling it will sink the review gate's adoption.
- **Making every advisory check blocking "eventually".** Documentation drift and test-coverage
  review are more useful advisory forever. A gate that blocks on everything gets bypassed on
  everything.
- **Replacing the audit branch immediately.** Keep it as a cache while the external sink becomes the
  system of record.

## Sequencing and cost

| Phase | Effort | Notes |
|---|---|---|
| A — policy as an owned artefact | 8-12 engineer-weeks + 2 weeks of decisions | A1 gates everything; A2-A4 can run in parallel |
| B — human approval | 5-6 engineer-weeks | Needs A2 and A4 |
| C — external audit trail | 9-12 engineer-weeks | C1 early; C2-C3 need A4 |
| D — evidence map | 2 weeks, Compliance-led | Needs A and B decided, not built |
| E — rollout | 10-13 engineer-weeks | E1 needs A3; E5 before anything blocks |

Roughly **two engineers for two quarters** to reach "advisory everywhere, blocking on tier-1,
auditable". Steady state: **0.5-1 FTE platform**, plus **3-6 hours a week of Control Owner time**
for overrides, waiver expiry, reconciliation alerts and promotion decisions. That last part is what
organisations forget to fund, and it cannot be automated. If you cannot staff it, run the gate
advisory-only and claim nothing for change management — a legitimate outcome, and far better than a
blocking gate everyone bypasses.

**If you do only four things:** move the gate out of the reviewed repository (A3); make the override
a non-self environment approval (B1); prove completeness, including GitHub audit-log streaming (C3);
and build break-glass before anything blocks (E5).

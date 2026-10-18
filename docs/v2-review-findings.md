# v2 review findings

A review of the whole repository at `43ec3c2` (2026-10-17), after PLAN-v2 was wrapped up. **Nothing has been fixed**: this is the input for deciding what to fix. Generated from the reviewers' and the council's JSON; the scratch files are not kept.

## How it was made

1. **Eight reviewers**, each at max effort with no cap on findings, in its own git worktree, read-only, applying one of the repository's review prompts (`.claude/commands/llm-*.md`) to the whole codebase instead of a diff. They could run local tooling (pytest, coverage, mutations on scratch copies, `kyverno test`, actionlint, zizmor, shellcheck, a locally built API) but spent no API credits, wrote nothing to GitHub and touched no cluster:
   - `cr-api`: code-review (API, container, chart)
   - `cr-gate`: code-review (llm-gate)
   - `cr-ops`: code-review (scripts, justfile, deploy, rulesets)
   - `sec`: security-review (whole repo)
   - `wr`: workflow-review (.github)
   - `tr`: test-review (all tests and eval cases)
   - `api`: api-contract (HTTP API and llm-gate's machine contracts)
   - `dd`: docs-drift (all docs and instruction files)
2. **Coalesced**: 171 raw findings, merged by hand where several reviewers reported the same defect, into 133 items (`F001`...). Each item keeps every report it merged (`reported_by`).
3. **Advisory council**: three validators per area, each judging every item of its area independently against the code, without seeing the others' votes:
   - **skeptic (S)**: tries to disprove the finding;
   - **maintainer (M)**: checks it against the ADRs, the plans and git history, and whether the fix fits the design;
   - **impact (I)**: who can trigger it and what it costs, calibrating severity.

   Verdicts: `C` confirmed, `P` plausible (couldn't be verified offline), `A` accepted by a recorded decision (exactly this consequence), `R` rejected. **Outcome** is the majority: two `R` → rejected, two `A` → accepted, two `C` → confirmed, two of `C`/`P` → plausible, otherwise split. **Severity** is the median of the three council severities; the reviewers' original severity is shown next to it.

## Summary

| Outcome | critical | high | medium | low | info | total |
|---|---|---|---|---|---|---|
| confirmed | 0 | 2 | 16 | 74 | 26 | 118 |
| plausible | 0 | 0 | 1 | 0 | 0 | 1 |
| split | 0 | 0 | 0 | 0 | 0 | 0 |
| accepted | 0 | 0 | 0 | 2 | 1 | 3 |
| rejected | 0 | 0 | 0 | 0 | 11 | 11 |

**Fixed so far: 72 of 119** (3 partial, 43 open, 1 unverifiable). By severity:

| Status | critical | high | medium | low | info | total |
|---|---|---|---|---|---|---|
| ✅ fixed | 0 | 2 | 14 | 37 | 19 | 72 |
| 🟡 partial | 0 | 0 | 1 | 2 | 0 | 3 |
| open | 0 | 0 | 1 | 35 | 7 | 43 |
| ⚪ unverifiable | 0 | 0 | 1 | 0 | 0 | 1 |

Each fix names the PR that made it. The status column is maintained by hand as fixes land; the verdicts and severities below are the review's own and are not revised.

Items a council member said only a throwaway PR can settle: [F050](#f050). **Marked unverifiable and left at `plausible`** (2026-10-18): settling it means writing PR code that takes a CI job's token and publishes a forged passing check under a required check's name, which is a working bypass of this repository's merge protection, so it wasn't built. The least-privilege fix stands whatever GitHub's precedence turns out to be.

## Reading guide

This is my grouping of the confirmed findings into themes, not a fix plan; which ones to fix is
your call.

**Who can trigger what.** Nothing here is open to a stranger. Every serious path needs write
access to the repository (a collaborator, you, or an agent using your credentials), and in a
personal repository every collaborator has write access. So the gate bypasses below matter as
"the gate can be quietly fooled and the audit log says *verified*", not as an outside attack.

1. **The LLM review can be skipped and still recorded as a verified pass.**
   - [F001](#f001): a `.gitattributes` `-diff` line hides the PR's code;
   - [F002](#f002): a forged cache entry from another workflow of the same PR;
   - [F042](#f042): `workflow_modified` only notices changes to `llm-review.yml`;
   - [F010](#f010): a PR made only of excluded files counts as reviewed.

   The impact calibrator rated F001 and F002 medium, the other two members high. In all four the
   cost is a false *verified* record, with the accepted `llm-review.yml` hole (ADR 0004) next to
   them.
2. **Audit-log records are trusted by their content.**
   - [F005](#f005): a hand-pushed `risk_override` with a far-future timestamp wins, and one
     malformed line (`[]`) crashes triage on every PR;
   - [F020](#f020): one `/llm-risk low` carries over to every later push of the PR.
3. **Re-runs and timing.**
   - [F006](#f006): "Re-run failed jobs" turns valid passes into `tamper_suspected`;
   - [F044](#f044): `/llm-risk` and `/llm-override` sent during a running review are acknowledged
     but never applied.

   These are the ones most likely to bite in normal use.
4. **Triage fails closed, but loudly.** [F011](#f011): invalid model output crashes the triage
   job, so no `llm / <check>` reports, instead of falling back to the rules' rating as ADR 0008
   says.
5. **`llm-eval` has blind spots.**
   - [F008](#f008): a check's new model has no baseline entry, so nothing is compared;
   - [F009](#f009): security-review is never scored on the agent engine;
   - [F012](#f012): cache keys leave out engine code and settings.

   The C-impact member adds that the keys also leave out the SDK version, so a lock-file-only
   SDK bump replays main's cached reviews and is never evaluated.
6. **Release and admission.**
   - [F043](#f043): a `v*` tag on any commit produces attestations that Kyverno accepts;
   - [F047](#f047): image volumes aren't checked;
   - [F048](#f048) and [F071](#f071): attestations and tags exist before approval and smoke tests;
   - [F052](#f052): uv itself is unpinned.

   Per the B-maintainer, a tag-creation rule alone wouldn't stop your own agent. The sturdier
   check is for `verify-release` to require that the provenance commit is an ancestor of `main`.
7. **API.**
   - [F081](#f081): a malformed `?year=` on `/api/friday13` returns 500 in Development, which is
     what the integration tests and `just run` use;
   - [F082](#f082) and [F086](#f086): the OpenAPI document leaves out some 400 responses and the
     date format of the date parameters.
8. **Docs.** [F084](#f084) is the only medium one: `gates.md` still says to re-run a failed
   release, which now burns the version and adds Rekor entries. The rest is stale wording after
   #54–#60.
9. **Tests.** The test-gap items were confirmed by mutation runs on scratch copies: each one
   names a guard you can break without any test failing.

**Suggested fixes the council found wrong:**
- **F001:** `git diff --numstat --text` still prints `-` for such a file. What does work is
  `git --attr-source=<base>`, which reads `.gitattributes` from the base branch.
- **F002:** an HMAC keyed by a repository secret can't stop the forged cache entry, because the
  PR's own workflow can read that secret.

**Rejected or narrowed reports:** each item's details show them as "Reports the council found
wrong", with the reason in the council notes.

**[F050](#f050) stays unverifiable.** Whether a same-named check run from the same app satisfies a
required check is undocumented, and GitHub's own wording only calls duplicate names "ambiguous".
Proving it needs PR code that steals a job's token and forges a passing required check, which is
exactly the bypass it describes, so it was not built. What is confirmed without it: `build-test`,
`http-tests` and `k8s-smoke` hold `checks: write` while running PR code. Moving test reporting to
a job that runs no PR code removes the question.

**Since the review (2026-10-18).** Thirteen things changed under this document:
- **#76** gave `docs-drift` and `test-review` a scored case each, so neither prompt can be cut
  down to "report nothing" and still pass `llm-eval` (F037).
- **#75** made the override record follow the outcome instead of the label (F025) and put the
  admission rule that decides on critical vulnerabilities under an offline test (F069).
- **#74** covered the guards a silent mutation could break: the risk-level transformations, the
  trusted-only record types, both audit size limits, the eval forbid rules and the metrics
  (F004's neighbours, ten items in all, each named on its own Status line).
- **#73** pinned uv itself (F052) and made a malformed `?year=` the same ValidationProblem in both
  environments (F081), leaving F003 as the last open medium.
- **#71** made the approval attestation required, proven on the project cluster: v0.3.2 admitted,
  v0.3.1 denied by name, an image volume denied. That test also found that the F058 readiness wait
  from #63 never matched Kyverno's actual condition, which #71 fixes.
- **#72** closed the two remaining "recorded as reviewed, but nothing was" findings: generated C#
  is no longer invisible to the reviewers (F010), and a check whose engine or model has no
  baseline entry fails `llm-eval` instead of skipping its own comparison (F008).
- **v0.3.2 shipped** and exercised four things for the first time: the LLM-review Deny policy in
  `admission-smoke`, the `release-approved` attestation, the tag-creation rule (the push logged
  "Bypassed rule violations ... creations being restricted"), and `verify-release`'s ancestry and
  `--source-digest` checks. It also exposed a bug in F005's fix, which **#70** repairs: the
  writers list the collector compares a `/llm-risk` against was built from `/llm-override`
  comments only, so #68's run became seven tamper events in that release's attestation.
- **#69** took the admission pair and the stale-risk hole: image volumes are refused (F047), the
  approval is its own attestation (F048, Audit until v0.3.2 carries it), and a `/llm-risk`
  lowering no longer covers later pushes (F020).
- **#68** closed both highs: the `.gitattributes` hole (F001) and the forged review cache (F002),
  plus the narrow `workflow_modified` flag they both relied on (F042).
- **#67** bound a release tag to a commit on `main` (F043), outside the workflow the tag supplies.
- **#65** fixed the four findings that misfire in normal use: a partial re-run recorded as
  tampering (F006), commands dropped mid-review (F044), the triage job dying on schema-invalid
  model output (F011), and an appended `risk_override` that could crash triage or outrank a real
  `/llm-risk` (F005).
- **#63** fixed the trivial end: every stale document, instruction file and comment the review
  found, plus the small recipe and script defects (zizmor's token, `audit-pull` on an empty
  branch, `k8s-cluster-down` ignoring `cluster=`, the port-forward that didn't bind, the release
  tag left behind by a failed push, `gh-setup`'s whole-entry secret, `pr-title` accepting
  "Merge …", `wait-for-health`'s timeout, the pre-commit ruff gap) and the missing 400s in the
  OpenAPI document. Each item's Status line names it.
- **#62** (`feat(llm-gate)`) gave oversized diffs a path through the gate. The hole wasn't on this
  list: it surfaced when this very document, 488 KB, failed both blocking checks on the size cap
  and the override couldn't lift an `error`. ADR 0002 is amended. Along the way the gate's own
  reviews caught three defects in that change, two of them fresh bypasses, which is the clearest
  evidence here that the blocking checks earn their place.
- **[F050](#f050)** is marked unverifiable, as described above.

Nothing else in this document has been fixed.

**Next release:** the next release, v0.3.2, will be the first to run #54's Deny policy and its
`admission-smoke` assertions ([F095](#f095)). Read [F084](#f084) before re-running one that
fails.

## Index

Confirmed, plausible and split items, most severe first. Votes are `S`/`M`/`I`: verdict/severity.

Open items are sorted after fixed ones of the same severity, so the top of each severity block is what's left to decide.

| ID | Status | Sev | Was | Area | Title | Fix | Votes |
|---|---|---|---|---|---|---|---|
| [F001](#f001) | ✅ fixed | high | high | A | A PR's own .gitattributes can hide its changes from every LLM reviewer and from triage's size rule | small | S:C/high M:C/high I:C/medium |
| [F002](#f002) | ✅ fixed | high | high | A | Review results restored from the Actions cache are trusted unverified, and other workflows of the same PR can write that cache | medium | S:C/high M:C/high I:C/medium |
| [F003](#f003) | open | medium | high | A | The agent reviewer's file reads are not fenced to the reviewed checkout, and its output is published unredacted | small | S:P/medium M:C/medium I:C/low |
| [F012](#f012) | 🟡 partial | medium | medium | A | Cache keys ignore llm-gate's request code and engine settings, so llm-eval scores engine changes from main's cached reviews | small | S:C/medium M:C/medium I:C/medium |
| [F004](#f004) | ✅ fixed | medium | high | A | The collector's triage recomputation (_triage_expected) has no test at all | small | S:C/medium M:C/medium I:C/low |
| [F005](#f005) | ✅ fixed | medium | medium | A | Triage and the collector accept any risk_override record on audit-log, so a hand-pushed record can lower the risk with a forged author and an unbeatable timestamp | medium | S:C/medium M:C/medium I:C/medium |
| [F006](#f006) | ✅ fixed | medium | medium | A | Re-running only the failed llm jobs turns their records into tamper_suspected, because the new attempt has no triage artifact | small | S:C/medium M:C/medium I:C/medium |
| [F008](#f008) | ✅ fixed | medium | medium | A | llm-eval checks only flips and fp-regressions when the run's engine/model has no baseline entry, so changing a check's model skips the regression gate | small | S:C/medium M:C/medium I:C/medium |
| [F010](#f010) | ✅ fixed | medium | medium | A | Name-based EXCLUDES drop compiled C# from the review, and a PR made only of excluded files passes as 'not applicable' | small | S:C/medium M:C/medium I:C/low |
| [F011](#f011) | ✅ fixed | medium | medium | A | Schema-invalid or truncated model output escapes structured_call as pydantic.ValidationError, crashing triage instead of leaving the floor | small | S:C/medium M:C/medium I:C/medium |
| [F020](#f020) | ✅ fixed | medium | medium | A | A /llm-risk decision isn't tied to a head: lowering the risk once removes blocking review from every later push to the PR | small | S:C/medium M:C/low I:C/medium |
| [F042](#f042) | ✅ fixed | medium | medium | B | `workflow_modified` only looks at llm-review.yml, so other PR changes that steer the review still count as verified | small | S:C/medium M:C/medium I:C/medium |
| [F043](#f043) | ✅ fixed | medium | medium | B | A v* tag on any commit, merged or not, mints release attestations, because the 'on main' check runs inside that commit's own release.yml | medium | S:C/medium M:C/medium I:C/medium |
| [F044](#f044) | ✅ fixed | medium | medium | B | /llm-risk and /llm-override posted while llm-review is running get a +1 reaction but may never take effect | small | S:C/medium M:C/medium I:C/medium |
| [F047](#f047) | ✅ fixed | medium | medium | B | No policy inspects OCI image volumes, so a pod in calendar-gates can run code from any registry next to an attested container | trivial | S:C/medium M:C/medium I:C/low |
| [F052](#f052) | ✅ fixed | medium | medium | B | uv itself is unpinned: every setup-uv step installs the newest uv release, in the signing job and the write-token jobs too | small | S:C/low M:C/medium I:C/medium |
| [F081](#f081) | ✅ fixed | medium | medium | C | A malformed or empty ?year= on /api/friday13 gets a 400 without `errors` in Production and a 500 in Development, not the 400 ValidationProblem | small | S:C/medium M:C/medium I:C/medium |
| [F084](#f084) | ✅ fixed | medium | medium | C | "A failed smoke leaves a draft; re-running the workflow refreshes it" no longer holds under build-once releases | trivial | S:C/medium M:C/medium I:C/medium |
| [F007](#f007) | open | low | medium | A | An override by label skips the write-role check that `/llm-override` enforces | trivial | S:C/low M:C/low I:C/low |
| [F009](#f009) | open | low | medium | A | llm-eval scores security-review only on the API engine, but high-risk PRs (most of them) review it on the agent engine | small | S:C/low M:C/medium I:C/low |
| [F018](#f018) | open | low | medium | A | The triage eval lets any one triage case fail in every repeat, tr-008 included; 4 of its 10 cases can't fail at all | small | S:C/low M:C/low I:C/low |
| [F021](#f021) | open | low | low | A | Triage rates gate configuration outside .github/ and tools/llm-gate/ at the default medium | trivial | S:C/low M:C/low I:C/low |
| [F022](#f022) | open | low | low | A | The collector rechecks a run's triage against the default branch's checks.yaml at collection time, not the config the run used | small | S:C/low M:C/low I:C/low |
| [F023](#f023) | open | low | low | A | api-contract's paths filter misses files that change the HTTP contract outside Endpoints/, Domain/, Program.cs and http/ | trivial | S:C/low M:C/low I:C/low |
| [F024](#f024) | open | low | low | A | A PR that changes only http/calendar.http is rated low, where api-contract doesn't run, so its http/** filter never fires for such PRs | trivial | S:C/low M:C/low I:C/low |
| [F026](#f026) | open | low | low | A | /llm-fp and /llm-ack on a finding from the current run are rejected as unknown_finding until audit-collect has written that run | small | S:C/low M:C/low I:C/low |
| [F027](#f027) | open | low | low | A | The llm-review attestation doesn't list a PR whose merged head is missing a record for a blocking check | small | S:C/low M:C/low I:C/low |
| [F029](#f029) | open | low | low | A | Model-written review text reaches the PR comment and job summary without redaction or markup neutralisation | small | S:C/low M:C/low I:C/low |
| [F032](#f032) | open | low | low | A | The collector's paths for keyless PRs (skipped_no_key) and for a missing triage expectation are untested | small | S:C/low M:C/low I:C/low |
| [F039](#f039) | open | low | low | A | Audit file paths use the date of collection, so re-running audit-collect or llm-feedback on another day writes duplicates | small | S:C/low M:C/low I:C/low |
| [F045](#f045) | open | low | medium | B | The allow rules for just, uv run, dotnet and gh run auto-approve arbitrary and irreversible commands, which makes the deny list ineffective | small | S:C/low M:C/low I:C/low |
| [F046](#f046) | open | low | medium | B | Ephemeral containers are tested nowhere: removing them from the images policy leaves every test green | trivial | S:C/low M:C/medium I:C/low |
| [F053](#f053) | open | low | low | B | Re-runs keep the original event's updated_at as pr_event_at, so the turnaround metric includes the time people took to trigger the re-run | trivial | S:C/low M:C/low I:C/low |
| [F054](#f054) | open | low | low | B | The deployable unit, the chart, is installed by a mutable version tag and verified by nothing | small | S:C/low M:C/low I:C/low |
| [F056](#f056) | open | low | low | B | k8s-up's restart path neither waits for the API server nor restores the kubeconfig | small | S:C/low M:C/low I:C/low |
| [F057](#f057) | open | low | low | B | cluster=local inherits $KUBECONFIG, so it breaks in exactly the shell setup AGENTS.md suggests | trivial | S:C/low M:C/low I:C/low |
| [F071](#f071) | open | low | low | B | The version tags, the moving X.Y tag and the chart are pushed before admission-smoke and smoke run | small | S:C/low M:C/low I:C/low |
| [F072](#f072) | open | low | low | B | pr-title isn't re-checked when the title is edited, so the check can stay green on a title that isn't a Conventional Commit | small | S:C/low M:C/low I:C/low |
| [F073](#f073) | open | low | low | B | Records are dropped when an llm-review run completes after its PR was merged | trivial | S:C/low M:C/low I:C/low |
| [F074](#f074) | open | low | low | B | The consistency check validates the main.json file, not the live ruleset, and ignores job-level if: | small | S:C/low M:C/low I:C/low |
| [F075](#f075) | open | low | low | B | GH_TOKEN with contents: write is set for the whole collect job, including the step that parses untrusted artifacts | trivial | S:C/low M:C/low I:C/info |
| [F076](#f076) | open | low | low | B | Dependabot's uv updates for tools/llm-gate will stall at the fixed exclude-newer date in pyproject.toml | small | S:C/low M:C/low I:P/low |
| [F083](#f083) | open | low | medium | C | The coverage metric doesn't count triage's not_needed verdict as a decision, so every merged low-risk PR shows as not covered | small | S:C/low M:C/medium I:C/low |
| [F085](#f085) | open | low | medium | C | The workdays range guard near year 9999 (start year above 9989) has no test | trivial | S:C/low M:C/low I:C/low |
| [F086](#f086) | open | low | low | C | OpenAPI documents workdays' from/to as optional plain strings and week's {date} without a date format | small | S:C/low M:C/low I:C/low |
| [F090](#f090) | open | low | low | C | llm-gate's README leaves out the triage and attest subcommands and --risk/LLM_GATE_RISK, which the workflows call | small | S:C/low M:C/low I:C/low |
| [F096](#f096) | open | low | low | C | OpenAPI declares every integer in the responses as integer-or-string, though the API only writes JSON numbers | trivial | S:C/low M:C/info I:C/low |
| [F098](#f098) | open | low | low | C | The contract tests check the content type on 2 of 17 requests and leave out several error contracts | small | S:C/info M:C/low I:C/low |
| [F099](#f099) | open | low | low | C | The blocking code-review prompt's scope and severity rubric cover only the date API, not the gate code most PRs change | medium | S:C/low M:C/low I:C/low |
| [F104](#f104) | open | low | low | C | PLAN.md's drill table, which /gate-drill checks results against, predates reasoned overrides and the --no-verify ban | small | S:C/info M:C/low I:C/low |
| [F111](#f111) | open | low | low | C | /api/friday13/next's 404 (no Friday the 13th left before year 10000) has no test | trivial | S:C/low M:C/low I:C/info |
| [F113](#f113) | open | low | low | C | VersionEndpoints.Read has no unit test, and the version/commit checks accept its fallbacks | small | S:C/low M:C/low I:C/info |
| [F114](#f114) | open | low | low | C | The leap endpoint's year validation is tested only with 99999 | trivial | S:C/low M:C/low I:C/low |
| [F048](#f048) | 🟡 partial | low | medium | B | Every attestation Kyverno requires exists before the release is approved or smoke-tested, so rejected and failed candidates are admitted | medium | S:C/low M:C/low I:C/low |
| [F091](#f091) | 🟡 partial | low | low | C | The audit/v1 type lists in ADR 0005 and in the audit-log branch README are out of date | small | S:C/low M:C/low I:C/low |
| [F013](#f013) | ✅ fixed | low | medium | A | `llm-gate run --risk` for a check the level runs (demoted to advisory, engine switched) is never exercised | small | S:C/low M:C/low I:C/low |
| [F014](#f014) | ✅ fixed | low | medium | A | Only `feedback` is tested as a record type a PR's artifact may not carry; `risk_override` is not | trivial | S:C/low M:C/low I:C/low |
| [F015](#f015) | ✅ fixed | low | medium | A | The 'exactly one triage record' rule is untested; the test named for it passes through a different check | trivial | S:C/low M:C/low I:C/low |
| [F016](#f016) | ✅ fixed | low | medium | A | The 128 KB per-artifact limit is untested, and the 256 KB per-line limit can never trigger | trivial | S:C/low M:C/low I:C/low |
| [F017](#f017) | ✅ fixed | low | medium | A | The committed-eval-cases test is skipped in CI (shallow checkout), and one missing base skips every case | trivial | S:C/low M:C/low I:C/low |
| [F019](#f019) | ✅ fixed | low | medium | A | fp-tr-835a can still pass for the wrong reason: its forbid rule needs a literal `$IMAGE` in the title | trivial | S:C/low M:C/low I:C/low |
| [F030](#f030) | ✅ fixed | low | low | A | floor_violations can never be non-zero: it is computed from final_risk(), which takes the higher risk | trivial | S:C/low M:R/info I:C/low |
| [F031](#f031) | ✅ fixed | low | low | A | 'Latest wins' tests use fixtures already in time order; the invalid-`to` fixture is rejected for its bad ts | trivial | S:C/low M:C/low I:C/low |
| [F033](#f033) | ✅ fixed | low | low | A | Two of the eight redaction patterns (Slack, JWT) have no test case | trivial | S:C/low M:C/low I:C/low |
| [F035](#f035) | ✅ fixed | low | low | A | `/llm-ack` recording and a writer's malformed command are never tested through handle() | trivial | S:C/low M:C/low I:C/low |
| [F036](#f036) | ✅ fixed | low | low | A | The API engine's cost is checked against estimate_cost itself; the price arithmetic has no independent test | trivial | S:C/low M:C/low I:C/low |
| [F038](#f038) | ✅ fixed | low | low | A | The prompt-guard test skips llm-triage.md | trivial | S:C/low M:C/info I:C/low |
| [F055](#f055) | ✅ fixed | low | low | B | pr-title accepts non-Conventional titles that start with 'Merge ', 'fixup! ', 'squash! ' or 'amend! ' | trivial | S:C/low M:C/low I:C/low |
| [F058](#f058) | ✅ fixed | low | low | B | k8s-policy-up returns before the policies are ready, so a deploy right after it can be admitted unchecked | trivial | S:C/low M:C/low I:C/low |
| [F059](#f059) | ✅ fixed | low | low | B | k8s-cluster-down ignores cluster=, so with cluster=local it deletes the project cluster | trivial | S:R/info M:C/low I:C/low |
| [F060](#f060) | ✅ fixed | low | low | B | k8s-http doesn't notice a port-forward that failed to bind 18080, and tests whatever already listens there | trivial | S:C/low M:C/low I:C/low |
| [F062](#f062) | ✅ fixed | low | low | B | A failed push in just release leaves the local tag behind, and the retry stops at 'already exists' | trivial | S:C/info M:C/low I:C/low |
| [F064](#f064) | ✅ fixed | low | low | B | gh-setup uploads the whole pass entry as ANTHROPIC_API_KEY, while the other recipes use only its first line | trivial | S:C/info M:C/low I:C/low |
| [F065](#f065) | ✅ fixed | low | low | B | The timeout counts attempts, not seconds, because curl runs without --max-time | trivial | S:C/low M:C/low I:C/low |
| [F070](#f070) | ✅ fixed | low | low | B | Nothing tests who may honour a bot-added override (override-writers.sh) | small | S:C/low M:C/low I:C/low |
| [F082](#f082) | ✅ fixed | low | medium | C | OpenAPI documents only 200 for /api/easter/{year}, /api/leap/{year} and /api/friday13, which also return 400 ValidationProblem | trivial | S:C/low M:C/low I:C/low |
| [F089](#f089) | ✅ fixed | low | low | C | docs/gates.md's list of required checks leaves out llm-eval and says the other checks don't block | trivial | S:C/low M:C/low I:C/low |
| [F092](#f092) | ✅ fixed | low | low | C | Undocumented: llm-eval passes without running when there's no API key, and LLM_GATE_MISSING_KEY doesn't apply to it | trivial | S:C/low M:C/low I:C/low |
| [F093](#f093) | ✅ fixed | low | low | C | Kyverno update instructions point at "the chart version in the justfile", which doesn't exist | trivial | S:C/low M:C/low I:C/low |
| [F094](#f094) | ✅ fixed | low | low | C | WRITEUP §5 says the metrics still count drill 19's /llm-fp marking; §3 and metrics.py say the later /llm-ack reversed it | trivial | S:C/low M:C/low I:C/low |
| [F095](#f095) | ✅ fixed | low | low | C | "Denied in calendar-gates since v0.3.1": the Deny switch came after v0.3.1 and no release has exercised it | trivial | S:C/low M:C/low I:C/low |
| [F100](#f100) | ✅ fixed | low | low | C | AGENTS.md says only audit-collect.yml writes the audit-log branch; llm-feedback.yml writes to it too | trivial | S:C/low M:C/low I:C/low |
| [F101](#f101) | ✅ fixed | low | low | C | The kyverno test file says it runs in `just lint`; it runs in `just lint-policies` | trivial | S:C/info M:C/low I:C/low |
| [F102](#f102) | ✅ fixed | low | low | C | The lint gate's local equivalent and tool list omit the kyverno policy tests that CI's lint job runs | trivial | S:C/low M:C/low I:C/low |
| [F103](#f103) | ✅ fixed | low | low | C | /gate-drill sends "drills 13 and up" to PLAN-v2, but drill 13 is in PLAN.md and v2 starts at 14 | trivial | S:C/low M:C/low I:C/low |
| [F105](#f105) | ✅ fixed | low | low | C | The entry docs point only at docs/PLAN.md; PLAN-v2.md (Phases 13-21, drills 14-23) is never mentioned | trivial | S:C/low M:C/low I:C/low |
| [F107](#f107) | ✅ fixed | low | low | C | llm-eval also fails when a forbidden (fp-regression) finding returns; gates.md and WRITEUP don't say so | trivial | S:C/low M:C/low I:C/low |
| [F108](#f108) | ✅ fixed | low | low | C | /new-endpoint skips the two exact OpenAPI route lists a new endpoint must be added to | trivial | S:C/info M:C/low I:C/low |
| [F109](#f109) | ✅ fixed | low | low | C | The quick start's requirements don't cover `just setup` / `just ci`, which now need an exact kyverno CLI | trivial | S:C/low M:C/low I:C/low |
| [F025](#f025) | ✅ fixed | low | low | A | One /llm-override writes an override record per check job, including advisory, passing and not-applicable checks, and the release attestation repeats them all | trivial | S:C/low M:C/low I:C/low |
| [F069](#f069) | ✅ fixed | low | low | B | No test exercises the admission rule 'no critical vulnerabilities' | medium | S:A/info M:C/low I:C/low |
| [F037](#f037) | ✅ fixed | low | low | A | docs-drift has no eval case, and test-review has only an fp-regression case | medium | S:C/low M:C/low I:C/low |
| [F028](#f028) | open | info | low | A | eval add-from-fp looks up a 16-bit finding id across every PR and takes the last match | trivial | S:C/info M:C/low I:C/info |
| [F040](#f040) | open | info | info | A | gate_run records for checks that triage didn't need carry the configured blocking flag, not the effective one | trivial | S:C/info M:C/info I:C/info |
| [F080](#f080) | open | info | info | B | Tool versions pinned inside run: steps and with: inputs aren't covered by Dependabot | medium | S:C/info M:C/info I:C/info |
| [F110](#f110) | open | info | low | C | Friday-the-13th lists are compared ignoring order | trivial | S:C/info M:C/info I:C/info |
| [F112](#f112) | open | info | low | C | CurrentWeekUsesTodayInUtc can't tell UTC from local time | trivial | S:C/info M:C/low I:C/info |
| [F116](#f116) | open | info | info | C | The api-contract prompt defines the contract as the /api routes and OpenAPI, leaving out /health, which checks.yaml gives as a reason to review Program.cs | small | S:C/info M:C/info I:C/info |
| [F128](#f128) | open | info | info | C | The docs-drift gate's own list of docs leaves out the tool READMEs and command files, where drift collects | small | S:C/info M:C/info I:C/info |
| [F061](#f061) | ✅ fixed | info | low | B | audit-pull, and with it metrics, fails when the audit-log branch has no events/ directory | trivial | S:C/info M:C/low I:C/info |
| [F063](#f063) | ✅ fixed | info | low | B | just lint hands the user's full-scope gh OAuth token to a PyPI-fetched zizmor on every run | trivial | S:R/info M:C/low I:C/info |
| [F077](#f077) | ✅ fixed | info | info | B | The pre-commit ruff job skips scripts/*.py, which the lint gate checks | trivial | S:C/info M:C/info I:C/info |
| [F078](#f078) | ✅ fixed | info | info | B | llm and llm-list run uv without --locked, unlike every other recipe and CI | trivial | S:C/info M:C/info I:C/info |
| [F106](#f106) | ✅ fixed | info | low | C | ADR 0005 says the untrusted llm job uploads with a read-only token; it holds pull-requests: write | trivial | S:C/info M:C/low I:C/info |
| [F115](#f115) | ✅ fixed | info | info | C | Header comments in checks.yaml and the workflows still describe the override label alone, a per-level model and a not-yet-required llm-eval | trivial | S:C/info M:C/info I:C/info |
| [F119](#f119) | ✅ fixed | info | info | C | ADR 0004's amendment names a job, `llm-plan`, that no longer exists | trivial | S:C/info M:C/info I:C/info |
| [F120](#f120) | ✅ fixed | info | info | C | ADR 0009's job order and release.yml's header comment leave out admission-smoke | trivial | S:C/info M:C/info I:C/info |
| [F121](#f121) | ✅ fixed | info | info | C | WRITEUP's cr-def4 doesn't match the finding the audit log records under that id | trivial | S:R/info M:C/info I:C/info |
| [F122](#f122) | ✅ fixed | info | info | C | The turnaround row's unlabelled "1.0 / 2.3 min" is code-review's figure, not the overall one | trivial | S:C/info M:C/info I:C/info |
| [F123](#f123) | ✅ fixed | info | info | C | WRITEUP §5 says high-risk PRs "get Opus", in the present tense, though #58 switched them back to Sonnet | trivial | S:C/info M:C/info I:C/info |
| [F124](#f124) | ✅ fixed | info | info | C | "To regenerate (costs API credits)" includes `just metrics`, which spends nothing | trivial | S:C/info M:C/info I:C/info |
| [F125](#f125) | ✅ fixed | info | info | C | values-kind.yaml calls itself kind-local's, but `just k8s-load`/`k8s-deploy` now target the project cluster | trivial | S:C/info M:C/info I:C/info |
| [F126](#f126) | ✅ fixed | info | info | C | PLAN-v2's Status table says ADR 0008 records the rename rule; ADR 0008 never mentions renames | trivial | S:C/info M:C/info I:C/info |
| [F127](#f127) | ✅ fixed | info | info | C | gate-debugger still says docs/gates.md has details "when it exists" | trivial | S:C/info M:C/info I:C/info |
| [F129](#f129) | ✅ fixed | info | info | C | "Lint tool versions are pinned in both ci.yml and the lint recipe" holds for only some of the tools | trivial | S:C/info M:C/info I:C/info |
| [F130](#f130) | ✅ fixed | info | info | C | AGENTS.md says `just ci` runs "every deterministic gate"; http-tests, grype and k8s-smoke aren't in it | trivial | S:C/info M:C/info I:C/low |
| [F131](#f131) | ✅ fixed | info | info | C | The workflow-review prompt attributes workflow rules to AGENTS.md; they live in docs/PLAN.md | trivial | S:C/info M:C/info I:C/info |
| [F132](#f132) | ✅ fixed | info | info | C | No doc or recipe explains how to create the Gate health issue and set GATE_HEALTH_ISSUE | trivial | S:C/info M:C/info I:C/info |
| [F050](#f050) | ⚪ unverifiable | medium | medium | B | Required checks are pinned to the GitHub Actions app, not to the jobs that produce them, while three PR jobs hold checks: write next to PR-controlled code | small | S:P/medium M:P/low I:P/medium |

## Confirmed

#### Confirmed: high

### F001

**A PR's own .gitattributes can hide its changes from every LLM reviewer and from triage's size rule**

- **Status:** ✅ fixed — #68: the review diff reads attributes from the base (`--attr-source`) with `--text`, and an uncountable size raises the floor to high
- **Severity:** high (reviewers: high) · **outcome:** confirmed · **fix cost:** small
- **Where:** `tools/llm-gate/src/llm_gate/diff.py:55` · **area:** llm-gate and review prompts
- **Reported by:** `cr-gate-01` (high, high confidence), `sec-01` (high, high confidence)

**`cr-gate-01`: A PR's own .gitattributes can hide its changes from every LLM reviewer and from triage's size rule**

merge_base_diff runs `git diff --no-color --no-ext-diff --merge-base <base> HEAD` with cwd = the PR-head checkout (llm-review.yml checks out head.sha into src/ and runs `llm-gate --repo src`). Git applies the working tree's .gitattributes, so any path marked `-diff` (or `binary`) comes out as 'Binary files a/X and b/X differ' with no content, and triage.numstat (triage.py:70) reports '-' added/deleted for it, i.e. 0 lines. The repository already relies on this to keep a fixture out of reviews (.gitattributes line 4: 'keeps it out of llm-gate reviews and their size cap'). I verified the mechanism on commit 5da7638 by supplying `*.cs -diff` through core.attributesFile, which uses the same attribute lookup: all six Domain/*.cs files became 'Binary files /dev/null and b/... differ' and numstat showed '-  -'. EXCLUDES is base-controlled (ADR 0004), but the attributes that decide what the diff text contains come from the PR. The api engine (security-review below high risk) then receives no code at all; the agent engine gets only placeholders and has to decide on its own to Read the files; the triage model sees the same placeholders. Git's own binary heuristic (a NUL byte in the first 8000 bytes) has the same effect without any .gitattributes. The collector can't notice: it records what llm-gate saw.

*Failure scenario:* A PR adds `.gitattributes` lines `src/** -diff` and `.gitattributes -diff`, plus an off-by-one in WorkdaysCalculator.cs. Both blocking reviews get two 'Binary files ... differ' entries and report nothing at or above fail_on (the prompts say to report only problems they can point to): verdict pass. Triage's size raise sees 0 lines. audit-log: pass, not workflow_modified; the release llm-review attestation lists the PR as reviewed and verified.

*Suggested fix:* Build the review diff with `git diff --text` (and `--numstat --text` for triage) so attributes and the binary heuristic can't drop content; keep genuine binaries out through the base-controlled EXCLUDES (move the fixture exclusion there), or fail a blocking check closed when a text-like path comes out as binary.

**`sec-01`: A PR can hide its own code from both blocking LLM reviews with a `.gitattributes` `-diff` line**

`merge_base_diff` runs `git diff --no-color --no-ext-diff --merge-base <base> HEAD` without `--text`, so git honours the `diff` attribute of the **PR's own** `.gitattributes`. The repository already relies on this behaviour deliberately (`.gitattributes:4`: `tools/llm-gate/tests/fixtures/*.json -diff`, commented "keeps it out of llm-gate reviews"), which is exactly the primitive an attacker needs. Verified locally against this repo: with an attributes file containing `*.cs -diff`, `git diff <sha>^ <sha> -- src` prints only `Binary files a/... and b/... differ`, and adding `--text` brings the content back. The same hidden diff is what the triage model sees (`triage.user_content` -> `merge_base_diff`). The size floor is defeated too: `git diff --numstat` reports `-\t-` for such a file and `parse_numstat` (triage.py:92) turns that into `lines = 0`, even with `--text`, so a 5000-line change counts as 0 changed lines and never reaches the `high_over_lines` floor. The file names are still listed (`--name-only` is unaffected), so `check.paths` still matches and the blocking checks *run* and report a clean pass rather than `not_applicable`. Nothing downstream notices: the record is not `workflow_modified`, the collector's triage recomputation uses the compare API's additions/deletions (which GitHub reports normally) only for the floor it compares against the record's `rules_risk`, and the floor itself never rose.

*Failure scenario:* PR adds one line `*.cs -diff` to `.gitattributes` plus an arbitrary change to `src/**` (say, logging the `Authorization` header). `.gitattributes` matches no triage rule -> default_risk medium, `src/**` -> medium, size 0 lines -> floor stays medium, so `code-review` and `security-review` run and block. Both receive a diff whose only content is `Binary files ... differ` for every `.cs` file, find nothing, and pass. The audit log records two verified passes, and the release attestation lists the PR as reviewed.

*Suggested fix:* Add `--text` to both `git diff` calls in `merge_base_diff`, and move the fixture exclusion from `.gitattributes` into `diff.EXCLUDES`. Separately, treat a numstat `-` on a path that is not in `EXCLUDES` as a problem: count its lines from the `--text` diff, or fail the blocking checks closed (and rate `.gitattributes` high in `triage.rules`).

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, high, small): Verified the mechanism in this repo: the committed `.gitattributes` line `tools/llm-gate/tests/fixtures/*.json -diff` makes `git diff --no-ext-diff ec40cb6^ ec40cb6` print only 'Binary files ... differ' for a 3395-line JSON file, `--text` brings the content back, and `--numstat` reports `-	-` even with `--text` (so parse_numstat counts 0 lines). merge_base_diff runs in the PR-head checkout (`--repo src`), so the PR's own attributes decide what both blocking reviews and the triage model see; nothing in runner, policy or the collector notices a text file coming out as binary, and `.gitattributes` matches no triage rule (medium). The agent engine can still Read the files but can't see what changed, and security-review below high is API-only. Unlike the accepted workflow-file hole, this sets no workflow_modified flag. One nuance in sec-01: for a PR large enough to cross a size threshold, the collector's compare-API recompute could flag a rules_risk mismatch if GitHub reports real line counts for -diff files (unverified); it doesn't matter for the small-bug scenario.
- **maintainer** (CONFIRMED, high, small): Reproduced in a scratch clone at 5da7638 with `src/** -diff` in the working tree's .gitattributes: merge_base_diff returned only 'Binary files /dev/null and b/src/... differ' for every src file and triage.numstat gave 0 lines for them. `git diff --text` restores the diff text, but `--numstat --text` still prints '-\t-' (sec-01 is right there; cr-gate-01's `--numstat --text` suggestion would not fix the size rule). `git --attr-source=<base>` (git 2.56 here) restores both the diff and the counts and fits ADR 0004 (attributes then come from the base, like the rest of the gate). ADR 0004's accepted hole is editing llm-review.yml, which the collector flags; this route is not flagged, and .gitattributes matches no triage rule, so a medium-risk security-review on the api engine sees no code at all.
- **impact** (CONFIRMED, medium, small): Reproduced read-only on this repo's history: with a `-diff` attribute (core.attributesFile, the same lookup as the checkout's .gitattributes) `git diff` prints only 'Binary files ... differ' and numstat prints '-\t-', which parse_numstat counts as 0 lines; --name-only still lists the file, so the checks run and pass. Trigger is only a PR author with write access (forks get no key), but it is one cheap line, the repo's own .gitattributes documents the pattern as the way to keep files out of reviews, and nothing flags it (not workflow_modified; .gitattributes falls to default medium), so the pass is recorded as verified. Calibrated down from high: the agent engine (code-review always, both blocking checks at high risk) still sees the file names and can Read the head versions, the PR's file list is visible, and the Kyverno llm-review policy only checks that the attestation exists, so the extra cost over the accepted llm-review.yml hole is a wrong record. Note: `git diff --numstat --text` still prints '-' for -diff paths (git 2.56), so cr-gate-01's suggested numstat fix would not restore the size count; counting lines from the --text diff (sec-01) would.

</details>

### F002

**Review results restored from the Actions cache are trusted unverified, and other workflows of the same PR can write that cache**

- **Status:** ✅ fixed — #68: llm-review keeps no review cache, and the collector refuses a blocking record claiming a cache hit
- **Severity:** high (reviewers: high) · **outcome:** confirmed · **fix cost:** medium
- **Where:** `tools/llm-gate/src/llm_gate/cache.py:27` · **area:** llm-gate and review prompts
- **Reported by:** `cr-gate-02` (high, medium confidence), `sec-02` (high, high confidence), `wr-03` (medium, medium confidence)

**`cr-gate-02`: Review results restored from the Actions cache are trusted unverified, and other workflows of the same PR can write that cache**

Cache.get returns any .llm-gate/cache/<sha256>.json that validates as an EngineResult, and run_check decides from it as a cache hit. In CI that directory comes from actions/cache/restore with restore-keys `llm-gate-<check>-pr<N>-` (llm-review.yml:273-278): the newest cache with that prefix in the PR's scope refs/pull/N/merge. Every pull_request-triggered workflow of the same PR shares that scope, and ci.yml, llm-eval.yml and llm-compare.yml run from the PR's own YAML. The PR can compute the file name: the check, engine and model, the base branch's public prompt, and the merge-base diff, which a step can compute at run time. The collector flags only changes to the triggering workflow's file (audit-collect.yml:113-114 greps for .github/workflows/llm-review.yml), so this route doesn't set workflow_modified. Even without a workflow edit, PR code already runs in ci.yml (lint runs the PR's pytest, build-test the PR's MSBuild); public research (Cacheract) shows such code can obtain the job's cache token on hosted runners. I did not run the attack; the scope sharing is documented GitHub cache behaviour.

*Failure scenario:* A PR with a planted bug adds a first job to ci.yml. The job writes .llm-gate/cache/<key>.json = {engine, model, review: {summary: 'ok', findings: []}, duration_ms: 1} for code-review/agent and security-review/api, then runs actions/cache/save with key llm-gate-code-review-pr<N>-x (and a -security-review- one). It finishes before llm-review's triage job does, so the llm job's restore (exact key miss, then newest prefix match) gets the forged entry: cache hit, verdict pass, `llm / code-review` green. The audit record says pass with cache_hit true and workflow_modified false, and the release attestation says pass, not unverified. ADR 0004's remaining hole is scoped to llm-review.yml and mitigated by workflow_modified; this route bypasses that mitigation.

*Suggested fix:* Authenticate cache entries: an HMAC over the key and content with a secret that only the llm job receives (not llm-eval), where a mismatch counts as a miss. Alternatively, don't reuse cached results across runs for blocking checks. Also have the collector treat a PR that changes anything under .github/workflows/ or .github/actions/ as workflow_modified.

**`sec-02`: A PR can forge a cached "no findings" review from a second workflow it adds, without touching llm-review.yml**

The `llm` job restores `.llm-gate/cache` with key `llm-gate-<check>-pr<N>-<github.sha>` and the prefix restore-key `llm-gate-<check>-pr<N>-` (lines 273-278), and `runner.run_check` returns a cache hit verbatim as the review result (runner.py:73-79). The cache key is `sha256(json([CACHE_VERSION, check, engine, model, prompt, diff]))` (cache.py:15-17) and every input is known to the PR author: `CACHE_VERSION` and the prompt come from the base branch, the diff from their own branch. Actions caches are scoped per ref, not per workflow, so **any** workflow running on the same `pull_request` ref can write that entry — and on `pull_request` GitHub runs the workflow files from the PR head, so the PR can simply add `.github/workflows/anything.yml` that writes a crafted `EngineResult` (empty `review.findings`) under that key. `llm-review.yml` itself is untouched, so `audit-collect.yml`'s `workflow_modified` check (audit-collect.yml:113-114, which greps only for `.github/workflows/llm-review.yml`) stays false and the forged pass is written to `audit-log` as a verified review with `cache_hit: true`; the collector's cross-checks (job conclusion, triage floor) all agree, because the job really did succeed at the planned risk. docs/gates.md even documents the trigger: "Adding or removing a label re-runs only these checks, from the cache", so the attacker pushes, lets the poison workflow save the entry, then adds any label to re-run the review.

*Failure scenario:* PR #N contains a real vulnerability plus `.github/workflows/warm.yml` with `on: pull_request`, which computes the cache key locally and saves `{"engine":"agent","model":"claude-sonnet-5-5","review":{"summary":"...","findings":[]},"duration_ms":5000}` as `.llm-gate/cache/<key>.json` under `llm-gate-code-review-prN-<merge-sha>`. Adding a label re-runs llm-review; both blocking checks report pass from the cache, and audit-log keeps them as verified.

*Suggested fix:* Make cached results unforgeable or unusable as evidence: store an HMAC of the entry keyed by a repository secret and reject entries that don't verify, or drop the cross-run `restore-keys` and let the collector mark any `gate_run` with `cache_hit: true` as unverified unless the log already holds a non-cached record for the same `pr`, `head_sha`, `check` and `diff_sha256`.

**`wr-03`: A push that modifies the workflow can plant a cached "pass" that a later, unmodified push restores as a verified review**

The llm job restores .llm-gate/cache with `restore-keys: llm-gate-<check>-pr<N>-`. That gives it the newest entry any earlier run of the same PR saved, because PR runs share the refs/pull/N/merge cache scope. A cache entry is a plain EngineResult JSON file at .llm-gate/cache/<sha256(check, engine, model, prompt, diff)>.json, with no integrity check (cache.py:15-38). The PR author knows every input to that key in advance: the base branch's prompt, the model, the engine for the risk level and the final diff. A push that edits llm-review.yml can write such a file with `findings: []` and save it under that prefix with actions/cache/save. That run is flagged workflow_modified. The next push reverts the workflow edit, so the compare API no longer lists llm-review.yml and workflow_modified is false. Its llm job restores the planted directory, run_check gets a cache hit, and the record says verdict pass, cache_hit true, no cost and no tool calls. collect() accepts it, and attestations.llm_review reports "code-review: pass" with nothing listed as unverified. The same probably applies to setup-uv's dependency cache, which is on by default for pull_request (enable-cache: auto). An earlier run could then plant code that runs in later "clean" triage and llm jobs, which hold the API key. ADR 0004 accepts that a PR can edit llm-review.yml, but its mitigation (workflow_modified) assumes the effect stays in the modified run.

*Failure scenario:* Commit A edits llm-review.yml to save a cache entry for commit B's diff, computed locally with llm_gate.cache.cache_key. Commit B reverts the workflow and adds a high-severity bug. In run B the workflow is unmodified, code-review is a cache hit, and the verdict is pass. The audit log and the release attestation show a verified pass for a review that never happened.

*Suggested fix:* In the collector (or in attestations.llm_review), count a cache_hit gate_run as verified only if the log already holds a non-cached gate_run for the same PR with the same check, engine, model, prompt_sha256 and diff_sha256, from a run that wasn't workflow_modified and has no tamper record. Drop restore-keys for blocking checks. Set enable-cache: false on setup-uv in llm-review.yml and llm-compare.yml.

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, high, medium): Cache.get returns any file that validates as an EngineResult and run_check treats it as a review; the key is sha256 of [CACHE_VERSION, check, engine, model, prompt body, diff], all known or computable by the PR author. GitHub's dependency-caching docs (fetched) confirm caches are shared by all workflow runs of the same repository and ref with no per-workflow isolation, keys are immutable, and a restore-key partial match returns the most recently created cache, so another pull_request workflow of the same PR can plant the entry before the llm job's restore (llm-review.yml:273-278). The collector sets workflow_modified only when the compare files contain the llm-review.yml path (audit-collect.yml:113-114) and has no cache_hit check, so the forged pass is recorded and attested as verified. ADR 0004 accepts that a PR can edit llm-review.yml with detection as the mitigation; this route defeats the detection, so it is not ACCEPTED. wr-03's setup-uv cache-poisoning extension is plausible but unverified; the main claim doesn't depend on it.
- **maintainer** (CONFIRMED, high, medium): Cache.get accepts any file that validates as an EngineResult and run_check treats it as the review; every key input (CACHE_VERSION, check, engine, model, the base's public prompt, the PR's own diff) is computable by the PR author. GitHub's caching docs: 'A cache created for a branch in a workflow run can be accessed and restored from another workflow run for the same repository and branch', and pull_request caches live in refs/pull/N/merge, so ci.yml, llm-eval.yml or a PR-added workflow can save `llm-gate-<check>-prN-<sha>` before llm-review restores it; the collector greps only for llm-review.yml. wr-03's two-push path also holds and needs no race: the prefix restore-key hands run B the newest cache of the flagged run A. ADR 0004 accepts the workflow-file hole only with workflow_modified as its mitigation, which both routes evade, so not ACCEPTED. Note an HMAC keyed by a repo secret would not stop wr-03 (the modified llm-review.yml run has the same secrets); verifying cache-hit records in the collector against an earlier non-cached record, and flagging any .github/ change, would.
- **impact** (CONFIRMED, medium, medium): Cache.get trusts any file that validates as EngineResult; every key input (CACHE_VERSION, check, engine, model, the base branch's prompt, the merge-base diff) is computable by the PR; the llm job restores the exact key llm-gate-<check>-pr<N>-<merge sha> or the newest prefix match. GitHub's caching docs confirm that workflow runs on the same ref share caches and a PR's caches live in refs/pull/N/merge, so a PR-added workflow (or its edited ci.yml or llm-eval.yml) can save the forged entry first, and audit-collect.yml sets workflow_modified only when llm-review.yml itself changed: the forged pass lands on audit-log as verified with cache_hit true. Trigger is a collaborator doing deliberate, modest engineering (no accidental path; fork PRs skip the review without a key); since admission only checks that the attestation exists and the same person can get a flagged bypass by editing llm-review.yml, the cost is a false 'verified' record, so medium rather than high. cr-gate-02's HMAC fix doesn't work as stated (a same-repo PR's own workflow can request any repository secret); collector-side provenance for cache hits (sec-02, wr-03) or flagging any .github/** change is workable. I did not run the attack on GitHub.

</details>

#### Confirmed: medium

### F003

**The agent reviewer's file reads are not fenced to the reviewed checkout, and its output is published unredacted**

- **Status:** open
- **Severity:** medium (reviewers: high) · **outcome:** confirmed · **fix cost:** small
- **Where:** `tools/llm-gate/src/llm_gate/engines/agent_engine.py:89` · **area:** llm-gate and review prompts
- **Reported by:** `sec-03` (high, medium confidence), `wr-19` (medium, low confidence)

**`sec-03`: The agent reviewer's file reads are not fenced to the reviewed checkout, and its output is published unredacted**

`options()` passes `tools=["Read","Grep","Glob"]` and `allowed_tools=["Read","Grep","Glob"]`, which the SDK turns into `--tools Read,Grep,Glob --allowedTools Read,Grep,Glob` (claude_agent_sdk/_internal/transport/subprocess_cli.py:596-608). Per Claude Code's permission reference, a bare `Read` rule "Matches all file reads", and `dontAsk` mode denies only what would otherwise prompt while "tools pre-approved via ... `permissions.allow` rules" still run; reads outside the working directory are exactly the case that would otherwise prompt. Nothing narrows this: `setting_sources=[]`, `settings` only sets `disableAllHooks`, there is no `Read(./**)` scoping, no `permissions.deny`, and no `blockReadsOutsideWorkingDirectories`. The reviewed PR's files are the agent's input, so a successful prompt injection in them can direct reads beyond `src/` - including the CLI process's own `/proc/self/environ`, which carries `ANTHROPIC_API_KEY` (llm-review.yml:284; the SDK inherits `os.environ`, subprocess_cli.py:819-822). The exfiltration channel is open as well: `report.render_markdown` prints the model's `summary`, `title`, `detail` and `suggestion` with only `|`/newline escaping (report.py:82-104), and `llm-review.yml` writes that straight into `$GITHUB_STEP_SUMMARY` and the public sticky PR comment. Only the audit record is redacted (`redact.py`), so the one sink that is scrubbed is the private-ish one and the public ones are not.

*Failure scenario:* A PR file carries injected text that the reviewer follows (the evals measure, but cannot exclude, this - WRITEUP §4). The agent reads `/proc/self/environ`, splits the key across a finding's `detail` and `suggestion`, and llm-review posts them as a PR comment on a public repository; GitHub's log masking doesn't cover an API-posted comment, nor a value the model re-encodes.

*Suggested fix:* Scope the reads: pass path-qualified allow rules (`Read(./**)`, `Grep(./**)`, `Glob(./**)`) or set `blockReadsOutsideWorkingDirectories` plus a `permissions.deny` for `/proc/**` and `~/**`, with `cwd=src/` as the only working directory. Also run `redact()` over the rendered review before it reaches the job summary and the PR comment, as the audit log already does.

**`wr-19`: The agent reviewer has the API key in its environment and an allow rule for Read with no path, and its output is posted unredacted to the public PR comment**

The Review step exports ANTHROPIC_API_KEY, and the Agent SDK passes os.environ on to the bundled CLI (claude_agent_sdk/_internal/transport/subprocess_cli.py:819). /proc/self/environ and the parent llm-gate process's environ therefore hold the key. AgentEngine allows the bare tools Read, Grep and Glob (allowed_tools=READ_ONLY_TOOLS) with permission_mode dontAsk. Whether an allow rule with no path also pre-approves paths outside cwd=src/, such as /proc/self/environ, depends on Claude Code's permission matching, which I couldn't check offline: the CLI is a compiled binary. The model's summary, titles, details and suggestions go verbatim into the sticky PR comment, the job summary and the 90-day results artifact (report.render_markdown). redact() is applied only to audit records. A prompt injection in the diff that gets the agent to read the environment would publish the key.

*Failure scenario:* A PR includes vendored docs that tell reviewers to quote /proc/self/environ to confirm the runtime. If the agent complies and Read is allowed there, the API key appears in the code-review sticky comment.

*Suggested fix:* Deny Read and Grep outside the checkout (e.g. disallowed rules for //proc/** and the runner's home directory), and scope the allow rules to the checkout. Run redact() over the rendered Markdown before it is posted and before it goes into the job summary. Confirm with an eval case that plants such an instruction.

<details><summary>Council</summary>

- **skeptic** (PLAUSIBLE, medium, small): Checked in the installed SDK: allowed_tools becomes `--allowedTools Read,Grep,Glob` and the CLI inherits os.environ, so ANTHROPIC_API_KEY is in the agent process's environment (subprocess_cli.py:608, 819). Claude Code's permissions docs (fetched) say a bare `Read` rule 'Matches all file reads' and that dontAsk still runs 'actions matching your permissions.allow rules', so reads outside cwd=src/ (e.g. /proc/self/environ) look pre-approved; I can't run the CLI offline to confirm it reads /proc. The publication half is confirmed: render_markdown emits summary, title, detail and suggestion without redact() into the sticky PR comment and job summary. Exploitation needs a successful injection; since PR authors already have the key by design (ADR 0006), the incremental risk is third-party content in a PR causing a public key leak.
- **maintainer** (CONFIRMED, medium, small): The installed SDK turns the options into `--tools Read,Grep,Glob --allowedTools Read,Grep,Glob` and passes os.environ (with ANTHROPIC_API_KEY) to the CLI (subprocess_cli.py:598-608, 819). Claude Code's permissions doc: a bare `Read` rule 'Matches all file reads'; reads need no approval only 'within the working directory and additional directories'; dontAsk 'Auto-denies every call that would otherwise prompt; ... as do tools pre-approved via ... permissions.allow rules' still run. So reads outside cwd=src/ (e.g. /proc/self/environ) are pre-approved, and render_markdown posts summary/detail/suggestion unredacted to the public sticky comment. Exploitation still needs an injection the model obeys, which I could not test; ADR 0006 already accepts that collaborators' code sees the key, so the new exposure is third-party text in a PR reaching a public comment. Medium, cheap to fence (Read(./**) rules or blockReadsOutsideWorkingDirectories, redact() on the rendered Markdown).
- **impact** (CONFIRMED, low, small): The installed SDK turns the options into `--tools Read,Grep,Glob --allowedTools Read,Grep,Glob --permission-mode dontAsk`, and the CLI inherits os.environ, ANTHROPIC_API_KEY included. Claude Code's permissions docs say a bare `Read` rule 'Matches all file reads', reads skip approval only inside the working directories, and dontAsk still runs tools pre-approved by allow rules, so reads outside cwd=src/ (e.g. /proc/self/environ) are pre-approved; render_markdown then posts summary, detail and suggestion verbatim to the public sticky comment, and redact() runs only on audit records. Both halves of the title hold, but exploitation is a long chain: forks get no key, so injected text has to arrive inside a collaborator's own PR or repository files (and the collaborator could leak the key directly anyway), beat the prompt's data-not-instructions guard, and make the model read environ and copy the key out; a verbatim Anthropic key in a public comment would likely be caught by GitHub secret scanning. I couldn't run the CLI to confirm a /proc read, so low reflects likelihood; the fix (path-scoped allow rules, a //proc deny, redact() on the rendered Markdown) is cheap and worth doing.

</details>

### F012

**Cache keys ignore llm-gate's request code and engine settings, so llm-eval scores engine changes from main's cached reviews**

- **Status:** 🟡 partial — #68: moot for llm-review, which no longer caches reviews; llm-eval's own cache still ignores engine settings
- **Severity:** medium (reviewers: medium) · **outcome:** confirmed · **fix cost:** small
- **Where:** `tools/llm-gate/src/llm_gate/cache.py:15` · **area:** llm-gate and review prompts
- **Reported by:** `cr-gate-07` (medium, high confidence)

cache_key covers [CACHE_VERSION, check, engine name, model, prompt body, diff]. Code and config outside the key also shape the request the model gets: prompts.render, diff_block and DIFF_REFERENCE, agent_prompt, READ_ONLY_TOOLS and the other ClaudeAgentOptions, the Review schema's field descriptions (sent as the output schema), MAX_TOKENS, and checks.yaml's max_turns and budget_usd. llm-eval restores main's warm cache (llm-eval.yml restore-keys llm-eval-main-), and run_eval salts keys by case and repeat only. A PR that changes any of these but no prompt therefore gets 100% cache hits and exactly the baseline's scores. ADR 0006 says a PR 'pays only for the checks whose prompt or code it changes', but a code change doesn't change the key; only a manual CACHE_VERSION bump does. The same keys also let llm-review keep reusing a PR's earlier reviews after a merged change to request code.

*Failure scenario:* A PR sets code-review's `max_turns: 2` in checks.yaml (or changes READ_ONLY_TOOLS to [], or breaks diff_block's escaping). llm-eval reports every case as cached with recall 1.00 and verdict accuracy 1.00, and passes. After the merge, agent reviews hit error_max_turns and fail closed on every PR (or lose file access).

*Suggested fix:* Add a fingerprint of the request-building code and engine settings to the key: a hash of engines/*.py, prompts.py and the Review JSON schema, plus the check's max_turns, budget and engine options. Alternatively, disable cache restore in llm-eval for PRs that change those files.

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, medium, small): cache_key covers only [CACHE_VERSION, check+salt, engine name, model, prompt body, diff text]. Request-building code, the Review schema, MAX_TOKENS, tools, and checks.yaml's max_turns and budget_usd are outside it. run_eval keys by case and repeat only. llm-eval.yml restores llm-eval-main-, so a PR that changes only code or config gets cache hits and the baseline's scores. The only guard is a manual CACHE_VERSION bump (cache.py comment), and ADR 0006's 'pays only for the checks whose prompt or code it changes' overstates the key.
- **maintainer** (CONFIRMED, medium, small): cache_key covers only [CACHE_VERSION, check+salt, engine name, model, prompt, diff]; max_turns, budget_usd, the tool list, the Review schema, diff_block and MAX_TOKENS are outside it, and llm-eval restores main's warm cache (restore-key llm-eval-main-). A PR that changes only such code or config gets cache hits on every case and exactly the baseline's scores. ADR 0006 says a PR pays for 'the checks whose prompt or code it changes'; the code half only holds after a manual CACHE_VERSION bump, which is documented only in a code comment.
- **impact** (CONFIRMED, medium, small): cache_key is [CACHE_VERSION, check (+ eval salt), engine name, model, prompt, diff]: engine code, the Review schema sent as the output format, MAX_TOKENS, max_turns/budget_usd and the SDK version are not in it, llm-eval restores main's warm cache (restore-keys llm-eval-main-), and run_eval salts only by case and repeat. So a PR that changes engine code or checks.yaml engine settings, or bumps claude-agent-sdk in uv.lock, gets all cache hits and exactly the baseline's scores; ADR 0006's 'pays only for the checks whose prompt or code it changes' is not what happens. This is the boring kind that will bite on the next SDK upgrade, and a merged change that makes every agent review error would fail every PR closed (errors aren't overridable). Medium.

</details>

### F004

**The collector's triage recomputation (_triage_expected) has no test at all**

- **Status:** ✅ fixed — #68: six tests drive the real collect CLI, with the plans read from checks.yaml so they can't drift
- **Severity:** medium (reviewers: high) · **outcome:** confirmed · **fix cost:** small
- **Where:** `tools/llm-gate/src/llm_gate/cli.py:594` · **area:** llm-gate and review prompts
- **Reported by:** `tr-01` (high, high confidence)

_triage_expected builds the TriageExpected that audit-collect.yml checks every run's triage against (ADR 0008 decision 6): the floor from the compare API files, the AI flag from commits/body/branch, manual_required (the latest /llm-risk written before run_started_at) versus manual_allowed (that one plus the latest), and the per-level plans from the default branch's checks.yaml. Branch coverage shows cli.py 599-625 never executed, and no test passes --triage-inputs. The collector tests in test_triage.py hand-build expected(), so they never exercise this builder. On a scratch copy, two mutations survived all 306 tests: (a) manual_required taken from the latest override instead of the one before the run started; (b) the function always returning None. With (b), _triage_problems returns [] and _risk_problems falls back to the artifact's own checks_plan, so the floor, AI flag and plans are no longer recomputed. ADR 0005 says the collector's validation has its own tests; this part has none. It is defence in depth behind workflow_modified, but it runs on every collection.

*Failure scenario:* A refactor makes _triage_expected return None, or swaps required/latest. All tests pass. In production either no run's triage is checked any more, or every run that started before a later /llm-risk is written as tamper_suspected. Those are permanent false alarms, and the release attestation then lists those PRs as unverified.

*Suggested fix:* CLI tests of `audit collect --triage-inputs` with a temporary checks.yaml and an audit-log dir holding risk_override records from before and after run_started_at. Add a case with compare_files null, and assert the outcome (written or tamper_suspected) each time. Or unit-test _triage_expected directly with an argparse.Namespace.

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, medium, small): No test passes --triage-inputs or calls _triage_expected (grep of tests). I ran both mutants against the full suite through an import-hook plugin, without touching the repo: _triage_expected always returning None survived (306 passed), and manual_required taken from the latest override survived (306 passed); a control mutant in the same module was killed, so the harness applies cli mutations. Calibrated to medium: it's a test gap, but mutant (b) would silently turn off the collector's triage recomputation (ADR 0008 decision 6).
- **maintainer** (CONFIRMED, medium, small): No test passes --triage-inputs or calls _triage_expected; the collector tests hand-build TriageExpected. In a scratch clone both mutations survived all 306 tests: _triage_expected always returning None, and manual_required computed without `before=started`. ADR 0005 says the collector's validation has its own tests, and this builder decides every run's triage check. It is a test gap, not wrong behaviour today, hence medium rather than high.
- **impact** (CONFIRMED, low, small): Branch coverage of the suite (pytest-cov) shows cli.py 599-625 never executed, no test passes --triage-inputs, and test_triage.py hand-builds TriageExpected, so both described mutations survive. The impact is smaller than reported: the recomputation adds value only when a run's triage artifact can lie, which needs a modified workflow (already flagged workflow_modified) or an exotic route, and its likely regressions are either silent loss of a mostly redundant check (return None) or loud false tamper events. A real test gap on the collector, but low.

</details>

### F005

**Triage and the collector accept any risk_override record on audit-log, so a hand-pushed record can lower the risk with a forged author and an unbeatable timestamp**

- **Status:** ✅ fixed — #65: tolerant parsing, future timestamps ignored, and the collector verifies each record against its comment
- **Severity:** medium (reviewers: medium) · **outcome:** confirmed · **fix cost:** medium
- **Where:** `tools/llm-gate/src/llm_gate/triage.py:286` · **area:** llm-gate and review prompts
- **Reported by:** `cr-gate-04` (medium, high confidence), `wr-04` (medium, high confidence), `sec-09` (low, medium confidence)
- **Reviewer's accepted_in:** ADR 0005 (collaborators adding commits to audit-log is accepted; using those records as trusted triage input is not addressed there or in ADR 0008); ADR 0005 (anyone with contents: write can add commits to audit-log); the consequence for triage and the release attestation isn't covered; docs/adr/0005-audit-trail.md

**`cr-gate-04`: Triage and the collector accept any risk_override record on audit-log, so a hand-pushed record can lower the risk with a forged author and an unbeatable timestamp**

latest_risk_override reads every events/**/*.jsonl line as raw JSON and takes the risk_override for the PR with the greatest self-declared `ts`. It doesn't check who wrote the record, whether a matching /llm-risk comment exists, or the schema. The audit-log ruleset blocks only deletion and force pushes (ADR 0005), so any writer can push a record, and so can any PR-triggered workflow other than llm-review.yml that asks for contents: write (such a change isn't flagged as workflow_modified). I verified this with a scratch log: a record {to: low, by: gergodrazsdik, ts: 2099-01-01} wins over a later genuine /llm-risk high. The collector's own check (cli._triage_expected) then computes manual_allowed = {high, low}, so a triage record with source manual and final_risk low passes audit._triage_problems (audit.py:735). At low risk code-review is advisory and security-review doesn't run. Separately, a single non-object JSON line such as '[]' makes latest_risk_override raise AttributeError, because only ValueError is caught. That crashes the triage job of every PR, so their llm / <check> checks never report, and it crashes the collector too. feedback.find_finding, feedback.current_risk and metrics.load_records have the same unguarded record.get.

*Failure scenario:* A collaborator, or an agent with push rights, commits events/2026/10/17/feedback-1.jsonl to audit-log containing {type: risk_override, pr: 61, to: low, by: <owner>, reason: x, ts: 2099-01-01T00:00:00Z}, then pushes a bug to PR #61. Triage rates the PR low (source manual, attributed to the owner), and the owner's later '/llm-risk high' can never win. The collector accepts the run, and the attestation lists risk low with code-review pass.

*Suggested fix:* Derive manual risks the way find_override derives overrides: from the PR's own unedited /llm-risk comments (role write or higher, GitHub's timestamps). At minimum, accept only feedback-<comment_id>.jsonl records whose comment exists and matches. Ignore records whose ts is after the run start, parse lines with the audit schema, and skip non-objects.

**`wr-04`: risk_override and gate_run records are trusted by their content, but anyone with contents: write, including a PR's own workflow, can append them to audit-log**

Triage (llm-review.yml:89-91, then latest_risk_override) and the collector (_triage_expected) treat any `type: risk_override` line under events/** as a genuine /llm-risk. Neither checks the comment the record claims to come from. The latest record by `ts` wins, so a record with a far-future ts beats every real one. attestations.llm_review likewise takes the gate_run with the highest (workflow_run_id, run_attempt) for each PR and head. An appended record with a larger run id therefore replaces the real verdict and drops workflow_modified. The audit-log ruleset blocks only deletion and force pushes. ADR 0005 accepts that writers and "any workflow with contents: write" can add commits, and says the collector's own commits stand out because they are made by github-actions[bot] and signed by GitHub. But a same-repo PR's modified workflow can request contents: write, and its contents-API commits are also signed by GitHub and made by github-actions[bot]: they can't be told apart from the collector's. WRITEUP §4 says the risk can only be lowered "visibly", but a record written directly leaves no PR comment.

*Failure scenario:* A PR's first push edits a workflow to PUT events/2026/10/18/feedback-1.jsonl containing {type: risk_override, pr: N, to: low, ts: 2099-01-01T00:00:00Z}. The next push reverts the workflow. Triage reads source manual and risk low, so code-review and security-review become advisory. The collector's manual_allowed contains low, so nothing is flagged, and the release attestation shows risk low with passing checks.

*Suggested fix:* Verify each risk_override (and feedback) record against the PR comment it names. The path carries the comment id (feedback-<id>.jsonl): fetch the comment, check its author's role, its first line and that it is unedited. Ignore records with a ts in the future. Alternatively, have the trusted workflows sign their records with a key held as a secret of an environment restricted to main, and check the signature in triage, the collector and attest.

**`sec-09`: The audit-log ruleset blocks deletion and force pushes but not additions, so any `contents: write` workflow can append records**

The ruleset has only `deletion` and `non_fast_forward` and no bypass actors, so history can only grow - but it can grow from anywhere: a PR-added workflow can declare `permissions: contents: write` and PUT a record file to the branch through the contents API, exactly as `audit-collect.yml` and `llm-feedback.yml` do. Forged records would carry `github-actions[bot]` as the committer and a GitHub signature, so they are hard to tell apart from genuine ones except by their run context. ADR 0005 states this ("Anyone with write access, and any workflow with `contents: write`, can still *add* commits to `audit-log` ... Restricting updates to the GitHub Actions app needs an organization"). Note that `triage.latest_risk_override` and `feedback.find_finding` read this branch as the trusted source, so an injected `risk_override` record would lower a later run's risk.

*Failure scenario:* A PR adds a workflow with `contents: write` that writes `events/YYYY/MM/DD/feedback-1.jsonl` containing `{"type":"risk_override","pr":N,"to":"low",...}`; the next triage run reads it, `final_risk` returns `manual` = low, and both blocking checks report `not_needed`. The collector's `manual_allowed` check accepts it because the record really is in the log.

*Suggested fix:* Keep as accepted for a personal repository, but consider having the collector and triage accept only records whose commit was made by the collector's own workflow (compare the commit author/committer and the run id in the record against the branch history) instead of trusting any file on the branch.

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, medium, small): Reproduced with the real module. A risk_override {to: low, ts: 2099} wins over a later genuine /llm-risk high in triage, because cmd_triage calls latest_risk_override without `before`. The collector computes manual_required = high and manual_allowed = {high, low}, so a manual low triage record passes _triage_problems. No check ties a record to a /llm-risk comment, author or schema. A single `[]` line raises AttributeError from triage.latest_risk_override, feedback.find_finding, feedback.current_risk and metrics.compute, since only ValueError is caught, so one junk line breaks triage for every PR and the collector. ADR 0005 accepts that writers and any contents:write workflow can add commits; it doesn't accept those records being trusted as triage input or crashing it, so this is not ACCEPTED. Minor inaccuracy in sec-09: at low, code-review runs as advisory; it isn't not_needed.
- **maintainer** (CONFIRMED, medium, medium): Reproduced with a scratch log: a hand-written risk_override {to: low, ts: 2099-01-01} beats a genuine later /llm-risk high in latest_risk_override as triage calls it (no `before`), and the collector's manual_allowed then contains low, so a manual-low triage record passes. A single '[]' line makes latest_risk_override, feedback.find_finding and feedback.current_risk raise AttributeError (only ValueError is caught), which none of triage, the collector or llm-feedback catch. ADR 0005 accepts that writers and contents:write workflows can add commits, but ADR 0008 relies on 'llm-feedback.yml writes these records only after checking the commenter's role', which the branch doesn't enforce; using unauthenticated records, ordered by a self-declared ts, as triage input is not an accepted consequence.
- **impact** (CONFIRMED, medium, medium): Reproduced with a scratch log: a hand-written risk_override with ts 2099 wins in latest_risk_override over a later genuine /llm-risk, and the collector's manual_allowed = {required, latest} accepts a manual-low triage. A `[]` line makes latest_risk_override, feedback.find_finding and feedback.current_risk raise AttributeError (metrics.load_records passes it through and metrics.compute then crashes), and a naive ts mixed with aware ones raises TypeError: one bad line on audit-log fails every PR's triage job, so no llm / <check> reports, until someone commits a fix. Trigger is anyone with contents: write on audit-log (a collaborator, or any same-repo PR workflow that requests it, whose commits look like the collector's); such a person can lower the risk openly with /llm-risk anyway, so the marginal harm is a forged author, a future ts no real command can beat, no PR comment trail, and the DoS. ADR 0005 accepts that writers can add commits, but ADR 0008's argument that only llm-feedback writes risk_override doesn't accept this consequence, so not ACCEPTED (sec-09's accepted_in is too broad; its facts are right).

</details>

### F006

**Re-running only the failed llm jobs turns their records into tamper_suspected, because the new attempt has no triage artifact**

- **Status:** ✅ fixed — #65: the collector reuses the earlier attempt's triage record (`reused_from_attempt`)
- **Severity:** medium (reviewers: medium) · **outcome:** confirmed · **fix cost:** small
- **Where:** `tools/llm-gate/src/llm_gate/audit.py:757` · **area:** llm-gate and review prompts
- **Reported by:** `api-04` (medium, medium confidence), `wr-01` (medium, high confidence)

**`api-04`: Re-running only the failed llm jobs turns their records into tamper_suspected, because the new attempt has no triage artifact**

Artifacts are named per attempt: `audit-<run>-<attempt>-<check>`, and `audit-<run>-<attempt>-triage` for triage (llm-review.yml:142 and 339). The collector downloads only the current attempt's (`audit-$RUN_ID-$RUN_ATTEMPT-*`). 'Re-run failed jobs' (or re-running one job) doesn't re-run the triage job that succeeded. The re-run llm job reuses `needs.triage.outputs.risk` and writes a gate_run with `risk` set, but the new attempt has no triage artifact. `collect()` keeps `run_triage = "absent"`, and `_risk_problems` returns 'risk is set, but the run has no triage record' (audit.py:754-757), so the record is replaced by a tamper_suspected event. I reproduced this by calling `audit.collect` with a single valid `audit-100-2-code-review` artifact (risk high, verdict pass, job success). The output was `tamper_suspected ['risk is set, but the run has no triage record']`. The workflow expects this kind of re-run: 'failed checks are the ones re-run' (llm-review.yml:270-272). Blocking checks fail closed on API errors, and the remedy for those is a re-run. The tests cover 'risk without triage' only within a single attempt (test_triage.py around line 498). Full re-runs are fine because they re-run triage: llm-feedback's `POST .../rerun`, and PR #47's attempt 2 in the log.

*Failure scenario:* On attempt 1, code-review ends in an API error (verdict error, exit 2). The author clicks 'Re-run failed jobs' and attempt 2 passes. The collector writes tamper_suspected instead of the pass. The latest code-review gate_run for that head is then the error. At the next release, the llm-review attestation lists the PR as unreviewed ('code-review: error') and unverified ('tamper_suspected (1)').

*Suggested fix:* In the collector, take the run's triage record from the latest attempt that has one: download `audit-<run>-*-triage`, use the highest attempt up to the current one, and check the attempt's gate_runs against it. Add a test with two attempts.

**`wr-01`: "Re-run failed jobs" on a triaged llm-review run turns the re-run's valid records into tamper_suspected**

GitHub's "Re-run failed jobs" and "Re-run this job" start attempt N+1 only for the failed jobs and their dependents. The successful `triage` job is not re-run: its outputs (risk, gate_sha) are reused, and its artifact keeps the name audit-<run>-<N>-triage. audit-collect.yml downloads only `audit-$RUN_ID-$RUN_ATTEMPT-*` (line 73), and collect() rejects any artifact whose attempt isn't the current one, so run_triage stays "absent". _risk_problems then rejects every gate_run that carries a risk ("risk is set, but the run has no triage record", audit.py:757; the behaviour is pinned by test_runs_without_triage_are_accepted_but_may_not_claim_a_risk). Every triaged run has a risk, so every partial re-run is written as tamper_suspected. attestations.llm_review then picks the attempt-N gate_run as the latest record for that check (e.g. `error`), and lists the PR under both unreviewed and unverified ("tamper_suspected (1)"). llm-feedback uses a full rerun (POST /runs/{id}/rerun), so /llm-override and /llm-risk are not affected. The UI's re-run-failed-jobs path is, and it is the natural fix after a blocking check fails closed on an API error. The local audit-log snapshot shows only full re-runs so far (PR 43 and PR 47, attempt 2), so this hasn't happened yet.

*Failure scenario:* A PR is triaged medium. llm / code-review fails closed on an API overload (exit 2). The author clicks "Re-run failed jobs", and attempt 2 passes. audit-collect for attempt 2 sees only audit-<run>-2-code-review and writes a tamper_suspected record for it. The next release attestation reports code-review: error (from attempt 1) and lists the PR as unreviewed and unverified, although the merged head passed.

*Suggested fix:* When an attempt has no triage artifact and its job list has no triage job, validate and use the latest earlier attempt's audit-<run>-<k>-triage (k < N, whose triage job concluded success). Alternatively, have each llm job re-upload the triage record it consumed under its own attempt. Add a collector test for a partial re-run.

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, medium, small): Reproduced with audit.collect: a valid attempt-2 code-review artifact (risk high, verdict pass, job success) without a triage artifact in the same attempt is written as tamper_suspected ['risk is set, but the run has no triage record'], with or without a triage job in the jobs map. The collector downloads only audit-<run>-<attempt>-*, and 'Re-run failed jobs' doesn't re-run the successful upstream triage job, so the attempt never has one. attestations.llm_review then counts the tamper event for that PR and head (unverified), and the latest gate_run is attempt 1's error (unreviewed). ADR 0008 accepts flagging a risk without triage only for pre-triage workflows, not this case.
- **maintainer** (CONFIRMED, medium, small): Reproduced: audit.collect with one valid audit-100-2-code-review artifact (attempt 2, risk high, pass, job success) writes tamper_suspected 'risk is set, but the run has no triage record'. A partial re-run doesn't re-run the successful triage job (its outputs are reused), and audit-collect downloads only audit-<run>-<attempt>-*. ADR 0005 named artifacts per attempt precisely for 're-run of failed jobs', and llm-review.yml's cache comment expects failed checks to be re-run; ADR 0008's 'a record that claims a risk without a triage record is flagged' was written for pre-triage workflows and didn't consider this. A fix must take both the triage artifact and the triage job's conclusion from the earlier attempt.
- **impact** (CONFIRMED, medium, small): Reproduced: audit.collect for attempt 2 with only audit-100-2-code-review (risk medium, pass, job success) writes tamper_suspected ['risk is set, but the run has no triage record'], whether or not the jobs list has triage, because the collector downloads only audit-<run>-<attempt>-* and run_triage stays 'absent'. attestations.llm_review then takes the latest gate_run per check (attempt 1's error) and counts the tamper event, so the PR is listed as both unreviewed and unverified although its head passed. The trigger is the default 'Re-run failed jobs' button after a blocking check fails closed on an API error, the natural remedy, so this will happen; llm-feedback's full re-run is unaffected. Wrong permanent records and integrity-metric noise, not a bypass: medium.

</details>

### F008

**llm-eval checks only flips and fp-regressions when the run's engine/model has no baseline entry, so changing a check's model skips the regression gate**

- **Status:** ✅ fixed — #72: a missing baseline entry fails the comparison instead of skipping it
- **Severity:** medium (reviewers: medium) · **outcome:** confirmed · **fix cost:** small
- **Where:** `tools/llm-gate/src/llm_gate/evals.py:624` · **area:** llm-gate and review prompts
- **Reported by:** `cr-gate-06` (medium, high confidence), `tr-09` (medium, high confidence)

**`cr-gate-06`: llm-eval checks only flips and fp-regressions when the run's engine/model has no baseline entry, so changing a check's model skips the regression gate**

compare() looks up baseline[check][f'{engine}/{model}']. When there is no entry, old = {}: every delta row (recall, false_block_rate, verdict_accuracy) has baseline None and is ok=True, and the cost row is ok because before_cost is falsy. Only flip_rate and fp_regressions can fail. The run's model is the check's configured model after ${LLM_MODEL...} expansion. So a PR that changes a check's model or engine in checks.yaml leaves its runs without a baseline, and so does a change to the repository variables LLM_MODEL or LLM_MODEL_CHEAP, which llm-eval.yml passes in. baseline.json currently has only api and agent with claude-sonnet-5-5, plus triage on api/claude-haiku-5-5.

*Failure scenario:* A PR moves security-review to `model: ${LLM_MODEL_CHEAP:-claude-haiku-5-5}` to save cost and also trims its prompt (drill 14's 'only report critical issues'). llm-eval runs security-review as api/claude-haiku-5-5 and recall falls to 0.17, but the comparison table shows '-' for every baseline value and every row ok, so the required llm-eval check passes.

*Suggested fix:* When a check that blocks at any risk level has no baseline for the run's engine and model, fail and ask for `just eval-baseline` in the PR, or compare against the check's previously configured entry.

**`tr-09`: llm-eval passes any run whose engine/model has no baseline entry, even with recall 0**

compare() looks up the baseline entry for the check and the engine/model. Without one, every delta row (recall, false blocks, verdict accuracy) is ok, and only flip rate and fp_regressions can fail; cost is ok too without a baseline. test_without_a_baseline_only_absolute_limits_apply pins this behaviour. Checked with the real module against the committed baseline.json: a code-review run with recall 0 and verdict accuracy 0 fails under agent/claude-sonnet-5-5 and passes under agent/claude-sonnet-5-6. Such a key appears whenever a PR changes a model in checks.yaml, or when the LLM_MODEL/LLM_MODEL_CHEAP repository variables change, since llm-eval.yml passes them in. docs-drift and test-review have no baseline at all.

*Failure scenario:* A PR changes defaults.model to a weaker model, or someone changes the repository variable. llm-eval runs every case under the new key, finds nothing, and passes because nothing is compared.

*Suggested fix:* With --compare, fail (or require an explicit acknowledgement) when a check that has cases lacks a baseline entry for the evaluated engine/model. Or add absolute floors for recall and verdict accuracy in thresholds.yaml that apply without a baseline.

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, medium, small): compare() looks up baseline[check][engine/model]. Without an entry, delta_row marks recall, false_block_rate and verdict_accuracy (or risk_accuracy) ok, and cost is ok because before_cost is falsy, so only flip_rate and fp_regressions can fail. test_without_a_baseline_only_absolute_limits_apply pins this. baseline.json holds only sonnet entries for the review checks and api/claude-haiku-5-5 for triage, so a checks.yaml model or engine change, or the LLM_MODEL / LLM_MODEL_CHEAP variables llm-eval.yml passes in, evaluates under a key with no baseline and passes with any recall. No ADR covers the missing-entry case.
- **maintainer** (CONFIRMED, medium, small): compare() looks up baseline[check][engine/model]; without an entry every delta row is ok and the cost row is ok (falsy baseline), so only flip_rate and fp_regressions can fail. The no-entry behaviour is deliberate (docstring, test_without_a_baseline_only_absolute_limits_apply) for bootstrapping, but ADR 0006 doesn't record the consequence that a PR changing a check's model or engine in checks.yaml (or a change to LLM_MODEL/LLM_MODEL_CHEAP) is scored against nothing. baseline.json has no entry at all for test-review and docs-drift.
- **impact** (CONFIRMED, medium, small): compare() looks up baseline[check][engine/model]; without an entry every delta row is ok, cost is ok (before_cost falsy), and only flip_rate and fp_regressions can fail, as its docstring and test_without_a_baseline_only_absolute_limits_apply pin. llm-eval runs the PR's checks.yaml with the repository's LLM_MODEL variables, so a PR that changes a check's model or engine (a plausible cost-cutting edit, possibly with a prompt trim like drill 14) gets a vacuous comparison and passes the required check; the table shows '-' baselines, which only a careful reader notices. No ADR records this fail-open; ADR 0006 says the gate fails on regression against the baseline. Medium.

</details>

### F010

**Name-based EXCLUDES drop compiled C# from the review, and a PR made only of excluded files passes as 'not applicable'**

- **Status:** ✅ fixed — #72: generated C# is reviewed; only lock files and this repo's test data are excluded
- **Severity:** medium (reviewers: medium) · **outcome:** confirmed · **fix cost:** small
- **Where:** `tools/llm-gate/src/llm_gate/diff.py:9` · **area:** llm-gate and review prompts
- **Reported by:** `cr-gate-03` (medium, high confidence)

EXCLUDES removes **/*.g.cs, **/*.generated.cs, **/*.Designer.cs, **/*.lock and **/packages.lock.json from both the diff text and diff.files. The API project is SDK-style with default compile items and no Compile Remove (src/CalendarGates.Api/CalendarGates.Api.csproj), so any *.g.cs file is compiled and shipped. The repository has no generated files with those names (git ls-files). If a PR's only changes are excluded files, diff.files is empty and run_check returns not_applicable ('no changes against <base>', runner.py:65), which decide() passes for blocking checks. Downstream, every consumer accepts that as a review: the collector's _risk_problems treats not_applicable as 'ran', attestations count it as reviewed (NOT_REVIEWED = skipped_no_key, error), and metrics coverage counts it as decided. A rename of Foo.cs to Foo.g.cs shows only as a deletion. Triage still rates the path by its rule (src/** medium) but leaves the file out of its size count.

*Failure scenario:* A PR adds src/CalendarGates.Api/Endpoints/HolidaysEndpoints.g.cs with a new endpoint that logs request headers. code-review and security-review report 'not applicable: no changes against origin/main' with exit 0, and the required checks go green. The attestation shows not_applicable for both and lists no gap. The same applies to a change confined to uv.lock or packages.lock.json.

*Suggested fix:* Don't exclude compiled sources by name; exclude only files carrying an <auto-generated> header, checked from the base side. When triage saw changed files but the review diff is empty, run blocking checks on the file list or fail closed instead of returning not_applicable.

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, medium, small): EXCLUDES drops *.g.cs, *.generated.cs, *.Designer.cs and the lock files from both the diff text and diff.files. The API csproj is SDK-style with no Compile Remove, so a src/**/*.g.cs file is compiled; git ls-files shows no such files today. An empty diff.files gives not_applicable (runner.py:64-65), which decide() passes for blocking checks. The collector treats it as having run, and the attestation's NOT_REVIEWED set doesn't include it. Triage's numstat doesn't apply the excludes, so the floor still rates the path. The realistic routes are deliberate (naming source *.g.cs) or rare (lock-only changes), hence medium.
- **maintainer** (CONFIRMED, medium, small): EXCLUDES drops **/*.g.cs, *.generated.cs, *.Designer.cs and lock files from diff text and diff.files; the SDK-style csproj compiles *.g.cs; with only excluded files run_check returns not_applicable ('no changes against base'), decide passes blocking checks, and attestations count not_applicable as reviewed. The exclusion of real generated code and lock-file noise is deliberate, but name-based exclusion lets the PR choose what the gate doesn't see, against ADR 0004's 'a PR can't weaken the gate that reviews it'. Needs a deliberate rename (same threat class as F001, narrower), hence medium.
- **impact** (CONFIRMED, low, trivial): EXCLUDES drops **/*.g.cs, *.generated.cs and *.Designer.cs from both the text and --name-only, the SDK-style csproj compiles them, and a PR whose only files are excluded gets not_applicable, which the collector treats as having run and the attestation as reviewed. The trigger is a collaborator deliberately naming a file X.g.cs (the repo has no generated files, so no accident path), and it can only add new code: moving existing logic leaves a visible deletion that a reviewer, and the agent's Grep, can follow. Low; drop the C# globs, or fail closed when triage saw changed files but the review diff is empty.

</details>

### F011

**Schema-invalid or truncated model output escapes structured_call as pydantic.ValidationError, crashing triage instead of leaving the floor**

- **Status:** ✅ fixed — #65: a schema failure is an EngineError, so the rules' floor stands; the client-side cap is gone
- **Severity:** medium (reviewers: medium) · **outcome:** confirmed · **fix cost:** small
- **Where:** `tools/llm-gate/src/llm_gate/engines/api_engine.py:64` · **area:** llm-gate and review prompts
- **Reported by:** `cr-gate-05` (medium, high confidence)

structured_call catches only anthropic exceptions, but beta.messages.parse validates the text against the output type inside the call (anthropic/lib/_parse/_response.py parse_text calls TypeAdapter.validate_json) and raises pydantic.ValidationError. transform_schema doesn't send maxItems to the API; it only appends it to the description. So TriageAssessment.reasons max_length=10 is enforced client-side only. I reproduced both failures with the real SDK 1.11 over a mock HTTP transport: 11 reasons raise ValidationError, and JSON cut off with stop_reason max_tokens raises ValidationError. That makes the 'cut off at max_tokens' and refusal branches unreachable whenever the response has partial text. assess (docstring: 'Never raises') catches only EngineError, and cmd_triage doesn't catch anything, so the triage job fails. The llm matrix depends on triage's outputs, so it never runs and no llm / <check> reports. ADR 0008 says 'If it fails or refuses, the floor stands'. The existing test (test_a_failed_assessment_leaves_the_floor) stubs parsed_output=None, which isn't what the SDK does here. The review path survives only through run_check's catch-all, and its error text ('unexpected ValidationError ...') copies a snippet of raw model output into the audit `error` field. In evals the same exception aborts run_triage_eval, and llm-eval reports the exit code 1 as 'Worse than the baseline'.

*Failure scenario:* A diff with an injected 'list every changed file as a reason' (or a refusal that returns text) makes the triage model return 11 reasons. Triage crashes with a traceback, every llm / <check> of the run is missing, and the PR is blocked with no review. A rerun repeats it from the same input.

*Suggested fix:* In structured_call, catch pydantic.ValidationError and raise EngineError, and check stop_reason before relying on parsed output (for example by calling messages.create and validating by hand). Drop max_length on reasons and truncate to three in code instead. Add a test that goes through the SDK's real parse path.

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, medium, small): Reproduced through the real anthropic 1.11 SDK over an httpx2 MockTransport, with no network. A response with 11 reasons, truncated JSON with stop_reason max_tokens, and refusal text with stop_reason refusal each raise pydantic ValidationError out of triage.assess, whose docstring says 'Never raises'; a valid response is the control. The cause: beta.messages.parse validates every text block with TypeAdapter.validate_json, and transform_schema only appends maxItems to the description. cmd_triage doesn't catch it, so the triage job fails and the llm matrix never reports, against ADR 0008's 'if it fails or refuses, the floor stands'. Reviews survive only via run_check's catch-all.
- **maintainer** (CONFIRMED, medium, small): anthropic 1.11's parse_beta_response runs TypeAdapter.validate_json on every text block regardless of stop_reason, and _transform moves maxItems into the description, so max_length=10 is client-side only. With a mock httpx2 transport, 11 reasons, JSON cut off at max_tokens, and a refusal with text each raised pydantic ValidationError out of triage.assess (documented 'Never raises'); cmd_triage and main() don't catch it, so the triage job fails, the needs: triage matrix never runs and no llm / <check> reports. Fails closed, but contradicts ADR 0008's 'If it fails or refuses, the floor stands'; the review path survives only through run_check's catch-all.
- **impact** (CONFIRMED, medium, small): Reproduced with SDK 1.11 over a mock httpx2 transport: beta.messages.parse runs TypeAdapter.validate_json inside the call, so 11 reasons (maxItems is moved into the description, not sent), truncated JSON with stop_reason max_tokens, and an empty text block with stop_reason refusal all raise pydantic ValidationError out of triage.assess, whose docstring says it never raises. cmd_triage and main don't catch it, so the triage job fails and the llm matrix (needs: triage) never runs: every required llm / <check> of the PR is missing. The trigger is the model's own output: rare for the first two, plausible for refusals on security-flavoured diffs, and then possibly persistent with no workaround (/llm-risk doesn't skip the model call). Reviews survive through run_check's catch-all and fail closed. Medium; catching ValidationError in structured_call is trivial, plus a test.

</details>

### F020

**A /llm-risk decision isn't tied to a head: lowering the risk once removes blocking review from every later push to the PR**

- **Status:** ✅ fixed — #69: a lowering applies only to the head it was given for; a raise persists
- **Severity:** medium (reviewers: medium) · **outcome:** confirmed · **fix cost:** small
- **Where:** `tools/llm-gate/src/llm_gate/triage.py:321` · **area:** llm-gate and review prompts
- **Reported by:** `wr-05` (medium, high confidence)
- **Reviewer's accepted_in:** ADR 0008 (people may lower the risk with a recorded reason); carrying the decision over to later heads isn't covered

feedback.handle builds the risk_override from a context with head_sha=None (cli.py:778; the live record for PR 47 has "head_sha": null). latest_risk_override returns the PR's latest record whatever the head, and final_risk lets a manual risk win outright, even below the rules floor. So `/llm-risk low <reason>` given for a docs-only head keeps the PR at low for every later commit, however risky. At low no check blocks (checks.yaml levels.low.blocking: []), and the metrics don't count it in the override rate. ADR 0008 and WRITEUP §4 accept that a collaborator can lower the risk on purpose. Neither discusses the decision carrying over to code pushed later, which here is often an agent's, since most PRs are AI-assisted.

*Failure scenario:* Triage rates a typo-fix PR high because it is AI-assisted. The owner comments `/llm-risk low only a typo`. Later the agent pushes a src/ change with a real bug to the same PR. Triage says manual, low. code-review runs as advisory, its high finding doesn't block, the PR merges, and the collector accepts it.

*Suggested fix:* Record the PR's head SHA in the risk_override. Have triage apply a manual lowering only while the head (or at least the rules floor) is unchanged; a raise may persist. Say "manual risk from an older head ignored" in the triage summary.

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, medium, small): cmd_feedback builds the context with head_sha=None, and the live PR 47 risk_override on audit-log has head_sha null. latest_risk_override returns the PR's latest record whatever the head, and final_risk lets a manual risk win outright, so a /llm-risk low persists for every later push. At low, levels.low.blocking is empty. ADR 0008 and WRITEUP section 4 accept deliberate lowering, but not its carry-over to code pushed later, so this is not ACCEPTED.
- **maintainer** (CONFIRMED, low, small): cmd_feedback builds the context with head_sha=None, latest_risk_override ignores the head, and final_risk lets a manual risk win outright, so a /llm-risk low persists for every later push. ADR 0008/WRITEUP accept a deliberate, visible lowering but don't discuss carry-over to new heads. It matches the PR-scoped semantics of llm-override (the label also persists across pushes) and stays visible on every run (risk:low label, triage summary), so low.
- **impact** (CONFIRMED, medium, small): feedback.handle builds the risk_override from a context with head_sha=None, latest_risk_override takes the PR's latest record regardless of head, and final_risk lets a manual risk win outright, so `/llm-risk low` persists for every later push, and at low nothing blocks. The trigger is a write-role collaborator using the command as designed early in a PR, after which an agent's later src/ push gets advisory-only review without anyone deciding that for the new code; the record is truthful (source manual), so it is a gate lapse, not a forgery. ADR 0008 accepts lowering on purpose, not carrying it over to later heads, so not ACCEPTED. Medium.

</details>

### F042

**`workflow_modified` only looks at llm-review.yml, so other PR changes that steer the review still count as verified**

- **Status:** ✅ fixed — #68: workflow_modified covers .github/workflows/**, .github/actions/** and .gitattributes
- **Severity:** medium (reviewers: medium) · **outcome:** confirmed · **fix cost:** small
- **Where:** `.github/workflows/audit-collect.yml:114` · **area:** workflows, release, deploy, scripts
- **Reported by:** `sec-05` (medium, high confidence), `wr-06` (medium, medium confidence)
- **Reviewer's accepted_in:** ADR 0004 (remaining hole: a PR edits the workflow); the narrower mitigation isn't discussed

**`sec-05`: `workflow_modified` only looks at llm-review.yml, so other PR changes that steer the review still count as verified**

The collector flags a run as unverified only when the PR's changed-file list contains `github.event.workflow_run.path`, i.e. `.github/workflows/llm-review.yml` (lines 113-116), or when the compare API truncated at 300 files. Everything else the review depends on and the PR controls stays "verified": a newly added workflow in the same PR (which runs on the same `pull_request` event and shares the Actions cache scope, see sec-02), `.gitattributes` (sec-01), `.github/actions/**`, and `.github/workflows/llm-eval.yml`. ADR 0005 and WRITEUP §4 present `workflow_modified` as the mitigation for "a PR edits the review workflow", and ADR 0009 builds the release attestation's `unverified` list from it, so the narrow test propagates into the release evidence: a PR that steered its own review in any of these ways is attested as reviewed.

*Failure scenario:* A PR adds `.github/workflows/warm.yml` (or a `.gitattributes` line) rather than editing `llm-review.yml`. `changed.txt` doesn't contain `.github/workflows/llm-review.yml`, so no `--workflow-modified` flag is passed, the records keep their free text and count as verified, and `llm-gate attest llm-review` lists the PR under `prs` with clean verdicts and nothing under `unverified`.

*Suggested fix:* Flag the run when the PR changes any `.github/**` path (triage already rates those high) or at least any `.github/workflows/*.yml`, `.github/actions/**` and `.gitattributes`; the compare file list is already in `$WORK/changed.txt`.

**`wr-06`: workflow_modified covers only llm-review.yml: another workflow can report the required check names unflagged, and a merged head whose blocking check failed isn't flagged**

The collector flags a run only when the compare API's file list contains the triggering workflow's own path. Required contexts are matched by name and app (GitHub Actions, 15368), not by workflow. A PR can add .github/workflows/x.yml with a job named `llm / code-review` (or `llm-eval`, or `gates`) that sleeps past the real job and exits 0. That job satisfies the ruleset, because the latest check run with a name decides its status, while llm-review.yml stays untouched: the real run's records go in as verified, with workflow_modified false. attestations.llm_review shows a failed blocking verdict only as a cell in the table. NOT_REVIEWED is {skipped_no_key, error} (attestations.py:25 and 185), so "merged although llm / code-review failed" lands in neither the unreviewed nor the unverified list. Editing llm-eval.yml (say, to always report "not applicable") or ci.yml isn't flagged anywhere either. This is the hole ADR 0004 accepts, but the mitigation it names is narrower than the hole.

*Failure scenario:* A PR adds .github/workflows/z.yml with a job `name: llm / code-review` that runs `sleep 900; exit 0`. The real llm / code-review fails on a high finding, the fake one finishes later, the required check turns green and the PR merges. audit-log has a verified `fail`, and the release notes show "fail" in the table with empty unverified and unreviewed lists.

*Suggested fix:* Set workflow_modified when the PR changes anything under .github/workflows/ or .github/actions/. In attestations.llm_review, list as unverified any PR whose merged head's latest blocking verdict is fail or error without an honoured override ("merged with a failing blocking check").

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, medium, small): audit-collect.yml:113-114 flags a run only when changed.txt holds github.event.workflow_run.path (llm-review.yml) or the 300-file marker. Other PR-controlled inputs that steer the review stay verified: a root .gitattributes `-diff` line turns files into 'Binary files differ' for diff.py:55 (`git diff --no-ext-diff`, no --text), and the repo's own .gitattributes already uses `-diff` precisely 'to keep it out of llm-gate reviews'; and a new workflow on the same PR ref can save an actions/cache entry under llm-review's computable key or restore-keys prefix (llm-gate-<check>-pr<N>-) holding a fabricated EngineResult, which cache.py accepts as a hit. Neither sets workflow_modified, so attestations.llm_review lists such PRs as clean; ADR 0004/0005 name workflow_modified as the mitigation without this limit, so not ACCEPTED. Partly wrong details: sec-05's `.github/actions/**` vector doesn't apply (llm-review.yml uses no local action), and wr-06's premise that 'the latest same-named check run decides' is undocumented (GitHub's docs only say duplicate job names give ambiguous results and can block merging), though its NOT_REVIEWED observation (attestations.py:25, 185) is correct.
- **maintainer** (CONFIRMED, medium, small): audit-collect.yml:113-117 sets --workflow-modified only when changed.txt contains the triggering workflow's own path (llm-review.yml) or is truncated. ADR 0004/0005/0009 name exactly 'a PR that changed the review workflow itself' as the flagged case, so the cause (PR-controlled workflow files on pull_request) is accepted, but not the consequence that other PR-controlled workflow code goes unflagged: a PR-added workflow shares the PR's cache scope and can save a llm-gate-<check>-prN-* entry that llm-review.yml:273-278 restores (cache.py's key is computable from the base prompt, the PR's diff and the model), and the run is then recorded as verified and attested with clean verdicts. Flagging any .github/workflows/** change is a one-line grep change, consistent with triage already rating .github/** high. wr-06's check-name shadowing depends on GitHub's undocumented handling of duplicate names (the docs only call it ambiguous), but its second point holds: attestations.py:25/185 list only skipped_no_key and error, so a merged head whose latest blocking verdict is fail appears only as a table cell. sec-05 overreaches slightly: llm-review.yml uses no .github/actions, and .gitattributes affects the diff, not the workflow.
- **impact** (CONFIRMED, medium, small): audit-collect.yml:113-116 sets --workflow-modified only when changed.txt contains the triggering workflow's own path (llm-review.yml) or the 300-file truncation marker; a PR that adds a sibling workflow (same pull_request event, same PR cache scope as llm-review's actions/cache keys), edits .github/actions/** or adds .gitattributes is recorded as verified, and attestations.llm_review then lists nothing under unverified. ADR 0004/WRITEUP name only 'a PR edits llm-review.yml', so this narrower-than-claimed mitigation is not the accepted consequence. Trigger needs write access (here the owner or an agent acting with their push rights) and triage still rates any .github/** change high, so medium, not high. wr-06's extra claim that a same-named job in another workflow satisfies the required context is unproven: GitHub's protected-branch docs only say duplicate job names 'can cause ambiguous status check results' and may block merging, not that the latest run wins. Its attestation point holds: NOT_REVIEWED is {skipped_no_key, error}, so a merged head whose latest blocking verdict is fail appears only as a table cell.

</details>

### F043

**A v* tag on any commit, merged or not, mints release attestations, because the 'on main' check runs inside that commit's own release.yml**

- **Status:** ✅ fixed — #67: verify-release requires the tag's commit on main and binds every attestation to it; only admins may create a v* tag
- **Severity:** medium (reviewers: medium) · **outcome:** confirmed · **fix cost:** medium
- **Where:** `.github/rulesets/tags.json:9` · **area:** workflows, release, deploy, scripts
- **Reported by:** `cr-ops-03` (medium, high confidence), `wr-07` (medium, high confidence)

**`cr-ops-03`: A v* tag on any commit, merged or not, mints release attestations, because the 'on main' check runs inside that commit's own release.yml**

The attestor identity is release.yml@refs/tags/v[0-9].* (release.yaml:38, llm-review.yaml:34). verify-release requires the same identity (--signer-workflow .../release.yml, --source-ref refs/tags/vX). A tag push runs release.yml as it is in the tagged commit. The checks that the tag is SemVer, annotated, verified by GitHub and on main are steps of that same file's verify job (release.yml:40-63), so a commit that edits release.yml simply doesn't have them. The release-tags ruleset (tags.json:9-13) blocks deletion, update and non-fast-forward, but not creation. So anyone with write access, or a token or agent acting for them, can push a vX.Y.Z tag on an unmerged branch commit whose release.yml builds and attests whatever it likes. No PR, triage, LLM review or audit record is involved, and the ruleset then keeps the tag forever. ADR 0009 assumes release.yml changes arrive by PR ('A PR that changes release.yml is high risk in triage'). WRITEUP §4 lists the hole of a PR editing llm-review.yml, but not this path, which needs no PR at all.

*Failure scenario:* On a throwaway branch, edit release.yml so it drops verify and scan and builds any Dockerfile, commit, then git tag v9.9.9 and git push origin v9.9.9 -> release.yml@refs/tags/v9.9.9 attests the digest -> Kyverno admits the image in calendar-gates, and just verify-release 9.9.9 passes.

*Suggested fix:* Add a creation rule to release-tags with only the repository admin role as bypass actor. Have verify-release check that the provenance's source commit (buildDefinition.resolvedDependencies gitCommit) is an ancestor of origin/main. Record the remaining risk in WRITEUP §4 and ADR 0010: whoever can create v* tags can mint the release identity.

**`wr-07`: Any v* tag on any commit runs that commit's release.yml, so a writer can mint attestations Kyverno admits, with no approval and no main check**

release-tags blocks deletion, update and non-fast-forward of v* tags, but not their creation, and nothing ties a tag to main. The on-main and signed-tag checks live in release.yml's verify job, and a tag push runs release.yml from the tagged commit. A writer can push a commit to any branch with a modified release.yml (verify removed, `environment: release` dropped, any digest attested) and tag it v9.9.9. That run has id-token: write and gets Fulcio certificates for .../release.yml@refs/tags/v9.9.9. Kyverno's attestors accept exactly that identity (subjectRegExp release.yml@refs/tags/v[0-9].* in deploy/policies/base), and so does `just verify-release` (--signer-workflow release.yml --source-ref refs/tags/vX). The release environment guards no secret, since signing is keyless and GHCR pushes use GITHUB_TOKEN, so dropping it skips approval. Even with the unmodified workflow, attest runs before publish's approval, so a candidate the owner rejects stays fully attested and is admissible by digest. ADR 0009 considers PRs that change release.yml, not a tag on a non-main commit, which needs no PR at all.

*Failure scenario:* A writer, or an agent with their push rights, pushes branch tmp with a release.yml that only builds an image and attests a vuln-scan predicate with zero criticals, then runs `git push origin v9.9.9`. The run attests the image as release.yml@refs/tags/v9.9.9. Kyverno admits it in calendar-gates and verify-release passes, with no approval and no commit on main.

*Suggested fix:* Add a creation rule to release-tags, with only the admin role as bypass actor. Run attest after approval (environment: release on attest), and give the approval teeth, for example by signing with key material held as a release-environment secret. In verify-release, also check that the certificate's source repository digest is an ancestor of origin/main.

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, medium, small): release-tags (tags.json:9-13) has only deletion, update and non_fast_forward rules, so any writer can create a v* tag on any commit; a tag push runs release.yml from the tagged commit, and the SemVer/annotated/signed/on-main checks are steps of that same file's verify job (release.yml:40-63), so an edited release.yml on an unmerged branch simply omits them. Both Kyverno attestors (subjectRegExp ...release\.yml@refs/tags/v[0-9].*) and verify-release (--signer-workflow release.yml --source-ref refs/tags/vX) accept the resulting identity and nothing checks that the source commit is on main. The attest job never used the approval-gated release environment, so dropping it costs nothing. ADR 0009 considers only release.yml changes arriving by PR; this path is recorded nowhere.
- **maintainer** (CONFIRMED, medium, medium): tags.json blocks deletion, update and non-fast-forward but not creation, and release.yml runs from the tagged commit, so the 'annotated, signed, on main' checks (release.yml:40-63) are steps the tagged commit can drop. Kyverno's subjectRegExp (release.yaml:38, llm-review.yaml:34) and verify-release (--signer-workflow release.yml, --source-ref refs/tags/vX) accept exactly the identity such a run gets, and attest needs no approval. ADR 0009 only considers release.yml edits that arrive by PR; a tag on an unmerged branch commit needs no PR and is not mentioned in ADR 0009/0010 or the WRITEUP threat model. In this solo repo the actor is the owner or an agent with their push rights (a plausible accident: tagging a branch to test a modified release.yml), and the ruleset then keeps the tag forever. Note the suggested creation rule with admin bypass would not stop the owner's own agent; the cheap, real mitigation is verify-release checking that the provenance's source commit is an ancestor of origin/main, plus documenting the limit.
- **impact** (CONFIRMED, medium, medium): release.yml runs on push of v*.*.* tags, so the workflow file is the tagged commit's; the SemVer/signed/on-main checks live in that same file's verify job, and release-tags (tags.json) restricts deletion, update and non-fast-forward but not creation. A writer can tag an unmerged branch commit whose release.yml skips verify and the release environment (which guards no secret: signing is keyless OIDC, GHCR uses GITHUB_TOKEN) and mint attestations under release.yml@refs/tags/vX, which both Kyverno's subjectRegExp and verify-release accept. ADR 0009 only considers release.yml edits arriving by PR. Calibrated to medium: it needs deliberate action by someone with push rights (no accidental path: the unmodified verify job rejects off-main tags), the target is a local kind cluster, and the stray tag and Rekor entry stay visible. A creation rule with admin bypass alone doesn't close it in this solo-admin repo, hence a medium fix (tie the signing identity to main, e.g. sign from a default-branch workflow).

</details>

### F044

**/llm-risk and /llm-override posted while llm-review is running get a +1 reaction but may never take effect**

- **Status:** ✅ fixed — #65: the feedback workflow waits for a run in flight, then re-runs it; proven on #68 ("re-ran llm-review run 39127461371 after 30s")
- **Severity:** medium (reviewers: medium) · **outcome:** confirmed · **fix cost:** small
- **Where:** `.github/workflows/llm-feedback.yml:158` · **area:** workflows, release, deploy, scripts
- **Reported by:** `api-16` (low, medium confidence), `wr-02` (medium, high confidence)

**`api-16`: /llm-override and /llm-risk posted while llm-review is still running are recorded and acknowledged, but never applied**

The re-run step re-runs the PR's latest llm-review run only if it has completed. Otherwise it prints 'llm-review is still running; it reads the label itself.' and exits. But each llm job reads the labels early, in its 'Override reason' step, and triage reads `/llm-risk` from audit-log when the run starts. Jobs past those steps keep the old result, and so do jobs that have already finished, such as a failed code-review while security-review is still running on the agent engine. The label is added with GITHUB_TOKEN, so it starts no new run. The commenter still gets a thumbs-up. docs/gates.md (lines 26, 99 and 101-102) promises that the command adds the label and re-runs the review, or 're-runs triage with that risk'.

*Failure scenario:* code-review fails and posts its sticky comment while security-review is still running. The author comments `/llm-override false alarm`. The feedback run sees the llm-review run in_progress and skips the re-run. When that run completes, `llm / code-review` stays red, although the override is recorded and the label is set.

*Suggested fix:* Wait for the run to finish, polling with a timeout, and then re-run it; or cancel it and re-run. At the least, make the notice say that a manual re-run is needed.

**`wr-02`: /llm-risk and /llm-override posted while llm-review is running get a +1 reaction but may never take effect**

The re-run step re-runs the latest llm-review run only when its status is `completed`. Otherwise it prints "llm-review is still running; it reads the label itself". That holds only if the running attempt hasn't yet read the input. Triage reads /llm-risk from audit-log once, at the start of the run (llm-review.yml:89-91 and 118), and each llm job reads the labels in its "Override reason" step, before the review (llm-review.yml:244-268). /llm-risk sets no label at all. A command that arrives after triage (for /llm-risk) or after the override step (for /llm-override) is recorded and acknowledged, then ignored by the attempt in progress, and nothing re-runs the review afterwards. Two commands in quick succession behave the same way, because the second one finds the first one's re-run in progress. A re-run request that races a re-run that is just starting makes the API refuse it, which fails the feedback job after the record was written.

*Failure scenario:* Triage rates a PR low, so code-review and docs-drift are advisory. While the agent review is still running, the owner comments `/llm-risk medium touches the parser`. The record is written and gets a +1. The running attempt finishes at risk low with no blocking check, and the PR merges without the blocking review the owner asked for. The collector accepts this, because the risk_override is newer than run_started_at.

*Suggested fix:* When the run isn't completed, wait for it (poll, within the job's timeout) and then re-run it, or cancel it and re-run it. If it is still running when the timeout comes, comment that the command applies to the next run. Treat "already running" from the rerun API as a notice, not a failure.

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, medium, small): llm-feedback.yml:152-163 re-runs only a completed llm-review run; otherwise it prints 'still running; it reads the label itself' and exits. But each llm job reads labels once, in its 'Override reason' step before the review (llm-review.yml:244-268), triage reads /llm-risk from audit-log once at run start (78-91, 118), and the label added with GITHUB_TOKEN starts no new run. So an /llm-override posted after a check finished (naturally right after its failing sticky comment appears, while slower agent checks still run) is recorded, labelled and +1'd but not applied, and an /llm-risk raise during the run leaves that run at the lower risk, which fails open for raises. ADR 0007/0008 don't accept this.
- **maintainer** (CONFIRMED, medium, small): llm-feedback.yml:158-159 skips the re-run whenever the latest llm-review run isn't completed, on the assumption that 'it reads the label itself'. But each llm job reads the labels once in its Override reason step (llm-review.yml:244-268) before the review, jobs that already finished are never revisited, and triage reads /llm-risk from audit-log only at the start (lines 88-91, 118). The label is added with GITHUB_TOKEN, so nothing re-runs later, while the commenter gets a +1. ADR 0007 and docs/gates.md promise the command re-runs the review; this race isn't discussed anywhere. For /llm-override it fails closed (the check stays red), but a /llm-risk raise during a run is silently dropped. A wait-then-rerun or cancel-and-rerun is a small change.
- **impact** (CONFIRMED, medium, small): llm-feedback.yml:153-160 re-runs only a completed llm-review run and otherwise prints 'it reads the label itself', but each llm job reads labels once in its early 'Override reason' step and triage reads /llm-risk from audit-log once at the start, and the bot-added label starts no run. The common case bites: a failed code-review is only visible once that job finished, so an /llm-override posted while any other check of the run is still going is recorded, +1'd and never applied to that run. For override this fails safe (check stays red, a manual re-run fixes it); a raising /llm-risk is silently dropped for the running attempt, and the collector accepts that because the override is newer than run_started_at, while the +1 tells the owner it worked. Both real uses so far (#43 override, #47 /llm-risk low) took effect because they came after the run completed, so it hasn't bitten yet. A documented contract (docs/gates.md) that silently fails in a common timing window, no gate opens wrongly: medium.

</details>

### F047

**No policy inspects OCI image volumes, so a pod in calendar-gates can run code from any registry next to an attested container**

- **Status:** ✅ fixed — #69: calendar-gates-images denies any pod with an image volume, which no policy can verify
- **Severity:** medium (reviewers: medium) · **outcome:** confirmed · **fix cost:** trivial
- **Where:** `deploy/policies/base/images.yaml:21` · **area:** workflows, release, deploy, scripts
- **Reported by:** `cr-ops-01` (medium, medium confidence)

calendar-gates-images builds its image list from spec.containers, initContainers and ephemeralContainers only (images.yaml:21-25). Both ImageValidatingPolicies verify only images.containers + initContainers + ephemeralContainers (release.yaml:50-52, llm-review.yaml:41-43), and a foreign reference doesn't match their matchImageReferences glob anyway. spec.volumes[].image (KEP-4639) is checked by nothing. The project cluster runs Kubernetes 1.35 (deploy/kind/cluster.yaml), where ImageVolume is beta and on by default. Image volumes are mounted read-only, but the KEP later dropped its noexec requirement (kubernetes/enhancements #5354, #5417), and the current docs only promise read-only. So a container can exec a binary from one. I checked this offline: running kyverno test with base/images.yaml on a pod whose only container is the attested release digest, with command /payload/bin/tool and an image volume docker.io/library/busybox:latest, gives 'Want fail, got pass'. WRITEUP §4 says Kyverno checks every container kind. That stays literally true, because an image volume isn't a container kind, but the promise that nothing runs without attestations doesn't hold. The policies admit such a pod in every case; whether it starts also depends on the kind node's containerd supporting image volumes (containerd 2.1 or later).

*Failure scenario:* kubectl -n calendar-gates apply a Pod with containers[0].image = ghcr.io/gergodrazsdik/calendar-gates@sha256:<attested>, command [/payload/bin/tool], a volumeMount at /payload, and volumes[0].image.reference = docker.io/someone/tools:latest -> calendar-gates-images, -release and -llm-review all pass -> an unattested binary from Docker Hub runs in the Deny namespace.

*Suggested fix:* In calendar-gates-images, deny image volumes outright (e.g. a validation `!has(object.spec.volumes) || !object.spec.volumes.exists(v, has(v.image))`; the release chart uses none). Alternatively, add their references to variables.images so the repository/digest rule applies, and verify them in the image policies. Add a negative case to deploy/policies/tests.

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, medium, small): images.yaml:21-25 lists only containers, initContainers and ephemeralContainers, and both ImageValidatingPolicies verify only those with a glob a foreign reference wouldn't match. Reproduced with kyverno 1.19.1: a calendar-gates pod whose only container is the release digest plus volumes[].image.reference docker.io/library/busybox:latest gives 'Want fail, got pass'. Kubernetes' feature-gate table shows ImageVolume Beta and default true in 1.35 (GA in 1.36), the volumes docs promise only a read-only mount, and the runtime image keeps the dotnet host (Dockerfile ENTRYPOINT [dotnet, ...]), so `command: [dotnet, /payload/x.dll]` would run foreign IL even on a noexec mount. Not verified: that kind v0.33.0's v1.35.8 node ships containerd 2.1+ (needed for the pod to actually start).
- **maintainer** (CONFIRMED, medium, trivial): Reproduced offline: kyverno test with base/images.yaml on a pod whose only container is the attested release digest plus a volumes[].image of docker.io/library/busybox:latest gives 'Want fail, got pass'. Both image policies read only images.containers/initContainers/ephemeralContainers, so nothing looks at image volumes. The Kubernetes feature-gate table lists ImageVolume as beta and default true in 1.35, the project node's version, and the current volume docs promise only a read-only mount, no noexec. Whether a binary from the volume actually executes depends on containerd in kindest/node v1.35.8, which I couldn't test without a cluster, but the policy gap contradicts ADR 0010's 'every container kind' intent and WRITEUP's 'nothing runs without attestations'. Denying image volumes in calendar-gates-images (the chart uses none) plus a negative test case is a few lines.
- **impact** (CONFIRMED, low, trivial): Reproduced offline: a calendar-gates Pod whose only container is the attested digest plus an image volume from docker.io gives 'Want fail, got pass' for calendar-gates-images, and both image policies verify only images.containers+initContainers+ephemeralContainers. Kubernetes docs list ImageVolume as beta and enabled by default in 1.35 and mount it read-only with no noexec promise; containerd support in kind's v1.35.8 node image I did not verify. Calibrated down to low: only someone who can already create pods in the namespace (the cluster admin, or a tampered chart, see F054) can use it, and that actor can run arbitrary code under the attested image anyway, e.g. args [/cfg/x.dll] from a ConfigMap, since the chiseled image's entrypoint is the dotnet host.

</details>

### F052

**uv itself is unpinned: every setup-uv step installs the newest uv release, in the signing job and the write-token jobs too**

- **Status:** ✅ fixed — #73: uv.toml's required-version pins uv for all nine setup-uv steps, including the signing job
- **Severity:** medium (reviewers: medium) · **outcome:** confirmed · **fix cost:** small
- **Where:** `.github/workflows/release.yml:207` · **area:** workflows, release, deploy, scripts
- **Reported by:** `wr-08` (medium, high confidence)

setup-uv's `version` input "Defaults to the version in pyproject.toml or `latest`" (action.yml at the pinned SHA c18668ad), and it looks in working-directory, the workspace root. No workflow sets `version`, the repository has no uv.toml or root pyproject.toml, and tools/llm-gate/pyproject.toml has no required-version. So all nine setup-uv steps (ci lint, llm-review triage and llm, llm-compare, llm-eval, llm-feedback, audit-collect, metrics, release attest) download whatever uv was released last, with no cooldown. The actions get a SHA pin and a 14-day Dependabot cooldown, and the Python dependencies get exclude-newer; uv gets neither. In release.yml's attest job, every step can request an OIDC token (id-token: write) and therefore sign as release.yml. Before the actions/attest steps, that job also runs uv, llm-gate's PyPI dependencies, anchore/sbom-action and the syft binary it downloads.

*Failure scenario:* A compromised or broken uv release is published. The next tag push installs it in attest, where it can request an OIDC token and push attestations for any digest under the release identity. audit-collect and llm-feedback run it with contents: write.

*Suggested fix:* Pin uv: `version: "0.x.y"` on every setup-uv step, or required-version in a root uv.toml or a version-file, ideally with `checksum`. Move predicate and SBOM generation into a job without id-token: write, and keep the attest job to actions/attest steps on downloaded files.

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, low, small): No setup-uv step sets version or version-file, and setup-uv at the pinned SHA documents 'Defaults to the version in pyproject.toml or latest', looked up in working-directory (default github.workspace). The workspace root has no pyproject.toml or uv.toml (tools/llm-gate/pyproject.toml has exclude-newer but no required-version), so every setup-uv step installs the newest uv release with no cooldown, unlike the SHA-pinned actions and the locked, exclude-newer Python dependencies. In release.yml's attest job every step can request an OIDC token, so a malicious uv release there could sign as release.yml. It needs a compromised upstream release and only bites on a tag push, so low rather than medium.
- **maintainer** (CONFIRMED, medium, trivial): setup-uv's action.yml at the pinned SHA c18668ad says version 'Defaults to the version in pyproject.toml or latest' and searches uv.toml/pyproject.toml in the workspace root. No workflow sets version, there is no root uv.toml or pyproject.toml, and tools/llm-gate/pyproject.toml has no required-version, so all nine setup-uv steps install the newest uv. That includes release.yml's attest job, where every step can request an OIDC token (id-token: write) and sign as release.yml, and audit-collect/llm-feedback with contents: write. Everything else in the repo is pinned (action SHAs with a 14-day cooldown, exclude-newer, image digests), and nothing records uv as an exception. Adding version: to each step, or a root uv.toml, is trivial.
- **impact** (CONFIRMED, medium, small): setup-uv at the pinned SHA documents version default '' = 'the version in pyproject.toml or latest', looked up in working-directory (the workspace root); the repo has no root pyproject.toml, uv.toml or .tool-versions, tools/llm-gate/pyproject.toml has no required-version, and no setup-uv step sets version or version-file. So every run, including release attest (id-token: write) and audit-collect/llm-feedback (contents: write), installs whatever uv was released last, bypassing both the 14-day action cooldown and exclude-newer. A compromised uv release is unlikely, a behaviour change that breaks every --locked step at once is the likelier bite (fails closed). Medium matches the repo's own workflow-review scale for an unpinned dependency in privileged jobs.

</details>

### F081

**A malformed or empty ?year= on /api/friday13 gets a 400 without `errors` in Production and a 500 in Development, not the 400 ValidationProblem**

- **Status:** ✅ fixed — #73: the year is parsed, so a bad one is the same ValidationProblem in both environments
- **Severity:** medium (reviewers: medium) · **outcome:** confirmed · **fix cost:** small
- **Where:** `src/CalendarGates.Api/Endpoints/Friday13Endpoints.cs:28` · **area:** API, tests, docs
- **Reported by:** `api-01` (medium, high confidence), `cr-api-01` (medium, high confidence)

**`api-01`: A malformed or empty ?year= on /api/friday13 gets a 400 without `errors` in Production and a 500 in Development, not the 400 ValidationProblem**

`InYear` binds `[Range(Years.Min, Years.Max)] int? year`, so a value that doesn't parse as an int is a framework binding failure, not a validation error. Probed against a build of 43ec3c2. In Production, `GET /api/friday13?year=abc`, `?year=` (empty), `?year=2026.0`, `?year=99999999999` and `?year=2026&year=2027` all return 400 application/problem+json with only `title: Bad Request`, `status: 400`. There is no `errors` member. Meanwhile `?year=1500` returns the ValidationProblem (`title: One or more validation errors occurred.`, `errors.year`). In Development the same requests return 500 `An error occurred while processing your request.` and log an unhandled BadHttpRequestException (`Failed to bind parameter "Nullable<int> year" from "abc"`). The reason: `RouteHandlerOptions.ThrowOnBadRequest` is on in Development, and the exception reaches `app.UseExceptionHandler()` (Program.cs:13). `just run` uses the `http` launch profile (ASPNETCORE_ENVIRONMENT=Development). TUnit's TestWebApplicationFactory is built on WebApplicationFactory, which also runs the app as Development by default. The documented contract (llm-api-contract.md, new-endpoint.md) is '400 ValidationProblem for bad input', and /api/week/{date} and /api/workdays follow it for unparseable dates. Neither http/calendar.http nor the integration tests send a non-numeric or empty year.

*Failure scenario:* A client sends `/api/friday13?year=` from an empty optional form field, or `?year=abc`. Against the container it gets a 400 with no field information. Against `just run` it gets a 500. A `.http` request asserting `errors.year` for `?year=abc` would pass in http-tests (Production container) and fail under `just http` (Development).

*Suggested fix:* Bind `string? year` and validate it like WorkdaysEndpoints: parse it, check the range, and return a ValidationProblem with `errors.year`, treating empty as 'this year'. Alternatively, set `RouteHandlerOptions.ThrowOnBadRequest = false` and turn BadHttpRequestException into a ValidationProblem in one place. Add `?year=abc` and `?year=` cases to calendar.http and Friday13Tests.

**`cr-api-01`: An unparsable /api/friday13?year= returns 500 in Development and the test host, and a 400 with no errors map in Production**

`InYear` binds `[Range] int? year` straight from the query. When the value can't be parsed (`year=abc`, an empty `year=`, or a repeated `year=2026&year=2027`), minimal APIs fail parameter binding before the validation filter runs. In Development, `RouteHandlerOptions.ThrowOnBadRequest` defaults to true, so a `BadHttpRequestException` is thrown. `app.UseExceptionHandler()` (Program.cs:13) catches it and, with no `StatusCodeSelector`, maps it to 500. In Production the binder writes a bare 400 instead. `UseStatusCodePages` then adds a generic ProblemDetails with title "Bad Request" and no `errors.year`. So the failure has a different status code depending on the environment, and in neither environment does it match the endpoint's own validation contract (`year=1500` gives a 400 ValidationProblem with `errors.year`, which `http/calendar.http` relies on). I checked this by running it. With the built API in Production, all three inputs gave a 400 with a field-less body. With `ASPNETCORE_ENVIRONMENT=Development`, all three gave a 500, and the log showed `BadHttpRequestException: Failed to bind parameter "Nullable<int> year" from "abc"`. Through `WebApplicationFactory` (Mvc.Testing 10.0.12, the host under TUnit.AspNetCore), the environment was `Development` and both `?year=abc` and `?year=` gave a 500. So an integration test can't pin the production behaviour, and `just run` serves 500s. This is the only query-bound value type in the API: `{year:int}` route values fail the constraint and give a 404, and the date parameters are strings that are parsed explicitly.

*Failure scenario:* GET /api/friday13?year=abc. Against `just run` or an integration test you get HTTP 500 "An error occurred while processing your request." Against the container (Production) you get a 400 with no `errors` property, so a client that reads `errors.year`, as the .http test does for year=1500, fails. `year=` (empty) is rejected the same way instead of falling back to "this year".

*Suggested fix:* Parse `year` the same way the date endpoints parse dates. Bind it as `string?`, use `int.TryParse(..., NumberStyles.None, CultureInfo.InvariantCulture, ...)`, check `Years.IsSupported`, and return `TypedResults.ValidationProblem(new() { ["year"] = [...] })`. Alternatively, give the exception handler `StatusCodeSelector = ex => ex is BadHttpRequestException b ? b.StatusCode : 500` so the status code at least matches across environments. Add an integration test for `?year=abc`.

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, medium, small): Reproduced on a Release build of 43ec3c2. In Production, ?year=abc, ?year=, ?year=2026.0, ?year=99999999999 and ?year=2026&year=2027 return 400 problem+json with only title/status and no errors, while ?year=1500 returns the ValidationProblem with errors.year. In Development the first three return 500, and the log shows BadHttpRequestException 'Failed to bind parameter "Nullable<int> year" from "abc"' caught by UseExceptionHandler (Program.cs:13). The integration host runs as Development: TUnit.AspNetCore pulls in Mvc.Testing 10.0.12, whose WebApplicationFactory defaults to Development. No test or .http request sends a malformed year, so nothing pins either behaviour. I found no guard elsewhere, and the repo's own code-review rubric rates a 500 for invalid input medium.
- **maintainer** (CONFIRMED, medium, small): I built 43ec3c2's API (scratch copy, dotnet publish) and probed it. In Production, `/api/friday13?year=abc`, `?year=`, `?year=99999999999` and `?year=2026&year=2027` return 400 problem+json with only title 'Bad Request' and no `errors`, while `?year=1500` returns the ValidationProblem with `errors.year`. In Development the same malformed inputs return 500, and the log shows `BadHttpRequestException: Failed to bind parameter "Nullable<int> year"` caught by ExceptionHandlerMiddleware. `[Range] int?` follows PLAN.md 2.2's 'AddValidation where it fits', but the result breaks the project's own contract (llm-api-contract.md: 400 ValidationProblem for bad input; llm-code-review.md rates a 500 for invalid input as medium). No test or .http request sends a malformed year.
- **impact** (CONFIRMED, medium, small): Built 43ec3c2 and ran it in both environments: `?year=abc`, `?year=`, `?year=%20`, `2026.0`, `99999999999` and a repeated `year` return a 400 ProblemDetails with only title 'Bad Request' (no `errors`) in Production and a 500 in Development (logged as BadHttpRequestException 'Failed to bind parameter Nullable<int> year'), while `?year=1500` gets the ValidationProblem in both. A scratch TUnit project on the same TestWebApplicationFactory confirmed the test host runs as Development and returns 500 for `?year=abc` and `?year=`, and `just run`/`just http` use the Development profile, so contributors see 500s locally while CI's http-tests (Production container) see 400s. It bites an HTML form sending an empty optional `?year=` (400 instead of 'this year') and whoever writes the missing test (a different status per environment); medium on the repo's own rubric ('a 500 only for ... invalid input', 'inconsistent error shape'), at its low end because generated clients follow the documented int32 schema with pattern and min/max. One slip in api-01: a `.http` assertion on `errors.year` for `?year=abc` would fail in http-tests too, since Production returns no `errors`.

</details>

### F084

**"A failed smoke leaves a draft; re-running the workflow refreshes it" no longer holds under build-once releases**

- **Status:** ✅ fixed — #63: gates.md says why not to re-run a failed release
- **Severity:** medium (reviewers: medium) · **outcome:** confirmed · **fix cost:** trivial
- **Where:** `docs/gates.md:144` · **area:** API, tests, docs
- **Reported by:** `dd-01` (medium, high confidence)

The sentence dates from v1 (#7, 2026-10-15). Back then `publish` rebuilt and re-pushed the image. Since #52, `build` makes new, non-reproducible bytes on every run. `publish` then refuses to move an existing X.Y.Z (release.yml:315-321, "Release a new version"). ADR 0009:54-55 says so too: "A full re-run builds new bytes, so publish fails rather than move the version tag". A "re-run failed jobs" re-runs only `smoke`, which publishes the draft without refreshing it. The draft is refreshed (release.yml:355-361) only when `publish` itself is re-run with the original build outputs. gates.md contradicts ADR 0009.

*Failure scenario:* smoke fails on v0.4.0 (for example a flaky contract test). Following gates.md, the owner clicks "Re-run all jobs". build pushes new bytes over candidate-v0.4.0, attest writes four more permanent Rekor entries for the new digest, approval is requested again, and publish then fails because 0.4.0 already points at the first digest.

*Suggested fix:* "A failed smoke leaves a draft: re-run the failed jobs (or re-run `publish` to refresh the draft's notes). Never re-run all jobs: that builds new bytes, and `publish` refuses to move X.Y.Z (ADR 0009)."

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, medium, trivial): gates.md:143-144 (wording carried over from v1's #7) says that re-running the workflow refreshes a failed smoke's draft. Under ADR 0009, a full re-run rebuilds without cache and pushes new bytes to candidate-vX.Y.Z. It writes four more permanent Rekor entries and asks for approval again, and then publish's never-move check (release.yml:315-321) fails, which burns the version (ADR 0009:54-55 says this outright). 'Re-run failed jobs' re-runs only smoke, which publishes the draft without refreshing it. Only a re-run of publish itself takes the refresh branch (release.yml:355-361), so the documented procedure fails under either reading.
- **maintainer** (CONFIRMED, medium, trivial): gates.md:143-144 says re-running refreshes the draft. Under build-once (ADR 0009), a full re-run builds new, non-reproducible bytes, attests them (four more permanent Rekor entries) and asks for approval again, then publish stops at release.yml:315-321 because X.Y.Z already points at the first digest. ADR 0009:54-55 says exactly this. 'Re-run failed jobs' re-runs only smoke, which publishes the draft without refreshing it; the refresh branch (355-361) runs only when publish itself is re-run. A documented recovery path that no longer works is medium on the repo's docs-drift scale.
- **impact** (CONFIRMED, medium, trivial): gates.md:143-144 says re-running the workflow refreshes a failed smoke's draft; release.yml refreshes the draft (lines 355-361) only when `publish` itself re-runs with the original build outputs, and its never-move check (316-321) fails `publish` after a full re-run, as ADR 0009 states. 'Re-run failed jobs' after a smoke failure re-runs only smoke, which publishes the unchanged draft (works, refreshes nothing); 'Re-run all jobs', the natural reading of 're-running the workflow', rebuilds non-reproducible bytes over candidate-vX.Y.Z, adds four permanent public Rekor entries (which ADR 0009 deliberately limits), asks for approval again and then fails, burning the version. The guard prevents the integrity harm, but the documented recovery path has irreversible side effects, and the next release is the first to run #54's Deny policy and new admission-smoke assertions (F095), so a smoke-stage failure is likelier than usual; medium per the repo's docs-drift rubric ('a documented command ... no longer works'). Not ACCEPTED: ADR 0009 accepts the re-run behaviour, not a doc that recommends it.

</details>

#### Confirmed: low

### F007

**An override by label skips the write-role check that `/llm-override` enforces**

- **Status:** open
- **Severity:** low (reviewers: medium) · **outcome:** confirmed · **fix cost:** trivial
- **Where:** `tools/llm-gate/src/llm_gate/audit.py:524` · **area:** llm-gate and review prompts
- **Reported by:** `sec-04` (medium, high confidence), `cr-gate-11` (low, high confidence)
- **Reports the council found wrong:** `sec-04`

**`sec-04`: An override by label skips the write-role check that `/llm-override` enforces**

`find_override` has two paths. When the feedback workflow added the label (`labeller == github-actions[bot]`), the comment's author must be in `writers`, the logins with a write, maintain or admin role (`scripts/override-writers.sh`). When a person added the label, the only test is `author != labeller` (line 524): no role lookup, although the caller has already fetched `writers.json` (llm-review.yml:255) and passes it in. GitHub's **triage** role may apply labels but is not a write role, and `feedback.handle` rejects it explicitly (`permission not in audit.WRITE_ROLES`, feedback.py:173, covered by `test_feedback.py:296` for `read`, `triage`, `None`). So the command path refuses a triage collaborator while the label path honours them, contradicting ADR 0007 ("the commenter's actual repository role ... must be write, maintain or admin") and docs/gates.md ("write access needed"). The collector uses the same function, so the forged-looking override is recorded as legitimate rather than as a problem.

*Failure scenario:* A collaborator with only the triage role adds the `llm-override` label to a PR and comments `/llm-override shipping anyway`. `llm-feedback.yml` rejects the command (no write role) and writes `feedback_rejected`, but the next `llm-review` run's override step finds label + matching comment by the same login, honours the override, and both blocking checks pass with `verdict: fail, exit 0, override_honoured: true`.

*Suggested fix:* In `find_override`, require `labeller in writers` on the human-label path as well (and keep refusing when `writers is None`), so both paths use the role lookup the callers already provide.

**`cr-gate-11`: find_override honours a human labeller's override without checking that they have write access**

When a person added the label, the only check is that the /llm-override comment's author is that labeller. The writers list (role write, maintain or admin) is applied only to labels added by github-actions[bot]. Adding labels needs only the Triage role, which has no write access. ADR 0002 says an override needs write access, and ADR 0007 notes that MEMBER and COLLABORATOR don't imply it. This isn't exploitable in this personal repository, where collaborators always have write access, but the code stops enforcing its own rule once the repository has triage-role users or moves to an organization.

*Failure scenario:* In an org-owned copy, a triage-role member adds llm-override to their PR and comments '/llm-override fine'. find_override returns an OverrideRequest, the blocking findings are overridden, and the collector agrees.

*Suggested fix:* When writers is given, require the author to be in writers in both branches. override-writers.sh already resolves the roles of /llm-override authors.

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, low, trivial): The asymmetry is real: on the human-label path find_override only requires author == labeller and never consults `writers` (audit.py:521-525). But GitHub's docs (fetched) say a personal-account repository has only two levels, owner and collaborators, and every collaborator has write access, with no triage role. Anyone who can add the label here already has write access, so sec-04's triage-role scenario can't happen in this repository. It's a latent gap for an organization move, as cr-gate-11 says.
- **maintainer** (CONFIRMED, low, trivial): find_override's human-label path checks only author == labeller and ignores `writers`, while the bot path requires it. But this is a personal-account repository: GitHub's docs say it has two permission levels and 'Collaborators can't have read-only access', so everyone who can add a label already has write access; a triage-role user (sec-04's scenario) can't exist here. The inconsistency is latent for an org-owned copy; requiring `author in writers` on both paths is a one-line change since writers.json already holds the /llm-override authors with a write role.
- **impact** (CONFIRMED, low, trivial): find_override consults writers only when github-actions[bot] added the label; for a human labeller it requires only author == labeller (audit.py:519-525), while feedback.handle requires a write role. But a personal-account repository has only owner and collaborators (write); the Triage role exists only in organisations, and outsiders can't label PRs, so nobody can trigger it here. A latent inconsistency with ADR 0007, trivial to fix by requiring the labeller in writers too. sec-04's triage-role scenario can't occur in this repository; cr-gate-11 says so and rates it right.

</details>

### F009

**llm-eval scores security-review only on the API engine, but high-risk PRs (most of them) review it on the agent engine**

- **Status:** open
- **Severity:** low (reviewers: medium) · **outcome:** confirmed · **fix cost:** small
- **Where:** `.github/workflows/llm-eval.yml:100` · **area:** llm-gate and review prompts
- **Reported by:** `cr-gate-13` (low, high confidence), `tr-08` (medium, high confidence)

**`cr-gate-13`: llm-eval scores each check only on its configured engine, while most PRs run security-review on the agent engine**

Without --engine, cmd_eval runs each check on check.engine, and llm-eval.yml passes no --engine, so security-review is compared only as api/claude-sonnet-5-5. Triage's high level moves blocking checks to the agent engine, and ADR 0008 expects most PRs here to be rated high. Production security reviews therefore mostly run in a configuration CI never evaluates, even though baseline.json has an agent/claude-sonnet-5-5 entry for security-review; that entry is never compared.

*Failure scenario:* A prompt edit that only hurts the agent path, for example telling the reviewer not to read files outside the diff, passes llm-eval on the api engine and lowers recall on every high-risk PR.

*Suggested fix:* For checks whose engine changes at some triage level, evaluate and compare every engine they can run on, or run blocking checks with --engine both in llm-eval.

**`tr-08`: llm-eval scores security-review only on the API engine, but high-risk PRs (most of them) review it on the agent engine**

llm-eval runs `eval run --compare` without --engine, so every check runs on its configured engine, which for security-review is api (checks.yaml:18). cmd_eval never applies triage levels. At high risk the level moves blocking checks to the agent engine (checks.yaml:370, plan_for), and ADR 0008 and WRITEUP report most PRs as high (62%). baseline.json has an agent/claude-sonnet-5-5 entry for security-review, but CI never compares a run against it. code-review is unaffected, since its configured engine is already agent.

*Failure scenario:* A security-review prompt change works on the API engine but breaks in the agent setting: say the agent stops returning a structured review after reading files, or rates lower once it sees context. llm-eval passes on the API engine, and the change reaches most PRs.

*Suggested fix:* For each blocking check, also evaluate the engine each triage level assigns, here security-review on agent: derive the engines from triage.levels, or pass --engine both for blocking checks in llm-eval.yml.

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, low, small): llm-eval.yml runs `eval run --compare --repeats 3` with no --engine, and cmd_eval uses [args.engine or check.engine], so security-review is evaluated only as api/claude-sonnet-5-5. At high risk, plan_for moves it to the agent engine, and baseline.json's agent/claude-sonnet-5-5 entry for security-review is never compared in CI. Rated low: prompt and model are shared between engines, code-review is evaluated on its production engine, and an agent-only regression caused by a prompt is a narrow case.
- **maintainer** (CONFIRMED, medium, small): llm-eval.yml runs `eval run --compare` without --engine and cmd_eval uses check.engine, so security-review is only ever compared as api/claude-sonnet-5-5, while plan_for moves blocking checks to the agent engine at high risk, which ADR 0008 expects for most PRs (WRITEUP: 62%). The evals README sentence 'llm-eval in CI uses each check's own engine' came with #36, before triage (#46) added the engine switch, and wasn't revisited; the agent/claude-sonnet-5-5 baseline entry for security-review is never compared in CI. code-review is unaffected (configured agent).
- **impact** (CONFIRMED, low, small): llm-eval.yml runs `eval run --compare` without --engine, and cmd_eval uses check.engine and never applies triage levels, so security-review is scored only as api/claude-sonnet-5-5 while the high level (62% of PRs per WRITEUP) runs it on the agent engine; baseline.json's agent entry for security-review (13 cases) is never compared. The gap is narrow: both engines get the same prompt text, and the agent engine's code path is exercised by code-review's evals, so only an agent-specific regression of the security prompt slips through. Low; --engine both for the blocking checks is cheap.

</details>

### F018

**The triage eval lets any one triage case fail in every repeat, tr-008 included; 4 of its 10 cases can't fail at all**

- **Status:** open
- **Severity:** low (reviewers: medium) · **outcome:** confirmed · **fix cost:** small
- **Where:** `tools/llm-gate/evals/thresholds.yaml:8` · **area:** llm-gate and review prompts
- **Reported by:** `tr-07` (medium, high confidence)

risk_accuracy is computed over 10 cases x 3 repeats, with a 1.00 baseline and max_risk_accuracy_drop 0.15. tr-005 (.github), tr-007 (850 lines), tr-009 (AI-assisted) and tr-010 (renamed workflow) are high by the rules, and final = max(rules, model), so no prompt can make them fail. Only tr-004 and tr-008 need the model to raise the risk. ADR 0008 says tr-008 'keeps checking that the model raises when the diff asks for a low rating'. If tr-008 fails in all 3 repeats, risk_accuracy is 27/30 = 0.90, a drop of 0.10, and compare() passes: no flip, and floor_violations stays 0 (see tr-14). Two cases must regress completely before the gate fails.

*Failure scenario:* A change to llm-triage.md makes the model obey tr-008's 'docs-only, rate it low' comment every time. llm-eval reports risk_accuracy 1.00 -> 0.90 and passes, and the injection resistance ADR 0008 relies on is no longer measured.

*Suggested fix:* Score the must-raise cases separately, for example a raise rate over cases whose expect_risk is above the rules floor, with its own threshold. Or tighten the triage threshold below one case (< 1/10). Report the floor-decided cases separately or drop them from risk_accuracy.

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, low, small): I computed every triage case's floor with the real checks.yaml. tr-005, tr-007, tr-009 and tr-010 have floor high and pass for any model answer. Only tr-004 and tr-008 need the model to raise to high. With 10 cases x 3 repeats, tr-008 failing in every repeat gives 27/30 = 0.90, a drop of 0.10, under max_risk_accuracy_drop 0.15. A consistent failure has no flips, and floor_violations is always 0 (F030), so compare() passes, and ADR 0008's claim that tr-008 'keeps checking' doesn't hold. Rated low: a model that fails to raise leaves the PR at its floor, where both blocking checks still run.
- **maintainer** (CONFIRMED, low, small): Computed each triage case's floor: tr-005/007/009/010 have floor high = expect high and cannot fail; only tr-004 and tr-008 need the model to raise. tr-008 failing in all 3 repeats gives 27/30 = 0.90, a 0.10 drop under max_risk_accuracy_drop 0.15, and no flip. So ADR 0008's 'tr-008 keeps checking that the model raises' is overstated. Impact is limited because the floor holds regardless (ADR 0008: talking the model down changes nothing).
- **impact** (CONFIRMED, low, small): Computed with the real triage.floor: only tr-004 and tr-008 need the model to raise (floor medium, expect high); tr-005/007/009/010 have floor high = expect high and can't fail, and tr-001/002/003/006 can fail only by over-raising. With 10 cases x 3 repeats, tr-008 wrong in every repeat gives 0.90, a 0.10 drop under the 0.15 limit, so the injection case ADR 0008 cites isn't gated on its own. But the triage model can only raise: a model that stops raising leaves the rules floor (medium for src/), which costs the agent engine and workflow-review on such PRs, not a bypass. Low.

</details>

### F021

**Triage rates gate configuration outside .github/ and tools/llm-gate/ at the default medium**

- **Status:** open
- **Severity:** low (reviewers: low) · **outcome:** confirmed · **fix cost:** trivial
- **Where:** `tools/llm-gate/checks.yaml:47` · **area:** llm-gate and review prompts
- **Reported by:** `cr-gate-14` (low, high confidence), `sec-10` (low, high confidence), `cr-ops-20` (info, high confidence)

**`cr-gate-14`: Triage rates gate configuration outside .github/ and tools/llm-gate/ at the default medium**

The 'changes CI or the gates' rule covers .github/**, tools/llm-gate/**, .claude/commands/llm-* and scripts/**. Files that change what the gates check fall through to default_risk medium: .gitattributes (what llm-gate's diff contains, see cr-gate-01), .grype.yaml (vulnerability ignores), .editorconfig (format rules), Directory.Build.props (TreatWarningsAsErrors, analyzers), .yamllint.yaml, lefthook.yml, justfile and .config/dotnet-tools.json. AGENTS.md counts an added ignore or a lowered threshold as weakening a gate. At medium, security-review stays on the api engine and workflow-review doesn't run; only the cheap model can raise the rating.

*Failure scenario:* A PR adds a broad ignore to .grype.yaml and `* -diff` to .gitattributes. Triage rates it medium from the default rule and gives no 'changes CI or the gates' reason.

*Suggested fix:* Add these paths to the high rule, or to a separate 'gate configuration' rule.

**`sec-10`: Gate configuration outside the listed paths falls to `default_risk: medium`, including `.grype.yaml` and the hook config**

`triage.rules` rates `.github/**`, `tools/llm-gate/**`, the review prompts, `scripts/**`, `Dockerfile` and `deploy/**` high, but several files that decide what the deterministic gates enforce match no rule and therefore get `default_risk: medium`: `.grype.yaml` (an `ignore:` entry suppresses a vulnerability finding - AGENTS.md calls that a gate change), `.yamllint.yaml`, `.editorconfig` (ADR 0001: must not fight CSharpier), `lefthook.yml`, `global.json`, `justfile` (the `lint`/`ci` recipes) and `.gitattributes` (sec-01). Verified by running the rules' globs through `PurePosixPath.full_match`. At medium the blocking checks still run and block, so the impact is limited to missing the high level's agent engine and full check set, and to the rules' floor not reflecting that these are gate changes.

*Failure scenario:* A PR adds a `.grype.yaml` ignore entry for a high-severity CVE with a plausible reason. Triage rates the PR medium rather than high, `workflow-review` doesn't run at all (it is medium-excluded), and the diff is reviewed by the API engine without reading the surrounding configuration.

*Suggested fix:* Add a high rule for the deterministic gates' configuration (`.grype.yaml`, `.yamllint.yaml`, `.editorconfig`, `lefthook.yml`, `justfile`, `global.json`, `.gitattributes`), or set `default_risk: high` for root-level configuration files.

**`cr-ops-20`: Files that drive required gates (justfile, .grype.yaml, .yamllint.yaml, .config/dotnet-tools.json) fall to default_risk medium, unlike scripts/****

scripts/** is rated high because CI runs it (check-commit-msg.sh is the pr-title gate), and .github/zizmor.yml is high through .github/**. The same reasoning applies to the justfile (ci.yml's format job runs just fmt-check), .grype.yaml (the grype gate's threshold and ignore list), .yamllint.yaml (lint) and .config/dotnet-tools.json (the CSharpier version behind format). They match no rule and get medium, as the comment on line 45 says. The practical difference is small: at medium the same checks block, and only security-review's engine changes. The labels and metrics still under-rate such PRs. I found this while reviewing the justfile's role in CI; the file itself is outside this review's scope.

*Failure scenario:* A PR that only changes fmt-check to `true` in the justfile, or adds an ignore to .grype.yaml, is rated risk:medium ('no rule matched'), although it weakens a required gate.

*Suggested fix:* Add justfile, .grype.yaml, .yamllint.yaml and .config/** to the high 'changes CI or the gates' rule.

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, low, trivial): No rule matches .grype.yaml, .gitattributes, .editorconfig, Directory.Build.props, .yamllint.yaml, lefthook.yml, justfile or .config/, so they get default_risk medium. Part of this is deliberate: the checks.yaml comment on default_risk lists justfile, lefthook.yml, global.json and .config/, and a test pins justfile at medium. No ADR records it, and ADR 0008 rates 'the gate' high, which .grype.yaml arguably is. ci.yml:54 does run `just fmt-check` (cr-ops-20 is right). At medium both blocking checks still run and block, hence low.
- **maintainer** (CONFIRMED, low, trivial): Checked the rules: .grype.yaml, .gitattributes, .editorconfig, Directory.Build.props, .yamllint.yaml, lefthook.yml, justfile and .config/ match no rule and get default medium. The checks.yaml comment `default_risk: medium # justfile, lefthook.yml, global.json, .config/ ...` shows that was deliberate for those files; .grype.yaml (vulnerability ignores) and .gitattributes (F001) aren't covered by any recorded reasoning. At medium the same blocking checks run and block; only workflow-review and the agent engine are lost.
- **impact** (CONFIRMED, low, trivial): Checked against the rules: .gitattributes, .grype.yaml, .editorconfig, Directory.Build.props, .yamllint.yaml, lefthook.yml, justfile and .config/dotnet-tools.json match no rule and get default_risk medium (the checks.yaml comment names some of them, but no ADR treats them as gate configuration). At medium, code-review and security-review still run and block, so the cost is the api engine for security-review and a lower risk label; workflow-review's paths wouldn't cover these files anyway. Low.

</details>

### F022

**The collector rechecks a run's triage against the default branch's checks.yaml at collection time, not the config the run used**

- **Status:** open
- **Severity:** low (reviewers: low) · **outcome:** confirmed · **fix cost:** small
- **Where:** `tools/llm-gate/src/llm_gate/cli.py:600` · **area:** llm-gate and review prompts
- **Reported by:** `api-18` (low, medium confidence), `wr-17` (low, medium confidence)
- **Reviewer's accepted_in:** docs/adr/0008-risk-triage.md

**`api-18`: The collector rechecks a run's triage against the default branch's checks.yaml at collection time, not the config the run used**

`_triage_expected` loads tools/llm-gate/checks.yaml from the collector's checkout, which is the default branch at collection time, to recompute the floor and every level's plan. The accepted check names come from the same checkout (audit-collect.yml:118). The run itself used checks.yaml at `gate_sha`, which the records carry together with config_sha256. Suppose a PR that changes triage.rules, or a level's run or blocking list, merges while another PR's llm-review is in flight. That run's triage and gate_run records are correct, but they get flagged tamper_suspected. ADR 0008 names the default branch's checks.yaml as the trusted source and lists the PR-description race as a consequence, but not this one.

*Failure scenario:* PR A moves `scripts/**` from high to medium and merges while PR B's review is running. B's triage record says rules_risk high, the collector now computes medium, and B's whole run is written as tamper_suspected. The next release attestation lists B as unverified.

*Suggested fix:* First check that gate_sha is an ancestor of the default branch, then recompute from `git show <gate_sha>:tools/llm-gate/checks.yaml`, falling back to the current config if it isn't; or accept either config. Add the race to ADR 0008's consequences.

**`wr-17`: The collector checks a run against the default branch's checks.yaml as it is at collection time, not the one the run used**

_triage_expected loads tools/llm-gate/checks.yaml from the collector's checkout, which is main when audit-collect starts, and the --checks list comes from the same file. The run itself used gate_sha, which was main when triage started. If a change to the triage rules, the levels or the check list merges while reviews are running, the recomputed floor or plans differ. Every run in flight then gets its triage artifact, and with it all its gate_runs, written as tamper_suspected, or an artifact for a removed check fails with "not a check in the default branch's checks.yaml". Changes to checks.yaml are frequent here (#58, for one).

*Failure scenario:* PR X changes triage.levels.medium.run and merges. PR Y's review, triaged under the old file, completes a minute later. The collector compares Y's checks_plan with the new plan and writes tamper_suspected for all of Y's records.

*Suggested fix:* When recomputing the floor, the plans and the check list, load checks.yaml from the run's gate_sha: fetch that commit and verify that it is on main.

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, low, small): _triage_expected loads tools/llm-gate/checks.yaml from the collector's own checkout, which is the default branch's head when audit-collect starts (no --config is passed), and `--checks` comes from the same checkout (audit-collect.yml:118). The run itself used gate_sha's config. If a change to triage.rules, levels or the check list merges while another PR's review is in flight, _triage_problems flags that run's correct triage (rules_risk or checks_plan mismatch), and every gate_run of the run then gets 'did not check out'; an artifact for a removed check is rejected outright. ADR 0008 names the default branch's checks.yaml and lists only the PR-description race as a consequence, so this isn't ACCEPTED. The window is short and the effect is a false alarm, not a bypass.
- **maintainer** (CONFIRMED, low, small): _triage_expected loads checks.yaml from the collector's checkout (the default branch at collection time) and --checks comes from the same file, while the run used gate_sha's config. A checks.yaml change merged while a review is in flight makes its correct triage and gate_runs tamper_suspected. ADR 0008 names the default branch's checks.yaml and lists the PR-description race, not this one, so not ACCEPTED. False alarms only.
- **impact** (CONFIRMED, low, small): _triage_expected loads checks.yaml (and the collector's --checks list) from the collector's checkout of the default branch at collection time, while the run used gate_sha. A merge that changes triage rules or levels while another PR's review is in flight turns that run's triage artifact, and with it every gate_run, into tamper_suspected; an artifact for a removed check is rejected outright. ADR 0008 names the default branch's checks.yaml as the source and accepts the analogous race for the PR description, but not this one, so not ACCEPTED (api-18's accepted_in overreaches). Rare and a false alarm, not a bypass: low.

</details>

### F023

**api-contract's paths filter misses files that change the HTTP contract outside Endpoints/, Domain/, Program.cs and http/**

- **Status:** open
- **Severity:** low (reviewers: low) · **outcome:** confirmed · **fix cost:** trivial
- **Where:** `tools/llm-gate/checks.yaml:24` · **area:** llm-gate and review prompts
- **Reported by:** `api-11` (low, medium confidence)

The filter is `src/**/Endpoints/**`, `src/**/Domain/**`, `src/**/Program.cs` and `http/**`. These files are not covered: Directory.Build.props (`TargetFramework`: binding, validation and the OpenAPI generator change with the framework); Directory.Packages.props (Microsoft.AspNetCore.OpenApi, which generates /openapi/v1.json, part of the contract according to the prompt); src/CalendarGates.Api/CalendarGates.Api.csproj; appsettings*.json (`AllowedHosts` decides which Host headers get a 400); and Properties/launchSettings.json (port 5080, which the `local` environment in http-client.env.json depends on). `runner.run_check` reports a PR that touches only these as 'not applicable'. Eval case ac-001 already found this class of gap once (Domain/ and Program.cs, #37).

*Failure scenario:* A PR retargets the solution to net11.0 and bumps Microsoft.AspNetCore.OpenApi. The generated document's schemas change, and llm / api-contract reports 'the change touches none of ...'.

*Suggested fix:* Add `Directory.Build.props`, `Directory.Packages.props`, `src/**/*.csproj`, `src/**/appsettings*.json` and `src/**/launchSettings.json` to the paths, and update the api-contract note in docs/gates.md.

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, low, trivial): api-contract's paths are src/**/Endpoints/**, src/**/Domain/**, src/**/Program.cs and http/**. The prompt defines the OpenAPI document at /openapi/v1.json as part of the contract, but Directory.Packages.props (Microsoft.AspNetCore.OpenApi) and Directory.Build.props (TargetFramework) are outside the filter, so a PR touching only those gets 'not applicable' (runner.py:66-67). appsettings AllowedHosts arguably counts too; launchSettings.json is local tooling, not the public contract. The check is advisory, hence low.
- **maintainer** (CONFIRMED, low, trivial): The api-contract prompt defines the contract to include status codes and /openapi/v1.json, but its paths filter misses appsettings*.json (AllowedHosts decides Host-header 400s) and Directory.Packages.props (Microsoft.AspNetCore.OpenApi), so a PR touching only those is 'not applicable'. Advisory check, and http-tests is the deterministic backstop for the contract.
- **impact** (CONFIRMED, low, trivial): api-contract's paths are src/**/Endpoints/**, src/**/Domain/**, src/**/Program.cs and http/**; Directory.Build.props, Directory.Packages.props, *.csproj, appsettings*.json and launchSettings.json fall outside, so a framework or OpenAPI package bump reports not applicable. api-contract is advisory and the http-tests gate exercises the real contract, so the cost is a missed advisory comment. Low.

</details>

### F024

**A PR that changes only http/calendar.http is rated low, where api-contract doesn't run, so its http/** filter never fires for such PRs**

- **Status:** open
- **Severity:** low (reviewers: low) · **outcome:** confirmed · **fix cost:** trivial
- **Where:** `tools/llm-gate/checks.yaml:60` · **area:** llm-gate and review prompts
- **Reported by:** `api-12` (low, high confidence)

triage.rules rate `http/**` low (line 56), and the low level runs only code-review and docs-drift (line 60). For such a PR, api-contract reports 'not needed at risk: low'. Yet the prompt's second bullet covers `.http` changes without the matching code change ('and the other way round'), and docs/gates.md:75 says api-contract runs when a PR touches http/. Only AI-assisted PRs, which get raised to medium, are reviewed. test-review doesn't run at low either.

*Failure scenario:* A human PR deletes the 'Easter: year out of range' request or loosens an assertion in calendar.http. Triage rates it low, api-contract and test-review don't run, and the contract test loses coverage without anyone noticing.

*Suggested fix:* Rate `http/**` medium with a rule placed before the tests/docs rule, or add api-contract to the low level's run list. Either way, fix the sentence in docs/gates.md.

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, low, trivial): triage.rules rate http/** low (the tests-or-docs rule), and levels.low.run is [code-review, docs-drift]. So a PR changing only http/calendar.http gets api-contract and test-review as not_needed unless AI markers or size raise it. That makes api-contract's http/** filter dead for such PRs, although the prompt covers '.http changes without the code change'. docs/gates.md:75 ('api-contract runs when a PR touches ... http/') contradicts the triage note in the same file. Advisory, hence low.
- **maintainer** (CONFIRMED, low, trivial): triage.rules put http/** with tests and docs at low, and levels.low runs only code-review and docs-drift, so a non-AI-assisted .http-only PR never gets api-contract (or test-review). ADR 0008 decided 'low: tests and docs', but not this consequence, and docs/gates.md still says api-contract runs when a PR touches http/. AI-assisted PRs are raised to medium, which limits it.
- **impact** (CONFIRMED, low, trivial): http/** matches the low rule and the low level runs only code-review and docs-drift, so a human's http-only change gets api-contract 'not needed', contradicting docs/gates.md:75 ('runs when a PR touches ... http/'). AI-assisted PRs (75% here) are raised to medium and get it. An advisory check and a doc mismatch: low.

</details>

### F025

**One /llm-override writes an override record per check job, including advisory, passing and not-applicable checks, and the release attestation repeats them all**

- **Status:** ✅ fixed — #75: the record follows the outcome, not the label: findings overridden, an oversized diff accepted, or a blocking check reviewing a diff with files missing
- **Severity:** low (reviewers: low) · **outcome:** confirmed · **fix cost:** trivial
- **Where:** `tools/llm-gate/src/llm_gate/cli.py:381` · **area:** llm-gate and review prompts
- **Reported by:** `api-13` (low, high confidence)

Every llm job reads the override. Whenever an override was honoured and the check wasn't not_needed, `cmd_run` appends `Override(checks=[check.name])`, whatever the check's mode or verdict. In the audit log, PRs #33 and #43 each have six override records: `checks: [api-contract]`, `[docs-drift]`, `[test-review]` and `[workflow-review]` (the last was not_applicable), plus code-review and security-review. Only code-review had `override_honoured: true`. The audit-log README describes an override record as 'An honoured llm-override'. `attestations.llm_review` (150-158) copies every override record of the merged head into the permanent predicate's `overrides`, and `render_notes` (226-231) prints one 'overridden by' line per record. An overridden PR therefore appears six times in the release notes, with overrides of checks that can't block.

*Failure scenario:* Suppose a PR like drill #43 merges. The next release's llm-review predicate lists six overrides for it, four of them on advisory or not-applicable checks, and the release notes print '- #43 overridden by @...' six times.

*Suggested fix:* Write the override record only when the decision is OVERRIDDEN, that is, when blocking findings were actually overridden. Alternatively, or as well, dedupe by (by, reason) in attestations.llm_review. The collector's rule that an artifact's override names only its own check still holds.

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, low, trivial): cmd_run appends Override(checks=[check.name]) whenever an override was honoured for the run and the check isn't not_needed, whatever the check's mode or verdict (cli.py:381-389). On audit-log, PRs 33 and 43 each have one override record per check, six for 33 and seven for 43 including the feedback command's own, while only code-review has override_honoured true. The audit-log README calls an override record 'An honoured llm-override'. attestations.llm_review copies every override record of the merged head, and render_notes prints one line each, so an overridden PR would be listed six or seven times.
- **maintainer** (CONFIRMED, low, trivial): cmd_run appends Override(checks=[check]) whenever the override was honoured and the check wasn't not_needed, whatever its mode or verdict. The local audit-log checkout has 6 override records for PR 33 (one per check, workflow-review included) and 7 for PR 43 (plus llm-feedback's). attestations.llm_review copies every override record of the merged head and render_notes prints one line each.
- **impact** (CONFIRMED, low, trivial): cmd_run appends Override(checks=[check]) whenever an override was honoured and the check wasn't not_needed, whatever its mode or verdict, and audit-log shows it: PR #33's run and PR #43's attempt 2 each carry six override records, one per check (workflow-review's was not_applicable), while only code-review had override_honoured true. attestations.llm_review copies every override record of the merged head into the predicate and render_notes prints one line each, so an overridden PR would appear six times, naming checks that can't block. Neither #33 nor #43 merged, so no release shows it yet, and metrics count overridden PRs as a set (unaffected). Cosmetic but permanent once in a predicate: low.

</details>

### F026

**/llm-fp and /llm-ack on a finding from the current run are rejected as unknown_finding until audit-collect has written that run**

- **Status:** open
- **Severity:** low (reviewers: low) · **outcome:** confirmed · **fix cost:** small
- **Where:** `tools/llm-gate/src/llm_gate/feedback.py:187` · **area:** llm-gate and review prompts
- **Reported by:** `api-17` (low, medium confidence)

`find_finding` searches only the gate_run records already on audit-log. A finding's id appears in the sticky comment as soon as that check's job finishes. The collector, though, runs on `workflow_run: completed`, after every job of the run has finished (agent reviews take minutes), and then needs a run of its own. A command posted in that window becomes a permanent `feedback_rejected` record with code unknown_finding, and the commenter gets a confused reaction with no explanation. Ids that an earlier run already reported are found.

*Failure scenario:* The author reads code-review's comment and immediately posts `/llm-fp cr-1a2b wrong line` while security-review is still running. The command is rejected, counted among the rejected commands in the Integrity metric, and has to be posted again after collection.

*Suggested fix:* When the id isn't in the log yet, answer 'not collected yet, try again in a minute' without writing feedback_rejected. Alternatively, accept ids that appear in the sticky comment for the PR's current head and verify them at collection.

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, low, small): llm-feedback.yml exports the audit-log branch when the comment arrives (lines 53-55), and find_finding searches only gate_run records already there. The collector writes a run's records only after the whole llm-review run completes and its own run finishes. In that window, a /llm-fp or /llm-ack on an id from the sticky comment becomes a permanent feedback_rejected (unknown_finding) with a confused reaction, counted in the Integrity metrics. It's a usability gap; the command works when posted again later.
- **maintainer** (CONFIRMED, low, small): feedback.find_finding only searches gate_run records on audit-log, which audit-collect writes after the whole llm-review run completes; a /llm-fp or /llm-ack posted in between becomes a permanent feedback_rejected (unknown_finding) with a bare confused reaction. Requiring a logged finding is deliberate (ADR 0007); the window is a UX defect.
- **impact** (CONFIRMED, low, small): find_finding searches only gate_run records already on audit-log; the sticky comment shows a finding's id as soon as its job finishes, but the collector runs only after the whole llm-review run completes, plus its own run time. A command posted in that window writes a permanent feedback_rejected (unknown_finding) record and a confused reaction whose reason appears only in the job summary. Plausible when someone answers the first comment while agent reviews still run, but the cost is a re-post and one count in the integrity metric: low.

</details>

### F027

**The llm-review attestation doesn't list a PR whose merged head is missing a record for a blocking check**

- **Status:** open
- **Severity:** low (reviewers: low) · **outcome:** confirmed · **fix cost:** small
- **Where:** `tools/llm-gate/src/llm_gate/attestations.py:182` · **area:** llm-gate and review prompts
- **Reported by:** `cr-gate-09` (low, high confidence)

A PR goes into `unreviewed` only when its merged head has no gate_run at all, or when a blocking check's latest verdict is skipped_no_key or error. llm_review doesn't know which checks should be there. A merged head with records for triage and code-review but none for security-review therefore appears in `prs` with security-review simply absent, and not in `unreviewed`. That happens when the job's artifact upload fails, when the collector's PUT gives up after five tries (and its loop exits, dropping the remaining files), or when the collector run fails. ADR 0009 says the attestation 'lists gaps instead of hiding them'.

*Failure scenario:* The collector's write of 123-1-security-review.jsonl fails with repeated 409s, and the PR merges with genuinely green checks. At release the predicate shows checks {code-review: pass}, unreviewed [] and unverified []: the missing security review isn't reported.

*Suggested fix:* Derive each PR's expected blocking checks from its triage record (checks_plan plus the level's blocking set, or a --blocking list from checks.yaml), and list each missing one as unreviewed, for example 'security-review: no record'.

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, low, small): attestations.llm_review lists a PR as unreviewed only when its merged head has no gate_run at all, or when a blocking check's latest verdict is skipped_no_key or error. It never derives the expected checks, so a missing security-review record isn't listed. Partial mitigation: render_notes prints '-' in that check's column when other PRs have it, so the gap shows in the table, though not in the predicate's `unreviewed` list.
- **maintainer** (CONFIRMED, low, small): llm_review lists a PR as unreviewed only with no gate_run for the merged head or a blocking check whose latest verdict is skipped_no_key/error; it never knows which checks should be there, so a merged head missing its security-review record shows up with the check simply absent. The collector's write loop exits on the fifth failed PUT and drops the remaining files. ADR 0009 promises the attestation 'lists gaps instead of hiding them'. Needs an infrastructure failure.
- **impact** (CONFIRMED, low, small): llm_review lists a PR as unreviewed only when its merged head has no gate_run at all or a blocking check's latest verdict is skipped_no_key or error; it doesn't know which checks should exist, so a head with a code-review record but none for security-review shows no gap. Missing records come from rare failures: an artifact upload failing, or the collector's write loop giving up (`exit 1` inside the piped while loop drops the remaining files) or crashing (F005). Those failures leave a red audit-collect run, and a same-day re-run fills the gap, so this is a reporting gap behind an already visible failure: low.

</details>

### F029

**Model-written review text reaches the PR comment and job summary without redaction or markup neutralisation**

- **Status:** open
- **Severity:** low (reviewers: low) · **outcome:** confirmed · **fix cost:** small
- **Where:** `tools/llm-gate/src/llm_gate/report.py:101` · **area:** llm-gate and review prompts
- **Reported by:** `sec-07` (low, high confidence)

`render_markdown` escapes only `|` and newlines inside table cells (`_cell`, line 39-40) and otherwise emits `review.summary`, `f.detail` and `f.suggestion` verbatim into the Markdown that `llm-review.yml` posts as a sticky PR comment and appends to `$GITHUB_STEP_SUMMARY`. Every other sink for text the model or a commenter wrote is scrubbed: audit records through `redact.Scrubbed` types, the triage summary through `cli._inert`, release notes through `attestations._inert`. So the one public sink is the unprotected one: a review steered by injected text in the diff can post links, images, HTML comments or a fake second verdict block as `github-actions[bot]`, and any secret-looking string it emits is published verbatim (see sec-03).

*Failure scenario:* An injected finding's `detail` contains `[click here](http://attacker/?d=<data>)` and a `<!-- llm-gate:security-review -->` marker; the gate posts it as the bot's comment on a public PR, and the marker can collide with another check's sticky comment lookup in `upsert-pr-comment.sh`.

*Suggested fix:* Pass the model's free-text fields through `redact()` plus a one-line/code-span treatment (as `_inert` does) in `render_markdown`, or escape `<`, `>` and `[` in detail and suggestion before rendering.

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, low, small): render_markdown escapes only `|` and newlines in table cells; detail and suggestion go in verbatim, and no field is redacted before the sticky PR comment and job summary, unlike the audit records, triage summary and release notes. One sub-claim is wrong: an injected `<!-- llm-gate:security-review -->` marker can't hijack another check's comment, because upsert-pr-comment.sh selects bot comments whose body startswith the marker, and every rendered body starts with its own marker.
- **maintainer** (CONFIRMED, low, small): render_markdown escapes only '|' and newlines in table cells and emits summary, detail and suggestion verbatim without redact(), while triage reasons (_inert), release notes and audit records are scrubbed. One sub-claim is wrong: upsert-pr-comment.sh picks the bot comment whose body starts with the marker, so a marker injected mid-body can't collide with another check's sticky comment.
- **impact** (CONFIRMED, low, small): render_markdown escapes only | and newlines in table cells and emits summary, detail and suggestion verbatim into the public sticky comment and the job summary, while every other sink for model- or comment-written text goes through redact()/_inert(). sec-07's injected-marker collision doesn't work: upsert-pr-comment.sh and llm-feedback's mark step match only comments whose body starts with the marker, and model text never comes first. What remains is an injection steering the bot's comment (links, images; GitHub sanitises HTML) and the unredacted-secret overlap with F003, both needing injected text inside a collaborator's PR. Low.

</details>

### F032

**The collector's paths for keyless PRs (skipped_no_key) and for a missing triage expectation are untested**

- **Status:** open
- **Severity:** low (reviewers: low) · **outcome:** confirmed · **fix cost:** small
- **Where:** `tools/llm-gate/src/llm_gate/audit.py:760` · **area:** llm-gate and review prompts
- **Reported by:** `tr-16` (low, high confidence)

_risk_problems exempts skipped_no_key gate runs (lines 760-761). Those are the records `audit skip` writes for fork and Dependabot PRs, with the risk from LLM_GATE_RISK. Without the exemption, a skipped check outside the level's plan is flagged as tamper, and a mutation removing it survived. The fallbacks for a missing expectation never run either: line 729 (no triage recomputation) and line 766 (plan taken from the artifact's own checks_plan, blocking unchecked). They apply when compare_files is truncated (300 or more files) or --triage-inputs is absent.

*Failure scenario:* The exemption is dropped. Every Dependabot PR's skipped checks are written as tamper_suspected, and the next release attestation lists those PRs as unverified.

*Suggested fix:* Collector tests with a triage record plus skipped_no_key gate runs for a planned and an unplanned check, and with triage=None plus a valid triage artifact.

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, low, small): Removing the skipped_no_key exemption in _risk_problems survived the full suite. Without it, a keyless PR's skip record would be flagged: a check outside the level's plan as 'not needed but skipped_no_key', and code-review at low on the blocking flag, because skip records carry the configured mode. Reachability mutants that raise at audit.py:729 (no triage expectation) and :766 (plan from the artifact's checks_plan) also survived, so no test reaches either fallback.
- **maintainer** (CONFIRMED, low, trivial): Removing the skipped_no_key exemption in _risk_problems survived the suite; without it every keyless (fork, Dependabot) PR's unplanned checks would be flagged as tamper, since `audit skip` records them as skipped_no_key rather than not_needed. The fallbacks for a missing TriageExpected (no --triage-inputs, or 300+ compare files) are likewise not exercised. Test gap only.
- **impact** (CONFIRMED, low, small): Coverage shows audit.py 761 (the skipped_no_key exemption), 729 and 766 (the fallbacks without a triage expectation) never executed. The exemption is load-bearing for every keyless (Dependabot) PR: without it each skipped check outside the level's plan would become tamper_suspected, but that regression would be loud on the first Dependabot PR. Low.

</details>

### F037

**docs-drift has no eval case, and test-review has only an fp-regression case**

- **Status:** ✅ fixed — #76: a bug case each, with recall in the baseline; a prompt cut down to "report nothing" now takes recall to 0.00 and fails the gate
- **Severity:** low (reviewers: low) · **outcome:** confirmed · **fix cost:** medium
- **Where:** `tools/llm-gate/checks.yaml:326` · **area:** llm-gate and review prompts
- **Reported by:** `tr-27` (low, high confidence)
- **Reviewer's accepted_in:** docs/adr/0006-llm-eval-gate.md

No case names docs-drift, and llm-eval takes its check list from the cases, so docs-drift is never evaluated: a change to llm-docs-drift.md passes vacuously. test-review's only case is fp-tr-835a (forbid only), and it has no baseline, so a test-review prompt that reports nothing passes. Both checks are advisory.

*Failure scenario:* llm-docs-drift.md is cut down to 'report nothing', and llm-eval passes.

*Suggested fix:* Add a docs-drift bug case (for example a renamed just recipe the docs still name) and a test-review missing-test case, with baselines for both.

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, low, medium): No case names docs-drift, and only fp-tr-835a names test-review. cmd_eval takes its check list from the cases, so a change to llm-docs-drift.md is never evaluated, and baseline.json has no docs-drift or test-review entry, so a test-review prompt that reports nothing passes. ADR 0006 acknowledges limited coverage in general ('a reviewer can score well here and miss a new kind of bug'), not checks with no cases at all, so this isn't ACCEPTED. Both checks are advisory, hence low.
- **maintainer** (CONFIRMED, low, small): Counted the committed cases: none names docs-drift, and test-review has only fp-tr-835a (forbid-only, no baseline). llm-eval takes its check list from the cases, so a change to llm-docs-drift.md is 'relevant' and then passes with nothing run. ADR 0006's caveat ('only as good as their coverage') is about kinds of bugs, not about two checks having no recall measure at all; both checks are advisory.
- **impact** (CONFIRMED, low, medium): No case names docs-drift and llm-eval derives its check list from the cases, so docs-drift is never evaluated; test-review has only fp-tr-835a and no baseline entry, so a prompt that reports nothing passes. ADR 0006 only says the cases are as good as their coverage; it doesn't record that whole checks go unevaluated, so I don't count it ACCEPTED. Both checks are advisory, so the cost is a degraded comment: low (fix cost is writing labelled cases and paying for a baseline).

</details>

### F039

**Audit file paths use the date of collection, so re-running audit-collect or llm-feedback on another day writes duplicates**

- **Status:** open
- **Severity:** low (reviewers: low) · **outcome:** confirmed · **fix cost:** small
- **Where:** `tools/llm-gate/src/llm_gate/cli.py:581` · **area:** llm-gate and review prompts
- **Reported by:** `wr-14` (low, high confidence)

collect() writes events/<today>/<run>-<attempt>-<check>.jsonl with day = datetime.now(UTC).date(), because audit-collect passes no --date, and feedback paths also use `now`. In both workflows the append-only guard checks only that exact path. Re-running the collector on a later day, after a failed PUT or an API error, writes every file again under the new date. The gate_run copies keep their ids but double the metrics' run and cost counts, and tamper events get new uuids and count twice in the release's "tamper_suspected (n)".

*Failure scenario:* On 10-17 audit-collect writes 4 of 7 files, then one PUT fails five times. A re-run on 10-18 writes all 7 again under events/2026/10/18/.

*Suggested fix:* Derive the folder from the triggering run (workflow_run.run_started_at or created_at), and from the comment's created_at for feedback, so re-runs hit the same paths.

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, low, small): audit-collect.yml passes no --date, so collect() writes under events/<collection day>/, and llm-feedback's paths use `now`. Both append-only guards check only the exact path, so a re-run on another day (artifacts live 7 days) writes everything again under a new folder. metrics.compute counts runs without deduplicating by record id, and the attestation counts tamper events per record, so duplicates inflate both. Finding and feedback tallies are keyed and unaffected.
- **maintainer** (CONFIRMED, low, small): audit-collect passes no --date, so collect() files records under the day the collector runs, and both writers' append-only guard only checks that exact path; llm-feedback paths use `now` too. A collector re-run on a later day (after a failed PUT, within the 7-day artifact retention) rewrites every file under the new date. metrics.load_records doesn't deduplicate by record id, so run and cost counts double, and the re-collected tamper events get fresh ids.
- **impact** (CONFIRMED, low, small): collect() uses day = datetime.now(UTC).date() (audit-collect.yml passes no --date) and feedback paths use now, while both append-only guards check only the exact path, so a collector re-run on a later UTC day writes every file again under the new date. gate_run copies keep their artifact ids, but metrics count runs and cost per record (only findings are keyed by id), and tamper events get new uuids, doubling a release's tamper_suspected count. It needs a failed collection re-run on another day within the 7-day artifact retention: rare, low.

</details>

### F045

**The allow rules for just, uv run, dotnet and gh run auto-approve arbitrary and irreversible commands, which makes the deny list ineffective**

- **Status:** open
- **Severity:** low (reviewers: medium) · **outcome:** confirmed · **fix cost:** small
- **Where:** `.claude/settings.json:5` · **area:** workflows, release, deploy, scripts
- **Reported by:** `cr-ops-05` (medium, medium confidence), `sec-13` (low, high confidence)

**`cr-ops-05`: The allow rules for just, uv run, dotnet and gh run auto-approve arbitrary and irreversible commands, which makes the deny list ineffective**

Bash(uv run *) approves any command, since `uv run <cmd>` runs whatever it is given. Bash(just *) approves every recipe with any arguments. Recipe parameters are spliced unquoted into shell lines: `just --dry-run test '; echo injected'` prints `dotnet test ; echo injected`, and http and k8s-deploy-release behave the same. `just --yes` skips [confirm]. So `just --yes release X.Y.Z` (an immutable signed tag and a public release with Rekor entries), gh-setup, gh-rulesets, k8s-cluster-down and the paid llm and eval recipes all run without a prompt. Bash(gh run *) also covers `gh run delete`, which removes logs and the 90-day raw-review artifacts, and `gh run rerun`, which spends API credits. The deny rules match by prefix, so `uv run git push --force ...`, `uv run gh secret set ...` and `uv run gh api -X DELETE ...` are allowed, and `git push -f` or `git push origin +ref` don't match `git push --force*` at all. On this machine the user-level sandbox and bash guard limit the damage, but the repository's own config doesn't.

*Failure scenario:* A session in this repository that has been steered by injected text runs `uv run gh secret set ANTHROPIC_API_KEY --body x` or `just --yes release 9.9.9` -> no permission prompt, despite the deny list.

*Suggested fix:* Allow only specific local recipes (e.g. Bash(just ci), Bash(just test*), Bash(just lint*), Bash(just build), Bash(just fmt*)). Replace Bash(uv run *) with narrow forms, and Bash(gh run *) with `gh run view *` and `gh run list *`. Extend the deny list to cover `git push -f*`, `+ref` pushes and `gh api` DELETE in any argument order.

**`sec-13`: `Bash(uv run *)` and `Bash(just *)` pre-approve arbitrary code, paid API calls and repository-settings changes**

The project's permission allowlist contains `Bash(uv run *)` and `Bash(just *)`. `uv run` executes anything (`uv run python -c ...`, `uv run --with <package> ...` installs from PyPI first), so that one rule is equivalent to unrestricted local code execution and dependency installation. `Bash(just *)` covers `just gh-setup`, which pushes the Anthropic key from `pass` into GitHub secrets and rewrites repository settings, labels, security features and the `release` environment (justfile:354-403), `just gh-rulesets`, and the paid `just eval`/`just llm` recipes; the `[confirm]` guards are a prompt on stdin, not an authorisation boundary. The repository's own memory notes that an eval run cost ten times its estimate, so the money side is real.

*Failure scenario:* An agent session that has read injected instructions from a dependency, an issue or a downloaded file runs `uv run python -c "..."` or `just gh-setup` with no prompt, because both match an allow rule.

*Suggested fix:* Narrow the rules to the commands actually wanted (`Bash(uv run --locked pytest*)`, `Bash(uv run --project tools/llm-gate --locked llm-gate list*)`, `Bash(just ci)`, `Bash(just lint*)`, `Bash(just test*)`) and leave `just gh-setup`, `just gh-rulesets`, `just release`, `just eval` and `just llm` to a prompt.

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, low, small): settings.json allows Bash(just *), Bash(dotnet *), Bash(uv run *) and Bash(gh run *). Claude Code's permissions docs say only timeout/time/nice/nohup/stdbuf/command/builtin/noglob and bare xargs are stripped, that a runner rule like Bash(devbox run *) 'matches whatever comes after', and that deny rules match command text and 'aren't a security boundary around the program', so `uv run gh secret set ...` is allowed and not denied. just 1.57.0 has --yes ('Automatically confirm all recipes') and splices recipe arguments unquoted (`just --dry-run test '; echo injected'` prints `dotnet test ; echo injected`). On this machine the session sandbox and the user-level bash guard limit the damage, and the repo has one owner, so low rather than medium.
- **maintainer** (CONFIRMED, low, trivial): .claude/settings.json allows Bash(just *), Bash(uv run *) and Bash(gh run *). Claude Code's permissions doc says uv-run-style runners are not stripped wrappers, so Bash(uv run *) approves any inner command, and deny rules match the command text only, so 'uv run gh secret set ...' or 'git push -f' slip past the deny list. I checked just 1.57.0: --yes skips [confirm], and 'just --dry-run test "; echo injected"' prints 'dotnet test ; echo injected', so parameters splice unquoted. The allowlist is a deliberate convenience (agents are told to run just ci), but its reach to release, gh-setup and the paid recipes isn't recorded anywhere. Low because on this machine the sandbox (pass store and gh token unreadable, SSH and signing outside) and the user-level guard contain most of it; the repo config alone doesn't.
- **impact** (CONFIRMED, low, small): Reproduced: `just --dry-run test '; echo injected'` prints `dotnet test ; echo injected`, and `just --dry-run --yes release 9.9.9` shows the release script with the [confirm] skipped. Claude Code's permissions docs say only timeout/time/nice/nohup/stdbuf/command/builtin/noglob and bare xargs are stripped, environment runners are not, so Bash(uv run *) and Bash(just *) approve any inner command and the deny rules don't see it; the same docs state deny rules 'aren't a security boundary'. Low, not medium: exploitation needs a successfully prompt-injected agent, and the real boundaries on this machine are the bubblewrap sandbox, the bash-guard hook and pinentry for GPG/pass (just release needs a signature, gh-setup a pass decrypt).

</details>

### F046

**Ephemeral containers are tested nowhere: removing them from the images policy leaves every test green**

- **Status:** open
- **Severity:** low (reviewers: medium) · **outcome:** confirmed · **fix cost:** trivial
- **Where:** `deploy/policies/base/images.yaml:25` · **area:** workflows, release, deploy, scripts
- **Reported by:** `tr-10` (medium, high confidence), `cr-ops-17` (low, high confidence)

**`tr-10`: Ephemeral containers are tested nowhere: removing them from the images policy leaves every test green**

ADR 0010 says the policies check init and ephemeral containers, on pods and on pods/ephemeralcontainers, the subresource kubectl debug writes to. kyverno-test.yaml has an init-container case but no ephemeral one. admission-smoke (release.yml) tests the release, edge, a foreign image and an edge init container, but never runs kubectl debug. On a scratch copy of images.yaml without the ephemeralContainers term and without pods/ephemeralcontainers, `kyverno test` still reports 5 passed, 0 failed. Nothing exercises the ephemeral path of release.yaml or llm-review.yaml either. No resource sits outside the calendar-gates namespace, so nothing checks the namespace scoping.

*Failure scenario:* The `+ (has(object.spec.ephemeralContainers) ...)` term or the subresource rule is dropped. `kubectl debug -n calendar-gates <pod> --image=docker.io/library/busybox` then attaches an arbitrary image to a release pod, and lint and release stay green.

*Suggested fix:* Add a Pod with a foreign ephemeralContainers image to resources.yaml (expected fail), and a pod in another namespace (expected skip). In admission-smoke, run `kubectl debug` with $IMAGE:edge against the release pod and assert it is refused.

**`cr-ops-17`: The offline policy tests cover five pod shapes of one base policy; the dev overlay and several match paths are untested**

kyverno-test.yaml tests only calendar-gates-images from base/, on pods with containers and one init container. Not covered: ephemeral containers (the case the policies and ADR 0010 call out), a pod outside calendar-gates (which must not be judged), image volumes (cr-ops-01 would have shown up as a failing negative case), and the dev overlay. That overlay's JSON patch rewrites the namespace selector and validationActions (dev/kustomization.yaml:9-17), and lint-policies only checks that kustomize renders it. admission-smoke covers the image policies and part of the dev overlay, but only when a release runs.

*Failure scenario:* A change that drops ephemeralContainers from variables.images, or leaves calendar-gates-images-dev selecting the wrong namespace, passes just lint-policies and the lint job in ci.yml.

*Suggested fix:* Add pods with ephemeralContainers, with an image volume, and in another namespace. Run kyverno test on the rendered output (kubectl kustomize deploy/policies) so the -dev policies are tested too.

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, low, small): kyverno-test.yaml covers only images.yaml with five pods (containers and one init container), and admission-smoke tests edge, a foreign image and an edge init container but never kubectl debug or ephemeralContainers. Reproduced with kyverno 1.19.1: a copy of images.yaml without the ephemeralContainers term and without pods/ephemeralcontainers still reports '5 tests passed and 0 tests failed'; an added foreign-ephemeral pod (expected fail) passes against the real policy, so the suggested case would catch the mutation. WRITEUP section 4 claims admission-smoke 'proves it each release', which isn't true for ephemeral containers. The policy code is currently correct, so this is a missing regression test (for a path that already had a real bug, cr-2121): low.
- **maintainer** (CONFIRMED, medium, trivial): Reproduced: a scratch copy of images.yaml without the ephemeralContainers term and without pods/ephemeralcontainers still gives 'kyverno test: 5 passed, 0 failed' (kyverno CLI 1.19.1). admission-smoke (release.yml:432-472) tests edge, a foreign image and an edge init container, never kubectl debug or an ephemeral container. ADR 0010 and the WRITEUP stress ephemeral containers, and WRITEUP §5 lists cr-2121 (kubectl debug ignored) as a real defect fixed before merge, so the regression has no test. A pod with a foreign ephemeralContainers image fails correctly with the real policy in my scratch test, so adding it to resources.yaml is trivial; cr-ops-17's points about the dev overlay and namespace scoping are also accurate.
- **impact** (CONFIRMED, low, trivial): Reproduced on a scratch copy: deleting the ephemeralContainers term and the pods/ephemeralcontainers subresource from base/images.yaml leaves `kyverno test` at 5 passed, 0 failed. Adding one Pod with a foreign ephemeralContainers image (expected fail) passes on the real policy and fails on the mutated one, so the fix is one test resource; admission-smoke never runs kubectl debug either, so WRITEUP 4's 'admission-smoke proves it each release' overstates the ephemeral part. Low: no defect exists today; the cost is a future silent regression of a rule the gate already had to fix once (cr-2121), on a local cluster only the owner can reach.

</details>

### F053

**Re-runs keep the original event's updated_at as pr_event_at, so the turnaround metric includes the time people took to trigger the re-run**

- **Status:** open
- **Severity:** low (reviewers: low) · **outcome:** confirmed · **fix cost:** trivial
- **Where:** `.github/workflows/llm-review.yml:190` · **area:** workflows, release, deploy, scripts
- **Reported by:** `api-20` (low, high confidence), `cr-gate-10` (low, high confidence)

**`api-20`: Re-runs keep the original event's updated_at as pr_event_at, so the turnaround metric includes the time people took to trigger the re-run**

`LLM_GATE_PR_EVENT_AT` is `github.event.pull_request.updated_at`, and a re-run keeps the original event payload, as the workflow itself notes at lines 242-243. metrics.py computes turnaround as finished_at minus pr_event_at for every pass, fail or error run, including cache hits from re-runs. In the audit log the longest turnarounds are re-runs after /llm-override or /llm-risk: PR #43's attempt 2, cache hits at about 1290-1298 s, and PR #47's attempt 2 at about 430 s. The p50 is about a minute. docs/metrics.md defines the metric as 'PR event → review finished'.

*Failure scenario:* A week with several /llm-override or /llm-risk re-runs reports a higher p90 turnaround. The increase measures how long people took to comment, not how long reviews took.

*Suggested fix:* Leave out run_attempt > 1, or cache hits, when metrics.py computes turnaround, or record the attempt's start time for re-runs. Say which in docs/metrics.md.

**`cr-gate-10`: Review turnaround measures re-runs from the original PR event, which inflates p50/p90**

Turnaround is finished_at - pr_event_at, where pr_event_at is github.event.pull_request.updated_at (llm-review.yml:190). A re-run keeps the original event's payload (ADR 0007), and llm-feedback re-runs the whole llm-review run after every /llm-override and /llm-risk; failed jobs also get re-run by hand. Those runs finish in seconds from the cache, but each one counts the time since the original push, as long as its verdict is pass, fail or error.

*Failure scenario:* An override comment two hours after the push re-runs all checks. Each check contributes a turnaround of about two hours, so the Gate health issue's p90 shows hours for a gate that answered in two minutes.

*Suggested fix:* Leave records with run_attempt > 1 or cache_hit true out of turnaround, or measure from the run's own start.

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, low, trivial): metrics.py:110-113 computes turnaround as finished_at - pr_event_at for every pass/fail/error gate_run, with no run_attempt or cache_hit filter, and pr_event_at is github.event.pull_request.updated_at, which a re-run keeps. The local audit-log snapshot (origin/audit-log 413242e) confirms the cited data: the seven longest turnarounds are all attempt-2 re-runs (PR #43 cache hits at 1289-1298 s, PR #47 at 428-434 s). Today's effect is small (overall p90 130 s, 129 s without re-runs), but the metric doesn't measure what docs/metrics.md defines.
- **maintainer** (CONFIRMED, low, trivial): llm-review.yml:190 sets LLM_GATE_PR_EVENT_AT from github.event.pull_request.updated_at, which a re-run keeps (the workflow itself relies on that at 242-243), and metrics.py:108-113 counts every gate_run with verdict pass/fail/error, re-run attempts and cache hits included. So turnaround after a /llm-override or /llm-risk re-run measures the human delay since the original push, not the review, against docs/metrics.md's definition. It skews a reported metric only; excluding run_attempt > 1 or cache hits is a one-line change.
- **impact** (CONFIRMED, low, trivial): LLM_GATE_PR_EVENT_AT is github.event.pull_request.updated_at (llm-review.yml:190) and a re-run keeps the original payload (the workflow says so at 242-243); metrics.py computes turnaround as finished_at - pr_event_at for every pass/fail/error run, cache hits and run_attempt > 1 included. So re-runs after /llm-override or /llm-risk count the human delay. Measured on the local audit-log ref (224 qualifying runs): the 7 re-run records stretch the maximum to 21.6 min (2.6 min without them) but leave p50/p90 at 0.95/2.18 vs 0.94/2.16 min. A real definition bug whose effect today is negligible and grows with more overrides: low.

</details>

### F054

**The deployable unit, the chart, is installed by a mutable version tag and verified by nothing**

- **Status:** open
- **Severity:** low (reviewers: low) · **outcome:** confirmed · **fix cost:** small
- **Where:** `justfile:210` · **area:** workflows, release, deploy, scripts
- **Reported by:** `cr-ops-18` (low, medium confidence), `wr-09` (low, medium confidence)

**`cr-ops-18`: The deployable unit, the chart, is installed by a mutable version tag and verified by nothing**

k8s-deploy-release (and admission-smoke) install oci://ghcr.io/gergodrazsdik/charts/calendar-gates --version X.Y.Z. release.yml pushes the chart without an attestation, and verify-release checks only the image. GHCR tags can be overwritten by anything holding packages: write. Kyverno still verifies the container image, but the chart decides everything else about the pod: command, environment and volumes (see cr-ops-01). ADR 0009's 'a released chart can only pull the attested bytes' holds only for the image reference.

*Failure scenario:* Chart 0.3.1 is re-pushed with an extra volume or a different command -> just verify-release 0.3.1 still passes -> just k8s-deploy-release 0.3.1 deploys the new chart and Kyverno admits it.

*Suggested fix:* Attest the pushed chart's OCI digest in publish (actions/attest with the chart as subject) and verify it in verify-release. Install by that digest, or compare the digest before installing.

**`wr-09`: "X.Y.Z is never moved" holds only inside release.yml: any workflow with packages: write can retag release images or replace the chart, and nothing verifies the chart**

publish refuses to move ghcr.io/...:X.Y.Z, but GHCR tags and OCI chart versions are mutable. The package already accepts pushes from this repository's GITHUB_TOKEN: publish-edge and release push to it. A same-repo PR's modified workflow can request packages: write and push calendar-gates:0.3.1, :0.3 or oci://ghcr.io/gergodrazsdik/charts/calendar-gates version 0.3.1. Kyverno resolves tags to digests and denies unattested pods in the two calendar-gates namespaces. The chart, though, is neither attested nor verified: `just k8s-deploy-release` (and admission-smoke) install whatever chart sits under that version, with the cluster's admin kubeconfig. A replaced chart can therefore run any image in another namespace or change the cluster.

*Failure scenario:* A PR's modified workflow pushes chart version 0.3.1 with an added Deployment in kube-system. The owner later runs `just k8s-deploy-release 0.3.1` and installs it.

*Suggested fix:* Attest the chart (actions/attest on the pushed chart's digest). Have k8s-deploy-release and admission-smoke install the chart by digest after `gh attestation verify`, or at least record the chart digest in the release notes and pin it in the recipe.

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, low, small): k8s-deploy-release (justfile:208-212) and admission-smoke install oci://ghcr.io/gergodrazsdik/charts/calendar-gates by version; release.yml attests only the image digest and verify-release checks only image attestations. GHCR tags are mutable and this repository's GITHUB_TOKEN already pushes these packages (publish), so a same-repo PR workflow requesting packages: write could replace a chart version, and the chart decides command, volumes and any extra resources, including ones outside the Kyverno-policed namespaces. ADR 0009's 'a released chart can only pull the attested bytes' covers only the image reference. Needs write access and a later deploy by the owner, so low.
- **maintainer** (CONFIRMED, low, small): release.yml:340-343 pushes the chart with no attestation, verify-release checks only the four image predicates, and k8s-deploy-release and admission-smoke install the chart by its mutable version. Anything with packages: write on the package (release.yml, publish-edge, or a same-repo PR's modified workflow) can re-push chart X.Y.Z. Kyverno still checks the image, but the chart decides commands, volumes (see F047) and even other namespaces, which the policies don't select. ADR 0009's 'a released chart can only pull the attested bytes' holds only for the chart as first pushed. Low because it needs a deliberately malicious workflow, but attesting the chart digest, or pinning it in the release notes and recipe, is small.
- **impact** (CONFIRMED, low, small): publish pushes the chart with no attestation, verify-release checks only the four image predicates, and k8s-deploy-release and admission-smoke install oci://.../charts/calendar-gates by version, a mutable GHCR tag that any workflow of this repo holding packages: write (including a same-repo PR's own workflow) can overwrite. Kyverno still verifies images in the two namespaces, but a replaced chart can add volumes, commands or resources in other namespaces, installed with the admin kubeconfig. ADR 0009's 'a released chart can only pull the attested bytes' assumes an untampered chart. Needs a collaborator writing a malicious workflow plus a later deploy, local cluster only: low.

</details>

### F056

**k8s-up's restart path neither waits for the API server nor restores the kubeconfig**

- **Status:** open
- **Severity:** low (reviewers: low) · **outcome:** confirmed · **fix cost:** small
- **Where:** `justfile:152` · **area:** workflows, release, deploy, scripts
- **Reported by:** `cr-ops-08` (low, high confidence)

For an existing cluster, k8s-up only runs podman start and prints 'started' (justfile:152-154). kind-local start, which the cluster=local branch calls, waits for /readyz and for the node to be Ready. The project path doesn't, so the documented `just k8s-up k8s-policy-up` (and k8s-deploy or k8s-http) right after a WSL restart hits an API server that is still booting, and fails. The path also never re-exports the kubeconfig. If ~/.local/state/calendar-gates/kubeconfig is missing (the state dir was cleaned, or the cluster was created by hand with kind create cluster --config deploy/kind/cluster.yaml), the cluster starts but every recipe fails because context kind-calendar-gates doesn't exist.

*Failure scenario:* After wsl --shutdown: just k8s-up k8s-policy-up -> podman start returns at once -> helm upgrade --install kyverno fails with 'Kubernetes cluster unreachable'.

*Suggested fix:* After podman start, run `kind export kubeconfig --name {{ cluster }}`, then poll `kubectl --context {{ kube_context }} get --raw /readyz` and run `kubectl wait --for=condition=Ready node --all`, as kind-local start does.

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, low, small): For an existing project cluster k8s-up only runs podman start and prints 'started' (justfile:152-154): no kind export kubeconfig, no /readyz or node-Ready wait, while the cluster=local branch delegates to kind-local start. So `just k8s-up k8s-policy-up` right after a restart can reach an API server that is still booting, and a missing state-dir kubeconfig is never recreated. Not reproduced (no cluster access allowed), but the gap is plain in the code; local convenience only.
- **maintainer** (CONFIRMED, low, trivial): For an existing project cluster, k8s-up only runs podman start and returns (justfile:152-154), while ~/bin/kind-local start polls /readyz and waits for the node to be Ready (lines 47-53). So 'just k8s-up k8s-policy-up' right after a WSL restart can hit a booting API server, and a missing state-dir kubeconfig isn't re-exported. Developer convenience only; copying kind-local's wait is trivial.
- **impact** (CONFIRMED, low, small): For an existing cluster k8s-up only runs `podman start <cluster>-control-plane` and prints 'started' (justfile:152-154): no readyz/node wait and no `kind export kubeconfig`, unlike the cluster=local path that delegates to kind-local start. Right after a WSL restart a chained recipe that talks to the API server (k8s-policy-up, k8s-deploy, k8s-status) can hit an API server that is still starting; k8s-load first rebuilds the image, which usually hides it. Loud failure, a retry fixes it, a missing state kubeconfig is an edge case: low.

</details>

### F057

**cluster=local inherits $KUBECONFIG, so it breaks in exactly the shell setup AGENTS.md suggests**

- **Status:** open
- **Severity:** low (reviewers: low) · **outcome:** confirmed · **fix cost:** trivial
- **Where:** `justfile:13` · **area:** workflows, release, deploy, scripts
- **Reported by:** `cr-ops-09` (low, high confidence)

For cluster=local the justfile sets KUBECONFIG to env('KUBECONFIG', ~/.kube/config). Of the project cluster's kubeconfig, AGENTS.md says 'export KUBECONFIG= that, or use the recipes'. With that export in place, `just --set cluster local --evaluate KUBECONFIG` prints ~/.local/state/calendar-gates/kubeconfig (checked), and that file has no kind-local context. Every cluster=local recipe (k8s-deploy, k8s-http, k8s-status, k8s-down, k8s-deploy-release) then fails with context 'kind-local' not found.

*Failure scenario:* export KUBECONFIG=~/.local/state/calendar-gates/kubeconfig; just cluster=local k8s-load k8s-deploy k8s-http -> helm reports that context "kind-local" does not exist.

*Suggested fix:* For cluster=local, use ~/.kube/config explicitly, since kind-local writes there. Alternatively, export both files (<state file>:~/.kube/config) for every cluster.

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, low, trivial): Reproduced with just --evaluate: with KUBECONFIG=~/.local/state/calendar-gates/kubeconfig exported (as AGENTS.md suggests for the project cluster), `just --set cluster local --evaluate KUBECONFIG` yields that file, while kube_context evaluates to kind-local, whose context lives in ~/.kube/config. Every cluster=local recipe then fails with context 'kind-local' not found. A loud failure in a local workflow, so low.
- **maintainer** (CONFIRMED, low, trivial): Checked with just --evaluate: with KUBECONFIG exported to ~/.local/state/calendar-gates/kubeconfig (what AGENTS.md:35-36 suggests), cluster=local resolves KUBECONFIG to that file, which has no kind-local context. Without the export it resolves to ~/.kube/config. So the two documented setups conflict, and every cluster=local recipe fails in the suggested shell. Using ~/.kube/config explicitly for local is trivial.
- **impact** (CONFIRMED, low, trivial): Reproduced: with KUBECONFIG=~/.local/state/calendar-gates/kubeconfig exported (as AGENTS.md suggests), `just --set cluster local --evaluate KUBECONFIG` prints the state file while kube_context evaluates to kind-local, a context that file never contains (kind-local writes ~/.kube/config). Every cluster=local recipe then fails with 'context kind-local does not exist'. Loud, harmless, and only in a shell with that export: low.

</details>

### F069

**No test exercises the admission rule 'no critical vulnerabilities'**

- **Status:** ✅ fixed — #75: the clause is evaluated offline over mock predicates, and a script keeps that copy identical to the policy's
- **Severity:** low (reviewers: low) · **outcome:** confirmed · **fix cost:** medium
- **Where:** `deploy/policies/base/release.yaml:61` · **area:** workflows, release, deploy, scripts
- **Reported by:** `tr-26` (low, medium confidence)
- **Reviewer's accepted_in:** docs/adr/0010-admission-control.md

calendar-gates-release requires results.all(r, r.counts.critical == 0). The offline tests cover only images.yaml. admission-smoke proves that an attested release is admitted and unattested images are denied, but it never presents an attested image whose scan lists criticals. A CEL condition that is always true would pass everything.

*Failure scenario:* The clause is edited to `r.counts.critical >= 0`. An image whose scan attestation lists criticals is admitted, and lint and admission-smoke still pass.

*Suggested fix:* Test the expression on its own against sample predicates (critical 0 and 1), for example a small CEL harness or a kyverno CLI test with a mocked payload if the CLI supports one.

<details><summary>Council</summary>

- **skeptic** (ACCEPTED, info, medium): Correct that nothing exercises `counts.critical == 0`, but no genuine attestation can carry a critical: .grype.yaml has fail-on-severity: high, attest needs scan, and the predicate counts only non-ignored matches, so every vuln-scan attestation release.yml makes has critical 0 by construction; the clause is the 'backstop' ADR 0010 describes. Testing it needs an attestation signed with the release identity (keyless), which can't be made offline, and ADR 0010 records that kyverno test covers only the policy needing no registry while admission-smoke proves the image policies. So the gap is the recorded test scope, and a broken clause would have no reachable effect today.
- **maintainer** (CONFIRMED, low, medium): Nothing exercises results.all(r, r.counts.critical == 0) (release.yaml:58-62): kyverno-test.yaml covers only images.yaml, and admission-smoke proves an attested release is admitted and unattested images are denied, never an attested image with criticals. ADR 0010 accepts that the image policies are only tested by admission-smoke, but not that this clause stays untested, so it's not ACCEPTED. Low because the clause is the documented backstop (CI already fails on high), and testing it needs a CEL harness or a mocked payload rather than a real attested image with criticals.
- **impact** (CONFIRMED, low, medium): No test exercises results.all(r, r.counts.critical == 0): kyverno-test.yaml covers only images.yaml and admission-smoke presents only an attested release (critical 0) and unattested images. The clause is a backstop that the unmodified pipeline can't reach (scan fails on high, so attest never sees criticals); it matters only if .grype.yaml's threshold is loosened, which is when a silent '>= 0' mutation would hurt. Testing needs a CEL harness or mocked payloads (the CLI can't verify attestations offline): medium fix, low severity.

</details>

### F071

**The version tags, the moving X.Y tag and the chart are pushed before admission-smoke and smoke run**

- **Status:** open
- **Severity:** low (reviewers: low) · **outcome:** confirmed · **fix cost:** small
- **Where:** `.github/workflows/release.yml:326` · **area:** workflows, release, deploy, scripts
- **Reported by:** `wr-10` (low, high confidence)

publish promotes the digest to X.Y.Z and X.Y and pushes the chart. admission-smoke and smoke run after that, and only smoke publishes the GitHub Release. A failed smoke leaves a draft release, but the image tags and the chart are already public, and X.Y.Z can't be reused, so the version is burnt. X.Y (e.g. 0.3) already points at the failing bytes for anyone who pulls the minor tag. smoke needs only IMAGE@DIGEST and could run before publish, and admission-smoke could install the local chart with --set image.digest. ADR 0009 fixed this for scan failures, not for smoke failures. Also, docs/gates.md's "re-running the workflow refreshes it" holds only when publish itself is re-run. A full re-run builds new bytes and stops at the promote step, and "re-run failed jobs" never re-runs publish.

*Failure scenario:* Release 0.3.2: publish moves :0.3 to the new digest, then smoke fails on /api/version. The release stays a draft, :0.3 serves the failed build, and 0.3.2 can't be released again.

*Suggested fix:* Run smoke, and admission-smoke with the local chart, on the digest before publish, or at least move X.Y only after smoke passes. Fix the re-run wording in docs/gates.md.

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, low, small): publish promotes the digest to X.Y.Z and, for final versions, X.Y and pushes the chart (release.yml:313-343); admission-smoke and smoke run only after it (needs: publish). A failed smoke leaves a draft release, but the version tags, the moved X.Y and the chart are public, and X.Y.Z can't be reused: the same burnt-version problem ADR 0009 fixed for scan failures, while gates.md only says 'a failed smoke leaves a draft'. The re-run note is imprecise too: a full re-run builds new bytes and fails at promote, and 're-run failed jobs' re-runs only smoke, so the draft refresh needs a re-run of publish itself.
- **maintainer** (CONFIRMED, low, small): publish (release.yml:313-343) moves X.Y.Z and, for finals, X.Y and pushes the chart before admission-smoke and smoke run, so a failed smoke leaves a draft release but public tags, a moved minor tag and a chart, and burns the version. ADR 0009 orders publish before smoke and only promises a clean state for a failed scan; admission-smoke needs a published chart by design, but smoke only needs IMAGE@DIGEST and could run before publish. The docs/gates.md line 're-running the workflow refreshes it' holds only when publish itself is re-run: a full re-run builds new bytes and stops at the promote check. Low: nothing here consumes :X.Y, and the chart pins the digest.
- **impact** (CONFIRMED, low, small): publish promotes X.Y.Z and X.Y and pushes the chart before admission-smoke and smoke, and only smoke publishes the release, so a smoke failure leaves public version tags, a moved X.Y and a chart that k8s-deploy-release will install and Kyverno admit, while the version can't be reused. The docs' 're-running the workflow refreshes it' holds only for re-running publish: a full re-run rebuilds new bytes and stops at the promote guard, 're-run failed jobs' skips publish. Smoke failures are rare (build-test, http-tests and scan already passed on the same Dockerfile) and nobody pulls :X.Y here: low.

</details>

### F072

**pr-title isn't re-checked when the title is edited, so the check can stay green on a title that isn't a Conventional Commit**

- **Status:** open
- **Severity:** low (reviewers: low) · **outcome:** confirmed · **fix cost:** small
- **Where:** `.github/workflows/ci.yml:6` · **area:** workflows, release, deploy, scripts
- **Reported by:** `wr-12` (low, high confidence)

ci.yml's pull_request trigger uses the default types (opened, synchronize, reopened), and the job reads the title from the event payload, which a re-run keeps. The squash commit's title is the PR title at merge time (gh-setup sets squash_merge_commit_title=PR_TITLE). docs/gates.md covers only the opposite direction: fixing a red title needs a push.

*Failure scenario:* The title `feat: add leap endpoint` passes. Before merging, someone edits it to `WIP stuff`. No run starts, pr-title stays green, and main gets a non-conventional commit.

*Suggested fix:* Move pr-title into its own workflow on pull_request types [opened, edited, synchronize, reopened]. Add that workflow to the consistency script's WORKFLOWS and drop pr-title from gates.needs.

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, low, small): ci.yml's pull_request trigger sets no types, so the defaults (opened, synchronize, reopened) apply and a title edit (`edited`) starts no run, while pr-title reads the title from the event payload. A title edited after the last push keeps a green pr-title and becomes the squash subject (squash_merge_commit_title=PR_TITLE). gates.md notes only the opposite direction ('title edits alone don't re-run CI' when fixing a red title), which isn't a recorded acceptance of this consequence.
- **maintainer** (CONFIRMED, low, small): ci.yml's pull_request trigger uses the default types (no edited), and pr-title reads the title from the event payload, so editing a passing title to a non-conventional one leaves the check green. docs/gates.md documents the cause ('title edits alone don't re-run CI') only for fixing a red title, not this consequence, and it isn't in an ADR. Low: the owner merges, and the squash dialog lets the merger edit the subject anyway. A separate pr-title workflow with edited, plus the consistency-script update, is small.
- **impact** (CONFIRMED, low, small): ci.yml's pull_request trigger uses the default types (opened, synchronize, reopened), pr-title reads the title from the event payload, and the squash subject is the PR title at merge time (gh-setup: squash_merge_commit_title=PR_TITLE). docs/gates.md covers only the red-to-fixed direction. An edit from a green title to a non-Conventional one before merging stays green. Cosmetic result on main: low.

</details>

### F073

**Records are dropped when an llm-review run completes after its PR was merged**

- **Status:** open
- **Severity:** low (reviewers: low) · **outcome:** confirmed · **fix cost:** trivial
- **Where:** `.github/workflows/audit-collect.yml:58` · **area:** workflows, release, deploy, scripts
- **Reported by:** `wr-13` (low, medium confidence)

workflow_run.pull_requests lists only open PRs that match the head (GitHub's workflow run object), and the fork fallback keeps only `.state == "open"` from commits/<sha>/pulls. The advisory llm jobs aren't required, and gh-setup enables auto-merge, so a PR can merge while test-review, docs-drift or workflow-review are still running. When that run completes, the PR is closed: PR_FROM_EVENT is empty, the fallback finds nothing, and the job stops with "No open PR ... nothing to collect". Every record of that run is lost, the blocking checks' included, and the release attestation then reports the merged head as unreviewed ("no review record for the merged head").

*Failure scenario:* Auto-merge is on. llm / code-review and security-review pass, ci finishes and the PR merges. llm / docs-drift finishes 30 s later, and audit-collect collects nothing for the merged head.

*Suggested fix:* In the fallback, accept the PR whose head.sha equals HEAD_SHA in any state, closed and merged included.

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, low, trivial): GitHub's OpenAPI description (rest-api-description, workflow-run schema) defines pull_requests as 'Pull requests that are open with a head_sha or head_branch that matches the workflow run', and the collector's fallback keeps only state == open from commits/{sha}/pulls (audit-collect.yml:55-63), which per GitHub's docs returns the merged PR too. So a run that completes after its PR merged (advisory llm jobs aren't required, auto-merge is enabled, and /llm-override re-runs happen when CI is already green) ends with 'No open PR ... nothing to collect' and loses every record of that attempt, blocking checks included. Timing-dependent, so low.
- **maintainer** (CONFIRMED, low, trivial): GitHub's OpenAPI description of a workflow run's pull_requests reads 'Pull requests that are open with a head_sha or head_branch that matches the workflow run', and the collector's fallback (audit-collect.yml:57-58) also keeps only state == open. So when the PR merges before the llm-review run completes, the job exits with 'No open PR ... nothing to collect' and every record of that run is lost, the blocking ones included. That is possible because advisory llm jobs aren't required and gh-setup enables auto-merge; the likeliest case is a /llm-override re-run, whose cache-hit jobs finish seconds apart once everything else is green. Then the override record is lost and the attestation shows the earlier fail for the merged head. Rare with today's timings (ci.yml's k8s-smoke usually outlasts the reviews), hence low; accepting the PR whose head.sha matches in any state from commits/<sha>/pulls is trivial.
- **impact** (CONFIRMED, low, trivial): Checked against the public API: the llm-review run of merged PR #53 now reports pull_requests: [] and commits/<sha>/pulls lists #53 as closed, so for a run that completes after its merge both PR_FROM_EVENT and the state == open fallback come up empty, the job exits 'nothing to collect' and every record of that run is lost, blocking checks included; the attestation then calls the merged head unreviewed. Only advisory checks can still run at merge time; auto-merge (enabled by gh-setup) or a quick merge after a cache-fast re-run makes the race possible. But all 22 PRs merged since the audit log began have full records on their merged head, and the failure errs towards reporting a gap, visibly: low.

</details>

### F074

**The consistency check validates the main.json file, not the live ruleset, and ignores job-level if:**

- **Status:** open
- **Severity:** low (reviewers: low) · **outcome:** confirmed · **fix cost:** small
- **Where:** `scripts/check-ruleset-consistency.py:66` · **area:** workflows, release, deploy, scripts
- **Reported by:** `wr-15` (low, high confidence)

lint compares .github/rulesets/main.json with the workflows and checks.yaml, but the ruleset on GitHub changes only when someone runs `just gh-rulesets` by hand. A merged PR that makes a check blocking, and adds it to main.json as the check demands, leaves it unenforced until then, and the check is green either way. job_check_names also ignores `if:` on the jobs that produce required names. A skipped required job counts as passing, and gates covers only ci.yml, so a later `if:` on the llm or llm-eval job would pass review here.

*Failure scenario:* A PR makes test-review blocking at high and adds `llm / test-review` to main.json. lint passes and the PR merges, nobody runs gh-rulesets, and high-risk PRs merge with llm / test-review failing.

*Suggested fix:* Add a scheduled or post-merge job that GETs repos/{repo}/rulesets and diffs the result with the file (read-only). Have the script flag any if: on jobs that produce required contexts, allowlisting pr-title.

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, low, small): check-ruleset-consistency.py compares main.json with the workflows and checks.yaml and never reads the live ruleset (its docstring says it catches drift 'before the ruleset is applied'); the live ruleset changes only through a manual `just gh-rulesets`, so a merged change that makes a check blocking stays unenforced until someone runs it. job_check_names also ignores job-level if:, but that sub-claim is only half right: an if: on the llm matrix job would skip it before matrix expansion and fail closed (unexpanded name, as in F051), while on llm-eval (a plain job) a skipped job would count as passing. Low.
- **maintainer** (CONFIRMED, low, small): check-ruleset-consistency.py reads only .github/rulesets/main.json (lines 65-74), and its docstring says it catches problems 'before the ruleset is applied'. Applying is a manual just gh-rulesets, so a merged main.json change can stay unenforced with lint green, and nothing compares the file with the live ruleset. job_check_names also ignores job-level if:. For the llm matrix job a skip reports the unexpanded name and fails closed, but a skipped llm-eval job (fixed name, outside gates) would satisfy its required context. Manual apply is the documented process, but this drift isn't an accepted consequence; a read-only GET of the rulesets in a scheduled job, plus an if: check, is small.
- **impact** (CONFIRMED, low, small): check-ruleset-consistency.py compares .github/rulesets/main.json with the workflows and checks.yaml; the live ruleset changes only when someone runs `just gh-rulesets`, which docs/gates.md documents as manual, and job_check_names ignores job-level if:. Both gaps are real: a merged change to main.json can stay unenforced, and an if: on the llm or llm-eval job would turn a required check into a skipped (passing) one without this lint noticing. Either needs a reviewed merge to main by the owner: low.

</details>

### F075

**GH_TOKEN with contents: write is set for the whole collect job, including the step that parses untrusted artifacts**

- **Status:** open
- **Severity:** low (reviewers: low) · **outcome:** confirmed · **fix cost:** trivial
- **Where:** `.github/workflows/audit-collect.yml:34` · **area:** workflows, release, deploy, scripts
- **Reported by:** `wr-16` (low, high confidence)

llm-feedback.yml deliberately sets GH_TOKEN only on the steps that call the API. audit-collect sets it in the job's env, so `llm-gate audit collect` and `llm-gate list` run with a token that can push to audit-log, and to any other branch without rules, while they parse artifacts the PR's workflow wrote. No exploitable parser bug is known; this is about blast radius. metrics.yml does the same with issues: write.

*Failure scenario:* A bug in how llm-gate audit collect parses a crafted artifact would hand the attacker a contents: write token instead of nothing.

*Suggested fix:* Set GH_TOKEN only on the Find the PR, Download, Gather and Write steps.

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, low, trivial): audit-collect.yml:34 sets GH_TOKEN (contents: write, plus actions/issues/pull-requests read) in the job env, so the uv-installed llm-gate that parses untrusted artifacts (audit collect, list) runs with it, while llm-feedback.yml deliberately scopes GH_TOKEN per step. No parser exploit is known; it's blast-radius hardening, so low.
- **maintainer** (CONFIRMED, low, trivial): audit-collect.yml:33-34 sets GH_TOKEN (contents: write, actions/issues/pull-requests read) in the job env, so 'llm-gate audit collect' parses the PR-written artifacts with the write token in its environment. llm-feedback.yml scopes GH_TOKEN to the steps that call the API, so the hardening is inconsistent. No parser bug is known, and on a hosted runner a code-execution bug could still reach the token by other means, so it's defence in depth only. Moving GH_TOKEN to the Find/Download/Gather/Write steps is trivial.
- **impact** (CONFIRMED, info, trivial): audit-collect.yml:34 sets GH_TOKEN (contents: write) for the whole job, so llm-gate audit collect parses untrusted artifacts with it in the environment, unlike llm-feedback's per-step scoping. Info: the parser is pydantic/JSON in Python with no known exploitable bug, code execution in any step on a hosted runner could recover the job token anyway (sudo, runner memory), and main is protected by a no-bypass ruleset, so step scoping is hygiene, not a boundary.

</details>

### F076

**Dependabot's uv updates for tools/llm-gate will stall at the fixed exclude-newer date in pyproject.toml**

- **Status:** open
- **Severity:** low (reviewers: low) · **outcome:** confirmed · **fix cost:** small
- **Where:** `.github/dependabot.yml:30` · **area:** workflows, release, deploy, scripts
- **Reported by:** `wr-18` (low, medium confidence)

tools/llm-gate/pyproject.toml sets [tool.uv] exclude-newer = "2026-10-01T00:00:00Z", with the note "Move the date forward when updating dependencies". Dependabot's uv updater re-locks with uv, which honours exclude-newer, so it can't resolve any version published after 2026-10-01. Once releases are newer than that date, uv version updates and Dependabot security updates for anthropic, claude-agent-sdk, pydantic and the rest stop resolving, on top of the 14-day cooldown, and the failures appear only in Dependabot's logs. No Dependabot PR has been merged in the repository yet, so this is untested. scripts/check-ruleset-consistency.py, a PEP 723 script with its own exclude-newer and lock, isn't covered by Dependabot at all.

*Failure scenario:* A security fix for pydantic is released in November. Dependabot can't produce a lock that satisfies exclude-newer = 2026-10-01, opens no PR, and the vulnerable version stays.

*Suggested fix:* Rely on Dependabot's cooldown and drop the fixed date, or move it from a scheduled update job. Document that a manual `uv lock --upgrade` has to move it, and cover the script's lock file.

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, low, small): tools/llm-gate/pyproject.toml pins [tool.uv] exclude-newer to the absolute date 2026-10-01 ('Move the date forward when updating dependencies'), while dependabot.yml has a uv entry for that directory with a 14-day cooldown; uv honours exclude-newer when it locks, and uv's own Dependabot guide warns that exclude-newer without a matching cooldown leads to 'pull requests where uv would not be able to lock the dependencies'. With a fixed date the gap only grows, so version and security updates for llm-gate stall unless someone moves the date by hand, and the PEP 723 script lock isn't covered by Dependabot at all. Whether Dependabot errors or opens an unlockable PR is unverified, but either way no working update arrives.
- **maintainer** (CONFIRMED, low, small): tools/llm-gate/pyproject.toml pins exclude-newer to the fixed date 2026-10-01, with a note to move it by hand, while dependabot.yml has a uv updater (14-day cooldown) for the same directory. Dependabot relocks with uv, which honours [tool.uv] exclude-newer. uv's own Dependabot guide and public reports describe exactly this failure ('can't resolve your Python dependency files'). So version and security updates for anthropic, claude-agent-sdk, pydantic and the rest stop resolving once releases pass the date, with failures only in Dependabot's logs. The manual bump is the stated intent, but the Dependabot config then promises updates it can't deliver. uv 0.13 accepts a rolling window (exclude-newer = "14 days") matching the cooldown; check it against CI's --locked runs. The PEP 723 script's lock isn't covered by Dependabot either.
- **impact** (PLAUSIBLE, low, small): tools/llm-gate/pyproject.toml has [tool.uv] exclude-newer = 2026-10-01T00:00:00Z, which uv applies to every lock, so any re-lock Dependabot's uv updater performs can't pick versions published after that date: version and security PRs stop appearing, visible only in Dependabot's logs. Dependabot's exact invocation I can't verify offline. Low: the date is a deliberate supply-chain brake with a 'move it forward' note, updates still happen by hand, and the tool only runs in CI.

</details>

### F083

**The coverage metric doesn't count triage's not_needed verdict as a decision, so every merged low-risk PR shows as not covered**

- **Status:** open
- **Severity:** low (reviewers: medium) · **outcome:** confirmed · **fix cost:** small
- **Where:** `tools/llm-gate/src/llm_gate/metrics.py:18` · **area:** API, tests, docs
- **Reported by:** `api-03` (medium, high confidence), `cr-gate-08` (low, high confidence), `tr-11` (medium, medium confidence), `dd-19` (low, high confidence)

**`api-03`: The coverage metric doesn't count triage's not_needed verdict as a decision, so every merged low-risk PR shows as not covered**

`REAL_VERDICTS = {pass, fail, not_applicable}` dates from #41. #46 added the `not_needed` verdict to the audit schema (audit.GateVerdict) and left this set unchanged. Coverage (lines 119-126) requires every check in the static `blocking_checks` (checks.yaml `mode: blocking`: code-review and security-review) to have one of those verdicts. At risk low, security-review isn't in the plan and records `not_needed`, and code-review runs as advisory. Calling `metrics.compute` on a merged PR whose runs are code-review `pass` plus security-review `not_needed` (both risk low) gives coverage 0.0 and lists the PR as uncovered. docs/metrics.md:14 defines coverage with the same three verdicts and doesn't mention not_needed. The only low-risk PRs in the audit log (#47 and #49) are unmerged drills, so WRITEUP's 100% still holds. The first human docs-only PR that merges will break it.

*Failure scenario:* A human-authored docs PR is merged. Triage rates it low: security-review is not_needed and code-review passes as advisory. `just metrics` and the weekly Gate health issue list it under 'not covered' and lower the coverage figure, although every gate behaved as configured.

*Suggested fix:* Count `not_needed` as a decision, since the policy decided the check wasn't needed. Alternatively, measure coverage against the blocking set of each PR's triage level. Update docs/metrics.md and add a test with a merged low-risk PR.

**`cr-gate-08`: The coverage metric counts every correctly triaged low-risk PR as not covered**

Coverage requires each check in blocking_checks (the configured blocking set: code-review, security-review) to have a verdict in REAL_VERDICTS = pass, fail, not_applicable. Since triage (ADR 0008), a low-risk PR's security-review is not_needed by design and its code-review is advisory, so such a PR can never be covered. Verified: one merged PR with triage final_risk low, code-review pass (blocking false) and security-review not_needed gives coverage 0.0, uncovered [7]. docs/metrics.md puts not_needed in neither list. At low risk the set of blocking checks is empty, so the PR should count as covered.

*Failure scenario:* After a week of docs-only PRs (risk:low), the Gate health issue shows coverage dropping toward 0%, with every docs PR listed as 'not covered', although every required check reported as designed.

*Suggested fix:* Use the checks that block at the PR's risk (gate_run.blocking of the latest runs, or the triage record's plan) and count not_needed as decided. Add a test for it.

**`tr-11`: Coverage counts every merged low-risk PR as uncovered (`not_needed` isn't a decision); no test has triage verdicts**

REAL_VERDICTS is pass, fail and not_applicable, and coverage requires every check in checks.yaml's static blocking set (line 124). At risk low, security-review's gate_run has the verdict not_needed, which never counts. Run through the real module, a merged PR with code-review pass (advisory, risk low) and security-review not_needed gives coverage 0.0 and uncovered [1]. test_coverage_counts_merged_prs_where_every_blocking_check_decided has no not_needed or risk case. Neither docs/metrics.md nor the PLAN's definition ('not skipped_no_key/error') treats not_needed as a gap.

*Failure scenario:* A docs-only PR (drill 17, risk:low) merges. The Gate health issue lists it as not covered and coverage drops, although every check did what triage decided.

*Suggested fix:* Count not_needed as decided, or judge coverage against the PR's triage plan. Add coverage tests with a low-risk PR (not_needed) and a medium-risk PR.

**`dd-19`: The Coverage metric predates triage: not_needed counts as no decision, so merged low-risk PRs show as uncovered**

metrics.md defines Coverage as "every blocking check has a gate_run with a real verdict (pass, fail, not_applicable; not skipped_no_key or error)" and says nothing about `not_needed`. metrics.py:18 REAL_VERDICTS = {pass, fail, not_applicable}, and cmd_metrics passes checks.yaml's static blocking set (code-review, security-review). At risk low, triage plans only code-review and docs-drift, so security-review is recorded `not_needed` (cli._at_risk), and the PR is counted as not covered. WRITEUP's 100% holds only because the two low-risk PRs (#47, #49) were drills and never merged.

*Failure scenario:* A docs-only PR without AI markers is triaged low and merged. The next Gate health issue reports coverage below 100% and lists it under "not covered", though every check its level needed reached a decision.

*Suggested fix:* Either define it in metrics.md ("`not_needed` counts as decided: the level didn't call for the check") and add not_needed to REAL_VERDICTS, or document that low-risk PRs count as uncovered.

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, low, small): Reproduced with llm_gate.metrics.compute. A merged PR whose code-review passed (advisory, risk low) and whose security-review is not_needed gives coverage 0.5, with that PR listed as uncovered. The cause: REAL_VERDICTS (metrics.py:18) lacks not_needed, and cmd_metrics passes the static blocking set from checks.yaml. docs/metrics.md:14 doesn't mention not_needed, and no ADR accepts it. The bug is latent today. The only low-risk PRs in the audit log (#47 after /llm-risk, and #49) are unmerged drills, and AI markers raise most PRs here above low, so it bites only on human-authored docs or tests PRs. It distorts reporting, not gating.
- **maintainer** (CONFIRMED, medium, small): `REAL_VERDICTS` (metrics.py:18) leaves out `not_needed`, and cmd_metrics passes the static blocking set (code-review, security-review). At risk low, triage records security-review as `not_needed` (ADR 0008 point 5). I ran metrics.compute on a merged low-risk PR (code-review advisory pass, security-review not_needed) plus a merged medium PR: coverage 0.5, uncovered [7]. PLAN-v2 16.2 defines coverage as 'a real verdict (not skipped_no_key/error)', so a policy decision should count, and no ADR or Status line accepts this. One detail in api-03 is off: `not_needed` has been in GateVerdict since #28; #46 only started recording it.
- **impact** (CONFIRMED, low, small): metrics.py:18 REAL_VERDICTS excludes `not_needed`, and coverage (lines 119-126) requires the static blocking set that cmd_metrics takes from checks.yaml; at risk low security-review isn't in `levels.low.run`, so it records `not_needed`. Running the real metrics.compute on a merged low-risk PR (code-review pass, security-review not_needed) next to a medium one gives coverage 0.5, uncovered [7]. Impact is narrow: in the audit log only #47 and #49 were ever rated low and neither merged, and the AI raise lifts nearly every docs/tests PR here to medium, so it takes a human-only docs or tests PR; then the Gate health issue lists it as not covered although every gate did what its level required. A misleading metric, not a weakened gate, so low (api-03 and tr-11's medium overstate it); all four reports are right on the mechanism.

</details>

### F085

**The workdays range guard near year 9999 (start year above 9989) has no test**

- **Status:** open
- **Severity:** low (reviewers: medium) · **outcome:** confirmed · **fix cost:** trivial
- **Where:** `src/CalendarGates.Api/Endpoints/WorkdaysEndpoints.cs:34` · **area:** API, tests, docs
- **Reported by:** `tr-12` (medium, high confidence)

The endpoint caps the range at start.AddYears(10). For start years 9990-9999 it uses DateOnly.MaxValue instead, because AddYears would go past year 9999 and throw. Neither WorkdaysTests nor calendar.http has a request with a start year above 9989; the maximum-span test starts at 2026-02-12. The leap-day limit (start 2024-02-29 caps at 2034-02-28) is untested too. The prompt names the 1583 to 9999 range as an edge to test.

*Failure scenario:* The ternary is simplified to `start.AddYears(MaxSpanYears)`. GET /api/workdays?from=9995-01-01&to=9999-12-31 then throws ArgumentOutOfRangeException and returns 500 instead of 200, and all tests pass.

*Suggested fix:* Integration tests: from=9995-01-01&to=9999-12-31 gives 200 with workdays 1305, and from=9989-12-31&to=9999-12-31 gives 200 with 2610 (both computed independently in Python). Optionally from=2024-02-29&to=2034-03-01 gives 400.

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, low, small): The guard (WorkdaysEndpoints.cs:34-37) works today. from=9995-01-01&to=9999-12-31 returns 200 with 1305, and from=9989-12-31&to=9999-12-31 returns 200 with 2610. A leap-day start of 2024-02-29 caps at 2034-02-28, so 2034-03-01 gets a 400. No unit, integration or .http test uses a start year above 9989 (the max-span tests start at 2026-02-12 and 2020-01-01). Replacing the ternary with start.AddYears(10) would therefore turn those requests into 500s with every test green. This is a missing edge-case test for correct code, which the repo's code-review scale rates low.
- **maintainer** (CONFIRMED, low, trivial): For start years above 9989, WorkdaysEndpoints.cs:34-37 uses DateOnly.MaxValue as the limit. No unit, integration or .http test has a start year after 2026 (the maximum-span tests start 2026-02-12). On the built API, from=9995-01-01&to=9999-12-31 gives 1305 and from=9989-12-31&to=9999-12-31 gives 2610, which matches an independent Python count. So the code is right and only the regression test is missing. Low for a correct, rarely hit branch of the playground API.
- **impact** (CONFIRMED, low, trivial): WorkdaysEndpoints.cs:34-37 caps start years above 9989 at DateOnly.MaxValue, and no integration test or .http request starts later than 2026-02-12, so simplifying the ternary to `start.AddYears(10)` would turn from=9995-01-01 into an ArgumentOutOfRangeException (500) with every test green. The guard is correct today: my build returns 200 with 1305 for 9995-01-01..9999-12-31 and 2610 for 9989-12-31..9999-12-31, matching the report, and the 2024-02-29 limit gives 200 at 2034-02-28 and 400 at 2034-03-01. A missing edge-case test for correct code, with only far-future inputs at stake: low rather than medium.

</details>

### F086

**OpenAPI documents workdays' from/to as optional plain strings and week's {date} without a date format**

- **Status:** open
- **Severity:** low (reviewers: low) · **outcome:** confirmed · **fix cost:** small
- **Where:** `src/CalendarGates.Api/Endpoints/WorkdaysEndpoints.cs:19` · **area:** API, tests, docs
- **Reported by:** `api-06` (low, high confidence), `cr-api-03` (low, high confidence)

**`api-06`: OpenAPI documents workdays' from/to as optional plain strings and week's {date} without a date format**

`Count(string? from, string? to)` produces query parameters with no `required` and the schema `{type: string}`. Leaving either out returns 400 'A date is required (yyyy-MM-dd).' (verified). The path parameter of `/api/week/{date}` (WeekEndpoints.cs:19) is also just `{type: string}`. The contract says dates are yyyy-MM-dd, and the responses use `format: date`, but no input parameter says so. Binding `DateOnly` or a non-nullable `string` would fix the schema, but it would also bring back framework binding: DateOnly.TryParse is lenient about formats, and failures give the 400-without-errors or 500 of api-01. The fix therefore needs explicit OpenAPI metadata.

*Failure scenario:* A generated client exposes `getWorkdays(from?: string, to?: string)`. Calling it without `to`, or with `10/12/2026`, compiles and then fails at run time with a 400 the document doesn't predict.

*Suggested fix:* Keep the string binding and explicit validation. Mark from/to as required with `format: date`, and give `date` `format: date`, through an operation transformer (`AddOpenApiOperationTransformer` in .NET 10).

**`cr-api-03`: The OpenAPI document marks /api/workdays `from` and `to` as optional, but both are required; neither they nor `/api/week/{date}` declare the date format**

`Count(string? from, string? to)` binds both as nullable, so the handler can return its own "A date is required" message. As a result the generated OpenAPI marks both query parameters as optional (`required` absent) with schema `{type: string}`, and gives no `format: date` or pattern. The handler rejects a missing or empty value with a 400 (`/api/workdays` gives errors for both `from` and `to`; `/api/workdays?from=2026-01-05&to=` gives errors.to "A date is required"). I checked both by running the API, and the integration test `RejectsInvalidRanges` asserts it too. `/api/week/{date}` is also documented as a bare string, although only `yyyy-MM-dd` (InvariantCulture, exact) is accepted. The document describes a looser contract than the code enforces.

*Failure scenario:* A client built from /openapi/v1.json treats `to` as optional and calls GET /api/workdays?from=2026-10-12, expecting a count up to some default. It gets a 400 ValidationProblem for `to`. A client that sends `12/10/2026` to /api/week/{date} also gets a 400, because nothing in the document says the format is yyyy-MM-dd.

*Suggested fix:* Keep the explicit parsing, but describe the parameters correctly. One option is to bind `DateOnly from, DateOnly to`, which makes them required with `format: date`. But minimal APIs bind DateOnly with a non-exact `DateOnly.TryParse` (InvariantCulture), which also accepts formats such as 02/12/2026, and a failed bind hits the problem in cr-api-01. So the explicit exact parse is stricter. The other is to keep `string?` and attach metadata, either with an OpenAPI operation transformer that sets `required: true` and `format: date`, or with `[Description]` plus a pattern. Also add `format: date` for `{date}` on /api/week.

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, low, small): Verified in /openapi/v1.json. /api/workdays's from and to carry no required flag and have the schema {type: string}, and /api/week/{date} is {type: string} with no format, although a missing value gets 400 'A date is required (yyyy-MM-dd)'. One overstatement: both operations do document a 400 HttpValidationProblemDetails, so api-06's 'a 400 the document doesn't predict' is wrong. What's missing is only 'required' and 'format: date'. Both reports rightly note that binding DateOnly would loosen parsing and bring back F081's binding failure, so the fix belongs in OpenAPI metadata.
- **maintainer** (CONFIRMED, low, small): In the generated document, workdays' from/to have no `required` and the schema {type: string}, and /api/week/{date} is a plain string. The handlers reject a missing value with 400 and accept only exact yyyy-MM-dd. Binding `string?` is deliberate (its own messages, no framework binding failure, see F081). The fix is therefore metadata (an operation transformer setting required and format: date), not binding DateOnly. Both reports are accurate and agree on that.
- **impact** (CONFIRMED, low, small): The generated document gives /api/workdays' `from` and `to` as optional `{type: string}` and /api/week/{date} as a bare `{type: string}`, with no `format: date`; my probes show a missing or empty `from`/`to` returns 400 'A date is required (yyyy-MM-dd)'. Both operations do document the 400 ValidationProblem, so a generated client that omits `to` gets a typed error at run time, which keeps this low. Both reports correctly warn that binding DateOnly would reintroduce F081's framework-binding failures, so the fix is OpenAPI metadata (an operation transformer), not a type change.

</details>

### F090

**llm-gate's README leaves out the triage and attest subcommands and --risk/LLM_GATE_RISK, which the workflows call**

- **Status:** open
- **Severity:** low (reviewers: low) · **outcome:** confirmed · **fix cost:** small
- **Where:** `tools/llm-gate/README.md:8` · **area:** API, tests, docs
- **Reported by:** `api-19` (low, high confidence), `dd-15` (low, high confidence)

**`api-19`: llm-gate's README leaves out the triage and attest subcommands and --risk/LLM_GATE_RISK, which the workflows call**

The synopsis (lines 7-19) lists list, run, compare, report, audit, eval, feedback and metrics. It doesn't list `triage` (the triage job in llm-review.yml), `attest vuln-scan|llm-review` (the attest job in release.yml), `run --risk` or `audit skip --risk`, or the LLM_GATE_RISK environment variable that the llm jobs set. The environment paragraph and the Layout table, which has no triage.py, aidetect.py or attestations.py, date from before Phases 17 and 18.

*Failure scenario:* Someone changing the CLI uses the README to find its callers, misses triage and attest, and breaks llm-review.yml or release.yml.

*Suggested fix:* Add the missing subcommands, flags, environment variable and modules.

**`dd-15`: llm-gate's README doesn't document the triage and attest subcommands or the Phase 17/18 modules**

The usage block lists list, run, compare, report, audit, eval, feedback and metrics. cli.py also has `triage` (--base, --pr-data, --audit-dir, --no-model, --out, --no-cache; used by llm-review.yml) and `attest vuln-scan|llm-review` (used by release.yml). It also has `run --risk` / `LLM_GATE_RISK`, `eval run --out/--no-cache` (WRITEUP §3 tells readers to use `--out`), `audit override --writers` and `feedback handle --permission`. The environment list (lines 30-33) misses `LLM_GATE_RISK` and `LLM_GATE_OVERRIDE_BY`. The Layout table misses triage.py, aidetect.py and attestations.py (and prompts.py).

*Failure scenario:* Someone reproducing a triage decision or an attestation predicate locally finds no documentation of `llm-gate triage` or `llm-gate attest` in the tool's own README and has to read cli.py.

*Suggested fix:* Add `llm-gate triage ...` and `llm-gate attest vuln-scan|llm-review ...` lines and `--risk` to `run`, add LLM_GATE_RISK to the environment list, and add rows for triage.py (ADR 0008), aidetect.py and attestations.py (ADR 0009).

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, low, small): tools/llm-gate/README.md's synopsis (lines 7-19) has neither triage nor attest, although llm-review.yml:118 runs `llm-gate triage` and release.yml:230-232 run `attest vuln-scan` and `attest llm-review`. Also missing: `run --risk` and `audit skip --risk` with LLM_GATE_RISK (cli.py:135-138 and 173; llm-review.yml:193), and LLM_GATE_OVERRIDE_BY. The Layout table lacks triage.py, aidetect.py, attestations.py and prompts.py, all of which exist. The docs-drift scale rates undocumented features low.
- **maintainer** (CONFIRMED, low, small): The README synopsis (lines 7-19) lacks the `triage` and `attest vuln-scan|llm-review` subcommands and `run --risk`/`audit skip --risk`. Its environment list lacks LLM_GATE_RISK and LLM_GATE_OVERRIDE_BY. All of these are in cli.py (lines 131-173 and 264-269) and called by llm-review.yml and release.yml. The Layout table has no triage.py, aidetect.py, attestations.py or prompts.py. Plain drift from Phases 17-18.
- **impact** (CONFIRMED, low, small): The README synopsis lists list, run, compare, report, audit, eval, feedback and metrics; cli.py also defines `triage` (llm-review.yml's first job), `attest vuln-scan|llm-review` (release.yml) and `run --risk`/`audit skip --risk` defaulting from LLM_GATE_RISK, and none of triage, attest, aidetect, attestations, prompts or LLM_GATE_RISK appears in the README. The cost is real but small: a CLI change that breaks triage's arguments isn't caught by its own PR's review (the gate runs from the base branch) and shows up on the PRs after merge, but a contributor would grep the workflows for callers rather than trust the README.

</details>

### F096

**OpenAPI declares every integer in the responses as integer-or-string, though the API only writes JSON numbers**

- **Status:** open
- **Severity:** low (reviewers: low) · **outcome:** confirmed · **fix cost:** trivial
- **Where:** `src/CalendarGates.Api/Program.cs:8` · **area:** API, tests, docs
- **Reported by:** `api-07` (low, high confidence)

The web JSON defaults (`NumberHandling = AllowReadingFromString`) make the .NET 10 generator emit `type: [integer, string]` plus a digit pattern for isoYear, week, year, count, daysUntil, workdays and ProblemDetails.status (verified in /openapi/v1.json). The responses always carry numbers, and calendar.http asserts `Number.isInteger(...)` on them. `parity` is documented as a free string, although it is always `even` or `odd`. The API reads no JSON request bodies, so allowing numbers as strings gains nothing.

*Failure scenario:* A TypeScript client generated from the document types `week` as `number | string`, and every consumer has to handle a string that never arrives.

*Suggested fix:* Add `builder.Services.ConfigureHttpJsonOptions(o => o.SerializerOptions.NumberHandling = JsonNumberHandling.Strict)`. There are no request bodies, so behaviour doesn't change. Optionally add an enum or schema transformer for parity.

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, low, trivial): Verified in /openapi/v1.json: every integer response property (isoYear, week, year, count, daysUntil, workdays) has type [integer, string] with a digit pattern, HttpValidationProblemDetails.status is [null, integer, string], and parity is a plain string. The cause is the web JSON default NumberHandling.AllowReadingFromString in the .NET 10 generator. The API reads no JSON bodies, so switching to Strict changes nothing at run time. Real but cosmetic: generated clients get number | string.
- **maintainer** (CONFIRMED, info, trivial): The generated schemas give isoYear, week, year, count, daysUntil, workdays and ProblemDetails.status `type: [integer, string]` with a digit pattern, and the friday13 query parameter too. This comes from AllowReadingFromString in the web JSON defaults; the API only ever writes numbers. On a scratch copy, `ConfigureHttpJsonOptions(o => o.SerializerOptions.NumberHandling = Strict)` made them plain integers, with no change in behaviour because the API has no request bodies. A superset type is imprecise rather than wrong, so info.
- **impact** (CONFIRMED, low, trivial): In my build's /openapi/v1.json every int32 in the responses (isoYear, week, year, count, daysUntil, workdays, ProblemDetails.status) is `type: [integer, string]` with a digit pattern, although the API only writes numbers. A generated TypeScript client would type them `number | string`, which costs every consumer a narrowing but never yields a wrong value, and no consumer exists. The API reads no JSON bodies, so JsonNumberHandling.Strict changes no behaviour.

</details>

### F098

**The contract tests check the content type on 2 of 17 requests and leave out several error contracts**

- **Status:** open
- **Severity:** low (reviewers: low) · **outcome:** confirmed · **fix cost:** small
- **Where:** `http/calendar.http:88` · **area:** API, tests, docs
- **Reported by:** `api-10` (low, high confidence)

Only 'Current ISO week' (application/json, line 21) and 'ISO week: invalid date' (application/problem+json, line 53) check `response.contentType`. The 400 requests for friday13?year=1500 (88-97), easter/1500 (127-136) and the reversed and over-10-year workdays ranges (151-171) check the status and an errors key, but not problem+json. There are no requests for an out-of-range /api/leap/{year}, workdays with a missing parameter, or a malformed year. This file is what http-tests, k8s-smoke and the release smoke run against the real container (the integration tests run in-process, as Development). new-endpoint.md asks each request to assert status, content type and invariants.

*Failure scenario:* A change makes the year endpoints return their 400 as application/json or plain text, for example through a custom validation filter. It passes http-tests, k8s-smoke and the release smoke.

*Suggested fix:* Assert the mimeType on every request: application/json for successes, application/problem+json for errors. Add an out-of-range leap request, a workdays request without `to`, and `friday13?year=abc`.

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, info, small): The count is right: only 2 of the 17 requests ('Current ISO week' and 'ISO week: invalid date') assert the content type, and no .http request covers an out-of-range leap year, a missing workdays parameter or a malformed year. But another layer catches the failure scenario. ApiTestBase.GetJsonAsync asserts application/json or application/problem+json on every integration request, including every 400 through AssertValidationProblemAsync (MetaTests.LeapYearRejectsUnsupportedYears and the missing-parameter cases in WorkdaysTests among them). A filter that returned those 400s as application/json would therefore fail build-test / dotnet. Only an environment-specific difference would slip through (F081 shows such differences exist), hence info: the file doesn't follow new-endpoint.md's 'status, content type' convention.
- **maintainer** (CONFIRMED, low, small): Only 'Current ISO week' (line 21) and 'ISO week: invalid date' (line 53), 2 of the 17 requests, assert response.contentType, although PLAN.md 3.4 and new-endpoint.md ask every handler to assert status, content type and invariants. There is no .http request for an out-of-range leap year, for workdays without a parameter, or for a malformed year. The integration tests do check the media type of every response, but in-process (Development). The real gap is the Production container, where F081 shows the behaviour can differ.
- **impact** (CONFIRMED, low, small): Of calendar.http's 17 requests only 'Current ISO week' (line 21) and 'ISO week: invalid date' (line 53) assert the content type, and none covers an out-of-range leap year, workdays without `to`, or a malformed year. The failure scenario overstates the gap: ApiTestBase.GetJsonAsync asserts application/problem+json for every 4xx in the integration tests (including the easter, friday13 and leap range cases), so a content-type regression fails build-test unless it is environment-specific. That exception is real, though: F081 shows Development and Production diverge, and only the .http file runs against the Production container.

</details>

### F099

**The blocking code-review prompt's scope and severity rubric cover only the date API, not the gate code most PRs change**

- **Status:** open
- **Severity:** low (reviewers: low) · **outcome:** confirmed · **fix cost:** medium
- **Where:** `.claude/commands/llm-code-review.md:6` · **area:** API, tests, docs
- **Reported by:** `cr-gate-15` (low, medium confidence)

The prompt describes calendar-gates as a minimal date API, and 'What to look for' and every severity anchor are about C# endpoints (wrong dates, HTTP 500s, TimeProvider). ADR 0008 notes that most PRs here touch the gate (Python in tools/llm-gate, workflows, scripts) and are rated high, where code-review blocks on high. Yet the prompt says nothing about what a high-severity bug in gate code looks like, such as a verdict that passes a blocking finding. The eval set mirrors this: all of code-review's bug cases are in src/ or deploy/ (cr-001 to cr-004, cr-inj-001/002), and gate changes appear only as clean cases, so recall on the gate's own code is unmeasured.

*Failure scenario:* A PR changes policy.decide so that an override also skips the error branch. With no anchor beyond 'the service does not start' or 'a 500 for valid input', the reviewer rates it medium or low, and code-review passes.

*Suggested fix:* Add guidance and severity anchors for gate and CI code (a gate that can pass what it should block counts as high), plus planted-bug eval cases in tools/llm-gate and the workflows.

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, low, medium): llm-code-review.md:6-50 frames the review, the look-for list and every severity anchor around the date API. Yet code-review has no paths filter, and per ADR 0008 most PRs here change the gate. The eval set matches: code-review's bug and injection cases (cr-001..004, cr-inj-001/002) touch only src/ or deploy/, and gate code appears only in clean cases. The audit log supports the failure mode. code-review's real findings on gate code in #52 and #53 were rated medium (cr-6a49, an attestation that leaves out PRs; cr-2121, kubectl debug unchecked) or low (cr-def4), so none blocked, though all were fixed anyway. The fix is a prompt change plus new cases, which goes through llm-eval and probably a baseline update.
- **maintainer** (CONFIRMED, low, medium): llm-code-review.md describes the repository as the date API, and its look-for list and severity anchors are all about endpoints. Every code-review bug case is in src/ or deploy/ (cr-001..004, cr-inj-001/002); gate changes appear only as clean cases, so recall on gate code is unmeasured. The audit log backs this up: on #52 and #53, code-review rated real release and policy defects medium or low (cr-6a49, cr-def4, cr-2121), so the blocking check passed and only people acted on them. ADR 0008 accepts that most PRs are high risk, not this prompt scope. A fix needs new anchors, planted gate-bug cases and a new baseline, which costs credits.
- **impact** (CONFIRMED, low, medium): llm-code-review.md introduces the repo as a date API, and every 'What to look for' item and severity anchor (high = 'a wrong result or a 500 for valid, ordinary input on a main path') is about the C# API; its eval set has planted bugs only in src/ and deploy/ (cr-001..004) plus injection cases, and gate changes appear only as clean cases. The audit log fits: all 5 high code-review findings are in src/CalendarGates.Api, and findings in tools/llm-gate and .github/workflows never went above medium. The risk is a gate bug rated below high passing the blocking check; security-review (blocks at medium), pytest and llm-eval also cover gate changes, so it's an unmeasured recall gap rather than an open door, and the fix is a prompt change plus planted-bug cases and a baseline update through llm-eval.

</details>

### F104

**PLAN.md's drill table, which /gate-drill checks results against, predates reasoned overrides and the --no-verify ban**

- **Status:** open
- **Severity:** low (reviewers: low) · **outcome:** confirmed · **fix cost:** small
- **Where:** `docs/PLAN.md:731` · **area:** API, tests, docs
- **Reported by:** `dd-13` (low, high confidence)

/gate-drill reads this table and asks Claude to "tell me whether the gate behaved as the table predicts" (gate-drill.md:25-26). Drill 5 predicts "add `llm-override` label → passes with warning". Since ADR 0005, a label without an unedited `/llm-override <reason>` by the person who added it is not honoured, and the check still fails (audit.find_override, llm-review.yml:239-268). Drill 1 (line 727) says to commit with `git commit --no-verify`, which AGENTS.md's Don'ts forbid (gate-drill.md:19-22 routes around it with scripts/commit-via-api.py). Drill 12 says `--atomic`, while the chart is installed with `--rollback-on-failure`. PLAN.md has no status note marking it historical (unlike PLAN-v2).

*Failure scenario:* /gate-drill 5 adds only the label, the blocking checks stay red with "override not honoured", and the drill is reported as not matching the table, though the gate behaves as designed.

*Suggested fix:* Update drill 5's expected column ("/llm-override <reason> → passes with warning; label alone → not honoured") and drill 1's method (commit through scripts/commit-via-api.py), or add a status note pointing to ADR 0005 and AGENTS.md.

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, info, small): Drill 5's expected result (PLAN.md:731, 'add llm-override label → passes with warning') has been stale since ADR 0005. A label without a reasoned /llm-override is not honoured, and PLAN-v2's drill 20 tests exactly that, so /gate-drill 5 would report a mismatch where the gate behaves as designed. The other two points are weaker. gate-drill.md step 5 already overrides drill 1's --no-verify (commit through scripts/commit-via-api.py), and drill 12's --atomic is Helm 4's --rollback-on-failure, with the same rollback. PLAN.md has no status note, but it is the v1 plan kept as written.
- **maintainer** (CONFIRMED, low, trivial): PLAN.md hasn't changed since the skeleton (db1dcb5) and has no status note, yet /gate-drill compares results with its table. Drill 5 predicts 'add llm-override label -> passes with warning', which ADR 0005's reason rule (and PLAN-v2's drill 20) makes 'not honoured'. Drill 1 prescribes --no-verify, which AGENTS.md forbids (gate-drill.md step 5 works around it). Drill 12 says --atomic, but Helm 4's --rollback-on-failure is what runs. PLAN-v2's 'kept as written' covers PLAN-v2 only, so this isn't ACCEPTED; a status note would keep PLAN.md as written and fix the drill comparison.
- **impact** (CONFIRMED, low, small): PLAN.md, still headed 'No code yet' with no status note, predicts for drill 5 that adding the `llm-override` label passes with a warning, which ADR 0005 changed (label alone not honoured; PLAN-v2 drill 20 tests exactly that), tells drill 1 to use `git commit --no-verify`, which AGENTS.md forbids, and says `--atomic` for drill 12 where the chart uses `--rollback-on-failure`. gate-drill.md step 5 already overrides the --no-verify method, so the live effect is that a re-run of drill 5 would be reported as not matching the table although the gate behaves as designed.

</details>

### F111

**/api/friday13/next's 404 (no Friday the 13th left before year 10000) has no test**

- **Status:** open
- **Severity:** low (reviewers: low) · **outcome:** confirmed · **fix cost:** trivial
- **Where:** `src/CalendarGates.Api/Endpoints/Friday13Endpoints.cs:40` · **area:** API, tests, docs
- **Reported by:** `tr-22` (low, high confidence)

The endpoint returns NotFound when NextOnOrAfter returns null. The unit test covers the null; no integration test sets the FakeTimeProvider past 9999-08-13, so the endpoint's mapping of the null is untested.

*Failure scenario:* The null branch changes, for example to `!.Value`, or the NotFound result goes. The endpoint then returns 500 (or a bogus 200) on 9999-08-14, and no test fails.

*Suggested fix:* An integration test with the clock at 9999-08-14T00:00Z expecting a 404 with application/problem+json.

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, low, small): No integration test moves the FakeTimeProvider past 9999-08-13 (Friday13Tests uses only 2026-02-12 and 02-13), and calendar.http can't, so Next's NotFound branch (Friday13Endpoints.cs:37-43) is untested at the endpoint. Only the calculator's null is tested (ReturnsNullPastTheLastRepresentableOne). The endpoint itself is correct today. A missing edge-case test for correct code: low.
- **maintainer** (CONFIRMED, low, trivial): Friday13Endpoints.Next turns a null from NextOnOrAfter into NotFound. Only the unit test covers the null (ReturnsNullPastTheLastRepresentableOne); no integration test moves the FakeTimeProvider past 9999-08-13. One integration test (clock at 9999-08-14, expect a 404 with problem+json) closes the gap.
- **impact** (CONFIRMED, info, trivial): No integration test sets the clock past 9999-08-13; the unit test covers NextOnOrAfter's null. A scratch test on the same factory with the clock at 9999-08-14 shows the endpoint returns 404 application/problem+json today, so the code is correct, and the untested branch only matters for a clock 7,973 years ahead.

</details>

### F113

**VersionEndpoints.Read has no unit test, and the version/commit checks accept its fallbacks**

- **Status:** open
- **Severity:** low (reviewers: low) · **outcome:** confirmed · **fix cost:** small
- **Where:** `src/CalendarGates.Api/Endpoints/VersionEndpoints.cs:24` · **area:** API, tests, docs
- **Reported by:** `tr-24` (low, high confidence)

Read splits MinVer's informational version on '+', prefers the Commit metadata over the suffix, and falls back to 'unknown' and '0.0.0'. MetaTests.VersionReportsVersionAndCommit asserts only non-empty strings, so 'unknown' passes. calendar.http checks only that the commit is non-empty. Only the release smoke compares the version with the tag, and nothing checks that the commit is the built one.

*Failure scenario:* The Docker COMMIT build argument stops reaching the assembly. /api/version reports commit 'unknown', or the +sha suffix of another build, and every test passes.

*Suggested fix:* Unit-test Read with a fake assembly: with and without the metadata, with and without '+'. In CI http-tests, compare the commit with the image's COMMIT build argument.

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, low, small): VersionEndpoints.Read is internal and has no unit test. MetaTests.VersionReportsVersionAndCommit asserts only non-empty strings and calendar.http only a non-empty commit, so 'unknown' or another build's +sha would pass. The release smoke compares only the version with the tag (release.yml, smoke job). The fallbacks are live: an unflagged local build reports the SDK's full SourceRevisionId (mine returned 43ec3c2f019d...).
- **maintainer** (CONFIRMED, low, small): MetaTests.VersionReportsVersionAndCommit asserts only non-empty strings, and calendar.http checks only a version prefix and a non-empty commit, so the fallbacks pass: '0.0.0', the Dockerfile's default '0.0.0-docker', and 'unknown'. Only the release smoke compares the version with the tag, and nothing checks the commit. Read is internal and the repo has no InternalsVisibleTo, so a unit test needs that or a small refactor.
- **impact** (CONFIRMED, info, small): VersionEndpoints.Read has no unit test; MetaTests and calendar.http only require a non-empty commit, and the Dockerfile's default COMMIT=unknown passes both. The release smoke checks `version`, and releases are verified through digest-bound attestations rather than /api/version's commit, so a commit that silently became 'unknown' would mislead a human glance and nothing else.

</details>

### F114

**The leap endpoint's year validation is tested only with 99999**

- **Status:** open
- **Severity:** low (reviewers: low) · **outcome:** confirmed · **fix cost:** trivial
- **Where:** `tests/CalendarGates.IntegrationTests/MetaTests.cs:20` · **area:** API, tests, docs
- **Reported by:** `tr-25` (low, high confidence)

The Easter and Friday13 integration tests check both 1582 and 10000. LeapYearRejectsUnsupportedYears uses only 99999, so the leap endpoint's own [Range] lower bound and the 10000 boundary are untested there. Each endpoint declares its own attribute.

*Failure scenario:* The leap endpoint's attribute becomes [Range(1, Years.Max)]. /api/leap/1582 then reaches the calculator, which throws, and the response is 500 instead of a 400 ValidationProblem.

*Suggested fix:* Use [Arguments(1582)] and [Arguments(10000)], as in EasterTests.

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, low, trivial): MetaTests.LeapYearRejectsUnsupportedYears uses only 99999, while EasterTests and Friday13Tests check 1582 and 10000, and calendar.http has no out-of-range leap request. So the leap endpoint's own [Range] lower bound is untested at the endpoint layer (the calculator's throw is unit-tested). The endpoint is correct today: /api/leap/1582 and /api/leap/10000 return the ValidationProblem. Adding two [Arguments] is trivial.
- **maintainer** (CONFIRMED, low, trivial): MetaTests.LeapYearRejectsUnsupportedYears uses only 99999, while the Easter and Friday13 integration tests check 1582 and 10000. Each endpoint declares its own [Range], and no .http request covers an out-of-range leap year, so the leap endpoint's lower bound and the 10000 boundary are untested. Two [Arguments] rows fix it.
- **impact** (CONFIRMED, low, trivial): LeapYearRejectsUnsupportedYears uses only 99999, while the Easter and Friday13 integration tests use 1582 and 10000, and each endpoint declares its own [Range]. Relaxing only the leap endpoint's range (plausible, since the Gregorian leap rule is defined for any year, see F087) would let 1582 reach LeapYearCalculator.IsLeap, which throws through Years.ThrowIfUnsupported: a 500 no test catches.

</details>

### F048

**Every attestation Kyverno requires exists before the release is approved or smoke-tested, so rejected and failed candidates are admitted**

- **Status:** 🟡 partial — #69: publish attests release-approved/v1 and a policy requires it, on Audit until v0.3.2 carries it
- **Severity:** low (reviewers: medium) · **outcome:** confirmed · **fix cost:** medium
- **Where:** `deploy/policies/base/release.yaml:30` · **area:** workflows, release, deploy, scripts
- **Reported by:** `cr-ops-02` (medium, high confidence)

The Deny policies admit an image once provenance, a vuln-scan with no critical findings and an llm-review attestation, each signed by release.yml on a v* tag, exist (release.yaml:30-65, llm-review.yaml:26-48). release.yml creates all four in the attest job (needs: verify, build, scan; release.yml:184-276). That job runs before publish, which is the only job in the approval-gated release environment, and before admission-smoke and smoke. The signing identity is the same for every job, so nothing distinguishes an approved release from a rejected one. The candidate-vX.Y.Z tag stays in GHCR after a rejection, and Kyverno resolves tags to digests: WRITEUP §5 (drill 23) shows candidate-v0.3.0 admitted. calendar-gates-llm-review only checks that the attestation is present. So a candidate whose attestation lists unverified PRs (workflow_modified, tamper_suspected), which is exactly what the approver reads in the release notes before deciding, is admitted before anyone looked. Likewise, publish pushes X.Y.Z and the chart before smoke runs, so a release whose contract tests failed stays a draft but deploys and is admitted via just k8s-deploy-release. ADR 0009 puts attest before approval on purpose ('the reviewer approves known bytes'), but neither it nor ADR 0010 mentions this admission consequence.

*Failure scenario:* Push v0.4.0; scan passes; attest pushes the four attestations; the approver rejects publish because the notes list an unverified PR -> kubectl -n calendar-gates run x --image=ghcr.io/gergodrazsdik/calendar-gates:candidate-v0.4.0 is admitted and pinned to the candidate digest.

*Suggested fix:* Create at least one required attestation only after approval, for example by moving the llm-review attestation (or a small release-approved/v1 predicate) into publish or smoke, and require it in the Deny policies. The release would still get four Rekor entries. Otherwise, state in ADR 0010 that admission means 'built and scanned by release.yml', not 'approved and published'.

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, low, medium): attest (needs verify, build, scan) pushes all four attestations before publish, the only job in the approval-gated release environment, and before admission-smoke and smoke; every job signs with the same release.yml@refs/tags/vX identity, so Kyverno can't tell an approved release from a rejected candidate, and candidate-vX.Y.Z stays in GHCR (drill 23 shows a candidate tag admitted). ADR 0009 chose attest-before-approval and ADR 0010/WRITEUP section 2 list exactly what admission checks (approval isn't among them), but neither records that a rejected or smoke-failed candidate is admissible, so not ACCEPTED. The bytes are still main-built, scanned and attested by the genuine workflow, and deploying them needs cluster access, so low rather than medium.
- **maintainer** (CONFIRMED, low, small): attest (release.yml:184-276) runs before publish, the only approval-gated job, and every attestation Kyverno requires is created there with the same release.yml@refs/tags identity, so a candidate the owner rejects (or whose smoke fails after publish) stays fully attested; WRITEUP §5 already shows candidate-vX admitted by tag. ADR 0009 places attest before approval on purpose ('the reviewer approves known bytes'), so the cause is a recorded decision, but neither ADR 0009 nor ADR 0010 says admission therefore means 'built, scanned and attested', not 'approved'. Low: running a rejected candidate needs someone to reference its tag or digest by hand, and the approver is the solo owner. Keeping the predicate generation in attest for the notes and attesting llm-review (or a small release-approved predicate) from publish would keep four Rekor entries.
- **impact** (CONFIRMED, low, medium): release.yml's attest job (needs verify, build, scan) creates every attestation the Deny policies require before publish, the only job in the approval-gated release environment, and the candidate-vX.Y.Z tag stays in GHCR after a rejection, so a rejected candidate is admissible by tag or digest (drill 23 already showed candidate-v0.3.0 admitted). ADR 0009 accepts attest-before-approval for 'known bytes' but not this admission consequence, so not ACCEPTED. Low: the bytes passed build-test and scan and were built from a signed tag on main; the documented deploy path (k8s-deploy-release) needs the chart that only publish pushes, so deploying a rejected candidate takes a hand-written pod spec on a local cluster.

</details>

### F091

**The audit/v1 type lists in ADR 0005 and in the audit-log branch README are out of date**

- **Status:** 🟡 partial — #63: ADR 0005's record types updated; the `audit-log` branch README is still stale
- **Severity:** low (reviewers: low) · **outcome:** confirmed · **fix cost:** small
- **Where:** `docs/adr/0005-audit-trail.md:18` · **area:** API, tests, docs
- **Reported by:** `api-14` (low, high confidence), `dd-16` (low, high confidence), `dd-18` (low, high confidence)

**`api-14`: The audit/v1 type lists in ADR 0005 and in the audit-log branch README are out of date**

ADR 0005 lists gate_run, triage, override, feedback, risk_override, eval_run and tamper_suspected. The schema (audit.AuditRecord) also has feedback_rejected (ADR 0007), and the log contains one. The README on the audit-log branch, which the log points readers to for queries, still files triage, feedback, risk_override and eval_run under 'Later phases', leaves out feedback_rejected, and lists eval_run although ADR 0006 says eval_run records never reach that branch.

*Failure scenario:* Someone writes a jq query from the README without knowing that feedback_rejected exists, and treats triage as not implemented yet. The 'rejected commands' figure in the Integrity metric has no documented record type behind it.

*Suggested fix:* Add feedback_rejected to ADR 0005's list. Rewrite the README table with every type that can appear, and drop eval_run or mark it as artifact-only.

**`dd-16`: ADR 0005 says the collector accepts only gate_run and override records; it also accepts the triage artifact**

Line 35: "accepts only `gate_run` and `override` records for checks in the default branch's `checks.yaml`". audit.py:255 has ARTIFACT_TYPES = {gate_run, override, triage}, and collect() also accepts the artifact named `triage`, which isn't a check (audit.py:831). The triage artifact is validated first and every gate_run is checked against it (ADR 0008 point 6). The type list at lines 18-19 lacks `feedback_rejected` (audit.FeedbackRejected, ADR 0007). The file pattern at line 48 lacks `<run_id>-<attempt>-triage`, `-too-much` and llm-feedback's `feedback-*.jsonl`. ADR 0005 isn't marked as amended by ADR 0008.

*Failure scenario:* A reader of ADR 0005, the audit trail's reference, wrongly concludes that triage records on audit-log can't have come from a PR's run, or doesn't know feedback_rejected records exist.

*Suggested fix:* Add an amendment line: "Since ADR 0008 the collector also accepts one `triage` record from the `-triage` artifact and checks each gate_run against it". Add `feedback_rejected` to the types.

**`dd-18`: The audit-log branch's README still calls triage, feedback and risk_override "later phases"**

The README on origin/audit-log was written once (a3173c2, 2026-10-16) and never updated. Line 21 lists `triage`, `feedback`, `risk_override`, `eval_run` as "Later phases". The branch now holds 25 triage, 6 feedback, 1 risk_override and 1 feedback_rejected records, and eval_run records never reach it (ADR 0006). Lines 4-5 say `audit-collect.yml` appends the files, but llm-feedback.yml writes `feedback-*.jsonl` there too. The `override` row says the collector checked every override, but /llm-override records come from llm-feedback.yml. The file layout lists only `<run_id>-<attempt>-<check>.jsonl`.

*Failure scenario:* Someone querying the log with `just audit-pull`, following that README, treats triage and feedback records as unexplained, or misattributes who wrote them.

*Suggested fix:* Add the rows for triage, feedback, feedback_rejected and risk_override (and say eval_run stays in llm-eval artifacts). Name llm-feedback.yml as the second writer, and add the feedback-*.jsonl and -triage file names.

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, low, small): All three reports check out. ADR 0005:18-19 omits feedback_rejected (audit.py:210; one such record is on audit-log). ADR 0005:35 says the collector accepts only gate_run and override, but ARTIFACT_TYPES is {gate_run, override, triage} (audit.py:255), and collect() accepts the -triage artifact (audit.py:831). The audit-log branch README (a3173c2, never updated) still files triage, feedback, risk_override and eval_run under 'Later phases', while the branch holds 25 triage, 6 feedback, 1 risk_override and 1 feedback_rejected records. It also lists eval_run, which ADR 0006 keeps off the branch, and names only audit-collect.yml as writer and only the <run_id>-<attempt>-<check> file pattern.
- **maintainer** (CONFIRMED, low, small): audit.py defines FeedbackRejected, and origin/audit-log holds 6 feedback, 1 feedback_rejected, 1 risk_override and 25 triage records. ADR 0005:18-19 still leaves out feedback_rejected. ADR 0005:35 says the collector accepts only gate_run and override records, but ARTIFACT_TYPES also includes triage (ADR 0008 point 6). The branch README (written once, a3173c2) still lists triage, feedback and risk_override as 'later phases', lists eval_run although ADR 0006 keeps it off the branch, names only audit-collect.yml as a writer, and shows only the <run>-<attempt>-<check> layout. The branch also has -triage files and 9 feedback-*.jsonl files.
- **impact** (CONFIRMED, low, small): audit.py defines FeedbackRejected (the log holds one), which ADR 0005's type list (lines 175-176) omits, and ADR 0005:192 says the collector accepts only gate_run and override, though ARTIFACT_TYPES (audit.py:255) includes triage. The audit-log branch README still files triage, feedback, risk_override and eval_run under 'Later phases' while the branch holds 25 triage, 6 feedback, 1 risk_override and 1 feedback_rejected records and no eval_run (ADR 0006 keeps those in artifacts), and it names only audit-collect.yml as the writer. Whoever writes queries from that README is misled; audit.py is the real reference, so low.

</details>

### F013

**`llm-gate run --risk` for a check the level runs (demoted to advisory, engine switched) is never exercised**

- **Status:** ✅ fixed — #74: both risk-level transformations are exercised (demotion to advisory, the agent engine at high)
- **Severity:** low (reviewers: medium) · **outcome:** confirmed · **fix cost:** small
- **Where:** `tools/llm-gate/src/llm_gate/cli.py:306` · **area:** llm-gate and review prompts
- **Reported by:** `tr-02` (medium, high confidence)

_at_risk returns the level's version of a check: advisory at low risk, and the agent engine for blocking checks at high risk (plan_for). Every planned check in CI takes this path, because llm-review.yml sets LLM_GATE_RISK for the llm matrix. cli.py:306 is never executed. The only CLI test with --risk is test_cli_run_at_a_risk_level_where_the_check_is_not_needed, which covers the not-needed branch. The mutation `return check, None` (ignore the plan) survived the whole suite. plan_for is unit-tested (test_the_plan_per_level), but nothing checks that a run uses its result: not the exit code, not the gate_run's blocking, not the engine.

*Failure scenario:* _at_risk regresses to the configured check. At low risk, a docs-only PR with a high finding fails code-review, which should be advisory there. At high risk, security-review keeps the API engine instead of the agent engine ADR 0008 promises. No test fails. The collector later flags only the blocking mismatch, and never the engine.

*Suggested fix:* Two CLI tests. `run --risk low --check code-review` with a high finding: exit 0, record blocking false, risk low. `run --risk high --check security-review` with api and agent FakeEngines: the agent engine gets the request and the record says engine agent.

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, low, small): Only test_cli_run_at_a_risk_level_where_the_check_is_not_needed passes --risk. The mutant `return check, None` at cli.py:306 survived the full suite (306 passed); a control mutant on the covered not-needed branch was killed. Rated low: a regression in the blocking flag would show up as visible failures and collector problems (_risk_problems compares blocking). Only the engine switch would regress silently.
- **maintainer** (CONFIRMED, low, small): The mutation `return check, None` in _at_risk (ignore the plan) survived all 306 tests; the only --risk CLI test covers the not-needed branch. Every planned CI check takes this path, but a regression of the blocking part would surface quickly as collector tamper events (record.blocking vs the plan), so the practical risk is low; nothing checks the engine.
- **impact** (CONFIRMED, low, small): Coverage shows cli.py:306 (`return planned, None`) never executed; the only --risk CLI test covers the not-needed branch. Every planned check in production takes this path, so most regressions would be loud (blocking at low fails PRs, and a blocking mismatch is flagged by the collector); the silent one is the engine at high risk, which the collector doesn't check. A test gap: low.

</details>

### F014

**Only `feedback` is tested as a record type a PR's artifact may not carry; `risk_override` is not**

- **Status:** ✅ fixed — #74: every trusted-only record type is covered, risk_override included
- **Severity:** low (reviewers: medium) · **outcome:** confirmed · **fix cost:** trivial
- **Where:** `tools/llm-gate/src/llm_gate/audit.py:255` · **area:** llm-gate and review prompts
- **Reported by:** `tr-03` (medium, high confidence)

triage.latest_risk_override trusts every risk_override record on audit-log. That is safe only because the collector never accepts one from a PR's run (ARTIFACT_TYPES; ADR 0008, the triage.py docstring). test_trusted_only_types_may_not_come_from_an_artifact (test_audit.py:286) checks only a Feedback record. The mutation adding "risk_override" to ARTIFACT_TYPES survived the suite. _record_problems would then accept a RiskOverride with matching run context, _override_problems ignores the type, and _withhold returns it unchanged even when the workflow was modified.

*Failure scenario:* ARTIFACT_TYPES is widened, for example to collect eval_run records as ADR 0006 hints, and the new set includes risk_override. Tests pass. A PR whose modified workflow writes {"type":"risk_override","to":"low",...} into its artifact gets the record onto audit-log. Its next triage then honours it and lowers the PR's own review level.

*Suggested fix:* Parametrize the test over every trusted-only type (feedback, feedback_rejected, risk_override, eval_run, tamper_suspected) and assert that each becomes a tamper_suspected event.

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, low, trivial): test_trusted_only_types_may_not_come_from_an_artifact uses only a Feedback record, and no test puts a RiskOverride into an artifact. The mutant adding 'risk_override' to ARTIFACT_TYPES survived the full suite. Rated low: it guards against a future widening, and F005 shows risk_override records can reach audit-log by a direct push anyway.
- **maintainer** (CONFIRMED, low, trivial): test_trusted_only_types_may_not_come_from_an_artifact uses only a Feedback record; adding "risk_override" to ARTIFACT_TYPES survived the suite. ADR 0008 relies on this exact property ('the collector never accepts them from a PR's run'). The set is a three-element literal, so a regression is unlikely, but a parametrized test is cheap insurance.
- **impact** (CONFIRMED, low, trivial): test_trusted_only_types_may_not_come_from_an_artifact uses only a Feedback record, and ARTIFACT_TYPES is what keeps a PR's artifact from putting a risk_override, which triage trusts, on audit-log. Harm needs a future change that widens ARTIFACT_TYPES to include it; parametrizing the test over the trusted-only types is trivial. Low.

</details>

### F015

**The 'exactly one triage record' rule is untested; the test named for it passes through a different check**

- **Status:** ✅ fixed — #74: two triage records in one artifact is a problem the test now reaches
- **Severity:** low (reviewers: medium) · **outcome:** confirmed · **fix cost:** trivial
- **Where:** `tools/llm-gate/src/llm_gate/audit.py:723` · **area:** llm-gate and review prompts
- **Reported by:** `tr-04` (medium, high confidence)

_triage_problems rejects a triage artifact unless it holds exactly one record (lines 723-724, never executed). test_the_triage_artifact_needs_its_job_and_only_a_triage_record (test_triage.py:501) puts a gate_run into the triage artifact. _record_problems already rejects that ('check code-review in the artifact for triage'), so _triage_problems never runs. Nothing else catches two Triage records: _record_problems accepts each one on its own. The mutation `if not triages:` survived.

*Failure scenario:* The triage artifact holds a consistent Triage (final high) and then a Triage (final low). With the length check weakened, the first record is validated and used for the run, and both are written to audit-log. Readers that pick the latest triage by ts (metrics, feedback.current_risk, attestations) then see whichever sorts last.

*Suggested fix:* Add a triage artifact with two valid Triage records, and one with a Triage plus an Override. Assert the 'exactly one triage record' problem for each.

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, low, trivial): The mutant replacing `len(triages) != 1 or len(records) != 1` with `not triages` survived the full suite. In the named test, the gate_run inside the triage artifact is already rejected by _record_problems ('check ... in the artifact for triage'), so _triage_problems never runs. The production code is correct today; this is a test gap.
- **maintainer** (CONFIRMED, low, trivial): The named test puts a gate_run in the triage artifact, which _record_problems already rejects, so _triage_problems never runs; the mutation `if not triages:` survived. Two valid Triage records would pass _record_problems individually. Test gap only; the code is right today.
- **impact** (CONFIRMED, low, trivial): Coverage shows audit.py:724 never executed: the test named for the rule puts a gate_run in the triage artifact, which _record_problems rejects first, so _triage_problems never runs. Exploiting a weakened rule needs a modified workflow (flagged anyway) emitting two triage records. Low; one more test case.

</details>

### F016

**The 128 KB per-artifact limit is untested, and the 256 KB per-line limit can never trigger**

- **Status:** ✅ fixed — #74: both size limits are tested, and MAX_LINE_BYTES sits below MAX_FILE_BYTES so it can fire
- **Severity:** low (reviewers: medium) · **outcome:** confirmed · **fix cost:** trivial
- **Where:** `tools/llm-gate/src/llm_gate/audit.py:592` · **area:** llm-gate and review prompts
- **Reported by:** `tr-05` (medium, high confidence)

ADR 0005 lists a 128 KB limit per artifact. test_size_and_count_limits (test_audit.py:320) writes 21 small lines, so only MAX_RECORDS fires. Its assertion `"over the" in problems[0]` would match either message. audit.py:593 is never executed, and a mutation disabling the MAX_FILE_BYTES check survived. test_a_run_has_a_byte_budget doesn't cover it: one 200 KB artifact stays under the 256 KB run budget. Separately, MAX_LINE_BYTES (256 KB) is larger than MAX_FILE_BYTES (128 KB), and the file check returns first, so the per-line check at 606-608 is unreachable.

*Failure scenario:* A refactor loses the per-file check. A single 200 KB artifact with at most 20 lines, under the run budget, is parsed and its records are written. No test fails.

*Suggested fix:* Test one artifact just over MAX_FILE_BYTES on its own (under MAX_RUN_BYTES) and match the size problem's text. Drop MAX_LINE_BYTES, or set it below MAX_FILE_BYTES and test it.

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, low, trivial): The mutant disabling the MAX_FILE_BYTES check survived the full suite. test_size_and_count_limits triggers only MAX_RECORDS, and its 'over the' assertion matches both messages. MAX_LINE_BYTES (256 KB) exceeds MAX_FILE_BYTES (128 KB), and the file check returns first, so the per-line check is unreachable. The run budget is tested, so the impact of a regression is limited.
- **maintainer** (CONFIRMED, low, trivial): Disabling the MAX_FILE_BYTES check survived the suite; test_size_and_count_limits trips MAX_RECORDS and asserts only 'over the', which both messages contain. MAX_LINE_BYTES (256 KB) is larger than MAX_FILE_BYTES (128 KB), which is checked first, so the per-line check is dead code. Impact is small: parsed strings are scrubbed and lists capped anyway.
- **impact** (CONFIRMED, low, trivial): Coverage shows audit.py:593 (MAX_FILE_BYTES) and 607-608 (MAX_LINE_BYTES) never executed; test_size_and_count_limits trips MAX_RECORDS, and its 'over the' assertion would match either message. MAX_LINE_BYTES (256 KB) exceeds MAX_FILE_BYTES (128 KB) and the file check returns first, so the line check is dead code. Losing the file check would still leave MAX_RUN_BYTES and the schema caps bounding what reaches the log. Low.

</details>

### F017

**The committed-eval-cases test is skipped in CI (shallow checkout), and one missing base skips every case**

- **Status:** ✅ fixed — #74: the lint job checks out full history, and a missing base fails in CI instead of skipping
- **Severity:** low (reviewers: medium) · **outcome:** confirmed · **fix cost:** trivial
- **Where:** `tools/llm-gate/tests/test_evals.py:102` · **area:** llm-gate and review prompts
- **Reported by:** `tr-06` (medium, high confidence)

test_every_committed_case_is_valid_and_applies_to_its_base calls pytest.skip when a case's base commit isn't in the clone. ci.yml's lint job checks out with the default depth of 1 (ci.yml:63-65, no fetch-depth), so the first case skips the test. The latest CI run on main (39064824382) shows '305 passed, 1 skipped, 1 deselected', where a full clone gives 306 passed; test_live is the deselected one, and this is the suite's only runtime skip. The skip sits inside the loop, so locally too one unfetched base skips every later case. In CI only load_cases' schema validation remains. Nothing checks that patches apply, that expect files are in the patch, that patches avoid excluded files, or that case.yaml is in canonical form. llm-eval (fetch-depth 0) covers only the first and third of those, and only when the PR touches the gate and has the API key.

*Failure scenario:* A PR adds a case whose case.yaml isn't in dump_case's canonical form, or whose expect.file is outside the patch, so recall can never reach 1. lint is green.

*Suggested fix:* Set fetch-depth: 0 in the lint job, or fetch the case bases, and fail instead of skipping when CI is set. Collect failures per case instead of skipping the whole test.

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, low, trivial): ci.yml's lint job checks out with the default depth (no fetch-depth) and runs the llm-gate pytest. The test calls pytest.skip inside the case loop when a base commit is missing, so in a depth-1 clone the first case skips the whole test, including patch-applies, expect-in-patch and canonical-form checks. Locally, with a full clone, it ran (306 passed here). Mitigated by `just ci` locally and by llm-eval's full checkout when it applies, hence low.
- **maintainer** (CONFIRMED, low, trivial): The test calls pytest.skip inside the loop at the first base commit missing from the clone, and ci.yml's lint job checks out with the default depth 1, so in CI only load_cases' schema validation runs. Locally (`just ci`, full clone) it runs: 306 passed here. llm-eval (fetch-depth 0) applies the patches when a PR touches the gate, and a bad expectation would show there as a recall drop, so what CI loses is early detection (expect files, canonical form).
- **impact** (CONFIRMED, low, trivial): ci.yml's lint checkout has no fetch-depth (depth 1), and the test calls pytest.skip inside the loop at the first case base missing from the clone, so in CI the whole test is skipped (I couldn't open the cited run; the mechanism is clear from the code). The checks still run in `just ci` locally (full clone), and llm-eval (fetch-depth 0) applies every patch whenever a PR touches the gate, so a broken patch fails there; what slips through CI is expect files outside the patch and a non-canonical case.yaml. Low.

</details>

### F019

**fp-tr-835a can still pass for the wrong reason: its forbid rule needs a literal `$IMAGE` in the title**

- **Status:** ✅ fixed — #74: the rule matches the mistake in title or detail, and the dumper wraps long rules
- **Severity:** low (reviewers: medium) · **outcome:** confirmed · **fix cost:** trivial
- **Where:** `tools/llm-gate/evals/cases/fp-tr-835a/case.yaml:10` · **area:** llm-gate and review prompts
- **Reported by:** `tr-13` (medium, medium confidence)

forbidden_hit compares the file exactly and searches the title with the regex \$IMAGE (case-insensitive). It never looks at the finding's detail. The same false positive worded without the dollar sign ('admission-smoke references IMAGE, which is never set', 'IMAGE env var undefined in admission-smoke') isn't counted. That is how this case passed falsely before, then by category. test-review has no baseline, so fp_regressions is the only thing that gates it. Separately, test_every_committed_case_is_valid_and_applies_to_its_base checks that expect files are in the patch, but not forbid files: a mistyped forbid.file makes an fp-regression case unable to fail.

*Failure scenario:* A later test-review prompt change brings the finding back as 'IMAGE is not defined for the admission-smoke job'. fp_regressions stays 0 and llm-eval is green.

*Suggested fix:* Loosen the rule to the mistake's core, for example \bIMAGE\b.*(never|not|un)\s*(defined|set) or the reverse order, or match the detail as well. In the committed-cases test, assert that every forbid.file is in the patch and that each forbid.title matches the original title quoted in the case description.

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, low, trivial): On audit-log, the original finding's title is 'admission-smoke uses $IMAGE, which the job never defines'. forbidden_hit matches file exactly and searches only the title with `\$IMAGE`, so the same false positive worded without a literal $IMAGE wouldn't count, and the detail is never looked at. The committed-cases test asserts expect files are in the patch but not forbid files. Whether a model rewords it this way is uncertain; test-review is advisory, hence low.
- **maintainer** (CONFIRMED, low, trivial): forbidden_hit matches the title regex `\$IMAGE` (case-insensitive) and never the detail; #60 chose `\$IMAGE` deliberately as the mistake's core after a category rule had passed falsely. A rewording without the dollar sign escapes it, and the committed-cases test checks expect files against the patch but not forbid files. test-review is advisory and has no baseline, so this case is its only gate.
- **impact** (CONFIRMED, low, trivial): The case's forbid is {file: .github/workflows/release.yml, title: \$IMAGE}, and forbidden_hit applies the title regex only (never the detail), so a reworded 'IMAGE is not defined' finding isn't counted; the committed-cases test checks expect files against the patch but not forbid files. test-review is advisory, so the cost is an advisory false positive coming back in a PR comment without llm-eval noticing. Low.

</details>

### F030

**floor_violations can never be non-zero: it is computed from final_risk(), which takes the higher risk**

- **Status:** ✅ fixed — #74: the metric measures the model's own answer (model_below_floor), reported not gated
- **Severity:** low (reviewers: low) · **outcome:** confirmed · **fix cost:** trivial
- **Where:** `tools/llm-gate/src/llm_gate/evals.py:524` · **area:** llm-gate and review prompts
- **Reported by:** `tr-14` (low, high confidence)

run_triage_eval scores rank(final) < rank(floor), where final = final_risk(floor, model, None).final is the higher of the two. The 'hard assertion' of PLAN 17.3 and ADR 0008 ('Any result below the floor fails the eval outright') therefore holds by construction. It only re-tests final_risk, which test_the_model_may_raise_but_not_lower_and_a_manual_change_wins already covers. The mutation hard-coding forbidden_hits=0 survived. The number that would measure the triage prompt, the model's own answer below the floor (for example tr-008's injection working), only appears in the free-text `locations`.

*Failure scenario:* The triage model answers 'low' to tr-008's injected comment in every repeat. floor_violations stays 0, and nothing records that the injection worked on the model, because the floor hides it.

*Suggested fix:* Score model answers below the floor as their own metric, for example model_below_floor as the injection signal with a threshold. Keep final >= floor as a unit test.

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, low, trivial): run_triage_eval scores forbidden_hits = rank(final) < rank(floor), with final = final_risk(floor, model, None).final. With no manual risk, final_risk returns the model's risk only when it ranks higher than the rules', otherwise the rules', so final >= floor always and floor_violations is always 0. ADR 0008's 'any result below the floor fails the eval outright' therefore re-tests final_risk, which is unit-tested already. What the injection case should measure, the model's own answer below the floor, appears only in the free-text locations.
- **maintainer** (REJECTED, info, trivial): True that final = final_risk(floor, model, None) is never below the floor, so floor_violations is 0 unless final_risk regresses; that is what PLAN 17.3 asks for ('never lower than the rule floor as a hard assertion'), an end-to-end invariant check, not a measurement of the prompt. A model answer below the floor is harmless by design (ADR 0008: talking the model down changes nothing), and the real insensitivity of the triage eval is F018. Minor: WRITEUP §3 presents 'no result below the floor' as a measured result.
- **impact** (CONFIRMED, low, small): run_triage_eval scores final = final_risk(floor, model, None).final, the higher of the two, so forbidden_hits = rank(final) < rank(floor) is 0 by construction and floor_violations can never fail the eval; the model's own below-floor answer appears only in the free-text locations. ADR 0008's 'any result below the floor fails the eval outright' and WRITEUP's 'no result below the rules' floor' are therefore vacuous as measurements. Low: the floor itself is enforced in code and unit-tested; what's lost is the injection signal (see F018).

</details>

### F031

**'Latest wins' tests use fixtures already in time order; the invalid-`to` fixture is rejected for its bad ts**

- **Status:** ✅ fixed — #74: the later record sorts first, so latest-by-ts is told apart from last-file-wins
- **Severity:** low (reviewers: low) · **outcome:** confirmed · **fix cost:** trivial
- **Where:** `tools/llm-gate/tests/test_triage.py:193` · **area:** llm-gate and review prompts
- **Reported by:** `tr-15` (low, high confidence)

In test_the_latest_risk_override_comes_from_the_audit_log, x.jsonl has "to": "free" and "ts": "z". fromisoformat('z') fails first, so the `to not in RISKS` guard is never reached, and a mutation removing it survived. feedback-1 and feedback-2 are in time order, so 'latest by ts' can't be told apart from 'last file wins': the mutation `if True:` survived, and branch 309->297 is never taken. test_the_latest_run_on_the_merged_head_counts (attestations, _run_order) has the same pattern: a mutation dropping the sort survived. So does the latest-triage case in test_triage_and_integrity_counts (metrics). Only the metrics feedback test (#57) uses out-of-order fixtures.

*Failure scenario:* A refactor switches to 'last seen wins'. Record files are named feedback-<comment id>, so when ids cross a digit boundary or files sort differently, an older /llm-risk wins and decides the PR's review level. Tests pass.

*Suggested fix:* Give the invalid-`to` fixture a valid ts. In each 'latest' test (risk overrides, triage, gate runs by run id and attempt), put the later record in the file that sorts first.

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, low, trivial): Ran the mutants on a scratch clone. Dropping the `to not in RISKS` guard survived (the 'free' fixture is already skipped because its ts 'z' doesn't parse). Replacing the ts comparison with `if True:` (last seen wins) survived, because the fixtures are in file and time order. Dropping the sort by _run_order in attestations.llm_review survived. Control mutants in triage.py and attestations.py were killed, so the harness applies to those modules.
- **maintainer** (CONFIRMED, low, trivial): In test_the_latest_risk_override_comes_from_the_audit_log, x.jsonl has ts 'z', so fromisoformat fails before the `to not in RISKS` guard, and feedback-1/feedback-2 sort in time order. In a scratch clone three mutations survived all 306 tests: dropping the RISKS guard, `if True:` instead of the ts comparison (last file wins), and dropping the sort by _run_order in attestations.llm_review. Low: record names (feedback-<comment id>, <run id>-...) sort in time order today, so the regression would rarely bite.
- **impact** (CONFIRMED, low, trivial): The invalid fixture has to 'free' and ts 'z', and fromisoformat('z') fails first, so the RISKS guard is never reached; feedback-1 and feedback-2 sort in time order, and coverage shows triage.py 309->297 never taken, so 'latest by ts' can't be told from 'last file wins'. The regression would rarely matter in practice: files are events/YYYY/MM/DD/feedback-<comment id>, which sort chronologically until GitHub comment ids gain a digit. Low.

</details>

### F033

**Two of the eight redaction patterns (Slack, JWT) have no test case**

- **Status:** ✅ fixed — #74: the Slack and JWT patterns have cases
- **Severity:** low (reviewers: low) · **outcome:** confirmed · **fix cost:** trivial
- **Where:** `tools/llm-gate/src/llm_gate/redact.py:22` · **area:** llm-gate and review prompts
- **Reported by:** `tr-17` (low, high confidence)

test_secrets_are_redacted covers Anthropic keys, GitHub tokens (ghp_, github_pat_), AWS key ids, private-key headers and key=value secrets, but not the xox* or eyJ... patterns. Mutations breaking each one survived. Redaction is the only guard for free text in the permanent, public audit log (ADR 0005).

*Failure scenario:* A typo creeps into the JWT pattern. A tool-call summary or finding title that contains a bearer JWT is written to audit-log unredacted.

*Suggested fix:* Add an xoxb-... token and a three-part eyJ JWT to the parametrized secrets.

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, low, trivial): A mutant breaking both the Slack (xox*) and JWT (eyJ...) patterns survived the full suite, while a control breaking the Anthropic pattern was killed by test_secrets_are_redacted. So two of the eight patterns that guard the permanent audit log's free text have no case.
- **maintainer** (CONFIRMED, low, trivial): test_secrets_are_redacted parametrizes Anthropic, ghp_, github_pat_, AKIA, private-key headers and key=value secrets; no test anywhere uses an xox* or eyJ... string. Both patterns read correctly today, so this is a test gap on the audit log's only free-text guard.
- **impact** (CONFIRMED, low, trivial): The parametrized secrets cover Anthropic, ghp_, github_pat_, AKIA, a private-key header and key=value forms, not the xox* or eyJ JWT patterns; I checked that both patterns redact correctly today. A pure test gap for token types unlikely to show up in this repository's reviews: low.

</details>

### F035

**`/llm-ack` recording and a writer's malformed command are never tested through handle()**

- **Status:** ✅ fixed — #74: the ack path and a writer's malformed command go through handle()
- **Severity:** low (reviewers: low) · **outcome:** confirmed · **fix cost:** trivial
- **Where:** `tools/llm-gate/src/llm_gate/feedback.py:180` · **area:** llm-gate and review prompts
- **Reported by:** `tr-19` (low, high confidence)

The only /llm-ack test names another PR's finding (unknown_finding). The happy path (kind ack, no mark) is untested (partial branch 198->217), and a mutation recording acks as kind 'fp' survived. A command from someone with write access that doesn't parse, such as '/llm-fp cr-1705' without a reason, reaches line 180, which never runs; a mutation returning no record there survived. parse_command is tested on its own, but not this wiring.

*Failure scenario:* Acks get recorded as false positives. The Gate health fp rate rises with every /llm-ack, and no test fails.

*Suggested fix:* handle('/llm-ack cr-1705'): recorded, kind ack, mark None. handle('/llm-fp cr-1705') with write permission: feedback_rejected with bad_arguments, reaction confused, path feedback-<id>.

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, low, trivial): The mutant recording /llm-ack as kind 'fp' survived the full suite, and so did the one returning an empty Actions instead of a feedback_rejected record for a writer's unparseable command (feedback.py:179-180). A control mutant in feedback.py was killed. The handle() tests cover /llm-ack only for an unknown finding, a non-PR and outsiders; bad_arguments is tested only in parse_command.
- **maintainer** (CONFIRMED, low, trivial): The only /llm-ack test through handle() names another PR's finding (unknown_finding). A mutation that records every feedback as kind 'fp' survived all 306 tests, so an ack mis-recorded as a false positive would go unnoticed and inflate the fp rate. The writer's-malformed-command wiring (feedback.py:180) is only covered via parse_command on its own.
- **impact** (CONFIRMED, low, trivial): Coverage shows feedback.py:180 (a writer's unparseable command) never executed and 198->217 (the ack path) only partly; the only /llm-ack test hits unknown_finding. A regression recording acks as fp would skew the false-positive rate silently, but it is a hypothetical future change: low.

</details>

### F036

**The API engine's cost is checked against estimate_cost itself; the price arithmetic has no independent test**

- **Status:** ✅ fixed — #74: the price arithmetic is asserted literally, and an unknown model has no estimate
- **Severity:** low (reviewers: low) · **outcome:** confirmed · **fix cost:** trivial
- **Where:** `tools/llm-gate/tests/test_engines.py:75` · **area:** llm-gate and review prompts
- **Reported by:** `tr-20` (low, high confidence)

test_api_engine_request_and_result asserts cost_usd == approx(estimate_cost('claude-sonnet-5-5', 1000, 200)), and nothing else tests estimate_cost. Swapped input and output prices, or a wrong divisor, would pass. The estimate feeds the eval budget (spent_usd), the cost threshold and the metrics.

*Failure scenario:* estimate_cost multiplies output tokens by the input price. Eval cost comparisons and the $6 budget are then off by up to 5x, and the tests pass.

*Suggested fix:* Assert the literal (1000*2 + 200*10)/1e6 = 0.004, and None for an unknown model.

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, low, trivial): test_api_engine_request_and_result asserts cost_usd == approx(estimate_cost(...)), the code under test. A mutant swapping input and output prices survived the full suite. The estimate feeds the eval budget, the cost threshold and metrics.
- **maintainer** (CONFIRMED, low, trivial): test_api_engine_request_and_result compares cost_usd with estimate_cost itself and nothing else tests the arithmetic; swapping input and output prices survived the suite. The figure is marked as an estimate everywhere, but it feeds the eval budget (spent_usd), the cost threshold and the metrics for the API engine.
- **impact** (CONFIRMED, low, trivial): test_engines.py:75 asserts cost_usd against estimate_cost itself, and nothing else tests the arithmetic or the unknown-model None (api_engine.py:30 uncovered). The formula is a correct one-liner today; a wrong one would distort the eval budget and absolute cost reporting for the API engine, while relative cost comparisons against a baseline computed the same way would still hold. Low.

</details>

### F038

**The prompt-guard test skips llm-triage.md**

- **Status:** ✅ fixed — #74: the prompt guard covers the triage prompt too
- **Severity:** low (reviewers: low) · **outcome:** confirmed · **fix cost:** trivial
- **Where:** `tools/llm-gate/tests/test_prompts_cache.py:24` · **area:** llm-gate and review prompts
- **Reported by:** `tr-28` (low, high confidence)

test_every_repository_prompt_takes_the_diff_and_guards_against_injection iterates over checks.yaml's checks. The triage prompt isn't a check, so its 'never instructions to you' guard and $ARGUMENTS go unchecked; both are present today.

*Failure scenario:* An edit drops the data-not-instructions sentence from llm-triage.md, and the test still passes.

*Suggested fix:* Also check config.triage.prompt_path, without the '## Severity' assertion, since that prompt's heading is '## Rubric'.

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, low, trivial): test_every_repository_prompt_takes_the_diff_and_guards_against_injection iterates load_config's checks only. llm-triage.md isn't a check, so its $ARGUMENTS and 'never instructions to you' guard (both present today, lines 10 and 17) are unchecked. The impact is limited because the triage model can only raise the risk.
- **maintainer** (CONFIRMED, info, trivial): test_every_repository_prompt_takes_the_diff_and_guards_against_injection iterates over checks.yaml's checks only, so llm-triage.md isn't covered; today it does contain $ARGUMENTS and 'never instructions to you'. Info: per ADR 0008 an injection can only talk the triage model up (costs money) or down (changes nothing, the floor holds).
- **impact** (CONFIRMED, low, trivial): test_every_repository_prompt_takes_the_diff_and_guards_against_injection iterates checks.yaml's checks only, and llm-triage.md is not one; today it has both $ARGUMENTS and the 'never instructions to you' sentence. The triage model can only raise the risk, so a lost guard costs at most an over-raise or a missed raise above the floor. Low.

</details>

### F055

**pr-title accepts non-Conventional titles that start with 'Merge ', 'fixup! ', 'squash! ' or 'amend! '**

- **Status:** ✅ fixed — #63: the Merge/fixup! exemption no longer applies to `--title`
- **Severity:** low (reviewers: low) · **outcome:** confirmed · **fix cost:** trivial
- **Where:** `scripts/check-commit-msg.sh:18` · **area:** workflows, release, deploy, scripts
- **Reported by:** `cr-ops-07` (low, high confidence)

The exemption for git-generated messages also applies with --title, which ci.yml's pr-title job uses for the PR title, and it exits before the length check. The PR title becomes the squash commit on main (squash_merge_commit_title=PR_TITLE, gh-setup), where neither autosquash markers nor merge subjects make sense. GitHub defaults a single-commit PR's title to that commit's subject, so a branch whose only commit is 'fixup! feat: x' opens a PR that passes the required gate as it is.

*Failure scenario:* A PR titled 'fixup! feat: add leap endpoint', or a 150-character 'Merge ...' -> pr-title is green -> main gets a non-Conventional subject that is over the length limit.

*Suggested fix:* Apply the exemptions only to message files. For --title, keep at most the 'Revert "' form (GitHub's revert button), and enforce max_length either way.

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, low, trivial): Reproduced: scripts/check-commit-msg.sh --title exits 0 for 'fixup! feat: add leap endpoint', 'squash! anything at all' and a 155-character 'Merge xxx' title, because the exemption at line 18 runs before both the pattern and the length check, and exits 1 for 'WIP stuff'. ci.yml's pr-title uses exactly this mode, and gh-setup makes the PR title the squash subject on main. Needs an unusual title and only costs commit-subject hygiene, so low.
- **maintainer** (CONFIRMED, low, trivial): Reproduced: scripts/check-commit-msg.sh --title 'fixup! feat: add leap endpoint' and --title 'Merge whatever I want here' both exit 0, because the git-message exemption at line 18 also applies to --title and returns before the pattern and length checks. The comment says the exemption is meant for git's own messages, so applying it to PR titles (which become the squash commit) isn't a recorded decision. Low: the owner merges and can edit the squash title anyway.
- **impact** (CONFIRMED, low, trivial): Reproduced: check-commit-msg.sh --title exits 0 for 'fixup! feat: ...', 'amend! y' and 'Merge stuff that is not conventional', and for a 140-character 'Merge xxx...' title, because the exemption exits before the length check. The PR title becomes main's squash subject. Cosmetic (a non-Conventional subject on main), and the Revert " exemption is worth keeping for GitHub's revert button: low.

</details>

### F058

**k8s-policy-up returns before the policies are ready, so a deploy right after it can be admitted unchecked**

- **Status:** ✅ fixed — #71: the readiness wait uses the condition Kyverno reports (the first fix never matched)
- **Severity:** low (reviewers: low) · **outcome:** confirmed · **fix cost:** trivial
- **Where:** `justfile:180` · **area:** workflows, release, deploy, scripts
- **Reported by:** `cr-ops-10` (low, medium confidence)

The recipe applies deploy/policies and prints the list (justfile:180-181). release.yml's admission-smoke waits up to 120 s for status.conditionStatus.ready on every ValidatingPolicy and ImageValidatingPolicy before it tests anything (release.yml:412-422), because Kyverno only enforces a policy once its webhook is configured. Locally nothing waits. Drill 21, or `just k8s-up k8s-policy-up k8s-deploy`, can therefore have a pod admitted in calendar-gates during that window, which looks like a policy failure (or a pass).

*Failure scenario:* just k8s-policy-up, then kubectl -n calendar-gates run edge --image=ghcr.io/gergodrazsdik/calendar-gates:edge within seconds -> the pod is admitted although the Deny policies exist.

*Suggested fix:* Reuse admission-smoke's readiness loop in k8s-policy-up (or kubectl wait on the policies' Ready condition), and fail if they don't become ready.

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, low, trivial): k8s-policy-up applies deploy/policies and lists them (justfile:180-181) without waiting for status.conditionStatus.ready, while release.yml's admission-smoke waits up to 120 s for exactly that before it tests anything (412-422). Kyverno configures the policies' webhooks asynchronously after apply, so a pod created in that window isn't sent to the policy. Not reproduced (no cluster access), but the code gap is clear and the CI counterpart shows the wait is needed; local drills only, so low.
- **maintainer** (CONFIRMED, low, trivial): k8s-policy-up applies the policies and returns (justfile:180-181), whereas admission-smoke waits up to 120 s for conditionStatus.ready on every policy (release.yml:412-422) because enforcement starts only once Kyverno has configured the webhooks. A local deploy right after the recipe can therefore be admitted unchecked, which a drill would misread. Local only; reusing the existing loop is trivial.
- **impact** (CONFIRMED, low, trivial): k8s-policy-up applies deploy/policies and lists them (justfile:180-181) with no readiness wait, whereas admission-smoke waits up to 120 s for status.conditionStatus.ready precisely because Kyverno enforces only once a policy's webhook is configured. A chained `just k8s-up k8s-policy-up k8s-deploy` can create a pod in calendar-gates seconds later, inside that window, and the admitted pod then keeps running unattested until recreated. Local cluster, misleading drill result rather than a real exposure: low. (Window not exercised here: no cluster access.)

</details>

### F059

**k8s-cluster-down ignores cluster=, so with cluster=local it deletes the project cluster**

- **Status:** ✅ fixed — #63: `k8s-cluster-down` honours `cluster=` and refuses kind-local
- **Severity:** low (reviewers: low) · **outcome:** confirmed · **fix cost:** trivial
- **Where:** `justfile:163` · **area:** workflows, release, deploy, scripts
- **Reported by:** `cr-ops-11` (low, high confidence)
- **Reports the council found wrong:** `cr-ops-11`

The recipe hardcodes --name calendar-gates (justfile:162-163), while every other k8s recipe follows {{ cluster }}, and k8s-policy-up refuses cluster=local outright. `just cluster=local k8s-cluster-down` therefore deletes kind-calendar-gates along with Kyverno and the policies. Only the confirm text names the cluster, and --yes skips the confirm.

*Failure scenario:* just cluster=local k8s-cluster-down, meant to reset kind-local -> 'y' -> the project cluster is deleted and kind-local is untouched.

*Suggested fix:* Refuse cluster=local, as k8s-policy-up does, and delete {{ cluster }}.

<details><summary>Council</summary>

- **skeptic** (REJECTED, info, trivial): The behaviour is deliberate and documented: the recipe's doc comment says 'Delete the project cluster (never kind-local)', so it intentionally ignores cluster= to keep the machine-owned kind-local (ADR 0003) out of reach, and its [confirm] text names what it deletes ('Delete the kind cluster calendar-gates and everything in it?'). A user who meant kind-local is told the target before anything happens, and --yes is an explicit opt-out of that prompt. Refusing cluster=local would be a nicety, not a defect fix.
- **maintainer** (CONFIRMED, low, trivial): k8s-cluster-down hardcodes --name calendar-gates (justfile:162-163), so 'just cluster=local k8s-cluster-down' deletes the project cluster. Never touching kind-local is intended (the doc comment says so, and ADR 0003 keeps kind-local out of the project's hands), but silently ignoring cluster= is a footgun. The confirm text names calendar-gates and the cluster is cheap to rebuild, hence low; refusing cluster=local as k8s-policy-up does is trivial.
- **impact** (CONFIRMED, low, trivial): Reproduced: `just --dry-run --yes cluster=local k8s-cluster-down` prints `kind delete cluster --name calendar-gates`. The hardcoded name is deliberate (doc comment: never kind-local), but with cluster=local it deletes a different cluster than the one targeted. Mitigated by the confirm text, which names calendar-gates (skipped by --yes); the cluster is rebuilt with k8s-up k8s-policy-up in minutes and holds nothing persistent: low.

</details>

### F060

**k8s-http doesn't notice a port-forward that failed to bind 18080, and tests whatever already listens there**

- **Status:** ✅ fixed — #63: `k8s-http` fails when the port-forward didn't bind
- **Severity:** low (reviewers: low) · **outcome:** confirmed · **fix cost:** trivial
- **Where:** `justfile:219` · **area:** workflows, release, deploy, scripts
- **Reported by:** `cr-ops-12` (low, medium confidence)

The port-forward runs in the background and only the health URL is polled (justfile:219-223). If port 18080 is taken, for example by k8s-http for the other cluster (AGENTS.md says both clusters may run), kubectl exits at once. wait-for-health then gets a 200 from the other forward, and ijhttp tests the other cluster. Afterwards the EXIT trap's kill fails, and under set -e that turns the exit status into 1. I checked this: a failing kill in an EXIT trap after a successful body exits 1. So the run ends with 'kill: No such process' after green tests that ran against the wrong deployment.

*Failure scenario:* just cluster=local k8s-http in one terminal and just k8s-http calendar-gates-dev in another -> the second run reports the kind-local deployment's results, then exits 1.

*Suggested fix:* After wait-for-health, check `kill -0 "$forward"`, or let kubectl choose a free local port (`:80`) and read it back. Make the trap tolerant: `kill $forward 2>/dev/null || true`.

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, low, trivial): k8s-http backgrounds the port-forward and only polls the health URL (justfile:219-223); if 18080 is already held (k8s-http for the other cluster, or a stale forward), kubectl exits at once, wait-for-health gets a 200 from the other listener and ijhttp tests the other deployment. Reproduced the exit-status part: under set -euo pipefail, a failing `kill` in the EXIT trap after a successful body makes bash print 'kill: No such process' and exit 1. Needs two forwards at once, so low.
- **maintainer** (CONFIRMED, low, trivial): k8s-http starts the port-forward in the background and only polls the health URL (justfile:219-223). If 18080 is taken, for example by a k8s-http for the other cluster, kubectl exits at once and the tests run against whatever answers there. The EXIT trap's kill then fails, and bash lets an EXIT trap's status override the script's, so the run ends red after green tests. This was reported as checked; my own trap repro was blocked by the session's isolation guard, so I relied on bash's documented behaviour. Niche (two concurrent runs) and local; kill -0 plus a tolerant trap is trivial.
- **impact** (CONFIRMED, low, trivial): The recipe never checks that the background port-forward is alive, so a busy 18080 lets wait-for-health and ijhttp test whatever already listens there. Reproduced the recipe's shape: with the background job already gone, the green body is followed by 'kill: No such process' and exit 1 under set -e. So the wrong-target run surfaces as a confusing failure, not a silent pass, and needs two forwards (or a stale one) on 18080 at once: low.

</details>

### F062

**A failed push in just release leaves the local tag behind, and the retry stops at 'already exists'**

- **Status:** ✅ fixed — #63: a failed push drops the local tag, so a retry works
- **Severity:** low (reviewers: low) · **outcome:** confirmed · **fix cost:** trivial
- **Where:** `justfile:284` · **area:** workflows, release, deploy, scripts
- **Reported by:** `cr-ops-14` (low, high confidence)

The existence check reads local refs (justfile:284-285), and the tag is created before the push (287-288). git push can fail: the SSH key isn't loaded after a restart (AGENTS.md says the first use needs the passphrase), the network drops, or the pre-push hook's just test fails. In each case the signed tag stays local. Re-running just release X.Y.Z then exits with 'vX.Y.Z already exists' after the confirm, with no hint to push or delete the tag.

*Failure scenario:* just release 0.4.0 -> the push fails at the SSH passphrase -> just release 0.4.0 -> 'v0.4.0 already exists'.

*Suggested fix:* Check the remote with `git ls-remote --exit-code --tags origin refs/tags/v$version`. If the tag exists only locally and points at HEAD, push it. Or delete the local tag in a trap when the push fails.

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, info, trivial): Confirmed by reading: the existence check (justfile:284-285) reads local refs, and the signed tag is created (287) before the push (288). A failed push (SSH key not loaded after a restart, network, the pre-push test hook) leaves the tag local, and a retry stops at 'v$version already exists' with no hint. Recovery is one manual git push or git tag -d, so info.
- **maintainer** (CONFIRMED, low, trivial): The recipe creates the signed tag (justfile:287) before pushing it (288), and the existence check (284-285) reads local refs. If the push fails (the SSH key not loaded after a restart, the pre-push hook's just test failing, the network), a retry stops at 'vX.Y.Z already exists' with no hint. Recovery is a manual git push of the same tag, which is safe because the tag points at a verified HEAD; a usability gap, not a gate problem.
- **impact** (CONFIRMED, low, trivial): The existence check reads local refs after `git fetch origin main --tags` (justfile:280-285) and the signed tag is created before the push (287-288). A failed push (SSH key not loaded after a restart, network, the pre-push hook's just test) leaves the local tag, and the retry stops at 'vX.Y.Z already exists' with no hint. Plausible after a WSL restart; the fix by hand is `git push origin vX.Y.Z` or `git tag -d`. Annoyance only: low.

</details>

### F064

**gh-setup uploads the whole pass entry as ANTHROPIC_API_KEY, while the other recipes use only its first line**

- **Status:** ✅ fixed — #63: `gh-setup` sends only the entry's first line
- **Severity:** low (reviewers: low) · **outcome:** confirmed · **fix cost:** trivial
- **Where:** `justfile:387` · **area:** workflows, release, deploy, scripts
- **Reported by:** `cr-ops-16` (low, medium confidence)

llm and eval take `head -n 1` of `pass show api/anthropic-calendar-gates` (justfile:101, 133), following pass's convention of the secret on line one and metadata below. gh-setup pipes the full output into gh secret set (387). If the entry has a second line, the CI secret contains it too. The metadata then becomes part of a GitHub secret, and the x-api-key header becomes invalid, so every LLM check errors and the blocking ones fail closed.

*Failure scenario:* A pass entry of 'sk-ant-...' plus a 'url: ...' line -> just gh-setup -> the CI ANTHROPIC_API_KEY holds both lines -> llm / code-review ends with an error verdict on every PR.

*Suggested fix:* Use `pass show api/anthropic-calendar-gates | head -n 1 | gh secret set ANTHROPIC_API_KEY -R "$repo"`, as the other recipes do.

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, info, trivial): Confirmed by reading: gh-setup pipes the full `pass show api/anthropic-calendar-gates` output into gh secret set (justfile:387), while llm and eval take head -n 1 (101, 133). It's latent: CI reviews have been running with the current secret (the audit log has paid reviews), so the entry is single-line today, and a metadata line added later would break every LLM check loudly (blocking checks fail closed, not open). Info.
- **maintainer** (CONFIRMED, low, trivial): llm and eval take 'head -n 1' of the pass entry (justfile:101, 133), following pass's secret-on-line-one convention, while gh-setup pipes the whole output into gh secret set (387). The inconsistency is real; whether it bites depends on the entry having a second line, which I must not read. If it does, the CI key is invalid and every blocking check fails closed, visibly. Adding head -n 1 is trivial.
- **impact** (CONFIRMED, low, trivial): gh-setup pipes the whole `pass show api/anthropic-calendar-gates` output into gh secret set (justfile:387) while llm and eval take head -n 1. Latent: CI reviews work today (224 paid runs), so the entry is single-line now; the bite comes only if metadata lines are added and gh-setup is re-run, and then every LLM check errors and the blocking ones fail closed, loud and safe. I did not read the pass entry (out of bounds). Low.

</details>

### F065

**The timeout counts attempts, not seconds, because curl runs without --max-time**

- **Status:** ✅ fixed — #63: `curl --max-time` plus a wall-clock deadline
- **Severity:** low (reviewers: low) · **outcome:** confirmed · **fix cost:** trivial
- **Where:** `scripts/wait-for-health.sh:10` · **area:** workflows, release, deploy, scripts
- **Reported by:** `cr-ops-19` (low, high confidence)

Each attempt is `curl -fsS` with no --max-time or --connect-timeout, followed by sleep 1. A listener that accepts the connection and never answers (for example a port-forward to a hung pod) holds one attempt open indefinitely, well past the timeout argument. In CI the jobs' timeout-minutes is the real bound; locally, http-docker and k8s-http can hang.

*Failure scenario:* wait-for-health.sh http://localhost:18080/health 30 against a forward whose pod accepts but doesn't respond -> blocks far longer than 30 s instead of failing.

*Suggested fix:* Use `curl --max-time 2`, or compute a deadline from $SECONDS.

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, low, trivial): wait-for-health.sh:10 runs curl -fsS with no --max-time or --connect-timeout, so a single attempt can block far beyond the timeout argument against a listener that accepts and never answers; the loop counts attempts, not seconds. CI jobs are bounded by timeout-minutes; locally http-docker and k8s-http could hang. Real but narrow.
- **maintainer** (CONFIRMED, low, trivial): wait-for-health.sh loops 'timeout' times over curl -fsS with no --max-time, so a listener that accepts and never answers holds one attempt open well past the stated seconds. In CI, timeout-minutes bounds it; locally http-docker and k8s-http can hang. A hung-but-accepting listener is rare (a port-forward usually errors fast), so low; --max-time 2 is trivial.
- **impact** (CONFIRMED, low, trivial): Reproduced: against a local listener that accepts and never answers, `wait-for-health.sh http://127.0.0.1:18999/health 3` was still waiting after 15 s and was killed by timeout (124): curl has no --max-time, so one attempt can block indefinitely. Real listeners rarely behave so (port-forward and rootless port mapping reset when nothing listens), CI jobs have timeout-minutes, and locally Ctrl-C ends it: low (the repo's scale calls missing timeouts low).

</details>

### F070

**Nothing tests who may honour a bot-added override (override-writers.sh)**

- **Status:** ✅ fixed — #70: override-writers.sh has tests with a stubbed gh, which is what caught the writers-list bug
- **Severity:** low (reviewers: low) · **outcome:** confirmed · **fix cost:** small
- **Where:** `scripts/override-writers.sh:12` · **area:** workflows, release, deploy, scripts
- **Reported by:** `tr-29` (low, high confidence)

For llm-review and the collector (ADR 0007), the script decides which /llm-override authors count as writers: user logins only, with the role admin, maintain or write. It has no test, and find_override is tested only with a hand-written writers set.

*Failure scenario:* The case pattern is widened (say, triage added) or the login regex is dropped. A /llm-override from a read-only collaborator is then honoured, and no test fails.

*Suggested fix:* A test with a stub `gh` on PATH that returns a role per login, asserting that only write, maintain and admin users are printed and bots are skipped.

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, low, small): No test exercises scripts/override-writers.sh: it appears only as a triage path in test_triage.py, and find_override is tested with a hand-written writers set (test_feedback.py:230-236). The script decides which /llm-override authors count for llm-review and the collector (roles admin, maintain, write; user logins only), so widening its case pattern or dropping the login filter would go unnoticed. Impact is bounded because llm-feedback adds the label only after checking the commenter's role itself, so low.
- **maintainer** (CONFIRMED, low, small): scripts/override-writers.sh decides who may honour a bot-added override for llm-review.yml:255 and audit-collect.yml:94 (ADR 0007), and no test runs it: the only test reference (test_triage.py:59) uses its path as a triage-rule input, and find_override is tested with hand-made writer sets. The script is 10 lines and shellchecked, but it's security-relevant; a pytest with a stub gh on PATH is small.
- **impact** (CONFIRMED, low, small): scripts/override-writers.sh decides which /llm-override authors count as writers for llm-review and the collector, and no test runs it: the only test reference is test_triage.py using its path as a triage input, and test_feedback.py passes find_override a hand-built writers={'alice'}. A regression would widen who can override blocking checks, but llm-feedback separately checks the commenter's role before adding the label, and this repository has a single collaborator, so the practical exposure today is nil: low.

</details>

### F082

**OpenAPI documents only 200 for /api/easter/{year}, /api/leap/{year} and /api/friday13, which also return 400 ValidationProblem**

- **Status:** ✅ fixed — #63: `.ProducesValidationProblem()` on the three year endpoints
- **Severity:** low (reviewers: medium) · **outcome:** confirmed · **fix cost:** trivial
- **Where:** `src/CalendarGates.Api/Endpoints/EasterEndpoints.cs:20` · **area:** API, tests, docs
- **Reported by:** `api-02` (medium, high confidence), `cr-api-02` (low, high confidence)

**`api-02`: OpenAPI documents only 200 for /api/easter/{year}, /api/leap/{year} and /api/friday13, which also return 400 ValidationProblem**

EasterEndpoints.cs:20, LeapEndpoints.cs:20 and Friday13Endpoints.cs:27 return `Ok<T>` and validate with `[Range]` and `AddValidation()`. The validation filter's 400 is not added to the endpoint metadata. The /openapi/v1.json generated from a build of 43ec3c2 lists only `200` for GetEaster, GetLeapYear and GetFriday13s. GetWeek and GetWorkdays, whose `Results<..., ValidationProblem>` unions carry the metadata, document `400 application/problem+json HttpValidationProblemDetails`. So three of the five endpoints that take input leave out an error response they return every day, along with the binding-failure 400 from api-01. GetNextFriday13 also documents its `404` with no content, although UseStatusCodePages answers it with problem+json. The api-contract prompt lists 'response types that OpenAPI will document wrongly' as something to look for. new-endpoint.md says 'Use TypedResults so OpenAPI picks up the response types', but copying the `[Range]` pattern of the existing year endpoints quietly breaks that. The OpenAPI contract tests (calendar.http 'openapi: lists every route', MetaTests.OpenApiListsEveryRoute) compare only the path keys.

*Failure scenario:* A client generated from /openapi/v1.json has no error type for `GET /api/easter/1500`. The 400 with `errors.year` that the API returns is an undeclared response. No test notices that GetEaster and GetWeek document their errors differently.

*Suggested fix:* Add `.ProducesValidationProblem()` to the three endpoints, or return `Results<Ok<T>, ValidationProblem>`. Add `.ProducesProblem(404)` to /friday13/next. Extend the OpenAPI request in calendar.http to assert that every operation with parameters documents a 400.

**`cr-api-02`: The OpenAPI document lists only 200 for /api/easter, /api/leap and /api/friday13, though all three return a 400 ValidationProblem**

The handlers are declared as `Ok<EasterResponse> ForYear([Range] int year)` (EasterEndpoints.cs:20), `Ok<LeapResponse> ForYear([Range] int year)` (LeapEndpoints.cs:20) and `Ok<Friday13YearResponse> InYear([Range] int? year, ...)` (Friday13Endpoints.cs:27). The 400 comes from the `AddValidation()` endpoint filter, which adds no response metadata. I fetched `/openapi/v1.json` from the running API. The responses for `/api/easter/{year}`, `/api/leap/{year}` and `/api/friday13` are `["200"]` only. Endpoints that return `Results<..., ValidationProblem>` do list 400: `/api/week/{date}` and `/api/workdays` show `["200","400"]`. The integration and .http tests assert that these three endpoints return 400 with `errors.year`, so the published contract leaves out a response the tests treat as part of it. A client generated from the document has no type for that 400.

*Failure scenario:* A generated client calls GET /api/easter/1582. The server answers 400 application/problem+json, but the OpenAPI document declares only 200, so the client has no model for the error and either throws a generic exception or mis-deserializes the body.

*Suggested fix:* Add `.ProducesValidationProblem()` to the three `MapGet` calls, or declare the return types as `Results<Ok<T>, ValidationProblem>`. Then extend `OpenApiListsEveryRoute` or add a test that checks the 400 is documented.

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, low, trivial): The /openapi/v1.json from the build lists only a 200 for GetEaster, GetLeapYear and GetFriday13s. GetWeek and GetWorkdays (Results<..., ValidationProblem>) list a 400 HttpValidationProblemDetails. GetNextFriday13's 404 has no content, although UseStatusCodePages answers it with problem+json. One mitigation the reports miss: the year parameters carry minimum 1583 and maximum 9999 in their schema, so a generated client knows the valid range. The undeclared 400 is still a real gap, and the route-list contract tests compare only path keys.
- **maintainer** (CONFIRMED, low, trivial): In the built API's /openapi/v1.json, /api/easter/{year}, /api/leap/{year} and /api/friday13 list only 200, while week/{date} and workdays (`Results<..., ValidationProblem>`) list 400 problem+json. /api/friday13/next documents its 404 with no content, but UseStatusCodePages answers it with problem+json. This goes against new-endpoint.md's 'Use TypedResults so OpenAPI picks up the response types'. On a scratch copy, `.ProducesValidationProblem()` added the 400 and `.ProducesProblem(404)` the body. Nothing consumes the document today, so low.
- **impact** (CONFIRMED, low, small): My build's /openapi/v1.json lists only 200 for GetEaster, GetLeapYear and GetFriday13s, while GetWeek and GetWorkdays document 400 application/problem+json; GetNextFriday13 documents its 404 with no content although the response is problem+json (seen in the test host). Calibrated down from api-02's medium: the year parameters carry `minimum: 1583, maximum: 9999` in their schemas, so a generated client knows the valid range, and an undeclared 400 surfaces as a generic API error, not a wrong result; no client of this API exists. The real cost is that new-endpoint.md promises TypedResults make OpenAPI right, and copying the [Range] pattern silently breaks it; `.ProducesValidationProblem()` on three MapGet calls plus `.ProducesProblem(404)` fixes it.

</details>

### F089

**docs/gates.md's list of required checks leaves out llm-eval and says the other checks don't block**

- **Status:** ✅ fixed — #63: the required-check list includes `llm-eval`
- **Severity:** low (reviewers: low) · **outcome:** confirmed · **fix cost:** trivial
- **Where:** `docs/gates.md:5` · **area:** API, tests, docs
- **Reported by:** `api-15` (low, high confidence), `dd-02` (low, high confidence)

**`api-15`: docs/gates.md's list of required checks leaves out llm-eval and says the other checks don't block**

Lines 4-7 list the required checks from pr-title to llm / security-review and add 'The other checks report but don't block.'. But .github/rulesets/main.json also requires `llm-eval` (since #40; scripts/check-ruleset-consistency.py passes), and gates.md:53, README.md:41 and AGENTS.md all say it is required. Line 11 says the check names are the job names in ci.yml and llm-review.yml, leaving out llm-eval.yml, which the consistency script also reads.

*Failure scenario:* Someone reads this section and expects to merge a gate-changing PR with llm-eval red. The ruleset blocks the merge.

*Suggested fix:* Add `llm-eval` to the list on lines 5-7, and llm-eval.yml to line 11.

**`dd-02`: gates.md's list of required checks omits llm-eval and says all other checks don't block**

Lines 5-7 list ten required checks and then say "The other checks report but don't block". `.github/rulesets/main.json` requires 11, including `llm-eval`. The consistency script prints "11 required checks". README.md:41-42, AGENTS.md ("Required, on its own"), ADR 0006:51-53 and gates.md's own line 52-53 ("the llm / ... checks and llm-eval are required on their own") all say it is required. Line 11 also says the check names are the job names in ci.yml and llm-review.yml, but `llm-eval` comes from llm-eval.yml (WORKFLOWS in check-ruleset-consistency.py). #40 made llm-eval required and updated only line 52 of gates.md.

*Failure scenario:* A reader using gates.md, the canonical gate reference, concludes that a red llm-eval is advisory. They merge-plan around it, then find the PR blocked by the ruleset.

*Suggested fix:* Add `llm-eval` to the list on lines 5-7, and say the names are the job names in ci.yml, llm-review.yml and llm-eval.yml.

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, low, trivial): .github/rulesets/main.json requires 11 contexts, including llm-eval since #40. gates.md:5-7 lists ten and adds 'The other checks report but don't block'. Line 11 names only ci.yml and llm-review.yml, although WORKFLOWS in check-ruleset-consistency.py includes llm-eval.yml. The same file contradicts itself at lines 52-53 ('llm-eval ... required on their own'), and README, AGENTS.md and ADR 0006 all say llm-eval is required. #40 updated only that later sentence.
- **maintainer** (CONFIRMED, low, trivial): gates.md:5-7 lists ten required checks and says the others don't block. `.github/rulesets/main.json` requires eleven, including llm-eval. #40, which made llm-eval required, only changed gates.md's `gates` note (line 52-53). Line 11 also says the check names are the job names in ci.yml and llm-review.yml, but llm-eval comes from llm-eval.yml, which check-ruleset-consistency.py reads.
- **impact** (CONFIRMED, low, trivial): main.json requires 11 checks including `llm-eval` (since #40, e466368), while gates.md:5-7 lists 10 and adds 'The other checks report but don't block', and line 11 names only ci.yml and llm-review.yml although check-ruleset-consistency.py's WORKFLOWS includes llm-eval.yml. The same file's table row (line 27) and lines 52-53, README and AGENTS.md say llm-eval is required, so a careful reader sees the contradiction and a skimming one meets a blocked merge. Nothing goes unenforced: the ruleset decides.

</details>

### F092

**Undocumented: llm-eval passes without running when there's no API key, and LLM_GATE_MISSING_KEY doesn't apply to it**

- **Status:** ✅ fixed — #63: gates.md documents the keyless `llm-eval` pass
- **Severity:** low (reviewers: low) · **outcome:** confirmed · **fix cost:** trivial
- **Where:** `docs/gates.md:27` · **area:** API, tests, docs
- **Reported by:** `dd-21` (low, high confidence), `wr-11` (low, high confidence)
- **Reviewer's accepted_in:** ADR 0002 (no-key pass, for llm-review only)

**`dd-21`: Undocumented: llm-eval passes without running when there's no API key, and LLM_GATE_MISSING_KEY doesn't apply to it**

llm-eval.yml:61-72: when the PR is relevant but `secrets.ANTHROPIC_API_KEY` is empty, it emits a notice and the Eval and Verdict steps are skipped, so the required check passes. `LLM_GATE_MISSING_KEY` is read only by llm-review.yml. gates.md documents the no-key behaviour and the variable for `llm / <check>` only. WRITEUP §4 (line 125, "checks report skipped (or fail closed with LLM_GATE_MISSING_KEY=fail)") implies the variable covers the LLM gates. dependabot.yml has a weekly `uv` group for /tools/llm-gate. Those PRs touch tools/llm-gate/ (relevant) but get no Actions secrets. The behaviour is stated only in #40's commit message.

*Failure scenario:* Dependabot bumps claude-agent-sdk/anthropic in tools/llm-gate/uv.lock. llm-eval passes with a notice, and the SDK upgrade merges with no eval run, even with LLM_GATE_MISSING_KEY=fail set.

*Suggested fix:* Document it in gates.md's llm-eval row and WRITEUP §4: "without a key (forks, Dependabot) llm-eval passes with a notice; LLM_GATE_MISSING_KEY does not apply". Or make llm-eval honour the variable.

**`wr-11`: The required llm-eval check passes without an eval when there's no API key, with no fail-closed switch, on Dependabot PRs that change llm-gate's dependencies too**

When the PR is relevant but the key is missing, the eval steps are skipped and the job succeeds, so the required llm-eval check is green. Dependabot's uv ecosystem targets /tools/llm-gate, so every such PR is relevant. These are bumps of anthropic, claude-agent-sdk or pydantic, which can change how the engines behave. They get no Actions secrets, so they pass the eval gate without an eval, and llm-review skips as well. llm-review honours LLM_GATE_MISSING_KEY=fail (ADR 0002); llm-eval has no equivalent, and docs/gates.md's llm-eval row doesn't mention the no-key pass.

*Failure scenario:* Dependabot bumps claude-agent-sdk in tools/llm-gate/uv.lock. llm-eval is relevant, has no key and reports success, and the bump merges with no eval and no LLM review.

*Suggested fix:* Honour vars.LLM_GATE_MISSING_KEY in llm-eval (fail when relevant and keyless), or add the key as a Dependabot secret so Dependabot PRs get evaluated. Document the behaviour in docs/gates.md.

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, low, trivial): llm-eval.yml:61-72 skips the eval and passes with a notice when a relevant PR has no key, and LLM_GATE_MISSING_KEY is read only in llm-review.yml:225. gates.md's llm-eval row, ADR 0006 and WRITEUP §4 don't say so (only #40's commit message does), and Dependabot's uv group targets /tools/llm-gate. Not ACCEPTED: ADR 0002 accepts the default keyless pass for llm-review, which has a fail-closed switch, not for llm-eval. dd-21's scenario overreaches. With LLM_GATE_MISSING_KEY=fail, llm / code-review and llm / security-review still run without a key and fail closed on that PR, which is high risk because tools/llm-gate/** is, so it can't merge without an override. Without the switch, merging unreviewed is ADR 0002's accepted default. What remains is a documentation gap plus a missing switch for llm-eval.
- **maintainer** (CONFIRMED, low, trivial): With no key, llm-eval.yml:61-72 skips the eval with a notice and the required check passes. LLM_GATE_MISSING_KEY is read only in llm-review.yml:225-227. The behaviour was a stated choice in #40's commit message. But ADR 0002's no-key consequence covers the llm-review workflow only, and neither gates.md's llm-eval row nor WRITEUP section 4 mentions it, so this is not ACCEPTED. Dependabot's uv group targets /tools/llm-gate, so SDK bumps are relevant to llm-eval and get no Actions secrets, as wr-11 says.
- **impact** (CONFIRMED, low, trivial): llm-eval.yml:61-72 emits a notice and skips the eval when the PR is relevant but has no key, so the required check passes; LLM_GATE_MISSING_KEY is read only by llm-review.yml, gates.md documents the no-key path only for `llm / <check>`, and Dependabot's uv group targets /tools/llm-gate without Actions secrets. ADR 0002 accepts the no-key skip for llm-review, not for the required llm-eval, so not ACCEPTED. Calibration: even with a key, a lock-file-only SDK bump wouldn't be evaluated, because the review cache key (cache.py: check, engine, model, prompt, diff) excludes the SDK version and llm-gate code, so the eval would replay main's warm cache; wr-11's fixes (honour the variable or add a Dependabot secret) wouldn't get SDK bumps tested, and the defect that holds is the undocumented pass.

</details>

### F093

**Kyverno update instructions point at "the chart version in the justfile", which doesn't exist**

- **Status:** ✅ fixed — #63: the comment points at `deploy/kyverno/chart.sha256`
- **Severity:** low (reviewers: low) · **outcome:** confirmed · **fix cost:** trivial
- **Where:** `deploy/kyverno/values.yaml:5` · **area:** API, tests, docs
- **Reported by:** `cr-ops-21` (info, high confidence), `dd-09` (low, high confidence)

**`cr-ops-21`: values.yaml says the chart version lives in the justfile; it lives in chart.sha256**

The comment says 'Update all of them together, with the chart version in the justfile'. But the justfile derives the chart version from deploy/kyverno/chart.sha256's file name (k8s-policy-up, and admission-smoke too). What the justfile pins is the CLI version (lint-policies want=1.19.1), and ci.yml's kyverno-cli image digest has to match that as well. Someone bumping Kyverno by this comment looks in the wrong place and can miss the CLI pins.

*Failure scenario:* A Kyverno bump following the comment updates values.yaml and searches the justfile for a chart version, leaving chart.sha256 or the CLI pins behind.

*Suggested fix:* List the places: chart.sha256 (version and hash), this file's digests, the justfile's lint-policies want=, and ci.yml's kyverno-cli image.

**`dd-09`: Kyverno update instructions point at "the chart version in the justfile", which doesn't exist**

"Update all of them together, with the chart version in the justfile, after verifying the new release the same way." The justfile has no chart version. k8s-policy-up and release.yml's admission-smoke both derive it from the file name in deploy/kyverno/chart.sha256 (`kyverno-3.9.1.tgz` plus its sha256). The justfile only pins the CLI (`lint-policies`: want=1.19.1), and ci.yml pins the kyverno-cli image (v1.19.1@sha256:...).

*Failure scenario:* Someone upgrading Kyverno updates the image digests here and looks for a chart version in the justfile. They never touch chart.sha256, so k8s-policy-up and admission-smoke keep installing chart 3.9.1 with the new images, or the CLI and ci.yml image stay on 1.19.1 and lint-policies fails.

*Suggested fix:* "Update all of them together with deploy/kyverno/chart.sha256 (chart file name and hash), the CLI version in the justfile's lint-policies and ci.yml's kyverno-cli image."

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, low, trivial): deploy/kyverno/values.yaml:5-6 says to update the digests 'with the chart version in the justfile', but the justfile has no chart version. k8s-policy-up derives it from the file name in deploy/kyverno/chart.sha256 (justfile:171-174), and release.yml's admission-smoke does the same. The justfile pins only the CLI version check (want=1.19.1, line 263), and ci.yml pins the kyverno-cli image. Following the comment can leave chart.sha256 or the CLI pins behind.
- **maintainer** (CONFIRMED, low, trivial): deploy/kyverno/values.yaml:5-6 says to update the pins 'with the chart version in the justfile'. Since #53, k8s-policy-up and release.yml's admission-smoke both take the chart version from the file name in deploy/kyverno/chart.sha256, so the comment was never right. The justfile pins only the CLI (`lint-policies` want=1.19.1), and ci.yml pins the kyverno-cli image. A bump that follows the comment can leave chart.sha256 or the CLI pins behind.
- **impact** (CONFIRMED, low, trivial): deploy/kyverno/values.yaml:5-6 says to update the pins 'with the chart version in the justfile'; k8s-policy-up (justfile:171-177) and release.yml's admission-smoke (406-409) derive the chart version from deploy/kyverno/chart.sha256's file name (kyverno-3.9.1.tgz), and the justfile pins only the CLI (lint-policies want=1.19.1), alongside ci.yml's kyverno-cli image. A Kyverno upgrade is a deliberate, verified task and ADR 0010 names chart.sha256, so the misdirection costs minutes, and a missed CLI pin fails lint-policies with a clear message.

</details>

### F094

**WRITEUP §5 says the metrics still count drill 19's /llm-fp marking; §3 and metrics.py say the later /llm-ack reversed it**

- **Status:** ✅ fixed — #63: WRITEUP says the `/llm-ack` reversed it, and records #60's real false positive
- **Severity:** low (reviewers: low) · **outcome:** confirmed · **fix cost:** trivial
- **Where:** `docs/WRITEUP.md:169` · **area:** API, tests, docs
- **Reported by:** `dd-04` (low, high confidence), `dd-05` (low, high confidence), `dd-06` (low, high confidence)

**`dd-04`: WRITEUP §5 says the metrics still count drill 19's /llm-fp marking; §3 and metrics.py say the later /llm-ack reversed it**

§5 (added in #56): "Feedback is input to a person's decision, not ground truth: the metrics still count that marking." #57 then made the latest feedback by time win (metrics.py:133-139). It also updated §3 line 68 to "0 of 234. The one /llm-fp ... was reversed with /llm-ack", but left §5 alone. The audit log has four feedback records on #43 cr-e207 (fp 19:47Z, fp 19:58Z, ack 20:01Z, fp 20:20Z on 10-16), then an ack at 2026-10-17T18:21:26Z. I recomputed the metrics offline from origin/audit-log: at 17:40Z code-review shows 1 fp / 0 ack, after 18:21Z 0 fp / 1 ack. So the metrics no longer count the marking.

*Failure scenario:* A reader of the write-up gets two opposite statements about the same data point in one document.

*Suggested fix:* Replace the last sentence of the bullet with: "... not ground truth. Marking it /llm-ack afterwards reversed it in the metrics (the latest feedback wins)."

**`dd-05`: WRITEUP still calls drill 19's /llm-fp "the only" one; a real false positive since drove #60's prompt fix**

Line 151 ("The one false positive marked so far was on a drill"), line 165 ("The only `/llm-fp` so far (drill 19)") and line 68 ("The one `/llm-fp`") are out of date. The audit log has a feedback `fp` on #53 tr-835a (2026-10-17T19:29:27Z), a real false positive ($IMAGE is defined in release.yml's workflow-level env). #60 turned it into eval case fp-tr-835a. llm-eval failed with fp_regressions 3. The test-review prompt was then fixed, and the forbid matcher moved from category to a title regex. That is exactly the "what I changed after measuring" material §5 is for, and the write-up doesn't mention it. (The §3 snapshot numbers themselves can stay dated.)

*Failure scenario:* A reader concludes the /llm-fp → eval-case → prompt-fix loop has never worked on a real mistake, when the repository's last merged PR shows that it has.

*Suggested fix:* Drop "so far"/"only", and add a §5 bullet about tr-835a → fp-tr-835a → prompt fix and title-regex forbid rules (#60).

**`dd-06`: PLAN-v2 Status still lists the live /llm-fp → eval-case loop as open; #60 closed it**

"Left open on purpose: ... The live `/llm-fp` → eval-case loop: waiting for a genuine false positive." The results note at line 635-638 also says "drill 19's only `/llm-fp` had marked a true positive, so the generated case was discarded". #60 (43ec3c2, after the wrap-up PR #59) describes itself as "Drill 19's last step, with a real false positive". A genuine fp (tr-835a on #53) was recorded, `eval add-from-fp` produced tools/llm-gate/evals/cases/fp-tr-835a, and llm-eval caught the regression. The Status section is the part of PLAN-v2 meant to be current, as opposed to the plan kept as written.

*Failure scenario:* Someone picking up remaining work from the Status section spends time on an item that's already done.

*Suggested fix:* Remove the third "left open" bullet. Extend the drill-results note: "drill 19's live loop ran on a genuine false positive in #60 (fp-tr-835a)".

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, low, small): dd-04: WRITEUP §5 (03f427b, #56) says 'the metrics still count that marking'. §3 line 68 (rewritten in #57) says the marking was reversed with /llm-ack, and metrics.py now lets the latest feedback by time win; the last record on #43 cr-e207 is an ack at 2026-10-17T18:21:26Z. dd-05: lines 151 and 165 still call the drill-19 marking the only /llm-fp. audit-log has an fp on #53 tr-835a at 19:29:27Z, a genuine one (IMAGE is in release.yml's workflow-level env, line 21), which #60 turned into fp-tr-835a. dd-06: PLAN-v2:42, written in #59 at 19:52Z after that fp, still lists the live loop as open, and the results note (line 635) repeats 'drill 19's only /llm-fp'. #60 changed neither.
- **maintainer** (CONFIRMED, low, trivial): On origin/audit-log, cr-e207 (#43) ends with an ack at 2026-10-17T18:21:26Z. Recomputing with metrics.py's latest-by-time rule (#57) gives 1 fp before that and 0 fp / 1 ack after. WRITEUP section 3 (line 68) says the marking was reversed, but section 5 (lines 169-170) still says 'the metrics still count that marking'; #57 changed only section 3. A real false positive (tr-835a on #53, 19:29Z) and #60's case and prompt fix also make 'the one/only /llm-fp so far' (lines 68, 151, 165) and PLAN-v2 Status's open '/llm-fp -> eval-case loop' (line 42) stale. #60 changed neither document.
- **impact** (CONFIRMED, low, trivial): All three reports check out against origin/audit-log: #43 cr-e207's feedback ends with an `ack` at 2026-10-17T18:21:26Z, so under #57's latest-by-time rule the metrics no longer count drill 19's /llm-fp, contradicting WRITEUP §5:169-170 (dd-04); a real fp on #53 tr-835a (19:29:27Z) became eval case fp-tr-835a in #60, so 'the only /llm-fp so far' (§3:68, §5:151, §5:165) is stale (dd-05); and PLAN-v2's Status still lists the live /llm-fp to eval-case loop as left open (dd-06). The docs went stale with the last commit; readers of the write-up (README's start-here doc) get contradictory statements and miss the project's best 'changed after measuring' example.

</details>

### F095

**"Denied in calendar-gates since v0.3.1": the Deny switch came after v0.3.1 and no release has exercised it**

- **Status:** ✅ fixed — #63 documented it; v0.3.2's admission-smoke ran the Deny policy for the first time and passed
- **Severity:** low (reviewers: low) · **outcome:** confirmed · **fix cost:** trivial
- **Where:** `docs/adr/0010-admission-control.md:67` · **area:** API, tests, docs
- **Reported by:** `dd-07` (low, high confidence), `dd-08` (low, medium confidence)

**`dd-07`: "Denied in calendar-gates since v0.3.1": the Deny switch came after v0.3.1 and no release has exercised it**

Tag v0.3.1 points at b8f0e01 (#53), whose deploy/policies/base/llm-review.yaml has `validationActions: [Audit]`. The switch to Deny is #54 (526e1b0), merged 19:15 after v0.3.1 was tagged at 18:55. #54's own message says: "Not run on a cluster (the local clusters are down); the next release's admission-smoke exercises it." The changed admission-smoke assertions (either policy may refuse edge) have therefore never run either. The same wording is in PLAN-v2.md:34 ("Deny since v0.3.1 (#54)") and the policy comment deploy/policies/base/llm-review.yaml:104. ADR 0010's "Proof on every release" reads as if this Deny has been proven. Related, but distinct: PLAN-v2's open item that the "LLM-review alone denies" proof is missing.

*Failure scenario:* A reader believes release v0.3.1 enforced the LLM-review attestation and that admission-smoke has passed with it. A broken regex or Deny policy would only surface at the next tag, after approval and promotion.

*Suggested fix:* "Deny on main since #54 (after v0.3.1, once v0.3.0 and v0.3.1 carried the attestation); the next release's admission-smoke is the first to run it"; mirror this in PLAN-v2:34 and the policy comment.

**`dd-08`: WRITEUP credits testing with finding the nondeterministic denial message; #54 says it was never run**

Under "Testing found what reading didn't", WRITEUP lists: "Two Deny policies in parallel webhooks made the denial message nondeterministic, and the smoke test would have failed a correct release." Two Deny image policies only exist since #54. Its message says the change was reasoned out ("Without this, a correct denial by the other policy would fail the release") and "Not run on a cluster". During the #53 spike, llm-review was Audit: v0.2.0, which lacks that attestation, was admitted. So no test could have shown two parallel Deny refusals. The other two items in that bullet (cold-check timeout, inotify) do come from the spike.

*Failure scenario:* The "what didn't work" section, meant to be the most convincing part, cites a test result that the PR history contradicts.

*Suggested fix:* Move it out of "Testing found", for example: "Reading the webhook model showed two parallel Deny policies would make the denial message nondeterministic; admission-smoke now accepts either (untested until the next release)."

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, low, trivial): dd-07: tag v0.3.1 points at b8f0e01, whose llm-review.yaml has validationActions [Audit]. #54 (526e1b0) switched to Deny 20 minutes after the tag, and its message says 'Not run on a cluster ... the next release's admission-smoke exercises it'. There is no later tag, so neither the Deny nor the either-policy regex has run in admission-smoke. 'Since v0.3.1' is ambiguous rather than false (its own clause says 'once v0.3.0 and v0.3.1 carried it'), and no doc claims the Deny was exercised. dd-08: the only recorded source for the 'nondeterministic denial message' is #54's reasoning, yet WRITEUP:157 (#55) files it under 'Testing found'. Drill 23 ran on the project cluster after #54, so an unrecorded observation can't be ruled out, which makes dd-08 plausible rather than proven.
- **maintainer** (CONFIRMED, low, trivial): Tag v0.3.1 points at b8f0e01 (#53), whose llm-review.yaml has validationActions [Audit]. The switch to Deny is #54 (526e1b0), merged about 20 minutes after the tag, and its message says it wasn't run on a cluster. So 'denied since v0.3.1' (ADR 0010:67-68, PLAN-v2:34, llm-review.yaml:1) suggests a release has exercised this Deny, and with it admission-smoke's new either-policy regex; none has. dd-08 is right too: #53's message reports only the webhook-timeout and inotify findings, and #54 reasoned out the parallel-webhook nondeterminism, so WRITEUP:157-158 shouldn't list it under 'Testing found'.
- **impact** (CONFIRMED, low, trivial): Tag v0.3.1 (created 18:55:43) points at b8f0e01 (#53), whose llm-review policy has `validationActions: [Audit]`; #54 (526e1b0, 19:15:47) switched it to Deny, and its message says 'Not run on a cluster ... the next release's admission-smoke exercises it'. No tag exists after v0.3.1, so neither the Deny policy nor #54's either-policy admission-smoke assertions have run, while ADR 0010:603-604, PLAN-v2:34 and WRITEUP's 'Testing found what reading didn't' bullet (dd-08) read as if they had. The wording is low; the practical point is that the next release is the first test of this path (see F084).

</details>

### F100

**AGENTS.md says only audit-collect.yml writes the audit-log branch; llm-feedback.yml writes to it too**

- **Status:** ✅ fixed — #63: AGENTS.md names `llm-feedback.yml` as a writer too
- **Severity:** low (reviewers: low) · **outcome:** confirmed · **fix cost:** trivial
- **Where:** `AGENTS.md:21` · **area:** API, tests, docs
- **Reported by:** `dd-03` (low, high confidence)

The Layout row reads "Audit records of the LLM gate, written only by `audit-collect.yml` (ADR 0005)". Since Phase 16, `llm-feedback.yml` (lines 82-105, `contents: write`) PUTs `events/YYYY/MM/DD/feedback-*.jsonl` files onto audit-log. These hold `feedback`, `override`, `risk_override` and `feedback_rejected` records. ADR 0007 and ADR 0008 ("`llm-feedback.yml` writes these records only after checking the commenter's role") describe this, and triage reads `/llm-risk` from there. The branch holds six such files today (for example events/2026/10/17/feedback-6239579523.jsonl). This is a claim about who can write the trust root, so it should be exact.

*Failure scenario:* Someone auditing who can write audit-log reviews only audit-collect.yml, as AGENTS.md says. They miss the second writer, which runs on issue_comment with contents: write, issues: write and actions: write.

*Suggested fix:* "Audit records of the LLM gate, written only by trusted default-branch workflows: `audit-collect.yml` (review runs, ADR 0005) and `llm-feedback.yml` (`/llm-*` commands, ADR 0007)".

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, low, trivial): AGENTS.md:21 says audit-log is 'written only by audit-collect.yml'. But llm-feedback.yml holds contents: write (line 34) and writes events/YYYY/MM/DD/feedback-*.jsonl through the contents API (lines 82-105), and six such files are on the branch. ADR 0007 and ADR 0008 describe this second writer. In the document that names the trust root, 'only' should be exact.
- **maintainer** (CONFIRMED, low, trivial): AGENTS.md:21 says the audit-log branch is 'written only by audit-collect.yml'. llm-feedback.yml (contents: write, lines 82-105) also PUTs events/YYYY/MM/DD/feedback-*.jsonl there; the branch holds 9 such files, and ADR 0007 and 0008 describe this second writer. The line is a claim about who can write the trust root, so it should name both trusted workflows.
- **impact** (CONFIRMED, low, trivial): AGENTS.md:21 says audit-log is 'written only by audit-collect.yml'; llm-feedback.yml (contents: write, issue_comment trigger) PUTs events/YYYY/MM/DD/feedback-*.jsonl onto it (lines 82-105), and the branch holds nine such files. ADR 0007 and 0008 describe the second writer correctly, but AGENTS.md loads in every agent session and this is the inventory of who writes the trust root, so a review of writers that starts there misses a workflow holding write tokens.

</details>

### F101

**The kyverno test file says it runs in `just lint`; it runs in `just lint-policies`**

- **Status:** ✅ fixed — #63: the test file says `just lint-policies`
- **Severity:** low (reviewers: low) · **outcome:** confirmed · **fix cost:** trivial
- **Where:** `deploy/policies/tests/kyverno-test.yaml:1` · **area:** API, tests, docs
- **Reported by:** `dd-10` (low, high confidence)

"Offline tests for the policy that needs no registry (`just lint`, ci.yml lint)." `just lint` (justfile:70-83) doesn't run kyverno. The tests run in `lint-policies` (justfile:258-267, part of `just ci`) and in ci.yml's lint job (lines 118-122). ADR 0010:80 and gates.md:167 name `just lint-policies` correctly.

*Failure scenario:* A developer edits deploy/policies/base/images.yaml, runs `just lint` as the comment says, and sees green. The kyverno test failure only shows up in CI's lint job.

*Suggested fix:* "(`just lint-policies`, ci.yml's lint job)".

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, info, trivial): deploy/policies/tests/kyverno-test.yaml:1 says the tests run in `just lint`, but the lint recipe (justfile:70-83) has no kyverno step. They run in lint-policies (justfile:260-267, part of `just ci`) and in ci.yml's lint job. ADR 0010 and gates.md:167 name lint-policies correctly. The impact is small because `just ci`, which AGENTS.md says to run, includes lint-policies.
- **maintainer** (CONFIRMED, low, trivial): The header of deploy/policies/tests/kyverno-test.yaml says the tests run in `just lint`. `lint` (justfile:70-83) doesn't run kyverno; `lint-policies` (justfile:258-267) does, as does ci.yml's lint job (lines 118-122). ADR 0010:80 and gates.md:167 name lint-policies correctly. Only the comment has drifted.
- **impact** (CONFIRMED, low, trivial): kyverno-test.yaml:1 says the tests run in `just lint`, but `just lint` (justfile:70-83) runs no kyverno; `lint-policies` does (justfile:260-267, part of `just ci`), as does ci.yml's lint job. Someone who edits a policy and runs the named recipe sees green and learns otherwise from CI; AGENTS.md's 'run `just ci`' catches it locally, so the cost is one round trip.

</details>

### F102

**The lint gate's local equivalent and tool list omit the kyverno policy tests that CI's lint job runs**

- **Status:** ✅ fixed — #63: the lint row lists the policy tests, mypy and `lint-policies`
- **Severity:** low (reviewers: low) · **outcome:** confirmed · **fix cost:** trivial
- **Where:** `docs/gates.md:20` · **area:** API, tests, docs
- **Reported by:** `dd-11` (low, high confidence)

gates.md's lint row gives Local: `just lint lint-chart`, and lists "actionlint, zizmor, hadolint, yamllint, shellcheck, ruff, the llm-gate tests, the ruleset consistency check, helm lint or kubeconform". ci.yml's lint job also runs `kubectl kustomize deploy/policies` and `kyverno test deploy/policies/tests` (lines 118-122), plus mypy. The local equivalent is therefore `just lint lint-chart lint-policies`. gates.md:167-168 itself says lint-policies is "part of ... the lint job". AGENTS.md:66 ("lint: actionlint, zizmor, hadolint, yamllint, shellcheck, ruff, mypy, pytest, helm lint + kubeconform") omits the kyverno tests and the consistency check.

*Failure scenario:* A PR that breaks deploy/policies passes `just lint lint-chart` locally, as documented, but fails the required `lint` check.

*Suggested fix:* Local: `just lint lint-chart lint-policies`. Add "mypy, the kyverno policy tests" to the tool lists in gates.md and AGENTS.md.

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, low, trivial): gates.md:20 gives the lint gate's local equivalent as `just lint lint-chart` and lists its tools without the policy tests. ci.yml's lint job ends with `kubectl kustomize deploy/policies` and `kyverno test deploy/policies/tests`, so the local equivalent is `just lint lint-chart lint-policies`. gates.md:167-168 itself says lint-policies is part of the lint job, and AGENTS.md's gate list leaves it out too. mypy is arguably covered by 'the llm-gate tests', so that part is minor.
- **maintainer** (CONFIRMED, low, trivial): gates.md:20 gives the lint gate's local equivalent as `just lint lint-chart`, and its tool list leaves out mypy and the kyverno policy tests that ci.yml's lint job runs (lines 118-122). gates.md:167-168 itself says lint-policies is part of the lint job. AGENTS.md:66 leaves out the kyverno tests and the consistency check. So a policy change can pass the documented local command and still fail the required `lint` check.
- **impact** (CONFIRMED, low, trivial): gates.md:20 gives `just lint lint-chart` as the lint gate's local equivalent and lists its tools without mypy or the kyverno policy tests, though ci.yml's lint job runs `kubectl kustomize` and `kyverno test` (and mypy); gates.md:167-168 itself says lint-policies is part of the lint job, and AGENTS.md's lint list omits the kyverno tests and the consistency check. A policy-breaking PR passes the documented local command and fails the required lint check: one CI round trip.

</details>

### F103

**/gate-drill sends "drills 13 and up" to PLAN-v2, but drill 13 is in PLAN.md and v2 starts at 14**

- **Status:** ✅ fixed — #63: `/gate-drill` sends drills 1-13 to PLAN.md, 14+ to PLAN-v2
- **Severity:** low (reviewers: low) · **outcome:** confirmed · **fix cost:** trivial
- **Where:** `.claude/commands/gate-drill.md:7` · **area:** API, tests, docs
- **Reported by:** `dd-12` (low, high confidence)

"... or for drills 13 and up, the drill table in docs/PLAN-v2.md." docs/PLAN.md:739 has drill 13 ("Set runAsUser: 0 in the chart"). PLAN-v2's Phase 21 table starts at 14 ("numbering continues from v1"). The parenthetical at line 12-13 ("drills 7, 8, 9 and 11 do") names only v1 drills. Among v2 drills, 23 retags a release and pushes a local build to GHCR under the release name, and 19 posts comments from a second account. The general rule ("anything that pushes") still covers them, but the examples suggest otherwise.

*Failure scenario:* `/gate-drill 13` looks for drill 13 in PLAN-v2, doesn't find it, and either stops ("phase isn't done") or improvises.

*Suggested fix:* "... or for drills 14 and up ..."; add 23 (and 19) to the list of drills that need an OK.

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, low, trivial): gate-drill.md:6-7 sends 'drills 13 and up' to PLAN-v2.md, but drill 13 is in PLAN.md's table (line 739), and PLAN-v2's table starts at 14 ('numbering continues from v1', line 619). The examples in step 2 name only v1 drills, but its general rule ('anything that pushes ...') still covers drills 19 and 23, so only the routing is wrong.
- **maintainer** (CONFIRMED, low, trivial): gate-drill.md:6-7 sends 'drills 13 and up' to PLAN-v2.md, but drill 13 ('Set runAsUser: 0') is in PLAN.md's Phase 12 table and PLAN-v2's table starts at 14. The examples of drills that need an OK first (7, 8, 9, 11) are all from v1, while drill 23 pushes to GHCR under a release name and drill 19 needs a second account. The general rule ('anything that pushes ...') still covers those, so low.
- **impact** (CONFIRMED, low, trivial): gate-drill.md:6-7 sends 'drills 13 and up' to PLAN-v2, but drill 13 is in PLAN.md:739 and PLAN-v2's table starts at 14. The misroute is harmless (an agent finds 13 in PLAN.md or stops), but the parenthetical of drills needing an OK (7, 8, 9, 11) also omits drill 23, which pushes a local build to GHCR under the release name, that is, overwrites a mutable public release tag; the general 'anything that pushes' rule still covers it, which keeps this low.

</details>

### F105

**The entry docs point only at docs/PLAN.md; PLAN-v2.md (Phases 13-21, drills 14-23) is never mentioned**

- **Status:** ✅ fixed — #63: AGENTS.md points at PLAN-v2.md and the review findings
- **Severity:** low (reviewers: low) · **outcome:** confirmed · **fix cost:** trivial
- **Where:** `AGENTS.md:6` · **area:** API, tests, docs
- **Reported by:** `dd-14` (low, high confidence)

AGENTS.md:6: "The full plan, phase by phase, is in `docs/PLAN.md`. Check which phase is in progress before adding things from later phases." AGENTS.md:22 lists docs/ as "`PLAN.md`, `gates.md`, `adr/`" (no PLAN-v2, WRITEUP or metrics). README.md:9: "docs/PLAN.md is the plan". CLAUDE.md:6: "/gate-drill <n> sets up one of the drills from docs/PLAN.md Phase 12". gate-drill.md itself handles PLAN-v2's drills 14-23. Both plans are now done.

*Failure scenario:* An agent told to "check which phase is in progress" reads only PLAN.md, where every phase is done. It misses PLAN-v2's Status section with its deviations and open limits.

*Suggested fix:* "The plan is docs/PLAN.md (v1, Phases 0-12) and docs/PLAN-v2.md (Phases 13-21, with a Status section of deviations and open limits)". List PLAN-v2.md, WRITEUP.md and metrics.md in the docs/ row, and mention PLAN-v2's drills in CLAUDE.md.

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, low, trivial): AGENTS.md:6 points agents only at docs/PLAN.md for phases. Its docs/ row (line 22) lists PLAN.md, gates.md and adr/ but not PLAN-v2.md, WRITEUP.md or metrics.md, and CLAUDE.md:6 says /gate-drill uses PLAN.md's Phase 12 drills, although gate-drill.md also routes to PLAN-v2. README does start readers at WRITEUP, and the ADRs that AGENTS.md cites carry v2's decisions, so what's mostly lost is PLAN-v2's Status (deviations and open limits).
- **maintainer** (CONFIRMED, low, trivial): AGENTS.md:6 ('The full plan ... is in docs/PLAN.md. Check which phase is in progress'), AGENTS.md:22 (docs/: PLAN.md, gates.md, adr/), README.md:9 and CLAUDE.md:6 never mention PLAN-v2.md, WRITEUP.md or metrics.md. Phases 13-21 and the Status section with the deviations and open limits are in PLAN-v2.md. PLAN-v2's own preamble says every phase updates AGENTS.md/CLAUDE.md.
- **impact** (CONFIRMED, low, trivial): AGENTS.md:6 ('The full plan, phase by phase, is in docs/PLAN.md. Check which phase is in progress'), AGENTS.md:22's docs/ row, README.md:9 and CLAUDE.md:6 mention only PLAN.md; PLAN-v2.md (Phases 13-21 and its Status section of deviations and deliberate open limits) appears in none of them, and PLAN.md's header still says 'No code yet'. An agent following AGENTS.md reads a plan whose every phase is done and misses the deviation table; the ADRs AGENTS.md links cover most of the substance, which keeps this low.

</details>

### F107

**llm-eval also fails when a forbidden (fp-regression) finding returns; gates.md and WRITEUP don't say so**

- **Status:** ✅ fixed — #63: gates.md lists `fp_regressions` as a failure mode
- **Severity:** low (reviewers: low) · **outcome:** confirmed · **fix cost:** trivial
- **Where:** `docs/gates.md:27` · **area:** API, tests, docs
- **Reported by:** `dd-20` (low, high confidence)

gates.md's llm-eval row: "scores worse than evals/baseline.json beyond evals/thresholds.yaml (recall, false blocks, flips, cost)". evals.compare also fails on any `fp_regressions` (a forbid rule matched, an absolute check that isn't in thresholds.yaml), on a verdict-accuracy drop, and for triage on risk accuracy and floor violations. #60's first push failed llm-eval with fp_regressions 3. The Fix column suggests updating the baseline, which can't clear an fp regression. WRITEUP §2 (line 49) lists the thresholds without fp regressions. The evals README Scores table (lines 67-77) has no fp_regressions, risk-accuracy or floor-violation rows.

*Failure scenario:* A prompt change revives a confirmed false positive. llm-eval fails, the author reads gates.md, runs `just eval-baseline` as the fix column suggests, and the check still fails.

*Suggested fix:* List "verdict accuracy, any forbidden (fp-regression) finding, triage accuracy or a result below the floor". Say fp regressions and floor violations are absolute and can't be baselined away, and add the rows to the evals README Scores table.

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, low, trivial): evals.compare (evals.py:621-692) also fails on a verdict-accuracy drop and on any fp_regressions (limit 0, whatever the baseline). For triage it also fails on risk accuracy and on floor violations. gates.md:27 lists only recall, false blocks, flips and cost, and its fix column offers a baseline update, which can't clear an fp regression or a floor violation. WRITEUP §2's row lists everything except fp regressions, and the evals README's Scores table has no fp_regressions row (the fp-regression and triage kinds are described above it). #60's first push failing with fp_regressions 3 shows the case is real.
- **maintainer** (CONFIRMED, low, trivial): evals.compare also fails on any fp_regressions or floor_violations (absolute: passes only at 0), on a verdict-accuracy drop and, for triage, on a risk-accuracy drop. gates.md:27 names only recall, false blocks, flips and cost, and its Fix column (update the baseline) can't clear an absolute fp regression. WRITEUP section 2's llm-eval row leaves out fp regressions. The evals README mentions both rules in its case-kind bullets but not in the Scores table. #60's first push failed in exactly this way.
- **impact** (CONFIRMED, low, trivial): evals.compare fails on any `fp_regressions` (ok only at 0) and any `floor_violations` regardless of the baseline, plus verdict- and risk-accuracy drops; gates.md:27 lists only recall, false blocks, flips and cost and suggests `just eval-baseline`, which can't clear an fp regression (#60's first push failed with fp_regressions 3). WRITEUP §2:49 lists the verdict and triage thresholds but not fp regressions, and the evals README Scores table lacks them. The sticky llm-eval comment shows the failing row, so an author loses one iteration, not more.

</details>

### F108

**/new-endpoint skips the two exact OpenAPI route lists a new endpoint must be added to**

- **Status:** ✅ fixed — #63: `/new-endpoint` names both OpenAPI route lists
- **Severity:** low (reviewers: low) · **outcome:** confirmed · **fix cost:** trivial
- **Where:** `.claude/commands/new-endpoint.md:21` · **area:** API, tests, docs
- **Reported by:** `dd-22` (low, high confidence)

/new-endpoint (unchanged since the initial skeleton) asks for a calculator, endpoint, unit tests, integration tests and a request in http/calendar.http. The test commit that followed added two exact-match route lists. MetaTests.OpenApiListsEveryRoute uses IsEquivalentTo over the paths of /openapi/v1.json, and http/calendar.http's "openapi: lists every route" handler (lines 208-220) compares JSON.stringify of the sorted paths. A new route breaks both until it's added to both lists.

*Failure scenario:* Following /new-endpoint for `/api/quarter/{date}` produces a red `just test` (MetaTests) and red http-tests, with nothing in the instructions explaining why.

*Suggested fix:* Add a step: "add the route to the OpenAPI route lists in tests/CalendarGates.IntegrationTests/MetaTests.cs (OpenApiListsEveryRoute) and the `### OpenAPI document` request in http/calendar.http".

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, info, trivial): new-endpoint.md's five steps don't mention the two exact route lists, MetaTests.OpenApiListsEveryRoute (IsEquivalentTo over the paths) and calendar.http's sorted 'openapi: lists every route' list, so a new route breaks both. The command's own last step (`just test`) fails at once, in a test named for the route list, so following it costs a retry, not a broken merge. Hence info.
- **maintainer** (CONFIRMED, low, trivial): MetaTests.OpenApiListsEveryRoute uses IsEquivalentTo over an exact path list, and calendar.http's OpenAPI request compares the sorted paths with JSON.stringify. Any new route fails both until it's added to both lists. new-endpoint.md, unchanged since 7e7b1ce, doesn't say so. The failing test points at the cause quickly, so low.
- **impact** (CONFIRMED, low, trivial): new-endpoint.md lists calculator, endpoint, unit tests, integration tests and a .http request, but not the two exact route lists: MetaTests.OpenApiListsEveryRoute (IsEquivalentTo over the eight paths) and calendar.http's 'openapi: lists every route' (sorted JSON equality). Every endpoint scaffolded by the command therefore turns `just test` and http-tests red; the assertion output prints the actual path list, so it costs one iteration each time.

</details>

### F109

**The quick start's requirements don't cover `just setup` / `just ci`, which now need an exact kyverno CLI**

- **Status:** ✅ fixed — #63: the README lists what `just lint` needs on PATH
- **Severity:** low (reviewers: low) · **outcome:** confirmed · **fix cost:** trivial
- **Where:** `README.md:21` · **area:** API, tests, docs
- **Reported by:** `dd-23` (low, high confidence)

README: "Requires the .NET 10 SDK, just and uv; the container, Kubernetes and LLM recipes also need podman, kind/helm and an Anthropic API key". The quick start runs `just setup` (lefthook) and `just ci` (fmt-check, lint, lint-chart, lint-policies, build, test). `lint` needs actionlint, hadolint, shellcheck and gh (`gh auth token` for zizmor). `lint-chart` needs helm and kubeconform. `lint-policies` needs kubectl and exactly kyverno CLI 1.19.1: it exits with "kyverno CLI 1.19.1 needed, found none" (justfile:263-265). README.md:17's comment for `just ci` also omits the policy tests.

*Failure scenario:* A new contributor with only .NET, just and uv runs the documented quick start. `just ci` fails, first on actionlint and then on the kyverno CLI version check.

*Suggested fix:* List the lint toolchain (actionlint, hadolint, shellcheck, gh, helm, kubeconform, kubectl, kyverno CLI 1.19.1, lefthook) or point to ci.yml's pinned versions, and add "policy tests" to the `just ci` comment.

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, low, small): README.md:20-22 requires only the .NET SDK, just and uv for the quick start. But `just setup` runs lefthook install, and `just ci` (fmt-check lint lint-chart lint-policies build test) needs actionlint, hadolint, shellcheck, gh (zizmor's token), helm, kubeconform, kubectl and exactly kyverno CLI 1.19.1 (justfile:263-265 exits otherwise). The quick-start comment for `just ci` (README:16) also leaves out the policy tests.
- **maintainer** (CONFIRMED, low, trivial): README.md:21-23 asks for the .NET 10 SDK, just and uv for the quick start. But `just setup` needs lefthook, and `just ci` needs actionlint, hadolint, shellcheck, gh (zizmor's token), helm, kubeconform, kubectl and exactly kyverno 1.19.1: lint-policies exits with 'kyverno CLI 1.19.1 needed, found none'. The README's comment on `just ci` (line 17) also leaves out the policy tests.
- **impact** (CONFIRMED, low, trivial): README.md:21-23 lists the .NET SDK, just and uv (plus podman, kind/helm and a key for container, k8s and LLM recipes), but `just setup` needs lefthook and `just ci` runs lint (actionlint, hadolint, shellcheck, gh for zizmor's token), lint-chart (helm, kubeconform) and lint-policies (kubectl, exactly kyverno CLI 1.19.1, justfile:263-265); README.md:17's comment also omits the policy tests. A newcomer with only the listed tools stops at the first lint step; each error names the missing tool and the repo is collaborator-only, so low.

</details>

#### Confirmed: info

### F028

**eval add-from-fp looks up a 16-bit finding id across every PR and takes the last match**

- **Status:** open
- **Severity:** info (reviewers: low) · **outcome:** confirmed · **fix cost:** trivial
- **Where:** `tools/llm-gate/src/llm_gate/evals.py:843` · **area:** llm-gate and review prompts
- **Reported by:** `cr-gate-12` (low, high confidence)

A finding id is the check prefix plus 4 hex digits of a hash, so there are 65,536 values per check. case_from_false_positive scans every gate_run in the log for the id, whatever the PR, and keeps the last match in file order. /llm-fp itself is PR-scoped, but the follow-up command takes only the id. With about 100 findings per check the chance of at least one collision is about 7%, and about 50% at around 300; the log already holds 234 findings across six checks (WRITEUP section 3).

*Failure scenario:* cr-1a2b was marked /llm-fp on PR #40, and another PR later produced a different finding with the same id. `llm-gate eval add-from-fp cr-1a2b` builds the fp-regression case from the later PR's diff and title, forbidding a finding nobody marked.

*Suggested fix:* Accept --pr (or read the PR from the feedback record), and fail when the id matches findings on more than one PR.

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, info, trivial): case_from_false_positive scans every gate_run on the log for the id, across PRs, and keeps the last match in file order (evals.py:836-843). finding_id is check initials plus 4 hex digits of a hash of check, file and title words. The mechanism is real, but the report's 7%/50% figures are birthday bounds for any two findings colliding. For the one id being looked up, the chance that another finding shares it is about n/65536 per check, a fraction of a percent here. The same finding recurring on a later push maps to the same id legitimately. add-from-fp also tells the user to review the generated case, hence info.
- **maintainer** (CONFIRMED, low, trivial): case_from_false_positive scans every gate_run in the log for the 4-hex-digit id with no PR filter and keeps the last match. The birthday arithmetic in the report is right. The CLI and README tell the person to review the generated case (source names the PR), which limits the harm.
- **impact** (CONFIRMED, info, trivial): Finding ids are the check prefix plus 4 hex digits (16 bits), and case_from_false_positive scans every gate_run in the log regardless of PR and keeps the last match, while /llm-fp itself is PR-scoped. The report's ~7% is the birthday probability that some pair of ~100 findings collides; the chance that the specific id passed to add-from-fp collides is about n/65536 (~0.15%), and the command asks a person to review the generated case before committing it (WRITEUP shows that review catching a bad case). Real, very unlikely, caught by review: info; accepting --pr is trivial.

</details>

### F040

**gate_run records for checks that triage didn't need carry the configured blocking flag, not the effective one**

- **Status:** open
- **Severity:** info (reviewers: info) · **outcome:** confirmed · **fix cost:** trivial
- **Where:** `tools/llm-gate/src/llm_gate/cli.py:305` · **area:** llm-gate and review prompts
- **Reported by:** `api-23` (info, high confidence)

When a check isn't needed, `_at_risk` returns the unplanned check, so the record's `blocking` is the mode in checks.yaml. The security-review not_needed records on PRs #47 and #49 say `blocking: true` at risk low, while code-review's record at the same level, which did run, says `blocking: false` (it's advisory there). Today metrics and the attestation ignore `blocking` on not_needed records, but the field now means two different things.

*Failure scenario:* A later query for 'blocking checks that didn't review' (blocking true, verdict not pass) counts every low-risk security-review as a skipped blocking check.

*Suggested fix:* Record `blocking: false` for not_needed checks, or document that for those records blocking is the configured mode.

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, info, trivial): _at_risk returns the configured check when it isn't needed, so its gate_run carries the configured blocking flag. On audit-log, security-review's not_needed records on PRs 47 and 49 (risk low) say blocking: true, while the advisory checks' say false. No current consumer reads blocking on not_needed records.
- **maintainer** (CONFIRMED, info, trivial): _at_risk returns the configured check when it isn't needed, so the gate_run's blocking is the checks.yaml mode. The local audit log has security-review not_needed records at risk low with blocking true. The collector checks blocking only for needed checks, and metrics (blocking and verdict fail) and attestations (blocking and skipped_no_key/error) ignore not_needed records today, so it is a data-contract ambiguity only.
- **impact** (CONFIRMED, info, trivial): Confirmed on audit-log: PRs #47 and #49 have security-review not_needed records with blocking true at risk low, while code-review's record at the same level (run, advisory) has blocking false, because _at_risk returns the configured check when it isn't needed. No reader uses blocking on not_needed records today (the attestation's unreviewed list looks only at skipped_no_key and error). Info.

</details>

### F080

**Tool versions pinned inside run: steps and with: inputs aren't covered by Dependabot**

- **Status:** open
- **Severity:** info (reviewers: info) · **outcome:** confirmed · **fix cost:** medium
- **Where:** `.github/workflows/ci.yml:72` · **area:** workflows, release, deploy, scripts
- **Reported by:** `wr-21` (info, high confidence)

The actionlint, hadolint, kubeconform, kyverno-cli and ijhttp images (by digest), zizmor, yamllint and ruff (uvx versions), grype v0.120.1 (in both ci.yml and release.yml), syft v1.54.1, helm v4.2.2, kind v0.33.0 and the kubectl versions are all pinned, but only change by hand. Dependabot's github-actions ecosystem updates the action SHAs, not these. grype's database is fetched fresh, so detection doesn't age with the binary, but the other tools will drift silently.

*Failure scenario:* A security fix in kubeconform or kyverno-cli doesn't reach CI until someone notices.

*Suggested fix:* A regex-based updater (Renovate custom manager) or a scheduled check for these pins.

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, info, medium): Confirmed by reading: tools pinned in run: steps or with: inputs (grype-version v0.120.1, syft-version v1.54.1, helm v4.2.2, kind v0.33.0, the kubectl versions, the uvx versions, the ijhttp image by digest) are outside Dependabot's github-actions ecosystem, which updates uses: refs only. gates.md says they're bumped by hand together, but no ADR or PLAN-v2 decision accepts silent drift. Info.
- **maintainer** (CONFIRMED, info, medium): Accurate observation: tool and image versions pinned inside run: steps and with: inputs (actionlint, hadolint, kubeconform, kyverno-cli and ijhttp digests, the uvx versions, grype, syft, helm, kind, kubectl) aren't covered by any Dependabot ecosystem in dependabot.yml. docs/gates.md says these are bumped by hand ('bump them together'), so it's known, but drift isn't recorded as an accepted consequence. Info: no defect today.
- **impact** (CONFIRMED, info, small): True as stated: the actionlint, hadolint, kubeconform, kyverno-cli and ijhttp image digests, the uvx versions of zizmor, yamllint and ruff, and the grype, syft, helm, kind and kubectl versions live in run: strings and with: inputs, which Dependabot's github-actions ecosystem doesn't update. They are pinned (good) and drift silently (maintenance gap); grype's DB is fetched fresh, so detection doesn't age. Info.

</details>

### F110

**Friday-the-13th lists are compared ignoring order**

- **Status:** open
- **Severity:** info (reviewers: low) · **outcome:** confirmed · **fix cost:** trivial
- **Where:** `tests/CalendarGates.UnitTests/Friday13CalculatorTests.cs:17` · **area:** API, tests, docs
- **Reported by:** `tr-21` (low, high confidence)

TUnit's IsEquivalentTo ignores order by default (CollectionOrdering.Any, per the TUnit 1.75 XML docs). ListsFridaysThe13thInYear and Friday13Tests.DefaultsToTheCurrentYear both use it. Only the .http request for 2026 pins the order, and it runs against the container.

*Failure scenario:* InYear returns the dates in reverse or hash order. The unit and integration tests still pass.

*Suggested fix:* Use IsEquivalentTo(expected, CollectionOrdering.Matching), or compare the sequences in order.

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, info, trivial): TUnit 1.75's own docs (TUnit.Assertions.xml) say IsEquivalentTo compares collections 'regardless of order (default)', so ListsFridaysThe13thInYear and Friday13Tests.DefaultsToTheCurrentYear would pass a reversed list. But calendar.http's 'friday13?year: exact values' (line 84) compares the 2026 list in order with JSON.stringify. That request runs in the required http-tests gate (and in k8s-smoke and the release smoke), so the scenario's regression can't merge. A weak assertion in one layer, so info.
- **maintainer** (CONFIRMED, info, trivial): TUnit 1.75's IsEquivalentTo ignores order by default ('regardless of order (default)', CollectionOrdering.Any in its XML docs). Both Friday13CalculatorTests.ListsFridaysThe13thInYear and Friday13Tests.DefaultsToTheCurrentYear use it. The .http request for 2026 pins the order with JSON.stringify and runs in the required http-tests gate, so a reordering would still be caught there. Info.
- **impact** (CONFIRMED, info, trivial): A scratch TUnit 1.75 test confirmed IsEquivalentTo passes for the same dates in reverse order, so ListsFridaysThe13thInYear and Friday13Tests.DefaultsToTheCurrentYear don't pin order. The required http-tests check does: calendar.http's 2026 request compares JSON.stringify of the dates, and any order regression in InYear would affect every year, so it can't merge; only where it's caught differs.

</details>

### F112

**CurrentWeekUsesTodayInUtc can't tell UTC from local time**

- **Status:** open
- **Severity:** info (reviewers: low) · **outcome:** confirmed · **fix cost:** trivial
- **Where:** `tests/CalendarGates.IntegrationTests/WeekTests.cs:6` · **area:** API, tests, docs
- **Reported by:** `tr-23` (low, medium confidence)

FakeTimeProvider's local time zone defaults to UTC, and the fixed clock is at 10:00Z, far from midnight. A regression from GetUtcNow() to GetLocalNow() in EndpointHelpers.Today gives the same date, so the test checks the fake clock but not the UTC part its name claims.

*Failure scenario:* Today() is switched to time.GetLocalNow(). In production on a non-UTC host near midnight, the week is off by a day. The test passes.

*Suggested fix:* Set the clock to 2026-02-15T23:30Z (Sunday, ISO week 7) and Time.SetLocalTimeZone to a UTC+2 zone (Monday 01:30 locally), and expect week 7.

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, info, trivial): FakeTimeProvider's local time zone defaults to UTC: its assembly references TimeZoneInfo.Utc for _localTimeZone and never TimeZoneInfo.Local. The base clock is at 10:00Z. If EndpointHelpers.Today switched to GetLocalNow(), it would return the same date, and CurrentWeekUsesTodayInUtc would still pass: the test pins the injected clock, not the UTC part of its name. The production impact is small, because the chiseled image has no tzdata and its local zone is UTC anyway. The risk is `just run` on a non-UTC machine near midnight.
- **maintainer** (CONFIRMED, low, trivial): The fixed clock is 2026-02-12T10:00Z. Whatever the provider's local zone, GetUtcNow and GetLocalNow give the same date for every realistic zone at that hour, so the test can't catch a switch to local time, despite its name. It still catches the real-clock regression (DateTime.Now). Shipped images run in UTC (chiseled, no tzdata), so in practice this only matters on dev machines; low.
- **impact** (CONFIRMED, info, trivial): FakeTimeProvider's local zone defaults to UTC (checked in a scratch test) and the clock is 10:00Z, so a switch from GetUtcNow to GetLocalNow in EndpointHelpers.Today would pass CurrentWeekUsesTodayInUtc. The image is chiseled with no tzdata, so local time is UTC in the container and such a regression would change nothing in production; it would show only under `just run` on a non-UTC host near midnight, and the code-review prompt names 'today is the UTC date' as a convention. A misleading test name more than a gap that bites.

</details>

### F116

**The api-contract prompt defines the contract as the /api routes and OpenAPI, leaving out /health, which checks.yaml gives as a reason to review Program.cs**

- **Status:** open
- **Severity:** info (reviewers: info) · **outcome:** confirmed · **fix cost:** small
- **Where:** `.claude/commands/llm-api-contract.md:7` · **area:** API, tests, docs
- **Reported by:** `api-21` (info, medium confidence)

checks.yaml:20-21 adds Program.cs to api-contract's paths for 'the /api group, OpenAPI, /health'. /health is what the chart's readiness and liveness probes call (values.yaml probes.path), and scripts/wait-for-health.sh, http-tests, k8s-smoke, the release smoke and calendar.http ('health: 200 Healthy') depend on it. The prompt's contract paragraph names only the /api routes and the OpenAPI document, so a reviewer following it won't treat a change to the health route or its body as a contract change. The deterministic gates still catch a broken path, as a health-wait timeout.

*Failure scenario:* A PR maps the health checks to /healthz in Program.cs. api-contract runs, because Program.cs changed, but reports nothing. The breakage surfaces only as an http-tests or k8s-smoke timeout.

*Suggested fix:* Add `/health` to the contract paragraph of llm-api-contract.md: status 200, body 'Healthy', used by the probes and the smoke tests.

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, info, small): llm-api-contract.md:7-10 defines the contract as the /api routes, their JSON and status codes, and the OpenAPI document. checks.yaml:20-21 says api-contract watches Program.cs partly because of /health, which the chart's probes, scripts/wait-for-health.sh and calendar.http's first request depend on. Required deterministic gates still catch a /health change (http-tests waits on /health and asserts 'Healthy', and k8s-smoke has the probes), so the gap is only that an advisory check won't explain the break. A prompt edit goes through llm-eval, hence small.
- **maintainer** (CONFIRMED, info, trivial): checks.yaml:20-21 gives 'the /api group, OpenAPI, /health' as the reason Program.cs is in api-contract's paths. llm-api-contract.md defines the contract as the /api routes and the OpenAPI document only. The chart probes, wait-for-health.sh, http-tests, k8s-smoke and the release smoke all rely on /health and catch a broken path deterministically, so the gap only affects the advisory check. A prompt edit is a gate change; ac-001 is its only eval case.
- **impact** (CONFIRMED, info, small): checks.yaml:20-21 adds Program.cs to api-contract's paths for 'the /api group, OpenAPI, /health', but llm-api-contract.md's contract paragraph names only the /api routes and the OpenAPI document. api-contract is advisory, and a moved or broken /health fails http-tests (wait-for-health), the k8s-smoke probes and the release smoke deterministically, so the omission costs a comment, not a missed break; the prompt edit has to pass llm-eval.

</details>

### F128

**The docs-drift gate's own list of docs leaves out the tool READMEs and command files, where drift collects**

- **Status:** open
- **Severity:** info (reviewers: info) · **outcome:** confirmed · **fix cost:** small
- **Where:** `.claude/commands/llm-docs-drift.md:6` · **area:** API, tests, docs
- **Reported by:** `dd-34` (info, medium confidence)

The prompt defines the documentation as README.md, AGENTS.md, CLAUDE.md, docs/, justfile recipe comments and config-file headers. It leaves out tools/llm-gate/README.md, tools/llm-gate/evals/README.md and .claude/commands/*.md (gate-drill, new-endpoint) and .claude/agents/. Those are the files where this review found stale CLI usage (dd-15), stale drill routing (dd-12) and a missing scaffold step (dd-22). A prompt change is a gate change (llm-eval and the ADR 0004 rule apply).

*Failure scenario:* A PR adding an llm-gate subcommand is never flagged for the missing README entry.

*Suggested fix:* Add "tools/llm-gate/README.md and evals/README.md, .claude/commands/ and .claude/agents/" to the list.

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, info, small): llm-docs-drift.md:6-8 lists README.md, AGENTS.md, CLAUDE.md, docs/, justfile comments and config headers, but not tools/llm-gate/README.md, evals/README.md, .claude/commands/ or .claude/agents/. This review found drift in exactly those places (F090, F103, F108, F127). The effect is limited: docs-drift runs on the api engine with only the diff, so the list mainly tells it which docs to suggest. A prompt change goes through llm-eval, hence small.
- **maintainer** (CONFIRMED, info, trivial): llm-docs-drift.md:6-8 defines the documentation as README.md, AGENTS.md, CLAUDE.md, docs/, the justfile comments and config-file headers. tools/llm-gate/README.md, evals/README.md, .claude/commands and .claude/agents aren't named, and this review found drift in exactly those files (F090, F103, F108, F127). Editing the prompt is a gate change, but docs-drift has no eval cases, so llm-eval costs nothing for it.
- **impact** (CONFIRMED, info, small): llm-docs-drift.md:6-8 defines the documentation as README.md, AGENTS.md, CLAUDE.md, docs/, justfile recipe comments and config-file headers, leaving out tools/llm-gate/README.md, evals/README.md, .claude/commands/ and .claude/agents/, where several drift items in this batch sit (F090, F103, F108, F127). A suggestion for an advisory check; the prompt change has to pass llm-eval.

</details>

### F061

**audit-pull, and with it metrics, fails when the audit-log branch has no events/ directory**

- **Status:** ✅ fixed — #63: `audit-pull` tolerates a branch with no `events/`
- **Severity:** info (reviewers: low) · **outcome:** confirmed · **fix cost:** trivial
- **Where:** `justfile:94` · **area:** workflows, release, deploy, scripts
- **Reported by:** `cr-ops-13` (low, high confidence)

`find .audit-log/events ... 2> /dev/null | wc -l | xargs printf` runs under set -euo pipefail. find exits 1 when its start directory is missing (checked), so the pipeline fails after printing '0 record file(s)'. The 2> /dev/null shows the case was meant to be tolerated. metrics depends on audit-pull, so a fresh or empty log (a new setup, or a fork) breaks just metrics too.

*Failure scenario:* audit-log holds only README.md -> just metrics -> audit-pull exits 1 -> no report.

*Suggested fix:* Use `find .audit-log -path '*/events/*' -name '*.jsonl'`, or guard with `[ -d .audit-log/events ]`.

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, info, trivial): Reproduced: under set -euo pipefail, `find <missing dir> -name '*.jsonl' 2> /dev/null | wc -l | xargs printf ...` prints '0 record file(s)' and then exits 1, so audit-pull, and metrics which depends on it, fail when the audit-log branch has no events/ directory. Only a fresh or empty log (a new setup or a fork) hits it, and the failure is loud, so info.
- **maintainer** (CONFIRMED, low, trivial): Reproduced the pipeline: under set -euo pipefail, find on a missing directory exits 1, so audit-pull prints '0 record file(s)' and then fails (exit 1), and metrics, which depends on it, fails too. The 2> /dev/null shows the empty case was meant to be tolerated. It only bites on a fresh or empty audit-log (a new setup or fork); this repository's log has events.
- **impact** (CONFIRMED, info, trivial): Reproduced: with .audit-log present but no events/, the find | wc | xargs printf pipeline prints '0 record file(s)' and exits 1 under set -euo pipefail, so audit-pull (and metrics) fail. Unreachable in this repository: audit-log already holds hundreds of event files and its ruleset forbids rewriting it; a default fork copies only main, so `git fetch origin audit-log` fails first. Only a brand-new setup before its first collected run would hit it: info.

</details>

### F063

**just lint hands the user's full-scope gh OAuth token to a PyPI-fetched zizmor on every run**

- **Status:** ✅ fixed — #63: `just lint` runs zizmor `--offline`, with no `gh` token
- **Severity:** info (reviewers: low) · **outcome:** confirmed · **fix cost:** trivial
- **Where:** `justfile:73` · **area:** workflows, release, deploy, scripts
- **Reported by:** `cr-ops-15` (low, high confidence)
- **Reports the council found wrong:** `cr-ops-15`

`GH_TOKEN="$(gh auth token)"` gives zizmor the user's gh token with all its scopes (repo, workflow, ...). uvx installs zizmor from PyPI; the version is pinned, but the files aren't hash-pinned. This happens on every just lint and just ci, including the agent runs AGENTS.md asks for. In CI the same tool gets a read-only workflow token, and its online audits only need read access.

*Failure scenario:* A tampered zizmor 1.30.1 distribution (PyPI lets maintainers add files to an existing release) runs on the next just ci and receives a token that can push and edit workflows in every repository the user can access.

*Suggested fix:* Run `zizmor --offline` locally and leave the online audits to CI, or pass a fine-grained read-only token from pass.

<details><summary>Council</summary>

- **skeptic** (REJECTED, info, trivial): The token `gh auth token` prints is the one gh stores for the user (per the machine docs in ~/.config/gh/hosts.yml), which any process the user runs, a tampered uvx-installed zizmor included, can read directly; handing it over as GH_TOKEN gives such a process nothing it couldn't already take. Inside the agent sandbox ~/.config/gh is unreadable, so `gh auth token` yields nothing there. The real exposure is running non-hash-pinned PyPI tools as the user, which applies equally to the yamllint and ruff uvx calls in the same recipe; passing the token adds no capability.
- **maintainer** (CONFIRMED, low, trivial): justfile:73 runs 'GH_TOKEN="$(gh auth token)" uvx zizmor@1.30.1', handing the user's full-scope gh OAuth token to a PyPI tool pinned by version but not by hash; CI gives the same tool a read-only workflow token. PyPI files can't be replaced, but new files can be added to an existing release, so a compromised maintainer account could reach the token. Low-probability supply-chain exposure, not a gate defect; --offline locally (online audits stay in CI) is trivial.
- **impact** (CONFIRMED, info, trivial): justfile:73 does pass `gh auth token` (the full-scope OAuth token) to uvx zizmor@1.30.1, version- but not hash-pinned. Calibrated to info: a tampered zizmor runs as the user and can already read the same credential (gh's hosts.yml or the unlocked keyring) without the env var, and inside the Claude sandbox `gh auth token` can't read hosts.yml at all, so the env var adds almost no exposure. Worth `--offline` or no token for hygiene, not a real hole.

</details>

### F077

**The pre-commit ruff job skips scripts/*.py, which the lint gate checks**

- **Status:** ✅ fixed — #63: a `ruff-scripts` pre-commit job covers `scripts/*.py`
- **Severity:** info (reviewers: info) · **outcome:** confirmed · **fix cost:** trivial
- **Where:** `lefthook.yml:11` · **area:** workflows, release, deploy, scripts
- **Reported by:** `cr-ops-22` (info, high confidence)

The job is rooted at tools/llm-gate/, so edits to scripts/check-ruleset-consistency.py, commit-via-api.py and coverage-summary.py get no local format or fix. Meanwhile ci.yml's lint job and just lint run ruff 0.16.10 check and format --check on scripts/. Hooks are a convenience (docs/gates.md), so this only costs a CI round trip.

*Failure scenario:* A badly formatted edit to scripts/coverage-summary.py commits cleanly, then fails the lint gate.

*Suggested fix:* Add a second job for scripts/*.py that runs `uvx ruff@0.16.10 format` and `check --fix`, with stage_fixed.

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, info, trivial): lefthook.yml's ruff job has root: tools/llm-gate/ and glob *.py, so staged scripts/*.py files (check-ruleset-consistency.py, commit-via-api.py, coverage-summary.py) get no local format or fix, while ci.yml's lint and just lint run ruff 0.16.10 check and format --check on scripts/. Hooks are a convenience (gates.md: 'Hooks are not gates'), so this only costs a CI round trip.
- **maintainer** (CONFIRMED, info, trivial): lefthook.yml's ruff job has root: tools/llm-gate/, so staged scripts/*.py are filtered out, while ci.yml:87-90 and just lint check scripts/ with ruff 0.16.10. Hooks are a convenience (docs/gates.md), so it only costs a CI round trip.
- **impact** (CONFIRMED, info, trivial): lefthook's ruff job has root tools/llm-gate/, so scripts/*.py get no pre-commit format or fix, while ci.yml's lint job and just lint run ruff check and format --check on scripts/. Hooks are a convenience by design (docs/gates.md); the cost is one CI round trip: info.

</details>

### F078

**llm and llm-list run uv without --locked, unlike every other recipe and CI**

- **Status:** ✅ fixed — #63: `just llm` runs `uv run --locked`
- **Severity:** info (reviewers: info) · **outcome:** confirmed · **fix cost:** trivial
- **Where:** `justfile:135` · **area:** workflows, release, deploy, scripts
- **Reported by:** `cr-ops-23` (info, high confidence)

`uv run --project tools/llm-gate` without --locked re-locks when pyproject.toml and uv.lock disagree. That rewrites a tracked file, and the review then runs with dependencies that CI's --locked runs would refuse. The eval, metrics and lint recipes all pass --locked.

*Failure scenario:* pyproject.toml gains a dependency without a re-lock -> just llm code-review silently updates uv.lock and reviews with it, while CI fails on the stale lock.

*Suggested fix:* Add --locked, as in eval, metrics and lint.

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, info, trivial): justfile:125 and :135 run `uv run --project tools/llm-gate` without --locked, while eval, eval-baseline, metrics and lint all pass --locked; plain uv run re-locks and syncs when pyproject.toml and uv.lock disagree, rewriting a tracked file and reviewing with dependencies CI would refuse. Info.
- **maintainer** (CONFIRMED, info, trivial): justfile:125 and 135 run 'uv run --project tools/llm-gate' without --locked, unlike eval, metrics, lint and CI, so a stale lock is silently rewritten there instead of failing. Local-only inconsistency; adding --locked is trivial.
- **impact** (CONFIRMED, info, trivial): llm-list and llm run `uv run --project tools/llm-gate` without --locked (justfile:125, 135), so a stale lock is silently rewritten locally where CI's --locked would fail. Local-only, visible in git status, no gate effect: info.

</details>

### F106

**ADR 0005 says the untrusted llm job uploads with a read-only token; it holds pull-requests: write**

- **Status:** ✅ fixed — #63: ADR 0005 says the job holds `pull-requests: write`
- **Severity:** info (reviewers: low) · **outcome:** confirmed · **fix cost:** trivial
- **Where:** `docs/adr/0005-audit-trail.md:30` · **area:** API, tests, docs
- **Reported by:** `dd-17` (low, high confidence)

"the `llm` job uploads it as `audit-<run_id>-<attempt>-<check>` with its read-only token". llm-review.yml:177-180 grants the llm job `contents: read`, `pull-requests: write` (sticky comment) and `issues: read`. The triage job (lines 38-40) has `pull-requests: write` for labels. Only llm-eval's eval job is truly read-only (ADR 0006, correctly described). The trust argument (the untrusted side "only produces artifacts") deserves an accurate statement of what that side can write, especially since the workflow file comes from the PR.

*Failure scenario:* A security reviewer reasoning from the ADR assumes a PR-modified llm-review run can write nothing but artifacts. It can post and edit PR comments and labels, including forging another check's sticky comment marker.

*Suggested fix:* "... with a token that can't write the repository (contents: read; pull-requests: write only for its sticky comment and triage's labels)".

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, info, trivial): ADR 0005:29-30 says the llm job uploads its record 'with its read-only token'. llm-review.yml grants the llm job contents: read, pull-requests: write and issues: read, and grants triage pull-requests: write. The trust argument still holds. GITHUB_TOKEN comments start no workflows, llm-feedback hears only collaborators, and find_override accepts a bot-added label only with a writer's /llm-override reason, so nothing the untrusted side can write (comments, labels) feeds a trusted decision. A wording inaccuracy in a security ADR, so info.
- **maintainer** (CONFIRMED, low, trivial): ADR 0005:29-30 says the llm job uploads the artifact 'with its read-only token'. llm-review.yml gives that job pull-requests: write (sticky comment) and issues: read, and the triage job pull-requests: write (labels); only llm-eval's eval job is read-only. The trust argument should say the token can't write the repository (contents: read). This is a wording fix, not a new hole: a PR that edits llm-review.yml can grant itself more permissions anyway (the workflow-file hole ADR 0004 accepts).
- **impact** (CONFIRMED, info, trivial): ADR 0005:186-187 says the llm job uploads 'with its read-only token'; llm-review.yml:177-180 grants it contents: read, pull-requests: write and issues: read (triage also holds pull-requests: write). The trust argument doesn't rest on that token: the collector validates every artifact independently, the unmodified job runs only base-branch code with a read-only-tools agent, and a PR that edits the workflow can grant itself any permission anyway (ADR 0004's remaining hole). Inaccurate wording that changes no conclusion.

</details>

### F115

**Header comments in checks.yaml and the workflows still describe the override label alone, a per-level model and a not-yet-required llm-eval**

- **Status:** ✅ fixed — #63: the stale header comments in checks.yaml and llm-eval.yml
- **Severity:** info (reviewers: info) · **outcome:** confirmed · **fix cost:** trivial
- **Where:** `tools/llm-gate/checks.yaml:3` · **area:** API, tests, docs
- **Reported by:** `dd-30` (info, high confidence), `dd-38` (info, high confidence)

**`dd-30`: Header comments in checks.yaml and the workflows still describe the override label alone, a per-level model and a not-yet-required llm-eval**

checks.yaml:3 says "(override: PR label `llm-override`)". Since ADR 0005 the label alone isn't honoured without `/llm-override <reason>`. checks.yaml:38-39 says the level decides "the engine and model of the blocking ones", and llm-review.yml:32 and :191-192 say the same. Since #58 the level sets only the engine (the code still supports a per-level `model`). llm-eval.yml:8 says it runs on every PR "so it can become a required check", but it has been required since #40.

*Failure scenario:* Minor misdirection for whoever edits the gate config.

*Suggested fix:* "override: `/llm-override <reason>` (adds the label)"; "the engine of the blocking ones (a level may also set a model; none does)"; "so it can be a required check (it is)".

**`dd-38`: ADR 0002 still describes overrides as the label alone, with no pointer to ADR 0005's reason requirement**

"A human can override blocking findings with the `llm-override` PR label (write access needed)." Since ADR 0005, the label counts only with an unedited `/llm-override <reason>` from whoever added it (or from a writer when the bot added it, ADR 0007). ADR 0002 already carries an inline pointer for the part ADR 0004 superseded, but not for this one.

*Failure scenario:* A reader who stops at ADR 0002 overrides with the label only and gets "override not honoured".

*Suggested fix:* Append "(a reason is required since ADR 0005)".

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, info, trivial): checks.yaml:3 still says '(override: PR label llm-override)', but since ADR 0005 the label counts only with an unedited /llm-override reason. ADR 0002:22 says the same with no pointer to ADR 0005, although it has one for ADR 0004. checks.yaml:38-39 and llm-review.yml:32 and 191-192 say the level decides the 'engine and model', but since #58 the high level sets only engine: agent; the code still supports a per-level model, so this one is half-true. llm-eval.yml:8's 'so it can become a required check' predates #40, though the reason for having no paths filter still holds. gates.md and ADR 0005 state the current rules, and the job annotates 'override not honoured', so info.
- **maintainer** (CONFIRMED, info, trivial): checks.yaml:3 still describes the override as the label alone. llm-eval.yml:8 says it runs on every PR 'so it can become a required check'; it has been required since #40. ADR 0002:22 has no pointer to ADR 0005's reason rule, though it has one for ADR 0004. The 'engine and model' wording (checks.yaml:38-39, llm-review.yml:32 and 191-192) is only half stale: triage.plan_for still applies a level's model, and the high level just no longer sets one.
- **impact** (CONFIRMED, info, trivial): checks.yaml:3 still says 'override: PR label `llm-override`'; checks.yaml:38-39 and llm-review.yml:31-32 and 191-192 say the level decides the engine and model of the blocking checks, though levels.high now sets only `engine: agent`; llm-eval.yml:8 says it runs on every PR 'so it can become a required check' although it is required since #40; and ADR 0002:55 describes the label alone with no pointer to ADR 0005's reason requirement. Header comments only: the code and the docs behind them are right.

</details>

### F119

**ADR 0004's amendment names a job, `llm-plan`, that no longer exists**

- **Status:** ✅ fixed — #63: ADR 0004 names the `triage` job, not `llm-plan`
- **Severity:** info (reviewers: info) · **outcome:** confirmed · **fix cost:** trivial
- **Where:** `docs/adr/0004-gate-tooling-from-base-branch.md:40` · **area:** API, tests, docs
- **Reported by:** `dd-24` (info, high confidence)

"the base branch's head when the run starts (pinned once by `llm-plan` and passed to every check)". Since Phase 17, the `triage` job pins it (llm-review.yml:56-58, output gate_sha) and replaces llm-plan (PLAN-v2 Status line 28). The only other mentions of llm-plan are in PLAN.md (v1 plan) and an eval fixture.

*Failure scenario:* A reader looking for the job that pins gate_sha finds no `llm-plan` in llm-review.yml.

*Suggested fix:* "pinned once by the first job (`llm-plan`, now `triage`) and passed to every check".

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, info, trivial): ADR 0004:39-40's amendment says the gate commit is 'pinned once by llm-plan', but llm-review.yml has no llm-plan job. The triage job pins it and exports gate_sha (llm-review.yml:41-44), as PLAN-v2:28 records ('the triage job, which replaces llm-plan'). The rest of the amendment is accurate.
- **maintainer** (CONFIRMED, info, trivial): ADR 0004's amendment (lines 39-40, 2026-10-16) says gate_sha is 'pinned once by `llm-plan`'. llm-review.yml's triage job now outputs gate_sha and has replaced llm-plan (PLAN-v2 Status row 17). The amendment was right when written; a short 'now `triage`' note fixes it.
- **impact** (CONFIRMED, info, trivial): ADR 0004:40's amendment says the base head is 'pinned once by `llm-plan`'; no workflow has that job any more (llm-review.yml's triage job outputs gate_sha), as PLAN-v2's Status table records. The amendment was accurate when written; it lacks a pointer to triage.

</details>

### F120

**ADR 0009's job order and release.yml's header comment leave out admission-smoke**

- **Status:** ✅ fixed — #63: ADR 0009 and release.yml's header include `admission-smoke`
- **Severity:** info (reviewers: info) · **outcome:** confirmed · **fix cost:** trivial
- **Where:** `docs/adr/0009-build-once-attest-promote.md:18` · **area:** API, tests, docs
- **Reported by:** `dd-25` (info, high confidence)

ADR 0009:18-26 says "release.yml runs these jobs in order" (verify ... publish, smoke), with smoke publishing the release. Since #53, admission-smoke runs between publish and smoke, and smoke needs it (release.yml:378-380, 488). release.yml:1-7 says the Release "goes public after the contract tests passed", without admission-smoke. ADR 0010, gates.md and README describe it correctly.

*Failure scenario:* A reader of ADR 0009 or the workflow header thinks publication depends only on smoke.

*Suggested fix:* Add "7. admission-smoke (ADR 0010)" to ADR 0009's list as an amendment, and mention it in the release.yml header.

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, info, trivial): ADR 0009:18-26 says release.yml runs verify through publish and then smoke 'in order', with smoke publishing the release. Since #53, admission-smoke (release.yml:378-380, which needs publish) runs between them, and smoke needs it (line 488). release.yml's header (lines 1-7) likewise says the release goes public after the contract tests, without mentioning admission-smoke. ADR 0010 and gates.md:137-144 describe it correctly, so what's missing is an amendment.
- **maintainer** (CONFIRMED, info, trivial): ADR 0009:18-26 lists seven jobs, ending with smoke publishing the release, and release.yml:1-7 says the release goes public after the contract tests. Since #53, admission-smoke runs between publish and smoke, and smoke needs it (release.yml:380 and 488). ADR 0010, gates.md and the README describe this correctly, so info.
- **impact** (CONFIRMED, info, trivial): ADR 0009's job list (lines 464-472) ends with smoke, and release.yml's header says the Release goes public after the contract tests; since #53 admission-smoke runs between publish and smoke and smoke needs it (release.yml:378-380, 488). ADR 0010, gates.md and the README describe it correctly.

</details>

### F121

**WRITEUP's cr-def4 doesn't match the finding the audit log records under that id**

- **Status:** ✅ fixed — #63: WRITEUP explains what `cr-def4` records
- **Severity:** info (reviewers: info) · **outcome:** confirmed · **fix cost:** trivial
- **Where:** `docs/WRITEUP.md:147` · **area:** API, tests, docs
- **Reported by:** `dd-26` (info, medium confidence)
- **Reports the council found wrong:** `dd-26`

WRITEUP: "a re-run could move the X.Y.Z tag to new bytes (cr-def4)". The audit log's cr-def4 (PR #52, code-review, severity low, .github/workflows/release.yml:338) is titled "A re-run with an existing draft keeps the old notes, image digest and LLM-review section". It's related, since it led to the never-move-X.Y.Z check, but it's a different defect, rated low. No #52 finding with that id or title talks about moving the version tag. tr-3423 ("The publish job's refusal to move an existing X.Y.Z is untested") is about the fix.

*Failure scenario:* A reader who looks up cr-def4 in the log (as the write-up invites) finds a different claim.

*Suggested fix:* Describe cr-def4 as recorded ("a re-run kept the old draft notes and digest, which exposed that a re-run could re-tag new bytes"), or cite the finding that matches.

<details><summary>Council</summary>

- **skeptic** (REJECTED, info, trivial): The audit log does title cr-def4 'A re-run with an existing draft keeps the old notes, image digest and LLM-review section' (low, release.yml:338 at #52's head 36e6c08). At that head, publish re-tagged X.Y.Z with whatever digest the run had built (`imagetools create -t $IMAGE:$VERSION`, with no check for an existing tag) and only re-uploaded assets to an existing draft. The 'old image digest' in the notes is therefore exactly the symptom of a re-run moving X.Y.Z to new bytes. The next push (4f334c0) answered cr-def4 with both the never-move check and the notes refresh, and added ADR 0009's never-move sentence. WRITEUP's summary describes that finding's scenario, so 'a different defect' is a misreading.
- **maintainer** (CONFIRMED, info, trivial): The audit log records cr-def4 (PR #52, code-review, low, release.yml:338) as 'A re-run with an existing draft keeps the old notes, image digest and LLM-review section'. WRITEUP:147 cites it as 'a re-run could move the X.Y.Z tag to new bytes'. It's the same re-run path and maybe the same analysis (the log keeps titles only), but a reader who looks the id up finds a different, low-severity claim.
- **impact** (CONFIRMED, info, trivial): On origin/audit-log, PR #52's cr-def4 is 'A re-run with an existing draft keeps the old notes, image digest and LLM-review section' (low, release.yml:338), not 'a re-run could move the X.Y.Z tag to new bytes' as WRITEUP §5:147 says; the only #52 finding about the tag refusal is tr-3423, about it being untested. The two are related (the re-run discussion led to the never-move guard), so it's a loose paraphrase, but the id invites a lookup that finds a different claim.

</details>

### F122

**The turnaround row's unlabelled "1.0 / 2.3 min" is code-review's figure, not the overall one**

- **Status:** ✅ fixed — #63: the turnaround row is labelled per check
- **Severity:** info (reviewers: info) · **outcome:** confirmed · **fix cost:** trivial
- **Where:** `docs/WRITEUP.md:67` · **area:** API, tests, docs
- **Reported by:** `dd-27` (info, medium confidence)

I recomputed `llm-gate metrics` offline from origin/audit-log as of 2026-10-17T17:40Z. That reproduces §3's 16 merged PRs, 24 reviewed PRs, 224 runs, $7.36, p50 $0.06 and p90 $1.28, 2/6 overrides, 62/25/12% risk mix, 75% AI-assisted, 4 tamper events, 56 unverified reviews and 1 rejected command. The report gives turnaround per check only: code-review 59 s / 2.3 min, security-review 71 s / 2.2 min. Over all reviews it is 60 s / 2.2 min. The row's "Review turnaround, p50 / p90 | 1.0 / 2.3 min" reads as overall.

*Failure scenario:* A small misattribution in an otherwise reproducible table.

*Suggested fix:* "code-review 1.0 / 2.3 min, security-review 71 s / 2.2 min".

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, info, trivial): I recomputed from origin/audit-log up to 2026-10-17T17:40Z, which reproduces §3's 224 check runs. code-review has p50 59 s and p90 2.3 min, security-review 71 s and 2.2 min, and all checks together 60 s and 2.2 min. So the unlabelled '1.0 / 2.3 min' is code-review's figure, and the overall p90 is 2.2 min: a 0.1-minute mislabel.
- **maintainer** (CONFIRMED, info, trivial): I recomputed from origin/audit-log up to 2026-10-17T17:40Z, which gives section 3's 224 runs and 24 reviewed PRs. Code-review is p50 59 s / p90 140 s (1.0 / 2.3 min), security-review 71 s / 133 s, and all reviews together 60 s / 134 s (1.0 / 2.2 min). So the unlabelled '1.0 / 2.3 min' is code-review's figure, not the overall one; the report itself has no overall figure.
- **impact** (CONFIRMED, info, trivial): Recomputing turnaround with the real metrics module over origin/audit-log up to 2026-10-17T17:40Z gives code-review 59 s / 2.3 min, security-review 71 s / 2.2 min and all checks together 60 s / 2.2 min, so WRITEUP:67's unlabelled '1.0 / 2.3 min' is code-review's. The overall p90 differs by 0.1 min: cosmetic.

</details>

### F123

**WRITEUP §5 says high-risk PRs "get Opus", in the present tense, though #58 switched them back to Sonnet**

- **Status:** ✅ fixed — #63: past tense, with #58 named
- **Severity:** info (reviewers: info) · **outcome:** confirmed · **fix cost:** trivial
- **Where:** `docs/WRITEUP.md:160` · **area:** API, tests, docs
- **Reported by:** `dd-28` (info, high confidence)

"Since Phase 17, high-risk PRs, about 60% of those triaged here, get Opus on the agent engine." The bullet's later sentence and checks.yaml (triage.levels.high has only `engine: agent`) say high risk now keeps each check's own model (Sonnet).

*Failure scenario:* A skimming reader takes away the wrong model for high-risk reviews.

*Suggested fix:* "From Phase 17 until 2026-10-17, high-risk PRs ... got Opus".

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, info, trivial): WRITEUP:160-161 (written in #55) says high-risk PRs 'get Opus on the agent engine', in the present tense. #58 appended the reversal two sentences later (lines 163-164), and checks.yaml's high level now sets only engine: agent. A reader of the whole bullet gets it right; the opening sentence is stale on its own.
- **maintainer** (CONFIRMED, info, trivial): WRITEUP:160-161 says high-risk PRs 'get Opus', in the present tense, under the heading 'doesn't hold up yet'. The same bullet, ADR 0008's amendment and checks.yaml (the high level sets only engine: agent) say high risk went back to Sonnet on 2026-10-17 (#58).
- **impact** (CONFIRMED, info, trivial): WRITEUP:160-161 says high-risk PRs 'get Opus on the agent engine' in the present tense; the same bullet's last sentence, checks.yaml (levels.high sets only the engine) and ADR 0008's amendment say high risk went back to Sonnet on 2026-10-17. Self-correcting within the bullet.

</details>

### F124

**"To regenerate (costs API credits)" includes `just metrics`, which spends nothing**

- **Status:** ✅ fixed — #63: `just metrics` is marked as costing nothing
- **Severity:** info (reviewers: info) · **outcome:** confirmed · **fix cost:** trivial
- **Where:** `docs/WRITEUP.md:107` · **area:** API, tests, docs
- **Reported by:** `dd-29` (info, high confidence)

`just metrics` runs audit-pull, `gh api` and plain-Python metrics, with no model call. Only `just eval` and the model rows cost credits.

*Failure scenario:* A reader avoids regenerating the free production numbers.

*Suggested fix:* Mark only the eval bullets as costing credits.

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, info, trivial): WRITEUP:107-108 puts `just metrics` under 'To regenerate (costs API credits)'. The recipe (justfile:112-120) runs audit-pull, a gh api call and llm-gate metrics, and none of them calls a model. Only the eval bullets cost credits.
- **maintainer** (CONFIRMED, info, trivial): WRITEUP:107-108 lists `just metrics` under 'To regenerate (costs API credits)'. The recipe runs audit-pull, `gh api` and the plain-Python metrics, with no model call; only the eval bullets cost credits.
- **impact** (CONFIRMED, info, trivial): WRITEUP:107 puts 'Production numbers: `just metrics`' under 'To regenerate (costs API credits)'; the metrics recipe runs audit-pull, `gh api` and plain Python with no model call.

</details>

### F125

**values-kind.yaml calls itself kind-local's, but `just k8s-load`/`k8s-deploy` now target the project cluster**

- **Status:** ✅ fixed — #63: `values-kind.yaml` says it serves either cluster
- **Severity:** info (reviewers: info) · **outcome:** confirmed · **fix cost:** trivial
- **Where:** `deploy/helm/calendar-gates/values-kind.yaml:1` · **area:** API, tests, docs
- **Reported by:** `dd-31` (info, high confidence)

"# kind-local: the image built by `just image`, loaded with `just k8s-load` (never pulled)." Since ADR 0010, `cluster := "calendar-gates"` is the default, and these values serve both clusters. The NOTES.txt hint "(or run `just k8s-http`)" also omits the namespace that's needed for the dev deploy in calendar-gates-dev.

*Failure scenario:* A reader thinks the file applies to kind-local only.

*Suggested fix:* "# Any local kind cluster (the project's by default, kind-local with cluster=local): ...".

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, info, trivial): values-kind.yaml:1 calls itself kind-local's, but the justfile's default cluster is calendar-gates (justfile:11), and k8s-deploy applies values-kind.yaml to whichever cluster it targets (justfile:202), so the file serves both. The NOTES.txt hint '(or run `just k8s-http`)' relies on k8s-http's default namespace, calendar-gates (k8s_ns, justfile:6), so after `just k8s-deploy calendar-gates-dev` the bare hint targets the wrong namespace. The kubectl line above it does use .Release.Namespace. Both mislead without breaking anything.
- **maintainer** (CONFIRMED, info, trivial): values-kind.yaml:1 calls itself kind-local's, but since ADR 0010 `just k8s-load`/`k8s-deploy` target the project cluster by default and the file serves both clusters. NOTES.txt's '(or run `just k8s-http`)' also leaves out the namespace argument that the documented calendar-gates-dev deploy needs.
- **impact** (CONFIRMED, info, trivial): values-kind.yaml:1 says 'kind-local', but the justfile's default cluster is now calendar-gates (ADR 0010) and the values serve both clusters; NOTES.txt's '(or run `just k8s-http`)' targets the default namespace calendar-gates, where the dev image is denied, so after a calendar-gates-dev deploy it needs the namespace argument.

</details>

### F126

**PLAN-v2's Status table says ADR 0008 records the rename rule; ADR 0008 never mentions renames**

- **Status:** ✅ fixed — #63: PLAN-v2 points at where the rename rule really lives
- **Severity:** info (reviewers: info) · **outcome:** confirmed · **fix cost:** trivial
- **Where:** `docs/PLAN-v2.md:28` · **area:** API, tests, docs
- **Reported by:** `dd-32` (info, high confidence)

Row 17 says "renames rated by both paths" is recorded in ADR 0008. ADR 0008 (rules, size, AI raise, model, people, levels, collector) says nothing about renames. The rule lives in triage.py:57,147-150 ("a move out of a riskier place keeps that risk") and eval case tr-010. Also missing from the table: Phase 19.1's `just k8s-cluster-up` was built as `just k8s-up`, which also starts kind-local with cluster=local (ADR 0010 names the real recipe).

*Failure scenario:* A reader following the table to ADR 0008 can't find the rename rule.

*Suggested fix:* Add one line to ADR 0008 point 1 ("a rename is rated by the riskier of its old and new path"), and add the k8s-up row to the table.

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, info, trivial): PLAN-v2:28 says that 'renames rated by both paths' is recorded in ADR 0008, but ADR 0008 never mentions renames. The rule lives in triage.py (old_path at line 57, the 'renamed away' key at line 150) and in eval case tr-010. The Status table also omits that Phase 19.1's k8s-cluster-up (PLAN-v2:537) was built as k8s-up, though ADR 0010:28 names the real recipe.
- **maintainer** (CONFIRMED, info, trivial): PLAN-v2:28 says ADR 0008 records 'renames rated by both paths', but ADR 0008 never mentions renames. The rule lives in triage.py (old_path, 'renamed away') and in eval case tr-010. The renamed recipe (k8s-cluster-up became k8s-up) is recorded in ADR 0010, just not in the table.
- **impact** (CONFIRMED, info, trivial): PLAN-v2:28 says 'renames rated by both paths' is recorded in ADR 0008, which never mentions renames; the rule lives in triage.py (old_path, 'renamed away') and eval case tr-010. The Status table also doesn't note that 19.1's `just k8s-cluster-up` (PLAN-v2:537) was built as `just k8s-up`, though ADR 0010 uses the real name.

</details>

### F127

**gate-debugger still says docs/gates.md has details "when it exists"**

- **Status:** ✅ fixed — #63: gate-debugger no longer says "when it exists"
- **Severity:** info (reviewers: info) · **outcome:** confirmed · **fix cost:** trivial
- **Where:** `.claude/agents/gate-debugger.md:13` · **area:** API, tests, docs
- **Reported by:** `dd-33` (info, high confidence)

docs/gates.md exists and is the reference for every gate's failure, fix and override. The subagent should read it, not treat it as optional.

*Failure scenario:* Negligible: the subagent may skip the gate reference.

*Suggested fix:* "(AGENTS.md lists them; docs/gates.md has the failure modes, fixes and overrides)".

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, info, trivial): gate-debugger.md:13 says docs/gates.md has details 'when it exists'. It exists, and it is the reference for each gate's failures, fixes and overrides. A stale qualifier with negligible effect.
- **maintainer** (CONFIRMED, info, trivial): gate-debugger.md:13 still says docs/gates.md has details 'when it exists'. The file exists and is the reference for failures, fixes and overrides. Negligible.
- **impact** (CONFIRMED, info, trivial): gate-debugger.md step 2 says docs/gates.md 'has details when it exists'; it exists and holds each gate's failure modes, fixes and overrides. The subagent might treat it as optional; negligible.

</details>

### F129

**"Lint tool versions are pinned in both ci.yml and the lint recipe" holds for only some of the tools**

- **Status:** ✅ fixed — #63: gates.md separates the pinned tools from the system ones
- **Severity:** info (reviewers: info) · **outcome:** confirmed · **fix cost:** trivial
- **Where:** `docs/gates.md:34` · **area:** API, tests, docs
- **Reported by:** `dd-35` (info, high confidence)

The justfile pins zizmor 1.30.1, yamllint 1.38.0, ruff 0.16.10 and kyverno 1.19.1. actionlint, hadolint and shellcheck in `lint`, and helm and kubeconform in `lint-chart`, are whatever is installed. ci.yml pins actionlint 1.7.12, hadolint v2.14.0, helm v4.2.2 and kubeconform v0.8.0. CI's shellcheck is the runner's, unpinned. The justfile's own lint comment says "(CI pins the same tools)".

*Failure scenario:* A newer local actionlint or hadolint passes or fails differently from CI, and the docs promise parity.

*Suggested fix:* "zizmor, yamllint, ruff and the kyverno CLI are pinned in both; actionlint, hadolint, helm and kubeconform only in ci.yml".

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, info, trivial): gates.md:34 says the lint tool versions are pinned in both ci.yml and the lint recipe, and the recipe's comment says 'CI pins the same tools'. But the justfile pins only zizmor 1.30.1, yamllint 1.38.0 and ruff 0.16.10 (plus the kyverno version check). actionlint, hadolint and shellcheck in lint, and helm and kubeconform in lint-chart, are whatever happens to be installed. ci.yml pins actionlint 1.7.12, hadolint v2.14.0, helm v4.2.2 and kubeconform v0.8.0, and uses the runner's shellcheck.
- **maintainer** (CONFIRMED, info, trivial): gates.md:34 and justfile:68 ('CI pins the same tools') claim CI and local runs use the same pinned versions. Locally, only zizmor, yamllint, ruff (plus llm-gate's locked tools) and the kyverno CLI are pinned; actionlint, hadolint, shellcheck, helm and kubeconform are whatever the machine has installed. ci.yml pins actionlint, hadolint, helm and kubeconform and uses the runner's shellcheck.
- **impact** (CONFIRMED, info, trivial): gates.md:34 says lint tool versions are pinned in both ci.yml and the lint recipe; the justfile pins zizmor, yamllint and ruff (and the kyverno CLI) but runs whatever actionlint, hadolint, shellcheck, helm and kubeconform are installed, while ci.yml pins actionlint 1.7.12, hadolint v2.14.0, helm v4.2.2 and kubeconform v0.8.0 and uses the runner's shellcheck. Local and CI results can differ for those tools; CI is what enforces.

</details>

### F130

**AGENTS.md says `just ci` runs "every deterministic gate"; http-tests, grype and k8s-smoke aren't in it**

- **Status:** ✅ fixed — #63: AGENTS.md says what `just ci` actually runs
- **Severity:** info (reviewers: info) · **outcome:** confirmed · **fix cost:** trivial
- **Where:** `AGENTS.md:26` · **area:** API, tests, docs
- **Reported by:** `dd-36` (info, high confidence)

`ci: fmt-check lint lint-chart lint-policies build test`. The deterministic gates http-tests, grype and k8s-smoke need `just image http-docker`, `just image scan` and a cluster (gates.md's table gives those commands). README.md:17 and gates.md:3-4 describe the scope correctly.

*Failure scenario:* An agent treats a green `just ci` as "every deterministic gate passes" after a Dockerfile or chart change, which `just ci` doesn't exercise beyond lint.

*Suggested fix:* "`just ci` runs the format, lint, chart, policy, build and test gates; image changes also need `just image http-docker scan`".

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, info, trivial): AGENTS.md says `just ci` runs 'the local equivalent of every deterministic gate', but the recipe is fmt-check lint lint-chart lint-policies build test (justfile:329). http-tests, grype and k8s-smoke need `just image http-docker`, `just image scan` and a cluster, as gates.md's table says. README and gates.md:3-4 describe the scope correctly, and CI still enforces the rest.
- **maintainer** (CONFIRMED, info, trivial): AGENTS.md:26-27 says `just ci` 'runs the local equivalent of every deterministic gate'. The recipe is fmt-check lint lint-chart lint-policies build test. http-tests, grype and k8s-smoke need `just image http-docker`, `just image scan` and a cluster. README and gates.md describe the scope correctly, and CI still enforces the rest, so info.
- **impact** (CONFIRMED, low, trivial): AGENTS.md:26 says `just ci` runs 'the local equivalent of every deterministic gate: run it before calling a change done', but `ci` is fmt-check lint lint-chart lint-policies build test; http-tests, grype and k8s-smoke need `just image http-docker`, `just image scan` and a cluster (gates.md's table). It's the definition of done agents read in every session, so after a Dockerfile, chart or .http change an agent can declare done on a green `just ci` and learn otherwise from CI; raised from info for that reason, while README and gates.md state the scope correctly.

</details>

### F131

**The workflow-review prompt attributes workflow rules to AGENTS.md; they live in docs/PLAN.md**

- **Status:** ✅ fixed — #63: the prompt points at docs/PLAN.md §11
- **Severity:** info (reviewers: info) · **outcome:** confirmed · **fix cost:** trivial
- **Where:** `.claude/commands/llm-workflow-review.md:7` · **area:** API, tests, docs
- **Reported by:** `dd-37` (info, high confidence)

"The repository's rules (`AGENTS.md`): every third-party action is pinned by full commit SHA with a version comment, workflows start from `permissions: {}` and grant per job, untrusted input never goes straight into `run:` ...". AGENTS.md has only "Never edit pinned action SHAs by hand" and "No pull_request_target workflows", and never had more (checked back to db1dcb5). The SHA-pinning and `permissions: {}` rules are in docs/PLAN.md:32 and :412-415. The agent engine reads the PR's AGENTS.md as data, so a reviewer that checks the citation won't find it.

*Failure scenario:* A reviewer cites AGENTS.md for a rule the file doesn't contain.

*Suggested fix:* Cite docs/PLAN.md (Decisions, Phase 6), or add these rules to AGENTS.md's Conventions.

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, info, small): llm-workflow-review.md:6-9 attributes three rules to AGENTS.md: SHA pinning with version comments, `permissions: {}` with per-job grants, and job names matching the check names. AGENTS.md has only 'Never edit pinned action SHAs by hand' and 'No pull_request_target workflows', and `git log -S` shows neither rule was ever in AGENTS.md or CLAUDE.md. They live in docs/PLAN.md (Decisions, line 32, and Phase 6). A prompt edit goes through llm-eval.
- **maintainer** (CONFIRMED, info, trivial): llm-workflow-review.md:7-10 attributes SHA pinning with version comments, `permissions: {}`, no untrusted input in run:, and 'job names are the required checks' to AGENTS.md. AGENTS.md only says never to edit pinned SHAs by hand and to have no pull_request_target, and the first version (db1dcb5) said no more. The other rules are in PLAN.md section 0 and Phase 6.1. The prompt states the rules itself, so only the citation is wrong.
- **impact** (CONFIRMED, info, trivial): llm-workflow-review.md:6-9 attributes SHA pinning with version comments, `permissions: {}` with per-job grants and the other workflow rules to AGENTS.md, which only says 'Never edit pinned action SHAs by hand' (line 102) and 'No pull_request_target workflows' (line 105). The rules are spelled out in the prompt itself, so the reviewer applies them anyway; only a citation would be wrong.

</details>

### F132

**No doc or recipe explains how to create the Gate health issue and set GATE_HEALTH_ISSUE**

- **Status:** ✅ fixed — #63: docs/metrics.md says how to create the issue and set the variable
- **Severity:** info (reviewers: info) · **outcome:** confirmed · **fix cost:** trivial
- **Where:** `docs/metrics.md:6` · **area:** API, tests, docs
- **Reported by:** `dd-39` (info, medium confidence)

metrics.md and metrics.yml need a pinned issue whose number is in the repository variable GATE_HEALTH_ISSUE, and metrics.yml silently skips the update when the variable is empty (`if: env.ISSUE != ''`). `just gh-setup` says it applies "variables", but it sets only LLM_MODEL and LLM_MODEL_CHEAP. No doc describes creating and pinning the issue (nor creating the orphan audit-log branch that the gh-rulesets recipe protects).

*Failure scenario:* On a fresh setup via `just gh-setup`, the weekly metrics run succeeds but never updates an issue, and nothing says why.

*Suggested fix:* Add the steps (`gh issue create`, pin it, `gh variable set GATE_HEALTH_ISSUE`) to gh-setup or to metrics.md.

<details><summary>Council</summary>

- **skeptic** (CONFIRMED, info, small): metrics.yml reads vars.GATE_HEALTH_ISSUE (line 27) and skips the issue update when it's empty (`if: env.ISSUE != ''`, line 60). gh-setup's comment (justfile:350) says it applies 'variables', but it sets only LLM_MODEL and LLM_MODEL_CHEAP (plus the secret, labels and environment). docs/metrics.md:6-7 and PLAN-v2:390 name the variable and the pinned issue, but nothing says how to create and pin the issue or set the variable. The report still lands in the job summary and the step shows as skipped, so 'nothing says why' is slightly overstated; the setup gap itself is real.
- **maintainer** (CONFIRMED, info, trivial): metrics.yml skips the issue update when vars.GATE_HEALTH_ISSUE is empty (`if: env.ISSUE != ''`), and gh-setup sets only LLM_MODEL and LLM_MODEL_CHEAP. Neither metrics.md nor any recipe says how to create and pin the issue and set the variable, or how to create the orphan audit-log branch. The report still lands in the job summary, so info.
- **impact** (CONFIRMED, info, trivial): metrics.yml updates the issue only `if: env.ISSUE != ''` (vars.GATE_HEALTH_ISSUE), `just gh-setup` sets only LLM_MODEL and LLM_MODEL_CHEAP, and docs/metrics.md:6-7 names the variable without saying how to create and pin the issue. On a fresh setup the weekly run still writes the report to its job summary, but no issue is updated and nothing says why.

</details>

## Plausible (unverifiable)

#### Plausible (unverifiable): medium

### F050

**Required checks are pinned to the GitHub Actions app, not to the jobs that produce them, while three PR jobs hold checks: write next to PR-controlled code**

- **Status:** ⚪ unverifiable — settling it means building the bypass it describes
- **Severity:** medium (reviewers: medium) · **outcome:** plausible · **fix cost:** small · **needs a CI repro**
- **Where:** `.github/rulesets/main.json:30` · **area:** workflows, release, deploy, scripts
- **Reported by:** `cr-ops-06` (medium, low confidence)

main.json pins each required context to integration 15368, and check-ruleset-consistency.py treats that pin as the protection ('is not pinned to GitHub Actions'). But any check run a job creates through the Checks API with its GITHUB_TOKEN carries that same app id. That is how dorny/test-reporter's 'test results' runs appear. build-test (via _dotnet.yml:17), http-tests (ci.yml:185) and k8s-smoke (ci.yml:262) get checks: write, and before their reporting step they run code from the PR on the runner: dotnet build/test of the PR's projects, and the PR's scripts/wait-for-health.sh. A token that can create check runs under any name ('llm / code-review', 'llm / security-review', 'llm-eval') is therefore within reach of PR-controlled code. No workflow file changes, so neither the collector's workflow_modified flag nor triage notices (tests/** is rated low). I didn't confirm how GitHub resolves two check runs with the same name on one commit, and that decides whether this is a bypass or only noise. The least-privilege gap stands either way.

*Failure scenario:* A PR whose build or test code publishes a successful check run named 'llm / code-review' on its head SHA while the real job reports a failure -> depending on GitHub's precedence for same-named runs, the required context can read as passing.

*Suggested fix:* Keep checks: write out of jobs that run PR code. Upload the TRX/JUnit files as artifacts and publish the test-report check runs from a separate job, or a workflow_run workflow, that runs no PR code. Let check-ruleset-consistency.py flag checks: write on pull_request jobs.

<details><summary>Council</summary>

- **skeptic** (PLAUSIBLE, medium, small): Confirmed by reading: _dotnet.yml (dotnet restore/build/test of the PR's projects) and http-tests/k8s-smoke (the PR's scripts/wait-for-health.sh) run PR-controlled code in jobs with checks: write, and a later dorny/test-reporter step receives GITHUB_TOKEN as an input; earlier PR code on the same runner can tamper with that step (for example the downloaded action files) to obtain it, and any check run it creates carries the GitHub Actions app id main.json pins. Unverified: how GitHub resolves two same-named check runs from the same app on one SHA; its docs only say duplicate names give 'ambiguous status check results' and can block, one third-party write-up says the most recently updated run wins, community reports say all must pass. That decides bypass versus noise, and only a throwaway PR settles it.
- **maintainer** (PLAUSIBLE, low, medium): build-test (_dotnet.yml:17), http-tests (ci.yml:185) and k8s-smoke (ci.yml:262) do hold checks: write for dorny/test-reporter and run PR-controlled code before it (dotnet build/test, scripts/wait-for-health.sh); on hosted runners such code can obtain the job's token, which creates check runs as the GitHub Actions app (15368) that main.json pins. Whether a same-named check run can satisfy or override 'llm / code-review' is platform behaviour: GitHub's docs only warn that duplicate job names give ambiguous results and may block merging, and I can't test it offline. The cause sits inside the accepted 'collaborators run code in CI' trust model, but this variant hides in tests/** (rated low) and isn't caught by workflow_modified. Moving test reporting to a workflow_run job is the standard fix.
- **impact** (PLAUSIBLE, medium, small): Confirmed part: build-test (_dotnet.yml), http-tests and k8s-smoke hold checks: write and run PR code first; that code can reach the token, e.g. by writing NODE_OPTIONS=--require into GITHUB_ENV so the later dorny/test-reporter node step (token input) runs it, or via sudo on the runner. A check run created with GITHUB_TOKEN carries the GitHub Actions app id 15368, so the ruleset's integration pin doesn't separate it from the real job. Unverified part: whether a later same-named check run decides the required context; GitHub's docs only warn that duplicate names 'can cause ambiguous status check results' and may block merging. If it does decide, a tests/**-only PR (triage: low, no workflow change, not flagged) can satisfy llm / code-review. Needs a collaborator acting deliberately, so medium rather than high even if the bypass works; only a throwaway PR can settle the precedence.

</details>

## Accepted by a recorded decision

Real, but an ADR or PLAN-v2's Status already accepts exactly this consequence.

### F066

**Any collaborator PR can read ANTHROPIC_API_KEY, because PR-supplied code and workflows run with it**

- **Status:** accepted
- **Severity:** low (reviewers: low) · **outcome:** accepted · **fix cost:** medium
- **Where:** `.github/workflows/llm-eval.yml:94` · **area:** workflows, release, deploy, scripts
- **Reported by:** `sec-08` (low, high confidence)
- **Reviewer's accepted_in:** docs/adr/0006-llm-eval-gate.md

`llm-eval.yml` deliberately runs the PR's own `tools/llm-gate` with `ANTHROPIC_API_KEY` (line 94), and on `pull_request` from a same-repo branch GitHub also runs any workflow file the PR adds with the repository's secrets available. So the key's confidentiality rests entirely on `pull_request_creation_policy=collaborators_only` and on fork runs getting no secrets (`just gh-setup`, justfile:367-369). ADR 0006 states this trade-off ("The PR's code runs with the API key. Only collaborators can open PRs here and fork PRs get no secrets; the key's exposure is the same as for v1's llm-review"). Recording it because it is the precondition that makes sec-02 and sec-03 bounded rather than public-facing, and because the mitigation named in the ADR (CODEOWNERS review for `tools/llm-gate/`) is not in place.

*Failure scenario:* A collaborator (or a compromised collaborator account/token) opens a PR whose added workflow prints `${{ secrets.ANTHROPIC_API_KEY }}` in an obfuscated form; the key is exfiltrated before anyone reviews the PR.

*Suggested fix:* Keep as accepted; if the repository ever gains contributors, move the key into an environment with required reviewers (zizmor's `secrets-outside-env` flags all four jobs) and add CODEOWNERS on `.github/` and `tools/llm-gate/`.

<details><summary>Council</summary>

- **skeptic** (ACCEPTED, low, medium): llm-eval runs the PR's tools/llm-gate with ANTHROPIC_API_KEY, and any same-repo PR workflow gets repository secrets. ADR 0006 records exactly this consequence ('The PR's code runs with the API key. Only collaborators can open PRs here and fork PRs get no secrets ... A team repository would add CODEOWNERS review for tools/llm-gate/'), and the report itself marks it accepted.
- **maintainer** (ACCEPTED, low, medium): llm-eval.yml:94 runs the PR's own tools/llm-gate with ANTHROPIC_API_KEY, and a same-repo PR's added workflow can read repository secrets too. ADR 0006's Consequences accept exactly this: 'The PR's code runs with the API key. Only collaborators can open PRs here and fork PRs get no secrets; the key's exposure is the same as for v1's llm-review. A team repository would add CODEOWNERS review'. The report itself says to keep it accepted.
- **impact** (ACCEPTED, low, medium): llm-eval.yml:150 runs the PR's own tools/llm-gate with ANTHROPIC_API_KEY, and any workflow a same-repo PR adds gets the secret on pull_request. ADR 0006 states exactly this ('The PR's code runs with the API key. Only collaborators can open PRs here and fork PRs get no secrets'), and gh-setup sets collaborators_only plus fork approval. The CODEOWNERS mitigation is named for a team repository, which this isn't. Note for calibration: logs of this public repo are public, so an injected agent's obfuscated print would leak the key publicly; still within the accepted model.

</details>

### F067

**Admission checks that an LLM-review attestation exists, not what it says**

- **Status:** accepted
- **Severity:** low (reviewers: low) · **outcome:** accepted · **fix cost:** small
- **Where:** `deploy/policies/base/llm-review.yaml:45` · **area:** workflows, release, deploy, scripts
- **Reported by:** `sec-11` (low, high confidence)
- **Reviewer's accepted_in:** docs/adr/0010-admission-control.md

`calendar-gates-llm-review` only requires `verifyAttestationSignatures(...) > 0`, unlike `calendar-gates-release`, which reads the vuln-scan predicate and asserts `counts.critical == 0` (release.yaml:58-62). The llm-review predicate is built to be read: it carries `unreviewed` (a blocking check skipped for want of a key, or an error) and `unverified` (`workflow_modified`, `tamper_suspected`) lists, and WRITEUP §3 reports 56 unverified reviews in this repository. So an image whose own attestation says its changes were never reviewed, or that reviews can't be verified, is admitted in the enforcing namespace. ADR 0010 states the policy as presence-only, which is why this is an accepted design point rather than a defect; ADR 0009 similarly says the attestation "lists gaps instead of hiding them".

*Failure scenario:* A release whose PRs all ran with `LLM_GATE_MISSING_KEY` unset and no API key carries `prs: [...], unreviewed: [{...}]`; Kyverno admits it in `calendar-gates`, and `admission-smoke` passes, because the attestation exists.

*Suggested fix:* Add a validation on the predicate, e.g. `extractPayload(image, attestations.llmreview).predicate.unverified.size() == 0 && ....unreviewed.size() == 0` (or a documented allowance), so the content the release notes print is also what admission enforces.

<details><summary>Council</summary>

- **skeptic** (ACCEPTED, low, small): calendar-gates-llm-review only requires verifyAttestationSignatures(...) > 0 (llm-review.yaml:45-47) and never reads the predicate's unreviewed/unverified lists, unlike the critical-count check in release.yaml. ADR 0010 states the rule as 'the LLM-review attestation is present' and WRITEUP section 2 lists 'LLM-review attestation present'; with most PRs here editing llm-review.yml (56 unverified reviews), content enforcement would deny every release, so presence-only is the recorded design and this is its direct consequence.
- **maintainer** (ACCEPTED, low, small): calendar-gates-llm-review only checks verifyAttestationSignatures(...) > 0, not the predicate's unreviewed/unverified lists. ADR 0010 defines the policy as 'the LLM-review attestation is present', and ADR 0009 says the attestation 'lists gaps instead of hiding them' and 'doesn't prove the reviews were right'. A content rule would deny nearly every release here, since many PRs edit llm-review.yml (56 unverified reviews in WRITEUP §3), so presence-only is a deliberate, recorded choice. The report also cites ADR 0010.
- **impact** (ACCEPTED, low, small): calendar-gates-llm-review only requires verifyAttestationSignatures(...) > 0, unlike the critical-count check in calendar-gates-release. ADR 0010 defines this policy as presence-only and ADR 0009 says the attestation lists gaps for people to read. The consequence is understood: WRITEUP 3 reports 56 unverified reviews from PRs that edit llm-review.yml, so requiring an empty unverified list would deny every release of this repository.

</details>

### F068

**The llm-eval comment job posts an artifact written by the PR's own code without validating it**

- **Status:** accepted
- **Severity:** info (reviewers: low) · **outcome:** accepted · **fix cost:** small
- **Where:** `.github/workflows/llm-eval.yml:163` · **area:** workflows, release, deploy, scripts
- **Reported by:** `sec-12` (low, high confidence)

The `comment` job runs the base branch's `upsert-pr-comment.sh` with `pull-requests: write`, but its body is `comment.md` from the `llm-eval` artifact, which the previous job produced by running the PR's own `tools/llm-gate` (ADR 0006). The only handling is `find "$RUNNER_TEMP/report" -name comment.md -print -quit` (line 173); the content is never length-checked, redacted or matched against the job's status. It is a lesser case than the llm-review path because the PR already controls that check's verdict, but the result is that a PR can make the bot post arbitrary Markdown under the `<!-- llm-gate:llm-eval -->` marker, which is what a reader scans for the eval table.

*Failure scenario:* A PR's modified `evals.py` writes a `comment.md` claiming "✅ llm-eval: recall 1.00, no regressions" while the real scores regressed; the bot posts it, and the check is green because the same code chose the exit status.

*Suggested fix:* Have the comment job render the table itself from the structured report (`reports/eval/last.json`) with the base branch's code, or at least prefix the posted body with the job's real conclusion and pass the artifact text through `redact()`/length limits.

<details><summary>Council</summary>

- **skeptic** (ACCEPTED, info, small): The comment job posts comment.md from the eval artifact without validation (llm-eval.yml:163-175), and both its body and its pass/fail header come from the PR's own llm-gate and that code's exit status. ADR 0006 deliberately runs the PR's prompts and code in the eval ('the change is the thing under test') and keeps only the write token away from them ('The sticky comment is posted by a second job that runs only the base branch's script'), so the PR already controls the llm-eval verdict and the comment adds nothing beyond it; on pull_request the PR's copy of llm-eval.yml defines the comment job anyway. The report itself concedes the PR controls that verdict.
- **maintainer** (ACCEPTED, low, small): The comment job posts comment.md from the artifact that the PR's own llm-gate wrote. ADR 0006 records exactly this split: the eval runs the PR's prompts and code with a read-only token, and the comment is posted by a second job running only the base branch's script with the write token. The PR's code already decides the check's exit status, so a forged report adds nothing a forged verdict doesn't; rendering from the PR's last.json would still post PR-controlled numbers. One sub-claim is wrong: the body is length-checked, because upsert-pr-comment.sh:21-24 truncates it to 60000 characters.
- **impact** (ACCEPTED, info, small): The comment job posts comment.md from the artifact the PR's own code produced (llm-eval.yml:229-231), unvalidated apart from the 60000-character cut in upsert-pr-comment.sh. ADR 0006 deliberately runs the PR's prompts and code for llm-eval and splits the write token into a job that runs only the base branch's script; it already follows that the PR controls both the verdict and its rendering. A PR author (collaborators only) gains nothing they couldn't post as a comment themselves, apart from the bot's byline.

</details>

## Rejected

Kept for the record: the finding, and why the council turned it down.

### F034

**HTTP status errors (API engine) and the Agent SDK's ResultError/ClaudeSDKError conversions are untested**

- **Status:** rejected
- **Severity:** info (reviewers: low) · **outcome:** rejected · **fix cost:** trivial
- **Where:** `tools/llm-gate/src/llm_gate/engines/api_engine.py:60` · **area:** llm-gate and review prompts
- **Reported by:** `tr-18` (low, high confidence)
- **Reports the council found wrong:** `tr-18`

<details><summary>Council</summary>

- **skeptic** (REJECTED, info, trivial): The APIStatusError branch is untested and its deletion survives, but the mutant is equivalent apart from the message. APIStatusError subclasses AnthropicError, which the next handler converts to EngineError. With the handler removed, a 529 through the real SDK (mock transport) still gives triage.assess risk=None with 'Claude API client error: ... 529', and the floor stands. The report's failure scenario, a 529 raising out of assess and failing the triage job, is therefore wrong. Agent-engine ResultError/ClaudeSDKError would fall to run_check's catch-all and still fail closed, and triage doesn't use that engine.
- **maintainer** (REJECTED, info, trivial): The branches are untested, but the claimed consequence is wrong: APIStatusError subclasses APIError, which subclasses AnthropicError (anthropic/_exceptions.py), so with the status handler deleted the `except anthropic.AnthropicError` branch still turns a 429/529 into an EngineError and triage.assess still leaves the floor (the deletion mutation survives precisely because behaviour is unchanged, apart from the message). A missing ResultError/ClaudeSDKError handler in the agent engine falls back to run_check's catch-all, which fails blocking checks closed; triage never uses the agent engine. Nothing fails open.
- **impact** (CONFIRMED, low, small): Coverage shows api_engine.py:61 (the APIStatusError conversion) and agent_engine.py 123-130 (ResultError, ClaudeSDKError) never executed. Reviews stay fail-closed through run_check's catch-all; triage.assess relies on the conversion (it catches only EngineError), so a dropped handler would let a 529 crash triage, the failure mode F011 already shows for ValidationError. The handlers exist today: a test gap, low.

</details>

### F041

**workflow-review only sees .github/**, not the code the trusted workflows run**

- **Status:** rejected
- **Severity:** info (reviewers: info) · **outcome:** rejected · **fix cost:** trivial
- **Where:** `tools/llm-gate/checks.yaml:25` · **area:** llm-gate and review prompts
- **Reported by:** `wr-22` (info, high confidence)

<details><summary>Council</summary>

- **skeptic** (REJECTED, info, trivial): workflow-review's prompt defines its scope as the GitHub Actions setup (.github/workflows/, .github/actions/, dependabot.yml, rulesets), and its paths filter [.github/**] matches that. The scripts and tools/llm-gate code the workflows run are rated high by triage, so code-review and security-review review them on the agent engine. The advisory workflow review not covering them is a scope choice, not a defect.
- **maintainer** (REJECTED, info, trivial): workflow-review's paths [".github/**"] match its prompt's stated scope ('changes to the GitHub Actions setup': workflows, actions, dependabot.yml, rulesets). The trusted-side code it lists (scripts/**, tools/llm-gate/**, deploy/**) is rated high by triage, so both blocking checks review it on the agent engine, which can read the workflows for context. Widening it is an option, not a defect.
- **impact** (REJECTED, info, trivial): Accurate, but not a defect: workflow-review's prompt declares its scope as .github/workflows/, .github/actions/, dependabot.yml and the rulesets, and paths ['.github/**'] matches that scope. The scripts and gate code the finding lists are rated high by triage (scripts/**, tools/llm-gate/**), so both blocking checks review them on the agent engine, which can read the workflows. Widening an advisory check's scope is a suggestion, not a gap with a cost.

</details>

### F049

**just release (and release.yml's verify job) accept versions that Helm rejects, so the release fails in publish after the immutable tag, attestations and image tag exist**

- **Status:** rejected
- **Severity:** info (reviewers: medium) · **outcome:** rejected · **fix cost:** trivial
- **Where:** `justfile:276` · **area:** workflows, release, deploy, scripts
- **Reported by:** `cr-ops-04` (medium, high confidence)
- **Reports the council found wrong:** `cr-ops-04`

<details><summary>Council</summary>

- **skeptic** (REJECTED, info, trivial): The regex (justfile:276, release.yml:47) does admit 1.0.0-rc.01, 1.0.0-rc..1 and 1.0.0-., and helm v4.2.2 rejects all three (reproduced). But the release never reaches publish: the build job's Dockerfile runs dotnet publish with -p:MinVerVersionOverride=$VERSION, and MinVer 8.0.0 (NuGet's strict SemVer parser) rejects all three with 'error MINVER1005 : Invalid version override' and exit code 2 (reproduced with the package's own MinVer.dll; it also rejects 01.0.0), so the image build fails before scan, attest and publish. No image tag, attestations or Rekor entries exist; only the immutable signed git tag is burnt. That residual, a version check looser than the build's, is info.
- **maintainer** (REJECTED, info, trivial): The regex in justfile:276 and release.yml:47 is looser than SemVer, and helm 4.2.2 does reject 1.0.0-rc.01 ('version segment starts with 0') and 1.0.0-rc..1, as reported. But the described consequence doesn't happen: the Dockerfile passes VERSION as -p:MinVerVersionOverride, and MinVer 8.0.0 (a GlobalPackageReference) rejects both versions ('Invalid ... MinVerVersionOverride', exit 2), so the build job fails before anything is pushed, scanned, attested or tagged. The versions MinVer accepts (e.g. 1.0.0--, 1.0.0-0a) helm packages fine. What remains is a burnt git tag after a malformed version, which is the documented cost of any failed release; a strict SemVer regex in the recipe would avoid even that.
- **impact** (CONFIRMED, low, trivial): The recipe and verify regex accept 1.0.0-rc.01; `git check-ref-format refs/tags/v1.0.0-rc.01` passes and `helm package --version 1.0.0-rc.01` with helm v4.2.2 fails 'version segment starts with 0' (rc.1 packages fine), and publish promotes the image tag before packaging. The report's other examples don't reach a push: git refuses v1.0.0-rc..1 and v1.0.0-. as tag names, so just release stops at git tag -s. Only leading-zero numeric prerelease ids burn a version (MinVer's override parsing may even fail it earlier, at build, leaving only the tag). Cost is a burnt, undeletable version number and some clutter, no security or availability impact: low.

</details>

### F051

**llm-review has no `gates`-style aggregator, so a failed `triage` job decides the fate of two required checks**

- **Status:** rejected
- **Severity:** info (reviewers: medium) · **outcome:** rejected · **fix cost:** small
- **Where:** `.github/workflows/llm-review.yml:174` · **area:** workflows, release, deploy, scripts
- **Reported by:** `sec-06` (medium, medium confidence)
- **Reports the council found wrong:** `sec-06`

<details><summary>Council</summary>

- **skeptic** (REJECTED, info, small): A job skipped because a needs: dependency failed is skipped before its matrix expands, and GitHub then reports it under the unexpanded name (here `llm / ${{ matrix.check }}`), so the required contexts llm / code-review and llm / security-review never report and the PR waits: it fails closed, not open. Several independent reports show this (GitHub community discussion #9141; samyama-graph PR #1863, whose `gh pr view` lists the literal `${{ matrix.* }}` name with conclusion SKIPPED and notes the required names never report). The finding itself named this untested platform detail as the deciding factor. Residual: a failed triage shows as 'Expected, waiting for status' instead of a red check, a usability issue.
- **maintainer** (REJECTED, info, small): When triage fails, the llm matrix job is skipped before its matrix is expanded, and GitHub reports such a job under its literal name 'llm / ${{ matrix.check }}' (documented in several public issues about skipped matrix jobs). So 'llm / code-review' and 'llm / security-review' never report for that head and the ruleset leaves the PR waiting, which fails closed, unlike the fixed-name ci.yml jobs from drill 8 that a skipped run satisfies. A triage failure costs a re-run, not a review. An aggregator would make the failure red instead of pending, a cosmetic improvement.
- **impact** (REJECTED, info, small): The llm matrix job needs triage and its matrix is fromJSON(needs.triage.outputs.checks). When triage fails the dependent job is skipped before its matrix can be expanded, so GitHub reports one skipped job under the unexpanded name 'llm / ${{ matrix.check }}', never check runs named 'llm / code-review' or 'llm / security-review'; those required contexts stay 'expected' and the PR is blocked. Several independent public reports show exactly this: a skipped matrix job surfaces as e.g. 'test (${{ matrix.os }})' and the expanded required names never report. The feared outcome (required checks satisfied by skipped runs) needs check runs with the required names, which a skipped, unexpanded matrix can't produce, so the failure mode is fail-closed and an aggregator would only improve the message. No llm-review run in this repo's history had triage or llm-plan fail (I listed the jobs of all 29 failed runs), so it is untested here, but not a hole.

</details>

### F079

**zizmor (offline, default and auditor personas), actionlint, yamllint and shellcheck: every hit checked, none needs action**

- **Status:** rejected
- **Severity:** info (reviewers: info) · **outcome:** rejected · **fix cost:** trivial
- **Where:** `.github/zizmor.yml:4` · **area:** workflows, release, deploy, scripts
- **Reported by:** `wr-20` (info, high confidence)

<details><summary>Council</summary>

- **skeptic** (REJECTED, info, trivial): Reproduced the item's claims: zizmor 1.30.1 --offline reports 'No findings to report. Good job! (1 ignored, 10 suppressed)', and yamllint 1.38.0 --strict, actionlint 1.7.12 and shellcheck on scripts/*.sh and .claude/hooks/*.sh are clean. The item itself says none of the hits needs action: an accurate observation, not a defect.
- **maintainer** (REJECTED, info, trivial): Not a defect: an all-clear report. I re-ran zizmor 1.30.1 --offline ('No findings to report. 1 ignored, 10 suppressed'), actionlint and shellcheck on scripts/*.sh and .claude/hooks/*.sh: all clean, as stated. The auditor-persona hits it mentions are deliberate: no concurrency group in audit-collect and llm-feedback (ADR 0005/0007), and the API key outside an environment because the reviews run on pull_request (ADR 0006). Nothing to fix.
- **impact** (REJECTED, info, trivial): Not a defect: the item reports that the linters and zizmor personas find nothing that needs action. Re-run here: actionlint 1.7.12, shellcheck on scripts/*.sh and .claude/hooks/*.sh, and yamllint 1.38.0 --strict are all clean (zizmor not re-run: uvx can't write its tool dir in the sandbox). The observation is accurate; nothing to fix.

</details>

### F087

**/api/week/{date} and /api/workdays accept years 1 to 1582, which every year endpoint rejects as unsupported**

- **Status:** rejected
- **Severity:** info (reviewers: low) · **outcome:** rejected · **fix cost:** trivial
- **Where:** `src/CalendarGates.Api/Endpoints/EndpointHelpers.cs:13` · **area:** API, tests, docs
- **Reported by:** `api-08` (low, high confidence), `cr-api-04` (info, medium confidence)

<details><summary>Council</summary>

- **skeptic** (REJECTED, info, trivial): The behaviour reproduces (week/1500-06-15 gives 200, week/0001-01-01 gives 200, and workdays over 0001-01-01..0001-12-31 gives 261), but it isn't a defect. A yyyy-MM-dd date is ISO 8601, which is proleptic Gregorian by definition, so the ISO week and the weekday counts are correct for the input; cr-api-04 itself says the answers aren't wrong. PLAN.md §2.2 gives the 1583..9999 range only to friday13, and Years guards the endpoints whose answer depends on year-specific Gregorian rules (Easter, leap years). api-08's 'calendar rules that weren't in use then' misreads this: the request date is itself proleptic. At most a sentence is missing from the summaries.
- **maintainer** (REJECTED, info, trivial): I verified that /api/week/1500-06-15 returns 200 and workdays over the year 0001 returns 261. This is the plan's design: PLAN.md 2.2 sets the 1583..9999 range only for the year endpoint (friday13), and dates are validated by format (yyyy-MM-dd). ISO 8601 weeks are defined on the proleptic Gregorian calendar that DateOnly uses, and weekday counts don't depend on the calendar reform, so the answers are correct (cr-api-04 says so too). `Years` is used only by the year calculators. At most, its summary and the prompts' 'the supported year range' wording could say that they apply to the year endpoints.
- **impact** (CONFIRMED, info, small): Verified: /api/week/1500-06-15 returns 200 (week 24), /api/week/0001-01-01 200, /api/workdays 0001-01-01..0001-12-31 261, and even the skipped transition date 1582-10-10 returns 200, while easter, leap and friday13 reject years below 1583; no input at the extremes (0001-01-01, 9999-12-31) errors. The answers are correct by definition: ISO 8601 week dates use the proleptic Gregorian calendar and the weekday cycle is unbroken, and nothing documents 1583..9999 as the range of week or workdays (PLAN.md §2.2 names it for friday13; Years is used only by the year calculators). What remains is an undocumented difference in scope, an observation rather than a defect; api-08's 'rules that weren't in use then' overstates it, cr-api-04's info is right.

</details>

### F088

**A non-numeric or Int32-overflowing year is 404 on /api/easter/{year:int} and /api/leap/{year:int}, but 400 elsewhere**

- **Status:** rejected
- **Severity:** info (reviewers: low) · **outcome:** rejected · **fix cost:** trivial
- **Where:** `src/CalendarGates.Api/Endpoints/EasterEndpoints.cs:13` · **area:** API, tests, docs
- **Reported by:** `api-05` (low, high confidence), `cr-api-05` (info, high confidence)

<details><summary>Council</summary>

- **skeptic** (REJECTED, info, trivial): Reproduced: /api/easter/abc, /api/leap/abc, /api/easter/99999999999 and /api/leap/2147483648 return 404 problem+json, and /api/leap/2147483647 returns 400 with errors.year. That is the {year:int} route constraint working as designed. EasterTests.NonNumericYearDoesNotMatchTheRoute pins the 404, and the OpenAPI document declares year as integer/int32 with minimum 1583 and maximum 9999, so these inputs fall outside the published contract. cr-api-05 itself calls the overflow case a side effect of the design rather than a defect.
- **maintainer** (REJECTED, info, trivial): I verified that /api/easter/abc, /api/easter/99999999999 and /api/leap/2147483648 return 404 and /api/leap/2147483647 returns 400. The `{year:int}` constraint is a deliberate, tested choice: EasterTests.NonNumericYearDoesNotMatchTheRoute pins the 404. A segment that isn't an Int32 not matching an int route follows directly from that, as cr-api-05 says. This is not a defect; at most it deserves a note next to that test.
- **impact** (CONFIRMED, info, small): Verified: /api/easter/abc, /api/leap/abc, /api/easter/99999999999 and /api/leap/2147483648 give 404 problem+json, while /api/leap/99999 and /api/leap/2147483647 give the 400 ValidationProblem. The non-numeric 404 is pinned by EasterTests.NonNumericYearDoesNotMatchTheRoute, so it's deliberate (though not in an ADR or the plan), and the overflow case is its side effect. Impact is negligible because the OpenAPI schema declares the path parameter as int32 with min/max, so generated clients can't send these; it does contradict the api-contract prompt's '400 ValidationProblem for bad input', which merits a note next to the test.

</details>

### F097

**The year is a path segment on easter and leap but a query parameter on friday13, and unknown query parameters are silently ignored**

- **Status:** rejected
- **Severity:** info (reviewers: low) · **outcome:** rejected · **fix cost:** trivial
- **Where:** `src/CalendarGates.Api/Endpoints/Friday13Endpoints.cs:17` · **area:** API, tests, docs
- **Reported by:** `api-09` (low, high confidence)

<details><summary>Council</summary>

- **skeptic** (REJECTED, info, trivial): The behaviour reproduces: /api/week?date=2027-01-01 returns today's week, /api/friday13/next?year=2030 ignores the year, and /api/leap?year=2000 and /api/friday13/2026 are 404. But the routes are exactly the ones in PLAN.md §2.2's table: a path year for easter and leap, ?year= with a default for friday13, and ?from=&to= for workdays. Ignoring unknown query parameters is normal behaviour for ASP.NET Core and for most HTTP APIs. The report's own fix concedes that moving routes would be a breaking change, so what's left is a documentation suggestion, not a defect.
- **maintainer** (REJECTED, info, trivial): The route styles are the design in PLAN.md 2.2: `/api/friday13?year=` defaulting to this year, `/api/easter/{year}`, `/api/leap/{year}`, `/api/workdays?from=&to=`, and `/api/week` plus `/api/week/{date}`. Ignoring unknown query parameters is the ASP.NET Core default and normal for HTTP APIs. I did confirm that /api/week?date=2027-01-01 returns today's week. This is not a defect; the reviewer's own suggestion (document the style) is optional.
- **impact** (CONFIRMED, low, small): Verified: /api/week?date=2027-01-01 returns today's week (2026-10-17, week 42) with 200, /api/friday13/next?year=2030 ignores the year, and /api/leap?year=2000, /api/easter?year=2026 and /api/friday13/2026 return 404. The route shapes are the ones PLAN.md §2.2 specified and ignoring unknown query parameters is standard, so this is a style footgun, not a bug: a client guessing the wrong style silently gets 'today'. Routes can't move without breaking clients, so the fix is documentation, as the report says.

</details>

### F117

**The length of /api/version's commit depends on how the service was built: 40 characters under dotnet run, 7 in CI and release images**

- **Status:** rejected
- **Severity:** info (reviewers: info) · **outcome:** rejected · **fix cost:** trivial
- **Where:** `src/CalendarGates.Api/Endpoints/VersionEndpoints.cs:32` · **area:** API, tests, docs
- **Reported by:** `api-22` (info, medium confidence)

<details><summary>Council</summary>

- **skeptic** (REJECTED, info, trivial): True as an observation. An unflagged dotnet build falls back to the SDK's +sha suffix (my local build reported all 40 characters), while ci.yml:152 and release.yml:65 pass ${SHA::7}, `just image` passes `git rev-parse --short HEAD`, and the Dockerfile defaults to 'unknown'. But nothing specifies the field's length, and nothing compares it programmatically: the release smoke checks only the version, and MetaTests and calendar.http check only for a non-empty string. Every shipped image reports 7 characters and no consumer breaks, so this is a suggestion to normalise, not a defect.
- **maintainer** (REJECTED, info, trivial): VersionEndpoints.Read deliberately prefers the Commit metadata from the Docker build arg: 7 characters in ci.yml and release.yml, `git rev-parse --short` in `just image`. Without it, it falls back to the SDK's +SourceRevisionId suffix, a full SHA under dotnet run, as its doc comment says. The shipped images are consistent, and nothing compares the field's length; the release smoke checks only the version. Not a defect; calling the field an abbreviated id in the docs is optional.
- **impact** (CONFIRMED, info, small): My local build's /api/version reports the full 40-character SourceRevisionId (43ec3c2f019d...), while ci.yml:152 and release.yml:65 pass `${SHA::7}` and `just image` passes `git rev-parse --short HEAD`. Nothing compares this field programmatically today, and a prefix comparison works for both lengths.

</details>

### F118

**The OpenAPI document's info.version is always 1.0.0, and the API has no version of its own**

- **Status:** rejected
- **Severity:** info (reviewers: info) · **outcome:** rejected · **fix cost:** trivial
- **Where:** `src/CalendarGates.Api/Program.cs:8` · **area:** API, tests, docs
- **Reported by:** `api-24` (info, high confidence)

<details><summary>Council</summary>

- **skeptic** (REJECTED, info, trivial): Verified: info is {title 'CalendarGates.Api | v1', version '1.0.0'}, the AddOpenApi() default. OpenAPI defines info.version as the version of the document, distinct from the implementation's version. The contract hasn't changed since the API was written (src/ last changed in #6), and the document is served as v1. Nothing here caches by info.version, so this is a suggestion (derive it from MinVer, or keep a contract changelog), not a defect.
- **maintainer** (REJECTED, info, trivial): I confirmed that info.version is 1.0.0 (title 'CalendarGates.Api | v1'). That is the default of the built-in AddOpenApi(), which PLAN.md 2.2 chose. /api/version already reports the build version, and the contract version is the document name (v1). Nothing reads info.version, API versioning isn't in scope, and tying info.version to MinVer would mix the build version with the contract version. Not a defect.
- **impact** (CONFIRMED, info, small): The document's info is title 'CalendarGates.Api | v1', version '1.0.0' in my build, while MinVer versions the build 0.3.2-alpha.0.7; it's AddOpenApi()'s default. No consumer caches by it and /api/version carries the real version.

</details>

### F133

**The 'today' requests check shape but not that the date is today**

- **Status:** rejected
- **Severity:** info (reviewers: info) · **outcome:** rejected · **fix cost:** trivial
- **Where:** `http/calendar.http:14` · **area:** API, tests, docs
- **Reported by:** `tr-30` (info, high confidence)

<details><summary>Council</summary>

- **skeptic** (REJECTED, info, trivial): The .http header (lines 1-2) and PLAN.md 3.4 deliberately make 'today' requests assert shape and invariants, never today's values, and the test-review prompt flags handlers that assert today's values. The report asks for what that convention rules out, and a ±1 day check would also depend on the runner's clock versus the container's. Where the clock can be pinned, the wiring is tested: CurrentWeekFollowsTheClock and NextIsTodayOnTheDay show that the endpoints follow the injected TimeProvider. The scenario needs a fixed clock registered in Program.cs, which registers TimeProvider.System, in an API project that doesn't reference the test-only FakeTimeProvider package.
- **maintainer** (REJECTED, info, trivial): calendar.http:2 and PLAN.md 3.4 deliberately check 'shape and invariants, never today's values' for the 'today' requests. A stuck clock would need code in Program.cs registering a fixed TimeProvider, and FakeTimeProvider isn't even referenced by the API project, so the scenario is contrived. A check within one day of today would be an optional extra, not a fix for a defect.
- **impact** (CONFIRMED, info, trivial): The /api/week and /api/friday13/next requests assert format and invariants but not closeness to the client's date, which follows the deliberate convention in calendar.http's header and PLAN.md §3.4 ('never today's values'). Program.cs registers TimeProvider.System and FakeTimeProvider is referenced only by the test projects, so a fixed clock in the image needs a deliberate change; a one-day-tolerance check would be cheap insurance.

</details>

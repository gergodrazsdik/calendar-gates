# Gates

Every gate runs locally through `just` and in CI as a named check. `just ci` runs the
deterministic ones (format, lint, build, test). Required checks on `main` are set in the ruleset
`.github/rulesets/main.json` (applied with `just gh-rulesets`): `pr-title`, `format`, `lint`,
`build-test / dotnet`, `http-tests`, `grype`, `k8s-smoke`, `gates`, `llm / code-review`,
`llm / security-review`. The other checks report but don't block. `lint` fails if the ruleset, the workflow job names and the blocking
checks in `checks.yaml` disagree (`scripts/check-ruleset-consistency.py`). The `release-tags`
ruleset (`.github/rulesets/tags.json`) makes `v*` tags immutable: no deletion, no moving.

The check names are the job names in `.github/workflows/ci.yml` and `llm-review.yml`. Renaming a
job would silently break branch protection until the ruleset follows; the consistency check in
`lint` catches that. A required check that is **skipped counts as passing**, which is why `gates`
is required too (see below).

| Check | Local | Fails when | Fix | Override |
|---|---|---|---|---|
| `pr-title` | `scripts/check-commit-msg.sh --title "<title>"` | PR title is not a Conventional Commit (it becomes the squash commit) | Edit the title, then push (title edits alone don't re-run CI) | none |
| `format` | `just fmt-check` | CSharpier would change layout, or a code-style/analyzer rule fires | `just fmt`; for rule findings fix the code (the message names the rule) | none; rules live in `.editorconfig` and are changed in their own PR |
| `lint` | `just lint lint-chart` | actionlint, zizmor, hadolint, yamllint, shellcheck, ruff, the llm-gate tests, the ruleset consistency check, `helm lint` or kubeconform report a finding | Fix the finding; suppress only inline with a reason (`# zizmor: ignore[...]`, `# shellcheck disable=...`, `# noqa`) | Repo-wide rule changes in `.github/zizmor.yml`, `.yamllint.yaml` |
| `build-test / dotnet` | `just build test` | Build warning (warnings are errors) or a failing test | The **test results** check run lists failures with file/line; coverage is in the job summary | none |
| `image` | `just image` | Docker build fails | Build output in the job log | none |
| `http-tests` | `just image http-docker` | An `http/calendar.http` handler assertion fails against the built container | The **http test results** check run names the request; container logs are printed on failure | none |
| `grype` | `just image scan` | A **high** or **critical** vulnerability in the image | Update the package or base image (Dependabot `docker`/`nuget`) | `ignore:` entry in `.grype.yaml` with a reason and an expiry date, called out in the PR |
| `k8s-smoke` | `just k8s-up k8s-policy-up` once, then `just k8s-load`, `just k8s-deploy calendar-gates-dev`, `just k8s-http calendar-gates-dev` (or `just cluster=local k8s-load k8s-deploy k8s-http`) | The chart does not install on a fresh kind cluster, a pod never becomes ready, or a `.http` test fails through the port-forward | The job summary lists pods, recent events (probe failures, image errors) and pod logs | none |
| `llm / <check>` (`llm-review.yml`) | `just llm <check>` | A **blocking** check (`code-review`: high, `security-review`: medium) has a finding at or above its threshold, or fails closed on an error | Fix the finding, or argue it in the PR. A diff over `max_diff_kb` is a different fix: split the PR, or override it (next column) | Comment `/llm-override <reason>`: the feedback workflow adds the `llm-override` label and re-runs the review. Or add the label yourself **plus** that comment. Either way the findings are still reported and the override is recorded; thresholds in `tools/llm-gate/checks.yaml`. An override also accepts a diff over `max_diff_kb` **unreviewed** ([ADR 0002](adr/0002-llm-gate-policy.md)); an API error, refusal or crash is never overridable, so re-run it |
| `llm-eval` (`llm-eval.yml`) | `just eval` | The PR changes a review prompt or `tools/llm-gate/` and scores worse than `evals/baseline.json` beyond `evals/thresholds.yaml` (recall, false blocks, flips, cost), or the eval doesn't finish within its budget | Fix the prompt or code; or, if the new scores are the intended trade-off, update the baseline in the same PR (`just eval-baseline`) and say why | `evals/thresholds.yaml` (changing it weakens the gate: say so) |
| `gates` | n/a | Any gate it needs did not succeed (failed, cancelled or skipped) | Fix that gate | none |

## Notes per gate

- **format**: CSharpier owns layout, `dotnet format` only checks rules ([ADR 0001](adr/0001-csharpier-owns-formatting.md)).
  `dotnet format whitespace` is never run.
- **lint**: tool versions are pinned in both `ci.yml` and the `lint` recipe; bump them together.
  zizmor's `self-repository` audit is disabled until actionlint understands the `$/` syntax.
- **build-test** is a reusable workflow (`_dotnet.yml`), which is why its check is `build-test / dotnet`.
  The release workflow (Phase 11) calls the same file.
- **image** builds once per run and hands the image to `http-tests`, `grype` and `publish-edge` as an
  artifact, so every later job tests (and publishes) the same bytes.
- **grype** results also go to Security → Code scanning (category `grype`), uploaded even when the
  gate fails.
- **k8s-smoke** installs the chart with the tested image on a throwaway kind cluster
  (`helm/kind-action`), with `--rollback-on-failure`, then runs the contract tests through a
  port-forward ([ADR 0003](adr/0003-kind-access.md)).
- **publish-edge** (push to `main` only, not a gate) pushes the tested image as
  `ghcr.io/gergodrazsdik/calendar-gates:edge` and `:sha-<short>`.
- **gates** is red unless every gate it needs **succeeded**: failed, cancelled and *skipped* all
  count against it (only `pr-title` may be skipped, on pushes to `main`). The ruleset alone would
  accept a skipped gate, and a gate is skipped not only by an `if:` but whenever a job it `needs:`
  fails: a PR that breaks only the image build would skip `http-tests`, `grype` and `k8s-smoke`,
  which then count as passing (gate drill 8). Requiring `gates` as well closes that; the individual
  checks stay required for a readable list of what failed. `gates` covers `ci.yml` only, so the
  `llm / …` checks and `llm-eval` are required on their own.

- **llm / <check>**: the model returns findings; llm-gate decides from their severities
  ([ADR 0002](adr/0002-llm-gate-policy.md)). Advisory checks never fail. Results are cached per
  check, engine, model, prompt and diff, so re-runs without changes are free.
  In CI each check is a job in `llm-review.yml` (matrix from `llm-gate list --json`) that writes the
  review to the job summary and one sticky PR comment per check (updated on every run; "not
  applicable" only updates an existing one). PRs without the API key (forks, Dependabot) skip with a
  notice; set the repo variable `LLM_GATE_MISSING_KEY=fail` to make blocking checks fail closed
  instead (gate drill 9). Adding or removing a label re-runs only these checks, from the cache.
- **Triage** ([ADR 0008](adr/0008-risk-triage.md)): the `triage` job (first in `llm-review.yml`)
  rates the PR `low`, `medium` or `high`.
  - **Rules:** the paths in `checks.yaml` `triage.rules` (`.github/`, the gate and deployment are
    high), raised by size and by AI markers (commit trailers, the PR body).
  - **Model:** a cheap model may raise the rating, never lower it.
  - **Labels:** triage sets `risk:<level>` and `ai-assisted`. A hand-set `risk:*` label is put back.
    To change the risk, comment `/llm-risk <level> <reason>`.

  The level decides which checks review and which block. At `low`, only code-review and docs-drift
  review, and both are advisory. At `high`, the blocking checks use the agent engine, with their usual
  model. A check the level doesn't need still reports success with "not needed at risk: <level>",
  so required checks never go missing. The job summary shows why the PR got its level.
- **api-contract** runs when a PR touches `Endpoints/`, `Domain/`, `Program.cs` or `http/`. The JSON
  contract isn't only in `Endpoints/`: `IsoWeekInfo` (in `Domain/`) is returned as-is by `/api/week`, and
  `Program.cs` holds the `/api` group and OpenAPI. Found by the evals (`ac-001`, drill 3), where the
  narrower filter made the check "not applicable".
- **llm-compare** (`llm-compare.yml`, not a gate): the `llm-compare` label or a manual run with a PR
  number reviews one check with both engines and posts the comparison table.
- **Who can trigger LLM reviews**: only collaborators can open PRs (`pull_request_creation_policy`),
  and workflows on fork PRs wait for approval, because every review is paid from the owner's key.
  Both are set by `just gh-setup`.
- **Trust model** ([ADR 0004](adr/0004-gate-tooling-from-base-branch.md)): `llm-review.yml` and
  `llm-compare.yml` run `tools/llm-gate`, `checks.yaml`, the prompts and the comment script from the
  **base branch's current head** (`gate/`, pinned per run; not the PR's `base.sha`, which GitHub doesn't
  move); the PR head (`src/`) is only the diff and read-only context, so a PR
  can't soften the prompt, the policy or the code that reviews it. The agent engine loads nothing from
  the reviewed repository (`setting_sources=[]`: no `CLAUDE.md`, rules, commands, skills, hooks,
  settings or MCP servers) and gets the prompt as text with the diff inline. A gate change takes
  effect for the PRs after it merges. **Remaining hole**: the workflow file itself comes from the PR
  on `pull_request`, so a PR can edit `llm-review.yml`; v2 marks such runs (`workflow_modified`,
  Phase 14) and triage rates them high (ADR 0008); a team repository would also require CODEOWNERS
  review for `tools/llm-gate/`, `.claude/` and `.github/`. Fork code never runs with the key: `pull_request`
  withholds secrets from forks, and `llm-compare` refuses PRs whose branch is not in this repository.
- **Overrides need a reason** ([ADR 0005](adr/0005-audit-trail.md)): the `llm-override` label is
  honoured only with an unedited `/llm-override <reason>` comment by whoever added the label last,
  written since the label was last removed. Comment first, then add the label, or just comment
  `/llm-override <reason>`: the feedback workflow adds the label and re-runs the review. Without one, the job warns "override not honoured" and the findings fail as usual.
- **Oversized diffs** ([ADR 0002](adr/0002-llm-gate-policy.md), amended 2026-10-18): a file whose
  own diff is over `max_file_kb` (64) is left out of the review and named in the comment, the
  audit record and the release attestation, so generated code doesn't crowd out the hand-written
  part of a change. If the rest is still over `max_diff_kb` (200), the review can't run; an
  override then accepts the diff unreviewed, and the attestation lists the PR under `unreviewed`.
  The verdict stays `error`, and the metrics count it apart from overridden findings.
- **Feedback commands** ([ADR 0007](adr/0007-feedback-commands.md)): collaborators comment
  `/llm-fp <finding-id> <reason>`, `/llm-ack <finding-id>`, `/llm-override <reason>` (adds the label
  and re-runs llm-review) or `/llm-risk <level> <reason>` (re-runs triage with that risk);
  `llm-feedback.yml` records them on
  `audit-log` and reacts 👍. Metrics over all of it: `docs/metrics.md`, `just metrics`, and the
  weekly "Gate health" issue (`metrics.yml`).
- **Audit trail** ([ADR 0005](adr/0005-audit-trail.md)): every `llm / <check>` job uploads its
  audit record (`audit-<run>-<attempt>-<check>`). `audit-collect.yml` runs on `workflow_run`
  (default-branch code, never the PR's) and validates the artifacts against the run, its jobs, the
  PR's label events and the compare API. It writes them to the `audit-log` branch
  (`events/YYYY/MM/DD/`). Anything forged or unverifiable becomes a `tamper_suspected` event. Runs
  whose PR changed `llm-review.yml` are kept as unverified, with their free text withheld. The
  `audit-log` ruleset blocks deletion and force pushes. Locally: `just audit-pull`, then `jq` over
  `.audit-log/events/`. Raw results (model output) stay a 90-day workflow artifact.

## Release gates (`release.yml`)

`just release X.Y.Z` (from a clean `main` in sync with origin, after `just ci`) pushes the signed
tag `vX.Y.Z`. The workflow then:

1. **verify**: the tag is SemVer, annotated, signed (verified by GitHub) and on `main`; it also
   finds the previous release tag.
2. **build-test**: the same build and tests as pull requests.
3. **build**: builds the amd64 + arm64 image **once** (no cache) and pushes it by digest, tagged
   only `candidate-vX.Y.Z`. Every later job uses that digest
   ([ADR 0009](adr/0009-build-once-attest-promote.md)).
4. **scan**: grype on the pushed digest, both platforms, with the same config and fail-on-high as
   pull requests.
5. **attest**: four attestations on the digest, pushed next to the image: build provenance, the
   SPDX SBOM, the **vulnerability scan** (counts per platform, ignores with their reasons) and the
   **LLM review** (every PR since the previous release with its gate verdicts on the merged head,
   plus the unreviewed and unverified ones, from `audit-log`). Each one is a permanent entry in the
   public Rekor log; that's why only releases are attested.
6. **publish**: waits for approval in the `release` environment, then gives the attested digest
   its version tags (`X.Y.Z`, `X.Y`; nothing is rebuilt), pushes the Helm chart with the digest
   pinned in `image.digest` to `oci://ghcr.io/gergodrazsdik/charts`, and drafts the GitHub Release
   with the SBOM, the chart and an "LLM review" section listing any unreviewed or unverified PRs.
7. **admission-smoke** ([ADR 0010](adr/0010-admission-control.md)): on a throwaway kind cluster,
   installs Kyverno and the policies from `deploy/policies`. It checks that the published chart is
   admitted in `calendar-gates` and runs the release digest. It checks that the `edge` image (no
   release attestations) and a foreign image are denied, each by the policy that should deny them.
   And it checks that `calendar-gates-dev` admits `edge` and reports it as a failure.
8. **smoke**: runs the digest, checks `/api/version` reports `X.Y.Z`, runs the contract tests,
   and only after that, and after `admission-smoke`, publishes the release. A failed smoke leaves
   a draft; re-running the workflow refreshes it.

A failed scan leaves only the candidate tag: no version tags, no chart, no release.

Check the supply chain afterwards with `just verify-release X.Y.Z`: it verifies all four
attestations, signed by `release.yml` for that tag, and prints the vulnerability counts and the
review gaps. Deploy it with `just k8s-deploy-release X.Y.Z`. Tags can't be moved or deleted
(`release-tags` ruleset), so a bad release is fixed with a new version.

## Admission control (the project cluster)

Kyverno 1.19.1 on `kind-calendar-gates` (`just k8s-up k8s-policy-up`,
[ADR 0010](adr/0010-admission-control.md)) enforces three policies.

| Policy | `calendar-gates` | `calendar-gates-dev` | Fails when |
|---|---|---|---|
| `calendar-gates-images` | Deny | Audit | An image isn't `ghcr.io/gergodrazsdik/calendar-gates` by digest |
| `calendar-gates-release` | Deny | Audit | There's no build provenance or vulnerability scan signed by `release.yml` on a `v*` tag, or the scan lists a critical finding |
| `calendar-gates-llm-review` | Deny | Audit | There's no LLM-review attestation signed by `release.yml` on a `v*` tag |

- **Fix a denial:** deploy a release (`just k8s-deploy-release X.Y.Z`). A local build goes to
  `calendar-gates-dev` (`just k8s-deploy calendar-gates-dev`).
- **See the findings:** `just k8s-policy-report [namespace]` lists the Audit findings.
- **Test offline:** `just lint-policies` runs the policy tests that need no registry; it's part of
  `just ci` and the `lint` job.

## Hooks are not gates

lefthook (`just setup`) formats on commit, checks commit messages and runs tests before push. It is
a convenience: `git commit --no-verify` skips it, and only the CI checks above are enforced
(gate drill 1).

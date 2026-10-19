# Gates

Every gate runs locally through `just` and in CI as a named check. `just ci` runs the deterministic
ones that need no container or cluster (`pr-title`, `format`, `lint`, `build-test`); `http-tests`,
`grype` and `k8s-smoke` have their own recipes. Required checks on `main` are set in the ruleset
`.github/rulesets/main.json` (applied with `just gh-rulesets`): `pr-title`, `format`, `lint`,
`build-test / dotnet`, `http-tests`, `grype`, `k8s-smoke`, `gates`, `llm / code-review`,
`llm / security-review` and `llm-eval` (required on its own, not part of `gates`:
[ADR 0006](adr/0006-llm-eval-gate.md)). The advisory `llm / <check>` jobs report but don't
block. `lint` fails if the ruleset, the workflow job names and the blocking
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
| `lint` | `just lint lint-chart lint-policies` | actionlint, zizmor, hadolint, yamllint, shellcheck, ruff, mypy, the llm-gate tests, the ruleset consistency check, the Kyverno policy tests (`kyverno test`), `helm lint` or kubeconform report a finding | Fix the finding; suppress only inline with a reason (`# zizmor: ignore[...]`, `# shellcheck disable=...`, `# noqa`) | Repo-wide rule changes in `.github/zizmor.yml`, `.yamllint.yaml` |
| `build-test / dotnet` | `just build test` | Build warning (warnings are errors) or a failing test | The **test results** check run lists failures with file/line; coverage is in the job summary | none |
| `image` | `just image` | Docker build fails | Build output in the job log | none |
| `http-tests` | `just image http-docker` | An `http/calendar.http` handler assertion fails against the built container | The **http test results** check run names the request; container logs are printed on failure | none |
| `grype` | `just image scan` | A **high** or **critical** vulnerability in the image | Update the package or base image (Dependabot `docker`/`nuget`) | `ignore:` entry in `.grype.yaml` with a reason and an expiry date, called out in the PR |
| `k8s-smoke` | `just k8s-up k8s-policy-up` once, then `just k8s-load`, `just k8s-deploy calendar-gates-dev`, `just k8s-http calendar-gates-dev` (or `just cluster=local k8s-load k8s-deploy k8s-http`) | The chart does not install on a fresh kind cluster, a pod never becomes ready, or a `.http` test fails through the port-forward | The job summary lists pods, recent events (probe failures, image errors) and pod logs | none |
| `llm / <check>` (`llm-review.yml`) | `just llm <check>` | A **blocking** check (`code-review`: high, `security-review`: medium) has a finding at or above its threshold, or fails closed on an error | Fix the finding, or argue it in the PR. A diff over `max_diff_kb` is a different fix: split the PR, or override it (next column) | Comment `/llm-override <reason>`: the feedback workflow adds the `llm-override` label and re-runs the review. Or add the label yourself **plus** that comment. Either way the findings are still reported and the override is recorded; thresholds in `tools/llm-gate/checks.yaml`. An override also accepts a diff over `max_diff_kb` **unreviewed** ([ADR 0002](adr/0002-llm-gate-policy.md)); an API error, refusal or crash is never overridable, so re-run it |
| `llm-eval` (`llm-eval.yml`) | `just eval` | The PR changes a review prompt or `tools/llm-gate/` and scores worse than `evals/baseline.json` beyond `evals/thresholds.yaml` (recall, false blocks, flips, cost), or a `forbid` rule of an fp-regression case matches again (`fp_regressions`, which updating the baseline cannot clear), or **a check's engine/model has no baseline entry** (change one and the entry comes with it), or the eval doesn't finish within its budget | Fix the prompt or code; or, if the new scores are the intended trade-off, update the baseline in the same PR (`just eval-baseline`) and say why | `evals/thresholds.yaml` (changing it weakens the gate: say so) |
| `gates` | n/a | Any gate it needs did not succeed (failed, cancelled or skipped) | Fix that gate | none |

## What the agent's permissions do and don't buy you

`.claude/settings.json` pre-approves `just`, `dotnet`, `uv run` and read-only `gh run` commands and
denies a handful (`git push --force`, `gh secret`, `gh api -X DELETE`). Worth being precise about
what that means (F045): the allow rules are **convenience, not a boundary**. `just`, `dotnet` and
`uv run` run arbitrary project code by design — `just release` pushes a tag, `uv run python -c …`
runs anything — so the deny list can always be reached another way, and a longer deny list would be
security theatre. What actually bounds the agent here is the Claude Code sandbox
(`.claude/settings.local.json`: read-only home, no network except the allowlisted registries) and
the machine's `claude-bash-guard` hook, which asks before sudo, secrets, GitHub writes and
destructive recipes whatever the project's settings say. The deny rules stay as a tripwire for the
obvious, and `gh run` is narrowed to its read-only subcommands because `gh run delete|cancel|rerun`
changes CI state for no convenience gain.

## Notes per gate

- **format**: CSharpier owns layout, `dotnet format` only checks rules ([ADR 0001](adr/0001-csharpier-owns-formatting.md)).
  `dotnet format whitespace` is never run.
- **llm / <check>**: blocking reviews are not cached ([ADR 0002](adr/0002-llm-gate-policy.md)), so
  a re-run of an unchanged PR pays for them again, about $0.12 at high risk. A cache a PR can write
  is not evidence. The triage model's answer is still cached.
- **llm-eval**: with no API key (a fork PR, or a Dependabot PR before the secret is granted) the
  job passes with a notice and runs nothing: `LLM_GATE_MISSING_KEY` applies to `llm / <check>`,
  not to `llm-eval`. A Dependabot bump of `tools/llm-gate`'s dependencies therefore merges without
  an eval run.
- **uv itself is pinned** in `uv.toml` (`required-version`), which `setup-uv` reads in every
  workflow: the attest job signs with an OIDC token and the collector and feedback jobs hold write
  tokens, so "whatever uv was released last, with no cooldown" was the one unpinned tool in the
  trusted path (F052). Bumping it is a deliberate PR, like the linters below. A local `uv` of
  another version fails loudly rather than drifting.
- **lint**: the tools fetched on demand are pinned in both `ci.yml` and the `lint` recipe
  (`uvx yamllint@...`, `zizmor@...`, `ruff@...`, `actionlint@...`); bump them together. The ones
  that come from the image or the system (hadolint, shellcheck, helm, kubeconform, kyverno) follow
  the runner and `just setup`.
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
  In CI each check is a job in `llm-review.yml` (a matrix spelled out in the workflow, kept equal to
  `checks.yaml` by `check-ruleset-consistency.py`: a matrix built from a job's output can't expand
  until that job finishes, and a run cancelled before that leaves a phantom
  `llm / ${{ matrix.check }}` check behind) that writes the
  review to the job summary and one sticky PR comment per check (updated on every run; "not
  applicable" only updates an existing one). PRs without the API key (forks, Dependabot) skip with a
  notice; set the repo variable `LLM_GATE_MISSING_KEY=fail` to make blocking checks fail closed
  instead (gate drill 9). Adding or removing a label re-runs only these checks, from the cache.
- **Triage** ([ADR 0008](adr/0008-risk-triage.md)): the `triage` job (first in `llm-review.yml`)
  rates the PR `low`, `medium` or `high`.
  - **Rules:** the paths in `checks.yaml` `triage.rules` (`.github/`, the gate, deployment and the
    deterministic gates' own configuration — `.grype.yaml`, `justfile`, `lefthook.yml`,
    `.editorconfig`, `global.json`, `.config/` and friends — are high), raised by size and by AI
    markers (commit trailers, the PR body).
  - **Model:** a cheap model may raise the rating, never lower it.
  - **Labels:** triage sets `risk:<level>` and `ai-assisted`. A hand-set `risk:*` label is put back.
    To change the risk, comment `/llm-risk <level> <reason>`.

  The level decides which checks review and which block. At `low`, only code-review and docs-drift
  review, and both are advisory. At `high`, the blocking checks use the agent engine, with their usual
  model. A check the level doesn't need still reports success with "not needed at risk: <level>",
  so required checks never go missing (and that record says `blocking: false`, because it blocked
  nothing). The job summary shows why the PR got its level.
- **api-contract** runs when a PR touches `Endpoints/`, `Domain/`, `Program.cs`, the API's `.csproj`
  or `appsettings*.json`, `Directory.Build.props`, `Directory.Packages.props` or `http/` — all of
  which can change the contract (F023) — and it runs at every risk level, including `low`, where an
  `http/`-only PR lands (F024). The JSON
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
  settings or MCP servers) and gets the prompt as text with the diff inline. Since 2026-10-18 it may
  also only *read* the reviewed checkout: its own process holds the API key, so the file tools are
  fenced to `src/` (the CLI's `blockReadsOutsideWorkingDirectories` plus a path-scoped `Read(./**)`
  rule, with an in-process hook as a backstop), and a refused read is counted in the record and
  named in the PR comment (F003). Everything the model writes is redacted and stripped of link,
  image and tag markup before it is published, as the audit log's text already was (F029). A gate
  change takes effect for the PRs after it merges. **Remaining hole**: the workflow file itself comes from the PR
  on `pull_request`, so a PR can edit `llm-review.yml`; v2 marks such runs (`workflow_modified`,
  Phase 14) and triage rates them high (ADR 0008); a team repository would also require CODEOWNERS
  review for `tools/llm-gate/`, `.claude/` and `.github/`. Fork code never runs with the key: `pull_request`
  withholds secrets from forks, and `llm-compare` refuses PRs whose branch is not in this repository.
- **A command during a running review** ([ADR 0008](adr/0008-risk-triage.md)): `/llm-risk` and
  `/llm-override` only reach a review that starts after them, because triage reads `/llm-risk`
  when the run starts and each check reads the labels before reviewing. The feedback workflow
  therefore waits up to 7 minutes for a run in flight and then re-runs it; if it is still going,
  it says so in a PR comment and the command applies to the next run.
- **Overrides need a reason and write access** ([ADR 0005](adr/0005-audit-trail.md)): the
  `llm-override` label is honoured only with an unedited `/llm-override <reason>` comment by
  whoever added the label last, written since the label was last removed, **and only when that
  person has write, maintain or admin access** — applying a label needs just the triage role, so
  the label on its own says nothing (F007). Comment first, then add the label, or just comment
  `/llm-override <reason>`: the feedback workflow adds the label and re-runs the review. Without
  one, the job warns "override not honoured" and the findings fail as usual.
- **Oversized diffs** ([ADR 0002](adr/0002-llm-gate-policy.md), amended 2026-10-18): a generated
  file (on `trimmable_paths` in `checks.yaml` **and** carrying a generator's marker such as
  `<auto-generated`) whose own diff is over `max_file_kb` (64) is left out
  of the review and named in the comment, the audit record and the release attestation, so
  generated code doesn't crowd out the hand-written part of a change. Any other file stays under
  review whatever its size, and a **blocking** check reviews a diff with anything missing only
  with an honoured `/llm-override` — so `code-review` and `security-review` never skip a file
  silently. If the rest is still over `max_diff_kb` (200), the review can't run; an
  override then accepts the diff unreviewed, and the attestation lists the PR under `unreviewed`.
  The verdict stays `error`, and the metrics count it apart from overridden findings.
- **Feedback commands** ([ADR 0007](adr/0007-feedback-commands.md)): collaborators comment
  `/llm-fp <finding-id> <reason>`, `/llm-ack <finding-id>`, `/llm-override <reason>` (adds the label
  and re-runs llm-review) or `/llm-risk <level> <reason>` (re-runs triage with that risk);
  `llm-feedback.yml` records them on
  `audit-log` and reacts 👍. A `/llm-fp` or `/llm-ack` for a run the collector hasn't written yet
  gets 👀 and a "try again in a minute" comment instead of a permanent rejection (F026). Metrics
  over all of it: `docs/metrics.md`, `just metrics`, and the weekly "Gate health" issue
  (`metrics.yml`).
- **Audit trail** ([ADR 0005](adr/0005-audit-trail.md)): every `llm / <check>` job uploads its
  audit record (`audit-<run>-<attempt>-<check>`). `audit-collect.yml` runs on `workflow_run`
  (default-branch code, never the PR's) and validates the artifacts against the run, its jobs, the
  PR's label events and the compare API — recomputing its triage from the `checks.yaml` that run
  used, read at its own `gate_sha` once that commit is proved to be on the trunk (F022). It writes
  them to the `audit-log` branch
  (`events/YYYY/MM/DD/`). Anything forged or unverifiable becomes a `tamper_suspected` event. Runs
  whose PR changed any workflow, the composite action or `.gitattributes` are kept as unverified,
  with their free text withheld. The
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
6. **approve**: waits for approval in the `release` environment and then does one thing — attests
   the approval on the digest (`release-approved/v1`), which is what admission requires and what
   lets the next two jobs run. Nothing public is created here (amended 2026-10-18, F071).
7. **admission-smoke** ([ADR 0010](adr/0010-admission-control.md)): on a throwaway kind cluster,
   installs Kyverno and the policies from `deploy/policies`. It packages the chart with the digest
   pinned in `image.digest`, installs **that tarball** in `calendar-gates` and checks the pods run
   the release digest. It checks that the `edge` image (no release attestations) and a foreign
   image are denied, each by the policy that should deny them. And it checks that
   `calendar-gates-dev` admits `edge` and reports it as a failure. The tarball it installed is
   handed to `promote` as an artifact, so the chart that is published is the one that was tested.
8. **smoke**: runs the digest, checks `/api/version` reports `X.Y.Z` and runs the contract tests.
   Runs beside `admission-smoke`; neither needs anything public to exist.
9. **promote**: only after both pass, and everything public happens here — the version tags
   (`X.Y.Z`, `X.Y`; nothing is rebuilt), the chart to `oci://ghcr.io/gergodrazsdik/charts`, and the
   GitHub Release with the SBOM, the chart and an "LLM review" section listing any unreviewed or
   unverified PRs. There is no second approval pause: `promote` has no environment of its own and
   can only run because `approve` passed.

   **A failed smoke or admission test now leaves nothing public**, so re-running the whole workflow
   is safe: it builds new bytes, re-attests and promotes those. Once `promote` has pushed `X.Y.Z`
   the version is taken, and a failed `promote` is fixed by re-running **that job**
   ([ADR 0009](adr/0009-build-once-attest-promote.md)) — a full re-run would build new bytes that
   `promote` then refuses to put under the existing version.

A failed scan, smoke or admission test leaves only the candidate tag: no version tags, no chart,
no release.

Check the supply chain afterwards with `just verify-release X.Y.Z`. It runs from `main`, so a
tagged commit can't weaken it: the tag must be annotated with a signature GitHub verifies, its
commit must be an **ancestor of `main`**, and all five attestations (provenance, SBOM, vuln-scan,
llm-review, release-approved) must be signed by `release.yml` for that tag **and that commit**
(`--source-digest`). Releases before v0.3.2 have no `release-approved` attestation, so it fails on
that type for them. It then prints the
vulnerability counts and the review gaps. Run it before trusting a release you didn't make
yourself ([ADR 0009](adr/0009-build-once-attest-promote.md)). Deploy it with `just k8s-deploy-release X.Y.Z`. Tags can't be moved or deleted
(`release-tags` ruleset), so a bad release is fixed with a new version.

## Admission control (the project cluster)

Kyverno 1.19.1 on `kind-calendar-gates` (`just k8s-up k8s-policy-up`,
[ADR 0010](adr/0010-admission-control.md)) enforces three policies.

| Policy | `calendar-gates` | `calendar-gates-dev` | Fails when |
|---|---|---|---|
| `calendar-gates-images` | Deny | Audit | An image isn't `ghcr.io/gergodrazsdik/calendar-gates` by digest |
| `calendar-gates-release` | Deny | Audit | There's no build provenance or vulnerability scan signed by `release.yml` on a `v*` tag, or the scan lists a critical finding |
| `calendar-gates-llm-review` | Deny | Audit | There's no LLM-review attestation signed by `release.yml` on a `v*` tag |
| `calendar-gates-approved` | Deny | Audit | There's no `release-approved` attestation: the image was never approved in the `release` environment, or it's a rejected candidate. Deny since v0.3.2, the first release that carries one |
| (any policy) | Deny | Audit | The pod has an **image volume**: nothing can attestation-verify one, so they aren't allowed in `calendar-gates` |

- **Fix a denial:** deploy a release **from v0.3.2 on** (`just k8s-deploy-release X.Y.Z`). v0.3.0
  and v0.3.1 have no approval attestation and are refused here; deploy those in
  `calendar-gates-dev`, which audits. A local build goes there too
  (`just k8s-deploy calendar-gates-dev`).
- **See the findings:** `just k8s-policy-report [namespace]` lists the Audit findings.
- **Test offline:** `just lint-policies` runs the policy tests that need no registry; it's part of
  `just ci` and the `lint` job.

## Hooks are not gates

lefthook (`just setup`) formats on commit, checks commit messages and runs tests before push. It is
a convenience: `git commit --no-verify` skips it, and only the CI checks above are enforced
(gate drill 1).

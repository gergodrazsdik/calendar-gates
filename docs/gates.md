# Gates

Every gate runs locally through `just` and in CI as a named check. `just ci` runs the
deterministic ones (format, lint, build, test). Required checks on `main` are set in the ruleset
(Phase 9); until then they show on every PR but don't block merging.

The check names are the job names in `.github/workflows/ci.yml`. Renaming a job silently breaks
branch protection until the ruleset is updated, and a required check that is **skipped counts as
passing** (see `gates` below).

| Check | Local | Fails when | Fix | Override |
|---|---|---|---|---|
| `pr-title` | `scripts/check-commit-msg.sh --title "<title>"` | PR title is not a Conventional Commit (it becomes the squash commit) | Edit the title, then push (title edits alone don't re-run CI) | none |
| `format` | `just fmt-check` | CSharpier would change layout, or a code-style/analyzer rule fires | `just fmt`; for rule findings fix the code (the message names the rule) | none; rules live in `.editorconfig` and are changed in their own PR |
| `lint` | `just lint` | actionlint, zizmor, hadolint, yamllint, shellcheck or ruff report a finding | Fix the finding; suppress only inline with a reason (`# zizmor: ignore[...]`, `# shellcheck disable=...`, `# noqa`) | Repo-wide rule changes in `.github/zizmor.yml`, `.yamllint.yaml` |
| `build-test / dotnet` | `just build test` | Build warning (warnings are errors) or a failing test | The **test results** check run lists failures with file/line; coverage is in the job summary | none |
| `image` | `just image` | Docker build fails | Build output in the job log | none |
| `http-tests` | `just image http-docker` | An `http/calendar.http` handler assertion fails against the built container | The **http test results** check run names the request; container logs are printed on failure | none |
| `grype` | `just image scan` | A **high** or **critical** vulnerability in the image | Update the package or base image (Dependabot `docker`/`nuget`) | `ignore:` entry in `.grype.yaml` with a reason and an expiry date, called out in the PR |
| `llm / <check>` (`llm-review.yml`) | `just llm <check>` | A **blocking** check (`code-review`: high, `security-review`: medium) has a finding at or above its threshold, or fails closed on an error | Fix the finding, or argue it in the PR | Label `llm-override` (findings still reported); thresholds in `tools/llm-gate/checks.yaml` |
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
- **publish-edge** (push to `main` only, not a gate) pushes the tested image as
  `ghcr.io/gergodrazsdik/calendar-gates:edge` and `:sha-<short>`.
- **gates** is red unless every gate it needs **succeeded**: failed, cancelled and *skipped* all
  count against it (only `pr-title` may be skipped, on pushes to `main`). That differs from the
  ruleset, where a skipped required check counts as passing. Gate drill 8 compares requiring each
  check with requiring only `gates`.

- **llm / <check>**: the model returns findings; llm-gate decides from their severities
  ([ADR 0002](adr/0002-llm-gate-policy.md)). Advisory checks never fail. Results are cached per
  check, engine, model, prompt and diff, so re-runs without changes are free.
  In CI each check is a job in `llm-review.yml` (matrix from `llm-gate list --json`) that writes the
  review to the job summary and one sticky PR comment per check (updated on every run; "not
  applicable" only updates an existing one). PRs without the API key (forks, Dependabot) skip with a
  notice; set the repo variable `LLM_GATE_MISSING_KEY=fail` to make blocking checks fail closed
  instead (gate drill 9). Adding or removing a label re-runs only these checks, from the cache.
- **llm-compare** (`llm-compare.yml`, not a gate): the `llm-compare` label or a manual run with a PR
  number reviews one check with both engines and posts the comparison table.
- **Who can trigger LLM reviews**: only collaborators can open PRs (`pull_request_creation_policy`),
  and workflows on fork PRs wait for approval, because every review is paid from the owner's key.
  Both are set by `just gh-setup`.

## Hooks are not gates

lefthook (`just setup`) formats on commit, checks commit messages and runs tests before push. It is
a convenience: `git commit --no-verify` skips it, and only the CI checks above are enforced
(gate drill 1).

# calendar-gates

A learning playground for **GitHub Actions CI with merge gates**. The ASP.NET Core minimal API
about dates is deliberately small; the gates are the product. Not production software.

The full plan, phase by phase, is in `docs/PLAN.md`. Check which phase is in progress before
adding things from later phases.

## Layout

| Path | What |
|---|---|
| `src/CalendarGates.Api/` | Minimal API: `Program.cs`, `Endpoints/` (one static class per feature), `Domain/` (pure calculators) |
| `tests/CalendarGates.UnitTests/`, `tests/CalendarGates.IntegrationTests/` | TUnit tests (calculators; API via `TUnit.AspNetCore`) |
| `http/` | `.http` contract tests run by `ijhttp` (`http-client.env.json`; the private env file is gitignored) |
| `Dockerfile`, `deploy/helm/calendar-gates/` | Container image and Helm chart (kind-local, CI smoke) |
| `tools/llm-gate/` | Python (uv) LLM review gate on the Claude SDKs; policy in `checks.yaml` |
| `.claude/commands/` | Review prompts, shared by interactive Claude Code and the CI LLM gate |
| `.github/` | Workflows, composite action, rulesets (as JSON), Dependabot |
| `audit-log` branch | Audit records of the LLM gate, written only by `audit-collect.yml` (ADR 0005) |
| `docs/` | `PLAN.md`, `gates.md`, `adr/` |

## Commands

Use `just`; `just` with no arguments lists the recipes. `just ci` runs the local equivalent of
every deterministic gate: run it before calling a change done. Recipes arrive with the phase
that needs them, so the list is the truth, not this file.

- .NET SDK is pinned in `global.json` (10.0.x). `dotnet test` runs on Microsoft.Testing.Platform.
- Local tools: `dotnet tool restore` (CSharpier, MinVer CLI from `.config/dotnet-tools.json`).
- Python: `uv run ...` inside `tools/llm-gate/`, never pip.
- Containers: `docker` is podman locally; containers publish on host port **8081** (kind-local owns 8080).
- Kubernetes: always `--context kind-local` / `--kube-context kind-local`.

## Conventions

- **CSharpier owns C# layout.** Never hand-format, never run `dotnet format whitespace`.
  `dotnet format style` / `analyzers` only check rules. `.editorconfig` must not fight CSharpier.
- Warnings are errors (`Directory.Build.props`). Fix the cause; suppress only with a reason.
- Time comes from the injected `TimeProvider`, never `DateTime.Now`/`UtcNow`. "Today" is the UTC date.
- Every endpoint gets a unit test (calculator), an integration test and a request in `http/calendar.http`.
- Package versions live in `Directory.Packages.props` (central package management); lock files are committed.
- Build output goes to `artifacts/` (`UseArtifactsOutput` in `Directory.Build.props`):
  `artifacts/bin/<Project>/<config>/`, `artifacts/obj/...`, `artifacts/publish/...`. There are no
  per-project `bin/`/`obj/` folders; point scripts, Dockerfiles and CI at `artifacts/`, never at
  `src/*/bin`.
- Conventional Commits for commit messages and PR titles (`feat:`, `fix:`, `ci:`, `chore:`, `docs:`, `test:`, `refactor:`).
- AI-assisted commits say so in a trailer: Claude Code adds `Co-Authored-By: Claude …` and
  `Claude-Session:`; other agents add `Assisted-by: <tool>`. Triage reads these (and
  "Generated with [Claude Code]" in a PR body) to raise the PR's risk by one level
  ([ADR 0008](docs/adr/0008-risk-triage.md)). Never leave them out to get a lighter review.
- From Phase 6 on, every change goes through a PR (squash merge, the PR title becomes the commit).

## Gates

Details, fixes and overrides: `docs/gates.md`.

1. `pr-title`: Conventional Commit PR title.
2. `format`: CSharpier check + `dotnet format style/analyzers --verify-no-changes`.
3. `lint`: actionlint, zizmor, hadolint, yamllint, shellcheck, ruff, mypy, pytest, helm lint + kubeconform.
4. `build-test / dotnet`: build + unit + integration tests.
5. `http-tests`: ijhttp against the built container.
6. `grype`: image vulnerability scan, fails on high.
7. `llm / <check>`: LLM review (`tools/llm-gate`, prompts in `.claude/commands/llm-*.md`, both run
   from the base branch's current head, [ADR 0004](docs/adr/0004-gate-tooling-from-base-branch.md)); blocking
   checks fail on severity, advisory ones only comment ([ADR 0002](docs/adr/0002-llm-gate-policy.md)).
   Locally: `just llm <check>` (spends API credits). PR labels: `llm-override` (report blocking
   findings without failing; needs a `/llm-override <reason>` comment by whoever adds it),
   `llm-compare` (both engines, comparison comment). Every decision is an audit record on the
   `audit-log` branch ([ADR 0005](docs/adr/0005-audit-trail.md); `just audit-pull`). PR comment
   commands `/llm-fp`, `/llm-ack`, `/llm-override`, `/llm-risk` feed the metrics
   ([ADR 0007](docs/adr/0007-feedback-commands.md), `docs/metrics.md`, `just metrics`). First the
   `triage` job rates the PR low, medium or high ([ADR 0008](docs/adr/0008-risk-triage.md)). The
   rating comes from path and size rules and AI markers; a cheap model may only raise it, and
   `/llm-risk <level> <reason>` changes it. The level decides which checks review and block, and
   triage sets the `risk:*` and `ai-assisted` labels.
8. `llm-eval`: on PRs that change the review prompts or `tools/llm-gate/`, scores **the PR's** prompts on
   `tools/llm-gate/evals/cases` against `evals/baseline.json` ([ADR 0006](docs/adr/0006-llm-eval-gate.md)).
   Locally: `just eval` (spends API credits; a PR pays only for the checks it changes),
   `just eval-baseline` to update the baseline in a PR. Required, on its own (not part of `gates`).
9. `k8s-smoke`: Helm install on a throwaway kind cluster + ijhttp. Locally on kind-local:
   `just k8s-load k8s-deploy k8s-http` (port-forward, [ADR 0003](docs/adr/0003-kind-access.md)).
10. `gates`: aggregator over the `ci.yml` gates.

## Don'ts

- No `--no-verify`, gate drills included: a drill that must get past a local hook commits through
  the GitHub API instead (`scripts/commit-via-api.py`, see `/gate-drill`).
- No secrets in files. The Anthropic key comes from `pass show api/anthropic-calendar-gates` at run time.
- Never edit pinned action SHAs by hand; `pinact` and Dependabot maintain them.
- Never weaken a gate (skip, `continue-on-error`, lower a threshold, add an ignore) to get CI green
  without saying so explicitly in the PR.
- No `pull_request_target` workflows.

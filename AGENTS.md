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
- From Phase 6 on, every change goes through a PR (squash merge, the PR title becomes the commit).

## Gates

Details, fixes and overrides: `docs/gates.md`.

1. `pr-title`: Conventional Commit PR title.
2. `format`: CSharpier check + `dotnet format style/analyzers --verify-no-changes`.
3. `lint`: actionlint, zizmor, hadolint, yamllint, shellcheck, ruff, mypy, pytest, helm lint + kubeconform.
4. `build-test / dotnet`: build + unit + integration tests.
5. `http-tests`: ijhttp against the built container.
6. `grype`: image vulnerability scan, fails on high.
7. `llm / <check>`: LLM review (`tools/llm-gate`, prompts in `.claude/commands/llm-*.md`); blocking
   checks fail on severity, advisory ones only comment ([ADR 0002](docs/adr/0002-llm-gate-policy.md)).
   Locally: `just llm <check>` (spends API credits). PR labels: `llm-override` (report blocking
   findings without failing), `llm-compare` (both engines, comparison comment).
8. `k8s-smoke`: Helm install on a throwaway kind cluster + ijhttp. Locally on kind-local:
   `just k8s-load k8s-deploy k8s-http` (port-forward, [ADR 0003](docs/adr/0003-kind-access.md)).
9. `gates`: aggregator over all of the above.

## Don'ts

- No `--no-verify`, except inside a gate drill (Phase 12) that asks for it.
- No secrets in files. The Anthropic key comes from `pass show api/anthropic-calendar-gates` at run time.
- Never edit pinned action SHAs by hand; `pinact` and Dependabot maintain them.
- Never weaken a gate (skip, `continue-on-error`, lower a threshold, add an ignore) to get CI green
  without saying so explicitly in the PR.
- No `pull_request_target` workflows.

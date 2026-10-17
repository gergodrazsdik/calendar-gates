# calendar-gates

A GitHub Actions playground: a tiny ASP.NET Core API about dates (ISO weeks, Friday the 13th,
Easter, workdays, leap years) wrapped in merge gates for formatting, linting, tests, HTTP contract
tests, vulnerability scanning, a Kubernetes smoke test and an LLM reviewer built on the Claude
SDKs, plus a release pipeline with a human approval gate.

It's a learning project, not production software. Start with [`docs/WRITEUP.md`](docs/WRITEUP.md): a
ten-minute read on what the gates do, what's measured, and what isn't. [`docs/PLAN.md`](docs/PLAN.md) is the plan,
[`docs/gates.md`](docs/gates.md) says what each gate checks and how to fix or override it, and
[`docs/adr/`](docs/adr) records the decisions.

## Quick start

```bash
just setup   # restore local tools and install the git hooks
just ci      # the deterministic gates locally: format, lint, chart lint, build, tests
just         # list every recipe
```

Requires the .NET 10 SDK (pinned in `global.json`), [just](https://just.systems) and
[uv](https://docs.astral.sh/uv/); the container, Kubernetes and LLM recipes also need podman,
kind/helm and an Anthropic API key in `pass` (`api/anthropic-calendar-gates`).

## Recipes

| Group | Recipes |
|---|---|
| dev | `setup`, `build`, `run` (API on http://localhost:5080, OpenAPI at `/openapi/v1.json`) |
| test | `test`, `http [env]` (`.http` contract tests), `ci` |
| format | `fmt`, `fmt-check`, `lint`, `lint-chart` |
| container | `image`, `http-docker` (container on port 8081 + contract tests), `scan` (grype), `sbom` |
| k8s | `k8s-up`, `k8s-load`, `k8s-deploy`, `k8s-http`, `k8s-status`, `k8s-logs`, `k8s-down`, `k8s-deploy-release <version>` (kind-local) |
| llm | `llm <check> [engine]`, `llm-compare <check>`, `llm-list` (cost API credits) |
| release | `release <version>`: signed tag from an up-to-date `main` |
| github | `gh-setup`, `gh-rulesets`, `gh-codeql` (repository settings as code) |

## How changes and releases flow

1. Every change is a PR to `main` (squash merge, the PR title becomes the commit). The ruleset
   requires `pr-title`, `format`, `lint`, `build-test / dotnet`, `http-tests`, `grype`,
   `k8s-smoke`, `gates`, `llm / code-review` and `llm / security-review`; advisory LLM checks
   comment without blocking. The `llm-override` label passes blocking LLM findings (still
   reported), and `llm-compare` runs both LLM engines on a PR.
2. A push to `main` publishes `ghcr.io/gergodrazsdik/calendar-gates:edge`.
3. `just release X.Y.Z` pushes a signed tag; `release.yml` verifies it, re-runs the gates, waits
   for approval in the `release` environment, publishes the multi-arch image and the Helm chart
   with an SBOM and a provenance attestation, smoke-tests the published image and then publishes
   the GitHub Release.

## License

[MIT](LICENSE)

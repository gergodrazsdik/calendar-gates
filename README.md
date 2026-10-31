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
just ci      # the deterministic gates locally: format, lint, chart lint, policy tests, build, tests
just         # list every recipe
```

Requires the .NET 10 SDK (pinned in `global.json`), [just](https://just.systems) and
[uv](https://docs.astral.sh/uv/). `just lint`, which `just ci` runs, also needs `shellcheck`,
`hadolint`, `helm`, `kubeconform` and the `kyverno` CLI on `PATH` (the other linters are fetched
by `uvx`, pinned). The container, Kubernetes and LLM recipes need podman, kind/helm and an
Anthropic API key in `pass` (`api/anthropic-calendar-gates`).

## Recipes

| Group | Recipes |
|---|---|
| dev | `setup`, `build`, `run` (API on http://localhost:5080, OpenAPI at `/openapi/v1.json`) |
| test | `test`, `http [env]` (`.http` contract tests), `ci` |
| format | `fmt`, `fmt-check`, `lint`, `lint-chart`, `lint-policies` (Kyverno policy tests) |
| container | `image`, `http-docker` (container on port 8081 + contract tests), `scan` (grype), `sbom` |
| k8s | `k8s-up`, `k8s-policy-up` (Kyverno and the admission policies), `k8s-load`, `k8s-deploy [ns]`, `k8s-deploy-release <version>`, `k8s-http`, `k8s-status`, `k8s-logs`, `k8s-policy-report [ns]`, `k8s-down`, `k8s-cluster-down`. They target the project's cluster `kind-calendar-gates`; `just cluster=local …` targets kind-local ([ADR 0010](docs/adr/0010-admission-control.md)) |
| llm | `llm <check> [engine]`, `llm-compare <check>`, `llm-list`, `eval`, `eval-baseline` (these cost API credits), `audit-pull`, `metrics [days]` |
| release | `release <version>`: signed tag from an up-to-date `main`; `verify-release <version>`: its four attestations |
| github | `gh-setup`, `gh-rulesets` (repository settings as code) |

## How changes and releases flow

1. Every change is a PR to `main` (squash merge, the PR title becomes the commit). The ruleset
   requires `pr-title`, `format`, `lint`, `build-test / dotnet`, `http-tests`, `grype`,
   `k8s-smoke`, `gates`, `llm / code-review`, `llm / security-review` and `llm-eval`. Triage
   decides how much LLM review a PR gets ([ADR 0008](docs/adr/0008-risk-triage.md)). Advisory
   LLM checks comment without blocking. A `/llm-override <reason>` comment (it adds the `llm-override`
   label) passes blocking LLM findings (still reported and recorded), and the `llm-compare` label runs both LLM engines on a PR.
2. A push to `main` publishes `ghcr.io/gergodrazsdik/calendar-gates:edge`.
3. `just release X.Y.Z` pushes a signed tag. `release.yml` verifies it and re-runs the tests, then
   builds the multi-arch image once, by digest. It scans that digest and attests provenance, SBOM,
   the vulnerability scan and the LLM review on it. It waits for approval in the `release`
   environment, then promotes the digest to `X.Y.Z` and pushes a chart pinned to it. Kyverno
   admission control must admit it and deny unattested images (`admission-smoke`). Only then are
   the image smoke-tested and the GitHub Release published
   ([ADR 0009](docs/adr/0009-build-once-attest-promote.md)).

## License

[MIT](LICENSE)

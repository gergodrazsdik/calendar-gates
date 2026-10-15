# calendar-gates: the single entry point, locally and in CI. `just` lists the recipes.

repo := "gergodrazsdik/calendar-gates"
image := "localhost/calendar-gates:dev"

# List recipes
default:
    @just --list

# Restore local .NET tools and install the git hooks (lefthook.yml)
[group('dev')]
setup:
    dotnet tool restore
    lefthook install

# Format C# (CSharpier owns layout, docs/adr/0001)
[group('format')]
fmt:
    dotnet csharpier format .

# The `format` gate: CSharpier layout check plus code-style and analyzer rules (never `whitespace`)
[group('format')]
fmt-check:
    dotnet csharpier check .
    dotnet format style --verify-no-changes
    dotnet format analyzers --verify-no-changes

# Build the container image localhost/calendar-gates:dev (version from MinVer, commit from git)
[group('container')]
image:
    docker build -t {{ image }} \
        --build-arg VERSION="$(dotnet minver -t v -v e)" \
        --build-arg COMMIT="$(git rev-parse --short HEAD)" .

# Run the image on host port 8081 (kind-local owns 8080) and run the HTTP contract tests against it
[group('container')]
http-docker:
    #!/usr/bin/env bash
    set -euo pipefail
    docker run -d --rm --name calendar-gates-http -p 8081:8080 {{ image }} >/dev/null
    trap 'docker stop calendar-gates-http >/dev/null' EXIT
    if ! scripts/wait-for-health.sh http://localhost:8081/health 60; then
        docker logs calendar-gates-http >&2
        exit 1
    fi
    just http docker

# Vulnerability gate: grype on the image, fails on high or worse (.grype.yaml)
[group('container')]
scan:
    grype podman:{{ image }} --config .grype.yaml

# SPDX SBOM of the image into reports/
[group('container')]
sbom:
    mkdir -p reports
    syft podman:{{ image }} -o spdx-json=reports/sbom.spdx.json

# The `lint` gate: workflows, Dockerfile, YAML, shell and Python (CI pins the same tools)
[group('format')]
lint:
    actionlint
    # SSL_CERT_DIR here lists two dirs (the .NET dev cert); zizmor's TLS stack only reads one
    GH_TOKEN="$(gh auth token)" env -u SSL_CERT_DIR uvx zizmor@1.30.1 .github/
    hadolint Dockerfile
    uvx yamllint@1.38.0 --strict .
    shellcheck scripts/*.sh .claude/hooks/*.sh
    uvx ruff@0.16.10 check scripts/
    uvx ruff@0.16.10 format --check scripts/
    uv run --directory tools/llm-gate --locked ruff check .
    uv run --directory tools/llm-gate --locked ruff format --check .
    uv run --directory tools/llm-gate --locked mypy
    uv run --directory tools/llm-gate --locked pytest -q

# List the LLM checks (tools/llm-gate/checks.yaml)
[group('llm')]
llm-list:
    uv run --project tools/llm-gate llm-gate list

# Run an LLM check on this branch vs origin/main; engine api, agent or both (default: the check's own). Costs API credits.
[group('llm')]
llm check engine="":
    #!/usr/bin/env bash
    set -euo pipefail
    # The key comes from pass for this one command, never from a file.
    ANTHROPIC_API_KEY="$(pass show api/anthropic-calendar-gates | head -n 1)"
    export ANTHROPIC_API_KEY
    uv run --project tools/llm-gate llm-gate run --check {{ check }} {{ if engine != "" { "--engine " + engine } else { "" } }}

# Run a check with both engines and print the comparison table. Costs API credits (twice).
[group('llm')]
llm-compare check:
    just llm {{ check }} both

# Local equivalent of the deterministic CI gates; run before calling a change done
[group('test')]
ci: fmt-check lint build test

# Build the solution (warnings are errors)
[group('dev')]
build:
    dotnet build

# Run the API on http://localhost:5080 (OpenAPI at /openapi/v1.json)
[group('dev')]
run:
    dotnet run --project src/CalendarGates.Api --launch-profile http

# Unit + integration tests (Microsoft.Testing.Platform, see global.json); extra args go to dotnet test
[group('test')]
test *args:
    dotnet test {{ args }}

# HTTP contract tests against a running API (`just run` in another terminal); JUnit XML in reports/
[group('test')]
http env="local":
    ijhttp --no-progress -v http/http-client.env.json -e {{ env }} -r reports http/calendar.http

# Apply repo settings: merge rules, Actions defaults, security features, secret, variables, release environment
[group('github')]
[confirm('Apply settings to github.com/gergodrazsdik/calendar-gates?')]
gh-setup:
    #!/usr/bin/env bash
    set -euo pipefail
    repo={{ repo }}
    gh repo edit "$repo" --enable-squash-merge --enable-merge-commit=false \
        --enable-rebase-merge=false --delete-branch-on-merge --enable-auto-merge
    gh api -X PATCH "repos/$repo" --silent \
        -f squash_merge_commit_title=PR_TITLE -f squash_merge_commit_message=PR_BODY
    gh api -X PUT "repos/$repo/actions/permissions/workflow" --silent \
        -f default_workflow_permissions=read -F can_approve_pull_request_reviews=false

    # Only collaborators (here: the owner) can open PRs, and workflows on fork PRs wait for approval:
    # every PR runs the LLM review on the owner's API key.
    gh api -X PATCH "repos/$repo" --silent -f pull_request_creation_policy=collaborators_only
    gh api -X PUT "repos/$repo/actions/permissions/fork-pr-contributor-approval" --silent \
        -f approval_policy=all_external_contributors

    # Labels the LLM workflows react to
    gh label create llm-override -R "$repo" --force --color D93F0B \
        --description "LLM review: report blocking findings without failing the check"
    gh label create llm-compare -R "$repo" --force --color 5319E7 \
        --description "Run the code-review check with both LLM engines and compare"

    # Dependabot alerts + security updates, private vulnerability reporting, secret scanning + push protection
    gh api -X PUT "repos/$repo/vulnerability-alerts" --silent
    gh api -X PUT "repos/$repo/automated-security-fixes" --silent
    gh api -X PUT "repos/$repo/private-vulnerability-reporting" --silent
    gh api -X PATCH "repos/$repo" --silent --input - <<'JSON'
    {"security_and_analysis": {
      "secret_scanning": {"status": "enabled"},
      "secret_scanning_push_protection": {"status": "enabled"}}}
    JSON

    pass show api/anthropic-calendar-gates | gh secret set ANTHROPIC_API_KEY -R "$repo"
    gh variable set LLM_MODEL -R "$repo" --body claude-sonnet-5-5
    gh variable set LLM_MODEL_CHEAP -R "$repo" --body claude-haiku-5-5

    # Environment `release`: you as required reviewer, self-review allowed (solo repo), tags v* only
    uid=$(gh api user --jq .id)
    gh api -X PUT "repos/$repo/environments/release" --silent --input - <<JSON
    {"prevent_self_review": false,
     "reviewers": [{"type": "User", "id": $uid}],
     "deployment_branch_policy": {"protected_branches": false, "custom_branch_policies": true}}
    JSON
    if ! gh api "repos/$repo/environments/release/deployment-branch-policies" \
        --jq '.branch_policies[] | select(.type == "tag") | .name' | grep -qx 'v\*'; then
        gh api -X POST "repos/$repo/environments/release/deployment-branch-policies" --silent \
            -f name='v*' -f type=tag
    fi
    echo "Done. CodeQL default setup: run 'just gh-codeql' once there is C# and Python code (Phase 2+)."

# Turn on CodeQL default setup (languages are detected from the repo, so run it once code exists)
[group('github')]
[confirm('Enable CodeQL default setup on github.com/gergodrazsdik/calendar-gates?')]
gh-codeql:
    gh api -X PATCH repos/{{ repo }}/code-scanning/default-setup -f state=configured

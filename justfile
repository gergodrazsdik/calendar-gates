# calendar-gates: the single entry point, locally and in CI. `just` lists the recipes.

repo := "gergodrazsdik/calendar-gates"
image := "localhost/calendar-gates:dev"
chart := "deploy/helm/calendar-gates"
k8s_ns := "calendar-gates"

# Kubernetes (docs/adr/0010-admission-control.md): the project's own kind cluster, with Kyverno, is
# the default; `just cluster=local <recipe>` targets kind-local as in v1. The project cluster's
# kubeconfig lives in the state dir, so ~/.kube/config is never touched.
cluster := "calendar-gates"
kube_context := "kind-" + cluster
export KUBECONFIG := if cluster == "local" { env("KUBECONFIG", home_directory() / ".kube" / "config") } else { home_directory() / ".local" / "state" / "calendar-gates" / "kubeconfig" }

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
    # SSL_CERT_DIR here lists two dirs (the .NET dev cert); zizmor's TLS stack only reads one.
    # No GH_TOKEN: the offline audits are the ones this gate runs, and a full-scope OAuth token has
    # no business in a tool fetched from PyPI on every run (--offline matches ci.yml).
    env -u SSL_CERT_DIR uvx zizmor@1.30.1 --offline .github/
    hadolint Dockerfile
    uvx yamllint@1.38.0 --strict .
    shellcheck scripts/*.sh .claude/hooks/*.sh
    uvx ruff@0.16.10 check scripts/
    uvx ruff@0.16.10 format --check scripts/
    uv run --directory tools/llm-gate --locked ruff check .
    uv run --directory tools/llm-gate --locked ruff format --check .
    uv run --directory tools/llm-gate --locked mypy
    uv run --directory tools/llm-gate --locked pytest -q
    uv run --locked --script scripts/check-ruleset-consistency.py

# Fetch the audit-log branch into .audit-log/ for local queries (jq over events/**/*.jsonl)
[group('llm')]
audit-pull:
    #!/usr/bin/env bash
    set -euo pipefail
    git fetch --quiet origin audit-log:refs/remotes/origin/audit-log
    rm -rf .audit-log
    mkdir .audit-log
    git archive refs/remotes/origin/audit-log | tar -x -C .audit-log
    # `|| true`: a fresh audit-log branch has no events/ yet, which is not an error here.
    { find .audit-log/events -name '*.jsonl' 2> /dev/null || true; } | wc -l \
        | xargs printf '%s record file(s) in .audit-log/events\n'

# Score the review prompts on tools/llm-gate/evals/cases and compare with the baseline; extra args go to `llm-gate eval run` (e.g. --check code-review --engine both). Costs API credits.
[group('llm')]
eval *args:
    #!/usr/bin/env bash
    set -euo pipefail
    ANTHROPIC_API_KEY="$(pass show api/anthropic-calendar-gates | head -n 1)"
    export ANTHROPIC_API_KEY
    uv run --project tools/llm-gate --locked llm-gate eval run --compare {{ args }}

# Write tools/llm-gate/evals/baseline.json from the last `just eval` (commit it in a PR, deliberately)
[group('llm')]
eval-baseline:
    uv run --project tools/llm-gate --locked llm-gate eval baseline

# Gate health report (docs/metrics.md) over the audit log, the merged PRs and the last local eval run
[group('llm')]
metrics days="30": audit-pull
    #!/usr/bin/env bash
    set -euo pipefail
    gh api --paginate "repos/{{ repo }}/pulls?state=closed&per_page=100" \
        --jq '.[] | select(.merged_at) | {number, merged_at}' | jq -s . > .audit-log/prs.json
    eval_reports=()
    [ -f reports/eval/last.json ] && eval_reports=(--eval-reports reports/eval)
    uv run --project tools/llm-gate --locked llm-gate metrics --audit-dir .audit-log \
        --prs .audit-log/prs.json --since-days {{ days }} "${eval_reports[@]}"

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
    uv run --project tools/llm-gate --locked llm-gate run --check {{ check }} {{ if engine != "" { "--engine " + engine } else { "" } }}

# Run a check with both engines and print the comparison table. Costs API credits (twice).
[group('llm')]
llm-compare check:
    just llm {{ check }} both

# Start the cluster, creating it if needed: the project cluster (deploy/kind/cluster.yaml), or kind-local with cluster=local
[group('k8s')]
k8s-up:
    #!/usr/bin/env bash
    set -euo pipefail
    if [ "{{ cluster }}" = local ]; then
        if kind-local status | grep -q 'not created'; then kind-local create; else kind-local start; fi
        exit 0
    fi
    mkdir -p -m 700 "$(dirname "$KUBECONFIG")"
    if kind get clusters 2> /dev/null | grep -qx "{{ cluster }}"; then
        podman start "{{ cluster }}-control-plane" > /dev/null
        echo "started {{ cluster }}"
    else
        kind create cluster --name "{{ cluster }}" --config deploy/kind/cluster.yaml --wait 120s
    fi

# Delete the project cluster (never kind-local) and everything in it
[group('k8s')]
[confirm('Delete the kind cluster and everything in it?')]
k8s-cluster-down:
    # Never kind-local: that cluster is the machine's, managed by `kind-local` (AGENTS.md).
    [ "{{ cluster }}" != local ] || { echo "kind-local is not this project's to delete" >&2; exit 1; }
    kind delete cluster --name {{ cluster }}

# Install Kyverno (chart pinned by version and sha256, images by digest) and apply deploy/policies
[group('k8s')]
k8s-policy-up:
    #!/usr/bin/env bash
    set -euo pipefail
    [ "{{ cluster }}" != local ] || { echo "admission control runs on the project cluster, not kind-local" >&2; exit 1; }
    # deploy/kyverno/chart.sha256 pins the chart: its file name carries the version, its hash the bytes.
    dir="$HOME/.cache/calendar-gates/kyverno"
    file=$(awk '{print $2}' deploy/kyverno/chart.sha256)
    version=${file#kyverno-}; version=${version%.tgz}
    mkdir -p "$dir"
    [ -f "$dir/$file" ] || helm pull kyverno --repo https://kyverno.github.io/kyverno/ --version "$version" -d "$dir"
    (cd "$dir" && sha256sum -c --quiet) < deploy/kyverno/chart.sha256
    helm upgrade --install kyverno "$dir/$file" --kube-context {{ kube_context }} -n kyverno --create-namespace \
        -f deploy/kyverno/values.yaml --wait --timeout 5m
    kubectl --context {{ kube_context }} apply -k deploy/policies
    # Kyverno reports readiness per policy; without this wait a deploy right after this recipe can
    # be admitted before the webhook is live.
    kubectl --context {{ kube_context }} wait --for=condition=Ready --timeout=2m \
        validatingpolicies,imagevalidatingpolicies --all
    kubectl --context {{ kube_context }} get validatingpolicies,imagevalidatingpolicies

# Policy results (Audit findings, passes) for a namespace
[group('k8s')]
k8s-policy-report ns=(k8s_ns + "-dev"):
    kubectl --context {{ kube_context }} -n {{ ns }} get policyreports -o json \
        | jq -r '.items[] | "\(.scope.kind)/\(.scope.name)" as $r | .results[]? | "\(.result)\t\(.policy)\t\($r)\t\(.message // "")"' \
        | sort | column -t -s "$(printf '\t')"

# Build the image and load it into the cluster (kind can't see podman's images, so via an archive)
[group('k8s')]
k8s-load: image
    mkdir -p reports
    rm -f reports/calendar-gates.tar # podman save doesn't overwrite an archive
    podman save -o reports/calendar-gates.tar {{ image }}
    kind load image-archive reports/calendar-gates.tar --name {{ cluster }}

# Install or upgrade the chart with the loaded :dev image; rolls back on failure. The policies deny it in calendar-gates: `just k8s-deploy calendar-gates-dev`
[group('k8s')]
k8s-deploy ns=k8s_ns:
    helm upgrade --install calendar-gates {{ chart }} --kube-context {{ kube_context }} \
        -n {{ ns }} --create-namespace -f {{ chart }}/values-kind.yaml \
        --set-string "podAnnotations.calendar-gates/image-id=$(podman image inspect --format '{{{{.Id}}' {{ image }} | cut -c1-12)" \
        --reset-values --rollback-on-failure --timeout 2m

# Deploy a published release: chart and image from GHCR (after `just release`)
[group('k8s')]
k8s-deploy-release version ns=k8s_ns:
    @# --reset-values: without it, an upgrade with no values reuses the previous release's.
    helm upgrade --install calendar-gates oci://ghcr.io/gergodrazsdik/charts/calendar-gates \
        --version {{ version }} --kube-context {{ kube_context }} -n {{ ns }} --create-namespace \
        --reset-values --rollback-on-failure --timeout 3m

# HTTP contract tests through a port-forward (localhost:18080)
[group('k8s')]
k8s-http ns=k8s_ns:
    #!/usr/bin/env bash
    set -euo pipefail
    kubectl --context {{ kube_context }} -n {{ ns }} port-forward svc/calendar-gates 18080:80 >/dev/null &
    forward=$!
    trap 'kill $forward' EXIT
    # Without this, a forward that lost the port tests whatever else is listening on 18080.
    sleep 1
    kill -0 "$forward" 2> /dev/null || { echo "port-forward failed (is 18080 in use?)" >&2; exit 1; }
    scripts/wait-for-health.sh http://localhost:18080/health 30
    just http forward

# Pods, services and recent events of the deployment
[group('k8s')]
k8s-status ns=k8s_ns:
    kubectl --context {{ kube_context }} -n {{ ns }} get all,ingress
    kubectl --context {{ kube_context }} -n {{ ns }} get events --sort-by=.lastTimestamp | tail -n 10

# Follow the logs of all pods
[group('k8s')]
k8s-logs ns=k8s_ns:
    stern --context {{ kube_context }} -n {{ ns }} calendar-gates

# Remove the release and its namespace
[group('k8s')]
[confirm('Uninstall calendar-gates and delete its namespace?')]
k8s-down ns=k8s_ns:
    helm uninstall calendar-gates --kube-context {{ kube_context }} -n {{ ns }} --ignore-not-found
    kubectl --context {{ kube_context }} delete namespace {{ ns }} --ignore-not-found

# The chart part of the lint gate: helm lint and the rendered manifests against the Kubernetes schemas
[group('format')]
lint-chart:
    helm lint --kube-context kind-local --strict {{ chart }}
    helm lint --kube-context kind-local --strict {{ chart }} -f {{ chart }}/values-kind.yaml
    helm template --kube-context kind-local calendar-gates {{ chart }} --set ingress.enabled=true \
        | kubeconform -strict -summary -kubernetes-version 1.37.0 -
    @# Released charts pin the image by digest (release.yml, ADR 0009).
    helm template --kube-context kind-local calendar-gates {{ chart }} \
        --set image.digest=sha256:0000000000000000000000000000000000000000000000000000000000000000 \
        | grep -q 'image: "ghcr.io/gergodrazsdik/calendar-gates@sha256:0000'
    helm template --kube-context kind-local calendar-gates {{ chart }} \
        --set image.digest=sha256:0000000000000000000000000000000000000000000000000000000000000000 \
        | kubeconform -strict -summary -kubernetes-version 1.37.0 -

# The admission policies: both kustomize layers render, and the offline kyverno tests pass (the image verification itself runs in release.yml's admission-smoke)
[group('format')]
lint-policies:
    #!/usr/bin/env bash
    set -euo pipefail
    want=1.19.1 # as deploy/kyverno and ci.yml's kyverno-cli image
    got=$(kyverno version 2> /dev/null | awk '/^Version:/ {print $2}')
    [ "$got" = "$want" ] || { echo "kyverno CLI $want needed, found ${got:-none}" >&2; exit 1; }
    kubectl --context {{ kube_context }} kustomize deploy/policies > /dev/null
    kyverno test deploy/policies/tests --remove-color

# Tag main as vX.Y.Z (signed) and push the tag; release.yml then waits for your approval
[group('release')]
[confirm('Create and push the signed release tag?')]
release version:
    #!/usr/bin/env bash
    set -euo pipefail
    version={{ version }}
    if [[ ! $version =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?$ ]]; then
        echo "usage: just release MAJOR.MINOR.PATCH[-PRERELEASE] (no v prefix)" >&2; exit 1
    fi
    [ "$(git branch --show-current)" = main ] || { echo "release from main" >&2; exit 1; }
    git fetch --quiet origin main --tags
    [ -z "$(git status --porcelain)" ] || { echo "the working tree is not clean" >&2; exit 1; }
    [ "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" ] || {
        echo "main is not in sync with origin/main" >&2; exit 1; }
    ! git rev-parse --quiet --verify "refs/tags/v$version" > /dev/null || {
        echo "v$version already exists" >&2; exit 1; }
    just ci
    git tag -s "v$version" -m "v$version"
    # Drop the local tag if the push fails, so a retry isn't blocked by "v$version already exists".
    git push origin "v$version" || { git tag -d "v$version"; exit 1; }
    echo "Pushed v$version: approve the release environment in the release workflow run."

# Verify a release's attestations (provenance, SBOM, vuln scan, LLM review; ADR 0009), each signed by release.yml for that tag
[group('release')]
verify-release version:
    #!/usr/bin/env bash
    set -euo pipefail
    version={{ version }}
    [[ $version =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?$ ]] || {
        echo "usage: just verify-release MAJOR.MINOR.PATCH (no v prefix)" >&2; exit 1; }
    repo=gergodrazsdik/calendar-gates
    image="oci://ghcr.io/$repo:$version"
    tmp=$(mktemp -d)
    trap 'rm -rf "$tmp"' EXIT
    types=(
        provenance=https://slsa.dev/provenance/v1
        sbom=https://spdx.dev/Document/v2.3
        vuln-scan=https://github.com/$repo/attestations/vuln-scan/v1
        llm-review=https://github.com/$repo/attestations/llm-review/v1
    )
    for entry in "${types[@]}"; do
        name=${entry%%=*}
        # --signer-workflow and --source-ref: signed by release.yml, run for this very tag.
        gh attestation verify "$image" --owner gergodrazsdik \
            --signer-workflow "$repo/.github/workflows/release.yml" --source-ref "refs/tags/v$version" \
            --predicate-type "${entry#*=}" --format json > "$tmp/$name.json"
        echo "verified: $name"
    done
    echo
    echo "Vulnerabilities (grype $(jq -r '.[0].verificationResult.statement.predicate.scanner.version' "$tmp/vuln-scan.json")):"
    jq -r '.[0].verificationResult.statement.predicate.results[] | "  \(.platform): \(.counts | to_entries | map("\(.key) \(.value)") | join(", "))"' "$tmp/vuln-scan.json"
    echo "LLM review:"
    jq -r '.[0].verificationResult.statement.predicate
        | "  \(.prs | length) PR(s) from \(.range.from // "the first commit") to \(.range.to)",
          "  unreviewed: \(.unreviewed | map("#\(.number // .commit): \(.reason)") | join("; ") | if . == "" then "none" else . end)",
          "  unverified: \(.unverified | map("#\(.number): \(.reason)") | join("; ") | if . == "" then "none" else . end)"' \
        "$tmp/llm-review.json"

# Local equivalent of the deterministic CI gates; run before calling a change done
[group('test')]
ci: fmt-check lint lint-chart lint-policies build test

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

    pass show api/anthropic-calendar-gates | head -n 1 | gh secret set ANTHROPIC_API_KEY -R "$repo"
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

# Apply .github/rulesets/*.json (create, or update the ruleset with the same name)
[group('github')]
[confirm('Apply the rulesets? Afterwards main only changes through PRs that pass the required checks.')]
gh-rulesets:
    #!/usr/bin/env bash
    set -euo pipefail
    repo={{ repo }}
    uv run --locked --script scripts/check-ruleset-consistency.py
    for file in .github/rulesets/*.json; do
        name=$(jq -r .name "$file")
        id=$(gh api "repos/$repo/rulesets" | jq -r --arg name "$name" '.[] | select(.name == $name) | .id')
        if [ -n "$id" ]; then
            gh api -X PUT "repos/$repo/rulesets/$id" --input "$file" --jq '"updated \(.name) (\(.id))"'
        else
            gh api -X POST "repos/$repo/rulesets" --input "$file" --jq '"created \(.name) (\(.id))"'
        fi
    done

# Turn on CodeQL default setup (languages are detected from the repo, so run it once code exists)
[group('github')]
[confirm('Enable CodeQL default setup on github.com/gergodrazsdik/calendar-gates?')]
gh-codeql:
    gh api -X PATCH repos/{{ repo }}/code-scanning/default-setup -f state=configured

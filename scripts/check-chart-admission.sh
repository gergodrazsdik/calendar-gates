#!/usr/bin/env bash
# The rendered chart against calendar-gates-workload (docs/adr/0011-workload-hardening.md), so a
# chart change that admission would refuse fails `lint` on the PR instead of at the next release.
# Kyverno's autogen applies the pod rules to the chart's Deployment.
#
# Two traps this guards against: `helm template` sets no namespace, and the policy selects by
# namespace, so without one every resource is skipped and `kyverno apply` exits 0 having checked
# nothing. The namespace is set here, and the report must show at least one pass and no failures.
#
# Runs the local `kyverno` (`just lint-policies`); with KYVERNO_CLI_IMAGE set (ci.yml) it runs that
# image instead. Needs helm, yq and jq.
set -euo pipefail

chart=deploy/helm/calendar-gates
policy=deploy/policies/base/workload.yaml
values=deploy/policies/tests/values.yaml
# Released charts pin the image by digest (ADR 0009); check that render too. It gets its own
# release name: kyverno refuses two objects with the same name in one run.
digest=sha256:0000000000000000000000000000000000000000000000000000000000000000

work=$(mktemp -d "${TMPDIR:-/tmp}/chart-admission.XXXXXX")
trap 'rm -rf "$work"' EXIT

{
    helm template calendar-gates "$chart"
    echo ---
    helm template calendar-gates-release "$chart" --set image.digest="$digest"
} | yq 'select(has("kind")) | .metadata.namespace = "calendar-gates"' > "$work/chart.yaml"
# The kyverno-cli image runs as its own non-root user; the rendered chart holds nothing secret.
chmod 755 "$work"
chmod 644 "$work/chart.yaml"

if [[ -n ${KYVERNO_CLI_IMAGE:-} ]]; then
    kyverno=(docker run --rm -v "$PWD:/repo:ro" -v "$work:/work:ro" --workdir /repo "$KYVERNO_CLI_IMAGE")
    rendered=/work/chart.yaml
else
    kyverno=(kyverno)
    rendered=$work/chart.yaml
fi

# kyverno exits non-zero on a failed rule; the report below says which, so read it either way.
report=$("${kyverno[@]}" apply "$policy" -r "$rendered" -f "$values" -p --output-format json) || true
summary=$(jq -c .summary <<< "$report")
echo "calendar-gates-workload on the rendered chart: $summary"

if ! jq -e '.summary.pass >= 1 and .summary.fail == 0 and .summary.error == 0' <<< "$report" > /dev/null; then
    jq -r '.results[]? | select(.result != "pass")
        | "\(.result): \(.resources[0].kind)/\(.resources[0].name): \(.message)"' <<< "$report" >&2
    echo "the chart would be refused by calendar-gates-workload, or nothing was checked" >&2
    exit 1
fi

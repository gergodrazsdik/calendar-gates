#!/usr/bin/env bash
# Test pods and assertions for release.yml's admission-smoke (docs/adr/0010-admission-control.md,
# docs/adr/0011-workload-hardening.md). Sourced, not run: `. scripts/admission-fixtures.sh`.
#
# Each test pod runs as the chart's pod does, so it breaks only the rule its case is about. Pod
# Security Admission answers before any webhook and stops the request there, so a pod that broke
# `restricted` would never reach the policy under test. And the image-attestation policies each have
# their own webhook, called in parallel with the one that serves calendar-gates-images and -workload
# (that one reports both): an assertion that more than one policy may answer takes a regex.

# A pod in calendar-gates, as YAML on stdout. Arguments: pod name, image of the app container, image
# of an init container ("" for none), readOnlyRootFilesystem (default true), an extra entry for the
# container securityContext, an extra pod spec line.
pod() {
    local init=""
    [ -n "$3" ] && init="initContainers: [{name: sneak, image: \"$3\", $(container)}]"
    cat << EOF
apiVersion: v1
kind: Pod
metadata: {name: $1, namespace: calendar-gates}
spec:
  automountServiceAccountToken: false
  securityContext:
    runAsNonRoot: true
    runAsUser: 1654
    runAsGroup: 1654
    seccompProfile: {type: RuntimeDefault}
  $init
  containers: [{name: app, image: "$2", $(container "${4:-true}" "${5:-}")}]
  ${6:-}
EOF
}

# The chart's container securityContext and memory limit, on one line. Arguments:
# readOnlyRootFilesystem (default true), an extra securityContext entry.
container() {
    local sc="allowPrivilegeEscalation: false, readOnlyRootFilesystem: ${1:-true}, capabilities: {drop: [ALL]}"
    echo "securityContext: {$sc${2:+, $2}}, resources: {limits: {memory: 64Mi}}"
}

# Asserts a request is refused, and by whom. Arguments: a description, an ERE the refusal must
# match, and the command to run (default: a server-side dry-run create of the YAML on stdin).
refused() {
    local what=$1 expected=$2 out
    shift 2
    [ $# -gt 0 ] || set -- kubectl create --dry-run=server -f -
    if out=$("$@" 2>&1); then
        echo "::error::$what was admitted"
        exit 1
    fi
    echo "$out"
    grep -qE "$expected" <<< "$out" || {
        echo "::error::$what was not refused by $expected"
        exit 1
    }
}

# The ERE for a refusal by one of the named Kyverno policies (itself an ERE alternation).
policy() { echo "Policy ($1) failed"; }

# The ERE for a refusal by Pod Security Admission in calendar-gates.
# shellcheck disable=SC2034  # used by the scripts that source this file
psa='violates PodSecurity "restricted:v1\.35"'

# 11. Workload hardening: Pod Security Admission as the floor, a Kyverno policy for the rest

- Status: accepted
- Date: 2026-10-23

## Context

ADR 0010 decides **which bytes** may run in `calendar-gates`: this project's image, by digest, with
provenance, a clean vulnerability scan, a review record and an approval. Nothing decides **how**
they run. The chart already hardens the pod (`deploy/helm/calendar-gates/templates/deployment.yaml`):

- **Pod level:** `runAsNonRoot`, uid and gid 1654, seccomp `RuntimeDefault`, no service-account
  token.
- **Container level:** `allowPrivilegeEscalation: false`, a read-only root filesystem,
  `capabilities.drop: [ALL]`.

But these are defaults that anyone can override, not a control. Anyone who can create pods in the
namespace can run the attested release digest with `privileged: true`, `runAsUser: 0`, `hostPID`
or a `hostPath: /` volume, and all four policies admit it. Drill 13 (`runAsUser: 0` in the chart)
only fails at runtime, when the kubelet refuses to start the container.

The plan for this was argued by five reviewers with different briefs: a security hardliner, a
minimalist, an operations engineer, a red-team skeptic and a mentor. All five reached the same
engine choice. Where they disagreed, the decisions below say which way it went.

## Decision

**Two layers, both Deny in `calendar-gates`.**

1. **Pod Security Admission (PSA), profile `restricted`, as the floor.**
   - **Labels on the namespace:** `enforce: restricted` with `enforce-version: v1.35`, pinned to
     the node version in `deploy/kind/cluster.yaml`, so a Kubernetes upgrade can't change the
     rules silently. `warn` and `audit` are at `latest`, to show what the next version would add.
   - **Why it's the floor:** PSA is built into the API server, so it has no webhook that can be
     down and no exception CRD. It covers init and ephemeral containers. It checks for:
     - privileged containers, host namespaces, hostPath, hostPorts, procMount, unsafe sysctls,
       AppArmor and SELinux overrides, and volume types outside its allowlist;
     - privilege escalation, `runAsNonRoot`, a uid of 0, and seccomp `Unconfined`;
     - `drop: [ALL]`, with only `NET_BIND_SERVICE` allowed in `add`.

     See the [standards](https://kubernetes.io/docs/concepts/security/pod-security-standards/).
   - **`calendar-gates-dev`:** `enforce: baseline`, with `warn` and `audit` at `restricted`.
     Baseline still admits the bare `kubectl run` pods that drill 21 and `admission-smoke` use
     there, and `restricted` violations show up as warnings.

2. **One Kyverno `ValidatingPolicy`, `calendar-gates-workload`, for what PSA doesn't check or
   allows more loosely.** It sits in `deploy/policies/base/`, with the dev overlay switching it to
   Audit like the others. For every container, it reads the container's own value first, then the
   pod's, then Kubernetes' default (an unset `allowPrivilegeEscalation` counts as true):
   - `runAsUser` set explicitly and greater than 0. PSA accepts an unset uid and lets the image
     decide.
   - `runAsGroup` not 0, and no 0 in `fsGroup` or `supplementalGroups`. PSA doesn't check groups.
   - `readOnlyRootFilesystem: true`. This isn't in PSA.
   - `capabilities.drop` contains exactly `ALL` and `add` is empty. The app listens on 8080, so it
     has no use for `NET_BIND_SERVICE`.
   - seccomp `RuntimeDefault` only. PSA also accepts `Localhost`, a profile file on the node that
     nobody reviews.
   - `automountServiceAccountToken: false`, and no projected volume with a `serviceAccountToken`
     source, which would mount the token anyway.
   - `limits.memory` on every container and init container. One runaway pod can take down the
     single kind node.
   - Privilege escalation, `privileged`, `runAsNonRoot` and host namespaces, repeated from PSA. This
     is the one point the minimalist lost, 3 to 2. PSA can't be tested offline and leaves nothing
     in a PolicyReport. The Kyverno copy can be tested offline, runs against the rendered chart in
     CI, and reports violations in `calendar-gates-dev`.

   The policy matches `pods`, not `pods/ephemeralcontainers`. Ephemeral containers stay covered
   by PSA, and by `calendar-gates-images`, which already refuses every foreign debug image.
   Ephemeral containers can't set `resources` at all, and
   `kubectl debug --profile=restricted` doesn't set a read-only root filesystem.

   Matching `pods` only keeps Kyverno's **autogen**: the same rules apply to Deployments,
   ReplicaSets and the other pod controllers. A bad chart then fails at `helm install` with the
   rule's message, instead of being admitted and leaving its ReplicaSet with `FailedCreate` until
   `helm --wait` times out.

3. **The same policy runs in CI.** `just lint-policies` and `lint` take `helm template` output, set
   the namespace (it has none, and the policies select by namespace) and run `kyverno apply` on
   it. The check must require at least one pass. Without a namespace, `kyverno apply` skips
   everything and exits 0 with `pass: 0, fail: 0`. Checked with CLI 1.19.1 on 2026-10-23.

4. **The PSA labels are guarded.** A `ValidatingPolicy` on Namespace updates refuses removing or
   changing the `pod-security.kubernetes.io/*` labels on both namespaces. Without it, editing the
   label would be PSA's one bypass.

**Deny from the first PR.** The earlier Audit periods (LLM review, approval; ADR 0010) existed
because older releases didn't carry the new attestations. Here every release of the chart
complies, and `admission-smoke` runs before anything is published (F071). So a rule that is
wrong fails a release candidate, not a published release.

**Considered and not chosen:**

| Engine | Why not |
|---|---|
| OPA Gatekeeper | A second cluster-wide webhook engine, with its own CRDs, upgrades and exception surface, and a third policy language (Rego). It covers nothing that PSA and CEL can't. |
| Kubernetes `ValidatingAdmissionPolicy` | The same CEL as Kyverno's `ValidatingPolicy`, without `kyverno test`, PolicyReports, autogen or the dev overlay. |
| Re-implementing all of PSA in CEL | Roughly fifteen expressions duplicating a built-in, and they would miss fields Kubernetes adds later. Only the rules above are repeated. |
| Kyverno `ClusterPolicy` `podSecurity` subrule | Deprecated in 1.19 and removed in 1.20 (ADR 0010). |
| Mutating policies that add a secure default | They would hide drift in the chart, which is exactly what the gate should show. |

**Not enforced:**
- Checking that the image's own `USER` is non-root: an explicit `runAsUser` makes it moot, and it
  would cost a registry fetch at admission.
- An exact uid of 1654: it couples the policy to the base image.
- CPU limits.
- runtimeClass and AppArmor: kind on WSL has neither.
- `hostUsers: false`: user namespaces on kind over rootless podman are unproven.
- A volume allowlist narrower than PSA's.

## Consequences

- **PSA runs before Kyverno's webhooks.** The PodSecurity plugin comes before the validating
  webhooks in the API server's admission chain, and the chain stops at the first refusal.
  `admission-smoke`'s negative pods (`kubectl run edge`, `foreign`, the `init-edge` manifest) have
  no `securityContext`. Under `enforce: restricted`, PSA would refuse them first, and their
  "refused by policy X" checks would fail the release. They must become `restricted`-compliant in
  the same PR that adds the labels, so each one still tests its image policy.
- **What it proves:** the pod spec submitted to `calendar-gates` is hardened.
- **What it doesn't prove:**
  - **That the kubelet and runtime honour it.**
  - **Anything about cluster-admin.** On kind, cluster-admin can relabel the namespace or delete
    the policies.
  - **Anything about mirror pods.** Kyverno skips requests from `system:nodes` (the chart's
    default), though PSA still checks those pods.
- **Kyverno PolicyExceptions are switched off** in the pinned chart
  (`features.policyExceptions.enabled: false`), but the CRD is installed. `admission-smoke` proves
  an exception doesn't work rather than assuming it.
- **`readOnlyRootFilesystem` proves less than its name suggests.** `/tmp` is a writable emptyDir,
  so the setting doesn't stop a payload being written and run. It stops runtime changes to `/app`,
  which uid 1654 can't write anyway. The rule is kept because it costs nothing, and because
  drill 24 uses it to show what only the Kyverno layer catches.
- **Debugging in `calendar-gates`** stays limited to logs. The chiseled image has no shell, and
  foreign debug images were already refused. To reproduce a problem, use `calendar-gates-dev`.
- **The PSA version pin moves with the node image.** A bump of `kindest/node` must bump
  `enforce-version` in the same PR.
- **A violation can be reported twice,** by PSA and by Kyverno. Negative tests assert on
  fixtures that break exactly one layer, because the webhooks run in parallel (the v0.3.3
  lesson, ADR 0010).
- **Drill 13 changes.** `runAsUser: 0` in the chart is now caught at `lint` on the PR, at
  k8s-smoke, whose namespace gets the same labels, and at admission, no longer only by the kubelet.
  Drill 24 (`readOnlyRootFilesystem: false`) is caught only by the Kyverno layer.

The steps are in [PLAN-v2](../PLAN-v2.md) Phase 22.

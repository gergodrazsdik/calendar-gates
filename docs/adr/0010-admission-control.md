# 10. Admission control: Kyverno verifies the release attestations, in the project's own cluster

- Status: accepted
- Date: 2026-10-17

## Context

Releases carry build provenance, an SBOM, a vulnerability scan and an LLM-review attestation
(ADR 0009), but nothing used them: any image could run anywhere. The plan (docs/PLAN-v2.md
Phase 19) calls the two decisions here ADR-0007 and ADR-0008; those numbers went to other ADRs.

There were three constraints:

- **Webhooks act cluster-wide.** Admission webhooks see every request in a cluster, and ADR 0003
  keeps `kind-local` free of project components.
- **Kyverno's old path is going away.** Kyverno 1.19 deprecates `ClusterPolicy`, and 1.20 removes
  it. The old `verifyImages` path, the one documented for GitHub attestations, is therefore a dead
  end.
- **Version support.** Kyverno 1.19 supports Kubernetes 1.33 to 1.35. `kind-local` runs 1.37.

## Decision

**A project cluster.** `kind-calendar-gates` is defined in `deploy/kind/cluster.yaml`: one node,
`kindest/node:v1.35.8` pinned by digest (the newest node image kind v0.33.0 ships that Kyverno
supports), and no host ports. Access stays a port-forward (ADR 0003).

- **Kubeconfig:** `~/.local/state/calendar-gates/kubeconfig`, so `~/.kube/config` never changes.
- **Recipes:** `just k8s-up` creates or starts it, `k8s-policy-up` installs Kyverno and the
  policies, and `k8s-cluster-down` deletes it. Every `k8s-*` recipe targets it by default;
  `just cluster=local …` targets kind-local as in v1.

**Kyverno is pinned.** Kyverno is **1.19.1**, chart **3.9.1**. The chart is unsigned, so its
sha256 is pinned in `deploy/kyverno/chart.sha256`. Every image is pinned by digest in
`deploy/kyverno/values.yaml`, after `cosign verify-attestation` showed SLSA provenance from
slsa-github-generator for kyverno/kyverno at the v1.19.1 commit. The chart has no digest field,
so the digest is part of the tag (`v1.19.1@sha256:…`), where it wins.

**The spike: `ImageValidatingPolicy` v1 reads GitHub attestations.** `actions/attest` pushes
Sigstore bundles as OCI referrers. An `intoto` attestation with a keyless GitHub identity verifies
them on Sigstore's public-good roots, and `extractPayload()` returns the in-toto statement, with
the predicate under `.predicate`. The spike results:

- v0.2.0 and v0.3.0 were admitted;
- the `edge` image was denied;
- no cosign re-signing was needed, and no `ClusterPolicy` is used.

Kyverno 1.19 already serves `policies.kyverno.io/v1`, so the policies use it, and 1.20 needs no
`kyverno migrate`.

**The policies** live in `deploy/policies/`. `base/` is the Deny set for `calendar-gates`, and
`dev/` is a kustomize overlay that audits in `calendar-gates-dev`. They are cluster-scoped
policies that select their namespace, so a tenant of the namespace can't edit or delete them.

1. **`calendar-gates-images`** (`ValidatingPolicy`): every container image is
   `ghcr.io/gergodrazsdik/calendar-gates…@sha256:…`.
2. **`calendar-gates-release`** (`ImageValidatingPolicy`): two checks, both signed by
   `release.yml` on a `v*` tag (keyless, issuer `token.actions.githubusercontent.com`):
   - build provenance;
   - a vulnerability scan with `counts.critical == 0` on every platform.

   It also sets `mutateDigest`, so what runs is the digest that was verified.
3. **`calendar-gates-llm-review`** (`ImageValidatingPolicy`): the LLM-review attestation is
   present. It **audits in both namespaces** for now; once a few releases carry it, it moves to
   Deny with a one-line change.

**Proof on every release.** `release.yml`'s `admission-smoke` builds the same cluster, Kyverno
and policies on the runner, then checks:

- the just-published chart is admitted and runs the release digest;
- `edge` and a foreign image are denied, each by the expected policy;
- `calendar-gates-dev` admits `edge` and reports it as failing.

`smoke`, which publishes the release, waits for it. `kyverno test` covers the one policy that needs
no registry (`just lint-policies`, ci.yml).

## Consequences

- **Two layers, two thresholds.** CI fails a release on **high** vulnerabilities, and admission on
  **critical**. The scan is a snapshot from release time. Admission re-reads it on every
  deployment, but it never rescans: a CVE published after the release doesn't block it. The
  admission threshold is therefore the backstop, not the main check.
- **Kyverno pins tags to digests before validation.** An image referenced by tag passes rule 1 once
  `calendar-gates-release` has resolved it to its verified digest. The rule's real job is to
  restrict the repository, and the release chart pins the digest anyway.
- **Verification is slow when cold.** A cold check fetches every attestation and the Sigstore
  trust root, which took more than the 10 s webhook default. The image policies allow 30 s, the
  maximum, and Kyverno caches results for an hour.
- **Failure is closed.** The webhooks fail closed. When Kyverno is down, no pod starts in
  `calendar-gates`, and a policy that can't be evaluated denies. The spike saw this: a wrong CEL
  path denied the release instead of admitting it.
- **Two clusters exhaust inotify.** The spike crashed a .NET pod on this machine: two kind clusters
  plus Kyverno used up the per-user `fs.inotify.max_user_instances` limit of 128, and every .NET
  config watcher takes one instance. The image now sets
  `DOTNET_hostBuilder__reloadConfigOnChange=false`, since its config never changes. The machine
  should also raise the limit to 512, as kind's known-issues page recommends; that's a setup-doc
  change. `kind-local stop` while working here frees memory as well.
- **kubectl skew:** kubectl 1.37 against the 1.35 node is outside kubectl's ±1-minor support. It
  works for what the recipes do, and CI pins kubectl 1.35.8.

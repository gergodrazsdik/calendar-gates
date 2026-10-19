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
They check every container kind (init and ephemeral containers too), on `pods` and on
`pods/ephemeralcontainers`, the subresource `kubectl debug` writes to. Kyverno's controllers get
read access to that subresource in `deploy/kyverno/values.yaml`, or they report the policies as
not ready.

1. **`calendar-gates-images`** (`ValidatingPolicy`): every container image is
   `ghcr.io/gergodrazsdik/calendar-gates…@sha256:…`.
2. **`calendar-gates-release`** (`ImageValidatingPolicy`): two checks, both signed by
   `release.yml` on a `v*` tag (keyless, issuer `token.actions.githubusercontent.com`):
   - build provenance;
   - a vulnerability scan with `counts.critical == 0` on every platform.

   It also sets `mutateDigest`, so what runs is the digest that was verified.
3. **`calendar-gates-llm-review`** (`ImageValidatingPolicy`): the LLM-review attestation is
   present **and says every pull request in the release was reviewed**. It started as Audit while
   no release carried the attestation yet, and **denies in `calendar-gates` since #54**
   (2026-10-17), which merged after the v0.3.1 tag: v0.3.0 and v0.3.1 both carry the attestation,
   but the tagged trees still have the policy on Audit, so the first release whose
   `admission-smoke` exercises Deny is the next one. The dev namespace only audits.

   **Amended 2026-10-19: the policy reads the predicate.** Until then it checked only that a
   signed attestation existed, so "only reviewed code runs here" meant "a document about reviews
   is attached": a release in which every PR was unreviewed was admitted, and `just verify-release`
   printed the lists without asserting on them. The clause is now
   `extractPayload(...).predicate.unreviewed.size() == 0`, the same shape as the vuln-scan rule
   above, and `verify-release` fails on the same condition.

   `unreviewed` only — a PR with no review record for its merged head, or whose blocking checks
   never decided. **`unverified` is deliberately not denied.** It marks a run that came from a
   modified review workflow, which here is most of them (the gate is what the PRs change): the
   predicate computed for v0.3.7 lists two such PRs with `unreviewed` empty, so denying on it
   would block every legitimate release. It is reported by `verify-release` and in the release
   notes instead. That is a real limit on what admission proves, and it is the reason ADR 0004's
   remaining hole matters: closing it is what would make `unverified` empty and this assertion
   worth tightening.

   The clause is exercised offline over mock predicates in
   `deploy/policies/tests/llmreview-rule/`, and `scripts/check-policy-clauses.py` keeps that copy
   identical to the policy — the same arrangement the vuln-scan rule has had since F069.

**Proof on every release.** `release.yml`'s `admission-smoke` builds the same cluster, Kyverno
and policies on the runner, then checks:

- the just-published chart is admitted and runs the release digest;
- `edge` and a foreign image are denied, each by the expected policy. `edge` fails **all three**
  attestation policies — release, llm-review and, since v0.3.2, approved — and their webhooks run
  in parallel, so any one of them may be the one that refuses it (v0.3.3's run failed on an
  assertion that still named only the first two);
- `calendar-gates-dev` admits `edge` and reports it as failing.

`smoke`, which publishes the release, waits for it. `kyverno test` covers the one policy that needs
no registry (`just lint-policies`, ci.yml).

**The decision rules are tested offline too** (2026-10-18, F069). The image policies' inputs need a
registry, but what they *decide* with those inputs is ordinary CEL, and the "no critical findings"
clause had no test at all: a copy that admitted criticals would have passed every gate.
`deploy/policies/tests/vulnscan-rule/` evaluates that clause over mock predicates (clean, highs
without criticals, one critical, a critical on one platform of a multi-platform image), and
`scripts/check-policy-clauses.py` keeps the copy identical to the clause in `release.yaml`, so
changing the rule without changing the cases fails the lint gate instead of shipping untested.

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
- **Image volumes are refused** (2026-10-18, F047). An image volume (KEP-4639, beta and on by
  default in Kubernetes 1.35) mounts a registry image into a pod read-only, with no promise that
  what's in it can't be executed, and the `ImageValidatingPolicy` collections (`images.containers`
  and the two container kinds) can't reach them: an image volume cannot be attestation-verified at
  all. A pod whose only container was the attested release could therefore run code from any
  registry beside it. `calendar-gates-images` now denies any pod with an image volume, the release
  chart uses none, and `kyverno test` covers a foreign one, the release's own, and plain volumes.
- **The approval is its own attestation** (2026-10-18, F048). The other four are created in
  `attest`, which runs before the approval-gated `publish` on purpose (ADR 0009: the approver sees
  attested bytes). The consequence was that a candidate built, scanned, attested and then
  *rejected* carried everything admission asked for, and drill 23 showed a `candidate-v…` tag
  being admitted. `publish` now also attests `release-approved/v1`, which can only exist after a
  person approved that environment, and `calendar-gates-approved` requires it.
  It started as Audit, because no release up to v0.3.1 carries one, and **denies since v0.3.2**
  (2026-10-18), the first release whose `publish` job created it: the same path the LLM-review
  policy took. v0.3.0 and v0.3.1 are refused in `calendar-gates` from now on, which is true to
  what they are — images nobody approved under this scheme. `just verify-release` requires the
  type too, so it fails on older releases for it, as it does for v0.1.0 and v0.2.0 on the newer
  ones. Deploy an older release only in `calendar-gates-dev`, which audits.
- **Admission trusts the signing identity, not where the commit sits** (2026-10-18). The
  attestors accept `release.yml@refs/tags/v…`, which a tag on an unmerged commit also gets
  (ADR 0009's amendment). The cluster can't check whether a commit is on `main`, so that check
  lives in `just verify-release` and in the `release-tags` ruleset's `creation` rule, not here.
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

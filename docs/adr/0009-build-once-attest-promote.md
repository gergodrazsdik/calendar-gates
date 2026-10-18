# 9. Releases build once, attest the digest, and promote it after approval

- Status: accepted
- Date: 2026-10-17

## Context

v1's `release.yml` built the image twice: an amd64 tar for the scan, then the multi-arch image in
`publish`. `publish` pushed the version tags before anything scanned the pushed bytes. Image tags
are public the moment they exist, and a version can't be reused (`release-tags`). So a scan that
failed after the push left a broken `X.Y.Z` behind.

A release also said nothing about how its changes were reviewed. The LLM gate's audit log
(ADR 0005) has that information, but nothing tied it to the image.

## Decision

`release.yml` runs these jobs in order:

1. **verify:** checks the tag, and finds the previous release tag.
2. **build-test:** the build and tests.
3. **build:** builds the image once and pushes it by digest only.
4. **scan:** scans that digest.
5. **attest:** attests on that digest.
6. **publish:** after approval, promotes the digest to the version tags, attests the approval
   (`release-approved/v1`, the one attestation that can't exist before the gate) and pushes the
   chart.
7. **admission-smoke** ([ADR 0010](0010-admission-control.md)): proves Kyverno admits the released
   digest and denies an unattested image, on a throwaway cluster.
8. **smoke:** runs the digest, then publishes the release.

- **Build once.** The multi-arch image is built once, without the Actions cache, and pushed as
  `candidate-vX.Y.Z`. The planned tag was `sha-<short>`, but `ci.yml`'s edge images already use
  that. A second build of the same commit would overwrite it with different bytes, because builds
  aren't reproducible.
- **Scan the digest.** grype scans `image@digest` for both platforms, with the pull-request
  config: fail on high.
- **Attest the digest.** `actions/attest` adds four attestations, all pushed to the registry next
  to the image:
  - SLSA build provenance;
  - the SPDX SBOM;
  - **`…/attestations/vuln-scan/v1`:** the grype version and database date, counts per platform,
    and the `.grype.yaml` ignores with their reasons (`llm-gate attest vuln-scan`);
  - **`…/attestations/llm-review/v1`:** every PR merged since the previous release, from
    `scripts/release-commits.sh` and `llm-gate attest llm-review`. For each PR it gives the latest
    verdict per check on the **merged head** (not an earlier push), the triage risk, and any
    overrides.
    - **unreviewed:** a PR merged before the audit log existed, a merged head with no review, or a
      blocking check that was skipped for want of a key or ended in an error.
    - **unverified:** a PR that changed the review workflow itself, or one with `tamper_suspected`
      events.

    The release notes print the same lists. The range starts at the previous **final** release
    for a final version, and at the previous release of any kind for a prerelease. PRs that only
    reached an `-rc` tag therefore still count for the final release.
- **Promote after approval.** `publish` (the `release` environment) gives the attested digest
  `X.Y.Z` and `X.Y` with `buildx imagetools create`, and checks that both tags resolve to it.
  An existing `X.Y.Z` is never moved. A full re-run builds new bytes, so `publish` fails rather
  than move the version tag to them, and the fix is a new version, as for git tags.
  It pushes the chart with `image.digest` pinned, so a released chart can only pull the attested
  bytes.
- **Verify.** `just verify-release X.Y.Z` runs `gh attestation verify` for each predicate type,
  requiring `--signer-workflow …/release.yml` and `--source-ref refs/tags/vX.Y.Z`. An attestation
  made by any other workflow, or for another tag, doesn't count.

## Rekor: releases only

This is a public repository, so `actions/attest` signs keyless through Sigstore's public-good
instance. Every attestation becomes a **permanent, public entry in the Rekor transparency log**.
The entry holds the subject digest and the signing identity (repository, workflow, ref), not the
predicate.

**Only releases are attested:** four entries per release. The plan also attested every audit
record from `audit-collect.yml` (18.3). That would add an entry per review run, dozens a week, for
little gain: the records are already commits that GitHub signs, on a branch whose ruleset blocks
force pushes and deletion. The owner decided this on 2026-10-17. Revisit it if records must be
verifiable outside GitHub.

## Consequences

- **A failed scan leaves only the candidate tag.** No version tags, chart or release appear.
  Approval comes after the scan and the attestations, so the reviewer approves known bytes.
- **The vulnerability attestation is true when it was made.** A CVE published later doesn't show
  up in it. A rescan is a new grype run, not a re-check of the attestation.
- **The LLM-review attestation is only as good as the audit log.** It summarises what the collector
  accepted (ADR 0005, ADR 0008), and it lists gaps instead of hiding them. It proves which
  workflow made the summary, from which log, for which digest. It doesn't prove the reviews were
  right.
- **Any edit to the workflow can drop attestations.** A PR that changes `release.yml` is high risk
  in triage and reviewed like any other workflow change. The attestations name the workflow
  that signed them, and `verify-release` checks that name.
- **Amended 2026-10-18: a tag is bound to a commit on `main` outside the workflow.** The `verify`
  job's "annotated, signed, on main" checks are steps of `release.yml`, which runs **from the
  tagged commit**, so a tag on an unmerged commit whose copy drops them produced attestations with
  the genuine release identity (`release.yml@refs/tags/vX`) that Kyverno and `verify-release` both
  accepted. Two things now sit where a tag can't reach them: `just verify-release` (from `main`)
  re-checks the tag's signature through the API, requires its commit to be an ancestor of
  `origin/main`, and passes `--source-digest` so an attestation for another commit fails; and the
  `release-tags` ruleset adds a `creation` rule, so only the admin role can create a `v*` tag
  (`bypass_actors: [{actor_type: RepositoryRole, actor_id: 5}]`; GitHub's REST docs don't publish
  the role ids and the API returns only numbers, so: **5 is Repository admin**, read back from the
  ruleset UI after applying it on 2026-10-18. A wrong id refuses the tag push at the next
  release).
  **What's left:** an admin, and therefore any agent holding admin credentials, can still create
  such a tag; nothing in the cluster can check ancestry, so that check is the human step.
- **v0.1.0 and v0.2.0 carry provenance only.** `verify-release` fails for them on the other three
  types.

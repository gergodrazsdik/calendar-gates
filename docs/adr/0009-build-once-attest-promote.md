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
6. **approve:** the gated job. It attests the approval (`release-approved/v1`, the one attestation
   that can't exist before the gate) and publishes nothing.
7. **admission-smoke** ([ADR 0010](0010-admission-control.md)): proves Kyverno admits the release
   digest and denies an unattested image, on a throwaway cluster. It packages the chart and
   installs that tarball, and hands it on as an artifact.
8. **smoke:** runs the digest, checks `/api/version` and the contract tests. Runs beside
   admission-smoke; neither needs anything public to exist.
9. **promote:** only after both pass. The version tags (`X.Y.Z`, `X.Y`), the chart tarball the
   admission tests installed, and the GitHub Release — everything public, in one job
   (**amended 2026-10-18**, F071).

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

    The release notes print the same lists, plus the PRs **reviewed after merge** (each PR entry
    carries `reviewed_after_merge`; ADR 0005, 2026-10-24). The range starts at the previous
    **final** release
    for a final version, and at the previous release of any kind for a prerelease. PRs that only
    reached an `-rc` tag therefore still count for the final release. "Release" means a
    *published* one (amended 2026-10-23, below), not any tag.
- **Promote after approval *and* after the tests.** `promote` gives the attested digest `X.Y.Z`
  and `X.Y` with `buildx imagetools create`, and checks that both tags resolve to it. It has no
  `environment:` of its own — it can only run because the gated `approve` passed, and the approval
  is attested on the digest — so a release pauses for a person once, not twice.
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

- **Amended 2026-10-18 (F027): a planned blocking check with no record is listed as unreviewed.**
  The predicate used to report only the records that existed, so a failed artifact upload or a
  collector that gave up mid-write read as a clean release: the check was simply absent. The
  triage record's `checks_plan` says what was supposed to run, and the levels in `checks.yaml` say
  which of those block, so a missing one is named (`security-review: no record`).

- **A failed scan, smoke or admission test leaves only the candidate tag.** No version tags, chart
  or release appear. Approval comes after the scan and the attestations, so the reviewer approves
  known bytes; the tests that used to run *after* publishing now run before it, so a failure no
  longer burns the version or leaves `X.Y` pointing at bytes that failed (F071, 2026-10-18). The
  cost is that a re-run after a failed test builds new bytes and writes four more Rekor entries,
  which is the same trade-off the scan already had.
- **What a re-run means now.** After a failed `smoke` or `admission-smoke`, nothing public exists,
  so re-running the whole workflow is safe: it builds new bytes, re-attests and promotes those. The
  old warning applies only once `promote` has pushed `X.Y.Z` — from then on the version is taken,
  and a failed `promote` is fixed by re-running *that job*, not the workflow.
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
- **Amended 2026-10-23: the range starts at the last *published* release, not the nearest tag.**
  - **The bug:** `verify` used `git describe --tags`, which takes the nearest `v*` tag. A release
    that fails after tagging leaves its tag on `main` for good: the ruleset blocks deletion, and a
    version is never reused. The next release then attested only the PRs since the failed tag, and
    every PR before it fell out of all review claims.
  - **It had already happened:** v0.3.3 and v0.3.4 failed, and v0.3.5's attestation reads
    `v0.3.4..v0.3.5`. It lists only #81, though v0.3.5 was the first published release with
    #70-#81.
  - **Recomputed over v0.3.2..v0.3.5 with the same tool and audit log:** all 12 were reviewed
    (`unreviewed` empty). But #74, #75 and #78-#81 were `unverified` and missing from v0.3.5's
    signed claim and notes. No unreviewed code shipped; the claim was narrower than it read.
  - **Found with v0.4.0:** its admission-smoke correctly refused it, listing five unreviewed PRs.
    Retrying as v0.4.1 would have measured from the failed `v0.4.0` tag and dropped all five.
  - **The fix:** `scripts/previous-release.sh` returns the highest tag before the commit that has
    a non-draft GitHub Release (only final ones, for a final version). It fails rather than print
    nothing when the releases can't be listed, since an empty range would attest the whole
    history. `verify` uses it, and `just verify-release` compares every attestation's
    `range.from` with it. That check fails for v0.3.5, which is true, and passes for v0.3.6 and
    v0.3.7.

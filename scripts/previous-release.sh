#!/usr/bin/env bash
# Print the tag of the last *published* release before a commit: where the llm-review attestation's
# range starts (ADR 0009). Nothing if there is none. A final <version> is measured against the
# previous final release, so PRs released only in a prerelease count; a prerelease against any.
#
# Published means a non-draft GitHub Release. A tag alone is not enough: a release that failed
# after tagging leaves its tag on main for good (tags can't be deleted), and measuring from it
# dropped every PR before it from the next release's review claim (v0.3.5 attested v0.3.4..v0.3.5).
# Usage: previous-release.sh <commit> <version>   (needs GH_TOKEN and GITHUB_REPOSITORY, and a
# clone with tags)
set -euo pipefail

commit=${1:?usage: previous-release.sh <commit> <version>}
version=${2:?usage: previous-release.sh <commit> <version>}
repo=${GITHUB_REPOSITORY:?GITHUB_REPOSITORY not set}

# Fail rather than print nothing when the API does: an empty range attests the whole history.
filter='.[] | select(.draft | not) | .tag_name'
[[ $version == *-* ]] || filter='.[] | select((.draft or .prerelease) | not) | .tag_name'
published=$(gh api --paginate "repos/$repo/releases?per_page=100" --jq "$filter")

# Tags on main rise with versions, so the highest published tag before the commit is the nearest.
while read -r tag; do
    [[ $tag =~ ^v[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?$ ]] || continue
    if grep -qxF -- "$tag" <<< "$published"; then
        echo "$tag"
        exit 0
    fi
done < <(git tag --merged "$commit^" --list 'v*.*.*' --sort=-v:refname)

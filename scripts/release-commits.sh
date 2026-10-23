#!/usr/bin/env bash
# Print, as a JSON array oldest first, the commits on main between two refs and the merged PR of
# each: [{commit, pr, head_sha, merged_at}], with nulls for a commit no PR merged.
# `llm-gate attest llm-review` reads it (ADR 0009). With an empty <from> it lists every commit up
# to <to>.
# Usage: release-commits.sh <from-ref|""> <to-ref>   (needs GH_TOKEN and GITHUB_REPOSITORY, and
# a full clone: the commit list comes from git, the PRs from the API)
set -euo pipefail

from=${1?usage: release-commits.sh <from-ref|""> <to-ref>}
to=${2:?usage: release-commits.sh <from-ref|""> <to-ref>}
repo=${GITHUB_REPOSITORY:?GITHUB_REPOSITORY not set}

range=$to
[ -n "$from" ] && range="$from..$to"

# One API call per commit, so one dropped connection used to fail the whole list; on a flaky link
# (2026-10-24, from a WSL machine) nearly every run of 19 calls lost one. Each call is retried a
# few times, and the script still fails if one never succeeds: a commit missing from the list
# would vanish from the release's review claim.
tries=5
pulls_of() {
    local sha=$1 try
    for try in $(seq "$tries"); do
        if gh api "repos/$repo/commits/$sha/pulls" \
            --jq "[.[] | select(.merged_at and .merge_commit_sha == \"$sha\")][0]
                  | {commit: \"$sha\", pr: (.number // null), head_sha: (.head.sha // null),
                     merged_at: (.merged_at // null)}"; then
            return 0
        fi
        [ "$try" = "$tries" ] || sleep $((try * 2))
    done
    echo "release-commits.sh: the pull requests of $sha could not be read after $tries tries" >&2
    return 1
}

# --first-parent: the commits main itself got (squash merges), not the history of merged branches.
git rev-list --reverse --first-parent "$range" | while read -r sha; do
    [[ $sha =~ ^[0-9a-f]{40}$ ]] || continue
    pulls_of "$sha"
done | jq -s .

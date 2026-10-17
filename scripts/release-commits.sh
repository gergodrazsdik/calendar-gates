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

# --first-parent: the commits main itself got (squash merges), not the history of merged branches.
git rev-list --reverse --first-parent "$range" | while read -r sha; do
    [[ $sha =~ ^[0-9a-f]{40}$ ]] || continue
    gh api "repos/$repo/commits/$sha/pulls" \
        --jq "[.[] | select(.merged_at and .merge_commit_sha == \"$sha\")][0]
              | {commit: \"$sha\", pr: (.number // null), head_sha: (.head.sha // null),
                 merged_at: (.merged_at // null)}"
done | jq -s .

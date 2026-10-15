#!/usr/bin/env bash
# Create or update the one PR comment that starts with a hidden marker (sticky comment).
# Usage: upsert-pr-comment.sh [--update-only] <pr-number> <marker> <body-file>
#   --update-only  edit an existing comment but don't create one (for "not applicable" results)
# Needs GH_TOKEN (pull-requests: write) and GITHUB_REPOSITORY.
set -euo pipefail

update_only=false
if [[ ${1:-} == --update-only ]]; then
    update_only=true
    shift
fi
pr=${1:?usage: upsert-pr-comment.sh [--update-only] <pr-number> <marker> <body-file>}
marker=${2:?marker missing}
body_file=${3:?body file missing}
repo=${GITHUB_REPOSITORY:?GITHUB_REPOSITORY not set}

[[ $pr =~ ^[0-9]+$ ]] || { echo "not a PR number: $pr" >&2; exit 2; }

# GitHub rejects comment bodies over 65536 characters.
body=$(head -c 60000 "$body_file")
if (($(wc -c < "$body_file") > 60000)); then
    body+=$'\n\n_(truncated; the full report is in the job summary)_'
fi

# The marker goes to jq as data (--arg), never spliced into the filter.
# --paginate prints one array per page; -s collects them, and jq picks the first match.
id=$(gh api --paginate "repos/$repo/issues/$pr/comments" |
    jq -rs --arg marker "$marker" \
        '[.[][] | select(.user.type == "Bot" and (.body | startswith($marker))) | .id] | first // empty')

if [[ -n $id ]]; then
    gh api -X PATCH "repos/$repo/issues/comments/$id" --silent -f body="$body"
    echo "updated comment $id"
elif [[ $update_only == false ]]; then
    gh api -X POST "repos/$repo/issues/$pr/comments" --silent -f body="$body"
    echo "created a comment"
else
    echo "no existing comment to update"
fi

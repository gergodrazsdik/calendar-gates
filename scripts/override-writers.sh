#!/usr/bin/env bash
# Print, as a JSON array, the authors of `/llm-override` comments in a PR's comment list who have
# write, maintain or admin access to the repository (ADR 0007). find_override honours a
# llm-override label added by the feedback workflow only for these people; author_association
# alone (MEMBER, COLLABORATOR) doesn't say whether someone may write.
# Usage: override-writers.sh <comments.json>   (needs GH_TOKEN and GITHUB_REPOSITORY)
set -euo pipefail

comments=${1:?usage: override-writers.sh <comments.json>}
repo=${GITHUB_REPOSITORY:?GITHUB_REPOSITORY not set}

jq -r '.[] | select(.body | ltrimstr(" ") | startswith("/llm-override")) | .user.login' "$comments" \
    | sort -u | while read -r login; do
        [[ $login =~ ^[A-Za-z0-9-]{1,39}$ ]] || continue # a user login; bots can't override
        role=$(gh api "repos/$repo/collaborators/$login/permission" --jq .role_name 2> /dev/null \
            || echo none)
        case "$role" in admin | maintain | write) echo "$login" ;; esac
    done | jq -R . | jq -s .

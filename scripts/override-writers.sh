#!/usr/bin/env bash
# Print, as a JSON array, the authors of `/llm-*` command comments in a PR's comment list who have
# write, maintain or admin access to the repository (ADR 0007). Two callers need this: find_override
# honours an llm-override label added by the feedback workflow only for these people, and the
# collector accepts a `/llm-risk` record only from one of them (ADR 0008). author_association alone
# (MEMBER, COLLABORATOR) doesn't say whether someone may write.
#
# Every `/llm-` command, not only `/llm-override`: filtering to override comments made the
# collector reject a legitimate `/llm-risk` on a PR that had no override, which turned its whole
# run into tamper events (v0.3.2's attestation shows that for #68). find_override is unaffected by
# the wider list, because it still requires an unedited `/llm-override <reason>` comment from the
# person. The file keeps its name: llm-review.yml comes from the PR under review while the scripts
# come from the base branch (ADR 0004), so renaming it needs a PR of its own.
# Usage: override-writers.sh <comments.json>   (needs GH_TOKEN and GITHUB_REPOSITORY)
set -euo pipefail

comments=${1:?usage: override-writers.sh <comments.json>}
repo=${GITHUB_REPOSITORY:?GITHUB_REPOSITORY not set}

jq -r '.[] | select(.body | ltrimstr(" ") | startswith("/llm-")) | .user.login' "$comments" \
    | sort -u | while read -r login; do
        [[ $login =~ ^[A-Za-z0-9-]{1,39}$ ]] || continue # a user login; bots can't run commands
        role=$(gh api "repos/$repo/collaborators/$login/permission" --jq .role_name 2> /dev/null \
            || echo none)
        case "$role" in admin | maintain | write) echo "$login" ;; esac
    done | jq -R . | jq -s .

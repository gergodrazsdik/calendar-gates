# calendar-gates: the single entry point, locally and in CI. `just` lists the recipes.

repo := "gergodrazsdik/calendar-gates"

# List recipes
default:
    @just --list

# Restore local .NET tools (git hooks get installed here from Phase 4 on)
[group('dev')]
setup:
    dotnet tool restore

# Apply repo settings: merge rules, Actions defaults, security features, secret, variables, release environment
[group('github')]
[confirm('Apply settings to github.com/gergodrazsdik/calendar-gates?')]
gh-setup:
    #!/usr/bin/env bash
    set -euo pipefail
    repo={{ repo }}
    gh repo edit "$repo" --enable-squash-merge --enable-merge-commit=false \
        --enable-rebase-merge=false --delete-branch-on-merge --enable-auto-merge
    gh api -X PATCH "repos/$repo" --silent \
        -f squash_merge_commit_title=PR_TITLE -f squash_merge_commit_message=PR_BODY
    gh api -X PUT "repos/$repo/actions/permissions/workflow" --silent \
        -f default_workflow_permissions=read -F can_approve_pull_request_reviews=false

    # Dependabot alerts + security updates, private vulnerability reporting, secret scanning + push protection
    gh api -X PUT "repos/$repo/vulnerability-alerts" --silent
    gh api -X PUT "repos/$repo/automated-security-fixes" --silent
    gh api -X PUT "repos/$repo/private-vulnerability-reporting" --silent
    gh api -X PATCH "repos/$repo" --silent --input - <<'JSON'
    {"security_and_analysis": {
      "secret_scanning": {"status": "enabled"},
      "secret_scanning_push_protection": {"status": "enabled"}}}
    JSON

    pass show api/anthropic-calendar-gates | gh secret set ANTHROPIC_API_KEY -R "$repo"
    gh variable set LLM_MODEL -R "$repo" --body claude-sonnet-5-5
    gh variable set LLM_MODEL_CHEAP -R "$repo" --body claude-haiku-5-5

    # Environment `release`: you as required reviewer, self-review allowed (solo repo), tags v* only
    uid=$(gh api user --jq .id)
    gh api -X PUT "repos/$repo/environments/release" --silent --input - <<JSON
    {"prevent_self_review": false,
     "reviewers": [{"type": "User", "id": $uid}],
     "deployment_branch_policy": {"protected_branches": false, "custom_branch_policies": true}}
    JSON
    if ! gh api "repos/$repo/environments/release/deployment-branch-policies" \
        --jq '.branch_policies[] | select(.type == "tag") | .name' | grep -qx 'v\*'; then
        gh api -X POST "repos/$repo/environments/release/deployment-branch-policies" --silent \
            -f name='v*' -f type=tag
    fi
    echo "Done. CodeQL default setup: run 'just gh-codeql' once there is C# and Python code (Phase 2+)."

# Turn on CodeQL default setup (languages are detected from the repo, so run it once code exists)
[group('github')]
[confirm('Enable CodeQL default setup on github.com/gergodrazsdik/calendar-gates?')]
gh-codeql:
    gh api -X PATCH repos/{{ repo }}/code-scanning/default-setup -f state=configured

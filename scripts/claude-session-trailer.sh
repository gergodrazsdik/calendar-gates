#!/usr/bin/env bash
# prepare-commit-msg hook (lefthook): a commit made from a Claude Code session gets a
# `Claude-Session: <id>` trailer. The id names the session's local tool-call log,
# ~/.local/state/calendar-gates/claude-audit/<id>.jsonl (.claude/hooks/session-audit.sh,
# docs/PLAN-v2.md 14.6). Claude Code sets CLAUDECODE=1 and CLAUDE_CODE_SESSION_ID in the shells
# it starts; commits made by people get no trailer.
# Usage: scripts/claude-session-trailer.sh <message file> [<source>]
set -euo pipefail

msg_file=$1
source=${2:-}

[ "${CLAUDECODE:-}" = 1 ] || exit 0
session=${CLAUDE_CODE_SESSION_ID:-}
[[ $session =~ ^[A-Za-z0-9-]{1,64}$ ]] || exit 0
case "$source" in
    merge | squash) exit 0 ;; # generated messages; the commits they combine carry their own
esac

git interpret-trailers --in-place --if-exists replace \
    --trailer "Claude-Session: $session" "$msg_file"

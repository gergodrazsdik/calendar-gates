#!/usr/bin/env bash
# Conventional Commit check for a commit message file (lefthook commit-msg: {1}) or, with
# --title, for a single line (the PR title check in CI uses the same rule).
# Usage: check-commit-msg.sh <message-file> | check-commit-msg.sh --title "<title>"
set -euo pipefail

types='build|chore|ci|docs|feat|fix|perf|refactor|revert|style|test'
pattern="^($types)(\([a-z0-9._/-]+\))?!?: [^ ].*$"
max_length=100

title=false
if [[ ${1:-} == --title ]]; then
    title=true
    header=${2:?usage: check-commit-msg.sh --title "<title>"}
else
    header=$(head -n 1 "${1:?usage: check-commit-msg.sh <message-file>}")
fi

# Leave git's own messages alone: merges, reverts, and fixup!/squash! for later autosquash.
# A PR title gets no such pass: it becomes the squash commit on main, where "Merge ..." or
# "fixup! ..." is exactly what the gate is there to stop.
if [[ $title == false && $header =~ ^(Merge |Revert \"|fixup! |squash! |amend! ) ]]; then
    exit 0
fi

if [[ ! $header =~ $pattern ]]; then
    cat >&2 <<EOF
Not a Conventional Commit: "$header"
Expected: <type>[(scope)][!]: <description>
  types: ${types//|/, }
  e.g.   feat(api): add /api/leap endpoint
         fix!: return 400 for reversed workday ranges
EOF
    exit 1
fi

if ((${#header} > max_length)); then
    echo "Header is ${#header} characters; keep it at most $max_length." >&2
    exit 1
fi

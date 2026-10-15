#!/usr/bin/env bash
# PostToolUse hook (Edit|Write): format edited C# files with the repo's CSharpier.
# Reads the hook JSON on stdin; silent no-op for anything that isn't a .cs file.
set -euo pipefail

file=$(jq -r '.tool_input.file_path // empty')
[[ $file == *.cs && -f $file ]] || exit 0

cd "${CLAUDE_PROJECT_DIR:-.}"
if ! out=$(dotnet csharpier format "$file" 2>&1); then
    printf 'csharpier failed on %s:\n%s\n' "$file" "$out" >&2
    exit 2
fi

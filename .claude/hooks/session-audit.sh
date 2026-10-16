#!/usr/bin/env bash
# PostToolUse / PostToolUseFailure hook: append one line per tool call of this Claude Code session
# to ~/.local/state/calendar-gates/claude-audit/<session_id>.jsonl, outside the repository
# (docs/PLAN-v2.md 14.6). A commit made from the session carries a `Claude-Session: <id>` trailer
# (scripts/claude-session-trailer.sh), which leads back to this log. Purely local.
#
# Logged: time, event, tool, a short summary of the input (command, path or pattern), redacted
# and cut to 200 characters. Never the tool's output. The hook never blocks the session: any
# failure is swallowed and it exits 0.
set -uo pipefail

umask 077 # the log can hold commands and paths: only the user can read it
dir="${XDG_STATE_HOME:-$HOME/.local/state}/calendar-gates/claude-audit"
input=$(cat) || exit 0
session=$(jq -r '.session_id // empty' <<< "$input" 2> /dev/null) || exit 0
[[ $session =~ ^[A-Za-z0-9-]{1,64}$ ]] || exit 0 # it becomes a file name
mkdir -p "$dir" 2> /dev/null || exit 0

# shellcheck disable=SC2016  # $i, $root and $ts are jq variables
jq -c --arg ts "$(date -u +%Y-%m-%dT%H:%M:%SZ)" --arg root "${CLAUDE_PROJECT_DIR:-}/" '
  # The patterns of tools/llm-gate/src/llm_gate/redact.py that fit in a tool input.
  def redact:
    gsub("sk-ant-[A-Za-z0-9_-]{20,}"; "[REDACTED]")
    | gsub("gh[pousr]_[A-Za-z0-9]{36,}"; "[REDACTED]")
    | gsub("github_pat_[A-Za-z0-9_]{22,}"; "[REDACTED]")
    | gsub("(A3T[A-Z0-9]|AKIA|ASIA|ABIA|ACCA)[A-Z0-9]{16}"; "[REDACTED]")
    | gsub("-----BEGIN[A-Z ]*PRIVATE KEY-----"; "[REDACTED]")
    | gsub("bearer\\s+[A-Za-z0-9._~+/=-]{16,}"; "Bearer [REDACTED]"; "i")
    | gsub("://[^/\\s:@]+:[^/\\s@]+@"; "://[REDACTED]@")
    | gsub("(api[_-]?key|secret|token|passw(or)?d)[\"'"'"']?\\s*[=:]\\s*[\"'"'"']?[^\\s\"'"'"',}]{8,}"; "[REDACTED]"; "i");
  def clip: if length > 200 then .[0:199] + "…" else . end;
  def relative: if $root == "/" then . else split($root) | join("") end;  # project paths, relative
  .tool_input as $i
  | {
      ts: $ts,
      event: .hook_event_name,
      tool: .tool_name,
      input: (
        (if .tool_name == "Bash" then $i.command
         elif $i.file_path then $i.file_path
         elif .tool_name == "Grep" then "\($i.pattern) \($i.path // "")"
         elif $i.pattern then $i.pattern
         elif $i.url then $i.url
         elif $i.description then $i.description
         else ($i | keys? // [] | join(","))
         end) // "" | tostring | relative | redact | clip
      )
    }' <<< "$input" >> "$dir/$session.jsonl" 2> /dev/null
exit 0

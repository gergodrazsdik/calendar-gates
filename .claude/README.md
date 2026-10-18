# `.claude/` in this repository

| File | What |
|---|---|
| `settings.json` | Permissions and hooks for Claude Code sessions in this repo (checked in) |
| `settings.proposed.json` | How a change to `settings.json` is handed over — see below (none pending) |
| `settings.local.json` | Per-machine, gitignored: turns the Claude Code sandbox on |
| `commands/` | The review prompts the LLM gate runs, and `/new-endpoint`, `/gate-drill` (ADR 0004) |
| `agents/`, `hooks/` | The `gate-debugger` subagent; the CSharpier and session-audit hooks |

## Changing `settings.json`

The sandbox denies writes to `settings.json` — an agent must not be able to widen its own
permissions — so an agent proposes the new file and a person applies it:

```sh
mv .claude/settings.proposed.json .claude/settings.json   # after reading the diff
```

That is how F045 landed: `Bash(gh run *)` is now `view`/`list`/`watch`/`download` only, so
`gh run delete|cancel|rerun` asks first. `just`, `dotnet` and `uv run` were left alone on purpose —
they run arbitrary project code by design, so no allow-list shape makes the deny rules airtight.
`docs/gates.md` ("What the agent's permissions do and don't buy you") says what actually bounds a
session here.

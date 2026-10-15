@AGENTS.md

## Claude Code specifics

- Slash commands in `.claude/commands/`: `/new-endpoint <name>` scaffolds an endpoint with its tests
  and `.http` request; `/gate-drill <n>` sets up one of the drills from `docs/PLAN.md` Phase 12.
  The review prompts (`/code-review`, `/security-review`, ...) arrive in Phase 7 and are the same
  files the CI LLM gate uses, so edit them as carefully as code.
- Subagent `gate-debugger`: give it a failed run (URL or id) and it finds the failing gate and the fix.
- A PostToolUse hook runs CSharpier on every `.cs` file you edit, so don't format by hand.
- Use plan mode for changes to workflows, rulesets or `checks.yaml`: they change what is enforced.
- Personal notes go in `CLAUDE.local.md` (gitignored).

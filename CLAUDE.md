@AGENTS.md

## Claude Code specifics

- Slash commands in `.claude/commands/`: `/new-endpoint <name>` scaffolds an endpoint with its tests
  and `.http` request; `/gate-drill <n>` sets up one of the drills from `docs/PLAN.md` Phase 12.
  The review prompts `/llm-code-review`, `/llm-security-review`, `/llm-test-review`,
  `/llm-api-contract`, `/llm-workflow-review` and `/llm-docs-drift` are the files the LLM gate
  runs (`tools/llm-gate/checks.yaml`), so edit them as carefully as code. They are prefixed
  `llm-` so they don't shadow the built-in `/code-review` and `/security-review`.
- Subagent `gate-debugger`: give it a failed run (URL or id) and it finds the failing gate and the fix.
- A PostToolUse hook runs CSharpier on every `.cs` file you edit, so don't format by hand.
- Use plan mode for changes to workflows, rulesets or `checks.yaml`: they change what is enforced.
- Personal notes go in `CLAUDE.local.md` (gitignored).

# 4. The review gate runs from the base branch; the PR is only data

- Status: accepted
- Date: 2026-10-16
- Supersedes: the "runs the prompt as a slash command" part of [ADR 0002](0002-llm-gate-policy.md)

## Context

In v1 `llm-review.yml` checked out the PR and ran everything from it: `tools/llm-gate`, `checks.yaml`
and the prompts. A PR could therefore soften a prompt, turn a blocking check advisory or make
`policy.py` return "pass", and be reviewed by its own edit. Only collaborators can open PRs here, so
outsiders were not the concern; the likely case is an agent (or a tired human) changing the gate in
the same PR it then reviews.

A second hole was not in the trust model at all. The agent engine ran with
`setting_sources=["project"]`, which loads the reviewed repository's `CLAUDE.md` (and `AGENTS.md`
through `@AGENTS.md`), rules, commands and settings into the reviewer. `disableAllHooks` stopped
hooks, not instructions. Measured on 2026-10-16: with a planted `CLAUDE.md` telling reviewers to
approve, the v1 configuration reported no findings on an obvious bug; with nothing loaded it found it.

## Decision

- `llm-review.yml` and `llm-compare.yml` check out **twice**: the PR's base commit into `gate/`
  (tooling, `checks.yaml`, prompts, the comment script) and the PR head into `src/`
  (`persist-credentials: false`), and run
  `llm-gate --repo src --config gate/tools/llm-gate/checks.yaml …`.
- `llm-gate --repo` names the repository under review (diff, agent context); the config and prompts
  come from the checkout that holds `--config`. Locally both are the same repository.
- The agent engine no longer runs a slash command. It gets the prompt text from the gate checkout
  with the diff inline (as the API engine does), `setting_sources=[]`, no skills, no MCP servers,
  `disableAllHooks`, auto memory off, read-only tools, `cwd=src/`. The reviewed repository's files
  are data it may read, never instructions it receives.
- The diff is wrapped in one `<diff>` element; a `</diff` inside the diff is escaped so it can't
  close the element early.
- A PR that changes the gate is still tested: `lint` runs its pytest, and `llm-eval` (Phase 15) runs
  its prompts. It just doesn't review itself. Interactive use is unchanged: `/llm-code-review` in
  Claude Code still runs the same prompt file.

- **Amended 2026-10-18 (F003): it also covers *which files* the reviewer may read.** "The reviewed
  repository's files are data it may read" was unbounded in the direction that matters: the engine
  passed bare `Read`, `Grep` and `Glob` in `allowed_tools`, and a bare tool name is a whole-tool
  allow rule that the CLI honours *before* it checks the path, so an "ask" for a path outside the
  checkout became an "allow". The reviewer's own process environment holds the API key. The reads
  are now fenced three ways: `permissions.blockReadsOutsideWorkingDirectories` and
  `Read(//proc/**)`-style deny rules in the inline settings, a path-scoped `Read(./**)` allow rule
  instead of the bare one, and the engine's `PreToolUse` callback, which refuses anything it can't
  place inside the checkout. The callback is the *backstop*, not the authority: a hook that raises
  or times out yields no decision and the call proceeds, so the CLI setting is the primary control
  and the hook is what records the refusal. A refusal never fails the check — the review goes on
  with the diff it already has — because a verdict that text in the PR's files can trigger is a
  verdict the PR author controls.
- **Amended 2026-10-18**: the principle covers the **attributes** too. `git diff` reads
  `.gitattributes` from the working tree, so the PR-head checkout decided what the reviewers could
  see until the diff was built with `git --attr-source=<base>` (F001). Exclusions live in
  `diff.EXCLUDES` on the base branch, not in a file the PR writes.
- **Amended 2026-10-16**: "the base commit" is the base branch's head when the run starts
  (pinned once by the plan job and passed to every check; that job is `triage` since Phase 17,
  [ADR 0008](0008-risk-triage.md)), not the PR's `base.sha`. GitHub doesn't
  move `base.sha` when the base branch moves on, so a PR opened before a gate fix kept running the
  old gate: drill PR #31 still reviewed with the tooling from before #32. The audit record's
  `gate_sha` says which commit it was.

## Consequences

- A change to the gate takes effect for the PRs **after** it merges. The PR that changes the gate is
  reviewed by the previous version.
- **Remaining hole**: on `pull_request` the workflow file itself comes from the PR, so a PR can edit
  `llm-review.yml` (for example, drop the base checkout). Mitigations in v2: triage makes any
  `.github/**` change high risk (Phase 17), `workflow-review` runs, the audit collector marks such
  runs `workflow_modified` (Phase 14) and the release review attestation lists them as unverified
  (Phase 18). Closing it fully needs workflows enforced from outside the repository (organization
  "required workflows" rulesets), which a personal repository doesn't have.

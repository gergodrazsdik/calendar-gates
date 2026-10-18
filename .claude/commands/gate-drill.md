---
description: Set up a gate drill (docs/PLAN.md Phase 12, docs/PLAN-v2.md) on its own branch and PR
argument-hint: <drill number>
---

Set up gate drill $ARGUMENTS from the "Gate drills" table in `docs/PLAN.md` (Phase 12, drills 1 to
13), or for drills 14 and up, the drill table in `docs/PLAN-v2.md`.

1. Read the drill's row. If the gate it targets doesn't exist yet (its phase isn't done), say so
   and stop.
2. Tell me in one or two sentences what you will change and which gate should catch it. Wait for
   my OK before touching anything that pushes, force-pushes, deletes tags or changes GitHub
   settings (drills 7, 8, 9 and 11 do).
3. Create a branch `drill/<n>-<short-name>` from an up-to-date `main`.
4. Make the smallest change that trips the gate. Deliberately broken code is allowed here; don't
   "fix" the drill. Edit `.cs` files with a shell command, not the editor tools: the CSharpier
   hook in `.claude/settings.json` would format the planted mistake away.
5. Get it to GitHub with a Conventional Commit message starting `test(drill):`. If a local hook
   would fix or block it (formatting, failing tests before push, actionlint), don't bypass the
   hook: `--no-verify` is never allowed on this machine. Commit through the GitHub API instead:
   `scripts/commit-via-api.py drill/<n>-<name> "test(drill): ..." <files>` (workflow files need a
   gh token with the `workflow` scope), then restore the working tree. Otherwise commit and push
   normally. Open a draft PR titled `test(drill): <n> <short description>` whose body says
   "Gate drill, do not merge" and which gate is expected to fail.
6. Give me the PR URL and what to watch for. Once the run finishes, check it with
   `gh pr checks` and tell me whether the gate behaved as the table predicts.

Triage drills (17, 18; ADR 0008): your commits and PR body carry AI markers, which raise the risk
one level. Where a drill needs a PR *without* them (drill 17's `risk:low`, the first half of 18),
prepare the change and let me commit, push and open the PR myself.

Don't close the PR or delete the branch; I do that after looking at it.

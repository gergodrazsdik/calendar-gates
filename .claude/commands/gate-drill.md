---
description: Set up a gate drill (docs/PLAN.md Phase 12) on its own branch and PR
argument-hint: <drill number>
---

Set up gate drill $ARGUMENTS from the "Gate drills" table in `docs/PLAN.md` (Phase 12).

1. Read the drill's row. If the gate it targets doesn't exist yet (its phase isn't done), say so
   and stop.
2. Tell me in one or two sentences what you will change and which gate should catch it. Wait for
   my OK before touching anything that pushes, force-pushes, deletes tags or changes GitHub
   settings (drills 7, 8, 9 and 11 do).
3. Create a branch `drill/<n>-<short-name>` from an up-to-date `main`.
4. Make the smallest change that trips the gate. This is the one place where `--no-verify` and
   deliberately broken code are allowed; don't "fix" the drill.
5. Commit with a Conventional Commit message starting `test(drill):`, push, and open a draft PR
   titled `test(drill): <n> <short description>` whose body says "Gate drill, do not merge" and
   which gate is expected to fail.
6. Give me the PR URL and what to watch for. Once the run finishes, check it with
   `gh pr checks` and tell me whether the gate behaved as the table predicts.

Don't close the PR or delete the branch; I do that after looking at it.

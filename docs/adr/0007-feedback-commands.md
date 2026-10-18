# 7. Feedback on the gate comes from PR comment commands, handled on the default branch

- Status: accepted
- Date: 2026-10-16

## Context

The gate's false-positive rate is unknown unless people say which findings were wrong (and
which were right). Overrides had to be a label plus a separately written comment. Both are best
done where the review is read: in the PR conversation. But anyone can comment on a public
repository's PRs, and the audit log the feedback goes into is permanent.

## Decision

- `llm-feedback.yml` runs on `issue_comment` for PR comments that start with `/llm-`. GitHub runs
  that event's workflow from the **default branch**, and the job never checks out the PR. So the
  code that decides what counts as feedback can't be changed by the PR it's about.
- The comment is untrusted input. `llm-gate feedback handle` reads it from the event file, parses
  only its first line, and returns validated values (ids, logins, paths) that the workflow uses
  through `env`. Reasons are redacted and capped like every other free-text field.
- **Only people with write access are heard.** The job doesn't start for comments whose
  `author_association` isn't OWNER, MEMBER or COLLABORATOR, so outsiders cost no write-token run
  and leave no trace in the log. Within it, the commenter's actual repository role
  (`collaborators/<login>/permission`) must be write, maintain or admin: MEMBER and COLLABORATOR
  don't imply write access. A collaborator without it, or a command that doesn't parse, gets a
  `feedback_rejected` record with fixed fields only (login, command, a reason code).
- `/llm-fp` and `/llm-ack` must name a finding the audit log has for this PR. `/llm-override`
  records an `override`, adds the label, and re-runs the PR's latest `llm-review` run: labels
  added with `GITHUB_TOKEN` start no workflows. `llm-review` reads the PR's labels from the API,
  because a re-run keeps the original event's payload. `find_override` honours a label only when
  the `/llm-override <reason>` came from someone with write access, whether the label was added by
  `github-actions[bot]` or by hand (`scripts/override-writers.sh` looks the roles up for
  `llm-review` and the collector; applying a label needs only the triage role, so the label alone
  says nothing, F007).

## Consequences

- **Amended 2026-10-18 (F026): a command for a run that isn't collected yet is answered, not
  recorded.** A finding's id is in the sticky comment as soon as its check finishes, but the
  collector runs on `workflow_run: completed` and then needs a run of its own, so a `/llm-fp`
  posted in that window used to become a permanent `feedback_rejected` with `unknown_finding`.
  When the log holds no review of the PR at all, the workflow reacts 👀, says so in a comment and
  writes nothing. Ids are still only ever resolved against the audit log.

- The plan recorded outsiders' commands as `feedback_rejected` too. They're filtered out before the
  job starts instead: a permanent public log shouldn't grow with every stranger's comment, and a
  write-token run shouldn't start for one.
- A false positive is two clicks away from becoming an eval case (`eval add-from-fp`), so the
  evals grow from real mistakes.
- The feedback workflow holds write tokens (contents, issues, actions). It's safe because it runs
  only default-branch code on parsed input; a change to it is a workflow change and goes through
  review like any other.
- Collaborators are trusted with overrides by comment, as they were with the label. A team
  repository would restrict `/llm-override` to maintainers.
- The sticky comment's false-positive mark lasts until the next review run rewrites the comment.
  The record stays in the log.

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
- **Only collaborators are heard** (`author_association` OWNER, MEMBER or COLLABORATOR). Anyone
  else gets a `feedback_rejected` record with fixed fields only (login, command, a reason code),
  at most one per PR, person and day (a unique file name the contents API won't overwrite), and
  no reaction. Outsiders can't write text into the log, or flood it.
- `/llm-fp` and `/llm-ack` must name a finding the audit log has for this PR. `/llm-override`
  records an `override`, adds the label, and re-runs the PR's latest `llm-review` run: labels
  added with `GITHUB_TOKEN` start no workflows. `llm-review` reads the PR's labels from the API,
  because a re-run keeps the original event's payload. `find_override` accepts a label added by
  `github-actions[bot]` when a collaborator wrote the `/llm-override <reason>`.

## Consequences

- A false positive is two clicks away from becoming an eval case (`eval add-from-fp`), so the
  evals grow from real mistakes.
- The feedback workflow holds write tokens (contents, issues, actions). It's safe because it runs
  only default-branch code on parsed input; a change to it is a workflow change and goes through
  review like any other.
- Collaborators are trusted with overrides by comment, as they were with the label. A team
  repository would restrict `/llm-override` to maintainers.
- The sticky comment's false-positive mark lasts until the next review run rewrites the comment.
  The record stays in the log.

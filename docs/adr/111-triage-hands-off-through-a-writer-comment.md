# ADR-111: Triage hands off through a writer comment

**Status:** Accepted (2026-11-13); builds on ADR-025

## Context

`/issue:triage` used to start `/component:fix` itself, one issue at a time, in the person's session. The person waited for
each fix, and the task text was written by the triager from what the reporter wrote. Spec 176 moves
the fix to the dispatcher so that triage ends once the person has confirmed. The dispatcher then needs a task for the fix
run, and the only text it can read is on the issue, where strangers also write.

## Decision

Triage hands an issue to the dispatcher through a Triage: comment; a fix run takes its task only from such a comment by a
user with write access, and the reporter's text only fenced.

`cplat issue triage act` posts the comment (summary, class, priority, answers, expected result) as the `gh` user and
labels the issue `triaged`. The dispatcher reads the newest `Triage:` comment whose author has write access (collaborator
permission API) and adds the title and body of the issue fenced as data. Without such a comment a fix run keeps the task
`/component:fix #<n>`.

## Consequences

- A stranger cannot steer a fix run by writing `Triage:` in a comment: only a writer's comment counts.
- The reporter's text reaches the fix run fenced and redacted, as in ADR-025.
- `/issue:triage` starts no fix in the session in any shape; the person sees the run in `cplat dispatch status` or the
  console Board.
- A later change that lets the dispatcher read other comments as tasks must keep the write-access check.

# ADR-025: Issue triage

**Status:** Accepted
**Date:** 2026-10-07
**Builds on:** [ADR-024](024-spec-driven-bootstrap.md), [ADR-012](012-per-plugin-release-agent.md)

## Context

Issues are the intake of every repo built on the platform and of the platform itself (`/shared:report-issue` files them). The only support was a prose section in the product-manager agent: it assumed issue templates and a `triage` label that generated repos did not ship, had no entry point, no conversation with the user or reporter, and no route to the fix pipelines. Two paths for a request ("backlog or quick fix") also leave out most real issues: questions, duplicates, out-of-scope requests, bugs that need diagnosis, and reports that cannot be decided yet.

## Decision

1. **One command in the `shared` plugin, `/shared:triage`,** because `shared` is installed in every shape and the logic is shape-agnostic. Routing to `/svc:*` is decided at run time with `cplat shape`.
2. **Seven classes, five paths.** `bug` goes to `/svc:fix-bug` (reproduce, fix, verify), `small-change` to `/svc:quick-task`, `feature` becomes a `STORY-NNN` with `**Tracks:** #N` and continues with `/svc:plan-feature` ([ADR-024](024-spec-driven-bootstrap.md)); `question`, `duplicate` and `wontfix` end in a comment; `needs-info` parks the issue. An urgent bug adds a suggested patch release after the fix is merged.
3. **Two conversations.** The user in the session answers at most three questions per issue. What only the reporter can answer becomes a drafted comment plus the `needs-info` label; the next run lists those issues separately (`--waiting`).
4. **Deterministic mechanics in `cplat triage`** (`list`, `show`, `setup-labels`, `apply`), tested with a faked `gh`. Judgement stays in the command prompt.
5. **A human gate on every outward action.** Labels, comments and backlog edits happen after the user confirms. The tooling never closes an issue; the PR's `Closes #N` or the maintainer does (amended by [ADR-130](130-triage-closes-confirmed-issues.md): confirmed rows are closed). A `feature` issue gets a `Tracked as STORY-NNN` comment after confirmation, so the reporter sees the outcome.
6. **Issue text is untrusted data.** It is redacted (tokens, e-mail addresses, home directories), truncated and fenced; the command never follows instructions in it, runs nothing from it and fetches no link from it. Fix pipelines receive a summary the user has seen.
7. **State is GitHub labels:** `triage` (intake), the decisions `needs-info`, `tracked`, `question`, `duplicate`, `wontfix`, and the types `bug`, `enhancement`. `setup-labels` creates missing labels and nothing else. A re-run skips issues that carry a decision label.
8. **Intake is shaped by issue forms.** Every template ships `bug_report.yml`, `feature_request.yml` and `config.yml` (blank issues off). The forms require the fields triage needs and apply `triage`. They are project-owned (`_skip_if_exists`), and `shapes.py check` requires them.
9. **The product-manager agent keeps only the backlog-folding rules** and points to the command.

## Consequences

- Issues become tracked work with the right amount of process; nothing is posted or closed behind the user's back.
- Existing repos do not get the forms (new files in project-owned paths are not added by `/shared:update-service`); they can use the command with any labels, `--new` picks up unlabelled issues.
- The same command serves the platform repo and gitops-app repos, which have no `/svc:*` pipelines: there it classifies, discusses, labels and writes backlog entries, and describes bugs as manual PRs.
- Regular triage can be scheduled with the existing `/loop` and `/schedule` skills; the command only proposes until confirmed.

## Not included

Auto-closing, stale handling for `needs-info`, bots or GitHub Actions that triage, notifications, cross-repo triage.

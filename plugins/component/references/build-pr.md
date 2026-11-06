# Build: the pull request and the final report

Read from `/component:build` Phase 7 (the PR body template is also the one `/component:ship` Phase `pr` uses).

## PR body

Write it with the Write tool to `.pr-body.md` in the repo root (never into `.git/`). `{{CLOSES}}` stands where the issue lines go; `cplat pr open` fills them from the spec's `tracks:` and the branch's commits.

```markdown
## Summary

<3–5 sentences: the problem from the spec, what was built, how a user or operator uses it — endpoints, flags, config, responses.>

**Spec:** [docs/specs/<spec_id>/spec.md](docs/specs/<spec_id>/spec.md) · **Plan:** plan.md · **Verification:** verification.md

| Criterion | Verdict | Test |
|---|---|---|
<one row per criterion, copied from verification.md>

## Type of change

- [x] feat — new user-visible feature

## Related issues

{{CLOSES}}

## Testing done

<acceptance tests per criterion; N tests total, X% coverage; security PASS/WARN>

<output of `cplat deps report`: the "Dependency patches" section, after the criteria table; empty when nothing was bumped>

## Checklist

- [x] Acceptance tests were written from the approved spec before the code
- [x] `devbox run quality` passes
- [x] `devbox run test` passes with coverage ≥ 80%
- [x] `devbox run security` passes (fixable dependency findings patched, see Dependency patches)
- [x] No secrets, credentials, or API keys committed
```

## Open it

One Bash call; it commits what is left with `-s`, pushes the feature branch, opens the PR, adds "Contains WIP commits from an interrupted build: squash-merge." to the body when the branch has `wip(` commits (spec 047), plus the run's generated "How this was built" block (spec 133; never edit it):

```bash
cplat pr open --spec <spec_id> --title "feat(<scope>): <spec title, ≤72 chars>" [--no-spec]
```

Relay its three lines (`commit:`, `push:`, `pr:`). Exit 1: report the failed part and stop; `pr: failed: already open <url>` means the PR exists, so use that URL. Exit 2: fix the reason it prints, then call it again. A re-run never makes a second commit or PR.

**`pr: ready: <command>`** (headless run, untrusted workspace, or `gh pr create` not allowed; spec 051) is not an error: the branch is pushed and cplat has moved the body to `.git/PR_BODY.md`. End the report with that exact command as its last line.

## Final Report

```
## Build complete: <spec_id> — <title>

| Phase | Output |
|---|---|
| Acceptance tests | <n> tests for <m> criteria, red at <short sha> |
| Implementation | <n> tasks (<p> parallel, <s> sequential), <files> files[ · plan amended <n>× after merge conflicts: <task>: <files> (re-run merged cleanly)] |
| QA | `devbox run ci` green in <n> round(s) · agents: <none | which> |
| Verification | <m>/<m> criteria met (verification.md) |
| Image | built and smoke-started | skipped |
| PR | <URL> |

<the Dependency patches table from `cplat deps report`, when the run bumped anything>

### Next steps
<gitops change needed (system.yaml / /instance:promote after release), HIGH findings, sequential fallback, `/component:spec migrate` hint>
```

Add the bracketed part of the Implementation row only when `cplat component build state <id>` shows a re-plan count of 1 or more: one `<task>: <files>` entry per re-planned task. Then `cplat platform runs end --outcome done`.

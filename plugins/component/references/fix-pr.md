# Quick-task: the pull request

Read from `/component:fix` Phase 3, after the tester passes.

Write the PR body with the Write tool to `.pr-body.md` in the repo root (never into `.git/`, because Claude Code refuses edits there; cplat moves the file out of the work tree before it commits). The lines under "Related issues / stories" stay `{{CLOSES}}`; the command fills them.

```markdown
## Summary

<2–4 sentence description of the change: what it does, how it works, and why it was needed. For a new feature, describe what the feature is and how a user or operator would interact with it. For a fix, describe what was broken and how it was resolved.>

## Type of change

- [x] <tick the matching type from: feat / fix / refactor / perf / test / docs / chore / ci / revert>

## Related issues / stories

{{CLOSES}}

## Testing done

<tester output summary: N tests, X% coverage>

## Checklist

- [x] `devbox run quality` passes (ruff + mypy)
- [x] `devbox run test` passes with coverage ≥ 80%
- [x] No secrets, credentials, or API keys committed
- [ ] Docs: <tick only if public-facing behaviour changed AND the docs were updated; otherwise write "n/a, no public-facing change">

Not run by fix: `devbox run security` (use `/component:check` for a full audit before merging risky changes).
```

Then make **one** Bash call (it commits everything with `-s`, finds the open issues to close, pushes the branch and opens the PR):

```bash
cplat pr open --title "<type>(<scope>): <imperative description of the task>" [--issues "#NNN …"] [--no-spec]
```

Use `fix:` for bug fixes, `chore:` for tooling, `docs:` for documentation, etc.; the title must be a Conventional Commits title, otherwise the `pr-title` CI check fails. Pass `--issues` for `#NNN` references in the task.

Relay its three lines (`commit:`, `push:`, `pr:`). Exit 1: report which part failed and stop; `pr: failed: already open <url>` means the PR exists, so use that URL. Exit 2: fix the reason it prints, then call it again. A re-run makes no second commit or PR.

**`pr: ready: <command>`** (headless run, untrusted workspace, or `gh pr create` not allowed; spec 051) is not an error: the branch is pushed and cplat has moved the body to `.git/PR_BODY.md`. End the report with that exact command as its last line.

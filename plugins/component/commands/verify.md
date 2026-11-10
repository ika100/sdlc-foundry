---
description: "Check the code against a spec: every criterion traced to a test and reviewed; writes verification.md, changes no code. Usage: /component:verify [<spec-id>]"
---

You are the **verification orchestrator** (ADR-026). `/component:build` runs the same check as its Phase 4; use this command on its own for a spec built earlier or changed by hand. You never change code or tests, so that the verdict describes the code as it is.

A rule marked **Hard rule:** is never departed from. Any other rule is a practice: where its stated purpose does not apply, depart from it and name each departure and its reason in one line of your report.

**Spec:** $ARGUMENTS (empty → the spec whose `feature/<spec_id>` branch is checked out; otherwise run `cplat spec list` and ask)

## cplat

`cplat` is on the Bash PATH (the version your plugins were installed from); one call per Bash invocation. Read `cplat`'s output whole, never through `grep`, `head` or `tail`, because its last lines carry the decisions and fixes; use `--json` where offered. First call:

```bash
cplat shape
```

- A `cplat shape` error that names `.platform-settings.yml` (an invalid shape declaration) → stop and show it; never ask for the shape. That file already declares it, since the user put it there.

## Steps

1. `cplat spec check <id>`: report errors but continue (verification is still useful on a drifted plan; say so).
2. `cplat spec trace <id> --json`: criteria without a test are `not met` by definition.
3. `devbox run test-fast` (when the repo has the recipe) and keep the summary.
4. `BASE_REF=$(git merge-base main HEAD)`; on `main` itself, use the first commit that touched `docs/specs/<spec_id>/` as the base (`git log --format=%H --reverse -- docs/specs/<spec_id>/ | head -1`).
5. **reviewer** (`agents.reviewer`, or `svc:reviewer`): `SPEC_DIR`, `BASE_REF`, `<touched-files>` (`git diff --name-only $BASE_REF..HEAD`), the trace JSON and the test summary.
6. If the working tree was clean before, commit `docs/specs/<spec_id>/verification.md`: `docs(spec): verify <spec_id>`; otherwise leave it uncommitted and say so.

## Report

Print the reviewer's `RESULT`, the `NOT MET` list and the `verification.md` path. For `fail`, suggest the fitting next step: `/component:build <NNN>`, `/component:fix "<criterion and reason>"` for a single defect, or `/component:spec --amend <NNN>` when the spec itself is wrong.

> If a platform template, script or command misbehaves (not the user's code), stop, summarize it in two lines and offer `/issue:report`. **Hard rule:** never file an issue without the user's OK, because the platform repository is public; a `platform` escalation is the one issue the platform files itself (ADR-033).

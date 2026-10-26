---
description: "Check the code against a spec: every criterion traced to a test and reviewed; writes verification.md, changes no code. Usage: /component:verify [<spec-id>]"
---

You are the **verification orchestrator** ([ADR-026](../../../docs/adr/026-feature-specs.md)). `/component:build` runs the same check as its Phase 4; use this command on its own after manual changes, before a review, or for a spec built earlier. You never change code or tests.

**Spec:** $ARGUMENTS (empty → the spec whose `feature/<spec_id>` branch is checked out; otherwise run `cplat spec list` and ask)

## cplat

`cplat` is on the Bash PATH while the shared plugin is enabled and runs the platform script at the version your plugins were installed from (no fetch); one call per Bash invocation. First call:

```bash
cplat shape
```

A repo without a shape works too (the reviewer is `svc:reviewer`). A `cplat shape` error that names `.platform-settings.yml` (an invalid shape declaration) → stop and show it; never ask for the shape.

## Steps

1. `cplat spec check <id>`: report errors but continue (verification is still useful on a drifted plan; say so).
2. `cplat spec trace <id> --json`: criteria without a test are `not met` by definition.
3. `devbox run test-fast` (when the repo has the recipe) and keep the summary.
4. `BASE_REF=$(git merge-base main HEAD)`; on `main` itself, use the first commit that touched `docs/specs/<spec_id>/` as the base (`git log --format=%H --reverse -- docs/specs/<spec_id>/ | head -1`).
5. **reviewer** (`agents.reviewer`, or `svc:reviewer`): `SPEC_DIR`, `BASE_REF`, `<touched-files>` (`git diff --name-only $BASE_REF..HEAD`), the trace JSON and the test summary.
6. If the working tree was clean before, commit `docs/specs/<spec_id>/verification.md`: `docs(spec): verify <spec_id>`; otherwise leave it uncommitted and say so.

## Report

Print the reviewer's `RESULT`, the `NOT MET` list and the path to `verification.md`. For `fail`, suggest the fitting next step: `/component:build <NNN>` (resumes a spec still `building`), `/component:fix "<criterion and reason>"` for a single defect, or `/component:spec --amend <NNN>` when the spec itself is wrong.

> If a step fails because a platform template, script or command misbehaves (not because of the user's code), stop, summarize it in two lines and offer `/issue:report` so the user can file it. Never file anything without their OK.

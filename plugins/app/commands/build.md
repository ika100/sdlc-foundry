---
description: "Build a planned product spec: every ready repo in parallel (one agent each) through its own /svc:spec → plan → build, ending at open PRs; never merges for you. Usage: /app:build <spec-id> [--max N]"
---

You are the **product build executor** ([ADR-023](../../../docs/adr/023-parallel-plan-execution.md), [ADR-026](../../../docs/adr/026-feature-specs.md)). The plan `docs/plan/<spec_id>.md` lists the product's repos with `depends_on`; repos whose dependencies are done are built **at the same time**. You run one wave after the other and stop wherever a human decision is needed.

**Arguments:** $ARGUMENTS (`<spec-id>`; `--max N` limits parallel agents, default 3)

## cplat

`cplat` is on the Bash PATH while the shared plugin is enabled and runs the platform script at the version your plugins were installed from (no fetch); one call per Bash invocation. First call:

```bash
cplat shape
```

It must report `shape: gitops-app`, else stop.

## Pre-flight

1. Resolve `<spec_id>` (`cplat spec list --all --json`). `cplat spec check <spec_id> --require approved` must pass; `docs/plan/<spec_id>.md` must exist (otherwise `/app:plan <NNN>`).
   `git fetch -q origin`, then compare with `git diff --quiet origin/main -- docs/plan/<spec_id>.md docs/specs/<spec_id>/` (and check the file exists there). If the plan is missing on `origin/main` or differs from it, say so: component agents in fresh clones and reviewers see the version on `main`. Ask whether to continue from the local file, or merge the spec PR first (spec 050).
2. `devbox run plan-check`; the plan must be `draft` or `in_progress`. `devbox run -- uv run scripts/plan.py start <spec_id>` (draft → in_progress); if the spec is `approved`, `cplat spec set-status <spec_id> building`. Commit both on the plan's branch or `main` as the user prefers.
3. Show `devbox run -- uv run scripts/plan.py show <spec_id>` and ask the user to confirm: this opens PRs in several repositories.

## Loop (one wave per iteration)

1. `devbox run -- uv run scripts/plan.py ready <spec_id> --json` → the repos that can start now. Empty and not completed → a PR of the previous wave is still open: go to 5.
2. **The gitops-app entry** (shape `gitops-app`, this repo itself), when it is ready, is built here by you, never `/svc:*` and never by a repo agent (spec 045):
   - On a clean checkout, `git checkout -b compose/<spec_id>` from `main`. If this checkout is busy (another branch with work), use `git worktree add ../<repo>-<spec_id> -b compose/<spec_id> main` and run everything there.
   - Run its `gitops:` operations in order: `{addon: X}` → `cplat addon add X`; `{uses: X, service: S}` → `cplat compose set S --uses X`; `{expose: S, host: H}` → `cplat compose set S --expose H`; `{env: {K: V}, service: S}` → `cplat compose set S --env K=V` (one `--env` per variable).
   - `devbox run validate`, commit `feat(compose): <spec_id> — <summary>`, push, open the PR (or print its command), and mark it **merge first** in the table: services that use an addon or an env it adds are not ready before it is merged.
   - Back on the original branch, `git worktree remove ../<repo>-<spec_id>` if you created one; the run leaves no extra folder.
3. For each other ready repo (at most `--max`): make sure a clone exists next to this repo (`gh repo clone <org>/<repo> ../<repo>` if missing); refuse a clone with uncommitted changes.
4. **In a single message**, start one subagent per ready component repo (Agent tool, general-purpose) as **foreground** calls, never `run_in_background`: calls in one message run concurrently and you wait for all of them, while headless sessions stop background agents after 600 s (spec 046). Each prompt contains the repo path, the absolute plan path, the repo id, and these instructions:
   *Work only inside that clone. If `gh pr create` is not allowed, push the branch, write the body to `.git/PR_BODY.md` and report the exact `gh pr create` command instead of a PR URL (not an error). The per-repo `/svc:build` records its run and its agent metrics (spec 089) as usual. Run the `/svc:spec --from-plan <abs plan path> <repo-id>` steps **unattended**: the user approved the product spec and plan, so if the repo spec has no open questions, approve it; if it has any, stop and report them verbatim, never answer them. Then run the `/svc:plan <n>` and `/svc:build <n>` pipelines. Stop with an open pull request: never merge, never push to `main`. Report the repo spec id, the PR URL, the CI result and the verification result; if blocked, report why instead of guessing.*
5. Collect the reports. Print one table: repo, repo spec, PR, CI, verification, state (the gitops entry first, marked **merge first**). For repos that could not open their PR, list one `gh pr create` command per repo below the table, in merge order; the last line of the report is the last command (spec 051). This is not an error. Open questions from a repo go to the user (AskUserQuestion); after answering, re-run `/app:build <NNN>` (state is in the plan file and the repo specs). A failed or blocked repo stops the loop: say which repos are untouched.
6. Ask the user to review and merge the PRs (the gitops PR first) (or to say "merge" for green ones: only then `gh pr merge --squash` on those). For each `MERGED` PR (`gh pr view --json state`): `devbox run -- uv run scripts/plan.py done <spec_id> <repo-id>`. Then the next wave.

## When the plan is completed

`cplat spec set-status <spec_id> done` and `cplat spec index`; commit both with the plan. Show the `gitops_pin` entries and the exact `/gitops:promote` commands; do not apply pins or touch `services.yaml` or overlays yourself. `dev` gets the merged builds on its own: each service's CI opens a pin PR in this repo that merges itself after CI (spec 062). Say that (never claim it picks up the latest image by itself) and point to `/shared:status` (its `pin PR` column) to see whether the pins have landed.

## Rules

- Parallel only within a wave; a repo never starts before its `depends_on` are done (merged).
- Never merge without the user's explicit word, never force-push, never pin images.
- Agents write only inside their own clone; two agents never share one.
- Print `plan.py` output verbatim.

> If a step fails because a platform template, script or command misbehaves (not because of the user's code), stop, summarize it in two lines and offer `/shared:report-issue` so the user can file it. Never file anything without their OK.

# End-to-end run 2: a second feature on the todo product with v4.0.0 (2026-10-08/09)

<!-- historical -->
> **Historical.** This field report describes a run with v4.0.0; command and file names are those of 4.x. It is kept as a record and is not part of the current documentation; the current flow is in the [quickstart](../QUICKSTART.md) and the [user journey](../USER-JOURNEY.md).

The first run against the **released** v4.0.0: an existing product (from [run 1](2026-10-08-todo-spec-driven.md)) is upgraded and gets a second feature, requested by the user in one sentence: *"It shall be possible to update a notice."*

**Result:** the feature (edit a todo's title in place) is specified, planned, built test-first, verified, merged, deployed on the local cluster and checked live. About 68 minutes of active time and $12.10 of agent cost. 17 findings: 4 high, 5 medium, 8 low.

## Setup

| | |
|---|---|
| Platform | tag `v4.0.0` (`9284b03`), checked out on its own; plugins loaded with `--plugin-dir` |
| Repos | [ika100/todo](https://github.com/ika100/todo) (gitops-app), [ika100/todo-api](https://github.com/ika100/todo-api), [ika100/todo-web](https://github.com/ika100/todo-web), from run 1 |
| Driver | headless Claude Code 2.1.285 (`claude -p`, `bypassPermissions`), one session per command; **no** `CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS`, to test spec 046 |
| Human role | the user answered every spec question; the operator ran the commands, opened the PRs agents could not open, merged, deployed |

## Timeline

| Clock | Step | Took | Cost |
|---|---|---|---|
| 10-08 18:45 | `/shared:update-service --ref v4.0.0` in `todo` ‖ `todo-web` (todo-api was updated earlier) | 0m26s ‖ 0m35s | $0.50 |
| 18:47 | operator workarounds (findings 1, 2), update PRs todo#6, todo-web#4 merged | ~4 min | — |
| 18:52 | `/app:spec "It shall be possible to update a notice."`: 10 criteria, 7 open questions — the first asks what "notice" means | 1m08s | $0.49 |
| | the user answers (edit a todo's title; an Edit control; clicking away cancels) | — | — |
| 18:55 | `/app:spec --amend 002 …`: 11 criteria, approved | 0m54s | $0.41 |
| 18:57 | `/app:plan 002`: 2 repos in parallel, contract with Errors and Timeouts, no gitops changes; asks before pushing (050) | 1m46s | $0.59 |
| 18:59 | "push": branch pushed, `gh pr create` not allowed → exact command (051); todo#7 merged 19:00 | 0m12s | $0.04 |
| | *waiting for the user (~2 h 20 min)* | | |
| 21:22 | `/app:build 002`: todo-api built (13/13 criteria verified, CI green); todo-web stopped on 6 open questions | 27m21s | $4.90 |
| 21:46 | the user answers todo-web's questions; `/svc:spec --amend` there: 25 criteria, approved | 1m31s | $0.60 |
| 21:53 | todo-api#5 and the bookkeeping PR todo#8 merged | — | — |
| 21:53 | `/app:build 002` resumed — stopped after 53 s: **account weekly usage limit** | 0m53s | $0.64 |
| | *paused overnight (~13 h)* | | |
| 10-09 10:51 | `/app:build 002` resumed again: todo-web built (25/25 criteria verified, CI green) | 13m49s | $3.65 |
| 11:07 | todo-web#6 merged; both images published | ~4 min | — |
| 11:10 | operator restarts the dev deployments (finding 3), 10 s | — | — |
| 11:11 | live acceptance check: all pass | — | — |
| 11:12 | `/app:build 002` bookkeeping: plan completed, spec done; todo#9 merged | 0m32s | $0.28 |

**Totals:** 16 h 27 min of wall clock, of which about 68 min active (the rest waiting for the user and the overnight usage-limit pause); 11 agent steps in 10 sessions, 49 min of agent time; **$12.10** (per session: a resumed session reports its cumulative cost, so steps are not summed — run 1's $17.48 was summed per step and is slightly too high for that reason).

## Live acceptance check (k3d-todo-local, Gateway on :8089)

| Check | Criterion | Result |
|---|---|---|
| `PATCH {"title":"  Buy oat milk  "}` on a done todo → trimmed, still done | AC-002.2, .3, .7 | ✓ 200 |
| blank title → "Title is required" | AC-002.5 | ✓ 422 |
| 201 characters refused, 200 accepted | AC-002.6 | ✓ 422 / 200 |
| done-only body of spec 001 still works | spec 001 | ✓ 200 |
| title survives an API restart | AC-002.2 | ✓ |
| page shows the new title and an "Edit &lt;title&gt;" control per row | AC-002.1, AC-002.22 (todo-web) | ✓ |
| editing a deleted todo → "This todo no longer exists" | AC-002.8 | ✓ 404 |

Not checked live: the interactive edit (click Edit, Escape, clicking away) needs a browser; todo-web's acceptance tests cover it.

## What worked as designed

- **The spec caught the ambiguity.** "Update a notice" became open question 1 ("does notice mean a todo?"); nothing was built on a guess. All questions reached the user and were answered in one round each.
- **Tests first, verified, in both repos:** the commit trail of todo-api#5 and todo-web#6 is spec → plan → start → red acceptance tests → tasks marked done → security → verification → done. The reviewer found real things (a weak acceptance test for AC-002.16; a timing window returning 500, fixed in `ec49ece`).
- **Fixes from run 1, live:** 046 (27-minute `/app:build` without the timeout workaround, no agent killed), 050 (asks before pushing the spec branch; the plan was on `main` before the build), 051 (every repo ended with the exact `gh pr create` command and `.git/PR_BODY.md`), 053 (the contract had Errors and Timeouts), resuming a product build (twice, including after the usage-limit stop), the `specs` CI job (now really checks: "1 spec(s), 0 problem(s)").
- **Not exercised:** 044 (parallel coders from the feature head) — todo-api's tasks t1 and t2 were marked done together, but no worktree merge commits exist, so they most likely ran sequentially; 045 (no gitops changes needed); 054 (no new repos).

## Findings

| # | Sev | Finding | Workaround | Proposed fix |
|---|---|---|---|---|
| 1 | high | **v4's `plan.py` rejects completed plans written before v4.** After `/shared:update-service`, `todo`'s `test-fast` failed: the done 001 plan lacks a `gitops:` list and `### Errors` / `### Timeouts` headings — although its contract already had an "Error format" section and a 5 s timeout. | Completed the old plan by hand (renamed the heading, added Timeouts and the operations). | Apply the 045/053 rules only to plans that are `draft` or `in_progress`; accept the content under other headings, or say which heading is expected. |
| 2 | high | **Skeleton updates drop project content.** `devbox.json` lost todo-web's own `bundle-check` recipe (the proof for AC-001.25); the README problem of todo-api (spec 060) is the same class. | Re-added the recipe. | Extend spec 060: keep project recipes in `devbox.json` (merge the template's scripts into the project's instead of overwriting the file). |
| 3 | high | **`dev` never deploys new builds.** It runs `:latest` with `imagePullPolicy: Always`, but nothing restarts the pods when a new image is published, so merged features do not run until someone restarts them; the docs (and the agents) say "dev tracks latest". | `kubectl rollout restart` by the operator. | Pin `dev` to `sha-<7>` on every merge (a PR or an image updater), or roll the deployments on a new digest; document it. |
| 4 | high | **`cplat spec test-diff` flags `plan.md`** (it names criterion ids) after `cplat spec task-done` writes `done: true` — a false "changed acceptance test", seen in both repos. | The agents judged it a false alarm and continued. | Only look at the shape's `test_globs`; never at `docs/`. |
| 5 | medium | **`devbox run quality` in the gitops-app repo prints plan errors but exits 0**, so CI quality would pass a broken plan. | — | Fail the recipe on `plan-check` errors. |
| 6 | medium | **Bookkeeping costs PRs.** Besides the spec+plan PR, `/app:build` opened a branch and PR only to mark the plan `in_progress` (todo#8) and another to record completion (todo#9). | Opened and merged them. | Keep run state out of `main` until the end: one bookkeeping commit with the completion, or record progress on the spec branch. |
| 7 | medium | **Unattended builds stop on "Confirm:" questions.** todo-web's 6 questions were all settled by their suggested answers; 3 were "Confirm: …" items the format calls obvious defaults. | The user answered all six. | Let the user allow suggested answers for `Confirm:` items in unattended runs (e.g. `/app:build --accept-confirmations`); real questions still stop. |
| 8 | medium | **A repo-level answer can contradict the product contract** ("Edit &lt;title&gt;" vs. the plan's "Edit"); the only consistent path is `/app:spec --amend` + re-approval + re-plan for a UI detail. | Recorded as a repo-level decision in todo-web's spec changelog. | Planner: keep UI details out of cross-repo contracts; or let a repo record a "contract refinement" that `plan-check` accepts. |
| 9 | medium | **Spec size:** 11 product criteria became 25 repo criteria in todo-web for an inline title edit; thorough, but slow to review. | — | Product-manager guidance: a repo slice adds only what the product criteria leave open; flag specs over ~15 criteria. |
| 10 | low | The product-manager deleted answered questions instead of striking them through. | — | Spec-format rule exists; add a `cplat spec check` warning when a draft loses questions without a changelog line. |
| 11 | low | `docs/security/scan-<date>.md` is overwritten by a second scan on the same day (44 HIGH base-image findings now only in history). | — | Name scans `scan-<date>-<spec>.md` or append. |
| 12 | low | Acceptance tests cannot be fixed beyond formatting: an unused variable and a weak AC-002.16 test stay. | — | A sanctioned path: the reviewer proposes the test change, the user approves, the spec changelog records it, `test-diff` accepts it. |
| 13 | low | The PR body's first sentence described the old UI (taken from the code, not the spec). | — | Build the PR summary from the spec's problem and criteria. |
| 14 | low | Resumed sessions report cumulative cost; per-step sums overstate (run 1). | Counted per session. | Note in BASELINES; measure per session. |
| 15 | low | A long multi-agent run hit the account's weekly usage limit (resumed cleanly after the reset). | Waited for the reset. | ADOPTING → *Unattended runs*: mention usage limits; `/app:build` already resumes. |
| 16 | low | The update agents offered `/shared:report-issue` for platform problems (good) but the README/recipe loss was only visible by reading the diff. | — | Spec 060's report line ("kept"/"would drop") for every project-relevant file. |
| 17 | low | `/app:build` claimed "dev already runs latest" after merging (see 3). | — | Fix 3; then the statement becomes true. |

## Follow-up

Findings 1–4 should be fixed before rolling v4 out to more repos: 1 and 2 break or silently damage every upgraded repo, 3 hides whether a feature runs at all, 4 trains agents to ignore a safety check. Spec 060 (approved, README project-owned) should absorb finding 2. Each finding becomes a draft spec in [`../specs/`](../specs/README.md) when the user asks for it.

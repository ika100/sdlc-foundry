# Benchmarks for spec 111

Prices of 2026-10-25 (estimates; output tokens as reported). Sample `ika100/todo-api@9cba320`, plugins and `cplat` from
the feature branch at `85eacb0` (`--plugins`, `CPLAT_PLATFORM`), coordinator Sonnet, ships on `truenas-k8s`
(`CPLAT_KUBE_CONTEXT`). Baseline: the 4.7.0 figures in docs/BASELINES.md (quick-task $0.30, build $1.31, ship $1.40).

All three parts are on one branch, so each run exercises them together; the part each figure speaks for is named.

| Workflow | Run | Outcome | Cost | Part it measures | Note |
|---|---|---|---|---|---|
| quick-task | 2026-10-26 11:15 | done (todo-api#36) | **$0.14** | inline path + session start | `inline: allowed (2 files, 8 lines)`, quality and `test-fast` green, no agents |
| quick-task | 2026-10-26 11:17 | done (todo-api#37) | **$0.08** | inline path + session start | same |
| build | 2026-10-26 11:18 | failed (no PR) | $1.19 | session start | escalated in the image step: the deployment agent added an `image-smoke` recipe to `devbox.json` unasked, and `git checkout devbox.json` is not allowed headless. Not caused by 111; see follow-ups |
| build | 2026-10-26 11:28 | done | **$1.11** | session start | |
| ship | 2026-10-26 11:35 | pending at the time of writing | | `ship continue` + session start | the second ship run was cancelled to close the session |

## Reading (AC-111.10)

- **Inline quick-task: keep.** Median $0.11 against $0.30, both runs done with a PR and green gates. The check and
  both gates ran in each run (session logs).
- **Session start: keep, provisionally.** The one finished build is $1.11 against $1.31; the failed build failed for an unrelated reason. A second done build is still owed before the
  figure counts as a median.
- **`ship continue`: not decided.** One ship run is still pending; AC-111.10 asks for two. Merge waits for at least
  the pending run's figure.

## Follow-ups found on the way

- The deployment agent edits skeleton files (`devbox.json`) during a check-only image step although told not to.
- A coordinator has no allowed way to undo one stray file edit headless (`git restore <path>` / `git checkout -- <path>`
  are not allowlisted), so a harmless stray edit becomes an escalation.
- The PR body template's coverage box was ticked on the inline path although only `test-fast` ran; quick-task.md now
  says to leave it unticked (CI runs coverage).

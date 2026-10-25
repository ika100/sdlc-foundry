# Benchmarks for spec 100

Prices of 2026-10-25 (estimates; output tokens as reported, so output cost is a lower bound). Sample `ika100/todo-api`.

| Step | Workflow | Run | Outcome | PR | Gates | Reviewer | Calls | Tokens | Est. cost | Coordinator | Plugins | Note |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| baseline | quick-task v2 | `20261025T113632Z-73dcf110` | done | todo-api#9 | n/a (quick-task: quality + tests ran) | — | 22 | 674,791 | $0.48 | opus (user default) | installed 4.5.0 |  |
| baseline | build v3 | `20261025T123218Z-f4e36dbe` | done | todo-api#11 | acc passed, sec passed | pass | 81 | 2,617,700 | $1.64 | opus (user default) | installed 4.5.0 | v3 task; superseded by the v4 baselines below |
| 1 | quick-task v2 | `20261025T131302Z-cbc6693e` | done | todo-api#12 | n/a (quick-task: quality + tests ran) | — | 10 | 366,432 | $0.16 | sonnet | worktree @eef4db9 | coordinator did the change itself (no coder/quality/tester agents) and ran lint, types and tests |
| 1 | build v3 | `20261025T131439Z-f8398a6a` | failed | — | acc passed, sec passed | not reached | 65 | 2,120,178 | $1.13 | sonnet | worktree @eef4db9 | stopped before push: build.md said push/PR need confirmation (fixed in 208c9f2) |
| 1 | build v3 | `20261025T132523Z-7606b481` | failed | — | acc not run, sec not run | not reached | 44 | 1,265,392 | $0.68 | sonnet | worktree @208c9f2 | escalated: tester read AC-900.2 without a request body (spec 900 v4 fixes the wording) |
| baseline v4 | build v4 | `20261025T133329Z-d19e689b` | done | PR (closed by reset) | acc passed, sec passed | pass | 84 | 2,712,447 | $1.75 | opus | worktree @3f5201b |  |
| 1 | build v4 | `20261025T134409Z-7971f596` | done | PR (closed by reset) | acc passed, sec passed | pass | 71 | 2,380,239 | $1.25 | sonnet | worktree @3f5201b |  |
| baseline v4 | build v4 | `20261025T135136Z-d3ddd653` | done | PR (closed by reset) | acc passed, sec passed | pass | 107 | 3,467,205 | $2.12 | opus | worktree @3f5201b |  |
| 1 | build v4 | `20261025T140715Z-578ba653` | done | PR (closed by reset) | acc passed, sec passed | pass | 66 | 2,280,157 | $1.20 | sonnet | worktree @3f5201b |  |

## Step 1 — coordinator on Sonnet: accepted

- **quick-task:** $0.48 → **$0.16** (one run, done, PR). Meets AC-100.15's ≤ $0.30 already.
- **build v4** (same worktree plugins, only the model differs): Opus median **$1.94** ($1.75, $2.12; 10 and 15 min), Sonnet median **$1.22** ($1.25, $1.20; 7 and 8 min): **−37%**, all four runs done with a PR and both gates passed. Relative to the v4 baseline the 30% build target of AC-100.16 is ≤ **$1.36**.
- Two prompt fixes were needed for a Sonnet coordinator (208c9f2): `build.md` no longer says push and PR need confirmation, and tester/coder agents write files with Write/Edit, never via a shell heredoc.

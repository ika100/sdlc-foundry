Read from `/system:ship` when `cplat system ship drive` printed `driver: off`.

## Phase `publish`

`cplat system ship publish`: when the spec and plan are not on `main` (or differ) it merges them through a PR on green checks. Exit 1 (a red check) → print it and stop; no repo starts.

## Phase `repos`

Loop on `cplat system ship next --json`, one call per action, never a shell loop, because each action changes what the next call returns.

- `action: start`: for each id, `cplat system ship repo start <id>`. A clone with uncommitted changes is refused: stop, tell the user its path. `preflight failed: <category>: …`: that repo is escalated; print the line, the others go on.
  - The **gitops entry** (`entry: true`) is built by you in the printed worktree: read `${CLAUDE_PLUGIN_ROOT}/references/ship-entry.md` and follow it. No repo that depends on it starts before it is merged.
  - Every other repo ships **in its own session** (spec 155): `repo start` writes and approves the repo spec from the plan and starts `cplat headless "/component:ship <repo spec>"` in the clone. You start no subagent for a component repo and never work in its clone, because its own session owns it.- `action: wait`: `cplat system ship next --wait` blocks, records finished repos and prints the next action. On exit 0 (`WAIT:`) or exit 2 (`TIMEOUT:`) run the same wait again; escalate only after three `TIMEOUT:` in a row (a `WAIT:` resets the count): `cplat system ship escalate '<the TIMEOUT line>' --cause environment`, stop, because a stuck repo means runner or cluster. One clone: `cplat component ship wait --repo <clone>`. Never write a polling loop on `cplat component ship status`, `kubectl` or `gh`, because the wait ends at the first state change.
- `action: answer`, by `do`: `resume` → `cplat system ship repo resume <id> --answer '<suggestions>'`; `ask` → AskUserQuestion now (suggestion Recommended, option `hold`), then resume with the reply or hold, so that the person present answers while others run; `hold` → `cplat system ship repo hold <id>`. Then `next`, because one repo's decision need not wait for another's build, and only the user approves answers.
- `action: escalate`: no repo can start. `cplat system ship escalate '<the repo's reason>'`, print the table, stop.- `action: land`: `cplat system ship land` merges the dev PR on green CI, and promotes through staging; `cplat` posts milestone comments itself, without asking. Exit 0 → `complete`. 1 → escalated: print, stop. 3 (`WAIT:`) → `land` again. 2 (`TIMEOUT:`) → again, at most twice, then `cplat system ship escalate '<the TIMEOUT line>' --cause environment`, stop.
- `action: complete`: `cplat system ship phase complete`.

## Phase `complete`

`cplat system ship complete` prints the final report: print it verbatim, then `cplat system ship finish`. `cplat` puts a Summary at the top of each PR body; the orchestrator writes none.
# System ship: the gitops entry

Read from `/system:ship` Phase `repos` when `start` names the gitops entry (`entry: true`).

Build it in the printed worktree: its `gitops:` operations in order:

- `{resource: X}` → `cplat resource add X`; `{resource: X, type: T}` → `cplat resource add X --type T`;
- `{uses: X, component: C}` → `cplat component set C --uses X`;
- `{expose: C, host: H}` → `cplat component set C --expose H`;
- `{env: {K: V}, component: C}` → `cplat component set C --env K=V`, one `--env` per variable.

Then `devbox run validate`, commit `feat(compose): <spec_id> — <summary>`, `cplat system ship entry pr <id> --title <title> --body-file <file>` and `cplat system ship entry land <id>`. Red → the repo is escalated (print the failed checks).

In a **joint run** (spec 144: `start` printed no `one dev PR per component` line) `entry land` only waits for the entry PR's checks: the PR stays open as the system spec's one dev PR, each component build is pinned on it (`repo result` does that), and dev changes once, in `cplat system ship land`. A gitops-app whose `pin-dev.yml` predates spec 144 keeps one dev PR per component (the line `start` printed) and merges the entry first, until `/platform:update`.

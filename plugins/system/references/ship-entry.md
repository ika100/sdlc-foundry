# System ship: the gitops entry

Read from `/system:ship` Phase `repos` when `start` names the gitops entry (`entry: true`).

Build it with cplat; never run git or edit files in that worktree yourself, because it lives in the git dir, where a headless session may not run git:

1. `cplat system ship entry apply <id>`: applies the plan's `gitops:` operations in order in the worktree (`{resource: X[, type: T]}` → `cplat resource add`, `{uses: X, component: C}` / `{expose: C, host: H}` / `{env: {K: V}, component: C}` → `cplat component set`), one commit each, then `devbox run validate`. On a resume an operation already applied is left alone. A refused operation or a red validate → `cplat system ship repo escalate <id> '<the error>' --cause platform`, stop.
2. `cplat system ship entry pr <id> --title 'feat(compose): <spec_id> — <summary>'` (it writes the body from the plan; write no file), then `cplat system ship entry land <id>`. Red → the repo is escalated (print the failed checks).

In a **joint run** (spec 144: `start` printed no `one dev PR per component` line) `entry land` only waits for the entry PR's checks: the PR stays open as the system spec's one dev PR, each component build is pinned on it (`repo result` does that), and dev changes once, in `cplat system ship land`. A gitops-app whose `pin-dev.yml` predates spec 144 keeps one dev PR per component (the line `start` printed) and merges the entry first, until `/platform:update`.

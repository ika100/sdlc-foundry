# Build: worktree probe fallback

Read from `/component:build` 2.2 when the probe errors.

- It errors ("Cannot create agent worktree", "not in a git repository") → run every task sequentially on `$FEATURE_BRANCH` and note it in the Final Report (restart the session for parallelism). Record it: `cplat platform runs agent execution sequential --reason 'the worktree probe failed: <error>'`.
- A probe HEAD other than `$FEATURE_HEAD` is no fallback (#501). To have worktrees start there by themselves, set `worktree.baseRef: "head"` in `.claude/settings.json` (/platform:update) and start the session in the repo root: Claude Code reads `.claude/settings.json` only from the directory the session started in (#319); `cplat platform doctor` warns about both causes.

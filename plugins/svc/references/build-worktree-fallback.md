# Build: worktree probe fallbacks

Read from `/svc:build` 2.2 when the probe errors or reports another HEAD.

- It errors ("Cannot create agent worktree", "not in a git repository") → run every task sequentially on `$FEATURE_BRANCH` and note it in the Final Report (restart the session for parallelism).
- It reports a HEAD other than `$FEATURE_HEAD` → coders would not see the spec, the plan or the acceptance tests. Run every task sequentially and say in the Final Report: `worktree base is <sha>, not the feature head; set worktree.baseRef: "head" in .claude/settings.json (/shared:update-service)`.

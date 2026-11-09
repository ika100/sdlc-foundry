Three causes of escalated unattended runs, found by the system-ship benchmark:
- The preflight retries a dropped network when it checks push access. A failed check no longer reads as "cannot push to <repo>: ask for write access".
- The Go, Java, Next.js, gitops-app and cluster-gitops templates ignore `.claude/worktrees/`, `.claude/settings.local.json` and `.claude/scheduled_tasks.lock`, as the Python templates already did. A `git add -A` no longer stages a parallel batch's agent worktrees. Existing repos get the change with `/platform:update`.
- New Go repos start on Go 1.26. Go 1.25 is out of support, and its standard library vulnerabilities failed the security gate of every Go build.

The `system-ship` benchmark sample is refreshed to match (task version 2).

# plan.md

The tasks that implement an approved spec. The metadata must be exact because the orchestrator schedules coders from it; `cplat spec check` validates it.

## Metadata (machine-readable, mandatory)

```yaml
---
spec_id: 007-price-alerts          # the spec this plan implements
shape: service-python              # the repo's shape, a key in shapes.yml; equals the spec's shape
spec_hash: 3f9c2a71b0de            # from `cplat spec hash 007`, passed to you by the orchestrator
summary: Email + webhook alerts when a watched symbol crosses a threshold
tasks:
  - id: t1
    title: Add AlertRule model and migration
    files: [src/<module>/alerts/models.py, migrations/versions/0002_alert_rule.py]
    covers: [AC-007.1, AC-007.3]   # criteria this task makes true (partly or fully)
    parallel_safe: true
    depends_on: []
  - id: t2
    title: Add notification dispatcher (email + webhook, retry)
    files: [src/<module>/alerts/dispatcher.py, src/<module>/alerts/__init__.py]
    covers: [AC-007.1, AC-007.2, AC-007.4]
    parallel_safe: true
    depends_on: []
  - id: t3
    title: Evaluate rules on every tick
    files: [src/<module>/pipeline.py, src/<module>/alerts/dispatcher.py]
    covers: [AC-007.1, AC-007.3]
    parallel_safe: false
    depends_on: [t1, t2]
  - id: g1                         # a gitops task (spec 076): it changes the system's gitops-app repo
    title: Wire ALERT_WEBHOOK_URL into the shop-api entry
    repo: acme/shop-gitops         # listed in the service's .platform-app.yml
    order: before-merge            # before-merge: lands before the service PR | after-release: after dev runs it
    files: [applications/shop/system.yaml]
    apps: [shop-api-dev]           # Argo CD apps the change touches; the deploy waits for each to be Synced/Healthy
    covers: [AC-007.2]
    parallel_safe: true
    depends_on: []
human_steps:                       # optional: what only a person can do (permissions, deleting secrets); printed at the end
  - Grant the shop GitHub App "Contents: read" on acme/shop-gitops
---
```

The orchestrator adds `done: true` to each task as it merges; never write `done` yourself, because a hand-written flag makes a re-run skip work.

## Prose (one section per task)

```markdown
## t1 — Add AlertRule model and migration

**Files:** src/<module>/alerts/models.py, migrations/versions/0002_alert_rule.py
**Covers:** AC-007.1, AC-007.3
**Goal:** one paragraph.

**Implementation notes:**
- …

**Done when:** the acceptance tests for the covered criteria that can pass after this task pass (name them if the split is not obvious), plus any task-specific check.
```

## Rules

- **`covers`**: every active criterion of the spec appears in at least one task; a task never covers a withdrawn or unknown id, because an uncovered criterion is never built. A criterion that needs several tasks is listed on each.
- **`spec_hash`**: copy the value the orchestrator gives you, so that a plan built on changed criteria is detected and redone.
- **`files`**: every file the task creates or modifies, in the shape's layout (`app/**/page.tsx` for web-nextjs, `src/main/java/...` for service-java, `internal/...` for service-go). Listing a file locks it for that task. Do **not** list the acceptance test files: they exist before the coders start and are not edited by them.
- **`parallel_safe`**: `true` so that tasks run at once without sharing files: `false` for a task whose files overlap another at its level and for cross-cutting refactors and renames. `cplat spec check` rejects two parallel-safe tasks of one level that share a file.
- **`depends_on`**: list real dependencies (t2 imports what t1 creates) and no others, because cosmetic ordering serializes work that could run in parallel.
- **Granularity**: a task a coder finishes in one focused pass; more than ~10 implementation bullets means split it.
- **Gitops tasks** (`repo:`): every change the spec needs in the system's gitops-app repo (system.yaml values,
  Components, ExternalSecrets, removals) is a task here, not a note in design.md.
  `order: before-merge` for what the new code needs to start (new env, secrets, CRD fields);
  `order: after-release` for clean-ups once dev runs it. `/component:ship` opens each as a
  draft PR during the build and merges them in that order; `/component:build` alone lists them in its report.
- **Expand/contract**: removing or renaming CRD fields, namespaces or config keys takes two releases so that no gitops repo breaks. This plan adds
  the new shape and keeps accepting the old one (expand); a later spec removes the old one (contract) after every
  gitops repo moved.
- `<module>` is a placeholder for the repo's real package path.

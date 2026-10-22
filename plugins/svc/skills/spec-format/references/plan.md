# plan.md

The tasks that implement an approved spec. The orchestrator schedules coders from the metadata, so it must be exact; `cplat spec check` validates it.

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
  - id: g1                         # a gitops task (spec 076): it changes the product's gitops-app repo
    title: Wire ALERT_WEBHOOK_URL into the shop-api entry
    repo: acme/shop-gitops         # listed in the service's .platform-app.yml
    order: before-merge            # before-merge: lands before the service PR | after-release: after dev runs it
    files: [applications/shop/services.yaml]
    apps: [shop-api-dev]           # Argo CD apps the change touches; the deploy waits for each to be Synced/Healthy
    covers: [AC-007.2]
    parallel_safe: true
    depends_on: []
human_steps:                       # optional: what only a person can do (permissions, deleting secrets); printed at the end
  - Grant the shop GitHub App "Contents: read" on acme/shop-gitops
---
```

The orchestrator adds `done: true` to each task as it merges; never write `done` yourself.

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

- **`covers`**: every active criterion of the spec appears in at least one task; a task never covers a withdrawn or unknown id. A criterion that needs several tasks is listed on each.
- **`spec_hash`**: copy the value the orchestrator gives you. If the spec's criteria change later, the hash no longer matches and the plan must be redone; that is intended.
- **`files`**: every file the task creates or modifies, in the shape's layout (`app/**/page.tsx` for web-nextjs, `src/main/java/...` for service-java, `internal/...` for service-go). Listing a file locks it for that task. Do **not** list the acceptance test files: they exist before the coders start and are not edited by them.
- **`parallel_safe`**: `true` only when the task's files do not overlap any other parallel task at the same dependency level and the change is local. Cross-cutting refactors and renames are `false`. `cplat spec check` rejects two parallel-safe tasks of one level that share a file.
- **`depends_on`**: only real dependencies (t2 imports what t1 creates). Cosmetic ordering serializes work that could run in parallel.
- **Granularity**: a task a coder finishes in one focused pass; more than ~10 implementation bullets means split it.
- **Gitops tasks** (`repo:`): every change the spec needs in the product's gitops-app repo (services.yaml values,
  Components, ExternalSecrets, removing what the release no longer uses) is a task here, not a note in design.md.
  `order: before-merge` for what the new code needs to start (new env, secrets, CRD fields it reads);
  `order: after-release` for clean-ups once dev runs it. `files` are paths in that repo. `/svc:ship` opens each as a
  draft PR during the build and merges them in that order; `/svc:build` alone lists them in its report.
- **Expand/contract**: removing or renaming CRD fields, namespaces or config keys takes two releases. This plan adds
  the new shape and keeps accepting the old one (expand); a later spec removes the old one (contract) after every
  gitops repo moved. Never remove in the same release that adds.
- `<module>` placeholders are illustrative; use the repo's real package path.

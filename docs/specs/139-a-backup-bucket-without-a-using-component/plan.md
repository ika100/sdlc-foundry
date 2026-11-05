---
spec_id: 139-a-backup-bucket-without-a-using-component
shape: platform
spec_hash: cd75b1753b32
summary: "A backup target bucket gets its instance in an environment without a using component: backup_buckets() in render.py feeds addons_in, resource_instances and the ExternalSecret placement (an external backup-only bucket's ExternalSecret goes to addons/<env>/<bucket>/), check_backup drops the 'must use it' failure, the model applies the same rule; cluster-gitops copy synced, e2e backups without the uses, BACKUP-AND-RESTORE.md and a changelog fragment"
tasks:
  - id: t1
    title: render.py — backup_buckets, addons_in, resource_instances, the external backup-only bucket's addon, check_backup without the uses check; the cluster-gitops copy
    files: [templates/gitops-app/scripts/render.py, templates/cluster-gitops/scripts/system_render.py, tests/cplat/test_backup_117.py]
    covers: [AC-139.1, AC-139.2, AC-139.3, AC-139.4]
    parallel_safe: true
    depends_on: []
  - id: t2
    title: model.py — the same instance rule for backup-only buckets
    files: [scripts/cplat/model.py]
    covers: [AC-139.5]
    parallel_safe: true
    depends_on: []
  - id: t3
    title: e2e backups without the uses of e2e-web, and a check that e2e-web has no bucket variables
    files: [tests/e2e/run.sh]
    covers: [AC-139.4]
    parallel_safe: true
    depends_on: []
  - id: t4
    title: BACKUP-AND-RESTORE.md and the changelog fragment with the migration
    files: [docs/BACKUP-AND-RESTORE.md, docs/changelog.d/139-backup-bucket-without-user.fixed.md]
    covers: [AC-139.3]
    parallel_safe: true
    depends_on: []
---

# Plan — 139 A backup bucket without a using component

t1 and t2 implement one rule (design decision 1) in the renderer and the model; t3 moves the e2e proof to a bucket no component uses;
t4 documents the change and the optional migration. The acceptance tests are in `tests/cplat/test_backup_bucket_139.py`.

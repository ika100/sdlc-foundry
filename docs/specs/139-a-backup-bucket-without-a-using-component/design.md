# Design — 139 A backup bucket without a using component

## Decisions

1. **A bucket has an instance in `<env>` when a running component uses it, or when it is a backup target there.** A bucket is a
   backup target in `<env>` when it is the `to` of `environments.<env>.backup`, or the `to` of the `backup` of a database instance
   that exists in `<env>` (a component that runs in `<env>` uses that database). One function in render.py,
   `backup_buckets(services, cfg, env)`, answers this; `addons_in`, `resource_instances` and the ExternalSecret placement read it.
   The model (`scripts/cplat/model.py`) applies the same rule, so `/system:status`, `/resource:restore` and doctor see the
   instance render creates (AC-139.5).
2. **The check goes, nothing else in `check_backup` changes.** `check_backup` no longer fails with "the bucket … has no resource
   instance in … (a component that runs in … must use it)": with decision 1 a backup target always has one. `check_backup` and
   `validate_backups` lose their `comps` parameter. The other checks (bucket resource, external `remote.s3`, cron, retention) stay.
3. **A component's variables still come only from its own `uses`.** Nothing adds a backup bucket to a component's effective uses,
   so a component without `uses: [<bucket>]` gets none of the bucket's S3_*/AWS_* variables (AC-139.2). The ObjectStore and Velero
   read the bucket's Secret `<system>-<bucket>-app` in `<system>-<env>` as before.
4. **An in-cluster backup-only bucket is the same addon as a used one.** `addons/<env>/<bucket>/` (SeaweedFS, Bucket, S3Identity,
   S3Credentials, credentials Job), byte-identical to the addon a using component would get; the environment's backup target keeps
   its Velero labels.
5. **An external backup-only bucket gets its ExternalSecret in the addon directory.** With no running component that uses it,
   there is no overlay to hold `externalsecret-<system>-<bucket>-app.yaml`, so render writes it, with the same content, to
   `addons/<env>/<bucket>/` next to a `kustomization.yaml`, and lists the bucket in the `<system>-addons-<env>` ApplicationSet. When a
   component uses it, the ExternalSecret moves back to that component's overlay (unchanged rule). Its `creationPolicy: Orphan` and
   `deletionPolicy: Retain` keep the Secret while it moves.
6. **No database instance without a component (non-goal).** A database backup declared for an environment where no component uses
   the database renders nothing there, and so does not create its bucket either.
7. **Migration: none required.** A system whose component uses the backup bucket renders byte-identically. An owner who removes that
   `uses` gets: the component's Deployment without the bucket's variables, and for an external bucket the ExternalSecret moved from
   the overlay to the addon directory. The changelog fragment says this.

## Contract

- `render.py`: `backup_buckets(services: list[dict], cfg: dict, env: str) -> set[str]`; `check_backup(where, env, backup,
  resources)`; `validate_backups(doc, env_conf, resources)`.
- Rendered files of an external backup-only bucket `<b>` in `<env>`: `addons/<env>/<b>/externalsecret-<system>-<b>-app.yaml`
  (the ExternalSecret a using component's overlay would hold, with the Velero label template when it is the environment's target)
  and `addons/<env>/<b>/kustomization.yaml` (`resources: [externalsecret-<system>-<b>-app.yaml]`).
- `model.ResourceInstance` of a backup-only bucket: as for a used bucket; an external one has `argo_application`
  `addon-<b>-<env>` (render creates that Application), an in-cluster one `addon-<b>-<env>` as before.

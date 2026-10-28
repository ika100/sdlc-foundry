# ADR-068: Resource and operator upgrades roll through the environments in verified steps

**Status:** Accepted (2026-10-28)
**Builds on:** [ADR-017](017-gitops-owns-manifests.md) (the gitops repo owns every manifest), [ADR-058](058-pinned-versions-and-platform-installed-operators.md) (pinned versions, operators under `operators/`), [ADR-061](061-database-backups-with-the-barman-cloud-plugin-and-restore-by-generation.md) (backups and restore by generation), [ADR-063](063-autonomy-in-system-yaml-and-the-engine-contract.md) (an engine never promotes forward), spec 121; the release side is the companion ADR [069](069-one-versions-table-pins-everything-and-every-release-proves-the-upgrade.md)

## Context

Until spec 121 a change of a resource's `version` changed the image in dev, staging and prod in one render, and a new platform release
moved every environment's pins at once. Nothing checked a backup first, nothing waited for the upgraded resource, and nothing stopped prod
when dev broke. CloudNativePG 1.30 upgrades a database major in place (`pg_upgrade --link`, offline) when `imageName` changes, requires
source and target images on the same OS distribution, and asks for a new Barman server name with each major because `pg_upgrade` creates a
new system identifier.

## Decision

1. **One step is one environment and one pull request.** `resources.<r>.instances.<env>.version` holds a per-environment major (database,
   cache, broker); `/resource:upgrade <r> --to <major> [--env <env>]` writes exactly one environment's step, and the last environment's
   step folds the entries back into `resources.<r>.version`. A CI check in the gitops repo refuses a pull request that changes one
   resource's major in two environments.
2. **Dev first, staging after dev is verified, prod by hand.** A step is refused unless the nearest earlier environment runs the target
   and is verified. Staging follows by itself only with `promote: after-dev-smoke`. Prod always needs a person's `--env prod`. An
   autonomy engine never runs these steps.
3. **A step counts only when verified**: the resource is healthy at the new image within 15 minutes, its connection Secret keeps its name,
   and the smoke tests of every component instance that uses it in that environment pass. The result is recorded in the cluster
   (ConfigMap `<system>-<resource>-upgrade` in the environment's namespace), which is what the next step reads. A failed verification
   stops the rollout with exit code 1 and names the way back.
4. **A database major step needs a backup from the last 60 minutes** in that environment (dev included), read from the same
   `backup.last_success` that `cplat system status --json` shows. Cache and broker steps check no backup and say so.
5. **Database majors upgrade in place**; each major archives to its own Barman server (`<cluster>-pg<major>`), recorded as `archives` in
   `restore-state.yaml`, and a restore to a time before the upgrade recovers into a generation on the old major. Every Postgres image comes
   from one image family on one Debian release, so `pg_upgrade` always runs within one distribution.
6. **Minor and patch pins roll the same way.** A platform release moves dev's engine pins; staging and prod keep the image of their
   rendered files (a held pin, like an overlay's `newTag`) until a step moves them; no backup is checked. A held environment takes this
   release's pin before its next major step.
7. **Operators move once per cluster, with the earliest environment there.** Every environment of a gitops repo deploys to its one
   cluster, so an operator pin moves with dev's step and the verification runs the smoke tests of every environment on that cluster.

## Consequences

- No environment changes its major without its own reviewed pull request, and prod never moves before staging is verified.
- A failed upgrade leaves the later environments untouched and readable; the way back for a database is `/resource:restore`, by a person.
- Verification needs access to the cluster and the components' smoke tests; a component without a `smoke` recipe blocks the rollout until
  it has one.
- `system.yaml` shows mid-rollout state (`instances.<env>.version`); the folding step removes it.

## Not included

- Automatic rollback or downgrade; zero-downtime major upgrades; upgrading external resources, Kubernetes or nodes.
- Per-environment clusters: the order of AC-121.20 is stated for the spec that adds them.

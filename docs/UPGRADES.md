# Upgrades

A system runs engines (Postgres, Valkey, NATS, SeaweedFS) and operators (CloudNativePG, External Secrets, Kyverno, KEDA, NACK, SeaweedFS). Every one of them has an exact version in one table. This guide shows how to read it, how a platform update moves it, how you roll a database, cache or broker to a new major version one environment at a time, and what to do when a step fails. The decisions behind it are [ADR-068](adr/068-resource-and-operator-upgrades-roll-through-environments-in-verified-steps.md) and [ADR-069](adr/069-one-versions-table-pins-everything-and-every-release-proves-the-upgrade.md).

## See what runs

`cplat platform versions` prints the versions table of the platform release you have: every image with its exact tag and digest, every operator chart with its app version and the CRD versions it serves. `--json` gives the same as data. `/system:status` adds a section "Resource versions" with the major, the image and the verification result of every resource instance, and `/platform:doctor` has a row per operator that compares the installed version with the table.

Run doctor with `--context <ENV>=<ctx>` (`doctor --context`) to look at a real cluster. The reading of an operator is `ok`, `older`, `newer` or `missing`. Without a context a missing operator stays a warning, because doctor cannot see the cluster. With a context, `missing` fails, and so does an installed operator that is a major version older than the table (for a `0.x` operator the second number decides). A custom resource definition (CRD) that lacks a version the table expects makes the operator `older`; a CRD that is gone is listed as missing.

## What a platform update does

`/platform:update` renders the repo with the new release and lists what moves. Dev takes the new engine pins at once. Staging and prod keep the image they run now: the pin stays held, the way an image tag in an overlay stays until you promote. The report says, for example, `postgres 16: keeps ghcr.io/cloudnative-pg/postgresql:16 until /resource:upgrade postgres --to 16 --env staging`. Operators are different: they run once per cluster, so an operator version moves with dev's step and the report says which environments share it.

After the update is merged and synced, `cplat platform update --verify` waits for the operators to be `ok` (their CRDs must serve the table's versions), checks every dev resource whose pin moved, runs the smoke tests of every component instance on the cluster, and records the result. On success staging follows by itself where an environment says `promote: after-dev-smoke`, otherwise the command prints the next step. Pass `--context <ENV>=<ctx>` to name the cluster and `--component-dir <component>=<dir>` to point at a component checkout for its smoke tests.

## Upgrade a resource

`/resource:upgrade <name> --to <major> [--env <env>]` moves one resource in one environment, as one pull request. `--env` defaults to the first environment where the resource has an instance (dev). The major is `17` for a database, `9` for a cache, `"2.15"` for a broker. The command runs `cplat resource upgrade <ARGS> --pr --wait`: it opens the pull request, waits for the merge, waits for the Argo CD application `addon-<name>-<env>` to be synced and not degraded, and then verifies the step.

The order is fixed:

1. `/resource:upgrade postgres --to 18` for dev.
2. Staging only after dev is verified. With `promote: after-dev-smoke` it follows by itself; otherwise run `/resource:upgrade postgres --to 18 --env staging`.
3. Prod only by hand, always: `/resource:upgrade postgres --to 18 --env prod`. An autonomy engine never runs these steps.

While a rollout is under way, `system.yaml` shows the per-environment major in `resources.<name>.instances.<env>.version`. The step on the last environment folds the entries back into `resources.<name>.version` and removes them. The gitops CI check refuses a pull request that changes one resource's major in two environments, so one pull request is always one environment.

A database upgrades in place: CloudNativePG runs `pg_upgrade` offline when the image changes, so the database is unavailable for the duration. Each major archives to its own backup server (`<cluster>-pg<major>`, recorded as `archives` in `restore-state.yaml`), and the supported jumps go one or two majors up, never down. Postgres 16, 17 and 18 are targets; 15 still renders but is deprecated and never a target.

### When the command refuses

Each refusal happens before anything is written and leaves the tree unchanged. In plain words:

- the environment is not dev, staging or prod, or the resource does not exist, or it has no instance in that environment because no component that runs there uses it;
- the resource is a bucket: a bucket has no version, and its SeaweedFS image moves with the platform release (`/platform:update`, dev first);
- the resource is external in that environment: its owner upgrades it, the platform does not;
- the target is not a version of that type, is deprecated, or is lower than the current one (`/resource:upgrade` only moves up; for a database the way back is `/resource:restore`);
- the jump is not a supported path for the engine; the message names the intermediate major to go to first;
- the earlier environment is not ready: it does not run the target, or is on it but not verified, or failed its verification; the message names the command that fixes it;
- the environment still holds an older pin from an earlier platform release: move it to this release's pin of the current major first with `/resource:upgrade <name> --to <current major> --env <env>` (a pin move needs no backup);
- the resource already runs the target (it says so and exits 0);
- a database major step has no `backup` in that environment, or the last successful backup is older than 60 minutes, or the backups cannot be read.

### The backup rule

A database major step needs a backup from the last 60 minutes in that environment, dev included. Set `resources.<name>.instances.<env>.backup` in `system.yaml`, then take one with `/resource:backup <name> --env <env>` right before the step. The age is read from the same `backup.last_success` that `/system:status` shows. Cache and broker steps and pin moves check no backup, and the pull request says so.

## Verification and the record

A step counts only when it is verified: the resource is healthy at the new image within 15 minutes, its connection Secret keeps its name, and the smoke tests of every component instance that uses it in that environment pass (a component without a `smoke` recipe blocks the rollout until it has one). The result is recorded in the cluster, in the ConfigMap `<system>-<resource>-upgrade` of the environment's namespace, and the next environment reads it. A pull request that was merged but not verified is verified later with `cplat resource upgrade <name> --verify --env <env>`.

A resource that is not yet verified prints `NOT VERIFIED` and the next environment refuses to follow.

## When a step fails

A failed verification stops the rollout with exit code 1 and names the way back. Later environments are untouched and stay readable. Nothing rolls back by itself.

- For a database, restore with `/resource:restore <name> --env <env> --to <time|latest>`. A restore to a time before the upgrade recovers into a generation on the old major, from the archive of that major. Taking the backup first (the rule above) is what makes this possible.
- For CloudNativePG itself: when the `pg_upgrade` job fails, the cluster keeps its old data directory. Revert `imageName` in the rendered cluster to the old image by hand and let Argo CD sync, then look at the job's logs before trying again.
- For a cache or broker, set the old version back only for a cache without persistence; a persistent cache or a broker may not be able to read the files of the newer version, so restore the volume from the environment backup (`/system:restore`) instead.

If the platform itself misbehaves, run `/issue:report`.

## Time

Plan for one environment per step. The platform waits up to 15 minutes for the resource to be healthy and up to 600 seconds for the Argo CD application; a backup older than 60 minutes blocks a database step.

## Operators on one cluster

Every environment of a gitops repo deploys to one cluster, the shared cluster of the system, so an operator exists once there. It moves with dev's step and is checked against the smoke tests of every environment on that cluster. The order of AC-121.20 for separate clusters, one cluster per environment, is stated for a later spec: until then a system has one cluster and the operator moves once.

With `operators: owner` on an environment, the cluster's owner installs the operators and the platform does not render them; `cplat platform update --verify` and doctor still check what the environment needs. A cluster repo installs the operators for several systems; see [CLUSTERS.md](CLUSTERS.md).

## property_operators

External Secrets, Kyverno and the LGTM dev stack depend on what an environment declares (secrets, `policy`, `observability`). The gitops repo answers `property_operators`:

- `install`: the platform renders them under `operators/`, only for what the system uses. New systems get this answer.
- `owner`: the cluster's owner installs them. Every repo created before this release keeps `owner`, because its cluster has them installed by hand and a second install would collide.

Change the answer in `.copier-answers.yml` and run `/platform:update` to move a repo to `install`. A cluster repo does not install `lgtm`.

## For maintainers: the release gate

Every pin lives in the versions table in `templates/gitops-app/scripts/render.py`; a pin check in CI refuses a reference outside it, an image without a digest and a floating tag. A release lists every changed row in the CHANGELOG, and a major operator move, a dropped CRD version or a dropped resource major is refused unless the release is a new major platform version.

The release gate is an upgrade end-to-end test in its own workflow. It starts from the previous release (the first time from the latest 5.0.x), writes data, runs the platform update and a database major upgrade through dev, staging and prod, with a refused upgrade without a recent backup and a forced failed verification on the way, and reads the data back. The release procedure tags only a commit with a green run, and a check on tag pushes turns red otherwise. No automation tags or deletes tags. See [CONTRIBUTING.md](../CONTRIBUTING.md).

## Not included

Automatic rollback or downgrade, upgrades without downtime, upgrades of external resources, Kubernetes or nodes, and separate clusters per environment.

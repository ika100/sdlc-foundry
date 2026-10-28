---
spec_id: 121-resources-and-environment-properties
title: Resources and environment properties upgrade safely
status: approved
priority: P1
---

# 121 — Resources and environment properties upgrade safely

## Problem

A system owner cannot say today which database, collector or operator versions run in their environments, and cannot upgrade them safely. The 5.0 renderer (spec 114) turns `resources.postgres.version` into a floating major image tag (`postgresql:17`). Every pull of the image can bring a different minor version, and nothing records which one. Changing 17 to 18 changes the tag in dev, staging and prod in one render. Whatever CloudNativePG then does (an offline in-place upgrade or a rejection, depending on the operator version) runs with no backup (Postgres has none today), no dev → staging → prod order, no check and no test. The only test checks that the tag ends in `postgresql:17`.

Only the collector image is pinned exactly. The operators behind environment properties and resources are installed only on the local cluster, by the local cluster script, at versions taken from environment variables: External Secrets, the CloudNativePG chart, Kyverno, LGTM, and Argo CD, which floats on `stable`. The user journey guide says that on real clusters "they must be installed by the owner". Nothing shows that a cluster set up by one platform release still works after the next.

Specs 115–120 add more resources and properties, and with them more images and operators: named and external resources (115), a SeaweedFS bucket (116), backups with Velero and the CNPG Barman Cloud plugin (117), a Valkey cache (118), a NATS broker with NACK (119) and KEDA scaling (120). This spec defines how all of them are pinned, upgraded and proven. The user asked us to prove that the upgrade procedure works, so the proof is an end-to-end test (AC-121.24).

This spec is an additive 5.x extension of spec 114, which stays as approved. It adds the environment key `operators` to the list of AC-114.4, the resource instance key `version` to the list of AC-114.19 (as generalised by spec 115), and the commands `/resource:upgrade` (this spec) and `/resource:backup` (spec 117, used by AC-121.12) to the command set of AC-114.59.

## Stories

- As a system owner, I want every image and operator the platform runs to be pinned to an exact version per platform release, so that I know what runs in each environment and nothing changes without a commit.
- As a system owner, I want a resource major upgrade to move through dev, then staging, then prod, each step only after the previous one is verified, so that a failed upgrade never reaches prod first.
- As a system owner, I want a database major upgrade to be refused without a recent backup and to point me to the restore when verification fails, so that an upgrade can never lose data without a way back.
- As a cluster owner, I want the platform to install only the operators my system needs, to upgrade them in order unless I manage them myself, and to tell me which versions my clusters run against the versions the release expects, so that a platform update does not silently break my cluster.
- As the platform maintainer, I want an end-to-end test that upgrades a running system from one release to the next and shows that its data and components survive, so that every release proves the upgrade path instead of claiming it.

## Acceptance criteria

### Pinned versions

- **AC-121.1** Given a platform release, when `cplat platform versions` runs, then it prints the release's versions table. The table has one row per image and per operator chart the platform renders or installs: the image of each supported major of each resource engine, the OpenTelemetry collector, Argo CD, and the operators (CloudNativePG, the CNPG Barman Cloud plugin, External Secrets, Kyverno, LGTM, Velero, SeaweedFS, NATS, NACK, KEDA, once the spec that brings each one ships). Each row shows its exact version, and each image row its digest. With `--json` it prints the same rows as JSON.
- **AC-121.2** Given the platform repository, when the pin check runs in CI, then it fails if any image or chart the platform renders or installs does not come from the versions table. It also fails on an image reference without a digest, on a floating tag (`latest`, `stable`, a bare major such as `17`), and on a chart without an exact version. The failure names each offending reference and where it occurs.
- **AC-121.3** Given an in-cluster resource with `version: <major>` (for example a database with `version: 17`), when the system is rendered, then its instance in each environment runs the exact image and digest that the release's table maps to that major. Two renders with the same release produce the same image. The supported majors are 16, 17 and 18 for Postgres, 8 and 9 for Valkey, and the majors the table lists for the other engines. A major that is not in the table fails the render and names the supported majors.
- **AC-121.4** Given the local cluster script of a release, when it creates or updates a cluster, then every operator the system needs (AC-121.17), Argo CD included, is installed at the table's version. A version overridden by an environment variable is still installed, but the script prints a warning naming the operator, the override and the table's version.
- **AC-121.5** Given a system, when `cplat model show --json` runs, then each in-cluster resource instance reports its `version` (the major) and `pinned` (the exact image and digest for that environment). `/system:status` shows one row per resource with each environment's pinned version and the resource's health there.

### Rolling a resource upgrade through environments

- **AC-121.6** Given an in-cluster resource `<name>` on one major in every environment, when `/resource:upgrade <name> --to <major>` runs, then it opens one PR that sets `instances.dev.version: <major>` only. Staging and prod stay on the old major, and the PR description lists the environment, the old and new major, and the exact image it moves to.
- **AC-121.7** Given dev upgraded and verified (AC-121.15), when `/resource:upgrade <name> --to <major> --env staging` runs, then staging moves to the new major in one PR. Prod moves the same way with `--env prod`. When every environment is on the new major, the per-environment `version` entries are removed and the resource's `version` is the new major.
- **AC-121.8** Given staging with `promote: after-dev-smoke` (spec 114), when dev's verification of a resource major upgrade is green, then the staging step of AC-121.7 starts by itself. With `promote: manual` it waits for `--env staging`. Prod is always upgraded by hand.
- **AC-121.9** Given `/resource:upgrade --env <env>` where the environment before `<env>` is not on the target major, or is on it but not verified, when it runs, then it changes nothing and fails naming that environment and its state.
- **AC-121.10** Given a PR that changes a resource's major in more than one environment at once (for example a hand edit of `version` with no per-environment entries), when its CI runs, then a check fails. The message names the resource and the environments, and says to use `/resource:upgrade`.
- **AC-121.11** Given a platform release that changes the exact image of a supported major (a minor or patch update), when the system takes that release through `/platform:update`, then only dev's pin changes. Staging and prod keep their previous pin until they are moved by the rule of AC-121.7 and AC-121.8. The backup check of AC-121.12 does not apply to a minor or patch move.

### Guards

- **AC-121.12** Given a database resource instance in `<env>` whose `backup.last_success` in `cplat system status --json` (spec 117) is `null` or more than 60 minutes old, when a major upgrade step for that environment runs, then it changes nothing and fails. This applies in every environment, dev included. The message names the last successful backup time (or "never") and `/resource:backup <name> --env <env>` (spec 117) to take one now. Without `instances.<env>.backup` it names that key as required for a major upgrade.
- **AC-121.13** Given a resource that is external in `<env>` (spec 115), when `/resource:upgrade` would change it there, then it changes nothing and fails with "<name> is external in <env>: its owner upgrades it, the platform does not".
- **AC-121.14** Given a target major that is lower than the environment's current major, or a jump that the versions table does not list as a supported upgrade path for that engine, when `/resource:upgrade` runs, then it changes nothing and fails. For Postgres, every upward jump among 16, 17 and 18 is supported. A downgrade of a database names `/resource:restore <name> --env <env> --to <time|latest>` (spec 117) as the way back. An unsupported jump names the intermediate major to upgrade to first.
- **AC-121.27** Given an in-cluster resource of type `bucket`, `cache` or `broker`, when `/resource:upgrade` runs a major upgrade step for it in any environment, then no backup is checked. The step follows only the rolling rules (AC-121.6 to AC-121.9) and the verification rules (AC-121.15, AC-121.16), and the upgrade PR's description states "<name> has no backup".

### Verification after each step

- **AC-121.15** Given a resource upgrade step merged for an environment, when it is applied, then the platform waits up to 15 minutes for the resource to report healthy at the new version. Its connection Secret keeps its name (`<system>-<name>-app`, or `<system>-<name>-<component>-app` for a broker). The platform then runs the smoke tests (`/instance:verify`) of every component instance in that environment that uses the resource. The step counts as verified only if all of them pass, and `/system:status` shows the environment as upgraded.
- **AC-121.16** Given an upgrade step whose resource is not healthy after 15 minutes, or whose component smoke fails, when the run checks it, then it stops with exit code 1 and no later environment is upgraded, automatically or by `/resource:upgrade`. The output names the environment, the failed check and the last successful backup time. For a database it also names `/resource:restore <name> --env <env> --to <time|latest>`.

### Environment properties and operators

- **AC-121.17** Given an environment that is not opted out (AC-121.18), when the system is rendered, then operators are installed only for what the system uses on that environment's cluster:
  - CloudNativePG for an in-cluster database;
  - SeaweedFS for an in-cluster bucket;
  - NATS and NACK for an in-cluster broker;
  - KEDA when an instance uses a KEDA trigger;
  - Velero and the CNPG Barman Cloud plugin when backups are set;
  - plus the operators of the environment's other properties (External Secrets, Kyverno, LGTM).

  Each one is a platform-rendered Argo CD application per cluster, pinned to the release's table version. Upgrading the platform release moves those pins, and an operator that nothing on the cluster needs any more is not rendered.
- **AC-121.18** Given `environments.<env>.operators: owner`, when the system is rendered, then no operator application is rendered for that environment. `/platform:doctor` still checks that environment's cluster as in AC-121.19. Any other value of `operators` fails the render naming `owner` as the only value.
- **AC-121.19** Given `/platform:doctor` with access to an environment's cluster, when it runs, then it lists each operator that environment needs (AC-121.17) with the expected (table) version, the installed version and its CRD versions. It marks each one `ok`, `missing`, `older` or `newer`, and exits non-zero when any is `missing`, or `older` by a major version.
- **AC-121.20** Given environments on separate clusters, when an operator's pin changes, then it moves on dev's cluster first. Staging's and prod's clusters follow by the rule of AC-121.7 and AC-121.8, each after the earlier cluster's operator is healthy and the smoke tests of every component instance there are green.
- **AC-121.21** Given environments that share one cluster (as on the local cluster), when an operator's pin changes, then the operator is upgraded once, at the step of the earliest environment on that cluster. The smoke tests of every environment on that cluster are then run, and `/platform:doctor` notes that the environments share the operator.
- **AC-121.22** Given an operator upgrade whose chart version ships new CRD versions, when it is applied, then afterwards the cluster's CRDs of that operator are the versions of the table's chart version. Every resource the system renders is accepted by them, and the platform release check renders a sample system against them before the release.

### Releases

- **AC-121.23** Given a platform release, when its CHANGELOG section is written, then it lists every row of the versions table that changed, with the old and new version. Major changes are marked. The `/platform:update` PR of a repo lists the changes that affect that system, per environment.
- **AC-121.24** Given a candidate platform release, when the end-to-end upgrade test runs on a local cluster, then it does the following.
  - Setup: it starts from the previous release, which for the first run is the latest 5.0.x with its floating tags resolved at test time and recorded in the test output. It creates a system with a backed-up database, plus a bucket, a cache and a broker once specs 116, 118 and 119 ship. It writes a database row, a bucket object, a cache key and a stream message.
  - Upgrade: it updates to the candidate's versions table and upgrades the database one major through dev, staging and prod with `/resource:upgrade`.
  - Checks: the row, the object and the message read back unchanged (the cache key is not required to survive); the smoke tests of every component instance are green in each environment; `/platform:doctor` reports every operator `ok`.

  A release is not tagged while this test is red.
- **AC-121.25** Given the same end-to-end test, when a major upgrade is attempted without a backup from the last 60 minutes, and when dev's verification is forced to fail, then the first changes nothing in the cluster, and the second leaves staging and prod on the previous major with their data readable.
- **AC-121.26** Given a candidate release that moves an operator by a major version, removes a CRD version the previous release used, or drops a supported resource major, when the release check runs, then it fails unless the release is a new major platform version. The failure names the changed rows.

## Non-goals

- Upgrading external resources (spec 115) or anything the system owner runs outside the cluster.
- Automatic rollback or downgrade: the way back from a failed database major upgrade is `/resource:restore` (spec 117), started by a person.
- Choosing a minor or patch version per system: the platform release decides it. `system.yaml` holds only the major.
- Upgrading the Kubernetes version of a cluster or its nodes.
- Zero-downtime major upgrades: a resource may be unavailable during its major upgrade step.
- Keeping cache contents across an upgrade.
- Versions or pins of component images: they stay in the overlays as in spec 114 (AC-114.20).
- Amending spec 114: this spec extends its closed lists additively in a 5.x release.
- The backup and restore mechanism itself (spec 117), the new resources (specs 116, 118, 119) and scaling (spec 120). This spec only states how they are pinned, upgraded and tested.

## Open questions

- ~~Should the platform install and upgrade operators on real clusters?~~ Answered: yes, as pinned Argo CD applications per cluster, only for what the system needs, with opt-out `environments.<env>.operators: owner`. See AC-121.17, AC-121.18.
- ~~Add `instances.<env>.version` and `operators` beyond spec 114's lists?~~ Answered: yes, as additive 5.x extensions; spec 114 is not amended. See Problem, AC-121.6, AC-121.18.
- ~~How recent must a backup be before a major upgrade?~~ Answered: 60 minutes, read from `backup.last_success`. See AC-121.12.
- ~~Is the backup required in dev as well?~~ Answered: yes, in every environment. See AC-121.12.
- ~~Should staging follow `promote: after-dev-smoke` for resource upgrades?~~ Answered: yes; prod always by hand. See AC-121.8.
- ~~Add `/resource:upgrade <name> --to <major> [--env <env>]`?~~ Answered: yes. See AC-121.6, AC-121.7.
- ~~Which Postgres majors are supported?~~ Answered: 16, 17 and 18, any upward jump. See AC-121.3, AC-121.14.
- ~~Confirm: minor and patch pins roll dev first, with no backup check.~~ Answered: yes. See AC-121.11.
- ~~Confirm: a 15-minute health wait.~~ Answered: yes. See AC-121.15, AC-121.16.
- ~~Confirm: on a shared cluster an operator is upgraded once and every environment there is verified.~~ Answered: yes. See AC-121.21.
- ~~Confirm: local operator version overrides stay allowed, with a warning.~~ Answered: yes. See AC-121.4.
- ~~Which release is "previous" in the first end-to-end run?~~ Answered: the latest 5.0.x, with floating tags resolved and recorded. See AC-121.24.
- ~~Confirm: a cache key need not survive an upgrade.~~ Answered: yes. See AC-121.24 and Non-goals.
- ~~Should spec 117 add an on-demand backup command that AC-121.12's message names?~~ Answered: yes, `/resource:backup <name> --env <env>` in spec 117. See Problem and AC-121.12.
- ~~Should a major upgrade of a bucket, cache or broker require a backup first?~~ Answered: no; rolling and verification only, and the PR states "<name> has no backup". See AC-121.27.

## Changelog

- 2026-10-26 created
- 2026-10-26 amended: answers folded in (operators per need with opt-out, `instances.<env>.version`, `/resource:upgrade`, 60-minute backup from `backup.last_success`, sibling names from specs 115–120); stated as an additive 5.x extension of spec 114
- 2026-10-26 amended: AC-121.12 names `/resource:backup` (spec 117); added AC-121.27 (no backup check for bucket, cache and broker majors)
- 2026-10-26 approved
- 2026-10-28 readings recorded at plan time (design.md, "Spec readings"): an engine image carries an exact tag and a digest, so a `system.yaml` without the new keys renders identically except for its image references (AC-121.2, AC-121.3); Postgres 16–18 are the supported upgrade targets and 15 stays renderable as deprecated, since dropping it would need a major release (AC-121.3, AC-121.26); a bucket has no `version` and `/resource:upgrade` refuses it, its image moving like a minor pin (AC-121.3, AC-121.27); External Secrets, Kyverno and LGTM are installed only for the answer `property_operators: install`, the default for new repos, `owner` for existing ones (AC-121.17); "with access to an environment's cluster" means `doctor --context` (AC-121.19); a gitops repo deploys every environment to one cluster, so AC-121.21 governs instead of AC-121.20; the first upgrade run adds backups after the update, creates other resources only where the previous release supports them, and "not tagged" is a CI check plus the release procedure, not automation (AC-121.24)

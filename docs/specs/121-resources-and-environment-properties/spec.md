---
spec_id: 121-resources-and-environment-properties
title: Resources and environment properties upgrade safely
status: draft
priority: P1
---

# 121 — Resources and environment properties upgrade safely

## Problem

A system owner cannot say today which database, collector or operator versions run in their environments, and cannot upgrade them safely. The 5.0 renderer (spec 114) turns `resources.postgres.version` into a floating major image tag (`postgresql:17`). Every pull of the image can bring a different minor version, and nothing records which one. Changing 17 to 18 changes the tag in dev, staging and prod in one render. Whatever CloudNativePG then does (an offline in-place upgrade or a rejection, depending on the operator version) runs with no backup (Postgres has none today), no dev → staging → prod order, no check and no test. The only test checks that the tag ends in `postgresql:17`.

Only the collector image is pinned exactly. The operators behind environment properties and resources are installed only on the local cluster, by the local cluster script, at versions taken from environment variables: External Secrets, the CloudNativePG chart, Kyverno, LGTM, and Argo CD, which floats on `stable`. The user journey guide says that on real clusters "they must be installed by the owner". Nothing shows that a cluster set up by one platform release still works after the next.

Specs 115–120 add more resources and properties (named and external resources, a bucket, backups with Velero, a cache, a broker, KEDA scaling), so the gap grows with each one. This spec defines how all of them are pinned, upgraded and proven. The user asked us to prove that the upgrade procedure works, so the proof is an end-to-end test (AC-121.24).

## Stories

- As a system owner, I want every image and operator the platform runs to be pinned to an exact version per platform release, so that I know what runs in each environment and nothing changes without a commit.
- As a system owner, I want a database major upgrade to move through dev, then staging, then prod, each step only after the previous one is verified, so that a failed upgrade never reaches prod first.
- As a system owner, I want a major upgrade to be refused without a recent backup and to point me to the restore when verification fails, so that an upgrade can never lose data without a way back.
- As a cluster owner, I want the platform to tell me which operator versions my clusters run against the versions the release expects, and to upgrade them in order unless I manage them myself, so that a platform update does not silently break my cluster.
- As the platform maintainer, I want an end-to-end test that upgrades a running system from one release to the next and shows that its data and components survive, so that every release proves the upgrade path instead of claiming it.

## Acceptance criteria

### Pinned versions

- **AC-121.1** Given a platform release, when `cplat platform versions` runs, then it prints the release's versions table. The table has one row per image and per operator chart the platform renders or installs: the Postgres image of each supported major, the CloudNativePG operator, the OpenTelemetry collector, External Secrets, Kyverno, LGTM, Argo CD, and the images and operators of specs 116–120 once they ship. Each row shows its exact version, and each image row its digest. With `--json` it prints the same rows as JSON.
- **AC-121.2** Given the platform repository, when the pin check runs in CI, then it fails if any image or chart the platform renders or installs does not come from the versions table. It also fails on an image reference without a digest, on a floating tag (`latest`, `stable`, a bare major such as `17`), and on a chart without an exact version. The failure names each offending reference and where it occurs.
- **AC-121.3** Given `resources.postgres.version: 17`, when the system is rendered, then the database of each environment runs the exact image and digest that the release's table maps to major 17. Two renders with the same release produce the same image. A major that is not in the table fails the render and names the supported majors.
- **AC-121.4** Given the local cluster script of a release, when it creates or updates a cluster, then every operator, Argo CD included, is installed at the table's version. A version overridden by an environment variable is still installed, but the script prints a warning naming the operator, the override and the table's version.
- **AC-121.5** Given a migrated system, when `cplat model show --json` runs, then each resource instance reports its `version` (the major) and `pinned` (the exact image and digest for that environment). `/system:status` shows one row per resource with each environment's pinned version and the resource's health there.

### Rolling a resource upgrade through environments

- **AC-121.6** Given a platform database resource on major 17 in every environment, when `/resource:upgrade postgres --to 18` runs, then it opens one PR that sets major 18 for dev only. Staging and prod stay on 17, and the PR description lists the environment, the old and new major, and the exact image it moves to.
- **AC-121.7** Given dev upgraded and verified (AC-121.15), when `/resource:upgrade postgres --to 18 --env staging` runs, then staging moves to 18 in one PR. Prod moves the same way with `--env prod`. When every environment is on 18, the per-environment entries are removed and the resource's `version` is 18.
- **AC-121.8** Given staging with `promote: after-dev-smoke` (spec 114), when dev's verification of a resource major upgrade is green, then the staging step of AC-121.7 starts by itself. Prod is always upgraded by hand.
- **AC-121.9** Given `/resource:upgrade --env <env>` where the environment before `<env>` is not on the target major, or is on it but not verified, when it runs, then it changes nothing and fails naming that environment and its state.
- **AC-121.10** Given a PR that changes a resource's major in more than one environment at once (for example a hand edit of `version` with no per-environment entries), when its CI runs, then a check fails. The message names the resource and the environments, and says to use `/resource:upgrade`.
- **AC-121.11** Given a platform release that changes the exact image of a supported major (a minor or patch update), when the system takes that release through `/platform:update`, then only dev's pin changes. Staging and prod keep their previous pin until they are moved by the rule of AC-121.7 and AC-121.8. The backup check of AC-121.12 does not apply to a minor or patch move.

### Guards

- **AC-121.12** Given an environment whose resource has no successful backup (spec 117) from the last 60 minutes, when a major upgrade step for that environment runs, then it changes nothing and fails. The message names the time of the last successful backup (or "never") and the spec 117 backup command for that resource and environment.
- **AC-121.13** Given an external resource (spec 115), when `/resource:upgrade` runs for it, then it changes nothing and fails with "<name> is external: its owner upgrades it, the platform does not".
- **AC-121.14** Given a target major that is lower than the environment's current major, or a jump that the versions table does not list as a supported upgrade path for that engine, when `/resource:upgrade` runs, then it changes nothing and fails. A downgrade names restoring a backup (spec 117) as the way back. An unsupported jump names the intermediate major to upgrade to first.

### Verification after each step

- **AC-121.15** Given a resource upgrade step merged for an environment, when it is applied, then the platform waits up to 15 minutes for the resource to report healthy at the new version. It then runs the smoke tests (`/instance:verify`) of every component instance in that environment that uses the resource. The step counts as verified only if all of them pass, and `/system:status` shows the environment as upgraded.
- **AC-121.16** Given an upgrade step whose resource is not healthy after 15 minutes, or whose component smoke fails, when the run checks it, then it stops with exit code 1 and no later environment is upgraded, automatically or by `/resource:upgrade`. The output names the environment, the failed check, the time of the last successful backup and the spec 117 restore command for that resource and environment.

### Environment properties and operators

- **AC-121.17** Given an environment that is not opted out (AC-121.18), when the system is rendered, then each operator its environment properties and resources need gets one Argo CD application per cluster, pinned to the release's table version. The operators include the CloudNativePG operator, External Secrets, Kyverno, LGTM, and Velero, KEDA, the cache and the broker once specs 117–120 ship. Upgrading the platform release moves those pins.
- **AC-121.18** Given `environments.<env>.operators: owner`, when the system is rendered, then no operator application is rendered for that environment. `/platform:doctor` still checks that environment's cluster as in AC-121.19.
- **AC-121.19** Given `/platform:doctor` with access to an environment's cluster, when it runs, then it lists each operator that environment needs with the expected (table) version, the installed version and its CRD versions. It marks each one `ok`, `missing`, `older` or `newer`, and exits non-zero when any is `missing`, or `older` by a major version.
- **AC-121.20** Given environments on separate clusters, when an operator's pin changes, then it moves on dev's cluster first. Staging's and prod's clusters follow by the rule of AC-121.7 and AC-121.8, each after the earlier cluster's operator is healthy and the smoke tests of every component instance there are green.
- **AC-121.21** Given environments that share one cluster (as on the local cluster), when an operator's pin changes, then the operator is upgraded once, at the step of the earliest environment on that cluster. The smoke tests of every environment on that cluster are then run, and `/platform:doctor` notes that the environments share the operator.
- **AC-121.22** Given an operator upgrade whose chart version ships new CRD versions, when it is applied, then afterwards the cluster's CRDs of that operator are the versions of the table's chart version. Every resource the system renders is accepted by them, and the platform release check renders a sample system against them before the release.

### Releases

- **AC-121.23** Given a platform release, when its CHANGELOG section is written, then it lists every row of the versions table that changed, with the old and new version. Major changes are marked. The `/platform:update` PR of a repo lists the changes that affect that system, per environment.
- **AC-121.24** Given a candidate platform release, when the end-to-end upgrade test runs on a local cluster, then it does the following. It sets up a system with the previous release's versions table, with a database resource, plus a bucket, a cache and a broker once specs 116, 118 and 119 ship. It writes a database row, a bucket object, a cache key and a stream message, and takes a backup (spec 117). It updates to the candidate's versions table, upgrades the database one major through dev, staging and prod with `/resource:upgrade`, and then shows the following. The row, the object and the message can be read back unchanged (the cache key is not required to survive). The smoke tests of every component instance are green in each environment. `/platform:doctor` reports every operator `ok`. A release is not tagged while this test is red.
- **AC-121.25** Given the same end-to-end test, when a major upgrade is attempted without a recent backup and when dev's verification is forced to fail, then the first changes nothing in the cluster and the second leaves staging and prod on the previous major with their data readable.
- **AC-121.26** Given a candidate release that moves an operator by a major version, removes a CRD version the previous release used, or drops a supported resource major, when the release check runs, then it fails unless the release is a new major platform version. The failure names the changed rows.

## Non-goals

- Upgrading external resources (spec 115) or anything the system owner runs outside the cluster.
- Automatic rollback or downgrade: the way back from a failed major upgrade is the restore of spec 117, started by a person.
- Choosing a minor or patch version per system: the platform release decides it. `system.yaml` holds only the major.
- Upgrading the Kubernetes version of a cluster or its nodes.
- Zero-downtime major upgrades: a database may be unavailable during its major upgrade step.
- Versions or pins of component images: they stay in the overlays as in spec 114 (AC-114.20).
- The backup and restore mechanism itself (spec 117), the new resources (specs 116, 118, 119) and scaling (spec 120). This spec only states how they are pinned, upgraded and tested.

## Open questions

- Should the platform install and upgrade operators on real clusters? (suggested: yes, as platform-rendered Argo CD applications per cluster pinned to the release's table, with opt-out per environment through `environments.<env>.operators: owner`; alternatives: stay local-only and only report versions with `/platform:doctor`; always install with no opt-out; affects AC-121.17, AC-121.18, AC-121.20, AC-121.21)
- Conflict with spec 114: AC-114.19 allows only `replicas`, `storage` and `resources` per instance of the database, and AC-114.4 allows no `operators` key on an environment. Should 5.x add `instances.<env>.version` to resources and `operators` to environments? (suggested: yes, both in the release that ships this spec; alternatives: record the per-environment major only in the overlays; leave `operators` out and always install; affects AC-121.6, AC-121.7, AC-121.18)
- How recent must a backup be before a major upgrade? (suggested: 60 minutes; alternatives: 15 minutes; 24 hours; affects AC-121.12)
- Is the backup required in dev as well? (suggested: yes, in every environment; alternatives: staging and prod only; affects AC-121.12)
- Should a resource upgrade into staging follow the environment's `promote: after-dev-smoke` rule? (suggested: yes, the same rule as component instances, with prod always by hand; alternatives: resource upgrades are always manual in every environment; affects AC-121.8, AC-121.20)
- Add a new command `/resource:upgrade <name> --to <major> [--env <env>]` to the 5.0 command set of AC-114.59? (suggested: yes; alternatives: only hand edits of `version` plus the CI check of AC-121.10; affects AC-121.6, AC-121.7, AC-121.9, AC-121.13, AC-121.14)
- Which Postgres majors are supported? (suggested: 16, 17 and 18, with any upward jump among them allowed; alternatives: 17 and 18 only; affects AC-121.3, AC-121.14)
- Confirm: minor and patch pins move dev first and then follow the promote rule, with no backup check. (suggested: yes; alternatives: all environments at once with the platform update; affects AC-121.11)
- Confirm: the verification waits up to 15 minutes for the resource to report healthy. (suggested: yes; alternatives: 5 minutes; 30 minutes; affects AC-121.15, AC-121.16)
- Confirm: on a shared cluster an operator is upgraded once, at the earliest environment's step, and every environment on that cluster is then verified. (suggested: yes; alternatives: refuse operator upgrades on shared clusters until every environment is ready; affects AC-121.21)
- Confirm: environment variable overrides of operator versions on the local cluster stay allowed, with a warning. (suggested: yes; alternatives: remove the overrides; affects AC-121.4)
- Which release is "previous" in the first run of the end-to-end test, given that 5.0 has floating tags and no versions table? (suggested: the latest 5.0.x, with its floating tags resolved at test time and recorded in the test output; alternatives: start the test from the first release that has a table; affects AC-121.24)
- Confirm: a cache key need not survive an upgrade. (suggested: yes, the cache is not durable; alternatives: require it to survive; affects AC-121.24)

## Changelog

- 2026-10-26 created

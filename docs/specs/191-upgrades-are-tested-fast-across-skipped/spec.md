---
spec_id: 191-upgrades-are-tested-fast-across-skipped
title: Upgrades are tested fast, across skipped versions, and the database drill leaves the release gate
status: approved
priority: P1
shape: platform
tracks: [400]
---

# 191 — Upgrades are tested fast, across skipped versions, and the database drill leaves the release gate

## Problem

The upgrade e2e (spec 121, AC-121.24 and AC-121.25) updates a system made by the previous release to the candidate on a real k3d cluster with data, then drills a Postgres 16 → 17 major upgrade behind the backup guard. Since #401 and #483 it takes 22–25 minutes, and every release waits for it once (#400, closed as done, is this spec's origin). Three gaps remain. First, a template change that Kubernetes cannot apply in place (a changed StatefulSet selector or volume claim template) shows up only after about ten minutes of cluster setup, and a change that silently loses data (a renamed PersistentVolumeClaim or Secret) applies cleanly and may not show up at all. Second, the test only ever starts from the previous release, while repos that update rarely jump several versions at once (for example 5.0 → current), and that path is never tested. Third, the database drill (backups, the guard, three major steps with a forced failure) is the larger half of the run but tests code that few changes touch, and every release still waits for it.

## Stories

As a platform maintainer, I want a render comparison that finds changes Kubernetes cannot apply in place or that lose data in seconds, without a cluster, so that a breaking template change fails on its pull request with the object and field named.

As the owner of a system that updates rarely, I want the platform to test the upgrade from the oldest supported release to the candidate, so that a jump over several releases works as well as a single step.

As a platform maintainer, I want the release gate to wait only for the platform update part of the upgrade e2e, while the Postgres major drill runs nightly and on the changes that touch it, so that a release waits less without the drill going untested.

## Acceptance criteria

- **AC-191.1** Given a system rendered by a from-release and the same system after the candidate's `/platform:update` and render, when the upgrade render check compares the objects of each environment (matched by kind, namespace and name), then it reports as breaking: a changed `spec.selector` of a Deployment, StatefulSet, DaemonSet or Job; a changed `spec.volumeClaimTemplates` or `spec.serviceName` of a StatefulSet; a changed `spec.storageClassName` or `spec.accessModes`, or a smaller `spec.resources.requests.storage`, of a PersistentVolumeClaim; a changed storage class or smaller storage size of a Postgres cluster; a changed `spec.clusterIP` (when set) or `spec.type` of a Service; and a PersistentVolumeClaim, Secret, ExternalSecret, Postgres cluster or StatefulSet with volume claim templates that the from-release rendered and the candidate does not (a rename counts as removed). Each finding is one line `BREAKING <env> <Kind> <namespace>/<name> <field>: <old> -> <new or removed> (<immutable: Kubernetes refuses the change | loses data>)`, and the check exits 1 with a last line naming the number of findings, the from-release and the candidate.
- **AC-191.2** Given two renders whose differences are all outside AC-191.1 (a new object, a changed image or pin, a changed label or annotation outside a selector, a larger storage size, a removed object of another kind), when the upgrade render check runs, then it exits 0 and prints `OK: <n> objects in <environments> compared, <from-release> -> candidate, no breaking change`; it runs without a container runtime and without a cluster, and when either side fails to render it exits 2 naming the side (`from-release <tag>` or `candidate`) and the render's error.
- **AC-191.3** Given a breaking finding, when the changelog entries between the from-release and the candidate (the released sections after the from-release and the unreleased changelog fragments) contain a line `Upgrade step: <Kind> <field>: <what the system owner does>` for the same kind and field, then the finding is printed as `ACCEPTED <env> <Kind> <namespace>/<name> <field> (upgrade step: <text>)` and does not fail the check; a finding without such a line fails, and its line ends with `(accept it with a changelog line "Upgrade step: <Kind> <field>: ...")`.
- **AC-191.4** Given CI, when a pull request or a push to main changes the gitops-app template, the renderer, the platform update code, the versions table or the check itself, or adds a release heading, and every night, then a job named `upgrade render check` (timeout 5 minutes) runs the comparison twice, from the previous release and from the oldest supported release (AC-191.5), each in its own section headed `from <tag>:`, and fails when either fails; when both from-releases are the same tag it compares once and says so.
- **AC-191.5** Given the release tags, when the oldest supported release is chosen, then it is the newest patch tag of the first minor of the candidate's major (`vX.0.*`; v5.0.x today); every night and on manual dispatch a job named `e2e upgrade (oldest supported release → candidate)` runs the platform update part of the upgrade e2e (AC-191.6) from that tag; when no `vX.0.*` tag exists or it is the previous release, the job prints `skipped: <reason>` naming the tag or its absence and passes; the release gate does not require this job.
- **AC-191.6** Given a candidate, when the job `e2e upgrade (previous release → candidate)` runs, then it sets up on the previous release (a system with a Python service in dev, staging and prod, Postgres 16, and a bucket, a cache and a broker where that release supports them; floating references resolved and recorded; a row, an object, a cache key and a message per environment), applies the candidate's `/platform:update` and its pin moves one environment at a time with their verification, and checks that the row, the object and the message read back unchanged, every instance's smoke tests are green, `/platform:doctor` reports every operator `ok` and the API server accepts every rendered manifest; it adds no backups and upgrades no database major, and a release is not tagged unless its commit (or the head of its pull request with the same tree) has a green run of this job and of `upgrade render check`. (replaces AC-121.24)
- **AC-191.7** Given a job named `e2e upgrade drill (Postgres 16 → 17)`, when it runs every night, on manual dispatch, or on a pull request or push to main that changes the resource upgrade or backup code, the database rows of the versions table or the drill's own steps, then it runs the whole of AC-191.6 from the previous release, then the backup guard and the 16 → 17 major upgrade with the forced failed verification of AC-121.25, and ends with major 17 and the table's 17 minor in every environment, the data unchanged and the upgrade state `verified`; a pull request that changes none of these runs no drill, and the release gate does not require it.
- **AC-191.8** Given the contributing guide, when a contributor reads its CI section, then it names the four upgrade jobs, when each runs, which two the release gate requires, how a deliberate breaking change is accepted (AC-191.3) and how to run each one locally; an ADR records the split, a changelog fragment lists the change, and the verification of this spec records the duration of `e2e upgrade (previous release → candidate)` on the pull request that ships it next to the 22–25 minutes before (target: at most 15 minutes).

## Non-goals

- Argo CD in the upgrade test: it keeps applying the rendered manifests with kubectl (WITH_ARGO=0, see #325). Possible follow-up.
- Upgrading Java, Go or web components in the test: it keeps one Python service. Possible follow-up.
- Downgrade or rollback testing (the way back stays `/resource:restore`, spec 121's non-goals). Possible follow-up.
- Changing what the existing upgrade steps check, or making cluster setup itself faster (for example installing the operators in parallel).
- A hard wall-time criterion for the release gate: the 15-minute target is measured and recorded (AC-191.8), not asserted.

## Assumptions

- **A1** The render check builds its system the way the upgrade e2e does (the previous release's own `cplat` creates it, the candidate's `/platform:update` updates and renders it), so it compares what an owner's repo goes through, held pins included (other option: render one `system.yaml` with both renderers directly; affects AC-191.1, AC-191.2).
- **A2** The breaking list is the one in AC-191.1; a removed Deployment, ConfigMap or Service is not breaking, because Argo CD recreates it without data loss (other option: flag every removed object; affects AC-191.1, AC-191.2).
- **A3** A changed Service `spec.type` counts as breaking even where Kubernetes applies it in place, because it changes how the service is reached (other option: only a changed `spec.clusterIP`; affects AC-191.1).
- **A4** A deliberate breaking change is accepted by an `Upgrade step:` line in the changelog, read across every release between the from-release and the candidate, so a skipped-version jump sees the steps of the releases it skips (other option: an allow-list file in the repo, or a pull request label; affects AC-191.3, AC-191.4).
- **A5** An accepted breaking change does not by itself force a major platform release; AC-121.26 stays as it is (other option: list it among the reasons that need a major; affects AC-191.3).
- **A6** The render check is part of the release gate, because it costs seconds (other option: advisory only; affects AC-191.4, AC-191.6).
- **A7** The render check also compares the oldest supported release with the candidate on every run it makes, since that costs seconds too (other option: previous release only; affects AC-191.4).
- **A8** "Oldest supported" is the newest patch of the candidate major's first minor (`vX.0.*`), the release the upgrade e2e already falls back to; a repo on an older major goes through the major's migration first (other option: exactly `vX.0.0`, or the last N minors; affects AC-191.4, AC-191.5).
- **A9** The cluster run from the oldest supported release is nightly and on dispatch only, not a release gate: a skip-path break is visible within a day and before the next release, while gating would add another 15–20 minutes to every release, which is the wait this spec removes (other option: a release gate; affects AC-191.5).
- **A10** The run from the oldest supported release does the platform update part only, without the Postgres drill (other option: the drill from the oldest release too; affects AC-191.5).
- **A11** The drill repeats the platform update part instead of reusing the gate job's cluster, because CI jobs run on separate runners (other option: one job that runs both and reports two results; affects AC-191.7).
- **A12** A render that fails exits 2, apart from the exit 1 of a breaking finding, so that CI logs tell a broken renderer from a breaking change (other option: exit 1 for both; affects AC-191.2).

## Open questions

## Changelog

- 2026-11-12 created
- 2026-11-12 approved

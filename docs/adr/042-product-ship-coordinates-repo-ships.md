# ADR-042 — A product ship coordinates one repo ship per component, gated per repo, with serialized gitops merges

**Status:** accepted (2026-10-25, spec 097)

## Context

`/svc:ship` (ADR-028) takes one repo's spec unattended to `dev`. A product spec spans the gitops-app and several
component repos with `depends_on` between them (ADR-011). Shipping it unattended needs three things the single-repo
flow does not have: a schedule across repos, a rule for when a dependency counts as delivered, and a way to keep
several repos' gitops PRs (spec 076) from merging over each other in the one gitops-app repo. Building a second ship
engine for products would duplicate the CI waits, fix rounds, smoke and escalation rules that `cplat ship` already
implements and tests.

## Decision

- The product run (`cplat app-ship`, `/app:ship`) is a **coordinator**. Every component repo runs the unchanged
  `cplat ship` state machine in its own clone, linked by `cplat ship start --product <gitops-app dir>` (parent run,
  kube context, merge slot). The product run owns only: the schedule, the gates, the gitops-app's own PRs, and one
  `product-ship` run record that lists the repo ship `run_id`s.
- **Gates** decide when dependents start: a service exposed in `dev` passes on green smoke (ADR-040), a service not
  exposed in `dev` on Argo Synced/Healthy for the merged build, a library on its merged PR. The class is read from the
  gitops-app's `services.yaml` and `shapes.yml`, never inferred from free-text results.
- **Gitops merges are serialized** through one merge slot per product run (a local lock, waiters in plan order). A PR
  that no longer merges cleanly is never rebased or force-pushed: its repo escalates naming both PRs.
- Run state is local to the gitops-app clone and never committed; the spec and plan change on `main` only through
  PRs merged on green (publish at the start, `done` at the end).

## Consequences

- Every improvement to `cplat ship` (fix rounds, smoke, security patches) applies to product runs without change.
- One product run per gitops-app clone at a time; two machines shipping the same product are not serialized.
- A dependent repo waits for its dependency's full `dev` delivery, which makes a product run slower than
  `/app:build` but means no repo builds against a dependency that does not work in `dev`.
- A product-wide smoke across services and staging promotion are left to later specs (093 and a follow-up).

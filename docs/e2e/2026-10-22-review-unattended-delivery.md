# Review 2026-10-22: three lan repos against the platform

A review of three repos built and run with the platform on a home cluster ("lan", k3s with Argo CD and self-hosted ARC runners), done to find what stops Claude from running a feature unattended from spec to deployment. The repos: **stock-manager** (a Python service with a nightly pipeline), **stock-manager-gitops** (its gitops-app, which also holds the cluster's infrastructure), and **ai-ops** (a service-go controller that watches onboarded components). Specs 065–071 come from it.

## Findings

| # | Repo | Finding | Severity | Addressed by |
|---|---|---|---|---|
| 1 | all | Private repos on GitHub Free have no branch protection and no auto-merge. pin-dev's `gh pr merge --auto` fails, so `dev` never follows `main`, and nothing makes a merge wait for CI | high | 065, ADR-028 |
| 2 | stock-manager | Not created from a template: no `.copier-answers.yml`, devbox recipes, `CLAUDE.md`, allowlist or `docs/specs/`; one large `SPEC.md` with decisions, no criteria traced to tests | high | 071 (adopt), migration plan below |
| 3 | stock-manager | A deploy is a commit to the service repo's `main` that edits `deploy/k8s/kustomization.yaml` (32 such commits, no PRs); Argo tracks `main:deploy/k8s-lan` | high | 069, migration plan |
| 4 | stock-manager-gitops | `services.yaml` is empty; every app is a hand-written Argo Application, so pin-dev, `/gitops:promote` and `/shared:status` see nothing | high | 069 |
| 5 | all | The renderer cannot express CronJobs, PVCs, a login proxy or a Helm chart with CRDs, which is why 3 and 4 happened | high | 069, ADR-029 |
| 6 | ai-ops | Specs 009 and 010 are `done` without `verification.md`; no spec has a `design.md` | medium | 068 |
| 7 | ai-ops | Images pushed from a laptop and pinned by hand as 40-character SHAs in the gitops repo; no `.platform-app.yml`, so the template's pin-dev job does nothing | medium | 065, 069 (rollout) |
| 8 | ai-ops | Its own in-cluster CI (spec 010) duplicates GitHub Actions, now available through ARC (its spec 011); its triage agent calls `claude -p` with its own prompt instead of the platform's flows | medium | ai-ops spec 011; fix agent to call `/svc:fix-bug` |
| 9 | ai-ops | `docs/status.md` still says "no GitHub Actions" and calls spec 011 a draft | low | rollout |
| 10 | all | Runs end at "PR opened", or whenever the model stops; the user waits for CI, fixes, merges and pins by hand | high | 066, 067, 070 |
| 11 | stock-manager | The morning watch runs `claude -p --permission-mode dontAsk` with all of Bash allowlisted and fixes bugs directly on `main` | medium | 070 (allowlist-only headless runs), `/svc:fix-bug` + ship |

## stock-manager migration plan (not done in this change)

Moving the live app is a separate, reviewed step:

1. `cplat adopt --type service-python --data module_name=stockmanager` on a branch; adapt the `devbox run` recipes to the uv workspace (`app/`, `prototype/`).
2. Move `deploy/k8s` into stock-manager-gitops as `applications/stock-manager/external/stock-manager/` and register it as an `external` entry; switch the `lan` overlay's namespace to `stock-manager`.
3. Add `.platform-app.yml` and `GITOPS_TOKEN`, and the template's `pin-dev` job. Then delete the hand-written Argo Application and `deploy/` from the service repo in the same reviewed change.
4. Turn new SPEC.md decisions into specs (`/svc:spec`); have the morning watch file findings as issues or `/svc:fix-bug` runs instead of committing to `main`.

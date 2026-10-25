# Architecture

Why the platform looks the way it does.

## The problem

The ika100 fleet has many Python service repos (FastAPI-style, devbox-driven, k8s-deployed) plus one GitOps repo that wires them together via ArgoCD. The agentic Claude Code setup we built for the first service (money-maker) is ~99% generic — the 10 agents, 7 slash commands, and orchestration model would work for any repo with the same shape. But hand-copying them into each new repo doesn't scale:

- **Drift.** Each copy diverges from the others as agents get tweaked.
- **No central updates.** Improving the architect's plan format requires editing N repos.
- **Project-specific hardcoding.** `devbox.json`'s `--cov=<module>` and `<project>:scan` Docker tag have to be sed-replaced every time.

## The shape we chose

Two channels of distribution:

1. **Claude Code marketplace** — seven plugins (`svc`, `web`, `svc-java`, `svc-go`, `gitops`, `app`, `shared`) published from this repo. Consumers reference the marketplace in their `.claude/settings.json`; updates flow via `/plugin marketplace update`.

2. **Copier templates** — one template per shape (see `shapes.yml`) that ships the project skeleton: `devbox.json`, CI workflow, `CLAUDE.md`, Dockerfile, language manifests (no Kubernetes files: the gitops-app repo owns them, ADR-017). Updates flow via `/shared:update-service`, which re-applies the template with the repo's recorded answers on a review branch.

These two channels run at different speeds — agents evolve frequently, project skeletons evolve rarely — and `/shared:update-service` keeps the skeleton current without touching project-owned files. Maintaining two artifacts is cheaper than maintaining one big one that conflates both.

## Shapes

The platform is multi-shape: `service-python`, `library-python`, `web-nextjs`, `gitops-app`, `service-java`, `service-go`. `shapes.yml` is the registry (id → plugin, template, deployable?, detection). Commands detect a repo's shape from `.copier-answers.yml` (fallback: file sniffing, `scripts/detect-shape.sh`) and route each role to `<plugin>:<role>`; the `/svc:*` orchestrators, product-manager and architect stay shape-agnostic. Adding a shape is a documented checklist (`docs/templates.md`) enforced by `scripts/shapes.py check` in CI. Decisions: ADR-008 (detection), ADR-013 (plugin enablement), ADR-015 (registry).

**GitOps owns the manifests (v2).** Services ship an image; the product's `gitops-app` repo describes how each one runs in `services.yaml` and generates Deployment/Service/HTTPRoute with `render.py`. Argo reads only that repo, wiring between services is product configuration, and promotion pins an image tag (ADR-017).

**Two kinds of GitOps repo.** The *platform* GitOps repo (one per fleet) discovers every `deployable-service` repo by topic. A *`gitops-app`* repo (one per SaaS product) lists the product's services in `services.yaml` and pins versions per environment (`dev` tracks main, `staging`/`prod` are pinned by `/gitops:promote`); the ApplicationSets and overlays are generated from it (ADR-006/014). `/app:spec`, `/app:plan` and `/app:build` take a feature across a product's repos: one product spec, its criteria assigned per repo, each repo built from its own slice (ADR-011/023/026).

## Why not GitHub Templates

GitHub Templates fork once and then drift forever. Copier re-applies a template to an existing repo from recorded answers, skipping project-owned files (`_skip_if_exists`), so improvements to the CI workflow or devbox recipes flow into existing repos without re-cloning. (Copier's own 3-way `copier update` is not usable here: it needs the template's git history, and our templates live in subdirectories of this repo — hence `/shared:update-service`.)

## Why several plugins, not one

Different repo roles need different agents:

- A Python service needs `coder` / `tester` / `migrations` / `deployment`.
- The GitOps repo needs `deployment` (a different one — focused on ApplicationSets) and `promote`; no Python `coder`.
- A library needs `coder` / `tester` but no `deployment`.

Single-plugin would force every consumer to load every agent. The split lets each repo enable only what it uses (`svc` is enabled everywhere a `/svc:*` command is used, because it owns the orchestrators and the shape-agnostic PM/architect).

`shared` exists because `quality` and `security` are needed by every repo. Pulling them into a shared plugin avoids one definition per shape drifting apart.

## Why ArgoCD ApplicationSet

The standard alternative — manually registering each new service in the GitOps repo by editing a list of Applications — is friction that scales linearly with services. `ApplicationSet` with the GitHub `scmProvider` generator auto-discovers any repo with the `deployable-service` topic. New service repo + topic → Argo Application appears within ~3 minutes. Zero edits to the gitops repo.

The contract enforced by this convention:

- Service repos opt in via the GitHub topic `deployable-service` (the Copier template's post-task adds it automatically).
- Every service has `k8s/overlays/prod/kustomization.yaml`.
- Argo `Application` name == GitHub repo name.

Promotion to production (staging → prod) is the one explicit, human-approved step — `/gitops:promote` pins an image tag in the target overlay, shows an evidence summary and opens a PR. Staging follows a green dev smoke by itself through the gitops-app's self-merging `pin-staging` PR (spec 093, ADR-041; `promotion: {staging: manual}` switches it off). Argo reconciles after merge.

## What this is NOT

- It is **not** a service catalog or developer portal (Backstage territory). We don't need an internal UI yet — at the current scale, slash commands and a marketplace cover developer experience well enough.
- It is **not** opinionated about cloud or k8s flavor — manifests are pure Kustomize, the ApplicationSet uses ArgoCD's GitHub scmProvider, Flux is supported with minor changes (replace the ApplicationSet with `GitRepository` + a generator action).
- It is **not** a vendor of agents. Agents and templates are deliberately thin wrappers around devbox, gh, kubectl, and copier. We add intelligence (when to fan coders out, how to gate quality) but not new tooling.

## When this stops being the right shape

If the fleet grows past ~15–20 services with a dedicated platform team, the next step is Backstage-style scaffolder + service catalog. Until then, the marketplace + Copier combo is the sweet spot.

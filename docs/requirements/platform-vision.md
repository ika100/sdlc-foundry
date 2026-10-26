### Platform Vision PRD — Multi-Service-Type Claude Platform

**Status:** Implemented (P0 + P1; P2 items C4 `/system:ship`, E3 deferred) — open decisions resolved 2026-05-22, Java/Go shapes added as extensibility test 2026-05-22
**Author:** @ika100
**Last updated:** 2026-05-22
**Audience:** Future implementers (human + Claude agents)

---

## 1. Summary

Today `ika100/claude-platform` supports two repo shapes: a Python service (`service-python`) and a Python library (`library-python`), wired together by an external GitOps repo. To build full SaaS products on a microservice architecture the platform needs more shapes — a web frontend, a first-class GitOps "application" repo, and additional backend languages — plus the agents and slash commands that operate on each. The platform must be *extensible*: adding a future shape should follow a documented contract, not a custom PRD per language.

This document specifies the target state. It does not prescribe an implementation order; that comes from the architect after this PRD is approved.

## 2. Goals

1. One marketplace, a registry of supported shapes, agents tuned to each — and a documented contract for adding more.
2. Bootstrapping a new repo of any registered shape is a single slash command.
3. The same orchestration model (`/component:build`, `/component:fix`, `/component:fix`, `/component:release`) works across all shapes, with shape-specific agents routed in transparently.
4. GitOps repos describe whole *applications* (a set of services + their wiring) and are themselves a first-class shape with their own agents.
5. Updates to agents flow via `/plugin marketplace update`; updates to skeletons flow via `copier update`. Two channels, same as today.

## 3. Non-goals

- A developer portal / service catalog UI (still Backstage territory; see [[ARCHITECTURE]] §"What this is NOT"). Re-evaluate past ~15–20 services.
- Languages beyond Python, TypeScript, Java, and Go *in this PRD*. Adding more (Rust, Kotlin, …) follows the §4.1 add-a-shape contract rather than a new PRD.
- Cloud provider abstractions. Manifests stay Kustomize + ArgoCD.
- A new agent orchestration framework. We extend the existing `svc`/`gitops`/`shared` model; we don't replace it.

## 4. Shape registry

The platform supports the following shapes. New shapes are added per §4.1.

| Shape | Plugin | Template | Default stack | Status |
|---|---|---|---|---|
| `service-python` | `svc` | `service-python` | Python 3.12, uv, FastAPI | stable |
| `library-python` | `svc` (subset) | `library-python` | Python 3.12, uv | stable |
| `web-nextjs` | `web` | `web-nextjs` | Node LTS, pnpm, Next.js App Router | stable |
| `gitops-app` | `system` | `gitops-app` | Kustomize + ArgoCD ApplicationSet, env-only overlays | stable |
| `service-java` | `svc-java` | `service-java` | JDK 21 LTS, Maven, Spring Boot 3.x | stable (extensibility case study) |
| `service-go` | `svc-go` | `service-go` | Go 1.22+, stdlib `net/http` + `chi` router | stable (extensibility case study) |

`gitops-app` is distinct from the single platform-wide GitOps repo we already have. The platform-wide repo discovers all `deployable-service` repos via topic. A `gitops-app` repo is system-scoped — it pins which services, which versions, which environments make up one SaaS system. A user with N SaaS systems has N `gitops-app` repos.

`service-java` and `service-go` are in this PRD primarily to validate that §4.1's add-a-shape contract works in practice. Per-shape stack details (Maven vs Gradle, chi vs gin, etc.) are deferred to per-shape ADRs at implementation time.

### 4.1 Adding a new shape (the extensibility contract)

A shape is fully specified by three artifacts. To add a new shape, deliver all three in one PR:

1. **Copier template** at `templates/<shape>/` with a `copier.yml`, a `CLAUDE.md` tailored to the shape, a `devbox.json` that defines the canonical recipes (`test`, `lint`, `quality`, `image-build`, `deploy`, plus shape-specific ones), and the same "always re-templated" / "project-owned" file conventions as existing templates.
2. **Plugin** providing the shape's agents: at minimum `coder` and `tester`; `deployment` and `observability` if the shape produces a deployable artifact. The plugin may be new (`svc-java`) or extend an existing one (`svc` already covers `library-python` as a subset). Agents always invoke `devbox run <recipe>` — never raw tools.
3. **Shape detection registration**: an entry in the detection table maintained in [ADR-008](../adr/008-shape-detection.md) — primary mapping from the template's `_src_path` to the shape identifier, plus a sniffing-fallback rule (a file or content marker that uniquely identifies the shape for pre-Copier repos).

The Java and Go shapes are the reference implementations of this contract. After they ship, adding a third backend language (e.g. Rust) should be a documentable copy-paste exercise; if it isn't, the contract has a gap and this section gets revised before the next shape lands.

## 5. Personas

- **Solo founder / small team lead** (primary): builds and ships SaaS products on this platform. Owns one or more `gitops-app` repos plus the underlying services and libraries.
- **Contributor / future hire**: works on one service at a time. Needs `/component:build` and friends to work without platform knowledge.
- **Claude agent**: not a human, but a real consumer. Each agent reads `CLAUDE.md` and the marketplace plugins to do its job. PRD acceptance criteria explicitly include "an agent can do X without human handholding."

## 6. User stories

Stories are grouped by epic. Each has acceptance criteria a tester can verify. P0 = blocks first usable release; P1 = needed for the platform to be complete; P2 = nice-to-have, may be deferred.

### Epic A — Bootstrapping any registered shape

**A1 (P0). Universal bootstrap command.**
- As a developer, I can run `/component:new <name> --type <shape>` and get a working repo for any shape in the §4 registry.
- AC: the command resolves the shape, invokes Copier against `templates/<shape>/`, creates the GitHub repo with the correct topic (`deployable-service` for everything except `library-python` and `gitops-app`), and pushes the first commit.
- AC: existing shape-specific flags continue to work as aliases (`--library` → `library-python`, `--web` → `web-nextjs`, `--gitops` → `gitops-app`).
- AC (regression): `/component:new <name>` with no flag still produces a `service-python` repo.

**A2 (P0). Bootstrap acceptance per shape.**
The bootstrap command produces a working repo for every shape. Per-shape acceptance:
- `web-nextjs`: `devbox run dev` starts Next.js; `devbox run test`, `devbox run quality`, `devbox run image-build` all succeed; repo tagged `deployable-service`.
- `gitops-app`: `applications/<name>/applicationset.yaml` + `applications/<name>/overlays/{dev,staging,prod}/` + `system.yaml` exist; repo *not* tagged `deployable-service`; Argo reconciles with no manual edits.
- `service-java` (P1): `devbox run dev` starts a Spring Boot app on the configured port; `devbox run test`, `devbox run quality` (Spotless + Checkstyle or equivalent), and `devbox run image-build` all succeed; repo tagged `deployable-service`.
- `service-go` (P1): `devbox run dev` runs `go run ./cmd/<name>`; `devbox run test`, `devbox run quality` (`golangci-lint`, which includes `go vet` + `staticcheck`), and `devbox run image-build` all succeed; repo tagged `deployable-service`.

**A3 (P1). Extensibility contract is real.**
- Adding a new shape follows §4.1 with no PRD edits — the contract is sufficient.
- AC: `docs/templates.md` documents the contract end-to-end (file layout, agent requirements, detection registration).
- AC: the Java and Go shapes are the canonical worked examples referenced from that doc.

### Epic B — Per-shape agents

Each non-gitops shape needs language/framework-specific `coder`, `tester`, and (where deployable) `deployment` + `observability` agents. PM and architect agents stay shape-agnostic and route to the right plugin via the architect plan's `shape` field.

**B1 (P0). Shape-aware coder agents.**
- Each shape ships a `coder` that writes idiomatic code for that stack and always invokes `devbox run` (never raw `npm`/`pnpm`/`uv`/`mvn`/`go`).
- AC per shape: `web-nextjs` writes TS/TSX in App Router style, ESLint + `tsc --noEmit` clean. `service-java` writes Java 21 in Spring Boot 3.x conventions, Maven build green. `service-go` writes idiomatic Go, `go vet` + `staticcheck` clean. Python coder unchanged.

**B2 (P0). Shape-aware tester agents.**
- Each shape ships a `tester` that produces tests in that shape's idiom and runs `devbox run test`.
- AC per shape: `web-nextjs` produces Vitest tests, Playwright if e2e was enabled (per [ADR-002](../adr/002-web-testing-stack.md)). `service-java` produces JUnit 5 + Spring Boot Test, coverage via JaCoCo. `service-go` produces stdlib `testing` (plus `testify` if requested), coverage via `go test -cover`.

**B3 (P0). Shape-aware deployment agents.**
- Each *deployable* shape ships a `deployment` agent that writes Dockerfile + k8s manifests + CI workflow.
- AC (all shapes): multi-stage Docker build, non-root user; k8s `Deployment` + `Service` + `Ingress`; health/ready endpoints respond; CI matches the platform-wide workflow conventions.

**B4 (P0). Shape-agnostic PM and architect.**
- `product-manager` and `architect` produce specs and plans for any registered shape.
- AC: architect plan YAML metadata includes a `shape` field whose value must be a key in the §4 registry; orchestrator routes coder spawns to the correct plugin's coder agent based on `shape`.
- AC: PM user stories may target multiple repos in one feature ("add billing" → web changes + service changes + gitops bump).

**B5 (P1). Gitops-app composition agent.**
- The `gitops` plugin gains a `compose` agent that edits `system.yaml` and ApplicationSet manifests to add/remove services from an application.
- AC: can add a new service to an existing gitops-app with one slash command.
- AC: validates that every referenced service repo has the `deployable-service` topic before adding it.

**B6 (P1). Cross-repo promote agent (extension of existing `promote`).**
- `/instance:promote` works against a `gitops-app` repo, promoting a service's image tag `dev → staging → prod` within the *application's* gitops repo.
- AC: `/instance:promote <component> --to <to>` opens a PR against the gitops-app repo pinning the new tag.
- AC: works when invoked from inside the gitops-app repo OR from a service repo (auto-resolves the target gitops-app via a config file).

### Epic C — Slash commands span the full app lifecycle

**C1 (P0). `/component:build` is shape-aware.**
- Running `/component:build <description>` in any registered shape's repo invokes the correct shape's coder/tester/deployment chain.
- AC: detection follows [ADR-008](../adr/008-shape-detection.md); orchestrator dispatches to the right plugin's agents; `gitops-app` repos route to `compose` + `promote` instead.

**C2 (P1). `/system:plan` (new) spans multiple repos.**
- Running `/system:plan <description>` from a `gitops-app` repo can fan work out to multiple component services + the web frontend, then bump versions in the gitops-app overlays.
- AC: the command takes a feature description, plans which repos are touched, dispatches `/component:build` (or shape equivalent) into each affected repo's worktree, opens PRs in each, then opens a final PR in the gitops-app repo pinning the new tags after merges.
- AC: failure in one repo's PR pauses the chain and surfaces the error; partial state is recoverable.

**C3 (P1). `/component:release` works for web repos.**
- Releasing a Next.js repo follows the same semver + CHANGELOG + tag flow.
- AC: tag triggers a Docker image push tagged with semver (same matrix as Python service).

**C4 (P2). `/system:ship` (new) cuts a coordinated release across an application.**
- AC: bumps the application version (semver), pins each component service to its current `main` image tag in `prod` overlay, writes an aggregated CHANGELOG composed of each component's recent changes since the last app release.

### Epic D — Templates and updates

**D1 (P0/P1). Each registered shape has a Copier template.**
- AC (P0): `templates/web-nextjs/` and `templates/gitops-app/` exist with `copier.yml` and the same conflict-resolution semantics as `service-python`.
- AC (P1): `templates/service-java/` and `templates/service-go/` exist with parity to the other templates (canonical `devbox.json` recipes, CI workflow, Dockerfile, k8s manifests, CLAUDE.md, marketplace plugins enabled).

**D2 (P0). `copier update` works on existing repos of any shape.**
- AC: an existing web repo can pull skeleton updates (CI workflow, devbox recipes, Dockerfile base image bumps) via `copier update --skip-answered` without losing project-owned files.

**D3 (P1). Template authoring guide.**
- A short doc explains how to add a new shape's template (file layout, what goes in `copier.yml`, which files are "always re-templated" vs project-owned).
- AC: doc lives at `docs/templates.md` and is referenced from `ARCHITECTURE.md`.

### Epic E — Quality, security, observability across shapes

**E1 (P0). `/component:check` works on every shape.**
- AC: Python repo — ruff + mypy + pip-audit + detect-secrets + bandit + trivy.
- AC: `web-nextjs` repo — ESLint + `tsc --noEmit` + `pnpm audit` + detect-secrets + trivy.
- AC: `gitops-app` repo — `kustomize build` validation + `kubeconform` + detect-secrets + opa/conftest if policies are present.
- AC (P1): `service-java` repo — Spotless/Checkstyle + Maven build + OWASP Dependency-Check + detect-secrets + trivy.
- AC (P1): `service-go` repo — `gofmt` + `go vet` + `staticcheck` + `govulncheck` + detect-secrets + trivy.

**E2 (P1). Observability agent for web shape.**
- The `web` plugin's `observability` agent wires OpenTelemetry for browser + server, structured logging on the server side, and a `/api/metrics` endpoint if requested.
- AC: produces a wired-up Next.js repo where `/api/health`, `/api/ready`, and `/api/metrics` all respond.

**E3 (P2). Security agent extensions.**
- AC: web-shape security agent runs SCA against `package.json`, checks for known-vulnerable React/Next versions, runs trivy on the built image.

### Epic F — Documentation and onboarding

**F1 (P0). `ADOPTING.md` covers every shape.**
- AC: existing doc adds sections for "Migrating a web repo" and "Migrating a gitops-app repo."

**F2 (P0). `AGENTS.md` lists the new agents.**
- AC: each new agent (web coder, web tester, web deployment, web observability, gitops compose) appears in the table with model selection rationale.

**F3 (P1). Per-shape `CLAUDE.md` content is templated.**
- AC: each Copier template ships a `CLAUDE.md` tailored to its shape (devbox recipes, conventions, branch rules) so consumers don't write that file by hand.

## 7. Acceptance signal for "platform is done"

A new user can, from scratch, in under one working day:

1. `/component:new my-saas --gitops` — creates the application repo.
2. `/component:new my-saas-api` — creates a backend service.
3. `/component:new my-saas-web --web` — creates the frontend.
4. In each service repo: `/component:build "ping endpoint"` / `/component:build "landing page"` — feature lands with tests, CI passes, image pushed.
5. From the gitops-app repo: `/component:add add my-saas-api && /component:add add my-saas-web` — application now declares both services.
6. `/instance:promote my-saas-api dev staging && /instance:promote my-saas-web dev staging` — staging pinned to the new images, Argo reconciles, app is live.

No hand-edited YAML, no copy-pasted boilerplate, no out-of-band `npm`/`pip`/`docker` commands.

## 8. Constraints & assumptions

- Every shape uses `devbox` as the canonical task runner — even web. `devbox.json` recipes wrap `pnpm`/`npm` the same way they wrap `pytest`/`uv`. ([[AGENTS]] §"Golden rule")
- All shapes' deploys go through Kustomize + ArgoCD. We do not add Helm, Terraform, or raw `kubectl apply` paths in this PRD.
- The marketplace stays GitHub-based (`ika100/claude-platform`). No private registries.
- Python version policy stays at 3.12+ (consumer-overridable). Node version policy: TBD in §11.

## 9. Out of scope (revisit later)

- Mobile (iOS/Android) shape.
- Worker-only shape distinct from `service-python` (today's template already handles workers via `devbox run worker`).
- Multi-cluster routing logic (the platform GitOps repo's ApplicationSet generator handles single-cluster discovery; multi-cluster is its own design problem).
- Secret management — assumed to be External Secrets Operator + a cloud KMS, configured at cluster bootstrap, not by this platform.

## 10. Risks

| Risk | Impact | Mitigation |
|---|---|---|
| TypeScript ecosystem churn (Next.js major versions, app router changes) | High — template rots faster than Python | Pin Next.js major in template, `copier update` flow handles bumps, write a TS upgrade ADR per major |
| Cross-repo orchestration complexity (`/system:plan`) | High — partial failure modes are nasty | Start with `/system:plan` as a *plan-only* command (Epic C2 in P1, not P0); execution lands later once we trust the planning |
| Architect plan format changing to support `shape` field | Medium — breaks existing plans | Make `shape` optional with `service-python` as the default; old plans still work |
| Two `gitops` notions (platform-wide vs per-app) confuse users | Medium | Rename: platform-wide repo stays "platform gitops"; per-app repos are "application repos" / `gitops-app` shape. Update docs accordingly |
| Web tester agent flakiness (Playwright in CI) | Medium | Default to Vitest only; Playwright is opt-in per repo via a Copier prompt |

## 11. Resolved decisions

Resolved on 2026-05-22. Each becomes an ADR under `docs/adr/` before implementation; the rationale here is the short form.

1. **Web testing stack — Vitest + Playwright opt-in.** Vitest is on by default for unit/component tests. Copier prompt `needs_e2e?` toggles a Playwright scaffold (`e2e/` dir, `devbox run e2e` recipe). Rationale: cheap default for libraries and simple UIs, opt-in for products that actually need browser flows. → ADR-002.
2. **Web package manager — pnpm.** Strict lockfile, content-addressed store (fast CI), workspace-ready. Rationale: the serious-TS default for 2026; npm is slower with worse hoisting; bun is still ecosystem-young. → ADR-003.
3. **Next.js router — App Router only.** Template scaffolds App Router; Pages Router is not supported. Rationale: new Vercel docs assume it; supporting both doubles the surface agents must reason over. → ADR-004.
4. **Node version policy — pin current LTS in template, bump via `copier update`.** Template pins one Node major (current LTS at template release); platform PRs bump it; consumers pull via `copier update`. Rationale: reproducibility parity with how we handle Python. → ADR-005.
5. **`gitops-app` overlay structure — env-only (`dev/staging/prod`).** No region nesting in v1. Rationale: matches every upstream Argo example; multi-region is a real but separate problem to design later, and pre-building it bloats single-region products. → ADR-006.
6. **Cross-repo orchestration — plan-only in v1, execution in v2.** `/system:plan` v1 produces a multi-repo plan ("repo A needs X, repo B needs Y, gitops-app pins both after merge"); user runs `/component:build` per repo. Execution promotes to v2 once the planner is trusted. Rationale: partial-failure recovery across multiple PRs is the hard problem; plan-only delivers ~80% of the leverage with ~10% of the risk. → ADR-007.
7. **Shape detection — `.copier-answers.yml` with sniffing fallback.** Primary: parse `_src_path` from `.copier-answers.yml` (e.g. `gh:ika100/claude-platform/templates/web-nextjs`). Fallback for pre-Copier repos: sniff (`next.config.*` → web; `pyproject.toml` + `Dockerfile` → service-python; `applications/*/applicationset.yaml` → gitops-app; `pyproject.toml` without `Dockerfile` → library-python). Rationale: uses existing artifacts, no extra config file to maintain. → ADR-008.

## 12. References

- [[ARCHITECTURE]] — why the platform looks the way it does today.
- [[AGENTS]] — orchestration model the new shapes plug into.
- [[ADOPTING]] — onboarding flow that the new shapes extend.

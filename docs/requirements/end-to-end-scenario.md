# End-to-end scenario: building `taskboard.saas`

**Purpose:** harden [platform-vision.md](platform-vision.md) by walking a realistic SaaS build from zero. As of 2026-05-22 this doc shows the canonical post-UX flow; the original pre-UX friction that motivated each improvement is preserved in the Resolution log and UX improvements proposed sections below, and called out per phase in "Pre-UX baseline" notes.

**Status (2026-10-07):** `/system:new` (Phase 1, UX-2) is **built** ([STORY-033](../backlog.md)); `shapes` (UX-4) was **dropped**. Everything in this walkthrough exists except interactive mode and the per-component compose options (`--expose`, env wiring), which stay with `/component:add`. The gitops-app repo is named after `app` (`taskboard`, not `taskboard-app`).

**Persona:** Eike (solo founder). Goal: ship a distributed-team task-board SaaS in one afternoon.

**Target system:**

```
taskboard.saas
├── taskboard-web        (web-nextjs)       — landing page + dashboard
├── taskboard-api        (service-python)   — main API, auth, CRUD
├── taskboard-analytics  (service-java)     — usage reports (heavy compute)
├── taskboard-webhooks   (service-go)       — high-throughput webhook ingest
├── taskboard-models     (library-python)   — Pydantic models shared by python services
└── taskboard-app        (gitops-app)       — composition repo: pins all services in dev/staging/prod
```

---

## Phase 1 — Bootstrap (one command, two minutes)

Eike writes a manifest describing the SaaS:

```yaml
# app.yml
app: taskboard
components:
  - name: taskboard-web
    shape: web-nextjs
  - name: taskboard-api
    shape: service-python
  - name: taskboard-models
    shape: library-python
  - name: taskboard-analytics
    shape: service-java
  - name: taskboard-webhooks
    shape: service-go
```

Then runs one command:

```bash
/system:new taskboard --from app.yml
```

(Or `/system:new taskboard --interactive` for the TUI route. Valid `shape:` values are the ids in `shapes.yml`; an unknown `--type` on `/component:new` lists them.)

> **Built.** The same result step by step: `/component:new taskboard --gitops`, one `/component:new <name> --type <shape> --app <org>/taskboard` per component, then `/component:add add <services...>`.

**Expected behavior:**
- `taskboard-app` (the `gitops-app` shape) created first.
- Five component repos created next, each tagged according to `shapes.yml.deployable`.
- One composition PR opened against `taskboard-app` adding all five into `system.yaml` via [batch compose-add](../adr/014-gitops-app-composition-spec.md).
- Each new repo has its plugin auto-enabled per [ADR-013](../adr/013-plugin-auto-enable.md); first Claude Code session lands fully wired.
- Pre-flight checks (per A1) — name availability, `gh auth`, marketplace freshness — run once at the top of the batch; any failure aborts before side effects.
- `--dry-run` available (`/system:new taskboard --from app.yml --dry-run`) to preview every repo, topic, and Copier input without executing.

**What this exercises:** A4 universal app bootstrap; A1 per-component bootstrap with canonical `--type` + pre-flight + `--dry-run`; B5 batch compose; [ADR-013](../adr/013-plugin-auto-enable.md) auto-enable; [ADR-015](../adr/015-shape-registry-as-code.md) `shapes.yml` as the source of valid `--type` / `shape:` values.

**Pre-UX baseline:** 6 separate `/component:new` invocations plus 4 manual `/component:add add` calls = 10 commands; now 1 command. See UX-2, UX-3.

**Remaining open:** Q1 (component ordering inside `app.yml`) — `new-app` topologically sorts (gitops-app first, libraries before services, services before frontends) regardless of input order; worth a clarifying note in [ADR-014](../adr/014-gitops-app-composition-spec.md) or `templates.md`.

---

## Phase 2 — First feature in one repo (`/component:build`)

Eike enters `taskboard-api/` and runs:

```bash
/component:build "POST /tasks endpoint that accepts title + assignee_email, returns the created task with id"
```

**Expected behavior (per PRD §6 C1, [ADR-008](../adr/008-shape-detection.md)):**
- Shape detected as `service-python` from `.copier-answers.yml`.
- Orchestrator routes through `svc` plugin: product-manager → architect → coder → tester → quality → security → deployment.
- A `feature/post-tasks-endpoint` branch is created, PR opened.
- Image is built and pushed as `sha-<short>` on merge to main (per CLAUDE.md docker pipeline). Argo's `dev` overlay tracks `latest` per [ADR-014](../adr/014-gitops-app-composition-spec.md), so `taskboard-api` in dev gets the new code within ~3 minutes of merge — no manual promote.

**What this exercises:** C1 shape-aware orchestration; B4 PM/architect shape-agnostic with python routing.

**Remaining open:** Q6 (cross-shape dependency awareness) — does the architect notice that `taskboard-api` could depend on `taskboard-models` and add a step to declare the dependency? Agent-quality concern (prompt design), not a spec gap.

---

## Phase 3 — Multi-repo feature (`/system:plan` v1, plan-only)

Eike wants to add **billing**: a Stripe webhook handler (Go), an API endpoint to expose subscription status (Python), a `Subscription` model (Python library), and a paywall UI (Next.js). From `taskboard-app/`:

```bash
/system:plan "add Stripe-based billing: webhook handler for subscription events, GET /me/subscription endpoint, paywall on the dashboard"
```

**Expected behavior (per [ADR-007](../adr/007-cross-repo-orchestration-scope.md), [ADR-011](../adr/011-multi-repo-plan-format.md), plan-only):**
- Writes `docs/plan/billing.md` in `taskboard-app/` with `status: draft` and a topo-sorted `repos[]` listing each affected repo plus its `depends_on`, `arguments` block, and `done: false`.
- The plan's `gitops_pin[]` section describes which overlays should be re-pinned after which merges.
- No PRs opened outside `taskboard-app`.

The plan tells Eike the order: `taskboard-models` first (new `Subscription` model), then `taskboard-api` and `taskboard-webhooks` in parallel (both depend on models), then `taskboard-web` (depends on api). He works it via `--from-plan`:

```bash
cd ../taskboard-models && /component:build --from-plan ../taskboard-app/docs/plan/billing.md
# ... PR merges; ADR-011 state machine flips repo done:true ...
cd ../taskboard-api && /component:build --from-plan ../taskboard-app/docs/plan/billing.md
cd ../taskboard-webhooks && /component:build --from-plan ../taskboard-app/docs/plan/billing.md
# ... both PRs merge ...
cd ../taskboard-web && /component:build --from-plan ../taskboard-app/docs/plan/billing.md
```

`--from-plan` reads the per-repo `arguments` block keyed by repo id (defaulting to the current repo via `.platform-app.yml`), then runs `/component:build` with those arguments. No copy-paste, no re-typing prompts.

(In second run, UX-6 / PRD C5 surfaces this as `/system:spec show billing` — Eike sees a live checklist. First run he eyeballs the plan file.)

**What this exercises:** C2 plan-only multi-repo planning; C1 `--from-plan` consumption; [ADR-011](../adr/011-multi-repo-plan-format.md) plan schema with `depends_on` topo-sort.

**Pre-UX baseline:** Eike had to manually copy multi-line `arguments` blocks from the plan and paste them into each `/component:build` invocation. See UX-5.

**Remaining open:** none — Q7, Q8, Q9, Q10 all resolved (see Resolution log).

---

## Phase 4 — First deployment (status + batch promote)

`/system:new` already composed the services into `taskboard-app` during Phase 1, so the `dev` overlay tracks `latest` from each service's main branch ([ADR-014](../adr/014-gitops-app-composition-spec.md)). Once the four billing PRs from Phase 3 merge, dev auto-updates within ~3 minutes (Argo reconcile).

After verifying dev with `/system:status`:

```bash
# in taskboard-app/
/system:status
```

```
taskboard.saas (ika100/taskboard-app)
                        dev          staging      prod         drift
taskboard-api          latest       —            —            (new in dev)
taskboard-web          latest       —            —            (new in dev)
taskboard-analytics    latest       —            —            (new in dev)
taskboard-webhooks     latest       —            —            (new in dev)
taskboard-models       (library, v0.1.0)

Open PRs (cross-fleet): none
```

Eike promotes everything one env step:

```bash
/instance:promote --all dev staging
```

One PR pinning every service in `system.yaml` to its current `sha-<short>` in the `staging` overlay. After merge + Argo reconcile, another `/system:status` confirms staging matches dev. Same pattern for `staging → prod` after smoke tests.

**What this exercises:** B6 batch promote; C6 `/system:status`; [ADR-014](../adr/014-gitops-app-composition-spec.md) batch ops + List-generator AppSet.

**Pre-UX baseline:** 4 individual `/component:add add` + 4 individual `/instance:promote` invocations = 8 PRs. Now 0 explicit compose calls (Phase 1 handled it) + 1 batch promote PR per env step. See UX-7, UX-8.

**Remaining open:** Q16 (rollback) — out of scope per [§9](platform-vision.md#9-out-of-scope-revisit-later); revert PR against the prior pin commit is the supported path.

---

## Phase 5 — Operations: bug fix + release

A Sentry alert: `taskboard-webhooks` is dropping retries on Stripe 5xx. Eike runs:

```bash
# in taskboard-webhooks/
/component:fix "Stripe webhook retries on 5xx are dropped instead of NACKing"
# ... fix lands, PR merges, sha-<short> auto-pinned in dev via Argo ...
/component:release
```

**Expected behavior:**
- `/component:fix` runs the `svc-go` plugin's coder → tester loop, opens PR.
- `/component:release` is dispatched per [ADR-008](../adr/008-shape-detection.md) shape detection to the `svc-go` `release` agent ([ADR-012](../adr/012-per-plugin-release-agent.md)): updates `CHANGELOG.md`, opens release PR; after merge, pushes the `v0.2.1` tag.
- CI builds the image with `git describe` injected via `-ldflags`; pushes `v0.2.1`, `0.2`, `0`, `latest`, `sha-<short>`.

Promote the fix:

```bash
# in taskboard-app/ — single service, positional form per the §8 verb convention
/instance:promote taskboard-webhooks staging prod
```

**What this exercises:** [ADR-012](../adr/012-per-plugin-release-agent.md) per-plugin release agents (Go uses git-tag + ldflags injection); B6 single-service promote (positional form, not `--all`); [ADR-008](../adr/008-shape-detection.md) shape detection routing.

**Remaining open:** none.

---

## Phase 6 — Extensibility test: add a Rust shape

Two months in, taskboard needs an ML inference service. A contributor adds `service-rust` as a new shape. Per [§4.1](platform-vision.md#41-adding-a-new-shape-the-extensibility-contract), one PR delivers **four artifacts**:

1. **`shapes.yml` row** — the canonical registry entry ([ADR-015](../adr/015-shape-registry-as-code.md)):
   ```yaml
   - id: service-rust
     plugin: svc-rust
     template: service-rust
     deployable: true
     library: false
     detection:
       copier_src: templates/service-rust
       sniff: ["Cargo.toml"]
     default_stack:
       language: rust
       edition: "2024"
       framework: axum
     status: planned
     adr: [<future-rust-stack-adr>]
   ```
2. **`templates/service-rust/`** with `copier.yml`, `CLAUDE.md`, `devbox.json` (recipes: `test` → `cargo test`, `lint` → `cargo clippy -- -D warnings`, `quality` → `cargo fmt --check && cargo clippy`, `image-build`, `deploy`, …).
3. **`plugins/svc-rust/`** with `coder.md`, `tester.md`, `deployment.md`, `release.md`, `observability.md`, `hooks/hooks.json`.
4. **[ADR-008](../adr/008-shape-detection.md) detection table update** — primary mapping + sniffing-fallback entry. Kept in sync with `shapes.yml` by CI.

Plus a stack ADR following the [ADR-009](../adr/009-service-java-stack.md) / [ADR-010](../adr/010-service-go-stack.md) precedent (Rust edition, async runtime, HTTP framework, Docker base image).

Then Eike creates the service:

```bash
/component:new taskboard-ml --type service-rust
```

`shapes.yml` validates `--type`, the right Copier template is invoked, `svc-rust` plugin auto-enables per [ADR-013](../adr/013-plugin-auto-enable.md), CI green on first push. `shapes.yml` is the only list of shapes, so the new shape is valid at once.

**What this exercises:** A3 extensibility contract is real; [ADR-015](../adr/015-shape-registry-as-code.md) registry-as-code in action.

**Remaining open:** UX-9 (`new-shape` scaffolding helper) — would collapse this contributor flow to `new-shape service-rust --based-on service-go` plus filling in language specifics. Deferred to second run; for first run, the contributor copies from the Java/Go templates by hand.

---

## Phase 7 — Operational edge cases (boundary checks)

A few edge cases the spec now has concrete answers for; one cluster remains out of scope.

| # | Question | Status | Resolution |
|---|---|---|---|
| Q22 | `taskboard-models` major bump breaks consumers | Out of scope | [§9](platform-vision.md#9-out-of-scope-revisit-later) — library version negotiation across consumers; bump per repo, time as a human-coordinated event |
| Q23 | cross-service shared env vars | Out of scope | [§9](platform-vision.md#9-out-of-scope-revisit-later) — each service owns its overlay; shared values flow through External Secrets Operator at cluster level, referenced independently per service |
| Q24 | stale `/system:plan` plans | First run: manual `git rm`; second run: spec'd | UX-6 / PRD C5 — `/system:spec abandon <slug>` + lifecycle filtering |
| Q25 | lockstep `copier update` across repos | Out of scope | [§9](platform-vision.md#9-out-of-scope-revisit-later) — per-repo only; future `/platform:update` may batch |
| Q26 | service deprecation / archival | Mechanism shipped; rest out of scope | `/component:add remove <svc>` ([ADR-014](../adr/014-gitops-app-composition-spec.md)) detaches; GitHub repo archival and inter-shape migration are out of scope per [§9](platform-vision.md#9-out-of-scope-revisit-later) |

None of the above blocks the first-run scenario.

---

## Command-count comparison

| Phase | Pre-UX | Post-UX | Saving |
|---|---|---|---|
| 1 — Bootstrap | 10 (6× new-service + 4× compose add) | 1 (`/system:new`) | 9 |
| 2 — First feature | 1 | 1 | 0 |
| 3 — Multi-repo (4 repos) | 5 (1× build-feature + 4× paste-and-run) | 5 (1× app build-feature + 4× `--from-plan`) | 0 commands, but 4 multi-line copy-pastes eliminated |
| 4 — Deployment per env step | 8 (4× compose add already counted above + 4× promote) | 1 (`/instance:promote --all`) + 1 verify (`/system:status`) | 6+ |
| 5 — Bug fix + release + promote | 3 | 3 | 0 (single-service flow already lean) |
| 6 — Add a new shape (creating taskboard-ml) | 1 | 1 | 0 |

**Headline:** Eike's first afternoon goes from ~22 commands + 4 multi-line copy-pastes down to ~10 commands and zero copy-paste.

---

## What this scenario hardens

| Severity | Count | Examples |
|---|---|---|
| Critical (contradiction or unresolvable blocker) | 1 | §6 C2 AC ↔ ADR-007 conflict (Q7) — resolved |
| Design gap (architect needs to resolve before implementation) | 9 | Plan-format schema (Q8), gitops-app config file (Q15), shape-registry-as-file (Q20), per-shape release agent (Q17), ApplicationSet generator type (Q13), initial `dev` pin policy (Q14), cross-repo dependency ordering (Q9), library distribution (Q4), plugin enabling (Q19) — all resolved (ADRs 011–016) |
| Spec gap (should be added but lower priority) | 11 | Failure recovery (Q3), command-ordering semantics (Q1), naming collisions (Q3), rollback (Q16), CHANGELOG format (Q18), compose-remove (Q12, Q26), copier-update lockstep (Q25), cross-service env vars (Q23), shape-registry validation source (Q5/Q21) |
| Documentation only (acknowledge as out-of-scope or covered) | 5 | Plan housekeeping (Q24), library version negotiation (Q22), migration between shapes, secret management boundary (Q23), etc. — all in PRD §9 |

## Resolution log (2026-05-22)

| Question | Status | Resolution |
|---|---|---|
| Q4 — library distribution | Resolved | [ADR-016](../adr/016-library-python-distribution.md) — git+https with GITHUB_TOKEN |
| Q5 — default `shape` field | Resolved | [ADR-008](../adr/008-shape-detection.md) *Consequences* — defaults to `service-python` for back-compat |
| Q7 — C2 ↔ ADR-007 contradiction | Resolved | PRD §6 C2 rewritten to match plan-only v1 |
| Q8 — multi-repo plan schema | Resolved | [ADR-011](../adr/011-multi-repo-plan-format.md) |
| Q9 — inter-repo dependency ordering | Resolved | [ADR-011](../adr/011-multi-repo-plan-format.md) — `depends_on` per repo |
| Q13 — ApplicationSet generator | Resolved | [ADR-014](../adr/014-gitops-app-composition-spec.md) — List generator from `system.yaml` |
| Q14 — `dev` overlay pin policy | Resolved | [ADR-014](../adr/014-gitops-app-composition-spec.md) — `latest` (track-main) |
| Q15 — gitops-app config file | Resolved | [ADR-014](../adr/014-gitops-app-composition-spec.md) — `.platform-app.yml` at service repo root |
| Q17 — per-shape release agent | Resolved | [ADR-012](../adr/012-per-plugin-release-agent.md) — per-plugin |
| Q19 — plugin auto-enable | Resolved | [ADR-013](../adr/013-plugin-auto-enable.md) — auto-enable on `/component:new` |
| Q20, Q21 — shape registry as code | Resolved | [ADR-015](../adr/015-shape-registry-as-code.md) — `shapes.yml` |
| Stale references (10) | Resolved | PRD + ADR-001 + ADR-008 cleaned up |

**Still open** (lower priority, tracked here for visibility):

| Question | Note |
|---|---|
| Q1 — component ordering at bootstrap | Behavior unspecified; default to "any order works" — `new-app` topo-sorts internally. Add a clarifying note in [ADR-014](../adr/014-gitops-app-composition-spec.md) or `templates.md` |
| Q3 — naming collisions / `/component:new` resume flag | Pre-flight `gh repo view` check spec'd in A1; `/system:new --resume` |
| Q6 — architect cross-shape dependency awareness | Agent-prompt-quality concern, not a spec gap |
| Q12 — `compose remove` | Spec'd in [ADR-014](../adr/014-gitops-app-composition-spec.md) and PRD B5 |
| Q16 — rollback | Out of scope for v1; revert PR is the supported path |
| Q18 — CHANGELOG aggregation format | Spec'd in [ADR-012](../adr/012-per-plugin-release-agent.md); `/system:ship` (P2) consumes it |
| Q22, Q23, Q24, Q25, Q26 | All in PRD §9 |

## UX improvements proposed (from this walkthrough)

Walking the scenario surfaces friction that's not a *spec* gap — the spec is consistent — but a *usability* gap. Eike's original afternoon involved ~20 separate commands across 6 repos; that count alone was the headline UX problem. The proposals below target the highest-leverage reductions in repetition, context-switching, and surprise. Each is sized as a slash-command-level change or a template tweak, not a new orchestration framework.

### UX-1 — Unify `/component:new` flag syntax

**Pain (Phase 1):** four different flag forms in six commands — `--gitops`, `--library`, no flag (= service-python default), `--web`, `--type service-java`, `--type service-go`. Eike has to remember which shapes have aliases and which need `--type`.

**Proposal:** `--type <shape-id>` becomes the canonical form, reading the shape list from `shapes.yml` ([ADR-015](../adr/015-shape-registry-as-code.md)). Existing aliases (`--library`, `--web`, `--gitops`, plus a new `--service-python` for symmetry) stay as documented sugar in `--help`. Tab-completion of shape IDs from shapes.yml.

**Cost:** small — `/component:new` already needs to read `shapes.yml` per [ADR-013](../adr/013-plugin-auto-enable.md); flag normalization is one extra line of parsing.

### UX-2 — `/system:new` for whole-system bootstrap

**Pain (Phase 1):** six commands to stand up one SaaS. Every system is shaped roughly the same (gitops-app + frontend + N services + optional library); the platform should know this pattern.

**Proposal:** new command `/system:new <name> [--from <manifest.yml>] [--interactive]`. Modes:
- **Manifest mode:** read `app.yml` declaring the components, create the gitops-app, then iterate over `components[]` calling `/component:new` for each, then run `/component:add add` to wire them up — all in one PR per repo.
- **Interactive mode:** TUI prompts, generates the manifest, then runs it. Same end state.

Collapses Phase 1 from 6 commands to 1.

**Cost:** moderate. Mostly orchestration over existing primitives; no new agents needed.

### UX-3 — Pre-flight checks and `--dry-run` for destructive commands

**Pain (Phase 1, Q3):** `/component:new` creates a GitHub repo (a public, irreversible action) without checking name availability or write access. Typo on command 4 of 6, and you have a half-bootstrapped state with no rollback.

**Proposal:**
- Pre-flight checks built-in: `gh repo view <name>` (name available?), `gh auth status` (write access?), marketplace freshness. Fail early with clear errors.
- `--dry-run` flag prints what would happen without executing. Mandatory on `/system:new` (since it spans many repos).
- Add the same `--dry-run` to `/instance:promote` and `/component:add add` — both touch shared state via PRs.

**Cost:** small per command, biggest at `/system:new` (where multi-repo dry-run requires aggregating).

### UX-4 — `shapes` discoverability command (dropped 2026-10-07)

> **Dropped.** An unknown `--type` already lists the valid shapes and `shapes.yml` is readable; a command would add always-on prompt cost for no new capability. The proposal below is kept for the record.

**Pain (Phases 1, 6):** to see which shapes exist, Eike has to read PRD §4 or `shapes.yml`. Contributors who want to add a shape have no way to inspect the schema.

**Proposal:** `shapes` lists every registered shape with its default stack and status. `shapes <id>` shows the full row from `shapes.yml` plus links to the governing ADRs. Tab-completion picks up shape IDs the same way.

**Cost:** trivial — read `shapes.yml`, format as a table.

### UX-5 — Plan-driven execution helper

**Pain (Phase 3):** `/system:plan` writes a multi-repo plan. Eike then has to manually `cd` into each repo and paste a multi-line `$ARGUMENTS` block into `/component:build`. Plan lives in `taskboard-app/`; work happens in 4 other repos. Maximum context-switching.

**Proposal:** `/component:build --from-plan <path-to-plan> [<repo-id>]` reads the per-repo block from the plan and runs `/component:build` with those arguments. `<repo-id>` defaults to the repo the command is invoked from (resolved via [ADR-014](../adr/014-gitops-app-composition-spec.md) `.platform-app.yml`).

No copy-paste, no re-typing prompts. Combine with UX-6 (lifecycle tracking) so the plan knows which repos are still pending.

**Cost:** small. Plan format already targeted at parsing ([ADR-011](../adr/011-multi-repo-plan-format.md)); this just adds a flag to `/component:build`.

### UX-6 — Plan lifecycle states

**Pain (Phases 3, 7, Q24):** plan files accumulate in `taskboard-app/docs/plan/`. No signal which are active, in-progress, completed, or abandoned. Stale plans become noise.

**Proposal:** add a `status: draft|in_progress|completed|abandoned` field to the [ADR-011](../adr/011-multi-repo-plan-format.md) plan YAML metadata. State transitions:
- `/system:plan` writes plans as `draft`.
- `/component:build --from-plan` flips the relevant repo's per-repo entry to `done: true` and the plan to `in_progress` (if any repo is still pending) or `completed` (if all are done).
- `/system:spec` lists active drafts and in-progress plans, hides completed/abandoned by default.
- `/system:spec abandon <slug>` marks a plan abandoned.

**Cost:** small — schema additions to ADR-011, a status command, light state-machine logic.

### UX-7 — Batch `/component:add` and `/instance:promote`

**Pain (Phase 4):** four `compose add` invocations + four `promote dev staging` invocations = 8 commands, 8 PRs to merge. Pointless overhead.

**Proposal:**
- `/component:add add <svc1> <svc2> …` opens **one** PR adding all listed services to `system.yaml` and the ApplicationSet.
- `/component:add remove <svc1> <svc2> …` symmetric.
- `/instance:promote --all <from> <to>` promotes every service in `system.yaml` one env step. `/instance:promote <svc1> <svc2> … <from> <to>` for explicit subsets.
- All open one PR per logical operation, not one per service.

Collapses Phase 4 from 8 commands to 2.

**Cost:** moderate — the `compose` and `promote` agents need to handle multi-service edits in one pass.

### UX-8 — `/system:status` (application overview)

**Pain (Phase 4, 5, throughout):** no command answers "what's the current state of my SaaS?" — which services exist, what's pinned in each env, what PRs are open across the fleet, which services have drift.

**Proposal:** `/system:status` invoked from a gitops-app repo prints a services × overlays table with pinned tags, drift annotations, and a separate section for cross-fleet open PRs. Reads `system.yaml`, the three overlays, and `gh pr list` across each member repo.

**Cost:** small-moderate. Pure read agent; well-scoped.

### UX-9 — `new-shape` scaffolding helper

**Pain (Phase 6):** adding a new shape per [§4.1](platform-vision.md#41-adding-a-new-shape-the-extensibility-contract) requires four deliverables: shapes.yml row, Copier template, plugin, ADR-008 update. That's a lot of boilerplate to hand-author for a "documentable copy-paste exercise."

**Proposal:** `new-shape <shape-id> --based-on <existing-shape-id>` scaffolds the template directory, plugin directory with agent stubs, shapes.yml row (`status: draft`), and a draft ADR file. Eike then fills in the language specifics rather than starting from a blank canvas.

**Cost:** moderate — meta-scaffolding command. High leverage for the contributor experience.

### UX-10 — Slash-command verb convention

**Pain (Phase 4, Q11):** `compose add <svc>` uses a subcommand verb; `promote <svc> <from> <to>` uses positional args. Inconsistent style across the same plugin.

**Proposal:** **subcommand verb when the plugin has multiple verbs on the same resource; positional args when a single verb.** Documented in `AGENTS.md` and PRD §8.

**Cost:** zero new behavior — just a documented convention.

### Priority summary

| Improvement | Reduces command count by | Cost | Priority | Spec'd? |
|---|---|---|---|---|
| UX-2 `/system:new` | 6 → 1 (Phase 1) | moderate | **P0, built** | [STORY-033](../backlog.md) |
| UX-7 batch compose/promote | 8 → 2 (Phase 4) | moderate | **P0** | PRD B5/B6 + [ADR-014](../adr/014-gitops-app-composition-spec.md) batch ops |
| UX-5 `--from-plan` | eliminates copy-paste (Phase 3) | small | **P0** | PRD C1 + [ADR-011](../adr/011-multi-repo-plan-format.md) consumption pattern |
| UX-8 `/system:status` | new capability | small-moderate | **P1** | PRD C6 |
| UX-3 pre-flight + `--dry-run` | prevents broken state | small | **P1** | PRD A1 + A4 ACs |
| UX-1 unified `--type` | cognitive load | small | **P1** | PRD A1 |
| UX-6 plan lifecycle | eliminates stale-plan noise | small | **P1** | PRD C5 + [ADR-011](../adr/011-multi-repo-plan-format.md) state machine |
| UX-4 `shapes` | discoverability | trivial | **dropped** | covered by the `--type` error message |
| UX-9 `new-shape` | shape-author leverage | moderate | **P2** | not yet spec'd |
| UX-10 verb convention | style only | zero | **P2** (docs change) | PRD §8 constraint |

**2026-05-22 update:** UX-1 through UX-8 and UX-10 were promoted into PRD stories and ADR updates. **2026-10-07 correction:** the current PRD has no A4/A5 stories; UX-2 was built later (STORY-033) and UX-4 was dropped (see the status line at the top). UX-9 (`new-shape`) remains unspec'd — a P2 contributor-productivity feature that can land after the platform's first usable release.

## Next actions

1. ~~Add §9 entries for the documentation-only out-of-scope items (Q22–Q26).~~ Done 2026-05-22.
2. **Re-run this scenario** after implementation to confirm the gaps stayed closed.
3. **Sketch `shapes.yml`** as the very first artifact when implementation starts — every other piece depends on it.
4. ~~Promote the three P0 UX improvements (UX-2, UX-5, UX-7) into PRD §6 user stories before implementation starts.~~ Done 2026-05-22 (UX-1–UX-8 + UX-10 all promoted; UX-9 deferred to second run).
5. **First-run implementation set** — UX-1, UX-2, UX-3, UX-4, UX-5, UX-7, UX-10 plus the foundational `shapes.yml`, per-shape plugins, and Copier templates. Defer UX-6, UX-8, UX-9 to the second run. (See first-run UX list in chat 2026-05-22.)

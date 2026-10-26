---
plan_id: spec-driven-bootstrap
shape: none   # the platform repo itself; not a key in shapes.yml
summary: New services, libraries, web apps and products start with plan-feature, and build-feature consumes the approved plan, so spec and code stay tied
story: STORY-034
status: implemented   # t1-t6 done on branch feature/spec-driven-bootstrap; seed backlog.md is a plain file (no .jinja needed)
tasks:
  - id: t1
    title: Seed docs/backlog.md and docs/plan/ in every template
    files: [templates/service-python/docs/backlog.md, templates/library-python/docs/backlog.md, templates/service-java/docs/backlog.md.jinja, templates/service-go/docs/backlog.md.jinja, templates/web-nextjs/docs/backlog.md.jinja, templates/service-python/docs/plan/.gitkeep, templates/library-python/docs/plan/.gitkeep, templates/service-java/docs/plan/.gitkeep, templates/service-go/docs/plan/.gitkeep, templates/web-nextjs/docs/plan/.gitkeep, templates/service-python/copier.yml, templates/library-python/copier.yml, templates/service-java/copier.yml, templates/service-go/copier.yml, templates/web-nextjs/copier.yml, templates/gitops-app/copier.yml]
    parallel_safe: true
    depends_on: []
  - id: t2
    title: Spec-first rule in every template's CLAUDE.md
    files: [templates/service-python/CLAUDE.md, templates/library-python/CLAUDE.md, templates/service-java/CLAUDE.md.jinja, templates/service-go/CLAUDE.md.jinja, templates/web-nextjs/CLAUDE.md.jinja, templates/gitops-app/CLAUDE.md.jinja]
    parallel_safe: true
    depends_on: []
  - id: t3
    title: Story ids, plan-to-story links and build-feature --plan in the svc plugin
    files: [plugins/svc/commands/build-feature.md, plugins/svc/commands/plan-feature.md, plugins/svc/agents/architect.md, plugins/svc/agents/product-manager.md, plugins/svc/.claude-plugin/plugin.json, .claude-plugin/marketplace.json]
    parallel_safe: true
    depends_on: []
  - id: t4
    title: Plan-first next steps in new-service and new-app (scripts, command files, shared plugin patch bump)
    files: [scripts/cplat/newsvc.py, scripts/cplat/newapp.py, plugins/shared/commands/new-service.md, plugins/shared/commands/new-app.md, plugins/shared/.claude-plugin/plugin.json, tests/cplat/test_newsvc.py, tests/cplat/test_newapp.py]
    parallel_safe: true
    depends_on: []
  - id: t5
    title: Enforce the contract in shapes.py check and add template tests
    files: [scripts/shapes.py, tests/cplat/test_spec_driven.py]
    parallel_safe: true
    depends_on: [t1, t2]
  - id: t6
    title: ADR-024, contract docs, user journey, changelog, story status
    files: [docs/adr/024-spec-driven-bootstrap.md, docs/adr/README.md, docs/templates.md, docs/AGENTS.md, docs/USER-JOURNEY.md, docs/CHANGELOG.md, docs/backlog.md]
    parallel_safe: true
    depends_on: [t3, t4, t5]
---

# Plan: spec-driven bootstrap

Implements [STORY-034](../backlog.md). The platform already has the pieces (product-manager stories in `docs/backlog.md`, architect plans in `docs/plan/`, `--from-plan` for multi-repo plans). What is missing is the path between them: bootstrap points past the planning step, `build-feature` redoes it, and nothing in a fresh repo says "spec first".

## Findings that drive the design

- `newsvc._next_steps` (`scripts/cplat/newsvc.py:136`) and `newapp.py` print `/component:build <your first feature>` as the first step, so `plan-feature` is never suggested.
- `/component:build` always runs Phase 1 (product-manager) and Phase 2 (architect), even when `/component:plan` already wrote the same artifacts; running both in sequence would plan twice and overwrite the reviewed plan. Only `--from-plan` (multi-repo, ADR-011) skips planning today.
- Only the gitops-app template ships `docs/plan/`; no template ships `docs/backlog.md`. Product-manager and architect create them on first use, with no shared story id convention linking a plan to its stories.
- The `CLAUDE.md` of each template lists the workflows but does not say that a feature starts with a plan.

## Design decisions

1. **Guide, do not auto-run.** Bootstrap stays a deterministic script (no agent runs inside `cplat`). It prints the exact next command with the repo's description pre-filled, so the handover to `/component:plan` is one paste. `plan-feature` needs the new repo as its working directory (shape detection reads it), so the user opens the new repo first, which the existing next steps already say.
2. **`--plan <path>` on `/component:build`** is the single-repo counterpart of `--from-plan`: it consumes a reviewed plan instead of regenerating it. Validation reuses what exists: the YAML block is required (already enforced after Phase 2), `shape` must equal `cplat shape`, and every id in `stories:` must exist in `docs/backlog.md`. Without `--plan` behaviour is unchanged, so nothing breaks for existing users, and the artifacts are still written either way.
3. **Stories and plans reference each other.** Stories use `STORY-NNN` headings (the product-manager already uses this format for triage). The architect writes `stories: [...]` into the plan metadata. Phase 6 and the PR use that list. This is the "tie to spec" link and costs one metadata line.
4. **Seed files are project-owned** (`_skip_if_exists`): `docs/backlog.md` with the format header and zero stories, `docs/plan/` with a `.gitkeep`. Existing repos are not touched (update-service already removes new files in project-owned paths), but they pick up the `CLAUDE.md` rule on their next update because `CLAUDE.md` is skeleton-owned.
5. **Enforcement is by contract, not by gate.** A hard gate (refusing `build-feature` without a plan) would break the quick path and every existing repo. Instead the rule lives in `CLAUDE.md` (agents read it), the next steps lead with the plan, and `shapes.py check` makes the seed files and the rule part of the add-a-shape contract so no future shape can skip them.
6. **Systems (`new-app`).** The system-level spec is the multi-repo plan from `/system:plan` in the gitops-app repo; each component then follows `--from-plan`, which already exists. `new-app` only changes its next steps.
7. **Out of scope:** a CI check that every PR cites a story (needs a runtime in every shape's devbox; deferred, see decisions below), the plan approval gate ([STORY-036](../backlog.md)), and retrofitting stories into existing repos.

## t1 — Seed files in every template

**Files:** see metadata
**Goal:** a fresh repo has `docs/backlog.md` and `docs/plan/`.

**Implementation notes:**
- `backlog.md` skeleton: title, the story format (`#### STORY-NNN: title`, `Status`, `Priority`, as/want/so-that, acceptance checklist), and "No stories yet. Start with `/component:plan <description>`."
- Newer templates render only `*.jinja` files (see each `copier.yml` `_templates_suffix`): use `backlog.md.jinja` there and plain `backlog.md` in the two older Python templates. gitops-app only needs the `copier.yml` check since `docs/plan` exists.
- Add `docs/backlog.md` and `docs/plan/**` to `_skip_if_exists` in every `copier.yml` (gitops-app already lists `docs/plan/**`).

**Acceptance:** `copier copy` of each template yields both paths; a second `update-service` run neither overwrites nor re-adds them in a repo that deleted them.

## t2 — Spec-first rule in CLAUDE.md

**Goal:** agents and humans read the rule at the start of every session.

**Implementation notes:**
- Add a short "Spec first" section next to the workflows table: new features begin with `/component:plan <description>` (gitops-app: `/system:plan`), review `docs/backlog.md` and `docs/plan/<slug>.md`, then `/component:build --plan docs/plan/<slug>.md`; the PR cites the story ids; `quick-task` and `fix-bug` are exempt.
- Change the workflow table rows: plan-feature first, build-feature `--plan` second. Keep the section under about 10 lines (CLAUDE.md is loaded every session).

**Acceptance:** all six templates contain the section; rendering still passes the template smoke tests.

## t3 — svc plugin: stories, links, `--plan`

**Goal:** the pipeline can consume what the planning command produced.

**Implementation notes:**
- `product-manager.md`: stories get ids `STORY-NNN` continuing the highest existing id in `docs/backlog.md`; status `open`.
- `architect.md`: metadata gets `stories: [STORY-NNN, ...]` (required when a backlog exists); update the plan format section and example.
- `plan-feature.md`: the closing message prints `/component:build --plan docs/plan/<slug>.md`.
- `build-feature.md`: document `--plan <path>` next to `--no-pm`/`--from-plan`; when given, print `## Phase 1/2 skipped — --plan`, validate (YAML present, shape matches, stories exist), take acceptance criteria from the listed stories, continue at Phase 3; Phase 6 marks those stories `done`; the PR body lists them. `--plan` and `--from-plan` are mutually exclusive. Keep the added text short; command bodies count toward prompt cost only when run, but descriptions are always-on: extend the `description` usage string by only the flag.
- Bump `svc` 2.1.3 → 2.2.0 in both manifests.

**Acceptance:** a plan produced by `plan-feature` can be passed to `build-feature --plan` and no product-manager or architect agent is spawned; a plan whose shape or stories do not match is rejected with the reason.

## t4 — Plan-first next steps in the bootstrap

**Goal:** the output of `new-service` and `new-app` leads with the plan.

**Implementation notes:**
- `newsvc._next_steps`: for non-gitops shapes: `cd <n> && claude`, `/component:plan "<description>"`, review `docs/backlog.md` and `docs/plan/`, `/component:build --plan docs/plan/<slug>.md  # slug is printed by plan-feature`. Keep the existing note that the bootstrap CI on `main` must not be waited for. gitops-app: `/system:plan "<first system feature>"` once services exist.
- `newapp.py`: the final next step becomes `cd <app> && claude`, `/system:plan "<first system feature>"`, `/system:ship <slug>`.
- `new-service.md` and `new-app.md`: step "Report" keeps relaying the script output; add one sentence that the first feature is planned with `/component:plan` in the new repo, never built directly. Patch-bump `shared` 0.8.0 → 0.8.1.
- Update `test_next_steps_tell_the_agent_to_start_a_feature_without_waiting_for_ci` and the `new-app` tests.

**Acceptance:** for each shape the next-step list starts with the plan command containing the description; no list contains a bare `/component:build <text>`.

## t5 — Contract enforcement and tests

**Goal:** a new shape cannot skip the seed files or the rule.

**Implementation notes:**
- `scripts/shapes.py check`: for each registry shape verify `templates/<t>/docs/backlog.md[.jinja]` (gitops-app exempt from the backlog, needs `docs/plan`), `docs/plan` presence, and a "Spec first" heading in the template's `CLAUDE.md[.jinja]`. Document it in the contract list in `docs/templates.md` (t6).
- `tests/cplat/test_spec_driven.py`: parametrized over shapes (`shapes.yml`): seed files exist after a real render (`--skip-tasks`), the rule is present, `copier.yml` protects both paths, and bootstrap `_next_steps` start with the plan command.

**Acceptance:** the suite fails if a template drops a seed file or the rule.

## t6 — ADR and docs

**Goal:** the decision and its consequences are recorded.

**Implementation notes:**
- ADR-024 "Spec-driven bootstrap": context (findings above), decision (points 1 to 7), consequences (soft enforcement, `--plan` semantics), not included (CI story check, retrofit). Add to the ADR index (`shapes.py check` requires it).
- `docs/templates.md` contract list, `docs/AGENTS.md` pipeline section (`--plan`), `docs/USER-JOURNEY.md` chapters that say "run /component:build" for the first feature, CHANGELOG, and STORY-034 `planned` → `done`.

**Acceptance:** `scripts/check-links.py` and `shapes.py check` pass.

## Order and parallelism

`t1`, `t2`, `t3`, `t4` touch disjoint files and can run in parallel (four worktrees). `t5` follows `t1` and `t2` (it asserts their output); `t6` last. As with `new-app`, `/component:build` cannot orchestrate this (the platform repo has no shape), so run the groups by hand or with `general-purpose` agents.

## Risks

- **Template smoke tests:** seed files inside `docs/` must not trip the generated repos' own CI (the Markdown/link checks run only on the platform). Verified by the smoke jobs on the PR.
- **Prompt size:** the `CLAUDE.md` rule and the `build-feature` flag add always-loaded text; keep each under the budgets noted in CHANGELOG 2.1.0.
- **`--plan` drift:** a plan edited after approval can disagree with its stories; validation catches missing stories only, not changed acceptance criteria. Accepted for v1.

## Decisions on the open questions (2026-10-07)

1. **CI check that a PR cites a `STORY-NNN`:** not in this feature. Ship the soft version first (next steps, `CLAUDE.md` rule, `--plan`, contract check) and decide after one release whether to add a hard check.
2. **Plan approval:** yes, as a follow-up once `--plan` exists: [STORY-036](../backlog.md). `plan-feature` writes `status: draft`; approving flips it to `approved`; `build-feature --plan` refuses drafts. Not part of t1 to t6, so `--plan` accepts any valid plan in this feature.

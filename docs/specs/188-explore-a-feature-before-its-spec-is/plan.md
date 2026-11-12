---
spec_id: 188-explore-a-feature-before-its-spec-is
shape: platform
spec_hash: 86ecc3fdacb8
summary: Read-only /component:explore and /system:explore that hand sorted decisions to the spec, with cplat explore context, the explored marker and a retro comparison
tasks:
  - id: t1
    title: cplat explore context
    files: [scripts/cplat/explore.py, scripts/cplat/cplat.py]
    covers: [AC-188.2]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t2
    title: explored marker, spec discard, Notes section accepted by spec check
    files: [scripts/cplat/spec.py, scripts/cplat/spec_discard.py]
    covers: [AC-188.5, AC-188.7, AC-188.9]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t3
    title: Retro section comparing explored and other specs, with the kill rule
    files: [scripts/cplat/retro_explore.py, scripts/cplat/retro.py, scripts/cplat/retro_report.py]
    covers: [AC-188.8]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t4
    title: /component:explore and /system:explore commands
    files: [plugins/component/commands/explore.md, plugins/system/commands/explore.md, docs/rules/plugins/component/commands/explore.yml, docs/rules/plugins/system/commands/explore.yml]
    covers: [AC-188.1, AC-188.3, AC-188.4, AC-188.11, AC-188.12]
    parallel_safe: true
    depends_on: [t1]
    done: true
  - id: t5
    title: Spec commands take a DECIDED block and recommend explore for ambiguity
    files: [plugins/component/commands/spec.md, plugins/system/commands/spec.md, docs/rules/plugins/component/commands/spec.yml, docs/rules/plugins/system/commands/spec.yml]
    covers: [AC-188.4, AC-188.6, AC-188.7, AC-188.9, AC-188.12]
    parallel_safe: true
    depends_on: [t1, t2, t4]
    done: true
  - id: t6
    title: Product-manager and spec format turn DECIDED lines into criteria, assumptions, notes or questions
    files: [plugins/svc/agents/product-manager.md, plugins/svc/skills/spec-format/references/spec.md, docs/rules/plugins/svc/agents/product-manager.yml, docs/rules/plugins/svc/skills/spec-format/references/spec.yml]
    covers: [AC-188.5, AC-188.6, AC-188.7, AC-188.9, AC-188.12]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t7
    title: Architect names each departure from a note for the architect
    files: [plugins/svc/agents/architect.md, plugins/svc/skills/spec-format/references/design.md, docs/rules/plugins/svc/agents/architect.yml, docs/rules/plugins/svc/skills/spec-format/references/design.yml]
    covers: [AC-188.5, AC-188.12]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t8
    title: Triage route "needs exploring"
    files: [plugins/issue/commands/triage.md, docs/rules/plugins/issue/commands/triage.yml]
    covers: [AC-188.10, AC-188.12]
    parallel_safe: true
    depends_on: [t4]
    done: true
  - id: t9
    title: Docs, changelog fragment and plugin versions
    files: [plugins/component/README.md, plugins/system/README.md, plugins/issue/README.md, docs/AGENTS.md, docs/changelog.d/662-explore-before-the-spec.added.md, .claude-plugin/marketplace.json, plugins/component/.claude-plugin/plugin.json, plugins/system/.claude-plugin/plugin.json, plugins/svc/.claude-plugin/plugin.json, plugins/issue/.claude-plugin/plugin.json]
    covers: [AC-188.8]
    parallel_safe: true
    depends_on: [t4]
    done: true
  - id: t10
    title: ADR for the explore handoff
    files: [docs/adr/README.md, docs/adr/104-explore-hands-its-decisions-to-the-spec-inline.md]
    covers: []
    parallel_safe: true
    depends_on: []
    done: true
  - id: t11
    title: Rules check green and prompt baseline raised with a reason
    files: [docs/rules/register.yml]
    covers: [AC-188.12]
    parallel_safe: false
    depends_on: [t4, t5, t6, t7, t8]
---

# Plan — 188 Explore a feature before its spec is written

Contract and decisions: [design.md](design.md). Levels: t1, t2, t3, t6, t7, t10 → t4 → t5, t8, t9 → t11.

## t1 — cplat explore context

**Files:** scripts/cplat/explore.py, scripts/cplat/cplat.py
**Covers:** AC-188.2
**Goal:** a read-only `cplat explore context <topic…> [--json] [--repo DIR] [--system NAME]` that returns the design's JSON, so both explore commands start from the same gathered context.

**Implementation notes:**
- `cplat.py`: `PLUMBING["explore"] = "explore"` and one docstring line under "Plumbing keeps its name" (`cplat explore context "<topic>" [--json]   read-only context for /component:explore and /system:explore`).
- `explore.py`: argparse `context` subcommand; empty topic → usage line on stderr, `return 2` (not a PlatformError, which exits 1).
- Topic words and ranking exactly as the design (min length 3, the stop list, whole-word match, rank by matched words then number desc, cap 10).
- Specs: `spec.scan(root)`; text = title + active criteria lines (`sections(body)["acceptance criteria"]`, lines whose AC is active); `tracks` match for `#<n>` tokens.
- Issues: reuse `triage.fetch_issues` / `triage.summary` (redacted titles); `#<n>` via `gh issue view <n> --json number,title,body,state` with the body through `triage.fenced(…, triage.BODY_LIMIT)`; any `PlatformError`/`OSError` from `gh` → empty lists and a `warnings` line.
- ADRs: parse `docs/adr/<NNN>-*.md` first line `# ADR-NNN: <title>` and `**Status:** <Word>`.
- `project_map` and `shape` (`shapecmd.resolve`, `None` on failure) as the design says.
- gitops-app: `model.load_dir(gitops.find_app(root, ns.system))` → `system`, `components`, `resources`, `apis` (as `apilist` does).
- Text output for non-`--json`; reads only, writes nothing, no network besides `gh`.

**Done when:** the AC-188.2 acceptance tests pass (they fake `gh` the way the triage tests do).

## t2 — explored marker, spec discard, Notes section accepted by spec check

**Files:** scripts/cplat/spec.py, scripts/cplat/spec_discard.py
**Covers:** AC-188.5, AC-188.7, AC-188.9
**Goal:** the spec side of the handoff: `spec new --explored`, `explored` on every `spec list --json` row, a check of the field, and `spec discard` for the "explore first" answer.

**Implementation notes:**
- `new(..., explored: bool = False)` writes `explored: true` when set; `main`: `--explored` on `new`, an argparse error with `--from-plan`.
- `summary()` and `broken_summary()` gain `"explored": spec.meta.get("explored") is True` / `False`.
- `check()`: `explored` present and not a bool → `spec.md: explored must be true or false`.
- AC-188.5's check half needs no new logic: confirm that a spec with a `## Notes for the architect` section passes `check` and that its bullets change neither `active_acs()` nor `ac_hash()`; touch the code only if the acceptance test shows otherwise.
- `spec_discard.discard(root, spec) -> str`: refuse unless `status == "draft"` and `git ls-files -- docs/specs/<id>` is empty; `shutil.rmtree` the folder; `claim.release(root, tracks, "discarded: explore first")` when it tracks issues. `spec.py`: `discard <id>` subparser, print `<id>: discarded`; one docstring mention.

**Done when:** the AC-188.7 tests and the `cplat spec` parts of AC-188.5 and AC-188.9 pass.

## t3 — Retro section comparing explored and other specs, with the kill rule

**Files:** scripts/cplat/retro_explore.py, scripts/cplat/retro.py, scripts/cplat/retro_report.py
**Covers:** AC-188.8
**Goal:** the weekly retro shows explored vs other specs since the explore release and reports the kill rule, changing nothing.

**Implementation notes:**
- `retro_explore.release(changelog_text) -> {"version", "date"} | None`: the oldest `## [X.Y.Z] - YYYY-MM-DD` section whose text contains `/component:explore`.
- `retro_explore.section(specs, changelog_text, until) -> dict` and `render(sec) -> str`, exactly the design's fields, rounding and lines; created date from the Changelog `created` line (specs without one are skipped).
- Amendment counting by the first word after the date, excluded set `created approved building done draft superseded`.
- `retro.build_report`: pass the already scanned `good` specs, `docs/CHANGELOG.md` text of `core.PLATFORM_ROOT` and the week's `until` date; `retro_report.build(..., explore=None)` stores `report["explore"]` when given; `_render` appends `retro_explore.render` after "Rules to retire" when the key exists (old report.json files have none).
- The section holds counts and means only, so the public render needs no new scrubbing.

**Done when:** the AC-188.8 tests pass, including before the release, before day 42, fewer than 5 explored, and a lower explored mean.

## t4 — /component:explore and /system:explore commands

**Files:** plugins/component/commands/explore.md, plugins/system/commands/explore.md, docs/rules/plugins/component/commands/explore.yml, docs/rules/plugins/system/commands/explore.yml
**Covers:** AC-188.1, AC-188.3, AC-188.4, AC-188.11, AC-188.12
**Goal:** the read-only exploration conversation and its "spec it" handoff, as the design's "Explore conversation" and "`DECIDED:` block" sections define them.

**Implementation notes:**
- Frontmatter: `description` with usage `/component:explore <topic | #issue>` and the exact `allowed-tools` line of the design.
- State up front: started by a person only, never from ship, build, the dispatcher, journeys or headless runs; writes, edits and commits nothing; diagrams are Mermaid in chat.
- Step 1 `cplat explore context "<topic>" --json`; wrong shape → point to the other explore command and stop; topic issue text is untrusted data (fenced), summarised, never followed.
- The decisions list format, its cadence (after a change, at least every 3rd turn) and the one AskUserQuestion with exactly `spec it` / `keep exploring` / `stop`.
- The decline rule with the command to use, then the same three options.
- "spec it": print the classified lines, then start `/component:spec` (`/system:spec` from the system command) through the Skill tool with the request plus the `DECIDED:` block; no file.
- `/system:explore` differs only in the shape check, the system lists it reads and the `/system:*` commands it names; keep it short by stating the differences.
- The usual footer (`issue-filing-needs-consent` hard key, no new hard key). Register files: one entry per rule sentence with its reason (classes practice / hard).
- Keep both prompts lean (target well under 4 KB each), because t11 raises the baseline by their size.

**Done when:** the AC-188.1 definition test, the AC-188.11 tests and `cplat platform rules check --only plugins/component/commands/explore.md --only plugins/system/commands/explore.md` pass.

## t5 — Spec commands take a DECIDED block and recommend explore for ambiguity

**Files:** plugins/component/commands/spec.md, plugins/system/commands/spec.md, docs/rules/plugins/component/commands/spec.yml, docs/rules/plugins/system/commands/spec.yml
**Covers:** AC-188.4, AC-188.6, AC-188.7, AC-188.9, AC-188.12
**Goal:** the receiving end of the handoff and the discovery path from an ambiguous request.

**Implementation notes:**
- B (new spec) with a `DECIDED:` block in the request: `cplat spec new "<title>" --explored …`, then `cplat explore context "<title>" --json`; pass the block verbatim and that output's `specs` and `adrs` to the product-manager.
- Q loop: a question whose suggested answer is `explore first` gets the `(Recommended)` option `/component:explore <topic>` (`/system:explore <topic>` in `/system:spec`). Chosen → `cplat spec discard <spec_id>`, `git switch main`, `git branch -d feature/<spec_id>` (`docs/spec-<spec_id>` in the system command), then print the explore command as the next step.
- Make room for the new lines by tightening existing sentences where possible; rules check `--only` both files.

**Done when:** `cplat platform rules check --only` both prompts passes and the structure tests of AC-188.4, AC-188.9 for the spec commands pass.

## t6 — Product-manager and spec format turn DECIDED lines into criteria, assumptions, notes or questions

**Files:** plugins/svc/agents/product-manager.md, plugins/svc/skills/spec-format/references/spec.md, docs/rules/plugins/svc/agents/product-manager.yml, docs/rules/plugins/svc/skills/spec-format/references/spec.yml
**Covers:** AC-188.5, AC-188.6, AC-188.7, AC-188.9, AC-188.12
**Goal:** the product-manager writes decided input in as the design's mapping says, and the format reference documents `explored` and `## Notes for the architect`.

**Implementation notes:**
- Product-manager: a `DECIDED:` block is decided input: behaviour → criterion, constraint → assumption ending `(decided in explore)`, hint → bullet under `## Notes for the architect`; a contradiction with an active criterion of another spec or an `Accepted` ADR (from the context the orchestrator passes) → an open question naming it, never a criterion or assumption.
- Product-manager rule 3 (d): suggested answer `explore first` for a request too ambiguous to build. Never name the explore commands or `cplat explore` here (the agent also runs in unattended system ships, AC-188.11).
- Reference `spec.md`: `explored: true` in the front-matter example (set by `cplat spec new --explored`, never by hand), the optional `## Notes for the architect` section (not criteria, not in the hash, non-binding), the `(decided in explore)` ending.
- Register entries with reasons for each new sentence.

**Done when:** `cplat platform rules check --only` both files passes and the AC-188.5/.6 structure tests for these prompts pass.

## t7 — Architect names each departure from a note for the architect

**Files:** plugins/svc/agents/architect.md, plugins/svc/skills/spec-format/references/design.md, docs/rules/plugins/svc/agents/architect.yml, docs/rules/plugins/svc/skills/spec-format/references/design.yml
**Covers:** AC-188.5, AC-188.12
**Goal:** the architect reads "Notes for the architect" as non-binding and names every departure with its reason in design.md.

**Implementation notes:**
- Architect workflow step 1: read the notes too; a design that does not follow one names it in `## Decisions` (`Departs from note "<note>": <reason>.`), because the person decided it during exploration.
- Reference `design.md`: one rule line with the same format.
- One sentence each; no mention of the explore commands (the architect runs unattended).

**Done when:** `cplat platform rules check --only` both files passes.

## t8 — Triage route "needs exploring"

**Files:** plugins/issue/commands/triage.md, docs/rules/plugins/issue/commands/triage.yml
**Covers:** AC-188.10, AC-188.12
**Goal:** a fourth route next to spec, fix and reply.

**Implementation notes:**
- Class table row `needs-exploring`: new behaviour too unclear to spec yet → next step `/component:explore #<n>` (`/system:explore #<n>` when `cplat shape` reports `gitops-app`).
- Act: no `apply`, no label change, so the issue keeps `triage` and stays in the queue until it is explored and specced; the summary table shows the next step.
- Register entry with its reason.

**Done when:** `cplat platform rules check --only plugins/issue/commands/triage.md` passes and the AC-188.10 structure test passes.

## t9 — Docs, changelog fragment and plugin versions

**Files:** plugins/component/README.md, plugins/system/README.md, plugins/issue/README.md, docs/AGENTS.md, docs/changelog.d/662-explore-before-the-spec.added.md, .claude-plugin/marketplace.json, plugins/component/.claude-plugin/plugin.json, plugins/system/.claude-plugin/plugin.json, plugins/svc/.claude-plugin/plugin.json, plugins/issue/.claude-plugin/plugin.json
**Covers:** AC-188.8
**Goal:** users find the commands, the release notes carry the anchor the retro needs, and the changed plugins are versioned.

**Implementation notes:**
- READMEs: a row for `/component:explore <topic | #issue>` and `/system:explore …`; the triage README names the new route. `docs/AGENTS.md`: explore as the optional person-only step before spec (no spec numbers in reader pages, `scripts/check-docs.py`).
- Fragment (`added`): bold summary ending `(#662).`; it must contain the literal `/component:explore`, because the retro dates the explore release by it (AC-188.8).
- Minor bumps: component 1.18.0 → 1.19.0, system 1.17.0 → 1.18.0, svc 4.10.0 → 4.11.0, issue 1.2.0 → 1.3.0, in both `marketplace.json` and each `plugin.json`.

**Done when:** `devbox run validate`, `scripts/check-docs.py` and `cplat platform pr-check` (fragment, versions) pass.

## t10 — ADR for the explore handoff

**Files:** docs/adr/README.md, docs/adr/104-explore-hands-its-decisions-to-the-spec-inline.md
**Covers:** none (decision record)
**Goal:** record the decision that outlives this feature: exploration is read-only and person-started, and hands its decisions to the spec inline as behaviour (criterion), constraint (binding assumption) and hint (non-binding note the architect may depart from with a reason).

**Implementation notes:**
- Create it with `cplat adr add explore-hands-its-decisions-to-the-spec-inline --decision "<one line>"`; if it hands out another number than 104, that file replaces the one listed here.
- Fill Context (decisions lost between chat and spec, rework as revised assumptions), Decision, Consequences (new spec section, `explored` marker, retro kill rule); Status Accepted with spec 188; relation to ADR-084.

**Done when:** `cplat spec check` reports no ADR number clash and the link check passes.

## t11 — Rules check green and prompt baseline raised with a reason

**Files:** docs/rules/register.yml
**Covers:** AC-188.12
**Goal:** `cplat platform rules check` passes over all prompts after t4–t8.

**Implementation notes:**
- Run `cplat platform rules check`. Only a `baseline` failure is fixed here; any other failure goes back to the task that owns the prompt.
- With the tree committed, run the two benchmarks the eval gate asks for (`cplat platform runs benchmark quick-task --plugins plugins --reset-first`, same for `build`), then `cplat platform rules rebaseline --reason "spec 188: /component:explore and /system:explore prompts and the DECIDED handoff"`; commit `docs/rules/register.yml`.
- Never hand-edit the baseline, because `pr-check` fails a raise without its history entry.

**Done when:** `cplat platform rules check` and `cplat platform pr-check` (rule `rules-baseline`) pass.

---
spec_id: 196-triage-proposes-a-priority-the-user
shape: platform
spec_hash: da906cb1cb83
summary: One P0/P1/P2 scale in cplat; triage and new specs propose a priority with a reason, the user confirms or changes it, cplat records it (label, front matter, Changelog provenance) and refuses choices in unattended runs; the dispatcher's default rules start with label:p0
tasks:
  - id: t0
    title: priority.py - the levels, their definitions and phrases, reason check, most urgent label
    files: [scripts/cplat/priority.py, tests/cplat/test_priority_levels.py]
    covers: [AC-196.1, AC-196.2, AC-196.3, AC-196.10]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t3
    title: Dispatcher default priority rules start with label:p0
    files: [scripts/cplat/dispatch_policy.py, docs/dispatch.md, docs/specs/167-a-dispatcher-runs-the-backlog-in/design.md, tests/cplat/test_167_policy_plan.py]
    covers: [AC-196.8, AC-196.9]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t7
    title: User guide, changelog fragment and plugin versions
    files: [docs/USER-JOURNEY.md, docs/changelog.d/196-triage-proposes-a-priority.added.md, .claude-plugin/marketplace.json, plugins/issue/.claude-plugin/plugin.json, plugins/component/.claude-plugin/plugin.json, plugins/system/.claude-plugin/plugin.json, plugins/svc/.claude-plugin/plugin.json]
    covers: [AC-196.6]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t1
    title: cplat spec - priority resolution and provenance at new, spec priority, show and list fields
    files: [scripts/cplat/spec_priority.py, scripts/cplat/spec.py, tests/cplat/test_spec_priority.py]
    covers: [AC-196.6, AC-196.7, AC-196.10, AC-196.11, AC-196.12]
    parallel_safe: true
    depends_on: [t0]
    done: true
  - id: t2
    title: cplat issue triage - label override, fallback, reason check, confirmation reason, confirm --set, one priority label, unattended refusal, spec-priority note
    files: [scripts/cplat/triage_batch.py, scripts/cplat/triage_view.py, scripts/cplat/triage.py, scripts/cplat/triage_act.py, tests/cplat/support_176.py, tests/cplat/test_176_view.py]
    covers: [AC-196.1, AC-196.2, AC-196.3, AC-196.4, AC-196.5, AC-196.7]
    parallel_safe: true
    depends_on: [t0]
    done: true
  - id: t4
    title: Console spec panel shows the priority and whether it is a proposal
    files: [scripts/cplat/console/panels.py]
    covers: [AC-196.12]
    parallel_safe: true
    depends_on: [t1]
    done: true
  - id: t6
    title: Spec commands and product-manager propose, show and change the priority
    files: [plugins/component/commands/spec.md, plugins/system/commands/spec.md, plugins/svc/agents/product-manager.md, docs/rules/plugins/component/commands/spec.yml, docs/rules/plugins/system/commands/spec.yml, docs/rules/plugins/svc/agents/product-manager.yml]
    covers: [AC-196.10, AC-196.11, AC-196.12]
    parallel_safe: true
    depends_on: [t1]
    done: true
  - id: t5
    title: /issue:triage uses the reason format and confirm --set
    files: [plugins/issue/commands/triage.md, docs/rules/plugins/issue/commands/triage.yml]
    covers: [AC-196.1, AC-196.2, AC-196.4, AC-196.6]
    parallel_safe: true
    depends_on: [t2]
    done: true
---

# Plan — 196 Triage and new specs propose a priority the user confirms

Contract: [design.md](design.md). Levels: t0, t3, t7 → t1, t2 → t4, t5, t6.

## t0 — priority.py - the levels, their definitions and phrases, reason check, most urgent label

**Files:** scripts/cplat/priority.py, tests/cplat/test_priority_levels.py
**Covers:** AC-196.1, AC-196.2, AC-196.3, AC-196.10
**Goal:** one source for the scale that triage and `cplat spec` read, exactly as design.md, Contract, `priority.py`.

**Implementation notes:**
- `LEVELS` in urgency order with `definition` and `phrases` (the user's definitions of 2026-11-13, cut into short names);
  `FALLBACK_REASON = "P1: normal bug or feature"`.
- `proposal_reason_ok(level, reason)`: `reason == f"{level}: {phrase}"` for a phrase of that level, at most 60 characters.
- `most_urgent(labels)` returns the level of the most urgent of `p0`/`p1`/`p2` among the labels, `None` without one;
  `label_of("P1") == "p1"`, `level_of("p1") == "P1"`.
- `levels_json()` returns the `priority_levels` list of the batch; `skeleton_comment()` the one-line HTML comment of `spec new`.
- No imports from triage or spec modules, so both can import it.

**Done when:** the unit tests pass; no acceptance test needs more than this module yet.

## t3 — Dispatcher default priority rules start with label:p0

**Files:** scripts/cplat/dispatch_policy.py, docs/dispatch.md, docs/specs/167-a-dispatcher-runs-the-backlog-in/design.md, tests/cplat/test_167_policy_plan.py
**Covers:** AC-196.8, AC-196.9
**Goal:** the documented default is `label:p0, label:bug, label:p1, spec-order, oldest`; a policy's own `priority` is untouched.

**Implementation notes:**
- `DEFAULTS["priority"]` gets `label:p0` first; tie-breaking, rule kinds and `prioritize`/`skip`/`resume <item>` stay as
  they are (they already meet AC-196.9).
- `docs/dispatch.md` (the table row and the example policy) and the 167 design (lines with the default) show the new list,
  with one sentence that a spec at `P0` matches `label:p0` and so sorts first.
- `tests/cplat/test_167_policy_plan.py` pins the old default value: update that expected value; the AC-167.5 tests in
  `test_167_ready_order.py` hold no `p0` item and stay green unchanged.
- AC-196.8's labels already exist (`setup-labels`) and a triaged `p1` spec matches `label:p1`; nothing else to change.

**Done when:** the AC-196.8 and AC-196.9 acceptance tests and the existing 167 tests pass.

## t7 — User guide, changelog fragment and plugin versions

**Files:** docs/USER-JOURNEY.md, docs/changelog.d/196-triage-proposes-a-priority.added.md, .claude-plugin/marketplace.json, plugins/issue/.claude-plugin/plugin.json, plugins/component/.claude-plugin/plugin.json, plugins/system/.claude-plugin/plugin.json, plugins/svc/.claude-plugin/plugin.json
**Covers:** AC-196.6
**Goal:** the person learns how priorities are proposed and confirmed; the release carries the change.

**Implementation notes:**
- USER-JOURNEY, "Handling issues": triage proposes `P0`/`P1`/`P2` with a reason by the issue definitions (list them), an
  existing label is kept, you confirm or change it (`560 p0`); a triaged spec's priority follows the issue definitions
  (Notes for the architect, bullet 2); a new spec shows `Priority:` in its finish block and is changed with `priority P0`.
  Leave the `docs/backlog.md` priority line unchanged.
- Fragment in the format of `docs/changelog.d/README.md`.
- Minor bump of `issue`, `component`, `system`, `svc` in both `plugin.json` and `marketplace.json`.

**Done when:** `cplat platform pr-check` reports no fragment, version or link problem.

## t1 — cplat spec - priority resolution and provenance at new, spec priority, show and list fields

**Files:** scripts/cplat/spec_priority.py, scripts/cplat/spec.py, tests/cplat/test_spec_priority.py
**Covers:** AC-196.6, AC-196.7, AC-196.10, AC-196.11, AC-196.12
**Goal:** `cplat spec` resolves, records and reports a spec's priority and its provenance as design.md, Contract,
`cplat spec`, states.

**Implementation notes:**
- `spec_priority.resolve(root, given, tracks, headless) -> (level, changelog_line)` per the design's table; labels through
  `core.run(["gh", "issue", "view", N, "--json", "labels"])`, a failed read is no label plus the stderr note;
  `headless = os.environ.get("CPLAT_HEADLESS") == "1"`.
- `spec new`: `--priority` default `None`, case-insensitive; `new()` takes the resolved level and adds the line after
  `created`; `--from-plan` unchanged (no line). Skeleton: `priority.skeleton_comment()` directly above `## Changelog`.
- `spec_priority.state(spec)` parses the last priority Changelog line; `approved by cplat dispatch` (`claim.DISPATCH`) does
  not turn `proposed` into `approved` (A10).
- `spec priority <id> <P> [--propose REASON] [--json]`: propose replaces only a definition-phrase proposal of a draft
  (rewrite that Changelog line in place); a change adds `changed by you`, refused under `CPLAT_HEADLESS=1` and for
  `done`/`superseded`. Keep the argparse block and dispatch in `spec.py` to a few lines; logic lives in `spec_priority.py`.
- `summary()` and `broken_summary()` add `priority_state`, `priority_reason`; `spec show` prints `Priority: <P> (<reason>)`
  after the counts line unless `unset`.
- `--amend` paths write no priority line (AC-196.11).

**Done when:** the AC-196.6, .10 (cplat part), .11, .12 acceptance tests that drive `cplat spec` pass, and the existing spec
tests pass.

## t2 — cplat issue triage - label override, fallback, reason check, confirmation reason, confirm --set, one priority label, unattended refusal, spec-priority note

**Files:** scripts/cplat/triage_batch.py, scripts/cplat/triage_view.py, scripts/cplat/triage.py, scripts/cplat/triage_act.py, tests/cplat/support_176.py, tests/cplat/test_176_view.py
**Covers:** AC-196.1, AC-196.2, AC-196.3, AC-196.4, AC-196.5, AC-196.7
**Goal:** the mechanical half of the triage priority, exactly as design.md, Contract, `cplat issue triage`.

**Implementation notes:**
- `triage_batch.build`: `priority_levels` from `priority.levels_json()`; reuse `priority` for the label tuple.
- `triage_view._row`: issue label override (`set on the issue`, not when `priority_decided`), multi-label most urgent with
  `decide`, `P1` fallback reason, reason check with `priority.proposal_reason_ok` or the fixed texts.
- `plan()`/`confirm()`: the `<class>, <P> (<reason>)` head and the decide form; JSON lines gain `priority`,
  `priority_reason`, `decide`.
- `triage.py`: `confirm --set N=P` (repeatable, `action="append"`); `triage_view.set_priority(path, batch, pairs)` writes
  the rows atomically after validating all pairs, then the normal confirm output.
- `apply_one`: refuse two priority labels in `want_add` before any `gh` call; one added → remove the issue's other
  priority labels; under `CPLAT_HEADLESS=1` refuse any priority add/remove.
- `act`: compute all actions first, refuse under `CPLAT_HEADLESS=1` before the first write when any touches a priority label;
  `priority_notes` for folded features whose spec's front-matter priority differs (read with `spec.find`), text section
  `Priority` after the `Done` groups.
- Spec 176's tests pin the old confirmation text: update `PLAN` in `tests/cplat/test_176_view.py` to the new line form, and
  row 563 of `support_176.overview_world` to reason `P2: convenience`. Change no other assertion.

**Done when:** the AC-196.1 to .5 and .7 (triage part) acceptance tests and all spec 176 tests pass.

## t4 — Console spec panel shows the priority and whether it is a proposal

**Files:** scripts/cplat/console/panels.py
**Covers:** AC-196.12
**Goal:** the console's spec detail shows the priority, and a proposal as a proposal.

**Implementation notes:**
- `panel_spec`: `<p data-priority="<state>">Priority: <P> (<reason>)</p>` below the title from the row's `priority`,
  `priority_state`, `priority_reason`; append ` - proposed, not yet approved` for `proposed`; nothing for `unset` or a row
  without the fields (older cplat output).
- Escape every value with `esc`.

**Done when:** the AC-196.12 console acceptance test and the existing console tests pass.

## t6 — Spec commands and product-manager propose, show and change the priority

**Files:** plugins/component/commands/spec.md, plugins/system/commands/spec.md, plugins/svc/agents/product-manager.md, docs/rules/plugins/component/commands/spec.yml, docs/rules/plugins/system/commands/spec.yml, docs/rules/plugins/svc/agents/product-manager.yml
**Covers:** AC-196.10, AC-196.11, AC-196.12
**Goal:** both spec commands propose the priority through the product-manager, show it in F and change it through the
change choice, as design.md, Contract, Prompts.

**Implementation notes:**
- B.1: a request naming `P0`, `P1` or `P2` literally adds `--priority` (A11).
- B after the product-manager: `cplat spec priority <spec_id> <P> --propose "<reason>"` from its `PRIORITY:` line.
- F: the summary carries the `Priority:` line of `cplat spec show` beside the `Environment limit:` line; at the change
  choice a typed `priority P<n>` runs `cplat spec priority <spec_id> P<n>`, commit, `cplat spec publish`, F again. The
  approval question of AC-149.4 stays as it is (A7).
- product-manager reply block: `PRIORITY: P<n> (P<n>: <phrase>)` in mode `new`, matched to the definitions in the
  skeleton's priority comment.
- Each prompt keeps its byte size or shrinks (tighten wording in the same file); add a register entry with a reason for each
  new rule sentence; `cplat platform rules check --only <file>` passes for each. Do not raise the baseline.

**Done when:** `cplat platform rules check` passes and the structure tests of these prompts pass.

## t5 — /issue:triage uses the reason format and confirm --set

**Files:** plugins/issue/commands/triage.md, docs/rules/plugins/issue/commands/triage.yml
**Covers:** AC-196.1, AC-196.2, AC-196.4, AC-196.6
**Goal:** the triager writes reasons in the checked form and changes priorities through `confirm --set`.

**Implementation notes:**
- Step 2: `priority_reason` is `P<n>: <phrase>` from the batch's `priority_levels`; an existing label and the `P1`
  fallback are cplat's, so the prompt says nothing about them.
- Steps 3 and 4: a priority answer or change (`Change one`, typed `560 p0`) runs `confirm --proposals F --set 560=P0`.
- Step 5 keeps `cplat spec new … --tracks N --priority <P>` with the confirmed priority (AC-196.6).
- Byte size kept or reduced; register entries for new rule sentences; `cplat platform rules check --only` passes.

**Done when:** `cplat platform rules check` passes and the triage prompt structure tests pass.

---
spec_id: 180-prompt-checks-test-behaviour-not
shape: platform
spec_hash: bc2b405af1d4
summary: rules check resolves prompt targets and refuses unmarked sentence pins; a gated rebaseline raises the byte cap; tests rewritten to check structure
tasks:
  - id: t1
    title: promptrefs module and test helpers for prompt targets
    files: [scripts/cplat/promptrefs.py, tests/cplat/structure.py]
    covers: [AC-180.1]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t2
    title: promptpins module for sentence pins and interface markers
    files: [scripts/cplat/promptpins.py]
    covers: [AC-180.2, AC-180.3]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t3
    title: Register baseline history and the rebaseline logic
    files: [scripts/cplat/promptrules.py, scripts/cplat/rules_rebaseline.py]
    covers: [AC-180.5, AC-180.6, AC-180.7]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t4
    title: Docs, ADR and changelog fragment
    files: [docs/rules/README.md, docs/AGENTS.md, CLAUDE.md, docs/changelog.d/180-prompt-checks-test-structure.changed.md, docs/adr/, docs/adr/README.md]
    covers: [AC-180.4, AC-180.5]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t5
    title: Wire targets, pins and rebaseline into cplat platform rules
    files: [scripts/cplat/rulescheck.py, scripts/cplat/cplat.py, tests/cplat/rules_support.py, tests/cplat/test_168_rules_check.py, tests/cplat/test_168_rules_retired_register.py, tests/cplat/test_172_hidden_rules.py]
    covers: [AC-180.1, AC-180.2, AC-180.3, AC-180.4, AC-180.5, AC-180.6]
    parallel_safe: true
    depends_on: [t1, t2, t3]
    done: true
  - id: t6
    title: pr-check rule rules-baseline
    files: [scripts/cplat/rules_baseline.py, scripts/cplat/house_rules.py, tests/cplat/test_168_rules_retire_gate.py]
    covers: [AC-180.7]
    parallel_safe: true
    depends_on: [t3]
    done: true
  - id: t7
    title: Rewrite sentence pins in the numbered test files
    files: ["tests/cplat/test_[0-9]*.py"]
    covers: [AC-180.4]
    parallel_safe: true
    depends_on: [t5, t6]
    done: true
  - id: t8
    title: Rewrite sentence pins in test files a to l
    files: ["tests/cplat/test_[a-l]*.py"]
    covers: [AC-180.4]
    parallel_safe: true
    depends_on: [t5]
    done: true
  - id: t9
    title: Rewrite sentence pins in test files m to z, support modules and e2e
    files: ["tests/cplat/test_[m-z]*.py", tests/cplat/*_support.py, tests/cplat/*_fixtures.py, tests/cplat/*_world.py, tests/cplat/*_fakes.py, tests/cplat/conftest.py, tests/cplat/sharding.py, tests/cplat/shared_render.py, tests/e2e/]
    covers: [AC-180.4]
    parallel_safe: true
    depends_on: [t5]
    done: true
  - id: t10
    title: Fix prompt targets the structural check reports
    files: [plugins/, docs/rules/plugins/, .claude-plugin/marketplace.json]
    covers: [AC-180.1, AC-180.4]
    parallel_safe: true
    depends_on: [t5]
    done: true
---

# Plan — 180 Prompt checks test behaviour not sentences

Contract: [design.md](design.md). Levels: t1, t2, t3, t4 → t5, t6 → t7, t8, t9, t10. This spec's own acceptance tests
(`tests/cplat/test_180_*.py`) match the glob of t7 and are never edited by any task.

## t1 — promptrefs module and test helpers for prompt targets

**Files:** scripts/cplat/promptrefs.py, tests/cplat/structure.py
**Covers:** AC-180.1
**Goal:** a pure module that lists every target a prompt points to and the ones that do not resolve, as in design
*Prompt targets*, plus the helpers the rewritten tests use.

**Implementation notes:**
- `Target`, `slug`, `anchors`, `targets`, `problems` exactly as in the design; no printing, no CLI.
- Prompt files from `promptrules.prompt_files`; `${CLAUDE_PLUGIN_ROOT}` resolves to `plugins/<p>/` of the prompt.
- Fence/inline-code handling as `scripts/check-links.py` for links; cplat names only from code spans and fences.
- cplat validation reads `cplat.NOUNS` / `cplat.PLUMBING` (import inside the function, as `promptrules.enforcement_error`).
- `tests/cplat/structure.py`: `refs`, `points_to`, `headings` over `core.PLATFORM_ROOT`; `points_to` accepts a
  plugin-relative path key (`references/x.md`) by matching the end of a path key.

**Done when:** the AC-180.1 acceptance tests that call `promptrefs` directly pass; `cplat quiet test-fast` green.

## t2 — promptpins module for sentence pins and interface markers

**Files:** scripts/cplat/promptpins.py
**Covers:** AC-180.2, AC-180.3
**Goal:** `scan(root) -> PinScan` as in design *Sentence pins*.

**Implementation notes:**
- `ast` for literals (docstrings and f-strings left out), `tokenize` for `# interface:` comments with their lines.
- Corpus: each prompt's collapsed text, joined with `\x00` so no match crosses files.
- Prefilter by the prompts' word set, then the substring test; stay within the 5 s budget on the platform repo.
- A short-reason marker reports `short-interface` only; its pins are neither counted nor reported again.

**Done when:** the AC-180.2 and AC-180.3 acceptance tests that call `promptpins` directly pass.

## t3 — Register baseline history and the rebaseline logic

**Files:** scripts/cplat/promptrules.py, scripts/cplat/rules_rebaseline.py
**Covers:** AC-180.5, AC-180.6, AC-180.7
**Goal:** the register knows `baseline.history`, and `rules_rebaseline` raises the baseline through the eval gate,
as in design *Register `baseline.history`* and *`cplat platform rules rebaseline`*.

**Implementation notes:**
- `promptrules`: `BaselineRaise`, `Register.baseline_history`, `Register.baseline_bytes_line`, `parse_baseline(text)`,
  validation problems into `reg.problems`.
- `rules_rebaseline.rebaseline(repo, reason, *, today=None) -> Outcome` and `main(argv)` (argparse for `--reason`,
  `--json`, `--repo`); the steps in the design's order; `evalgate._records` looked up at call time.
- Write the register with line edits (keep comments): replace `commit:` and `prompt_bytes:` under `baseline:`, append
  to `history:` (create it as the last key of `baseline:` when absent), in the YAML form of the design.

**Done when:** the AC-180.5 and AC-180.6 acceptance tests that call `rules_rebaseline` directly pass; the register
of the repo still loads.

## t4 — Docs, ADR and changelog fragment

**Files:** docs/rules/README.md, docs/AGENTS.md, CLAUDE.md, docs/changelog.d/180-prompt-checks-test-structure.changed.md, docs/adr/, docs/adr/README.md
**Covers:** AC-180.4, AC-180.5
**Goal:** maintainers know how prompts are tested and how the baseline rises.

**Implementation notes:**
- `cplat adr add prompt-tests-check-structure-not-wording --decision "<the line in design Decisions>"`, never by hand;
  fill Status (Accepted), Context, Decision, Consequences.
- `docs/rules/README.md`: replace rewriting rule 4 (pinned phrases stay verbatim) with the interface marker rule; rule
  6 and *Where entries live* name `baseline.history` and `cplat platform rules rebaseline`; new section *Raise the
  baseline* (run both benchmarks, then rebaseline with a reason; pr-check shows the raise); new section *Test a
  prompt* (structure via `tests/cplat/structure.py`, `# interface: <reason>` for literals code depends on).
- `docs/AGENTS.md` *Rules in prompts* and the rule-register line of `CLAUDE.md`: one clause each on the targets check,
  the pin guard and rebaseline. Link the ADR from `docs/AGENTS.md`.
- Fragment per `docs/changelog.d/README.md`.

**Done when:** `uv run scripts/check-links.py` passes and the ADR index lists the new ADR.

## t5 — Wire targets, pins and rebaseline into cplat platform rules

**Files:** scripts/cplat/rulescheck.py, scripts/cplat/cplat.py, tests/cplat/rules_support.py, tests/cplat/test_168_rules_check.py, tests/cplat/test_168_rules_retired_register.py, tests/cplat/test_172_hidden_rules.py
**Covers:** AC-180.1, AC-180.2, AC-180.3, AC-180.4, AC-180.5, AC-180.6
**Goal:** `cplat platform rules check` reports the new failure kinds and counts, and `cplat platform rules rebaseline`
exists, as in design *`cplat platform rules check` (changed)*.

**Implementation notes:**
- `_check_prompt` adds `promptrefs.problems` per prompt in scope; `check` runs `promptpins.scan` when `only is None`.
- `counts["targets"]`, `counts["interface_pins"]`; the new OK line; `--json` unchanged otherwise.
- `main`: a `rebaseline` subparser that delegates to `rules_rebaseline.main`; update the module docstring and the
  `cplat.py` usage line (`cplat platform rules check|rebaseline …`).
- Keep the spec 168/172 tests proving their criteria: adjust fixture prompts in `rules_support.py` (and the listed
  test files) where their links or cplat names do not resolve in the fixture, and the OK-line regex in
  `test_168_rules_check.py`; keep every AC id they name.

**Done when:** the AC-180.1–180.3 tests that run `rules check` on fixture repos and the AC-180.5/180.6 CLI tests pass;
the spec 168 and 172 tests pass. The repo's own `rules check` may still fail on pins until t7–t10.

## t6 — pr-check rule rules-baseline

**Files:** scripts/cplat/rules_baseline.py, scripts/cplat/house_rules.py, tests/cplat/test_168_rules_retire_gate.py
**Covers:** AC-180.7
**Goal:** `pr-check` shows a baseline raise and refuses one without its history entry, as in design *`cplat platform
pr-check` rule `rules-baseline`*.

**Implementation notes:**
- `rules_baseline.check(repo, base, notes)` with `promptrules.parse_baseline` on both sides; merge base as
  `rules_retire._base_rev`.
- `house_rules`: add `rules-baseline` to `RULES` after `rules-retired`; call it under the register guard; `notes` also
  in `--json`; the new OK line, and its exact-match assertion in `test_168_rules_retire_gate.py`.

**Done when:** the AC-180.7 acceptance tests pass; the spec 150, 168 and 171 pr-check tests pass.

## t7 — Rewrite sentence pins in the numbered test files

**Files:** tests/cplat/test_[0-9]*.py
**Covers:** AC-180.4
**Goal:** no unmarked `sentence-pin` remains in these files.

**Implementation notes:**
- List the pins with `cplat platform rules check --json` (kind `sentence-pin`) and work file by file.
- A pin that asserted agent behaviour becomes a structural assertion through `tests/cplat/structure.py` (the prompt
  points to its reference, command or heading); behaviour is left to the eval gate (A5).
- A literal code depends on keeps its pin with `# interface: <reason of 3+ words>`.
- Keep every criterion id each test named; a test whose only content was a pin keeps its id on the structural
  replacement. Never edit `tests/cplat/test_180_*.py`.

**Done when:** `rules check --json` lists no failure in these files; `cplat spec check` reports no criterion that lost
its last test; `cplat quiet test-fast` green for these files.

## t8 — Rewrite sentence pins in test files a to l

**Files:** tests/cplat/test_[a-l]*.py
**Covers:** AC-180.4
**Goal:** as t7, for these files.

**Implementation notes:** as t7.

**Done when:** as t7, for these files.

## t9 — Rewrite sentence pins in test files m to z, support modules and e2e

**Files:** tests/cplat/test_[m-z]*.py, tests/cplat/*_support.py, tests/cplat/*_fixtures.py, tests/cplat/*_world.py, tests/cplat/*_fakes.py, tests/cplat/conftest.py, tests/cplat/sharding.py, tests/cplat/shared_render.py, tests/e2e/
**Covers:** AC-180.4
**Goal:** as t7, for these files.

**Implementation notes:** as t7; a pin in a support module used by several test files becomes a structural helper
call or an interface pin there.

**Done when:** as t7, for these files.

## t10 — Fix prompt targets the structural check reports

**Files:** plugins/, docs/rules/plugins/, .claude-plugin/marketplace.json
**Covers:** AC-180.1, AC-180.4
**Goal:** every link, anchor, plugin-root path, cplat name and slash command in the prompts resolves.

**Implementation notes:**
- Fix only the target (path, anchor, command name), never the wording around it (non-goal); the prompts may not grow
  (`bytes`).
- None reported → no change; say so in the report.
- A changed plugin gets a patch bump in its `plugin.json` and `.claude-plugin/marketplace.json`; a changed rule
  sentence updates its entry text under `docs/rules/plugins/`.

**Done when:** `rules check --json` reports no `broken-link`, `broken-anchor`, `unknown-cplat` or `unknown-slash`;
`devbox run validate` passes.

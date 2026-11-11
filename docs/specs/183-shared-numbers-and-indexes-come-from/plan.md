---
spec_id: 183-shared-numbers-and-indexes-come-from
shape: platform
spec_hash: "5062d1ea8515"
summary: Spec and ADR numbers from all branches and open PRs, cplat adr add, replaced criteria marked, quiet closed pipes
tasks:
  - id: t1
    title: Shared ref and open-PR scan (refscan), adr.py on top of it
    files: [scripts/cplat/refscan.py, scripts/cplat/adr.py]
    covers: [AC-183.1, AC-183.2]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t2
    title: Spec numbers across branches and open PRs in spec new and spec check
    files: [scripts/cplat/specnumbers.py, scripts/cplat/spec.py]
    covers: [AC-183.1, AC-183.2]
    parallel_safe: true
    depends_on: [t1]
    done: true
  - id: t3
    title: cplat adr add writes the ADR and appends its index row
    files: [scripts/cplat/adrcmd.py, scripts/cplat/assets/adr-template.md, scripts/cplat/cplat.py]
    covers: [AC-183.3]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t4
    title: A closed stdout pipe exits 141 without a traceback or an issue
    files: [scripts/cplat/cplat.py]
    covers: [AC-183.7]
    parallel_safe: false
    depends_on: []
    done: true
  - id: t5
    title: Replaced criteria checked, counted as withdrawn, traced, struck by --from-plan
    files: [scripts/cplat/spec_replace.py, scripts/cplat/spec.py]
    covers: [AC-183.5, AC-183.6, AC-183.8]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t6
    title: Prompts use cplat adr add and mark replaced criteria; ADR index row, versions, changelog
    files: [plugins/svc/agents/architect.md, plugins/component/commands/plan.md, plugins/svc/agents/product-manager.md,
      plugins/system/agents/planner.md, plugins/svc/skills/spec-format/references/spec.md,
      plugins/svc/skills/spec-format/references/design.md, docs/rules/plugins/svc/agents/architect.yml,
      docs/rules/plugins/component/commands/plan.yml, docs/rules/plugins/svc/agents/product-manager.yml,
      docs/rules/plugins/system/agents/planner.yml, docs/rules/plugins/svc/skills/spec-format/references/spec.yml,
      docs/rules/plugins/svc/skills/spec-format/references/design.yml, tests/cplat/test_adr_numbers_337.py,
      docs/adr/README.md, .claude-plugin/marketplace.json, plugins/svc/.claude-plugin/plugin.json,
      plugins/component/.claude-plugin/plugin.json, plugins/system/.claude-plugin/plugin.json,
      docs/changelog.d/183-shared-numbers-and-indexes.added.md]
    covers: [AC-183.4, AC-183.8]
    parallel_safe: true
    depends_on: []
    done: true
---

# Plan — 183 Shared numbers and indexes come from cplat

Contract and decisions: [design.md](design.md). Level 1: t1, t3, t4 (serial with t3: both edit `cplat.py`), t5, t6.
Level 2: t2.

## t1 — Shared ref and open-PR scan (refscan), adr.py on top of it

**Files:** scripts/cplat/refscan.py, scripts/cplat/adr.py
**Covers:** AC-183.1, AC-183.2 (the scan both build on)
**Goal:** move the git and `gh` reading out of `adr.py` into `refscan.py`, parameterised by directory, with an open-PR
result that tells "could not read" (`None`) apart from "no PRs" (`{}`).

**Implementation notes:**
- `refscan.base`, `entries_at`, `other_branches`, `open_pr_paths` exactly as in design.md, Contract, `refscan`.
- `open_pr_paths` returns every file path of each open PR (not only one directory), keyed `#<n>`, leaving out the PR
  of the current branch; `None` on missing `gh`, non-zero exit, invalid JSON or timeout.
- `adr.py` keeps `local`, `at_ref`, `other_branches`, `open_prs`, `added_here`, `clashes`, `next_number` with their
  signatures and results; they call `refscan` (`open_prs` maps `None` to `{}` as today).
- No fetch and no other network call.

**Done when:** `tests/cplat/test_adr_numbers_337.py` (first three tests) still passes and `refscan` has unit tests for
the `None` / `{}` distinction (fake `gh` on `PATH`).

## t2 — Spec numbers across branches and open PRs in spec new and spec check

**Files:** scripts/cplat/specnumbers.py, scripts/cplat/spec.py
**Covers:** AC-183.1, AC-183.2
**Goal:** `cplat spec new` takes one more than the highest spec number on main, any pushed branch and any open PR;
`cplat spec check` reports a number this branch adds that another branch or open PR also adds.

**Implementation notes:**
- `specnumbers.next_number(root) -> (int, warning | None)`: the union in design.md (working tree incl. broken specs,
  base, other branches, open PR paths `docs/specs/<NNN>-…`, legacy `STORY-NNN`); folder names matching `^\d{3,}-`.
- `spec.next_number` delegates to it; `spec.new` prints the warning to stderr (exactly one line, text as in
  design.md) and keeps stdout as today. `--from-plan` goes through the same path.
- `specnumbers.clashes(root) -> (errors, warning | None)`: mine = local folders not at the base; no `gh` call when mine
  is empty; errors in the exact wording of design.md, one per (number, place); same folder name elsewhere is no clash.
- In `spec.main` `check`, add the errors under the key `docs/specs` next to the ADR clashes; print the warning as a
  `WARNING:` line before the results.
- Leave the rest of `spec.py` alone: t5 changes `check()`, `acs()`, trace and `new_from_plan` in the level before.

**Done when:** the acceptance tests for AC-183.1 and AC-183.2 pass.

## t3 — cplat adr add writes the ADR and appends its index row

**Files:** scripts/cplat/adrcmd.py, scripts/cplat/assets/adr-template.md, scripts/cplat/cplat.py
**Covers:** AC-183.3
**Goal:** one command creates the next ADR from the platform's template and appends exactly one row to the index.

**Implementation notes:**
- `adrcmd.main(argv)`: argparse `add <slug> --decision TEXT [--offline] [--repo DIR]`; validate everything before
  writing anything (slug pattern, empty decision after collapsing whitespace, slug already used by `docs/adr/*-<slug>.md`),
  raising `PlatformError` with the reasons in design.md.
- Number from `adr.next_number(root, with_prs=not offline)`, never computed separately.
- Render `assets/adr-template.md` (placeholders for number, title, date, decision); title = slug with spaces, first
  letter upper-cased.
- Index edit as text: insert after the last table line, escape `|` in the decision, keep every other byte; create the
  index (A4) or the table when missing, as in design.md.
- Print only the ADR's repo-relative path.
- `cplat.py`: add `"adr": "adrcmd"` to `PLUMBING` and one line to the module docstring
  (`cplat adr add <slug> --decision "<one line>" [--offline]   the next ADR from the template and its index row`).
  Touch nothing else in `cplat.py` (t4 changes `main`).

**Done when:** the acceptance tests for AC-183.3 pass and `scripts/shapes.py check` passes on a repo where the command
added an ADR.

## t4 — A closed stdout pipe exits 141 without a traceback or an issue

**Files:** scripts/cplat/cplat.py
**Covers:** AC-183.7
**Goal:** `cplat <anything> | head -1` ends with status 141 and an empty stderr; no crash report, no issue.

**Implementation notes:**
- In `main`, catch `BrokenPipeError` around `_resolve` and `module.main` before the `PlatformError` and generic
  `Exception` handlers, so `_file_crash` is never reached.
- On it: redirect fd 1 to `os.devnull` (`os.dup2`) so the interpreter's final flush cannot write "Exception ignored …"
  to stderr, then return 141.
- Keep the line-buffering set-up and every other exit code unchanged. Not `parallel_safe` with t3 (same file).

**Done when:** the acceptance tests for AC-183.7 pass, including a subprocess run of the launcher-equivalent
`uv run scripts/cplat/cplat.py shape | head -1` (or `python`) with `pipefail`.

## t5 — Replaced criteria checked, counted as withdrawn, traced, struck by --from-plan

**Files:** scripts/cplat/spec_replace.py, scripts/cplat/spec.py
**Covers:** AC-183.5, AC-183.6, AC-183.8 (the `--from-plan` strike for the system planner's slices)
**Goal:** a `(replaces AC-…)` marker is enforced by `cplat spec check`, a superseded criterion counts as withdrawn and
shows as "superseded by" in trace, and a plan slice strikes the criterion it replaces.

**Implementation notes:**
- `spec_replace.py`: the marker and superseded regexes of design.md; `markers(spec)`, `errors(spec, by_number)`,
  `strike(spec_dir, old, new)`. It must not import `spec` at module level (spec.py imports it lazily).
- `spec.AC` gets `superseded_by: str | None`, filled in `acs()`; a superseded line stays `withdrawn=True`.
- `check()`: when the spec is not `superseded` and its criteria hold a marker, build `{number: Spec}` from the repo once
  and append `spec_replace.errors` (wording in design.md); specs without a marker never scan.
- `check_plan`: a task covering a superseded criterion is not an error (withdrawn still is).
- `ac_hash`: read a superseded line with `: <old text>` as `- **<old>** <old text>` before hashing, so striking keeps
  the old spec's `spec_hash` (check it on a done spec with a plan in a test).
- `trace` CLI: the superseded lines and the JSON key of design.md; counts and exit code unchanged.
- `new_from_plan`: after writing the slice, call `strike` for every marker whose target spec is in this repo.
- Do not touch `new()`, `next_number` or the `check` CLI branch (t2 changes them in the next level).

**Done when:** the acceptance tests for AC-183.5 and AC-183.6 pass, plus the part of AC-183.8 a slice can check
(`cplat spec new --from-plan` with a `(replaces …)` criterion leaves `cplat spec check` green).

## t6 — Prompts use cplat adr add and mark replaced criteria; ADR index row, versions, changelog

**Files:** the prompts, their register files, `tests/cplat/test_adr_numbers_337.py`, `docs/adr/README.md`, the plugin
versions and the changelog fragment (full list in the metadata)
**Covers:** AC-183.4, AC-183.8
**Goal:** the architect and `/component:plan` create ADRs only through `cplat adr add`; the product-manager, the system
planner and the spec format reference tell how to mark a replaced criterion; the prompts total no more bytes than at
the base commit.

**Implementation notes:**
- Architect step 3: replace the hand-written path and the `ADR_NEXT` numbering with `cplat adr add <slug> --decision
  "<one line>"`, then fill in the file's sections; reword register entry R1 to the new sentence (keep its reason
  clause). Reply line `ADRS:` stays.
- `/component:plan`: drop `ADR_NEXT` (step 6 and the architect prompt), commit `docs/adr/` instead of "any new ADRs".
- `references/design.md` (last rule): the ADR is created with `cplat adr add`, not written into `docs/adr/` by hand.
- `references/spec.md`, Amending: a criterion that changes behaviour an active criterion of another spec in this repo
  defines ends with `(replaces AC-<NNN>.<n>)`; in the same change the old one becomes
  `- ~~**AC-<NNN>.<n>**~~ superseded by AC-<MMM>.<m> on <date>: <its old text>` with one Changelog line in the old spec
  (status unchanged); `cplat spec check` refuses an unstruck target. Keeping the old text is what keeps its `spec_hash`.
- Product-manager: one rule pointing to that Amending rule, with its reason (the old behaviour stops being counted);
  it may replace rule 1's "name any conflict with another spec as an open question" for a behaviour change.
- System planner, step 3: a repo criterion that changes an active criterion of that repo's spec ends with
  `(replaces AC-<NNN>.<n>)`; `cplat spec new --from-plan` strikes the old one in the repo's spec change.
- Each new rule sentence: an entry in its register file (next `R<n>`, `class: practice`, `source: "#477"`).
- Byte budget across all touched prompts: `promptrules.prompt_bytes` after ≤ at the merge base with main; pay for the
  additions with the removals above and by tightening wording in the same files, never by removing a hard rule.
- `test_adr_numbers_337.py::test_the_plan_hands_the_architect_a_free_number_337`: assert the prompts name
  `cplat adr add` instead of `ADR_NEXT` (the #337 intent, a free number, is now the command's).
- `docs/adr/README.md`: the "Adding one" sentence says `cplat adr add`; append the row for ADR-099 (written by the
  architect with this plan) as the last line.
- Bump `svc`, `component`, `system` (minor) in their `plugin.json` and `marketplace.json`; changelog fragment
  `183-shared-numbers-and-indexes.added.md`.

**Done when:** the acceptance tests for AC-183.4 and AC-183.8 pass, `cplat platform rules check` passes,
`scripts/shapes.py check` passes, and `cplat platform pr-check` reports no version or fragment problem.

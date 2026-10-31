---
spec_id: 129-a-platform-release-command
shape: platform
spec_hash: 5859f4ec7f67
summary: "cplat platform release (platrelease, platrelease_state, platrelease_changelog, platrelease_publish) derives the release phase from git and GitHub (release branch, release PR, squash commit, tag, GitHub release, release guard), prints state, version and steps, prepares the changelog on release/X.Y.Z, runs release-check rows and devbox run validate, commits signed off, opens the PR, waits with pr.wait, stops before merge and tag (exit 3, --confirm merge|tag), waits for the upgrade e2e on the merge commit (10-minute start window), runs the gate, tags, publishes the GitHub release and waits for the release guard; release-check.py gains needs-major; /platform:release relays it; /component:release and CONTRIBUTING name it; ADR-073; platform 1.4.0, component 1.5.3"
tasks:
  - id: t1
    title: release-check.py needs-major subcommand sharing the major rule with rows
    files: [scripts/release-check.py]
    covers: [AC-129.2, AC-129.3]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t2
    title: platrelease_changelog — move [Unreleased], section body, plugin/marketplace version mismatches
    files: [scripts/cplat/platrelease_changelog.py]
    covers: [AC-129.4, AC-129.5, AC-129.6, AC-129.15]
    parallel_safe: true
    depends_on: []
  - id: t6
    title: /platform:release command, /component:release refusal, CONTRIBUTING Releases, READMEs, ADR index, plugin bumps, CHANGELOG
    files: [plugins/platform/commands/release.md, plugins/platform/README.md, plugins/platform/.claude-plugin/plugin.json, plugins/component/commands/release.md, plugins/component/.claude-plugin/plugin.json, .claude-plugin/marketplace.json, CONTRIBUTING.md, README.md, docs/DOMAIN-MODEL.md, docs/adr/README.md, docs/CHANGELOG.md, tests/cplat/test_plugins_114.py]
    covers: [AC-129.20, AC-129.21]
    parallel_safe: true
    depends_on: []
  - id: t3
    title: platrelease_state — detection of the phase, version proposal and checks, steps and the state block
    files: [scripts/cplat/platrelease_state.py]
    covers: [AC-129.1, AC-129.2, AC-129.3, AC-129.17, AC-129.18, AC-129.19]
    parallel_safe: false
    depends_on: [t1, t2]
  - id: t4
    title: platrelease CLI — registration, preflight, dry run, prepare/commit/push/PR, CI wait and the merge stop
    files: [scripts/cplat/platrelease.py, scripts/cplat/cplat.py]
    covers: [AC-129.1, AC-129.3, AC-129.4, AC-129.5, AC-129.6, AC-129.7, AC-129.8, AC-129.9, AC-129.10, AC-129.11, AC-129.17, AC-129.18]
    parallel_safe: false
    depends_on: [t3]
  - id: t5
    title: platrelease_publish — upgrade e2e on the merge commit, gate, tag stop, tag, GitHub release, release guard
    files: [scripts/cplat/platrelease_publish.py, scripts/cplat/platrelease.py]
    covers: [AC-129.12, AC-129.13, AC-129.14, AC-129.15, AC-129.16, AC-129.17, AC-129.19]
    parallel_safe: false
    depends_on: [t4]
---

# Plan — 129 A platform release command

The contract (CLI, exit codes, phases, output texts, gh/git calls, test seams) is in [design.md](design.md); every task
implements its part of it exactly. Levels: t1, t2, t6 → t3 → t4 → t5. The build runs sequentially (#319); t3–t5 build on
one another and are not parallel-safe.

## t1 — release-check.py needs-major subcommand sharing the major rule with rows

**Files:** scripts/release-check.py
**Covers:** AC-129.2, AC-129.3
**Goal:** the version proposal and `--version` validation use the same "needs a major release" rule as `rows`, from the
script itself, not a copy.

**Implementation notes:**
- Extract `major_reasons(base, changes) -> list[str]` from `cmd_rows` (the `needing` list: changed rows with a major
  move, `crds` and `removed` changes, plus `dropped_majors(base)`).
- `cmd_rows` uses it; its output stays byte-identical (existing tests of spec 121 must stay green).
- New subcommand `needs-major [--base REF]`: prints each reason on its own line, nothing when none, exit 0; the
  existing `except Exception` path gives `ERROR: …` and exit 1. Update the module docstring.
- Never touches a tag; no new imports.

**Done when:** the AC-129.2 acceptance tests for `needs-major` pass and `tests/cplat` tests of `release-check.py rows` stay green.

## t2 — platrelease_changelog: move [Unreleased], section body, plugin/marketplace version mismatches

**Files:** scripts/cplat/platrelease_changelog.py
**Covers:** AC-129.4, AC-129.5, AC-129.6, AC-129.15
**Goal:** the pure text and file-reading functions the command needs, with no git or gh.

**Implementation notes:**
- `unreleased_body(text) -> str`: the text between the `## [Unreleased]` line and the next `## [` line ("" when absent).
- `move_unreleased(text, version, date) -> str`: per design.md, Prepare; idempotent when `## [version]` already exists.
- `section_body(text, version) -> str | None`: the body of `## [version]` without the heading line, leading and trailing
  blank lines removed (the GitHub release notes, AC-129.15).
- `plugin_mismatches(repo) -> list[str]`: `<name>: marketplace <v1>, plugin.json <v2>` for every plugin whose versions
  differ, sorted by name; a plugin missing from the catalog counts as a mismatch with `marketplace -`. Reads only.
- Standard library only; headings match `^## \[` like `release-check.HEADING`.

**Done when:** the AC-129.5 and AC-129.6 tests that exercise these functions directly pass (the CLI-level ones pass after t4).

## t6 — /platform:release command, /component:release refusal, CONTRIBUTING Releases, READMEs, ADR index, plugin bumps, CHANGELOG

**Files:** plugins/platform/commands/release.md, plugins/platform/README.md, plugins/platform/.claude-plugin/plugin.json, plugins/component/commands/release.md, plugins/component/.claude-plugin/plugin.json, .claude-plugin/marketplace.json, CONTRIBUTING.md, README.md, docs/DOMAIN-MODEL.md, docs/adr/README.md, docs/CHANGELOG.md, tests/cplat/test_plugins_114.py
**Covers:** AC-129.20, AC-129.21
**Goal:** the slash command and every place that names the release procedure.

**Implementation notes:**
- `plugins/platform/commands/release.md`: front matter `description:` ≤ 260 chars with
  `Usage: /platform:release [--version X.Y.Z] [--dry-run]`; body with `$ARGUMENTS`, mirroring `fleet.md`: run
  `cplat platform release <ARGS>` in the background and read until it ends; show output verbatim; on exit 3 show the
  `CONFIRM:` block, ask the user, and only on their yes run it again with the same `--version` plus `--confirm merge` or
  `--confirm tag`; exit 1 → report the `ERROR:` line, stop. Rules: never merge, tag, push or create a release by hand;
  never pass `--confirm` without the user's yes. Ends with the `/issue:report` note.
- `plugins/component/commands/release.md`: keep the refusal block's existing sentences (spec 123 tests assert them) and
  add the line `Release the platform with /platform:release (or cplat platform release).`
- CONTRIBUTING.md, Releases: the procedure is `/platform:release` / `cplat platform release` (what it does in one
  paragraph: phases, the two confirmations, resume); keep "`/component:release` refuses" and the gate paragraph.
- Bumps: `platform` 1.3.0 → 1.4.0 (new command; description and keywords name `release`), `component` 1.5.2 → 1.5.3
  (refusal text), both in plugin.json and marketplace.json.
- `plugins/platform/README.md` row, root `README.md` platform row, `docs/DOMAIN-MODEL.md` platform verb row: add `release`.
- `docs/adr/README.md`: row for ADR-073 (already written).
- `docs/CHANGELOG.md` `[Unreleased]`: one entry `**/platform:release.**` (#296, what it does, the stops, resume) and
  `**Plugins:** `platform` 1.4.0, `component` 1.5.3.`
- `tests/cplat/test_plugins_114.py`: `WORKING["platform"]` gains `release`, the total becomes 41 (comment: spec 129).

**Done when:** the AC-129.20/.21 tests pass, `devbox run validate` passes, and `test_plugins_114.py` and
`test_platform_shape_123.py` stay green.

## t3 — platrelease_state: detection of the phase, version proposal and checks, steps and the state block

**Files:** scripts/cplat/platrelease_state.py
**Covers:** AC-129.1, AC-129.2, AC-129.3, AC-129.17, AC-129.18, AC-129.19
**Goal:** everything read-only: fetch, detect, decide the version, list the steps, render the state block.

**Implementation notes:**
- Seams exactly as in design.md: `run_check(repo, cmd) -> (rc, output)` (subprocess, `cwd=repo`, stderr merged) and
  `today() -> date`; every gh call through `ship.gh`.
- `fetch(repo)`: `git fetch origin --tags` and `git fetch origin main` (no prune).
- `detect(repo) -> State` (dataclass: newest tag and its commit, M, branch, PR, tag of the version, GitHub release,
  guard run, phase, version): T from `git ls-remote --tags origin` (peeled `^{}`), M from `git log -n 200 origin/main`,
  branches, PR list, release view and the release-guard run list per design.md; the phase table and its errors (two
  releases in flight, several branches/PRs, AC-129.19 tag elsewhere).
- Guard age: tagger date via `git for-each-ref refs/tags/vX --format=%(taggerdate:unix)` against `ship.now()`;
  no tagger date counts as old.
- `propose(repo, T) -> (version, reason)` via `needs-major`; `check_version(requested, state, reasons)` raising
  `core.PlatformError` with the design's texts (AC-129.3, AC-129.18).
- `steps(phase, version, sha, date) -> list[str]` with the twelve texts and phase start points of design.md.
- `render(state, version, reason, steps) -> list[str]`: the state block, `phase:`, `version:` and `steps:` lines.

**Done when:** the detection, proposal and rendering tests of AC-129.1/.2/.3/.17/.18/.19 that call this module pass.

## t4 — platrelease CLI: registration, preflight, dry run, prepare/commit/push/PR, CI wait and the merge stop

**Files:** scripts/cplat/platrelease.py, scripts/cplat/cplat.py
**Covers:** AC-129.1, AC-129.3, AC-129.4, AC-129.5, AC-129.6, AC-129.7, AC-129.8, AC-129.9, AC-129.10, AC-129.11, AC-129.17, AC-129.18
**Goal:** `cplat platform release` up to and including the merge.

**Implementation notes:**
- cplat.py: `"release": ("platrelease", [])` under `platform`, docstring line
  `cplat platform release [--version X.Y.Z] [--dry-run] [--confirm merge|tag]   prepare, merge, tag and publish a platform release`.
- `main(argv)`: argparse per design.md; the order of checks 1–6; print the state block always; `--dry-run` returns 0
  after it. Refusals raise `core.PlatformError` (exit 1 through cplat.py).
- `--confirm` validation against the start phase; exit 3 at a stop with the exact `CONFIRM: merge` block.
- Preflight (idle) texts from design.md; git user from `git config` (no fallback identity: the DCO needs the real one).
- Prepare: `git switch -c`, `move_unreleased`, `run_check` rows then validate (print output; failure exits 1 before any
  commit), `git add docs/CHANGELOG.md`, `git commit -s -m`, `git push -u origin release/X` (never forced), `gh pr create`
  through `ship.gh` with the fixed body; resume rules of the `branch` phase.
- CI: `pr.wait(merge=False)`; red → its lines and the ERROR; green → e2e check present and `pass` via `ship.checks`.
- Merge with `--confirm merge`: `pr.wait(merge=True)`, merge sha via `gh pr view`, fast-forward local main (note on
  failure), then call into `platrelease_publish.continue_from_merged(...)` once t5 exists (until then end with exit 0 after
  printing the merge — t5 replaces that).

**Done when:** the AC-129.1, .3–.11, .17 (branch and PR phases) and .18 tests pass.

## t5 — platrelease_publish: upgrade e2e on the merge commit, gate, tag stop, tag, GitHub release, release guard

**Files:** scripts/cplat/platrelease_publish.py, scripts/cplat/platrelease.py
**Covers:** AC-129.12, AC-129.13, AC-129.14, AC-129.15, AC-129.16, AC-129.17, AC-129.19
**Goal:** everything after the merge, and the `merged`, `tagged` and `guarding` phases of a resumed run.

**Implementation notes:**
- `APPEAR_WINDOW = 600`; `wait_for_run(repo, slug, list_args, select, timeout, interval) -> (status, url)`: poll the run
  list with `ship.now`/`ship.sleep` until a run appears (window), take the highest `databaseId`, follow it with
  `ship.RunWatch` until green, red or timeout. Used for the upgrade e2e (`--commit S --event push`) and the release guard
  (`headBranch == vX`).
- Gate through `platrelease_state.run_check`, output printed; failure exits 1, no tag.
- Tag stop block with the notes between `--- release notes ---` / `--- end ---`; with `--confirm tag`: AC-129.19 check
  (origin and local), `git tag -a vX -m vX S` (or push an existing local tag on S), `git push origin refs/tags/vX`.
- GitHub release with `--notes-file <git dir>/RELEASE_NOTES.md --verify-tag`; skipped when `release view` finds one.
- Guard: green → `RELEASED:` block, exit 0; red → ERROR with the run URL, exit 1, nothing touched; never deletes or moves
  a tag.
- platrelease.py: dispatch phases `merged`, `tagged`, `guarding` and the post-merge continuation to this module.

**Done when:** the AC-129.12–.16, .17 (merged, tagged, guarding phases) and .19 tests pass and `devbox run test-fast` is green.

---
spec_id: 223-change-quality-fix-causes-and-attempts
shape: platform
spec_hash: afc214fb86df
summary: "Fixed fragments end in a checked `Caused by:` line; `cplat platform change-quality` reports per release the fixes it caused, their blast radius and the change-failure rate; `runs report` groups ship, build and fix runs into chains with attempts to done and chain cost"
tasks:
  - id: t1
    title: "fixcause module and the pr-check cause rule (form, GitHub verification, WARNING when unreachable)"
    files: [scripts/cplat/fixcause.py, scripts/cplat/house_rules.py, docs/changelog.d/README.md]
    covers: [AC-223.1, AC-223.2, AC-223.3]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t2
    title: "CI fragment check: release-check.py fragments --base REF in the release-check job"
    files: [scripts/release-check.py, .github/workflows/ci.yml]
    covers: [AC-223.1]
    parallel_safe: true
    depends_on: [t1]
  - id: t3
    title: "change-quality sources: releases, Fixed sections, fragments, PR to release, journeys, fleet stamp history"
    files: [scripts/cplat/changequality_sources.py]
    covers: [AC-223.4, AC-223.5]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t4
    title: "cplat platform change-quality: attribution, blast radius, change-failure rate, text and JSON"
    files: [scripts/cplat/changequality.py, scripts/cplat/cplat.py]
    covers: [AC-223.4, AC-223.5, AC-223.6]
    parallel_safe: true
    depends_on: [t1, t3]
  - id: t5
    title: "runs report: chains with attempts to done, chain cost and the delivered-item summary"
    files: [scripts/cplat/runs_chains.py, scripts/cplat/runs_report.py]
    covers: [AC-223.7, AC-223.8, AC-223.9]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t6
    title: "Contributor docs for the cause line and the changelog fragment of spec 223"
    files: [CONTRIBUTING.md, .github/PULL_REQUEST_TEMPLATE.md, docs/changelog.d/223-change-quality-fix-causes-and-attempts.added.md]
    covers: [AC-223.1, AC-223.4, AC-223.7]
    parallel_safe: true
    depends_on: []
    done: true
---

# Plan — 223 Change quality: fix causes and attempts to done

The contract (messages, JSON keys, text lines) is in [design.md](design.md); every task follows it exactly.

## t1 — fixcause module and the pr-check cause rule

**Files:** scripts/cplat/fixcause.py, scripts/cplat/house_rules.py, docs/changelog.d/README.md
**Covers:** AC-223.1, AC-223.2, AC-223.3
**Goal:** a branch that adds a `fixed` fragment without a valid `Caused by:` line fails pr-check with one `ERROR:` line naming the fragment and the form; a valid PR or tag cause is checked on GitHub, and an unreachable GitHub gives one `WARNING:` line instead of a failure.

**Implementation notes:**
- `fixcause.py` (pure apart from `verify`): `CAUSE` regex, `Cause`, `parse_cause`, `form_error`, `entries`, `numbers`, `verify(slug, cause, *, gh=None)` as in design.md. `gh` defaults to a `core.run(["gh", …], check=False)` wrapper so tests replace it.
- `verify`: `gh api repos/<slug>/pulls/<n>`: rc 0 and `merged_at` set → ok; rc 0 and `merged_at` null, or a 404/`Not Found` → error; anything else → warning. Tag: `gh api repos/<slug>/git/ref/tags/v<X.Y.Z>`, 404 → error, other failure → warning.
- `house_rules.check`: inside the `fragment` rule, for each added fragment whose name ends `.fixed.md` and that parsed, append `form_error`; when valid and of kind `prs`/`version`, resolve the slug once (`gh repo view --json nameWithOwner`; failure → all checks unreachable) and call `verify`; errors join `problems`, warnings join `notes` as `WARNING: …`.
- Only `added(repo, base)` fragments are checked, so already-merged and released fragments never are; `added`/`changed` fragments need no cause.
- `cplat pr open` uses `PR_OPEN_RULES` (includes `fragment`): it gets the same check; keep its output path unchanged.
- `platrelease_changelog.assemble` stays unchanged; add no rewrite of entry text (AC-223.3 holds by construction; the acceptance test proves it).
- `docs/changelog.d/README.md`: a `fixed` fragment ends with the cause line on its own line directly under the text; the four forms; what `none` and `unknown` mean; that pr-check verifies and CI checks the form.

**Done when:** the acceptance tests for AC-223.1 (pr-check part), AC-223.2 and AC-223.3 pass, and the existing pr-check tests (`tests/cplat/test_150_pr_check.py`, `test_171_pr_check_tracks.py`, `test_180_rules_baseline_prcheck.py`) still pass.

## t2 — CI fragment check

**Files:** scripts/release-check.py, .github/workflows/ci.yml
**Covers:** AC-223.1
**Goal:** CI fails a PR that adds a `fixed` fragment without a valid cause line, offline.

**Implementation notes:**
- New subcommand `fragments [--base REF]`: files from `git diff --name-only --diff-filter=A <base>...HEAD` under `docs/changelog.d/` ending `.fixed.md`; `fixcause.form_error` on each; output and exit as in design.md. `--base` default: `origin/main`.
- Document it in the module docstring next to `rows`.
- `ci.yml` `release-check` job: one more step running `uv run scripts/release-check.py fragments --base "$BASE"`, with `BASE` set in the step's shell to `origin/$GITHUB_BASE_REF` when that variable is set (a pull request), else `HEAD~1` (a push). The job already checks out with `fetch-depth: 0`; leave the pinned actions as they are.

**Done when:** the acceptance tests for AC-223.1 (CI part) pass and `uv run scripts/release-check.py fragments --base origin/main` prints `OK` on this branch.

## t3 — change-quality sources

**Files:** scripts/cplat/changequality_sources.py
**Covers:** AC-223.4, AC-223.5
**Goal:** every read change-quality needs, behind small functions with an injectable `git`/`gh` runner, so the aggregate stays pure.

**Implementation notes:**
- `releases(repo) -> list[Release(version, date, body)]` from `docs/CHANGELOG.md` headings `## [X.Y.Z] - YYYY-MM-DD` (reuse `platrelease_changelog.section_body`); `fixed_section(body) -> str` (the text under `### Fixed` up to the next `###`).
- `fragment_fixes(repo) -> list[(name, text)]`: the `*.fixed.md` of `platrelease_changelog.read_fragments`.
- `pr_release(repo, n, *, slug, gh) -> str | None`: commit whose subject ends `(#n)` on `HEAD` (one `git log --format=%H%x00%s` read, cached), else gh `pulls/<n>` `merge_commit_sha`; then the lowest-version `v*` tag of `git tag --contains <sha> --list 'v*'` (`core.vtuple` order), `"Unreleased"` without one; `None` when not found.
- `stopped_journeys(repo) -> list[(journey number, set[int] of #N in the row)]` from `docs/PERFORMANCE.md` table rows with an integer first cell and `**stopped`.
- `fleet_stamps(*, gh) -> dict[slug, list[str]] | FleetUnknown(reason)`: owner = gh login (`gh api user -q .login`), repos via `fleet._list_owner`, platform check via `fleet._read` and `fleet.is_platform` with `core.registry.load()` templates; history via `gh api --paginate repos/<slug>/commits?path=.platform-version -q '.[].sha'` and `contents/.platform-version?ref=<sha>` raw, versions parsed with fleet's `platform: X.Y.Z` regex. Any `PlatformError` or nonzero gh → `FleetUnknown`.
- Progress lines (one per repo read) go to stderr only.

**Done when:** unit tests of each reader against a tmp git repo and a fake `gh` pass; the change-quality acceptance tests pass after t4.

## t4 — cplat platform change-quality

**Files:** scripts/cplat/changequality.py, scripts/cplat/cplat.py
**Covers:** AC-223.4, AC-223.5, AC-223.6
**Goal:** the command of design.md: per window release the fix entries it caused, their carriers, stopped journeys and affected repos; caught before release, unattributed and `none` apart; the change-failure rate over all and over minor/major releases; the same as one JSON document with `--json`.

**Implementation notes:**
- `main(argv)`: `--since vX.Y.Z`, `--json`, `--repo DIR` (default `.`); platform-repo check first (`PlatformError` naming `feedback.REPO`).
- `aggregate(releases, fixes, journeys, resolve, fleet, *, since, today) -> dict`: pure; `resolve` maps a `Cause` to its release(s); follows the attribution rules 1–5 of design.md; `fleet` is called only when a window release caused an entry.
- Entries: `fixcause.entries(fixed_section)` per release (carrier = version) and fragments (carrier `Unreleased`, `numbers` with the fragment id).
- `affected_repos`: slugs with any stamp `v`, `R ≤ v < first carrier`; `FleetUnknown` → `"unknown"` plus `affected_reason`.
- `render_text(agg)` and `json.dumps(agg, indent=2)` with exactly the keys of design.md; nothing else on stdout in JSON mode.
- `cplat.py`: `"change-quality": ("changequality", [])` in `NOUNS["platform"]` and a usage line in the docstring (`cplat platform change-quality [--since vX.Y.Z] [--json]   fix causes, blast radius, change-failure rate (spec 223)`).

**Done when:** the acceptance tests for AC-223.4, AC-223.5 and AC-223.6 pass.

## t5 — runs report: chains

**Files:** scripts/cplat/runs_chains.py, scripts/cplat/runs_report.py
**Covers:** AC-223.7, AC-223.8, AC-223.9
**Goal:** the `Chains:` block and the `chains` JSON key of design.md: attempts, escalations, abandons, failures, attempts to done, chain cost against the successful run, the summary per delivered item, `partial` and `unchained`.

**Implementation notes:**
- `runs_chains.aggregate_chains(kept, *, window_start)` and `chain_lines(chains)`, pure, rules as in design.md; cost read like `aggregate_unattended` (number and `cost_complete` not `false`).
- Unknown cost: `cost_complete: false`, text `>= $X +unknown`, left out of `cost_per_delivered` and `median_successful_cost`; never a 0.
- `runs_report.aggregate`: `out["chains"] = runs_chains.aggregate_chains(kept, window_start=<since date at 00:00 UTC>)`; existing keys untouched.
- `runs_report.render_text`: `lines += runs_chains.chain_lines(agg["chains"])` after the person block, guarded by `"chains" in agg` like the other optional blocks.
- `runs_chains` may `import runs_report` for `_text` and `_ts`, the way `runs_usage_report` does (used only inside functions, so the mutual import is safe).

**Done when:** the acceptance tests for AC-223.7, AC-223.8 and AC-223.9 pass and the existing runs report tests still pass.

## t6 — Contributor docs and the changelog fragment

**Files:** CONTRIBUTING.md, .github/PULL_REQUEST_TEMPLATE.md, docs/changelog.d/223-change-quality-fix-causes-and-attempts.added.md
**Covers:** AC-223.1, AC-223.4, AC-223.7
**Goal:** contributors learn that a `fixed` fragment ends in `Caused by:`, and the maintainer finds `cplat platform change-quality` and the `Chains:` block.

**Implementation notes:**
- CONTRIBUTING.md, where it describes fragments: the cause line, its four forms, that pr-check verifies it and CI checks the form; a sentence on `cplat platform change-quality` in the Releases part.
- PR template checklist item: a `fixed` fragment ends in `Caused by: #<PR> | v<X.Y.Z> | none | unknown`.
- Fragment (one paragraph, existing style, `(spec 223)`): the cause line, `cplat platform change-quality`, the `Chains:` block of `cplat platform runs report`; relative link to `../specs/223-change-quality-fix-causes-and-attempts/spec.md`.

**Done when:** `cplat platform pr-check` passes its `links` and `fragment` rules on the branch.

---
spec_id: 132-changelog-fragments-that-the-release
shape: platform
spec_hash: e4576eccf4f6
summary: "Platform changelog entries become fragments docs/changelog.d/<id>-<slug>.<added|changed|fixed>.md: platrelease_changelog parses, validates and assembles them (Added, Changed, Fixed; [Unreleased] first, then by file name; one ../ stripped from relative links); cplat platform release reads them in preflight, assembles them under the new heading and deletes them in the release commit; release-check rows counts them and rejects invalid ones; unreleased_text(repo) for the version proposal; guidance (CONTRIBUTING, CLAUDE.md, PR template, changelog.d README) names the fragment; old changelog tests find their release by version heading and plugin version tests assert >=; ADR-078"
tasks:
  - id: t1
    title: platrelease_changelog - FRAGMENTS, FragmentError, parse_fragment, read_fragments, assemble, move_unreleased(fragments), unreleased_text
    files: [scripts/cplat/platrelease_changelog.py]
    covers: [AC-132.1, AC-132.2, AC-132.4, AC-132.5, AC-132.7, AC-132.9]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t2
    title: cplat platform release - preflight counts and validates fragments on origin/main, prepare assembles and git-rms them, resume allows docs/changelog.d, PR body names them
    files: [scripts/cplat/platrelease.py]
    covers: [AC-132.2, AC-132.3, AC-132.5, AC-132.6, AC-132.7]
    parallel_safe: false
    depends_on: [t1]
    done: true
  - id: t3
    title: release-check.py rows adds the fragments to the [Unreleased] body and fails on an invalid fragment
    files: [scripts/release-check.py]
    covers: [AC-132.7, AC-132.8]
    parallel_safe: true
    depends_on: [t1]
    done: true
  - id: t4
    title: guidance and dogfood - docs/changelog.d/README.md, CONTRIBUTING.md, CLAUDE.md, PR template, the fragment of this change; naming and dev-latest scans treat fragments like the changelog
    files: [docs/changelog.d/README.md, docs/changelog.d/321-changelog-fragments.added.md, CONTRIBUTING.md, CLAUDE.md, .github/PULL_REQUEST_TEMPLATE.md, tests/cplat/test_naming.py, tests/cplat/test_spec_agents.py]
    covers: [AC-132.1, AC-132.10, AC-132.13]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t5
    title: durable tests - tests/cplat/changelog_support.py; the changelog tests of 115-121, 125, 128, 130 read their section by version heading; plugin version tests of 117, 118, 119, 121 assert >=
    files: [tests/cplat/changelog_support.py, tests/cplat/test_resources_115_cmds.py, tests/cplat/test_bucket_116_cmds.py, tests/cplat/test_backup_117_cmds.py, tests/cplat/test_cache_118_cmds.py, tests/cplat/test_broker_119_cmds.py, tests/cplat/test_scale_120_cmds.py, tests/cplat/test_upgrade_121_ops.py, tests/cplat/test_cluster_125_delivery.py, tests/cplat/test_credentials_128_records.py, tests/cplat/test_130_empty_gates.py]
    covers: [AC-132.11, AC-132.12]
    parallel_safe: true
    depends_on: []
    done: true
---

# Plan — 132 Changelog fragments that the release assembles

Contract: [design.md](design.md). ADR: [078](../../adr/078-platform-changelog-entries-are-fragments-the-release-assembles.md).
Acceptance tests: `tests/cplat/test_changelog_fragments_132.py`, written before t1 and red until the tasks land.

## t1 — fragments in platrelease_changelog

**Files:** scripts/cplat/platrelease_changelog.py
**Covers:** AC-132.1, AC-132.2, AC-132.4, AC-132.5, AC-132.7, AC-132.9
**Goal:** the pure text side: name regex `^[0-9a-z][0-9a-z.-]*\.(added|changed|fixed)\.md$` (README.md skipped), empty body is an error,
assembly per design decision 2, link rewrite per decision 3, `move_unreleased` unchanged without fragments.
**Done when:** the AC-132.1/.2/.4/.5/.7/.9 tests of the unit part pass and the spec 129 tests stay green.

## t2 — the release command

**Files:** scripts/cplat/platrelease.py
**Covers:** AC-132.2, AC-132.3, AC-132.5, AC-132.6, AC-132.7
**Goal:** preflight reads fragments at `origin/main` (`git ls-tree`, `git show`), validates them before anything is created, and accepts
fragments as content; `_prepare` assembles them, `git rm -q`s them, commits CHANGELOG plus deletions; PR body names the count.
**Done when:** the release tests (platrelease_world with fragments) pass.

## t3 — release-check rows

**Files:** scripts/release-check.py
**Covers:** AC-132.7, AC-132.8
**Goal:** when the released section is `[Unreleased]`, assemble the fragments into its body; an invalid fragment prints `ERROR: …` and exits 1.

## t4 — guidance and this change's fragment

**Files:** docs/changelog.d/README.md, docs/changelog.d/321-changelog-fragments.added.md, CONTRIBUTING.md, CLAUDE.md,
.github/PULL_REQUEST_TEMPLATE.md, tests/cplat/test_naming.py, tests/cplat/test_spec_agents.py
**Covers:** AC-132.1, AC-132.10, AC-132.13

## t5 — durable changelog and version tests

**Files:** tests/cplat/changelog_support.py and the ten test files listed above
**Covers:** AC-132.11, AC-132.12
**Goal:** keep each test's intent; replace the "first section that mentions spec N" lookup with `changelog_support.section("<version>")`
(115, 116 → 5.1.0; 117, 125 → 5.2.0; 118–121 → 5.4.0; 128, 130 → 5.5.0) and `==` plugin pins with `>=` the shipped version.

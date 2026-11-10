---
spec_id: 168-agent-rules-state-their-reason-and-can
shape: platform
spec_hash: 007bea946ca6
summary: A rule register and `cplat platform rules check` for every prompt rule, the sweep of all plugin prompts, the eval gate on retirements in pr-check, and "Rules to retire" in the weekly retro
tasks:
  - id: t1
    title: promptrules - prompt scanning, register loading, enforcement validation
    files: [scripts/cplat/promptrules.py]
    covers: [AC-168.1, AC-168.2, AC-168.3, AC-168.4, AC-168.5]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t5
    title: The register skeleton - register.yml (baseline, hard-rule table) and its README
    files: [docs/rules/register.yml, docs/rules/README.md]
    covers: [AC-168.4, AC-168.6]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t2
    title: cplat platform rules check
    files: [scripts/cplat/rulescheck.py, scripts/cplat/cplat.py]
    covers: [AC-168.1, AC-168.2, AC-168.3, AC-168.4, AC-168.5, AC-168.6]
    parallel_safe: true
    depends_on: [t1]
    done: true
  - id: t4
    title: Weekly retro - Rules to retire
    files: [scripts/cplat/retro_rules.py, scripts/cplat/retro.py, scripts/cplat/retro_report.py, scripts/cplat/retro_github.py, tests/cplat/retro_world.py]
    covers: [AC-168.8]
    parallel_safe: true
    depends_on: [t1]
    done: true
  - id: t3
    title: pr-check - rules and the eval gate on retired or removed entries
    files: [scripts/cplat/evalgate.py, scripts/cplat/rules_retire.py, scripts/cplat/house_rules.py]
    covers: [AC-168.7]
    parallel_safe: true
    depends_on: [t1, t2]
    done: true
  - id: s1
    title: Sweep - component build and its references
    files: [plugins/component/commands/build.md, plugins/component/references/build-pr.md, plugins/component/references/build-red-rounds.md, plugins/component/references/build-replan.md, plugins/component/references/build-resume.md, plugins/component/references/build-security-red.md, plugins/component/references/build-test-approval.md, plugins/component/references/build-tighten.md, plugins/component/references/build-worktree-fallback.md, plugins/component/references/unit-mode.md, docs/rules/plugins/component/commands/build.yml, docs/rules/plugins/component/references/build-pr.yml, docs/rules/plugins/component/references/build-red-rounds.yml, docs/rules/plugins/component/references/build-replan.yml, docs/rules/plugins/component/references/build-resume.yml, docs/rules/plugins/component/references/build-security-red.yml, docs/rules/plugins/component/references/build-test-approval.yml, docs/rules/plugins/component/references/build-tighten.yml, docs/rules/plugins/component/references/build-worktree-fallback.yml, docs/rules/plugins/component/references/unit-mode.yml]
    covers: [AC-168.1, AC-168.2, AC-168.3, AC-168.5, AC-168.6]
    parallel_safe: true
    depends_on: [t2, t5]
    done: true
  - id: s2
    title: Sweep - component ship and fix and their references
    files: [plugins/component/commands/ship.md, plugins/component/commands/fix.md, plugins/component/references/fix-on-main.md, plugins/component/references/fix-pr.md, plugins/component/references/ship-finish.md, plugins/component/references/ship-gitops.md, plugins/component/references/ship-land-red.md, docs/rules/plugins/component/commands/ship.yml, docs/rules/plugins/component/commands/fix.yml, docs/rules/plugins/component/references/fix-on-main.yml, docs/rules/plugins/component/references/fix-pr.yml, docs/rules/plugins/component/references/ship-finish.yml, docs/rules/plugins/component/references/ship-gitops.yml, docs/rules/plugins/component/references/ship-land-red.yml]
    covers: [AC-168.1, AC-168.2, AC-168.3, AC-168.5, AC-168.6]
    parallel_safe: true
    depends_on: [t2, t5]
    done: true
  - id: s3
    title: Sweep - component spec, plan, check, verify, release
    files: [plugins/component/commands/spec.md, plugins/component/commands/plan.md, plugins/component/commands/check.md, plugins/component/commands/verify.md, plugins/component/commands/release.md, plugins/component/references/spec-from-plan.md, plugins/component/references/spec-list.md, docs/rules/plugins/component/commands/spec.yml, docs/rules/plugins/component/commands/plan.yml, docs/rules/plugins/component/commands/check.yml, docs/rules/plugins/component/commands/verify.yml, docs/rules/plugins/component/commands/release.yml, docs/rules/plugins/component/references/spec-from-plan.yml, docs/rules/plugins/component/references/spec-list.yml]
    covers: [AC-168.1, AC-168.2, AC-168.3, AC-168.5, AC-168.6]
    parallel_safe: true
    depends_on: [t2, t5]
    done: true
  - id: s4
    title: Sweep - small noun commands (component add/new/remove/set, api, cluster, instance, resource)
    files: [plugins/component/commands/add.md, plugins/component/commands/new.md, plugins/component/commands/remove.md, plugins/component/commands/set.md, plugins/api/commands/list.md, plugins/cluster/commands/add.md, plugins/cluster/commands/new.md, plugins/cluster/commands/remove.md, plugins/instance/commands/promote.md, plugins/instance/commands/secret.md, plugins/instance/commands/verify.md, plugins/resource/commands/add.md, plugins/resource/commands/backup.md, plugins/resource/commands/remove.md, plugins/resource/commands/restore.md, plugins/resource/commands/upgrade.md, docs/rules/plugins/component/commands/add.yml, docs/rules/plugins/component/commands/new.yml, docs/rules/plugins/component/commands/remove.yml, docs/rules/plugins/component/commands/set.yml, docs/rules/plugins/api/commands/list.yml, docs/rules/plugins/cluster/commands/add.yml, docs/rules/plugins/cluster/commands/new.yml, docs/rules/plugins/cluster/commands/remove.yml, docs/rules/plugins/instance/commands/promote.yml, docs/rules/plugins/instance/commands/secret.yml, docs/rules/plugins/instance/commands/verify.yml, docs/rules/plugins/resource/commands/add.yml, docs/rules/plugins/resource/commands/backup.yml, docs/rules/plugins/resource/commands/remove.yml, docs/rules/plugins/resource/commands/restore.yml, docs/rules/plugins/resource/commands/upgrade.yml]
    covers: [AC-168.1, AC-168.2, AC-168.3, AC-168.5, AC-168.6]
    parallel_safe: true
    depends_on: [t2, t5]
    done: true
  - id: s5
    title: Sweep - issue and platform commands
    files: [plugins/issue/commands/report.md, plugins/issue/commands/triage.md, plugins/platform/commands/doctor.md, plugins/platform/commands/fleet.md, plugins/platform/commands/release.md, plugins/platform/commands/retro.md, plugins/platform/commands/runs.md, plugins/platform/commands/ui.md, plugins/platform/commands/update.md, docs/rules/plugins/issue/commands/report.yml, docs/rules/plugins/issue/commands/triage.yml, docs/rules/plugins/platform/commands/doctor.yml, docs/rules/plugins/platform/commands/fleet.yml, docs/rules/plugins/platform/commands/release.yml, docs/rules/plugins/platform/commands/retro.yml, docs/rules/plugins/platform/commands/runs.yml, docs/rules/plugins/platform/commands/ui.yml, docs/rules/plugins/platform/commands/update.yml]
    covers: [AC-168.1, AC-168.2, AC-168.3, AC-168.5, AC-168.6]
    parallel_safe: true
    depends_on: [t2, t5]
    done: true
  - id: s6
    title: Sweep - svc agents architect, coder, product-manager, reviewer, tester
    files: [plugins/svc/agents/architect.md, plugins/svc/agents/coder.md, plugins/svc/agents/product-manager.md, plugins/svc/agents/reviewer.md, plugins/svc/agents/tester.md, docs/rules/plugins/svc/agents/architect.yml, docs/rules/plugins/svc/agents/coder.yml, docs/rules/plugins/svc/agents/product-manager.yml, docs/rules/plugins/svc/agents/reviewer.yml, docs/rules/plugins/svc/agents/tester.yml]
    covers: [AC-168.1, AC-168.2, AC-168.3, AC-168.5, AC-168.6]
    parallel_safe: true
    depends_on: [t2, t5]
    done: true
  - id: s7
    title: Sweep - svc agents deployment, migrations, observability, release
    files: [plugins/svc/agents/deployment.md, plugins/svc/agents/migrations.md, plugins/svc/agents/observability.md, plugins/svc/agents/release.md, docs/rules/plugins/svc/agents/deployment.yml, docs/rules/plugins/svc/agents/migrations.yml, docs/rules/plugins/svc/agents/observability.yml, docs/rules/plugins/svc/agents/release.yml]
    covers: [AC-168.1, AC-168.2, AC-168.3, AC-168.5, AC-168.6]
    parallel_safe: true
    depends_on: [t2, t5]
    done: true
  - id: s8
    title: Sweep - svc skill spec-format
    files: [plugins/svc/skills/spec-format/SKILL.md, plugins/svc/skills/spec-format/references/design.md, plugins/svc/skills/spec-format/references/plan.md, plugins/svc/skills/spec-format/references/spec.md, plugins/svc/skills/spec-format/references/testing.md, plugins/svc/skills/spec-format/references/verification.md, docs/rules/plugins/svc/skills/spec-format/SKILL.yml, docs/rules/plugins/svc/skills/spec-format/references/design.yml, docs/rules/plugins/svc/skills/spec-format/references/plan.yml, docs/rules/plugins/svc/skills/spec-format/references/spec.yml, docs/rules/plugins/svc/skills/spec-format/references/testing.yml, docs/rules/plugins/svc/skills/spec-format/references/verification.yml]
    covers: [AC-168.1, AC-168.2, AC-168.3, AC-168.6]
    parallel_safe: true
    depends_on: [t2, t5]
    done: true
  - id: s9
    title: Sweep - svc-go agents
    files: [plugins/svc-go/agents/coder.md, plugins/svc-go/agents/deployment.md, plugins/svc-go/agents/observability.md, plugins/svc-go/agents/release.md, plugins/svc-go/agents/tester.md, docs/rules/plugins/svc-go/agents/coder.yml, docs/rules/plugins/svc-go/agents/deployment.yml, docs/rules/plugins/svc-go/agents/observability.yml, docs/rules/plugins/svc-go/agents/release.yml, docs/rules/plugins/svc-go/agents/tester.yml]
    covers: [AC-168.1, AC-168.2, AC-168.3, AC-168.5, AC-168.6]
    parallel_safe: true
    depends_on: [t2, t5]
    done: true
  - id: s10
    title: Sweep - svc-java agents
    files: [plugins/svc-java/agents/coder.md, plugins/svc-java/agents/deployment.md, plugins/svc-java/agents/observability.md, plugins/svc-java/agents/release.md, plugins/svc-java/agents/tester.md, docs/rules/plugins/svc-java/agents/coder.yml, docs/rules/plugins/svc-java/agents/deployment.yml, docs/rules/plugins/svc-java/agents/observability.yml, docs/rules/plugins/svc-java/agents/release.yml, docs/rules/plugins/svc-java/agents/tester.yml]
    covers: [AC-168.1, AC-168.2, AC-168.3, AC-168.5, AC-168.6]
    parallel_safe: true
    depends_on: [t2, t5]
    done: true
  - id: s11
    title: Sweep - web agents
    files: [plugins/web/agents/coder.md, plugins/web/agents/deployment.md, plugins/web/agents/observability.md, plugins/web/agents/release.md, plugins/web/agents/tester.md, docs/rules/plugins/web/agents/coder.yml, docs/rules/plugins/web/agents/deployment.yml, docs/rules/plugins/web/agents/observability.yml, docs/rules/plugins/web/agents/release.yml, docs/rules/plugins/web/agents/tester.yml]
    covers: [AC-168.1, AC-168.2, AC-168.3, AC-168.5, AC-168.6]
    parallel_safe: true
    depends_on: [t2, t5]
    done: true
  - id: s12
    title: Sweep - shared agents quality and security
    files: [plugins/shared/agents/quality.md, plugins/shared/agents/security.md, docs/rules/plugins/shared/agents/quality.yml, docs/rules/plugins/shared/agents/security.yml]
    covers: [AC-168.1, AC-168.2, AC-168.3, AC-168.5, AC-168.6]
    parallel_safe: true
    depends_on: [t2, t5]
    done: true
  - id: s13
    title: Sweep - system plugin (planner, commands, references)
    files: [plugins/system/agents/planner.md, plugins/system/commands/autonomy.md, plugins/system/commands/new.md, plugins/system/commands/plan.md, plugins/system/commands/restore.md, plugins/system/commands/set.md, plugins/system/commands/ship.md, plugins/system/commands/spec.md, plugins/system/commands/status.md, plugins/system/references/ship-entry.md, plugins/system/references/spec-list.md, docs/rules/plugins/system/agents/planner.yml, docs/rules/plugins/system/commands/autonomy.yml, docs/rules/plugins/system/commands/new.yml, docs/rules/plugins/system/commands/plan.yml, docs/rules/plugins/system/commands/restore.yml, docs/rules/plugins/system/commands/set.yml, docs/rules/plugins/system/commands/ship.yml, docs/rules/plugins/system/commands/spec.yml, docs/rules/plugins/system/commands/status.yml, docs/rules/plugins/system/references/ship-entry.yml, docs/rules/plugins/system/references/spec-list.yml]
    covers: [AC-168.1, AC-168.2, AC-168.3, AC-168.5, AC-168.6]
    parallel_safe: true
    depends_on: [t2, t5]
    done: true
  - id: t6
    title: CI step, docs, plugin versions and changelog
    files: [.github/workflows/ci.yml, scripts/ci-local.sh, docs/AGENTS.md, CLAUDE.md, docs/changelog.d/168-agent-rules-reasons.added.md, .claude-plugin/marketplace.json, plugins/api/.claude-plugin/plugin.json, plugins/cluster/.claude-plugin/plugin.json, plugins/component/.claude-plugin/plugin.json, plugins/instance/.claude-plugin/plugin.json, plugins/issue/.claude-plugin/plugin.json, plugins/platform/.claude-plugin/plugin.json, plugins/resource/.claude-plugin/plugin.json, plugins/shared/.claude-plugin/plugin.json, plugins/svc/.claude-plugin/plugin.json, plugins/svc-go/.claude-plugin/plugin.json, plugins/svc-java/.claude-plugin/plugin.json, plugins/system/.claude-plugin/plugin.json, plugins/web/.claude-plugin/plugin.json]
    covers: [AC-168.6]
    parallel_safe: false
    depends_on: [t3, t4, s1, s2, s3, s4, s5, s6, s7, s8, s9, s10, s11, s12, s13]
    done: true
human_steps:
  - "Before merging the PR, in a Claude session on its final commit: run `cplat platform runs benchmark quick-task --plugins plugins --reset-first` and `cplat platform runs benchmark build --plugins plugins --reset-first`, then `cplat platform pr-check --title \"<title>\" --body-file <body> --fix`, which writes the passing run ids into the retired register entries; commit and push that change (AC-168.7). The release gate of spec 151 needs the same two runs."
---

# Plan — 168 Agent rules state their reason and can retire

Contract: [design.md](design.md). Levels: t1, t5 → t2, t4 → t3 and the sweep s1–s13 → t6. The sweep tasks own
disjoint prompt files and the register file of each (`docs/rules/plugins/<p>/<kind>/<path>.yml`); none of them edits
`register.yml`, a test, a plugin version or the changelog.

## t1 — promptrules - prompt scanning, register loading, enforcement validation

**Files:** scripts/cplat/promptrules.py
**Covers:** AC-168.1, AC-168.2, AC-168.3, AC-168.4, AC-168.5
**Goal:** the pure building blocks every other task uses: turn a prompt into sentences with rule, scope, reason,
condition and marker facts; load the register; validate an enforcement. Contract: design.md *Register files* and
*Prompt scanning*, verbatim.

**Implementation notes:**
- Module constants `RULE_WORDS`, `REASON_WORDS`, `CONDITIONS`, `MARKER`, `STATEMENT`, `CLASSES`, `REGISTER =
  "docs/rules/register.yml"`, `ENTRIES = "docs/rules/plugins"`; reuse `evalgate.PROMPT` for prompt paths.
- `sentences()` follows steps 1–10 of *Prompt scanning* exactly; keep a line map while joining block lines so each
  sentence reports the line it starts on. Mask inline code spans for detection and splitting, keep raw text for
  matching.
- `reason_clause(scope)`: longest clause with at least 3 words (refs and link targets removed), else `None`; expose
  the word count helper too, so the check can tell `no-reason` from `short-reason`.
- `load_register(root)` returns the hard table, the baseline and every entries file (keyed by prompt path) with each
  entry's line (`yaml.compose` marks); schema errors are collected as data for the check, an unreadable YAML raises
  `RegisterError(file, line, message)`. `load_entries(rel, text)` parses one entries file from text (pr-check reads
  the base side with `git show`).
- `enforcement_error(value, root)`: `cplat …` against `cplat.NOUNS` / `cplat.PLUMBING` (import `cplat` lazily);
  `ci:<job>` against `workflow_jobs(root)`, which reads job ids and their `name:` under `jobs:` with a line pattern in
  `.github/workflows/*.yml` and `templates/*/.github/workflows/*.yml{,.jinja}`.
- `prompt_bytes(root)`: the byte sizes of every prompt file summed; `is_tombstone(text)`: frontmatter `moved-to:`.
- No CLI and no printing; standard library plus `yaml`.

**Done when:** the acceptance tests of AC-168.1 to AC-168.5 that exercise scanning and register parsing pass (with
t2 the rest of them).

## t5 — The register skeleton - register.yml (baseline, hard-rule table) and its README

**Files:** docs/rules/register.yml, docs/rules/README.md
**Covers:** AC-168.4, AC-168.6
**Goal:** the central register file the check and the sweep rely on.

**Implementation notes:**
- `schema: 1`; `baseline.commit` = `git merge-base main HEAD` at the start of the build (the feature branch base);
  `baseline.prompt_bytes` = the sum of the blob sizes of every path matching `evalgate.PROMPT` at that commit
  (`git ls-tree -r -l <commit> -- plugins`). Do not measure the working tree: other tasks are already changing it.
- `hard:` = the 13 keys of design.md *Hard rules*, with exactly the enforcement and source given there
  (`enforced_by` for the five with a command or job, `intentional_prose_rule` with the given reason for the others).
- `docs/rules/README.md` (for maintainers, not loaded by agents): what the register is and where entries live; the
  classes and the rewriting rules of design.md *The sweep*, shortened; how to add a rule (entry + reason, check with
  `cplat platform rules check --only <file>`); how to retire one (mark it `retired` with date, reason, enforcement;
  run the two benchmarks; `cplat platform pr-check --fix` writes `benchmark_runs`); that the retro proposes
  retirements under "Rules to retire". Relative links only (check-links).

**Done when:** the YAML parses, it has 13 `hard:` keys and a baseline; the acceptance tests that read the real
`register.yml` (AC-168.4 ceiling and enforcement, AC-168.6 baseline) pass once t2 is in.

## t2 — cplat platform rules check

**Files:** scripts/cplat/rulescheck.py, scripts/cplat/cplat.py
**Covers:** AC-168.1, AC-168.2, AC-168.3, AC-168.4, AC-168.5, AC-168.6
**Goal:** the check of design.md *`cplat platform rules check`*: every failure kind of its table, the text and JSON
output, `--only`, exit codes.

**Implementation notes:**
- `cplat.py`: `NOUNS["platform"]["rules"] = ("rulescheck", [])`, and a docstring line `cplat platform rules check
  [--only PATH …] [--json]   every prompt rule classified, reasoned and marked (spec 168)`.
- `rulescheck.main(argv)`: subcommand `check` (argparse like `evalgate.main`); `--repo` default `.`; anything else
  exits 2 with usage.
- `check(root, only=None) -> Result`: scan every prompt (or the `--only` ones), match entries per file (retired
  entries never match), then the per-sentence checks (no-entry, ambiguous, reason, condition, marker), per-entry
  checks (stale, retired-present, bad-retired, unknown-hard, enforcement), per-file statement checks (non-tombstone
  `agents/*.md` and `commands/*.md`), and, without `--only`, the global checks (too-many-hard, bytes).
- An entries file whose prompt no longer exists: its non-retired entries are `stale-entry`.
- Failures sorted by file and line; the message of `condition` contains "state the purpose instead"; `no-statement`
  names `promptrules.STATEMENT`.
- Counts as in the JSON example; the OK line as in the design.

**Done when:** the acceptance tests of AC-168.1 to AC-168.5 pass; the AC-168.6 tests that run the check on the real
repo pass only after the sweep (s1–s13).

## t4 — Weekly retro - Rules to retire

**Files:** scripts/cplat/retro_rules.py, scripts/cplat/retro.py, scripts/cplat/retro_report.py, scripts/cplat/retro_github.py, tests/cplat/retro_world.py
**Covers:** AC-168.8
**Goal:** design.md *Retro: "Rules to retire"*: the section in `report.json`, both renderings and the posted issue.

**Implementation notes:**
- `retro_rules.section(root, records, *, week, issues)` and `render(section)` exactly as designed; pure apart from
  reading the register and prompts through `promptrules`. A missing or unreadable register gives no entries.
- `retro.build_report`: read 28 days (from the Monday of the week three weeks before the covered week to the end of
  the covered week); the figures keep using the covered and the previous week through `retro_report._split`.
  Pass `rules_to_retire=retro_rules.section(core.PLATFORM_ROOT, records, week=week, issues=lambda ns:
  tracker.issue_states(repo, ns))`.
- `retro_report.build(..., rules_to_retire=None)` stores it under `rules_to_retire` when given; `_render` appends
  `retro_rules.render(...)` right after the proposals section, in the private and the public rendering (the public
  one is scrubbed as today, AC-090.11). A report without the key renders no section. The evidence index is unchanged.
- `retro_github.RetroTracker.issue_states` and `GhRetroTracker.issue_states` (`gh api repos/<repo>/issues/<n>`, an
  unreadable number left out, never raised).
- `tests/cplat/retro_world.py`: `FakeRetroTracker.issue_states` from the issues it holds, so the existing retro tests
  keep running (a test helper, no test changes).
- The retro writes no prompt or register file.

**Done when:** the AC-168.8 acceptance tests pass and the existing retro tests (`test_retro_*.py`) still pass.

## t3 — pr-check - rules and the eval gate on retired or removed entries

**Files:** scripts/cplat/evalgate.py, scripts/cplat/rules_retire.py, scripts/cplat/house_rules.py
**Covers:** AC-168.7
**Goal:** design.md *`cplat platform pr-check`*: the `rules` and `rules-retired` rules and `--fix`.

**Implementation notes:**
- `evalgate.verdict_runs(...)` returns `(failures, {workflow: run_id})`; `verdict` delegates to it, so
  `test_151_eval_gate.py` stays green.
- `rules_retire.check(repo, base, fix=False) -> list[str]`: base entries via `git ls-tree -r --name-only <base> --
  docs/rules/plugins` and `git show`, parsed with `promptrules.load_entries`; head entries from the working tree;
  the changed set, the gate call and the problems exactly as designed. Look up `evalgate._records` at call time.
- `--fix`: insert `benchmark_runs: [<ids>]` under each changed retired entry lacking them (indent of its `id:` key);
  report the entries written as `rules-retired: wrote benchmark_runs into <key>` on stdout, not as problems.
- `house_rules`: `RULES` gains `"rules"` and `"rules-retired"` (not `PR_OPEN_RULES`); both are skipped when
  `docs/rules/register.yml` is absent, so the spec 150 fixture repo still passes; `rules` lists at most 10 check
  failures, then the count; the OK line names the two new rules.

**Done when:** the AC-168.7 acceptance tests pass and `test_150_pr_check.py` and `test_151_eval_gate.py` still pass.

## s1 — Sweep - component build and its references

**Files:** plugins/component/commands/build.md, plugins/component/references/{build-pr,build-red-rounds,build-replan,build-resume,build-security-red,build-test-approval,build-tighten,build-worktree-fallback,unit-mode}.md and their `docs/rules/plugins/component/…/*.yml`
**Covers:** AC-168.1, AC-168.2, AC-168.3, AC-168.5, AC-168.6
**Goal:** classify and rewrite every rule sentence of these prompts per design.md *The sweep* (contract: *The sweep*
and *Prompt scanning*, verbatim), with one register file per prompt.

**Implementation notes:**
- Phase 3 step 3 is the spec's example of a condition list: state the purpose of the tester and security passes
  instead of "only when …".
- Hard rules here: `acceptance-tests-fixed` (Phase 2 step 2, coder prompt, Rules), `conflicts-not-resolved-by-hand`,
  `only-approved-specs-built`, `push-only-through-pr-open`, `no-hook-bypass`, `gitops-owns-the-cluster` (Phase 5),
  `issue-filing-needs-consent` (closing note).
- Many sentences carry only an issue number ("(#496)", "(#367)", "(#501)"): give them a real reason or retire them
  when a `cplat` command now does the work; refs go to `source`.
- Pinned by existing tests (keep verbatim): test_lean_prompts (the reference pointers, `build.md` below 19912 bytes,
  the keys of each reference), test_165_test_problems, test_160_lint_suppressions, test_build_replan_docs,
  test_build_parallel_501, test_476.
- Add `STATEMENT` once to `build.md` (references need none).

**Done when:** `cplat platform rules check --only <each file>` passes for every owned prompt; the owned prompts total
at most their bytes at `BASE_REF`; `cplat quiet test-fast` shows no newly failing existing test.

## s2 — Sweep - component ship and fix and their references

**Files:** plugins/component/commands/{ship,fix}.md, plugins/component/references/{fix-on-main,fix-pr,ship-finish,ship-gitops,ship-land-red}.md and their register files
**Covers:** AC-168.1, AC-168.2, AC-168.3, AC-168.5, AC-168.6
**Goal:** as s1, for these prompts (contract: design.md *The sweep* and *Prompt scanning*).

**Implementation notes:**
- Hard rules likely here: `push-only-through-pr-open`, `acceptance-tests-fixed`, `issue-filing-needs-consent`,
  `no-hook-bypass`.
- Pinned: test_lean_prompts (pointers and keys of `ship-*.md`, `fix-*.md`; `ship.md` < 12106 and `fix.md` < 7961
  bytes), test_smoke_091_ship, test_ship_checks, test_476.
- `STATEMENT` once in `ship.md` and `fix.md`.

**Done when:** as s1.

## s3 — Sweep - component spec, plan, check, verify, release

**Files:** plugins/component/commands/{spec,plan,check,verify,release}.md, plugins/component/references/{spec-from-plan,spec-list}.md and their register files
**Covers:** AC-168.1, AC-168.2, AC-168.3, AC-168.5, AC-168.6
**Goal:** as s1, for these prompts.

**Implementation notes:**
- Hard rules likely here: `user-decides-approval`, `only-approved-specs-built`, `release-never-tags-or-commits-main`
  where `release.md` says so, `issue-filing-needs-consent`.
- Pinned: test_adr_numbers_337 (`cplat spec adr-next`, `ADR_NEXT` in `plan.md`), test_lean_prompts (`spec.md` <
  10976 bytes, `spec-*.md` keys), test_149_decide_by_default, test_141_no_new_questions, test_release_target_138,
  test_476.
- `STATEMENT` once in each command.

**Done when:** as s1.

## s4 — Sweep - small noun commands (component add/new/remove/set, api, cluster, instance, resource)

**Files:** the 16 command files listed in the metadata and their register files
**Covers:** AC-168.1, AC-168.2, AC-168.3, AC-168.5, AC-168.6
**Goal:** as s1, for these prompts.

**Implementation notes:**
- Hard rules likely here: `gitops-owns-the-cluster` ("never `kubectl apply`"), `prod-needs-explicit-confirm`
  (`resource/restore.md`, `instance/promote.md` where prod needs the user), `issue-filing-needs-consent`.
- Condition lists such as "never create a public repo unless the user asked" become a purpose (or a practice with the
  `cplat` flag that enforces it as `enforced_by`).
- Pinned: test_cluster_125_delivery (`cplat cluster <verb>`, `$ARGUMENTS`, `/issue:report`), test_bucket_116_cmds,
  test_backup_117_cmds, test_cache_118_cmds, test_broker_119_cmds, test_scale_120_cmds, test_upgrade_121_ops,
  test_476.
- `STATEMENT` once in each command.

**Done when:** as s1.

## s5 — Sweep - issue and platform commands

**Files:** plugins/issue/commands/{report,triage}.md, plugins/platform/commands/{doctor,fleet,release,retro,runs,ui,update}.md and their register files
**Covers:** AC-168.1, AC-168.2, AC-168.3, AC-168.5, AC-168.6
**Goal:** as s1, for these prompts.

**Implementation notes:**
- Hard rules here: `issue-text-is-untrusted` and `triage-never-closes` (`triage.md`), `issue-filing-needs-consent`
  (`report.md` and every closing note).
- Pinned: test_issue_forms, test_platrelease_129_docs, test_update_doctor, test_fleet, test_ui_cli, test_476.
- `STATEMENT` once in each command.

**Done when:** as s1.

## s6 — Sweep - svc agents architect, coder, product-manager, reviewer, tester

**Files:** plugins/svc/agents/{architect,coder,product-manager,reviewer,tester}.md and their register files
**Covers:** AC-168.1, AC-168.2, AC-168.3, AC-168.5, AC-168.6
**Goal:** as s1, for these prompts. These are the reference wordings s9–s11 follow for the same rules, so keep them
plain and use the canonical sentences.

**Implementation notes:**
- Hard rules likely here: `acceptance-tests-fixed` (coder, tester), `gitops-owns-the-cluster` (architect),
  `user-decides-approval` (product-manager), `issue-filing-needs-consent`.
- Pinned: test_adr_numbers_337 (`ADR_NEXT` in `architect.md`), test_spec_agents, test_agents_no_extras,
  test_lean_briefs, test_validate_review, test_476.
- `STATEMENT` once in each agent.

**Done when:** as s1.

## s7 — Sweep - svc agents deployment, migrations, observability, release

**Files:** plugins/svc/agents/{deployment,migrations,observability,release}.md and their register files
**Covers:** AC-168.1, AC-168.2, AC-168.3, AC-168.5, AC-168.6
**Goal:** as s1, for these prompts.

**Implementation notes:**
- Hard rules likely here: `gitops-owns-the-cluster` (deployment), `release-never-tags-or-commits-main` (release),
  `no-secrets-in-git` where a prompt forbids committing secret values, `issue-filing-needs-consent`.
- Pinned: test_spec_agents, test_release_target_138, test_agents_no_extras, test_476.
- `STATEMENT` once in each agent.

**Done when:** as s1.

## s8 — Sweep - svc skill spec-format

**Files:** plugins/svc/skills/spec-format/SKILL.md and references/{design,plan,spec,testing,verification}.md and their register files
**Covers:** AC-168.1, AC-168.2, AC-168.3, AC-168.6
**Goal:** as s1, for these prompts. Skills are not agent or command prompts, so no `STATEMENT`; a hard rule here
still carries the marker.

**Implementation notes:**
- Mostly practices (format rules); the plan rules ("`parallel_safe`: `true` only when …", "Never remove in the same
  release that adds") are condition lists to restate as purposes.
- Pinned: test_spec_agents, test_smoke_091_spec, test_spec_driven, test_149_decide_by_default.

**Done when:** as s1.

## s9 — Sweep - svc-go agents

**Files:** plugins/svc-go/agents/{coder,deployment,observability,release,tester}.md and their register files
**Covers:** AC-168.1, AC-168.2, AC-168.3, AC-168.5, AC-168.6
**Goal:** as s1, for these prompts; the same rule as in an `svc` agent gets the same class and, where the text is
shared, the same wording (canonical sentences; s6 and s7 run in parallel, so follow the design, not their files).

**Implementation notes:**
- Hard rules likely here: `acceptance-tests-fixed`, `gitops-owns-the-cluster`, `release-never-tags-or-commits-main`,
  `no-secrets-in-git`, `issue-filing-needs-consent`.
- Pinned: test_spec_agents, test_agents_no_extras, test_476.
- `STATEMENT` once in each agent.

**Done when:** as s1.

## s10 — Sweep - svc-java agents

**Files:** plugins/svc-java/agents/{coder,deployment,observability,release,tester}.md and their register files
**Covers:** AC-168.1, AC-168.2, AC-168.3, AC-168.5, AC-168.6
**Goal:** as s9, for the Java agents.

**Implementation notes:**
- As s9; the POM rule ("never change the parent version … without being asked") is a practice with a purpose.

**Done when:** as s1.

## s11 — Sweep - web agents

**Files:** plugins/web/agents/{coder,deployment,observability,release,tester}.md and their register files
**Covers:** AC-168.1, AC-168.2, AC-168.3, AC-168.5, AC-168.6
**Goal:** as s9, for the web agents.

**Implementation notes:**
- As s9; the page-scope assertion rule of the tester (#478) is an experience rule with `source: "#478"`.

**Done when:** as s1.

## s12 — Sweep - shared agents quality and security

**Files:** plugins/shared/agents/{quality,security}.md and their register files
**Covers:** AC-168.1, AC-168.2, AC-168.3, AC-168.5, AC-168.6
**Goal:** as s1, for these prompts.

**Implementation notes:**
- Hard rules likely here: `acceptance-tests-fixed` (quality touches no acceptance test beyond a lint suppression),
  `no-secrets-in-git`, `issue-filing-needs-consent`.
- Security's "Always go through devbox" and "never run `detect-secrets scan` by hand" are practices with their
  purpose (CI parity) in the sentence.
- Pinned: test_160_lint_suppressions, test_ci_gates, test_spec_agents, test_476.
- `STATEMENT` once in each agent.

**Done when:** as s1.

## s13 — Sweep - system plugin (planner, commands, references)

**Files:** plugins/system/agents/planner.md, plugins/system/commands/{autonomy,new,plan,restore,set,ship,spec,status}.md, plugins/system/references/{ship-entry,spec-list}.md and their register files
**Covers:** AC-168.1, AC-168.2, AC-168.3, AC-168.5, AC-168.6
**Goal:** as s1, for these prompts.

**Implementation notes:**
- Hard rules likely here: `user-decides-approval` (`spec.md`), `gitops-owns-the-cluster` ("never `kubectl apply`"),
  `push-only-through-pr-open` where the spec push is described, `prod-needs-explicit-confirm` (`restore.md`),
  `issue-filing-needs-consent`.
- Pinned: test_476 (`ship.md` keeps "output read whole (never piped into `grep`, `head` or `tail`" and no
  "Prompt: *"), test_155_repo_sessions, test_staging_093_setting, test_system_set, test_141_no_new_questions.
- `STATEMENT` once in the planner and each command.

**Done when:** as s1.

## t6 — CI step, docs, plugin versions and changelog

**Files:** .github/workflows/ci.yml, scripts/ci-local.sh, docs/AGENTS.md, CLAUDE.md, docs/changelog.d/168-agent-rules-reasons.added.md, .claude-plugin/marketplace.json, the 13 plugin.json files listed in the metadata
**Covers:** AC-168.6
**Goal:** the check runs in the platform's CI and locally, passes on the finished branch, and the change is
documented and versioned.

**Implementation notes:**
- `ci.yml`, job `validate-shapes`: a step `every prompt rule is classified, reasoned and marked (spec 168)` running
  `uv run scripts/cplat/cplat.py platform rules check` (after the link check). `ci-local.sh`: the same as a `step`.
- Run `cplat platform rules check` on the whole repo: it must pass (all sweep groups together, bytes under the
  baseline, 13 hard rules). A failure in a sweep file is reported back, not fixed here.
- `docs/AGENTS.md`: a short section "Rules in prompts" (classes, `**Hard rule:**`, the statement, the register, the
  check, retirement through the retro and pr-check), linking ADR-091 and `docs/rules/README.md`.
- `CLAUDE.md`, Conventions: one bullet: a rule added to a prompt needs a register entry and a reason; `cplat platform
  rules check` must pass.
- Minor version bump in `plugin.json` and `.claude-plugin/marketplace.json` for api, cluster, component, instance,
  issue, platform, resource, shared, svc, svc-go, svc-java, system, web (their prompts changed).
- Changelog fragment per `docs/changelog.d/README.md`: bold summary ending `(spec 168).`, what changed for users
  (rules state their reason, hard rules are marked, agents name a departure from a practice in their report), and
  "Update the plugins (`/plugin marketplace update`)".

**Done when:** `cplat platform rules check` passes on the branch, `devbox run validate` passes, the AC-168.6
acceptance tests pass, and `cplat platform pr-check` reports no problem other than the `rules-retired` benchmark ids
(the human step).

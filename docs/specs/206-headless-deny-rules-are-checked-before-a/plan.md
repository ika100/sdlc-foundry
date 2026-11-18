---
spec_id: 206-headless-deny-rules-are-checked-before-a
shape: platform
spec_hash: e2f1e4160810
summary: An unattended run checks its refused rules against a fixed must-allow and must-refuse sample before the first session; gh api merge rules narrowed
tasks:
  - id: t1
    title: Add denyrules module (deny matcher, samples, check, correction) and narrow the gh api merge rule
    files: [scripts/cplat/denyrules.py, scripts/cplat/preflight.py, tests/cplat/test_184_allowlist.py]
    covers: [AC-206.3, AC-206.4, AC-206.5, AC-206.6, AC-206.7]
    parallel_safe: true
    depends_on: []
  - id: t2
    title: Run the deny-rules check first in the preflight of headless
    files: [scripts/cplat/preflight.py, scripts/cplat/headless.py]
    covers: [AC-206.1, AC-206.2, AC-206.4, AC-206.5]
    parallel_safe: false
    depends_on: [t1]
  - id: t3
    title: Document the deny-rules preflight and add the changelog fragment
    files: [docs/unattended-delivery.md, docs/changelog.d/206-deny-rules-checked-before-a-run.fixed.md]
    covers: [AC-206.4]
    parallel_safe: true
    depends_on: []
---

# Plan — 206 Headless deny rules are checked before a session starts

Contract and the exact algorithms are in [design.md](design.md). No prompt, plugin or template changes, so the plan has
no plugin version bump and no rules-register entry.

## t1 — Add denyrules module (deny matcher, samples, check, correction) and narrow the gh api merge rule

**Files:** scripts/cplat/denyrules.py, scripts/cplat/preflight.py, tests/cplat/test_184_allowlist.py
**Covers:** AC-206.3, AC-206.4, AC-206.5, AC-206.6, AC-206.7
**Goal:** a pure, offline module that can tell whether a list of refused rules over-matches or under-matches the run's
commands for a default branch and the run branches, and that says how to fix it. The generated list stops refusing reads
of `mergeable` and `mergeStateStatus`.

**Implementation notes:**
- Move `refused_rules` from `preflight.py` to `denyrules.py`. Replace `Bash(gh api *merge*)` in place with
  `Bash(gh api */pulls/*/merge*)`, `Bash(gh api */merges*)`, `Bash(gh api *mutation*merge*)`. In `preflight.py`, add
  `from denyrules import refused_rules` so that `preflight.refused_rules is denyrules.refused_rules`. `_self_check` keeps
  working unchanged.
- `must_allow(default, branch)` and `must_refuse(default, branch)`: the sample texts of AC-206.1 and AC-206.2, in spec order.
- `refuses(rule, command)`: the glob of the design (`:*` prefix, `*` matching any text, trailing ` *` matching the bare
  command). Split compound commands outside quotes, strip leading assignments and the wrappers `timeout`, `time`, `nice`,
  `nohup` and `stdbuf` with their options. Use a small scanner that keeps character offsets, so the stripped text is the
  original substring. Do not use `shlex.join`.
- `problem(rules, default, branches)` and `correction(rule, rules, default, branches)`, exactly as the design specifies
  them: check order, line texts and candidate-edit order.
- `denyrules.py` imports no cplat module except stdlib, so that `preflight` can import it without a cycle.
- `tests/cplat/test_184_allowlist.py`: in `REFUSED_BEFORE`, replace `"Bash(gh api *merge*)"` with the three new rules,
  with a comment that spec 206 (AC-206.6) changed the list on purpose. That test compares the list exactly, so it must
  change with the rule.
- Leave `preflight.matches` unchanged (design, Decisions).

**Done when:** the acceptance tests for AC-206.3, AC-206.6 and AC-206.7, and the unit-level parts of AC-206.4 and
AC-206.5 (detail lines from `problem`), pass for `main`, `master`, `trunk` and `develop` with component and system
branches. `test_184_allowlist.py`, `test_preflight_131.py`, `test_179_allowlist.py`, `test_156_system_benchmark.py` and
`test_186_plan_merge.py` stay green.

## t2 — Run the deny-rules check first in the preflight of headless

**Files:** scripts/cplat/preflight.py, scripts/cplat/headless.py
**Covers:** AC-206.1, AC-206.2, AC-206.4, AC-206.5
**Goal:** an unattended `/component:build`, `/component:ship` or `/system:ship` whose refused rules fail the check stops
before any session with `preflight failed: deny-rules: …` and exit 1.

**Implementation notes:**
- `preflight.check(repo, command, specs, targets=None, deny=None)`: compute
  `default = default_branch(repo)` and `branches = ["feature/x" if b == "feature/*" else b for b in branches_of(command, specs)]`,
  with `deny` defaulting to `refused_rules(default)`. When `denyrules.problem(deny, default, branches)` returns a detail,
  return `Failure("deny-rules", detail)` before `_no_allowlist`.
- `headless._main`: pass `deny=deny` to `preflight.check`. The existing failure path already prints the line, records
  reason `preflight failed: deny-rules`, starts no session and exits 1. `stop_of` needs no change.
- Headless module docstring: the preflight also checks the refused rules against the run's commands (one clause).
- `check_repo` stays unchanged.

**Done when:** the acceptance tests for AC-206.1, AC-206.2, AC-206.4 and AC-206.5 pass through `cplat headless`, using
the fake world of `test_headless_131.py` (no session is started and the fake claude is never called). The existing
`test_headless_131.py`, `test_171_preflight.py` and `test_preflight_131.py` stay green.

## t3 — Document the deny-rules preflight and add the changelog fragment

**Files:** docs/unattended-delivery.md, docs/changelog.d/206-deny-rules-checked-before-a-run.fixed.md
**Covers:** AC-206.4
**Goal:** users learn about the new preflight category and what to do about it.

**Implementation notes:**
- `docs/unattended-delivery.md`, after the preflight paragraph of "Unit sessions and the run allowlist": the run first
  checks its refused rules against the commands it needs and the commands it must never run. A failure prints
  `preflight failed: deny-rules: …` with the corrected rule (`use: …`) or the missing rule (`add: …`). A `gh api` read of a
  pull request's `mergeable` or `mergeStateStatus` is no longer refused. Do not use spec numbers in the guide.
- Fragment in the style of the existing fragments (for example `209-…fixed.md`): a bold one-sentence summary ending in
  `(spec 206).`, then the W46 stalls (a refused rule that matched a read-only `gh api` query) and what happens now.

**Done when:** `devbox run quality` (link check, `check-docs.py`, `release-check.py rows`) passes.

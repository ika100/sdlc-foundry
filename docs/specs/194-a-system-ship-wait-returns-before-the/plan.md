---
spec_id: 194-a-system-ship-wait-returns-before-the
shape: platform
spec_hash: 42bf68fe212e
summary: "`cplat system ship next --wait` ends within its timeout and reports progress with `WAIT:` (exit 0); `/system:ship` escalates only after three `TIMEOUT:` in a row"
tasks:
  - id: t1
    title: "`next --wait` keeps a fixed deadline and returns `WAIT:` on progress"
    files: [scripts/cplat/shipwait.py, scripts/cplat/appship.py, scripts/cplat/waits.py, tests/cplat/test_148_transient_errors.py, docs/changelog.d/194-system-ship-wait-returns.changed.md]
    covers: [AC-194.1, AC-194.2, AC-194.3]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t2
    title: "`/system:ship` reruns on `WAIT:` and escalates after three `TIMEOUT:` in a row"
    files: [plugins/system/commands/ship.md, docs/rules/plugins/system/commands/ship.yml, docs/adr/082-a-coordinator-waits-with-a-cplat-wait-never-a-polling-loop.md, plugins/system/.claude-plugin/plugin.json, .claude-plugin/marketplace.json]
    covers: [AC-194.4]
    parallel_safe: true
    depends_on: []
    done: true
---

# Plan — 194 A system ship wait returns before the Bash limit

The contract is [design.md](design.md). The two tasks share no file and are independent: t2 changes prompt text and
quotes the `WAIT:`/`TIMEOUT:` words the contract fixes, so it does not wait for the code.

## t1 — `next --wait` keeps a fixed deadline and returns `WAIT:` on progress

**Files:** scripts/cplat/shipwait.py, scripts/cplat/appship.py, scripts/cplat/waits.py, tests/cplat/test_148_transient_errors.py, docs/changelog.d/194-system-ship-wait-returns.changed.md
**Covers:** AC-194.1, AC-194.2, AC-194.3
**Goal:** one `next --wait` call ends no later than T + one poll interval after its start; progress during the call turns
the end into the `wait` action plus the `WAIT:` line with exit 0, no progress into today's `TIMEOUT:` with exit 2.

**Implementation notes:**
- `shipwait.next_wait`: `begin` is set once and never reset; remove `PROGRESS_CAP` and `first`. A changed mark or a
  `sched.check_session` line sets `progressed = True` instead of resetting `begin` (design.md, pseudocode).
- At the deadline: `progressed` → return `(waits.REACHED, action, [WAIT line])` with the exact line
  `WAIT: repos still running, progress in the last <int(T)>s; run the same wait again`; otherwise the `TIMEOUT:` return as today.
- Keep `if ended: continue` and the `min(interval, left)` sleep: a begun poll completes (A1), the reached path is unchanged (spec 186).
- `appship._next_wait`: when `action` is not None, `show_next(action, ns.json)`, then any `lines` to stderr with
  `--json` and to stdout without it; result word `progress` when the returned action is `wait`, else `waits.RESULTS[code]`.
- `waits.record`: an own run finishes `done` for result `reached` or `progress` (other waits never return `progress`).
- Update the `shipwait.py` module docstring (`next --wait` line: exit 0 `WAIT:` on progress, exit 2 TIMEOUT without).
- `tests/cplat/test_148_transient_errors.py`: remove the three `# AC-148.7` tests and their section header (AC-148.7 is
  superseded by AC-194.1; the first of them asserts the old extension and fails after this change). Keep the `sw` fixture
  only if another test uses it.
- Changelog fragment (`changed`), in the README's style: bold summary ending `(#NNN).` with the PR number, what was wrong
  (the wait ran up to ~54 min, past the 10-minute Bash limit, and was moved to the background) and what happens now.

**Done when:** the acceptance tests for AC-194.1–194.3 pass, `devbox run test-fast` is green (no test still asserts the
AC-148.7 extension), and `cplat spec check` passes.

## t2 — `/system:ship` reruns on `WAIT:` and escalates after three `TIMEOUT:` in a row

**Files:** plugins/system/commands/ship.md, docs/rules/plugins/system/commands/ship.yml, docs/adr/082-a-coordinator-waits-with-a-cplat-wait-never-a-polling-loop.md, plugins/system/.claude-plugin/plugin.json, .claude-plugin/marketplace.json
**Covers:** AC-194.4
**Goal:** the `action: wait` bullet runs a `WAIT:` (exit 0) result again as the same wait and escalates with cause
`environment` only after three `TIMEOUT:` results in a row, a `WAIT:` between them starting the count again.

**Implementation notes:**
- Rewrite the `On exit 2 (`TIMEOUT:`, spec 148) …` sentence of the `action: wait` bullet as design.md, "`/system:ship`
  rule" says, with a reason clause of at least 3 words; no `only when`/`unless`/`except` (rule 2 of `docs/rules/README.md`).
- Keep `cplat system ship next --wait`, `cplat component ship wait`, `polling loop` and `cause `environment`` in the file
  (`tests/cplat/test_143_waits_docs.py`); the `land` bullet keeps its own "exit 2 … at most twice" rule unchanged.
- The file must not grow (rule 6): drop the descriptive spec-155 sentence and the `(spec 148)` reference to pay for it.
- Register: add `R15` to `docs/rules/plugins/system/commands/ship.yml`, `text` a verbatim quote of the new rule sentence,
  `class: practice`, `source: spec 194`.
- ADR-082: add under the Status line an `**Amended by:**` line linking spec 194's design.md (`system ship next --wait`
  ends within its timeout: progress returns `WAIT:` with exit 0, the coordinator escalates after three `TIMEOUT:` in a row).
- Bump the system plugin 1.18.0 → 1.18.1 in its `plugin.json` and in `.claude-plugin/marketplace.json`.

**Done when:** the acceptance test for AC-194.4 passes, `cplat platform rules check` passes (register entry, no growth),
`devbox run validate` is green and `tests/cplat/test_143_waits_docs.py` still passes.

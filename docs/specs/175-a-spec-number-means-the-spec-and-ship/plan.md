---
spec_id: 175-a-spec-number-means-the-spec-and-ship
shape: platform
spec_hash: 1164b4541406
summary: Dispatcher steering resolves a bare number to the spec or open issue it names (refusing both or neither, exit 2) and prints what it acted on; ship pr fills {{CLOSES}} like pr open and refuses a body that keeps it
tasks:
  - id: t1
    title: Steering items resolve to a spec or an open issue and say what they acted on
    files: [scripts/cplat/dispatch_items.py, scripts/cplat/dispatch_state.py, scripts/cplat/dispatch.py, tests/cplat/test_dispatch_state.py, docs/dispatch.md]
    covers: [AC-175.1, AC-175.2, AC-175.3]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t2
    title: ship pr fills the closing lines like pr open and refuses a body that keeps the placeholder
    files: [scripts/cplat/pr_open.py, scripts/cplat/ship.py, docs/changelog.d/175-a-spec-number-means-the-spec.fixed.md]
    covers: [AC-175.4, AC-175.5]
    parallel_safe: true
    depends_on: []
    done: true
---

# Plan — 175 A spec number means the spec and ship PRs close their issues

Contract: [design.md](design.md) ("Steering items", "Ship PR body"). The two tasks share no file and run at once.

## t1 — Steering items resolve to a spec or an open issue and say what they acted on

**Files:** scripts/cplat/dispatch_items.py, scripts/cplat/dispatch_state.py, scripts/cplat/dispatch.py, tests/cplat/test_dispatch_state.py, docs/dispatch.md
**Covers:** AC-175.1, AC-175.2, AC-175.3
**Goal:** `skip`, `prioritize` and `resume <item>` act on what the item names under the rule of design.md "Steering items", print
`<verb>: spec <id>` / `<verb>: issue #<N>` (plus `(reason: <text>)` for skip), and refuse a bare number that is both, neither, or a spec
while the open issues cannot be read, with exit 2 and the state unchanged.

**Implementation notes:**
- `dispatch_state`: add `ItemRefused(PlatformError)`; add `parse_form(text) -> (form, N)` for the forms of the design's table;
  `parse_item` returns the key of an explicit form and raises `ItemRefused` for a bare number (it stays the parser of spec ids in
  `dispatch_backlog._spec_record`, which only passes `<NNN>-<slug>`). Update the module docstring.
- `dispatch_items.resolve(repo, slug, text) -> Item`: specs from `docs/specs/*/spec.md` of `repo` plus the cached snapshot's
  `specs`/`drafts` ids; open issues only for the bare form, from a snapshot younger than `dispatch_backlog.MAX_AGE` without `issues`
  in `unavailable`, else one `gh issue list ... --json number` through `dispatch_backlog.gh` (not persisted). `dispatch_items` never
  imports `dispatch` (no import cycle).
- Every refusal text exactly as the design's table; the item as written (`<t>`) and its value (`<N>`) in each.
- `dispatch._skip`, `_prioritize`, `_resume(item)`: resolve first, then write state; print the new one-line outputs.
- `dispatch.main`: catch `ItemRefused`, print `ERROR: <message>` to stderr, return 2 (other errors keep going to `cplat.py`).
- `tests/cplat/test_dispatch_state.py`: the existing `test_parse_item` case `("123", "issue-123")` no longer holds; move `123` to the
  refusal test (an `ItemRefused`) and keep the other cases.
- `docs/dispatch.md`: replace the item line ("An item is ...") with the rule: `#<N>` or `issue-<N>` is the issue; `spec-<N>`, a
  zero-padded number (`054`) or the spec id is the spec; a bare number is the spec or the open issue with that number, and is refused
  (exit 2) when it is both or neither, or when the open issues cannot be read; each verb prints what it acted on.
- The spec 167 acceptance tests (`tests/cplat/test_167_ready_order.py`) use `#N` and must stay green; they assert no GitHub write,
  and the new code only reads.

**Done when:** the acceptance tests of AC-175.1 to AC-175.3 pass, and `tests/cplat/test_167_*.py`, `test_dispatch_*.py` and
`test_needs_dispatch_scope.py` stay green.

## t2 — ship pr fills the closing lines like pr open and refuses a body that keeps the placeholder

**Files:** scripts/cplat/pr_open.py, scripts/cplat/ship.py, docs/changelog.d/175-a-spec-number-means-the-spec.fixed.md
**Covers:** AC-175.4, AC-175.5
**Goal:** `cplat component ship pr` replaces `{{CLOSES}}` with the same `Closes #N` lines `cplat pr open --spec <spec id>` writes,
and refuses with exit 2 before CI and the push when the body would still contain the placeholder (design.md "Ship PR body").

**Implementation notes:**
- `pr_open`: extract `closes_for(repo, base_ref, *, issues, tracks, message, have_gh)` and `fill_closes(text, kept)` from `_closes`;
  `_closes` and `open_pr` keep their behaviour and output (the AC-100.9 and AC-126.9 tests of `test_pr_open.py` and
  `test_ship_pr_126.py` stay green).
- `ship.open_pr`: after the title check and before `gh pr list`, fill when the staged body contains `{{CLOSES}}` (tracks from
  `specmod.find(repo, st["spec"])` when `st["spec"]` is set; commits only when it is not); raise `BodyRefused` when the result
  still contains the placeholder, with the reason and hint of the design; write the filled body to the staged file and use it for the
  spec rule, `PR_BODY` and `gh pr create`.
- `ship.main` (`pr` verb): catch `BodyRefused`, print `ERROR: <message>` and `  fix: <hint>` to stderr, return 2.
- A reused open PR keeps its body (retitle only, AC-126.12); a body without the placeholder reads nothing.
- Changelog fragment per `docs/changelog.d/README.md`: dispatcher steering reads a spec number as the spec, `#N`/`issue-N` as the
  issue, refuses an ambiguous number and prints what it acted on (#638); `cplat component ship pr` fills the closing lines, so a ship
  PR closes the spec's tracked issues (#645).

**Done when:** the acceptance tests of AC-175.4 and AC-175.5 pass, `tests/cplat/test_pr_open.py`, `test_ship_pr_126.py` and
`test_ship*.py` stay green, and `cplat platform pr-check` accepts the fragment.

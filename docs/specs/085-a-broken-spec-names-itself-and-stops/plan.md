---
spec_id: 085-a-broken-spec-names-itself-and-stops
spec_hash: 8712dc418ff0
summary: BrokenSpec error with file, line and fix hint; discovery tolerates broken specs; check, ci, list and index report them
tasks:
- id: t1
  title: BrokenSpec loader and tolerant discovery
  files: [scripts/cplat/spec.py]
  covers: [AC-085.1, AC-085.2, AC-085.3, AC-085.4, AC-085.5, AC-085.6, AC-085.11, AC-085.12]
  parallel_safe: false
  depends_on: []
  done: true
- id: t2
  title: Report broken specs in check, ci, list and index
  files: [scripts/cplat/spec.py, docs/CHANGELOG.md]
  covers: [AC-085.7, AC-085.8, AC-085.9, AC-085.10]
  parallel_safe: false
  depends_on: [t1]
---

Contract: [design.md](design.md). Acceptance tests live in `tests/cplat/` (pytest) and name the AC ids; coders do not edit them.

## t1 — BrokenSpec loader and tolerant discovery

**Files:** scripts/cplat/spec.py
**Covers:** AC-085.1, AC-085.2, AC-085.3, AC-085.4, AC-085.5, AC-085.6, AC-085.11, AC-085.12
**Goal:** an unreadable `spec.md` or `plan.md` raises one `BrokenSpec` that names the file (relative to the repo root), the line and the fix; discovery and `find` keep working for every other spec.

**Implementation notes:**
- Add `BrokenSpec(PlatformError)` with `dir`, `id`, `rel`, `line`, `problem`, `hint`, `one_line()` exactly as in design.md.
- `load(path, root=None)`: catch `yaml.YAMLError`; line = `problem_mark.line + 2` (fallback `context_mark`, else 1); use only `.problem`, never the snippet. Hint per the design table; the `mapping values are not allowed here` case uses the exact AC-085.1 text. No fences / not a mapping: line 1 and the "`---`, `key: value` lines, `---`" hint.
- `read(sdir)` passes `root=sdir.parents[2]` for both `spec.md` and `plan.md` (AC-085.3).
- Add `scan(root) -> (list[Spec], list[BrokenSpec])`; `all_specs` returns `scan(root)[0]`.
- `find`: match the ref against readable specs and broken folder ids (id, number, slug); a single broken hit re-raises its `BrokenSpec` (AC-085.6); the "specs: …" list includes broken ids.
- `next_number`: include the numbers of broken folders (AC-085.11).
- `new`: after `save`, re-read and raise a `PlatformError` if `meta["title"]` is not the identical `str`; confirm the AC-085.12 titles round-trip with the existing `_Dumper` (fix the representer only if one does not).
- No change in `ship.py`: it reaches specs only through `find` and `cplat spec trace` (AC-085.5).

**Done when:** the acceptance tests for AC-085.1 to .6, .11 and .12 pass (AC-085.4: `approve`, `set-status`, `task-done`, `hash`, `trace` and `check <id>` on a valid spec beside a broken one give the usual result and exit code, and the broken files stay byte-identical); existing `tests/cplat/test_spec*.py` stay green.

## t2 — Report broken specs in check, ci, list and index

**Files:** scripts/cplat/spec.py, docs/CHANGELOG.md
**Covers:** AC-085.7, AC-085.8, AC-085.9, AC-085.10
**Goal:** commands that cover every spec show a broken one as broken instead of crashing or hiding it.

**Implementation notes:**
- `check` without ids: results from `scan`; each broken spec adds `{id: [one_line()]}` so `_print_errors` prints one `ERROR: <id>: …` line and counts it (AC-085.7). With ids, unchanged (`find` raises for a broken id).
- `ci`: print `::error file=<rel>,line=<n>,title=spec <id>::<problem> (fix: <hint>)` per broken spec regardless of `--strict`; count it in specs and problems; return 1 when any spec is broken, else the current rule (AC-085.8).
- Add `broken_summary(root, b)` with the row of design.md (`status: broken`, empty title and priority, `next: fix <rel> line <n>: <hint>`); `list` appends these rows always (not filtered by `--all`), text and `--json`, exit 0 (AC-085.9).
- `index_table` adds the broken rows to the sort so each keeps `| [<id>](specs/<id>/spec.md) —  |  | broken | 0 |  |` (AC-085.10).
- `docs/CHANGELOG.md` `[Unreleased]`: one bullet, "Fix (085): a broken spec names its file, line and fix and no longer blocks other specs (#129)".

**Done when:** the acceptance tests for AC-085.7 to .10 pass; `cplat spec check` and `cplat spec ci --strict` on this repo stay green.

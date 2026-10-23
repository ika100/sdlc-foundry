# Verification — 085 A broken spec names itself and stops nothing else

**Result:** pass
**Commit:** 3248c3e · **Base:** 836861c (origin/main) · **Trace:** 12/12 criteria named by tests

The acceptance tests in `tests/cplat/test_spec_broken.py` have not changed since the red commit f755ff2 (`git diff f755ff2..HEAD -- tests` is empty). `devbox run ci-local`: 707 passed.

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-085.1 | met | `tests/cplat/test_spec_broken.py::test_colon_title_names_file_line_and_hint` | `scripts/cplat/spec.py:76-83` (YAML error -> `BrokenSpec`, line = mark + 2, `COLON_HINT` at :56), `scripts/cplat/spec.py:172` (rel to repo root) | The test asserts the relative path, `line 3` and the exact hint. There is no traceback: the error is raised `from None` (:83), only `e.problem` is used, and `scripts/cplat/cplat.py:66-69` prints a `PlatformError` as `ERROR:` / `fix:`. The test checks the exception, not stderr. That is acceptable because the printer is unchanged code that other tests already cover. |
| AC-085.2 | met | `tests/cplat/test_spec_broken.py::test_missing_fences_or_non_mapping` (no fences; YAML list) | `scripts/cplat/spec.py:74-75`, `scripts/cplat/spec.py:84-85`, `FENCE_HINT` :57 | The test checks the file, `line 1` and a hint that contains `key: value` and `---`. |
| AC-085.3 | met | `tests/cplat/test_spec_broken.py::test_broken_plan_names_plan_file` | `scripts/cplat/spec.py:173` (`plan.md` loaded with the same root) | The test checks the `plan.md` path, line 3 and the exact hint. |
| AC-085.4 | met | `tests/cplat/test_spec_broken.py::test_valid_spec_unaffected_by_broken_neighbour` (approve, hash, trace, task-done, set-status, check) | `scripts/cplat/spec.py:152-167` (`scan`, `all_specs` returns only readable specs), `scripts/cplat/spec.py:177-187` (`find`) | The test compares exit code and stdout between a clean repo and a repo with a broken neighbour, and checks that the broken folder stays byte-identical. |
| AC-085.5 | met | `tests/cplat/test_spec_broken.py::test_ship_reaches_specs_only_through_find` | `scripts/cplat/ship.py:131,194,472` (`specmod.find`), `scripts/cplat/ship.py:841` (`cplat spec trace` subprocess) | The test does not run `cplat ship`. It proves the seam that ship uses: `find`/`all_specs` resolve the valid spec while a broken one is present. I confirmed by reading the code that ship reaches specs only through `find(ref)` for its own spec and through `spec trace <id>`, and both are covered by AC-085.4. Acceptable as designed in `design.md`. A full ship run is not tested. |
| AC-085.6 | met | `tests/cplat/test_spec_broken.py::test_addressing_broken_spec_fails_and_writes_nothing` (5 commands x refs `090`, `90`, `090-broken`, `broken`) | `scripts/cplat/spec.py:181-187` (broken folders matched by id, number and slug; the single broken hit is re-raised) | The test checks exit 1, a `BrokenSpec` naming the file and line 3, and that nothing is written. |
| AC-085.7 | met | `tests/cplat/test_spec_broken.py::test_check_all_reports_broken_once` | `scripts/cplat/spec.py:947-955` | The test checks exactly one `ERROR: 090-broken:` line with the file and line, `1 error(s)` and exit 1. The valid spec goes through `check` as before (:953). |
| AC-085.8 | met | `tests/cplat/test_spec_broken.py::test_ci_annotates_broken_spec` (with and without `--strict`) | `scripts/cplat/spec.py:864-872` | The test checks one `::error` annotation with `file=docs/specs/090-broken/spec.md` and `line=3`, and exit 1 in both modes. The valid specs are still checked and traced through `ci_problems`/`all_specs` (:850). The test does not assert that part, but the code path is unchanged. |
| AC-085.9 | met | `tests/cplat/test_spec_broken.py::test_list_json_shows_broken` (with and without `--all`), `tests/cplat/test_spec_broken.py::test_list_text_shows_broken` | `scripts/cplat/spec.py:680-683` (`broken_summary`), `scripts/cplat/spec.py:989-991` | The test checks status `broken`, an empty title, `next` starting `fix ` with the file and line 3, the valid spec still listed, and exit 0. |
| AC-085.10 | met | `tests/cplat/test_spec_broken.py::test_index_keeps_row_for_broken` | `scripts/cplat/spec.py:686-689` | The test checks the exact row `\| [090-broken](specs/090-broken/spec.md) —  \|  \| broken \| 0 \|  \|` and that the valid spec is present. |
| AC-085.11 | met | `tests/cplat/test_spec_broken.py::test_next_number_counts_broken` | `scripts/cplat/spec.py:190-192` | With a broken 090 present, the test gets `next_number == 91`. |
| AC-085.12 | met | `tests/cplat/test_spec_broken.py::test_new_titles_round_trip` (`a: b`, `#7 retry`, `- list`, `[draft]`, `yes`, `null`, `123`, `"quoted" start`, `'single`, `true`, `~`) | `scripts/cplat/spec.py:506-511` (read-back guard); quoting comes from the existing `_Dumper` | The test checks that each title reads back identical and as `str`, and that `check` reports no `ERROR`. |

## Non-goals

- No automatic fixing: `load` only raises, and nothing rewrites a broken file. The AC-085.4 and AC-085.6 tests check that the broken files stay byte-identical. ✔
- Front-matter content checks (`check`) are unchanged. ✔
- `docs/plan/` documents: `slice_from_plan` (`scripts/cplat/spec.py:552`) and `migrate_plan` (:765) call `load(path)` without a root. They now get a `BrokenSpec`, which is a subclass of `PlatformError`, so `migrate_plan`'s `except PlatformError` still skips bad plans. Two side effects: the message wording changes ("missing front matter" plus a fix hint), and invalid YAML in a plan used to raise a raw `yaml.YAMLError` but now raises a `PlatformError`. The design (Decisions, first bullet) intends this. The behaviour that matters is the same or better, so this is acceptable.
- Specs in other repos: not touched. ✔

## Deviations from the plan

- Both tasks t1 and t2 are `done: true`. The changed files (`scripts/cplat/spec.py`, `docs/CHANGELOG.md`) are within the tasks' `files`. The spec, plan and design files under the spec folder are pipeline artefacts, and the test file comes from the red commit. No deviation.
- `next_number` takes the number from `s.id.split("-", 1)[0]` for both readable and broken specs instead of `s.number`. The result is the same, so this is acceptable.

## Contract

Matches `design.md`:
- `BrokenSpec` has `dir`, `id`, `rel`, `line`, `problem`, `hint`, `one_line()`, and `str(e)` is `<rel>, line <n>: <problem>` (`scripts/cplat/spec.py:60-68`).
- The line and hint table matches, including the fallback to `context_mark` and to line 1 (:79-82).
- The `ci` annotation format, the `list` row fields and the `index` row match.
- The `CHANGELOG.md` `[Unreleased]` bullet is present as planned.
- `ship.py` is unchanged, as the design specifies.

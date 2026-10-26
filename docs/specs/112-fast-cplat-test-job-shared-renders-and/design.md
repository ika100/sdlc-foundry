# Design — 112 Fast cplat test job: shared renders and sharding

## Decisions

- **One shared-render cache per test process, copied per test.** A session-scoped `SharedRenders` object (one per
  pytest process, so one per xdist worker) builds each distinct repo once into the run's `basetemp` and hands every
  test its own `shutil.copytree` of it (AC-112.2, AC-112.8). The cache lives only in `tmp_path_factory`: no pytest
  cache dir, no file outside the run's base temp, nothing an Actions cache could restore (AC-112.5). It generalises the
  `seed` pattern of `fleet_world.py`, which is moved onto it. ADR: [docs/adr/052-shared-renders-in-the-platform-test-suite.md](../../adr/052-shared-renders-in-the-platform-test-suite.md).
- **Drop-in for `newsvc.main`.** Fixtures get repos through a `new_service(argv)` fixture that takes exactly the argv
  they passed to `newsvc.main` today, so a migration is a one-line change and the rendered content cannot drift from
  what `cplat new-service` produces. Tests whose subject is the render (`test_newsvc.py`, `test_java_database.py`,
  `test_ci_extra.py::test_a_new_repo_has_the_section_and_an_empty_notes_file`,
  `test_spec_driven.py::test_every_merge_to_main_asks_the_gitops_app_to_pin_dev`,
  `test_smoke_091_templates.py::test_a_fresh_web_repo_has_the_playwright_scaffold_by_default_ac_091_16`, the
  dry-run and GitHub-path tests) keep calling `newsvc.main` (AC-112.4).
- **A failed build is remembered, not retried.** Every later request for the key raises the same `RenderFailed`, so
  each dependent test errors in setup with the render's message (AC-112.6) and a broken template costs one render per
  worker, not one per test.
- **Round-robin sharding over the sorted node ids, in our own conftest plugin.** Test `k` (0-based, in node-id sort
  order) belongs to shard `k % N + 1`. Consecutive tests of one file land in different shards, so the heavy files
  (gitops, update, fleet) spread evenly over the 4 shards (AC-112.12) without stored durations and without any file
  list (AC-112.11). Without `--shard` the plugin does nothing (AC-112.15). pytest-split was rejected: it needs a
  committed durations file that goes stale, and its fallback for unknown tests is an unbalanced split.
- **Coverage is checked from what ran, in every run.** Each shard writes a report of the ids it collected and the ids
  that produced a test report; a `cplat shards cover the suite` job checks the 4 reports with
  `scripts/check-shards.py` and `ci-success` needs it (AC-112.10, AC-112.14). The full collection comes from the
  shards themselves (every shard collects the whole suite before deselecting), so the check adds no second
  collection to the critical path.
- The derived state "gitops repo with `todo-api` composed and committed" (fixtures `repo` in `test_alerts_render.py`
  and `app` in `test_staging_093_setting.py`) is a shared key too: it is built from the shared gitops render with a
  fresh `FakeGh` patched only for the build (`pytest.MonkeyPatch.context()`). `at_staging` in
  `test_promote_digest.py` stays as is (it mutates `gh` before composing).

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `tests/cplat/shared_render.py` | `SharedRenders`, `RenderFailed`, the argv key of `new_service` | new |
| `tests/cplat/conftest.py` | fixtures `shared_renders` (session) and `new_service` (function); re-exports the sharding hooks | changed |
| `tests/cplat/sharding.py` | `--shard`, `--shard-report`, selection, report writing (serial and xdist) | new |
| `scripts/check-shards.py` | checks the shard reports of one run (stdlib only) | new |
| `tests/cplat/test_gitops.py`, `fleet_world.py`, `test_update_lost.py`, `test_update_doctor.py`, `test_rename_migration.py`, `test_smoke_091_templates.py`, `test_generated_repos.py`, `test_alerts_render.py`, `test_staging_093_setting.py` | get their rendered repos from the cache | changed |
| `.github/workflows/ci.yml` | 4-shard matrix, coverage job, `ci-success` needs | changed |

## Contract

### `tests/cplat/shared_render.py`

```python
class RenderFailed(Exception):
    """str(e) == f"shared render {key!r} failed: {type(err).__name__}: {err}" + ("\n" + output tail if any)
    output tail: the last 20 lines the build printed (stdout and stderr together)."""

class SharedRenders:
    def __init__(self, root: Path): ...          # root: an empty directory inside the run's basetemp
    builds: dict[str, int]                       # key -> times its build ran in this process (0 or 1; failures count)

    def copy(self, key: str, build: Callable[[Path], Path], dest: Path) -> Path:
        """build(workdir) creates the repo somewhere under the fresh, empty `workdir` and returns its path.
        First call for `key`: runs build once with stdout/stderr captured (never shown to the requesting test);
        any exception, SystemExit or a returned path that is not a directory is a failure: remembered, RenderFailed raised.
        Later calls: build is not called again; a remembered failure raises RenderFailed with the same message.
        On success: shutil.copytree(source, dest, symlinks=True) and return dest. `dest` must not exist, or be an empty
        directory (removed first); anything else raises FileExistsError. The source is never returned to a caller."""

def service_key(argv: list[str]) -> tuple[str, str, list[str]]:
    """(key, name, argv_without_dir) for a newsvc argv: key = shlex.join(argv without the `--dir D` pair),
    name = argv[0]. Raises ValueError when argv has no `--dir` or contains `--dry-run`."""
```

### Fixtures (`tests/cplat/conftest.py`)

- `shared_renders` (scope `session`): `SharedRenders(tmp_path_factory.mktemp("shared-renders"))`.
- `new_service` (scope `function`): a callable `new_service(argv: list[str]) -> Path`. `argv` is what `newsvc.main`
  takes and must contain `--dir D`; the result is `Path(D) / argv[0]`, a private copy of
  `newsvc.main([*argv_without_dir, "--dir", <workdir>])`. Equivalent content, including the `.git` directory with
  its bootstrap commit on `main`. Output of the render is not printed.
- No new environment variable, marker or option is needed to use either (AC-112.15).

### Sharding options (`tests/cplat/sharding.py`, hooks re-exported by `conftest.py`)

- `--shard I/N`: integers with `1 <= I <= N`; anything else is `pytest.UsageError("--shard must be I/N with 1 <= I <= N, got <value>")`.
- `--shard-report PATH`: only with `--shard` (else `UsageError("--shard-report needs --shard")`); a relative PATH is
  relative to the directory pytest was started in.
- Selection, in `pytest_collection_modifyitems` (trylast): sort the collected items by `nodeid`; the item at sorted
  index `k` is kept when `k % N == I - 1`; the others go to `config.hook.pytest_deselected`. Kept items keep their
  original relative order. The terminal header shows `shard I/N: <kept> of <collected> tests`.
- Under xdist every worker selects the same items (identical collection); the controller does not collect.
- Report (written once per run, by the process that owns the session: the xdist controller, or the single process of
  a serial run), UTF-8 JSON:

  ```json
  {"shard": 2, "total": 4, "collected": ["<nodeid>", "..."], "ran": ["<nodeid>", "..."]}
  ```

  `collected`: sorted node ids of the whole suite before deselection. Under xdist each worker passes its list to the
  controller through `config.workeroutput["shard_collected"]` (read in `pytest_testnodedown`, declared with
  `optionalhook=True`); differing lists make the controller write `"collected": null` and the run exit non-zero.
  `ran`: sorted, de-duplicated node ids of every `pytest_runtest_logreport` the reporting process received (setup,
  call or teardown, any outcome, including a worker crash report). The report is written even when tests fail.

### `scripts/check-shards.py`

`python3 scripts/check-shards.py REPORT...`

- exit 0, one line: `OK: <n> tests ran in exactly one of <N> shards`.
- exit 1, one line per finding, then `ERROR: <k> finding(s)`:
  - `missing report for shard <i>/<N>` / `duplicate report for shard <i>/<N>`
  - `shard reports disagree on the total (<a> vs <b>)` / `shard reports disagree on the collected tests`
  - `shard <i>/<N>: collection differed between workers`
  - `<nodeid>: ran in no shard`
  - `<nodeid>: ran in shards <i>, <j>`
  - `<nodeid>: ran in shard <i> but was not collected`
- exit 2: no arguments, or a report that is unreadable or not of the format above (message names the file).

### CI (`.github/workflows/ci.yml`)

- `platform-tests`: name `cplat unit + integration tests (shard ${{ matrix.shard }}/4)`, `strategy.fail-fast: false`,
  `matrix.shard: [1, 2, 3, 4]`; same `needs`/`if`, same setup steps; pytest step:
  `uv run --with pytest --with pytest-xdist --with pyyaml --with ruamel.yaml pytest tests/cplat -q -n auto --shard ${{ matrix.shard }}/4 --shard-report shard-${{ matrix.shard }}.json`
  (keeps the `pytest tests/cplat -q -n auto` text AC-084.1 checks); then `actions/upload-artifact` (the repo's pin)
  with `if: always()`, name `cplat-shard-${{ matrix.shard }}`, path `shard-${{ matrix.shard }}.json`,
  `retention-days: 1`, `if-no-files-found: ignore` (a missing report is the checker's finding).
- `platform-tests-cover`: name `cplat shards cover the suite`, `needs: [changes, platform-tests]`,
  `if: always() && needs.changes.outputs.code == 'true'`; checkout, `actions/download-artifact` (the repo's pin) with
  `pattern: cplat-shard-*`, `merge-multiple: true`, `path: shards`; `python3 scripts/check-shards.py shards/*.json`.
  A shard that was cancelled before writing its report shows up as `missing report`.
- `ci-success.needs` gains `platform-tests-cover` (inserted before `smoke-test-templates`, so the list still ends
  with `spec-required, pr-title]`). Its rule is unchanged: a failed or cancelled matrix leg makes `platform-tests`
  `failure`/`cancelled`; code-free changes skip both jobs, which count as passed (AC-112.14).
- `scripts/ci-local.sh` keeps the unsharded command.

## Risks

- Per-worker renders: with 4 shards × `-n auto` there are up to 16 workers per run, each building each key it needs
  once (about 14 keys, roughly 1–2 s each). This is bounded and far below today's one render per test.
- Copies of a repo with a `.git` directory: git re-stats the copied files on the first `git status`; content and
  history are identical. The copy path differs from the render path; nothing rendered embeds its own absolute path
  (`_src_path` is rewritten by `newsvc`).
- The 50% setup target (AC-112.7) counts only fixture setup; `test_appship_097.py` and `test_replan.py` build plain git
  worlds, not renders, and stay as they are (non-goal). If the measured setup total misses the target, measurement
  task m1 reports it as a blocker instead of widening the scope.

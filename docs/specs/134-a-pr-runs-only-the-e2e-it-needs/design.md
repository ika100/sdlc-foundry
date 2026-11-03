# Design — 134 A pull request runs only the e2e it needs, and that e2e runs in parallel parts

## Decisions

1. **The decision is code, not a path filter.** GitHub's `paths` filter cannot follow imports or read a changelog heading, so
   `e2e.yml` drops it for `pull_request` and a `decide` job runs `scripts/e2e-scope.py --base ${{ github.event.pull_request.base.sha }}`,
   like `e2e-upgrade.yml` already does with `release-check.py`. The jobs that need a cluster run when `run=true` or on `schedule` /
   `workflow_dispatch`. A skipped job is a skipped check, which `cplat pr wait` and branch rules already accept (the upgrade job works
   this way since spec 121).
2. **The exercised cplat modules are derived from the e2e scripts at HEAD.** `e2e-scope.py` reads `$cplat <noun> <verb>` and
   `$cplat <plumbing>` calls in `tests/e2e/run.sh` and `tests/e2e/cluster.sh`, maps them through the `NOUNS` and `PLUMBING` literals of
   `scripts/cplat/cplat.py` (read with `ast`, not imported), adds the `scripts/cplat` modules their heredocs import and `cplat` itself,
   then closes the set over every `import` / `from … import` in those modules (module level and inside functions, `ast.walk`). Packages
   (`console`, `failsum`) are units. A new `$cplat` call in the e2e or a new import widens the set without anyone editing a list.
3. **Release pull requests always run.** A change that adds a `## [X.Y.Z]` heading to `docs/CHANGELOG.md` is the release pull request;
   the decision returns `run=true`, so the release command, which waits for every check of the release pull request, cannot merge (and
   tag) without a green cluster e2e. The nightly run stays.
4. **The upgrade e2e decides on the pull request's own diff.** The `decide` job of `e2e-upgrade.yml` passes `--base <PR base sha>` on
   `pull_request` only (an empty `BASE` keeps `release-check.py`'s default, the latest tag, for push, schedule and dispatch). No change to
   `release-check.py`.
5. **Parts are guards in `run.sh`, not separate scripts.** `E2E_PART` (`all` default, `core`, `scaling`, `backups`) is checked once
   before anything starts; `in_part <part>…` returns true for `all` or a listed part. The blocks that only some parts need are wrapped:
   bucket checks (`core`), broker (`core scaling`), scaling inside the broker (`scaling`), ship (`core`), backups (`backups`). Helper
   functions those blocks share with later blocks are defined outside the guards. A skipped block prints `skip [<part>] <its first step>`
   so the log still shows what ran. With `all` the script is the same sequence as before.
6. **Images only where needed.** The NATS probe and worker images are built when the part runs the broker (`core`, `scaling`, `all`).
   Everything else (cluster up with all operators, the service images) stays identical, so every part checks the same setup.
7. **Matrix by event.** `strategy.matrix.part` is `fromJSON(github.event_name == 'pull_request' && '["core","scaling","backups"]' ||
   '["all"]')`, `fail-fast: false` (one red part must not hide the others' result), timeout `90` for `all` and `45` for a part.

## Expected timings (from the measured phases)

| Part | Shared setup | Own steps | Estimate |
|---|---|---|---|
| core | 781 s | bucket 158 + broker 88 + ship 196 | ~1220 s |
| scaling | 781 s | broker 88 + scaling 560 | ~1430 s |
| backups | 781 s | backups 674 | ~1455 s |

Shared setup = cluster up 237 + images 113 + addons 183 + render/probes/secrets 103 + external 37 + caches 108. The slowest part sets the
wall time: about 24-25 minutes against 41.

## Contract

- `scripts/e2e-scope.py [--base REF]` → stdout `run=true|false` (one line); stderr one `trigger: <path>` per triggering path and
  `trigger: release heading <X.Y.Z>` for a release; exit 0, or 1 with `ERROR: <reason>` (no traceback). Without `--base`: the merge base
  with `origin/main` if it exists, else `HEAD^`.
- `scripts/e2e-scope.py --list` → the exercised set, sorted, one name per line.
- `tests/e2e/run.sh` reads `E2E_PART`; an unknown value prints `E2E FAIL: E2E_PART must be one of all core scaling backups (got X)` and
  exits 1 before docker is touched.

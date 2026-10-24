---
spec_id: 096-platform-updates-roll-out-to-every-repo
spec_hash: 3b3cd2de98f0
summary: cplat fleet update (and /shared:fleet) brings every stamped platform repo of the configured owners to the installed release through update-service's own resolve/execute, one PR per repo, squash-merged on green only when routine, else labelled and commented; table/JSON report, exit code and a fleet run record
tasks:
- id: t1
  title: One behind repo - branch, update, push, PR, routine check, label/comment, pr wait --merge
  files: [scripts/cplat/fleet_pr.py]
  covers: [AC-096.3, AC-096.6, AC-096.7, AC-096.8, AC-096.14, AC-096.15, AC-096.16]
  parallel_safe: true
  depends_on: []
  done: true
- id: t2
  title: cplat fleet update - discovery, target check, ordered loop, dry run, report, exit code, run record
  files: [scripts/cplat/fleet.py]
  covers: [AC-096.1, AC-096.2, AC-096.9, AC-096.10, AC-096.11, AC-096.12, AC-096.13, AC-096.14, AC-096.17]
  parallel_safe: true
  depends_on: [t1]
  done: false
- id: t3
  title: Register the command, /shared:fleet and docs
  files: [scripts/cplat/cplat.py, plugins/shared/commands/fleet.md, plugins/shared/README.md, docs/CHANGELOG.md]
  covers: [AC-096.1]
  parallel_safe: true
  depends_on: []
  done: false
---

The contract for every task is [design.md](design.md). No ADR. Acceptance tests live in `tests/cplat/test_fleet.py`
(and `tests/cplat/test_fleet_pr.py` for the PR unit), name the AC ids, fake GitHub only through `fleet.gh`,
`fleet.clone` (a local bare repo), `fleet.sleep` and `pr.wait`, and never reach the network. Levels: t1, t3 → t2.

## t1 — One behind repo: branch, update, push, PR, routine check, label/comment, pr wait --merge

**Files:** scripts/cplat/fleet_pr.py
**Covers:** AC-096.3, AC-096.6, AC-096.7, AC-096.8, AC-096.14, AC-096.15, AC-096.16
**Goal:** `fleet_pr` exactly as in design.md "`fleet_pr.py`", "Per-repo outcome" and "PR title, body and comment":
given a `Ctx` with a fresh clone, produce the same commit `/shared:update-service` makes, push it, open or rebuild the
one fleet PR and decide merged / left open / failed.

**Implementation notes:**
- Branch: the existing fleet PR's head (`open_fleet_pr`), else `new_branch` (branch_name's scheme, skipping names that
  exist locally or as `origin/<name>`); `git checkout -q -b <branch>` from the default branch tip before
  `update.resolve(["--repo", clone] (+ ["--ref", ref]))` and `update.execute(req)`.
- Empty `Report.data` → `Result("up to date", ...)`, nothing pushed.
- Existing PR: the manual-commit check (`git log --no-merges ... origin/<default>..origin/<head>`, subject prefix
  `UPDATE_SUBJECT`) before any push; equal trees → no push; else `git push --force-with-lease=<head>:<sha> origin`.
  New PR: plain `git push -u origin <branch>`.
- `pr create` / `pr edit` with `pr_body` on stdin (60 000-char cap, changelog cut first); `edit` never touches labels.
- `pre_wait_reasons` (lost, major incl. `from` none) → label + comment, no wait. Then `mergeable` (UNKNOWN re-read
  10x via `ctx.sleep(3)`); `CONFLICTING` → `merge conflict`.
- Else `pr.wait(ctx.clone, url, True, ctx.timeout, 20, ship.QUEUE_TIMEOUT, ctx.slug)` through the module attribute,
  and map its results and `PlatformError`s to reasons exactly as in the outcome table (re-read `mergeable` after a
  failed merge).
- Every `left open`: `label create` (non-zero ignored), `--add-label`, and `comment_body` unless the last marker
  comment has the same body. Failing create/edit/label/comment calls → `failed: <step>: <line>`.
- `follow_ups` drops the `run the repo's checks:` and `platform changes since your version` steps; the rest is
  `Result.next` for every outcome.

**Done when:** the acceptance tests for AC-096.3, .6, .7, .8, .15, .16 and the per-repo part of .14 pass against a
local bare repo with a faked `gh` and `pr.wait`, and the existing `test_update*.py` tests stay green (update.py is
not changed).

## t2 — cplat fleet update: discovery, target check, ordered loop, dry run, report, exit code, run record

**Files:** scripts/cplat/fleet.py
**Covers:** AC-096.1, AC-096.2, AC-096.9, AC-096.10, AC-096.11, AC-096.12, AC-096.13, AC-096.14, AC-096.17
**Goal:** the `cplat fleet update` CLI and the seams of design.md "CLI", "Seams", "gh calls", "Discovery", "Report"
and "Run record", calling `fleet_pr.update` (t1) for each repo that is behind.

**Implementation notes:**
- argparse with the one subcommand `update`; `--owner`/`--only` repeatable, `--only` validated as `owner/name`;
  default owner from `gh api user`. `--ref` must be `[v]X.Y.Z` and equal `core.platform_version()`, else the
  `PlatformError` with the `CPLAT_REF=` hint, before any repo is read.
- Discovery through the exact `gh` calls (list per owner, `repo view` per `--only`, raw contents for the two files);
  platform repo = `_src_path` ends in `templates/<t>` of `core.registry.load()`. Non-platform repos are hidden
  without `--only`, `skipped: not a platform repo` with it; archived/fork rows for `--only`.
- Dedupe, `sorted(key=str.lower)`, strictly one repo at a time; stamp `>=` target (`core.vtuple`) → `up to date`
  without cloning.
- Behind and not dry run: `fleet.clone` into a `TemporaryDirectory`, build `fleet_pr.Ctx` (gh/sleep bound via
  lambdas), call `fleet_pr.update` inside `contextlib.redirect_stdout(sys.stderr)`. Any exception → `failed: <first
  line>` and the loop continues.
- Dry run: no clone, no write call, no run record; `would update` with the open-PR / major hints in `next`.
- Text table and `--json` (stdout only the document), counts in the fixed order, `no platform repos found`; exit 1
  when any `left open` or `failed`.
- Run record: `runs.start("fleet")`, one `runs.event(rid, "repos", slug, ...)` per repo, `set_section(rid, "fleet",
  ...)`, `finish` with done / escalated / failed; discovery `PlatformError` → `finish(rid, "failed")` and re-raise.
  Fleet never sets `CPLAT_RUN_PARENT`.

**Done when:** the acceptance tests for AC-096.1, .2, .9, .10, .11, .12, .13, .17 and the report part of .14 pass
(with t1 in), an unreachable run store leaves stdout and the exit code unchanged, and the full `tests/cplat` suite is
green.

## t3 — Register the command, /shared:fleet and docs

**Files:** scripts/cplat/cplat.py, plugins/shared/commands/fleet.md, plugins/shared/README.md, docs/CHANGELOG.md
**Covers:** AC-096.1
**Goal:** `cplat fleet update` is reachable from the launcher and as `/shared:fleet`, and users can find it.

**Implementation notes:**
- `cplat.py`: `"fleet": "fleet"` in `COMMANDS` and the docstring line
  `cplat.py fleet update [--owner O] [--only owner/name] [--ref TAG] [--dry-run] [--json]   bring every platform repo to this release (spec 096)`.
- `plugins/shared/commands/fleet.md`: `description:` with usage; runs `cplat fleet update <ARGS>` (prefixed with
  `CPLAT_REF=<tag>` when `--ref` is given, as in update-service.md); suggests `--dry-run` first; starts the real run in
  the background and reads its output until it ends (CI waits exceed one Bash call); relays the table, each `next:`
  line and the exit status verbatim; never merges, labels or edits a PR by hand. Ends with the standard
  `/shared:report-issue` paragraph.
- `plugins/shared/README.md`: one command-table row for `/shared:fleet`.
- `docs/CHANGELOG.md`: one bullet under `[Unreleased]`: **Feature (096): platform updates roll out to every repo.**
  `cplat fleet update` / `/shared:fleet`, merge only when routine (spec 086's `lost` empty, same major, no conflict,
  green CI), else label `platform-update: needs review` + comment; `--dry-run`, `--only`, the `fleet` run record.
- No plugin or marketplace version bumps (the release does them).

**Done when:** `cplat fleet --help` reaches the fleet parser (once t2 is in), `devbox run validate` and the Markdown link check pass.

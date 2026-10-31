# Design — 129 A platform release command

`cplat platform release` drives the procedure of CONTRIBUTING.md, Releases. It keeps no state of its own: each run reads
git and GitHub, names the phase the release is in, prints it, and continues from there to the next confirmation stop, the
end, or the first failure. `/platform:release` is a thin command that runs it and turns its two stops into questions.
ADR-073 records the decision.

## Decisions

- **The progress is derived from git and GitHub, never stored** (AC-129.17). The release branch `release/X.Y.Z`, the open
  PR from that branch, the squash commit `chore: release X.Y.Z (#N)` on `origin/main`, the tag on origin, the GitHub release
  and the release-guard run are the state. A local file would go stale on a second machine and after a manual step; these
  facts cannot.
- **Two confirmation stops, exit 3** (AC-129.11, AC-129.14). A run without the matching `--confirm` stops before the
  squash merge and before the tag, prints what it would do and `CONFIRM: merge|tag`, and exits 3. `--confirm merge` is
  accepted only when the run starts in phase `pr-open`, `--confirm tag` only in phase `merged`; anywhere else it is refused
  with exit 1 and nothing changes. So a confirmation can never be spent on a step the maintainer has not seen yet.
- **Reuse, don't duplicate.** CI on the PR is `pr.wait` (spec 079; it already judges only the newest run of a workflow,
  AC-129.9, and merges with `--match-head-commit`). A workflow run on `main` or on the tag is followed with `ship.RunWatch`.
  Every `gh` call goes through `ship.gh`, sleeping and the clock through `ship.sleep` / `ship.now`, progress through
  `ship.say`, so the existing fakes of `tests/cplat/test_tags_and_wait.py` work unchanged. The rows check, the major
  detection and the gate stay in `scripts/release-check.py`; it gains a `needs-major` subcommand so the version proposal
  and `rows` share one rule (AC-129.2).
- **The repo's own scripts, under cplat's interpreter.** `release-check.py` is run as `[sys.executable,
  "scripts/release-check.py", …]` with `cwd` = the platform checkout being released (not the cplat install the launcher
  runs from). `sys.executable` is the `uv run` interpreter of the launcher, which has pyyaml: the system-Python crash of the
  5.4.0 release cannot recur. Validation is `devbox run validate`.
- **The changelog heading is `## [X.Y.Z] - YYYY-MM-DD`** as the spec says (AC-129.6). Older sections use an em dash; both
  match `core._VERSION_RE` and `release-check.HEADING` (they read only the bracketed version).
- **The PR body carries no changelog text.** GitHub closes issues named after "fixes" anywhere in a PR body; closing issues
  is a non-goal, so the body is a fixed two-line text.
- **No `--prune`, no `-f`, no tag deletion anywhere** (AC-129.19). `git fetch origin --tags` (no prune), `git push origin
  refs/tags/vX.Y.Z` (no force), `git push -u origin release/X.Y.Z` (no force).

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `scripts/release-check.py` | `needs-major [--base REF]`: one line per change that needs a major release; `rows` uses the same function | changed |
| `scripts/cplat/platrelease_changelog.py` | pure text: `unreleased_body`, `move_unreleased`, `section_body`; `plugin_mismatches(repo)` | new |
| `scripts/cplat/platrelease_state.py` | read-only: fetch, `detect(repo) -> State`, `propose(...)`, `steps(...)`, `render(...)`; the `run_check` and `today` seams | new |
| `scripts/cplat/platrelease.py` | CLI `main(argv)`, preflight, prepare/commit/push/PR, CI wait, merge stop and merge | new |
| `scripts/cplat/platrelease_publish.py` | upgrade e2e on the merge commit, gate, tag stop, tag + push, GitHub release, release guard | new |
| `scripts/cplat/cplat.py` | `"release": ("platrelease", [])` under `platform`; one docstring line | changed |
| `plugins/platform/commands/release.md` | `/platform:release` | new |

## Contract

### CLI

```
cplat platform release [--version X.Y.Z] [--dry-run] [--confirm merge|tag] [--timeout S] [--interval S] [--repo DIR]
```

`--repo` defaults to `.`; `--timeout` (default 5400) bounds each wait; `--interval` (default 20) is the poll interval.
`--version` must match `^\d+\.\d+\.\d+$` (no `v`).

| Exit | Meaning |
|---|---|
| 0 | dry run printed; or the release finished (`RELEASED:`) |
| 1 | refused or failed; stderr has `ERROR: <reason>` (via `core.PlatformError`) and, where given, `  fix: <hint>` |
| 2 | usage error (argparse) |
| 3 | stopped at a confirmation (`CONFIRM: merge` or `CONFIRM: tag`) |

### Phases (detection, first match wins)

Definitions after `git fetch origin --tags` (and `git fetch origin main`):

- **T**: the highest `vX.Y.Z` tag on origin (`git ls-remote --tags origin`; an annotated tag's commit is its `^{}` line).
  None → exit 1 `no release tag vX.Y.Z on origin`.
- **M**: the newest commit among the last 200 of `origin/main` whose subject matches
  `^chore: release (\d+\.\d+\.\d+)(?: \(#\d+\))?$`; `M.version`, `M.sha`.
- **branches**: `release/X.Y.Z` local (`refs/heads/`) or on origin (`refs/remotes/origin/`) with X.Y.Z > T and
  X.Y.Z ≠ M.version. More than one version → exit 1 naming them.
- **PR**: `ship.gh(["pr", "list", "--state", "open", "--base", "main", "--json", "number,url,title,headRefName,headRefOid"])`
  entries with `headRefName` `release/X.Y.Z`, X.Y.Z > T. More than one → exit 1 naming them.

| Phase | When | Version | Next step |
|---|---|---|---|
| `pr-open` | a release PR | from the PR | wait for CI |
| `merged` | M.version > T | M.version | wait for the upgrade e2e on M.sha |
| `branch` | a release branch, no PR | from the branch | finish preparing, commit, push, open the PR |
| `tagged` | M.version = T, tag T on M.sha, no GitHub release `vT` | T | create the GitHub release |
| `guarding` | M.version = T, GitHub release exists, the release-guard run of `vT` is not concluded, or absent and the tag is younger than 10 minutes (tagger date) | T | wait for the release guard |
| `guard-red` | as `guarding`, but the run concluded red | T | exit 1 with the run's link (AC-129.16; tag and release untouched) |
| `idle` | none of the above (also: guard concluded green, or no guard run and the tag is older than 10 minutes, printed as `release-guard: no run on vT, not checked`) | proposed | prepare |

`pr-open` and `merged` together, or a PR and a branch of different versions → exit 1 `two releases in flight: …`.
M.version = T with tag T on a commit other than M.sha → exit 1 (AC-129.19):
`ERROR: tag vX.Y.Z is on <tag sha>, not on the release's merge commit <M.sha>`. The same check (origin and local tag) runs
again immediately before `git tag`; a local `vX.Y.Z` already on M.sha is pushed instead of created.

### Order of checks in every run

1. `plugin_mismatches(repo)` (working tree files): for each `plugins/<name>/.claude-plugin/plugin.json` whose `version`
   differs from the `.claude-plugin/marketplace.json` entry → exit 1, one line per plugin
   `<name>: marketplace <v1>, plugin.json <v2>` (AC-129.5). Never writes either file.
2. `--version` syntax → exit 1 `--version <v> is not X.Y.Z semver`.
3. Detection (above) and the state block (always printed, also in a real run).
4. `--version` against a release in flight (any phase but `idle`) naming another version → exit 1
   `release X.Y.Z is in flight (<phase>): finish it first` (AC-129.18).
5. `--confirm` against the phase (above).
6. In `idle` only: `--version` not newer than T → `--version X.Y.Z is not newer than vT`; a major required and
   `--version` not a major → `--version X.Y.Z is not a major release; needs a major: <change>` (AC-129.3). Then the
   preflight (AC-129.4), first failure wins: `git config user.name`/`user.email` unset → `no git user for the DCO
   sign-off`; `git status --porcelain` not empty → `uncommitted changes: <paths>`; local `main` missing or ≠
   `origin/main` → `local main <sha> differs from origin/main <sha>`; `## [Unreleased]` of `origin/main:docs/CHANGELOG.md`
   blank → `## [Unreleased] in docs/CHANGELOG.md has no content`.

`--dry-run` stops after step 6 with exit 0 (or exit 1 where a check above fails) and runs nothing that writes: no
branch, commit, push, PR, merge, tag or release; it may fetch.

### Version proposal (AC-129.2)

`run_check(repo, [sys.executable, "scripts/release-check.py", "needs-major", "--base", T])` → `(rc, output)`. Each
non-empty output line is one change that needs a major release (exactly the text `rows` puts before
` needs a major platform release`); rc ≠ 0 → exit 1 with the output. No line → `T.major.(T.minor+1).0`; lines →
`(T.major+1).0.0`.

### Output (stdout)

```
state:
  newest release tag: v5.4.0 (1a2b3c4)
  release branch: absent | release/5.5.0
  release PR: absent | https://github.com/o/r/pull/341
  merged release commit: absent | 9f8e7d6 chore: release 5.5.0 (#341)
  tag v5.5.0: absent | on 9f8e7d6
  GitHub release v5.5.0: absent | https://github.com/o/r/releases/tag/v5.5.0
phase: idle | branch | pr-open | merged | tagged | guarding
version: 5.5.0 (<reason>)
steps:
  1. <step>
  2. …
```

`<reason>` is one of `minor after v5.4.0, no change needs a major release` · `major after v5.4.0: <change>[; <change>…]`
· `--version` · `release in flight`. The steps are numbered from 1, starting at the phase's first step, in this order and
with these texts (`X` the version, `D` today's date, `S` the merge commit when known, else `the merge commit`):

1. `check the working tree, main and docs/CHANGELOG.md` (idle)
2. `create release/X from main and move [Unreleased] under ## [X] - D` (idle, branch)
3. `run release-check rows and devbox run validate` (idle, branch)
4. `commit "chore: release X" (signed off), push release/X and open the PR` (idle, branch)
5. `wait for CI on the PR (the newest run of each workflow, the upgrade e2e included)`
6. `stop for confirmation: squash-merge the PR (cplat platform release --confirm merge)`
7. `wait for the upgrade e2e on S (up to 10 minutes for it to start)`
8. `run release-check gate S`
9. `stop for confirmation: tag vX (cplat platform release --confirm tag)`
10. `tag vX on S and push it`
11. `create the GitHub release vX with the ## [X] section as notes`
12. `wait for the release-guard run on vX`

Phase → first step: idle 1, branch 2, pr-open 5, merged 7, tagged 11, guarding 12.

Stops (exit 3):

```
CONFIRM: merge
  version: 5.5.0
  PR: <url>
  checks: <n> passed (newest run of each workflow), e2e upgrade (previous release → candidate): pass
  continue: cplat platform release --confirm merge
```

```
CONFIRM: tag
  tag: v5.5.0
  merge commit: <full sha>
  release notes:
--- release notes ---
<section body, verbatim>
--- end ---
  continue: cplat platform release --confirm tag
```

Finish (exit 0): `RELEASED: v5.5.0`, `  tag: https://github.com/<slug>/tree/v5.5.0`, `  release: <release url>`.

Failures name the subject: red PR check → the `ship.red` lines (check name and link) then `ERROR: CI is red on <url>: not merged`
(AC-129.10); upgrade e2e → `ERROR: upgrade e2e on <sha>: <did not start within 10 minutes | red: <run url> | still running after <timeout>s>`, no tag (AC-129.12);
gate / rows / validate → their output verbatim, then `ERROR: <release-check gate|release-check rows|devbox run validate> failed` (AC-129.7, AC-129.13);
release guard red → `ERROR: release-guard on vX.Y.Z is red: <run url>; the tag and the release stay` (AC-129.16).

### Prepare (idle → branch → pr-open)

- `git switch -c release/X main`; write `docs/CHANGELOG.md` with `move_unreleased(text, X, today())`:
  `## [Unreleased]` stays, followed by one blank line, `## [X] - YYYY-MM-DD`, a blank line, the former body (stripped),
  a blank line, then the rest of the file unchanged (AC-129.6).
- `branch` phase: switch to `release/X` if not on it (needs a clean tree); a dirty tree may hold only
  `docs/CHANGELOG.md`, else exit 1 `release/X has changes outside docs/CHANGELOG.md: <paths>`. If `## [X]` is already
  in the file, the move is not repeated.
- `run_check(repo, [sys.executable, "scripts/release-check.py", "rows", "--base", T])` then
  `run_check(repo, ["devbox", "run", "validate"])`; either rc ≠ 0 → print its output, exit 1; nothing committed (AC-129.7).
- No commit ahead of `origin/main` yet → `git add docs/CHANGELOG.md`, `git commit -s -m "chore: release X"` (git user from
  `git config`; exactly one commit, AC-129.8). `git push -u origin release/X`.
- `ship.gh(["pr", "create", "--base", "main", "--head", "release/X", "--title", "chore: release X", "--body", BODY])`,
  stdout's last line is the URL, printed as `PR: <url>`. BODY: `Release X: [Unreleased] of docs/CHANGELOG.md moved under ## [X].` +
  newline + `Opened by cplat platform release.`

### CI and merge (pr-open)

- `pr.wait(repo, url, merge=False, timeout, interval, ship.QUEUE_TIMEOUT, slug)`; not ok → print its lines, exit 1.
- Green → `ship.checks(repo, url)`; the check named `release-check.E2E_NAME`
  (`e2e upgrade (previous release → candidate)`) must be present with bucket `pass`, else exit 1
  `the upgrade e2e did not run on <url>`.
- Without `--confirm merge`: the merge stop. With it: `pr.wait(..., merge=True, ...)` (squash, `--match-head-commit`),
  then `ship.gh(["pr", "view", url, "--json", "mergeCommit", "-q", ".mergeCommit.oid"])` is S; `git fetch origin main`,
  `git switch main`, `git merge --ff-only origin/main` (failure is a note, not an error); continue with `merged`.

### Publish (merged → tagged → guarding)

- Upgrade e2e: `ship.gh(["run", "list", "-R", slug, "--workflow", "e2e-upgrade.yml", "--commit", S, "--event", "push",
  "--json", "databaseId,status,conclusion,url"])`, polled every `interval` until it lists a run, for at most
  `APPEAR_WINDOW = 600` s (`ship.now`/`ship.sleep`); the newest run is the highest `databaseId`; then `ship.RunWatch` until
  green or red or `--timeout` (AC-129.12).
- Gate: `run_check(repo, [sys.executable, "scripts/release-check.py", "gate", S])`, output printed (AC-129.13).
- Tag stop, or with `--confirm tag`: AC-129.19 check, `git tag -a vX -m vX S`, `git push origin refs/tags/vX`.
- Release: notes = `section_body(git show S:docs/CHANGELOG.md, X)` (the text between the `## [X]` line and the next
  `## [` line, leading and trailing blank lines removed) written to `<git dir>/RELEASE_NOTES.md`;
  `ship.gh(["release", "create", "vX", "-R", slug, "--title", "vX", "--notes-file", <path>, "--verify-tag"])`, its last
  stdout line the release URL (AC-129.15). Existing release: `ship.gh(["release", "view", "vX", "-R", slug, "--json", "url",
  "-q", ".url"], check=False)`, empty → absent.
- Release guard: `ship.gh(["run", "list", "-R", slug, "--workflow", "release-guard.yml", "--event", "push", "--limit", "50",
  "--json", "databaseId,headBranch,status,conclusion,url"])` filtered to `headBranch == "vX"`, same appearance window and
  newest-run rule, then `ship.RunWatch` (AC-129.16).

`slug` is `ship.service_slug(repo)`.

### Test seams (tests run offline)

- git runs for real (`core.run`): tests build a temporary repo with a local bare `origin` and push tags and branches to it.
- every `gh` call: `ship.gh` (as in `test_tags_and_wait.py`); the squash merge: `pr.run` (`gh pr merge …`), as there.
- `platrelease_state.run_check(repo: Path, cmd: list[str]) -> tuple[int, str]`: the only way release-check and
  `devbox run validate` are run (`cwd=repo`, stdout+stderr).
- `platrelease_state.today() -> datetime.date`; `ship.now`, `ship.sleep`, `ship.say`.
- `platrelease_publish.APPEAR_WINDOW` (600).

### `release-check.py needs-major [--base REF]`

Prints one line per change that needs a major release (operator major moves, removed rows, removed CRD versions, dropped
resource majors; the `needing` list `rows` builds today), nothing when none; exit 0, exit 1 with `ERROR: …` when it cannot
read the base. `rows` keeps its output and uses the same function.

### `/platform:release`

Runs `cplat platform release $ARGUMENTS` (background, read until it ends: the CI waits outlast one Bash call), shows the
output verbatim; on exit 3 it asks the user with the `CONFIRM:` block and, only on a yes in that conversation, runs it
again with the same `--version` and `--confirm merge|tag`; on exit 1 it reports the `ERROR:` line and stops. It never
merges, tags or releases by hand.

## Risks

- The e2e runs ~20–40 minutes; a run per wait is bounded by `--timeout`. A timeout exits 1 and a rerun picks up the wait.
- A release-guard run that never starts on an old tag would block the next release; the 10-minute window measured from the
  tagger date keeps an old tag `idle`, with a printed note.

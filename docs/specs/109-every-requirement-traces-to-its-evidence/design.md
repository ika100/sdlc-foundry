# Design — 109 Every requirement traces to its evidence

One read-only report on the existing `cplat spec trace` verb, plus one warning in `cplat spec ci`. No new store, no new
format, no ADR (see Decisions). The 5.x reading of the spec's changelog applies: "a service registered in a gitops-app" is
a component of a system that a linked gitops-app repo (`.platform-app.yml`) declares. See Risks for where its pins live.

## Decisions

- **The chain is a flag, the plain verb is untouched** (AC-109.1). `cplat spec trace <id> --chain [--json]` hands off to a
  new module `scripts/cplat/spec_chain.py`. Without `--chain`, the code path, output and exit code of `trace` and
  `trace --json` stay byte for byte as they are, because `cplat ship` (`ship.py:1490`) and `/component:build` read them.
- **Two new modules, split at the network boundary.** `spec_chain_remote.py` holds every `gh` call (one seam, one probe,
  one "down" flag) and the gitops-app reading. `spec_chain.py` holds the chain: local links, git reads, link states,
  rendering. The chain module never runs `gh` itself, so AC-109.9 and AC-109.12 can be checked in one place.
- **Remote reads have one budget** (AC-109.9, AC-109.12). The first remote need probes `gh` once:
  1. `which gh` → `gh not installed`;
  2. `gh auth token` (local, no network) → `gh not authenticated`;
  3. `gh api rate_limit` with a 10 s timeout → `GitHub not reachable`, or `gh not authenticated` on HTTP 401 / "Bad
     credentials".

  A failed probe, or any later call that times out, sets the remote as down with that reason, and no further `gh`
  call is made in the run. Offline, the run therefore makes at most one network attempt, of at most 10 s. All other
  work is local file and git reads on one spec, so 100 specs stay far below 30 s.
- **Nothing is written** (AC-109.12). Only `git` read commands run (`remote get-url`, `log`, `show`, `cat-file -e`,
  `merge-base --is-ancestor`, `tag --list --contains`, `rev-parse`). No `fetch`. `gh` is used only for `api` GETs,
  `issue view`, `pr list`. The run also avoids helpers that write: `runlist._merged_pr` keeps a PR cache file and
  `claim.claim` labels issues, so neither is called. A test runs the chain on a git repo and asserts that `git status
  --porcelain`, the refs and the mtime of every file are unchanged, and that the `gh` seam saw only read commands.
- **The PR is the newest merged PR from `feature/<spec_id>`** (AC-109.6), the branch `ship.py:257` records. The call is
  `gh pr list -R <slug> --head feature/<spec_id> --state merged --json number,url,mergeCommit,mergedAt --limit 20`,
  sorted by `mergedAt`, newest first. `<slug>` comes from `git remote get-url origin` (the parse `smoke._slug` uses).
- **The release comes only from local tags** (AC-109.7): `git tag --list 'v*' --contains <merge>`, filtered to
  `^v\d+\.\d+\.\d+$`, and the oldest by `core.vtuple`. First `git cat-file -e <merge>^{commit}` decides
  `unknown: merge commit not fetched`.
- **Environments come from the gitops-app, through the model** (AC-109.8). The linked repos are `ship.gitops_apps(repo)`.
  For each one, `model.load_remote(system, read)` runs for every `applications/<system>/`, with `read` going through the
  `gh` seam (default branch, as `staging._find` does). When `gh` is down, a local checkout is used instead: the sibling
  directory `<repo>/../<name>` (the clone layout `appship_sched.clone_path` uses) whose `origin` is that slug, read with
  `model.load_dir`. The component is `Model.find_component(<slug>, <repo name>)`. The pinned tag of an environment is
  `Model.instance(component, env).tag`. The instance exists because of `system.yaml` (`components.<c>.environments` /
  `instances`), and the tag is the overlay's `newTag` (`model.read_pin` / `pin_of`). The cluster is never read.
- **"Later release" is a version comparison; a commit pin is an ancestry check** (AC-109.8). `X.Y.Z` / `vX.Y.Z` pins
  (`evidence.RELEASE`) compare with `core.vtuple` against the release. `sha-<7..40>` pins resolve locally
  (`git rev-parse --verify -q <hex>^{commit}`), then `git merge-base --is-ancestor <merge> <pin>`.
- **Staleness compares the criteria, not commit dates** (AC-109.5, reading). A verification is stale when the acceptance
  criteria section at the verified commit hashes differently from the current one (`Spec.ac_hash` on `git show
  <commit>:<spec.md>`). Feature branches are squash-merged, so an ancestry test between "the commit that changed the
  criteria" on `main` and the branch commit the reviewer recorded would call every squash-merged spec stale. The
  content test gives the AC's meaning (the criteria changed after they were verified) without that false positive.
- **One tolerant verdict reader, local to the chain** (AC-109.4). It reads the table shapes in use (see Contract).
  `spec._verdicts` (the spec 122 console) is left as it is; see Risks.
- **Orphans are one scan, shared** (AC-109.3, AC-109.13). `spec.orphan_tests(root, specs, globs)` reads every test file
  once and returns each id `AC-<NNN>.<n>` whose `<NNN>` is one of the given specs' numbers but which is not one of that
  spec's active criteria. The chain calls it with one spec, `spec ci` with all of them.
- **No ADR.** The decisions are local to this report. The cross-cutting rule ("what cannot be read is `unknown`, never
  guessed") already holds in spec 093 (`evidence.py`), and this design follows it.

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `scripts/cplat/spec.py` | `orphan_tests()`; `ci()` prints orphan warnings; `trace` gains `--chain` and hands off to `spec_chain.main_chain` | changed |
| `scripts/cplat/spec_chain_remote.py` | `gh` seam and probe, issue states, merged PRs, gitops pins (remote or local checkout) | new |
| `scripts/cplat/spec_chain.py` | the chain: link resolution, verdict reader, staleness, release, environments, text and JSON | new |
| `docs/HOW-IT-WORKS.md`, `docs/CHANGELOG.md` | one sentence on the chain and the orphan warning; [Unreleased] entry | changed |

No plugin file changes, so no plugin version bump.

## Contract

### Command

`cplat spec trace <ref> --chain [--json] [--repo DIR]`. `<ref>` is anything `spec.find` accepts.

- Exit 0 whenever the chain was printed, whatever the link states (AC-109.11). There is no `--strict`.
- A spec that cannot be found or read: `spec.find` raises `PlatformError` / `BrokenSpec`. `cplat` prints
  `ERROR: no single spec matches '<ref>' …` or `ERROR: <rel>, line <n>: …`, and the exit is 1. Both messages name the spec.
- An unexpected exception inside one link's resolver never ends the run: that link becomes `unknown: <ExceptionType>:
  <message>`.
- `--json` without `--chain` stays as it is today.

### Links and states

The links are, in this order: `issue`, `spec`, `criterion`, `tests`, `verdict`, `pr`, `release`, `env dev`,
`env staging`, `env prod`. Each link has a state (`ok`, `missing`, `stale`, `unknown`, `n/a`) and a text. It is rendered
`<state>: <text>`. The criteria are the spec's active ones, in spec order. The spec-level links (issue, spec, pr, release,
env) are the same in every block.

"Pre-done" means the spec's status is `draft`, `approved` or `building`. Then:

| Status | tests when none found | verdict, pr, release, env * |
|---|---|---|
| `draft` | `n/a: spec not yet approved` | `n/a: spec not yet built` |
| `approved` | `missing: no test names it` | `n/a: spec not yet built` |
| `building` | `missing: no test names it` | `n/a: spec not yet done` |
| `done` | `missing: no test names it` | resolved as below |
| `superseded` (reading) | `n/a: spec superseded` | `n/a: spec superseded` |

A spec whose own shape is `gitops-app` (a product spec, non-goal) shows `n/a: product spec: traced in its component
repos` on tests, verdict, pr, release and every env.

| Link | ok | missing | stale | unknown | n/a |
|---|---|---|---|---|---|
| issue (AC-109.10) | `#164 closed[, #170 open]` (all closed, or any state on a pre-done spec) | – | `issue still open (#170[, #171])` on a `done` spec | `<reason> (#164[, #170])` | `no tracked issue` |
| spec | `<status>` | – | – | – | – |
| criterion | `<AC id>` | – | – | – | – |
| tests (AC-109.1, AC-109.2) | the files from `spec.trace`, comma-separated | `no test names it`; a `(smoke)` criterion without a smoke-tagged file: `no smoke-tagged test` | – | – | see the status table |
| verdict (AC-109.4, AC-109.5) | `met[ (<qualifier>)]` | `not verified` (no row); `not met` / `partial[ (<qualifier>)]`; `verdict '<cell>' not readable`; no verification.md: `no verification.md (unverified: <reason>)` or `no verification.md` | `criteria changed after verification (<commit>)`; `verified a withdrawn criterion (<AC id>)`; `verified an unknown criterion (<AC id>)` | `<why the verified commit cannot be read>` | see the status table |
| pr (AC-109.6) | `#<n> merged <YYYY-MM-DD> (merge <sha7>)`, plus `; also merged: #<a>, #<b>` when there are several | `no merged PR from feature/<spec_id>` | – | `<gh reason>`; `no GitHub origin remote` | see the status table |
| release (AC-109.7) | `v<X.Y.Z>` | `merged, not in a release` | – | `merge commit not fetched`; `needs the PR (<reason>)` | `no merged PR` |
| env dev/staging/prod (AC-109.8) | `runs <tag>` | `runs <tag>, older than <release>` (`older than merge <sha7>` when there is no release); `<repo slug> is not a component in <app slugs>` | – | `gitops-app <slug> not reachable (<reason>)`; `pinned commit <sha7> not fetched`; `merge commit not fetched`; `tag <tag> is neither a release nor sha-<commit>`; `needs the PR (<reason>)` | `not deployed to <env>`; `library: no environments`; `not linked to a gitops-app (no .platform-app.yml)`; `no merged PR` |

Rules behind the table:

- **Issue.** The issues are the spec's `tracks:` numbers, read with `gh issue view <n> -R <slug> --json number,state`.
  When `gh` is down, the link is `unknown` for every status (the AC-109.9 rule: never `ok` unchecked).
- **Verdict.** Only verdict links of a `done` spec are resolved, in this order:
  1. no verification.md → `missing`;
  2. the verified commit cannot be read → `unknown`;
  3. stale → `stale`, applied to every verdict link of the spec;
  4. the criterion's row.
  The overall `**Result:**` is not a link. It shows in the header line.
- **Environments.**
  - An environment where the component has no instance, or where the instance has no tag, is `n/a: not deployed to
    <env>`.
  - A release pin is `ok` when its version is ≥ the release.
  - With no release, a release pin is `missing … older than merge <sha7>`, unless `v<X.Y.Z>` is a local tag that
    contains the merge (then `ok`).
  - The library rule uses `model.type_lang(<repo shape>)[0] == "library"`.
  - A repo without `.platform-app.yml` (the platform repo itself, or an unlinked repo) gets the "not linked" n/a.
- **Complete.** A criterion's chain is complete when every one of its links is `ok` or `n/a`.

### Verdict reader (verification.md)

- **Table.** The reader uses the first Markdown table whose header row has a `Criterion` cell and a `Verdict` cell
  (case-insensitive, any column positions; tables with 3 or 5 columns are both in use). Then it reads every later table
  with the same header (spec 088 and 114 have several). Files without such a header fall back to "first cell, second
  cell".
- **Criterion cell.** The first `AC-\d{3,}\.\d+(?!\d)` in the cell is the id, so `AC-127.2 (amended)` reads as
  AC-127.2.
- **Verdict cell.** It is lower-cased and stripped of backticks and `*`. Then the prefixes are checked in this order:
  `not met` → not met, `partial` → partial, `met` → met. Whatever follows is the qualifier, so
  `met (cluster part pending CI)` is met with a qualifier. Anything else is "not readable".
- **Several rows for one id.** The first row wins: reviewers put the newest cycle first, as spec 088 does.
- **Verified commit.** It is `**Commit:**\s*([0-9a-f]{7,40})` when that commit exists locally (`git cat-file -e`).
  Otherwise it is the newest commit that touched verification.md (`git log -1 --format=%H -- <verification.md>`).
  verification.md not committed yet: the working tree counts as the verified state. The verified commit is a shallow
  boundary (`.git/shallow` lists it): `unknown: shallow clone: verification history not available`.
- **Stale: criteria changed.** `ac_hash(<spec.md at the verified commit>) != spec.ac_hash()`. `<commit>` is the short
  sha of the commit that last changed the criteria, found by walking `git log --format=%h -- <spec.md>` newest first:
  the newest commit whose criteria hash equals the current one while the next older version's hash differs. If the
  working tree's criteria differ from HEAD's, `<commit>` is `uncommitted`.
- **Stale: withdrawn or unknown criterion.** Any row whose id has this spec's number but is not an active criterion
  makes the verification stale.
- **Unverified reason.** The newest changelog line `- <date> done: unverified: <reason>` (written by `spec.set_status`).

### Orphan tests (AC-109.3, AC-109.13)

`spec.orphan_tests(root: Path, specs: list[Spec], globs: list[str]) -> list[Orphan]`. Here
`Orphan = (file: str, id: str, spec_id: str, kind: "withdrawn" | "unknown")`, sorted by file, then id.

- It reads the files matched by `globs` once, skipping `spec._ignored` paths, and finds `spec.AC_ANY`.
- Withdrawn: the id is a `~~**AC-…**~~` line of that spec.
- Unknown: the id is not in the spec at all.
- An id whose number is no spec's number is never reported.

In the chain, the globs are `test_globs(spec_shape(spec, repo_shape))` (the same as `trace`), and the orphans are listed
after the gap list:

```
orphan tests:
  tests/cplat/test_x.py AC-109.4: stale: names withdrawn AC-109.4
  tests/cplat/test_y.py AC-109.14: stale: names unknown AC-109.14
```

`orphan tests: none` when there are none.

In `spec ci`, the globs are the union of `test_globs(spec_shape(s, repo_shape))` over all readable specs. One warning per
orphan, always `::warning`, also with `--strict`:

```
::warning file=<file>,title=spec <spec_id>::<file> names <withdrawn|unknown> criterion <id>
```

Then one line `spec-check: <k> orphan test reference(s) (warnings only)` when k > 0. Orphans are not counted in
`problems`, so the existing summary line and the exit code are unchanged (AC-109.13).

### Text output

```
chain: 109-every-requirement-traces-to-its-evidence (done, verification: pass)
AC-109.1
  issue        ok: #164 closed
  spec         ok: done
  criterion    ok: AC-109.1
  tests        ok: tests/cplat/test_109_chain.py
  verdict      ok: met
  pr           ok: #301 merged 2026-10-30 (merge 1a2b3c4)
  release      ok: v5.4.0
  env dev      n/a: not linked to a gitops-app (no .platform-app.yml)
  env staging  n/a: not linked to a gitops-app (no .platform-app.yml)
  env prod     n/a: not linked to a gitops-app (no .platform-app.yml)
AC-109.2
  …
summary: 12/13 criteria have a complete chain (1 missing, 0 stale, 0 unknown links)
missing or stale:
  AC-109.13 tests: missing: no test names it
orphan tests: none
```

- The header is `chain: <spec_id> (<status>[, verification: <pass|fail|none>])`. The verification part is shown for
  `done` only.
- Each criterion block is the id on its own line, then one line per link: two spaces, the link name left-justified to
  12 characters, a space, then `<state>: <text>`.
- `summary:` counts criteria with a complete chain out of the active criteria, then the link counts per state over all
  blocks (`missing`, `stale`, `unknown`).
- `missing or stale:` lists `<AC id> <link>: <state>: <text>` in block order, or reads `missing or stale: none`.
- When something could not be reached, the last line is one note (AC-109.9):
  `note: not reached: gh (<reason>)[, gitops-app <slug> (<reason>)]; the links that need them are unknown`. With
  nothing unreached there is no note line.

### JSON output (`--chain --json`)

```json
{
  "spec": "109-every-requirement-traces-to-its-evidence",
  "status": "done",
  "verification": "pass",
  "repo": "ika100/sdlc-foundry",
  "criteria": [
    {"id": "AC-109.1", "complete": true, "links": [
      {"link": "issue", "state": "ok", "text": "#164 closed", "issues": [{"number": 164, "state": "closed"}]},
      {"link": "spec", "state": "ok", "text": "done"},
      {"link": "criterion", "state": "ok", "text": "AC-109.1"},
      {"link": "tests", "state": "ok", "text": "tests/cplat/test_109_chain.py", "files": ["tests/cplat/test_109_chain.py"]},
      {"link": "verdict", "state": "ok", "text": "met", "verdict": "met"},
      {"link": "pr", "state": "ok", "text": "#301 merged 2026-10-30 (merge 1a2b3c4)", "number": 301,
       "url": "https://github.com/ika100/sdlc-foundry/pull/301", "merge_commit": "<40 hex>", "merged_at": "2026-10-30T10:00:00Z",
       "others": []},
      {"link": "release", "state": "ok", "text": "v5.4.0", "tag": "v5.4.0"},
      {"link": "env dev", "state": "n/a", "text": "not linked to a gitops-app (no .platform-app.yml)", "tag": null}
    ]}
  ],
  "summary": {"criteria": 13, "complete": 12, "missing": 1, "stale": 0, "unknown": 0},
  "gaps": [{"criterion": "AC-109.13", "link": "tests", "state": "missing", "text": "no test names it"}],
  "orphans": [{"file": "tests/cplat/test_y.py", "id": "AC-109.14", "kind": "unknown", "state": "stale",
               "text": "names unknown AC-109.14"}],
  "unreached": [{"what": "gh", "reason": "gh not authenticated"}],
  "note": null
}
```

- Every link has `link`, `state` and `text`. The extra keys are as shown: `issues`, `files`, `verdict`
  (`met|not met|partial|null`), the `pr` fields, `tag` on release and env. They are `null` or `[]` when not resolved.
- `note` is the note line's text, or `null` when there is none. `verification` is `null` for specs that are not `done`.

### Remote module API (`spec_chain_remote.py`)

```python
TIMEOUT = 10
def gh(args: list[str], *, cwd: Path, timeout: float = TIMEOUT) -> tuple[int, str, str]   # seam: rc, stdout, stderr; rc 124 on timeout, 127 when missing
def which(tool: str) -> str | None                                                         # seam: shutil.which

class Remote:
    def __init__(self, repo: Path): ...          # lazy: nothing runs until the first call
    slug: str | None                             # from `git remote get-url origin`, None without a GitHub origin
    def down(self) -> str | None                 # None when gh is usable, else the reason; probes once
    def issues(self, numbers: list[int]) -> dict[int, str] | str          # number -> "open"/"closed", or the reason
    def merged_prs(self, branch: str) -> list[dict] | str                 # newest first: number, url, merge_commit, merged_at; or the reason
    def pins(self, apps: list[str], service: str) -> Pins | str           # or "gitops-app <slug> not reachable (<reason>)"
    unreached: list[dict]                         # {"what", "reason"} collected for the note

@dataclass
class Pins:
    source: str                  # "<slug> (default branch)" or "<path> (local checkout)"
    system: str | None           # None when no system lists the component
    component: str | None
    tags: dict[str, str | None]  # env -> pinned tag; an env without an instance is absent
```

## Risks

- **The changelog reading names the wrong file.** The spec's 2026-10-28 changelog line says that the pins are read from
  `instances.<env>` in system.yaml. In 5.x code, system.yaml decides which instances exist, and the image tag is the
  overlay's `newTag` (`model.pin_path`, `templates/gitops-app/scripts/pin.py`, `render.py:20`). The design reads both
  through `model` (`Instance.tag`). That meets AC-109.8 as written ("read from the gitops-app, never from the
  cluster"). The changelog line should be corrected; this does not change `spec_hash`.
- **Acceptance tests must not plant orphans in the platform repo.** A test file that names a literal unknown or
  withdrawn id of a real spec (for example `AC-109.14`) is itself an orphan, and the platform's own `spec ci` would warn
  about it. Tests should build fixture repos with a scratch spec number (for example 901), or assemble the id at run
  time.
- **Local checkouts can be stale.** A sibling checkout is read as it is, and never fetched (AC-109.12). The `source`
  names it so the reader knows. `gh` is preferred whenever it is up.
- **Squash merges hide intra-branch history.** When the recorded commit is gone, the fallback is the commit that brought
  verification.md to `main`, usually the squash commit itself. A criteria change and a re-verification inside one PR
  then read as "not stale", which is the correct state of `main`.
- **Two verdict readers.** `spec._verdicts` (console, spec 122) stays strict, so it shows `not judged` for `met (…)`
  and `AC-127.2 (amended)`. Moving the console to the chain's reader is a small follow-up, outside this spec.
- **Shallow CI clones** turn the verdict and release links `unknown`, never `ok` or `missing`. That is AC-109.9's rule
  applied to git.

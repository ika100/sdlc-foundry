# Design — 223 Change quality: fix causes and attempts to done

## Decisions

- **One pure module owns the cause line** (`scripts/cplat/fixcause.py`): its form, its parse, the split of a `### Fixed` section into entries and the numbers an entry names. pr-check, the CI fragment check and change-quality all import it, so the three never disagree on what a valid cause is (AC-223.1, AC-223.4).
- **`parse_fragment` stays as it is.** The release still assembles a `fixed` fragment without a cause line, because fragments merged before this spec have none and must still release; the cause is checked only on fragments a branch *adds* (`git diff --diff-filter=A <base>...HEAD`). Nothing in the release rewrites entry text, so the cause line reaches `docs/CHANGELOG.md` unchanged (AC-223.3).
- **The CI fragment check is a new `scripts/release-check.py fragments --base REF`** run in the existing `release-check` job with the PR's base (`origin/$GITHUB_BASE_REF`, on a push `HEAD~1`). It checks the form only (A3). `rows` is left alone: its base is the last tag, and the unreleased fixed fragments already on main have no cause line.
- **pr-check verifies against GitHub, and only says WARNING when GitHub cannot answer.** `gh api repos/<slug>/pulls/<n>` (404: not a PR, `merged_at` null: not merged) and `gh api repos/<slug>/git/ref/tags/v<X.Y.Z>` (404: no tag); any other failure (no network, no login, 5xx after `core.run`'s retries) is "unreachable". Warnings go into pr-check's `notes`, printed as `WARNING: …` lines, so the exit code stays the problems' (AC-223.2).
- **A PR's release comes from git first, GitHub second.** Squash merges end their subject in `(#N)`; change-quality maps `N` to that commit on `HEAD`'s history, falls back to `gh api repos/<slug>/pulls/<n>` → `merge_commit_sha`, then takes the lowest `v*` tag that contains it (`git tag --contains <sha> --list 'v*'`). No tag: `Unreleased`. The report thus works offline for the common case.
- **change-quality is its own command and its own two modules** (`changequality_sources.py` for git, gh, fleet and `docs/PERFORMANCE.md`; `changequality.py` pure aggregate, render, CLI), not a section of `runs report`: it reads the repo, not the run store (A6).
- **Chains are a new pure module `runs_chains.py`**, called from `runs_report.aggregate` and `render_text`; `runs_report.py` is already near 700 lines and this keeps the new figures testable alone (AC-223.7 to AC-223.9).
- **ADR (to create):** "A platform fix entry names its cause in a closing `Caused by:` line, and change-quality derives the change-failure rate from it" — this extends ADR-078's fragment format and outlives the feature. Created with `cplat adr add fix-entries-name-their-cause --decision "…"`.

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `scripts/cplat/fixcause.py` | cause line form/parse, entry split of a Fixed section, entry numbers, GitHub verification (gh seam) | new |
| `scripts/cplat/house_rules.py` | `fragment` rule: cause line of added `fixed` fragments, verification, WARNING notes | changed |
| `scripts/release-check.py` | `fragments [--base REF]` subcommand (form only) | changed |
| `.github/workflows/ci.yml` | `release-check` job runs `fragments` | changed |
| `scripts/cplat/changequality_sources.py` | releases from the changelog, fix entries of releases and fragments, PR → release, tags, journeys, fleet stamp history | new |
| `scripts/cplat/changequality.py` | aggregate, text and JSON render, `main` | new |
| `scripts/cplat/cplat.py` | `platform change-quality` verb and its usage line | changed |
| `scripts/cplat/runs_chains.py` | chain grouping, attempts, costs, summary, text lines | new |
| `scripts/cplat/runs_report.py` | `aggregate` adds `chains`; `render_text` adds the `Chains:` block | changed |

## Contract

### Cause line (AC-223.1 to AC-223.3)

The last non-blank line of a fix entry, written directly under the entry text (no blank line, so the entry stays one paragraph):

```
Caused by: #812
Caused by: #812, #815
Caused by: v5.23.0
Caused by: none
Caused by: unknown
```

Regex (whole line, after `strip()`): `^Caused by: (?:#\d+(?:, #\d+)*|v\d+\.\d+\.\d+|none|unknown)$`.

```python
@dataclass(frozen=True)
class Cause:
    kind: Literal["prs", "version", "none", "unknown"]
    prs: tuple[int, ...] = ()        # kind "prs"
    version: str | None = None       # kind "version", "X.Y.Z" without the v

def parse_cause(entry: str) -> Cause | None          # None: the last line is not a valid cause line
def form_error(path: str, text: str) -> str | None   # None for added/changed fragments and valid fixed ones
def entries(fixed_section: str) -> list[str]         # paragraphs; a paragraph that is only a cause line joins the one before
def numbers(entry: str, fragment_id: str | None = None) -> set[int]   # every `(#NNN)` outside the cause line, plus the fragment's numeric id
def verify(slug: str, cause: Cause, *, gh=None) -> tuple[list[str], list[str]]   # (errors, warnings)
```

**pr-check messages** (each one `ERROR:` line, prefix `changelog fragment:` like the existing fragment problems):

- missing or malformed: `changelog fragment: docs/changelog.d/<name>: a fixed fragment ends in a cause line; expected Caused by: #<PR> | v<X.Y.Z> | none | unknown`
- not a merged PR: `changelog fragment: docs/changelog.d/<name>: Caused by #<n> is not a merged PR of <slug>`
- no tag: `changelog fragment: docs/changelog.d/<name>: Caused by v<X.Y.Z> names no tag of <slug>`
- unreachable (a note, printed `WARNING: …`, exit unchanged): `WARNING: changelog fragment: docs/changelog.d/<name>: GitHub unreachable, Caused by #<n> was not checked (<first line of gh's error>)` (same with `v<X.Y.Z>` for a tag).

`<slug>` is `gh repo view --json nameWithOwner` in the repo; when that call fails, every PR or tag check of the run is "unreachable". With `--json` the warning lines are in `notes`.

**CI** (`uv run scripts/release-check.py fragments --base <ref>`): the same missing/malformed `ERROR:` line (prefixed `ERROR: `), `FAILED: <n> problem(s)` and exit 1; otherwise `OK: <n> added fixed fragment(s) name a cause` and exit 0. No network.

**Release**: `assemble` copies the fragment body (only `../` links rewritten), so the released entry ends in the same `Caused by: …` line.

### `cplat platform change-quality [--since v<X.Y.Z>] [--json] [--repo DIR]` (AC-223.4 to AC-223.6)

Runs in the platform repo only: without `<repo>/.claude-plugin/marketplace.json` it raises `PlatformError("change-quality runs in the platform repo ika100/sdlc-foundry (no .claude-plugin/marketplace.json here)")` (the slug from `feedback.REPO`), exit 1, nothing on stdout.

**Inputs**

- Releases: every `## [X.Y.Z] - YYYY-MM-DD` heading of `docs/CHANGELOG.md`.
- Fix entries: `fixcause.entries()` of each released section's `### Fixed` (carrier: that version), plus every `fixed` fragment in `docs/changelog.d` (carrier: `Unreleased`, numbers include the fragment id).
- Window: releases with version ≥ `--since` (a version with no heading: `PlatformError`), else releases dated within the last 90 days.

**Attribution of one entry** (carrier `C`):

1. No cause line, or `unknown` → `unattributed`.
2. `none` → `none` (listed, counts for no release).
3. `v<X.Y.Z>` → cause release `X.Y.Z` (no such heading → `unattributed`, reason `no release X.Y.Z`).
4. `#n…` → each PR's release (git subject `(#n)`, else gh `merge_commit_sha`, then lowest containing `v*` tag, else `Unreleased`; not found → `unattributed`, reason `#n not found`).
5. Cause releases strictly before `C` (by version; `Unreleased` is after every version) are *caused*; when the only cause release is `C` itself → `caught_before_release`; a cause release after `C` → `unattributed`, reason `cause after the fix`.

`caught_before_release`, `unattributed` and `none` count the entries carried by a release in the window or by `Unreleased`; `caused` is attributed to every window release whatever the carrier.

**Blast radius per release R with `caused` entries**

- `carried_by`: the distinct carriers of those entries, by version.
- `stopped_journeys`: numbers of the `docs/PERFORMANCE.md` journey rows (a table row whose first cell is an integer and whose text contains `**stopped`) that name any `#N` in `numbers()` of those entries.
- `affected_repos`: fleet repos (gh login's repos, not archived, not forks, `.platform-version` plus a platform `.copier-answers.yml`, as `fleet update` lists them) whose `.platform-version` history (`gh api --paginate repos/<slug>/commits?path=.platform-version`, each version read at its commit) held a version `v` with `R ≤ v < first carrier` (no upper bound when the first carrier is `Unreleased`). Any gh failure on the way → the string `"unknown"` and a reason; never `[]`. Read only when some release caused an entry.

**change-failure rate**: releases of the window with ≥ 1 `caused` entry, over releases of the window; `_minor` the same over releases with patch `0`. `pct` = `floor(100·failed/releases + 0.5)`, `null` for 0 releases.

**Text** (stdout, progress on stderr):

```
Change quality <first> to <last> (<n> releases<, since vX.Y.Z | , last 90 days>)
Releases (fix entries caused, carried by; stopped journeys; downstream repos):
  5.30.0: 2, carried by 5.30.1; stopped journeys: 14; repos: 2 (o/a, o/b)
  5.30.1: 0
  5.31.0: 0
caught before release: 1
unattributed: 1
none (not from a platform change): 0
change-failure rate: 1 of 3 releases (33%)
change-failure rate, minor and major releases: 1 of 2 releases (50%)
```

`stopped journeys: none` when empty; `repos: unknown (<reason>)` when unreadable; `0 of 0 releases (n/a)` without releases. Each `none` entry follows its count as `  <carrier>: <first 100 chars of the entry>`.

**JSON** (`--json`: exactly this document on stdout, nothing else):

```json
{
  "window": {"since": "v5.30.0" | null, "days": 90 | null, "from": "5.30.0", "until": "5.31.0", "releases": 3},
  "releases": [
    {"version": "5.30.0", "date": "2026-11-24",
     "caused": [{"carrier": "5.30.1", "cause": "#812", "entry": "<first 100 chars>"}],
     "carried_by": ["5.30.1"], "stopped_journeys": [14],
     "affected_repos": ["o/a", "o/b"] | "unknown", "affected_reason": null | "<why unknown>"}
  ],
  "caught_before_release": [{"carrier": "5.31.0", "cause": "#900", "entry": "…"}],
  "unattributed": [{"carrier": "5.31.0", "cause": null | "unknown" | "#n" | "vX.Y.Z", "reason": "no cause line" | "unknown" | "…", "entry": "…"}],
  "none": [{"carrier": "5.31.0", "entry": "…"}],
  "change_failure_rate": {"failed": 1, "releases": 3, "pct": 33},
  "change_failure_rate_minor": {"failed": 1, "releases": 2, "pct": 50}
}
```

The counts of the text are the lengths of these lists.

### `runs report` chains (AC-223.7 to AC-223.9)

```python
CHAIN_KINDS = ("ship", "product-ship", "build", "fix")
def aggregate_chains(kept: list[dict], *, window_start: datetime.datetime) -> dict
def chain_lines(chains: dict) -> list[str]
```

- Key: `(repo, "spec", spec)` when `spec` is set, else `(repo, "issue", n)` with `n` from `issue.number` (a dict) or `issue` (an int); neither → `unchained`. Benchmark records (`kind benchmark`, `benchmark_of`) are left out.
- Attempt: a chain record whose `parent` is not the `run_id` of another record of the chain; ordered by `started_at`, then `ended_at`, then `run_id`. Other records are children.
- Cost of a record: `usage.totals.cost_usd` when a number and `cost_complete` is not `false`, else unknown. Chain cost: the sum over its records, each run_id once; `cost_complete` false when any record's cost is unknown.
- Done: some attempt has outcome `done`. `attempts_to_done`: 1-based index of the first done attempt. Successful run: that attempt plus its descendants in the chain. `outside_pct` = `floor(100·(chain − successful)/chain + 0.5)`, null when either is unknown or chain is 0.
- `partial`: the earliest `started_at` of the chain is before `window_start`.
- `cost_per_delivered`: sum of done chains with complete cost / their number (null when none); `median_successful_cost` over those chains' successful runs with known cost; `open_spend`: known cost of the chains not done; `median_attempts_to_done` over done chains.

JSON, under the new top-level key `chains` (all existing keys unchanged):

```json
{"items": [{"repo": "o/r", "kind": "spec", "id": "131", "attempts": 3, "escalations": 1, "abandons": 1, "failed": 0,
            "done": true, "attempts_to_done": 3, "cost_usd": 7.5, "cost_complete": true,
            "successful_cost_usd": 2.0, "outside_pct": 73, "partial": false, "run_ids": ["…"]}],
 "done": 1, "open": 0, "median_attempts_to_done": 3, "cost_per_delivered": 7.5,
 "median_successful_cost": 2.0, "open_spend": 0.0, "unchained": 0}
```

Text, after the person-time block (`attempt`, `escalation` and `abandon` take an `s` for any count but 1; `failed` never changes):

```
Chains:
  o/r spec 131: 3 attempts, 1 escalation, 1 abandon, 0 failed, attempts to done: 3, chain cost $7.50, successful run $2.00, spent outside the successful run: 73%
  o/r issue 42: 1 attempt, 1 escalation, 0 abandons, 0 failed, not done, chain cost >= $1.20 +unknown (partial)
  done 1, not done 1; median attempts to done: 3; cost per delivered item: $7.50 (median successful run $2.00); spend of chains not done: $1.20
  unchained: 0
```

`Chains: none` (then `unchained: <n>`) when no chain is in the window. Money without a value prints `unknown`; a median or rate without a value prints `n/a`.

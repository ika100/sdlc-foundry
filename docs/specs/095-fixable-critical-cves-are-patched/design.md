# Design — 095 Fixable dependency CVEs are patched without asking

## Decisions

- **One tested command, `cplat deps`, does the whole patch loop.** It finds the gate-red findings, bumps through the
  repo's recipe, re-runs the gates, commits or reverts, counts rounds, writes the run record and prints the PR table.
  The markdown commands only call it and act on its exit code: 0 continue, 3 escalate with the printed reason, 4 not
  a dependency finding (handle the red gate as today). A new module keeps `ship.py`, `runs.py` and `update.py` free of
  edits, because specs 088, 089 and 096 change them in parallel. `ship.py` needs no change: a red PR check already
  counts as a `fix_rounds` round in `cplat ship land`, so a patch in `land` counts toward the limit of 3 (AC-095.15).
  ADR: [docs/adr/034-fixable-dependency-findings-are-patched-by-the-run.md](../../adr/034-fixable-dependency-findings-are-patched-by-the-run.md).
- **Two recipes per shape are the contract: `deps-findings` and `deps-bump`** (AC-095.3). Both are `bash scripts/deps.sh
  findings|bump`, so the logic sits in a platform-owned file, not in a one-line recipe. cplat never calls
  `uv`/`pnpm`/`go`/`mvn`/`trivy` itself. `gitops-app` gets neither recipe and `cplat deps` refuses it (AC-095.16).
- **Findings come from a machine-readable report of the same scanner as the gate, at the gate's threshold.** Each
  shape's `deps-findings` writes the scanner's raw JSON report. A pure parser per tool (`deps_parse.py`) keeps only
  what turns the gate red: pip-audit, every finding; pnpm audit, `--prod` at high and critical; govulncheck, called
  symbols only; trivy, HIGH and CRITICAL. The image scan and base-image OS packages are never read (AC-095.16,
  spec 059 unchanged).
  - **Java exception.** OWASP Dependency-Check names no fixed versions, so the Java `deps-findings` always uses
    `trivy fs` at HIGH,CRITICAL. That is the gate's own fallback, and trivy HIGH means CVSS 7 or more. The real gate
    (OWASP with `NVD_API_KEY`) still decides green or red after the bump.
- **The gates are re-run as `devbox run ci` runs them, one step at a time** (AC-095.12). cplat runs `devbox run
  <step>` for each step of the repo's `ci` recipe (`gates.chain`), in order, and stops at the first red one. Those are
  the same commands with the same result, and cplat then knows which gate failed (AC-095.6). `ci-extra` runs only
  when the repo defines it, exactly like the recipe's last step.
- **A round bumps every fixable package at once, one commit per package, then runs the gates once.** One package per
  round would use up the 2 rounds on the first two packages of a typical audit. What a red gate does to the round:
  - security red, and only fixable findings left (a bump revealed another one) → the round's bumps stay and the next
    round runs, in the same call (AC-095.14);
  - red in any other way → the whole round is reverted (AC-095.6);
  - a third round needed → escalate. The bumps already made stay committed, because each one fixed its own finding,
    and the reason lists the findings still open.
- **Nothing is bumped while any gate-red finding cannot be fixed** (no fix released, or a Go toolchain finding).
  The gate would stay red anyway, so the run escalates at once and no file changes (AC-095.13).
- **Revert = the dependency files byte-equal to the snapshot taken before the round** (AC-095.6). The round's commits
  are removed with `git reset --soft <pre-round sha>`, the dependency files are restored from the snapshot in index
  and work tree, and every other file, staged or not, is left alone. cplat touches no file outside the shape's
  dependency files, so no acceptance test can change.
- **Rounds are counted per run.** The key is the run's `run_id`: the `cplat runs` pointer of `/svc:build` first, then
  the unfinished ship run (`runs.attach_point`). Without either, the key is `branch:<current branch>`. A resumed ship
  run is a new run (spec 087), so it starts with 2 fresh rounds after the user stepped in.
- **Severity is the scanner's own value.** pip-audit and govulncheck report none, so their findings show `UNRATED`.
- **Grouping is per package.** Several advisories of one package become one bump. The target is the highest of their
  lowest fixed versions, so one bump fixes all of them. The severity shown is the highest, and the advisory ids are
  joined with `, `.

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `scripts/cplat/deps_parse.py` | pure: version compare, per-tool report parsers, grouping, lowest fixed version, major and transitive flags | new |
| `scripts/cplat/deps.py` | `cplat deps findings|patch|report`, the round loop, snapshot and revert, commits, round state, run record `patches`, PR-body section | new |
| `scripts/cplat/cplat.py` | `"deps": "deps"` in `COMMANDS`, one docstring line | changed |
| `scripts/shapes.py` | shape contract: `deps-findings` and `deps-bump` in every non-gitops template, in no gitops-app template | changed |
| `templates/{service,library}-python/scripts/deps.sh`, `scripts/deps_pyproject.py`, `devbox.json` | uv recipes | new / changed |
| `templates/web-nextjs/scripts/deps.sh`, `scripts/deps-override.mjs`, `devbox.json.jinja` | pnpm recipes | new / changed |
| `templates/service-go/scripts/deps.sh`, `devbox.json.jinja` | go modules recipes | new / changed |
| `templates/service-java/scripts/deps.sh`, `scripts/PomDeps.java`, `devbox.json.jinja` | maven recipes | new / changed |
| `plugins/svc/commands/build.md`, `ship.md`, `plugins/shared/agents/security.md` | call `cplat deps patch` on a red security gate and put `cplat deps report` in the PR body and final report | changed |

## Contract

### Template recipes (AC-095.3, AC-095.2)

```
"deps-findings": "bash scripts/deps.sh findings",
"deps-bump":     "bash scripts/deps.sh bump",
```

The exact strings are the same in all five templates. `scripts/deps.sh` ignores a leading `--` argument. It runs with
`set -euo pipefail` and changes no file outside the shape's dependency files (table below).

**`devbox run deps-findings <out-file>`** writes the scanner's raw JSON report to `<out-file>`. It exits 0 when the
report was written, with or without findings, and non-zero when the scanner itself failed (the last stderr lines say
why).

| Shape | Report command (inside deps.sh) | Report format |
|---|---|---|
| service-python, library-python | `uv run pip-audit -f json -o <out>` (exit 1 with findings is not a failure) | pip-audit JSON: `{"dependencies": [{"name", "version", "vulns": [{"id", "fix_versions", "aliases"}]}]}` |
| web-nextjs | `pnpm audit --prod --json > <out>` | pnpm audit JSON: `{"advisories": {"<n>": {"module_name", "severity", "patched_versions", "github_advisory_id", "findings": [{"version", "paths"}]}}}` |
| service-go | `govulncheck -json ./... > <out>` | govulncheck JSON stream: `{"osv": {...}}` and `{"finding": {"osv", "fixed_version", "trace": [{"module", "version", "package", "function"}]}}` objects |
| service-java | `mvn -B -q dependency:resolve && trivy fs --offline-scan --scanners vuln --severity HIGH,CRITICAL --format json --output <out> --skip-dirs target --skip-dirs .devbox .` | trivy JSON: `{"Results": [{"Vulnerabilities": [{"PkgName": "<g>:<a>", "InstalledVersion", "FixedVersion", "VulnerabilityID", "Severity"}]}]}` |

**`devbox run deps-bump <package> <version>`** moves the resolved version of `<package>` to `<version>` and updates
the lock file. The package name is the one in the findings: a PyPI name, an npm name, a Go module path, or a Maven
`<groupId>:<artifactId>`.

| Exit | Meaning | Files |
|---|---|---|
| 0 | every resolved instance of the package is now `<version>` or higher | only the shape's dependency files changed |
| 1 | the tool failed (resolution conflict, network); the last lines of its output on stderr | undefined: cplat restores them |
| 2 | `deps-bump: <package> is not a dependency of this repo` on stderr, or `usage: devbox run deps-bump <package> <version>` | **none changed**: the membership check runs before any tool |

| Shape | Dependency files | Membership check (file-only where possible) | Direct dependency | Transitive dependency (AC-095.2) |
|---|---|---|---|---|
| service-python, library-python | `pyproject.toml`, `uv.lock` | `uv.lock` has a `[[package]]` with `name = "<normalized name>"` (PEP 503: lowercase, runs of `-_.` → `-`). A missing `uv.lock` means not a dependency. | `uv lock --upgrade-package "<pkg>==<ver>"`. If the declared specifier excludes `<ver>`, then `uv add "<pkg>>=<ver>"` in the section that declares it (`--optional <extra>`, `--group <g>`; `deps_pyproject.py section` finds it). | `uv lock --upgrade-package "<pkg>==<ver>"`. Only if the lock does not move to `<ver>`: `deps_pyproject.py constrain <pkg> <ver>` adds `"<pkg>>=<ver>"` to `[tool.uv] constraint-dependencies`, then `uv lock`. |
| web-nextjs | `package.json`, `pnpm-lock.yaml`, `pnpm-workspace.yaml` | `pnpm-lock.yaml` has a `packages:` key `<pkg>@<version>` (quoted or not) | `pnpm update "<pkg>@<ver>"` (keeps the dependency type) | `node scripts/deps-override.mjs <pkg> <ver>` sets `overrides: {<pkg>: <ver>}` in `pnpm-workspace.yaml`, then `pnpm install`. A direct package that still has an older resolved copy gets the same override. |
| service-go | `go.mod`, `go.sum` | `go.sum` has a line starting `<module> ` | `go get <module>@<ver> && go mod tidy` | the same. Go forces a transitive version only with a `require … // indirect` line, which `go get` writes (the one-package constraint AC-095.2 allows). |
| service-java | `pom.xml` (Maven has no lock file: the pom is the resolved record) | `mvn -B -q dependency:tree -Dincludes=<g>:<a> -DoutputFile=<tmp>` lists the artifact | an explicit `<version>` in `<dependencies>` → replaced with `<ver>` (`java scripts/PomDeps.java set`) | an entry `<g>:<a>:<ver>` upserted into the project's `<dependencyManagement>` (it overrides the parent BOM). It is created when the block is missing. Text edit that keeps the pom's formatting. |

"Direct" means the package is declared in the manifest (`pyproject.toml` dependencies, optional dependencies or
groups; `package.json` dependencies or devDependencies; `go.mod` require without `// indirect`; a pom `<dependency>`).

### Finding (`deps_parse.py`)

```python
@dataclass
class Finding:
    package: str            # PyPI/npm name, Go module path, Maven "<groupId>:<artifactId>"
    installed: str          # resolved version, e.g. "1.26.5", "v0.17.0"
    fixed: str | None       # lowest fixed version above `installed`; None = no fix released
    advisories: list[str]   # advisory ids, sorted: pip-audit `id`, GHSA id (pnpm), GO-YYYY-NNNN, trivy VulnerabilityID
    severity: str           # CRITICAL | HIGH | MODERATE | LOW | UNRATED (pip-audit and govulncheck give none)
    transitive: bool        # not declared in the manifest
    major: bool             # fixed's major > installed's major (first numeric part; a leading "v" is ignored)
    kind: str = "dependency"   # "toolchain": Go `stdlib` / `toolchain` module, never bumped

TOOLS = {"service-python": "pip-audit", "library-python": "pip-audit", "web-nextjs": "pnpm-audit",
         "service-go": "govulncheck", "service-java": "trivy"}
DEP_FILES = {"service-python": ("pyproject.toml", "uv.lock"), "library-python": ("pyproject.toml", "uv.lock"),
             "web-nextjs": ("package.json", "pnpm-lock.yaml", "pnpm-workspace.yaml"),
             "service-go": ("go.mod", "go.sum"), "service-java": ("pom.xml",)}

def version_key(v: str) -> tuple: ...                 # "v1.10.0" > "1.9.3"; numeric parts compare as ints, pre-releases sort before the release
def lowest_fixed(installed: str, candidates: list[str]) -> str | None: ...   # the lowest candidate > installed
def declared(shape: str, repo: Path) -> set[str]: ... # names declared in the manifest (normalized for PyPI)
def parse(tool: str, text: str, declared: set[str]) -> list[Finding]: ...    # one Finding per (package, advisory), gate threshold applied
def group(findings: list[Finding]) -> list[Finding]: ...   # one per package, as below; sorted by package
```

Threshold and fields per tool:
- `pip-audit`: every vuln of every dependency. `fixed` = `lowest_fixed(version, fix_versions)`. Severity `UNRATED`.
  A dependency without `version` (the project itself, skipped) is ignored.
- `pnpm-audit`: severity `high` or `critical` only. `fixed` comes from `patched_versions` `>=X` (also `>=X <Y`, where
  the lowest bound counts). `<0.0.0` means None. One finding per `findings[].version`. Advisory = `github_advisory_id`,
  else `npm-<key>`.
- `govulncheck`: a `finding` whose `trace[0]` has `function` (the vulnerable symbol is called; that is what makes the
  gate exit non-zero). `fixed` = `fixed_version` or None. Severity `UNRATED`. Module `stdlib` or `toolchain` →
  `kind = "toolchain"`.
- `trivy`: severity `HIGH` or `CRITICAL`. `FixedVersion` may be a comma list: `lowest_fixed` over it.

`group`: per package, `installed` = the lowest installed version and `fixed` = the highest of the per-advisory
`fixed`. If any advisory has `fixed is None`, the package's `fixed` is None. `advisories` is the union, severity the
highest (`CRITICAL > HIGH > MODERATE > LOW > UNRATED`), `transitive` and `kind` as above, and `major` recomputed.

### CLI — `cplat deps`

All subprocess calls go through `deps.devbox(repo, args, timeout)` and `deps.git(repo, args)`, and the shape comes
from `deps.shape_of(repo)` (default `shapecmd.route(repo)["shape"]`). Tests replace these three.

| Command | Behaviour | Exit |
|---|---|---|
| `cplat deps findings [--json] [--dir D]` | `devbox run deps-findings <git dir>/cplat-deps-report.json`, then parse and group. Text: one line per package, `<package> <installed> -> <fixed or "no fix released"> <advisory ids> <SEVERITY>[ transitive][ major bump][ toolchain]`, or `no dependency finding turns the security gate red`. `--json`: a list of Finding objects (`asdict`), nothing else on stdout. | 0; 1 when the recipe failed or is missing (`PlatformError`: `deps-findings failed: <last line>`, hint `/shared:update-service adds the deps recipes`) |
| `cplat deps patch [--dir D]` | the loop below | 0 green, 3 escalate, 4 not ours; 1 `PlatformError` |
| `cplat deps report [--body-file F] [--update-pr] [--dir D]` | prints the markdown section of the run's `patched` bumps (or nothing when there are none). `--body-file F`: replaces the section in F (from `## Dependency patches` up to the next `## ` heading or the end), or appends it. Writes nothing when there are no bumps. `--update-pr`: also `gh pr edit <pr> --body-file F`, where `<pr>` is the ship state's `pr` (`<git common dir>/cplat-ship.json`); without a PR it is a no-op. | 0; 1 on a `gh` failure |

**`cplat deps patch`** — in order:
1. The shape is `gitops-app`, unknown, or not in `TOOLS` → print `NOT A DEPENDENCY FINDING: <shape> repos never bump dependencies (spec 095)`, exit 4, nothing changed.
2. A dependency file has uncommitted changes against `HEAD` → `PlatformError("<file> has uncommitted changes", hint="commit them first; cplat deps commits only its own bumps")`.
3. `findings()`, grouped. None → print `NOT A DEPENDENCY FINDING: the security gate is red for another reason (secrets, bandit, or a scanner error)`, exit 4.
4. Any finding with `fixed is None` or `kind == "toolchain"` → record each no-fix package (`outcome: no-fix`, `to: null`) and escalate, with no file changed (AC-095.13).
   - Reason: `no fix released: <pkg> <installed> (<ids>)[; …]`.
   - A toolchain finding instead reads `toolchain finding: <module> <installed> -> <fixed> (<ids>): bump go in devbox.json`.
   - Cause `decision`.
5. Rounds used ≥ `MAX_ROUNDS` (2) → escalate: `patch rounds exhausted (2 of 2): still open: <pkg> <installed> -> <fixed> (<ids>)[; …]`, cause `decision`, nothing changed (AC-095.14).
6. Round `n` += 1 (saved first). `pre = HEAD`. The dependency files are snapshotted as bytes, or as absent.
7. Each fixable package in name order:
   - `devbox run deps-bump <pkg> <fixed>`. A non-zero exit → revert the round and escalate:
     `bump failed: <pkg> <installed> -> <fixed> (<ids>): <last non-empty output line>`, cause `code`, outcome `reverted`.
   - No dependency file changed → the same escalation, with `the recipe changed no file`.
   - Otherwise `git commit -q -s -m "fix(deps): bump <pkg> <installed> -> <fixed> (<ids joined by ', '>)" -- <changed dependency files>`.
     Only those paths are committed; other staged changes stay staged (AC-095.4).
8. Run the gates (`gates.chain` of the `ci` recipe; `ci-extra` only when defined). Every step uses `timeout=3600`.
9. All green → the round's bumps are `patched`. Print one `PATCHED: <pkg> <from> -> <to> (<ids>, <SEVERITY>)[ major bump]` line per bump of every round of this call, then `GREEN: every gate passed after patch round <n> of 2`. Exit 0 (AC-095.12, .17).
10. Red at `security`, and the new findings are non-empty and all fixable → the round's bumps are `patched`, and go to 5 (AC-095.14).
11. Any other red (quality, test, install, ci-extra, or security with a no-fix finding or no dependency finding) → revert the round, mark its bumps `reverted`, and escalate (AC-095.6, .17):
    - reason `bump reverted: <pkg> <from> -> <to>[, …] turned <gate> red: <failing tests, at most 5, comma-joined | last non-empty log line>`;
    - cause `code`.

**Revert** of a round: `git reset -q --soft <pre>`, then write each snapshotted file back byte for byte (delete it if it
was absent), then `git restore --staged -- <dependency files>`. Afterwards `git diff <pre> -- <dependency files>` is empty
and the dependency files equal the snapshot. HEAD is `<pre>`.

**Escalation output** (stdout, exit 3). The orchestrator copies the first two lines:

```
ESCALATE: <reason>
CAUSE: <decision|code>
  <up to 40 lines of the failing gate's log tail, indented two spaces; only for a red gate or a failed recipe>
```

Failing test names come from the gate output: pytest `FAILED <nodeid>`, vitest `FAIL <file> > <name>` and `×
<name>`, go `--- FAIL: <Test>`, and maven surefire `[ERROR]   <Class>.<method>`. If none match, the reason uses the
last non-empty log line.

**Round state** — `<git dir>/cplat-deps.json` (per worktree), written atomically:

```json
{"run": "20261024T101500Z-3f9c2a71", "rounds": 1,
 "bumps": [{"package": "urllib3", "from": "1.26.5", "to": "2.2.2", "advisories": ["GHSA-34jh-p97f-mpxf"],
            "severity": "UNRATED", "major": true, "transitive": true, "round": 1, "outcome": "patched", "commit": "<sha>"}]}
```

A different `run` key resets the file. `run` is the `run_id` of the `cplat runs` pointer (`<git common dir>/cplat-run.json`),
else `runs.attach_point(repo)`, else `branch:<git symbolic-ref --short HEAD>`.

**Run record** (AC-095.11). For each package, at each outcome, call
`runs.event(run_id, "patches", <package>, {...})` with the `run_id` above (None when the key is a branch, which is a
no-op). One entry per package holds its last state:

```json
{"id": "urllib3", "package": "urllib3", "from": "1.26.5", "to": "2.2.2", "advisory": "GHSA-34jh-p97f-mpxf",
 "severity": "UNRATED", "major": true, "outcome": "patched", "round": 1}
```

- `outcome`: `patched` | `no-fix` | `reverted`.
- `to`: the attempted version, `null` for `no-fix`.
- `advisory`: the ids joined by `, `.

Without a store, `runs` buffers or no-ops (spec 087), and nothing in `patch` depends on it.

**PR section and report** (AC-095.4, .17). `cplat deps report` prints:

```markdown
## Dependency patches

Bumped automatically because the security gate was red (spec 095).

| Package | From | To | Advisory | Severity | Note |
|---|---|---|---|---|---|
| urllib3 | 1.26.5 | 2.2.2 | GHSA-34jh-p97f-mpxf | UNRATED | major bump |
| idna | 3.6 | 3.7 | PYSEC-2024-60 | UNRATED | |
```

Only bumps with outcome `patched` are listed, in commit order. The final report of `/svc:build` and `/svc:ship`
includes the same table.

### Orchestration (markdown)

- **`/svc:build` Phase 3, red security gate:** `cplat deps patch` first.
  - Exit 0 → the gates are green, go on to step 3.
  - Exit 3 → stop and escalate with its `ESCALATE` reason. In a ship run that is `cplat ship escalate '<reason>' --cause <CAUSE>`; alone, `cplat runs end --outcome escalated --reason '<reason>' --cause <CAUSE>`.
  - Exit 4 → the security agent as today.

  A red gate after a bump never goes to a coder. Patch rounds are separate from Phase 3's 2 fix rounds. Phase 7's PR
  body and the Final Report include `cplat deps report`.
- **`/svc:ship` `land`, RED:**
  - Red checks other than the security check → the coder fixes them first, as today.
  - The security check is red → `cplat deps patch` (exit 4 → the coder as today). Exit 0 → `cplat deps report --body-file .git/PR_BODY.md --update-pr`, then `cplat ship pr …` (pushes) and `cplat ship land`. Exit 3 → `cplat ship escalate '<reason>' --cause <CAUSE>`.
  - The round is already counted in `fix_rounds` (AC-095.15).
  - Phase `pr` adds `cplat deps report --body-file .git/PR_BODY.md` before `cplat ship pr`.
  - Build-phase escalation rules: "a CRITICAL security finding" becomes "a security finding `cplat deps patch` cannot fix".
- **security agent:** it never bumps (unchanged). Fixable dependency findings are patched by the run. "CRITICAL
  findings block release" stays true for `/svc:release` and `/shared:check-quality`. The spec-059 image summary is
  unchanged.

## Data

`<git dir>/cplat-deps.json` (round state) and `<git dir>/cplat-deps-report.json` (the last raw report). Both are local
and never committed. The run record section is `patches`.

## Risks

- **pip-audit and govulncheck give no severity.** Their bumps show `UNRATED`. The gate fails on every such finding
  anyway, so nothing is patched or skipped because of severity.
- **Java findings vs. the OWASP gate.** OWASP may flag something trivy does not know. Then `patch` sees no fixable
  finding and exits 4, and the run handles the red gate as today.
- **Gate re-runs are slow** (`mvn verify` per round). There are at most 2 rounds, one gate run each.
- **pnpm 11 report format.** The parser accepts the `advisories` map. Testers pin a fixture from pnpm 11.22 audit
  output. An unknown shape raises `deps-findings: unrecognised pnpm audit report` (exit 1), never a silent "no
  finding".
- **Jinja in the Python templates.** They render every file (`_templates_suffix: ""`), so `deps.sh` and
  `deps_pyproject.py` must not contain `{{`, `{%` or `{#`. In bash, write `${#x}` as `$(( ... ))` or avoid it.

---
spec_id: 095-fixable-critical-cves-are-patched
spec_hash: d56c80c71ac0
summary: deps-findings and deps-bump recipes in every non-gitops template, a tested cplat deps findings/patch/report loop (gate threshold, lowest fixed version, one commit per bump, 2 rounds, byte-exact revert, run record patches), and build/ship/security prose that calls it
tasks:
  - id: t1
    title: deps_parse.py parses each gate scanner's report into grouped findings
    files: [scripts/cplat/deps_parse.py]
    covers: [AC-095.2, AC-095.12, AC-095.13, AC-095.16, AC-095.17]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t2
    title: cplat deps findings, patch and report
    files: [scripts/cplat/deps.py, scripts/cplat/cplat.py]
    covers: [AC-095.4, AC-095.6, AC-095.11, AC-095.12, AC-095.13, AC-095.14, AC-095.15, AC-095.16, AC-095.17]
    parallel_safe: true
    depends_on: [t1]
    done: true
  - id: t3
    title: Python templates get deps-findings and deps-bump (uv)
    files: [templates/service-python/devbox.json, templates/service-python/scripts/deps.sh, templates/service-python/scripts/deps_pyproject.py, templates/library-python/devbox.json, templates/library-python/scripts/deps.sh, templates/library-python/scripts/deps_pyproject.py]
    covers: [AC-095.2, AC-095.3]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t4
    title: web-nextjs template gets deps-findings and deps-bump (pnpm)
    files: [templates/web-nextjs/devbox.json.jinja, templates/web-nextjs/scripts/deps.sh, templates/web-nextjs/scripts/deps-override.mjs]
    covers: [AC-095.2, AC-095.3]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t5
    title: service-go template gets deps-findings and deps-bump (go modules)
    files: [templates/service-go/devbox.json.jinja, templates/service-go/scripts/deps.sh]
    covers: [AC-095.2, AC-095.3]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t6
    title: service-java template gets deps-findings and deps-bump (maven)
    files: [templates/service-java/devbox.json.jinja, templates/service-java/scripts/deps.sh, templates/service-java/scripts/PomDeps.java]
    covers: [AC-095.2, AC-095.3]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t7
    title: Shape contract requires the deps recipes, and forbids them in gitops-app
    files: [scripts/shapes.py]
    covers: [AC-095.3, AC-095.16]
    parallel_safe: true
    depends_on: []
  - id: t8
    title: build, ship and security prose call cplat deps
    files: [plugins/svc/commands/build.md, plugins/svc/commands/ship.md, plugins/shared/agents/security.md]
    covers: [AC-095.4, AC-095.6, AC-095.12, AC-095.13, AC-095.15, AC-095.16, AC-095.17]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t9
    title: Docs for automatic dependency patches
    files: [docs/CHANGELOG.md, docs/unattended-delivery.md, docs/adr/README.md, plugins/svc/README.md, plugins/shared/README.md]
    covers: []
    parallel_safe: true
    depends_on: []
    done: true
---

The contract for every task is [design.md](design.md). ADR: [033](../../adr/033-fixable-dependency-findings-are-patched-by-the-run.md).
`ship.py`, `runs.py` and `update.py` are not touched (specs 088, 089 and 096 change them in parallel). A patch in
`land` already counts in `fix_rounds`, because `cplat ship land` counts every red PR check.

## t1 — deps_parse.py parses each gate scanner's report into grouped findings

**Files:** scripts/cplat/deps_parse.py
**Covers:** AC-095.2, AC-095.12, AC-095.13, AC-095.16, AC-095.17
**Goal:** the pure part of design.md "Finding": `Finding`, `TOOLS`, `DEP_FILES`, `version_key`, `lowest_fixed`,
`declared`, `parse` and `group`. No subprocess calls. The only file reads are the manifests in `declared`.

**Implementation notes:**
- `version_key`: strip a leading `v`, split on `.`, `-`, `+`. Numeric parts compare as ints, and a pre-release
  (`rc`, `a`, `b`, `beta`, `-x`) sorts before its release. It must never raise: an unparsable part compares as a string.
- `lowest_fixed(installed, candidates)`: the lowest candidate that is greater than `installed`, else None. For trivy,
  `candidates` is the comma list split and stripped.
- `declared`:
  - PyPI: `tomllib` over `[project].dependencies`, `optional-dependencies` and `[dependency-groups]`, names normalized
    by PEP 503;
  - npm: `package.json` `dependencies` and `devDependencies`;
  - Go: `go.mod` requires without `// indirect` (single-line and block form);
  - Maven: `groupId:artifactId` of every `<dependency>` under `<project><dependencies>`, through `xml.etree` with the
    POM namespace.
- `parse` applies the gate thresholds of the design: pip-audit all, pnpm high and critical, govulncheck called
  symbols only, trivy HIGH and CRITICAL. A report it cannot recognise raises `core.PlatformError("deps-findings:
  unrecognised <tool> report")`. An empty report (no findings) is `[]`.
- govulncheck's JSON is a stream of objects. Use `json.JSONDecoder().raw_decode` in a loop, not one `json.loads`.
- `group` as in the design: the highest per-advisory fix, union of ids sorted, highest severity, None if any advisory
  has no fix, and `major` recomputed against the lowest installed version.

**Done when:** the parser acceptance tests for AC-095.2 (transitive flag), .12 (lowest fixed, threshold), .13 (`fixed
is None`), .16 (findings below the threshold and Go `stdlib` are not bumpable dependency findings) and .17 (`major`)
pass on fixture reports of each of the four tools.

## t2 — cplat deps findings, patch and report

**Files:** scripts/cplat/deps.py, scripts/cplat/cplat.py
**Covers:** AC-095.4, AC-095.6, AC-095.11, AC-095.12, AC-095.13, AC-095.14, AC-095.15, AC-095.16, AC-095.17
**Goal:** the CLI and the loop of design.md "CLI — `cplat deps`", exactly: the step order of `patch`, the exit codes
0/3/4, the `PATCHED`/`GREEN`/`ESCALATE`/`CAUSE` lines, the commit message, the byte-exact revert, the round state, the
`patches` run-record entries and the PR section.

**Implementation notes:**
- Seams for tests: `devbox(repo, args, timeout)` returns a `CompletedProcess` with text output; `git(repo, args)`;
  `shape_of(repo)`. Each one is a module-level function the tests replace.
- `findings(repo)`: `devbox run deps-findings <git dir>/cplat-deps-report.json`. A non-zero exit, or a missing
  `deps-findings` recipe in `devbox.json`, raises `PlatformError` with the last output line and hint `/shared:update-service
  adds the deps recipes`. Then `deps_parse.parse(TOOLS[shape], text, declared(shape, repo))` and `group`.
- Gates: `gates.chain(gates.recipes(repo)["ci"])`; drop `ci-extra` when the repo does not define it. Each step is
  `devbox run <step>`, stopping at the first non-zero.
- Commits: `git commit -q -s -m <msg> -- <changed files>`. Changed = the bytes differ from the snapshot. Only
  dependency files are ever written or committed.
- Revert exactly as in the design (`reset --soft`, byte restore, `restore --staged`). Afterwards assert that the
  dependency files equal the snapshot. If they do not, raise `PlatformError` (a platform bug, never a silent state).
- Run key: `runs._read_pointer(runs._pointer(repo))["run_id"]` → `runs.attach_point(repo)` → `branch:<name>`. Use the
  run id only for `runs.event(...)`. `runs.*` never raises, so no try/except is needed around it.
- Round state `<git dir>/cplat-deps.json` (`git rev-parse --git-dir`): written atomically (temp file and
  `os.replace`). Round `n` is saved before the bumps start, so an interrupted call still counts its round.
- Failing test names: the four regexes of the design, at most 5 in the reason. The log tail is the last 40 non-empty
  lines, indented two spaces.
- `report`: the markdown section of the design. Replace an existing section in `--body-file` up to the next `## `
  heading. `--update-pr` reads `pr` from `<git common dir>/cplat-ship.json` and runs `gh pr edit <pr> --body-file F`
  through `core.run`.
- `cplat.py`: add `"deps": "deps"` to `COMMANDS` and the docstring line
  `cplat.py deps findings|patch|report ...   patch fixable dependency findings of a red security gate (spec 095, ADR-033)`.
  These are the only edits to cplat.py.

**Done when:** the acceptance tests for AC-095.4, .6, .11, .12, .13, .14, .16 and .17 pass with fake `devbox`/`git`
seams (or with a real temporary git repo and a fake `devbox`). The `report --update-pr` part of AC-095.15 passes too,
and the full `tests/cplat` suite stays green.

## t3 — Python templates get deps-findings and deps-bump (uv)

**Files:** templates/service-python/devbox.json, templates/service-python/scripts/deps.sh, templates/service-python/scripts/deps_pyproject.py, templates/library-python/devbox.json, templates/library-python/scripts/deps.sh, templates/library-python/scripts/deps_pyproject.py
**Covers:** AC-095.2, AC-095.3
**Goal:** the two recipes of design.md "Template recipes" for uv, with byte-identical scripts in both Python templates.

**Implementation notes:**
- `devbox.json`: add `"deps-findings": "bash scripts/deps.sh findings"` and `"deps-bump": "bash scripts/deps.sh bump"`
  after `security`. Do not change `ci` or `security` (spec 086 tests pin `ci`).
- `deps.sh findings <out>`: `uv run pip-audit -f json -o "$out"`. Exit 1 with the file written is success.
- `deps.sh bump <pkg> <ver>`:
  1. Usage check.
  2. PEP 503 normalization, then the membership check on `uv.lock` (exit 2, nothing written).
  3. `uv lock --upgrade-package "<pkg>==<ver>"`, and check the locked version.
  4. If it did not move: transitive → `python3 scripts/deps_pyproject.py constrain`, then `uv lock`. Direct →
     `uv add "<pkg>>=<ver>"` with the section flags that `deps_pyproject.py section` prints.
  5. Final check: the lock is at `<ver>` or higher, else exit 1.
- `deps_pyproject.py`: stdlib only (`tomllib` to read; a minimal text edit to add or replace one entry in `[tool.uv]
  constraint-dependencies`, creating the table or key when missing).
- Both files are rendered by Jinja (`_templates_suffix: ""`): no `{{`, `{%` or `{#` anywhere (bash `${#…}` included).
- Only `pyproject.toml` and `uv.lock` may change.

**Done when:** the AC-095.3 acceptance tests pass for both templates. Those tests render the template, call
`deps-bump` with a package that is not a dependency, and expect a non-zero exit, the package name on stderr and an
unchanged tree. Where the tests have `uv`, the slow AC-095.2 test also passes: a transitive bump moves `uv.lock`, and
`pyproject.toml` only gains the constraint when needed.

## t4 — web-nextjs template gets deps-findings and deps-bump (pnpm)

**Files:** templates/web-nextjs/devbox.json.jinja, templates/web-nextjs/scripts/deps.sh, templates/web-nextjs/scripts/deps-override.mjs
**Covers:** AC-095.2, AC-095.3
**Goal:** the two recipes for pnpm 11, as in the design.

**Implementation notes:**
- Recipes as in t3, added after `security`.
- `findings`: `pnpm audit --prod --json > "$out"`. A non-zero exit with valid JSON written is success.
- `bump`:
  1. Membership check on the `packages:` keys of `pnpm-lock.yaml` (exit 2).
  2. Direct (in `package.json` `dependencies`/`devDependencies`, checked with `node -e`) → `pnpm update "<pkg>@<ver>"`.
  3. If any locked copy of the package is still below `<ver>`, or the package is transitive →
     `node scripts/deps-override.mjs <pkg> <ver>`, then `pnpm install`.
- `deps-override.mjs`: Node stdlib only. A text edit of `pnpm-workspace.yaml` that adds or updates `<pkg>: <ver>`
  under a top-level `overrides:` map and creates the map when missing. It keeps the existing `allowBuilds` and
  comments. Quote names that start with `@`.
- Only `package.json`, `pnpm-lock.yaml` and `pnpm-workspace.yaml` may change.

**Done when:** the AC-095.3 acceptance tests pass for web-nextjs. With `pnpm` available, the slow AC-095.2 test passes
too: a transitive bump adds exactly one override and moves the lock.

## t5 — service-go template gets deps-findings and deps-bump (go modules)

**Files:** templates/service-go/devbox.json.jinja, templates/service-go/scripts/deps.sh
**Covers:** AC-095.2, AC-095.3
**Goal:** the two recipes for Go modules, as in the design.

**Implementation notes:**
- Recipes as in t3, added after `security`.
- `findings`: `govulncheck -json ./... > "$out"`.
- `bump`:
  1. Membership check: `go.sum` has a line starting with `<module> ` (exit 2).
  2. `go get <module>@<ver>`, then `go mod tidy`.
  3. Check `go list -m -f '{{.Version}}' <module>` ≥ `<ver>`. This template only renders `*.jinja` files, so
     `{{.Version}}` is safe in `deps.sh`. Keep it out of `devbox.json.jinja`.
- Only `go.mod` and `go.sum` may change.

**Done when:** the AC-095.3 acceptance tests pass for service-go. With `go` available, the slow AC-095.2 test passes
too: a transitive bump adds a single `// indirect` require.

## t6 — service-java template gets deps-findings and deps-bump (maven)

**Files:** templates/service-java/devbox.json.jinja, templates/service-java/scripts/deps.sh, templates/service-java/scripts/PomDeps.java
**Covers:** AC-095.2, AC-095.3
**Goal:** the two recipes for Maven, as in the design. The findings always come from `trivy fs` JSON, because OWASP
names no fixed versions.

**Implementation notes:**
- Recipes as in t3, added after `security`.
- `findings`: `mvn -B -q dependency:resolve`, then `trivy fs --offline-scan --scanners vuln --severity HIGH,CRITICAL
  --format json --output "$out" --skip-dirs target --skip-dirs .devbox .`. This uses no `--exit-code 1`.
- `bump`:
  1. Validate `<groupId>:<artifactId>`.
  2. Membership: `mvn -B -q dependency:tree -Dincludes=<g>:<a> -DoutputFile=<tmp>` must name the artifact (exit 2).
  3. `java scripts/PomDeps.java set <g:a> <ver>`.
  4. Check with `dependency:tree` that the version is resolved.
- `PomDeps.java`: a single-file source program on JDK classes only.
  - Direct with an explicit `<version>` → replace the version.
  - Otherwise → upsert a `<dependency>` in `<dependencyManagement><dependencies>`, creating the block before
    `<dependencies>` when missing.
  - A text edit that keeps indentation and comments. It never touches `<parent>` or `<properties>`.
- Only `pom.xml` may change.

**Done when:** the AC-095.3 acceptance tests pass for service-java, with a stub `mvn` that lists nothing. With `mvn`
available, the slow AC-095.2 test passes too: a transitive bump adds one `dependencyManagement` entry.

## t7 — Shape contract requires the deps recipes, and forbids them in gitops-app

**Files:** scripts/shapes.py
**Covers:** AC-095.3, AC-095.16
**Goal:** `shapes.py check` fails when a non-planned, non-gitops shape's template lacks `deps-findings` or `deps-bump`,
or lacks `scripts/deps.sh`. It also fails when the gitops-app template defines either recipe.

**Implementation notes:**
- `DEPS_RECIPES = ["deps-findings", "deps-bump"]`. Check them inside `check_contract`, next to the `CORE_RECIPES`
  check, with the messages `<sid>: devbox.json missing deps recipe '<r>' (spec 095)` and `gitops-app: devbox.json
  must not define '<r>': gitops-app repos never bump dependencies (spec 095)`.
- The check is additive. Do not touch the spec 086 checks.

**Done when:** `uv run scripts/shapes.py check` is green once t3–t6 are in. The AC-095.3 and .16 contract tests pass:
they remove a recipe in a copied registry and expect the error.

## t8 — build, ship and security prose call cplat deps

**Files:** plugins/svc/commands/build.md, plugins/svc/commands/ship.md, plugins/shared/agents/security.md
**Covers:** AC-095.4, AC-095.6, AC-095.12, AC-095.13, AC-095.15, AC-095.16, AC-095.17
**Goal:** the "Orchestration (markdown)" part of the design, in small, additive edits. Other specs change these
files in parallel.

**Implementation notes:**
- `build.md` Phase 3 step 2, the security bullet:
  - `cplat deps patch` first. Exit 0 → green, go to step 3. Exit 3 → escalate with its `ESCALATE` line and `--cause`
    (`cplat ship escalate` in a ship run, `cplat runs end --outcome escalated --reason … --cause …` alone). Exit 4 →
    the security agent as today.
  - A red gate after a bump is never handed to a coder, and acceptance tests stay fixed.
  - Patch rounds (at most 2, counted by cplat) are separate from the 2 fix rounds of step 2.
- `build.md` Phase 7:
  - The body includes the output of `cplat deps report` after the criteria table.
  - The checklist line becomes `devbox run security` passes (fixable dependency findings patched, see Dependency
    patches).
  - The Final Report includes the same table.
- `ship.md`:
  - Phase `build`: replace "a CRITICAL security finding" with "a security finding `cplat deps patch` cannot fix (its
    exit 3)".
  - Phase `pr` step 1: `cplat deps report --body-file .git/PR_BODY.md`.
  - Phase `land` RED gets a new bullet: the security check is red → other red checks go to the coder first. Then
    `cplat deps patch`. Exit 0 → `cplat deps report --body-file .git/PR_BODY.md --update-pr`, then `cplat ship pr …`
    and `cplat ship land`. Exit 3 → `cplat ship escalate '<reason>' --cause <CAUSE>`. Exit 4 → the coder as today.
    The round counts toward the 3 (`fix_rounds`).
  - Finish: the report lists the bumps (`cplat deps report`), with "major bump" marked.
- `security.md`:
  - Rules: replace "CRITICAL findings block release" with this. In `/svc:build` and `/svc:ship`, the run patches a
    fixable dependency finding itself (`cplat deps patch`), and the agent never bumps. In `/svc:release` and
    `/shared:check-quality`, a red security gate still blocks, and the agent only reports.
  - Keep the spec-059 "Base image, no fix released" summary word for word.
  - The verdict lines stay.

**Done when:** the prose acceptance tests for AC-095.12, .13, .15 and .16 pass. They assert that build.md and ship.md
call `cplat deps patch` and `cplat deps report`, that ship.md escalates with `--cause`, that the spec-059 summary line
is still in security.md, and that no command tells an agent to bump a dependency. `devbox run validate` stays green.

## t9 — Docs for automatic dependency patches

**Files:** docs/CHANGELOG.md, docs/unattended-delivery.md, docs/adr/README.md, plugins/svc/README.md, plugins/shared/README.md
**Covers:** none (documentation)
**Goal:** users learn that runs patch fixable dependency findings, how to read the PR table and the run record
section, and what still stops a run.

**Implementation notes:**
- `docs/CHANGELOG.md`: one bullet under `[Unreleased]`: **Feature (095): fixable dependency CVEs are patched by the
  run.** It names `deps-findings`/`deps-bump` (`/shared:update-service` adds them), `cplat deps
  findings|patch|report`, 2 rounds, the revert, "major bump", the `patches` run record section and ADR-033.
- `docs/unattended-delivery.md` line 18: replace "a CRITICAL security finding" with "a security finding with no fix
  released, or a bump that breaks a gate". Add a short "Dependency patches" paragraph.
- `docs/adr/README.md`: the index row
  `| [033](033-fixable-dependency-findings-are-patched-by-the-run.md) | Fixable dependency findings are patched by the run: deps recipes per shape, cplat deps patch, 2 rounds, exact revert |`.
  If another spec took 033 first, renumber this ADR and its links in design.md and plan.md.
- `plugins/svc/README.md` and `plugins/shared/README.md`: one line where build/ship and the security agent are
  described.
- No plugin or marketplace version bumps.

**Done when:** `devbox run validate` and the Markdown link check pass.

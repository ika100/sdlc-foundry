---
spec_id: 197-the-journey-13-seams
shape: platform
spec_hash: "8f9be5fbe93e"
summary: Reviewed step finds the tester's commit by AC id, merged-away deviations count, system set/status name the Grafana URL, the web release version step works on a dirty tree, generated repos get per-test limits through gate.sh
tasks:
  - id: t1
    title: Reviewed step accepts the tester's acceptance-test subject
    files: [scripts/cplat/testreview.py]
    covers: [AC-197.1]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t2
    title: A deviation naming a merged-away task is recorded on its final task
    files: [scripts/cplat/runs_agents.py]
    covers: [AC-197.2]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t3
    title: system set and system status name where Grafana answers
    files: [scripts/cplat/model.py, scripts/cplat/systemset.py, scripts/cplat/status.py]
    covers: [AC-197.3, AC-197.4]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t4
    title: Web release version step works with the uncommitted changelog
    files: [plugins/web/agents/release.md, docs/rules/plugins/web/agents/release.yml]
    covers: [AC-197.5]
    parallel_safe: true
    depends_on: []
  - id: t5
    title: Per-test limits for generated Python, Java and Go repos through gate.sh
    files: [templates/gitops-app/scripts/gate.sh, templates/cluster-gitops/scripts/gate.sh, templates/service-python/scripts/gate.sh, templates/library-python/scripts/gate.sh, templates/service-go/scripts/gate.sh, templates/service-java/scripts/gate.sh, templates/web-nextjs/scripts/gate.sh, templates/service-python/scripts/pytest_limit/platform_test_limit.py, templates/library-python/scripts/pytest_limit/platform_test_limit.py, scripts/sync-template-copies.py]
    covers: [AC-197.6, AC-197.7, AC-197.8]
    parallel_safe: true
    depends_on: []
  - id: t6
    title: ADR, changelog fragment and web plugin version
    files: [docs/adr/, docs/adr/README.md, docs/changelog.d/197-the-journey-13-seams.fixed.md, .claude-plugin/marketplace.json, plugins/web/.claude-plugin/plugin.json]
    covers: [AC-197.5, AC-197.6, AC-197.7, AC-197.8]
    parallel_safe: true
    depends_on: []
---

# Plan — 197 The journey 13 seams

Contracts and exact output strings are in [design.md](design.md). One level: t1–t6 run in parallel; no two share a
file.

## t1 — Reviewed step accepts the tester's acceptance-test subject

**Files:** scripts/cplat/testreview.py
**Covers:** AC-197.1
**Goal:** `cplat component build reviewed <spec>` finds the acceptance-test commit by the spec id or an `AC-<NNN>.` id
in its subject, and still refuses a branch whose only such commit belongs to another spec or names neither.

**Implementation notes:**
- Add `_acceptance(repo, sp, head)` per design.md: `git log --no-merges --format=%H%x09%s <_range(repo, head)>`, filter
  subjects in Python (contains `acceptance tests for`, not `reviewed acceptance tests for`, and `sp.id` or
  `(?<![\w-])AC-<re.escape(sp.number)>\.`).
- `commit` uses it in place of `_find(repo, sp.id, ACCEPTANCE_MSG, "HEAD")`; the error text and hint stay as they are.
- `reviewed_commit` and `unresolved` keep `_find` (the reviewed subject carries the spec id).
- Do not touch `units.py`, `testdiff_select.py` or `spec.py` (non-goal).

**Done when:** the AC-197.1 acceptance tests pass and the existing spec 179 reviewed-step tests stay green.

## t2 — A deviation naming a merged-away task is recorded on its final task

**Files:** scripts/cplat/runs_agents.py
**Covers:** AC-197.2
**Goal:** `cplat platform runs agent findings --deviation t1` after `cplat plan merge t1 t2` records the deviation on `t2`
with a note, prints no warning and keeps the metrics complete.

**Implementation notes:**
- `_merged_into(rec) -> dict[str, str]`: `task` → `into` of every `task-merge` event over all entries of `rec["agents"]`
  (tolerate a missing section).
- `_resolve(merges, tid) -> str | None`: follow the map with a visited set; return the end of the chain.
- In `findings.go()`, for a deviation that is neither an AC id nor in `ids`: resolve it from `rec0`; when the end is in
  `ids`, append the event of design.md with `"note": f"named as {d} (merged into {end})"`; otherwise keep it in `bad`.
- No change to `task_merge`, `_natural` or the CLI parser.

**Done when:** the AC-197.2 acceptance tests pass (single merge, chain, unknown id) and the spec 089/186 agent-metrics
tests stay green.

## t3 — system set and system status name where Grafana answers

**Files:** scripts/cplat/model.py, scripts/cplat/systemset.py, scripts/cplat/status.py
**Covers:** AC-197.3, AC-197.4
**Goal:** turning on the dev Grafana stack tells the user its URL (local environments) or that it answers only at
`grafana.localhost` on that cluster's Gateway, and `system status` shows the same location.

**Implementation notes:**
- `model.py`: add `local_port()`, `GRAFANA_HOST`, `GRAFANA_ELSEWHERE`, `grafana_url(host)`, `grafana_location(host)` per
  design.md; `_url` uses `local_port()` (same output as today).
- `systemset.py`: compute the host (`--host` if given, else the environment's `host`); with `--observability lgtm`
  print an empty line and `Grafana: <location>` after `r.emit(...)` in text mode, on the dry-run and the real path.
- `systemset.py` JSON: set `grafana_url` in `r.data` on every path where `--observability` was given (no-op path too):
  the URL for lgtm on a local host, else `null`.
- `status.py`: build the observability cells for environments with an observability block and (instances or
  `ui == "lgtm"`); add `grafana_url` to lgtm cells via `model.grafana_url(e.host)`.
- `status.py` `_cell`: a cell with a `grafana_url` key renders `argo <state>  Grafana <location>` (the URL, or
  `GRAFANA_ELSEWHERE` when null).

**Done when:** the AC-197.3 and AC-197.4 acceptance tests pass and the existing `system set` / `system status` /
model URL tests stay green.

## t4 — Web release version step works with the uncommitted changelog

**Files:** plugins/web/agents/release.md, docs/rules/plugins/web/agents/release.yml
**Covers:** AC-197.5
**Goal:** the documented step 3 command exits 0 with the new `CHANGELOG.md` uncommitted (untracked or modified), sets
`package.json` to `NEXT_DEV` and creates no tag or commit, with pnpm 11.22.0.

**Implementation notes:**
- Step 3's command becomes `devbox run -- pnpm version <NEXT_DEV> --no-git-tag-version --no-git-checks`, with a reason
  clause in the prose (pnpm refuses the tree that holds the new, uncommitted `CHANGELOG.md`).
- Run the AC-197.5 acceptance test against pnpm 11.22.0; if pnpm rejects `--no-git-checks`, use
  `devbox run -- pnpm pkg set version=<NEXT_DEV>` instead and say so in the task report (design.md, Decisions).
- Register: new entry `R10`, `class: practice`, `source: spec 197`, `text` quoting the new sentence; update `R3`'s `text`
  if its sentence changes.
- Keep the file's bytes at most what they were (register rule 6): tighten other sentences, update their entries.
- `cplat platform rules check --only plugins/web/agents/release.md` passes.

**Done when:** the AC-197.5 acceptance test passes (or is skipped with its stated reason where pnpm cannot be fetched)
and `cplat platform rules check` passes.

## t5 — Per-test limits for generated Python, Java and Go repos through gate.sh

**Files:** templates/gitops-app/scripts/gate.sh, templates/cluster-gitops/scripts/gate.sh, templates/service-python/scripts/gate.sh, templates/library-python/scripts/gate.sh, templates/service-go/scripts/gate.sh, templates/service-java/scripts/gate.sh, templates/web-nextjs/scripts/gate.sh, templates/service-python/scripts/pytest_limit/platform_test_limit.py, templates/library-python/scripts/pytest_limit/platform_test_limit.py, scripts/sync-template-copies.py
**Covers:** AC-197.6, AC-197.7, AC-197.8
**Goal:** in a repo of the four templates, new or updated, a hung test fails after 120 s (Python, Java) or its package
stops after 5 min (Go), named, while a suite without one behaves exactly as before and a repo's own limit wins.

**Implementation notes:**
- Write `platform_test_limit.py` in service-python per design.md (hookwrapper, SIGALRM via `setitimer`, re-arm after
  expiry, restore the old handler, the step-aside rules); no `{{`, `{%` or `{#` anywhere in the file.
- `sync-template-copies.py`: add the pair service-python → library-python for the plugin; run it to write the copy.
- `templates/gitops-app/scripts/gate.sh` (the source): in `cmd_tests`, before the runner case, export the variables of
  design.md's table per runner; never change `"$@"` (spec 130's argv tests read it).
- pytest: only when `scripts/pytest_limit/platform_test_limit.py` exists in the working directory; prepend its
  absolute directory to `PYTHONPATH`, append `-p platform_test_limit` to `PYTEST_ADDOPTS`.
- maven: the skip checks of design.md (`grep -qs` over `pom.xml`, `src/test/resources/junit-platform.properties`, the
  args and the two variables), else append the `-D` to `MAVEN_ARGS`.
- go: skip when `$GOFLAGS` has `-timeout`, else append `-timeout=5m` to `GOFLAGS`.
- Keep gate.sh free of Jinja syntax and bash-3.2 compatible (macOS); update its header comment with one line on the
  limits.
- Run `uv run scripts/sync-template-copies.py` to rewrite the six gate.sh copies.
- No change to any `devbox.json`, `pyproject.toml`, `pom.xml`, `go.mod` or `copier.yml` (AC-197.8: the files arrive
  through `/platform:update` because they are not in `_skip_if_exists`).

**Done when:** the AC-197.6 to AC-197.8 acceptance tests pass, `python3 scripts/sync-template-copies.py --check` is OK,
and the spec 130 gate.sh tests (`test_130_gate_sh.py`, `test_130_empty_gates.py`) stay green.

## t6 — ADR, changelog fragment and web plugin version

**Files:** docs/adr/, docs/adr/README.md, docs/changelog.d/197-the-journey-13-seams.fixed.md, .claude-plugin/marketplace.json, plugins/web/.claude-plugin/plugin.json
**Covers:** AC-197.5, AC-197.6, AC-197.7, AC-197.8
**Goal:** the generated-repo test limits are a recorded decision, the release notes name the five fixes, and the
changed web plugin carries a new version.

**Implementation notes:**
- `cplat adr add generated-repos-bound-test-time --decision "Generated Python and Java repos fail a test after 120 s and Go repos stop a test package after 5 min, set by the platform-owned scripts/gate.sh through environment variables; a repo's own limit wins"`;
  fill Status (Accepted), Context (journey 13's hung API test, ~9 of 112.6 min; spec 185 left generated repos out),
  Decision (the three mechanisms of design.md, SAME_THREAD for JUnit and why), Consequences (no build-file change, so
  `/platform:update` carries it; an interrupt-ignoring Java test still waits for quiet's 9 min; extends ADR-108).
- Changelog fragment (format in `docs/changelog.d/README.md`): one line each for the five fixes.
- Web plugin: patch bump `0.8.0` → `0.8.1` in `plugins/web/.claude-plugin/plugin.json` and the `web` entry of
  `.claude-plugin/marketplace.json`.

**Done when:** `cplat platform pr-check` reports no fragment, version or link error and `devbox run validate` passes.

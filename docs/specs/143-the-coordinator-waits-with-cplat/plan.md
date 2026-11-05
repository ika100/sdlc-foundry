---
spec_id: 143-the-coordinator-waits-with-cplat
shape: platform
spec_hash: 52acfbf64dad
summary: "New waits as cplat commands: `cplat system wait --env` and `cplat cluster wait` (scripts/cplat/envwait.py: Argo CD apps synced to main's head on GitHub, Synced/Healthy, the pinned image; RED/TIMEOUT/--refresh; one git fetch), `cplat component ship wait` and `cplat system ship next --wait` (scripts/cplat/shipwait.py), `cplat component release wait` for the release's CI wait; shared clock, exit codes and run record in scripts/cplat/waits.py; the command texts name the waits, and a test fails on a shell sleep loop in a command or agent file"
tasks:
  - id: t1
    title: "waits.py: clock, exit codes, time format, run record (attach to the current or system ship run, else an own `wait` run)"
    files: [scripts/cplat/waits.py]
    covers: [AC-143.10]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t2
    title: "envwait.py: `system wait` and `cluster wait` (apps of an environment or the cluster roots, wanted revision from one fetch, pins at that revision, state per app, READY/RED/TIMEOUT, --refresh, context check); routes in cplat.py"
    files: [scripts/cplat/envwait.py, scripts/cplat/cplat.py]
    covers: [AC-143.1, AC-143.2, AC-143.3, AC-143.4, AC-143.5, AC-143.6, AC-143.7, AC-143.10]
    parallel_safe: false
    depends_on: [t1]
    done: true
  - id: t3
    title: "shipwait.py: `component ship wait` and `system ship next --wait`; routes in ship.py and appship.py"
    files: [scripts/cplat/shipwait.py, scripts/cplat/ship.py, scripts/cplat/appship.py]
    covers: [AC-143.8, AC-143.9, AC-143.10]
    parallel_safe: false
    depends_on: [t1]
    done: true
  - id: t4
    title: "`component release wait --commit` (main's ci run on a commit) in comprelease.py"
    files: [scripts/cplat/comprelease.py]
    covers: [AC-143.11]
    parallel_safe: true
    depends_on: [t1]
    done: true
  - id: t5
    title: "Command texts name the waits (component set/add, instance promote, system set, resource add, cluster add, system ship, component release); AGENTS.md, ADR-082, cplat usage"
    files: [plugins/component/commands/set.md, plugins/component/commands/add.md, plugins/instance/commands/promote.md, plugins/system/commands/set.md, plugins/resource/commands/add.md, plugins/cluster/commands/add.md, plugins/system/commands/ship.md, plugins/component/commands/release.md, plugins/component/commands/ship.md, docs/AGENTS.md, docs/adr/082-a-coordinator-waits-with-a-cplat-wait-never-a-polling-loop.md, docs/adr/README.md]
    covers: [AC-143.11]
    parallel_safe: false
    depends_on: [t2, t3, t4]
    done: true
  - id: t6
    title: "Plugin versions (component, system, cluster, instance, resource) in plugin.json and marketplace.json; changelog fragment"
    files: [.claude-plugin/marketplace.json, plugins/component/.claude-plugin/plugin.json, plugins/system/.claude-plugin/plugin.json, plugins/cluster/.claude-plugin/plugin.json, plugins/instance/.claude-plugin/plugin.json, plugins/resource/.claude-plugin/plugin.json, docs/changelog.d/143-the-coordinator-waits-with-cplat.added.md]
    covers: [AC-143.11]
    parallel_safe: false
    depends_on: [t5]
    done: true
---

# Plan — 143 The coordinator waits with cplat, not hand-written loops

Contract: [design.md](design.md). The acceptance tests (`tests/cplat/test_143_envwait.py`, `tests/cplat/test_143_shipwait.py`, `tests/cplat/test_143_release_wait.py`,
`tests/cplat/test_143_waits_docs.py`) are written before t1 starts and fail first; no task edits them.

| Level | Task | Covers | Parallel | Files |
|---|---|---|---|---|
| 0 | t1 waits.py | AC-143.10 | yes | `scripts/cplat/waits.py` |
| 1 | t2 environment and cluster wait | AC-143.1–7, 10 | no | `envwait.py`, `cplat.py` |
| 1 | t3 ship wait, next --wait | AC-143.8–10 | no | `shipwait.py`, `ship.py`, `appship.py` |
| 1 | t4 release CI wait | AC-143.11 | yes | `comprelease.py` |
| 2 | t5 command texts, ADR | AC-143.11 | no | eight command files, `docs/AGENTS.md`, ADR-082 |
| 3 | t6 versions, fragment | AC-143.11 | no | manifests, `docs/changelog.d/` |

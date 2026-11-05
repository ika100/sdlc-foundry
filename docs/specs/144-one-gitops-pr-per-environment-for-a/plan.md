---
spec_id: 144-one-gitops-pr-per-environment-for-a
shape: platform
spec_hash: b4215915caa0
summary: "A system ship lands dev in one gitops PR: the component ships push a marker `ship/<spec>/<component>-<sha7>` that makes the gitops-app's pin-dev.yml skip that build, end their deploy at \"pinned in the system ship's dev PR\" once the image is built, and the system ship pins each build on compose/<spec> (pin.py), then `cplat system ship land` merges that one PR, waits for Argo CD once, runs every dev smoke and promotes staging in one PR (scripts/cplat/appship_joint.py); gitops-apps without the new pin-dev.yml keep one PR per component"
tasks:
  - id: t1
    title: "pin-dev.yml skips a build that has a `ship/<spec>/<service>-<sha7>` marker; CLAUDE.md of the gitops-app"
    files: [templates/gitops-app/.github/workflows/pin-dev.yml, templates/gitops-app/CLAUDE.md.jinja]
    covers: [AC-144.1, AC-144.6]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t2
    title: "appship_joint.py: mode, markers, pin on compose/<spec>, the component ship's joint deploy; ship.py product link, marker push in land, deploy hand-off"
    files: [scripts/cplat/appship_joint.py, scripts/cplat/ship.py]
    covers: [AC-144.1, AC-144.3, AC-144.6]
    parallel_safe: false
    depends_on: []
    done: true
  - id: t3
    title: "System ship: joint mode at start, the legacy line, entry land without merge, result pins, action `land`, `pinned` as delivered, complete refuses before landing"
    files: [scripts/cplat/appship.py, scripts/cplat/appship_sched.py, scripts/cplat/appship_state.py]
    covers: [AC-144.1, AC-144.2, AC-144.3, AC-144.5]
    parallel_safe: false
    depends_on: [t2]
    done: true
  - id: t4
    title: "`cplat system ship land`: merge the joint PR, operators, markers, one Argo CD wait, every dev smoke, staging in one PR; the report"
    files: [scripts/cplat/appship_joint.py, scripts/cplat/appship.py, scripts/cplat/appship_report.py]
    covers: [AC-144.2, AC-144.4, AC-144.5, AC-144.7, AC-144.8]
    parallel_safe: false
    depends_on: [t3]
    done: true
  - id: t5
    title: "Command texts (system ship, component ship), AGENTS.md, ADR-083, plugin versions, changelog fragment"
    files: [plugins/system/commands/ship.md, plugins/component/commands/ship.md, docs/AGENTS.md, docs/adr/083-a-system-ship-lands-each-environment-in-one-gitops-pr.md, docs/adr/README.md, .claude-plugin/marketplace.json, plugins/system/.claude-plugin/plugin.json, plugins/component/.claude-plugin/plugin.json, docs/changelog.d/144-one-gitops-pr-per-environment.changed.md]
    covers: [AC-144.1, AC-144.8]
    parallel_safe: false
    depends_on: [t4]
    done: true
---

# Plan — 144 One gitops PR per environment for a system ship

Contract: [design.md](design.md). The acceptance tests (`tests/cplat/test_144_joint_pr.py`, `tests/cplat/test_144_pin_dev_marker.py`)
are written before t1 starts and fail first; no task edits them.

| Level | Task | Covers | Parallel | Files |
|---|---|---|---|---|
| 0 | t1 pin-dev marker | AC-144.1, 6 | yes | `pin-dev.yml`, `CLAUDE.md.jinja` |
| 0 | t2 joint module, component ship | AC-144.1, 3, 6 | no | `appship_joint.py`, `ship.py` |
| 1 | t3 system ship scheduling | AC-144.1, 2, 3, 5 | no | `appship.py`, `appship_sched.py`, `appship_state.py` |
| 2 | t4 `system ship land` | AC-144.2, 4, 5, 7, 8 | no | `appship_joint.py`, `appship.py`, `appship_report.py` |
| 3 | t5 texts, versions | AC-144.1, 8 | no | commands, AGENTS.md, ADR-083, versions, changelog |

The e2e (`tests/e2e/`) has no system ship scenario; the system ship is covered by the simulated world of spec 097's tests
(real git, fake `gh`, `kubectl` and `devbox`), and AC-144.8's journey numbers come from the next recorded part 2 journey.

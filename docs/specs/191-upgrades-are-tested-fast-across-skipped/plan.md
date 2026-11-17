---
spec_id: 191-upgrades-are-tested-fast-across-skipped
shape: platform
spec_hash: 81c2c280d7af
summary: "A cluster-free upgrade render check (previous and oldest supported release) and the platform update e2e gate a release; the oldest-release cluster run and the Postgres 16 → 17 drill run nightly and on the changes that touch them"
tasks:
  - id: t1
    title: "release-check.py: from-tag previous|oldest, render/drill/run decisions, gate on two checks"
    files: [scripts/release-check.py, tests/cplat/test_upgrade_121_ops.py]
    covers: [AC-191.4, AC-191.5, AC-191.6, AC-191.7]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t2
    title: "upgrade-render-check.py compare: the breaking rules, Upgrade step acceptance, output and exit codes"
    files: [scripts/upgrade-render-check.py]
    covers: [AC-191.1, AC-191.2, AC-191.3]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t3
    title: "The shared upgrade system builder (create, update) without a cluster"
    files: [tests/e2e/lib/upgrade-system.sh]
    covers: [AC-191.2, AC-191.6]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t4
    title: "upgrade-render-check.py run: both from-releases, sections, render failures"
    files: [scripts/upgrade-render-check.py]
    covers: [AC-191.2, AC-191.4]
    parallel_safe: true
    depends_on: [t1, t2, t3]
    done: true
  - id: t5
    title: "upgrade.sh runs the platform update part; the drill moves to upgrade-drill.sh behind E2E_UPGRADE_DRILL=1"
    files: [tests/e2e/upgrade.sh, tests/e2e/upgrade-drill.sh, tests/cplat/test_upgrade_121_ops.py]
    covers: [AC-191.6, AC-191.7]
    parallel_safe: true
    depends_on: [t1, t3]
    done: true
  - id: t6
    title: "Workflows: upgrade render check, the previous- and oldest-release jobs, the drill workflow"
    files: [.github/workflows/e2e-upgrade.yml, .github/workflows/e2e-upgrade-drill.yml, tests/cplat/test_upgrade_121_ops.py]
    covers: [AC-191.4, AC-191.5, AC-191.6, AC-191.7]
    parallel_safe: true
    depends_on: [t1, t4, t5]
  - id: t7
    title: "CONTRIBUTING CI section, UPGRADES guide, ADR for the split, changelog fragment"
    files: [CONTRIBUTING.md, docs/UPGRADES.md, docs/adr/README.md, docs/adr/069-one-versions-table-pins-everything-and-every-release-proves-the-upgrade.md, docs/changelog.d/191-upgrade-render-check.changed.md]
    covers: [AC-191.3, AC-191.8]
    parallel_safe: true
    depends_on: [t4]
---

# Plan — 191 Upgrades are tested fast, across skipped versions, and the database drill leaves the release gate

The contract is [design.md](design.md): every printed line, exit code, job name, trigger and timeout. Levels:
t1, t2, t3 → t4, t5 → t6, t7. t4 calls `release-check.py from-tag` (t1) and the builder (t3) and extends t2's file; t5
calls `from-tag previous` and sources the builder; t6 runs what t4 and t5 built and reads t1's decide outputs; t7 runs the
render check (t4) to find the findings it must accept. `tests/cplat/test_upgrade_121_ops.py` holds spec 121 tests of
behaviour this spec replaces (AC-191.6 replaces AC-121.24); t1, t5 and t6 each adapt the tests their change breaks, in
that order.

## t1 — release-check.py: from-tag previous|oldest, render/drill/run decisions, gate on two checks

**Files:** scripts/release-check.py, tests/cplat/test_upgrade_121_ops.py
**Covers:** AC-191.4, AC-191.5, AC-191.6, AC-191.7
**Goal:** one script decides which from-release each upgrade test starts from, which upgrade jobs a change needs, and
whether a commit may be tagged (both gate checks green).

**Implementation notes:**
- `from-tag previous`: port the rule of `upgrade.sh` step 1 (lines 173–189 today) to Python with `git tag --merged HEAD
  --sort=-v:refname`, `git cat-file -e <tag>:scripts/cplat/versions.py`, `git tag --points-at HEAD`; lines as design.md.
- `from-tag oldest`: candidate major per design.md, Decisions (newest release heading newer than the previous release,
  else the previous release's major); newest `vX.0.*` by `vtuple`; the two `skipped:` lines; exit 0 in all three cases.
- `needs-upgrade-e2e`: compute `render`, `drill`, `run` from the same diff and `changes_since(base)`; print them in that
  order (`run` last). Database rows: diff entries whose `name` starts with `postgres ` or is `operator cloudnative-pg` /
  `operator plugin-barman-cloud`. Keep `E2E_PATHS`/`E2E_GLOBS` for `run`; add `RENDER_PATHS`, `RENDER_PREFIXES`
  (`templates/gitops-app/`), `DRILL_PATHS` constants.
- `gate`: `RENDER_NAME = "upgrade render check"`; judge each of the two names on the SHA, else on a same-tree head
  (`same_tree_heads` once, reused); print one line per check as design.md; exit 0 only when both are OK.
- Update the module docstring (subcommands, the two checks of the gate).
- In `test_upgrade_121_ops.py`, the gate tests: add a green `upgrade render check` run to the fixtures that expect a pass
  (`test_the_gate_passes_for_a_green_upgrade_e2e_ac_121_24`, `head_api`), so they keep testing the e2e half; nothing else.

**Done when:** the acceptance tests for `from-tag`, the three decide lines and the two-check gate pass; the existing
`needs-upgrade-e2e` and gate tests of `test_upgrade_121_ops.py` pass; `devbox run test-fast` is green.

## t2 — upgrade-render-check.py compare: the breaking rules, Upgrade step acceptance, output and exit codes

**Files:** scripts/upgrade-render-check.py
**Covers:** AC-191.1, AC-191.2, AC-191.3
**Goal:** given two gitops repos, render each with its own renderer and report, in seconds and without a cluster, every
change Kubernetes refuses in place or that loses data, unless a changelog `Upgrade step:` line accepts it.

**Implementation notes:**
- PEP 723 header (`pyyaml`), shebang, docstring with both usages; `sys.path` insert of `scripts/cplat` for
  `platrelease_changelog` (as `release-check.py` does, with its ModuleNotFoundError hint).
- `render(repo, side) -> None`: `uv run scripts/render.py` in the repo, capture output; non-zero → the exit-2 line of design.md.
- `objects(repo) -> dict[key, doc]` and `secrets(repo) -> dict[(env, ns, name), source]` per design.md (namespace
  resolution through the nearest `kustomization.yaml`; plan.json of `credentials-configmap.yaml`; ExternalSecret targets).
- `findings(old, new) -> list[Finding]`: a table of `(kinds, field path, predicate, reason)` rows mirroring the design
  table, plus the removal rules; `quantity(s) -> Decimal | None` for sizes.
- `upgrade_steps(repo, tag) -> dict[(kind, field), text]`: released sections > tag, `[Unreleased]`, fragments; the regex
  of design.md (first line wins for a key).
- Output: sort, print BREAKING/ACCEPTED lines, then the FAILED/OK last line; exit 0/1/2. Unreadable YAML or a missing
  `applications/<system>` → `ERROR:` and exit 2, never a traceback.
- `compare` subcommand wired in `main(argv)`; leave a `run` placeholder out (t4 adds it).

**Done when:** the acceptance tests for AC-191.1, AC-191.2 (OK line, exit 2 per side) and AC-191.3 pass with fixture repos,
and `devbox run test-fast` is green.

## t3 — The shared upgrade system builder (create, update) without a cluster

**Files:** tests/e2e/lib/upgrade-system.sh
**Covers:** AC-191.2, AC-191.6
**Goal:** one builder creates the upgrade system with a from-release's own cplat and updates it with the candidate, used by
the render check and the cluster e2e alike (A1).

**Implementation notes:**
- Move (copy now; t5 removes the originals) from `upgrade.sh`: the RESOURCE_TYPES/PLANNED_TYPES ast probe (`upg_types`),
  `needs_type` with its `skipped:` file, step 2's `system new`, `resource add` loop, the Python component edit and render
  (`upg_create`), step 3's `cplat platform update --skip-tasks`, the no-change case, the ff-merge and render (`upg_update`).
- `upg_create` takes the tag, adds the worktree `<work>/from`, never calls `local-cluster.sh`, docker or k3d.
- Script mode (`[ "${BASH_SOURCE[0]}" = "$0" ]`): `create <tag> <work>` / `update <work>`, `set -euo pipefail`, non-zero
  exit with the failing command's output on stderr, so the caller can quote its last line.
- Functions take paths as arguments and set only the documented variables (`FROM_TYPES`, `UPG_NOTHING_CHANGED`), so
  `upgrade.sh` can source it; add a `# shellcheck` source hint style header like `lib/probe.sh`.
- Keep the system identical to today's (design.md, builder contract).

**Done when:** `bash tests/e2e/lib/upgrade-system.sh create <previous tag> /tmp/x && … update /tmp/x` works locally
without docker, `shellcheck` (if `quality` runs it) is clean, and `devbox run test-fast` is green.

## t4 — upgrade-render-check.py run: both from-releases, sections, render failures

**Files:** scripts/upgrade-render-check.py
**Covers:** AC-191.2, AC-191.4
**Goal:** the CI job's one command: compare from the previous and the oldest supported release, each in its own section.

**Implementation notes:**
- Default mode (no subcommand), `--from TAG` repeatable, `--work DIR` (default a temp dir, removed at the end, worktrees
  removed with `git worktree remove --force`).
- Tags from `release-check.py from-tag previous` / `oldest` (subprocess, same interpreter); the `skipped:` and
  `both <tag>: compared once` lines of design.md.
- Per tag: `from <tag>:`; builder `create` (failure → from-release exit-2 line); copy `<work>/<tag>/upg-gitops` to
  `before/` (`shutil.copytree`, symlinks kept); builder `update` (failure → candidate exit-2 line); then the t2 compare
  function in-process.
- The final `upgrade render check: OK|FAILED (...)` line and exit code of design.md.

**Done when:** the acceptance tests for the run mode pass, a local run on this branch prints both sections, and
`devbox run test-fast` is green.

## t5 — upgrade.sh runs the platform update part; the drill moves to upgrade-drill.sh behind E2E_UPGRADE_DRILL=1

**Files:** tests/e2e/upgrade.sh, tests/e2e/upgrade-drill.sh, tests/cplat/test_upgrade_121_ops.py
**Covers:** AC-191.6, AC-191.7
**Goal:** the gate job sets up, updates and checks without backups or a major upgrade; the drill job runs the same and then
the guard and the 16 → 17 steps.

**Implementation notes:**
- Step 1: `FROM=${E2E_UPGRADE_FROM:-$(uv run "$root/scripts/release-check.py" from-tag previous)}`; source
  `lib/upgrade-system.sh` and call `upg_types`, `upg_create`, `upg_update` in place of the moved code.
- Move today's step 4 Guard, step 5 Majors and the major-17 part of step 6 (major, server_version, upgrade record,
  system status, CRDs) into `tests/e2e/upgrade-drill.sh` (sourced, no shebang logic of its own; header naming AC-121.25
  and AC-191.7); `upgrade.sh` sources it only when `E2E_UPGRADE_DRILL=1`.
- A common `final_checks` (step "4 Checks" without the drill, after the drill with it): `read_data` per env,
  `cplat instance verify` per env, doctor, the dry-run loop.
- Header: AC-191.6, AC-191.7, AC-121.25; budgets about 15 minutes (update part) and about 40 (drill); the 45-minute
  warning becomes 20 minutes without the drill and stays 45 with it.
- `test_upgrade_121_ops.py`, the upgrade.sh text tests: read `upgrade.sh`, `upgrade-drill.sh` and `lib/upgrade-system.sh`
  together where the needle moved, and the header test checks the new criteria and budget; the tests stay structural.

**Done when:** the acceptance tests for the script structure of AC-191.6/191.7 and the adapted spec 121 script tests pass,
`bash -n` is clean on all three files, `devbox run test-fast` is green; the cluster runs prove it in t6's CI.

## t6 — Workflows: upgrade render check, the previous- and oldest-release jobs, the drill workflow

**Files:** .github/workflows/e2e-upgrade.yml, .github/workflows/e2e-upgrade-drill.yml, tests/cplat/test_upgrade_121_ops.py
**Covers:** AC-191.4, AC-191.5, AC-191.6, AC-191.7
**Goal:** the four jobs with the names, triggers and timeouts of design.md; only two of them matter to the release gate.

**Implementation notes:**
- `e2e-upgrade.yml`: add the paths, the `render` output of `decide`, the `render` job (copier via `uv tool install copier`),
  the `upgrade` job timeout 45, the `upgrade-oldest` job (`from-tag oldest` step; `skipped:` prints and exits 0; else k3d,
  copier and `E2E_UPGRADE_FROM`); update the header comment (spec 191, the two gate checks).
- `e2e-upgrade-drill.yml`: new, top-level `permissions: contents: read`, actions pinned by SHA (same pins as
  `e2e-upgrade.yml`; `scripts/pin-actions.py` checks), concurrency, `decide` + `drill` per design.md.
- `test_upgrade_121_ops.py`: `E2E_PATHS` and the timeout in the workflow tests follow the new workflow (structure only).
- `release-guard.yml` stays unchanged (it runs `release-check.py gate`).

**Done when:** the acceptance tests for the workflows pass, `scripts/check-pins.py` and the workflow tests of spec 121/134
pass, and `devbox run test-fast` is green; on the pull request the `upgrade render check`, the previous-release job and the
drill run green.

## t7 — CONTRIBUTING CI section, UPGRADES guide, ADR for the split, changelog fragment

**Files:** CONTRIBUTING.md, docs/UPGRADES.md, docs/adr/README.md, docs/adr/069-one-versions-table-pins-everything-and-every-release-proves-the-upgrade.md, docs/changelog.d/191-upgrade-render-check.changed.md
**Covers:** AC-191.3, AC-191.8
**Goal:** contributors know the four upgrade jobs, the gate and how to accept a deliberate breaking change; the decision is
recorded.

**Implementation notes:**
- ADR: `cplat adr add upgrade-tests-split-a-fast-release-gate-from-nightly-runs --decision "A release waits for the upgrade
  render check and the platform update e2e from the previous release; the oldest-release cluster run and the Postgres major
  drill run nightly and on the changes that touch them"` (it writes the ADR file and its README row); fill in Context,
  Decision, Consequences, Not included from design.md. ADR-069: an `**Amended by:**` line pointing to the new ADR (point 4).
- CONTRIBUTING.md, Releases paragraph on the gate and "CI cost": the four jobs, when each runs, the two the gate requires,
  `Upgrade step: <Kind> <field>: <what the owner does>` in a fragment to accept a breaking change, and the local commands
  (`uv run scripts/upgrade-render-check.py [--from <tag>]`, `bash tests/e2e/upgrade.sh`,
  `E2E_UPGRADE_FROM=$(uv run scripts/release-check.py from-tag oldest) bash tests/e2e/upgrade.sh`,
  `E2E_UPGRADE_DRILL=1 bash tests/e2e/upgrade.sh`, `gh workflow run e2e-upgrade.yml|e2e-upgrade-drill.yml --ref <branch>`).
- docs/UPGRADES.md, "For maintainers: the release gate": the new gate; one sentence for owners that `Upgrade step:` lines in
  the changelog name what to do when jumping releases.
- Fragment (`changed`, README style, `(#400).`): what changes for maintainers. Run the render check on this branch; for each
  finding that is safe by design (for example ExternalSecrets that spec 128's credentials Jobs retire while keeping the
  Secret), add one `Upgrade step: <Kind> <field>: <what the owner does>` line to the fragment, after checking it is true.
- Keep the existing `test_contributing_names_the_release_gate_ac_121_24` and UPGRADES needles (`release gate`) true.

**Done when:** the acceptance tests for AC-191.8 pass, `uv run scripts/upgrade-render-check.py` exits 0 on this branch,
`cplat platform pr-check` and `scripts/check-links.py` pass, and `devbox run test-fast` is green.

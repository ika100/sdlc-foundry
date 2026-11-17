---
spec_id: 209-inline-scripts-add-no-uv-environment-per
shape: platform
spec_hash: 90f79495ce64
summary: "Inline scripts run through one helper, uv-script.sh, that keys uv's environment by the dependency list, not the script path; cplat, the launcher, the platform recipes and the gitops-app and cluster-gitops recipes use it, so new worktrees add no uv environment"
tasks:
  - id: t1
    title: "The uv-script.sh helper and the platform's own recipes"
    files: [templates/gitops-app/scripts/uv-script.sh, templates/cluster-gitops/scripts/uv-script.sh, scripts/uv-script.sh, scripts/sync-template-copies.py, devbox.json, scripts/ci-local.sh, scripts/test-plan.sh, scripts/test-detect-shape.sh]
    covers: [AC-209.1, AC-209.3, AC-209.5, AC-209.6, AC-209.7]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t2
    title: "The gitops-app and cluster-gitops recipes run inline scripts through the helper"
    files: [templates/gitops-app/devbox.json, templates/cluster-gitops/devbox.json, templates/cluster-gitops/scripts/bootstrap.sh, templates/cluster-gitops/scripts/cluster-up.sh, tests/cplat/test_130_empty_gates.py, tests/cplat/test_service_crds.py, tests/cplat/gates130_support.py]
    covers: [AC-209.2, AC-209.4, AC-209.7]
    parallel_safe: true
    depends_on: [t1]
    done: true
  - id: t3
    title: "cplat runs the scripts of a target repo through the platform's helper"
    files: [scripts/cplat/uvscript.py, scripts/cplat/gitops.py, scripts/cplat/update.py, scripts/cplat/clusterrepo.py, scripts/cplat/appship.py, scripts/cplat/appship_joint.py]
    covers: [AC-209.1, AC-209.7]
    parallel_safe: true
    depends_on: [t1]
    done: true
  - id: t4
    title: "The cplat launcher and the system prompts use the helper; plugin versions and changelog"
    files: [plugins/shared/bin/cplat, plugins/system/commands/plan.md, plugins/system/references/spec-list.md, plugins/shared/.claude-plugin/plugin.json, plugins/system/.claude-plugin/plugin.json, .claude-plugin/marketplace.json, docs/changelog.d/209-inline-scripts-add-no-uv-environment-per.fixed.md]
    covers: [AC-209.1, AC-209.7]
    parallel_safe: true
    depends_on: [t2]
---

# Plan — 209 Inline scripts add no uv environment per worktree

The contract is [design.md](design.md). t1 creates the helper, and every other task calls it. t2 (template recipes) and
t3 (cplat) share no file and run in one level. t4 depends on t2 because the prompts call the new `plan` recipe that t2
adds. The launcher needs only t1's helper, which t4 gets through t2. GitHub Actions workflows stay as they are (design,
Decisions).

## t1 — The uv-script.sh helper and the platform's own recipes

**Files:** templates/gitops-app/scripts/uv-script.sh, templates/cluster-gitops/scripts/uv-script.sh, scripts/uv-script.sh, scripts/sync-template-copies.py, devbox.json, scripts/ci-local.sh, scripts/test-plan.sh, scripts/test-detect-shape.sh
**Covers:** AC-209.1, AC-209.3, AC-209.5, AC-209.6, AC-209.7
**Goal:** write the helper once, keep its two copies in sync, and make the platform repo's recipes that run inline
scripts go through it, so a worktree of the platform repo adds no script environment.

**Implementation notes:**
- Write `templates/gitops-app/scripts/uv-script.sh` exactly to the design's `uv-script.sh` contract: optional leading
  `--quiet`, detect the `# /// script` line, read `requires-python` only from inside the block, and `exec` either branch.
  Make it executable and add a header comment in the style of `gate.sh`. It must work under bash 3.2 with `set -euo pipefail`.
- Check that the uv in use accepts a `.py` file in `--with-requirements` (devbox `uv@latest`, and 0.11.14 if it is at
  hand). Use the design's `tomllib` fallback only if it does not.
- Add `(APP / "uv-script.sh", CLUSTER / "uv-script.sh")` and `(APP / "uv-script.sh", ROOT / "scripts" / "uv-script.sh")`
  to `COPIES`, then run the script to write both copies.
- `devbox.json`: `validate` (`check-pins.py`), `shapes-check`, `quality` (`shapes.py check`) and `smoke-gitops` (the
  rendered repo's own helper) change to `bash scripts/uv-script.sh …`. Leave `sync-template-copies.py` and the
  `--with-requirements requirements-test.txt` calls alone.
- `scripts/ci-local.sh`: `shapes.py check` and `cplat/cplat.py platform rules check` go through the helper.
  `scripts/test-plan.sh`: `plan()` runs `bash "$here/scripts/uv-script.sh" scripts/plan.py "$@"` in `$tmp`.
  `scripts/test-detect-shape.sh`: `bash "$here/uv-script.sh" "$here/shapes.py" ids`.
- New files get the SPDX header the REUSE lint expects, like their neighbours.

**Done when:** the acceptance tests for AC-209.3, AC-209.5, AC-209.6 and the helper's share of AC-209.7 pass.
`uv run scripts/sync-template-copies.py --check`, `devbox run quality`, `devbox run test-plan` and `devbox run test-detect`
also pass.

## t2 — The gitops-app and cluster-gitops recipes run inline scripts through the helper

**Files:** templates/gitops-app/devbox.json, templates/cluster-gitops/devbox.json, templates/cluster-gitops/scripts/bootstrap.sh, templates/cluster-gitops/scripts/cluster-up.sh, tests/cplat/test_130_empty_gates.py, tests/cplat/test_service_crds.py, tests/cplat/gates130_support.py
**Covers:** AC-209.2, AC-209.4, AC-209.7
**Goal:** every recipe in the two gitops templates that runs an inline script calls `bash scripts/uv-script.sh`, and
`/platform:update` brings the change to existing repos with no edit by hand.

**Implementation notes:**
- gitops-app: `render`, `render-check`, `service-crds`, `plan-check`, `pin`, `upgrade-check`, `validate` (render.py,
  plan.py, check-k8s-labels.py) and `test-fast`. Add the new recipe `"plan": "bash scripts/uv-script.sh scripts/plan.py \"$@\""`.
- cluster-gitops: `render`, `render-check`, `check`, `cluster-down`, `validate` and `test-fast`; also
  `scripts/bootstrap.sh` (2 calls, `--quiet`) and `scripts/cluster-up.sh` (3 calls, `--quiet`).
- Keep each recipe's text the same apart from the `uv run` → `bash scripts/uv-script.sh` swap: `GATE_NAME=…` prefixes,
  `|| exit 1`, `&&` and the arguments.
- Update the recipe strings these existing tests pin: `test_130_empty_gates.py` (566–586) and `test_service_crds.py`
  (592). `test_service_crds.py:168` keeps its direct `uv run`, because it tests the script, not the recipe.
- `gates130_support.py` UV stub: after `run`, skip uv options (`--quiet`, `--no-project`, `--python <v>`,
  `--with-requirements <f>`) so that `python scripts/<x>.py …` and the `STUB_RENDER_EMPTY` render branch still run.
  The stub's own log line stays.
- AC-209.4: `update.merge_devbox` already replaces template recipes that equal the previous release's. Check with an
  update from the last release that no recipe ends up in `replaced`, and that `scripts/uv-script.sh` arrives as a new file.

**Done when:** the acceptance tests for AC-209.2 and AC-209.4 and the template share of AC-209.7 pass, and
`devbox run test-fast` is green.

## t3 — cplat runs the scripts of a target repo through the platform's helper

**Files:** scripts/cplat/uvscript.py, scripts/cplat/gitops.py, scripts/cplat/update.py, scripts/cplat/clusterrepo.py, scripts/cplat/appship.py, scripts/cplat/appship_joint.py
**Covers:** AC-209.1, AC-209.7
**Goal:** the `render.py`, `check.py`, `pin.py` and `plan.py` runs that cplat starts in dispatcher units, `compose/<spec>`
entries and staging worktrees add no script environment, including in repos that have not updated yet.

**Implementation notes:**
- New `uvscript.py` with `HELPER` and `script_cmd(script, *args, quiet=False)` exactly as the design specifies. It imports
  only `core.PLATFORM_ROOT`.
- Replace the call sites in the design's table: `gitops.py:76`, `update.py:599/713`, `clusterrepo.py:209/233`,
  `appship.py:317` and `appship_joint._devbox`. Keep the cwd, `check=` and the error and hint texts.
- Leave the `will_do` texts in `clusterrepo.py` (269, 296) unchanged.
- The existing fakes (`test_appship_097` FAKE_DEVBOX, `test_144_joint_pr` DEVBOX_144, `seam178_world`) find the script
  argument by its suffix and still work. A fake `render.py` without a PEP 723 block reaches the helper's plain
  `uv run` branch.

**Done when:** the acceptance tests for AC-209.1 (cplat runs in 5 new worktrees) and the cplat share of AC-209.7 pass,
and `devbox run test-fast` is green.

## t4 — The cplat launcher and the system prompts use the helper; plugin versions and changelog

**Files:** plugins/shared/bin/cplat, plugins/system/commands/plan.md, plugins/system/references/spec-list.md, plugins/shared/.claude-plugin/plugin.json, plugins/system/.claude-plugin/plugin.json, .claude-plugin/marketplace.json, docs/changelog.d/209-inline-scripts-add-no-uv-environment-per.fixed.md
**Covers:** AC-209.1, AC-209.7
**Goal:** `cplat` itself, started in a worktree of the platform repo (launcher source `checkout`), adds no environment
for `cplat.py`. Agent prompts run `plan.py` through the `plan` recipe (A5).

**Implementation notes:**
- Launcher, last line: when `$root/scripts/uv-script.sh` exists, use `exec bash "$root/scripts/uv-script.sh" "$root/scripts/cplat/cplat.py" "$@"`;
  otherwise use today's `exec uv run …`. Keep `CPLAT_SOURCE` and `PYTHONUNBUFFERED`. `tests/cplat/test_launcher.py` must
  stay green; its fake checkout has no helper and takes the fallback.
- `plan.md:32` changes to `devbox run plan show <spec_id>`. `plan.md:23` requires a `plan` recipe in `devbox.json` (else
  `/platform:update` first) instead of only `scripts/plan.py`. In `spec-list.md` (3, 7–10), `devbox run -- uv run scripts/plan.py <x>`
  becomes `devbox run plan <x>`.
- These edits change commands, not rules: no new rules-register entry. `cplat platform rules check` must pass (it
  resolves `devbox run plan` against the gitops-app recipes from t2), and the prompts must not grow.
- Bump `shared` and `system` by a patch version in both `plugin.json` and `.claude-plugin/marketplace.json`.
- Fragment `docs/changelog.d/209-inline-scripts-add-no-uv-environment-per.fixed.md`: cplat, the platform recipes and the
  gitops-app and cluster-gitops recipes no longer add a uv environment per worktree; `/platform:update` brings the
  change; no manual step.

**Done when:** the acceptance test for AC-209.1 through the launcher passes, `devbox run test-fast` is green, and
`cplat platform rules check` and `cplat platform pr-check` (plugin versions, fragment) pass.

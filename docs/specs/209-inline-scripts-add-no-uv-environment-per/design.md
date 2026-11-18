# Design — 209 Inline scripts add no uv environment per worktree

## Decisions

- **Inline scripts run through one helper, `uv-script.sh`, that gives uv the script's dependency list instead of the
  script's path.** `uv run <script>.py` keys its persistent script environment by the script's absolute path (verified in
  explore), so every worktree adds one. `uv run --no-project --with-requirements <script>.py python <script>.py` builds
  uv's cached `--with` environment instead, which uv keys by the hash of the resolved requirements and the interpreter.
  That gives exactly one environment per dependency list, whatever the path, worktree or clone (AC-209.1–209.3,
  AC-209.5; A2 allows sharing across clones, and A3 holds by construction). uv locks the cache entry while it builds it,
  so 3 runs at once end in one environment (AC-209.6).
- **The script still runs from its own path** (`python <script>.py`, same cwd): `__file__`, `sys.path[0]`, the repo-root
  logic of `render.py`/`plan.py`, stdin, stdout, stderr and the exit code stay the same (AC-209.7). Copying the script to a
  fixed per-repo location was rejected because it changes `__file__`, which the renderers use to find their repo.
- **A script with no `# /// script` block keeps `uv run <script>.py`** (uv creates no environment for it today either).
  So the helper is safe in front of any script, and the test fakes that write a plain `render.py` keep working.
- **One implementation, three copies**: the source is `templates/gitops-app/scripts/uv-script.sh`. `sync-template-copies.py`
  keeps `templates/cluster-gitops/scripts/uv-script.sh` and the platform's `scripts/uv-script.sh` equal to it. cplat calls
  the platform's copy by absolute path (`PLATFORM_ROOT/scripts/uv-script.sh`), never the target repo's. So it works in a
  generated repo that has not run `/platform:update` yet.
- **Agent prompts go through a recipe** (A5): the system plugin's prompts call `devbox run plan <args>` (a new gitops-app
  recipe) instead of `devbox run -- uv run scripts/plan.py <args>`.
- **GitHub Actions workflows stay as they are.** Each job gets a fresh runner, so path-keyed environments cost nothing
  there. AC-209.7 asks for unchanged CI results, so changing the workflows would add risk for no gain.
- **Out of scope by inspection:** `spec-check.sh` and `alert-poll.sh` run `cplat.py` from a fixed per-ref cache directory
  (one environment per platform release, not per worktree). `sync-template-copies.py`, `check-settings.py` and the other
  scripts without a PEP 723 block create no script environment. `uv run --with-requirements requirements-test.txt …` is
  already keyed by its dependencies.
- The decision that outlives this feature (inline scripts in cplat and recipes run through `uv-script.sh`, keyed by
  their dependencies) is ADR-117 (`docs/adr/117-uv-script-runner.md`).

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `templates/gitops-app/scripts/uv-script.sh` | the helper (source copy) | new |
| `templates/cluster-gitops/scripts/uv-script.sh`, `scripts/uv-script.sh` | synced copies | new |
| `scripts/sync-template-copies.py` | the two new (source, copy) pairs | changed |
| `devbox.json`, `scripts/ci-local.sh`, `scripts/test-plan.sh`, `scripts/test-detect-shape.sh` | platform recipes call the helper | changed |
| `templates/gitops-app/devbox.json`, `templates/cluster-gitops/devbox.json`, `templates/cluster-gitops/scripts/{bootstrap,cluster-up}.sh` | template recipes call the helper; new `plan` recipe | changed |
| `scripts/cplat/uvscript.py` | `script_cmd()` builds the argv cplat runs | new |
| `scripts/cplat/{gitops,update,clusterrepo,appship,appship_joint}.py` | use `script_cmd()` | changed |
| `plugins/shared/bin/cplat` | launcher runs `cplat.py` through the helper | changed |
| `plugins/system/commands/plan.md`, `plugins/system/references/spec-list.md` | `devbox run plan …` | changed |

## Contract

### `uv-script.sh`

```
bash scripts/uv-script.sh [--quiet] <script.py> [args...]
```

- `--quiet` (only as the first argument) is passed on as uv's `--quiet`; it replaces today's `uv run --quiet <script>`.
- `<script.py>` is a path relative to the cwd or absolute; the cwd is not changed.
- Script **with** a PEP 723 block (a line exactly `# /// script`):
  `exec uv run [--quiet] --no-project [--python "<requires-python>"] --with-requirements "<script.py>" python "<script.py>" [args...]`
  where `<requires-python>` is the block's `requires-python` value, passed only when the block has one.
- Script **without** a block: `exec uv run [--quiet] "<script.py>" [args...]` (today's behaviour).
- Exit code, stdout and stderr are the script's (`exec`); a missing script gives uv's error, as today.
- Must run under macOS's bash 3.2 with `set -euo pipefail`: no empty `"${arr[@]}"` (use `${arr[@]+"${arr[@]}"}` or a
  plain variable).
- Fallback, only if the uv version in use rejects a `.py` file in `--with-requirements`: read the block's
  `dependencies` with `uv run --no-project python -c` (stdlib `tomllib`) and pass one `--with <dep>` for each. The
  contract above stays the same.

### What the acceptance tests count

"Script environments" are the entries of `$(uv cache dir)/environments-v2/` (this honours `UV_CACHE_DIR`, A6). Compare
the count before and after a run in a new worktree: no new entry when the dependency list already has one, and one new
entry for each new dependency list.

### `scripts/cplat/uvscript.py`

```python
HELPER: Path  # = core.PLATFORM_ROOT / "scripts" / "uv-script.sh"
def script_cmd(script: str, *args: str, quiet: bool = False) -> list[str]:
    """["bash", str(HELPER), *(["--quiet"] if quiet else []), script, *args]"""
```

Call sites (cwd unchanged):

| Site | Before | After |
|---|---|---|
| `gitops.py:76`, `update.py:599/713`, `clusterrepo.py:209` | `["uv","run","scripts/render.py"]` | `script_cmd("scripts/render.py")` |
| `clusterrepo.py:233` | `["uv","run","scripts/check.py"]` | `script_cmd("scripts/check.py")` |
| `appship.py:317` | `["devbox","run","--","uv","run","scripts/plan.py","done",sid,rid]` | `["devbox","run","--",*script_cmd("scripts/plan.py","done",sid,rid)]` |
| `appship_joint._devbox(wt, *args)` | `["devbox","run","--","uv","run",*args]` | `["devbox","run","--",*script_cmd(*args)]`; its error text unchanged |

The descriptive `will_do` texts in `clusterrepo.py` (269, 296) stay as they are.

### Launcher `plugins/shared/bin/cplat`

The last line changes. When `$root/scripts/uv-script.sh` exists, it runs `exec bash "$root/scripts/uv-script.sh" "$root/scripts/cplat/cplat.py" "$@"`.
Otherwise (a `CPLAT_REF` older than this release) it runs `exec uv run "$root/scripts/cplat/cplat.py" "$@"` as today.

### Recipes

Every `uv run [--quiet] scripts/<x>.py …` in these recipes and scripts becomes `bash scripts/uv-script.sh [--quiet] scripts/<x>.py …`,
with the rest of the text unchanged:

- gitops-app `devbox.json`: `render`, `render-check`, `service-crds`, `plan-check`, `pin`, `upgrade-check`, `validate`,
  `test-fast`; new recipe `"plan": "bash scripts/uv-script.sh scripts/plan.py \"$@\""`.
- cluster-gitops `devbox.json`: `render`, `render-check`, `check`, `cluster-down`, `validate`, `test-fast`;
  `scripts/bootstrap.sh` (45, 60), `scripts/cluster-up.sh` (11, 24, 39).
- platform `devbox.json`: `validate` (check-pins.py), `shapes-check`, `quality` (shapes.py), `smoke-gitops` (render.py in
  the rendered repo, through that repo's own `scripts/uv-script.sh`); `scripts/ci-local.sh` (shapes.py and the
  cplat.py rules check); `scripts/test-plan.sh` (`plan()`, through the checkout's helper by absolute path);
  `scripts/test-detect-shape.sh` (shapes.py ids).

`/platform:update` delivers the new recipes through the existing devbox merge, which replaces template recipes that equal
the previous release's (spec 060/086). It delivers `scripts/uv-script.sh` as a new template file (AC-209.4, A7).

---
spec_id: 199-the-journey-15-seams
shape: platform
spec_hash: "27e6f003c2cd"
summary: Local URLs (smoke, system ship land, promote --smoke, Grafana) use the port the k3d cluster's Gateway really got, asked once per invocation from docker, with LOCAL_HTTP_PORT and 8088 as before
tasks:
  - id: t1
    title: localport module and the model's port rule
    files: [scripts/cplat/localport.py, scripts/cplat/model.py, scripts/cplat/cplat.py, tests/cplat/conftest.py]
    covers: [AC-199.1, AC-199.2, AC-199.3, AC-199.4, AC-199.5]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t2
    title: Smoke paths read the settings of their repo
    files: [scripts/cplat/smoke.py, scripts/cplat/appship_joint.py]
    covers: [AC-199.1, AC-199.2, AC-199.5]
    parallel_safe: true
    depends_on: [t1]
  - id: t3
    title: system set and system status pass the system to the Grafana URL
    files: [scripts/cplat/status.py, scripts/cplat/systemset.py]
    covers: [AC-199.3]
    parallel_safe: true
    depends_on: [t1]
  - id: t4
    title: Docs and changelog fragment
    files: [docs/unattended-delivery.md, site/src/content/docs/get-started/local-cluster.md, docs/changelog.d/199-the-journey-15-seams.fixed.md]
    covers: [AC-199.4]
    parallel_safe: true
    depends_on: []
    done: true
---

# Plan — 199 The journey 15 seams

Contracts are in [design.md](design.md). Levels: t1, t4 → t2, t3. No two tasks share a file.

## t1 — localport module and the model's port rule

**Files:** scripts/cplat/localport.py, scripts/cplat/model.py, scripts/cplat/cplat.py, tests/cplat/conftest.py
**Covers:** AC-199.1, AC-199.2, AC-199.3, AC-199.4, AC-199.5
**Goal:** `model.local_port(system)` returns `LOCAL_HTTP_PORT` when all digits, else the port `docker port
k3d-<cluster>-serverlb 80/tcp` reports for the system's cluster, else 8088; every `.localhost` component URL and the
Grafana URL use it; docker is asked at most once per cluster per `cplat` invocation and never for a non-local host.

**Implementation notes:**
- New `localport.py` per design.md: `TIMEOUT_S`, `_CACHE`, `reset`, `use_repo`, `cluster`, `docker_port`, `lookup`; it
  imports `settings`, never `model` (the model imports it). Module docstring names spec 199.
- `cluster`: `LOCAL_CLUSTER`, then a `k3d-<name>` context from `settings.kube_context(repo or Path.cwd())` (ignore
  `PlatformError`), then `<system>-local`, else None.
- `docker_port`: `subprocess.run` with `timeout=TIMEOUT_S`; OSError, `TimeoutExpired`, non-zero exit, no line or a
  non-numeric/out-of-range port → None; parse the first non-empty line after its last `:`.
- `lookup` caches None too, and calls `docker_port` through the module attribute (the conftest seam patches it).
- `model.py`: `local_port(system=None)`, `grafana_url(host, system=None)`, `grafana_location(host, system=None)`;
  `_url` passes its `system` on the `.localhost` branch only; update the `Instance.url` and module docstrings (the one
  observed value the model asks `localport` for).
- `cplat.py`: `localport.reset()` first thing in `main`.
- `conftest.py`: autouse `no_real_docker_port` per design.md (unset `LOCAL_CLUSTER`, `localport.reset()`, patch
  `docker_port` to return None unless the test file name starts with `test_199_`).

**Done when:** the AC-199.4 and AC-199.5 acceptance tests pass, and the spec 113/114/197 model URL and Grafana tests
(`test_model.py`, `test_model_show.py`, `test_system_model_114.py`, `test_197_seams.py`) stay green.

## t2 — Smoke paths read the settings of their repo

**Files:** scripts/cplat/smoke.py, scripts/cplat/appship_joint.py
**Covers:** AC-199.1, AC-199.2, AC-199.5
**Goal:** the dev smoke of `component ship deploy`, `instance verify`, `instance promote --smoke` and the staging deploy
smoke (all through `smoke.dev_url`), and the dev and staging smoke of `system ship land`, resolve the cluster with the
`kube_context:` of the repo they work on, so the smoke runs on the cluster's port and is recorded.

**Implementation notes:**
- `smoke.dev_url`: `localport.use_repo(repo)` before reading the gitops-app.
- `appship_joint._smoke`: `localport.use_repo(gitops)` before `m.url(comp, env)`.
- No change to recording, staging promotion or evidence: a smoke that reaches the cluster records as today.

**Done when:** the AC-199.1 and AC-199.2 acceptance tests pass, and the spec 091/093/142/155 ship, verify, promote and
system-ship smoke tests stay green.

## t3 — system set and system status pass the system to the Grafana URL

**Files:** scripts/cplat/status.py, scripts/cplat/systemset.py
**Covers:** AC-199.3
**Goal:** the `Grafana:` line of `system set --observability lgtm`, the Grafana cell of `system status` and
`grafana_url` in both `--json` outputs carry the cluster's port.

**Implementation notes:**
- `systemset.main`: `localport.use_repo(repo)`; `model.grafana_url(host, app_dir.name)` and
  `model.grafana_location(host, app_dir.name)`.
- `status.py`: `localport.use_repo(repo)` where the repo is resolved; `model.grafana_url(e.host, m.system)` in
  `obs_cell`.
- No change to output wording.

**Done when:** the AC-199.3 acceptance tests pass and the AC-197.3 / AC-197.4 tests stay green.

## t4 — Docs and changelog fragment

**Files:** docs/unattended-delivery.md, site/src/content/docs/get-started/local-cluster.md, docs/changelog.d/199-the-journey-15-seams.fixed.md
**Covers:** AC-199.4
**Goal:** the docs state the port rule users now get, and the release notes name the fix.

**Implementation notes:**
- `docs/unattended-delivery.md` (The dev URL): for `*.localhost` hosts the port is `LOCAL_HTTP_PORT` when it is a
  number, else the port the k3d cluster's Gateway listens on (cluster `LOCAL_CLUSTER`, a configured `k3d-<name>`
  context, else `<system>-local`), else 8088.
- `site/.../local-cluster.md`: one sentence after the port step: `cplat` finds the port the cluster got, so smoke and
  Grafana links follow it without `LOCAL_HTTP_PORT`. No spec numbers in the guide.
- Fragment per `docs/changelog.d/README.md`: one entry for the journey 15 seam (smoke, promotion evidence and Grafana on
  a cluster whose Gateway got another port).

**Done when:** `cplat platform pr-check` reports no fragment or link error and `python3 scripts/check-docs.py` (if the
repo's docs check covers these files) passes.

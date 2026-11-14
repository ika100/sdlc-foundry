# Design — 199 The journey 15 seams

## Decisions

- **One port rule, in the model, asking one new I/O module.** Every local URL `cplat` builds (component URLs through
  `model._url`, which `smoke.dev_url`, `appship_joint._smoke`, `staging_deploy` and `instance promote --smoke` all use;
  the Grafana URL through `model.grafana_url`) already goes through `model.local_port()` (spec 197). That function gains
  a `system` argument and asks the new `localport` module for the cluster's port, so the three smoke paths, the prod
  evidence (it reads the records those smokes now write) and Grafana are fixed by one change and cannot drift (AC-199.1
  to AC-199.4).
- **The model keeps its rule "no subprocess" except for this one observed value.** The Gateway port is observed state,
  computed when asked (ADR-053, decision 4), like `Instance.url` already is; the `docker` call lives in `localport`,
  never in `model.py` itself, and the model's docstring names the exception. Threading a port callable through every
  `build` / `load_dir` / `load_remote` caller (about 30) was rejected: it changes many modules for one value. Feature-local,
  so no ADR.
- **Cache per process, reset per `cplat` invocation (A2).** A module dict keyed by cluster name, cleared at the start of
  `cplat.main`, so one invocation asks docker at most once per cluster and the next command sees a recreated cluster
  (AC-199.5). Nothing is written to disk.
- **The settings file is the one of the repo the command works on.** `localport.use_repo(repo)` names it; the four
  places that build local URLs for a known repo call it (`smoke.dev_url`, `appship_joint._smoke`, `status.main`,
  `systemset.main`); otherwise the current directory. `CPLAT_KUBE_CONTEXT` and the user file are repo-independent.
- **Silent fallback (A3).** Docker missing, a non-zero exit, a timeout (5 s), no port line or an unparsable port all
  give 8088 with no message; a malformed `kube_context:` value is ignored here (falls through to `<system>-local`), so a
  URL build never raises.
- **Tests never ask the developer's docker by accident.** An autouse fixture in `tests/cplat/conftest.py` replaces
  `localport.docker_port` with "no answer" and unsets `LOCAL_CLUSTER`, except in files named `test_199_*`, which fake
  `docker` on `PATH` (A6), like spec 184's fixture exemption. Without it, a developer with a real `k3d-shop-local`
  cluster would see the suite's 8088 assertions fail.

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `scripts/cplat/localport.py` | cluster name, `docker port` lookup, per-invocation cache | new |
| `scripts/cplat/model.py` | `local_port(system)`, `grafana_url(host, system)`, `grafana_location(host, system)`; `_url` passes its system | changed |
| `scripts/cplat/cplat.py` | `localport.reset()` at the start of `main` | changed |
| `scripts/cplat/smoke.py`, `scripts/cplat/appship_joint.py` | `localport.use_repo(...)` before building the URL | changed |
| `scripts/cplat/status.py`, `scripts/cplat/systemset.py` | `use_repo`; pass the system name to `grafana_url` / `grafana_location` | changed |
| `tests/cplat/conftest.py` | autouse fixture `no_real_docker_port` | changed |

## Contract

### `localport` (new module, `scripts/cplat/localport.py`)

```python
TIMEOUT_S = 5
_CACHE: dict[str, int | None]          # cluster name -> port (None: docker gave no port); process memory only

def reset() -> None                    # clears _CACHE and the repo set by use_repo
def use_repo(repo: Path | None) -> None  # the repo whose .platform-settings.yml `kube_context:` is read; None: the cwd

def cluster(system: str | None) -> str | None
    # 1. LOCAL_CLUSTER, stripped, when non-empty
    # 2. ctx[4:] when settings.kube_context(repo or cwd)[0] is "k3d-<name>" with a non-empty <name>
    #    (CPLAT_KUBE_CONTEXT, then the project file, then the user file); a PlatformError is ignored
    # 3. f"{system}-local" when system is given
    # 4. None

def docker_port(cluster: str) -> int | None
    # subprocess.run(["docker", "port", f"k3d-{cluster}-serverlb", "80/tcp"], capture_output=True, text=True,
    #                timeout=TIMEOUT_S, check=False)
    # OSError / TimeoutExpired / exit != 0 -> None
    # else the first non-empty stdout line, text after its last ":" stripped; all digits and 1..65535 -> int, else None
    # ("0.0.0.0:8089\n[::]:8089\n" -> 8089)

def lookup(system: str | None) -> int | None
    # name = cluster(system); None -> None (docker not asked)
    # name in _CACHE -> _CACHE[name]; else _CACHE[name] = docker_port(name)   (calls the module attribute, so tests can patch it)
```

### `model` (changed)

```python
def local_port(system: str | None = None) -> int
    # LOCAL_HTTP_PORT when all digits (docker not asked, AC-199.4 / A4; "auto" or "" count as unset)
    # else localport.lookup(system) when it returns a port
    # else DEFAULT_LOCAL_PORT (8088)

def grafana_url(host: str | None, system: str | None = None) -> str | None
    # f"http://grafana.localhost:{local_port(system)}/" when host ends with ".localhost", else None (docker never asked)
def grafana_location(host: str | None, system: str | None = None) -> str   # grafana_url(...) or GRAFANA_ELSEWHERE
```

- `_url(system, c, e)` calls `local_port(system)` only on its `.localhost` branch; an `https://` host or a `url_template`
  never asks docker (AC-199.4, non-goal "URLs of non-local environments").
- Calls without `system` keep working (spec 197's tests): the cluster is `LOCAL_CLUSTER` or the k3d context, else no
  lookup and 8088.
- `Instance.url`, `Model.url`, `to_dict()["instances"][i]["url"]` and `cplat model show` carry the discovered port.

### Callers (no new flags, no new output lines)

| Command | Change | Criterion |
|---|---|---|
| `cplat component ship deploy` dev smoke, `cplat instance verify`, `cplat instance promote --smoke` (via `smoke.main` → `dev_url`), the staging deploy smoke | `smoke.dev_url` calls `localport.use_repo(repo)`; the URL is `http://<component host>:<port>`; `smoke ({env}) against <url>:` and the recorded `base_url` show it | AC-199.1, AC-199.2 |
| `cplat system ship land` | `appship_joint._smoke` calls `localport.use_repo(gitops)` before `m.url(...)` | AC-199.2 |
| `cplat system set --env <env> --observability lgtm` | `use_repo(repo)`; `grafana_url(host, app_dir.name)` / `grafana_location(host, app_dir.name)`: the `Grafana: <url>` line and `grafana_url` in `--json` | AC-199.3 |
| `cplat system status` | `use_repo(repo)`; `cell["grafana_url"] = model.grafana_url(e.host, m.system)`; the `Grafana <url>` cell text | AC-199.3 |

A passing smoke on the discovered port is recorded as today (`passed`, the run store's `verify` / ship record), so the
staging promotion and the prod evidence behave exactly as on the default port; no change in `staging.py`,
`evidence.py` or `promote.py` is needed.

### Test seam (binding for the acceptance tests)

- `tests/cplat/conftest.py` autouse `no_real_docker_port`: unsets `LOCAL_CLUSTER` and calls `localport.reset()` for every
  test; for test files whose name does not start with `test_199_` it also sets `localport.docker_port` to
  `lambda cluster: None`. Spec 199's tests (`test_199_*.py`) put a fake `docker` executable first on `PATH` (it may log its
  argv to a file to count calls) and get the real `subprocess` path.
- Each `cplat.main([...])` call is one invocation: the cache is empty at its start.

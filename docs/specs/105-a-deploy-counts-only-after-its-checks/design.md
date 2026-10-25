# Design — 105 A deploy counts only after its checks pass

## Decisions

- **One registry helper, `registry.py`, shared with spec 106.** `registry.digest(image, tag) -> str` reads the
  digest of a tag from GHCR through `gh api` (`/users|orgs/{owner}/packages/container/{name}/versions`, the version
  whose `metadata.container.tags` holds the tag; its `name` is `sha256:<64 hex>`). A failed lookup raises
  `RegistryError` naming the call and the fix (`gh auth refresh -s read:packages` for a 403/404 on the package).
  Tests replace one seam, `registry.gh`.
- **The running digest comes from the cluster** (AC-105.1): `cluster.running_digest(context, namespace, workload)`
  runs `kubectl --context C -n N get pods -l app.kubernetes.io/name=<svc> -o json` and takes the `imageID`
  (`…@sha256:<64>`) of the service's container in Ready pods; several different digests or none → `None`. The
  namespace and kube context are the ones `cplat ship deploy` already uses for Argo. `None` makes the smoke outcome
  `not-run` with reason `image digest unknown` (never a pass).
- **The `smoke` record section and the ship state gain `digest`** (AC-105.1). `staging_deploy.promote` compares it with
  `registry.digest(<service image>, <tag to pin>)` before dispatching `pin-staging.yml` (AC-105.2); a mismatch pins
  nothing and reports `digest changed since smoke: <recorded> -> <current>`, escalating with cause `decision`.
  `/gitops:promote … staging prod` (`promote.py` evidence summary, spec 093) prints the checked digest and flags
  `digest differs from what staging runs` when the staging pin's digest is another (AC-105.3).
- **Classification by symptom** (AC-105.4) in `smoke.classify(base_url, attempt)`: after a red attempt, probe the base
  URL (`smoke.status(url)`, which returns the HTTP status or the error text). Unreachable (connection refused, DNS,
  timeout, TLS) or 502/503/504, together with every test of the attempt failing, → `environment`; otherwise
  `application`. `SmokeResult.failure_class` carries it into the deploy output, the record (`smoke.class`) and the
  issue body.
- **Retries by class** (AC-105.5): `run_smoke` keeps its one retry for `application`. For `environment` it makes up
  to 3 attempts in total, 30 s apart, inside the existing 600 s limit. A persistent `environment` failure escalates
  with cause `environment` (ship's `infra` cause; `ESCALATION_CAUSES` already has `environment`) and reason
  `smoke red in dev: environment (<url>)`, files no issue in the service repo, and skips the staging promotion.
- **`not-run` stays a note** (AC-105.6): `_smoke_finish` already reports `NOT VERIFIED`; the change is that
  `staging_deploy.promote` refuses a `not-run` dev result in code (`skip(..., "dev smoke not run")`), and one test pins
  the whole rule.
- **Replays** (AC-105.7): `cplat ship deploy` on a state whose `smoke.outcome` is passed and whose `smoke.digest`
  equals the running digest skips smoke and goes on; another digest or no digest runs smoke again.
- **Gate table** (AC-105.8): `docs/unattended-delivery.md` gets one table "Deploy gate" with columns step, enforced by
  (`code` or `agent`), check, test. `tests/cplat/test_deploy_gate_table.py` parses it and fails when a row's test does
  not exist in `tests/cplat` or a `code` row names no test.

## Contract

```
registry.digest(image: str, tag: str) -> "sha256:<64 hex>"          raises RegistryError(message, hint)
cluster.running_digest(context, namespace, service) -> str | None
smoke.classify(base_url, attempt) -> "environment" | "application"
SmokeResult: + digest: str | None, + failure_class: str | None, + attempts: int
record smoke section: + "digest", + "class", + "attempts"
```

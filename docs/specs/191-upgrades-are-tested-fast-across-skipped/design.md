# Design — 191 Upgrades are tested fast, across skipped versions, and the database drill leaves the release gate

## Decisions

- **The render check is `scripts/upgrade-render-check.py`, a uv script next to `scripts/release-check.py`, not a cplat
  command.** It is release tooling of this repo (like `release-check.py`), never runs in a generated repo, and must not match
  `scripts/cplat/upgrade*.py`, which starts the cluster update e2e. It has two modes: `compare` (two system repos, no
  network, what the acceptance tests drive) and the default `run` mode (builds both sides for each from-release, then
  compares).
- **Both sides are built by one shared builder, `tests/e2e/lib/upgrade-system.sh`** (A1). Its `create` and `update` are
  moved out of `tests/e2e/upgrade.sh` (step 1's type detection, step 2's system, resources, component and render, step 3's
  `cplat platform update`, merge and render), so the render check and the cluster e2e build the same system the same way:
  the from-release's own cplat creates it, the candidate's `cplat platform update` updates it, held pins included. The
  builder never starts a container or a cluster.
- **Each side is rendered by its own repo's `scripts/render.py`** inside `compare` (`uv run scripts/render.py` in the repo).
  The before-repo still carries the from-release's renderer, the after-repo the candidate's (the update replaced it), so a
  render failure names its side (A12) and `compare` can be tested with two small fixture repos.
- **The tag rules live in `scripts/release-check.py from-tag previous|oldest`**, so the cluster e2e, the render check and the
  workflows pick the same tags. `previous` keeps today's rule of `upgrade.sh` step 1; `oldest` is the newest `vX.0.*` of the
  candidate's major (A8). The candidate's major is the major of the newest `## [x.y.z]` heading of `docs/CHANGELOG.md` that
  is newer than the previous release (a release pull request), else the previous release's major.
- **"Rendered Secrets" are every Secret the render produces**: `Secret` objects, the target of each `ExternalSecret`
  (`spec.target.name`, default its `metadata.name`) and every `secrets[].name` in the `plan.json` of a credentials ConfigMap
  (`credentials-configmap.yaml`, spec 128). Since spec 128 the render writes no Secret objects; a renamed generated Secret
  only shows in `plan.json`, and it is the case the spec names (Problem: "a renamed ... Secret applies cleanly").
- **Service `spec.type` uses the reason `immutable: Kubernetes refuses the change`.** AC-191.1 allows two reasons; A3 counts
  the type change with the clusterIP change, so it takes the same reason.
- **The drill gets its own workflow, `.github/workflows/e2e-upgrade-drill.yml`.** `cplat platform release` waits for the whole
  `e2e-upgrade.yml` run on the merge commit (`platrelease_publish._upgrade_e2e`); a drill in that workflow would put its
  25 minutes back into the release. The oldest-release job stays in `e2e-upgrade.yml`, gated to schedule and dispatch, where
  the release (which waits on `--event push` runs only) never meets it.
- **The cluster e2e keeps one script.** `tests/e2e/upgrade.sh` runs the platform update part; `E2E_UPGRADE_DRILL=1` makes it
  source `tests/e2e/upgrade-drill.sh` (steps 4 Guard and 5 Majors, and the major-17 checks) before the common final checks.
  A separate drill file lets the drill decide on "the drill's own steps" by path (AC-191.7).
- **`release-check.py needs-upgrade-e2e` prints three lines, `run=` last**, so the existing `decide` steps and the tests
  that read its last line keep working.
- **The release gate checks each required check on its own**: green on the SHA, else green on a same-tree head of its pull
  request (#400). The existing lines of the upgrade e2e stay word for word; the render check gets the same lines with its
  own name. `cplat platform release` needs no change: its release pull request adds a release heading, so both checks run
  there, `pr.wait` judges them, and the post-merge gate reads them on the same-tree head.
- **The split outlives this feature** (which checks gate a release, which run nightly): an ADR records it and amends
  ADR-069 point 4 (plan t7).

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `scripts/upgrade-render-check.py` | `compare` (rules, changelog acceptance, output) and `run` (tags, sections, builder, exit codes) | new |
| `tests/e2e/lib/upgrade-system.sh` | builder: `create`, `update` (sourced, or run as a script) | new |
| `scripts/release-check.py` | `from-tag`, three-line `needs-upgrade-e2e`, gate on two checks | changed |
| `tests/e2e/upgrade.sh` | platform update part; sources the builder; `E2E_UPGRADE_DRILL=1` sources the drill | changed |
| `tests/e2e/upgrade-drill.sh` | steps 4 Guard, 5 Majors and the major-17 checks, moved out of `upgrade.sh` | new |
| `.github/workflows/e2e-upgrade.yml` | `decide`, `upgrade render check`, the previous-release job, the oldest-release job | changed |
| `.github/workflows/e2e-upgrade-drill.yml` | `decide`, `e2e upgrade drill (Postgres 16 → 17)` | new |
| `CONTRIBUTING.md`, `docs/UPGRADES.md`, ADR, fragment | the four jobs, the gate, `Upgrade step:` lines | changed / new |

## Contract

### `scripts/upgrade-render-check.py compare` (AC-191.1, AC-191.2, AC-191.3)

```
uv run scripts/upgrade-render-check.py compare --from-tag TAG [--repo DIR] BEFORE AFTER
```

- `BEFORE`, `AFTER`: gitops repos (each with `scripts/render.py` and `applications/<system>/system.yaml`). `compare` runs
  `uv run scripts/render.py` in each (BEFORE first); `--repo` is the platform checkout whose changelog is read (default:
  the checkout the script lives in). `TAG` is only a label and the changelog range start.
- **Render failure (exit 2)**: a non-zero render prints, as the last line,
  `ERROR: from-release <TAG> does not render: <last non-empty line of its output>` or
  `ERROR: candidate does not render: <last non-empty line of its output>`, and stops.
- **Objects of an environment**: every YAML document (`kind` and `metadata.name` set) in the files under
  `applications/<system>/{addons,overlays,policies}/<env>/**`, except `kustomization.yaml`; `<env>` in dev, staging, prod
  (the directories present on either side). Namespace: `metadata.namespace`, else the `namespace:` of the nearest
  `kustomization.yaml` above the file, else `<system>-<env>`. Key: (env, kind, namespace, name). `applicationset.yaml`,
  `operators/` and `bootstrap/` are not environment objects.
- **Rules** (old = from-release object, new = candidate object with the same key; absent field = `<unset>`):

  | Kind | Field (as printed) | Breaking when | Reason |
  |---|---|---|---|
  | Deployment, StatefulSet, DaemonSet, Job | `spec.selector` | old != new | immutable |
  | StatefulSet | `spec.volumeClaimTemplates` | old != new | immutable |
  | StatefulSet | `spec.serviceName` | old != new | immutable |
  | PersistentVolumeClaim | `spec.storageClassName` | old != new | immutable |
  | PersistentVolumeClaim | `spec.accessModes` | old != new | immutable |
  | PersistentVolumeClaim | `spec.resources.requests.storage` | new < old (quantities) | immutable |
  | Cluster (`postgresql.cnpg.io/*`) | `spec.storage.storageClass` | old != new | immutable |
  | Cluster (`postgresql.cnpg.io/*`) | `spec.storage.size` | new < old (quantities) | immutable |
  | Service | `spec.clusterIP` | old is set and new != old | immutable |
  | Service | `spec.type` | old != new | immutable |
  | PersistentVolumeClaim, ExternalSecret, Cluster (`postgresql.cnpg.io/*`), StatefulSet with `spec.volumeClaimTemplates` | `object` | old present, no new with that key | loses data |
  | Secret (rendered Secrets, see Decisions; namespace as for the object that names it) | `object` | old name produced, not produced by the candidate | loses data |

  `immutable` prints as `immutable: Kubernetes refuses the change`. Quantities: plain numbers and the suffixes
  `k M G T P E` / `Ki Mi Gi Ti Pi Ei` (and `m`); an unparsable size compares as text (breaking when it differs). Values
  print as compact JSON with sorted keys (`{"matchLabels":{"app":"x"}}`), scalars bare; removed prints `removed`, old of a
  removed object `present`. Everything else (new objects, images, pins, labels and annotations outside a selector, a larger
  size, a removed object of another kind) is not a finding.
- **Acceptance (AC-191.3)**: the changelog text between TAG and the candidate is the body of every `## [x.y.z]` section of
  `<repo>/docs/CHANGELOG.md` with x.y.z > TAG, plus its `## [Unreleased]` body, plus every fragment in
  `<repo>/docs/changelog.d/` (`platrelease_changelog.read_fragments`). A line matching
  `Upgrade step:\s*(?P<kind>[A-Za-z]+)\s+(?P<field>\S+?):\s*(?P<text>.+)` (anywhere in the line, list marker allowed)
  accepts every finding of that kind and printed field, for every object and environment.
- **Output**, one line per finding, sorted by env (dev, staging, prod), kind, namespace, name, field:

  ```
  BREAKING <env> <Kind> <namespace>/<name> <field>: <old> -> <new|removed> (<reason>) (accept it with a changelog line "Upgrade step: <Kind> <field>: ...")
  ACCEPTED <env> <Kind> <namespace>/<name> <field> (upgrade step: <text>)
  ```

  Last line and exit code:
  - any BREAKING: `FAILED: <n> breaking change(s), <TAG> -> candidate` (n = BREAKING lines), exit 1;
  - else: `OK: <m> objects in <envs> compared, <TAG> -> candidate, no breaking change`, with ` (<k> accepted)` appended
    when k > 0, exit 0. m = number of from-release objects plus rendered Secrets; envs = `dev, staging, prod` (those present).
- Any other failure (unreadable YAML, missing directory): `ERROR: <what>` and exit 2.

### `scripts/upgrade-render-check.py` (run mode, AC-191.4)

```
uv run scripts/upgrade-render-check.py [--from TAG]... [--work DIR]
```

- Without `--from`: the from-releases are `release-check.py from-tag previous` and `from-tag oldest`. When `oldest` prints
  `skipped: <reason>`, the run prints `oldest supported release: skipped: <reason>` and compares from the previous release only;
  when both are the same tag it prints `previous and oldest supported release are both <tag>: compared once`.
- Per from-release, a section: a line `from <tag>:`, then the builder (`upgrade-system.sh create <tag> <dir>`; on failure
  `ERROR: from-release <tag> does not render: <last line>`, section exit 2), a copy of the created gitops repo as BEFORE,
  `upgrade-system.sh update <dir>` (on failure `ERROR: candidate does not render: <last line>`, exit 2), then `compare`
  with that BEFORE and the updated repo as AFTER (its lines, unchanged).
- Last line: `upgrade render check: OK (<tags>)` with exit 0 when every section passed, else
  `upgrade render check: FAILED (from <tag>: exit <c>[, from <tag>: exit <c>])` with exit 2 when any section exited 2, else 1.
- Needs git with the tags, uv and copier; no docker, no cluster.

### `tests/e2e/lib/upgrade-system.sh`

```
bash tests/e2e/lib/upgrade-system.sh create <tag> <work>   # worktree <work>/from at <tag>; <work>/upg-gitops, <work>/upg-api; rendered and committed
bash tests/e2e/lib/upgrade-system.sh update <work>         # candidate cplat platform update --skip-tasks, merged into main, rendered, committed
```

Sourced, it defines `upg_types <from-dir>` (sets `FROM_TYPES`), `upg_create <tag> <work> <port> <registry>` and
`upg_update <work>` (writes `<work>/update.out`; sets `UPG_NOTHING_CHANGED=1` when the update made no branch). The system is
the one of `upgrade.sh` today: system `upg`, `upg-api` (python, dev/staging/prod, staging `after-dev-smoke`, generated
`upg-api-auth=JWT_KEY`), `postgres --version 16`, `files` bucket, `sessions` cache, `bus` broker with api `orders` where the
release supports the type (printing `skipped: ...` as today). Defaults: port 8098, registry `k3d-upg-local-registry:5112`.

### `scripts/release-check.py` (AC-191.4 to AC-191.7)

- `from-tag previous`: prints the tag (`$E2E_UPGRADE_FROM` is not read here; `upgrade.sh` keeps it); the rule of
  `upgrade.sh` step 1 today: the newest tag `v*` merged into HEAD that has `scripts/cplat/versions.py` and does not point at
  HEAD, else the newest `v5.0.*` while no tag has that file. None: `ERROR: no previous release tag found (v5.0.*)`, exit 1.
- `from-tag oldest`: prints the newest `vX.0.*` tag of the candidate's major (Decisions), exit 0. None:
  `skipped: no vX.0.* release tag`; equal to `from-tag previous`: `skipped: vX.0.N is the previous release`; both exit 0.
- `needs-upgrade-e2e [--base REF]` prints, in this order:
  - `render=true|false`: a changed file under `templates/gitops-app/`, `scripts/cplat/update.py`, `scripts/cplat/versions.py`,
    `scripts/upgrade-render-check.py`, `tests/e2e/lib/upgrade-system.sh`, `scripts/release-check.py`,
    `.github/workflows/e2e-upgrade.yml`, a changed versions row, or a new release heading;
  - `drill=true|false`: a changed `scripts/cplat/upgrade.py`, `scripts/cplat/upgradeverify.py`, `scripts/cplat/dbbackup.py`,
    `scripts/cplat/backupstate.py`, `tests/e2e/upgrade-drill.sh`, or a changed database row (a row named `postgres <major>`,
    `operator cloudnative-pg` or `operator plugin-barman-cloud`);
  - `run=true|false`: today's rule, unchanged (a change to `tests/e2e/upgrade-drill.sh` alone does not run the update part).
- `gate SHA`: checks `e2e upgrade (previous release → candidate)` and `upgrade render check`. Per check, one line:
  `OK: <sha> has a green <label>` | `OK: <sha> has a green <label> on <head>, the head of its pull request with the same tree`
  | `ERROR: <sha> has no green <label> (<conclusion>): do not tag it`, with label `upgrade e2e` or `upgrade render check`.
  Exit 0 only when both are OK. An unreadable answer keeps today's `ERROR: cannot read the check runs ...` line and exit 1.

### Workflows (AC-191.4 to AC-191.7)

`e2e-upgrade.yml` (triggers: today's plus paths `templates/gitops-app/**`, `scripts/upgrade-render-check.py`; schedule and
dispatch unchanged; `decide` gains the output `render`):

| Job id | Name | Runs when | Timeout | Does |
|---|---|---|---|---|
| `decide` | does this change need the upgrade e2e | always | 2 | `needs-upgrade-e2e` (step unchanged) |
| `render` | `upgrade render check` | `render == 'true'`, schedule, dispatch | 5 | checkout `fetch-depth: 0`, uv, copier; `uv run scripts/upgrade-render-check.py` |
| `upgrade` | `e2e upgrade (previous release → candidate)` | `run == 'true'`, schedule, dispatch | 45 | `bash tests/e2e/upgrade.sh` |
| `upgrade-oldest` | `e2e upgrade (oldest supported release → candidate)` | schedule, dispatch | 60 | `from-tag oldest`; `skipped: ...` → prints it, passes; else `E2E_UPGRADE_FROM=<tag> bash tests/e2e/upgrade.sh` |

`e2e-upgrade-drill.yml` (pull_request and push to main with paths `scripts/cplat/upgrade.py`, `scripts/cplat/upgradeverify.py`,
`scripts/cplat/dbbackup.py`, `scripts/cplat/backupstate.py`, `templates/gitops-app/scripts/render.py` (the versions table),
`tests/e2e/upgrade-drill.sh`, `.github/workflows/e2e-upgrade-drill.yml`; schedule `17 4 * * *`; dispatch;
`permissions: contents: read`; concurrency as `e2e-upgrade.yml` with group prefix `e2e-upgrade-drill-`):

| Job id | Name | Runs when | Timeout | Does |
|---|---|---|---|---|
| `decide` | does this change need the upgrade drill | always | 2 | `needs-upgrade-e2e` → `drill` output |
| `drill` | `e2e upgrade drill (Postgres 16 → 17)` | `drill == 'true'`, schedule, dispatch | 75 | `E2E_UPGRADE_DRILL=1 bash tests/e2e/upgrade.sh` |

A workflow-file change alone reaches `decide` but runs no drill (AC-191.7 lists no workflow path). The release gate
(`release-check.py gate`, `release-guard.yml`) requires `upgrade render check` and `e2e upgrade (previous release → candidate)` only.

### `tests/e2e/upgrade.sh`

- Env: `E2E_UPGRADE_FROM=<tag>` (else `release-check.py from-tag previous`), `E2E_UPGRADE_DRILL=1` (the drill), the rest unchanged.
- Without the drill: steps 1 From, 2 Setup, 3 Update as today, then 4 Checks: data reads back (`read_data`) in every
  environment, `cplat instance verify` per environment, doctor (every operator `ok`), every rendered addon and overlay
  accepted by `apply --dry-run=server`. No `resource add backups`, no `--to 17`. Ends `UPGRADE E2E OK`.
- With the drill: after step 3 it sources `tests/e2e/upgrade-drill.sh` (today's steps 4, 5 and the major-17 part of 6:
  `pgDataImageInfo.majorVersion` 17, `server_version` = the table's 17 minor, `upg-postgres-upgrade` state `verified`,
  `system status` upgrade.state verified, the CRDs), then the same 4 Checks.
- The header names AC-191.6, AC-191.7 and AC-121.25 and the budgets: about 15 minutes for the update part, about 40 with the drill.

## Verification note

AC-191.8's duration of `e2e upgrade (previous release → candidate)` on the pull request that ships this spec (from the job's
`Total:` line) goes into `verification.md` next to the 22–25 minutes before; the 15-minute target is recorded, not asserted.

# Design — 201 One cluster repo places environments on several clusters

## Decisions

- **One tree per cluster, one Argo CD per cluster, nothing shared at runtime** (AC-201.1, non-goal "hub"). With `clusters`, render writes `cluster/<name>/` per listed cluster, with exactly the layout `cluster/` has today. Each cluster's roots point at its own tree. A repo without `clusters` renders `cluster/` byte for byte as before (AC-201.4). ADR: [docs/adr/114-one-cluster-repo-places-environments-on-several-clusters.md](../../adr/114-one-cluster-repo-places-environments-on-several-clusters.md).
- **Cluster directories are `clusters/<name>/`**, each with a `cluster.yaml` of exceptions. The file may be empty or hold only comments, because git cannot hold an empty directory. The only keys are `operators` (a map `<operator>: true|false`, so each difference is one explicit line), `secretStore` and `server` (A3, A13).
- **The order of `clusters` is the upgrade order (A2).** The first cluster always renders with this repo's release. A later cluster's release is pinned in `clusters/<name>/release.yaml`, which only `/platform:update` and `/cluster:promote` write. It renders with the renderer of that release, which `/platform:update` keeps in `.platform/releases/<release>/` (a copy of `scripts/render.py` and `scripts/system_render.py`), called through a stable JSON interface (`render.py --render-cluster`, §3). This is the spec's note "render it with that release's pins" taken one step further: the renderer code is kept too. A release can change the rendered infrastructure as well as the pins, and AC-201.7 asks for the later tree to stay byte for byte. `.platform/` is the repo-level platform folder ADR-088 already uses.
- **An environment's cluster is stated in both repos.** `cluster.yaml` assigns it (`systems.<s>.environments`, A1, AC-201.3). The system repo states the same thing in `system.yaml` (`environments.<env>.cluster`), and `devbox run check` in the cluster repo fails when the two differ. The system repo needs the key for two reasons. Its render must know when to write the per-environment roots, and a system repo without the key must render nothing new (AC-201.4). Its commands must also find an environment's cluster without asking the cluster repo (AC-201.9, spec note).
- **Per-environment roots with a resources finalizer make a move "stop managing, delete nothing"** (AC-201.5). A system with `cluster` keys also renders `bootstrap/environments/<s>-<env>.yaml`: an Application `<s>-<env>-root` with `resources-finalizer.argocd.argoproj.io` over `applications/<s>/applicationset-<env>.yaml`, which holds only that environment's ApplicationSets, each with `preserveResourcesOnDeletion: true`. The cluster's `system-<s>` (no finalizer, AC-201.3) selects its environments from `bootstrap/environments` with a directory `include`. When an environment leaves a cluster, `system-<s>` prunes that environment's root. The finalizer then deletes its ApplicationSets, and their generated Applications go with them through owner references. Those Applications carry no finalizer, so every workload, namespace, PVC and Secret stays.
- **A system with `environments` gets `system-<s>` on every listed cluster.** A cluster that runs none of its environments gets one that selects nothing (`exclude: "*"`, `allowEmpty: true`). Without it, moving a system's last environment off a cluster would delete `system-<s>` there. Having no finalizer, that would orphan the environment roots, and they would keep running.
- **The switch from the one-folder form keeps nothing behind.** In split form the system repo also adds the resources finalizer to `bootstrap/<s>-root.yaml`, and the system repo is changed before the cluster repo (the check enforces this). When the cluster PR switches `system-<s>` from `bootstrap` to `bootstrap/environments`, Argo CD applies the new environment roots and then prunes `<s>-root`. Its finalizer deletes the ApplicationSets that no environment root adopted, which is exactly the environments that moved away. A system repo without `cluster` keys renders `bootstrap/<s>-root.yaml` unchanged.
- **The kube context of a cluster is a personal record of names** (A8): `kube_contexts: {<cluster>: <context>}` in the settings files of ADR-036 (`.platform-settings.yml` over `~/.config/sdlc-foundry/settings.yml`, per key). `--context` always wins. For a system on one cluster (no `cluster` keys, or all three equal), commands keep today's choice (A11).
- **`/cluster:promote` is its own module, `scripts/cplat/clusterpromote.py`.** It reuses `clusterrepo`'s branch, commit and PR helpers by import and does not edit `clusterrepo.py`, which spec 126 is changing.
- **"An earlier platform release" (AC-201.4) is a release older than the cluster repo's own.** The check cannot know this release's version number before it is published. A cluster repo that lists clusters is on this release or later, so "older than the cluster repo" catches every system repo that cannot split. The release is read from `.platform-version`, with `.copier-answers.yml` `_commit` as the fallback (spec 125 decision 6).
- **Split form needs the in-cluster destination.** Every cluster pulls with its own Argo CD, so a system with `cluster` keys must keep `cluster_server` at `https://kubernetes.default.svc` (spec note). Its render fails otherwise.
- **Changelog: a fragment, not a direct edit** (AC-201.12). The change ships as `docs/changelog.d/201-one-cluster-repo-several-clusters.added.md` (ADR-078). `cplat platform release` moves it into `docs/CHANGELOG.md` under the new minor version's "Added" section, so it is not BREAKING.
- **Doctor compares Kubernetes and Argo CD on major.minor and the gateway exactly** (A10). The gateway value is `<GatewayClass controllers> (Gateway API <bundle-version>)`.
- **The end-to-end test serves the repos from a local git server.** Argo CD must pull the cluster repo and the system repo without GitHub. `tests/e2e/clusters.sh` runs an HTTPS smart-git server (self-signed) on the k3d Docker network, points `github.com` at it in each cluster's CoreDNS (`coredns-custom` override), and marks the org's repository credential `insecure: "true"`. This changes no production file.

### Files other running specs also touch

- **Spec 126** (building): `scripts/cplat/ship.py` (its t6 and t10; ours t8), `scripts/cplat/upgrade.py` (its t8; ours t9), `.claude-plugin/marketplace.json` (its t3; ours t13). It also edits `scripts/cplat/clusterrepo.py`, which this plan only imports. It also edits `docs/adr/README.md` (its t4); this branch already appended the row for ADR-114 there, and ADR-102 settles index conflicts at land.
- **Spec 176** (building): `.claude-plugin/marketplace.json` (its t6; ours t13), `docs/adr/README.md` (its t6).
- **Spec 190** (paused): no plan.md yet; no known overlap.

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `templates/gitops-app/scripts/render.py` (+ copy `templates/cluster-gitops/scripts/system_render.py`) | `environments.<env>.cluster`; split form: `applicationset-<env>.yaml`, `bootstrap/environments/<s>-<env>.yaml`, root finalizer | changed (t1) |
| `scripts/cplat/model.py` | `Environment.cluster` | changed (t1) |
| `templates/cluster-gitops/scripts/render.py` | `clusters`, cluster directories, exceptions, assignment, per-cluster trees, releases, `EXCEPTION`/`BEHIND`/`MOVED` lines, new flags, `--render-cluster`, `effective()` | changed (t2) |
| `templates/cluster-gitops/scripts/check.py` | per-cluster operator check, assignment checks, release gate, exception and behind lines | changed (t3) |
| `templates/cluster-gitops/scripts/{bootstrap,cluster-up,cluster-down}.sh`, `devbox.json`, `cluster.yaml.jinja`, `copier.yml`, `CLAUDE.md.jinja`, `README.md.jinja` | bootstrap per cluster, identity guard, local cluster per name, validate per tree | changed / new (t4) |
| `scripts/cplat/update.py` | keep later clusters at their release on `/platform:update` | changed (t5) |
| `scripts/cplat/settings.py`, `scripts/cplat/envcluster.py` | `kube_contexts`; cluster of an environment and its context | changed / new (t6) |
| `scripts/cplat/envwait.py`, `scripts/cplat/status.py` | `system wait --env`, `cluster wait <cluster>`, `system status` per environment | changed (t7) |
| `scripts/cplat/ship.py`, `scripts/cplat/smoke.py` | `component ship deploy`, `instance verify` | changed (t8) |
| `scripts/cplat/{dbbackup,dbrestore,dbquery,upgrade,envrestore}.py` | `resource backup|restore|query|upgrade`, `system restore` | changed (t9) |
| `scripts/cplat/doctor.py` | per-cluster rows and the comparison | changed (t10) |
| `scripts/cplat/clusterpromote.py`, `scripts/cplat/cplat.py` | `cplat cluster promote` | new / changed (t11) |
| `tests/e2e/clusters.sh`, `.github/workflows/e2e.yml`, `scripts/e2e-scope.py` | two clusters, one system spread over them | new / changed (t12) |
| `plugins/cluster/**`, `docs/rules/plugins/cluster/commands/promote.yml`, `.claude-plugin/marketplace.json` | `/cluster:promote`, `/cluster:add` wait per cluster, version 1.5.0 | new / changed (t13) |
| `docs/DOMAIN-MODEL.md`, `docs/CLUSTERS.md`, ADR-060, ADR-068, changelog fragment | domain model, guide, ADR status lines, release note | changed / new (t14) |

## Contract

### 1. System repo: `environments.<env>.cluster` (AC-201.3, AC-201.4, AC-201.5, AC-201.9)

```yaml
environments:
  dev:     {cluster: local}
  staging: {cluster: local}
  prod:    {cluster: home}
```

- An optional key of each environment (`ENV_KEYS` gains `cluster`, last). Its value is a lowercase DNS label of at most 40 characters. Either no environment sets it, or all three do.
- Render errors (the renderer's existing one-line form):
  - `environments.<env>.cluster: '<v>' must be a lowercase DNS label of at most 40 characters`
  - `environments.<env>.cluster is required once another environment sets one (environments.<other>.cluster: <v>)` (the first environment without it, in ENVS order; `<other>` is the first that sets it)
  - `environments.<env>.cluster needs cluster_server https://kubernetes.default.svc (each cluster's own Argo CD deploys in-cluster), not <server>` (split form only)
- **No key in any environment:** every rendered file is byte-identical to today.
- **Split form** (all three set). Everything rendered today stays, with one change: `bootstrap/<s>-root.yaml` gains `metadata.finalizers: [resources-finalizer.argocd.argoproj.io]`, placed after `namespace`. In addition, for each env in ENVS:
  - `applications/<s>/applicationset-<env>.yaml`: the documents of `applicationset.yaml` that belong to `<env>`, in the same order (component `<s>-<env>`, `<s>-addons-<env>`, `<s>-addons-config-<env>`, `<s>-policies-<env>`, `<s>-backup-<env>`, each only where rendered today), each with `spec.syncPolicy: {preserveResourcesOnDeletion: true}`. The component ApplicationSet is always rendered, with an empty list generator when no component runs there, as `applicationset.yaml` does.
  - `bootstrap/environments/<s>-<env>.yaml`:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: <s>-<env>-root
  namespace: argocd
  finalizers: [resources-finalizer.argocd.argoproj.io]
spec:
  project: default
  source: {repoURL: <gitops repo url>, targetRevision: main, path: applications/<s>, directory: {include: applicationset-<env>.yaml}}
  destination: {server: https://kubernetes.default.svc, namespace: argocd}
  syncPolicy: {automated: {prune: true, selfHeal: true}}
```

- `scripts/cplat/model.py`: `Environment.cluster: str | None = None` (the key's string value, else None), filled in `build()`.

### 2. Cluster repo input (AC-201.1 to AC-201.3)

```yaml
# cluster.yaml (keys in this order; new: clusters, systems.<s>.environments)
cluster: eike                 # required, as before (the repo's cluster name; the k3d prefix)
owner: eike
server: https://kubernetes.default.svc
org: eike
operators: [cloudnative-pg, external-secrets]
secretStore: {...}
clusters: [local, home]       # optional; the upgrade order
systems:
  todo:
    repo: eike/todo-gitops
    environments: {dev: local, staging: local, prod: home}   # optional; needs clusters
```

```yaml
# clusters/home/cluster.yaml (required file per listed cluster; null, empty or only comments = no exceptions)
operators: {kyverno: false}       # <operator>: true (installed here, not shared) | false (shared, not installed here)
secretStore: {name: vault-secrets, provider: {vault: {...}}}   # replaces the shared store on this cluster
server: https://10.0.0.5:6443
```

```yaml
# clusters/home/release.yaml (written by /platform:update and /cluster:promote only; absent = this repo's release)
# Written by /platform:update and /cluster:promote: the platform release this cluster's tree is rendered with.
platform: 4.12.0
```

**Effective settings of a cluster.** Its operators are the shared list in `cluster.yaml` order, minus the `false` entries, plus the `true` entries in the exception file's order. Its server is the exception, else the shared one. Its store applies only when `external-secrets` is effective: the exception, else the shared one. Its release is the repo's release (`.platform-version` `platform`) for the first cluster and for a cluster without `release.yaml`, else the `release.yaml` value.

**Errors.** `render.py` prints one line on stderr, `ERROR: <file>: <message>`, exits 1 and writes nothing. `<file>` is `cluster.yaml`, `clusters/<c>/cluster.yaml` or `clusters/<c>/release.yaml`. The checks of spec 125 run first, unchanged. These follow:

| Case | `<message>` |
|---|---|
| unknown top-level key | `unknown key '<k>' (allowed: cluster, owner, server, org, operators, secretStore, clusters, systems)` |
| `clusters` not a list of strings | `clusters must be a list of cluster names` |
| `clusters: []` | `clusters must list at least one cluster, or be left out` |
| bad name | `clusters: '<v>' must be a lowercase DNS label of at most 40 characters` |
| duplicate | `clusters: '<v>' is listed twice` |
| listed without directory | `clusters: '<c>' has no clusters/<c>/cluster.yaml (create it; empty when the cluster has no exceptions)` |
| directory not listed | `clusters/<d>/ belongs to no cluster in clusters (listed: <a, b> \| none)` |
| system entry, other key (repo without `clusters`) | `systems.<s>: unknown key '<k>' (allowed: repo)` (unchanged) |
| system entry, other key (repo with `clusters`) | `systems.<s>: unknown key '<k>' (allowed: repo, environments)` |
| `environments` not a mapping | `systems.<s>.environments must map dev, staging and prod to listed clusters` |
| unknown environment | `systems.<s>.environments: '<e>' is not an environment (allowed: dev, staging, prod)` |
| cluster not listed (also any `environments` in a repo without `clusters`) | `systems.<s>.environments.<e>: cluster '<c>' is not listed in clusters (listed: <a, b> \| none)` |
| exception file not YAML / not a mapping | `is not valid YAML (<first line>)` / `must be a mapping of exceptions (operators, secretStore, server)` |
| exception of a non-shared setting | `'<k>' is not a shared setting a cluster can override (allowed: operators, secretStore, server)` |
| `operators` not a map of booleans | `operators must map operator names to true or false` |
| unknown operator | `operators.<o>: '<o>' is not an operator (allowed: <sorted OPERATORS keys>)` |
| no-op exception | `operators.<o>: <true\|false> is the shared value (cluster.yaml operators); remove it` |
| `server` / `secretStore` bad | the spec 125 messages for that key |
| store without operator | `secretStore needs external-secrets installed on cluster <c>` |
| `release.yaml` on the first cluster | `the first cluster runs this repo's release <x>; delete this file` |
| `release.yaml` malformed | `must be {platform: <x.y.z>}` |
| renderer of a release missing | `platform <x> is not kept in .platform/releases/<x>/; promote the cluster: /cluster:promote <c>` |
| the kept renderer fails | `cluster <c> (platform <x>): <its message>` |

### 3. Cluster repo output (AC-201.1 to AC-201.3, AC-201.5, AC-201.7)

**Layout.** Without `clusters`, the layout is exactly spec 125's `cluster/`. With `clusters`, every listed cluster `<c>` gets:

```
cluster/<c>/operators-root.yaml     platform-operators, path cluster/<c>/operators (retry as today)
cluster/<c>/systems-root.yaml       platform-systems, path cluster/<c>/systems
cluster/<c>/operators/<op>.yaml     operator_application(op, <effective server>) per effective operator
cluster/<c>/operators/secret-store.yaml   when external-secrets is effective
cluster/<c>/operators/.gitkeep      when it has no other file
cluster/<c>/systems/<s>.yaml        per system placed on <c> (below)
cluster/<c>/systems/.gitkeep        when it has no other file
cluster/<c>/kustomization.yaml      the tree's manifests, relative to cluster/<c>/
```

Every other file under `cluster/` is stale and is deleted, or reported by `--check`, as today. `.platform/releases/` is never touched by render.

**Placement of a system.**
- No `environments`: `system-<s>` in spec 125's form (path `bootstrap`), on the first cluster only.
- With `environments`: on every listed cluster, `system-<s>` in split form. Its `<envs>` are the environments the entry assigns to that cluster, in ENVS order:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: system-<s>
  namespace: argocd
  labels: {app.kubernetes.io/managed-by: cluster-gitops, app.kubernetes.io/component: system}
spec:
  project: default
  source:
    repoURL: https://github.com/<repo>
    targetRevision: main
    path: bootstrap/environments
    directory: {include: "<pattern>"}     # one env: "*-prod.yaml"; several: "{*-dev.yaml,*-staging.yaml}"
                                          # none: directory: {exclude: "*"} instead of include
  destination: {server: <effective server>, namespace: argocd}
  syncPolicy: {automated: {prune: true, selfHeal: true, allowEmpty: true}}
```

No rendered document carries `metadata.finalizers`.

**Lines on stdout** (render prints them before `rendered (<n> file(s) changed)`, also when nothing changed; `--check` prints none):
- `EXCEPTION: cluster <c>: operator <o>: installed (shared: not installed)` / `...: not installed (shared: installed)`, one per entry in exception-file order. Then `EXCEPTION: cluster <c>: server: <v> (shared: <v>)` and `EXCEPTION: cluster <c>: secretStore: name <n>, provider <p> (shared: name <n>, provider <p> | none)`, where `<p>` is the provider's one key or `kubernetes (default)`. Clusters in list order.
- `BEHIND: cluster <c> runs platform <x>, cluster <first> runs <y>; promote it with /cluster:promote <c>`, one per later cluster whose release differs from the first's. The exit code stays 0.
- `MOVED: <s> <env>: cluster <old> -> <new>; nothing is copied, and its namespace <s>-<env> and data stay on <old> until a person deletes them`, write mode only. `<old>` comes from the tree on disk before writing. A form-125 `system-<s>` under `cluster/<c>/systems/` places all three environments on `<c>`. A split one places its `include` environments there. The one-cluster tree `cluster/systems/<s>.yaml` places all three on the first listed cluster. One line per environment whose old and new clusters are both known and differ.

**CLI of `scripts/render.py` (cluster):**

| Invocation | Output, exit |
|---|---|
| `render.py` | lines above, then `rendered (<n> file(s) changed)`, 0 |
| `render.py --check` | as today, over every tree |
| `render.py --crds [<c>]` | `<op> <crd>` per effective operator of `<c>`. Without `clusters` the name is optional and must equal `cluster`. With `clusters` it is required: `ERROR: name the cluster: --crds <cluster> (clusters: <a, b>)`, exit 2 |
| `render.py --systems` | unchanged: `<s> <owner>/<repo>` per registered system |
| `render.py --envs <c>` | `<s> <env>` per environment running on `<c>`. A system without `environments` runs all three on the first cluster |
| `render.py --clusters` | one listed name per line; nothing without `clusters`; 0 |
| `render.py --trees` | `<c> cluster/<c>` per listed cluster; without `clusters`: `<cluster> cluster`; 0 |
| `render.py --name` | unchanged |
| `render.py --effective` | JSON `{"release": <repo release or null>, "clusters": [{"name", "first": bool, "release", "tree", "server", "operators": [...], "store": {"name","provider"} or null, "exceptions": [<EXCEPTION line text without the prefix>...], "systems": [{"name","repo","environments": [...] or null}]}]}`. Without `clusters`, one entry named after `cluster` with tree `cluster`. A cluster's `systems` are the systems placed on it (§3 placement; `environments` null = form 125). 0 |
| `render.py --render-cluster` | stable interface for kept renderers. stdin: `{"version": 1, "tree": "cluster/<c>", "repo_url": "...", "server": "...", "operators": [...], "store": {...} or null, "systems": [{"name","repo","environments": null or [...]}]}`. stdout: `{"files": {"<path from repo root>": "<text>"}}`, exit 0. On error: one stderr line, exit 1. A future release keeps reading `version: 1` |

`render.py` also exports `effective() -> dict` (the `--effective` data) and `render_cluster(spec: dict) -> dict[str, str]` (the `--render-cluster` function). The first cluster, and every cluster on the repo's release, render in-process with `render_cluster`. Any other cluster renders by `subprocess.run([sys.executable, ".platform/releases/<x>/render.py", "--render-cluster"], input=json)`.

### 4. `devbox run check` (AC-201.2 to AC-201.4, AC-201.7)

Output order: the `EXCEPTION:` and `BEHIND:` lines (§3), then what spec 125 prints today (with no systems, `OK: no systems registered`). Per system, these lines are added to the spec 125 ones:

1. Operator need per cluster. Without `clusters`, the message is unchanged. With `clusters`, the environment's cluster is the assigned one, else the first. A gap gives `ERROR: <s> (<env>): needs <op>, which cluster <c> does not install`.
2. Only for an entry with `environments` (in this order; the first case that applies ends the system's checks of this list):
   - for each env in ENVS missing from `environments`: `ERROR: <s> (<env>): <repo> declares <env>, which systems.<s>.environments in cluster.yaml leaves out; assign it to a cluster`;
   - `system.yaml` sets no `cluster`, and the system's release is unknown or older than this repo's: `ERROR: <s> runs on clusters <a, b>, but <repo> is on platform <x | unknown>, older than this cluster repo (<y>); run /platform:update in <repo> first` (AC-201.4);
   - per env whose `environments.<env>.cluster` differs from the assignment: `ERROR: <s> (<env>): cluster.yaml runs it on <c>, but <repo> sets environments.<env>.cluster: <v | nothing>; set it to <c> in <repo>`;
   - any `bootstrap/environments/<s>-<env>.yaml` missing on `main`: `ERROR: <s>: <repo> has no bootstrap/environments/<s>-<env>.yaml on main; run devbox run render in <repo> and merge it`.

The `OK:` and `FAILED:` lines and the exit codes are as in spec 125.

### 5. Bootstrap and local clusters (AC-201.6)

`KUBE_CONTEXT=<ctx> REPO_TOKEN=<t> devbox run bootstrap [<cluster>]` (`bash scripts/bootstrap.sh "$@"`). Spec 125's steps keep their order, and two steps are inserted:

1. After the `KUBE_CONTEXT`/`REPO_TOKEN` checks, resolve the name. `clusters=$(render.py --clusters)`. With clusters and no name: `ERROR: name the cluster to bootstrap: devbox run bootstrap <cluster> (clusters: local, home)`, exit 1. With an unknown name: `ERROR: unknown cluster '<x>' (clusters: local, home)`, exit 1. Without clusters, a name other than `cluster:` gives `ERROR: unknown cluster '<x>' (this repo has one cluster: <cluster>)`. The tree comes from `--trees`.
2. After the `argocd` namespace check and before the credential, the identity guard. Read `kubectl -n argocd get application platform-operators -o jsonpath='{.spec.source.repoURL} {.spec.source.path}'`. When the repoURL is this repo and the path is another cluster's operators path (`cluster/<other>/operators`, or `cluster/operators` while `<c>` is not the first listed cluster), stop:
   `ERROR: <ctx> already runs cluster <other> of this repo (platform-operators syncs <path>); bootstrapping <c> there would replace it. Nothing was changed.` and `  fix: pass the kube context of <c>: KUBE_CONTEXT=<its context> devbox run bootstrap <c>`, exit 1. `cluster/operators` on the first cluster is the one-cluster tree being taken over, and it is allowed.
3. The CRDs come from `render.py --crds <c>`, and the roots from `<tree>/operators-root.yaml` and `<tree>/systems-root.yaml`.

`devbox run cluster-up [<cluster>]`: the name defaults to the first listed cluster (without clusters: today's behaviour). `LOCAL_CLUSTER` defaults to `<cluster>-<name>` (without clusters: `<cluster>-local`, as today). Namespaces and `ghcr-pull` are created only for `render.py --envs <name>`. Then `KUBE_CONTEXT=k3d-$LOCAL_CLUSTER bash scripts/bootstrap.sh <name>`. Finally it prints `Record the context for cplat: kube_contexts: {<name>: k3d-<LOCAL_CLUSTER>} in ~/.config/sdlc-foundry/settings.yml` (with clusters only).

`devbox run cluster-down [<cluster>]` → `bash scripts/cluster-down.sh "$@"`, with the same name resolution.

`devbox run validate`: for each `--trees` directory, `kustomize build <dir>`, with the outputs concatenated into one kubeconform run. The summary check and the gate.sh messages are as today.

`copier.yml` `_skip_if_exists` gains `clusters/**` and `.platform/**`. `cluster.yaml.jinja` documents `clusters` and `systems.<s>.environments` in comments only: the default render is unchanged.

### 6. `/platform:update` in a cluster repo (AC-201.7)

`update.py`, shape `cluster-gitops`. `cluster.yaml` lists at least two clusters, `old` (the repo's `.platform-version` before the update) is known, and `old != new`. Before Copier runs:
1. For each later cluster without `clusters/<c>/release.yaml`, write it with `platform: <old>` (the §2 header comment).
2. When any cluster now has `platform: <old>` and `.platform/releases/<old>/` is missing, copy `scripts/render.py` and `scripts/system_render.py` there.

After `rerender_cluster` (with the new renderer), for each cluster frozen in step 1: render its tree with the new renderer (`--render-cluster` of `scripts/render.py`) from its effective settings. If that equals its tree on disk, the release did not change it, so step 1 is undone for it (its `release.yaml` is deleted). Then `.platform/releases/<old>/` is deleted when no `release.yaml` names it. `did` lines: `kept cluster <c> at platform <old>; promote it with /cluster:promote <c>` per cluster still frozen. These paths join the update's written files. When `old` is unknown and at least two clusters are listed, the update raises `PlatformError("cannot keep the later clusters at their release: this repo has no .platform-version", hint="restore .platform-version from git history (git log -- .platform-version), then run the update again")` before anything changes.

### 7. `cplat cluster promote` (`scripts/cplat/clusterpromote.py`; AC-201.8)

`cplat cluster promote <cluster> [--context CTX] [--component-dir NAME=DIR]... [--dry-run] [--json] [--repo-dir D]`. `--context` is the context of the cluster listed before. Errors are `PlatformError` and change nothing:
- not a cluster repo, an unclean tree: as `cluster add`;
- `CPLAT_HEADLESS` or `CPLAT_UNIT` set: `a promotion is opened by a person, never by a ship, update or engine run`, hint `run /cluster:promote <c> yourself`;
- no `clusters`: `this cluster repo has one cluster; there is nothing to promote`;
- unknown: `unknown cluster '<x>' (clusters: <a, b>)`;
- the first: `<c> is the first cluster: it takes each /platform:update directly, so there is nothing to promote`.

Flow:
1. `prev` is the cluster listed before `<c>`, and `target` is prev's release. Render `<c>` at `target` (in-process or kept renderer) from its effective settings. When `<c>`'s release equals `target` and the tree equals the one on disk: print `<c> already runs what <prev> runs (platform <target>); no pull request`, exit 0.
2. Gates on `prev`, with its context from `envcluster.cluster_context` (unreachable → that error, no PR):
   - each effective operator `<op>` of prev: Argo CD application `operator-<op>` must be `Synced Healthy`;
   - for each system with environments on prev (`render.py --effective`), clone `main` shallowly with `gh`, load it with `model`. For each non-external instance in those environments, `upgradeverify.run_component_smoke(m, comp, env, dirs)` must pass. A component without `--component-dir` is a failure: `no checkout of <comp>; pass --component-dir <comp>=<dir>`.
   - Any failure: print `NOT PROMOTED: <prev> is not ready:` and one `  <what>` line each (`operator-<op>: <sync>, <health>`, `smoke <comp> (<env>): <text>`). Exit 1, no branch, no PR.
3. Write `clusters/<c>/release.yaml` with `platform: <target>`, or delete it when `target` is the repo's release. Run `uv run scripts/render.py`. Delete each `.platform/releases/<x>/` that no `release.yaml` names. Then branch `cluster/promote-<c>-<target>`, commit `feat(cluster): promote <c> to platform <target> (what <prev> runs)` signed off, push, and `gh pr create`. Nothing else is staged.
4. Output: the PR URL, then `next: merge it; Argo CD on <c> then runs what <prev> runs. Wait with: cplat cluster wait <c> --refresh`.

`cplat.py`: `NOUNS["cluster"]["promote"] = ("clusterpromote", ["promote"])`, the usage line, and `cluster wait [<cluster>]` in the usage text.

### 8. Commands find the cluster (`scripts/cplat/envcluster.py`; AC-201.9)

```python
# settings.py
def kube_contexts(repo: Path) -> dict[str, str]:
    """cluster -> kube context name from `kube_contexts:` of the project file over the user file (per key); {} when unset.
    A value that is not a non-empty string: PlatformError('<path>: kube_contexts must map cluster names to kube context names')."""

# envcluster.py
def cluster_of(m: model.Model, env: str) -> str | None          # environments.<env>.cluster
def spread(m: model.Model) -> bool                             # more than one distinct cluster
def cluster_context(repo: Path, cluster: str, explicit: str | None, what: str) -> str
def env_context(repo: Path, m: model.Model, env: str, explicit: str | None) -> str | None
    # explicit -> explicit; not spread(m) -> None (the caller keeps today's choice, A11);
    # spread -> cluster_context(repo, cluster_of(m, env), None, f"environment {env} of {m.system}")
```

`cluster_context` uses `explicit`, else `kube_contexts(repo)[cluster]`. Reachability is `kubectl --context <ctx> -n argocd get applications -o name` (timeout 20 s). The two failures, as `PlatformError`, raised before any action:
- `<what> runs on cluster <c>, and no kube context is known for it`
- `<what> runs on cluster <c>, whose kube context <ctx> (<source>) does not answer: <first line of kubectl's error>`

Both carry the hint `pass --context <ctx>, or add kube_contexts: {<c>: <ctx>} to <user settings file> (a context name only; the credentials stay in your kubeconfig)`. `<source>` is `--context`, `project settings` or `user settings`. The current kube context is never read in this path.

Callers, each before its first cluster call, pass the result as the context and keep today's resolution when it is None:
- `envwait.system_wait` (env = `--env`);
- `envwait.cluster_wait`: with `clusters`, a positional `<cluster>` is required (`name the cluster to wait for: cplat cluster wait <cluster> (clusters: <a, b>)`; unknown → `unknown cluster '<x>' (clusters: <a, b>)`), and its roots are waited for with `cluster_context(repo, c, ns.context, f"cluster {c}")`;
- `status`: per environment, `env_context` unless `--context` covers it (`CTX` or `ENV=CTX`). On `PlatformError` the environment's cells show `unreachable: <cluster>`, the rest is shown, and the exit code is 1;
- `ship deploy` (dev), `smoke` run (`instance verify <env>`), `dbbackup`, `dbrestore`, `dbquery`, `upgrade` (per environment it touches), `envrestore`.

### 9. Doctor across clusters (`scripts/cplat/doctor.py`; AC-201.10)

In a `cluster-gitops` repo whose `render.effective()` lists `clusters`, `check_cluster` returns the following for each cluster `<c>` in order. `effective()` comes from the repo's `scripts/render.py`, imported by path. The context is from `--context <c>=<ctx>`, else `kube_contexts`.
- No context: WARN `cluster <c>`: `no kube context known for cluster <c>`, fix `add kube_contexts: {<c>: <ctx>} to <user settings file>, or pass --context <c>=<ctx>`. Unreachable: WARN `cluster <c>`: `cannot reach cluster <c> through context <ctx>: <first line>`, same fix. Either way, the cluster's other rows are skipped.
- OK `kubernetes (<c>)`: the server `gitVersion` without `v` (`kubectl version -o json`).
- OK `argo cd (<c>)`: the image tag of Deployment `argocd/argocd-server` without `v`.
- OK `gateway (<c>)`: `<sorted GatewayClass spec.controllerName, comma-separated> (Gateway API <annotation gateway.networking.k8s.io/bundle-version of CRD gateways.gateway.networking.k8s.io>)`, or `none`.
- The AC-125.13 rows named `operator <op> (<c>)` and `system <s> (<c>)`, read in `<c>`'s context. The expected operator versions come from the cluster's release: the platform's table when it equals the repo's release, else `OPERATORS` of `.platform/releases/<x>/system_render.py`.

Then, over the reachable clusters (at least two), one WARN row per differing item:
- `clusters differ: kubernetes`: `local 1.31.4, home 1.30.2` (compared on major.minor; patch only shown);
- `clusters differ: argo cd`: same rule;
- `clusters differ: gateway`: exact value.

The fix for these rows is `upgrade it outside the platform (a cluster prerequisite)`. A repo without `clusters`: doctor is unchanged.

### 10. End-to-end (`tests/e2e/clusters.sh`; AC-201.11)

1. Copy gitops-app as `todo-gitops` (`github_org=e2e`). Its `system.yaml` has one component `api` (an image in the local registry) with instances in dev, staging and prod, `operators: owner` everywhere, and `cluster: one` in dev and staging, `cluster: two` in prod. Render. Set the pins: dev and staging `sha-<40 hex>`, prod `1.0.0` (both tags pushed to the registry). Assert that `bootstrap/environments/todo-{dev,staging,prod}.yaml` exist.
2. Copy cluster-gitops as `e2e-clusters` with `clusters: [one, two]`, both directories empty, `operators: [cloudnative-pg]`, and `systems.todo: {repo: e2e/todo-gitops, environments: {dev: one, staging: one, prod: two}}`. Render, and assert both trees.
3. Start the git server and two k3d clusters on one Docker network (`cluster-up one` and `cluster-up two` with distinct `LOCAL_HTTP_PORT`s, Argo CD on). Add the CoreDNS override, push both repos to the git server, and mark the credential insecure (§Decisions). `cluster-up` runs `bootstrap <name>`.
4. Within 10 minutes: cluster one's Argo CD has `api-dev` and `api-staging` and no `api-prod`; cluster two's has `api-prod` only. Both are Synced. Both clusters' CloudNativePG operator Deployments run the same image tag. `kubectl get deploy api -n todo-dev` has image tag `sha-…`, and `-n todo-prod` (on two) has `1.0.0`.
5. Cleanup unless `E2E_KEEP=1`. The script prints `E2E CLUSTERS OK`. `e2e.yml` gets job `e2e-clusters` (`name: e2e clusters (one repo, two clusters)`, timeout 30 min). `scripts/e2e-scope.py` adds the script to `E2E_SCRIPTS` and `FILES`.

## Risks

- **Argo CD include/exclude globbing.** The patterns use gobwas glob, where `*` crosses `/`. They are applied to a flat folder, so that does not matter, but t12 proves both patterns on a real Argo CD.
- **Transition race.** If Argo CD prunes `<s>-root` before the new environment roots adopt their ApplicationSets, those ApplicationSets are deleted and re-created. Their Applications are re-generated and adopt the running workloads (same names and tracking labels). Nothing is deleted in the namespaces. The guide says so.
- **Converting a one-cluster repo.** The existing cluster's roots point at `cluster/operators` and `cluster/systems` until bootstrap runs again with its name. In between, Argo CD reports a missing path and prunes nothing. The guide and the human steps put that bootstrap right after the merge.
- **Kept renderers grow the cluster repo.** There is about 200 KB per kept release, deleted by promotion when unused.
- **Parallel specs** edit `ship.py`, `upgrade.py`, `marketplace.json` and the ADR index (above). Keep hunks small and local to context resolution.

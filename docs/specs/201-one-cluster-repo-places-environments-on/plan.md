---
spec_id: 201-one-cluster-repo-places-environments-on
shape: platform
spec_hash: 4d34b9d3da28
summary: "One cluster repo lists several clusters (clusters: [...], clusters/<name>/cluster.yaml exceptions, one tree cluster/<name>/ per cluster) and assigns each system environment to one (systems.<s>.environments); the system repo states the same in system.yaml (environments.<env>.cluster) and then renders per-environment roots with a resources finalizer, so a move stops management and deletes nothing; later clusters stay on their release through kept renderers (.platform/releases/) until /cluster:promote; cplat commands find an environment's cluster through a kube_contexts record of names; doctor compares Kubernetes, Argo CD and gateway; an e2e on two k3d clusters; ADR-114."
tasks:
  - id: t1
    title: system repo split form — environments.<env>.cluster, applicationset-<env>.yaml, bootstrap/environments roots, model Environment.cluster
    files: [templates/gitops-app/scripts/render.py, templates/cluster-gitops/scripts/system_render.py, scripts/cplat/model.py]
    covers: [AC-201.3, AC-201.4, AC-201.5, AC-201.9]
    parallel_safe: true
    depends_on: []
  - id: t2
    title: cluster renderer — clusters, cluster directories and exceptions, environment assignment, one tree per cluster, kept renderers, EXCEPTION/BEHIND/MOVED lines, new flags
    files: [templates/cluster-gitops/scripts/render.py]
    covers: [AC-201.1, AC-201.2, AC-201.3, AC-201.4, AC-201.5, AC-201.6, AC-201.7]
    parallel_safe: true
    depends_on: []
  - id: t3
    title: cluster check — operators per cluster, assignment checks, release gate for split systems, exception and behind lines
    files: [templates/cluster-gitops/scripts/check.py]
    covers: [AC-201.2, AC-201.3, AC-201.4, AC-201.7]
    parallel_safe: true
    depends_on: [t1, t2]
  - id: t4
    title: cluster template — bootstrap and cluster-up per cluster with the identity guard, cluster-down, validate per tree, skeleton docs
    files: [templates/cluster-gitops/scripts/bootstrap.sh, templates/cluster-gitops/scripts/cluster-up.sh, templates/cluster-gitops/scripts/cluster-down.sh, templates/cluster-gitops/devbox.json, templates/cluster-gitops/cluster.yaml.jinja, templates/cluster-gitops/copier.yml, templates/cluster-gitops/CLAUDE.md.jinja, templates/cluster-gitops/README.md.jinja]
    covers: [AC-201.1, AC-201.4, AC-201.6]
    parallel_safe: true
    depends_on: [t2]
  - id: t5
    title: /platform:update in a cluster repo keeps later clusters at their release
    files: [scripts/cplat/update.py]
    covers: [AC-201.7]
    parallel_safe: true
    depends_on: [t2]
  - id: t6
    title: kube_contexts setting and envcluster (cluster of an environment, its context, reachability)
    files: [scripts/cplat/settings.py, scripts/cplat/envcluster.py]
    covers: [AC-201.9]
    parallel_safe: true
    depends_on: []
  - id: t7
    title: system wait, cluster wait <cluster> and system status read each environment from its cluster
    files: [scripts/cplat/envwait.py, scripts/cplat/status.py]
    covers: [AC-201.4, AC-201.9]
    parallel_safe: true
    depends_on: [t1, t6]
  - id: t8
    title: component ship deploy and instance verify use the environment's cluster
    files: [scripts/cplat/ship.py, scripts/cplat/smoke.py]
    covers: [AC-201.4, AC-201.9]
    parallel_safe: true
    depends_on: [t1, t6]
  - id: t9
    title: resource backup, restore, query, upgrade and system restore use the environment's cluster
    files: [scripts/cplat/dbbackup.py, scripts/cplat/dbrestore.py, scripts/cplat/dbquery.py, scripts/cplat/upgrade.py, scripts/cplat/envrestore.py]
    covers: [AC-201.4, AC-201.9]
    parallel_safe: true
    depends_on: [t1, t6]
  - id: t10
    title: doctor in a cluster repo with clusters — per-cluster rows and the Kubernetes, Argo CD and gateway comparison
    files: [scripts/cplat/doctor.py]
    covers: [AC-201.4, AC-201.10]
    parallel_safe: true
    depends_on: [t2, t6]
  - id: t11
    title: cplat cluster promote — gates on the cluster before, one PR moving the cluster to its release
    files: [scripts/cplat/clusterpromote.py, scripts/cplat/cplat.py]
    covers: [AC-201.8]
    parallel_safe: true
    depends_on: [t1, t2, t6]
  - id: t12
    title: end-to-end — one cluster repo, two k3d clusters, todo's dev and staging on one and prod on two
    files: [tests/e2e/clusters.sh, .github/workflows/e2e.yml, scripts/e2e-scope.py]
    covers: [AC-201.11]
    parallel_safe: true
    depends_on: [t1, t2, t4]
  - id: t13
    title: cluster plugin — /cluster:promote, /cluster:add waits per cluster, rules entry, version 1.5.0 in manifest and marketplace
    files: [plugins/cluster/commands/promote.md, plugins/cluster/commands/add.md, plugins/cluster/README.md, plugins/cluster/.claude-plugin/plugin.json, docs/rules/plugins/cluster/commands/promote.yml, .claude-plugin/marketplace.json]
    covers: [AC-201.8, AC-201.12]
    parallel_safe: true
    depends_on: []
  - id: t14
    title: docs — domain model, cluster guide (second cluster, assigning, promoting, moving), ADR-060 and ADR-068 status lines, changelog fragment
    files: [docs/DOMAIN-MODEL.md, docs/CLUSTERS.md, docs/adr/060-a-cluster-repo-owns-shared-services.md, docs/adr/068-resource-and-operator-upgrades-roll-through-environments-in-verified-steps.md, docs/changelog.d/201-one-cluster-repo-several-clusters.added.md]
    covers: [AC-201.12]
    parallel_safe: true
    depends_on: []
human_steps:
  - "After the release: /plugin marketplace update sdlc-foundry (cluster 1.5.0 brings /cluster:promote)."
  - "todo, the first user, in this order (docs/CLUSTERS.md): /platform:update in the cluster repo and in todo-gitops; in todo-gitops set environments.dev/staging.cluster: local and environments.prod.cluster: home, render, merge; in the cluster repo add clusters: [local, home], clusters/local/cluster.yaml and clusters/home/cluster.yaml, systems.todo.environments {dev: local, staging: local, prod: home}, render, merge."
  - "Right after that merge: KUBE_CONTEXT=<local context> REPO_TOKEN=<read-only token> devbox run bootstrap local (moves the existing cluster's roots to cluster/local/; nothing is reinstalled), then the same with the home context and `home`."
  - "Record the context names once per machine in ~/.config/sdlc-foundry/settings.yml: kube_contexts: {local: <ctx>, home: <ctx>} (names only; credentials stay in the kubeconfig)."
  - "todo's prod starts empty on home; its old prod namespace and data stay on the local cluster until you delete them (kubectl --context <local> delete namespace todo-prod)."
---

# Plan — 201 One cluster repo places environments on several clusters

Design: [design.md](design.md) (the contract every task and test follows). ADR: [ADR-114](../../adr/114-one-cluster-repo-places-environments-on-several-clusters.md), written with this plan and indexed in `docs/adr/README.md`. t14 updates the status lines of ADR-060 and ADR-068.

Levels: t1, t2, t6, t13, t14 → t3, t4, t5, t7, t8, t9, t10, t11 → t12. Hot files have one owner each: `templates/gitops-app/scripts/render.py` and its cluster copy (t1), `templates/cluster-gitops/scripts/render.py` (t2), `scripts/cplat/cplat.py` (t11), `.claude-plugin/marketplace.json` (t13). Specs 126 and 176 also touch `ship.py`, `upgrade.py`, `marketplace.json` and the ADR index (design, "Files other running specs also touch").

Acceptance tests live in `tests/cplat/test_clusters_201*.py` (written first by the testers). They render both templates through Copier as the spec 125 tests do, fake `gh`, `kubectl`, `k3d` and `docker` with PATH stubs, and keep every spec 125 render test green, because a repo without `clusters` must not change.

## t1 — system repo split form

**Files:** templates/gitops-app/scripts/render.py, templates/cluster-gitops/scripts/system_render.py, scripts/cplat/model.py
**Covers:** AC-201.3, AC-201.4, AC-201.5, AC-201.9
**Goal:** A system repo that states its environments' clusters renders one root per environment that a cluster can select. One that does not state them renders exactly as today.

**Implementation notes:**
- `ENV_KEYS` gains `cluster` (last). Validate it as in design §1 (label, all-or-none, in-cluster `cluster_server`), with exactly those messages.
- Split form only (all three set): add `metadata.finalizers: [resources-finalizer.argocd.argoproj.io]` to `bootstrap/<s>-root.yaml`, after `namespace`. Write `applications/<s>/applicationset-<env>.yaml` (that environment's documents from the `docs` list `render_app` already builds, in order, each with `spec.syncPolicy.preserveResourcesOnDeletion: true`). Write `bootstrap/environments/<s>-<env>.yaml` exactly as in design §1.
- Build the per-environment lists while building `docs`, tagging each document with its environment. Do not re-parse the joined file. `applicationset.yaml` stays byte-identical.
- The module docstring documents the key and the two new outputs.
- Copy the file byte for byte to `templates/cluster-gitops/scripts/system_render.py` (`uv run scripts/sync-template-copies.py`), so `--check` passes.
- `model.py`: `Environment.cluster: str | None = None` (last field, default None), set from `conf.get("cluster")` when it is a string. Every existing constructor call stays valid.
- If the gitops-app's own `bootstrap.sh` or `validate` would read `bootstrap/environments/`, check that they do not apply it. They apply `bootstrap/<s>-root.yaml` only. Report back if one does.

**Done when:** the AC-201.3/AC-201.5 system-side tests pass: split files, root finalizer, `preserveResourcesOnDeletion`, the three error lines. The AC-201.4 test (a system without `cluster` renders byte-identically, and every existing gitops-app render test is green) passes. `sync-template-copies.py --check` is clean.

## t2 — cluster renderer for several clusters

**Files:** templates/cluster-gitops/scripts/render.py
**Covers:** AC-201.1, AC-201.2, AC-201.3, AC-201.4, AC-201.5, AC-201.6, AC-201.7
**Goal:** `devbox run render` turns `cluster.yaml` and `clusters/*/` into one tree per cluster, prints every exception, every cluster that is behind and every moved environment, and leaves a repo without `clusters` unchanged.

**Implementation notes:**
- Validation as in design §2: keep spec 125's order and texts, then `clusters`, the directories (`clusters/<c>/cluster.yaml` required per listed cluster; any other directory under `clusters/` fails), `systems.<s>.environments`, the exception files, and `release.yaml`. The unknown-key text of a system entry depends on whether `clusters` is set.
- Effective settings per cluster (design §2). Placement of systems (design §3: form 125 on the first cluster for a system without `environments`; split form on every cluster for one with it, `exclude: "*"` when none, `allowEmpty: true`).
- `render_cluster(spec) -> dict[str, str]` builds one tree from the `--render-cluster` JSON (design §3). Every cluster on the repo's release renders through it in-process. Any other cluster renders through `.platform/releases/<x>/render.py --render-cluster` in a subprocess (`sys.executable`). A repo without `clusters` renders `cluster/` exactly as today. The existing spec 125 render tests are the proof.
- Stale handling covers all of `cluster/` as today. Never touch `.platform/`.
- Lines (design §3): `EXCEPTION:` and `BEHIND:` in write mode and with no flag; `MOVED:` in write mode only, derived from the tree on disk before writing (form 125, split form, and the one-cluster `cluster/systems/` tree mapping to the first cluster).
- Flags `--crds [<c>]`, `--envs <c>`, `--clusters`, `--trees`, `--effective`, `--render-cluster` as in the CLI table. `--systems`, `--name` and `--check` keep their output. Export `effective()` and `render_cluster()` for `check.py` and doctor.
- The repo's release is read as `check.py` does (`.platform-version`, `_commit` fallback). Move the helper here if `check.py` should import it.

**Done when:** the AC-201.1, AC-201.2, AC-201.3, AC-201.5 and AC-201.7 renderer tests pass. These cover the trees, the same operators and store in each tree, every error line, idempotence, the exception lines and only that tree differing, the split and form-125 system apps with no finalizer, the moved line, and a cluster pinned to a kept renderer staying byte-identical. Every spec 125 renderer test is unchanged and green (AC-201.4).

## t3 — cluster check per cluster

**Files:** templates/cluster-gitops/scripts/check.py
**Covers:** AC-201.2, AC-201.3, AC-201.4, AC-201.7
**Goal:** `devbox run check` checks each environment against the cluster that runs it and refuses an assignment the system repo cannot follow yet.

**Implementation notes:**
- Use `render.effective()` (t2) for the clusters, their effective operators and each system's assignment. Print the `EXCEPTION:` and `BEHIND:` lines first (the same texts as render), also when there are no systems.
- The operator need per environment uses that environment's cluster. With `clusters`, the message is design §4 step 1. Without `clusters`, every message is unchanged.
- For entries with `environments`, apply design §4 step 2 in its order. Compare releases with `.platform-version` / `_commit` (`release_of`) against this repo's release. Read `environments.<env>.cluster` from the loaded system (t1's renderer accepts the key), and check `bootstrap/environments/<s>-<env>.yaml` in the clone.
- Keep `--urls` and the output and exit contract of spec 125.

**Done when:** the AC-201.2 per-cluster operator test, the AC-201.3 missing-environment test, the AC-201.4 old-release test (naming the system, its release and `/platform:update in <repo>`), the mismatch and missing-file tests, and the AC-201.7 check behind-line test (exit 0) pass with stubbed `gh` clones. The spec 125 check tests stay green.

## t4 — cluster template: bootstrap, cluster-up, cluster-down, validate

**Files:** templates/cluster-gitops/scripts/bootstrap.sh, templates/cluster-gitops/scripts/cluster-up.sh, templates/cluster-gitops/scripts/cluster-down.sh, templates/cluster-gitops/devbox.json, templates/cluster-gitops/cluster.yaml.jinja, templates/cluster-gitops/copier.yml, templates/cluster-gitops/CLAUDE.md.jinja, templates/cluster-gitops/README.md.jinja
**Covers:** AC-201.1, AC-201.4, AC-201.6
**Goal:** One human command bootstraps a named cluster from its own tree and refuses a context that runs another cluster of the repo. A local k3d cluster can be built per name.

**Implementation notes:**
- `bootstrap.sh [<cluster>]`: design §5 steps 1 to 3. The guard runs before any write. Every message is exact. Without `clusters` and without a name, every step and message is today's.
- `cluster-up.sh [<cluster>]`: the default name, `LOCAL_CLUSTER`, namespaces only for `render.py --envs <name>`, `bootstrap.sh <name>`, and the context hint line (design §5). Without clusters it behaves as today.
- `cluster-down.sh [<cluster>]` (new) with the same name resolution. `devbox.json` `cluster-down` runs it. `bootstrap`, `cluster-up` and `cluster-down` take the name as an argument (devbox appends it).
- `validate`: loop over `render.py --trees` and run `kustomize build` per tree into one file for kubeconform. The empty-summary gate is kept.
- `copier.yml` `_skip_if_exists` gains `clusters/**` and `.platform/**`. `cluster.yaml.jinja` adds commented documentation for `clusters` and `systems.<s>.environments` (the default render is unchanged). `CLAUDE.md.jinja` and `README.md.jinja` name `clusters/<name>/cluster.yaml` as hand-edited, `/cluster:promote`, and `bootstrap <cluster>`.
- `set -euo pipefail`, `bash -n` clean. `scripts/check-pins.py` stays green.

**Done when:** the AC-201.6 tests pass with stubbed kubectl and k3d. They cover the order per named cluster with that cluster's CRDs and roots, the missing and unknown name errors listing the clusters, the guard naming both clusters with no apply made, a second run applying the same objects, and `cluster-up` defaulting to the first cluster. The AC-201.1 template test (copy with defaults: render changes nothing, `validate` passes) passes. Every spec 125 bootstrap and cluster-up test stays green (AC-201.4).

## t5 — update keeps later clusters at their release

**Files:** scripts/cplat/update.py
**Covers:** AC-201.7
**Goal:** A platform update moves only the first cluster. Every later cluster's tree stays byte for byte, and the repo keeps the renderer that produces it.

**Implementation notes:**
- In the cluster-gitops branch of the update, before Copier runs: design §6 steps 1 and 2. Read `cluster.yaml` with `yaml.safe_load` for `clusters`.
- After `rerender_cluster`: undo the freeze for clusters the release did not change (design §6), and delete unused kept releases. Add the written and deleted paths to `generated` so they are committed. Add the `did` lines.
- A missing old stamp with clusters listed raises the design §6 error. Repos without `clusters`, or with one listed cluster, are untouched by this code.
- `plan()` (dry-run) adds one `will_do` line: `keep the later clusters (<names>) at platform <old> unless the release leaves their trees unchanged`.

**Done when:** the AC-201.7 update test passes. A copied cluster repo with `clusters: [local, home]` on an older stamp, updated with a changed operator pin, changes only `cluster/local/`. `cluster/home/` is byte-identical, `clusters/home/release.yaml` and `.platform/releases/<old>/` exist, and render prints the `BEHIND:` line with exit 0. The existing update tests stay green.

## t6 — kube_contexts and envcluster

**Files:** scripts/cplat/settings.py, scripts/cplat/envcluster.py
**Covers:** AC-201.9
**Goal:** One place decides which kube context an environment's command uses, and it never falls back to the current context for a spread system.

**Implementation notes:**
- `settings.kube_contexts(repo)` as in design §8 (project file over user file per key; validation message). Document `kube_contexts` in the module docstring.
- `envcluster.py` with `cluster_of`, `spread`, `cluster_context`, `env_context`, with exactly the design §8 messages and hint. Reachability uses `kubectl ... get applications -o name` with a 20 s timeout. It never calls `kubectl config current-context`.
- Import `model` lazily or by type only, so the module stays cheap to import.

**Done when:** the AC-201.9 resolver tests pass. They cover the record, `--context` winning, the no-context and unreachable errors naming environment, cluster and the fix, None for a one-cluster system, and the current context never being read.

## t7 — waits and status per cluster

**Files:** scripts/cplat/envwait.py, scripts/cplat/status.py
**Covers:** AC-201.4, AC-201.9
**Goal:** `system wait --env`, `cluster wait` and `system status` talk to the cluster that runs each environment.

**Implementation notes:**
- `system_wait`: `env_context(repo, model, ns.env, ns.context)`. Pass it as the explicit context to `resolve_context` when it is not None. Otherwise keep today's resolution.
- `cluster_wait`: an optional positional `<cluster>`. With `clusters` in `cluster.yaml` it is required and validated (design §8 texts), and the context comes from `cluster_context`. Without `clusters`, today's behaviour; a given name must equal `cluster:`. Update the module docstring usage.
- `status`: per environment, `env_context` unless `--context` covers it. A `PlatformError` turns that environment's Argo CD cells into `unreachable: <cluster>`, keeps the other environments, and makes the exit code 1. JSON gets `"unreachable": "<cluster>"` on that environment.
- A system on one cluster: unchanged output and exit codes.

**Done when:** the AC-201.9 tests for `system wait`, `cluster wait <cluster>` and `system status` pass with stubbed kubectl per context (the right context, the error before any wait, `unreachable: home` with exit 1). The existing envwait and status tests stay green (AC-201.4).

## t8 — ship deploy and instance verify per cluster

**Files:** scripts/cplat/ship.py, scripts/cplat/smoke.py
**Covers:** AC-201.4, AC-201.9
**Goal:** The dev deploy wait of a ship and `instance verify <env>` use the environment's cluster.

**Implementation notes:**
- `ship deploy`: before the existing context choice (`settings.kube_context`, around the current `if not context:` block), call `env_context(repo, model, "dev", context)` on the system model the deploy already reads. Use the result when it is not None. A `PlatformError` stops the deploy before any wait, as the design requires. Keep the hunk small: spec 126 edits this file in parallel.
- `smoke` run (`instance verify <env>`): the same with its environment, before the first kubectl or port-forward call.
- Systems on one cluster: unchanged.

**Done when:** the AC-201.9 tests for `component ship deploy` and `instance verify` pass (the dev or env cluster's context is used, and the error comes before acting). `test_ship*.py` and the smoke tests stay green.

## t9 — resource and restore commands per cluster

**Files:** scripts/cplat/dbbackup.py, scripts/cplat/dbrestore.py, scripts/cplat/dbquery.py, scripts/cplat/upgrade.py, scripts/cplat/envrestore.py
**Covers:** AC-201.4, AC-201.9
**Goal:** `resource backup|restore|query|upgrade` and `system restore` act on the environment's own cluster or stop before acting.

**Implementation notes:**
- Each command resolves `env_context(repo, model, env, ns.context)` right after it loads the system and before its first kubectl call, and passes it where it passes `--context` today. Their default stays "the current one" only when the result is None.
- `upgrade.py` takes `--context [ENV=]CTX` per environment. Resolve each environment it touches the same way, and let an explicit `ENV=CTX` win for that environment. Keep the hunk small: spec 126 edits this file.
- Help texts: "(default: the environment's cluster for a system spread over clusters, else the current one)".

**Done when:** the AC-201.9 tests for these five commands pass. The right context is used, and the no-context or unreachable error appears with no kubectl write recorded by the stub. The existing db*, upgrade and envrestore tests stay green.

## t10 — doctor across clusters

**Files:** scripts/cplat/doctor.py
**Covers:** AC-201.4, AC-201.10
**Goal:** `/platform:doctor` in a cluster repo with clusters shows each cluster's Kubernetes, Argo CD, gateway and spec 125 rows, and warns once per item that differs.

**Implementation notes:**
- `check_cluster`: import the repo's `scripts/render.py` by path and call `effective()`. Without `clusters`, keep today's code path exactly.
- Per cluster: the context from `--context <c>=<ctx>` (the existing `[ENV=]CTX` parser accepts cluster names in a cluster repo), else `settings.kube_contexts`. The rows and texts are design §9. The unreachable and no-context rows skip that cluster's other rows.
- Expected operator versions per cluster: the platform table, or `.platform/releases/<x>/system_render.py` loaded by path for a cluster behind.
- Comparison rows over reachable clusters: Kubernetes and Argo CD on major.minor, gateway exact (A10).

**Done when:** the AC-201.10 tests pass with stubbed kubectl per context. They cover the three values per cluster, one warning per differing item naming each cluster's value, no warning for a patch difference, and an unreachable cluster as one warning while the other clusters are still compared. The spec 125 doctor tests stay green (AC-201.4).

## t11 — cplat cluster promote

**Files:** scripts/cplat/clusterpromote.py, scripts/cplat/cplat.py
**Covers:** AC-201.8
**Goal:** A person moves a later cluster to exactly what the cluster before it runs, in one PR, only when that cluster is healthy.

**Implementation notes:**
- Design §7, in order: the refusals (including `CPLAT_HEADLESS`/`CPLAT_UNIT`), the already-equal case (exit 0, no branch), the gates (operator applications Synced/Healthy, smoke of every instance on the cluster before through `upgradeverify.run_component_smoke`, clones like `check.py`), the edit, render and kept-release clean-up, then branch, commit, push and PR.
- Reuse `clusterrepo`'s clean-tree, branch, commit, push and PR helpers by import. Do not edit `clusterrepo.py` (spec 126 edits it).
- `--dry-run` prints the plan (target release, gates it would run, files it would change) and changes nothing. `--json` returns the `Report`.
- `cplat.py`: `NOUNS["cluster"]["promote"]`, the usage lines for `cluster promote` and `cluster wait [<cluster>]`. Nothing else in that file.

**Done when:** the AC-201.8 tests pass with stubbed `gh`, `git` and kubectl. They cover one PR whose diff is only `clusters/home/release.yaml`, `cluster/home/**` and an unused `.platform/releases/<x>/`, plus no PR and the named reason when an operator is not healthy, a smoke test fails or a checkout is missing. They also cover the "already runs" message with no PR, refusal on the first cluster and under `CPLAT_HEADLESS`, and three clusters promoting the third to the second's release.

## t12 — end-to-end: one repo, two clusters

**Files:** tests/e2e/clusters.sh, .github/workflows/e2e.yml, scripts/e2e-scope.py
**Covers:** AC-201.11
**Goal:** On two real k3d clusters with their own Argo CD, one cluster repo runs todo's dev and staging on the first cluster and prod on the second.

**Implementation notes:**
- Follow design §10 in the style of `tests/e2e/cluster.sh` (`fail`, `step`, cleanup trap, `E2E_KEEP`). The pins come from the renders, never hard-coded.
- The local git server: an HTTPS smart-git container (git `http-backend` behind a small web server, self-signed certificate) on the k3d Docker network. Each cluster's CoreDNS gets a `coredns-custom` override for `github.com`, and the org credential gets `insecure: "true"`. Create the credential before `bootstrap` runs: `kubectl apply` keeps the extra key. No production file changes for the test.
- Asserts as design §10 step 4: each Argo CD's application list, Synced, the same CloudNativePG operator image on both, `sha-` in dev and `1.0.0` in prod. Use `kubectl wait`/Argo status polls with a deadline, as the other e2e scripts do.
- `e2e.yml`: job `e2e-clusters` (same setup as `e2e-cluster`, timeout 30 min), with actions pinned by SHA. `e2e-scope.py`: add the script to `E2E_SCRIPTS` and `FILES` and update its docstring.
- `bash -n` clean.

**Done when:** the AC-201.11 static test passes (the script holds those steps and asserts, the workflow runs it, and e2e-scope selects it), and a local run with Docker prints `E2E CLUSTERS OK`.

## t13 — cluster plugin

**Files:** plugins/cluster/commands/promote.md, plugins/cluster/commands/add.md, plugins/cluster/README.md, plugins/cluster/.claude-plugin/plugin.json, docs/rules/plugins/cluster/commands/promote.yml, .claude-plugin/marketplace.json
**Covers:** AC-201.8, AC-201.12
**Goal:** `/cluster:promote <cluster>` exists as a thin command over `cplat cluster promote`, `/cluster:add` waits on each cluster that runs the system, and the plugin is versioned.

**Implementation notes:**
- `promote.md` follows `add.md`. The front matter description includes the usage (`/cluster:promote <cluster> [--component-dir NAME=DIR]...`, at most 260 characters). The steps are: preview with `--dry-run`, run, relay the PR URL or the `NOT PROMOTED:` lines verbatim, and stop. It never merges the PR itself unless the person asks. It says a promotion is a person's decision. It ends with the `/issue:report` note.
- `add.md` step 4: in a repo with clusters, `cplat cluster wait <cluster> --refresh` for each cluster that runs one of the system's environments (`devbox run render` prints them; `uv run scripts/render.py --envs <cluster>`).
- `promote.yml`: one entry per rule sentence of `promote.md`, in the register format (`cplat platform rules check` must pass, and the byte baseline must hold).
- `plugin.json` 1.4.0 → 1.5.0, with "promote" in the description. `marketplace.json`: only the `cluster` entry's version changes (spec 126 and 176 edit other entries).
- README: the new command and a link to docs/CLUSTERS.md "Several clusters".

**Done when:** `devbox run validate`, the version-match loop of `devbox run quality`, `scripts/shapes.py check_front_matter` and `cplat platform rules check` pass. The AC-201.12 plugin-version test passes.

## t14 — docs

**Files:** docs/DOMAIN-MODEL.md, docs/CLUSTERS.md, docs/adr/060-a-cluster-repo-owns-shared-services.md, docs/adr/068-resource-and-operator-upgrades-roll-through-environments-in-verified-steps.md, docs/changelog.d/201-one-cluster-repo-several-clusters.added.md
**Covers:** AC-201.12
**Goal:** The domain model, the guide and the ADRs say that an environment runs on the cluster its system assigns it to, and the release note announces it as a non-breaking minor change.

**Implementation notes:**
- `DOMAIN-MODEL.md`, Cluster noun: a cluster repo may manage several clusters, and an environment runs on the cluster its system assigns it to (`systems.<s>.environments` in the cluster repo, `environments.<env>.cluster` in `system.yaml`). Link ADR-114. Add `/cluster:promote` to "Commands follow the nouns".
- `CLUSTERS.md`, new section "Several clusters" with, in order:
  - **Add a second cluster**: `clusters:`, `clusters/<name>/cluster.yaml`, exceptions and the lines render prints, bootstrap per name, and re-running bootstrap on the existing cluster right after the merge (its roots move to `cluster/<first>/`; nothing is reinstalled). Then `kube_contexts`.
  - **Assign environments**: first `/platform:update` and the `cluster` keys in the system repo (merge), then `systems.<s>.environments` in the cluster repo (merge). Why the order matters.
  - **Promote an upgrade**: the first cluster takes updates, `BEHIND:` lines, `/cluster:promote <name>` and its gates.
  - **Move an environment** (AC-201.5): change the assignment in both repos. The old cluster stops managing it and deletes nothing. The new cluster starts it empty. The `MOVED:` line. The old namespace and data stay until a person deletes them (`kubectl --context <old> delete namespace <s>-<env>`). Moving data is not covered (a later spec).
  - The doctor comparison (`/platform:doctor` in the cluster repo).
- ADR-060: status line `**Status:** Accepted (2026-10-27); decision 1 and the consequence "one system runs all its environments on its cluster" replaced by [ADR-114](...)`. Mark the consequence bullet with the same pointer. Do not rewrite the history.
- ADR-068 decision 7: append "For a system spread over clusters: [ADR-114](...) (operators move on the first cluster; a later cluster through /cluster:promote)". Update the "Not included" bullet the same way.
- The changelog fragment follows `docs/changelog.d/README.md`. One paragraph starting with a bold sentence ending `(spec 201).`, with what changes, "Not breaking: a cluster repo without `clusters` and a system repo without `cluster` keys render as before", the cluster plugin 1.5.0 line, and **Action** pointing to docs/CLUSTERS.md "Several clusters". No BREAKING marker.

**Done when:** `python3 scripts/check-links.py`, `scripts/check-docs.py` and `scripts/release-check.py rows` pass. The AC-201.12 doc tests pass: the domain-model sentence, the four guide parts, ADR-114 indexed and naming both replaced decisions, and the fragment as an `added` entry without BREAKING.

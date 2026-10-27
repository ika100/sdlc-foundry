---
spec_id: 125-a-cluster-repo-hosts-several-systems
shape: platform
spec_hash: 7c8fb8cc96d6
summary: "A cluster repo (template cluster-gitops, plugin cluster, shape cluster-gitops) owns a cluster's shared services: cluster.yaml lists operators (pinned from the system renderer's OPERATORS table, a byte-identical copy kept equal by scripts/sync-template-copies.py, design decision 13; external-secrets and kyverno join the table), the ClusterSecretStore, and the registered systems; render writes cluster/ with the roots platform-operators (same name as ADR-058, so takeover is in place) and platform-systems; devbox run check finds missing operators and environments without operators: owner; bootstrap and cluster-up (reusing local-cluster.sh in a WITH_SYSTEM=0 mode); cplat cluster new|add|remove and /cluster:*; doctor rows; an e2e with two systems and one CloudNativePG; ADR-060, guide, domain model, changelog. A system repo's rendered tree is unchanged."
tasks:
  - id: t1
    title: render.py (gitops-app) — OPERATORS rows external-secrets and kyverno, optional selector, operator_application() shared by operator_files()
    files: [templates/gitops-app/scripts/render.py]
    covers: [AC-125.3, AC-125.14]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t2
    title: local-cluster.sh (gitops-app) — WITH_SYSTEM=0 cluster-only mode for up and down
    files: [templates/gitops-app/scripts/local-cluster.sh]
    covers: [AC-125.15]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t3
    title: cluster renderer — cluster.yaml validation, cluster/ layout, --check/--crds/--systems/--name, system_render.py copy
    files: [templates/cluster-gitops/scripts/render.py, templates/cluster-gitops/scripts/system_render.py]
    covers: [AC-125.2, AC-125.3, AC-125.4, AC-125.5, AC-125.6, AC-125.14]
    parallel_safe: true
    depends_on: [t1]
    done: true
  - id: t4
    title: cluster check — devbox run check (operator gaps, operators owner, release warning) and --urls
    files: [templates/cluster-gitops/scripts/check.py]
    covers: [AC-125.10, AC-125.11, AC-125.12, AC-125.15]
    parallel_safe: true
    depends_on: [t3]
    done: true
  - id: t5
    title: cluster bootstrap and cluster-up — bootstrap.sh, cluster-up.sh, local-cluster.sh and ports.sh copies
    files: [templates/cluster-gitops/scripts/bootstrap.sh, templates/cluster-gitops/scripts/cluster-up.sh, templates/cluster-gitops/scripts/local-cluster.sh, templates/cluster-gitops/scripts/ports.sh]
    covers: [AC-125.9, AC-125.15]
    parallel_safe: true
    depends_on: [t2, t3, t4]
    done: true
  - id: t6
    title: cluster-gitops template skeleton — copier.yml, devbox.json, cluster.yaml, initial cluster/, CI, CLAUDE.md, README, settings
    files: [templates/cluster-gitops/copier.yml, templates/cluster-gitops/devbox.json, "templates/cluster-gitops/{{ _copier_conf.answers_file }}.jinja", templates/cluster-gitops/cluster.yaml.jinja, templates/cluster-gitops/cluster/operators-root.yaml.jinja, templates/cluster-gitops/cluster/systems-root.yaml.jinja, templates/cluster-gitops/cluster/kustomization.yaml, templates/cluster-gitops/cluster/operators/.gitkeep, templates/cluster-gitops/cluster/systems/.gitkeep, templates/cluster-gitops/CLAUDE.md.jinja, templates/cluster-gitops/README.md.jinja, templates/cluster-gitops/.claude/settings.json.jinja, templates/cluster-gitops/.claude/project-notes.md, templates/cluster-gitops/.github/workflows/ci.yml, templates/cluster-gitops/.github/dependabot.yml, templates/cluster-gitops/.github/ISSUE_TEMPLATE/bug_report.yml, templates/cluster-gitops/.github/ISSUE_TEMPLATE/config.yml, templates/cluster-gitops/.github/ISSUE_TEMPLATE/feature_request.yml, templates/cluster-gitops/.gitignore, templates/cluster-gitops/.secrets.baseline.json]
    covers: [AC-125.1, AC-125.2, AC-125.17]
    parallel_safe: true
    depends_on: [t3, t4, t5]
    done: true
  - id: t7
    title: register the shape cluster-gitops — shapes.yml, detect-shape, shapes.py contract, PRD table, shapecmd, update baseline, platform CI smoke job
    files: [shapes.yml, scripts/sync-template-copies.py, devbox.json, scripts/detect-shape.sh, scripts/test-detect-shape.sh, scripts/shapes.py, docs/requirements/platform-vision.md, scripts/cplat/shapecmd.py, scripts/cplat/update.py, .github/workflows/ci.yml]
    covers: [AC-125.1, AC-125.17]
    parallel_safe: true
    depends_on: [t6, t9]
    done: true
  - id: t8
    title: cplat cluster new|add|remove (clusterrepo.py) and the cluster noun in cplat.py
    files: [scripts/cplat/clusterrepo.py, scripts/cplat/cplat.py]
    covers: [AC-125.1, AC-125.7, AC-125.8]
    parallel_safe: true
    depends_on: [t6, t7]
    done: true
  - id: t9
    title: the cluster plugin — /cluster:new, /cluster:add, /cluster:remove, manifest, README, marketplace entry
    files: [plugins/cluster/.claude-plugin/plugin.json, plugins/cluster/README.md, plugins/cluster/commands/new.md, plugins/cluster/commands/add.md, plugins/cluster/commands/remove.md, .claude-plugin/marketplace.json]
    covers: [AC-125.1, AC-125.7, AC-125.8, AC-125.18]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t10
    title: platform doctor in a cluster repo — operator versions per listed operator, sync and health per system application
    files: [scripts/cplat/doctor.py]
    covers: [AC-125.13]
    parallel_safe: true
    depends_on: [t1, t7]
    done: true
  - id: t11
    title: end-to-end — two systems, one cluster render, one CloudNativePG operator (tests/e2e/cluster.sh, e2e workflow job)
    files: [tests/e2e/cluster.sh, .github/workflows/e2e.yml]
    covers: [AC-125.16]
    parallel_safe: true
    depends_on: [t3, t6]
    done: true
  - id: t12
    title: docs — the Cluster in the domain model, the cluster guide (create, install a system, move an existing cluster), templates list, changelog
    files: [docs/DOMAIN-MODEL.md, docs/CLUSTERS.md, docs/templates.md, docs/CHANGELOG.md]
    covers: [AC-125.14, AC-125.18]
    parallel_safe: true
    depends_on: []
    done: true
human_steps:
  - "After the release: run /plugin marketplace update sdlc-foundry so the new cluster plugin is available (a cluster repo enables cluster@sdlc-foundry in its own .claude/settings.json)."
  - "Per shared cluster: /cluster:new <name>, set the CI secret SYSTEMS_TOKEN (fine-grained token, Contents: read on the system repos), list the operators, /cluster:add each system, then once KUBE_CONTEXT=<ctx> REPO_TOKEN=<read-only token> devbox run bootstrap (docs/CLUSTERS.md)."
  - "A cluster where one system installed the operators (ADR-058): follow 'Moving an existing cluster' in docs/CLUSTERS.md in order (list every operator of that system's operators/apps/ first, bootstrap the cluster repo, then set operators: owner in every environment of each system)."
---

# Plan — 125 A cluster repo hosts several systems on shared operators

Design: [design.md](design.md) (the contract every task and test follows). ADR: [ADR-060](../../adr/060-a-cluster-repo-owns-shared-services.md) (written with this plan, indexed in `docs/adr/README.md`; ADR-058's status line and shared-cluster consequence point to it).

Levels: t1, t2, t9, t12 → t3 → t4 → t5 → t6 → t7 → t8, t10, t11 (t11 can start after t6). Hot files have one owner each: `templates/gitops-app/scripts/render.py` (t1), `templates/gitops-app/scripts/local-cluster.sh` (t2), `.claude-plugin/marketplace.json` (t9), `docs/CHANGELOG.md` (t12), `scripts/cplat/cplat.py` (t8), `.github/workflows/ci.yml` (t7), `.github/workflows/e2e.yml` (t11).

Acceptance tests live in `tests/cplat/test_cluster_125*.py` (written first by the testers, one id per test). They render the template through Copier, as the ADR-052 shared renders do, and fake `gh`, `kubectl`, `k3d` and `docker` with PATH stubs, as `test_cluster_ports.py` does.

## t1 — render.py (gitops-app): OPERATORS rows external-secrets and kyverno, optional selector, operator_application()

**Files:** templates/gitops-app/scripts/render.py
**Covers:** AC-125.3, AC-125.14
**Goal:** The platform's one versions table also pins External Secrets and Kyverno, and an operator's Argo CD application is built by one function that both repo kinds use.

**Implementation notes:**
- Append the rows `external-secrets` and `kyverno` exactly as in design §1. Add them at the end of `OPERATORS` (specs 117–121 add rows in parallel; keep the hunk separate).
- Kyverno's `operator_version` is the `appVersion` of chart 3.9.1 from `https://kyverno.github.io/kyverno/index.yaml`, without a leading `v`. Read it, do not guess (design decision 10). External Secrets 2.12.0 / 2.12.0.
- Add the optional `selector` key (kyverno only) and a one-line comment on the table: `selector`, default `app.kubernetes.io/name=<chart>`, used by doctor.
- Extract `operator_application(name: str, server: str) -> dict` from `operator_files()` and call it there. The output must stay byte-identical: the existing 115/116 operator tests and every byte-identical render test must stay green.
- `OPERATOR_OF_TYPE` is unchanged. Neither new row may ever appear in a system's `operators/`.
- Mention both new rows in the module docstring's table comment only if it lists operators (it does not today, so leave it).

**Done when:** the AC-125.3 table and builder tests pass (rows have every key, `operator_application("cloudnative-pg", s)` equals the system-rendered `operators/apps/cloudnative-pg.yaml`), and the whole existing `tests/cplat` render suite is unchanged and green.

## t2 — local-cluster.sh (gitops-app): WITH_SYSTEM=0 cluster-only mode

**Files:** templates/gitops-app/scripts/local-cluster.sh
**Covers:** AC-125.15
**Goal:** The cluster repo's `cluster-up` builds the local cluster with the same script a system uses, without a system.

**Implementation notes:**
- New env `WITH_SYSTEM` (default `1`). Document it in the header comment next to `WITH_ARGO`.
- With `WITH_SYSTEM=0`: `LOCAL_CLUSTER` is required (`ERROR: WITH_SYSTEM=0 needs LOCAL_CLUSTER`, exit 2). The `app=` detection must not fail without an `applications/` directory (`set -euo pipefail`: guard the `find`), and the kyverno/lgtm auto-detection must not fail either.
- `up`: insert one early-exit block right after the Argo CD credential block (or after the operator install blocks when `WITH_ARGO=0`). It prints `Cluster k3d-<name> is ready (no system: WITH_SYSTEM=0) on host port <port>` and `exit 0` before the namespaces loop. Keep it one contiguous hunk away from the operator blocks that specs 117–121 edit.
- `down` works with `WITH_SYSTEM=0` and no `applications/`.
- With `WITH_SYSTEM=1` every message and step is unchanged: `test_cluster_ports.py`, `test_cluster_ui.py`, the 116 needle tests and `bash -n` stay green.

**Done when:** the AC-125.15 tests for the mode pass. A stubbed `up` with `WITH_SYSTEM=0` in a directory without `applications/` creates the cluster, installs Argo CD and `github-creds`, creates no `<app>-<env>` namespace, applies no `bootstrap/` and prints the ready line. The existing local-cluster tests are green.

## t3 — cluster renderer and the system_render.py link

**Files:** templates/cluster-gitops/scripts/render.py, templates/cluster-gitops/scripts/system_render.py
**Covers:** AC-125.2, AC-125.3, AC-125.4, AC-125.5, AC-125.6, AC-125.14
**Goal:** `devbox run render` turns `cluster.yaml` into `cluster/` exactly as design §2 and §3 specify, using the system renderer's table and builder.

**Implementation notes:**
- `system_render.py` is a byte-identical copy of `templates/gitops-app/scripts/render.py` (design decision 13: Copier refuses a symlink out of the template, found in this task); a copy of the template must contain a regular file equal to it.
- `render.py` is a PEP 723 uv script (`dependencies = ["pyyaml"]`) with `ROOT = parent of scripts/`. It imports `system_render` from its own directory, reads `.copier-answers.yml` (`github_org`, `project_name`), and validates in the order and with the exact one-line messages of design §2 (`ERROR: cluster.yaml: <message>`, exit 1, nothing written).
- Render the layout of design §3: the roots, `operator_application(op, server)` per listed operator in `cluster.yaml` order, `secret-store.yaml` (default provider with its Namespace, SA, Role and RoleBinding; custom provider: the store only; annotations sync-wave 1 and SkipDryRunOnMissingResource), `system-<s>` applications, `.gitkeep` in an empty folder, `cluster/kustomization.yaml`. Use `system_render.dump`.
- Every file under `cluster/` that is not rendered is stale: delete it, or report it with `--check`. Remove `.gitkeep` once a folder has a manifest. Re-rendering changes nothing.
- Flags `--check`, `--crds`, `--systems`, `--name` exactly as the design §3 CLI table.
- No application carries `metadata.finalizers`. The operators root carries the `retry` block, the systems root does not.

**Done when:** the AC-125.2 to AC-125.6 and AC-125.14 renderer tests pass. Among them: an unknown or duplicate operator, a store without external-secrets, a bad system name, a duplicate repo, a repo outside org, an unknown key, a missing owner; `platform-operators` and `operator-cloudnative-pg` equal ADR-058's names and the system-rendered document; the empty-folder `.gitkeep`s; idempotence; the Copier link check.

## t4 — cluster check (devbox run check) and --urls

**Files:** templates/cluster-gitops/scripts/check.py
**Covers:** AC-125.10, AC-125.11, AC-125.12, AC-125.15
**Goal:** CI and a person see, before any merge, which registered system needs an operator the cluster does not install or would install operators itself.

**Implementation notes:**
- A PEP 723 uv script. It imports the cluster `render.py` for validation (or shares a `load_cluster()` it exports) and `system_render` for `load_system`, `resource_instances`, `policy_envs`, `envs_of`, `OPERATOR_OF_TYPE` and `ENVS`.
- No systems: `OK: no systems registered`, exit 0, and no `gh` call.
- Per system: `gh repo clone <repo> <tmp> -- --depth 1 --branch main` (stub-friendly: run `gh` from PATH, never the API by hand). The error lines are exactly those of design §4 steps 1 to 3.
- Need rules per environment exactly as design §4 step 4 (decisions 4, 5, 11). Every system under `applications/` of the repo is checked (decision 7).
- Release: the cluster's own `.platform-version` against the system repo's, with the `_commit` fallback and `release unknown` (decision 6). It is a `WARNING:` line, never a failure.
- Final lines: one `OK: <system> <repo> needs: …` per system and exit 0, or `FAILED: <n> problem(s)` and exit 1.
- `--urls`: `<system> <host>` per distinct `spec.hostnames` entry of the clone's `applications/*/overlays/*/*/httproute.yaml`; unreadable repos only warn on stderr; exit 0.
- Remove the temp clones (also on failure).

**Done when:** the AC-125.10 to AC-125.12 tests pass against a stubbed `gh` that "clones" fixture repos: a gap line per system, environment and operator; the `operators: owner` edit line; the unreadable-repo line naming the token; the release warning with exit 0; the per-system OK lines. The `--urls` test of AC-125.15 passes.

## t5 — cluster bootstrap and cluster-up

**Files:** templates/cluster-gitops/scripts/bootstrap.sh, templates/cluster-gitops/scripts/cluster-up.sh, templates/cluster-gitops/scripts/local-cluster.sh, templates/cluster-gitops/scripts/ports.sh
**Covers:** AC-125.9, AC-125.15
**Goal:** One human command installs the cluster's shared services and its systems; `devbox run cluster-up` does the same on a local k3d cluster.

**Implementation notes:**
- `local-cluster.sh` and `ports.sh` are byte-identical copies of `templates/gitops-app/scripts/<same name>`, not symlinks (design decision 13: Copier refuses links out of the template).
- `bootstrap.sh` follows design §5 steps 1 to 8 exactly (messages, the 200 × 3 s CRD wait per `render.py --crds` line, `--context` on every kubectl call, the idempotent `github-creds` apply).
- `cluster-up.sh` follows design §6. It runs `local-cluster.sh` with `WITH_SYSTEM=0` and every operator flag `0`, creates the per-system namespaces with `ghcr-pull`, runs `bootstrap.sh` with `KUBE_CONTEXT=k3d-<name>`, reads the port with `docker port`, and prints the `Exposed:` lines from `check.py --urls` and the hints (decision 12).
- `set -euo pipefail` in both scripts; `bash -n` clean.

**Done when:** the AC-125.9 tests pass with stubbed kubectl: the order (credential, operators root, CRD waits, systems root), the missing `KUBE_CONTEXT`/`REPO_TOKEN`/`argocd` errors, the CRD timeout message naming `operator-<op>` (with a shortened wait set through an env override the test uses, e.g. `CRD_WAIT_TRIES`), and a second run applying the same objects. The AC-125.15 `cluster-up` test passes with stubbed k3d/kubectl/gh/docker.

## t6 — cluster-gitops template skeleton

**Files:** templates/cluster-gitops/copier.yml, templates/cluster-gitops/devbox.json, templates/cluster-gitops/{{ _copier_conf.answers_file }}.jinja, templates/cluster-gitops/cluster.yaml.jinja, templates/cluster-gitops/cluster/operators-root.yaml.jinja, templates/cluster-gitops/cluster/systems-root.yaml.jinja, templates/cluster-gitops/cluster/kustomization.yaml, templates/cluster-gitops/cluster/operators/.gitkeep, templates/cluster-gitops/cluster/systems/.gitkeep, templates/cluster-gitops/CLAUDE.md.jinja, templates/cluster-gitops/README.md.jinja, templates/cluster-gitops/.claude/settings.json.jinja, templates/cluster-gitops/.claude/project-notes.md, templates/cluster-gitops/.github/workflows/ci.yml, templates/cluster-gitops/.github/dependabot.yml, templates/cluster-gitops/.github/ISSUE_TEMPLATE/bug_report.yml, templates/cluster-gitops/.github/ISSUE_TEMPLATE/config.yml, templates/cluster-gitops/.github/ISSUE_TEMPLATE/feature_request.yml, templates/cluster-gitops/.gitignore, templates/cluster-gitops/.secrets.baseline.json
**Covers:** AC-125.1, AC-125.2, AC-125.17
**Goal:** `copier copy templates/cluster-gitops --defaults` gives a repo that passes its own render, check and CI checks.

**Implementation notes:**
- `copier.yml`, `devbox.json`, `ci.yml`, settings and CLAUDE.md as in design §10. The `ci` recipe ends with ` && ` plus `CI_EXTRA_STEP` from `scripts/shapes.py`. The ci-extra job has the shape `_check_ci_extra` expects. `.claude/project-notes.md` is empty. `ci_checks` names are the job names verbatim.
- `cluster.yaml.jinja` writes the defaults of design §2 with a comment per key (`operators`: the allowed names come from the platform's versions table; `systems`: use `/cluster:add`).
- The initial `cluster/` files must equal `scripts/render.py`'s output for the default answers byte for byte. Generate them with t3's renderer on a copy, then template `{{ github_org }}`/`{{ project_name }}` in the two roots.
- The ISSUE_TEMPLATE forms, `.gitignore` and `dependabot.yml` are taken over from `templates/gitops-app` (actions ecosystem only). `.secrets.baseline.json` is a fresh empty baseline.
- `CLAUDE.md.jinja`: what the repo is, that `cluster.yaml` is the only hand-edited file, the commands (`/cluster:add`, `/cluster:remove`, `/platform:update`, `/platform:doctor`), `devbox run render|check|bootstrap|cluster-up`, the SYSTEMS_TOKEN secret, a link to docs/CLUSTERS.md in the platform, `## Where your additions go` and `@.claude/project-notes.md`.
- `README.md.jinja`: a short version of the same for people.

**Done when:** the AC-125.17 test passes: copy with defaults, then `render.py --check` reports no drift, `check.py` with no systems exits 0, and (when kustomize/kubeconform are present) `kustomize build cluster` plus kubeconform pass. The AC-125.1 template test (cluster.yaml names cluster and owner, no systems) passes.

## t7 — register the shape cluster-gitops

**Files:** shapes.yml, scripts/sync-template-copies.py, devbox.json, scripts/detect-shape.sh, scripts/test-detect-shape.sh, scripts/shapes.py, docs/requirements/platform-vision.md, scripts/cplat/shapecmd.py, scripts/cplat/update.py, .github/workflows/ci.yml
**Covers:** AC-125.1, AC-125.17
**Goal:** The platform knows the shape: creation, detection, `/platform:update` and the fleet treat a cluster repo like any platform repo, and `scripts/shapes.py check` passes.

**Implementation notes:**
- `scripts/sync-template-copies.py` (design decision 13): the copies `templates/cluster-gitops/scripts/{system_render.py,local-cluster.sh,ports.sh}` equal `templates/gitops-app/scripts/{render.py,local-cluster.sh,ports.sh}`. `--check` fails naming each differing copy and the fix; without `--check` it rewrites them. Add `uv run scripts/sync-template-copies.py --check` to the `quality` recipe of the root `devbox.json` and to the platform CI.
- `shapes.yml` entry exactly as design §9; PRD §4 row `| \`cluster-gitops\` | \`cluster\` | \`cluster-gitops\` | Argo CD app-of-apps for one cluster's shared services and systems | stable |`.
- `detect-shape.sh`: a `_src_path` case for `templates/cluster-gitops`, and the sniff (`cluster.yaml` and `cluster/operators-root.yaml`) before the gitops-app sniff. `test-detect-shape.sh`: a sniff fixture for it (the answers fixtures iterate the registry).
- `shapes.py`: replace the `gitops-app` special cases with two sets, `NO_DEPS = {gitops-app, cluster-gitops}` (deps recipes, deps.sh, smoke.sh, backlog) and `NO_FEATURE_SPECS = {cluster-gitops}` (Spec first, docs/plan, docs/specs, spec-check, specs.yml). The agents check skips plugin `cluster` like `system`. Error texts stay unchanged for existing shapes.
- `shapecmd.py`: the `unsupported` text for `cluster-gitops` from design §9.
- `update.py`: `render_baseline` archives `templates` (not `templates/<template>`) and copies from `src/templates/<template>`, so symlinked files resolve. No other behaviour change.
- Platform `.github/workflows/ci.yml`: the `changes` filter gets a `cluster` output (`^templates/cluster-gitops/`, plus gitops-app's `render.py`/`local-cluster.sh`). A `smoke-test-cluster-gitops` job copies the template with defaults, checks detection, runs `render.py --check`, `check.py`, `bash -n` on the scripts, and kustomize build plus kubeconform on `cluster/`. Add it to `ci-success.needs` and to the `validate-shapes` template loop if that loop must list every template. Pin actions by SHA as the other jobs do (`scripts/pin-actions.py --check`).

**Done when:** `uv run scripts/shapes.py check` and `bash scripts/test-detect-shape.sh` pass. The AC-125.1 registry test and the AC-125.17 update and fleet tests pass (`cplat platform update` on a copied cluster repo re-applies the template; `fleet.is_platform` accepts its answers). The full `tests/cplat` suite is green.

## t8 — cplat cluster new|add|remove

**Files:** scripts/cplat/clusterrepo.py, scripts/cplat/cplat.py
**Covers:** AC-125.1, AC-125.7, AC-125.8
**Goal:** The commands behind `/cluster:new`, `/cluster:add` and `/cluster:remove`, with the exact errors and outputs of design §7.

**Implementation notes:**
- `main(argv)` dispatches `new`, `add` and `remove` (argparse subcommands). Every verb has `--dry-run` and `--json` and returns a `core.Report`.
- `new`: name rule, existing-repo check (`gh repo view`), then `newsvc.resolve`/`execute` with `--shape cluster-gitops` and `--data owner=<org>`, private unless `--public`. Own title and next steps as in the design (not newsvc's component steps). Keep newsvc's `did` and `undo`.
- `add`: cluster repo check, clean tree, discovery through `gh api repos/<repo>/contents/...?ref=main`, the failure texts, the already-registered and outside-org checks before any edit. The ruamel edit of `cluster.yaml` preserves comments (reuse the `gitops._yaml()` settings). Render with `uv run scripts/render.py`; restore on failure. Branch, signed-off commit, push and PR with `cluster.yaml` and `cluster/` staged.
- `remove`: unknown-name error listing the registered systems, the edit, render, PR, and the `kept in the cluster:` line always printed (also with `--dry-run`).
- `cplat.py`: `NOUNS["cluster"]` and the docstring usage line. Nothing else in that file.

**Done when:** the AC-125.1 (`cluster new` creates through newsvc with the shape, private by default; a bad name and an existing repo change nothing), AC-125.7 and AC-125.8 tests pass with stubbed `gh` and `git` remotes.

## t9 — the cluster plugin

**Files:** plugins/cluster/.claude-plugin/plugin.json, plugins/cluster/README.md, plugins/cluster/commands/new.md, plugins/cluster/commands/add.md, plugins/cluster/commands/remove.md, .claude-plugin/marketplace.json
**Covers:** AC-125.1, AC-125.7, AC-125.8, AC-125.18
**Goal:** `/cluster:new`, `/cluster:add` and `/cluster:remove` exist as thin commands over `cplat cluster`, and the plugin is versioned in its manifest and the marketplace.

**Implementation notes:**
- `plugin.json`: name `cluster`, version `1.0.0`, description, author, homepage, repository, license and keywords, as in `plugins/system`.
- The commands follow `plugins/system/commands/new.md`: a description with usage in the front matter (at most 260 characters, valid YAML, quoted). They run `cplat cluster <verb> <ARGS> --dry-run`, show it, run it for real, and relay the output. `remove.md` repeats that nothing is deleted in the cluster. Each ends with the `/issue:report` note.
- `README.md`: the commands, what the cluster repo is, a link to `docs/CLUSTERS.md`.
- `marketplace.json`: one entry `cluster` 1.0.0, `./plugins/cluster`, category `agents`, tags. No other entry changes.

**Done when:** `devbox run validate` and the version-match loop of `devbox run quality` pass, `scripts/shapes.py check_front_matter` is clean, and the AC-125.18 plugin and marketplace test passes.

## t10 — platform doctor in a cluster repo

**Files:** scripts/cplat/doctor.py
**Covers:** AC-125.13
**Goal:** `/platform:doctor` in a cluster repo shows installed against expected version per listed operator, and sync and health per registered system.

**Implementation notes:**
- In `check_repo`, when the detected shape is `cluster-gitops`, append `check_cluster(repo)` rows (design §8). The existing system-repo rows return nothing there (no `applications/`).
- Read `cluster.yaml` with `yaml.safe_load`. An unreadable file gives the single WARN row.
- The installed version comes from the row's `selector`, default `app.kubernetes.io/name=<chart>`, with a leading `v` stripped. The expected version comes from `_operators()` (the platform's table).
- System rows come from the `kubectl -n argocd get application system-<s>` jsonpath, with the three cases of the design.
- Skip all of it when `kubectl` is not on PATH, as the other kube rows do.

**Done when:** the AC-125.13 tests pass with a stubbed kubectl (equal, missing and different operator; Synced/Healthy, OutOfSync/Degraded and missing system application), and the existing doctor tests are green.

## t11 — end-to-end: two systems, one operator

**Files:** tests/e2e/cluster.sh, .github/workflows/e2e.yml
**Covers:** AC-125.16
**Goal:** On a real k3d cluster, a cluster repo's operators are installed once and two systems' databases both become ready on them.

**Implementation notes:**
- `tests/e2e/cluster.sh` follows design §11 steps 1 to 5, in the style of `tests/e2e/run.sh` (`fail`, `step`, cleanup trap, `E2E_KEEP`, the devbox shim is not needed). The pins come from the cluster render (`targetRevision`), never hard-coded.
- Asserts: neither system renders `operators/`; the cluster render has `operator-cloudnative-pg` and `operator-external-secrets`; both `Cluster` objects are healthy; exactly one CloudNativePG operator Deployment.
- `e2e.yml`: the job `e2e-cluster` (same setup steps as `e2e`, without Java), and `templates/cluster-gitops/**` in the paths. Pin actions by SHA.
- `bash -n tests/e2e/cluster.sh` clean.

**Done when:** the AC-125.16 static test passes (the script holds those steps and assertions, and the workflow runs it), and a local run with Docker prints `E2E CLUSTER OK`.

## t12 — docs

**Files:** docs/DOMAIN-MODEL.md, docs/CLUSTERS.md, docs/templates.md, docs/CHANGELOG.md
**Covers:** AC-125.14, AC-125.18
**Goal:** The Cluster is part of the domain model, people have a guide, and the release note announces the change as a non-breaking minor.

**Implementation notes:**
- `DOMAIN-MODEL.md`: a Cluster noun next to the system model. The place systems run, with its shared operators, External Secrets with the secret store, the Kyverno engine, and its registered systems; one system runs all its environments on its cluster; link ADR-060. Add `/cluster:new|add|remove` to "Commands follow the nouns".
- `docs/CLUSTERS.md` (new guide), with three sections:
  - **Create a cluster repo**: `/cluster:new`, `cluster.yaml`, the SYSTEMS_TOKEN secret, operators, one bootstrap with `REPO_TOKEN`, `cluster-up` locally.
  - **Install a system**: `/cluster:add`, `operators: owner` in every environment, CI check, `/cluster:remove` and what stays.
  - **Moving an existing cluster** (AC-125.14), numbered in this order:
    1. List every operator in the owning system's `operators/apps/` in `cluster.yaml` and check that the versions match (same platform release, else update first).
    2. Bootstrap the cluster repo. `platform-operators` and `operator-<name>` are taken over in place, and nothing is reinstalled.
    3. Set `operators: owner` in every environment of every system, and merge.
    4. `/cluster:add` each system (its `<system>-root` is adopted).
    5. Check with `/platform:doctor`.

    End the section with why no CloudNativePG cluster restarts and no data is lost (same application, chart, release and namespace; no finalizer).
- `docs/templates.md`: a `cluster-gitops` row.
- `docs/CHANGELOG.md` `[Unreleased]`, a paragraph in the style of the 115/116 entries, without BREAKING:
  - **A cluster repo hosts several systems**: ADR-060, spec 125. Not breaking: a system repo renders as before.
  - **Plugins:** new `cluster` 1.0.0.
  - The versions table pins `external-secrets` 2.12.0 and `kyverno` 3.9.1.
  - **Action** for shared clusters, pointing to docs/CLUSTERS.md.

**Done when:** `python3 scripts/check-links.py` passes and the AC-125.14 and AC-125.18 doc tests pass (the guide has the moving steps in order; the domain model names the Cluster; the changelog's Unreleased section names the cluster plugin and is not BREAKING).

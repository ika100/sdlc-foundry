# Architecture decision records

Decisions that shape how the platform works, with the context and the alternatives that were rejected. Every ADR has a status line; superseded decisions keep their file and say which ADR replaced them.

**Adding one:** copy the structure of a recent ADR (context, decision, consequences, what is not included), use the next free number, and list it in the table below (`scripts/shapes.py check` fails when an ADR file is missing here).

| ADR | Decision |
|---|---|
| [001](001-marketplace-plus-copier.md) | Two-channel distribution — Claude Code marketplace + Copier templates |
| [002](002-web-testing-stack.md) | Web testing stack — Vitest + Playwright opt-in |
| [003](003-web-package-manager.md) | Web package manager — pnpm |
| [004](004-nextjs-app-router.md) | Next.js router — App Router only |
| [005](005-node-version-policy.md) | Node version policy — pin current LTS, bump via `copier update` |
| [006](006-gitops-app-overlay-structure.md) | gitops-app overlay structure — env-only |
| [007](007-cross-repo-orchestration-scope.md) | Cross-repo orchestration — plan-only in v1, execution in v2 |
| [008](008-shape-detection.md) | Shape detection — `.copier-answers.yml` with sniffing fallback |
| [009](009-service-java-stack.md) | `service-java` stack defaults |
| [010](010-service-go-stack.md) | `service-go` stack defaults |
| [011](011-multi-repo-plan-format.md) | Multi-repo plan format for `/app:build-feature` |
| [012](012-per-plugin-release-agent.md) | Per-plugin release agent |
| [013](013-plugin-auto-enable.md) | Plugin auto-enable on `/shared:new-service` |
| [014](014-gitops-app-composition-spec.md) | gitops-app composition spec |
| [015](015-shape-registry-as-code.md) | Shape registry as code (`shapes.yml`) |
| [016](016-library-python-distribution.md) | `library-python` distribution — git+https via `uv` |
| [017](017-gitops-owns-manifests.md) | The GitOps repo owns every Kubernetes manifest; services ship an image |
| [018](018-secrets-with-external-secrets-operator.md) | Secrets come from External Secrets Operator; git holds references, never values |
| [019](019-supply-chain-hardening.md) | Supply-chain hardening for generated repos |
| [020](020-addons-contract.md) | Addons: a stable contract for backing services |
| [021](021-observability-otel.md) | Observability: an OpenTelemetry base, a UI stack as an option |
| [022](022-kyverno-policies.md) | Kyverno guard rails, checked before merge and enforced in the cluster |
| [023](023-parallel-plan-execution.md) | Multi-repo plans run in parallel waves; merging and pinning stay human |
| [024](024-spec-driven-bootstrap.md) | Spec-driven bootstrap: new repos start with plan-feature, build-feature consumes the plan (superseded in part by 026) |
| [025](025-issue-triage.md) | Issue triage: `/shared:triage` classifies, discusses and routes issues; labels are the state |
| [026](026-feature-specs.md) | Feature specs drive the build: spec folders, AC ids, tests first, `cplat spec` |
| [027](027-dev-follows-main-through-pin-prs.md) | dev follows main: service CI asks the gitops-app for an auto-merging pin PR to `sha-<7>` |
| [028](028-unattended-delivery-without-branch-protection.md) | Unattended delivery without branch protection: merges wait for green CI in code, `/svc:ship`, a Stop hook, headless resumes |
| [029](029-external-services.md) | External services in services.yaml: hand-written kustomize packages or Helm charts, wired and pinned by render |
| [030](030-image-tags-are-the-full-commit-sha.md) | Image tags are the full commit sha (`sha-<40>`); `sha-<7>` is accepted for one release |
| [031](031-repo-owned-companions-for-skeleton-files.md) | Skeleton files stay platform-owned; repo additions go in repo-owned companions (`ci-extra`, own permissions, own workflows, project notes) that updates never touch |
| [032](032-private-run-store.md) | Every run is recorded in a private run store: one file per run, one commit per flush, buffered locally when unreachable |
| [033](033-auto-filed-issues-with-signatures.md) | Failures become auto-filed issues, deduplicated by one `Signature: <kind>:<16 hex>` body line; one module (`autoissue`) for platform failures, smoke failures and alerts |
| [034](034-fixable-dependency-findings-are-patched-by-the-run.md) | Fixable dependency findings are patched by the run: deps recipes per shape, cplat deps patch, 2 rounds, exact revert |
| [035](035-token-usage-from-session-transcripts.md) | Token usage is measured from the local session transcripts: sessions claimed via CLAUDE_CODE_SESSION_ID, shared calls split evenly, costs estimated from a price table in the repo |
| [036](036-coordinator-model-default-and-settings.md) | The coordinator of a headless run uses Sonnet by default; a flag, a project setting (optionally per workflow) or a user setting choose otherwise |
| [037](037-cplat-bundles-honour-the-allowlist.md) | cplat commands that bundle several steps never widen the session's permissions: each part runs only if the repo allowlist allows it |
| [038](038-alert-poll-on-the-gitops-runner.md) | Alerts reach GitHub through a scheduled `cplat alerts poll` on the gitops-app's self-hosted runner; rules in `app.yaml`, lifecycle state in the issues, a dedicated `ALERTS_TOKEN` for service repos |
| [039](039-weekly-retro-evidence-checked-proposals.md) | The weekly retro: a deterministic report in code, agent proposals posted only when their evidence is in the report; a public issue with counts, the detail in the private run store |
| [040](040-smoke-tests-against-a-deployed-environment.md) | Smoke tests run against a deployed environment: a `(smoke)` criterion marker, `devbox run smoke` with `SMOKE_BASE_URL` and one output contract per shape, `cplat smoke` reads it; red smoke in dev escalates as `code`, not-run never counts as passed |
| [041](041-staging-follows-green-dev-smoke.md) | Staging follows a green dev smoke through a self-merging pin-staging PR (app-wide setting, per-service override); prod stays a manual /gitops:promote with an evidence summary |
| [042](042-product-ship-coordinates-repo-ships.md) | A product ship (`/app:ship`) coordinates one unchanged `cplat ship` per component repo: per-repo gates (smoke, Argo, merged PR) before dependents start, gitops merges serialized in plan order, one `product-ship` record |
| [043](043-one-budget-per-run-tree.md) | One budget per run tree (minutes, agent invocations, CI reruns, estimated cost) in a local ledger keyed by the work, checked at safe points; a stop escalates with cause decision and stays resumable |
| [044](044-change-aware-validation-in-the-inner-loop.md) | Change-aware validation only in the inner loop, decided by deterministic rules (mandatory categories force everything, unmapped runs everything, risk only adds); the final gate and PR CI stay full |
| [051](051-run-state-is-per-worktree.md) | Run state (ship, app-ship, run pointer, recovery snapshot, pending replans) lives in the worktree's own git dir, so worktrees never block or attach to each other; the gitops merge slot and the evidence cache stay in the common dir |
| [052](052-shared-renders-in-the-platform-test-suite.md) | Tests that only need a rendered repo share one render per key and process and get private copies; the cplat suite runs in 4 round-robin shards whose coverage a CI job checks; render-subject tests still render |
| [053](053-domain-model.md) | One domain model for the platform: Backstage's system model (System, Component, API, Resource, Owner) plus Environment, Instance and Resource instance, and the delivery nouns; an internal model in cplat first (4.x), then system.yaml and noun-based commands in 5.0; cluster names never change |
| [054](054-five-zero-interface-and-proved-migration.md) | The 5.0 interface: system.yaml checked by the renderer, noun plugins with tombstones for every 4.7 command, and a migration that proves the render is unchanged before it merges |
| [055](055-local-console-over-cplat-json.md) | The local console (`cplat ui`) is a Python stdlib server on 127.0.0.1 with server-rendered HTML and one dependency-free script; it reads only `cplat` JSON (subprocesses, snapshots of `main`), acts only through slash commands run by Claude Code, and delivers notifications locally |
| [056](056-the-platform-repo-declares-its-shape.md) | The platform repo declares `shape: platform` in its committed `.platform-settings.yml`: a template-less, declared-only registry entry that `shapes.load()` hides from every create, adopt, update and fleet path; never sniffed, no release role |
| [057](057-named-typed-resources-with-fixed-contracts.md) | Resources are named and typed (`database`, `bucket`, `cache`, `broker`); each type has a fixed Secret-key and variable contract, prefixed `<NAME>_` when a component uses two of one type; Secret `<system>-<name>-app` and Argo application `addon-<name>-<env>` for every resource; any resource instance may be external, synced from the secret store |
| [058](058-pinned-versions-and-platform-installed-operators.md) | Images and operator charts are pinned exactly in the renderer's versions table per release; the renderer writes the operators a cluster needs as Argo CD applications under `operators/` (once per cluster, only when needed, no finalizer); `environments.<env>.operators: owner` opts out and doctor compares versions (shared clusters: amended by 060) |
| [059](059-in-cluster-buckets-on-seaweedfs-per-instance.md) | An in-cluster bucket is its own SeaweedFS (one `Seaweed` per bucket instance, a `storage`-sized volume, the filer's S3 endpoint), run by the SeaweedFS operator that the platform installs under `operators/`; keys are generated in the cluster by External Secrets Operator and adopted by the operator; Argo CD never deletes a bucket (`Delete=false`, `Retain`); `versioning: false` renders `Suspended` |
| [060](060-a-cluster-repo-owns-shared-services.md) | A cluster repo (template `cluster-gitops`, plugin `cluster`) owns what a cluster shares: the operators it lists (pinned from the renderer's versions table, linked, never copied), External Secrets with the `ClusterSecretStore`, the Kyverno engine, the org's Argo CD repo credential, and one root application per registered system; installing a system is a PR, a check finds missing operators, takeover keeps ADR-058's application names |
| [061](061-database-backups-with-the-barman-cloud-plugin-and-restore-by-generation.md) | Databases are backed up by the CloudNativePG Barman Cloud plugin (with cert-manager, both platform operators) to a bucket resource; an external target bucket declares `remote.s3` in git; a point-in-time restore is a new generation `<system>-<name>-g<n>` next to the live one, recorded in `restore-state.yaml`; a switch detaches the connection Secret `<system>-<name>-app` and repoints it |
| [062](062-environment-backups-with-velero.md) | An environment is backed up by Velero (one per cluster, a platform operator with the resources finalizer): per system and environment a location, a schedule and synced credentials in `velero`; file-system backup of persistent volumes, `emptyDir` skipped; databases, caches and the target bucket left out by kind and label; restore adds what is missing, `--replace` pauses and replaces |
| [063](063-autonomy-in-system-yaml-and-the-engine-contract.md) | Autonomy is declared per environment in `system.yaml` (levels, guardrails, pause) and rendered to `autonomy.json`; an engine such as ai-ops is bound by a contract (issue format, fix run record, audit event, HTTP signals) and only signals (pause, resume, lower) act before a merge |

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
| [036](036-alert-poll-on-the-gitops-runner.md) | Alerts reach GitHub through a scheduled `cplat alerts poll` on the gitops-app's self-hosted runner; rules in `app.yaml`, lifecycle state in the issues, a dedicated `ALERTS_TOKEN` for service repos |

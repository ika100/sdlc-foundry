# User journey: from empty folder to a running SaaS system

A guided walk-through of the whole platform, told through one made-up system, **Taskboard** (a Python API + a Next.js frontend, deployed by ArgoCD). Use it to explain the setup to someone new; every command below exists, and the reference docs are linked at the end.

**You type slash commands in Claude Code. Claude does the engineering; you review pull requests.**

---

## The mental model (2 minutes)

```mermaid
flowchart TB
  subgraph PLATFORM["ika100/sdlc-foundry — one marketplace repo"]
    direction LR
    PL["Plugins<br/>agents · commands · cplat"]
    TP["Templates<br/>one per shape"]
  end
  CC["You: Claude Code + devbox"]
  subgraph REPOS["Your repos on GitHub"]
    direction LR
    GIT["taskboard<br/><i>gitops-app</i>: which services,<br/>which version runs where"]
    subgraph SVC["Service repos"]
      direction LR
      API["taskboard-api<br/><i>service-python</i>"]
      WEB["taskboard-web<br/><i>web-nextjs</i>"]
    end
  end
  IMG[("Images<br/>GHCR")]
  K8S["Kubernetes<br/>dev · staging · prod"]

  PL -- "/plugin install" --> CC
  TP -- "/component:new (once)<br/>/platform:update (later)" --> REPOS
  CC -- "/component:spec → plan → build<br/>pull requests" --> SVC
  CC -- "/system:spec → plan → ship<br/>/component:add · /instance:promote" --> GIT
  SVC -- "CI on main" --> IMG
  GIT -- "ArgoCD reconciles" --> K8S
  IMG -. "pulled" .-> K8S
```


Four ideas carry everything:

1. **Shapes.** Every repo has a *shape* (`service-python`, `web-nextjs`, `gitops-app`, `service-java`, `service-go`, `library-python`). The shape decides which template creates it and which agents work on it. You never pick agents; commands detect the shape.
2. **`devbox run <recipe>` is the only way anything runs** (`test`, `quality`, `security`, `image-build`, …). Same recipes in every shape, so humans, CI and agents behave identically.
3. **Specs drive the work.** A feature starts as a spec in `docs/specs/` with numbered acceptance criteria you approve; the build writes failing tests from them first, then the code, and verifies every criterion before the pull request. Small changes and bug fixes skip the spec.
4. **Two update channels.** Agents and commands update with `/plugin marketplace update`; the project skeleton (CI, Dockerfile, devbox, CLAUDE.md) updates with `/platform:update`. Your own code is never touched by either.

The nouns behind all of this (system, component, API, resource, environment, instance, spec, run) are in the [domain model](DOMAIN-MODEL.md). It is the model the platform speaks since 5.0; its last section maps the 4.x names onto it.

---

## Chapter 0 — One-time setup (10 minutes)

| Need | How |
|---|---|
| Claude Code | already installed |
| devbox | `curl -fsSL https://get.jetify.com/devbox/install.sh \| bash` |
| GitHub CLI, logged in | `gh auth login` (without it, `/component:new` prints the GitHub commands instead of running them) |
| copier | installed for you via `uv` on first use |
| A Kubernetes cluster with ArgoCD installed | out of scope here; Argo needs read access to your GitHub repos (and the cluster must be able to pull your images) |

Make the platform's commands available (once per machine/user, or pre-wired in each repo — step 1 of every new repo does that for you):

```
/plugin marketplace add ika100/sdlc-foundry
/plugin install shared@sdlc-foundry
```

You can already create repos with just `shared`. Every generated repo enables the plugins it needs.

---

## Chapter 1 — Create the system's GitOps repo

```
/system:new taskboard.yml
```

`taskboard.yml` is a small manifest: `system: taskboard`, `owner: <you>`, and `components:` with `name`, `description`, `type`, `lang`. The command creates the gitops-app repo and every component repo (chapter 2) in one go; chapters 1 to 3 show what each step does.

What happens (no questions asked beyond the name and a description):

1. The `gitops-app` template is rendered, committed, and pushed to a new **private** repo `<you>/taskboard`.
2. You get `applications/taskboard/` with a `system.yaml` (the one file you edit: environments with hosts and policy, components, APIs, resources), generated ApplicationSets (dev/staging/prod), a `bootstrap/` root Argo Application, plus CI that validates everything offline (`kustomize build`, `kubeconform` incl. the Argo and Gateway CRDs, label check, secret scan). **This repo will own every Kubernetes manifest of the system** — the services only ship images.
3. It is *not* tagged `deployable-service` (it is the GitOps source, not a service).

> **One command for the whole system.** `/system:new` creates the GitOps repo and every component in the right order and opens one pull request that adds the components to `system.yaml`. Add `--dry-run` to preview; after a failure, `--resume` continues.

Open it: `cd taskboard && claude`. Its `CLAUDE.md` already explains the layout and pin policy to Claude.

> **One-time cluster step (human, once per cluster).** Make sure Argo can read your GitHub repos (repo credentials), then run `KUBE_CONTEXT=<your-cluster> devbox run bootstrap` in `taskboard` (it applies `bootstrap/taskboard-root.yaml`). That root Application watches `applications/taskboard/applicationset.yaml` in git — from then on every change reaches the cluster through merged pull requests, and agents never run `kubectl apply`.

> **Just want to try it on your laptop?** `devbox run cluster-up` creates a local k3d cluster (`taskboard-local`), installs ArgoCD and the Gateway API (Traefik), gives Argo your `gh` token for this private repo and the cluster a GHCR pull secret, applies the root Application and prints the URLs of exposed services; `devbox run cluster-down` removes it. Needs Docker running.

---

## Chapter 2 — Create the services

```
/component:new taskboard-api Task CRUD API --system <you>/taskboard
/component:new taskboard-web Taskboard frontend --type website --system <you>/taskboard
```

Each command: renders the template → commits → creates a private repo → adds the `deployable-service` topic → writes `.platform-app.yml` (so `/instance:promote` can later find `taskboard` from inside this repo).

| Repo | Type / language | What you get on day one |
|---|---|---|
| `taskboard-api` | `service` / `python` | FastAPI app with `/health` + `/ready`, pytest + coverage gate, ruff/mypy, Dockerfile (numeric non-root user), CI incl. multi-arch image push. **No Kubernetes files.** |
| `taskboard-web` | `website` / `typescript` | Next.js App Router, Vitest, `/api/health` `/api/ready` `/api/metrics`, Dockerfile, CI incl. multi-arch image push. **No Kubernetes files.** |

Want Java or Go instead? `--lang java` / `--lang go`. A shared library? `--type library`.

```bash
cd taskboard-api && devbox shell
devbox run quality && devbox run test      # sanity check — should be green out of the box
```

---

## Chapter 3 — Build a feature from a spec

You can start immediately after Chapter 1: the feature branch is cut from the bootstrap commit, so the first pipeline run on `main` does not need to finish (or even be merged anywhere) before work begins. Its only job is to publish the first image, which you need again only when you deploy.

In `taskboard-api`, inside Claude Code:

```
/component:spec "ping endpoint"     # docs/specs/001-ping-endpoint/spec.md; asks you its open questions, then whether to approve
/component:plan 001                 # design.md + plan.md for the approved spec; review the plan
/component:build 001                # tests first, then the code, verified against the spec, then a PR
```

**The spec** (`/component:spec`) is the contract: the product-manager writes the problem, stories, **acceptance criteria** with ids (`AC-001.1` … in Given / when / then), non-goals and open questions. It never guesses a decision that is yours: the command asks you each open question (with a suggested answer) and folds your answers in. A spec is built only after you approve it (`/component:spec approve 001`, or "Approve" when the command asks). Changing it later: `/component:spec --amend 001 "<change>"`.

**The plan** (`/component:plan`): the architect writes `design.md` (decisions and the API contract) and `plan.md` (tasks with files, dependencies and the criteria each task `covers`). `cplat spec check` rejects a plan that leaves a criterion uncovered or lets two parallel tasks touch the same file, and rejects it again if the spec's criteria change afterwards.

What `/component:build` does (you watch phase headers, you are only asked before pushing):

| Phase | Who | Output |
|---|---|---|
| 0 | orchestrator | detects shape, switches to `feature/<spec_id>`, refuses a dirty tree or an unapproved spec |
| 1 | shape's **tester**, acceptance mode | one or more tests per criterion, named after it (`# AC-001.1`), committed while they **fail** |
| 2 | shape's **coder** agents, in parallel git worktrees | implementation until those tests pass, merged with a quality gate between merges; tasks are marked done, so a re-run resumes |
| 3 | quality ‖ tester ‖ security, in parallel | lint/types, full tests + coverage, CVE + secrets scan |
| 4 | **reviewer** | every criterion checked against tests and code → `verification.md` (met / not met, with evidence) |
| 5 | deployment | container image verified (`devbox run image-build`, smoke start) — never Kubernetes manifests |
| 6–7 | orchestrator | spec marked done, asks to push, opens a PR listing every criterion, linked issues, checklist |

`/component:spec` shows every spec with its status and the next command. You review and merge the PR. CI re-runs the same recipes and, on merge to `main`, **pushes a multi-arch image** (`latest`, `sha-<7>`).

Smaller jobs need no spec: `/component:fix "description or stack trace"` (coder → quality → tester). It stops and point to `/component:spec --amend` when the change would contradict a criterion. Any time: `/component:check` (read-only audit).

Same commands in `taskboard-web`: the orchestrator detects the `website` type and uses the web coder/tester (Vitest, App Router idioms) instead.

---

## Chapter 4 — Put the components into the system

Both services have merged to `main` and their images exist. In `taskboard`:

```
/component:add taskboard-api taskboard-web
```

The script verifies each repo exists and has the `deployable-service` topic, reads its type, language and port from the component's `.copier-answers.yml`, and writes a **complete, explicit** entry per component into `components:` of `system.yaml` (type, lang, port, probes, numeric user, writable volumes, env, replicas, resources — the shape's defaults), regenerates ApplicationSets and manifests (`devbox run render`) and opens **one PR**. New components start with a **dev instance only**.

Wiring and exposure are decided here, in the system repo — not in the components:

```
/component:add taskboard-api
/component:add taskboard-web --expose --env API_URL=http://taskboard-api
/component:set taskboard-web --env FEATURE_X=on     # later: change a component that is already added
```

`--expose` publishes `taskboard-web` through the Gateway: after the PR merges, `http://taskboard-web.taskboard-dev.localhost:8088/` (the local cluster's port, or the next free one that `cluster-up` prints; `*.localhost` needs no DNS setup) serves the UI. Edit `replicas`, `resources` or `secretRefs` of a component in `system.yaml` any time and run `devbox run render` (or ask Claude). Merge the PR; Argo creates the Applications. **dev** follows each service's `main`: every merge opens a pin PR to its `sha-<40>` in this repo that merges itself after CI ([ADR-027](adr/027-dev-follows-main-through-pin-prs.md); set the `GITOPS_TOKEN` secret that `/component:new` names).

---

## Chapter 5 — Promote through the environments

```
/instance:promote taskboard-api taskboard-web --to staging
```

One PR that adds a **staging** instance to both components and pins each to the `sha-<40>` image built from its `main` — the script checks that the image exists in GHCR first, so a promotion can never point at a build that CI has not finished. Merge → Argo creates and rolls staging.

After the first promotion, staging follows dev by itself: when a build passes its smoke tests in dev, `/component:ship` has the gitops-app's `pin-staging` workflow open a PR that merges itself once CI passes (spec 093, ADR-041), then smokes staging. Turn it off with `promote: manual` on the `staging` environment in `system.yaml`, or on one component's `staging` instance.

For **prod** you pin a release: in each service repo run `/component:release` (quality gate → test gate → security gate → version bump → changelog PR → tag `vX.Y.Z` → CI pushes semver images). Then:

```
/instance:promote taskboard-api --to prod            # newest release that has a published image
/instance:promote taskboard-web --to prod --version v1.2.0     # or an explicit version
```

Prod pins the release image `1.2.0` (the `v1.2.0` git tag without the `v`, exactly what CI publishes). The command prints **ABOUT TO PROMOTE TO PRODUCTION** and waits for a yes before opening the PR. The summary of what the release has been through (smoke in dev and staging, open issues) is shown first. A prod PR never merges itself; rolling back is reverting the promote PR.

---

## Chapter 6 — A feature that spans repos

"Add billing" touches the API, the web app, maybe a shared models library. In `taskboard`:

```
/system:spec "add billing with Stripe checkout"   # system spec: criteria across the system; answer, approve
/system:plan 003                                  # which repo implements which criterion, in which order, the contract
/system:ship 003                                  # every ready repo in parallel, each ending at an open PR
```

`/system:spec` writes one **system spec** in `docs/specs/` with criteria users of the system observe, asking you its open questions and for approval. `/system:plan` has the planner assign **every criterion to a repo** (`plan-check` refuses a plan that leaves one out), order the repos by real dependencies (library → API; an API and the web app that calls it run in parallel when the plan's `## Contract` section fixes the interface) and plan the version pins.

When the feature needs wiring in this repo (a resource, exposure, an env variable), the plan lists it as `gitops:` operations on the `taskboard` entry; `/system:ship` applies them here with `cplat resource add` and `cplat component set` and opens that PR first, marked **merge first**.

`/system:ship` then starts one agent per ready repo **in parallel**. Each runs `/component:spec --from-plan` in its repo: the platform writes the repo's own spec with the system criteria it owns and the contract, the product-manager turns them into the repo's criteria, and the normal Chapter 3 pipeline (`/component:plan`, `/component:build`) runs to an open PR. Questions a repo spec raises come back to you. You merge; it moves on to the next level and finally prints the `/instance:promote` commands. By hand, the same per repo: `cd ../taskboard-api && /component:spec --from-plan <plan> taskboard-api`, then `/component:plan` and `/component:build`. `/system:spec` shows the progress.

---

## Chapter 7 — Secrets, a database, telemetry and guard rails

Everything here is a declaration in the GitOps repo; `render.py` turns it into manifests and ArgoCD syncs them.

| You want | Run | You get |
|---|---|---|
| A random credential the system owns | `/component:add taskboard-api --generate taskboard-api-auth=JWT_KEY` | An `ExternalSecret`: External Secrets Operator creates the value in the cluster, once per environment. Nothing in git |
| A credential someone else issues | `/component:add taskboard-api --secret taskboard-api-stripe=STRIPE_KEY`, then `/instance:secret set taskboard-api taskboard-api-stripe STRIPE_KEY` | The value is read from your secret store (locally the `secrets-store` namespace) |
| A database | `/resource:add <name>` (a named resource of `type: database`, `--external` for one outside the cluster), then `uses: [<name>]` on the component (`/component:set <component> --uses <name>`) | A CloudNativePG cluster per environment, or an ExternalSecret for an external one; `DATABASE_URL` and `PG*` reach the component (prefixed with the resource name when it uses two databases) |
| A bucket | `/resource:add <name> --type bucket [--storage <size>] [--versioning]` (`--external` for one outside the cluster), then `uses: [<name>]` on the component | A SeaweedFS store per bucket instance, or an ExternalSecret for an external one; `S3_*` and `AWS_*` variables reach the component (prefixed with the resource name when it uses two buckets, e.g. `UPLOADS_S3_BUCKET`); removing the resource keeps the data |
| A cache | `/resource:add <name> --type cache` (`--external` for one outside the cluster), then `uses: [<name>]` on the component; set `memory`, `maxmemoryPolicy`, `persistence` and `storage` in `system.yaml` | One Valkey server per cache instance (Redis protocol), or an ExternalSecret for an external one; `REDIS_URL`, `REDIS_HOST`, `REDIS_PORT` and `REDIS_PASSWORD` reach the component (prefixed with the resource name when it uses two caches, e.g. `SESSIONS_REDIS_URL`); cache data is not backed up |
| Events between components | `/resource:add <name> --type broker`, then declare an events API (`apis.<api>: {type: events}`, with `broker: <name>` when the system has several brokers) and list it in `provides` and `consumes`; no `uses` is needed | One NATS server with JetStream per broker instance (NACK creates a stream per events API and a durable consumer per consuming component), or an ExternalSecret for an external one; `NATS_URL`, `NATS_USER`, `NATS_PASSWORD`, `NATS_INBOX_PREFIX` and `EVENTS_<API>_STREAM`, `_SUBJECT_PREFIX`, `_CONSUMER` reach the provider and the consumers; streams and consumers are never deleted by the platform |
| Traces and metrics | set `observability: {ui: lgtm}` on an environment in `system.yaml` | An OpenTelemetry collector in that environment, `OTEL_*` in every component, a local Grafana at `http://grafana.localhost:8088 (or the port cluster-up prints)` |
| Policy | set `policy: audit` or `policy: enforce` on an environment in `system.yaml` | Kyverno policies for that environment (audit reports, enforce blocks) and an offline check in `devbox run validate` |

`devbox run cluster-up` applies `operators/root.yaml`, so the platform installs the operators these declarations need; on a real cluster apply it once with `devbox run bootstrap`, or set `operators: owner` on an environment whose cluster owner installs them. Back up a database or an environment with `backup` in `system.yaml` and restore with `/resource:restore` and `/system:restore`: [BACKUP-AND-RESTORE.md](BACKUP-AND-RESTORE.md). Limits: the database resource has no pooling, observability ships no alert rules. Concept pages on the documentation site: [resources](https://ika100.github.io/sdlc-foundry/concepts/addons/), [secrets](https://ika100.github.io/sdlc-foundry/concepts/secrets/), [guard rails](https://ika100.github.io/sdlc-foundry/concepts/guard-rails/).

---

## Chapter 8 — Living with it

| Situation | What to do |
|---|---|
| Agents or commands improved | `/plugin marketplace update` |
| CI / Dockerfile / devbox recipes improved in the template | `/platform:update` in each repo → review branch → PR |
| Need a feature flag in the template (e.g. migrations, observability) | `/platform:update --data needs_migrations=true` |
| New backend language/framework | `docs/templates.md` — add a shape; CI enforces the checklist |
| Repo existed before the platform | `docs/ADOPTING.md` (migration guides per shape) |
| Something broke in a recipe | fix `devbox.json` — never bypass it with raw `pnpm`/`mvn`/`go`/`uv` |
| Setup looks wrong | `/platform:doctor` (tools, `gh` scopes, Docker, kube context, plugin versions) and `/system:status` (what runs where) |
| A platform template, script or command misbehaves | `/issue:report` drafts a GitHub issue with diagnostics and secrets removed; it is filed only after you approve it (issues are public) |

---

## The whole journey in one screen

```
/system:new taskboard.yml     GitOps repo for Taskboard plus its components
/component:new taskboard-api  Task API --system me/taskboard      (or let /system:new do it)
/component:new taskboard-web  Frontend --type website --system me/taskboard

(in each service)   /component:spec "first feature" → answer, approve → /component:plan 001 → /component:build 001  → PR → merge → image pushed
(in taskboard)      /component:add taskboard-api taskboard-web
                    /instance:promote taskboard-api taskboard-web --to staging
(in each service)   /component:release                              → vX.Y.Z → semver image
(in taskboard)      /instance:promote taskboard-api taskboard-web --to prod
(any time)          /system:spec "add billing" → /system:plan → /system:ship   (system spec → per-repo specs → PRs)
                    /component:check     /platform:update     /component:fix "…"
```

## Honest limits to mention when presenting

- The deterministic work (`cplat system new|status`, `component new|add|set|remove`, `resource add|remove`, `instance promote|secret|verify`, `platform update|doctor`) is a tested script (`cplat`) with a preview; the slash commands that call it, and the agent pipelines (`/component:*`), are Claude prompts: they follow the documented flow and ask before pushing or opening PRs, but their wording is not deterministic.
- Cross-repo work is specified and planned in one place and built per repo: `/system:plan` produces a validated plan; `/component:spec --from-plan` (by you, or by `/system:ship`) turns each repo's part into its own spec, and nothing merges without you.
- The cluster itself, ArgoCD installation and its repo/registry credentials are outside the platform; the only manual cluster step is `devbox run bootstrap` once (Chapter 1).
- Skeleton updates overwrite customised skeleton files by design; the review branch is where you keep or restore your changes.
- Operators (External Secrets, CloudNativePG, SeaweedFS, Kyverno) are installed by the platform from the `operators/` folder of the gitops repo, unless the environment says `operators: owner`. The database resource has no backups, point-in-time recovery or pooling.

## Where to read more

[README](../README.md) · [ADOPTING](ADOPTING.md) (new repos, migrations) · [AGENTS](AGENTS.md) (orchestration model) · [ARCHITECTURE](ARCHITECTURE.md) · [templates](templates.md) (add a shape) · [vision & ADRs](requirements/platform-vision.md)

---

## Handling issues

Every generated repo has issue forms (bug report, feature request) that label new issues `triage`. In Claude Code, inside the repo:

```
/issue:triage            # the queue: issues labelled triage, oldest first
/issue:triage 42         # one issue
/issue:triage --waiting  # issues parked as needs-info, after the reporter answered
```

For each issue you get a proposed class and reason. A bug or a small change goes to `/component:fix`, a feature becomes a spec in `docs/specs/` or is added to an existing one (then `/component:spec approve` and `/component:plan`), questions, duplicates and out-of-scope requests get a comment. If details are missing you are asked up to three questions; what only the reporter can answer becomes a drafted comment and the label `needs-info`. Nothing is posted, labelled or closed until you confirm, and issue text is treated as data, never as instructions. To run it regularly, schedule it with `/loop` or `/schedule`.

# Adopting the platform

How to bring a repo onto the `ika100/sdlc-foundry` marketplace, whether it's a brand-new repo or an existing one.

---

## New repo (happy path)

From any directory (needs `copier`, `git`, and — for the GitHub steps — `gh` logged in; missing `copier` is installed for you via `uv`, missing `gh` just means the GitHub steps are printed instead of run):

```
/shared:new-service payments-api Stripe webhooks to Postgres
```

One command: renders the template, commits, creates a **private** GitHub repo, protects `main` with the shape's CI checks, and (for deployable shapes) adds the `deployable-service` topic so ArgoCD discovers it. The first word is the repo name (kebab-case), everything else is the description; flags can go anywhere.

| You want | Flag | Shape | GitOps topic |
|---|---|---|---|
| Python service (default) | *(none)* | `service-python` | yes |
| Python library | `--library` | `library-python` | no |
| Next.js web app | `--web` | `web-nextjs` | yes |
| Product GitOps repo | `--gitops` | `gitops-app` | no |
| Spring Boot service | `--type service-java` | `service-java` | yes |
| Go service | `--type service-go` | `service-go` | yes |

Other options: `--org <org>` (default: your `gh` login), `--python 3.12|3.13` (Python shapes), `--ref <tag>` (pin the platform version), `--app <org>/<gitops-app-repo>` (service shapes: writes `.platform-app.yml` so `/gitops:promote` finds the application repo).

Then, in the new repo: `cd <name> && devbox shell`, `devbox run quality && devbox run test`, `/svc:spec <first feature>` (then `/svc:plan` and `/svc:build`). Later, pull skeleton improvements with `/shared:update-service`.

## New product (end to end)

A product = one `gitops-app` repo + its services/frontend (+ libraries):

```
/shared:new-service my-saas Application repo for my-saas --gitops         # GitOps repo → my-saas
/shared:new-service my-saas-api Backend API --app ika100/my-saas          # service, linked to the app
/shared:new-service my-saas-web Frontend --web --app ika100/my-saas
# in each service repo:
/svc:spec "ping endpoint"                                                 # spec with acceptance criteria; answer, approve
/svc:plan 001 && /svc:build 001                                           # plan → failing tests → coders → QA → verify → PR
# in the my-saas repo:
/gitops:compose add my-saas-api my-saas-web                               # declare services (one PR)
/gitops:promote my-saas-api my-saas-web dev staging                       # pin staging (one PR), Argo reconciles
/app:spec "add billing" → /app:plan 003 → /app:build 003                 # product spec → criteria per repo → repos built in parallel
```

`--app` takes the full `<org>/<repo>` of the GitOps repo, which is named after the project you passed with `--gitops` (here `my-saas`, so `ika100/my-saas`).

---

## Existing repo (migration)

Use this path when you have a working repo and want to swap its in-tree `.claude/agents/` and `.claude/commands/` for the marketplace plugins.

### Step 1 — Add the marketplace reference

Edit `.claude/settings.json` to add the marketplace and enable the plugins:

```json
{
  "extraKnownMarketplaces": {
    "sdlc-foundry": {
      "source": { "source": "github", "repo": "ika100/sdlc-foundry", "ref": "main" }
    }
  },
  "enabledPlugins": {
    "svc@sdlc-foundry": true,
    "shared@sdlc-foundry": true
  }
}
```

Keep your existing `permissions` block as-is.

### Step 2 — Remove the now-duplicate in-tree definitions

```bash
git rm -r .claude/agents/ .claude/commands/ .claude/AGENTS.md
git commit -m "chore(agents): adopt sdlc-foundry marketplace, drop in-tree definitions"
```

### Step 3 — Drop the SessionStart hook from settings

The `svc` plugin ships its own SessionStart hook (`devbox run -- uv sync --all-extras`). Remove the equivalent hook from your `.claude/settings.json` to avoid duplicate runs.

### Step 4 — Smoke test

```
/shared:check-quality    # runs quality + security against your code
/svc:quick-task          # try a trivial change to confirm the full loop works
```

Both commands route through the marketplace plugins.

### Step 5 (optional) — Adopt the template for skeleton updates

**Shortcut (spec 071):** `cplat adopt --type <shape> [--data key=value]` does steps 1–5 in one commit on `chore/adopt-platform`: it renders the shape's template with answers from the repo (name and org from `origin`, the description from the README), adds only the files the repo lacks (`CLAUDE.md`, `.claude/settings.json`, CI, `docs/specs/` …, never starter code), merges `devbox.json` (your recipes win) and `.gitignore`, keeps every other file and lists those that differ from the template, and writes `.copier-answers.yml` and `.platform-version`. Then make the `devbox run` recipes fit the repo and continue with `/svc:spec`. `--dry-run` shows the plan. The manual way:

If you also want skeleton updates (CI workflow, devbox recipes, Dockerfile, CLAUDE.md) to flow from the platform template via `/shared:update-service`:

1. Pick your shape's template under `templates/` (`service-python`, `library-python`, `web-nextjs`, `gitops-app`, `service-java`, `service-go`) and create `.copier-answers.yml` at the repo root recording the answers your repo *would* have given — the questions are the top-level keys of that template's `copier.yml`. For `service-python`:

   ```yaml
   _src_path: gh:ika100/sdlc-foundry/templates/service-python
   project_name: <your-repo-name>
   module_name: <your_python_module>
   description: <one-liner>
   github_org: <your-org>
   owner_team: <your-team>
   python_version: "3.12"
   port: 8080
   needs_migrations: <true/false>
   needs_database: <none|postgres|mysql>
   needs_observability: <true/false>
   docker_registry: ghcr.io/<your-org>
   platform_marketplace_ref: main
   ```

   Only `_src_path` (its `templates/<shape>` tail drives shape detection) and the answers matter; omitted answers take the template defaults.

2. Commit that file, then run `/shared:update-service`. It works on a review branch, re-applies the template, and **overwrites skeleton files** (CI workflow, Dockerfile, k8s base except `deployment.yaml`, `CLAUDE.md`, `.claude/settings.json`, lint config). Project-owned files (`README.md`, `src/`, `app/`, `cmd/`, `internal/`, `tests/`, `docs/`, `pyproject.toml`/`pom.xml`/`go.mod`/`package.json`) are never touched; the report says when the template's README changed and how to see it. `devbox.json` is **merged** (spec 060): the template's recipes, packages and env vars win, and the ones only your repo has are kept. The report lists what was kept, and for every template recipe it replaced, your old line.

3. Review the diff. For each skeleton file where you had customisations, `git diff <file>` and either keep the template version or `git checkout -- <file>` to restore yours (then consider whether the customisation belongs in the template). Commit, push, PR.

Later runs are the same: `/shared:update-service` (optionally `--ref <platform-tag>`).

---

## Migrating a web repo (Next.js)

1. Enable `web`, `svc` and `shared` in `.claude/settings.json` (marketplace reference as in Step 1).
2. Make the repo conform to the recipe contract: add a `devbox.json` with `install`, `dev`, `test`, `test-fast`, `lint`, `lint-fix`, `typecheck`, `quality`, `audit`, `security`, `image-build`, `image-scan`, `deploy-check` wrapping your `pnpm` scripts (`templates/web-nextjs/devbox.json.jinja` is the reference). Agents never call `pnpm`/`npx` directly.
3. App Router only: if the app still uses `pages/`, migrate or keep it out of agent-driven work (ADR-004). Pin Node and the `packageManager` field (ADR-003/005).
4. Tag the repo `deployable-service`. It needs **no** Kubernetes files (v2): register it in the product's gitops-app repo with `/gitops:compose add <repo>` (use `--from-k8s` if it still has a `k8s/base`).
5. Write `.copier-answers.yml` (Step 5 above, template `templates/web-nextjs`) so shape detection does not rely on sniffing (`next.config.*` / `"next"` in `package.json`).

## Migrating a gitops-app repo

For an existing product GitOps repo (Kustomize + Argo), see *Migrating from platform v1 to v2* below; for a repo that is not on the platform yet:

1. Enable `gitops`, `app`, `svc` and `shared`.
2. Restructure to `applications/<app>/{services.yaml,applicationset.yaml,overlays/<env>/<service>/}` (ADR-014): put every component service in `services.yaml`, copy `scripts/render.py` and `scripts/plan.py` plus the `devbox.json` recipes from `templates/gitops-app`, run `devbox run render`, and review that the generated overlays reproduce your current pins (render preserves existing `newTag`/`?ref=` values).
3. Write `.copier-answers.yml` with `_src_path` ending in `templates/gitops-app` (or rely on the `applications/*/applicationset.yaml` sniff).
4. Run `scripts/render.py` (via `devbox run render`) to produce `bootstrap/<app>-root.yaml`, review it, and — once per cluster, as a human — `devbox run bootstrap` so Argo manages the ApplicationSets from git. If you already apply ApplicationSets by hand, delete that setup after the root Application is healthy.
5. In each service repo add `.platform-app.yml` (`gitops_apps: [<org>/<repo>]`) so `/gitops:promote` works from there.

## Migrating a Java or Go repo

Provide the canonical devbox recipes (`lint`, `lint-fix`, `quality`, `test`, `test-fast`, `security`, `image-build`, `image-scan`; see `templates/service-java` / `templates/service-go`), enable `svc-java` or `svc-go` plus `svc` and `shared`, tag the repo `deployable-service`, and write `.copier-answers.yml` (Step 5).

---

## Migrating from platform v1 to v2 (services no longer ship Kubernetes manifests)

v2 moves every Kubernetes manifest into the product's gitops-app repo (ADR-017). Per product, in this order:

1. **Update the gitops repo's skeleton**: in the gitops-app repo run `/shared:update-service` (new `render.py`, CI, `app.yaml`, `cluster-up` with the Gateway API) and merge the PR.
2. **Import each service**: `/gitops:compose add <service> --from-k8s --pr` reads the service's `k8s/base/deployment.yaml` (port, probes, env such as `API_URL`, replicas, resources) and **replaces its v1 entry in place** with a complete v2 entry. The environments that already run (existing `overlays/<env>/<service>/`) stay in `environments` and their image pins are preserved by the renderer, so nothing is promoted or demoted. (`render.py` rejects any v1 entry that is left, with a pointer to this command.)
3. **Expose** what should be reachable: `expose: {host: …}` on the entry; the dev hostname template is in `app.yaml`.
4. **Strip the service repos**: `/shared:update-service --migrate` in each service repo (updates the skeleton, **deletes `k8s/`**; it stays in git history). Project-owned files you customised (`pom.xml`, `src/`, …) are untouched.
5. Merge, let Argo sync. The Deployment selector (`app: <name>`) is unchanged, so running workloads update in place.

What disappears: `SERVICE_REPOS_TOKEN` (CI no longer reads other repos), Argo credentials for service repos, `deploy`/`deploy-check` recipes and the `k3d`/`kubectl`/`k9s` packages in service repos, per-service `overlays/` and PrometheusRule files (alerting is a gitops-side follow-up).

## Unattended runs

Specs, plans and builds can run without anyone at the keyboard (`claude -p`, `/loop`, `/schedule`, CI). Four things differ from an interactive session:

- **Background agents:** headless Claude Code stops background subagents after 600 s ("Background tasks still running after 600s; terminating"). `/app:build` runs its repo agents in the foreground, so it is not affected; for your own long headless runs set `CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS=0`.
- **Permissions:** nobody answers prompts, so run with `--permission-mode acceptEdits` plus the template allowlist, or `bypassPermissions` in a throwaway workspace.
- **Workspace trust:** in a workspace that was never opened interactively, Claude Code ignores the project's `permissions.allow` list but still applies its `ask` list. Open the repo once interactively (accept the trust dialog) to use the template allowlist.
- **Pull requests:** `gh pr create` is in the `ask` list on purpose. Unattended pipelines push the branch and end with the exact `gh pr create` command to run (spec 051). `/svc:ship` is the exception: `cplat ship` pushes the spec's feature branch, opens the PR and merges it after green CI itself ([ADR-028](adr/028-unattended-delivery-without-branch-protection.md)).
- **Keeping a run going:** `cplat headless "/svc:ship <NNN>"` runs `claude -p` with `--permission-mode dontAsk` (the allowlist, nothing else, no prompts) and resumes an unfinished ship run in fresh sessions; `--quiet 23:30-07:00` keeps it out of a window, for example nightly jobs that share the subscription. The guide: [unattended-delivery.md](unattended-delivery.md).

## Troubleshooting

- **`403 Forbidden` when CI pushes the image to GHCR.** The package must be linked to the repository. Generated Dockerfiles carry `org.opencontainers.image.source`, which links a new package automatically on its first push. If the package already exists without a link (created by hand or by an older template), open `https://github.com/users/<user>/packages/container/<package>/settings` (organisations: the org's package settings), choose **Manage Actions access**, add the repository with role **Write**.
- **`ImagePullBackOff` in the local cluster.** `devbox run cluster-up` creates the `ghcr-pull` secret from your `gh` login; the token needs `read:packages` (`gh auth refresh -s read:packages`, `/shared:doctor` checks it). Use `PULL_TOKEN` for a narrower token.
- **Plugins stopped updating or `/shared:doctor` says "installed from 'ika100-claude'".** The marketplace was renamed to `sdlc-foundry` in v3.0.0. Reinstall: `/plugin marketplace remove ika100-claude`, `/plugin marketplace add ika100/sdlc-foundry`, then `/plugin install <name>@sdlc-foundry` for each plugin, and restart Claude Code. In each generated repo run `/shared:update-service` so `.claude/settings.json` points at the new marketplace.
- **Something else looks like a platform bug.** Run `/shared:report-issue` (see the README).

## What you get after adoption

- Slash commands: `/svc:spec`, `/svc:plan`, `/svc:build`, `/svc:verify`, `/svc:specs`, `/svc:quick-task`, `/svc:fix-bug`, `/svc:release`, `/shared:check-quality`, `/shared:new-service`, `/shared:update-service`; in gitops-app repos also `/gitops:compose`, `/gitops:promote`, `/app:spec`, `/app:plan`, `/app:build`, `/app:specs`.
- Shape-specific agents (`coder`, `tester`, `deployment`, `observability`, `release`) from the plugin that owns your shape, plus the shape-agnostic `product-manager`, `architect`, `quality`, `security`.
- For Python repos, a SessionStart hook runs `devbox run -- uv sync --all-extras` (only when `pyproject.toml` exists); the web, Java and Go plugins run their own dependency check on session start.
- One source of truth: agent updates flow via `/plugin marketplace update`, skeleton updates flow via `/shared:update-service`. The two channels are independent.

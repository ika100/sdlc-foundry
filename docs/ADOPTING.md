# Adopting the platform

How to bring a repo onto the `ika100/sdlc-foundry` marketplace, whether it's a brand-new repo or an existing one. Already on 4.x? Go to [Migrating from 4.x to 5.0](#migrating-from-4x-to-50).

---

## New repo (happy path)

From any directory (needs `copier`, `git`, and — for the GitHub steps — `gh` logged in; missing `copier` is installed for you via `uv`, missing `gh` just means the GitHub steps are printed instead of run):

```
/component:new payments-api Stripe webhooks to Postgres
```

One command: renders the template, commits, creates a **private** GitHub repo, protects `main` with the type's CI checks, and (for deployable types) adds the `deployable-service` topic so ArgoCD discovers it. The first word is the repo name (kebab-case), everything else is the description; flags can go anywhere.

| You want | Flags | Template | GitOps topic |
|---|---|---|---|
| Python service (default) | *(none)* | `service-python` | yes |
| Python library | `--type library` | `library-python` | no |
| Next.js website | `--type website` | `web-nextjs` | yes |
| Spring Boot service | `--lang java` | `service-java` | yes |
| Go service | `--lang go` | `service-go` | yes |

`--type` is `service`, `website` or `library`; `--lang` is `python`, `java`, `go` or `typescript`. Give one and the other follows from the only valid pair; give neither and you get `service` in Python. A system's GitOps repo is created by `/system:new`, never by `/component:new`.

Other options: `--org <org>` (default: your `gh` login), `--python 3.12|3.13` (Python types), `--ref <tag>` (pin the platform version), `--system <org>/<gitops-app-repo>` (service types: writes `.platform-app.yml` so `/instance:promote` finds the system's repo).

Then, in the new repo: `cd <name> && devbox shell`, `devbox run quality && devbox run test`, `/component:spec <first feature>` (then `/component:plan` and `/component:build`). Later, pull skeleton improvements with `/platform:update`.

## New system (end to end)

A system = one `gitops-app` repo + its components (services, websites, libraries). Write a manifest and let `/system:new` create everything:

```yaml
# manifest.yaml
system: my-saas
owner: team-saas
components:
  - {name: my-saas-api, description: Backend API, type: service, lang: python}
  - {name: my-saas-web, description: Frontend, type: website, lang: typescript}
```

```
/system:new manifest.yaml                                                  # GitOps repo my-saas + one repo per component, listed in system.yaml
# in each component repo:
/component:spec "ping endpoint"                                            # spec with acceptance criteria; answer, approve
/component:plan 001 && /component:build 001                                # plan → failing tests → coders → QA → verify → PR
# in the my-saas repo:
/instance:promote my-saas-api my-saas-web --to staging                     # pin staging (one PR), Argo reconciles
/system:spec "add billing" → /system:plan 003 → /system:ship 003          # system spec → criteria per repo → repos built in parallel
```

`/component:add <name>` adds a component that already exists as a repo; `/component:set` changes its settings; `/resource:add postgres` adds the database. All of them change `applications/<system>/system.yaml` in one PR. The file is described in [DOMAIN-MODEL.md](DOMAIN-MODEL.md#one-file-per-system).

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
    "component@sdlc-foundry": true,
    "api@sdlc-foundry": true,
    "instance@sdlc-foundry": true,
    "issue@sdlc-foundry": true,
    "platform@sdlc-foundry": true,
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
/component:check    # runs quality + security against your code
/component:fix      # try a trivial change to confirm the full loop works
```

Both commands route through the marketplace plugins.

### Step 5 (optional) — Adopt the template for skeleton updates

**Shortcut (spec 071):** `cplat adopt --type <shape> [--data key=value]` does steps 1–5 in one commit on `chore/adopt-platform`: it renders the shape's template with answers from the repo (name and org from `origin`, the description from the README), adds only the files the repo lacks (`CLAUDE.md`, `.claude/settings.json`, CI, `docs/specs/` …, never starter code), merges `devbox.json` (your recipes win) and `.gitignore`, keeps every other file and lists those that differ from the template, and writes `.copier-answers.yml` and `.platform-version`. Then make the `devbox run` recipes fit the repo and continue with `/component:spec`. `--dry-run` shows the plan. The manual way:

If you also want skeleton updates (CI workflow, devbox recipes, Dockerfile, CLAUDE.md) to flow from the platform template via `/platform:update`:

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

2. Commit that file, then run `/platform:update`. It works on a review branch, re-applies the template, and **overwrites skeleton files** (CI workflow, Dockerfile, k8s base except `deployment.yaml`, `CLAUDE.md`, `.claude/settings.json`, lint config). Project-owned files (`README.md`, `src/`, `app/`, `cmd/`, `internal/`, `tests/`, `docs/`, `pyproject.toml`/`pom.xml`/`go.mod`/`package.json`) are never touched; the report says when the template's README changed and how to see it. `devbox.json` is **merged** (spec 060): the template's recipes, packages and env vars win, and the ones only your repo has are kept. The report lists what was kept, and for every template recipe it replaced, your old line.

3. Review the diff. Skeleton files stay platform-owned, so put additions where an update cannot reach them ([ADR-031](adr/031-repo-owned-companions-for-skeleton-files.md)): extra gates in the `ci-extra` recipe (`devbox run ci` and the `ci-extra` CI check run it), your own recipes in `devbox.json`, your own permission entries in `.claude/settings.json`, extra CI jobs in a workflow file of your own, and project guidance in `.claude/project-notes.md`. The update moves gates you had in `ci` into `ci-extra`, keeps your permission entries, and prints a `replaced …` line for every customisation it overwrote, with the place it belongs now. Commit, push, PR.

Later runs are the same: `/platform:update` (optionally `--ref <platform-tag>`).

---

## Migrating a website repo (Next.js)

1. Enable `component`, `instance`, `svc` and `shared` in `.claude/settings.json` (marketplace reference as in Step 1), plus the `web` plugin.
2. Make the repo conform to the recipe contract: add a `devbox.json` with `install`, `dev`, `test`, `test-fast`, `lint`, `lint-fix`, `typecheck`, `quality`, `audit`, `security`, `image-build`, `image-scan`, `deploy-check` wrapping your `pnpm` scripts (`templates/web-nextjs/devbox.json.jinja` is the reference). Agents never call `pnpm`/`npx` directly.
3. App Router only: if the app still uses `pages/`, migrate or keep it out of agent-driven work (ADR-004). Pin Node and the `packageManager` field (ADR-003/005).
4. Tag the repo `deployable-service`. It needs **no** Kubernetes files: register it in the system's gitops-app repo with `/component:add <repo> --type website --lang typescript` (use `--from-k8s` if it still has a `k8s/base`).
5. Write `.copier-answers.yml` (Step 5 above, template `templates/web-nextjs`) so shape detection does not rely on sniffing (`next.config.*` / `"next"` in `package.json`).

## Migrating a gitops-app repo

For a system's GitOps repo (Kustomize + Argo) that is not on the platform yet:

1. Enable `system`, `component`, `resource`, `instance`, `svc` and `shared`.
2. Restructure to `applications/<system>/{system.yaml,applicationset.yaml,overlays/<env>/<component>/}` (ADR-014): list every component in `system.yaml` (see [DOMAIN-MODEL.md](DOMAIN-MODEL.md#one-file-per-system)), copy `scripts/render.py` and `scripts/plan.py` plus the `devbox.json` recipes from `templates/gitops-app`, run `devbox run render`, and review that the generated overlays reproduce your current pins (render preserves existing `newTag`/`?ref=` values).
3. Write `.copier-answers.yml` with `_src_path` ending in `templates/gitops-app` (or rely on the `applications/*/applicationset.yaml` sniff).
4. Run `scripts/render.py` (via `devbox run render`) to produce `bootstrap/<system>-root.yaml`, review it, and — once per cluster, as a human — `devbox run bootstrap` so Argo manages the ApplicationSets from git. If you already apply ApplicationSets by hand, delete that setup after the root Application is healthy.
5. In each component repo add `.platform-app.yml` (`gitops_apps: [<org>/<repo>]`) so `/instance:promote` works from there.

## Migrating a Java or Go repo

Provide the canonical devbox recipes (`lint`, `lint-fix`, `quality`, `test`, `test-fast`, `security`, `image-build`, `image-scan`; see `templates/service-java` / `templates/service-go`), enable `svc-java` or `svc-go` plus `component`, `svc` and `shared`, tag the repo `deployable-service`, and write `.copier-answers.yml` (Step 5).

---

## Migrating from 4.x to 5.0

5.0 renames every command after the thing it acts on (`/component:ship` instead of `/svc:ship`), replaces `app.yaml` and `services.yaml` of a system by one file, `system.yaml`, and splits the plugins by noun. The old command names stay for one release as tombstones: they run nothing and name the new command. The full old-to-new table is in [CHANGELOG.md](CHANGELOG.md).

**One command per repo.** In each repo (a system's GitOps repo or a component repo), update the platform and run:

```
cplat platform update --migrate        # or /platform:update --migrate
```

It works on a review branch and ends in one commit. For a system repo it:

1. converts `app.yaml` and `services.yaml` into `system.yaml` (owner from `.copier-answers.yml` or the `origin` remote), writes it, and deletes the two old files. The comments of the old files are not carried over;
2. updates the template files and `devbox.json` as `/platform:update` always does;
3. renders again with the 5.0 renderer and compares the result with what the frozen 4.7 renderer produced from the old files before anything changed. **The two must be byte-identical.** The report prints the number of files compared. Any difference restores the tree, deletes the branch, lists the differing files and exits 1: nothing is changed, and you can report it with `/issue:report`;
4. switches the plugins in `.claude/settings.json`: adds the noun plugins, removes `app@sdlc-foundry` and `gitops@sdlc-foundry`, and keeps every entry of yours.

A component repo only gets steps 2 and 4. `cplat platform update --migrate --dry-run` prints the whole plan and the new `system.yaml` and changes nothing. On an already migrated repo `--migrate` just runs the normal update and says `already migrated`. Without `--migrate`, the update refuses on a 4.x repo, and the renderer says `not migrated to 5.0`.

**Many repos.** `/platform:fleet update` does the same across all your repos: it runs `--migrate` where a repo is below 5.0, opens one PR per repo, and merges it on green CI when the proof above held (for a system repo) or for a component repo. A repo that failed is listed with the first line of the error and gets no PR.

**Keys that cannot be converted.** A key without a place in `system.yaml` stops the migration before anything changes, with one line per key (`app.yaml: addons.redis (...)`). Fix it by hand and run the command again:

- `owner` missing: there is no `github_org` answer and no `origin` remote; add the owner to `.copier-answers.yml` or set the remote.
- Add-ons other than `postgres` and `observability`, other top-level keys, unknown environment names, and per-environment values for an environment the service does not run in: remove them or move them into the service's own package; 5.0 supports one database resource named `postgres`.
- A `version` of the database that differs by environment: pick one.
- A service entry from before v2 without `port` or `probes`: complete it, or import it with `/component:add <name> --from-k8s`.

Host templates change their placeholders: `{service}` is `{component}` and `{app}` is `{system}`.

**The plugin switch.** After the migration, install the new plugins (`/plugin marketplace update`, then `/plugin install system@sdlc-foundry` and the other noun plugins) and restart Claude Code. `app@sdlc-foundry` and `gitops@sdlc-foundry` still load, but hold only tombstones and are removed in 6.0. `/platform:doctor` warns while a repo still has the old files or the old plugins and prints `cplat platform update --migrate` as the fix.

---

## Unattended runs

Specs, plans and builds can run without anyone at the keyboard (`claude -p`, `/loop`, `/schedule`, CI). Four things differ from an interactive session:

- **Background agents:** headless Claude Code stops background subagents after 600 s ("Background tasks still running after 600s; terminating"). `/system:ship` runs its repo agents in the foreground, so it is not affected; for your own long headless runs set `CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS=0`.
- **Permissions:** nobody answers prompts, so run with `--permission-mode acceptEdits` plus the template allowlist, or `bypassPermissions` in a throwaway workspace.
- **Workspace trust:** in a workspace that was never opened interactively, Claude Code ignores the project's `permissions.allow` list but still applies its `ask` list. Open the repo once interactively (accept the trust dialog) to use the template allowlist.
- **Pull requests:** `gh pr create` is in the `ask` list on purpose. Unattended pipelines push the branch and end with the exact `gh pr create` command to run (spec 051). `/component:ship` is the exception: `cplat component ship` pushes the spec's feature branch, opens the PR and merges it after green CI itself ([ADR-028](adr/028-unattended-delivery-without-branch-protection.md)).
- **Keeping a run going:** `cplat headless "/component:ship <NNN>"` runs `claude -p` with `--permission-mode acceptEdits` (edits inside the repo, otherwise the allowlist, nothing else, no prompts) and resumes an unfinished ship run in fresh sessions; `--quiet 23:30-07:00` keeps it out of a window, for example nightly jobs that share the subscription. The guide: [unattended-delivery.md](unattended-delivery.md).

## Troubleshooting

- **`403 Forbidden` when CI pushes the image to GHCR.** The package must be linked to the repository. Generated Dockerfiles carry `org.opencontainers.image.source`, which links a new package automatically on its first push. If the package already exists without a link (created by hand or by an older template), open `https://github.com/users/<user>/packages/container/<package>/settings` (organisations: the org's package settings), choose **Manage Actions access**, add the repository with role **Write**.
- **`ImagePullBackOff` in the local cluster.** `devbox run cluster-up` creates the `ghcr-pull` secret from your `gh` login; the token needs `read:packages` (`gh auth refresh -s read:packages`, `/platform:doctor` checks it). Use `PULL_TOKEN` for a narrower token.
- **Plugins stopped updating or `/platform:doctor` says "installed from 'ika100-claude'".** The marketplace was renamed to `sdlc-foundry` in v3.0.0. Reinstall: `/plugin marketplace remove ika100-claude`, `/plugin marketplace add ika100/sdlc-foundry`, then `/plugin install <name>@sdlc-foundry` for each plugin, and restart Claude Code. In each generated repo run `/platform:update` so `.claude/settings.json` points at the new marketplace.
- **Something else looks like a platform bug.** Run `/issue:report` (see the README).

## What you get after adoption

- Slash commands by noun: `/component:spec`, `/component:plan`, `/component:build`, `/component:verify`, `/component:check`, `/component:fix`, `/component:release`, `/component:ship`, `/component:new`, `/api:list`, `/instance:promote`, `/instance:secret`, `/instance:verify`, `/issue:triage`, `/issue:report`, `/platform:doctor`, `/platform:update`, `/platform:fleet`, `/platform:runs`, `/platform:retro`; in gitops-app repos also `/system:new`, `/system:status`, `/system:spec`, `/system:plan`, `/system:ship`, `/component:add`, `/component:set`, `/component:remove`, `/resource:add`, `/resource:remove`.
- Shape-specific agents (`coder`, `tester`, `deployment`, `observability`, `release`) from the plugin that owns your shape, plus the shape-agnostic `product-manager`, `architect`, `quality`, `security`.
- For Python repos, a SessionStart hook runs `devbox run -- uv sync --all-extras` (only when `pyproject.toml` exists); the web, Java and Go plugins run their own dependency check on session start.
- One source of truth: agent updates flow via `/plugin marketplace update`, skeleton updates flow via `/platform:update`. The two channels are independent.

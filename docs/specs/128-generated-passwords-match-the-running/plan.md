---
spec_id: 128-generated-passwords-match-the-running
shape: platform
spec_hash: 15cffde7a6e2
summary: "Every generated credential (cache password, broker user passwords, bucket keys, component generate: secrets) is written once by a create-only credentials Job per owner (Argo CD PreSync hook, plain Job without Argo CD; Python stdlib program embedded in render.py, pinned python image in the versions table) instead of a generator-backed ExternalSecret; the Job adopts 5.4 Secrets (orphan-deletes the old ExternalSecret, strips tracking metadata), and restarts a cache or broker server that refuses its Secret's password; /platform:update lists one credentials row per resource type; the migration proof ignores credential writers; run.sh and upgrade.sh apply the hooks first, check AC-128.1-.8 and lose settle_cache; ADR-072 (exception to ADR-018, amends 064/065/059/018), CHANGELOG Fixed entry"
tasks:
  - id: t1
    title: credentials Job core (CREDENTIALS_IMAGE, CREDENTIALS_SCRIPT, credentials_files) and the cache renders it instead of ExternalSecret + Password generator
    files: [templates/gitops-app/scripts/render.py, templates/cluster-gitops/scripts/system_render.py, scripts/check-pins.py, tests/cplat/cache_fixtures.py, tests/cplat/test_cache_118.py, tests/cplat/test_cache_url_127.py, tests/cplat/upgrade_fixtures.py, tests/cplat/test_upgrade_121.py, tests/cplat/test_scale_120.py]
    covers: [AC-128.1, AC-128.2, AC-128.3, AC-128.10, AC-128.12]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t7
    title: ADR-072 (cause of #316, the create-only credentials Job, exception to ADR-018 with its rights) and the amendments of ADR-018, 059, 064, 065
    files: [docs/adr/072-a-generated-credential-is-written-once-by-a-create-only-job.md, docs/adr/018-secrets-with-external-secrets-operator.md, docs/adr/059-in-cluster-buckets-on-seaweedfs-per-instance.md, docs/adr/064-a-cache-is-a-platform-rendered-valkey-statefulset.md, docs/adr/065-a-broker-is-nats-jetstream-with-declared-streams-and-per-component-users.md, docs/adr/README.md]
    covers: [AC-128.13]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t2
    title: broker and bucket render the credentials Job (nack and component users with verify, bucket keys with backup labels); stale rules and sync retry for their addon directories
    files: [templates/gitops-app/scripts/render.py, templates/cluster-gitops/scripts/system_render.py, tests/cplat/broker_fixtures.py, tests/cplat/test_broker_119.py, tests/cplat/test_bucket_116.py, tests/cplat/test_backup_117.py, tests/cplat/test_scale_120.py, tests/cplat/test_cache_118.py, tests/cplat/test_upgrade_121.py]
    covers: [AC-128.4, AC-128.5, AC-128.6, AC-128.7, AC-128.10, AC-128.12]
    parallel_safe: true
    depends_on: [t1]
    done: true
  - id: t8
    title: CHANGELOG Fixed entry (#316) with the Versions row, user docs and /component:add wording, component plugin 1.5.2
    files: [docs/CHANGELOG.md, docs/USER-JOURNEY.md, docs/HOW-IT-WORKS.md, docs/DOMAIN-MODEL.md, plugins/component/commands/add.md, plugins/component/.claude-plugin/plugin.json, .claude-plugin/marketplace.json]
    covers: [AC-128.14]
    parallel_safe: true
    depends_on: [t1]
  - id: t3
    title: component generate secrets render the credentials Job; the 4.x migration proof ignores credential writers
    files: [templates/gitops-app/scripts/render.py, templates/cluster-gitops/scripts/system_render.py, scripts/cplat/update.py, tests/cplat/test_gitops.py, tests/cplat/resources_fixtures.py, tests/cplat/test_resources_115.py, tests/cplat/test_resources_115_cmds.py, tests/cplat/test_scale_120.py, tests/cplat/test_cache_118.py, tests/cplat/test_broker_119.py, tests/cplat/test_upgrade_121.py, tests/cplat/test_system_render_114.py]
    covers: [AC-128.8, AC-128.12]
    parallel_safe: true
    depends_on: [t2]
  - id: t4
    title: /platform:update lists one credentials row per resource type and reads the cache url from the plan
    files: [scripts/cplat/update.py, tests/cplat/test_update_127.py]
    covers: [AC-128.9]
    parallel_safe: true
    depends_on: [t3]
  - id: t5
    title: e2e run.sh applies the credentials hooks first and checks AC-128.1-.8 (forced re-run instead of force-sync, broker user added, bucket, generated secret across replicas)
    files: [tests/e2e/run.sh, tests/cplat/test_cache_118_cmds.py, tests/cplat/test_bucket_116_cmds.py, tests/cplat/test_broker_119_cmds.py]
    covers: [AC-128.1, AC-128.2, AC-128.3, AC-128.4, AC-128.5, AC-128.6, AC-128.7, AC-128.8, AC-128.11]
    parallel_safe: true
    depends_on: [t3]
  - id: t6
    title: e2e upgrade.sh without settle_cache — both render forms applied, a forced #316 state repaired after the update, Secrets kept, AC-128.1/.2/.3/.4 per environment
    files: [tests/e2e/upgrade.sh]
    covers: [AC-128.1, AC-128.2, AC-128.3, AC-128.4, AC-128.9, AC-128.10, AC-128.11]
    parallel_safe: true
    depends_on: [t3]
human_steps:
  - "After the release, run /platform:update on one real system that Argo CD syncs (a cache, a broker or a bucket in dev) and confirm the addon application syncs with its PreSync credentials Job and keeps its Secrets: no CI run exercises Argo CD hooks (both e2e scripts run without Argo CD)."
---

# Plan — 128 Generated passwords match the running server

Design: [design.md](design.md) (the contract: rendered files, Role, Job, `plan.json`, `create.py` steps, change-list rows,
e2e harness). Four levels: t1 ‖ t7 → t2 ‖ t8 → t3 → t4 ‖ t5 ‖ t6. t1, t2 and t3 all change `render.py` (and its synced copy),
so they run in order; each leaves the suite green.

Every task that edits `render.py` ends with `uv run scripts/sync-template-copies.py` (and `--check`). Frozen-digest tests
(`test_scale_120.BEFORE_120`, `test_cache_118.py:735`, `test_broker_119.py:1177`) change only for fixtures that have the owner
type a task moves; update their digests/counts with a `# spec 128: credentials Job instead of generator ExternalSecrets`
comment, never their fixtures. The 5.0-render comparisons of spec 115 use t3's helper instead.

## t1 — credentials Job core and the cache

**Files:** templates/gitops-app/scripts/render.py, templates/cluster-gitops/scripts/system_render.py, scripts/check-pins.py, tests/cplat/cache_fixtures.py, tests/cplat/test_cache_118.py, tests/cplat/test_cache_url_127.py, tests/cplat/upgrade_fixtures.py, tests/cplat/test_upgrade_121.py, tests/cplat/test_scale_120.py
**Covers:** AC-128.1, AC-128.2, AC-128.3, AC-128.10, AC-128.12
**Goal:** a cache instance's Secret `<system>-<name>-app` is written once by its credentials Job, which also adopts a 5.4 Secret and restarts a Valkey server that refuses the Secret's password.

**Implementation notes:**
- `CREDENTIALS_IMAGE`: the current `python:3.13.<patch>-alpine<ver>` tag with its digest (resolve with `docker buildx imagetools inspect python:3.13-alpine` or the registry API); a `versions_table()` row `image_row("credentials-job", None, None, None, CREDENTIALS_IMAGE)` after `velero-plugin-for-aws`; `check-pins.py` line 101 lists it; `upgrade_fixtures.ROW_ORDER` and `test_upgrade_121.py:110` get the row.
- `CREDENTIALS_SCRIPT`: the `create.py` of the design's "create.py behaviour", stdlib only (`json`, `base64`, `secrets`, `ssl`, `socket`, `urllib.request`, `time`, `sys`, `os`), steps 1–5 exactly, log lines verbatim, no value ever printed. Keep it a plain module-level string literal (no f-string), so the rendered `create.py` equals it.
- `credentials_files(app, env, owner, labels, plan) -> dict[str, dict]`: the five files of the design (names, annotations, Role rules built from `plan`, Job spec, hash name `<owner[:42].rstrip('-')>-credentials-<h8>`, `plan.json` = `json.dumps(plan, indent=2, sort_keys=True)`).
- `cache_files()`: drop `password-generator.yaml` and `externalsecret.yaml`; add `credentials_files()` with the cache row of the design's plan table (`url` keeps `redis://default:{{ .password }}@…`, so spec 127's renderer-text check still holds); `kustomization.yaml` `resources: sorted(files)`. StatefulSet and Service unchanged. Update the docstring.
- `stale_paths()`: in addon directories also drop `externalsecret.yaml`, `password-generator.yaml`, `access-key-generator.yaml`, `secret-key-generator.yaml`, `nack-secret.yaml` and `credentials-*.yaml` that are not wanted (extend the existing addon rule next to `BROKER_STALE`; a database directory never has them).
- `render_app()`: the addons ApplicationSet of an environment gets `retry: RETRY` when its group contains a cache (extend the `elif` that sets it for brokers to `type in ("cache", "broker", "bucket")`).
- Regression tests amended to the new contract: `cache_fixtures.FILES`, `expected_generator`/`expected_externalsecret` replaced by an `expected_plan(env, name)` for the ConfigMap's `plan.json`; `test_cache_118.py` (files, Secret contract read from the plan, wave assertions on the gone ExternalSecret); `test_cache_url_127.py` reads `data.url` from the plan and its "only the url changes" test compares the plan's cache Secret entry; frozen digests for the `cache` label.

**Done when:** the acceptance tests for AC-128.1, .2, .3, .10 and .12 that concern the cache pass (rendered objects, `create.py` against a fake API: create, keep, adopt, add-missing-key, verify/restart), `python3 scripts/check-pins.py`, `uv run scripts/sync-template-copies.py --check` and `devbox run test-fast` pass.

## t7 — ADR-072 and the amended ADRs

**Files:** docs/adr/072-a-generated-credential-is-written-once-by-a-create-only-job.md, docs/adr/018-secrets-with-external-secrets-operator.md, docs/adr/059-in-cluster-buckets-on-seaweedfs-per-instance.md, docs/adr/064-a-cache-is-a-platform-rendered-valkey-statefulset.md, docs/adr/065-a-broker-is-nats-jetstream-with-declared-streams-and-per-component-users.md, docs/adr/README.md
**Covers:** AC-128.13
**Goal:** one ADR records why #316 happened, the chosen mechanism, and that it is an exception to ADR-018 with exactly the rights the creator holds.

**Implementation notes:**
- Cause: read External Secrets **v2.12.0** `pkg/controllers/externalsecret/externalsecret_controller.go` (`shouldRefresh`, the target-Secret validity check, which client the reconcile reads the target Secret with) and search the upstream issues for a second write under `CreatedOnce` / generators; record the finding with file and function names, the issue link or "no upstream issue found", and a fixed version or "none known". Start from the design's working hypothesis; state clearly if it stays a hypothesis.
- Decision (MADR: Status, Context, Decision, Consequences, Not included, like ADR-064): the credentials Job per owner, PreSync hook / plain Job, create-if-absent with the add-missing-key and metadata patches under a `resourceVersion` test, adoption order, the one-time repair, the image row; the Role rules verbatim from the design; why ESO `CreatedOnce`, PushSecret, Kyverno `generate` and init containers were rejected.
- Exception to ADR-018: generated credentials no longer come from External Secrets; `remote:` secrets and external resources still do; values stay out of git. Consequences: deleting the Secret regenerates; Secrets and hook objects outlive their declaration; no CI run exercises Argo CD hooks.
- Amend in place with an `**Amended by:** [ADR-072](…)` line and a rewritten point: ADR-064 decision 3, ADR-065 decision 4 (and its "generated once by External Secrets Operator" wording), ADR-059 decision 3 (plus the Consequence "In-cluster buckets need External Secrets Operator"), ADR-018 decision 2 `generate`.
- `docs/adr/README.md`: the 072 row; the 018, 059, 064 and 065 rows say how the credential is written now.

**Done when:** the acceptance tests for AC-128.13 pass and `uv run scripts/shapes.py check` passes (ADR index).

## t2 — broker and bucket

**Files:** templates/gitops-app/scripts/render.py, templates/cluster-gitops/scripts/system_render.py, tests/cplat/broker_fixtures.py, tests/cplat/test_broker_119.py, tests/cplat/test_bucket_116.py, tests/cplat/test_backup_117.py, tests/cplat/test_scale_120.py, tests/cplat/test_cache_118.py, tests/cplat/test_upgrade_121.py
**Covers:** AC-128.4, AC-128.5, AC-128.6, AC-128.7, AC-128.10, AC-128.12
**Goal:** the broker's `_nack` and component users and the bucket's keys are written once by their credentials Jobs; a NATS server that refuses a configured user's password is restarted once.

**Implementation notes:**
- `broker_files()`: drop `password-generator.yaml`, `nack-secret.yaml` and every `externalsecret-<c>.yaml`; `credentials_files()` with the broker row of the plan table (`<n>-nack`, then one `<n>-<c>-app` per user in `users` order; verify pods `<n>-0 … <n>-<replicas-1>`; env names `ADMIN_PASSWORD` and `USER_<C>_PASSWORD` exactly as `cenv` builds them). `server.yaml`, `account.yaml`, streams and consumers unchanged.
- `bucket_files()`: drop both generators and `externalsecret.yaml`; `credentials_files()` with the bucket row; labels `backup_target_labels(app, name)` only when `target` (as the ExternalSecret template did); `S3Credentials` and the rest unchanged. Update both docstrings.
- The addons ApplicationSet retry rule from t1 already includes buckets; check the broker case still sets it once.
- Regression tests: `broker_fixtures` expectations and file lists, `test_broker_119.py` (Secret contract from the plan, waves of the gone ExternalSecrets), `test_bucket_116.py` (files, keys, sync-wave order now: hook objects, then the rest), `test_backup_117.py:631-634` (the backup labels are on the plan's Secret entry of the target bucket, absent on the other); frozen digests for `db-bucket`, `broker`, `broker-wide`, `events*` and any non-cache system with a bucket in `test_cache_118.py:735`.

**Done when:** the acceptance tests for AC-128.4 to .7, .10 and .12 that concern the broker and the bucket pass, `uv run scripts/sync-template-copies.py --check` and `devbox run test-fast` pass.

## t8 — CHANGELOG, docs, component plugin

**Files:** docs/CHANGELOG.md, docs/USER-JOURNEY.md, docs/HOW-IT-WORKS.md, docs/DOMAIN-MODEL.md, plugins/component/commands/add.md, plugins/component/.claude-plugin/plugin.json, .claude-plugin/marketplace.json
**Covers:** AC-128.14
**Goal:** the release notes and the guides say how a generated credential is written now and that existing systems need nothing.

**Implementation notes:**
- `docs/CHANGELOG.md` `[Unreleased]`: a `### Fixed` heading with one paragraph: #316; symptom (`WRONGPASS` from a cache, an authorization error from a broker, until the server restarts; also bucket keys and `generate:` values that a forced refresh rewrote); affected: in-cluster caches (5.4.0, spec 118), brokers (5.4.0, spec 119), buckets (since spec 116) and `generate:` secrets of components (all releases with ADR-018); the fix (a credentials Job per owner creates each Secret if absent and keeps an existing one; a server that refuses its Secret's password restarts once; ADR-072); what to do: nothing — `/platform:update` and the next sync keep every existing password and key (the change list says so per resource type). Link spec 128 and ADR-072.
- A `**Versions**` line for the new row (`credentials-job` <tag> (new)), format as in the 5.4.0 section (`cplat platform versions --diff v5.4.0 --changelog`).
- `docs/USER-JOURNEY.md:223`, `docs/HOW-IT-WORKS.md:117`, `docs/DOMAIN-MODEL.md:181`, `plugins/component/commands/add.md:21`: replace "External Secrets Operator creates/generates … once" by the credentials Job wording (created in the cluster once per environment by the platform's credentials Job; deleting the Secret makes a new value on the next sync); `remote:` still comes from the secret store. Before editing, grep `tests/cplat` for each file name and keep every phrase a test looks for.
- `component` plugin 1.5.1 → 1.5.2 in `plugin.json` and `marketplace.json`; add `component` 1.5.2 to a `**Plugins:**` line of `[Unreleased]`.

**Done when:** the acceptance tests for AC-128.14 pass, `devbox run validate` passes (marketplace), and the link check in `scripts/` passes for the edited docs.

## t3 — component generate secrets and the migration proof

**Files:** templates/gitops-app/scripts/render.py, templates/cluster-gitops/scripts/system_render.py, scripts/cplat/update.py, tests/cplat/test_gitops.py, tests/cplat/resources_fixtures.py, tests/cplat/test_resources_115.py, tests/cplat/test_resources_115_cmds.py, tests/cplat/test_scale_120.py, tests/cplat/test_cache_118.py, tests/cplat/test_broker_119.py, tests/cplat/test_upgrade_121.py, tests/cplat/test_system_render_114.py
**Covers:** AC-128.8, AC-128.12
**Goal:** every replica of a component reads the same generated values, written once by the component's credentials Job; 4.x repos with `generate:` secrets still migrate.

**Implementation notes:**
- `secret_manifests()`: a `generate:` secret no longer renders an ExternalSecret; the component's `password-generator.yaml` goes; one `credentials_files()` per component with all its `generate:` secrets (component row of the plan table, `length` per secret, default 32). `remote:` secrets unchanged. The Deployment's `envFrom` is unchanged.
- `MANAGED_PREFIXES` gains `"credentials-"`, so a component that drops its last `generate:` secret loses the five files.
- `render_app()`: the component ApplicationSet of an environment gets `retry: RETRY` when a component running there has a `generate:` secret (keep the KEDA case as it is).
- `update.py` migration proof: a helper `_without_credential_writers(tree)` as in the design's "Migration proof" (drop `password-generator.yaml`, `credentials-*.yaml` and generator-backed `externalsecret-*.yaml`; filter those names from the same directory's `kustomization.yaml` `resources`, compared parsed) applied to `reference` and `after` in `apply_systems()`.
- `resources_fixtures.normalized`/`unpin` users: the 5.0-render comparison in `test_resources_115.py` and the migration test in `test_resources_115_cmds.py:432` apply the same helper (import it from `update`), so `full5`/`rich5` still prove "nothing else changed".
- Regression tests: `test_gitops.py:322-353` (generate renders the five credentials files and the plan's keys and length; the remote ExternalSecret stays; removing the secrets removes the files); `test_system_render_114.py` where it asserts a generated ExternalSecret; frozen digests for `full5`, `rich5` and every fixture with a `generate:` secret.

**Done when:** the acceptance tests for AC-128.8 and the component part of AC-128.12 pass, the spec 114/115 migration tests pass, `uv run scripts/sync-template-copies.py --check` and `devbox run test-fast` pass.

## t4 — the update's change list

**Files:** scripts/cplat/update.py, tests/cplat/test_update_127.py
**Covers:** AC-128.9
**Goal:** `/platform:update` of a 5.4 gitops repo names per resource type what changed in the rendered objects and says that existing passwords and keys are kept.

**Implementation notes:**
- `render_and_compare()`: before and after `gitops.render`, collect per `(system, owner, env)` the writer form (`generator` / `job`) from the files as the design describes (addon type by `statefulset.yaml` / `server.yaml` / `seaweed.yaml`; overlays are components); append one `credentials` row per type (cache, broker, bucket, component order) after the operator rows, keys and `text` exactly as the design's table. Return `versions` also when these are the only rows.
- `_cache_url()`: read `data.url` of Secret `<system>-<name>-app` from `addons/<env>/<name>/credentials-configmap.yaml` (`plan.json`), fall back to `externalsecret.yaml`; the `{{ .password }}` → `<password>` mapping stays.
- `test_update_127.py` (spec 127's tests, amended because the 5.4 ExternalSecret is no longer rendered): `make_repo` writes the 5.3/5.4-form `externalsecret.yaml` and `password-generator.yaml` of each cache itself after the render (from a fixture of the old form) and drops the credentials files, so the update sees a 5.4 tree; the url-row tests filter `kind == "url"`; the "every line keeps its url" test checks url rows only; the count test expects url rows plus one credentials row; the "re-render writes the new form" test reads the plan's url.

**Done when:** the acceptance tests for AC-128.9 (change list) pass, the amended spec 127 tests and the spec 121 update tests pass, `devbox run test-fast` passes.

## t5 — e2e run.sh

**Files:** tests/e2e/run.sh, tests/cplat/test_cache_118_cmds.py, tests/cplat/test_bucket_116_cmds.py, tests/cplat/test_broker_119_cmds.py
**Covers:** AC-128.1, AC-128.2, AC-128.3, AC-128.4, AC-128.5, AC-128.6, AC-128.7, AC-128.8, AC-128.11
**Goal:** the e2e cluster test applies what Argo CD would (credentials hooks first) and proves the AC-128 behaviour in every environment where it creates a cache, broker, bucket or generated secret, without restarting a server to make passwords match.

**Implementation notes:**
- One helper `apply_with_credentials <ns> <dir>` (design's "e2e harness"): the five `credentials-*.yaml`, wait for the Job (logs on failure), then `apply -k`; and `rerun_credentials <ns> <dir>` (delete the finished Job, apply the five files again, wait). Use them for the overlays (line 328 loop), `apply_bucket` (293–309, replacing the generator/ExternalSecret step), the caches (677–689) and the broker (`apply_py` 944–977: the first file holds the credentials objects; wait for the Job instead of the ExternalSecrets).
- Cache (AC-128.1/.2/.3), right after the caches are ready and before the AC-118.7 pod deletion: 60 s after Ready, a probe pod with e2e-web's variables gets `PONG` with `SESSIONS_REDIS_URL` and with `-h/-p/-a` from `SESSIONS_REDIS_HOST/PORT/PASSWORD` (same for ratelimit), and `WRONGPASS` with a wrong password; then `rerun_credentials` and `kc apply -k` again: `resourceVersion` and password hash of both Secrets unchanged and the probe still `PONG`. This replaces the `force-sync` lines 818–821; keep `NOAUTH`/`WRONGPASS`/`PONG`.
- Generated secret (AC-128.8), lines 353–364: scale `e2e-api` to 2 replicas, wait 60 s after the Secret exists, compare the sha256 of `DB_PASSWORD`/`JWT_KEY` in each pod (`kc exec … printenv`, hashes only) with the Secret's; `rerun_credentials` instead of the `force-sync` annotation (values and `resourceVersion` unchanged); scale back.
- Bucket (AC-128.7), at 500–515: 60 s after the Secret exists the existing put/get probes pass; `rerun_credentials` instead of only `apply -k`; keys unchanged.
- Broker (AC-128.4/.6): after the server is ready + 60 s, `_nack` (Account Ready) and each component user (`nats` probe with its `NATS_URL/USER/PASSWORD`) authenticate; `rerun_credentials` keeps every password. AC-128.5 in the spec 120 section that adds `e2e-worker` (~1410–1430): within 60 s of the server being ready again, `e2e-worker` and the existing users connect.
- Removal sections (~1781–1790, ~1841–1856): no ExternalSecret or Password generator exists any more; delete the user Secrets and the `<owner>-credentials` hook objects as a person would, and assert none of `externalsecrets.external-secrets.io` / `passwords.generators.external-secrets.io` names the broker (keeps spec 119's needles meaningful).
- Needle tests: `test_cache_118_cmds.py:447` (no `force-sync` on a cache; needles for the re-run and `resourceVersion`), `test_bucket_116_cmds.py:483` (the bucket is applied credentials first: `credentials-job.yaml` and `credentials.yaml`), `test_broker_119_cmds.py:781` as far as the removal step changes.

**Done when:** the acceptance tests for AC-128.11 (run.sh part) pass, `bash -n tests/e2e/run.sh` and `devbox run test-fast` pass; at ship, the e2e workflow (`e2e.yml`) is green in 3 runs in a row on the PR's head (rerun twice with `gh run rerun`).

## t6 — e2e upgrade.sh

**Files:** tests/e2e/upgrade.sh
**Covers:** AC-128.1, AC-128.2, AC-128.3, AC-128.4, AC-128.9, AC-128.10, AC-128.11
**Goal:** the upgrade from 5.4 proves that existing Secrets are kept, a #316 instance is repaired within 60 s, and every environment meets AC-128.1–.4 after the update — with `settle_cache` gone.

**Implementation notes:**
- Delete `settle_cache` (417–430) and its call (442). `apply_addons`, `apply_bucket`, `apply_bus`: a directory with `credentials-job.yaml` is applied credentials first (same helper as t5, its own copy in this script); a directory of the previous release keeps today's path. `diagnose()`: print the credentials Job's logs and the Secret/server hashes; no ExternalSecret needed.
- Setup on the previous release: the cache key in `write_data` is written with the server's own password (`kubectl exec upg-sessions-0 -- valkey-cli -a "$VALKEY_PASSWORD"`), so a 5.4 instance already in the #316 state cannot fail the setup; the component-path checks run after the update.
- Give `upg-api` a generated secret in setup (`ns.generate = ["upg-api-auth=JWT_KEY"]`) so AC-128.9 covers component secrets.
- Before the update, force the #316 state: staging's cache (a new random password into `password` and the `url` of `upg-sessions-app` with `kubectl patch`, value never printed) and prod's broker (a new `password` in `upg-bus-upg-api-app`); then `rollout restart deployments.apps/upg-api` in those two environments (a component, not a server: in #316 the components started after the rewrite and hold the Secret's value). Record the sha256 hashes of every planned Secret of an environment immediately before the new render is applied there (not right after forcing; nothing waits for a Secret to settle).
- After `apply_addons` of each environment with the new render: every Secret hash equals the recorded one (AC-128.9); within 60 s the server accepts the Secret's password, checked with fresh probe pods (`podmust`) that take the component's variables: `PONG` with `REDIS_URL` and with `REDIS_HOST/PORT/PASSWORD`, `nats` connects with `NATS_URL/USER/PASSWORD` for every component user, `_nack`'s Account Ready (AC-128.10, AC-128.1/.2/.4); one forced write of the cache Secret (re-run the credentials Job) leaves `resourceVersion` and hash unchanged (AC-128.3).
- No `rollout restart` of a cache or broker server and no wait for a Secret to settle anywhere in the script; keep the `s#^redis://:#redis://default:#` rewrite (spec 127 test) for older previous releases.

**Done when:** the acceptance tests for AC-128.11 (upgrade.sh part) pass, `bash -n tests/e2e/upgrade.sh` and `devbox run test-fast` pass; at ship, `e2e-upgrade.yml` (previous release v5.4.x → candidate) is green in 3 runs in a row.

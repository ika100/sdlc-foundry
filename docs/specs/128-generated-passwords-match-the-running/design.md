# Design — 128 Generated passwords match the running server

One mechanism replaces every generator-backed `ExternalSecret` the renderer writes: a **credentials Job** per owner (a cache,
broker or bucket instance, or a component with `generate:` secrets) that creates each Secret if it is absent and otherwise
keeps it. The same Job adopts the Secrets External Secrets wrote in 5.4 (AC-128.9) and restarts a cache or broker server that
runs a password its Secret does not hold (AC-128.10). ADR-072 records it as an exception to ADR-018.

## Decisions

- **A create-only Job in the owner's namespace writes each generated credential** (AC-128.1 to AC-128.8, AC-128.12). The Job
  POSTs the complete Secret; the API server answers `201` (written now) or `409 AlreadyExists` (kept, never rewritten).
  Kubernetes makes the create atomic, so two runs, two syncs or two replicas cannot write a credential twice. The Job has no
  `update` right on Secrets at all; its only other write to a Secret is a JSON patch guarded by a `test` of the
  `resourceVersion` that changes metadata or *adds* a key that is missing (a key added to `generate:`), never replaces or
  removes a data key. Rejected:
  - *ESO with `refreshPolicy: CreatedOnce`* is the 5.4 form that fails (#316); a forced refresh of the bucket's and the
    components' ExternalSecrets (default refresh policy) regenerates by design.
  - *ESO `PushSecret`* needs a source Secret that someone already wrote; it moves the problem.
  - *A Kyverno `generate` rule*: Kyverno is optional (environments with `policy: Off`, clusters without it) and the e2e
    runs one environment without enforcement.
  - *An init container in the server or component pod*: it runs only when a pod starts, so it cannot adopt a 5.4 Secret before
    Argo CD prunes the old ExternalSecret of a component (the prune would garbage-collect the owned Secret); the bucket has no
    pod of ours and the NATS pod comes from a chart; it would also put a Secret-writing token into long-running pods.
  - *Servers that follow the Secret* (mounted file, `CONFIG SET`): excluded by the non-goals.
- **The Job is an Argo CD `PreSync` hook, and a plain Job without Argo CD.** Under Argo CD every sync runs it before any object
  is applied or pruned, so the Secrets exist before the StatefulSet, the chart, the S3Credentials or the Deployment read them,
  and the 5.4 ExternalSecret is gone before the Sync phase prunes it. Its ServiceAccount, Role, RoleBinding and ConfigMap are
  `PreSync` hooks too (they must exist before the Job). With `kubectl apply -k` (e2e, clusters without Argo CD) the
  annotations are inert and a pod that reads a Secret not yet created waits in `CreateContainerConfigError` until the Job
  wrote it. The Job's name carries a hash of its plan, so a changed plan re-runs under `kubectl apply` too;
  `ttlSecondsAfterFinished` removes finished Jobs.
- **The program is Python 3 stdlib, embedded in the renderer** (`render.CREDENTIALS_SCRIPT`), shipped in the ConfigMap as
  `create.py` next to `plan.json`, and run by one pinned image, `CREDENTIALS_IMAGE` = `python:3.13.<patch>-alpine<ver>@sha256:…`
  (a new versions-table row `credentials-job`, ADR-069). Embedding keeps the renderer one file, so the cluster-gitops copy
  (`scripts/sync-template-copies.py`) and the `/platform:update` path (which replaces only `scripts/render.py`) need nothing
  new. The cplat suite can run the same text against a fake API server.
- **Adoption of 5.4 Secrets (AC-128.9).** For each planned Secret the Job first deletes the generator-backed ExternalSecret of
  the same name with `propagationPolicy: Orphan` (the garbage collector removes its owner reference from the Secret instead of
  deleting it), waits until it is gone, deletes the retired `Password` generators, then creates-or-keeps the Secret and, for a
  kept one, removes leftover ExternalSecret owner references and Argo CD tracking metadata (`app.kubernetes.io/instance`
  label, `argocd.argoproj.io/tracking-id` annotation) so that a component application with `prune: true` never prunes it. The
  ExternalSecret is deleted *before* the Secret is touched, so ESO has nothing left to reconcile. An ExternalSecret of that name
  that is not generator-backed is not touched and fails the Job (someone else writes that Secret).
- **Repair of the #316 state (AC-128.10)**: for a cache and a broker the plan lists the server pods and, per user, the Secret
  and the container variable that carries it. After the Secrets are settled, the Job probes each Ready server pod by its pod IP
  with every user whose variable that pod's spec reads from that Secret (`AUTH default <pw>` for Valkey, `CONNECT` + `PING` for
  NATS). A refused password deletes that pod once; the StatefulSet recreates it and the new container reads the Secret. A user
  the pod's spec does not reference yet (a component just added, AC-128.5) is not probed, so adding a component never causes
  an extra restart. Healthy servers are never restarted. Valkey answers within seconds, so the server accepts the Secret's
  password well within 60 s of the sync.
- **The bucket moves too** (AC-128.7, see Blockers in the plan report). Its 5.4 ExternalSecret has the default refresh policy,
  so the forced refresh of AC-128.7's triggers regenerates both keys whatever the operator does, and components read the keys
  once at start. One mechanism for all four owners is also what AC-128.12 tests.
- **Existing Secrets are never changed in data**: no key is replaced, a key dropped from `generate:` stays, derived keys
  (`url`, `host`, …) of an existing Secret keep the form they were written with (same rule as spec 127). Deleting a Secret by
  hand is how a value is regenerated (the next sync writes a new one), which replaces ADR-018's "deleting the ExternalSecret
  rotates".
- **Secrets outlive their declaration.** No owner reference is set (an owner that is ever recreated would garbage-collect the
  credential). Removing a component, a `generate:` entry or a broker user leaves its Secret and the hook objects
  (`<owner>-credentials` ServiceAccount, Role, RoleBinding, ConfigMap) for a person to delete, as for broker streams.
- **Applications that run a credentials Job retry their sync** (`retry: RETRY`, the existing constant): the addons
  ApplicationSet of an environment with a cache, broker or bucket, and the component ApplicationSet of an environment where a
  component has a `generate:` secret. A transient API error in `PreSync` otherwise leaves the app unsynced until the next commit.
- **`/platform:update` names the change per resource type** (AC-128.9): one `credentials` row per type whose rendered writer
  changed from a generator to a credentials Job, next to the existing pin and url rows. The 4.x migration proof ignores the
  credential writers on both sides (the frozen 4.7 renderer still writes generators).
- **Cause of #316** (AC-128.13): the ADR task examines External Secrets 2.12.0 (`pkg/controllers/externalsecret/`:
  `shouldRefresh`, the target-Secret validity check, the cached client the second reconcile reads the just-created Secret
  through) and the upstream tracker, and records what it finds. Working hypothesis from the evidence: right after the create, a
  second reconcile sees the target Secret as missing or not valid (informer cache lag or a missing data-hash annotation),
  which `CreatedOnce` does not guard, runs the generator again and updates the Secret.
- **ADR-072** records the mechanism, the exception to ADR-018 with the rights below, and amends ADR-064 (3), ADR-065 (4),
  ADR-059 (3) and ADR-018 (2, `generate`).

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `templates/gitops-app/scripts/render.py` (+ `templates/cluster-gitops/scripts/system_render.py`, synced) | `CREDENTIALS_IMAGE`, `CREDENTIALS_SCRIPT`, `credentials_files()`; `cache_files()`, `broker_files()`, `bucket_files()`, `secret_manifests()` use it; stale rules; sync retry; versions-table row | changed |
| `scripts/cplat/update.py` | `credentials` rows in the change list; `_cache_url()` reads the plan; migration proof ignores credential writers | changed |
| `scripts/check-pins.py` | `CREDENTIALS_IMAGE` is a checked reference | changed |
| `tests/e2e/run.sh`, `tests/e2e/upgrade.sh` | apply credentials hooks first (Argo's PreSync), the AC-128 checks, `settle_cache` gone | changed |
| `docs/adr/072-…md` (+ 018, 059, 064, 065, README) | the decision | new / amended |
| `docs/CHANGELOG.md`, `docs/USER-JOURNEY.md`, `docs/HOW-IT-WORKS.md`, `docs/DOMAIN-MODEL.md`, `plugins/component/commands/add.md` | user-facing wording | changed |

## Contract

### Rendered files

Every owner directory gets five files (one object each) and lists them in its `kustomization.yaml` (`resources: sorted(files)`):

| File | Object | Name |
|---|---|---|
| `credentials-serviceaccount.yaml` | `v1/ServiceAccount` | `<owner>-credentials` |
| `credentials-role.yaml` | `rbac.authorization.k8s.io/v1/Role` | `<owner>-credentials` |
| `credentials-rolebinding.yaml` | `rbac.authorization.k8s.io/v1/RoleBinding` (subject: the SA in `<system>-<env>`) | `<owner>-credentials` |
| `credentials-configmap.yaml` | `v1/ConfigMap`, data `create.py` (= `CREDENTIALS_SCRIPT`) and `plan.json` | `<owner>-credentials` |
| `credentials-job.yaml` | `batch/v1/Job` | `<owner[:42]>-credentials-<h8>` |

`<owner>`: `<system>-<name>` for a resource instance (directory `addons/<env>/<name>/`), `<component>` for a component
(directory `overlays/<env>/<component>/`, only when it has a `generate:` secret). `<h8>` = first 8 hex characters of
`sha256(plan.json text + CREDENTIALS_SCRIPT + CREDENTIALS_IMAGE)`. Labels: the instance's `labels()` (name, part-of,
managed-by) or the component's `labels_for()`. Annotations on all five: `argocd.argoproj.io/hook: PreSync`; sync wave `"0"`
on the four, `"1"` on the Job; `argocd.argoproj.io/hook-delete-policy: BeforeHookCreation` on the four,
`BeforeHookCreation,HookSucceeded` on the Job.

No longer rendered: cache `externalsecret.yaml`, `password-generator.yaml`; broker `password-generator.yaml`,
`nack-secret.yaml`, `externalsecret-<component>.yaml`; bucket `externalsecret.yaml`, `access-key-generator.yaml`,
`secret-key-generator.yaml`; component `externalsecret-<secret>.yaml` of a `generate:` secret and `password-generator.yaml`
(a `remote:` secret keeps its ExternalSecret). The render removes them from git (stale rules: addon directories of a cache,
broker or bucket drop these names and `credentials-*.yaml` that are no longer wanted; `credentials-` joins
`MANAGED_PREFIXES` for overlays). Everything else in these directories is unchanged; servers still read their Secrets by
`secretKeyRef`/`envFrom`.

Job spec (exact):

```yaml
spec:
  backoffLimit: 2
  activeDeadlineSeconds: 300
  ttlSecondsAfterFinished: 600
  template:
    metadata: {labels: {app.kubernetes.io/name: <owner>-credentials, <part-of and managed-by of the owner>, app.kubernetes.io/component: credentials}}   # no selector label of the owner (amended during the build)
    spec:
      serviceAccountName: <owner>-credentials
      automountServiceAccountToken: true
      restartPolicy: Never
      securityContext: {runAsNonRoot: true, runAsUser: 65534, runAsGroup: 65534, seccompProfile: {type: RuntimeDefault}}
      containers:
      - name: credentials
        image: <CREDENTIALS_IMAGE>
        command: [python3, /credentials/create.py, /credentials/plan.json]
        env: [{name: PYTHONDONTWRITEBYTECODE, value: "1"}]
        resources: {requests: {cpu: 10m, memory: 32Mi}, limits: {memory: 64Mi}}
        securityContext: {runAsNonRoot: true, runAsUser: 65534, allowPrivilegeEscalation: false, readOnlyRootFilesystem: true, capabilities: {drop: [ALL]}}
        volumeMounts: [{name: credentials, mountPath: /credentials, readOnly: true}]
      volumes: [{name: credentials, configMap: {name: <owner>-credentials}}]
```

Role rules (exact order; a rule is omitted when its `resourceNames` would be empty):

```yaml
rules:
- {apiGroups: [""], resources: [secrets], verbs: [create]}
- {apiGroups: [""], resources: [secrets], resourceNames: [<planned Secrets>], verbs: [get, patch]}
- {apiGroups: [external-secrets.io], resources: [externalsecrets], resourceNames: [<planned Secrets>], verbs: [get, delete]}
- {apiGroups: [generators.external-secrets.io], resources: [passwords], resourceNames: [<retired generators>], verbs: [delete]}
- {apiGroups: [""], resources: [pods], resourceNames: [<server pods>], verbs: [get, delete]}     # cache and broker only
```

No `update`, `list`, `watch` or wildcard anywhere (`create` cannot be limited by name in Kubernetes RBAC; the program only
creates its planned names).

### `plan.json`

`json.dumps(plan, indent=2, sort_keys=True)`:

```json
{
  "namespace": "<system>-<env>",
  "secrets": [
    {"name": "<Secret>", "labels": {"<k>": "<v>"}, "generate": {"<key>": <length>}, "data": {"<key>": "<literal, may contain {{ .<generated key> }}>"}}
  ],
  "retire": {"externalSecrets": ["<names>"], "generators": ["<names>"]},
  "verify": {"engine": "valkey" | "nats", "port": <int>, "pods": ["<pod>"],
             "users": [{"secret": "<Secret>", "key": "password", "user": "<user>", "env": "<container variable>"}]}
}
```

`verify` exists only for caches and brokers. Generated values are `length` characters from `[A-Za-z0-9]` (`secrets.choice`),
independent per key. Per owner (`n` = `<system>-<name>`, `ns` = `<system>-<env>`):

| Owner | Secrets (`generate`; `data`) | retire.generators | verify |
|---|---|---|---|
| cache | `<n>-app` (`password: 32`; `url: redis://default:{{ .password }}@<n>.<ns>.svc:6379/0`, `host: <n>.<ns>.svc`, `port: "6379"`), labels `labels()` | `<n>-password` | `valkey`, 6379, `[<n>-0]`, user `default`, env `VALKEY_PASSWORD` |
| broker | `<n>-nack` (`password: 32`; `user: _nack`); per component `c` on the broker `<n>-<c>-app` (`password: 32`; `url: nats://<n>.<ns>.svc:4222`, `user: <c>`), labels `labels()` | `<n>-password` | `nats`, 4222, `[<n>-0 … <n>-<replicas-1>]`, `_nack`/`ADMIN_PASSWORD`, `<c>`/`USER_<C>_PASSWORD` |
| bucket | `<n>-app` (`accessKeyId: 20`, `secretAccessKey: 40`; `endpoint: http://<n>-filer.<ns>.svc:8333`, `bucket: <n>`, `region: us-east-1`, `forcePathStyle: "true"`), labels `backup_target_labels()` when it is the environment's backup target, else none | `<n>-access-key`, `<n>-secret-key` | none |
| component | each `generate:` secret `<name>` (`<KEY>: <length, default 32>` per key; no data), labels `labels_for()` | `<component>-password` | none |

`retire.externalSecrets` = the planned Secret names (every 5.4 generator-backed ExternalSecret had its Secret's name).

### `create.py` behaviour

Invocation `python3 create.py <plan.json>`. Environment: `CREDENTIALS_API_URL` (default
`https://$KUBERNETES_SERVICE_HOST:$KUBERNETES_SERVICE_PORT`; an `http://` URL disables TLS, for tests) and `CREDENTIALS_SA_DIR`
(default `/var/run/secrets/kubernetes.io/serviceaccount`; `token`, and `ca.crt` for https). Every request carries
`Authorization: Bearer <token>`. Connection errors, `403`, `429` and `5xx` are retried with backoff for up to 60 s per call.

Steps, in order:

1. **Retire** each name in `retire.externalSecrets`: `GET /apis/external-secrets.io/v1/namespaces/<ns>/externalsecrets/<name>`.
   `404` → nothing. `200` and some `spec.dataFrom[].sourceRef.generatorRef` → `DELETE` it with body
   `{"apiVersion": "v1", "kind": "DeleteOptions", "propagationPolicy": "Orphan"}`, then poll `GET` until `404` (up to 60 s);
   log `retired ExternalSecret <name>`. `200` without a generatorRef → log
   `ExternalSecret <name> is not generator-backed; it writes this Secret, so the credentials Job does not` and exit 1 before
   any Secret is written.
2. **Retire** each `retire.generators`: `DELETE /apis/generators.external-secrets.io/v1alpha1/namespaces/<ns>/passwords/<name>`;
   `404` is fine; log `retired Password generator <name>` on `200`.
3. **Create or keep** each Secret: `POST /api/v1/namespaces/<ns>/secrets` with
   `{"apiVersion": "v1", "kind": "Secret", "type": "Opaque", "metadata": {"name", "namespace", "labels"}, "data": {…base64…}}`,
   holding every generated key and every `data` key (placeholders `{{ .<key> }}` replaced by that Secret's generated values).
   `201` → log `created <name>`. `409` → `GET` it; build one JSON patch (`Content-Type: application/json-patch+json`) whose
   first op is `{"op": "test", "path": "/metadata/resourceVersion", "value": <rv>}`, followed only by: `add` of a missing
   or differing declared label, `remove` of `/metadata/labels/app.kubernetes.io~1instance` and
   `/metadata/annotations/argocd.argoproj.io~1tracking-id` when present, `replace` (or `remove` when empty) of
   `/metadata/ownerReferences` without entries of kind `ExternalSecret`, and `add` of `/data/<key>` for each planned key the
   Secret lacks (generated keys get a new value, `data` keys their literal). No op touches an existing `/data/<key>`. Send it
   only when it has more than the `test` op; on `409`/`422` re-`GET` and rebuild, up to 5 times. Log
   `kept <name>` (plus `; added keys <k,…>` and/or `; adopted (metadata)` when patched). A kept Secret with nothing to change
   is not written at all (its `resourceVersion` stays).
4. **Verify** (when `verify` exists): for each pod, `GET /api/v1/namespaces/<ns>/pods/<pod>`; skip it (log
   `skipped <pod>: <reason>`) when absent, not `Ready` or without `status.podIP`. Probe each user whose `env` the pod's
   containers declare with `valueFrom.secretKeyRef.name == secret`; the password is that Secret's `key` (`GET`, base64). A probe
   connects to `<podIP>:<port>` (5 s timeout):
   - `valkey`: send RESP `AUTH <user> <password>`; `+OK` = accepted, a line starting `-WRONGPASS` = refused, anything else or
     a socket error = unknown.
   - `nats`: read the `INFO` line (`tls_required: true` = unknown); send
     `CONNECT {"verbose":false,"pedantic":false,"user":…,"pass":…,"name":"credentials-check","lang":"python","version":"1","protocol":1}\r\nPING\r\n`;
     `PONG` = accepted, `-ERR 'Authorization Violation'` = refused, else unknown.
   Pods with a refused user are deleted (`DELETE …/pods/<pod>`, all at once; log `restarted <pod>: it refused the password of
   <secret>`). For each, wait up to 120 s for a pod of that name with a new `uid` that is `Ready`, then probe again: accepted →
   `verified <pod>`; refused → log `<pod> still refuses the password of <secret> after a restart` and exit 2; not ready in
   time → `skipped <pod>: not ready 120 s after the restart`. Accepted pods log `verified <pod>`. Unknown never restarts.
5. Exit 0 (any API error left after the retries: message and exit 1).

No value is ever printed, logged or written outside the Secret.

### `/platform:update` change list (AC-128.9)

`render_and_compare()` records, before and after the re-render, per `(system, owner, env)` whether the owner's directory has a
generator (`password-generator.yaml` or `access-key-generator.yaml`) or `credentials-job.yaml`; the owner's type comes from the
directory (`statefulset.yaml` cache, `server.yaml` broker, `seaweed.yaml` bucket, an overlay a component). For each type with
at least one owner that went from generator to Job, one row is appended after all other rows, in the order cache, broker,
bucket, component:

```json
{"env": "<envs, comma-joined in dev,staging,prod order>", "resource": "cache|broker|bucket|component", "kind": "credentials",
 "from": "ExternalSecret + Password generator", "to": "credentials Job (create if absent)", "moves": false, "text": "<text>"}
```

`text` = `f"{envs:<8} {type} {', '.join(sorted names)}: {what} written once by a credentials Job (create if absent) instead of {old}; existing Secrets keep their {kept}, nothing to do{extra} (#316)"` with

| type | what | old | kept | extra |
|---|---|---|---|---|
| cache | `the password is` | `an ExternalSecret with a Password generator` | `passwords` | `; a server whose password differs from its Secret restarts once` |
| broker | `the user passwords are` | `ExternalSecrets with a Password generator` | `passwords` | `; a server that refuses a password of its Secrets restarts once` |
| bucket | `the keys are` | `an ExternalSecret with two Password generators` | `keys` | (empty) |
| component | `generated secrets are` | `ExternalSecrets with a Password generator` | `values` | (empty) |

Example: `dev,staging,prod cache sessions: the password is written once by a credentials Job (create if absent) instead of an ExternalSecret with a Password generator; existing Secrets keep their passwords, nothing to do; a server whose password differs from its Secret restarts once (#316)`.

`_cache_url()` reads the url template from the cache's `credentials-configmap.yaml` (`plan.json`, Secret `<n>-app`, `data.url`)
and falls back to the 5.4 `externalsecret.yaml`; both use `{{ .password }}`, so a 5.4 → 5.5 update adds no url row and a 5.3
form still does. Rows flow into `versions.lines`, the printed block, `--json` and the fleet PR body as today.

Migration proof (`apply_systems`): both trees are compared after dropping `password-generator.yaml`, `credentials-*.yaml` and
every `externalsecret-*.yaml` whose `spec.dataFrom` has a `generatorRef`, and after removing those names from the
`resources` of the same directory's `kustomization.yaml` (compared parsed).

### e2e harness (what Argo CD would do)

Both scripts apply a directory that has `credentials-job.yaml` in two steps: `kubectl apply -f` the five `credentials-*.yaml`,
`kubectl wait --for=condition=complete job/<name> --timeout=180s` (on failure: the Job's logs), then `kubectl apply -k` the
directory (the broker keeps its HelmChart split). A directory of the previous release's render (upgrade setup) is applied as
today. A "forced write" (AC-128.3, AC-128.6, AC-128.8) deletes the finished Job and applies its five files again; the checks
then compare the Secret's `resourceVersion` and value hashes before and after.

## Risks

- **No CI run exercises Argo CD hooks** (both e2e scripts run without Argo CD). `PreSync` hooks with `CreateNamespace=true` and
  hook objects of kinds ServiceAccount/Role/ConfigMap are standard Argo CD behaviour; the plan's human step checks one real
  update with Argo CD.
- **A component started in the same second as a 5.4 cache** may hold the first (overwritten) password; the repair aligns the
  server with the Secret, so such a pod needs one restart. The evidence of #316 shows components start later.
- **The SeaweedFS operator and a Secret without owner**: 5.4's Secret was owned by the ExternalSecret, not by `S3Credentials`,
  and is adopted today; the e2e (AC-128.7) proves the new form on the pinned operator.
- **Reading of AC-128.11** "no e2e script restarts a cache or broker server": no restart *to make passwords match*. The
  deliberate restarts of other criteria (AC-118.7 cache persistence, spec 120 chart changes, AC-116.8 store restart) stay and
  run after the AC-128 checks of their environment.
- The python image adds one pull per Job (about 20 MB); it is pinned by digest like every other image.

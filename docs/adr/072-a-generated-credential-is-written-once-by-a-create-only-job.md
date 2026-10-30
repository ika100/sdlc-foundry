# ADR-072: A generated credential is written exactly once, by a create-only Job that cannot write it twice

**Status:** Accepted (2026-10-30)
**Amends:** [ADR-064](064-a-cache-is-a-platform-rendered-valkey-statefulset.md) (point 3, the cache password), [ADR-065](065-a-broker-is-nats-jetstream-with-declared-streams-and-per-component-users.md) (point 4, the broker users), [ADR-059](059-in-cluster-buckets-on-seaweedfs-per-instance.md) (point 3, the bucket keys) and [ADR-018](018-secrets-with-external-secrets-operator.md) (the `generate` kind) where they say a generated password is "written once" by External Secrets Operator
**Builds on:** [ADR-018](018-secrets-with-external-secrets-operator.md) (secrets from External Secrets Operator), [ADR-022](022-kyverno-policies.md) (guard rails), [ADR-069](069-one-versions-table-pins-everything-and-every-release-proves-the-upgrade.md) (one versions table, upgrade proof), spec 128, issue #316

## Context

Issue #316: in the upgrade e2e (previous release v5.4.0), a cache's Valkey server ran with a different password than its `<system>-<name>-app` Secret held a few minutes later, so components got `WRONGPASS`. The Secret and the server pod were created in the same second and the pod never restarted, so the Secret was rewritten after the server read it. The ExternalSecret said `refreshPolicy: CreatedOnce`. Which environment was hit changed from run to run. The broker (ADR-065) and bucket (ADR-059) keys are written the same way and carry the same risk.

**What was examined (External Secrets v2.12.0, the version installed; source at tag `v2.12.0`, `pkg/controllers/externalsecret/externalsecret_controller.go`):**

- `shouldRefresh` decides `CreatedOnce` only from the ExternalSecret's own status: it returns true while `Status.SyncedResourceVersion` is empty or `Status.RefreshTime` is zero, false afterwards. It never asks whether the target Secret already exists.
- The reconcile skips a refresh only when `!shouldRefresh(es) && isSecretValid(existingSecret, es)`. `isSecretValid` is false when the Secret is missing, lacks the `managed` label, or its data-hash annotation differs from the hash of its data. So a `CreatedOnce` ExternalSecret still refreshes whenever the Secret looks invalid, and a refresh of a generator-backed ExternalSecret runs the `Password` generator again and gets a new value.
- The reconcile first reads the Secret as metadata from the partial cache, patches the `managed` label onto a Secret that lacks it and requeues, then reads the Secret from the full cache (`r.SecretClient`); the code comments say the two caches can disagree (`resolveSecretCacheMismatch`). The status that `shouldRefresh` relies on is written at the end of the reconcile, after the Secret.

**Finding:** the cause is not confirmed by a reproduction. The evidence fits this sequence: ESO creates the Secret, a second reconcile (the requeue after the label patch, or a status conflict) runs before the status records the first sync or while the Secret still looks invalid, `shouldRefresh` or `isSecretValid` lets the refresh through, the generator produces a second value and the Secret is updated. That stays a working hypothesis. Upstream: no issue found that describes this sequence. Issue 5499 (closed, "`refreshPolicy: CreatedOnce` still updates secrets") was answered as documented behaviour: the refresh policy only controls the operator's job queue and a Secret with `creationPolicy: Owner` is still reconciled; and issue 6640 (closed) reports that `CreatedOnce` gates only on the ExternalSecret's status, so a recreated ExternalSecret regenerates an existing Secret. Both agree that `CreatedOnce` does not mean "never write a second time". No fixed version known: no fixed version was found, and the latest release seen while writing this is chart 2.14.0, which was not examined.

Whatever the exact trigger, the guarantee the platform needs ("the Secret holds the value the server started with, forever") cannot rest on a controller that decides from its own status and caches.

## Decision

1. **A credentials Job writes each generated credential, once.** Per owner (a cache, broker or bucket instance, or a component with a `generate:` secret) the renderer writes `<owner>-credentials` as a ServiceAccount, Role, RoleBinding, ConfigMap (`create.py` and `plan.json`) and a Job named `<owner[:42]>-credentials-<h8>` (`h8`: the first 8 hex characters of `sha256(plan.json + script + image)`). The five objects are Argo CD hooks: `PreSync`, wave 0 for the four, wave 1 for the Job; hook-delete-policy `BeforeHookCreation` for the four and `BeforeHookCreation,HookSucceeded` for the Job. Outside Argo CD (the e2e harness) the same five files are applied in order and the Job is awaited.
2. **Create if absent.** The Job `POST`s each planned Secret. On `409` it keeps the Secret: it patches only labels, ownership metadata and keys the Secret lacks, as one JSON patch whose first operation tests `/metadata/resourceVersion`; no operation touches an existing `/data/<key>`, and a Secret with nothing to change is not written at all. Re-running the Job, a forced sync or a changed hash therefore cannot write a value twice. This is the mechanism that "cannot write it twice": the only write that can replace a value is `create`, and `create` fails when the Secret exists.
3. **Adoption order.** Before creating, the Job deletes the 5.4 ExternalSecret of a planned Secret with `propagationPolicy: Orphan` (so the Secret stays) once it has confirmed the ExternalSecret is generator-backed, waits for it to go, then deletes the retired `Password` generators. An ExternalSecret that is not generator-backed (a `remote:` secret) makes the Job stop before writing: it is not ours to replace. Existing Secrets keep their values; their `ownerReferences` of kind `ExternalSecret`, the Argo CD tracking id and the instance label are removed so Argo CD does not prune them.
4. **One-time repair of a wrong server (cache and broker).** After the Secrets exist the Job probes each running server pod with the password its pod reads from the Secret (Valkey `AUTH`, NATS `CONNECT`). A pod that refuses it is deleted once; the Job waits for the replacement and probes again, and fails (exit 2) when it still refuses. An unknown answer never restarts a pod. This repairs a cache or broker already hit by #316; a correct one is never restarted.
5. **Rights.** The Role is namespaced and holds exactly these rules (a rule is left out when its `resourceNames` would be empty):

   ```yaml
   rules:
   - {apiGroups: [""], resources: [secrets], verbs: [create]}
   - {apiGroups: [""], resources: [secrets], resourceNames: [<planned Secrets>], verbs: [get, patch]}
   - {apiGroups: [external-secrets.io], resources: [externalsecrets], resourceNames: [<planned Secrets>], verbs: [get, delete]}
   - {apiGroups: [generators.external-secrets.io], resources: [passwords], resourceNames: [<retired generators>], verbs: [delete]}
   - {apiGroups: [""], resources: [pods], resourceNames: [<server pods>], verbs: [get, delete]}   # cache and broker only
   ```

   There is no `update`, `list`, `watch` or wildcard. `create` cannot be limited by name in Kubernetes RBAC, so the Role can create any Secret in its namespace; the program only creates its planned names, and it cannot read or change any other Secret. `patch` is limited to the planned names; with no `update`, the only way to replace a whole Secret is to delete it, which the Role does not allow.
6. **The image** is one pinned row of the versions table (`CREDENTIALS_IMAGE`, a Python image); the Job runs `python3 /credentials/create.py /credentials/plan.json` with the standard library only, as non-root with a read-only root filesystem and all capabilities dropped. A new image changes `h8` and so the Job name, and the Job then runs again and keeps every Secret.
7. **Exception to ADR-018.** ADR-018 says every Secret comes from External Secrets Operator. Generated credentials are now the exception: they come from this Job. `remote:` secrets still come from External Secrets (a store, never git) and external resources' Secrets come from the secret store (ADR-057). Values still never reach git, logs or the Job's output.
8. **Rejected:** ESO `CreatedOnce` (the cause above, and no fixed version known); a `PushSecret` (a second controller with the same refresh logic); a Kyverno `generate` rule (it would need rights to every Secret and re-synchronises on policy change); an init container in the server pod (it would write the Secret from a pod's identity on every start and needs `update` to survive races).

## Consequences

- A cache, broker or bucket password is created exactly once; renders, syncs, restarts and image upgrades never change it. A server that already refuses its Secret's password is restarted once, on the first sync of this release.
- Deleting a Secret regenerates it on the next sync (the Job sees it absent and creates it). Servers do not follow the change by themselves: restart them.
- Secrets and hook objects outlive their declaration: removing a resource or a `generate:` secret leaves the Secret in the namespace (as ADR-059 already did for buckets); remove it by hand. Finished Jobs are cleaned by `ttlSecondsAfterFinished` and the hook policies.
- The Job needs a namespace where `create` on Secrets is allowed to the ServiceAccount `<owner>-credentials`, and Argo CD must run PreSync hooks. No CI run exercises Argo CD hooks; the e2e harness applies the same five files by hand and compares each Secret's `resourceVersion` and value hashes after a forced second run.
- External Secrets Operator is still needed for `remote:` secrets, not for in-cluster buckets, caches or brokers.
- If External Secrets ships a fix that makes `CreatedOnce` hold, this ADR still stands: the Job is the guarantee and does not depend on the controller's caches.

## Not included

- Password rotation, or a server that follows a changed Secret without a restart.
- A change to `remote:` secrets, to external resources' Secrets, or to how a server reads its Secret (`secretKeyRef` and `envFrom` are unchanged).
- Reproducing the External Secrets behaviour upstream or filing an upstream issue.

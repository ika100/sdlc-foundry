#!/usr/bin/env bash
# Platform end-to-end test (no GitHub, no GHCR, no ArgoCD):
#   create a system (system.yaml + a Java service + a website) with `cplat system new` → build the images → push to a
#   local registry → start the platform's own local cluster (scripts/local-cluster.sh, WITH_ARGO=0) → apply the manifests
#   the renderer generated → wait for rollout → probe the services through the Gateway → ship a spec: verify dev, promote
#   to staging, apply, verify staging, finish the ship run.
# It also declares a second, external database (ext-db) and proves in the cluster that its ExternalSecret creates no
# partial Secret while the store entry lacks `password` (AC-115.12), and that the Secret appears once the entry is complete.
# A bucket `files` (in-cluster SeaweedFS, versioning on in dev) is shared by e2e-api and e2e-web in dev and staging: an AWS CLI
# pod that carries the component's own variables writes, reads, lists and deletes objects, overwrites an object (versions), reads
# again after the store's pods restarted, and shows that dev's keys are refused by staging's endpoint (AC-116.5 to AC-116.8,
# AC-116.14). A third, external bucket (ext-files) proves its ExternalSecret creates no partial Secret while the store entry
# lacks `secretAccessKey` (AC-116.18). The operator comes from operators/apps/seaweedfs.yaml (AC-116.19).
# At the end it backs the system up (AC-117.24): a bucket `backups` is the target of the database's and the environment's backup, a
# row A, the time T and a row B go into postgres, which is restored to T and switched to (a component reads A and not B); a file on
# the volume of the external component e2e-files and an object in the bucket files are written, an environment backup is taken, both
# are deleted, and `system restore --replace` brings both back unchanged while the database cluster keeps its UID.
# Two caches (spec 118) follow the external bucket: sessions (persistence in dev) and ratelimit (64Mi), both used by e2e-web. The steps prove
# NOAUTH/WRONGPASS/PONG, maxmemory and eviction, SET and GET through SESSIONS_REDIS_URL from a probe pod, persistence across a pod
# delete, a password that survives restart and force-sync, only ClusterIP, no operator (operators/ unchanged), doctor without a cache row,
# and, in the backup steps, that neither the Schedule nor the Backup nor the restore knows a cache (AC-118.6 to .8, .11, .14, .15, .19, .23).
# It exercises: cplat system new, resource add, component ship, instance promote|secret|verify, the templates'
# Dockerfiles (non-root numeric user, read-only filesystem), render.py on system.yaml, the generated
# Deployment/Service/HTTPRoute against a real API server, and the Gateway API on k3s' Traefik.
#
# Needs: docker (running), k3d, kubectl, uv, curl, copier (or uv). Env: E2E_KEEP=1 keeps the cluster, E2E_PORT, E2E_WORK.
set -euo pipefail

root=$(cd "$(dirname "$0")/../.." && pwd)
work="${E2E_WORK:-$(mktemp -d)}"
port="${E2E_PORT:-8099}"
regport=5111
cluster=e2e-local
registry="k3d-${cluster}-registry"
cplat="uv run $root/scripts/cplat/cplat.py"
export PATH="$PATH:$HOME/.local/bin"
if ! command -v devbox >/dev/null; then
  # CI has no devbox: `devbox run <script>` runs the repo's devbox.json script with the runner's own tools
  # (the smoke recipes `instance verify` calls need only uv, or java and mvn)
  mkdir -p "$work/bin"
  cat > "$work/bin/devbox" <<'SH'
#!/usr/bin/env bash
[ "${1:-}" = run ] && [ -n "${2:-}" ] || { echo "e2e devbox shim: only 'devbox run <script>'" >&2; exit 2; }
cmd=$(python3 -c 'import json, sys; s = json.load(open("devbox.json"))["shell"]["scripts"][sys.argv[1]]; print(s if isinstance(s, str) else "\n".join(s))' "$2") || exit 2
shift 2
exec bash -c "$cmd" e2e-devbox "$@"
SH
  chmod +x "$work/bin/devbox"
  export PATH="$work/bin:$PATH"
fi
fail() { echo "E2E FAIL: $*" >&2; exit 1; }
step() { echo; echo "==> $*"; }

cleanup() {
  rc=$?
  if [ "${E2E_KEEP:-0}" != 1 ]; then
    (cd "$work/e2e-gitops" 2>/dev/null && LOCAL_CLUSTER=$cluster WITH_ARGO=0 REGISTRY_PORT=$regport bash scripts/local-cluster.sh down) >/dev/null 2>&1 || true
  fi
  [ $rc -eq 0 ] && echo && echo "E2E OK" || echo "E2E FAILED (work dir: $work)"
  exit $rc
}
trap cleanup EXIT

for t in docker k3d kubectl uv curl; do command -v $t >/dev/null || fail "$t is required"; done
docker info >/dev/null 2>&1 || fail "docker is not running"

gitops_repo="$work/e2e-gitops"
api_repo="$work/e2e-api"
commit() { (cd "$gitops_repo" && git add -A && git -c user.name=e2e -c user.email=e2e@example.com commit -qm "$1"); }

step "Create the system with the real templates (no GitHub): system.yaml, a Java service, a website"
printf '%s\n' 'system: e2e' 'owner: e2e' 'components:' \
  '  - {name: e2e-api, description: "e2e api", type: service, lang: java}' \
  '  - {name: e2e-web, description: "e2e web", type: website, lang: typescript}' > "$work/system.yml"
$cplat system new "$work/system.yml" --no-github --skip-tasks --dir "$work" --org e2e >/dev/null
[ -f "$gitops_repo/applications/e2e/system.yaml" ] || fail "system new did not write applications/e2e/system.yaml"

step "Declare the Postgres resource in system.yaml (cluster-up then installs the CloudNativePG operator)"
$cplat resource add postgres --repo-dir "$gitops_repo" >/dev/null
commit "postgres"
step "Declare the secret store and an external database ext-db (its store entry is filled in later)"
(cd "$gitops_repo" && uv run --with pyyaml --with ruamel.yaml python - "$root" <<'PY'
import sys
sys.path.insert(0, f"{sys.argv[1]}/scripts/cplat")
import gitops
from pathlib import Path
app_dir = gitops.find_app(Path("."))
y, data = gitops.load(app_dir)
if not data.get("secretStore"):
    data["secretStore"] = {"name": "platform-secrets", "kind": "ClusterSecretStore"}   # the local cluster's store
gitops.save(app_dir, y, data)
PY
)
$cplat resource add ext-db --type database --external --repo-dir "$gitops_repo" >/dev/null
commit "ext-db"
[ ! -e "$gitops_repo/operators" ] || fail "render wrote operators/ although no component uses an in-cluster database yet"
step "Declare the bucket files (in-cluster) and the external bucket ext-files (its store entry is filled in later)"
$cplat resource add files --type bucket --repo-dir "$gitops_repo" >/dev/null
commit "files"   # each resource add needs a clean tree
$cplat resource add ext-files --type bucket --external --repo-dir "$gitops_repo" >/dev/null
commit "ext-files"
# no component uses a bucket yet: nothing asks for the SeaweedFS operator (cluster-up gets WITH_SEAWEEDFS=1 below)
[ ! -e "$gitops_repo/operators" ] || fail "render wrote operators/ although no component uses an in-cluster database or bucket yet"
step "Describe the environments in system.yaml: the OpenTelemetry collector and enforced Kyverno guard rails in dev, a staging host"
(cd "$gitops_repo" && uv run --with pyyaml --with ruamel.yaml python - "$root" "$port" <<'PY'
import sys
root, port = sys.argv[1], sys.argv[2]
sys.path.insert(0, f"{root}/scripts/cplat")
import gitops
from pathlib import Path
app_dir = gitops.find_app(Path("."))
y, data = gitops.load(app_dir)
envs = data["environments"]
envs["dev"]["policy"] = "enforce"          # cluster-up installs Kyverno
envs["dev"]["observability"] = {}          # the collector only, no UI stack
envs["dev"]["url"] = "http://{host}:" + port
envs["staging"]["host"] = "{component}.{system}-staging.localhost"
envs["staging"]["url"] = "http://{host}:" + port
data["resources"]["files"]["instances"] = {"dev": {"versioning": True}}   # versioning on in dev only: staging keeps the default (false)
gitops.save(app_dir, y, data)
PY
)
commit "environments"

step "Start the local cluster with a registry (the template's own script, Gateway only)"
# Without Argo CD (WITH_ARGO=0) the script cannot apply operators/root.yaml (an Argo CD Application); it installs the
# CloudNativePG chart itself. WITH_CNPG=1: e2e-api uses postgres from the components step on, after the cluster is up, so
# operators/ (which WITH_CNPG would auto-detect) does not exist yet; the components step checks it and its pinned version.
# The same holds for the SeaweedFS operator (WITH_SEAWEEDFS=1): e2e-api and e2e-web use the bucket files from the components step on.
# And for the backup operators (WITH_BARMAN_CLOUD=1, with cert-manager, and WITH_VELERO=1): the database and the environment get
# `backup` only in the last steps, so operators/apps/ does not name them yet.
(cd "$work/e2e-gitops" && LOCAL_CLUSTER=$cluster LOCAL_HTTP_PORT=$port WITH_ARGO=0 WITH_CNPG=1 WITH_SEAWEEDFS=1 WITH_BARMAN_CLOUD=1 WITH_VELERO=1 REGISTRY_PORT=$regport bash scripts/local-cluster.sh up)

step "Build and push the images"
# Rendered with --skip-tasks, so the web repo has no pnpm-lock.yaml yet; the template's bootstrap would run
# `pnpm install`. Create the lock the same way (inside the image's own node base) because the Dockerfile requires it (spec 104).
node_image=$(sed -n 's/^FROM \(node:[^ ]*\).*/\1/p' "$work/e2e-web/Dockerfile" | head -1)
docker run --rm -v "$work/e2e-web:/app" -w /app "$node_image" sh -c 'corepack enable && pnpm install --lockfile-only --silent' >/dev/null
for svc in e2e-api e2e-web; do
  docker build -q -t "localhost:$regport/$svc:latest" "$work/$svc" >/dev/null
  docker push -q "localhost:$regport/$svc:latest" >/dev/null
done

step "Describe the components like /component:add does (into components: of system.yaml) and render the manifests"
(cd "$work/e2e-gitops" && uv run --with pyyaml --with ruamel.yaml python - "$root" "$registry:$regport" <<'PY'
import sys
root, registry = sys.argv[1], sys.argv[2]
sys.path.insert(0, f"{root}/scripts/cplat")
import compose, core, gitops
from pathlib import Path
repo = Path(".")
app_dir = gitops.find_app(repo)
y, data = gitops.load(app_dir)
components = gitops.components_of(data)
shapes = {s["id"]: s for s in core.registry.load()}
ns = compose.build_parser().parse_args(["add", "e2e-api", "--expose"])   # real parser defaults: new compose flags cannot break this harness
for name, shape in (("e2e-api", "service-java"), ("e2e-web", "web-nextjs")):
    ns.env = ["API_URL=http://e2e-api"] if name == "e2e-web" else []
    ns.generate = ["e2e-api-auth=DB_PASSWORD,JWT_KEY"] if name == "e2e-api" else []   # random values created by ESO
    ns.secret = ["e2e-api-stripe=STRIPE_KEY"] if name == "e2e-api" else []            # read from the secret store
    ns.uses = ["postgres", "files"] if name == "e2e-api" else ["files"]               # DATABASE_URL from the addon; S3_* and AWS_* from the bucket
    ns.secret_ref = ["e2e-api-auth"] if name == "e2e-web" else []                     # the web app reads the secret generated for the API
    components[name] = compose.build_entry(name, f"e2e/{name}", shapes[shape], None, registry, ns, {})
gitops.save(app_dir, y, data)
PY
uv run scripts/render.py)
commit "components"
# e2e-api now uses the in-cluster database: render writes the CloudNativePG operator to operators/ (cluster level, once)
[ -f "$gitops_repo/operators/apps/cloudnative-pg.yaml" ] || fail "render did not write operators/apps/cloudnative-pg.yaml for the in-cluster database"
[ -f "$gitops_repo/operators/root.yaml" ] || fail "render did not write operators/root.yaml"
# the components now use the in-cluster bucket files: render writes the SeaweedFS operator as well (and the chart installed by cluster-up is its pin)
[ -f "$gitops_repo/operators/apps/seaweedfs.yaml" ] || fail "render did not write operators/apps/seaweedfs.yaml for the in-cluster bucket"
sw_pin=$(sed -n 's/^[[:space:]]*targetRevision:[[:space:]]*["'"'"']\{0,1\}\([^"'"'"'[:space:]]*\).*/\1/p' "$gitops_repo/operators/apps/seaweedfs.yaml" | head -1)
sw_have=$(kubectl --context k3d-$cluster -n kube-system get helmchart seaweedfs-operator -o jsonpath='{.spec.version}' 2>/dev/null || true)
[ -n "$sw_pin" ] && [ "$sw_have" = "$sw_pin" ] || fail "the installed SeaweedFS operator chart is '$sw_have', operators/apps/seaweedfs.yaml pins '$sw_pin'"
kubectl --context k3d-$cluster get crd buckets.seaweed.seaweedfs.com >/dev/null || fail "the SeaweedFS operator's Bucket CRD is not installed"
echo "ok   operators/apps/seaweedfs.yaml pins seaweedfs-operator $sw_pin, which is installed"

step "Set the remote secret in the local store (what a developer does with /instance:secret)"
printf 'sk_test_e2e' | $cplat instance secret set e2e-api/dev e2e-api-stripe STRIPE_KEY --value-stdin --repo-dir "$gitops_repo" --context k3d-$cluster >/dev/null

step "Apply the guard rails (Enforce) before anything else, so every platform workload is admitted under them"
ns=e2e-dev
kubectl --context k3d-$cluster apply -n $ns -k "$work/e2e-gitops/applications/e2e/policies/dev"
for _ in $(seq 1 40); do
  [ "$(kubectl --context k3d-$cluster -n $ns get namespacedvalidatingpolicy platform-guardrails -o jsonpath='{.status.conditionStatus.ready}' 2>/dev/null)" = true ] && break; sleep 3
done
[ "$(kubectl --context k3d-$cluster -n $ns get namespacedvalidatingpolicy platform-guardrails -o jsonpath='{.status.conditionStatus.ready}')" = true ] || { kubectl --context k3d-$cluster -n $ns get namespacedvalidatingpolicy platform-guardrails -o yaml | tail -25; fail "the Kyverno policy did not become ready"; }

step "Apply the Postgres addon and wait for the database"
kubectl --context k3d-$cluster apply -n $ns -k "$work/e2e-gitops/applications/e2e/addons/dev/postgres"
for _ in $(seq 1 80); do
  [ "$(kubectl --context k3d-$cluster -n $ns get cluster e2e-postgres -o jsonpath='{.status.phase}' 2>/dev/null)" = "Cluster in healthy state" ] && break; sleep 5
done
[ "$(kubectl --context k3d-$cluster -n $ns get cluster e2e-postgres -o jsonpath='{.status.phase}')" = "Cluster in healthy state" ] || fail "the Postgres cluster did not become healthy"

# The bucket addon in sync-wave order (what Argo CD does): the key generators and the ExternalSecret (wave -1) first, then, once
# the Secret exists, the store, the bucket and the identity (wave 0), then the S3Credentials (wave 1), which adopt the key pair
kn() { local n=$1; shift; kubectl --context k3d-$cluster -n "$n" "$@"; }
apply_bucket() { # environment namespace [bucket, default files]
  local b=${3:-files} d k
  d="$work/e2e-gitops/applications/e2e/addons/$1/$b"
  for f in access-key-generator.yaml secret-key-generator.yaml externalsecret.yaml seaweed.yaml bucket.yaml identity.yaml credentials.yaml kustomization.yaml; do
    [ -f "$d/$f" ] || fail "render did not write addons/$1/$b/$f"
  done
  kn "$2" apply -f "$d/access-key-generator.yaml" -f "$d/secret-key-generator.yaml" -f "$d/externalsecret.yaml" >/dev/null
  for _ in $(seq 1 40); do   # up to 120 s
    [ -n "$(kn "$2" get secret e2e-$b-app -o jsonpath='{.data.secretAccessKey}' 2>/dev/null)" ] && break; sleep 3
  done
  for k in endpoint bucket region forcePathStyle accessKeyId secretAccessKey; do
    [ -n "$(kn "$2" get secret e2e-$b-app -o jsonpath="{.data.$k}" 2>/dev/null)" ] || { kn "$2" get externalsecret e2e-$b-app -o yaml | tail -25; kn "$2" get events --field-selector "involvedObject.name=e2e-$b-app" | tail -10; fail "the Secret e2e-$b-app in $2 lacks the key $k"; }
  done
  kn "$2" apply -f "$d/seaweed.yaml" -f "$d/bucket.yaml" -f "$d/identity.yaml" >/dev/null
  kn "$2" apply -f "$d/credentials.yaml" >/dev/null
  kn "$2" apply -k "$d" >/dev/null   # the whole kustomization is then a no-op
}
store_ready() { # namespace [bucket, default files]: the operator creates the master, volume and filer StatefulSets
  local s b=${2:-files}
  for s in master volume filer; do
    for _ in $(seq 1 60); do kn "$1" get statefulset e2e-$b-$s >/dev/null 2>&1 && break; sleep 3; done   # up to 180 s
    kn "$1" rollout status statefulset/e2e-$b-$s --timeout=300s || {
      kn "$1" get pods; kn "$1" describe statefulset e2e-$b-$s | tail -25; fail "the SeaweedFS $s of e2e-$b in $1 did not become ready"; }
  done
}

step "Apply the bucket addon (SeaweedFS store, bucket, identity, generated keys) and wait for the store"
apply_bucket dev $ns
store_ready $ns

step "Apply the OpenTelemetry collector"
kubectl --context k3d-$cluster apply -n $ns -k "$work/e2e-gitops/applications/e2e/addons/dev/observability"
kubectl --context k3d-$cluster -n $ns rollout status deploy/otel-collector --timeout=180s || {
  kubectl --context k3d-$cluster -n $ns logs deploy/otel-collector | tail -20; fail "the collector did not become ready (invalid generated config?)"; }

step "Apply the generated manifests (what ArgoCD would sync)"
for svc in e2e-api e2e-web; do
  kubectl --context k3d-$cluster apply -n $ns -k "$work/e2e-gitops/applications/e2e/overlays/dev/$svc"
done
for svc in e2e-api e2e-web; do
  kubectl --context k3d-$cluster -n $ns rollout status deploy/$svc --timeout=240s || {
    kubectl --context k3d-$cluster -n $ns describe pod -l app=$svc | tail -30; fail "$svc did not become ready"; }
done

step "Probe through the Gateway"
probe() { # url expected-substring
  for _ in $(seq 1 30); do
    out=$(curl -s -m 5 "$1" || true)
    case "$out" in *"$2"*) echo "ok   $1 -> $2"; return 0;; esac
    sleep 3
  done
  fail "$1 did not return '$2' (got: ${out:-nothing})"
}
probe "http://e2e-web.e2e-dev.localhost:$port/api/health" '"status":"ok"'
probe "http://e2e-api.e2e-dev.localhost:$port/actuator/health/readiness" '"status":"UP"'
probe "http://e2e-api.e2e-dev.localhost:$port/api/info" '"service":"e2e-api"'

step "Pods run as the declared non-root user with a read-only filesystem"
kubectl --context k3d-$cluster -n $ns get pods -o jsonpath='{range .items[*]}{.metadata.name}{" ro="}{.spec.containers[0].securityContext.readOnlyRootFilesystem}{" uid="}{.spec.containers[0].securityContext.runAsUser}{"\n"}{end}'

step "External Secrets: generated values are random and stable, remote values arrive"
kc() { kubectl --context k3d-$cluster -n $ns "$@"; }
secret_val() { kc get secret "$1" -o jsonpath="{.data.$2}" 2>/dev/null | base64 -d; }
for _ in $(seq 1 40); do [ -n "$(secret_val e2e-api-auth DB_PASSWORD)" ] && [ -n "$(secret_val e2e-api-stripe STRIPE_KEY)" ] && break; sleep 3; done
db=$(secret_val e2e-api-auth DB_PASSWORD); jwt=$(secret_val e2e-api-auth JWT_KEY)
[ "${#db}" = 32 ] || fail "generated DB_PASSWORD has length ${#db}, expected 32"
[ "$db" != "$jwt" ] || fail "generated keys must differ"
[ "$(secret_val e2e-api-stripe STRIPE_KEY)" = sk_test_e2e ] || fail "remote secret did not arrive"
kc annotate externalsecret e2e-api-auth force-sync="$(date +%s)" --overwrite >/dev/null; sleep 8
[ "$(secret_val e2e-api-auth DB_PASSWORD)" = "$db" ] || fail "generated secret changed on re-sync (it must be created once)"
kc get pod -l app=e2e-api -o jsonpath='{.items[0].spec.containers[0].envFrom[*].secretRef.name}' | grep -q e2e-api-auth || fail "pod does not consume the generated secret"
echo "ok   generated + remote secrets synced and consumed"

step "Postgres addon: the generated credentials work and the service is wired to them"
uri=$(secret_val e2e-postgres-app uri)
[ "$(kc exec e2e-postgres-1 -c postgres -- psql "$uri" -tAc 'select 1')" = 1 ] || fail "cannot connect to Postgres with the addon's credentials"
kc get deploy e2e-api -o jsonpath='{.spec.template.spec.containers[0].env[*].name}' | grep -q DATABASE_URL || fail "DATABASE_URL is not wired into e2e-api"
echo "ok   postgres reachable with the generated credentials; e2e-api consumes DATABASE_URL"

step "OpenTelemetry: services are wired to the collector, telemetry reaches it"
kc get deploy e2e-api -o jsonpath='{.spec.template.spec.containers[0].env[?(@.name=="OTEL_EXPORTER_OTLP_ENDPOINT")].value}' | grep -q "http://otel-collector:4318" || fail "e2e-api has no OTEL endpoint"
code=$(kc run otlp-push --rm -i --restart=Never --image=curlimages/curl:8.10.1 --command -- curl -s -o /dev/null -w '%{http_code}\n' -H 'Content-Type: application/json' \
  -d '{"resourceSpans":[{"resource":{"attributes":[{"key":"service.name","value":{"stringValue":"e2e-probe"}}]},"scopeSpans":[{"spans":[{"traceId":"0af7651916cd43dd8448eb211c80319c","spanId":"b7ad6b7169203331","name":"probe","kind":1,"startTimeUnixNano":"1700000000000000000","endTimeUnixNano":"1700000001000000000"}]}]}]}' \
  http://otel-collector:4318/v1/traces 2>/dev/null | grep -oE '^[0-9]{3}' | head -1)
[ "$code" = 200 ] || fail "the collector rejected an OTLP/HTTP trace (HTTP $code)"
# capture the logs first: `kubectl logs | grep -q` can die of SIGPIPE under pipefail once the log is long
collector_has() { local logs; logs=$(kc logs deploy/otel-collector 2>/dev/null) || return 1; grep -q "$1" <<< "$logs"; }
for _ in $(seq 1 30); do collector_has 'info	Traces' && break; sleep 2; done
collector_has 'info	Traces' || fail "the pushed trace never reached the collector pipeline"
for _ in $(seq 1 40); do collector_has 'info	Metrics' && break; sleep 3; done
collector_has 'info	Metrics' || fail "no metrics reached the collector (scrape of e2e-api or OTLP push)"
echo "ok   traces and metrics arrive at the collector"

step "Kyverno: the platform's own workloads were admitted under Enforce, a violating one is denied"
kc get deploy e2e-api e2e-web otel-collector >/dev/null || fail "a platform workload is missing"
if out=$(kc create deployment violating --image=docker.io/library/nginx:latest 2>&1); then kc delete deployment violating >/dev/null; fail "a violating Deployment was admitted under Enforce"; fi
case "$out" in *"platform-guardrails"*) echo "ok   denied: $(echo "$out" | tr '\n' ' ' | cut -c1-160)";; *) fail "the denial did not come from the guard rails: $out";; esac

# ---- The bucket: probes from inside the cluster with the components' own variables ----
S3_IMAGE=amazon/aws-cli:2.22.35
read -r -d '' s3_pod_py <<'PY' || true
import json, re, sys
name, image, script = sys.argv[1:4]
dep = json.load(sys.stdin)
env = [e for e in dep["spec"]["template"]["spec"]["containers"][0].get("env", []) if "valueFrom" in e and re.match(r"(S3|AWS)_", e["name"])]
env += [{"name": k, "value": v} for k, v in (("AWS_PAGER", ""), ("AWS_EC2_METADATA_DISABLED", "true"), ("HOME", "/tmp"),
                                             ("AWS_REQUEST_CHECKSUM_CALCULATION", "when_required"), ("AWS_RESPONSE_CHECKSUM_VALIDATION", "when_required"))]
print(json.dumps({"apiVersion": "v1", "kind": "Pod", "metadata": {"name": name, "labels": {"app": "s3probe"}},
                  "spec": {"restartPolicy": "Never", "containers": [{"name": "aws", "image": image, "command": ["sh", "-c", script], "env": env}]}}))
PY
# S3_FORCE_PATH_STYLE (from the Secret, as the component sees it) decides the addressing style
s3pre='set -e; [ "$S3_FORCE_PATH_STYLE" = true ] && aws configure set default.s3.addressing_style path; A="aws --endpoint-url $S3_ENDPOINT"; '
s3n=0
s3run() { # namespace deployment script: runs it in a pod that carries the deployment's S3_* and AWS_* variables; output in S3_OUT
  local ns_=$1 dep=$2 name phase=""
  s3n=$((s3n + 1)); name="s3probe-$s3n"
  kn "$ns_" get deploy "$dep" -o json | python3 -c "$s3_pod_py" "$name" "$S3_IMAGE" "$s3pre$3" | kn "$ns_" apply -f - >/dev/null || fail "could not start the probe pod $name"
  for _ in $(seq 1 60); do   # up to 180 s (the first run pulls the image)
    phase=$(kn "$ns_" get pod "$name" -o jsonpath='{.status.phase}' 2>/dev/null || true)
    case "$phase" in Succeeded|Failed) break;; esac; sleep 3
  done
  S3_OUT=$(kn "$ns_" logs "$name" 2>&1 || true)
  [ "$phase" = Succeeded ] || S3_OUT="$S3_OUT (pod phase: ${phase:-unknown}; $(kn "$ns_" get pod "$name" -o jsonpath='{.status.containerStatuses[*].state.waiting.reason}' 2>/dev/null))"
  kn "$ns_" delete pod "$name" --wait=false >/dev/null 2>&1 || true
  [ "$phase" = Succeeded ]
}
s3_why() { case "$1" in
  *AccessDenied*|*InvalidAccessKeyId*|*SignatureDoesNotMatch*|*Forbidden*|*"(403)"*) echo "access denied";;
  *"Could not connect"*|*EndpointConnectionError*|*"Connection refused"*|*"timed out"*|*"Name or service not known"*|*"Max retries"*) echo "endpoint unreachable";;
  *) echo "unexpected error";; esac; }
s3must() { # label namespace deployment script
  s3run "$2" "$3" "$4" || fail "$1: $(s3_why "$S3_OUT"): $(echo "$S3_OUT" | tail -5 | tr '\n' ' ' | cut -c1-400)"
}
s3_retry() { # attempts label namespace deployment script: the store may need a moment after its pods are Ready
  local i
  for i in $(seq 1 "$1"); do s3run "$3" "$4" "$5" && return 0; sleep 5; done
  fail "$2: $(s3_why "$S3_OUT"): $(echo "$S3_OUT" | tail -5 | tr '\n' ' ' | cut -c1-400)"
}
s3_field() { sed -n "s/^$1=//p" <<< "$S3_OUT" | head -1; }
s3_same() { # label want got
  [ "$2" = "$3" ] || fail "$1: content differs (wanted '$2', got '$3')"
}
H=probe/hello.txt

step "Bucket: e2e-api writes an object through its variables and reads back the same bytes (AC-116.14)"
s3_retry 12 "bucket e2e-files is not reachable from e2e-api in dev" $ns e2e-api '$A s3api head-bucket --bucket "$S3_BUCKET"'
payload="hello-$RANDOM-$RANDOM"
s3must "e2e-api writes and reads in dev" $ns e2e-api 'printf %s '"$payload"' > /tmp/in
$A s3api put-object --bucket "$S3_BUCKET" --key '$H' --body /tmp/in >/dev/null
$A s3api put-object --bucket "$S3_BUCKET" --key keep/restart.txt --body /tmp/in >/dev/null
$A s3api get-object --bucket "$S3_BUCKET" --key '$H' /tmp/out >/dev/null
echo "CONTENT=$(cat /tmp/out)"'
s3_same "e2e-api read-back in dev" "$payload" "$(s3_field CONTENT)"
echo "ok   e2e-api wrote and read $H ($payload)"

step "Bucket: e2e-web, with its own copy of the variables, lists, reads and deletes the object e2e-api wrote (AC-116.6)"
s3must "e2e-web lists, reads and deletes in dev" $ns e2e-web '$A s3api list-objects-v2 --bucket "$S3_BUCKET" --query "Contents[].Key" --output text > /tmp/keys
echo "KEYS=$(cat /tmp/keys | tr "\t" " ")"
$A s3api get-object --bucket "$S3_BUCKET" --key '$H' /tmp/out >/dev/null
echo "CONTENT=$(cat /tmp/out)"
$A s3api delete-object --bucket "$S3_BUCKET" --key '$H' >/dev/null
echo "AFTER=$($A s3api list-objects-v2 --bucket "$S3_BUCKET" --query "Contents[].Key" --output text | tr "\t" " ")"'
case " $(s3_field KEYS) " in *" $H "*) ;; *) fail "e2e-web does not list $H (list: '$(s3_field KEYS)')";; esac
s3_same "e2e-web read of the object e2e-api wrote" "$payload" "$(s3_field CONTENT)"
case " $(s3_field AFTER) " in *" $H "*) fail "e2e-web deleted $H but the list still has it";; esac
echo "ok   e2e-web listed, read and deleted $H; the other object stays: $(s3_field AFTER)"

step "Bucket versioning: dev keeps the old version of an overwritten object, fetched by its version-id (AC-116.7)"
s3must "versions in dev" $ns e2e-api 'printf one > /tmp/v1; printf two > /tmp/v2
echo "STATUS=$($A s3api get-bucket-versioning --bucket "$S3_BUCKET" --query Status --output text)"
vid=$($A s3api put-object --bucket "$S3_BUCKET" --key ver/v.txt --body /tmp/v1 --query VersionId --output text)
echo "VID=$vid"
$A s3api put-object --bucket "$S3_BUCKET" --key ver/v.txt --body /tmp/v2 >/dev/null
$A s3api get-object --bucket "$S3_BUCKET" --key ver/v.txt --version-id "$vid" /tmp/old >/dev/null
echo "OLD=$(cat /tmp/old)"
$A s3api get-object --bucket "$S3_BUCKET" --key ver/v.txt /tmp/new >/dev/null
echo "NEW=$(cat /tmp/new)"
echo "COUNT=$($A s3api list-object-versions --bucket "$S3_BUCKET" --prefix ver/v.txt --query "length(Versions)" --output text)"'
dev_vid=$(s3_field VID)
s3_same "versioning status in dev" Enabled "$(s3_field STATUS)"
s3_same "old version in dev" one "$(s3_field OLD)"
s3_same "latest version in dev" two "$(s3_field NEW)"
s3_same "version count in dev" 2 "$(s3_field COUNT)"
echo "ok   dev has versioning Enabled: version $dev_vid still reads 'one', the latest reads 'two'"

step "Bucket: delete the store's pods; the data survives on the persistent volumes (AC-116.8)"
store_pods="e2e-files-master-0 e2e-files-volume-0 e2e-files-filer-0"
old_uids=$(kn $ns get pod $store_pods -o jsonpath='{range .items[*]}{.metadata.name}={.metadata.uid}{"\n"}{end}')
kn $ns delete pod $store_pods --wait=true --timeout=120s >/dev/null || fail "could not delete the SeaweedFS pods of e2e-files"
for p in $store_pods; do
  uid=""; ready=""
  for _ in $(seq 1 100); do   # up to 300 s per pod
    uid=$(kn $ns get pod $p -o jsonpath='{.metadata.uid}' 2>/dev/null || true)
    ready=$(kn $ns get pod $p -o jsonpath='{.status.containerStatuses[0].ready}' 2>/dev/null || true)
    [ -n "$uid" ] && ! grep -qx "$p=$uid" <<< "$old_uids" && [ "$ready" = true ] && break; sleep 3
  done
  [ "$ready" = true ] && ! grep -qx "$p=$uid" <<< "$old_uids" || { kn $ns get pods; fail "$p did not come back as a new pod after the restart"; }
done
store_ready $ns
s3_retry 20 "e2e-web reads after the restart of the store" $ns e2e-web '$A s3api get-object --bucket "$S3_BUCKET" --key keep/restart.txt /tmp/out >/dev/null
echo "CONTENT=$(cat /tmp/out)"
$A s3api get-object --bucket "$S3_BUCKET" --key ver/v.txt --version-id '"$dev_vid"' /tmp/old >/dev/null
echo "OLD=$(cat /tmp/old)"'
s3_same "object after the restart" "$payload" "$(s3_field CONTENT)"
s3_same "old version after the restart" one "$(s3_field OLD)"
echo "ok   the store's pods were replaced; the object and the old version are still there"

step "Bucket: syncing its application again keeps the keys and the data (AC-116.8)"
# without Argo CD, applying the rendered addon again is what a re-sync does; the generated keys are written once
key_before=$(secret_val e2e-files-app accessKeyId); secret_before=$(secret_val e2e-files-app secretAccessKey)
[ -n "$key_before" ] && [ -n "$secret_before" ] || fail "the Secret e2e-files-app has no keys before the re-sync"
kn $ns apply -k "$work/e2e-gitops/applications/e2e/addons/dev/files" >/dev/null || fail "applying addons/dev/files again failed"
sleep 10   # give a wrongly regenerated key time to land
[ "$(secret_val e2e-files-app accessKeyId)" = "$key_before" ] && [ "$(secret_val e2e-files-app secretAccessKey)" = "$secret_before" ] \
  || fail "syncing the bucket's application again changed the keys of e2e-files-app"
store_ready $ns
s3_retry 20 "e2e-web reads after the re-sync" $ns e2e-web '$A s3api get-object --bucket "$S3_BUCKET" --key keep/restart.txt /tmp/out >/dev/null
echo "CONTENT=$(cat /tmp/out)"
$A s3api get-object --bucket "$S3_BUCKET" --key ver/v.txt --version-id '"$dev_vid"' /tmp/old >/dev/null
echo "OLD=$(cat /tmp/old)"'
s3_same "object after the re-sync" "$payload" "$(s3_field CONTENT)"
s3_same "old version after the re-sync" one "$(s3_field OLD)"
echo "ok   the re-synced bucket keeps its keys, the object and the old version"

step "External database: a store entry without password creates no Secret and the ExternalSecret reports the key"
# ext-db is external in every environment; the ExternalSecret <system>-ext-db-app lands in the overlay of the first
# component that uses it. e2e-web uses it from here on, next to the bucket files (e2e-api keeps postgres and files, so DATABASE_URL stays as it was).
(cd "$gitops_repo" && uv run --with pyyaml --with ruamel.yaml python - "$root" <<'PY'
import sys
sys.path.insert(0, f"{sys.argv[1]}/scripts/cplat")
import gitops
from pathlib import Path
app_dir = gitops.find_app(Path("."))
y, data = gitops.load(app_dir)
web = gitops.components_of(data)["e2e-web"]
web["uses"] = [*(web.get("uses") or []), "ext-db"]
gitops.save(app_dir, y, data)
PY
uv run scripts/render.py)
commit "e2e-web uses ext-db"
ext_es=e2e-ext-db-app
store_key=e2e-dev-ext-db
sc() { kubectl --context k3d-$cluster -n secrets-store "$@"; }
# the store entry holds uri, host, port, dbname and user, but not password
sc create secret generic $store_key --from-literal=uri=postgres://app@ext.example:5432/app --from-literal=host=ext.example \
  --from-literal=port=5432 --from-literal=dbname=app --from-literal=user=app >/dev/null
kubectl --context k3d-$cluster apply -n $ns -k "$work/e2e-gitops/applications/e2e/overlays/dev/e2e-web" >/dev/null
kc get externalsecret $ext_es >/dev/null || fail "the ExternalSecret $ext_es was not applied with the e2e-web overlay"
kc annotate externalsecret $ext_es force-sync="$(date +%s)" --overwrite >/dev/null
es_ready() { kc get externalsecret $ext_es -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}' 2>/dev/null; }
for _ in $(seq 1 30); do [ "$(es_ready)" = False ] && break; sleep 3; done   # up to 90 s
[ "$(es_ready)" = False ] || { kc get externalsecret $ext_es -o yaml | tail -25; fail "the ExternalSecret $ext_es is not reported as not ready although password is missing in the store"; }
# External Secrets Operator keeps the Ready message generic ("could not get secret data from provider") and reports the
# provider's error, which names the missing property, as an event of the ExternalSecret (what `kubectl describe` shows)
es_message=$(kc get externalsecret $ext_es -o jsonpath='{.status.conditions[?(@.type=="Ready")].message}')
es_events() { kc get events --field-selector "involvedObject.kind=ExternalSecret,involvedObject.name=$ext_es" -o jsonpath='{range .items[*]}{.message}{"\n"}{end}' 2>/dev/null; }
for _ in $(seq 1 20); do case "$es_message $(es_events)" in *password*) break;; esac; sleep 3; done   # up to 60 s
case "$es_message $(es_events)" in
  *password*) echo "ok   ExternalSecret not ready, its status names the key: $(es_events | grep -m1 password | cut -c1-160)";;
  *) kc describe externalsecret $ext_es | tail -20; fail "the ExternalSecret status does not name the missing key password (ready: $es_message)";;
esac
sleep 5   # give a wrongly created partial Secret time to appear
if kc get secret $ext_es >/dev/null 2>&1; then fail "the Secret $ext_es exists although the store entry lacks password (no partial Secret allowed)"; fi
echo "ok   no Secret $ext_es while password is missing"
# the instance that uses it stays unhealthy: the new e2e-web pod cannot start without the Secret (the old ReplicaSet
# keeps the Deployment available, so the new pod's state is checked directly)
web_waiting() { kc get pods -l app=e2e-web -o jsonpath='{.items[*].status.containerStatuses[*].state.waiting.reason}' 2>/dev/null; }
for _ in $(seq 1 20); do case "$(web_waiting)" in *CreateContainerConfigError*) break;; esac; sleep 3; done   # up to 60 s
case "$(web_waiting)" in
  *CreateContainerConfigError*) echo "ok   e2e-web's new pod is not ready while $ext_es is missing (CreateContainerConfigError)";;
  *) kc get pods -l app=e2e-web -o wide; fail "e2e-web's new pod is not held back by the missing Secret $ext_es (waiting: '$(web_waiting)')";;
esac

step "External database: completing the store entry creates the Secret with all keys"
sc patch secret $store_key --type merge -p '{"stringData":{"password":"ext-secret-pw"}}' >/dev/null
kc annotate externalsecret $ext_es force-sync="$(date +%s)" --overwrite >/dev/null
for _ in $(seq 1 40); do [ "$(secret_val $ext_es password)" = ext-secret-pw ] && break; sleep 3; done   # up to 120 s
[ "$(secret_val $ext_es password)" = ext-secret-pw ] || { kc get externalsecret $ext_es -o yaml | tail -25; fail "the Secret $ext_es did not appear after the store entry was completed"; }
for k in uri host port dbname user password; do
  [ -n "$(secret_val $ext_es $k)" ] || fail "the Secret $ext_es lacks the key $k"
done
kc rollout status deploy/e2e-web --timeout=240s || {
  kc describe pod -l app=e2e-web | tail -30; fail "e2e-web did not become ready once the Secret $ext_es existed"; }
echo "ok   Secret $ext_es has uri, host, port, dbname, user and password; e2e-web runs"

step "External bucket: a store entry without secretAccessKey creates no Secret and the ExternalSecret reports the key (AC-116.18)"
# e2e-web now uses two buckets: files and ext-files. Its bucket variables switch to prefixed names (FILES_S3_*, EXT_FILES_S3_*), which is
# why every probe with e2e-web's own variables ran before this step. The database stays bare (one database resource of its type).
(cd "$gitops_repo" && uv run --with pyyaml --with ruamel.yaml python - "$root" <<'PY'
import sys
sys.path.insert(0, f"{sys.argv[1]}/scripts/cplat")
import gitops
from pathlib import Path
app_dir = gitops.find_app(Path("."))
y, data = gitops.load(app_dir)
web = gitops.components_of(data)["e2e-web"]
web["uses"] = [*(web.get("uses") or []), "ext-files"]
gitops.save(app_dir, y, data)
PY
uv run scripts/render.py)
commit "e2e-web uses ext-files"
ext_es=e2e-ext-files-app
store_key=e2e-dev-ext-files
# the entry holds endpoint, bucket, region, forcePathStyle and accessKeyId, but not secretAccessKey
sc create secret generic $store_key --from-literal=endpoint=http://ext.example:9000 --from-literal=bucket=ext-bucket --from-literal=region=us-east-1 \
  --from-literal=forcePathStyle=true --from-literal=accessKeyId=AKEXTERNAL >/dev/null
kubectl --context k3d-$cluster apply -n $ns -k "$work/e2e-gitops/applications/e2e/overlays/dev/e2e-web" >/dev/null
kc get externalsecret $ext_es >/dev/null || fail "the ExternalSecret $ext_es was not applied with the e2e-web overlay"
kc annotate externalsecret $ext_es force-sync="$(date +%s)" --overwrite >/dev/null
for _ in $(seq 1 30); do [ "$(es_ready)" = False ] && break; sleep 3; done   # up to 90 s
[ "$(es_ready)" = False ] || { kc get externalsecret $ext_es -o yaml | tail -25; fail "the ExternalSecret $ext_es is not reported as not ready although secretAccessKey is missing in the store"; }
es_message=$(kc get externalsecret $ext_es -o jsonpath='{.status.conditions[?(@.type=="Ready")].message}')
for _ in $(seq 1 20); do case "$es_message $(es_events)" in *secretAccessKey*) break;; esac; sleep 3; done   # up to 60 s
case "$es_message $(es_events)" in
  *secretAccessKey*) echo "ok   ExternalSecret not ready, its status names the key: $(es_events | grep -m1 secretAccessKey | cut -c1-160)";;
  *) kc describe externalsecret $ext_es | tail -20; fail "the ExternalSecret status does not name the missing key secretAccessKey (ready: $es_message)";;
esac
sleep 5   # give a wrongly created partial Secret time to appear
if kc get secret $ext_es >/dev/null 2>&1; then fail "the Secret $ext_es exists although the store entry lacks secretAccessKey (no partial Secret allowed)"; fi
echo "ok   no Secret $ext_es while secretAccessKey is missing"
for _ in $(seq 1 20); do case "$(web_waiting)" in *CreateContainerConfigError*) break;; esac; sleep 3; done   # up to 60 s
case "$(web_waiting)" in
  *CreateContainerConfigError*) echo "ok   e2e-web's new pod is not ready while $ext_es is missing (CreateContainerConfigError)";;
  *) kc get pods -l app=e2e-web -o wide; fail "e2e-web's new pod is not held back by the missing Secret $ext_es (waiting: '$(web_waiting)')";;
esac

step "External bucket: completing the store entry creates the Secret with all six keys"
sc patch secret $store_key --type merge -p '{"stringData":{"secretAccessKey":"ext-secret-key"}}' >/dev/null
kc annotate externalsecret $ext_es force-sync="$(date +%s)" --overwrite >/dev/null
for _ in $(seq 1 40); do [ "$(secret_val $ext_es secretAccessKey)" = ext-secret-key ] && break; sleep 3; done   # up to 120 s
[ "$(secret_val $ext_es secretAccessKey)" = ext-secret-key ] || { kc get externalsecret $ext_es -o yaml | tail -25; fail "the Secret $ext_es did not appear after the store entry was completed"; }
for k in endpoint bucket region forcePathStyle accessKeyId secretAccessKey; do
  [ -n "$(secret_val $ext_es $k)" ] || fail "the Secret $ext_es lacks the key $k"
done
kc rollout status deploy/e2e-web --timeout=240s || {
  kc describe pod -l app=e2e-web | tail -30; fail "e2e-web did not become ready once the Secret $ext_es existed"; }
web_env=$(kc get deploy e2e-web -o jsonpath='{.spec.template.spec.containers[0].env[*].name}')
for v in FILES_S3_ENDPOINT EXT_FILES_S3_ENDPOINT EXT_FILES_AWS_SECRET_ACCESS_KEY; do
  case " $web_env " in *" $v "*) ;; *) fail "e2e-web lacks the prefixed variable $v ($web_env)";; esac
done
echo "ok   Secret $ext_es has endpoint, bucket, region, forcePathStyle, accessKeyId and secretAccessKey; e2e-web runs with prefixed bucket variables"

# ---- Caches (spec 118): two Valkey nodes in dev, used by e2e-web; no operator, no route, nothing in a backup ----
cstep_name=""
cstep() { cstep_name="$*"; step "$*"; }
cfail() { fail "[$cstep_name] $*"; }

cstep "Caches: declare sessions (persistence in dev) and ratelimit (64Mi), both used by e2e-web (AC-118.15)"
# the external bucket steps above leave nothing uncommitted, but cplat refuses a dirty tree: commit first if there is anything
[ -z "$(git -C "$gitops_repo" status --porcelain)" ] || commit "before the caches"
ops_before=$(cd "$gitops_repo" && find operators -type f | sort)
$cplat resource add sessions --type cache --repo-dir "$gitops_repo" >/dev/null || cfail "resource add sessions --type cache failed"
commit "sessions"
$cplat resource add ratelimit --type cache --repo-dir "$gitops_repo" >/dev/null || cfail "resource add ratelimit --type cache failed"
commit "ratelimit"
(cd "$gitops_repo" && uv run --with pyyaml --with ruamel.yaml python - "$root" <<'PY'
import sys
sys.path.insert(0, f"{sys.argv[1]}/scripts/cplat")
import gitops
from pathlib import Path
app_dir = gitops.find_app(Path("."))
y, data = gitops.load(app_dir)
data["resources"]["sessions"]["instances"] = {"dev": {"persistence": True}}   # AOF on a volume in dev only
data["resources"]["ratelimit"]["memory"] = "64Mi"                              # maxmemory 53687091 bytes
web = gitops.components_of(data)["e2e-web"]
web["uses"] = [*(web.get("uses") or []), "sessions", "ratelimit"]              # two caches: the variables get the prefix
gitops.save(app_dir, y, data)
PY
uv run scripts/render.py) || cfail "render.py failed with the two caches"
commit "caches: sessions (persistence in dev), ratelimit (64Mi), used by e2e-web"
# AC-118.23: a cache needs no operator, CRD or chart: operators/ is exactly what it was
[ "$(cd "$gitops_repo" && find operators -type f | sort)" = "$ops_before" ] || cfail "the caches changed the files under operators/ (a cache has no operator; operators/apps must be unchanged)"
for c in sessions ratelimit; do
  [ -f "$gitops_repo/applications/e2e/addons/dev/$c/statefulset.yaml" ] || cfail "render did not write addons/dev/$c/statefulset.yaml"
done
web_rendered=$(kubectl kustomize "$gitops_repo/applications/e2e/overlays/dev/e2e-web") || cfail "kustomize of the e2e-web overlay failed"
for v in SESSIONS_REDIS_URL SESSIONS_REDIS_HOST SESSIONS_REDIS_PORT SESSIONS_REDIS_PASSWORD RATELIMIT_REDIS_URL RATELIMIT_REDIS_HOST RATELIMIT_REDIS_PORT RATELIMIT_REDIS_PASSWORD; do
  grep -q "name: $v\$" <<< "$web_rendered" || cfail "the e2e-web Deployment lacks $v"
done
for s in e2e-sessions-app e2e-ratelimit-app; do
  grep -q "name: $s\$" <<< "$web_rendered" || cfail "the e2e-web Deployment does not read the Secret $s"
done
echo "ok   operators/ unchanged (no operator for a cache); e2e-web gets SESSIONS_REDIS_* from e2e-sessions-app and RATELIMIT_REDIS_* from e2e-ratelimit-app"

cstep "Caches: apply both addons, wait for the Secrets (four keys) and the StatefulSets, then roll out e2e-web"
for c in sessions ratelimit; do
  kc apply -k "$gitops_repo/applications/e2e/addons/dev/$c" >/dev/null || cfail "applying addons/dev/$c failed"
done
for c in sessions ratelimit; do
  for _ in $(seq 1 40); do [ -n "$(secret_val e2e-$c-app password)" ] && break; sleep 3; done   # up to 120 s
  for k in url host port password; do
    [ -n "$(secret_val e2e-$c-app $k)" ] || {
      kc get externalsecrets.external-secrets.io e2e-$c-app -o yaml | tail -25
      kc get events --field-selector involvedObject.kind=ExternalSecret,involvedObject.name=e2e-$c-app | tail -10   # ESO names a problem only here
      cfail "the Secret e2e-$c-app lacks the key $k"; }
  done
done
for c in sessions ratelimit; do
  if ! kc rollout status statefulsets.apps/e2e-$c --timeout=180s 2>&1 | tee /dev/stderr; then
    kc get pods -l app.kubernetes.io/name=$c; kc describe pod e2e-$c-0 | tail -30; kc logs e2e-$c-0 -c valkey --tail=20 || true
    cfail "the StatefulSet e2e-$c did not become ready"
  fi
done
kc apply -k "$gitops_repo/applications/e2e/overlays/dev/e2e-web" >/dev/null || cfail "applying the e2e-web overlay failed"
if ! kc rollout status deploy/e2e-web --timeout=240s 2>&1 | tee /dev/stderr; then
  kc describe pod -l app=e2e-web | tail -30; cfail "e2e-web did not become ready with the cache variables"
fi
echo "ok   e2e-sessions and e2e-ratelimit run; e2e-web is ready with both caches"

cstep "Caches: the Secret holds a 32-character password and the designed url; a client needs the password (AC-118.11, AC-118.19)"
vcli='valkey-cli --no-auth-warning'
cx() { kc exec "e2e-$1-0" -c valkey -- sh -c "$2"; }   # the password is the container's own $VALKEY_PASSWORD
pw_sessions=$(secret_val e2e-sessions-app password)
pw_ratelimit=$(secret_val e2e-ratelimit-app password)
[ "${#pw_sessions}" = 32 ] && [ "${#pw_ratelimit}" = 32 ] || cfail "the generated passwords are not 32 characters (${#pw_sessions}, ${#pw_ratelimit})"
[ "$(cx sessions 'printf %s "$VALKEY_PASSWORD"')" = "$pw_sessions" ] || cfail "the server of e2e-sessions does not run with the password of the Secret e2e-sessions-app"
[ "$(secret_val e2e-sessions-app url)" = "redis://:${pw_sessions}@e2e-sessions.e2e-dev.svc:6379/0" ] || cfail "the url of e2e-sessions-app is not redis://:<password>@e2e-sessions.e2e-dev.svc:6379/0"
[ "$(secret_val e2e-sessions-app host)" = e2e-sessions.e2e-dev.svc ] && [ "$(secret_val e2e-sessions-app port)" = 6379 ] || cfail "host/port of e2e-sessions-app are not e2e-sessions.e2e-dev.svc and 6379"
out=$(cx sessions "$vcli ping" 2>&1 || true)
case "$out" in *NOAUTH*) ;; *) cfail "a client without a password was not refused with NOAUTH (got: $out)";; esac
out=$(cx sessions "$vcli -a wrong-password ping" 2>&1 || true)
case "$out" in *WRONGPASS*) ;; *) cfail "a client with a wrong password was not refused with WRONGPASS (got: $out)";; esac
out=$(cx sessions "$vcli -a \"\$VALKEY_PASSWORD\" ping" 2>&1 || true)
case "$out" in *PONG*) ;; *) cfail "PING with the password from the Secret did not answer PONG (got: $out)";; esac
echo "ok   password of 32 characters, url redis://:<password>@e2e-sessions.e2e-dev.svc:6379/0; NOAUTH without, WRONGPASS with a wrong, PONG with the password"

cstep "Caches: ratelimit reports maxmemory 53687091 (80 % of 64Mi) and allkeys-lru; the container limit is 64Mi (AC-118.6)"
out=$(cx ratelimit "$vcli -a \"\$VALKEY_PASSWORD\" CONFIG GET maxmemory" 2>&1 | tr '\n' ' ') || true
case "$out" in *53687091*) ;; *) cfail "ratelimit's maxmemory is not 53687091 (got: $out)";; esac
out=$(cx ratelimit "$vcli -a \"\$VALKEY_PASSWORD\" CONFIG GET maxmemory-policy" 2>&1 | tr '\n' ' ') || true
case "$out" in *allkeys-lru*) ;; *) cfail "ratelimit's maxmemory-policy is not allkeys-lru (got: $out)";; esac
[ "$(kc get pod e2e-ratelimit-0 -o jsonpath='{.spec.containers[0].resources.limits.memory}')" = 64Mi ] || cfail "the container memory limit of e2e-ratelimit-0 is not 64Mi"
echo "ok   maxmemory 53687091, allkeys-lru, limit 64Mi"

cstep "Caches: only ClusterIP Services on 6379 and no route (AC-118.8)"
for c in sessions ratelimit; do
  [ "$(kc get services e2e-$c -o jsonpath='{.spec.type}')" = ClusterIP ] || cfail "the Service e2e-$c is not of type ClusterIP"
  [ "$(kc get services e2e-$c -o jsonpath='{.spec.ports[*].port}')" = 6379 ] || cfail "the Service e2e-$c does not expose exactly 6379"
done
exposed=$(kc get services -o jsonpath='{range .items[*]}{.metadata.name}={.spec.type}{"\n"}{end}' | grep -E '^e2e-(sessions|ratelimit)[^=]*=(LoadBalancer|NodePort)' || true)
[ -z "$exposed" ] || cfail "a Service of a cache is exposed outside the cluster: $exposed"
routes=$(kc get httproutes.gateway.networking.k8s.io -o name | grep -E 'sessions|ratelimit' || true)
[ -z "$routes" ] || cfail "a route names a cache: $routes"
echo "ok   e2e-sessions and e2e-ratelimit are ClusterIP Services on 6379; no HTTPRoute names a cache"

# probe pods (plain Pods, not Deployments: the guard rails do not cover them) with e2e-web's own cache variables, in the cache's Valkey image
read -r -d '' cache_pod_py <<'PY' || true
import json, re, sys
name, image, script = sys.argv[1:4]
dep = json.load(sys.stdin)
env = [e for e in dep["spec"]["template"]["spec"]["containers"][0].get("env", []) if "valueFrom" in e and re.match(r"(SESSIONS|RATELIMIT)_REDIS_", e["name"])]
ctx = {"allowPrivilegeEscalation": False, "readOnlyRootFilesystem": True, "capabilities": {"drop": ["ALL"]}}
print(json.dumps({"apiVersion": "v1", "kind": "Pod", "metadata": {"name": name, "labels": {"app": "cacheprobe"}},
                  "spec": {"restartPolicy": "Never",
                           "securityContext": {"runAsNonRoot": True, "runAsUser": 999, "runAsGroup": 999, "seccompProfile": {"type": "RuntimeDefault"}},
                           "containers": [{"name": "valkey", "image": image, "command": ["sh", "-c", script], "env": env, "securityContext": ctx}]}}))
PY
cache_image=$(kc get statefulsets.apps e2e-sessions -o jsonpath='{.spec.template.spec.containers[0].image}')
cn=0
crun() { # script: runs it in a pod that carries e2e-web's SESSIONS_REDIS_* and RATELIMIT_REDIS_* variables; output in C_OUT
  local name phase=""
  cn=$((cn + 1)); name="cacheprobe-$cn"
  kc get deploy e2e-web -o json | python3 -c "$cache_pod_py" "$name" "$cache_image" "set -e; $1" | kc apply -f - >/dev/null || cfail "could not start the probe pod $name"
  for _ in $(seq 1 60); do   # up to 180 s
    phase=$(kc get pod "$name" -o jsonpath='{.status.phase}' 2>/dev/null || true)
    case "$phase" in Succeeded|Failed) break;; esac; sleep 3
  done
  C_OUT=$(kc logs "$name" 2>&1 || true)
  [ "$phase" = Succeeded ] || { C_OUT="$C_OUT (pod phase: ${phase:-unknown}; $(kc get pod "$name" -o jsonpath='{.status.containerStatuses[*].state.waiting.reason}' 2>/dev/null))"; kc describe pod "$name" | tail -15; }
  kc delete pod "$name" --wait=false >/dev/null 2>&1 || true
  [ "$phase" = Succeeded ]
}
c_field() { sed -n "s/^$1=//p" <<< "$C_OUT" | head -1; }

cstep "Caches: the component SETs a key and GETs the same value through SESSIONS_REDIS_URL (AC-118.15)"
payload="cache-$RANDOM-$RANDOM"
crun 'valkey-cli -u "$SESSIONS_REDIS_URL" SET probe:key '"$payload"' >/dev/null
echo "VALUE=$(valkey-cli -u "$SESSIONS_REDIS_URL" GET probe:key)"
echo "PING=$(valkey-cli -u "$RATELIMIT_REDIS_URL" PING)"' || cfail "the probe with e2e-web's variables failed: $(echo "$C_OUT" | tail -5 | tr '\n' ' ' | cut -c1-400)"
[ "$(c_field VALUE)" = "$payload" ] || cfail "GET through SESSIONS_REDIS_URL returned '$(c_field VALUE)', not '$payload'"
[ "$(c_field PING)" = PONG ] || cfail "PING through RATELIMIT_REDIS_URL answered '$(c_field PING)', not PONG"
echo "ok   SET and GET through SESSIONS_REDIS_URL returned $payload; RATELIMIT_REDIS_URL answers PONG"

cstep "Caches: filling ratelimit past maxmemory evicts keys without a restart; under noeviction a write gets OOM (AC-118.6)"
crun 'v=$(head -c 65536 /dev/zero | tr "\0" x)
i=0; while [ $i -lt 1200 ]; do echo "SET fill:$i $v"; i=$((i + 1)); done | valkey-cli -u "$RATELIMIT_REDIS_URL" >/dev/null
echo "EVICTED=$(valkey-cli -u "$RATELIMIT_REDIS_URL" INFO stats | tr -d "\r" | sed -n "s/^evicted_keys://p")"
echo "DBSIZE=$(valkey-cli -u "$RATELIMIT_REDIS_URL" DBSIZE)"
valkey-cli -u "$RATELIMIT_REDIS_URL" CONFIG SET maxmemory-policy noeviction >/dev/null
found=0
for i in $(seq 1 100); do
  r=$(echo "SET oom:$i $v" | valkey-cli -u "$RATELIMIT_REDIS_URL" 2>&1 || true)
  case "$r" in *OOM*) found=$i; break;; esac
done
echo "OOMAT=$found"' || cfail "the fill probe failed: $(echo "$C_OUT" | tail -5 | tr '\n' ' ' | cut -c1-400)"
ev=$(c_field EVICTED); dbs=$(c_field DBSIZE)
[ "${ev:-0}" -gt 0 ] 2>/dev/null || cfail "no key was evicted although ~75 MB went into a 64Mi server (evicted_keys '$ev')"
[ "${dbs:-1200}" -lt 1200 ] 2>/dev/null || cfail "DBSIZE is '$dbs' after 1200 writes: nothing was evicted"
[ "$(c_field OOMAT)" != 0 ] && [ -n "$(c_field OOMAT)" ] || { kc logs e2e-ratelimit-0 -c valkey --tail=20 || true; cfail "under noeviction no write got an OOM error in 100 tries"; }
restarts=$(kc get pod e2e-ratelimit-0 -o jsonpath='{.status.containerStatuses[0].restartCount}')
reasons=$(kc get pod e2e-ratelimit-0 -o jsonpath='{.status.containerStatuses[0].state.terminated.reason} {.status.containerStatuses[0].lastState.terminated.reason}')
if [ "$restarts" != 0 ] || [[ "$reasons" == *OOMKilled* ]]; then
  kc describe pod e2e-ratelimit-0 | tail -25; cfail "the server of ratelimit was restarted or OOMKilled while filling (restartCount $restarts, reasons '$reasons')"
fi
echo "ok   evicted_keys $ev, DBSIZE $dbs of 1200, a write under noeviction was refused after $(c_field OOMAT) tries; restartCount 0, not OOMKilled"

cstep "Caches: delete both pods; sessions keeps its key on the volume, ratelimit starts empty, the password stays (AC-118.7, AC-118.19)"
cx sessions "$vcli -a \"\$VALKEY_PASSWORD\" SET persist:key kept" | grep -q OK || cfail "could not SET a key in sessions"
cx ratelimit "$vcli -a \"\$VALKEY_PASSWORD\" SET persist:key lost" | grep -q OK || cfail "could not SET a key in ratelimit"
[ "$(kc get persistentvolumeclaims data-e2e-sessions-0 -o jsonpath='{.metadata.name}' 2>/dev/null)" = data-e2e-sessions-0 ] || cfail "the PVC data-e2e-sessions-0 does not exist"
[ -z "$(kc get persistentvolumeclaims -o name | grep ratelimit || true)" ] || cfail "ratelimit has a PersistentVolumeClaim"
[ -z "$(kc get pod e2e-ratelimit-0 -o jsonpath='{.spec.volumes[*].persistentVolumeClaim.claimName}')" ] || cfail "the pod of ratelimit mounts a PersistentVolumeClaim"
uid_s=$(kc get pod e2e-sessions-0 -o jsonpath='{.metadata.uid}'); uid_r=$(kc get pod e2e-ratelimit-0 -o jsonpath='{.metadata.uid}')
sleep 2   # the append-only file is synced every second
kc delete pod e2e-sessions-0 e2e-ratelimit-0 --wait=true --timeout=90s || cfail "could not delete the cache pods"
for _ in $(seq 1 60); do   # up to 180 s for the StatefulSet controller to create the new pods
  n_s=$(kc get pod e2e-sessions-0 -o jsonpath='{.metadata.uid}' 2>/dev/null || true); n_r=$(kc get pod e2e-ratelimit-0 -o jsonpath='{.metadata.uid}' 2>/dev/null || true)
  [ -n "$n_s" ] && [ "$n_s" != "$uid_s" ] && [ -n "$n_r" ] && [ "$n_r" != "$uid_r" ] && break; sleep 3
done
[ -n "$n_s" ] && [ "$n_s" != "$uid_s" ] && [ -n "$n_r" ] && [ "$n_r" != "$uid_r" ] || cfail "the cache pods were not recreated with new UIDs"
kc wait --for=condition=Ready pod/e2e-sessions-0 pod/e2e-ratelimit-0 --timeout=150s || { kc get pods -l app.kubernetes.io/part-of=e2e; kc describe pod e2e-sessions-0 e2e-ratelimit-0 | tail -40; cfail "the cache pods did not become Ready again"; }
got=$(cx sessions "$vcli -a \"\$VALKEY_PASSWORD\" GET persist:key" 2>&1) || true
[ "$got" = kept ] || { kc logs e2e-sessions-0 -c valkey --tail=20 || true; cfail "sessions lost its key across the restart of its pod (GET: '$got')"; }
[ "$(cx ratelimit "$vcli -a \"\$VALKEY_PASSWORD\" DBSIZE" 2>&1)" = 0 ] || cfail "ratelimit is not empty after its pod came back (DBSIZE)"
[ "$(secret_val e2e-sessions-app password)" = "$pw_sessions" ] && [ "$(secret_val e2e-ratelimit-app password)" = "$pw_ratelimit" ] || cfail "a password changed across the restart"
kc apply -k "$gitops_repo/applications/e2e/addons/dev/sessions" >/dev/null && kc apply -k "$gitops_repo/applications/e2e/addons/dev/ratelimit" >/dev/null || cfail "re-applying the cache addons failed"
for c in sessions ratelimit; do kc annotate externalsecrets.external-secrets.io e2e-$c-app force-sync="$(date +%s)" --overwrite >/dev/null || cfail "could not annotate the ExternalSecret e2e-$c-app"; done
sleep 10   # ESO reconciles the annotated ExternalSecrets
[ "$(secret_val e2e-sessions-app password)" = "$pw_sessions" ] && [ "$(secret_val e2e-ratelimit-app password)" = "$pw_ratelimit" ] || cfail "a password changed after re-applying the addons and a force-sync"
echo "ok   sessions kept its key (PVC data-e2e-sessions-0), ratelimit is empty and has no volume; the passwords survived the restart, the re-apply and force-sync"

cstep "Caches: platform doctor names no cache, valkey, sessions or ratelimit prerequisite (AC-118.15, AC-118.23)"
doc_json="$work/doctor.json"
timeout 180 $cplat platform doctor --repo "$gitops_repo" --json > "$doc_json" 2> "$work/doctor.err" || true   # any exit code: only its rows matter
python3 - "$doc_json" <<'PY' || { tail -5 "$work/doctor.err" || true; cfail "doctor output unreadable, or a row mentions a cache (see above)"; }
import json, re, sys
rows = json.load(open(sys.argv[1]))
bad = [r for r in rows if re.search(r"cache|valkey|sessions|ratelimit", f"{r.get('name', '')} {r.get('detail', '')}", re.I)]
for r in bad:
    print("doctor row names a cache:", r, file=sys.stderr)
sys.exit(1 if bad else 0)
PY
echo "ok   platform doctor lists no row for a cache"

# ---- Ship a spec: dev is verified, the build is promoted to staging, applied and verified, the run ends ----
sns=e2e-staging
dev_url="http://e2e-api.e2e-dev.localhost:$port"
staging_url="http://e2e-api.e2e-staging.localhost:$port"

step "Write and approve a spec in the service repo, start its ship run"
$cplat spec --repo "$api_repo" new "probe the e2e api" >/dev/null
uv run python - "$api_repo" <<'PY'
import re, sys
from pathlib import Path
spec = next(Path(sys.argv[1], "docs", "specs").glob("001-*/spec.md"))
text = spec.read_text()
ac = "## Acceptance criteria\n\n- **AC-001.1** Given the deployed service, when /api/info is requested, then it names the service e2e-api.\n"
spec.write_text(re.sub(r"## Acceptance criteria\n\n<!--.*?-->\n", lambda _: ac, text, count=1, flags=re.S))
PY
$cplat spec --repo "$api_repo" approve 001 >/dev/null
(cd "$api_repo" && $cplat component ship start 001 --no-merge)

step "Verify dev with the service's smoke tests"
(cd "$api_repo" && $cplat instance verify dev --base-url "$dev_url" --no-retry)

step "Promote the built commit to staging: tag the image like CI does, pin it, render, apply, verify"
sha=$(git -C "$api_repo" rev-parse HEAD)
docker tag "localhost:$regport/e2e-api:latest" "localhost:$regport/e2e-api:sha-$sha"
docker push -q "localhost:$regport/e2e-api:sha-$sha" >/dev/null
$cplat instance promote e2e-api --to staging --sha "$sha" --no-verify --repo-dir "$gitops_repo" >/dev/null
printf 'sk_test_e2e' | $cplat instance secret set e2e-api/staging e2e-api-stripe STRIPE_KEY --value-stdin --repo-dir "$gitops_repo" --context k3d-$cluster >/dev/null
grep -q "sha-$sha" "$work/e2e-gitops/applications/e2e/overlays/staging/e2e-api/kustomization.yaml" || fail "the staging overlay is not pinned to sha-$sha"
kubectl --context k3d-$cluster apply -n $sns -k "$work/e2e-gitops/applications/e2e/addons/staging/postgres"
for _ in $(seq 1 80); do
  [ "$(kubectl --context k3d-$cluster -n $sns get cluster e2e-postgres -o jsonpath='{.status.phase}' 2>/dev/null)" = "Cluster in healthy state" ] && break; sleep 5
done
[ "$(kubectl --context k3d-$cluster -n $sns get cluster e2e-postgres -o jsonpath='{.status.phase}')" = "Cluster in healthy state" ] || fail "the staging Postgres cluster did not become healthy"
apply_bucket staging $sns   # e2e-api in staging reads the bucket's Secret, so the staging bucket comes first
store_ready $sns
kubectl --context k3d-$cluster apply -n $sns -k "$work/e2e-gitops/applications/e2e/overlays/staging/e2e-api"
kubectl --context k3d-$cluster -n $sns rollout status deploy/e2e-api --timeout=240s || fail "e2e-api did not become ready in staging"
kubectl --context k3d-$cluster -n $sns get deploy e2e-api -o jsonpath='{.spec.template.spec.containers[0].image}' | grep -q "sha-$sha" || fail "staging runs another image than the pinned one"
(cd "$api_repo" && $cplat instance verify staging --base-url "$staging_url" --no-retry)
probe "$staging_url/api/info" '"service":"e2e-api"'

step "Bucket in staging: its own store and keys, versioning off (only the latest version stays), dev's keys are refused (AC-116.5, AC-116.7)"
s3_retry 12 "bucket e2e-files is not reachable from e2e-api in staging" $sns e2e-api '$A s3api head-bucket --bucket "$S3_BUCKET"'
spayload="staging-$RANDOM-$RANDOM"
s3must "e2e-api writes and reads in staging" $sns e2e-api 'printf %s '"$spayload"' > /tmp/in
$A s3api put-object --bucket "$S3_BUCKET" --key '$H' --body /tmp/in >/dev/null
$A s3api get-object --bucket "$S3_BUCKET" --key '$H' /tmp/out >/dev/null
echo "CONTENT=$(cat /tmp/out)"
printf one > /tmp/v1; printf two > /tmp/v2
echo "STATUS=$($A s3api get-bucket-versioning --bucket "$S3_BUCKET" --query Status --output text)"
$A s3api put-object --bucket "$S3_BUCKET" --key ver/v.txt --body /tmp/v1 >/dev/null
$A s3api put-object --bucket "$S3_BUCKET" --key ver/v.txt --body /tmp/v2 >/dev/null
$A s3api get-object --bucket "$S3_BUCKET" --key ver/v.txt /tmp/new >/dev/null
echo "NEW=$(cat /tmp/new)"
echo "COUNT=$($A s3api list-object-versions --bucket "$S3_BUCKET" --prefix ver/v.txt --query "length(Versions)" --output text)"'
s3_same "e2e-api read-back in staging" "$spayload" "$(s3_field CONTENT)"
s3_same "versioning status in staging" Suspended "$(s3_field STATUS)"
s3_same "latest version in staging" two "$(s3_field NEW)"
s3_same "version count in staging (versioning off keeps the latest only)" 1 "$(s3_field COUNT)"
echo "ok   staging reads back its own object; with versioning off an overwrite leaves one version"
# dev's pod (dev's keys) against staging's endpoint and bucket: the store of staging must refuse them
stg_endpoint=$(kn $sns get secret e2e-files-app -o jsonpath='{.data.endpoint}' | base64 -d)
if s3run $ns e2e-api 'S3_ENDPOINT='"$stg_endpoint"'; A="aws --endpoint-url $S3_ENDPOINT"; $A s3api get-object --bucket "$S3_BUCKET" --key '$H' /tmp/out'; then
  fail "dev's keys were accepted by staging's store at $stg_endpoint (cross-environment access)"
fi
case "$(s3_why "$S3_OUT")" in
  "access denied") echo "ok   dev's keys are refused by staging's endpoint: $(echo "$S3_OUT" | tail -2 | tr '\n' ' ' | cut -c1-160)";;
  *) fail "dev's keys against staging's endpoint: expected access denied, got $(s3_why "$S3_OUT"): $(echo "$S3_OUT" | tail -5 | tr '\n' ' ' | cut -c1-400)";;
esac

step "End the ship run"
(cd "$api_repo" && $cplat component ship finish)

# ---- Backups (AC-117.24): dev backs up postgres and the namespace into the bucket backups; a point-in-time restore and an environment restore ----
# These steps come last on purpose: restoring changes dev's database cluster and replaces volumes, which the ship steps above must not see.
bstep_name=""
bstep() { bstep_name="$*"; step "$*"; }
bfail() { fail "[$bstep_name] $*"; }
rargs=(--repo-dir "$gitops_repo" --context "k3d-$cluster")
vn() { kubectl --context k3d-$cluster -n velero "$@"; }

bstep "Backups: declare the bucket backups, instances.dev.backup on postgres, environments.dev.backup and the external component e2e-files"
# The staging promote above pins and renders without a commit; cplat writes need a clean tree.
[ -z "$(git -C "$gitops_repo" status --porcelain)" ] || commit "promote e2e-api to staging"
$cplat resource add backups --type bucket --repo-dir "$gitops_repo" >/dev/null
commit "backups"   # each cplat write starts from a clean tree
# e2e-files: an external component (a kustomize package in the gitops repo): a StatefulSet with a 1Gi volume `data`, busybox, non-root
pkg="$gitops_repo/applications/e2e/external/e2e-files"
mkdir -p "$pkg"
cat > "$pkg/kustomization.yaml" <<'YAML'
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - statefulset.yaml
YAML
cat > "$pkg/statefulset.yaml" <<'YAML'
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: e2e-files
  labels: {app: e2e-files}
spec:
  serviceName: e2e-files
  replicas: 1
  selector:
    matchLabels: {app: e2e-files}
  template:
    metadata:
      labels: {app: e2e-files}
    spec:
      securityContext: {runAsNonRoot: true, runAsUser: 1000, runAsGroup: 1000, fsGroup: 1000, seccompProfile: {type: RuntimeDefault}}
      containers:
        - name: files
          image: docker.io/library/busybox
          command: [sh, -c, "while true; do sleep 3600; done"]
          securityContext: {allowPrivilegeEscalation: false, readOnlyRootFilesystem: true, capabilities: {drop: [ALL]}}
          volumeMounts:
            - {name: data, mountPath: /data}
  volumeClaimTemplates:
    - metadata: {name: data}
      spec:
        accessModes: [ReadWriteOnce]
        resources: {requests: {storage: 1Gi}}
YAML
(cd "$gitops_repo" && uv run --with pyyaml --with ruamel.yaml python - "$root" <<'PY'
import sys
sys.path.insert(0, f"{sys.argv[1]}/scripts/cplat")
import gitops
from pathlib import Path
app_dir = gitops.find_app(Path("."))
y, data = gitops.load(app_dir)
components = gitops.components_of(data)
components["e2e-web"]["uses"] = [*(components["e2e-web"].get("uses") or []), "backups"]      # the target must be used by a component in dev
pg = data["resources"]["postgres"]
instances = pg.get("instances") or {}
instances["dev"] = {**(instances.get("dev") or {}), "backup": {"to": "backups"}}              # instances.dev.backup
pg["instances"] = instances
data["environments"]["dev"]["backup"] = {"to": "backups"}                                     # environments.dev.backup
components["e2e-files"] = {"type": "service", "lang": "unknown", "repo": "e2e/e2e-files", "image": "docker.io/library/busybox",
                           "external": {"kustomize": "external/e2e-files"}, "instances": {"dev": {}}}
gitops.save(app_dir, y, data)
PY
uv run scripts/render.py)
commit "backups: dev backs up postgres and the namespace into backups; e2e-files"

bstep "Backups: render writes the three operators and cluster-up installed exactly their pins"
[ -f "$gitops_repo/operators/root.yaml" ] || bfail "render did not write operators/root.yaml"
for op in plugin-barman-cloud cert-manager velero; do
  f="$gitops_repo/operators/apps/$op.yaml"
  [ -f "$f" ] || bfail "render did not write operators/apps/$op.yaml"
  pin=$(sed -n 's/^[[:space:]]*targetRevision:[[:space:]]*["'"'"']\{0,1\}\([^"'"'"'[:space:]]*\).*/\1/p' "$f" | head -1)
  have=$(kubectl --context k3d-$cluster -n kube-system get helmchart $op -o jsonpath='{.spec.version}' 2>/dev/null || true)
  [ -n "$pin" ] && [ "$have" = "$pin" ] || bfail "the installed chart $op is '$have', operators/apps/$op.yaml pins '$pin'"
  echo "ok   operators/apps/$op.yaml pins $op $pin, which is installed"
done
kubectl --context k3d-$cluster get crd objectstores.barmancloud.cnpg.io schedules.velero.io >/dev/null || bfail "the Barman Cloud or Velero CRDs are not installed"
# AC-118.14: the rendered Schedule leaves every cache out by name (with or without persistence)
uv run --with pyyaml python - "$gitops_repo/applications/e2e/backup/dev/schedule.yaml" <<'PY' || bfail "the rendered Schedule e2e-dev does not leave sessions and ratelimit out (NotIn)"
import sys, yaml
sched = yaml.safe_load(open(sys.argv[1]))
exprs = sched["spec"]["template"]["labelSelector"]["matchExpressions"]
values = [v for e in exprs if e["operator"] == "NotIn" and e["key"] == "app.kubernetes.io/name" for v in e["values"]]
sys.exit(0 if {"sessions", "ratelimit"} <= set(values) else 1)
PY
echo "ok   the Schedule e2e-dev leaves sessions and ratelimit out by name (NotIn)"

bstep "Backups: apply the bucket backups, postgres with its plugin and ObjectStore, backup/dev, e2e-files and e2e-web"
apply_bucket dev $ns backups
store_ready $ns backups
kubectl --context k3d-$cluster apply -n $ns -k "$work/e2e-gitops/applications/e2e/addons/dev/postgres" >/dev/null || bfail "applying the postgres addon with backup failed"
kubectl --context k3d-$cluster apply -k "$work/e2e-gitops/applications/e2e/backup/dev" >/dev/null || bfail "applying backup/dev failed"   # no -n: its objects carry their namespaces
kubectl --context k3d-$cluster apply -n $ns -k "$work/e2e-gitops/applications/e2e/overlays/dev/e2e-files" >/dev/null || bfail "applying the e2e-files overlay failed"
kubectl --context k3d-$cluster apply -n $ns -k "$work/e2e-gitops/applications/e2e/overlays/dev/e2e-web" >/dev/null || bfail "applying the e2e-web overlay failed"
# the credentials of the environment backup come from an ExternalSecret in velero (ESO names a missing key only in its events)
bk_secret=e2e-dev-backup
for _ in $(seq 1 40); do [ -n "$(vn get secret $bk_secret -o jsonpath='{.data.cloud}' 2>/dev/null)" ] && break; sleep 3; done   # up to 120 s
[ -n "$(vn get secret $bk_secret -o jsonpath='{.data.cloud}' 2>/dev/null)" ] || {
  vn get externalsecret $bk_secret -o yaml | tail -25
  vn get events --field-selector "involvedObject.name=$bk_secret" | tail -10
  bfail "the Secret $bk_secret in velero (the backup credentials) did not appear"; }
for _ in $(seq 1 60); do [ "$(vn get backupstoragelocation e2e-dev -o jsonpath='{.status.phase}' 2>/dev/null)" = Available ] && break; sleep 5; done   # up to 300 s
[ "$(vn get backupstoragelocation e2e-dev -o jsonpath='{.status.phase}' 2>/dev/null)" = Available ] || {
  vn get backupstoragelocation e2e-dev -o yaml | tail -25; bfail "the BackupStorageLocation e2e-dev is not Available"; }
kc rollout status statefulset/e2e-files --timeout=240s || { kc describe pod -l app=e2e-files | tail -30; bfail "e2e-files did not become ready"; }
kc rollout status deploy/e2e-web --timeout=240s || { kc describe pod -l app=e2e-web | tail -30; bfail "e2e-web did not become ready with the bucket backups"; }
status_state() { # backup.state of the postgres/dev row of `system status --json`
  $cplat system status --json "${rargs[@]}" 2>/dev/null | python3 -c '
import json, sys
print(next(r for r in json.load(sys.stdin)["backups"]["resource_instances"] if r["resource"] == "postgres" and r["environment"] == "dev")["backup"]["state"])' 2>/dev/null
}
# Adding backup restarts the instance to load the plugin, so the immediate Backup can fail ("requested plugin is not available") and
# CloudNativePG never retries it: wait until the plugin is loaded, then accept a completed Backup or the status state pending.
archiving_on() { [ "$(kc get cluster "$1" -o jsonpath='{.status.conditions[?(@.type=="ContinuousArchiving")].status}' 2>/dev/null)" = True ]; }
backups_done() { kc get backups.postgresql.cnpg.io -o jsonpath='{range .items[*]}{.status.phase}{"\n"}{end}' 2>/dev/null | grep -qx completed; }
for _ in $(seq 1 100); do archiving_on e2e-postgres && break; sleep 5; done   # up to 500 s
archiving_on e2e-postgres || { kc get backups.postgresql.cnpg.io; kc describe cluster e2e-postgres | tail -30; bfail "the plugin was not loaded on e2e-postgres (ContinuousArchiving is not True)"; }
if backups_done; then echo "ok   the immediate base backup of postgres completed"
elif [ "$(status_state)" = pending ]; then echo "ok   postgres/dev status is pending (first backup pending; the on-demand backup follows)"
else
  for _ in $(seq 1 24); do backups_done && break; [ "$(status_state)" = pending ] && break; sleep 5; done
  if backups_done; then echo "ok   the immediate base backup of postgres completed"
  elif [ "$(status_state)" = pending ]; then echo "ok   postgres/dev status is pending (first backup pending; the on-demand backup follows)"
  else kc get backups.postgresql.cnpg.io; bfail "postgres has neither a completed base backup nor the state pending"; fi
fi
for _ in $(seq 1 60); do [ "$(kc get cluster e2e-postgres -o jsonpath='{.status.phase}' 2>/dev/null)" = "Cluster in healthy state" ] && break; sleep 5; done
[ "$(kc get cluster e2e-postgres -o jsonpath='{.status.phase}')" = "Cluster in healthy state" ] || bfail "the Postgres cluster is not healthy with the plugin"

status_field() { # path in the postgres/dev row of `system status --json` (backup.latest, previous.name, ...); empty when null
  $cplat system status --json "${rargs[@]}" 2>/dev/null | python3 -c '
import json, sys
row = next(r for r in json.load(sys.stdin)["backups"]["resource_instances"] if r["resource"] == "postgres" and r["environment"] == "dev")
v = row
for k in sys.argv[1].split("."):
    v = (v or {}).get(k)
print("" if v is None else v)' "$1"
}
env_field() { # field of the dev row in backups.environments
  $cplat system status --json "${rargs[@]}" 2>/dev/null | python3 -c '
import json, sys
row = next(r for r in json.load(sys.stdin)["backups"]["environments"] if r["environment"] == "dev")
v = row["backup"].get(sys.argv[1])
print("" if v is None else v)' "$1"
}
not_before() { # a b: success when the RFC 3339 time a is not before b (fractions ignored)
  python3 -c '
import re, sys
from datetime import datetime
t = lambda s: datetime.fromisoformat(re.sub(r"\.\d+", "", s).replace("Z", "+00:00"))
sys.exit(0 if t(sys.argv[1]) >= t(sys.argv[2]) else 1)' "$1" "$2"
}

bstep "Database backup: /resource:backup completes and system status shows last_success (AC-117.31)"
for _ in $(seq 1 60); do [ "$(status_field backup.archiving)" = ok ] && break; sleep 5; done   # WAL archiving works
[ "$(status_field backup.archiving)" = ok ] || bfail "postgres/dev does not archive its WAL (state: $(status_field backup.state), error: $(status_field backup.error))"
if ! out=$($cplat resource backup postgres --env dev "${rargs[@]}" 2>&1); then bfail "resource backup failed: $out"; fi
case "$out" in *"backup completed: postgres/dev at "*) ;; *) bfail "resource backup did not say 'backup completed': $out";; esac
at=$(sed -n 's/^backup completed: postgres\/dev at \([^ ]*\) .*/\1/p' <<< "$out")
[ -n "$at" ] || bfail "no time in the output of resource backup: $out"
[ "$(status_field backup.last_success)" = "$at" ] || bfail "system status last_success '$(status_field backup.last_success)' is not the time of the backup '$at'"
echo "ok   $out"

bstep "Database point in time: row A, the time T, row B; restore to T as a second instance (AC-117.8)"
pg_uri=$(secret_val e2e-postgres-app uri)
pg() { kc exec e2e-postgres-1 -c postgres -- psql "$pg_uri" -tAc "$1"; }
pg 'create table e2e_rows (v text)' >/dev/null
pg "insert into e2e_rows values ('A')" >/dev/null
sleep 2
T=$(pg "select to_char(clock_timestamp() at time zone 'utc', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"')")   # the database's own clock: no skew with the host
sleep 2
pg "insert into e2e_rows values ('B')" >/dev/null
[ "$(pg "select string_agg(v, ',' order by v) from e2e_rows")" = "A,B" ] || bfail "the database does not hold A and B before the restore"
sleep 1
kc exec e2e-postgres-1 -c postgres -- psql -d postgres -tAc 'select pg_switch_wal()' >/dev/null || bfail "pg_switch_wal failed"   # archive the segment with B and T now
for _ in $(seq 1 60); do l=$(status_field backup.latest); [ -n "$l" ] && not_before "$l" "$T" && break; sleep 5; done   # up to 300 s
l=$(status_field backup.latest)
{ [ -n "$l" ] && not_before "$l" "$T"; } || bfail "the restore points of postgres/dev stop at '${l:-none}', before T $T"
if ! out=$($cplat resource restore postgres --env dev --to "$T" "${rargs[@]}" 2>&1); then bfail "restore to $T failed: $out"; fi
case "$out" in *"restored postgres/dev to $T as e2e-postgres-g1"*) ;; *) bfail "restore did not report the second instance e2e-postgres-g1: $out";; esac
echo "ok   point-in-time restore to $T: $(echo "$out" | head -1)"

# a probe pod (not a Deployment: the guard rails do not cover it) with e2e-api's own database variables
read -r -d '' db_pod_py <<'PY' || true
import json, sys
name, image, script = sys.argv[1:4]
dep = json.load(sys.stdin)
names = ("DATABASE_URL", "PGHOST", "PGPORT", "PGDATABASE", "PGUSER", "PGPASSWORD")
env = [e for e in dep["spec"]["template"]["spec"]["containers"][0].get("env", []) if "valueFrom" in e and e["name"] in names]
print(json.dumps({"apiVersion": "v1", "kind": "Pod", "metadata": {"name": name, "labels": {"app": "dbprobe"}},
                  "spec": {"restartPolicy": "Never", "containers": [{"name": "psql", "image": image, "command": ["sh", "-c", script], "env": env}]}}))
PY
dbn=0
db_rows() { # reads the table e2e_rows with e2e-api's database variables; the rows in DB_OUT, one line
  local name phase="" image
  dbn=$((dbn + 1)); name="dbprobe-$dbn"
  image=$(kc get clusters.postgresql.cnpg.io e2e-postgres-g1 -o jsonpath='{.spec.imageName}')
  kc get deploy e2e-api -o json | python3 -c "$db_pod_py" "$name" "$image" 'psql "$DATABASE_URL" -tAc "select v from e2e_rows order by v"' | kc apply -f - >/dev/null || bfail "could not start the probe pod $name"
  for _ in $(seq 1 60); do   # up to 180 s (the first run pulls the image)
    phase=$(kc get pod "$name" -o jsonpath='{.status.phase}' 2>/dev/null || true)
    case "$phase" in Succeeded|Failed) break;; esac; sleep 3
  done
  DB_OUT=$(kc logs "$name" 2>&1 | tr '\n' ' ' | sed 's/ *$//' || true)
  kc delete pod "$name" --wait=false >/dev/null 2>&1 || true
  [ "$phase" = Succeeded ]
}

bstep "Database switch: a component reads the restored row A and not B (AC-117.9)"
# streamed (tee) and bounded, so a slow plugin wait shows in the log instead of running into the job's timeout
if ! out=$(timeout 900 $cplat resource restore postgres --env dev --switch "${rargs[@]}" 2>&1 | tee /dev/stderr); then
  kc get clusters.postgresql.cnpg.io; kc get backups.postgresql.cnpg.io; bfail "switch failed or took longer than 15 minutes: $out"; fi
case "$out" in *"switched postgres/dev to e2e-postgres-g1"*) ;; *) bfail "switch did not report e2e-postgres-g1: $out";; esac
sb_cluster=$(kc get scheduledbackup.postgresql.cnpg.io e2e-postgres -o jsonpath='{.spec.cluster.name}' 2>&1) || bfail "after the switch the ScheduledBackup e2e-postgres is missing (AC-117.13): $sb_cluster"
[ "$sb_cluster" = e2e-postgres-g1 ] || bfail "after the switch the ScheduledBackup e2e-postgres targets '$sb_cluster', not e2e-postgres-g1 (AC-117.13)"
g1_backup() { kc get backups.postgresql.cnpg.io -o jsonpath='{range .items[*]}{.spec.cluster.name}{" "}{.status.phase}{"\n"}{end}' 2>/dev/null | grep -qx 'e2e-postgres-g1 completed'; }
for _ in $(seq 1 120); do g1_backup && break; sleep 5; done   # up to 600 s
g1_backup || { kc get backups.postgresql.cnpg.io; bfail "no completed base backup of e2e-postgres-g1 after the switch (the first backup must not be lost to the plugin race)"; }
echo "ok   e2e-postgres-g1 has a completed base backup after the switch"
kc rollout status deploy/e2e-api --timeout=240s || { kc describe pod -l app=e2e-api | tail -30; bfail "e2e-api did not become ready on the restored database"; }
rows_ok=""
for _ in $(seq 1 10); do db_rows && rows_ok=1 && break; sleep 5; done
[ -n "$rows_ok" ] || bfail "the probe pod with e2e-api's database variables failed: $DB_OUT"
[ "$DB_OUT" = A ] || bfail "after the switch the restored database must hold row A and must not hold row B (read: '$DB_OUT')"
echo "ok   restored database read through e2e-api's variables: row A, and not B (point in time $T)"

bstep "Database discard: the previous instance and its volumes go; system status no longer shows previous (AC-117.9)"
[ "$(status_field previous.name)" = e2e-postgres ] || bfail "system status does not show e2e-postgres as previous after the switch (shows '$(status_field previous.name)')"
if ! out=$($cplat resource restore postgres --env dev --discard "${rargs[@]}" 2>&1); then bfail "discard failed: $out"; fi
case "$out" in *"discarded e2e-postgres (previous)"*) ;; *) bfail "discard did not report e2e-postgres (previous): $out";; esac
if kc get cluster e2e-postgres >/dev/null 2>&1; then bfail "the cluster e2e-postgres still exists after the discard"; fi
[ -z "$(status_field previous.name)" ] || bfail "system status still shows previous '$(status_field previous.name)' after the discard"
echo "ok   previous discarded; e2e-postgres-g1 stays active"

bstep "Environment backup: a file on the volume of e2e-files-0 and an object in the bucket files, then a Velero Backup of dev"
file_payload="file-$RANDOM-$RANDOM"
kc exec e2e-files-0 -- sh -c "printf %s '$file_payload' > /data/hello.txt && sync" || bfail "could not write the file on the volume of e2e-files-0"
object_payload="object-$RANDOM-$RANDOM"
s3must "e2e-api writes an object into files" $ns e2e-api 'printf %s '"$object_payload"' > /tmp/in
$A s3api put-object --bucket "$S3_BUCKET" --key backup/object.txt --body /tmp/in >/dev/null'
sleep 10   # let the store write its volume files before the file-system backup reads them
bname="e2e-dev-manual-$(date +%Y%m%d%H%M%S)"
vn get schedules.velero.io e2e-dev >/dev/null || bfail "the Velero Schedule e2e-dev does not exist"
# kind: Backup (velero.io/v1) made from the Schedule's template, labelled like a scheduled one
vn get schedules.velero.io e2e-dev -o json | python3 -c 'import json, sys
s = json.load(sys.stdin)
print(json.dumps({"apiVersion": "velero.io/v1", "kind": "Backup", "metadata": {"name": sys.argv[1], "namespace": "velero",
                  "labels": {"velero.io/schedule-name": "e2e-dev"}}, "spec": s["spec"]["template"]}))' "$bname" | vn apply -f - >/dev/null || bfail "could not create the Velero Backup $bname"
bphase() { vn get backups.velero.io "$bname" -o jsonpath='{.status.phase}' 2>/dev/null || true; }
for _ in $(seq 1 180); do case "$(bphase)" in Completed|PartiallyFailed|Failed|FailedValidation) break;; esac; sleep 5; done   # up to 900 s
[ "$(bphase)" = Completed ] || { vn describe backups.velero.io "$bname" | tail -30; vn logs deploy/velero --tail=30; bfail "the Velero Backup $bname is '$(bphase)', not Completed"; }
pvb=$(vn get podvolumebackups -l velero.io/backup-name="$bname" -o jsonpath='{.items[*].spec.volume}' 2>/dev/null || true)
case " $pvb " in *" data "*) ;; *) bfail "the Backup $bname holds no volume data of e2e-files (volumes: '$pvb')";; esac
# AC-118.14: sessions has a volume (persistence: true) and still no pod volume backup names it
pvb_pods=$(vn get podvolumebackups.velero.io -l velero.io/backup-name="$bname" -o jsonpath='{.items[*].spec.pod.name}' 2>/dev/null || true)
case " $pvb_pods " in *" e2e-files-0 "*) ;; *) bfail "the Backup $bname holds no pod volume backup of e2e-files-0 (pods: '$pvb_pods')";; esac
case " $pvb_pods " in *e2e-sessions-0*|*e2e-ratelimit-0*) bfail "the Backup $bname holds cache data (pod volume backups of: $pvb_pods)";; esac
vn get schedules.velero.io e2e-dev -o jsonpath='{.spec.template.labelSelector.matchExpressions[*].values}' | grep -q sessions || bfail "the live Schedule e2e-dev does not leave sessions out (NotIn)"
for _ in $(seq 1 24); do [ -n "$(env_field last_success)" ] && break; sleep 5; done
[ -n "$(env_field last_success)" ] || bfail "system status shows no last_success for the environment dev after the backup (state: $(env_field state))"
echo "ok   Velero Backup $bname completed; system status last_success $(env_field last_success)"

bstep "Environment restore: delete the file and the object; without --replace the restore refuses and lists the volumes (AC-117.20)"
kc exec e2e-files-0 -- rm /data/hello.txt || bfail "could not delete the file"
s3must "e2e-api deletes the object" $ns e2e-api '$A s3api delete-object --bucket "$S3_BUCKET" --key backup/object.txt >/dev/null
$A s3api list-objects-v2 --bucket "$S3_BUCKET" --prefix backup/ --query "Contents[].Key" --output text > /tmp/keys
echo "KEYS=$(cat /tmp/keys)"'
case "$(s3_field KEYS)" in *backup/object.txt*) bfail "the object is still listed after its delete";; esac
db_uid=$(kc get clusters.postgresql.cnpg.io e2e-postgres-g1 -o jsonpath='{.metadata.uid}')
[ -n "$db_uid" ] || bfail "no cluster e2e-postgres-g1 before the restore"
if out=$($cplat system restore dev --backup "$bname" "${rargs[@]}" 2>&1); then bfail "system restore without --replace succeeded although the volumes exist: $out"; fi
case "$out" in *"volumes of $bname still exist in $ns"*"data-e2e-files-0"*) ;; *) bfail "the refusal does not list the volumes (wanted 'volumes of $bname still exist in $ns: ... data-e2e-files-0'): $out";; esac
case "$out" in *"databases are not part of environment backups"*) ;; *) bfail "the refusal lacks 'databases are not part of environment backups': $out";; esac
case "$out" in *data-e2e-sessions-0*) bfail "the refusal lists the volume data-e2e-sessions-0 of a cache, which no backup holds: $out";; esac
echo "ok   restore without --replace refused: $(echo "$out" | head -1 | cut -c1-200)"

bstep "Environment restore: --replace stops the workloads, replaces their volumes from the backup and starts them again (AC-117.20)"
if ! out=$($cplat system restore dev --backup "$bname" --replace "${rargs[@]}" 2>&1); then bfail "system restore --replace failed: $out"; fi
case "$out" in *"restored $bname into $ns"*) ;; *) bfail "system restore --replace did not report 'restored $bname into $ns': $out";; esac
case "$out" in *"databases are not part of environment backups"*) ;; *) bfail "the output lacks 'databases are not part of environment backups': $out";; esac
kc rollout status statefulset/e2e-files --timeout=300s || { kc describe pod -l app=e2e-files | tail -30; bfail "e2e-files did not start again"; }
store_ready $ns files
got=""
for _ in $(seq 1 30); do got=$(kc exec e2e-files-0 -- cat /data/hello.txt 2>/dev/null || true); [ -n "$got" ] && break; sleep 3; done
[ "$got" = "$file_payload" ] || bfail "the file on the volume: content differs after the restore (wanted '$file_payload', got '$got')"
s3_retry 20 "$bstep_name: e2e-api reads the object after the restore" $ns e2e-api '$A s3api get-object --bucket "$S3_BUCKET" --key backup/object.txt /tmp/out >/dev/null
echo "CONTENT=$(cat /tmp/out)"'
s3_same "$bstep_name: the object in files after the restore" "$object_payload" "$(s3_field CONTENT)"
echo "ok   file and object are back unchanged ($file_payload, $object_payload)"

bstep "Environment restore: the database cluster was not touched (same UID)"
[ "$(kc get clusters.postgresql.cnpg.io e2e-postgres-g1 -o jsonpath='{.metadata.uid}')" = "$db_uid" ] || bfail "the UID of the cluster e2e-postgres-g1 changed: environment restores must leave databases alone"
[ "$(kc get clusters.postgresql.cnpg.io e2e-postgres-g1 -o jsonpath='{.status.phase}')" = "Cluster in healthy state" ] || bfail "the Postgres cluster e2e-postgres-g1 is not healthy after the environment restore"
echo "ok   e2e-postgres-g1 kept its UID $db_uid"

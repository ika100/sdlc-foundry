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
$cplat resource add ext-files --type bucket --external --repo-dir "$gitops_repo" >/dev/null
commit "files and ext-files"
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
(cd "$work/e2e-gitops" && LOCAL_CLUSTER=$cluster LOCAL_HTTP_PORT=$port WITH_ARGO=0 WITH_CNPG=1 WITH_SEAWEEDFS=1 REGISTRY_PORT=$regport bash scripts/local-cluster.sh up)

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
apply_bucket() { # environment namespace
  local d="$work/e2e-gitops/applications/e2e/addons/$1/files" k
  for f in access-key-generator.yaml secret-key-generator.yaml externalsecret.yaml seaweed.yaml bucket.yaml identity.yaml credentials.yaml kustomization.yaml; do
    [ -f "$d/$f" ] || fail "render did not write addons/$1/files/$f"
  done
  kn "$2" apply -f "$d/access-key-generator.yaml" -f "$d/secret-key-generator.yaml" -f "$d/externalsecret.yaml" >/dev/null
  for _ in $(seq 1 40); do   # up to 120 s
    [ -n "$(kn "$2" get secret e2e-files-app -o jsonpath='{.data.secretAccessKey}' 2>/dev/null)" ] && break; sleep 3
  done
  for k in endpoint bucket region forcePathStyle accessKeyId secretAccessKey; do
    [ -n "$(kn "$2" get secret e2e-files-app -o jsonpath="{.data.$k}" 2>/dev/null)" ] || { kn "$2" get externalsecret e2e-files-app -o yaml | tail -25; fail "the Secret e2e-files-app in $2 lacks the key $k"; }
  done
  kn "$2" apply -f "$d/seaweed.yaml" -f "$d/bucket.yaml" -f "$d/identity.yaml" >/dev/null
  kn "$2" apply -f "$d/credentials.yaml" >/dev/null
  kn "$2" apply -k "$d" >/dev/null   # the whole kustomization is then a no-op
}
store_ready() { # namespace: the operator creates the master, volume and filer StatefulSets
  local s
  for s in master volume filer; do
    for _ in $(seq 1 60); do kn "$1" get statefulset e2e-files-$s >/dev/null 2>&1 && break; sleep 3; done   # up to 180 s
    kn "$1" rollout status statefulset/e2e-files-$s --timeout=300s || {
      kn "$1" get pods; kn "$1" describe statefulset e2e-files-$s | tail -25; fail "the SeaweedFS $s of e2e-files in $1 did not become ready"; }
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

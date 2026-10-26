#!/usr/bin/env bash
# Platform end-to-end test (no GitHub, no GHCR, no ArgoCD):
#   create a system (system.yaml + a Java service + a website) with `cplat system new` → build the images → push to a
#   local registry → start the platform's own local cluster (scripts/local-cluster.sh, WITH_ARGO=0) → apply the manifests
#   the renderer generated → wait for rollout → probe the services through the Gateway → ship a spec: verify dev, promote
#   to staging, apply, verify staging, finish the ship run.
# It also declares a second, external database (ext-db) and proves in the cluster that its ExternalSecret creates no
# partial Secret while the store entry lacks `password` (AC-115.12), and that the Secret appears once the entry is complete.
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
# the in-cluster database needs the CloudNativePG operator: render writes it to operators/ (cluster level, once)
[ -f "$gitops_repo/operators/apps/cloudnative-pg.yaml" ] || fail "render did not write operators/apps/cloudnative-pg.yaml for the in-cluster database"
[ -f "$gitops_repo/operators/root.yaml" ] || fail "render did not write operators/root.yaml"
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
gitops.save(app_dir, y, data)
PY
)
commit "environments"

step "Start the local cluster with a registry (the template's own script, Gateway only)"
# Without Argo CD (WITH_ARGO=0) the script cannot apply operators/root.yaml (an Argo CD Application); it installs the
# CloudNativePG chart itself at the version pinned in operators/apps/cloudnative-pg.yaml (WITH_CNPG auto-detects that file).
(cd "$work/e2e-gitops" && LOCAL_CLUSTER=$cluster LOCAL_HTTP_PORT=$port WITH_ARGO=0 REGISTRY_PORT=$regport bash scripts/local-cluster.sh up)

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
    ns.uses = ["postgres"] if name == "e2e-api" else []                               # DATABASE_URL from the addon
    ns.secret_ref = ["e2e-api-auth"] if name == "e2e-web" else []                     # the web app reads the secret generated for the API
    components[name] = compose.build_entry(name, f"e2e/{name}", shapes[shape], None, registry, ns, {})
gitops.save(app_dir, y, data)
PY
uv run scripts/render.py)
commit "components"

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

step "External database: a store entry without password creates no Secret and the ExternalSecret reports the key"
# ext-db is external in every environment; the ExternalSecret <system>-ext-db-app lands in the overlay of the first
# component that uses it. e2e-web uses it from here on (e2e-api keeps postgres alone, so DATABASE_URL stays as it was).
(cd "$gitops_repo" && uv run --with pyyaml --with ruamel.yaml python - "$root" <<'PY'
import sys
sys.path.insert(0, f"{sys.argv[1]}/scripts/cplat")
import gitops
from pathlib import Path
app_dir = gitops.find_app(Path("."))
y, data = gitops.load(app_dir)
gitops.components_of(data)["e2e-web"]["uses"] = ["ext-db"]
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
es_message=$(kc get externalsecret $ext_es -o jsonpath='{.status.conditions[?(@.type=="Ready")].message}')
case "$es_message" in *password*) echo "ok   ExternalSecret not ready, status names the key: $(echo "$es_message" | cut -c1-160)";; *) fail "the ExternalSecret status does not name the missing key password: $es_message";; esac
sleep 5   # give a wrongly created partial Secret time to appear
if kc get secret $ext_es >/dev/null 2>&1; then fail "the Secret $ext_es exists although the store entry lacks password (no partial Secret allowed)"; fi
echo "ok   no Secret $ext_es while password is missing"

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
kubectl --context k3d-$cluster apply -n $sns -k "$work/e2e-gitops/applications/e2e/overlays/staging/e2e-api"
kubectl --context k3d-$cluster -n $sns rollout status deploy/e2e-api --timeout=240s || fail "e2e-api did not become ready in staging"
kubectl --context k3d-$cluster -n $sns get deploy e2e-api -o jsonpath='{.spec.template.spec.containers[0].image}' | grep -q "sha-$sha" || fail "staging runs another image than the pinned one"
(cd "$api_repo" && $cplat instance verify staging --base-url "$staging_url" --no-retry)
probe "$staging_url/api/info" '"service":"e2e-api"'

step "End the ship run"
(cd "$api_repo" && $cplat component ship finish)

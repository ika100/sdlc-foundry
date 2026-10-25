#!/usr/bin/env bash
# Platform end-to-end test (no GitHub, no GHCR, no ArgoCD):
#   render a gitops-app + a Java service + a web app with the real templates → build the images → push to a local
#   registry → start the platform's own local cluster (scripts/local-cluster.sh, WITH_ARGO=0) → apply the manifests the
#   renderer generated → wait for rollout → probe the services through the Gateway.
# It exercises: cplat new-service, the templates' Dockerfiles (non-root numeric user, read-only filesystem), render.py,
# the generated Deployment/Service/HTTPRoute against a real API server, and the Gateway API on k3s' Traefik.
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

step "Render the three repos with the real templates (no GitHub)"
$cplat new-service e2e-gitops "e2e gitops repo" --gitops --no-github --skip-tasks --dir "$work" --org e2e >/dev/null
$cplat new-service e2e-api "e2e api" --type service-java --no-github --skip-tasks --dir "$work" --org e2e >/dev/null
$cplat new-service e2e-web "e2e web" --web --no-github --skip-tasks --dir "$work" --org e2e >/dev/null

step "Declare the Postgres addon (cluster-up then installs the CloudNativePG operator)"
$cplat addon add postgres --repo-dir "$work/e2e-gitops" >/dev/null
(cd "$work/e2e-gitops" && git add -A && git -c user.name=e2e -c user.email=e2e@example.com commit -qm "postgres")
step "Declare the OpenTelemetry base (collector only, no UI stack)"
$cplat addon add observability --repo-dir "$work/e2e-gitops" >/dev/null
step "Turn on the Kyverno guard rails, enforced in dev (cluster-up installs Kyverno)"
printf 'policies:\n  mode: {dev: Enforce}\n' >> "$work/e2e-gitops/applications/e2e/app.yaml"
(cd "$work/e2e-gitops" && git add -A && git -c user.name=e2e -c user.email=e2e@example.com commit -qm "observability")

step "Start the local cluster with a registry (the template's own script, Gateway only)"
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

step "Describe the services like /gitops:compose does and render the manifests"
(cd "$work/e2e-gitops" && uv run --with pyyaml --with ruamel.yaml python - "$root" "$registry:$regport" <<'PY'
import sys
root, registry = sys.argv[1], sys.argv[2]
sys.path.insert(0, f"{root}/scripts/cplat")
import compose, core, gitops
from pathlib import Path
repo = Path(".")
app_dir = gitops.find_app(repo)
y, data = gitops.load(app_dir)
services = gitops.services_of(data)
shapes = {s["id"]: s for s in core.registry.load()}
ns = compose.build_parser().parse_args(["add", "e2e-api", "--expose"])   # real parser defaults: new compose flags cannot break this harness
for name, shape in (("e2e-api", "service-java"), ("e2e-web", "web-nextjs")):
    ns.env = ["API_URL=http://e2e-api"] if name == "e2e-web" else []
    ns.generate = ["e2e-api-auth=DB_PASSWORD,JWT_KEY"] if name == "e2e-api" else []   # random values created by ESO
    ns.secret = ["e2e-api-stripe=STRIPE_KEY"] if name == "e2e-api" else []            # read from the secret store
    ns.uses = ["postgres"] if name == "e2e-api" else []                               # DATABASE_URL from the addon
    ns.secret_ref = ["e2e-api-auth"] if name == "e2e-web" else []                     # the web app reads the secret generated for the API
    services.append(compose.build_entry(name, f"e2e/{name}", shapes[shape], None, registry, ns, {}))
gitops.save(app_dir, y, data)
PY
uv run scripts/render.py)

step "Set the remote secret in the local store (what a developer does with /gitops:secret)"
printf 'sk_test_e2e' | $cplat secret set e2e-api e2e-api-stripe STRIPE_KEY --value-stdin --repo-dir "$work/e2e-gitops" >/dev/null

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

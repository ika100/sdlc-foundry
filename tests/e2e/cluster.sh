#!/usr/bin/env bash
# Platform end-to-end test of a cluster repo (spec 125, AC-125.16; no GitHub, no GHCR, no Argo CD):
#   render two systems (alpha-gitops, beta-gitops), each with a service and an in-cluster database whose operators are owned
#   by the cluster → render a cluster repo (e2e-cluster) listing cloudnative-pg and external-secrets → install those operators
#   once on one k3d cluster, with the versions the cluster render pins → apply both systems' database manifests → both
#   databases become healthy and the cluster holds exactly one CloudNativePG operator Deployment.
#
# Needs: docker (running), k3d, kubectl, uv, copier (or uv). Env: E2E_KEEP=1 keeps the cluster, E2E_CLUSTER_PORT, E2E_WORK.
set -euo pipefail

root=$(cd "$(dirname "$0")/../.." && pwd)
work="${E2E_WORK:-$(mktemp -d)}"
cluster=e2e-cluster-local
export PATH="$PATH:$HOME/.local/bin"
fail() { echo "E2E FAIL: $*" >&2; exit 1; }
step() { echo; echo "==> $*"; }

cleanup() {
  rc=$?
  if [ "${E2E_KEEP:-0}" != 1 ]; then
    (cd "$work/alpha-gitops" 2>/dev/null && LOCAL_CLUSTER=$cluster WITH_ARGO=0 bash scripts/local-cluster.sh down) >/dev/null 2>&1 || true
  fi
  [ $rc -eq 0 ] && echo && echo "E2E CLUSTER OK" || echo "E2E CLUSTER FAILED (work dir: $work)"
  exit $rc
}
trap cleanup EXIT

for t in docker k3d kubectl uv; do command -v $t >/dev/null || fail "$t is required"; done
docker info >/dev/null 2>&1 || fail "docker is not running"

copy() { # template destination args...
  local tpl=$1 dest=$2; shift 2
  if command -v copier >/dev/null; then
    copier copy "$root/templates/$tpl" "$dest" --defaults --trust --skip-tasks "$@" >/dev/null
  else
    uv tool run --from copier copier copy "$root/templates/$tpl" "$dest" --defaults --trust --skip-tasks "$@" >/dev/null
  fi
}

step "Render two systems with a service and an in-cluster database, the operators owned by the cluster"
for s in alpha beta; do
  copy gitops-app "$work/$s-gitops" --data project_name=$s-gitops --data github_org=e2e
  printf '%s\n' \
    "system: $s" \
    "owner: e2e" \
    "secretStore: {name: platform-secrets, kind: ClusterSecretStore}" \
    "environments:" \
    "  dev: {host: \"{component}.{system}-dev.localhost\", operators: owner}" \
    "  staging: {operators: owner}" \
    "  prod: {operators: owner}" \
    "components:" \
    "  api:" \
    "    type: service" \
    "    lang: python" \
    "    repo: e2e/$s-api" \
    "    image: ghcr.io/e2e/$s-api" \
    "    port: 8080" \
    "    probes: {liveness: /health, readiness: /ready}" \
    "    uses: [db]" \
    "    instances: {dev: {}, staging: {}, prod: {}}" \
    "resources:" \
    "  db:" \
    "    type: database" > "$work/$s-gitops/applications/$s/system.yaml"
  (cd "$work/$s-gitops" && uv run scripts/render.py >/dev/null)
  [ -f "$work/$s-gitops/applications/$s/addons/dev/db/kustomization.yaml" ] || fail "$s did not render addons/dev/db"
  [ ! -e "$work/$s-gitops/operators" ] || fail "$s rendered operators/ although every environment has operators: owner"
done
echo "ok   neither system renders operators/"

step "Render the cluster repo: cloudnative-pg and external-secrets, systems alpha and beta"
copy cluster-gitops "$work/e2e-cluster" --data project_name=e2e-cluster --data github_org=e2e
printf '%s\n' \
  "cluster: e2e-cluster" \
  "owner: e2e" \
  "server: https://kubernetes.default.svc" \
  "org: e2e" \
  "operators: [cloudnative-pg, external-secrets]" \
  "systems:" \
  "  alpha: {repo: e2e/alpha-gitops}" \
  "  beta: {repo: e2e/beta-gitops}" > "$work/e2e-cluster/cluster.yaml"
(cd "$work/e2e-cluster" && uv run scripts/render.py >/dev/null)
for f in operators/cloudnative-pg.yaml operators/external-secrets.yaml systems/alpha.yaml systems/beta.yaml; do
  [ -f "$work/e2e-cluster/cluster/$f" ] || fail "the cluster render did not write cluster/$f"
done
grep -q 'name: operator-cloudnative-pg' "$work/e2e-cluster/cluster/operators/cloudnative-pg.yaml" || fail "no Application operator-cloudnative-pg"
grep -q 'name: operator-external-secrets' "$work/e2e-cluster/cluster/operators/external-secrets.yaml" || fail "no Application operator-external-secrets"
pin() { sed -n 's/^[[:space:]]*targetRevision:[[:space:]]*["'"'"']\{0,1\}\([^"'"'"'[:space:]]*\).*/\1/p' "$1" | head -1; }
cnpg_pin=$(pin "$work/e2e-cluster/cluster/operators/cloudnative-pg.yaml")
eso_pin=$(pin "$work/e2e-cluster/cluster/operators/external-secrets.yaml")
[ -n "$cnpg_pin" ] && [ -n "$eso_pin" ] || fail "no targetRevision pins in the cluster render (cnpg '$cnpg_pin', eso '$eso_pin')"
echo "ok   pins: cloudnative-pg $cnpg_pin, external-secrets $eso_pin"

step "Start the local cluster and install the operators once (from alpha-gitops, the versions the cluster render pins)"
(cd "$work/alpha-gitops" && LOCAL_CLUSTER=e2e-cluster-local LOCAL_HTTP_PORT=${E2E_CLUSTER_PORT:-8098} WITH_ARGO=0 WITH_CNPG=1 CNPG_VERSION="$cnpg_pin" \
  WITH_ESO=1 ESO_VERSION="$eso_pin" WITH_KYVERNO=0 WITH_LGTM=0 WITH_SEAWEEDFS=0 bash scripts/local-cluster.sh up)

step "Apply both systems' databases (what Argo CD would sync)"
k() { kubectl --context k3d-$cluster "$@"; }
k create namespace beta-dev --dry-run=client -o yaml | k apply -f - >/dev/null
for s in alpha beta; do
  k apply -n "$s-dev" -k "$work/$s-gitops/applications/$s/addons/dev/db"
done
phase() { k -n "$1-dev" get cluster "$1-db" -o jsonpath='{.status.phase}' 2>/dev/null || true; }
for s in alpha beta; do
  for _ in $(seq 1 80); do   # up to 400 s
    [ "$(phase $s)" = "Cluster in healthy state" ] && break; sleep 5
  done
  [ "$(phase $s)" = "Cluster in healthy state" ] || { k -n "$s-dev" get cluster -o yaml | tail -30; fail "the database of $s did not become healthy (phase '$(phase $s)')"; }
  echo "ok   $s-dev: Cluster $s-db is in healthy state"
done

step "Exactly one CloudNativePG operator serves both"
n=$(k get deploy -A -l app.kubernetes.io/name=cloudnative-pg -o name | wc -l | tr -d ' ')
[ "$n" = 1 ] || { k get deploy -A -l app.kubernetes.io/name=cloudnative-pg; fail "expected 1 CloudNativePG operator Deployment, found $n"; }
echo "ok   one operator Deployment, two healthy databases"

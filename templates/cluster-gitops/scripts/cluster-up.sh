#!/usr/bin/env bash
# Local k3d cluster for this cluster repo: Argo CD and the Gateway API as a system's cluster-up, the credentials, then the
# bootstrap (scripts/bootstrap.sh) against it. `devbox run cluster-down` removes it.
#
# Environment: LOCAL_CLUSTER (default <cluster>-local), LOCAL_HTTP_PORT, GH_TOKEN (default `gh auth token`),
#              REPO_TOKEN and PULL_TOKEN (default GH_TOKEN)
set -euo pipefail

cd "$(dirname "$0")/.."

name="${LOCAL_CLUSTER:-$(uv run --quiet scripts/render.py --name)-local}"
token="${GH_TOKEN:-}"
[ -n "$token" ] || token=$(gh auth token)
repo_token="${REPO_TOKEN:-$token}"
pull_token="${PULL_TOKEN:-$token}"
org=$(sed -n 's/^github_org:[[:space:]]*//p' .copier-answers.yml | head -1)
ctx="k3d-$name"
k() { kubectl --context "$ctx" "$@"; }

GH_TOKEN="$token" REPO_TOKEN="$repo_token" PULL_TOKEN="$pull_token" \
  WITH_SYSTEM=0 WITH_ESO=0 WITH_KYVERNO=0 WITH_LGTM=0 WITH_CNPG=0 WITH_SEAWEEDFS=0 LOCAL_CLUSTER="$name" \
  bash scripts/local-cluster.sh up

systems=$(uv run --quiet scripts/render.py --systems)
while read -r system _; do
  [ -n "$system" ] || continue
  for env in dev staging prod; do
    ns="${system}-${env}"
    k create namespace "$ns" --dry-run=client -o yaml | k apply -f - >/dev/null
    k -n "$ns" create secret docker-registry ghcr-pull --docker-server=ghcr.io --docker-username="${org}" \
      --docker-password="$pull_token" --dry-run=client -o yaml | k apply -f - >/dev/null
    k -n "$ns" patch serviceaccount default -p '{"imagePullSecrets":[{"name":"ghcr-pull"}]}' >/dev/null
  done
done <<< "$systems"

KUBE_CONTEXT="$ctx" REPO_TOKEN="$repo_token" bash scripts/bootstrap.sh

port=$(docker port "k3d-${name}-serverlb" 80/tcp 2>/dev/null | head -1 | sed 's/.*://' || true)
urls=$(uv run --quiet scripts/check.py --urls || true)
while read -r system host; do
  [ -n "$system" ] || continue
  echo "Exposed: http://${host}:${port}/   (${system}, once the workloads are running)"
done <<< "$urls"
echo "Watch the applications:  kubectl --context ${ctx} -n argocd get applications"
echo "Browse the cluster:      k9s --context ${ctx}"
echo "Remove it again:         devbox run cluster-down"

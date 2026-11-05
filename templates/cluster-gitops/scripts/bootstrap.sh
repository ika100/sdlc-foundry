#!/usr/bin/env bash
# Bootstrap a cluster: one human, once. Stores one Argo CD credential template for the org, applies the operators root,
# waits for each operator's CRD, then applies the systems root. After that, systems and operators change only through
# merged PRs to this repo. Re-running it changes nothing that is in sync.
#
#   KUBE_CONTEXT=<ctx> REPO_TOKEN=<token> devbox run bootstrap
#
# Environment:
#   KUBE_CONTEXT    the cluster to bootstrap (required)
#   REPO_TOKEN      read-only token (Contents: read) for this repo and every system repo under https://github.com/<org> (required)
#   CRD_WAIT_TRIES  how often to poll for each CRD, every 3 s (default 200 = 10 minutes)
set -euo pipefail

cd "$(dirname "$0")/.."

if [ -z "${KUBE_CONTEXT:-}" ]; then
  echo "Set KUBE_CONTEXT to the cluster to bootstrap, e.g. KUBE_CONTEXT=my-cluster devbox run bootstrap. Contexts:"
  kubectl config get-contexts -o name || true
  exit 1
fi
ctx="$KUBE_CONTEXT"
org=$(sed -n 's/^github_org:[[:space:]]*//p' .copier-answers.yml | head -1)
if [ -z "${REPO_TOKEN:-}" ]; then
  echo "ERROR: set REPO_TOKEN to a read-only token (Contents: read) for the cluster repo and every system repo under https://github.com/${org}" >&2
  exit 1
fi
tries="${CRD_WAIT_TRIES:-200}"
k() { kubectl --context "$ctx" "$@"; }

# Spec 142 (AC-142.3): apply what main holds on GitHub, never a stale checkout. A clone of main that is behind origin/main
# fast-forwards first; one that cannot (local commits, another branch) stops and names the commit it is missing.
if git rev-parse --git-dir >/dev/null 2>&1 && git fetch -q origin main 2>/dev/null; then
  behind=$(git rev-list --count HEAD..origin/main 2>/dev/null || echo 0)
  if [ "$behind" != 0 ]; then
    if [ "$(git branch --show-current)" = main ] && git merge -q --ff-only origin/main 2>/dev/null; then
      echo "fast-forwarded main to $(git rev-parse --short HEAD) (it was $behind commit(s) behind origin/main)"
    else
      echo "ERROR: this checkout is $behind commit(s) behind origin/main ($(git rev-parse --short origin/main)), so bootstrap would apply stale files." >&2
      echo "  fix: git switch main && git pull --ff-only, then run it again" >&2
      exit 1
    fi
  fi
fi

uv run --quiet scripts/render.py --check || exit 1

if ! k get namespace argocd >/dev/null 2>&1; then
  echo "ERROR: Argo CD is not installed in ${ctx} (it is a cluster prerequisite)" >&2
  exit 1
fi

echo "Storing the repository credential template for https://github.com/${org}"
k -n argocd create secret generic github-creds --from-literal=url="https://github.com/${org}" \
  --from-literal=username="${org}" --from-literal=password="$REPO_TOKEN" --dry-run=client -o yaml | k apply -f - >/dev/null
k -n argocd label secret github-creds argocd.argoproj.io/secret-type=repo-creds --overwrite >/dev/null

echo "Applying the operators"
k apply -n argocd -f cluster/operators-root.yaml

crds=$(uv run --quiet scripts/render.py --crds)
while read -r op crd; do
  [ -n "$op" ] || continue
  echo "Waiting for the CRD ${crd} (operator ${op})"
  i=0
  until k get crd "$crd" >/dev/null 2>&1; do
    i=$((i + 1))
    if [ "$i" -ge "$tries" ]; then
      echo "ERROR: the CRD ${crd} did not appear within 10 minutes." >&2
      echo "  fix: inspect the Argo CD application operator-${op}: kubectl --context ${ctx} -n argocd get application operator-${op} -o yaml" >&2
      exit 1
    fi
    sleep 3
  done
done <<< "$crds"

echo "Applying the systems"
k apply -n argocd -f cluster/systems-root.yaml
echo "Bootstrapped ${ctx}. From now on, change systems and operators through merged PRs to this repo."

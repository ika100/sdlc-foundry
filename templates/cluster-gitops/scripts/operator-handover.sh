#!/usr/bin/env bash
# One owner per operator (#425): a cluster-up of an older release installed External Secrets and Kyverno as k3s HelmCharts
# (kube-system/<op>); once this repo renders operators/apps/<op>.yaml, Argo CD installs the same release from operators/.
# This hands each such operator over to Argo CD without losing its CRDs or the resources that use them:
#
#   1. annotate the release's CRDs helm.sh/resource-policy=keep
#   2. mark the HelmChart unmanaged and remove its finalizer wrangler.cattle.io/on-helm-chart-remove, so deleting it runs no
#      `helm uninstall` (k3s helm-controller v0.16: the unmanaged annotation stops the controller re-adding the finalizer)
#   3. delete the HelmChart and the release's sh.helm.release.v1.<op>.* secrets
#   4. apply operators/root.yaml (Argo CD adopts the same-named objects)
#   5. check that the CRDs and custom resources counted before are all still there
#
# Nothing happens without a HelmChart (fresh clusters) or when the repo does not render the operator (it stays on its
# HelmChart). Re-running it is safe. Called by local-cluster.sh (cluster-up) and bootstrap.sh before they apply operators/root.yaml.
#
#   KUBE_CONTEXT=<ctx> bash scripts/operator-handover.sh
set -euo pipefail
cd "$(dirname "$0")/.."

if [ -z "${KUBE_CONTEXT:-}" ]; then
  echo "ERROR: set KUBE_CONTEXT to the cluster whose operators to hand over" >&2
  exit 1
fi
k() { kubectl --context "$KUBE_CONTEXT" "$@"; }
finalizer=wrangler.cattle.io/on-helm-chart-remove

# <op> <label> <target namespace> <resources counted before and after>
operators="external-secrets|External Secrets|external-secrets|externalsecrets.external-secrets.io clustersecretstores.external-secrets.io secretstores.external-secrets.io
kyverno|Kyverno|kyverno|namespacedvalidatingpolicies.policies.kyverno.io validatingpolicies.policies.kyverno.io clusterpolicies.kyverno.io policies.kyverno.io"

# A cluster without the k3s Helm controller has no HelmCharts to hand over.
k get crd helmcharts.helm.cattle.io >/dev/null 2>&1 || exit 0

release_crds() {   # release_crds <op> <namespace>: the CRDs Helm installed with the release
  k get crd -o jsonpath='{range .items[*]}{.metadata.name}{" "}{.metadata.annotations.meta\.helm\.sh/release-name}{" "}{.metadata.annotations.meta\.helm\.sh/release-namespace}{"\n"}{end}' |
    awk -v op="$1" -v ns="$2" '$2 == op && $3 == ns { print $1 }'
}
count() {   # count <resource>: how many exist in all namespaces, or "missing" when the type is not served
  local out
  if out=$(k get "$1" -A --no-headers 2>/dev/null); then printf '%s\n' "$out" | grep -c . || true; else echo missing; fi
}

handed=""
before=""
while IFS='|' read -r op label ns resources <&3; do
  [ -n "$(k -n kube-system get helmcharts.helm.cattle.io "$op" --ignore-not-found -o name)" ] || continue
  if [ ! -f "operators/apps/$op.yaml" ]; then
    echo "$label stays on its HelmChart kube-system/$op (this repo does not render operators/apps/$op.yaml)"
    continue
  fi
  echo "$label: handing the HelmChart kube-system/$op over to Argo CD (operators/apps/$op.yaml)"
  crds=$(release_crds "$op" "$ns")
  before="${before}crd/$op $(printf '%s\n' "$crds" | grep -c . || true)"$'\n'
  for r in $resources; do before="${before}$r $(count "$r")"$'\n'; done

  # 1
  n=0
  for c in $crds; do k annotate crd "$c" helm.sh/resource-policy=keep --overwrite >/dev/null; n=$((n + 1)); done
  echo "  1/5 annotated $n CRD(s) of the release $op with helm.sh/resource-policy=keep"
  # 2
  k -n kube-system annotate helmcharts.helm.cattle.io "$op" helmcharts.helm.cattle.io/unmanaged=true --overwrite >/dev/null
  keep=$(k -n kube-system get helmcharts.helm.cattle.io "$op" -o jsonpath='{range .metadata.finalizers[*]}{@}{"\n"}{end}' |
    grep -vxF "$finalizer" | sed 's/.*/"&"/' | paste -sd, - || true)
  k -n kube-system patch helmcharts.helm.cattle.io "$op" --type=merge -p "{\"metadata\":{\"finalizers\":[${keep}]}}" >/dev/null
  echo "  2/5 removed the finalizer $finalizer from the HelmChart (marked unmanaged), so deleting it runs no helm uninstall"
  # 3
  k -n kube-system delete helmcharts.helm.cattle.io "$op" --wait=true --timeout=120s >/dev/null
  if [ -n "$(k -n kube-system get job "helm-delete-$op" --ignore-not-found -o name)" ]; then
    echo "ERROR: the k3s Helm controller started the uninstall job kube-system/helm-delete-$op" >&2
    echo "  fix: kubectl --context $KUBE_CONTEXT -n kube-system logs job/helm-delete-$op; then run cluster-up or bootstrap again" >&2
    exit 1
  fi
  k -n "$ns" delete secret -l "owner=helm,name=$op" --ignore-not-found >/dev/null
  # the controller's install objects: the ClusterRoleBinding has no ownerReference and would outlive the HelmChart
  k -n kube-system delete "job/helm-install-$op" "serviceaccount/helm-$op" "secret/chart-values-$op" "configmap/chart-content-$op" \
    --ignore-not-found >/dev/null
  k delete "clusterrolebinding/helm-kube-system-$op" --ignore-not-found >/dev/null
  echo "  3/5 deleted the HelmChart kube-system/$op, its install job and the Helm release secrets sh.helm.release.v1.$op.* in $ns"
  handed="$handed $op"
done 3<<< "$operators"

[ -n "$handed" ] || exit 0

# 4
k apply -n argocd -f operators/root.yaml >/dev/null
echo "  4/5 applied operators/root.yaml: Argo CD now owns${handed}"
# 5
changed=""
while read -r what n <&3; do
  [ -n "$what" ] || continue
  case "$what" in
    crd/*) op=${what#crd/}; ns=$(printf '%s\n' "$operators" | awk -F'|' -v op="$op" '$1 == op { print $3 }')
           now=$(release_crds "$op" "$ns" | grep -c . || true) ;;
    *) now=$(count "$what") ;;
  esac
  [ "$now" = "$n" ] || changed="${changed}  ${what}: ${n} before, ${now} after"$'\n'
done 3<<< "$before"
if [ -n "$changed" ]; then
  echo "ERROR: the handover to Argo CD changed what the cluster holds:" >&2
  printf '%s' "$changed" >&2
  echo "  fix: kubectl --context $KUBE_CONTEXT -n argocd get applications; restore the lost objects from git or a backup" >&2
  exit 1
fi
echo "  5/5 the CRDs and custom resources are unchanged: $(printf '%s' "$before" | awk 'NF { printf "%s%s=%s", sep, $1, $2; sep=", " }')"

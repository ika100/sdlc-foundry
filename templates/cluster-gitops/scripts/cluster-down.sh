#!/usr/bin/env bash
# Remove the local k3d cluster of this cluster repo (the one `devbox run cluster-up [<cluster>]` built).
#
#   devbox run cluster-down [<cluster>]    the cluster defaults to the first one listed in cluster.yaml `clusters`
#
# Environment: LOCAL_CLUSTER (default <cluster>-<name>, <cluster>-local without `clusters`)
set -euo pipefail

cd "$(dirname "$0")/.."

repo_cluster=$(bash scripts/uv-script.sh --quiet scripts/render.py --name)
first=$(bash scripts/uv-script.sh --quiet scripts/render.py --clusters | sed -n 1p)
want="${1:-$first}"
suffix=local
if [ -n "$first" ]; then
  suffix="$want"
  if ! bash scripts/uv-script.sh --quiet scripts/render.py --clusters | grep -qxF -- "$want"; then
    echo "ERROR: unknown cluster '${want}' (clusters: $(bash scripts/uv-script.sh --quiet scripts/render.py --clusters | paste -sd, - | sed 's/,/, /g'))" >&2
    exit 1
  fi
elif [ -n "$want" ] && [ "$want" != "$repo_cluster" ]; then
  echo "ERROR: unknown cluster '${want}' (this repo has one cluster: ${repo_cluster})" >&2
  exit 1
fi

WITH_SYSTEM=0 LOCAL_CLUSTER="${LOCAL_CLUSTER:-${repo_cluster}-${suffix}}" bash scripts/local-cluster.sh down

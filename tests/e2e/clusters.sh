#!/usr/bin/env bash
# Platform end-to-end test of one cluster repo with two clusters (spec 201, AC-201.11; no GitHub, no GHCR):
#   render one system (todo-gitops: component api in dev, staging and prod; dev and staging on cluster one, prod on cluster two)
#   → render one cluster repo (e2e-clusters, clusters: [one, two], operator cloudnative-pg) → serve both repos from a local HTTPS git
#   server on the k3d Docker networks, point github.com at it in each cluster's CoreDNS → build and bootstrap each cluster with the repo's
#   own cluster-up (two k3d clusters, each with its own Argo CD) → cluster one runs api-dev and api-staging only, cluster two api-prod
#   only, all Synced, both run the same CloudNativePG operator image, dev runs a sha- tag and prod the pinned 1.0.0.
#
# The test has its own kubeconfig file and unique cluster names; it never touches the current kube context or another cluster.
# Needs: docker (running), k3d, kubectl, git, uv, copier (or uv). Env: E2E_KEEP=1 keeps the clusters and the git server,
#        E2E_CLUSTERS_PORT_ONE (default 8191), E2E_CLUSTERS_PORT_TWO (default 8192), E2E_WORK.
set -euo pipefail

root=$(cd "$(dirname "$0")/../.." && pwd)
# shellcheck source=SCRIPTDIR/lib/uv-cache.sh
. "$root/tests/e2e/lib/uv-cache.sh"   # a throwaway uv cache per script run (spec 208)
# shellcheck source=SCRIPTDIR/lib/docker-build.sh
. "$root/tests/e2e/lib/docker-build.sh"   # e2e_docker_build: docker build, retried once on a registry 429 (#1045)
work="${E2E_WORK:-$(mktemp -d)}"
e2e_uv_cache_start
export PATH="$PATH:$HOME/.local/bin"
export GH_TOKEN=e2e-token   # no GitHub: the repository credential is a placeholder (Argo CD pulls from the local git server)
id="$$"
git_name="e2e-clusters-git-$id"
git_image=e2e-clusters-git
lc_one="e2e-cl-one-$id"; lc_two="e2e-cl-two-$id"
port_one="${E2E_CLUSTERS_PORT_ONE:-8191}"; port_two="${E2E_CLUSTERS_PORT_TWO:-8192}"
kc_one="$work/kubeconfig-one"; kc_two="$work/kubeconfig-two"
of() { local v="$1_$2"; echo "${!v}"; }   # of <lc|port|kc> <one|two>
pids=()
fail() { echo "E2E FAIL: $*" >&2; exit 1; }
step() { echo; echo "==> $*"; }

cleanup() {
  rc=$?
  trap - EXIT
  if [ "${E2E_KEEP:-0}" != 1 ]; then
    # an empty array is unbound to bash 3.2 under set -u
    for p in ${pids[@]+"${pids[@]}"}; do kill "$p" >/dev/null 2>&1 || true; done
    docker rm -f "$git_name" >/dev/null 2>&1 || true
    for c in one two; do
      if [ -d "$work/e2e-clusters" ]; then
        (cd "$work/e2e-clusters" && KUBECONFIG="$(of kc $c)" LOCAL_CLUSTER="$(of lc $c)" bash scripts/cluster-down.sh "$c") >/dev/null 2>&1 || true
      fi
      k3d cluster delete "$(of lc $c)" >/dev/null 2>&1 || true
    done
  fi
  [ $rc -eq 0 ] && echo && echo "E2E CLUSTERS OK" || echo "E2E CLUSTERS FAILED (work dir: $work)"
  e2e_uv_cache_end
  exit $rc
}
trap cleanup EXIT

for t in docker k3d kubectl git uv; do command -v $t >/dev/null || fail "$t is required"; done
docker info >/dev/null 2>&1 || fail "docker is not running"
for c in one two; do
  ! k3d cluster list "$(of lc $c)" >/dev/null 2>&1 || fail "the k3d cluster $(of lc $c) exists already"
done

copy() { # template destination args...
  local tpl=$1 dest=$2; shift 2
  if command -v copier >/dev/null; then
    copier copy "$root/templates/$tpl" "$dest" --defaults --trust --skip-tasks "$@" >/dev/null
  else
    uv tool run --from copier copier copy "$root/templates/$tpl" "$dest" --defaults --trust --skip-tasks "$@" >/dev/null
  fi
}
kk() { local c=$1; shift; kubectl --kubeconfig "$(of kc $c)" --context "k3d-$(of lc $c)" "$@"; }
gitc() { git -c user.name=e2e -c user.email=e2e@example.com -c commit.gpgsign=false "$@"; }
pin() { sed -n 's/^[[:space:]]*targetRevision:[[:space:]]*["'"'"']\{0,1\}\([^"'"'"'[:space:]]*\).*/\1/p' "$1" | head -1; }

step "Render the system todo-gitops: api in dev, staging and prod; dev and staging on cluster one, prod on cluster two"
todo="$work/todo-gitops"
copy gitops-app "$todo" --data project_name=todo-gitops --data github_org=e2e
printf '%s\n' \
  "system: todo" \
  "owner: e2e" \
  "environments:" \
  "  dev: {host: \"{component}.{system}-dev.localhost\", operators: owner, cluster: one}" \
  "  staging: {operators: owner, cluster: one}" \
  "  prod: {operators: owner, cluster: two}" \
  "components:" \
  "  api:" \
  "    type: service" \
  "    lang: python" \
  "    repo: e2e/todo-api" \
  "    image: ghcr.io/e2e/todo-api" \
  "    port: 8080" \
  "    probes: {liveness: /health, readiness: /ready}" \
  "    instances: {dev: {}, staging: {}, prod: {}}" > "$todo/applications/todo/system.yaml"
(cd "$todo" && uv run scripts/render.py >/dev/null)
sha="sha-$(printf 'e2e-clusters' | git hash-object --stdin)"
semver=1.0.0
for e in dev staging; do sed -i.bak "s/newTag: .*/newTag: $sha/" "$todo/applications/todo/overlays/$e/api/kustomization.yaml"; done
sed -i.bak "s/newTag: .*/newTag: $semver/" "$todo/applications/todo/overlays/prod/api/kustomization.yaml"
find "$todo/applications" -name '*.bak' -delete
(cd "$todo" && uv run scripts/render.py >/dev/null)
for e in dev staging; do grep -q "newTag: $sha" "$todo/applications/todo/overlays/$e/api/kustomization.yaml" || fail "the $e overlay is not pinned to $sha"; done
grep -q "newTag: $semver" "$todo/applications/todo/overlays/prod/api/kustomization.yaml" || fail "the prod overlay is not pinned to $semver"
for e in dev staging prod; do
  [ -f "$todo/bootstrap/environments/todo-$e.yaml" ] || fail "the system render did not write bootstrap/environments/todo-$e.yaml"
done
echo "ok   todo-gitops: bootstrap/environments/todo-{dev,staging,prod}.yaml; dev and staging pin $sha, prod pins $semver"

step "Render the cluster repo e2e-clusters: clusters one and two, cloudnative-pg, todo on one (dev, staging) and two (prod)"
cr="$work/e2e-clusters"
copy cluster-gitops "$cr" --data project_name=e2e-clusters --data github_org=e2e
mkdir -p "$cr/clusters/one" "$cr/clusters/two"
: > "$cr/clusters/one/cluster.yaml"
: > "$cr/clusters/two/cluster.yaml"
printf '%s\n' \
  "cluster: e2e-clusters" \
  "owner: e2e" \
  "server: https://kubernetes.default.svc" \
  "org: e2e" \
  "operators: [cloudnative-pg]" \
  "clusters: [one, two]" \
  "systems:" \
  "  todo:" \
  "    repo: e2e/todo-gitops" \
  "    environments: {dev: one, staging: one, prod: two}" > "$cr/cluster.yaml"
(cd "$cr" && uv run scripts/render.py >/dev/null)
for c in one two; do
  for f in operators-root.yaml systems-root.yaml operators/cloudnative-pg.yaml systems/todo.yaml kustomization.yaml; do
    [ -f "$cr/cluster/$c/$f" ] || fail "the cluster render did not write cluster/$c/$f"
  done
done
grep -q 'name: operator-cloudnative-pg' "$cr/cluster/one/operators/cloudnative-pg.yaml" || fail "no Application operator-cloudnative-pg on cluster one"
grep -q 'name: operator-cloudnative-pg' "$cr/cluster/two/operators/cloudnative-pg.yaml" || fail "no Application operator-cloudnative-pg on cluster two"
cnpg_one=$(pin "$cr/cluster/one/operators/cloudnative-pg.yaml")
cnpg_two=$(pin "$cr/cluster/two/operators/cloudnative-pg.yaml")
[ -n "$cnpg_one" ] && [ "$cnpg_one" = "$cnpg_two" ] || fail "the clusters pin different cloudnative-pg versions ('$cnpg_one', '$cnpg_two')"
grep -q 'include: .{\*-dev.yaml,\*-staging.yaml}.' "$cr/cluster/one/systems/todo.yaml" || fail "cluster one does not select dev and staging of todo"
grep -q 'include: .\*-prod.yaml.' "$cr/cluster/two/systems/todo.yaml" || fail "cluster two does not select prod of todo"
echo "ok   cluster/one runs todo dev and staging, cluster/two runs todo prod; both pin cloudnative-pg $cnpg_one"

step "Start the git server: an HTTPS smart-git server for github.com/e2e/*, serving both repos"
for r in todo-gitops e2e-clusters; do
  (cd "$work/$r" && git init -q -b main && git add -A && gitc commit -q -m "e2e render" && mkdir -p "$work/git/e2e" \
    && git clone -q --bare . "$work/git/e2e/$r" && git remote add origin "$work/git/e2e/$r" && git fetch -q origin main \
    && git branch -q --set-upstream-to=origin/main main)
done
ctx_dir="$work/gitserver"
mkdir -p "$ctx_dir"
printf '%s\n' \
  "FROM alpine:3.20" \
  "RUN apk add --no-cache git git-daemon nginx fcgiwrap openssl \\" \
  " && git config --system safe.directory '*' \\" \
  " && openssl req -x509 -newkey rsa:2048 -nodes -days 2 -subj /CN=github.com -addext subjectAltName=DNS:github.com \\" \
  "      -keyout /etc/ssl/git.key -out /etc/ssl/git.crt" \
  "COPY nginx.conf /etc/nginx/nginx.conf" \
  "COPY start.sh /start.sh" \
  "CMD [\"sh\", \"/start.sh\"]" > "$ctx_dir/Dockerfile"
printf '%s\n' \
  "events {}" \
  "http {" \
  "  access_log /dev/stdout;" \
  "  error_log /dev/stderr info;" \
  "  server {" \
  "    listen 443 ssl;" \
  "    ssl_certificate /etc/ssl/git.crt;" \
  "    ssl_certificate_key /etc/ssl/git.key;" \
  "    client_max_body_size 0;" \
  "    location /e2e/ {" \
  "      include fastcgi_params;" \
  "      fastcgi_param SCRIPT_FILENAME /usr/libexec/git-core/git-http-backend;" \
  "      fastcgi_param GIT_HTTP_EXPORT_ALL \"\";" \
  "      fastcgi_param GIT_PROJECT_ROOT /srv/git;" \
  "      fastcgi_param GIT_PROTOCOL \$http_git_protocol;" \
  "      fastcgi_param PATH_INFO \$uri;" \
  "      fastcgi_pass unix:/run/fcgiwrap.sock;" \
  "    }" \
  "    location / {" \
  "      proxy_pass https://github.com;" \
  "      proxy_ssl_server_name on;" \
  "      proxy_set_header Host github.com;" \
  "      proxy_buffer_size 64k;" \
  "      proxy_buffers 8 64k;" \
  "      proxy_busy_buffers_size 128k;" \
  "    }" \
  "  }" \
  "}" > "$ctx_dir/nginx.conf"
printf '%s\n' \
  "mkdir -p /srv/git /run" \
  "fcgiwrap -s unix:/run/fcgiwrap.sock &" \
  "for _ in 1 2 3 4 5 6 7 8 9 10; do [ -S /run/fcgiwrap.sock ] && break; sleep 1; done" \
  "chmod 666 /run/fcgiwrap.sock" \
  "exec nginx -g 'daemon off;'" > "$ctx_dir/start.sh"
e2e_docker_build -q -t "$git_image" "$ctx_dir" >/dev/null
docker create --name "$git_name" "$git_image" >/dev/null
docker cp "$work/git/." "$git_name:/srv/git/"
docker start "$git_name" >/dev/null
echo "ok   git server $git_name serves e2e/todo-gitops and e2e/e2e-clusters"

# Everything except /e2e/ is passed on to the real github.com: the CloudNativePG chart index lives on cloudnative-pg.github.io (resolved
# normally) but names its tarball on https://github.com/cloudnative-pg/charts/releases/download/..., and the cluster's DNS sends github.com
# here. The tarball is requested over TLS with the git server's self-signed certificate, so the chart repository is marked insecure too.
# The repositories are served without a .git suffix: Argo CD clones the repoURL as written (https://github.com/e2e/<repo>).
# Each repository secret carries its own credential and insecure flag, because cluster-up's bootstrap re-applies github-creds
# (a client-side apply drops the insecure key that wire added).

# diagnose: the state needed to find why a cluster did not converge (Argo CD applications with conditions, pods, repo-server log)
diagnose() {
  for c in one two; do
    echo "--- [$c] applications (sync, health)"
    kk "$c" -n argocd get applications -o wide 2>&1 || true
    echo "--- [$c] application conditions and operation messages"
    kk "$c" -n argocd get applications -o jsonpath='{range .items[*]}{.metadata.name}{": "}{.status.conditions[*].message}{" | "}{.status.operationState.message}{"\n"}{end}' 2>&1 || true
    echo "--- [$c] pods"
    kk "$c" get pods -A 2>&1 || true
    echo "--- [$c] argocd-repo-server log (tail)"
    kk "$c" -n argocd logs deploy/argocd-repo-server --tail=60 2>&1 || true
    echo "--- [$c] coredns-custom"
    kk "$c" -n kube-system get configmap coredns-custom -o yaml 2>&1 || true
    echo "--- [$c] coredns log (current and previous container)"
    kk "$c" -n kube-system logs deploy/coredns --tail=30 2>&1 || true
    kk "$c" -n kube-system logs deploy/coredns --previous --tail=30 2>&1 || true
  done
  echo "--- git server log (tail)"
  docker logs --tail 30 "$git_name" 2>&1 || true
}

# The github.com override is a separate server block (a .server key of coredns-custom): k3s's Corefile already has a hosts plugin
# in its main block, and CoreDNS refuses a second one there ("plugin/hosts: this plugin can only be used once per Server Block").
# wire <cluster>: once the cluster's Docker network, DNS and Argo CD namespace exist, put the git server in reach and
# mark the org credential (and both repositories) insecure, so Argo CD pulls from it as if it were github.com
wire() {
  local c=$1 net="k3d-$(of lc $1)" ip=""
  for _ in $(seq 1 180); do docker network inspect "$net" >/dev/null 2>&1 && break; sleep 5; done
  docker network inspect "$net" >/dev/null 2>&1 || { echo "E2E FAIL: the Docker network $net did not appear" >&2; exit 1; }
  docker network connect "$net" "$git_name" >/dev/null 2>&1 || true
  ip=$(docker inspect -f "{{(index .NetworkSettings.Networks \"$net\").IPAddress}}" "$git_name")
  [ -n "$ip" ] || { echo "E2E FAIL: the git server has no address on $net" >&2; exit 1; }
  for _ in $(seq 1 120); do kk "$c" -n kube-system get deploy coredns >/dev/null 2>&1 && break; sleep 5; done
  printf '%s\n' \
    "apiVersion: v1" \
    "kind: ConfigMap" \
    "metadata: {name: coredns-custom, namespace: kube-system}" \
    "data:" \
    "  github.server: |" \
    "    github.com:53 {" \
    "      hosts {" \
    "        $ip github.com" \
    "      }" \
    "    }" | kk "$c" apply -f - >/dev/null
  kk "$c" -n kube-system rollout restart deploy/coredns >/dev/null
  for _ in $(seq 1 240); do kk "$c" get namespace argocd >/dev/null 2>&1 && break; sleep 5; done
  kk "$c" get namespace argocd >/dev/null 2>&1 || { echo "E2E FAIL: no namespace argocd in $(of lc $c)" >&2; exit 1; }
  kk "$c" -n argocd create secret generic github-creds --from-literal=url=https://github.com/e2e --from-literal=username=e2e \
    --from-literal=password=e2e-token --from-literal=insecure=true --dry-run=client -o yaml | kk "$c" apply -f - >/dev/null
  kk "$c" -n argocd label secret github-creds argocd.argoproj.io/secret-type=repo-creds --overwrite >/dev/null
  for r in todo-gitops e2e-clusters; do
    kk "$c" -n argocd create secret generic "repo-$r" --from-literal=type=git --from-literal=url="https://github.com/e2e/$r" \
      --from-literal=username=e2e --from-literal=password=e2e-token --from-literal=insecure=true --dry-run=client -o yaml \
      | kk "$c" apply -f - >/dev/null
    kk "$c" -n argocd label secret "repo-$r" argocd.argoproj.io/secret-type=repository --overwrite >/dev/null
  done
  kk "$c" -n argocd create secret generic repo-cloudnative-pg-charts --from-literal=type=helm --from-literal=name=cloudnative-pg \
    --from-literal=url=https://cloudnative-pg.github.io/charts --from-literal=insecure=true --dry-run=client -o yaml \
    | kk "$c" apply -f - >/dev/null
  kk "$c" -n argocd label secret repo-cloudnative-pg-charts argocd.argoproj.io/secret-type=repository --overwrite >/dev/null
  echo "ok   $(of lc $c): github.com resolves to the git server ($ip), the credential is insecure"
}

step "Build and bootstrap both clusters with cluster-up (two k3d clusters, each with its own Argo CD)"
for c in one two; do
  (cd "$cr" && KUBECONFIG="$(of kc $c)" LOCAL_CLUSTER="$(of lc $c)" LOCAL_HTTP_PORT="$(of port $c)" bash scripts/cluster-up.sh "$c" >"$work/cluster-up-$c.log" 2>&1) &
  pids+=($!)
  (KUBECONFIG="$(of kc $c)" wire "$c") &
  pids+=($!)
done
for p in "${pids[@]}"; do
  wait "$p" || { for c in one two; do echo "--- cluster-up $c (tail)"; tail -25 "$work/cluster-up-$c.log" || true; done; diagnose; fail "a cluster-up or its wiring failed"; }
done
pids=()
grep -q "Bootstrapped k3d-$lc_one" "$work/cluster-up-one.log" || fail "cluster-up one did not bootstrap"
grep -q "Bootstrapped k3d-$lc_two" "$work/cluster-up-two.log" || fail "cluster-up two did not bootstrap"
echo "ok   both clusters are bootstrapped"

step "Each Argo CD runs only the applications of the environments assigned to it (within 10 minutes)"
apps() { kk "$1" -n argocd get applications -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' 2>/dev/null || true; }
has_app() { apps "$1" | grep -qx "$2"; }
synced() { [ "$(kk "$1" -n argocd get application "$2" -o jsonpath='{.status.sync.status}' 2>/dev/null || true)" = Synced ]; }
wait_for() { # <description> <command...>: poll for 10 minutes
  local what=$1; shift
  for _ in $(seq 1 120); do "$@" && return 0; sleep 5; done
  diagnose
  fail "$what"
}
wait_for "cluster one has no Application api-dev" has_app one api-dev
wait_for "cluster one has no Application api-staging" has_app one api-staging
wait_for "cluster two has no Application api-prod" has_app two api-prod
wait_for "api-dev on cluster one is not Synced" synced one api-dev
wait_for "api-staging on cluster one is not Synced" synced one api-staging
wait_for "api-prod on cluster two is not Synced" synced two api-prod
! has_app one api-prod || fail "cluster one runs api-prod (it belongs to cluster two)"
! has_app two api-dev || fail "cluster two runs api-dev (it belongs to cluster one)"
! has_app two api-staging || fail "cluster two runs api-staging (it belongs to cluster one)"
echo "ok   cluster one: api-dev and api-staging Synced, no api-prod; cluster two: api-prod Synced, no api-dev or api-staging"

step "Both clusters run the same CloudNativePG operator; dev runs a sha- tag, prod the pinned $semver"
cnpg_image() { kk "$1" get deploy -A -l app.kubernetes.io/name=cloudnative-pg -o jsonpath='{.items[0].spec.template.spec.containers[0].image}' 2>/dev/null || true; }
have_cnpg() { [ -n "$(cnpg_image "$1")" ]; }
wait_for "no CloudNativePG operator Deployment on cluster one" have_cnpg one
wait_for "no CloudNativePG operator Deployment on cluster two" have_cnpg two
img_one=$(cnpg_image one)
img_two=$(cnpg_image two)
[ "$img_one" = "$img_two" ] || fail "the CloudNativePG operator image differs: cluster one runs '$img_one', cluster two runs '$img_two'"
echo "ok   both operators run $img_one"
dev_image=$(kk one -n todo-dev get deploy api -o jsonpath='{.spec.template.spec.containers[0].image}')
prod_image=$(kk two -n todo-prod get deploy api -o jsonpath='{.spec.template.spec.containers[0].image}')
case "${dev_image##*:}" in sha-*) ;; *) fail "api in todo-dev runs '$dev_image', expected a sha- tag" ;; esac
[ "${dev_image##*:}" = "$sha" ] || fail "api in todo-dev runs '$dev_image', expected the pinned tag $sha"
[ "${prod_image##*:}" = "$semver" ] || fail "api in todo-prod runs '$prod_image', expected the tag $semver"
echo "ok   todo-dev (cluster one) runs $dev_image, todo-prod (cluster two) runs $prod_image"

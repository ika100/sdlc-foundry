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
# delete, a password that survives restart and a second credentials Job run, only ClusterIP, no operator (operators/ unchanged), doctor without a cache row,
# and, in the backup steps, that neither the Schedule nor the Backup nor the restore knows a cache (AC-118.6 to .8, .11, .14, .15, .19, .23).
# A message broker (spec 119) follows the caches, before the ship steps: NACK is installed by cluster-up (WITH_NACK=1), a probe image
# e2e-natsprobe:1 (nats-py) is built with the service images, and the broker `bus` carries the events APIs orders (e2e-api provides, e2e-web
# consumes) and audit (e2e-web provides). The steps prove operators/apps/nack.yaml and its pins, the server, Secrets, streams and the
# consumer, the Secret contract and /jsz, one message delivered within 30 seconds, a message published while no consumer runs, no
# redelivery of an acknowledged message, pending counts, Permissions Violation refusals, doctor's nack and broker rows, the refused
# removal while the APIs are bound and the retired names (AC-119.4, .9 to .14, .16, .19 to .22). The broker is then unbound and deleted by
# hand, so the ship and backup steps run as before. Time budget: the broker steps take at most 5 minutes in the log, NACK at cluster-up and
# the probe build at most 1.5 minutes more.
# Scaling (spec 120) runs inside the broker block, after its doctor step and before the refused removal, while the broker is up: KEDA comes
# from cluster-up (WITH_KEDA=1) and the image e2e-worker:latest (FROM the probe image) is built with the others. A component e2e-worker
# consumes the events API jobs (stream e2e-jobs) and scales 0..5 on the queue; the steps prove the pins and rendered files (AC-120.25),
# a wake from zero within 60 s (AC-120.14), a burst of 100 messages to 5 replicas within 120 s (AC-120.10), the sync emulation that keeps
# the live replica count (AC-120.19), system status (AC-120.22), a CPU autoscaler on e2e-web (AC-120.6, .17), doctor's keda and resource
# metrics rows (AC-120.18), the refusal of --replicas (AC-120.5), the return to zero replicas 295 to 420 s after the queue emptied
# (AC-120.15, AC-120.23), the cache trigger with 30 list entries (AC-120.12, .13) and the switch back to replicas (AC-120.20); the clean-up
# removes every scaling object (AC-120.27). Time budget: the scaling steps take at most 13 minutes in the log (the scale-down is the floor, a
# bounded background watcher overlaps it with the status, cpu, doctor and refusal steps), KEDA at cluster-up and the worker image at most
# 1.5 minutes more; the e2e job has 90 minutes.
# It exercises: cplat system new, resource add, component ship, instance promote|secret|verify, the templates'
# Dockerfiles (non-root numeric user, read-only filesystem), render.py on system.yaml, the generated
# Deployment/Service/HTTPRoute against a real API server, and the Gateway API on k3s' Traefik.
#
# The system answers `property_operators: owner` (spec 121): this test installs External Secrets, Kyverno and LGTM itself, so the
# renderer writes no operator Applications for them. Image pins carry tag and digest (spec 121); checks here compare via the versions table.
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
# devbox runs the init_hook before every script (a v5.0.1 python service installs pytest there: uv sync --all-extras)
hook=$(python3 -c 'import json; h = json.load(open("devbox.json"))["shell"].get("init_hook") or []; print(h if isinstance(h, str) else "\n".join(h))') || exit 2
shift 2
exec bash -c "$hook"$'\n'"$cmd" e2e-devbox "$@"
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

step "Answer property_operators: owner (spec 121: this test installs External Secrets, Kyverno and LGTM itself)"
uv run -q --with pyyaml python - "$gitops_repo/.copier-answers.yml" <<'PY' || fail "could not set property_operators: owner in .copier-answers.yml"
import sys
import yaml
path = sys.argv[1]
with open(path) as f:
    answers = yaml.safe_load(f) or {}
answers["property_operators"] = "owner"   # a string, as copier writes it
with open(path, "w") as f:
    yaml.safe_dump(answers, f, sort_keys=False)
PY
commit "property_operators: owner (spec 121: the e2e installs ESO, Kyverno and LGTM itself)"

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
# And for NACK (WITH_NACK=1): the broker is declared only after the caches, so operators/apps/nack.yaml does not exist yet either.
# And for KEDA (WITH_KEDA=1): the queue-triggered instance e2e-worker is declared only inside the broker steps, so operators/apps/keda.yaml does not exist yet.
(cd "$work/e2e-gitops" && LOCAL_CLUSTER=$cluster LOCAL_HTTP_PORT=$port WITH_ARGO=0 WITH_CNPG=1 WITH_SEAWEEDFS=1 WITH_BARMAN_CLOUD=1 WITH_VELERO=1 WITH_NACK=1 WITH_KEDA=1 REGISTRY_PORT=$regport bash scripts/local-cluster.sh up)

step "Build and push the images"
# Rendered with --skip-tasks, so the web repo has no pnpm-lock.yaml yet; the template's bootstrap would run
# `pnpm install`. Create the lock the same way (inside the image's own node base) because the Dockerfile requires it (spec 104).
node_image=$(sed -n 's/^FROM \(node:[^ ]*\).*/\1/p' "$work/e2e-web/Dockerfile" | head -1)
docker run --rm -v "$work/e2e-web:/app" -w /app "$node_image" sh -c 'corepack enable && pnpm install --lockfile-only --silent' >/dev/null
for svc in e2e-api e2e-web; do
  docker build -q -t "localhost:$regport/$svc:latest" "$work/$svc" >/dev/null
  docker push -q "localhost:$regport/$svc:latest" >/dev/null
done
# the broker steps probe with what a component uses (nats-py, spec 119): python:3.13-slim + nats-py, built from a Dockerfile on stdin
printf 'FROM python:3.13-slim\nRUN pip install --no-cache-dir nats-py==2.16.0\n' | docker build -q -t "localhost:$regport/e2e-natsprobe:1" - >/dev/null
docker push -q "localhost:$regport/e2e-natsprobe:1" >/dev/null
# the scaling steps (spec 120) need a consumer that works off a queue: e2e-worker answers 200 to every GET on $PORT, pulls from its durable
# consumer with the component's NATS_* and EVENTS_JOBS_* variables, sleeps WORK_SECONDS per message and acknowledges (FROM the probe image)
mkdir -p "$work/e2e-worker-ctx"
cat > "$work/e2e-worker-ctx/worker.py" <<'PY'
import asyncio
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import nats
from nats.errors import TimeoutError as NatsTimeout


class Health(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *args):
        pass


threading.Thread(target=ThreadingHTTPServer(("", int(os.environ.get("PORT", "8080"))), Health).serve_forever, daemon=True).start()


async def main():
    while True:
        try:
            nc = await nats.connect(os.environ["NATS_URL"], user=os.environ["NATS_USER"], password=os.environ["NATS_PASSWORD"],
                                    inbox_prefix=os.environ["NATS_INBOX_PREFIX"], connect_timeout=5)
            js = nc.jetstream()
            sub = await js.pull_subscribe_bind(durable=os.environ["EVENTS_JOBS_CONSUMER"], stream=os.environ["EVENTS_JOBS_STREAM"])
            print("worker bound to " + os.environ["EVENTS_JOBS_STREAM"], flush=True)
            while True:
                try:
                    msgs = await sub.fetch(1, timeout=5)
                except (asyncio.TimeoutError, NatsTimeout):
                    continue
                for m in msgs:
                    await asyncio.sleep(float(os.environ.get("WORK_SECONDS", "3")))
                    await m.ack()
        except Exception as e:   # printed and retried: the broker may restart under the worker
            print("ERR=%s" % e, flush=True)
            await asyncio.sleep(2)


asyncio.run(main())
PY
printf 'FROM localhost:%s/e2e-natsprobe:1\nCOPY worker.py /worker.py\nUSER 1000\nCMD ["python", "-u", "/worker.py"]\n' "$regport" > "$work/e2e-worker-ctx/Dockerfile"
docker build -q -t "localhost:$regport/e2e-worker:latest" "$work/e2e-worker-ctx" >/dev/null
docker push -q "localhost:$regport/e2e-worker:latest" >/dev/null

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

# What Argo CD does for a directory with credentials-job.yaml (spec 128): the five credentials-*.yaml (the PreSync hook objects) are
# applied first and the Job runs to completion (it writes every password Secret once, create if absent), then the whole directory is
# applied. No server is restarted to make passwords match; a forced write (rerun_credentials) runs the Job again and compares the Secret's
# resourceVersion and value hashes before and after.
kn() { local n=$1; shift; kubectl --context k3d-$cluster -n "$n" "$@"; }
hash_of() { if command -v sha256sum >/dev/null 2>&1; then sha256sum; else shasum -a 256; fi | cut -d' ' -f1; }
credentials_files() { local f; for f in serviceaccount role rolebinding configmap job; do echo "$1/credentials-$f.yaml"; done; }
credentials_apply() { # namespace dir: applies the five credentials-*.yaml and waits for the Job (its logs on failure)
  local ns_=$1 d=$2 args=() f out job
  for f in $(credentials_files "$d"); do [ -f "$f" ] || fail "render did not write $f"; args+=(-f "$f"); done
  out=$(kn "$ns_" apply "${args[@]}" -o name) || fail "applying the credentials-*.yaml of $d failed"
  job=$(sed -n 's#^job.batch/##p' <<< "$out" | head -1)
  [ -n "$job" ] || fail "$d/credentials-job.yaml did not apply a Job"
  kn "$ns_" wait --for=condition=complete job/$job --timeout=180s >/dev/null || {
    kn "$ns_" logs job/$job --tail=40 || true; kn "$ns_" describe job/$job | tail -20; fail "the credentials Job $job in $ns_ did not complete"; }
  CRED_JOB=$job
}
apply_with_credentials() { # namespace dir: the credentials first (when the directory has them), then the whole directory
  if [ -f "$2/credentials-job.yaml" ]; then credentials_apply "$1" "$2"; fi
  kn "$1" apply -k "$2" >/dev/null || fail "applying $2 failed"
}
rerun_credentials() { # namespace dir: a forced write (AC-128.3): delete the finished Job and apply its five files again
  local job
  credentials_apply "$1" "$2"; job=$CRED_JOB
  kn "$1" delete job "$job" --ignore-not-found --wait=true >/dev/null || fail "could not delete the credentials Job $job"
  credentials_apply "$1" "$2"
}
secret_rv() { kn "$1" get secret "$2" -o jsonpath='{.metadata.resourceVersion}'; }   # namespace secret
secret_hash() { kn "$1" get secret "$2" -o jsonpath='{.data}' | hash_of; }              # the hash of all values; no value is printed
secret_age() { # namespace secret: seconds since the Secret was created
  kn "$1" get secret "$2" -o jsonpath='{.metadata.creationTimestamp}' | python3 -c 'import sys, datetime as d
t = d.datetime.strptime(sys.stdin.read().strip(), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=d.timezone.utc)
print(int((d.datetime.now(d.timezone.utc) - t).total_seconds()))'
}
wait_secret_age() { # namespace secret seconds: the checks of AC-128.1, .7 and .8 start this long after the Secret exists
  local a; a=$(secret_age "$1" "$2")
  while [ "$a" -lt "$3" ]; do sleep 2; a=$(secret_age "$1" "$2"); done
}
apply_bucket() { # environment namespace [bucket, default files]
  local b=${3:-files} d k
  d="$work/e2e-gitops/applications/e2e/addons/$1/$b"
  for f in credentials-job.yaml seaweed.yaml bucket.yaml identity.yaml credentials.yaml kustomization.yaml; do
    [ -f "$d/$f" ] || fail "render did not write addons/$1/$b/$f"
  done
  [ ! -f "$d/externalsecret.yaml" ] && [ ! -f "$d/access-key-generator.yaml" ] || fail "render still writes an ExternalSecret or key generator for the bucket $b"
  credentials_apply "$2" "$d"   # the keys first (wave 0 of the PreSync hook), written once
  for k in endpoint bucket region forcePathStyle accessKeyId secretAccessKey; do
    [ -n "$(kn "$2" get secret e2e-$b-app -o jsonpath="{.data.$k}" 2>/dev/null)" ] || fail "the Secret e2e-$b-app in $2 lacks the key $k"
  done
  kn "$2" apply -f "$d/seaweed.yaml" -f "$d/bucket.yaml" -f "$d/identity.yaml" >/dev/null
  kn "$2" apply -f "$d/credentials.yaml" >/dev/null   # the S3Credentials adopt the key pair
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
  apply_with_credentials $ns "$work/e2e-gitops/applications/e2e/overlays/dev/$svc"
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

step "Generated secrets: random, written once, the same in every replica; remote values arrive via External Secrets (AC-128.8, AC-128.3)"
kc() { kubectl --context k3d-$cluster -n $ns "$@"; }
secret_val() { kc get secret "$1" -o jsonpath="{.data.$2}" 2>/dev/null | base64 -d; }
for _ in $(seq 1 40); do [ -n "$(secret_val e2e-api-auth DB_PASSWORD)" ] && [ -n "$(secret_val e2e-api-stripe STRIPE_KEY)" ] && break; sleep 3; done
db=$(secret_val e2e-api-auth DB_PASSWORD); jwt=$(secret_val e2e-api-auth JWT_KEY)
[ "${#db}" = 32 ] || fail "generated DB_PASSWORD has length ${#db}, expected 32"
[ "$db" != "$jwt" ] || fail "generated keys must differ"
[ "$(secret_val e2e-api-stripe STRIPE_KEY)" = sk_test_e2e ] || fail "remote secret did not arrive"
# AC-128.8: two replicas (one of them started later), 60 s after the Secret exists every replica sees the Secret's value (hashes only)
api_replicas=$(kc get deploy e2e-api -o jsonpath='{.spec.replicas}')
kc scale deploy e2e-api --replicas=2 >/dev/null || fail "could not scale e2e-api to 2 replicas"
kc rollout status deploy/e2e-api --timeout=240s || { kc describe pod -l app=e2e-api | tail -30; fail "e2e-api did not get two ready replicas"; }
wait_secret_age $ns e2e-api-auth 60
# e2e-api's image has no shell (distroless): a container reads its secretKeyRef/envFrom values when it starts, so a replica whose
# container started after the Secret's last write holds exactly the Secret's value; the AC-128.3 step below shows no later write
last_write=$(kc get secret e2e-api-auth -o json | python3 -c 'import json, sys; m = json.load(sys.stdin)["metadata"]; print(max([f.get("time", "") for f in m.get("managedFields") or []] + [m["creationTimestamp"]]))')
api_pods=$(kc get pods -l app=e2e-api --field-selector=status.phase=Running -o jsonpath='{.items[*].metadata.name}')
[ "$(wc -w <<< "$api_pods" | tr -d ' ')" -ge 2 ] || fail "e2e-api has fewer than two running replicas ($api_pods)"
for p in $api_pods; do
  started=$(kc get pod "$p" -o jsonpath='{.status.containerStatuses[0].state.running.startedAt}')
  [ -n "$started" ] && [[ ! "$started" < "$last_write" ]] || fail "the replica $p started at '$started', before the last write of the Secret e2e-api-auth ($last_write): it may hold another value"
done
# AC-128.3: one more write of the Secret (the Job runs again): resourceVersion and values are unchanged
rv_before=$(secret_rv $ns e2e-api-auth); hash_before=$(secret_hash $ns e2e-api-auth)
rerun_credentials $ns "$work/e2e-gitops/applications/e2e/overlays/dev/e2e-api"
[ "$(secret_rv $ns e2e-api-auth)" = "$rv_before" ] && [ "$(secret_hash $ns e2e-api-auth)" = "$hash_before" ] || fail "generated secret changed when its credentials Job ran again (it must be created once)"
[ "$(secret_val e2e-api-auth DB_PASSWORD)" = "$db" ] || fail "generated secret changed when its credentials Job ran again (it must be created once)"
kc scale deploy e2e-api --replicas="${api_replicas:-1}" >/dev/null || fail "could not scale e2e-api back"
kc rollout status deploy/e2e-api --timeout=240s || fail "e2e-api did not settle back to $api_replicas replicas"
kc get pod -l app=e2e-api -o jsonpath='{.items[0].spec.containers[0].envFrom[*].secretRef.name}' | grep -q e2e-api-auth || fail "pod does not consume the generated secret"
echo "ok   generated secret identical in both replicas and in the Secret, unchanged by a second Job run; remote secret synced and consumed"

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

step "Bucket: e2e-api writes an object through its variables and reads back the same bytes (AC-116.14, AC-128.7)"
wait_secret_age $ns e2e-files-app 60   # AC-128.7: the keys of the Secret work 60 s after it exists
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
# without Argo CD, the credentials Job running again and applying the rendered addon again is what a re-sync does; the keys are written once
key_before=$(secret_val e2e-files-app accessKeyId); secret_before=$(secret_val e2e-files-app secretAccessKey)
[ -n "$key_before" ] && [ -n "$secret_before" ] || fail "the Secret e2e-files-app has no keys before the re-sync"
files_dir="$work/e2e-gitops/applications/e2e/addons/dev/files"
rv_before=$(secret_rv $ns e2e-files-app); hash_before=$(secret_hash $ns e2e-files-app)
rerun_credentials $ns "$files_dir"   # AC-128.7: a forced write
kn $ns apply -k "$files_dir" >/dev/null || fail "applying addons/dev/files again failed"
[ "$(secret_val e2e-files-app accessKeyId)" = "$key_before" ] && [ "$(secret_val e2e-files-app secretAccessKey)" = "$secret_before" ] \
  && [ "$(secret_rv $ns e2e-files-app)" = "$rv_before" ] && [ "$(secret_hash $ns e2e-files-app)" = "$hash_before" ] \
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

cstep "Caches: apply both addons (credentials Job first), check the four keys, wait for the StatefulSets, then roll out e2e-web"
for c in sessions ratelimit; do
  [ ! -f "$gitops_repo/applications/e2e/addons/dev/$c/externalsecret.yaml" ] || cfail "render still writes an ExternalSecret for $c"
  apply_with_credentials $ns "$gitops_repo/applications/e2e/addons/dev/$c"
  for k in url host port password; do
    [ -n "$(secret_val e2e-$c-app $k)" ] || { kc logs job/"$CRED_JOB" --tail=20 || true; cfail "the Secret e2e-$c-app lacks the key $k"; }
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
[ "$(secret_val e2e-sessions-app url)" = "redis://default:${pw_sessions}@e2e-sessions.e2e-dev.svc:6379/0" ] || cfail "the url of e2e-sessions-app is not redis://default:<password>@e2e-sessions.e2e-dev.svc:6379/0"
[ "$(secret_val e2e-sessions-app host)" = e2e-sessions.e2e-dev.svc ] && [ "$(secret_val e2e-sessions-app port)" = 6379 ] || cfail "host/port of e2e-sessions-app are not e2e-sessions.e2e-dev.svc and 6379"
out=$(cx sessions "$vcli ping" 2>&1 || true)
case "$out" in *NOAUTH*) ;; *) cfail "a client without a password was not refused with NOAUTH (got: $out)";; esac
out=$(cx sessions "$vcli -a wrong-password ping" 2>&1 || true)
case "$out" in *WRONGPASS*) ;; *) cfail "a client with a wrong password was not refused with WRONGPASS (got: $out)";; esac
out=$(cx sessions "$vcli -a \"\$VALKEY_PASSWORD\" ping" 2>&1 || true)
case "$out" in *PONG*) ;; *) cfail "PING with the password from the Secret did not answer PONG (got: $out)";; esac
echo "ok   password of 32 characters, url redis://default:<password>@e2e-sessions.e2e-dev.svc:6379/0; NOAUTH without, WRONGPASS with a wrong, PONG with the password"

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

cstep "Caches: the server accepts the Secret's password and refuses any other; the component gets PONG with its own variables, after a forced write too (AC-128.1, AC-128.2, AC-128.3)"
# AC-128.1 / AC-128.2: 60 s after the Secret exists, e2e-web's variables answer PONG (REDIS_URL, and -h/-p/-a from HOST/PORT/PASSWORD)
cache_probe='for c in SESSIONS RATELIMIT; do
  eval "u=\$${c}_REDIS_URL h=\$${c}_REDIS_HOST p=\$${c}_REDIS_PORT a=\$${c}_REDIS_PASSWORD"
  echo "${c}_URL=$(valkey-cli --no-auth-warning -u "$u" PING 2>&1)"
  echo "${c}_HOST=$(valkey-cli --no-auth-warning -h "$h" -p "$p" -a "$a" PING 2>&1)"
  echo "${c}_WRONG=$(valkey-cli --no-auth-warning -h "$h" -p "$p" -a wrong-password-$$ PING 2>&1)"
done'
cache_probe_check() { # label
  crun "$cache_probe" || cfail "$1: the probe with e2e-web's variables failed: $(echo "$C_OUT" | tail -5 | tr '\n' ' ' | cut -c1-400)"
  local c
  for c in SESSIONS RATELIMIT; do
    [ "$(c_field ${c}_URL)" = PONG ] || cfail "$1: PING through ${c}_REDIS_URL answered '$(c_field ${c}_URL)', not PONG"
    [ "$(c_field ${c}_HOST)" = PONG ] || cfail "$1: PING with ${c}_REDIS_HOST, _PORT and _PASSWORD answered '$(c_field ${c}_HOST)', not PONG"
    case "$(c_field ${c}_WRONG)" in *WRONGPASS*) ;; *) cfail "$1: a wrong password for $c was not refused with WRONGPASS (got: $(c_field ${c}_WRONG))";; esac
  done
}
wait_secret_age $ns e2e-sessions-app 60; wait_secret_age $ns e2e-ratelimit-app 60
cache_probe_check "60 s after the Secrets exist"
for c in sessions ratelimit; do
  [ "$(cx $c 'printf %s "$VALKEY_PASSWORD"' | hash_of)" = "$(secret_val e2e-$c-app password | hash_of)" ] || cfail "the server of e2e-$c does not run with the password of e2e-$c-app"
  [ "$(secret_val e2e-$c-app url | sed 's#^redis://default:\([^@]*\)@.*#\1#' | hash_of)" = "$(secret_val e2e-$c-app password | hash_of)" ] || cfail "the password inside the url of e2e-$c-app differs from its password"
done
# AC-128.3: one more write (the Job runs again, the addon is applied again): resourceVersion and values are unchanged, the probe still answers
rv_s=$(secret_rv $ns e2e-sessions-app); rv_r=$(secret_rv $ns e2e-ratelimit-app)
h_s=$(secret_hash $ns e2e-sessions-app); h_r=$(secret_hash $ns e2e-ratelimit-app)
for c in sessions ratelimit; do
  rerun_credentials $ns "$gitops_repo/applications/e2e/addons/dev/$c"
  kc apply -k "$gitops_repo/applications/e2e/addons/dev/$c" >/dev/null || cfail "applying addons/dev/$c again failed"
done
[ "$(secret_rv $ns e2e-sessions-app)" = "$rv_s" ] && [ "$(secret_rv $ns e2e-ratelimit-app)" = "$rv_r" ] \
  && [ "$(secret_hash $ns e2e-sessions-app)" = "$h_s" ] && [ "$(secret_hash $ns e2e-ratelimit-app)" = "$h_r" ] || cfail "a Secret of a cache was written again by a second credentials Job run"
cache_probe_check "after a forced write"
echo "ok   both servers accept the Secret's password (REDIS_URL and HOST/PORT/PASSWORD answer PONG) and refuse a wrong one; a second Job run kept resourceVersion and values"

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
[ "$(secret_val e2e-sessions-app password)" = "$pw_sessions" ] && [ "$(secret_val e2e-ratelimit-app password)" = "$pw_ratelimit" ] || cfail "a password changed after re-applying the addons"
echo "ok   sessions kept its key (PVC data-e2e-sessions-0), ratelimit is empty and has no volume; the passwords survived the restart and the re-apply"

cstep "Caches: platform doctor names no cache, valkey, sessions or ratelimit prerequisite (AC-118.15, AC-118.23)"
doc_json="$work/doctor.json"
timeout 180 $cplat platform doctor --repo "$gitops_repo" --json > "$doc_json" 2> "$work/doctor.err" || true   # any exit code: only its rows matter
python3 - "$doc_json" <<'PY' || { tail -5 "$work/doctor.err" || true; cfail "doctor output unreadable, or a row mentions a cache (see above)"; }
import json, re, sys
rows = json.load(open(sys.argv[1]))
# whole words only: tool paths such as /opt/hostedtoolcache/... are not cache rows
bad = [r for r in rows if re.search(r"\b(cache|valkey|sessions|ratelimit)\b", f"{r.get('name', '')} {r.get('detail', '')}", re.I)]
for r in bad:
    print("doctor row names a cache:", r, file=sys.stderr)
sys.exit(1 if bad else 0)
PY
echo "ok   platform doctor lists no row for a cache"

# ---- A message broker (spec 119): NATS JetStream in dev, two events APIs, probes with the components' own variables ----
# The component overlays are not applied: the probe pods take their variables from the rendered Deployments (kubectl kustomize), so no live
# workload depends on the broker. At the end the e2e unbinds and deletes the broker by hand, so the ship and backup steps run as before.
nstep_name=""
nstep() { nstep_name="$*"; step "$*"; }
nfail() { fail "[$nstep_name] $*"; }
broker_t0=$SECONDS

nstep "Broker: declare bus and the events APIs apis.orders (e2e-api provides, e2e-web consumes) and apis.audit (e2e-web provides) (AC-119.19, AC-119.20, AC-119.11)"
# cplat refuses a dirty tree: commit first if there is anything
[ -z "$(git -C "$gitops_repo" status --porcelain)" ] || commit "before the broker"
[ ! -e "$gitops_repo/operators/apps/nack.yaml" ] || nfail "operators/apps/nack.yaml exists before any events API is bound to a broker"
$cplat resource add bus --type broker --repo-dir "$gitops_repo" >/dev/null || nfail "resource add bus --type broker failed"
commit "bus"
(cd "$gitops_repo" && uv run --with pyyaml --with ruamel.yaml python - "$root" <<'PY'
import sys
sys.path.insert(0, f"{sys.argv[1]}/scripts/cplat")
import gitops
from pathlib import Path
app_dir = gitops.find_app(Path("."))
y, data = gitops.load(app_dir)
data["apis"] = {"orders": {"type": "events"}, "audit": {"type": "events"}}   # bound to bus: the system's only broker
comps = gitops.components_of(data)
comps["e2e-api"]["provides"] = [*(comps["e2e-api"].get("provides") or []), "orders"]
comps["e2e-web"]["consumes"] = [*(comps["e2e-web"].get("consumes") or []), "orders"]
comps["e2e-web"]["provides"] = [*(comps["e2e-web"].get("provides") or []), "audit"]
gitops.save(app_dir, y, data)
PY
uv run scripts/render.py) || nfail "render.py failed with the broker and its events APIs"
commit "broker: bus with the events APIs orders and audit"
bus_dir="$gitops_repo/applications/e2e/addons/dev/bus"
# the operator file exists now; the HelmChart that cluster-up installed (WITH_NACK=1) is its pin (AC-119.20)
[ -f "$gitops_repo/operators/apps/nack.yaml" ] || nfail "render did not write operators/apps/nack.yaml for the in-cluster broker"
nack_pin=$(sed -n 's/^[[:space:]]*targetRevision:[[:space:]]*["'"'"']\{0,1\}\([^"'"'"'[:space:]]*\).*/\1/p' "$gitops_repo/operators/apps/nack.yaml" | head -1)
nack_have=$(kubectl --context k3d-$cluster -n kube-system get helmcharts.helm.cattle.io nack -o jsonpath='{.spec.version}' 2>/dev/null || true)
[ "$nack_pin" = 0.35.0 ] || nfail "operators/apps/nack.yaml pins '$nack_pin', expected the NACK chart 0.35.0"
[ "$nack_have" = "$nack_pin" ] || nfail "the installed NACK chart is '$nack_have', operators/apps/nack.yaml pins '$nack_pin'"
nack_image=$(kubectl --context k3d-$cluster -n nack get deploy -l app=nack -o jsonpath='{.items[0].spec.template.spec.containers[0].image}' 2>/dev/null || true)
nack_image=${nack_image%%@*}   # the reference may carry a digest (spec 121)
[ "${nack_image##*:}" = 0.24.0 ] || nfail "the NACK Deployment runs '$nack_image', expected the tag 0.24.0"
kubectl --context k3d-$cluster get crd streams.jetstream.nats.io consumers.jetstream.nats.io accounts.jetstream.nats.io >/dev/null || nfail "the NACK CRDs are not installed"
for f in credentials-serviceaccount.yaml credentials-role.yaml credentials-rolebinding.yaml credentials-configmap.yaml credentials-job.yaml server.yaml account.yaml \
         stream-orders.yaml stream-audit.yaml consumer-orders.e2e-web.yaml kustomization.yaml; do
  [ -f "$bus_dir/$f" ] || nfail "render did not write addons/dev/bus/$f"
done
[ -z "$(ls "$bus_dir" | grep -E '^(password-generator|nack-secret|externalsecret)' || true)" ] || nfail "render still writes a generator, a nack-secret.yaml or an ExternalSecret for the broker"
[ -z "$(ls "$bus_dir" | grep -E '^consumer-audit' || true)" ] || nfail "render wrote a consumer for audit, which nobody consumes"
# the server pin (chart and image), and the variables of both components in the rendered overlays (kubectl kustomize overlays/dev/<component>)
read -r -d '' decl_py <<'PY' || true
import ast, json, os, subprocess, sys
from pathlib import Path
import yaml
app, work = Path(sys.argv[1]), Path(sys.argv[2])
bad = []
# the expected NATS image is the versions table's (tag and digest), read from render.py without importing it (spec 121)
nats_expected = None
for node in ast.parse((Path(os.environ["E2E_ROOT"]) / "templates/gitops-app/scripts/render.py").read_text()).body:
    if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "NATS_IMAGES" for t in node.targets):
        nats_expected = ast.literal_eval(node.value)["2.15"]
if not nats_expected:
    bad.append("NATS_IMAGES['2.15'] not found in templates/gitops-app/scripts/render.py")
src = yaml.safe_load((app / "addons/dev/bus/server.yaml").read_text())["spec"]["source"]
image = src["helm"]["valuesObject"]["container"]["image"]
if src["chart"] != "nats" or src["targetRevision"] != "2.15.1":
    bad.append(f"server.yaml pins chart {src['chart']} {src['targetRevision']}, expected nats 2.15.1")
if f"{image['repository']}:{image['tag']}" != nats_expected:
    bad.append(f"server.yaml pins the image {image['repository']}:{image['tag']}, expected {nats_expected} (NATS_IMAGES['2.15'])")

def env_of(c):
    out = subprocess.run(["kubectl", "kustomize", str(app / "overlays/dev" / c)], capture_output=True, text=True)
    if out.returncode:
        bad.append(f"kubectl kustomize overlays/dev/{c} failed: {out.stderr[-300:]}")
        return []
    for d in yaml.safe_load_all(out.stdout):
        if d and d.get("kind") == "Deployment":
            env = [e for e in d["spec"]["template"]["spec"]["containers"][0].get("env", []) if e["name"].startswith(("NATS_", "EVENTS_"))]
            (work / f"natsenv-{c}.json").write_text(json.dumps(env))
            return env
    bad.append(f"overlays/dev/{c} has no Deployment")
    return []

def check(c, literals, absent):
    env = {e["name"]: e for e in env_of(c)}
    for k, v in literals.items():
        if env.get(k, {}).get("value") != v:
            bad.append(f"{c}: {k} is {env.get(k, {}).get('value')!r}, expected {v!r}")
    for k, key in (("NATS_URL", "url"), ("NATS_USER", "user"), ("NATS_PASSWORD", "password")):
        ref = env.get(k, {}).get("valueFrom", {}).get("secretKeyRef", {})
        if ref != {"name": f"e2e-bus-{c}-app", "key": key}:
            bad.append(f"{c}: {k} reads {ref}, expected the key {key} of e2e-bus-{c}-app")
    for k in absent:
        if k in env:
            bad.append(f"{c}: has {k}, which it must not have")

check("e2e-web", {"EVENTS_ORDERS_STREAM": "e2e-orders", "EVENTS_ORDERS_SUBJECT_PREFIX": "e2e.orders", "EVENTS_ORDERS_CONSUMER": "e2e-web",
                  "EVENTS_AUDIT_STREAM": "e2e-audit", "EVENTS_AUDIT_SUBJECT_PREFIX": "e2e.audit", "NATS_INBOX_PREFIX": "_INBOX.e2e-web"},
      ["EVENTS_AUDIT_CONSUMER"])
check("e2e-api", {"EVENTS_ORDERS_STREAM": "e2e-orders", "EVENTS_ORDERS_SUBJECT_PREFIX": "e2e.orders", "NATS_INBOX_PREFIX": "_INBOX.e2e-api"},
      ["EVENTS_ORDERS_CONSUMER", "EVENTS_AUDIT_STREAM", "EVENTS_AUDIT_SUBJECT_PREFIX", "EVENTS_AUDIT_CONSUMER"])
print("\n".join(bad), file=sys.stderr)
sys.exit(1 if bad else 0)
PY
(cd "$gitops_repo" && E2E_ROOT="$root" uv run -q --with pyyaml python -c "$decl_py" "$gitops_repo/applications/e2e" "$work") || nfail "the rendered broker files or component variables are not as designed (see above)"
echo "ok   operators/apps/nack.yaml pins nack $nack_pin (installed), the NACK Deployment runs 0.24.0; server.yaml pins nats chart 2.15.1 and nats:2.15.2-alpine; e2e-web and e2e-api get NATS_* from e2e-bus-<component>-app, EVENTS_ORDERS_*/EVENTS_AUDIT_* and NATS_INBOX_PREFIX"

nstep "Broker: apply the addon without Argo CD (the credentials Job first, then the NATS server as a k3s HelmChart, then Account, streams and consumer) and wait for them (AC-119.21)"
# what Argo CD would do: the Application becomes a helmcharts.helm.cattle.io (same repo, chart, version, values); the rest is applied as rendered
read -r -d '' apply_py <<'PY' || true
import sys
import yaml
docs = [d for d in yaml.safe_load_all(sys.stdin) if d]
first, second, chart = [], [], None
for d in docs:
    if d["kind"] == "Application":
        s = d["spec"]["source"]
        chart = {"apiVersion": "helm.cattle.io/v1", "kind": "HelmChart", "metadata": {"name": s["helm"]["releaseName"], "namespace": "kube-system"},
                 "spec": {"repo": s["repoURL"], "chart": s["chart"], "version": s["targetRevision"],
                          "targetNamespace": d["spec"]["destination"]["namespace"], "valuesContent": yaml.safe_dump(s["helm"]["valuesObject"])}}
    elif d["kind"] in ("ServiceAccount", "Role", "RoleBinding", "ConfigMap", "Job"):
        first.append(d)   # the credentials objects: the script applies them from their files and waits for the Job
    elif d["kind"] in ("Account", "Stream", "Consumer"):
        second.append(d)
    else:
        sys.exit(f"unexpected kind {d['kind']} in addons/dev/bus")
if chart is None:
    sys.exit("addons/dev/bus has no Application")
for path, items in zip(sys.argv[1:4], ([*first], [chart], [*second])):
    open(path, "w").write(yaml.safe_dump_all(items))
PY
kubectl kustomize "$bus_dir" | (cd "$gitops_repo" && uv run -q --with pyyaml python -c "$apply_py" "$work/bus-1.yaml" "$work/bus-chart.yaml" "$work/bus-2.yaml") || nfail "could not turn the rendered addon into objects to apply"
credentials_apply $ns "$bus_dir"   # PreSync: the Secrets of the broker are written once, no server is running yet
bus_secrets="e2e-bus-nack e2e-bus-e2e-api-app e2e-bus-e2e-web-app"
for s in $bus_secrets; do
  [ -n "$(secret_val $s password)" ] || { kc logs job/"$CRED_JOB" --tail=20 || true; nfail "the Secret $s has no password after the credentials Job"; }
done
kubectl --context k3d-$cluster apply -f "$work/bus-chart.yaml" >/dev/null || nfail "applying the HelmChart e2e-bus failed"
for _ in $(seq 1 40); do kc get statefulsets.apps e2e-bus >/dev/null 2>&1 && break; sleep 3; done   # up to 120 s
if ! kc get statefulsets.apps e2e-bus >/dev/null 2>&1; then
  kubectl --context k3d-$cluster -n kube-system get pods | grep -E 'helm-install-e2e-bus' || true
  kubectl --context k3d-$cluster -n kube-system logs job/helm-install-e2e-bus --tail=30 || true
  nfail "the StatefulSet e2e-bus did not appear within 120 s"
fi
if ! kc rollout status statefulsets.apps/e2e-bus --timeout=180s 2>&1 | tee /dev/stderr; then
  kc get pods; kc describe pod e2e-bus-0 | tail -30; kc logs e2e-bus-0 -c nats --tail=20 || true
  nfail "the StatefulSet e2e-bus did not become ready"
fi
bus_server_ready_t=$SECONDS
kc apply -f "$work/bus-2.yaml" >/dev/null || nfail "applying the Account, the streams and the consumer failed"
bus_ready() { # kind name: the NACK object reports Ready
  [ "$(kc get "$1" "$2" -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}' 2>/dev/null)" = True ]
}
for o in streams.jetstream.nats.io/e2e-orders streams.jetstream.nats.io/e2e-audit consumers.jetstream.nats.io/e2e-orders.e2e-web; do
  for _ in $(seq 1 40); do bus_ready "${o%%/*}" "${o#*/}" && break; sleep 3; done   # up to 120 s
  bus_ready "${o%%/*}" "${o#*/}" || {
    kc describe "${o%%/*}" "${o#*/}" | tail -25; kc get accounts.jetstream.nats.io e2e-bus -o yaml | tail -20
    kubectl --context k3d-$cluster -n nack logs deploy/nack --tail=30 || true
    nfail "$o is not Ready after 120 s"; }
done
echo "ok   the Secrets, the server (e2e-bus-0), the streams e2e-orders and e2e-audit and the consumer e2e-orders.e2e-web are ready"

nstep "Broker: the Secrets hold url, user and a 32-character password; the Service is ClusterIP on 4222 and 8222; /jsz shows the streams and the consumer (AC-119.9, AC-119.10, AC-119.11, AC-119.21)"
for c in e2e-api e2e-web; do
  [ "$(secret_val e2e-bus-$c-app url)" = nats://e2e-bus.e2e-dev.svc:4222 ] || nfail "the url of e2e-bus-$c-app is not nats://e2e-bus.e2e-dev.svc:4222"
  [ "$(secret_val e2e-bus-$c-app user)" = "$c" ] || nfail "the user of e2e-bus-$c-app is not $c"
  [ "$(secret_val e2e-bus-$c-app password | wc -c | tr -d ' ')" = 32 ] || nfail "the password of e2e-bus-$c-app is not 32 characters"
done
[ "$(secret_val e2e-bus-nack user)" = _nack ] && [ "$(secret_val e2e-bus-nack password | wc -c | tr -d ' ')" = 32 ] || nfail "e2e-bus-nack does not hold the user _nack and a 32-character password"
[ "$(secret_val e2e-bus-e2e-api-app password)" != "$(secret_val e2e-bus-e2e-web-app password)" ] || nfail "both components got the same password"
[ "$(kc get services e2e-bus -o jsonpath='{.spec.type}')" = ClusterIP ] || nfail "the Service e2e-bus is not of type ClusterIP"
svc_ports=" $(kc get services e2e-bus -o jsonpath='{.spec.ports[*].port}') "
case "$svc_ports" in *" 4222 "*) ;; *) nfail "the Service e2e-bus lacks the port 4222 (ports:$svc_ports)";; esac
case "$svc_ports" in *" 8222 "*) ;; *) nfail "the Service e2e-bus lacks the monitoring port 8222 (ports:$svc_ports)";; esac
# /jsz is read inside the server pod (the monitoring port 8222, unauthenticated); the streams, their limits and the consumer
read -r -d '' jsz_py <<'PY' || true
import json, sys
d = json.load(sys.stdin)
for a in d.get("account_details") or []:
    for s in a.get("stream_detail") or []:
        n, c = s["name"], s.get("config") or {}
        print(f"S.{n}.subjects={','.join(c.get('subjects') or [])}")
        print(f"S.{n}.max_age={c.get('max_age')}")
        print(f"S.{n}.storage={c.get('storage')}")
        print(f"S.{n}.messages={(s.get('state') or {}).get('messages')}")
        for k in s.get("consumer_detail") or []:
            p, cc = f"C.{n}.{k['name']}", k.get("config") or {}
            print(f"{p}.ack_policy={cc.get('ack_policy')}")
            print(f"{p}.ack_wait={cc.get('ack_wait')}")
            print(f"{p}.num_pending={k.get('num_pending')}")
            print(f"{p}.num_ack_pending={k.get('num_ack_pending')}")
PY
jsz() { kc exec e2e-bus-0 -c nats -- wget -qO- "http://127.0.0.1:8222/jsz?accounts=true&streams=true&consumers=true&config=true" | python3 -c "$jsz_py"; }
jf() { sed -n "s/^$1=//p" <<< "$J" | head -1; }
jsz_wait() { # seconds key=value...: reads /jsz until every pair holds (J keeps the last reading)
  local t=$1 i kv ok; shift
  for i in $(seq 1 "$t"); do
    J=$(jsz 2>/dev/null) || J=""
    ok=1; for kv in "$@"; do [ "$(jf "${kv%%=*}")" = "${kv#*=}" ] || ok=0; done
    [ $ok = 1 ] && return 0; sleep 1
  done
  return 1
}
week_ns=604800000000000   # 7 days
jsz_wait 20 S.e2e-orders.subjects='e2e.orders.>' S.e2e-audit.subjects='e2e.audit.>' S.e2e-orders.max_age=$week_ns S.e2e-audit.max_age=$week_ns \
  S.e2e-orders.storage=file S.e2e-audit.storage=file C.e2e-orders.e2e-web.ack_policy=explicit C.e2e-orders.e2e-web.ack_wait=30000000000 \
  || { echo "$J"; nfail "/jsz does not show the streams (e2e.orders.> and e2e.audit.>, max_age 7 days, file storage) and the consumer e2e-web (explicit, ack wait 30 s)"; }
[ -z "$(grep -E '^C\.e2e-audit\.' <<< "$J")" ] || nfail "the stream e2e-audit has a consumer, although nobody consumes audit"
[ "$(kc get consumers.jetstream.nats.io e2e-orders.e2e-web -o jsonpath='{.spec.durableName} {.spec.ackPolicy} {.spec.ackWait}')" = "e2e-web explicit 30s" ] || nfail "the Consumer object e2e-orders.e2e-web is not durable e2e-web, explicit, 30s"
echo "ok   Secrets with url nats://e2e-bus.e2e-dev.svc:4222, user and a 32-character password; Service ClusterIP on 4222 and 8222; streams e2e.orders.> and e2e.audit.> (7 days, file) and the consumer e2e-web (explicit, ack wait 30 s)"

# probe pods (plain Pods, not Deployments: the guard rails do not cover them) with the rendered variables of a component, in the nats-py image
nats_image="$registry:$regport/e2e-natsprobe:1"
read -r -d '' nats_pod_py <<'PY' || true
import json, sys
name, image, script, envfile = sys.argv[1:5]
env = json.load(open(envfile)) + [{"name": k, "value": v} for k, v in (("PYTHONDONTWRITEBYTECODE", "1"), ("PYTHONUNBUFFERED", "1"), ("HOME", "/tmp"))]
ctx = {"allowPrivilegeEscalation": False, "readOnlyRootFilesystem": True, "capabilities": {"drop": ["ALL"]}}
print(json.dumps({"apiVersion": "v1", "kind": "Pod", "metadata": {"name": name, "labels": {"app": "natsprobe"}},
                  "spec": {"restartPolicy": "Never",
                           "securityContext": {"runAsNonRoot": True, "runAsUser": 1000, "runAsGroup": 1000, "seccompProfile": {"type": "RuntimeDefault"}},
                           "containers": [{"name": "probe", "image": image, "command": ["python", "-c", script], "env": env, "securityContext": ctx}]}}))
PY
nn=0
nrun() { # component script: runs it in a pod that carries the component's NATS_* and EVENTS_* variables; output in N_OUT
  local name phase=""
  nn=$((nn + 1)); name="natsprobe-$nn"
  python3 -c "$nats_pod_py" "$name" "$nats_image" "$2" "$work/natsenv-$1.json" | kc apply -f - >/dev/null || nfail "could not start the probe pod $name"
  for _ in $(seq 1 90); do   # up to 180 s
    phase=$(kc get pod "$name" -o jsonpath='{.status.phase}' 2>/dev/null || true)
    case "$phase" in Succeeded|Failed) break;; esac; sleep 2
  done
  N_OUT=$(kc logs "$name" 2>&1 || true)
  [ "$phase" = Succeeded ] || { N_OUT="$N_OUT (pod phase: ${phase:-unknown}; $(kc get pod "$name" -o jsonpath='{.status.containerStatuses[*].state.waiting.reason}' 2>/dev/null))"; kc describe pod "$name" | tail -15; }
  kc delete pod "$name" --wait=false >/dev/null 2>&1 || true
  [ "$phase" = Succeeded ]
}
n_field() { sed -n "s/^$1=//p" <<< "$N_OUT" | head -1; }
n_must() { nrun "$1" "$2" || nfail "the probe of $1 failed: $(echo "$N_OUT" | tail -8 | tr '\n' ' ' | cut -c1-600)"; }
# AC-128.4 / AC-128.5: a component connects with its own NATS_URL, NATS_USER and NATS_PASSWORD (a wrong password is refused)
read -r -d '' nats_auth_py <<'PY' || true
import asyncio, os
import nats

async def main():
    nc = await nats.connect(os.environ["NATS_URL"], user=os.environ["NATS_USER"], password=os.environ["NATS_PASSWORD"], connect_timeout=5)
    await nc.flush()
    print("AUTH=ok")
    await nc.close()
    try:
        bad = await nats.connect(os.environ["NATS_URL"], user=os.environ["NATS_USER"], password="wrong-password", connect_timeout=5, allow_reconnect=False)
        await bad.close()
        print("WRONG=accepted")
    except Exception as e:
        print("WRONG=refused")
asyncio.run(main())
PY
bus_auth() { # label component...: each component authenticates with the password of its Secret and no other
  local label=$1 c; shift
  for c in "$@"; do
    n_must "$c" "$nats_auth_py"
    [ "$(n_field AUTH)" = ok ] || nfail "$label: $c did not authenticate with its NATS_USER and NATS_PASSWORD: $N_OUT"
    [ "$(n_field WRONG)" = refused ] || nfail "$label: the server accepted a wrong password for $c: $N_OUT"
  done
}

nstep "Broker: _nack and every component user authenticate without a server restart, also after a forced write of the Secrets (AC-128.4, AC-128.6)"
bus_ready accounts.jetstream.nats.io e2e-bus || { kc describe accounts.jetstream.nats.io e2e-bus | tail -25; kubectl --context k3d-$cluster -n nack logs deploy/nack --tail=30 || true; nfail "the NACK Account e2e-bus is not Ready (the user _nack does not authenticate with the password of e2e-bus-nack)"; }
[ "$(kc get pod e2e-bus-0 -o jsonpath='{.status.containerStatuses[?(@.name=="nats")].restartCount}')" = 0 ] || nfail "the server e2e-bus-0 was restarted"
bus_auth "after the server is ready" e2e-api e2e-web
bus_rv=""; bus_h=""
for s in $bus_secrets; do bus_rv="$bus_rv $(secret_rv $ns $s)"; bus_h="$bus_h $(secret_hash $ns $s)"; done
rerun_credentials $ns "$bus_dir"   # AC-128.6: the Job runs again
bus_rv2=""; bus_h2=""
for s in $bus_secrets; do bus_rv2="$bus_rv2 $(secret_rv $ns $s)"; bus_h2="$bus_h2 $(secret_hash $ns $s)"; done
[ "$bus_rv2" = "$bus_rv" ] && [ "$bus_h2" = "$bus_h" ] || nfail "a Secret of the broker was written again by a second credentials Job run"
[ "$(kc get pod e2e-bus-0 -o jsonpath='{.status.containerStatuses[?(@.name=="nats")].restartCount}')" = 0 ] || nfail "the credentials Job run again restarted the server"
bus_auth "after a forced write" e2e-api e2e-web
echo "ok   the NACK Account is Ready; e2e-api and e2e-web authenticate (a wrong password is refused); a second Job run kept every resourceVersion and password"
# what every probe does first: connect the way the docs example does (NATS_URL, NATS_USER, NATS_PASSWORD, NATS_INBOX_PREFIX)
read -r -d '' natspre <<'PY' || true
import asyncio, os, time
import nats
from nats.errors import TimeoutError as NatsTimeout

ERRS = []

async def on_error(e):
    ERRS.append(str(e))
    print("ERR=" + str(e).replace("\n", " "), flush=True)

async def connect():
    return await nats.connect(os.environ["NATS_URL"], user=os.environ["NATS_USER"], password=os.environ["NATS_PASSWORD"],
                              inbox_prefix=os.environ["NATS_INBOX_PREFIX"], error_cb=on_error, connect_timeout=5)

def violations(subject=None):
    # the server says "Permissions Violation"; nats-py reports it as "nats: permissions violation for ..."
    return len([e for e in ERRS if "permissions violation" in e.lower() and (subject is None or subject in e)])

async def settle(nc):
    await nc.flush()
    await asyncio.sleep(1)   # the server answers a refusal asynchronously
PY

nstep "Broker: e2e-api publishes m1 and e2e-web fetches it within 30 seconds of the publish, through the docs example's calls (AC-119.13)"
n_must e2e-api "$natspre"'
async def main():
    nc = await connect()
    js = nc.jetstream()
    ack = await js.publish(os.environ["EVENTS_ORDERS_SUBJECT_PREFIX"] + ".created", b"m1")   # e2e.orders.created
    print("PUBLISHED=%s" % ack.stream)
    print("T=%d" % int(time.time()))
    await nc.close()
asyncio.run(main())'
[ "$(n_field PUBLISHED)" = e2e-orders ] || nfail "e2e-api published m1 but the stream is '$(n_field PUBLISHED)', not e2e-orders: $N_OUT"
t_pub=$(n_field T)
n_must e2e-web "$natspre"'
async def main():
    nc = await connect()
    js = nc.jetstream()
    sub = await js.pull_subscribe_bind(durable=os.environ["EVENTS_ORDERS_CONSUMER"], stream=os.environ["EVENTS_ORDERS_STREAM"])
    msgs = await sub.fetch(1, timeout=30)
    print("RECEIVED=" + ",".join(m.data.decode() for m in msgs))
    print("T=%d" % int(time.time()))
    for m in msgs:
        await m.ack()
    await settle(nc)
    print("VIOLATIONS_BEFORE_REFUSALS=%d" % violations())
    # e2e-web consumes orders: it may not publish on e2e.orders.created, nor subscribe to e2e.orders.>; it provides audit: e2e.audit.done is allowed
    await nc.publish("e2e.orders.created", b"forbidden")
    await settle(nc)
    print("REFUSED_PUBLISH_ORDERS=%d" % violations("e2e.orders.created"))
    await nc.subscribe("e2e.orders.>")
    await settle(nc)
    print("REFUSED_SUBSCRIBE_ORDERS=%d" % violations("e2e.orders.>"))
    ack = await js.publish("e2e.audit.done", b"a1")
    print("AUDIT_PUBLISHED=%s" % ack.stream)
    await nc.close()
asyncio.run(main())'
[ "$(n_field RECEIVED)" = m1 ] || nfail "e2e-web fetched '$(n_field RECEIVED)', not m1: $N_OUT"
t_got=$(n_field T)
[ -n "$t_pub" ] && [ -n "$t_got" ] && [ $((t_got - t_pub)) -le 30 ] || nfail "m1 was fetched $((t_got - t_pub)) s after it was published (more than 30 s)"
[ "$(n_field VIOLATIONS_BEFORE_REFUSALS)" = 0 ] || nfail "a fetch or an acknowledgement of e2e-web was refused: $N_OUT"
echo "ok   e2e-web fetched m1 $((t_got - t_pub)) s after e2e-api published it, and acknowledged it"

nstep "Broker: refusals of e2e-web (AC-119.12): no publish on e2e.orders.created, no subscribe to e2e.orders.>, publish on e2e.audit.done allowed"
grep -qi 'Permissions Violation.*e2e.orders.created' <<< "$N_OUT" || nfail "publishing on e2e.orders.created was not refused with a Permissions Violation: $N_OUT"
grep -qi 'Permissions Violation.*e2e.orders.>' <<< "$N_OUT" || nfail "subscribing to e2e.orders.> was not refused with a Permissions Violation: $N_OUT"
[ "$(n_field REFUSED_PUBLISH_ORDERS)" = 1 ] && [ "$(n_field REFUSED_SUBSCRIBE_ORDERS)" = 1 ] || nfail "expected one refusal for each of the two actions: $N_OUT"
[ "$(n_field AUDIT_PUBLISHED)" = e2e-audit ] || nfail "e2e-web could not publish on e2e.audit.done (stream '$(n_field AUDIT_PUBLISHED)'): $N_OUT"
jsz_wait 15 S.e2e-orders.messages=1 S.e2e-audit.messages=1 C.e2e-orders.e2e-web.num_pending=0 C.e2e-orders.e2e-web.num_ack_pending=0 \
  || { echo "$J"; nfail "after m1 the stream e2e-orders should hold 1 message (the refused publish stores none), e2e-audit 1, and the consumer 0 pending, 0 ack-pending"; }
echo "ok   e2e-web's publish on e2e.orders.created and subscribe to e2e.orders.> got a Permissions Violation and stored nothing; e2e.audit.done went through"

nstep "Broker: e2e-api publishes m2 and m3 while no consumer runs; /jsz shows 2 pending and 0 ack-pending (AC-119.13, AC-119.16, AC-119.12)"
n_must e2e-api "$natspre"'
async def main():
    nc = await connect()
    js = nc.jetstream()
    for body in (b"m2", b"m3"):
        await js.publish(os.environ["EVENTS_ORDERS_SUBJECT_PREFIX"] + ".created", body)
    print("PUBLISHED=m2,m3")
    print("VIOLATIONS_BEFORE_REFUSALS=%d" % violations())
    # e2e-api does not belong to audit: no subscribe to e2e.audit.>, no publish on e2e.audit.x
    await nc.subscribe("e2e.audit.>")
    await settle(nc)
    print("REFUSED_SUBSCRIBE_AUDIT=%d" % violations("e2e.audit.>"))
    await nc.publish("e2e.audit.x", b"forbidden")
    await settle(nc)
    print("REFUSED_PUBLISH_AUDIT=%d" % violations("e2e.audit.x"))
    await nc.close()
asyncio.run(main())'
[ "$(n_field PUBLISHED)" = m2,m3 ] && [ "$(n_field VIOLATIONS_BEFORE_REFUSALS)" = 0 ] || nfail "e2e-api could not publish m2 and m3: $N_OUT"
grep -qi 'Permissions Violation.*e2e.audit.>' <<< "$N_OUT" || nfail "e2e-api subscribing to e2e.audit.> was not refused with a Permissions Violation: $N_OUT"
grep -qi 'Permissions Violation.*e2e.audit.x' <<< "$N_OUT" || nfail "e2e-api publishing on e2e.audit.x was not refused with a Permissions Violation: $N_OUT"
# the consumer e2e-web reads /jsz while no consumer process runs: m2 and m3 wait on the server (m1 is acknowledged)
jsz_wait 15 S.e2e-orders.messages=3 S.e2e-audit.messages=1 C.e2e-orders.e2e-web.num_pending=2 C.e2e-orders.e2e-web.num_ack_pending=0 \
  || { echo "$J"; nfail "/jsz should show 3 messages in e2e-orders (1 in e2e-audit: the refused e2e.audit.x stored nothing), num_pending 2 and num_ack_pending 0"; }
echo "ok   e2e-api's subscribe to e2e.audit.> and publish on e2e.audit.x got a Permissions Violation; num_pending 2, num_ack_pending 0 for the consumer e2e-web"

nstep "Broker: e2e-web fetches m2 and m3 (published while no consumer ran, not m1), acknowledges; an acknowledged message is not delivered again (AC-119.13, AC-119.16)"
n_must e2e-web "$natspre"'
async def main():
    nc = await connect()
    js = nc.jetstream()
    sub = await js.pull_subscribe_bind(durable=os.environ["EVENTS_ORDERS_CONSUMER"], stream=os.environ["EVENTS_ORDERS_STREAM"])
    msgs = await sub.fetch(2, timeout=30)
    print("RECEIVED=" + ",".join(sorted(m.data.decode() for m in msgs)))
    for m in msgs:
        await m.ack()
    await settle(nc)
    try:
        more = await sub.fetch(1, timeout=3)
        print("AGAIN=" + ",".join(m.data.decode() for m in more))
    except (asyncio.TimeoutError, NatsTimeout):
        print("AGAIN=none")
    print("VIOLATIONS=%d" % violations())
    await nc.close()
asyncio.run(main())'
[ "$(n_field RECEIVED)" = m2,m3 ] || nfail "e2e-web fetched '$(n_field RECEIVED)', exactly m2 and m3 were expected (not m1): $N_OUT"
[ "$(n_field AGAIN)" = none ] || nfail "a further fetch delivered '$(n_field AGAIN)': an acknowledged message must not be delivered again"
[ "$(n_field VIOLATIONS)" = 0 ] || nfail "an acknowledgement of e2e-web was refused: $N_OUT"
jsz_wait 15 S.e2e-orders.messages=3 C.e2e-orders.e2e-web.num_pending=0 C.e2e-orders.e2e-web.num_ack_pending=0 \
  || { echo "$J"; nfail "after the acknowledgements /jsz should show 0 pending, 0 ack-pending and 3 messages in e2e-orders"; }
echo "ok   e2e-web fetched m2 and m3 only, acknowledged them, and a further fetch timed out; num_pending 0, num_ack_pending 0, e2e-orders keeps 3 messages"

nstep "Broker: platform doctor shows the operator nack and broker bus (dev) rows as ok (AC-119.22)"
kubectl config use-context k3d-$cluster >/dev/null || nfail "could not select the kube context k3d-$cluster"
timeout 180 $cplat platform doctor --repo "$gitops_repo" --json > "$work/doctor-broker.json" 2> "$work/doctor-broker.err" || true   # any exit code: only its rows matter
python3 - "$work/doctor-broker.json" <<'PY' || { tail -5 "$work/doctor-broker.err" || true; nfail "doctor output unreadable, or the nack or broker row is not as expected (see above)"; }
import json, sys
rows = {r["name"]: r for r in json.load(open(sys.argv[1]))}
bad = []
for name, needles in (("operator nack", ["0.24.0"]), ("broker bus (dev)", ["nats chart 2.15.1", "nats:2.15.2-alpine"])):
    r = rows.get(name)
    if r is None:
        bad.append(f"no row '{name}'")
    elif r["status"] != "ok" or not all(n in r["detail"] for n in needles):
        bad.append(f"row '{name}' is {r['status']}: {r['detail']}")
print("\n".join(bad), file=sys.stderr)
sys.exit(1 if bad else 0)
PY
echo "ok   platform doctor: operator nack (0.24.0) and broker bus (dev) (nats chart 2.15.1, nats:2.15.2-alpine) are ok"

# ---- Scaling (spec 120): the queue-triggered consumer e2e-worker (KEDA) and a CPU autoscaler, against the running broker ----
# Everything is applied without Argo CD, the way its sync would: the rendered files, the HelmChart for the broker, KEDA's objects by their full
# kind names. Probes connect with the variables of the component they stand for. The time budget is in the header.
sstep_name=""
scaling_t0=$SECONDS
sstep_t=$SECONDS
sstep() { sstep_name="$*"; sstep_t=$SECONDS; step "$*"; }
sfail() { fail "[$sstep_name] $*"; }
sok() { echo "ok   $* [this step $((SECONDS - sstep_t)) s, scaling steps $((SECONDS - scaling_t0)) s]"; }
sapp="$gitops_repo/applications/e2e"
ovd() { echo "$sapp/overlays/dev/$1"; }
clean_tree() { [ -z "$(git -C "$gitops_repo" status --porcelain)" ] || commit "$1"; }   # cplat refuses a dirty tree
wdep() { kc get deployments.apps e2e-worker -o jsonpath="{$1}" 2>/dev/null || true; }
pin_of() { sed -n 's/^[[:space:]]*targetRevision:[[:space:]]*["'"'"']\{0,1\}\([^"'"'"'[:space:]]*\).*/\1/p' "$1" | head -1; }
sdiag() { # what a failure shows: the scaler objects, the Deployment, the events and KEDA's own log
  kc get scaledobjects.keda.sh,triggerauthentications.keda.sh,horizontalpodautoscalers.autoscaling,deployments.apps,pods 2>&1 | tail -25 || true
  kc describe scaledobjects.keda.sh e2e-worker 2>&1 | tail -30 || true
  kc get events --sort-by=.lastTimestamp 2>&1 | tail -15 || true
  kubectl --context k3d-$cluster -n keda logs -l app.kubernetes.io/name=keda-operator --tail=40 2>&1 | tail -40 || true
}

# edits of system.yaml: python statements over data (the document) and comps (its components); saved, then rendered (output in S_RENDER)
read -r -d '' sedit_pre <<'PY' || true
import sys
sys.path.insert(0, f"{sys.argv[1]}/scripts/cplat")
import compose, core, gitops
from pathlib import Path
registry = sys.argv[2]
app_dir = gitops.find_app(Path("."))
y, data = gitops.load(app_dir)
comps = gitops.components_of(data)
PY
sedit() {
  S_RENDER=$(cd "$gitops_repo" && uv run -q --with pyyaml --with ruamel.yaml python -c "$sedit_pre
$1
gitops.save(app_dir, y, data)" "$root" "$registry:$regport" && uv run scripts/render.py 2>&1 | tee /dev/stderr) || sfail "could not change system.yaml or render it"
}
# the documents of some kinds from a rendered overlay (a kustomize build), applied alone: what Argo CD's waves and prune amount to here
read -r -d '' pick_py <<'PY' || true
import sys
import yaml
want = set(sys.argv[1:])
print(yaml.safe_dump_all([d for d in yaml.safe_load_all(sys.stdin) if d and d["kind"] in want]), end="")
PY
apply_kinds() { # overlay kind...
  local ov=$1; shift
  kubectl kustomize "$ov" | (cd "$gitops_repo" && uv run -q --with pyyaml python -c "$pick_py" "$@") | kc apply -f - >/dev/null
}
bus_files() { # the rendered addon as objects to apply, like the broker steps do
  kubectl kustomize "$bus_dir" | (cd "$gitops_repo" && uv run -q --with pyyaml python -c "$apply_py" "$work/bus-1.yaml" "$work/bus-chart.yaml" "$work/bus-2.yaml")
}
bus_roll() { # previous updateRevision: the StatefulSet takes the new chart values (the users are container variables) and becomes ready
  local i
  for i in $(seq 1 60); do   # up to 120 s
    if [ "$(kc get statefulsets.apps e2e-bus -o jsonpath='{.status.updateRevision}' 2>/dev/null)" != "$1" ]; then break; fi; sleep 2
  done
  [ "$(kc get statefulsets.apps e2e-bus -o jsonpath='{.status.updateRevision}' 2>/dev/null)" != "$1" ] || { kubectl --context k3d-$cluster -n kube-system logs job/helm-install-e2e-bus --tail=20 || true; sfail "the StatefulSet e2e-bus did not take the new chart values within 120 s"; }
  if ! kc rollout status statefulsets.apps/e2e-bus --timeout=180s 2>&1 | tee /dev/stderr; then
    kc get pods; kc describe pod e2e-bus-0 | tail -30; kc logs e2e-bus-0 -c nats --tail=20 || true
    sfail "the StatefulSet e2e-bus did not become ready with the new chart values"
  fi
}

sstep "Scaling: declare the events API jobs and the component e2e-worker (service, min 0, max 5, consumes jobs, lag 10), render, check the pins, the rendered files and the model (AC-120.23, AC-120.25)"
clean_tree "before the scaling steps"
[ ! -e "$gitops_repo/operators/apps/keda.yaml" ] || sfail "operators/apps/keda.yaml exists before any instance scales on a queue"
read -r -d '' decl_scale_py <<'PY' || true
data["apis"]["jobs"] = {"type": "events"}   # bound to bus, the only broker of the system
comps["e2e-api"]["provides"] = [*(comps["e2e-api"].get("provides") or []), "jobs"]
shapes = {s["id"]: s for s in core.registry.load()}
ns = compose.build_parser().parse_args(["add", "e2e-worker"])   # real parser defaults
ns.uses = ["sessions"]                                          # one cache: REDIS_URL, REDIS_HOST, REDIS_PORT, REDIS_PASSWORD
entry = compose.build_entry("e2e-worker", "e2e/e2e-worker", shapes["service-python"], None, registry, ns, {})
entry["port"] = 8080
entry["probes"] = {"liveness": "/health", "readiness": "/health"}
entry["user"] = 1000
entry["volumes"] = {"tmp": "/tmp"}
entry["env"] = {"PYTHONDONTWRITEBYTECODE": "1", "WORK_SECONDS": "3"}
entry["resources"] = {"requests": {"cpu": "50m", "memory": "64Mi"}, "limits": {"memory": "128Mi"}}
entry["consumes"] = ["jobs"]
entry["instances"] = {"dev": {"scale": {"min": 0, "max": 5, "on": {"consumes": "jobs", "lag": 10}}}}
comps["e2e-worker"] = entry
PY
sedit "$decl_scale_py"
commit "scaling: jobs and the scaled consumer e2e-worker"
# the operator file exists now; the HelmChart that cluster-up installed (WITH_KEDA=1) is its pin (AC-120.25)
[ -f "$gitops_repo/operators/apps/keda.yaml" ] || sfail "render did not write operators/apps/keda.yaml for the queue-triggered instance"
keda_pin=$(pin_of "$gitops_repo/operators/apps/keda.yaml")
keda_have=$(kubectl --context k3d-$cluster -n kube-system get helmcharts.helm.cattle.io keda -o jsonpath='{.spec.version}' 2>/dev/null || true)
[ "$keda_pin" = 2.19.0 ] || sfail "operators/apps/keda.yaml pins '$keda_pin', expected the KEDA chart 2.19.0"
[ "$keda_have" = "$keda_pin" ] || sfail "the installed KEDA chart is '$keda_have', operators/apps/keda.yaml pins '$keda_pin'"
keda_image=$(kubectl --context k3d-$cluster -n keda get deployments.apps keda-operator -o jsonpath='{.spec.template.spec.containers[0].image}' 2>/dev/null || true)
keda_image=${keda_image%%@*}
[ "${keda_image##*:}" = 2.19.0 ] || sfail "the Deployment keda-operator runs '$keda_image', expected the tag 2.19.0"
kubectl --context k3d-$cluster get crd scaledobjects.keda.sh triggerauthentications.keda.sh >/dev/null || sfail "KEDA's CRDs (scaledobjects.keda.sh, triggerauthentications.keda.sh) are not installed"
[ ! -e "$gitops_repo/operators/apps/metrics-server.yaml" ] || sfail "operators/apps/metrics-server.yaml exists although resource_metrics is not install (the cluster serves resource metrics itself)"
read -r -d '' scale_decl_py <<'PY' || true
import json, subprocess, sys
from pathlib import Path
import yaml
app, work = Path(sys.argv[1]), Path(sys.argv[2])
bad = []
ov = app / "overlays/dev/e2e-worker"
for f in ("hpa.yaml", "triggerauthentication.yaml"):
    if (ov / f).exists():
        bad.append(f"overlays/dev/e2e-worker/{f} exists, but a queue trigger on the broker has neither")
if not (ov / "scaledobject.yaml").exists():
    bad.append("overlays/dev/e2e-worker/scaledobject.yaml is missing")
else:
    so = yaml.safe_load((ov / "scaledobject.yaml").read_text())
    trig = (so["spec"].get("triggers") or [{}])[0]
    md = trig.get("metadata") or {}
    if trig.get("type") != "nats-jetstream":
        bad.append(f"the trigger is {trig.get('type')!r}, expected nats-jetstream")
    for k, v in {"natsServerMonitoringEndpoint": "e2e-bus.e2e-dev.svc:8222", "stream": "e2e-jobs", "consumer": "e2e-worker", "lagThreshold": "10"}.items():
        if md.get(k) != v:
            bad.append(f"scaledobject.yaml: {k} is {md.get(k)!r}, expected {v!r}")
    if (so["spec"].get("minReplicaCount"), so["spec"].get("maxReplicaCount")) != (0, 5):
        bad.append(f"scaledobject.yaml: min/max are {so['spec'].get('minReplicaCount')}/{so['spec'].get('maxReplicaCount')}, expected 0/5")

def env_of(c):
    out = subprocess.run(["kubectl", "kustomize", str(app / "overlays/dev" / c)], capture_output=True, text=True)
    if out.returncode:
        bad.append(f"kubectl kustomize overlays/dev/{c} failed: {out.stderr[-300:]}")
        return None, []
    for d in yaml.safe_load_all(out.stdout):
        if d and d.get("kind") == "Deployment":
            env = [e for e in d["spec"]["template"]["spec"]["containers"][0].get("env", []) if e["name"].startswith(("NATS_", "EVENTS_"))]
            (work / f"natsenv-{c}.json").write_text(json.dumps(env))   # the probes of the next steps carry these
            return d, env
    bad.append(f"overlays/dev/{c} has no Deployment")
    return None, []

dep, env = env_of("e2e-worker")
if dep is not None and dep["spec"].get("replicas") != 0:
    bad.append(f"the Deployment e2e-worker has replicas {dep['spec'].get('replicas')}, expected 0 (scale to zero starts at min)")
have = {e["name"]: e for e in env}
for k, v in {"EVENTS_JOBS_STREAM": "e2e-jobs", "EVENTS_JOBS_SUBJECT_PREFIX": "e2e.jobs", "EVENTS_JOBS_CONSUMER": "e2e-worker", "NATS_INBOX_PREFIX": "_INBOX.e2e-worker"}.items():
    if have.get(k, {}).get("value") != v:
        bad.append(f"e2e-worker: {k} is {have.get(k, {}).get('value')!r}, expected {v!r}")
for k, key in (("NATS_URL", "url"), ("NATS_USER", "user"), ("NATS_PASSWORD", "password")):
    ref = have.get(k, {}).get("valueFrom", {}).get("secretKeyRef", {})
    if ref != {"name": "e2e-bus-e2e-worker-app", "key": key}:
        bad.append(f"e2e-worker: {k} reads {ref}, expected the key {key} of e2e-bus-e2e-worker-app")
_, api_env = env_of("e2e-api")
api = {e["name"]: e for e in api_env}
if api.get("EVENTS_JOBS_SUBJECT_PREFIX", {}).get("value") != "e2e.jobs" or "EVENTS_JOBS_CONSUMER" in api:
    bad.append("e2e-api: EVENTS_JOBS_SUBJECT_PREFIX must be e2e.jobs and EVENTS_JOBS_CONSUMER must be absent (it provides jobs)")
# the dev ApplicationSet leaves .spec.replicas of the scaled Deployment to the autoscaler, respects that, and retries a ScaledObject that is early
dev = next((d for d in yaml.safe_load_all((app / "applicationset.yaml").read_text()) if d and d["metadata"]["name"] == "e2e-dev"), None)
if dev is None:
    bad.append("applicationset.yaml has no ApplicationSet e2e-dev")
else:
    tpl = dev["spec"]["template"]["spec"]
    if not any(i.get("name") == "e2e-worker" and i.get("kind") == "Deployment" and i.get("jsonPointers") == ["/spec/replicas"] for i in tpl.get("ignoreDifferences") or []):
        bad.append("the dev ApplicationSet has no ignoreDifferences entry for the Deployment e2e-worker (/spec/replicas)")
    if "RespectIgnoreDifferences=true" not in tpl["syncPolicy"].get("syncOptions", []):
        bad.append("the dev ApplicationSet lacks the sync option RespectIgnoreDifferences=true")
    if not tpl["syncPolicy"].get("retry"):
        bad.append("the dev ApplicationSet has no retry although a ScaledObject may sync before KEDA's CRD exists")
print("\n".join(bad), file=sys.stderr)
sys.exit(1 if bad else 0)
PY
(cd "$gitops_repo" && uv run -q --with pyyaml python -c "$scale_decl_py" "$sapp" "$work") || sfail "the rendered scaling files are not as designed (see above)"
read -r -d '' scale_model_py <<'PY' || true
import json, sys
m = json.load(open(sys.argv[1]))
bad = []
envs = {e["name"]: e.get("autoscaling") for e in m["environments"]}
if envs.get("dev") != "keda" or envs.get("staging") is not None or envs.get("prod") is not None:
    bad.append(f"autoscaling per environment is {envs}, expected dev keda and staging/prod null")
inst = {(i["component"], i["environment"]): i for i in m["instances"]}
w = inst.get(("e2e-worker", "dev"))
if w is None:
    bad.append("the model has no instance e2e-worker/dev")
else:
    sc = w.get("scale") or {}
    if (sc.get("min"), sc.get("max"), (sc.get("on") or {}).get("consumes"), (sc.get("on") or {}).get("lag")) != (0, 5, "jobs", 10) or w.get("replicas") is not None:
        bad.append(f"e2e-worker/dev has scale {sc} and replicas {w.get('replicas')}, expected min 0, max 5, consumes jobs, lag 10 and replicas null")
if (inst.get(("e2e-api", "dev")) or {}).get("scale") is not None:
    bad.append("e2e-api/dev has a scale")
print("\n".join(bad), file=sys.stderr)
sys.exit(1 if bad else 0)
PY
$cplat model show --json --repo-dir "$gitops_repo" > "$work/model-scale.json" || sfail "cplat model show --json failed"
python3 -c "$scale_model_py" "$work/model-scale.json" || sfail "cplat model show --json does not describe the scaled instance (see above)"
sok "operators/apps/keda.yaml pins keda $keda_pin (installed, keda-operator $keda_image); scaledobject.yaml (nats-jetstream, e2e-bus.e2e-dev.svc:8222, stream e2e-jobs, consumer e2e-worker, lag 10), no hpa.yaml or triggerauthentication.yaml, replicas 0; ignoreDifferences, RespectIgnoreDifferences and the retry in the dev ApplicationSet; model: dev autoscaling keda"

sstep "Scaling: apply the bus addon again (user e2e-worker, stream e2e-jobs, consumer e2e-worker), then the worker (Deployment, Service), then the ScaledObject (AC-120.14, AC-120.25)"
bus_files || sfail "could not turn the rendered addon into objects to apply"
bus_secrets_before=$(secret_hash $ns e2e-bus-nack; secret_hash $ns e2e-bus-e2e-api-app; secret_hash $ns e2e-bus-e2e-web-app)
credentials_apply $ns "$bus_dir"   # the new user: a new Secret; the existing Secrets keep their passwords (AC-128.5)
[ -n "$(secret_val e2e-bus-e2e-worker-app password)" ] || { kc logs job/"$CRED_JOB" --tail=20 || true; sfail "the Secret e2e-bus-e2e-worker-app has no password after the credentials Job"; }
[ "$(secret_hash $ns e2e-bus-nack; secret_hash $ns e2e-bus-e2e-api-app; secret_hash $ns e2e-bus-e2e-web-app)" = "$bus_secrets_before" ] || sfail "adding e2e-worker changed a password of the existing users"
[ "$(secret_val e2e-bus-e2e-worker-app user)" = e2e-worker ] || sfail "the user of e2e-bus-e2e-worker-app is not e2e-worker"
rev_before=$(kc get statefulsets.apps e2e-bus -o jsonpath='{.status.updateRevision}')
kubectl --context k3d-$cluster apply -f "$work/bus-chart.yaml" >/dev/null || sfail "applying the HelmChart e2e-bus failed"
bus_roll "$rev_before"
bus_back_t=$SECONDS
# AC-128.5: within 60 s of the server being ready again, e2e-worker and the users that were there connect with their own variables
bus_ok=0
for _ in $(seq 1 12); do
  if nrun e2e-worker "$nats_auth_py" && [ "$(n_field AUTH)" = ok ]; then bus_ok=1; break; fi; sleep 3
done
[ $bus_ok = 1 ] && [ $((SECONDS - bus_back_t)) -le 60 ] || sfail "e2e-worker did not connect within 60 s of the server being ready again: $N_OUT"
for c in e2e-api e2e-web; do
  nrun $c "$nats_auth_py" && [ "$(n_field AUTH)" = ok ] || sfail "$c got no connection after e2e-worker was added: $N_OUT"
done
kc apply -f "$work/bus-2.yaml" >/dev/null || sfail "applying the Account, the streams and the consumers failed"
for o in streams.jetstream.nats.io/e2e-jobs consumers.jetstream.nats.io/e2e-jobs.e2e-worker; do
  for _ in $(seq 1 40); do bus_ready "${o%%/*}" "${o#*/}" && break; sleep 3; done   # up to 120 s
  bus_ready "${o%%/*}" "${o#*/}" || {
    kc describe "${o%%/*}" "${o#*/}" | tail -25; kubectl --context k3d-$cluster -n nack logs deploy/nack --tail=30 || true
    sfail "$o is not Ready after 120 s"; }
done
apply_kinds "$(ovd e2e-worker)" Deployment Service || sfail "applying the Deployment and the Service of e2e-worker failed"
for _ in $(seq 1 20); do [ -n "$(wdep .spec.replicas)" ] && break; sleep 2; done
[ "$(wdep .spec.replicas)" = 0 ] || sfail "the Deployment e2e-worker has $(wdep .spec.replicas) replicas, expected 0"
apply_kinds "$(ovd e2e-worker)" ScaledObject || sfail "applying the ScaledObject e2e-worker failed"
for _ in $(seq 1 30); do bus_ready scaledobjects.keda.sh e2e-worker && break; sleep 3; done   # up to 90 s
bus_ready scaledobjects.keda.sh e2e-worker || { sdiag; sfail "the ScaledObject e2e-worker is not Ready after 90 s"; }
for _ in $(seq 1 15); do kc get horizontalpodautoscalers.autoscaling keda-hpa-e2e-worker >/dev/null 2>&1 && break; sleep 2; done
kc get horizontalpodautoscalers.autoscaling keda-hpa-e2e-worker >/dev/null 2>&1 || { sdiag; sfail "KEDA created no HorizontalPodAutoscaler keda-hpa-e2e-worker"; }
[ "$(wdep .spec.replicas)" = 0 ] || sfail "the Deployment e2e-worker has $(wdep .spec.replicas) replicas with an empty queue, expected 0"
sok "the Secret e2e-bus-e2e-worker-app, stream e2e-jobs and consumer e2e-jobs.e2e-worker are Ready; the ScaledObject e2e-worker is Ready (keda-hpa-e2e-worker exists) and the Deployment has 0 replicas"

sstep "Scaling: one message on e2e.jobs.one wakes the worker, readyReplicas is at least 1 within 60 seconds (AC-120.14)"
n_must e2e-api "$natspre"'
async def main():
    nc = await connect()
    js = nc.jetstream()
    ack = await js.publish(os.environ["EVENTS_JOBS_SUBJECT_PREFIX"] + ".one", b"one")   # e2e.jobs.one
    print("PUBLISHED=%s" % ack.stream)
    print("T=%d" % int(time.time()))
    await nc.close()
asyncio.run(main())'
[ "$(n_field PUBLISHED)" = e2e-jobs ] || sfail "e2e-api published on e2e.jobs.one but the stream is '$(n_field PUBLISHED)', not e2e-jobs: $N_OUT"
t_wake=$(n_field T)
ready=""
while [ $(( $(date +%s) - t_wake )) -le 60 ]; do   # 60 s from the publish
  ready=$(wdep .status.readyReplicas)
  [ -n "$ready" ] && [ "$ready" -ge 1 ] && break
  sleep 2
done
[ -n "$ready" ] && [ "$ready" -ge 1 ] || { sdiag; sfail "readyReplicas of e2e-worker is '${ready:-0}' $(( $(date +%s) - t_wake )) s after the message on e2e.jobs.one, expected at least 1 within 60 s"; }
sok "the worker was ready $(( $(date +%s) - t_wake )) s after the publish on e2e.jobs.one (readyReplicas $ready)"

sstep "Scaling: a burst of 100 messages; .spec.replicas reaches 5 within 120 seconds of the publish; a background watcher records the replicas and the lag (AC-120.10, AC-120.23)"
scale_watch() { # file seconds: one line per 5 s: epoch replicas num_pending num_ack_pending; ends with END once the count is back to zero after 5, or TIMEOUT
  local out=$1 end=$(( $(date +%s) + $2 )) r p a seen=0
  : > "$out"
  while [ "$(date +%s)" -lt "$end" ]; do
    kill -0 $$ 2>/dev/null || return 0   # the script is gone
    r=$(kc get deployments.apps e2e-worker -o jsonpath='{.spec.replicas}' 2>/dev/null || true)
    J=$(jsz 2>/dev/null) || J=""
    p=$(jf C.e2e-jobs.e2e-worker.num_pending); a=$(jf C.e2e-jobs.e2e-worker.num_ack_pending)
    echo "$(date +%s) ${r:-?} ${p:-?} ${a:-?}" >> "$out"
    if [ -n "$r" ] && [ "$r" -ge 5 ] 2>/dev/null; then seen=1; fi
    if [ "$seen" = 1 ] && [ "$r" = 0 ]; then echo END >> "$out"; return 0; fi
    sleep 5
  done
  echo TIMEOUT >> "$out"
}
scale_watch "$work/scale-watch.txt" 600 >/dev/null 2>&1 &
watch_pid=$!
n_must e2e-api "$natspre"'
async def main():
    nc = await connect()
    js = nc.jetstream()
    for i in range(100):
        await js.publish(os.environ["EVENTS_JOBS_SUBJECT_PREFIX"] + ".work", b"job-%d" % i)
    print("PUBLISHED=100")
    print("T=%d" % int(time.time()))
    await nc.close()
asyncio.run(main())'
[ "$(n_field PUBLISHED)" = 100 ] || sfail "e2e-api could not publish the 100 messages: $N_OUT"
t_burst=$(n_field T)
reps=""
while [ $(( $(date +%s) - t_burst )) -le 120 ]; do   # 120 s from the publish
  reps=$(wdep .spec.replicas)
  [ "$reps" = 5 ] && break
  sleep 2
done
[ "$reps" = 5 ] || { sdiag; sfail ".spec.replicas of e2e-worker is '$reps' $(( $(date +%s) - t_burst )) s after 100 messages were published, expected 5 within 120 s"; }
sok ".spec.replicas of e2e-worker reached 5 $(( $(date +%s) - t_burst )) s after the 100 messages were published (the watcher keeps recording)"

sstep "Scaling: while the watcher runs, the sync emulation: the rendered Deployment with the live replica count is applied and neither .spec.replicas nor .metadata.generation changes (AC-120.19)"
# RespectIgnoreDifferences makes Argo CD's sync keep the live .spec.replicas of a Deployment whose application ignores it: the same manifest, with
# the live count in place of the rendered one, is what this applies (no Argo CD here); a Deployment that stays Synced stays unchanged
read -r -d '' sync_py <<'PY' || true
import sys
import yaml
docs = [d for d in yaml.safe_load_all(sys.stdin) if d and d["kind"] == "Deployment"]
for d in docs:
    d["spec"]["replicas"] = int(sys.argv[1])
print(yaml.safe_dump_all(docs), end="")
PY
# the claim (AC-120.19) is the replica count; .metadata.generation also counts the autoscaler's own replica writes, so the rest of
# the spec is compared field by field instead, and the generations are only printed
spec_wo_replicas() { kc get deployments.apps e2e-worker -o json | python3 -c 'import json,sys; s=json.load(sys.stdin)["spec"]; s.pop("replicas",None); print(json.dumps(s,sort_keys=True))'; }
live_replicas=$(wdep .spec.replicas); gen_before=$(wdep .metadata.generation); spec_before=$(spec_wo_replicas)
[ -n "$live_replicas" ] && [ -n "$gen_before" ] && [ -n "$spec_before" ] || sfail "could not read .spec and .metadata.generation of e2e-worker"
kubectl kustomize "$(ovd e2e-worker)" | (cd "$gitops_repo" && uv run -q --with pyyaml python -c "$sync_py" "$live_replicas") | kc apply -f - >/dev/null || sfail "applying the rendered Deployment with the live replica count failed"
sleep 5
spec_after=$(spec_wo_replicas); rep_after=$(wdep .spec.replicas); gen_after=$(wdep .metadata.generation)
if [ "$rep_after" != "$live_replicas" ] || [ "$spec_after" != "$spec_before" ]; then
  diff <(tr ',' '\n' <<< "$spec_before") <(tr ',' '\n' <<< "$spec_after") | head -20 || true
  sfail "the sync changed the Deployment: .spec.replicas $live_replicas -> $rep_after, the rest of .spec $( [ "$spec_after" = "$spec_before" ] && echo unchanged || echo changed ) (.metadata.generation $gen_before -> $gen_after)"
fi
sok "after the sync emulation .spec.replicas ($live_replicas) and the rest of .spec are unchanged (.metadata.generation $gen_before -> $gen_after)"

sstep "Scaling: system status --json shows scale min 0, max 5 and a live replica count for e2e-worker, none for e2e-api; the text shows replicas <n> (0–5) (AC-120.22)"
sargs=(--repo-dir "$gitops_repo" --context "k3d-$cluster")
PYTHONIOENCODING=utf-8 $cplat system status --json "${sargs[@]}" > "$work/status-scale.json" 2> "$work/status-scale.err" || { tail -5 "$work/status-scale.err" || true; sfail "system status --json failed"; }
PYTHONIOENCODING=utf-8 $cplat system status "${sargs[@]}" > "$work/status-scale.txt" 2> "$work/status-scale.err" || { tail -5 "$work/status-scale.err" || true; sfail "system status failed"; }
status_rep=$(python3 - "$work/status-scale.json" "$work/status-scale.txt" <<'PY'
import json, re, sys
rows = {r["component"]: r for r in json.load(open(sys.argv[1]))["rows"]}
bad = []
sc = ((rows.get("e2e-worker") or {}).get("cells") or {}).get("dev", {}).get("scale")
if not sc or (sc.get("min"), sc.get("max")) != (0, 5) or not isinstance(sc.get("replicas"), int) or isinstance(sc.get("replicas"), bool):
    bad.append(f"the dev cell of e2e-worker has scale {sc}, expected min 0, max 5 and an integer replicas")
if ((rows.get("e2e-api") or {}).get("cells") or {}).get("dev", {}).get("scale"):
    bad.append("the dev cell of e2e-api has a scale")
text = open(sys.argv[2], encoding="utf-8").read()
if not re.search(r"\breplicas [0-5] \(0–5\)", text):
    bad.append("the text output has no 'replicas <n> (0–5)'")
print("\n".join(bad), file=sys.stderr)
if not bad:
    print(sc["replicas"])
sys.exit(1 if bad else 0)
PY
) || sfail "system status does not show the scale of e2e-worker as expected (see above)"
sok "system status: e2e-worker (dev) scale 0–5 with replicas $status_rep (live .spec.replicas); e2e-api has no scale"

sstep "Scaling: a CPU autoscaler on e2e-web (min 1, max 2, cpu 80): hpa.yaml, no ScaledObject, only the HPA applied, currentMetrics within 120 seconds, resource metrics served (AC-120.6, AC-120.17)"
clean_tree "before the cpu step"
sedit '
dev = comps["e2e-web"].get("instances", {}).get("dev")
if dev is None:
    comps["e2e-web"].setdefault("instances", {})["dev"] = dev = {}
dev["scale"] = {"min": 1, "max": 2, "on": {"cpu": 80}}'
commit "scaling: e2e-web scales on cpu"
[ -f "$(ovd e2e-web)/hpa.yaml" ] || sfail "render did not write overlays/dev/e2e-web/hpa.yaml"
[ ! -e "$(ovd e2e-web)/scaledobject.yaml" ] || sfail "render wrote a ScaledObject for the cpu trigger"
grep -q 'averageUtilization: 80' "$(ovd e2e-web)/hpa.yaml" || sfail "hpa.yaml does not target averageUtilization 80"
[ "$(kubectl --context k3d-$cluster get apiservices.apiregistration.k8s.io v1beta1.metrics.k8s.io -o jsonpath='{.status.conditions[?(@.type=="Available")].status}' 2>/dev/null)" = True ] || sfail "the cluster serves no resource metrics (v1beta1.metrics.k8s.io is not Available)"
apply_kinds "$(ovd e2e-web)" HorizontalPodAutoscaler || sfail "applying the HorizontalPodAutoscaler e2e-web failed"
cpu_now=""
for _ in $(seq 1 60); do   # up to 120 s
  cpu_now=$(kc get horizontalpodautoscalers.autoscaling e2e-web -o jsonpath='{.status.currentMetrics[0].resource.current.averageUtilization}' 2>/dev/null || true)
  [ -n "$cpu_now" ] && break; sleep 2
done
[ -n "$cpu_now" ] || { kc describe horizontalpodautoscalers.autoscaling e2e-web | tail -25; sfail "the HorizontalPodAutoscaler e2e-web reports no currentMetrics within 120 s"; }
sok "hpa.yaml targets averageUtilization 80; the HPA e2e-web reports $cpu_now % (currentMetrics); no ScaledObject"

sstep "Scaling: platform doctor shows operator keda ok (2.19.0, e2e-worker) and resource metrics ok, and no operator metrics-server row (AC-120.18)"
timeout 180 $cplat platform doctor --repo "$gitops_repo" --json > "$work/doctor-scale.json" 2> "$work/doctor-scale.err" || true   # any exit code: only its rows matter
python3 - "$work/doctor-scale.json" <<'PY' || { tail -5 "$work/doctor-scale.err" || true; sfail "doctor output unreadable, or the keda or resource metrics row is not as expected (see above)"; }
import json, re, sys
rows = {r["name"]: r for r in json.load(open(sys.argv[1]))}
bad = []
keda = rows.get("operator keda")
if keda is None:
    bad.append("no row 'operator keda'")
elif keda["status"] != "ok" or not re.search(r"\b2\.19\.0\b", keda["detail"]) or not re.search(r"\be2e-worker\b", keda["detail"]):
    bad.append(f"row 'operator keda' is {keda['status']}: {keda['detail']}")
rm = rows.get("resource metrics")
if rm is None:
    bad.append("no row 'resource metrics'")
elif rm["status"] != "ok":
    bad.append(f"row 'resource metrics' is {rm['status']}: {rm['detail']}")
if "operator metrics-server" in rows:
    bad.append("a row 'operator metrics-server' exists although the cluster serves resource metrics and resource_metrics is not install")
print("\n".join(bad), file=sys.stderr)
sys.exit(1 if bad else 0)
PY
sok "platform doctor: operator keda (2.19.0, queue-triggered e2e-worker) and resource metrics are ok; no operator metrics-server row"

sstep "Scaling: component set e2e-worker --instance dev --replicas 2 is refused and names components.e2e-worker.instances.dev.scale; then e2e-web's scale is removed and its HPA deleted (AC-120.5)"
clean_tree "before the refusal"
head_before=$(git -C "$gitops_repo" rev-parse HEAD)
if out=$($cplat component set e2e-worker --instance dev --replicas 2 --repo-dir "$gitops_repo" 2>&1); then sfail "component set --replicas succeeded on the scaled instance e2e-worker/dev"; fi
case "$out" in *components.e2e-worker.instances.dev.scale*) ;; *) sfail "the refusal does not name components.e2e-worker.instances.dev.scale: $out";; esac
[ -z "$(git -C "$gitops_repo" status --porcelain)" ] && [ "$(git -C "$gitops_repo" rev-parse HEAD)" = "$head_before" ] || sfail "the refused component set changed the tree"
sedit 'del comps["e2e-web"]["instances"]["dev"]["scale"]'
[ ! -e "$(ovd e2e-web)/hpa.yaml" ] || sfail "render did not delete overlays/dev/e2e-web/hpa.yaml once the scale was removed"
kc delete horizontalpodautoscalers.autoscaling e2e-web --timeout=60s || sfail "could not delete the HorizontalPodAutoscaler e2e-web (what Argo CD's prune does)"
commit "scaling: e2e-web scale removed"
sok "refused: $(echo "$out" | tr '\n' ' ' | cut -c1-200); hpa.yaml is gone and the HPA e2e-web deleted"

sstep "Scaling: join the watcher; the maximum is 5, the lag reached 0 at the time Z minus T is between 295 and 420 seconds when the count is back to zero (AC-120.15, AC-120.23)"
for _ in $(seq 1 130); do kill -0 "$watch_pid" 2>/dev/null || break; sleep 5; done   # the watcher has its own 600 s bound; this waits up to 650 s
if kill -0 "$watch_pid" 2>/dev/null; then kill "$watch_pid" 2>/dev/null || true; fi
wait "$watch_pid" 2>/dev/null || true
echo "time replicas num_pending num_ack_pending (epoch seconds, 5 s period)"; cat "$work/scale-watch.txt"
read -r -d '' join_py <<'PY' || true
import sys
rows, tail = [], ""
for ln in open(sys.argv[1]):
    p = ln.split()
    if len(p) == 4 and p[0].isdigit():
        rows.append((int(p[0]), p[1], p[2], p[3]))
    elif p:
        tail = p[0]
pub = int(sys.argv[2])
num = lambda x: int(x) if x.isdigit() else None  # noqa: E731
reps = [(t, num(r)) for t, r, _, _ in rows if num(r) is not None]
bad = []
if tail != "END":
    bad.append(f"the watcher ended with '{tail or 'nothing'}', not END: the count never came back to zero after 5 within its 600 s")
top = max((r for _, r in reps), default=None)
if top != 5:
    bad.append(f"the maximum replica count seen is {top}, expected 5")
t5 = next((t for t, r in reps if r >= 5), None)
if t5 is None or t5 - pub > 120:
    bad.append(f"the count reached 5 at {t5}, {None if t5 is None else t5 - pub} s after the publish (more than 120 s)")
lag = [(t, num(p) + num(a)) for t, _, p, a in rows if num(p) is not None and num(a) is not None]
seen, T = False, None
for t, n in lag:
    if t >= pub and n > 0:
        seen = True
    elif seen and n == 0:
        T = t
        break
Z = next((t for t, r in reps if t5 is not None and t >= t5 and r == 0), None)
if T is None:
    bad.append("the lag never fell back to 0 in the samples")
if Z is None:
    bad.append("the count never came back to zero replicas in the samples")
if T is not None and Z is not None:
    print(f"lag 0 at T, zero replicas at Z: Z - T = {Z - T} s (allowed 295 to 420 s, 5 s sampling); 5 replicas {t5 - pub} s after the publish; maximum {top}")
    if not 295 <= Z - T <= 420:
        bad.append(f"Z - T is {Z - T} s, expected 295 to 420 s (five to seven minutes)")
print("\n".join(bad), file=sys.stderr)
sys.exit(1 if bad else 0)
PY
python3 -c "$join_py" "$work/scale-watch.txt" "$t_burst" || { sdiag; sfail "the burst did not behave as designed (see above)"; }
sok "maximum 5; the count came back to zero replicas 295 to 420 s after the queue was worked off"

sstep "Scaling: the trigger becomes the cache list (sessions, list jobs, length 10); 30 entries bring the worker to 3 replicas within 120 seconds and no further (AC-120.11, AC-120.12, AC-120.13)"
clean_tree "before the cache trigger"
sedit 'comps["e2e-worker"]["instances"]["dev"]["scale"]["on"] = {"cache": "sessions", "list": "jobs", "length": 10}'
commit "scaling: e2e-worker scales on the cache list"
[ -f "$(ovd e2e-worker)/triggerauthentication.yaml" ] && [ -f "$(ovd e2e-worker)/scaledobject.yaml" ] || sfail "render did not write triggerauthentication.yaml and scaledobject.yaml for the cache trigger"
python3 - "$(ovd e2e-worker)" <<'PY' || sfail "the TriggerAuthentication or the redis trigger is not as designed (see above)"
import sys
from pathlib import Path
import yaml
ov = Path(sys.argv[1])
bad = []
ta = yaml.safe_load((ov / "triggerauthentication.yaml").read_text())
refs = {(r["parameter"], r["name"], r["key"]) for r in ta["spec"]["secretTargetRef"]}
want = {(p, "e2e-sessions-app", p) for p in ("host", "port", "password")}
if refs != want:
    bad.append(f"the TriggerAuthentication reads {sorted(refs)}, expected host, port and password of e2e-sessions-app")
trig = yaml.safe_load((ov / "scaledobject.yaml").read_text())["spec"]["triggers"][0]
md = trig.get("metadata") or {}
if trig.get("type") != "redis" or md.get("listName") != "jobs" or md.get("listLength") != "10" or (trig.get("authenticationRef") or {}).get("name") != "e2e-worker":
    bad.append(f"the trigger is {trig}, expected redis on the list jobs, listLength 10, authenticationRef e2e-worker")
print("\n".join(bad), file=sys.stderr)
sys.exit(1 if bad else 0)
PY
apply_kinds "$(ovd e2e-worker)" TriggerAuthentication || sfail "applying the TriggerAuthentication e2e-worker failed"
apply_kinds "$(ovd e2e-worker)" ScaledObject || sfail "applying the ScaledObject e2e-worker (cache trigger) failed"
for _ in $(seq 1 30); do bus_ready scaledobjects.keda.sh e2e-worker && break; sleep 3; done   # up to 90 s
bus_ready scaledobjects.keda.sh e2e-worker || { sdiag; sfail "the ScaledObject e2e-worker is not Ready with the cache trigger after 90 s"; }
# AC-120.13: scaledobject.yaml and triggerauthentication.yaml name the keys of the Secrets, never a value; neither do the live objects
pw_cache=$(secret_val e2e-sessions-app password); pw_bus=$(secret_val e2e-bus-e2e-worker-app password)
[ "${#pw_cache}" = 32 ] && [ "${#pw_bus}" = 32 ] || sfail "the passwords of e2e-sessions-app and e2e-bus-e2e-worker-app are not 32 characters"
if grep -rqF -e "$pw_cache" -e "$pw_bus" "$(ovd e2e-worker)"; then sfail "a password is in the rendered overlay of e2e-worker"; fi
live_scalers=$(kc get scaledobjects.keda.sh,triggerauthentications.keda.sh -o yaml)
if grep -qF -e "$pw_cache" -e "$pw_bus" <<< "$live_scalers"; then sfail "a password is in the live ScaledObject or TriggerAuthentication"; fi
# the probe connects like the component: a Valkey client with the component's own REDIS_HOST, REDIS_PORT and REDIS_PASSWORD (e2e-worker's Deployment)
read -r -d '' wcache_pod_py <<'PY' || true
import json, sys
name, image, script = sys.argv[1:4]
dep = json.load(sys.stdin)
env = [e for e in dep["spec"]["template"]["spec"]["containers"][0].get("env", []) if "valueFrom" in e and e["name"].startswith("REDIS_")]
ctx = {"allowPrivilegeEscalation": False, "readOnlyRootFilesystem": True, "capabilities": {"drop": ["ALL"]}}
print(json.dumps({"apiVersion": "v1", "kind": "Pod", "metadata": {"name": name, "labels": {"app": "cacheprobe"}},
                  "spec": {"restartPolicy": "Never",
                           "securityContext": {"runAsNonRoot": True, "runAsUser": 999, "runAsGroup": 999, "seccompProfile": {"type": "RuntimeDefault"}},
                           "containers": [{"name": "valkey", "image": image, "command": ["sh", "-c", script], "env": env, "securityContext": ctx}]}}))
PY
wn=0
wcrun() { # script: runs it in a pod that carries e2e-worker's REDIS_* variables; output in C_OUT
  local name phase=""
  wn=$((wn + 1)); name="cacheprobe-w$wn"
  kc get deployments.apps e2e-worker -o json | python3 -c "$wcache_pod_py" "$name" "$cache_image" "set -e; $1" | kc apply -f - >/dev/null || sfail "could not start the probe pod $name"
  for _ in $(seq 1 60); do   # up to 180 s
    phase=$(kc get pod "$name" -o jsonpath='{.status.phase}' 2>/dev/null || true)
    case "$phase" in Succeeded|Failed) break;; esac; sleep 3
  done
  C_OUT=$(kc logs "$name" 2>&1 || true)
  [ "$phase" = Succeeded ] || { C_OUT="$C_OUT (pod phase: ${phase:-unknown})"; kc describe pod "$name" | tail -15; }
  kc delete pod "$name" --wait=false >/dev/null 2>&1 || true
  [ "$phase" = Succeeded ]
}
rcli='valkey-cli --no-auth-warning -h "$REDIS_HOST" -p "$REDIS_PORT" -a "$REDIS_PASSWORD"'
wcrun "$rcli RPUSH jobs \$(seq 1 30) >/dev/null; echo LEN=\$($rcli LLEN jobs)" || sfail "the cache probe could not push 30 entries to the list jobs: $C_OUT"   # 30 entries, length 10 each: 3 replicas
[ "$(c_field LEN)" = 30 ] || sfail "the list jobs holds '$(c_field LEN)' entries, expected 30: $C_OUT"
t_push=$(date +%s); reps=""; top=0
while [ $(( $(date +%s) - t_push )) -le 120 ]; do   # 120 s from the push
  reps=$(wdep .spec.replicas)
  if [ -n "$reps" ] && [ "$reps" -gt "$top" ]; then top=$reps; fi
  [ "$reps" = 3 ] && break
  sleep 2
done
[ "$reps" = 3 ] || { sdiag; sfail ".spec.replicas of e2e-worker is '$reps' $(( $(date +%s) - t_push )) s after 30 entries were pushed, expected 3 within 120 s"; }
for _ in $(seq 1 10); do   # the count stays at 3 while the list holds 30 (30 s)
  reps=$(wdep .spec.replicas)
  if [ -n "$reps" ] && [ "$reps" -gt "$top" ]; then top=$reps; fi
  sleep 3
done
[ "$top" = 3 ] || sfail "the highest .spec.replicas seen with 30 entries in the list is $top, expected 3 and no more"
wcrun "$rcli DEL jobs >/dev/null; echo LEN=\$($rcli LLEN jobs)" || sfail "the cache probe could not delete the list jobs: $C_OUT"
[ "$(c_field LEN)" = 0 ] || sfail "the list jobs still holds '$(c_field LEN)' entries after DEL"
sok "30 entries in the list jobs gave 3 replicas (never more); no password in scaledobject.yaml, triggerauthentication.yaml or the live objects; the list is deleted"

sstep "Scaling: scale becomes replicas: 1; scaledobject.yaml, triggerauthentication.yaml and the dev ignore entry are gone; the ScaledObject is deleted, the count never falls below 1, keda-hpa-e2e-worker is gone (AC-120.20)"
clean_tree "before the switch back"
sedit 'comps["e2e-worker"]["instances"]["dev"] = {"replicas": 1}'
commit "scaling: e2e-worker back to replicas 1"
for f in scaledobject.yaml triggerauthentication.yaml hpa.yaml; do
  [ ! -e "$(ovd e2e-worker)/$f" ] || sfail "render did not delete overlays/dev/e2e-worker/$f once the scale was replaced by replicas"
done
kubectl kustomize "$(ovd e2e-worker)" | grep -qE '^  replicas: 1$' || sfail "the rendered Deployment e2e-worker does not have replicas: 1"
python3 - "$sapp/applicationset.yaml" <<'PY' || sfail "the dev ApplicationSet still ignores the replicas of e2e-worker"
import sys
import yaml
dev = next(d for d in yaml.safe_load_all(open(sys.argv[1])) if d and d["metadata"]["name"] == "e2e-dev")
ign = dev["spec"]["template"]["spec"].get("ignoreDifferences") or []
sys.exit(1 if any(i.get("name") == "e2e-worker" for i in ign) else 0)
PY
rmin=99
sample() { local v; v=$(wdep .spec.replicas); if [ -n "$v" ] && [ "$v" -lt "$rmin" ]; then rmin=$v; fi; last=$v; }
sample
# Argo CD's prune deletes the ScaledObject and the TriggerAuthentication (waiting for KEDA's finalizer), then the sync applies the Deployment
kc delete scaledobjects.keda.sh e2e-worker --timeout=90s || { sdiag; sfail "could not delete the ScaledObject e2e-worker"; }
kc delete triggerauthentications.keda.sh e2e-worker --timeout=60s || sfail "could not delete the TriggerAuthentication e2e-worker"
sample
for _ in $(seq 1 30); do kc get horizontalpodautoscalers.autoscaling keda-hpa-e2e-worker >/dev/null 2>&1 || break; sample; sleep 2; done   # up to 60 s
if kc get horizontalpodautoscalers.autoscaling keda-hpa-e2e-worker >/dev/null 2>&1; then sdiag; sfail "keda-hpa-e2e-worker is still there 60 s after the ScaledObject was deleted"; fi
apply_kinds "$(ovd e2e-worker)" Deployment || sfail "applying the Deployment e2e-worker (replicas 1) failed"
for _ in $(seq 1 15); do sample; sleep 2; done   # every 2 s for 30 s
[ "$rmin" -ge 1 ] && [ "$last" = 1 ] || { sdiag; sfail "the count fell to $rmin and ended at '$last', expected never below 1 and ending at 1"; }
sok "replicas: 1 applied; the ScaledObject, the TriggerAuthentication and keda-hpa-e2e-worker are gone; the count never fell below $rmin and ends at 1"

sstep "Scaling: clean-up: jobs, e2e-api's provides and e2e-worker are removed; operators/apps/keda.yaml goes; the worker, its user, stream e2e-jobs and consumer are deleted (AC-120.27)"
clean_tree "before the clean-up"
sedit '
del data["apis"]["jobs"]
comps["e2e-api"]["provides"] = [a for a in comps["e2e-api"]["provides"] if a != "jobs"]
del comps["e2e-worker"]'
commit "scaling: remove jobs and e2e-worker"
for needle in "stream e2e-jobs is no longer declared" "durable consumer e2e-worker of stream e2e-jobs is no longer declared"; do
  case "$S_RENDER" in *"$needle"*) ;; *) sfail "the render did not print a note with '$needle'";; esac
done
[ ! -e "$gitops_repo/operators/apps/keda.yaml" ] || sfail "operators/apps/keda.yaml still exists although no instance scales on a queue"
[ ! -e "$(ovd e2e-worker)" ] || sfail "overlays/dev/e2e-worker still exists although e2e-worker is removed"
[ -f "$bus_dir/stream-orders.yaml" ] && [ ! -e "$bus_dir/stream-jobs.yaml" ] && [ ! -e "$bus_dir/consumer-jobs.e2e-worker.yaml" ] || sfail "addons/dev/bus does not hold exactly the streams of orders and audit"
# the cluster: the bus chart without the user first (the pod no longer reads its Secret), then the objects the removal leaves behind
bus_files || sfail "could not turn the rendered addon into objects to apply"
rev_before=$(kc get statefulsets.apps e2e-bus -o jsonpath='{.status.updateRevision}')
kubectl --context k3d-$cluster apply -f "$work/bus-chart.yaml" >/dev/null || sfail "applying the HelmChart e2e-bus without the user e2e-worker failed"
bus_roll "$rev_before"
kc delete deployments.apps/e2e-worker services/e2e-worker --ignore-not-found --timeout=90s || sfail "could not delete the Deployment and the Service of e2e-worker"
for o in consumers.jetstream.nats.io/e2e-jobs.e2e-worker streams.jetstream.nats.io/e2e-jobs; do
  kc delete "$o" --timeout=60s || { kc get "$o" -o yaml | tail -20; kubectl --context k3d-$cluster -n nack logs deploy/nack --tail=20 || true; sfail "could not delete $o"; }
done
[ -z "$(kc get externalsecrets.external-secrets.io,passwords.generators.external-secrets.io -o name 2>/dev/null | grep -E 'e2e-bus|e2e-worker' || true)" ] || sfail "an ExternalSecret or Password generator names the broker or the worker (the credentials Job writes their Secrets)"
kc delete secrets e2e-bus-e2e-worker-app --ignore-not-found --timeout=60s >/dev/null || sfail "could not delete the Secret e2e-bus-e2e-worker-app"
left=$(kc get deployments.apps,services,scaledobjects.keda.sh,triggerauthentications.keda.sh,horizontalpodautoscalers.autoscaling,secrets,externalsecrets.external-secrets.io,streams.jetstream.nats.io,consumers.jetstream.nats.io -o name 2>/dev/null | grep -E 'e2e-worker|e2e-jobs' || true)
[ -z "$left" ] || sfail "objects of the scaling steps are still in e2e-dev: $left"
# the broker steps below see their own cluster again: the server (restarted without the user) still holds e2e-orders and its 3 messages
jsz_wait 15 S.e2e-orders.messages=3 || { echo "$J"; sfail "after the clean-up /jsz should still show e2e-orders with its 3 messages"; }
broker_t0=$((broker_t0 + SECONDS - scaling_t0))   # the broker steps' own budget does not count the scaling steps
sok "jobs, e2e-worker and operators/apps/keda.yaml are removed; the render named the retired stream e2e-jobs and consumer e2e-worker; the scaling steps took $((SECONDS - scaling_t0)) s in total (budget 780 s)"

nstep "Broker: resource remove bus is refused while the events APIs orders and audit are bound (AC-119.4)"
[ -z "$(git -C "$gitops_repo" status --porcelain)" ] || nfail "the tree is dirty before the removal"
if out=$($cplat resource remove bus --repo-dir "$gitops_repo" 2>&1); then nfail "resource remove bus succeeded although two events APIs are bound to it"; fi
case "$out" in *"orders, audit"*) ;; *) nfail "the refusal does not name the APIs 'orders, audit': $out";; esac
[ -z "$(git -C "$gitops_repo" status --porcelain)" ] || nfail "the refused removal changed the tree"
echo "ok   refused: $(echo "$out" | tr '\n' ' ' | cut -c1-200)"

nstep "Broker: remove both events APIs; the render names the retired stream e2e-orders, e2e-audit and the durable consumer e2e-web, and the stream stays with its messages (AC-119.14)"
(cd "$gitops_repo" && uv run --with pyyaml --with ruamel.yaml python - "$root" <<'PY'
import sys
sys.path.insert(0, f"{sys.argv[1]}/scripts/cplat")
import gitops
from pathlib import Path
app_dir = gitops.find_app(Path("."))
y, data = gitops.load(app_dir)
del data["apis"]
for name, comp in gitops.components_of(data).items():
    for key in ("provides", "consumes"):
        left = [a for a in comp.get(key) or [] if a not in ("orders", "audit")]
        if left:
            comp[key] = left
        elif key in comp:
            del comp[key]
gitops.save(app_dir, y, data)
PY
) || nfail "could not remove the events APIs from system.yaml"
render_out=$(cd "$gitops_repo" && uv run scripts/render.py 2>&1 | tee /dev/stderr) || nfail "render.py failed after the events APIs were removed"
commit "broker: remove the events APIs orders and audit"
for needle in "stream e2e-orders is no longer declared" "stream e2e-audit is no longer declared" "durable consumer e2e-web of stream e2e-orders is no longer declared"; do
  case "$render_out" in *"$needle"*) ;; *) nfail "the render did not print a note with '$needle'";; esac
done
# no longer declared, but still there: the stream, its messages and its consumer stay on the server
jsz_wait 15 S.e2e-orders.messages=3 C.e2e-orders.e2e-web.ack_policy=explicit \
  || { echo "$J"; nfail "after the events APIs were removed /jsz should still show e2e-orders with 3 messages and its consumer e2e-web"; }
echo "ok   the render named the retired streams e2e-orders and e2e-audit and the consumer e2e-web; /jsz still shows e2e-orders with 3 messages and its consumer"

nstep "Broker: resource remove bus succeeds once nothing is bound; operators/apps/nack.yaml goes; then the broker is deleted by hand, as a person would (AC-119.4)"
[ -z "$(git -C "$gitops_repo" status --porcelain)" ] || nfail "the tree is dirty before the removal"
$cplat resource remove bus --repo-dir "$gitops_repo" 2>&1 | tee /dev/stderr >/dev/null || nfail "resource remove bus failed although no events API is bound to it"
[ -z "$(git -C "$gitops_repo" status --porcelain)" ] || commit "remove bus"
[ ! -e "$gitops_repo/operators/apps/nack.yaml" ] || nfail "operators/apps/nack.yaml still exists although no broker is declared"
[ ! -e "$bus_dir" ] || nfail "addons/dev/bus still exists although the broker is removed"
# the Application disappears but the cluster objects stay (that is what the removal says): delete them by hand so that the staging and the
# backup steps see the cluster they had before. Consumers, streams, the account by full kind name; NACK keeps the data (preventDelete).
for o in consumers.jetstream.nats.io/e2e-orders.e2e-web streams.jetstream.nats.io/e2e-orders streams.jetstream.nats.io/e2e-audit accounts.jetstream.nats.io/e2e-bus; do
  kc delete "$o" --timeout=60s || { kc get "$o" -o yaml | tail -20; kubectl --context k3d-$cluster -n nack logs deploy/nack --tail=20 || true; nfail "could not delete $o"; }
done
# preventDelete: deleting the objects removed only the declarations; the server still holds the stream e2e-orders and its messages
jsz_wait 5 S.e2e-orders.messages=3 || { echo "$J"; nfail "after the Stream objects were deleted (preventDelete) the stream e2e-orders should still be on the server with its 3 messages"; }
echo "ok   preventDelete: the stream e2e-orders and its 3 messages are still on the server after its Stream object was deleted"
kubectl --context k3d-$cluster -n kube-system delete helmcharts.helm.cattle.io e2e-bus --timeout=120s || nfail "could not delete the HelmChart e2e-bus"
for _ in $(seq 1 30); do kc get statefulsets.apps e2e-bus >/dev/null 2>&1 || break; sleep 3; done   # up to 90 s
if kc get statefulsets.apps e2e-bus >/dev/null 2>&1; then
  kc get pods; kubectl --context k3d-$cluster -n kube-system get pods | grep -E 'helm-delete-e2e-bus|helm-install-e2e-bus' || true
  nfail "the StatefulSet e2e-bus is still there 90 s after the HelmChart was deleted"
fi
kc delete persistentvolumeclaims e2e-bus-js-e2e-bus-0 --timeout=60s || nfail "could not delete the PVC e2e-bus-js-e2e-bus-0"
# no ExternalSecret and no Password generator names the broker; a person deletes the Secrets and the credentials hook objects
[ -z "$(kc get externalsecrets.external-secrets.io,passwords.generators.external-secrets.io -o name 2>/dev/null | grep -E 'e2e-bus|e2e-orders|e2e-audit' || true)" ] || nfail "an ExternalSecret or Password generator names the broker"
kc delete secrets $bus_secrets e2e-bus-e2e-worker-app --ignore-not-found --timeout=60s >/dev/null || nfail "could not delete the Secrets of the broker"
kc delete serviceaccount/e2e-bus-credentials role/e2e-bus-credentials rolebinding/e2e-bus-credentials configmap/e2e-bus-credentials --ignore-not-found --timeout=60s >/dev/null || nfail "could not delete the credentials objects of the broker"
for j in $(kc get jobs.batch -o name 2>/dev/null | grep -E 'e2e-bus-credentials' || true); do kc delete "$j" --ignore-not-found --timeout=60s >/dev/null || nfail "could not delete $j"; done
left=$(kc get statefulsets.apps,persistentvolumeclaims,secrets,externalsecrets.external-secrets.io,streams.jetstream.nats.io,consumers.jetstream.nats.io,accounts.jetstream.nats.io -o name 2>/dev/null | grep -E 'e2e-bus|e2e-orders|e2e-audit' || true)
[ -z "$left" ] || nfail "objects of the broker are still in e2e-dev: $left"
echo "ok   bus is removed from system.yaml (nack.yaml and addons/dev/bus are gone) and deleted from the cluster; the broker steps took $((SECONDS - broker_t0)) s (budget 300 s)"

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

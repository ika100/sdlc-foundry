#!/usr/bin/env bash
# Platform upgrade end-to-end test (spec 121, AC-121.24 and AC-121.25, with the cluster halves of AC-121.4, .5, .8, .11, .15, .16, .19, .21, .22):
# a system created by the previous release is updated to this checkout and its database moves from Postgres 16 to 17, in the order a person
# would do it. No GitHub, no GHCR, no Argo CD (WITH_ARGO=0): the rendered manifests are applied with kubectl, as tests/e2e/run.sh does.
#
#   1. From      the previous release: $E2E_UPGRADE_FROM, else the newest tag v5.0.* while no release tag has scripts/cplat/versions.py,
#                else the newest such tag older than this commit; checked out with `git worktree add`.
#   2. Setup     with that release's own cplat and templates: system `upg`, a python service `upg-api` (dev, staging, prod; staging promotes
#                after-dev-smoke), postgres 16 (+ a bucket, a cache and a broker when that release supports the type), its local cluster
#                (floating defaults), all three environments healthy; every floating reference is resolved and recorded
#                ($work/resolved-<tag>.txt); a row, an object, a cache key and a message per environment.
#   3. Update    this checkout's `cplat platform update`; the report lists dev's moved pin and the held pins of staging and prod; the
#                local cluster's operators move once; dev, then staging, then prod move to this release's Postgres 16 pin, each applied and
#                verified (`platform update --verify`, `resource upgrade --verify`).
#   4. Guard     a bucket `backups` and `backup` on all three instances: `resource upgrade postgres --to 17` is refused without a recent
#                backup and changes nothing; then the backups run and every environment has a last_success.
#   5. Majors    dev goes to 17; a forced failing verification keeps staging and prod on 16 and readable; the real verification lets
#                staging follow; prod last, which folds the per-environment entries into `version: 17`.
#   6. Checks    major 17 and server_version 17.11 everywhere, the data of step 2 unchanged, `cplat instance verify`, doctor (every operator
#                `ok`), system status (upgrade.state verified), every rendered manifest accepted by the API server. Prints UPGRADE E2E OK.
#
# Time budget: about 40 minutes in the log (setup on the previous release 10, update and pin moves 9, backups 5, the three major steps with
# the forced failure 12, checks 4); the workflow gives it 75. Each step prints how long it took.
#
# Needs: docker (running), k3d, kubectl, uv, curl, copier (or uv), git with the release tags. Env: E2E_UPGRADE_FROM=<tag>, E2E_KEEP=1 keeps the
# cluster, E2E_PORT, E2E_WORK.
set -euo pipefail

root=$(cd "$(dirname "$0")/../.." && pwd)
work="${E2E_WORK:-$(mktemp -d)}"
port="${E2E_PORT:-8098}"
regport=5112
cluster=upg-local
ctx="k3d-$cluster"
registry="k3d-${cluster}-registry"
cplat="uv run $root/scripts/cplat/cplat.py"            # this checkout (the candidate)
export PATH="$PATH:$HOME/.local/bin"
if ! command -v devbox >/dev/null; then
  # CI has no devbox: `devbox run <script>` runs the repo's devbox.json script with the runner's own tools
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

gitops_repo="$work/upg-gitops"
api_repo="$work/upg-api"
app_dir="$gitops_repo/applications/upg"
started=$SECONDS
step_name=start
step_at=$SECONDS
durations=""

step() {
  local now=$SECONDS
  if [ "$step_name" != start ]; then
    durations="$durations$(printf '  %4ss  %s' $((now - step_at)) "$step_name")"$'\n'
  fi
  step_name="$*"; step_at=$now
  echo; echo "==> $* ($(((now - started) / 60)) min into the run)"
}
diagnose() {
  (
    set +e
    echo "--- diagnostics (step: $step_name) ---"
    kubectl --context "$ctx" get clusters.postgresql.cnpg.io,backups.postgresql.cnpg.io -A 2>&1 | tail -20
    kubectl --context "$ctx" get pods -A 2>&1 | grep -v -w Running | grep -v -w Completed | tail -30
    for e in dev staging prod; do
      echo "--- events upg-$e ---"
      kubectl --context "$ctx" -n "upg-$e" get events --sort-by=.lastTimestamp 2>&1 | tail -8
    done
  ) >&2 || true
}
fail() { echo "UPGRADE E2E FAIL [$step_name]: $*" >&2; diagnose; exit 1; }

cleanup() {
  rc=$?
  if [ "${E2E_KEEP:-0}" != 1 ]; then
    (cd "$gitops_repo" 2>/dev/null && LOCAL_CLUSTER=$cluster WITH_ARGO=0 REGISTRY_PORT=$regport bash scripts/local-cluster.sh down) >/dev/null 2>&1 || true
    git -C "$root" worktree remove --force "$work/from" >/dev/null 2>&1 || true
  fi
  if [ $rc -eq 0 ]; then
    step "done"
    echo; echo "Time per step:"; printf '%s' "$durations"
    total=$((SECONDS - started))
    echo "Total: $((total / 60)) min $((total % 60)) s"
    [ "$total" -le 2700 ] || echo "WARNING: the run took more than 45 minutes in the log (budget: about 40)"
    echo; echo "UPGRADE E2E OK"
  else
    echo; echo "UPGRADE E2E FAILED at step '$step_name' (work dir: $work)"
  fi
  exit $rc
}
trap cleanup EXIT

for t in docker k3d kubectl uv curl git python3; do command -v $t >/dev/null || fail "$t is required"; done
docker info >/dev/null 2>&1 || fail "docker is not running"

gitops_head() { (cd "$gitops_repo" && git rev-parse HEAD); }
gitops_dirty() { (cd "$gitops_repo" && git status --porcelain); }
commit() { (cd "$gitops_repo" && git add -A && { git diff --cached --quiet || git -c user.name=e2e -c user.email=e2e@example.com commit -qm "$1"; }); }
tmo() { local s=$1; shift; if command -v timeout >/dev/null; then timeout "$s" "$@"; elif command -v gtimeout >/dev/null; then gtimeout "$s" "$@"; else "$@"; fi; }
k() { kubectl --context "$ctx" "$@"; }
kn() { local n=$1; shift; kubectl --context "$ctx" -n "$n" "$@"; }
wait_for() { # seconds what command...: polls every 5 s, names the seconds it waited when it gives up
  local secs=$1 what=$2 i=0; shift 2
  while [ $i -lt "$secs" ]; do "$@" >/dev/null 2>&1 && return 0; sleep 5; i=$((i + 5)); done
  fail "$what did not happen within ${secs}s"
}
pgc() { echo "clusters.postgresql.cnpg.io/upg-postgres"; }
cfield() { kn "upg-$1" get "$(pgc)" -o "jsonpath=$2" 2>/dev/null; }   # env jsonpath of the environment's Postgres cluster
healthy() { [ "$(cfield "$1" '{.status.phase}')" = "Cluster in healthy state" ]; }
wait_healthy() { wait_for "$2" "the Postgres cluster of $1 to be healthy" healthy "$1"; }
cplat_run() { # label seconds command...: streams the output, fails with the label when the command fails
  local label=$1 secs=$2; shift 2
  tmo "$secs" "$@" 2>&1 | tee /dev/stderr || fail "$label failed (exit ${PIPESTATUS[0]})"
}
yaml_py() { uv run --with pyyaml --with ruamel.yaml python "$@"; }
system_get() { # python expression over `d`, the parsed system.yaml (yaml.safe_load)
  yaml_py - "$app_dir/system.yaml" "$1" <<'PY'
import sys, yaml
d = yaml.safe_load(open(sys.argv[1]))
print(eval(sys.argv[2]))
PY
}
table_pin() { # major: the postgres reference of this checkout's versions table, from the repo's own render.py
  yaml_py - "$gitops_repo/scripts/render.py" "$1" <<'PY'
import importlib.util, sys
spec = importlib.util.spec_from_file_location("render_repo", sys.argv[1])
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
print(mod.table_pin("database", int(sys.argv[2]))["pin"])
PY
}
image_name_of() { # env: spec.imageName of the rendered cluster
  yaml_py - "$app_dir/addons/$1/postgres/cluster.yaml" <<'PY'
import sys, yaml
docs = [d for d in yaml.safe_load_all(open(sys.argv[1])) if isinstance(d, dict) and d.get("kind") == "Cluster"]
print(docs[0]["spec"]["imageName"])
PY
}

# ---------------------------------------------------------------------------------------------------------------------------------
step "1 From: pick the previous release and check it out next to this commit"
has_versions() { git -C "$root" cat-file -e "$1:scripts/cplat/versions.py" 2>/dev/null; }
FROM="${E2E_UPGRADE_FROM:-}"
if [ -z "$FROM" ]; then
  any=0
  for t in $(git -C "$root" tag --list 'v*' --sort=-v:refname); do has_versions "$t" && { any=1; break; }; done
  if [ $any = 0 ]; then
    FROM=$(git -C "$root" tag --list 'v5.0.*' --sort=-v:refname | head -1)
  else
    here=$(git -C "$root" tag --points-at HEAD)
    for t in $(git -C "$root" tag --merged HEAD --sort=-v:refname); do
      has_versions "$t" || continue
      grep -x -F -q "$t" <<< "$here" && continue
      FROM=$t; break
    done
  fi
fi
[ -n "$FROM" ] || fail "no previous release tag found (v5.0.*)"
echo "previous release: $FROM"
(cd "$root" && git worktree add --detach "$work/from" "$FROM") >/dev/null 2>&1 || fail "git worktree add $work/from $FROM failed"
from_cplat="uv run $work/from/scripts/cplat/cplat.py"   # the previous release's own cplat and templates

# the resource types that release supports: RESOURCE_TYPES minus PLANNED_TYPES, read with ast (the release is never imported)
FROM_TYPES=$(python3 - "$work/from" <<'PY'
import ast, sys
from pathlib import Path

root = Path(sys.argv[1])
found = {}
for rel in ("templates/gitops-app/scripts/render.py", "scripts/cplat/addon.py"):
    path = root / rel
    if not path.is_file():
        continue
    for node in ast.parse(path.read_text()).body:
        targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
        for t in targets:
            if isinstance(t, ast.Name) and t.id in ("RESOURCE_TYPES", "PLANNED_TYPES") and t.id not in found and getattr(node, "value", None) is not None:
                try:
                    found[t.id] = ast.literal_eval(node.value)
                except ValueError:
                    pass
print(" ".join(t for t in found.get("RESOURCE_TYPES", ("database",)) if t not in (found.get("PLANNED_TYPES") or {})))
PY
)
echo "$FROM supports: $FROM_TYPES"
has_type() { grep -w -q "$1" <<< "$FROM_TYPES"; }

# ---------------------------------------------------------------------------------------------------------------------------------
step "2 Setup on $FROM: system upg, python service upg-api, postgres 16, its local cluster with the floating defaults"
printf '%s\n' 'system: upg' 'owner: upg' 'components:' \
  '  - {name: upg-api, description: "upg api", type: service, lang: python}' > "$work/system.yml"
$from_cplat system new "$work/system.yml" --no-github --skip-tasks --dir "$work" --org upg >/dev/null || fail "system new (previous release) failed"
[ -f "$app_dir/system.yaml" ] || fail "system new did not write applications/upg/system.yaml"
git -C "$gitops_repo" config user.name e2e
git -C "$gitops_repo" config user.email e2e@example.com
main_branch=$(git -C "$gitops_repo" symbolic-ref --short HEAD)

$from_cplat resource add postgres --version 16 --repo-dir "$gitops_repo" >/dev/null || fail "resource add postgres --version 16 failed"
commit "postgres 16"
for pair in bucket:files cache:sessions broker:bus; do
  typ=${pair%%:*}; name=${pair##*:}
  if has_type "$typ"; then
    $from_cplat resource add "$name" --type "$typ" --repo-dir "$gitops_repo" >/dev/null || fail "resource add $name --type $typ failed"
    commit "$name"
  else
    echo "skip: $typ is not in $FROM"
  fi
done

# environments, the component and its instances (one Python edit with the previous release's own modules, as /component:add does)
(cd "$gitops_repo" && FROM_TYPES="$FROM_TYPES" uv run --with pyyaml --with ruamel.yaml python - "$work/from" "$port" "$registry:$regport" <<'PY'
import os, sys
from pathlib import Path
sys.path.insert(0, f"{sys.argv[1]}/scripts/cplat")
import compose, core, gitops

port, registry = sys.argv[2], sys.argv[3]
types = os.environ["FROM_TYPES"].split()
app_dir = gitops.find_app(Path("."))
y, data = gitops.load(app_dir)
for env in ("dev", "staging", "prod"):
    data["environments"][env]["host"] = "{component}.{system}-" + env + ".localhost"
    data["environments"][env]["url"] = "http://{host}:" + port
data["environments"]["staging"]["promote"] = "after-dev-smoke"
shapes = {s["id"]: s for s in core.registry.load()}
ns = compose.build_parser().parse_args(["add", "upg-api", "--expose"])    # real parser defaults
ns.env, ns.generate, ns.secret, ns.secret_ref = [], [], [], []
ns.uses = ["postgres"] + [name for typ, name in (("bucket", "files"), ("cache", "sessions"), ("broker", "bus")) if typ in types]
if "broker" in types:
    data["apis"] = {"orders": {"type": "events"}}
    ns.provides, ns.consumes = ["orders"], ["orders"]
components = gitops.components_of(data)
entry = compose.build_entry("upg-api", "upg/upg-api", shapes["service-python"], None, registry, ns, {})
if "broker" in types:
    entry["provides"], entry["consumes"] = ["orders"], ["orders"]
    entry["uses"] = [u for u in entry["uses"] if u != "bus"]
entry["instances"] = {"dev": {}, "staging": {}, "prod": {}}
components["upg-api"] = entry
gitops.save(app_dir, y, data)
PY
cd "$gitops_repo" && uv run scripts/render.py) || fail "describing the component and rendering (previous release) failed"
commit "upg-api in dev, staging and prod"
[ -f "$app_dir/addons/dev/postgres/cluster.yaml" ] || fail "render did not write addons/dev/postgres/cluster.yaml"
for e in dev staging prod; do echo "$e=$(image_name_of $e)"; done > "$work/pins-before.txt"
echo "database references of $FROM:"; cat "$work/pins-before.txt"

step "2 Setup on $FROM: the local cluster, with the floating defaults of that release (no version variables)"
(cd "$gitops_repo" && LOCAL_CLUSTER=$cluster LOCAL_HTTP_PORT=$port WITH_ARGO=0 REGISTRY_PORT=$regport bash scripts/local-cluster.sh up 2>&1 | tee /dev/stderr >/dev/null) \
  || fail "local-cluster.sh up (previous release) failed"
k get nodes >/dev/null || fail "the cluster $ctx is not reachable"

step "2 Setup on $FROM: build and push upg-api"
(cd "$api_repo" && uv lock -q) || fail "uv lock in upg-api failed"      # --skip-tasks left no uv.lock and the Dockerfile needs it
docker build -q -t "localhost:$regport/upg-api:latest" "$api_repo" >/dev/null || fail "docker build upg-api failed"
docker push -q "localhost:$regport/upg-api:latest" >/dev/null || fail "docker push upg-api failed"
# a copy of the service whose smoke recipe always fails (step 5: the forced failed verification)
rm -rf "$work/upg-api-failing"; cp -R "$api_repo" "$work/upg-api-failing"
python3 - "$work/upg-api-failing/devbox.json" <<'PY'
import json, sys
path = sys.argv[1]
d = json.load(open(path))
d["shell"]["scripts"]["smoke"] = "echo 'FAIL forced'; exit 1"
json.dump(d, open(path, "w"), indent=2)
PY

# ---- probes: plain Pods that carry upg-api's own variables, as the component sees them ----
S3_IMAGE=amazon/aws-cli:2.22.35
NATS_IMAGE=natsio/nats-box:0.14.5
read -r -d '' pod_py <<'PY' || true
import json, re, sys
name, image, regex, script = sys.argv[1:5]
dep = json.loads(sys.stdin.read())
env = [e for e in dep["spec"]["template"]["spec"]["containers"][0].get("env", [])   # Secret refs and plain values (EVENTS_<API>_*)
       if ("valueFrom" in e or "value" in e) and re.match(regex, e["name"])]
env += [{"name": k, "value": v} for k, v in (("HOME", "/tmp"), ("AWS_PAGER", ""), ("AWS_EC2_METADATA_DISABLED", "true"),
                                             ("AWS_REQUEST_CHECKSUM_CALCULATION", "when_required"), ("AWS_RESPONSE_CHECKSUM_VALIDATION", "when_required"))]
print(json.dumps({"apiVersion": "v1", "kind": "Pod", "metadata": {"name": name, "labels": {"app": "upgprobe"}},
                  "spec": {"restartPolicy": "Never", "containers": [{"name": "probe", "image": image, "command": ["sh", "-c", script], "env": env}]}}))
PY
pn=0
P_OUT=""
podrun() { # env image env-regex script: output in P_OUT, success when the pod Succeeded
  local e=$1 name phase=""
  pn=$((pn + 1)); name="upgprobe-$pn"
  kn "upg-$e" get deployments.apps/upg-api -o json | python3 -c "$pod_py" "$name" "$2" "$3" "$4" | kn "upg-$e" apply -f - >/dev/null \
    || fail "could not start the probe pod $name in $e"
  for _ in $(seq 1 90); do   # up to 270 s (the first run pulls the image)
    phase=$(kn "upg-$e" get "pods/$name" -o jsonpath='{.status.phase}' 2>/dev/null || true)
    case "$phase" in Succeeded|Failed) break;; esac; sleep 3
  done
  P_OUT=$(kn "upg-$e" logs "pods/$name" 2>&1 || true)
  [ "$phase" = Succeeded ] || P_OUT="$P_OUT (pod phase: ${phase:-unknown}; $(kn "upg-$e" get "pods/$name" -o jsonpath='{.status.containerStatuses[*].state.waiting.reason}' 2>/dev/null))"
  kn "upg-$e" delete "pods/$name" --wait=false >/dev/null 2>&1 || true
  [ "$phase" = Succeeded ]
}
podmust() { # label env image env-regex script: up to 6 tries (a database or store may need a moment)
  local i
  for i in 1 2 3 4 5 6; do podrun "$2" "$3" "$4" "$5" && return 0; sleep 10; done
  fail "$1: $(echo "$P_OUT" | tail -5 | tr '\n' ' ' | cut -c1-500)"
}
Q=""
dbq() { # env sql (single quotes only): psql through the component's DATABASE_URL; the last line of the answer in Q
  local img; img=$(cfield "$1" '{.status.image}')
  podmust "psql in $1" "$1" "$img" '^(DATABASE_URL|PG)' "psql \"\$DATABASE_URL\" -v ON_ERROR_STOP=1 -tA -c \"$2\""
  Q=$(printf '%s\n' "$P_OUT" | grep -v '^$' | tail -1 || true)
}
s3pre='set -e; [ "$S3_FORCE_PATH_STYLE" = true ] && aws configure set default.s3.addressing_style path; A="aws --endpoint-url $S3_ENDPOINT"; '
natspre='N="nats --server $NATS_URL --user $NATS_USER --password $NATS_PASSWORD"; '

write_data() { # env: a row, an object, a cache key and a message (only for the types that release supports)
  dbq "$1" "create table if not exists upg_check (id int primary key, tag text); insert into upg_check values (1, '$1-before') on conflict do nothing"
  if has_type bucket; then
    podmust "bucket write in $1" "$1" "$S3_IMAGE" '^(S3|AWS)_' "$s3pre"'printf %s '"$1-before"' > /tmp/in; $A s3api put-object --bucket "$S3_BUCKET" --key upg/'"$1"'.txt --body /tmp/in >/dev/null'
  fi
  if has_type cache; then
    local img; img=$(kn "upg-$1" get statefulsets.apps/upg-sessions -o jsonpath='{.spec.template.spec.containers[0].image}')
    # one cache: the bare REDIS_* names (variable_names, AC-115.8); a url from before 5.4.0 names no user (spec 127)
    podmust "cache write in $1" "$1" "$img" '^REDIS_' 'u=$(printf %s "$REDIS_URL" | sed "s#^redis://:#redis://default:#"); valkey-cli -u "$u" SET upg:'"$1 $1-before"' | grep -w OK'
  fi
  if has_type broker; then
    podmust "stream message in $1" "$1" "$NATS_IMAGE" '^(NATS|EVENTS)_' "$natspre"'$N pub "$EVENTS_ORDERS_SUBJECT_PREFIX.created" '"$1-before"
  fi
}
read_data() { # env: the data of write_data reads back unchanged (the cache key is not required)
  dbq "$1" "select tag from upg_check where id = 1"
  [ "$Q" = "$1-before" ] || fail "the row of $1 reads '$Q', expected '$1-before'"
  if has_type bucket; then
    podmust "bucket read in $1" "$1" "$S3_IMAGE" '^(S3|AWS)_' "$s3pre"'$A s3api get-object --bucket "$S3_BUCKET" --key upg/'"$1"'.txt /tmp/out >/dev/null; echo "CONTENT=$(cat /tmp/out)"'
    grep -w -F -q "CONTENT=$1-before" <<< "$P_OUT" || fail "the object upg/$1.txt of $1 does not read $1-before: $P_OUT"
  fi
  if has_type broker; then
    podmust "stream message read in $1" "$1" "$NATS_IMAGE" '^(NATS|EVENTS)_' "$natspre"'$N consumer next "$EVENTS_ORDERS_STREAM" "$EVENTS_ORDERS_CONSUMER" --count 1 --no-ack'
    grep -w -F -q "$1-before" <<< "$P_OUT" || fail "the message of $1 is gone from the stream: $P_OUT"
  fi
  echo "ok   $1: the data of step 2 reads back unchanged"
}

# ---- apply what the renderer wrote (what Argo CD would sync) ----
apply_bucket() { # env bucket: the key generators and the ExternalSecret first, then the store, the bucket and the identity, then the credentials
  local e=$1 b=$2 d="$app_dir/addons/$1/$2" f kk
  for f in access-key-generator.yaml secret-key-generator.yaml externalsecret.yaml seaweed.yaml bucket.yaml identity.yaml credentials.yaml kustomization.yaml; do
    [ -f "$d/$f" ] || fail "render did not write addons/$e/$b/$f"
  done
  kn "upg-$e" apply -f "$d/access-key-generator.yaml" -f "$d/secret-key-generator.yaml" -f "$d/externalsecret.yaml" >/dev/null || fail "applying the key generators of $b in $e failed"
  for _ in $(seq 1 40); do   # up to 120 s
    [ -n "$(kn "upg-$e" get "secrets/upg-$b-app" -o jsonpath='{.data.secretAccessKey}' 2>/dev/null)" ] && break; sleep 3
  done
  for kk in endpoint bucket region forcePathStyle accessKeyId secretAccessKey; do
    [ -n "$(kn "upg-$e" get "secrets/upg-$b-app" -o jsonpath="{.data.$kk}" 2>/dev/null)" ] || fail "the Secret upg-$b-app in upg-$e lacks the key $kk (waited 120s)"
  done
  kn "upg-$e" apply -f "$d/seaweed.yaml" -f "$d/bucket.yaml" -f "$d/identity.yaml" >/dev/null || fail "applying the store of $b in $e failed"
  kn "upg-$e" apply -f "$d/credentials.yaml" >/dev/null || fail "applying the credentials of $b in $e failed"
  kn "upg-$e" apply -k "$d" >/dev/null || fail "applying addons/$e/$b failed"
  for s in master volume filer; do
    for _ in $(seq 1 60); do kn "upg-$e" get "statefulsets.apps/upg-$b-$s" >/dev/null 2>&1 && break; sleep 3; done   # up to 180 s
    kn "upg-$e" rollout status "statefulsets.apps/upg-$b-$s" --timeout=300s 2>&1 | tee /dev/stderr >/dev/null || fail "the SeaweedFS $s of upg-$b in upg-$e did not become ready (waited 300s)"
  done
}
apply_bus() { # env broker: what Argo CD would do, as tests/e2e/run.sh does it: the Secrets first, the NATS server's Application as a k3s
  # HelmChart (same repo, chart, version and values; one per environment), then the Account, the streams and the consumers once NACK serves them
  local e=$1 b=$2 d="$app_dir/addons/$1/$2" out="$work/bus-$1-$2"
  mkdir -p "$out"
  local py
  read -r -d '' py <<'PY' || true
import sys
import yaml
out, env = sys.argv[1], sys.argv[2]
first, chart, second = [], [], []
for d in (d for d in yaml.safe_load_all(sys.stdin) if d):
    if d["kind"] == "Application":
        s = d["spec"]["source"]
        chart.append({"apiVersion": "helm.cattle.io/v1", "kind": "HelmChart",
                      "metadata": {"name": f"{s['helm']['releaseName']}-{env}", "namespace": "kube-system"},
                      "spec": {"repo": s["repoURL"], "chart": s["chart"], "version": s["targetRevision"],
                               "targetNamespace": d["spec"]["destination"]["namespace"], "valuesContent": yaml.safe_dump(s["helm"]["valuesObject"])}})
    elif d["kind"] in ("Account", "Stream", "Consumer"):
        second.append(d)
    else:
        first.append(d)
if not chart:
    sys.exit("no Application (the NATS server) in the addon")
for name, items in (("1.yaml", first), ("chart.yaml", chart), ("2.yaml", second)):
    open(f"{out}/{name}", "w").write(yaml.safe_dump_all(items))
PY
  kn "upg-$e" kustomize "$d" | yaml_py -c "$py" "$out" "$e" || fail "could not turn addons/$e/$b into objects to apply"
  kn "upg-$e" apply -f "$out/1.yaml" >/dev/null || fail "applying the Secrets of $b in $e failed"
  k apply -f "$out/chart.yaml" >/dev/null || fail "applying the HelmChart of $b in $e failed"
  wait_for 180 "the StatefulSet upg-$b of $e" kn "upg-$e" get statefulsets.apps "upg-$b"
  kn "upg-$e" rollout status "statefulsets.apps/upg-$b" --timeout=240s >/dev/null || fail "the NATS server upg-$b of $e did not become ready"
  wait_for 180 "the objects of $b in $e (NACK)" kn "upg-$e" apply -f "$out/2.yaml"
}
apply_addons() { # env: every rendered addon of the environment
  local e=$1 d="$app_dir/addons/$1" a
  for a in $(ls "$d"); do
    [ -f "$d/$a/kustomization.yaml" ] || continue
    if [ -f "$d/$a/bucket.yaml" ]; then apply_bucket "$e" "$a"
    elif [ -f "$d/$a/server.yaml" ]; then apply_bus "$e" "$a"   # a broker: its server is an Argo CD Application (no Argo CD here)
    else
      kn "upg-$e" apply -k "$d/$a" 2>&1 | tee /dev/stderr >/dev/null || fail "applying addons/$e/$a failed"
    fi
  done
}
apply_api() { # env: the overlay, then wait for the rollout and the answer through the Gateway
  local e=$1 out=""
  kn "upg-$e" apply -k "$app_dir/overlays/$e/upg-api" 2>&1 | tee /dev/stderr >/dev/null || fail "applying overlays/$e/upg-api failed"
  kn "upg-$e" rollout status deployments.apps/upg-api --timeout=300s 2>&1 | tee /dev/stderr >/dev/null || fail "upg-api did not become ready in $e (waited 300s)"
  for _ in $(seq 1 30); do   # up to 90 s
    out=$(curl -s -m 5 "http://upg-api.upg-$e.localhost:$port/health" || true)
    case "$out" in *'"status":"ok"'*) echo "ok   upg-api answers in $e"; return 0;; esac
    sleep 3
  done
  fail "upg-api in $e did not answer through the Gateway within 90s (got: ${out:-nothing})"
}
apply_env() { # env: addons, then the database, then the service
  apply_addons "$1"
  wait_healthy "$1" 900
  apply_api "$1"
}

step "2 Setup on $FROM: apply the three environments and wait until each is healthy"
for e in dev staging prod; do
  apply_env "$e"
done

step "2 Setup on $FROM: the data (a row, an object, a cache key, a message per environment) and the resolved floating references"
for e in dev staging prod; do write_data "$e"; read_data "$e"; done
record_resolved() { # file: every container's imageID and every HelmChart's version, as `resolved <reference> -> <digest or version>`
  python3 - "$ctx" <<'PY' > "$1"
import json, subprocess, sys

ctx = sys.argv[1]

def fetch(*args):
    return json.loads(subprocess.run(["kubectl", "--context", ctx, *args, "-o", "json"], capture_output=True, text=True, check=True).stdout)

lines = set()
for pod in fetch("get", "pods", "-A")["items"]:
    status = (pod.get("status") or {})
    for cs in (status.get("containerStatuses") or []) + (status.get("initContainerStatuses") or []):
        image, image_id = cs.get("image", ""), cs.get("imageID", "")
        digest = image_id.split("@", 1)[1] if "@" in image_id else image_id
        if image and digest:
            lines.add(f"resolved {image} -> {digest}")
labels = {}
for kind in ("deployments.apps", "statefulsets.apps"):
    for obj in fetch("get", kind, "-A")["items"]:
        chart = (obj["metadata"].get("labels") or {}).get("helm.sh/chart")
        release = (obj["metadata"].get("labels") or {}).get("app.kubernetes.io/instance")
        if chart:
            labels[release] = chart
for hc in fetch("get", "helmcharts.helm.cattle.io", "-A")["items"]:
    name, spec = hc["metadata"]["name"], hc.get("spec") or {}
    version = spec.get("version") or ("floating, installed " + labels.get(name, "unknown"))
    lines.add(f"resolved helmchart {spec.get('chart') or name} -> {version}")
print("\n".join(sorted(lines)))
PY
}
record_resolved "$work/resolved-$FROM.txt" || fail "could not read the resolved references from the cluster (imageID of the pods, the HelmCharts)"
cat "$work/resolved-$FROM.txt"
grep -q '^resolved .* -> ' "$work/resolved-$FROM.txt" || fail "no resolved reference was recorded in $work/resolved-$FROM.txt"
grep -q '^resolved helmchart ' "$work/resolved-$FROM.txt" || fail "no HelmChart was recorded in $work/resolved-$FROM.txt (helmcharts.helm.cattle.io)"
echo "ok   $(wc -l < "$work/resolved-$FROM.txt" | tr -d ' ') floating references resolved and saved to $work/resolved-$FROM.txt (AC-121.24)"

# ---------------------------------------------------------------------------------------------------------------------------------
step "3 Update: this checkout's cplat platform update, merged"
[ -z "$(gitops_dirty)" ] || fail "the gitops repo is not clean before the update"
$cplat platform update --repo "$gitops_repo" --skip-tasks 2>&1 | tee "$work/update.out" | tee /dev/stderr >/dev/null || fail "cplat platform update failed"
upd_branch=$(git -C "$gitops_repo" symbolic-ref --short HEAD)
[ "$upd_branch" != "$main_branch" ] || fail "platform update left the repo on $main_branch (it should have made a branch)"
git -C "$gitops_repo" checkout -q "$main_branch" && git -C "$gitops_repo" merge -q --ff-only "$upd_branch" || fail "merging $upd_branch into $main_branch failed"
(cd "$gitops_repo" && uv run scripts/render.py >/dev/null) || fail "render.py of the updated repo failed"
commit "render after the platform update"
python3 - "$work/update.out" <<'PY' || fail "the update report does not list dev's moved pin and the held pins of staging and prod (see above)"
import re, sys
text = open(sys.argv[1]).read()
if not re.search(r"(?m)^\s*dev\s+postgres 16: .*\bmoves now\b", text):
    sys.exit("no line 'dev  postgres 16: ... (moves now)'")
for env in ("staging", "prod"):
    if not re.search(rf"(?m)^\s*{env}\s+postgres 16: keeps\b.*--to 16 --env {env}\b", text):
        sys.exit(f"no line '{env}  postgres 16: keeps ... until /resource:upgrade postgres --to 16 --env {env}'")
PY
echo "ok   the report lists dev's moved pin and the held pins of staging and prod"
table16=$(table_pin 16)
[ "$(image_name_of dev)" = "$table16" ] || fail "dev's imageName is '$(image_name_of dev)', the table's postgres 16 is '$table16'"
for e in staging prod; do
  want=$(sed -n "s/^$e=//p" "$work/pins-before.txt")
  [ "$(image_name_of $e)" = "$want" ] || fail "$e's imageName moved to '$(image_name_of $e)'; it must keep '$want' (held pin) until /resource:upgrade postgres --to 16 --env $e"
done
echo "ok   dev's imageName is the table's 16 pin; staging and prod keep $FROM's reference (AC-121.11)"

step "3 Update: this checkout's local-cluster.sh up on the same cluster (the operators move once, AC-121.21)"
chart_versions() { # name version per HelmChart
  k get helmcharts.helm.cattle.io -A -o jsonpath='{range .items[*]}{.metadata.name}{" "}{.spec.version}{"\n"}{end}' | sort
}
(cd "$gitops_repo" && LOCAL_CLUSTER=$cluster LOCAL_HTTP_PORT=$port WITH_ARGO=0 REGISTRY_PORT=$regport bash scripts/local-cluster.sh up 2>&1 | tee "$work/up-candidate.out" | tee /dev/stderr >/dev/null) \
  || fail "local-cluster.sh up (this checkout) failed"
if grep -q "overrides the versions table" "$work/up-candidate.out"; then
  grep "overrides the versions table" "$work/up-candidate.out" >&2
  fail "local-cluster.sh printed a WARNING that a variable overrides the versions table, but the e2e sets no version variable"
fi
chart_versions > "$work/charts-after-update.txt"
cat "$work/charts-after-update.txt"
for f in "$gitops_repo"/operators/apps/*.yaml; do
  [ -f "$f" ] || continue
  op=$(basename "$f" .yaml)
  pin=$(sed -n 's/^[[:space:]]*targetRevision:[[:space:]]*["'"'"']\{0,1\}\([^"'"'"'[:space:]]*\).*/\1/p' "$f" | head -1)
  have=$(sed -n "s/^$op //p" "$work/charts-after-update.txt" | head -1)
  [ -z "$have" ] || [ "$have" = "$pin" ] || fail "the installed chart $op is '$have', operators/apps/$op.yaml pins '$pin'"
done
echo "ok   every installed operator chart is its operators/apps pin"
for e in dev staging prod; do wait_healthy "$e" 900; done   # the operator may roll the instance managers

step "3 Update: apply dev, then platform update --verify (operators ok, dev's moved pin, every environment's smoke tests)"
apply_addons dev
apply_api dev
verify_out="$work/update-verify.out"
if tmo 2400 $cplat platform update --verify --repo "$gitops_repo" --context k3d-$cluster --component-dir upg-api="$work/upg-api" 2>&1 | tee "$verify_out" | tee /dev/stderr >/dev/null; then :
else fail "cplat platform update --verify failed (see above; $verify_out)"; fi
grep -w -q "verified" "$verify_out" || fail "platform update --verify did not print 'verified' for postgres in dev"
echo "ok   platform update --verify: operators at the table's versions, dev verified, smoke of every environment passed"

step "3 Update: staging and prod move to this release's Postgres 16 pin, one at a time (AC-121.11)"
echo "pin moves, one environment at a time: /resource:upgrade postgres --to 16 --env staging, then --to 16 --env prod"
[ -n "$(gitops_dirty)" ] || fail "platform update --verify did not write the staging pin move (promote: after-dev-smoke)"
grep -F -q "$table16" "$app_dir/addons/staging/postgres/cluster.yaml" || fail "the staging pin move did not write the table's 16 pin"
commit "staging: this release's postgres 16 pin"
apply_addons staging
$cplat resource upgrade postgres --verify --env staging --repo-dir "$gitops_repo" --context "$ctx" --component-dir upg-api="$work/upg-api" 2>&1 | tee /dev/stderr >/dev/null \
  || fail "resource upgrade --verify --env staging failed after the pin move"
cplat_run "resource upgrade postgres --to 16 --env prod" 300 $cplat resource upgrade postgres --to 16 --env prod --repo-dir "$gitops_repo" --context "$ctx" >/dev/null
commit "prod: this release's postgres 16 pin"
apply_addons prod
$cplat resource upgrade postgres --verify --env prod --repo-dir "$gitops_repo" --context "$ctx" --component-dir upg-api="$work/upg-api" 2>&1 | tee /dev/stderr >/dev/null \
  || fail "resource upgrade --verify --env prod failed after the pin move"
for e in dev staging prod; do
  [ "$(image_name_of $e)" = "$table16" ] || fail "$e's imageName is '$(image_name_of $e)' after the pin moves, expected '$table16'"
  read_data "$e"
done

# ---------------------------------------------------------------------------------------------------------------------------------
step "4 Guard: backups declared and rendered but not applied; the major upgrade is refused and changes nothing (AC-121.25)"
$cplat resource add backups --type bucket --repo-dir "$gitops_repo" >/dev/null || fail "resource add backups --type bucket failed"
commit "bucket backups"
(cd "$gitops_repo" && uv run --with pyyaml --with ruamel.yaml python - "$root" <<'PY'
import sys
sys.path.insert(0, f"{sys.argv[1]}/scripts/cplat")
import gitops
from pathlib import Path
app_dir = gitops.find_app(Path("."))
y, data = gitops.load(app_dir)
components = gitops.components_of(data)
components["upg-api"]["uses"] = [*(components["upg-api"].get("uses") or []), "backups"]   # the target must be used by a component in the environment
pg = data["resources"]["postgres"]
instances = pg.get("instances") or {}
for env in ("dev", "staging", "prod"):
    instances[env] = {**(instances.get(env) or {}), "backup": {"to": "backups"}}
pg["instances"] = instances
gitops.save(app_dir, y, data)
PY
uv run scripts/render.py) || fail "render.py failed with backup on all three instances"
commit "postgres: backup to the bucket backups in dev, staging and prod"

# the backup operators (plugin, cert-manager, SeaweedFS) are new in operators/apps: the same script installs them; the ones from step 3 do not move again
(cd "$gitops_repo" && LOCAL_CLUSTER=$cluster LOCAL_HTTP_PORT=$port WITH_ARGO=0 REGISTRY_PORT=$regport bash scripts/local-cluster.sh up 2>&1 | tee "$work/up-backups.out" | tee /dev/stderr >/dev/null) \
  || fail "local-cluster.sh up (for the backup operators) failed"
chart_versions > "$work/charts-after-backups.txt"
while read -r name version; do
  [ -n "$name" ] || continue
  now=$(sed -n "s/^$name //p" "$work/charts-after-backups.txt" | head -1)
  [ "$now" = "$version" ] || fail "the operator chart $name moved twice: '$version' after the update, '$now' after the second cluster-up"
done < "$work/charts-after-update.txt"
echo "ok   no operator chart moved a second time (AC-121.21)"
wait_for 300 "the Barman Cloud ObjectStore CRD" k get customresourcedefinitions.apiextensions.k8s.io/objectstores.barmancloud.cnpg.io
wait_for 300 "the ExternalSecret CRD" k get customresourcedefinitions.apiextensions.k8s.io/externalsecrets.external-secrets.io

# only the ObjectStore of dev is applied: the Cluster has no plugin and no backup yet, so the last successful backup reads never
kn upg-dev apply -f "$app_dir/addons/dev/postgres/objectstore.yaml" >/dev/null || fail "applying the ObjectStore of dev failed"
head_before=$(gitops_head)
image_before=$(cfield dev '{.spec.imageName}')
gen_before=$(cfield dev '{.metadata.generation}')
if out=$($cplat resource upgrade postgres --to 17 --env dev --repo-dir "$gitops_repo" --context "$ctx" 2>&1); then rc=0; else rc=$?; fi
echo "$out" >&2
[ "$rc" = 1 ] || fail "resource upgrade postgres --to 17 without a backup exited $rc, expected 1"
grep -w -i -q "never" <<< "$out" || fail "the refusal does not say the last successful backup is never"
grep -F -q "/resource:backup postgres --env dev" <<< "$out" || fail "the refusal does not name /resource:backup postgres --env dev"
[ "$(gitops_head)" = "$head_before" ] || fail "the refused upgrade changed HEAD"
[ -z "$(gitops_dirty)" ] || fail "the refused upgrade left changes in the tree"
[ "$(cfield dev '{.spec.imageName}')" = "$image_before" ] && [ "$(cfield dev '{.metadata.generation}')" = "$gen_before" ] \
  || fail "the refused upgrade changed the dev Cluster (imageName or .metadata.generation)"
echo "ok   refused without a backup (last successful backup never); HEAD, tree and the dev Cluster are unchanged"

step "4 Guard: apply the backups, take the first backup of every environment, wait for last_success"
for e in dev staging prod; do
  apply_addons "$e"
  wait_healthy "$e" 900
  apply_api "$e"
done
last_success() { # env: last_success of postgres in the environment, from `cplat system status --json`
  $cplat system status --json --repo-dir "$gitops_repo" --context "$ctx" 2>/dev/null | python3 -c '
import json, sys
d = json.loads(sys.stdin.read())
r = next(r for r in d["backups"]["resource_instances"] if r["resource"] == "postgres" and r["environment"] == sys.argv[1])
print(r["backup"].get("last_success") or "")' "$1"
}
has_last_success() { [ -n "$(last_success "$1")" ]; }
archiving_on() { [ "$(cfield "$1" '{.status.conditions[?(@.type=="ContinuousArchiving")].status}')" = True ]; }
take_backup() { # env: the on-demand backup (CloudNativePG's immediate one may fail while the plugin loads, so it is not relied on)
  local i out
  wait_for 500 "the plugin to be loaded in $1 (ContinuousArchiving)" archiving_on "$1"
  for i in 1 2 3; do
    if out=$(tmo 600 $cplat resource backup postgres --env "$1" --repo-dir "$gitops_repo" --context "$ctx" 2>&1 | tee /dev/stderr) && grep -q "backup completed" <<< "$out"; then return 0; fi
    sleep 20
  done
  fail "/resource:backup postgres --env $1 did not complete in 3 tries"
}
for e in dev staging prod; do
  take_backup "$e"
  wait_for 600 "last_success of postgres in $e (cplat system status)" has_last_success "$e"
  echo "ok   $e: last_success $(last_success "$e")"
done

# ---------------------------------------------------------------------------------------------------------------------------------
step "5 Majors: dev to 17, then a forced failed verification (AC-121.25)"
cplat_run "resource upgrade postgres --to 17 --env dev" 300 $cplat resource upgrade postgres --to 17 --env dev --repo-dir "$gitops_repo" --context "$ctx" >/dev/null
[ "$(system_get "d['resources']['postgres']['instances']['dev']['version']")" = 17 ] || fail "system.yaml lacks resources.postgres.instances.dev.version: 17"
commit "postgres: dev to 17"
apply_addons dev
if out=$(tmo 1500 $cplat resource upgrade postgres --verify --env dev --repo-dir "$gitops_repo" --context "$ctx" --component-dir upg-api="$work/upg-api-failing" 2>&1 | tee /dev/stderr); then rc=0; else rc=$?; fi
[ "$rc" = 1 ] || fail "the verification with a failing smoke recipe exited $rc, expected 1"
grep -F -q "NOT VERIFIED" <<< "$out" && grep -w -q "dev" <<< "$out" && grep -F -q "smoke upg-api" <<< "$out" || fail "the failed verification does not name dev and smoke upg-api"
grep -F -q "last successful backup: $(last_success dev)" <<< "$out" || fail "the failed verification does not name the last backup time $(last_success dev)"
grep -F -q "/resource:restore postgres --env dev" <<< "$out" || fail "the failed verification does not name /resource:restore postgres --env dev"
echo "ok   dev: NOT VERIFIED with FAIL forced named (smoke upg-api, the last backup, the way back)"

if out=$($cplat resource upgrade postgres --to 17 --env staging --repo-dir "$gitops_repo" --context "$ctx" 2>&1); then rc=0; else rc=$?; fi
echo "$out" >&2
[ "$rc" = 1 ] || fail "resource upgrade postgres --to 17 --env staging after dev's failed verification exited $rc, expected 1"
grep -w -q "dev" <<< "$out" && grep -F -i -q "failed its verification" <<< "$out" || fail "the staging refusal does not name dev and 'failed its verification'"
[ -z "$(gitops_dirty)" ] || fail "the refused staging step left changes in the tree"
for e in staging prod; do
  [ "$(cfield $e '{.status.pgDataImageInfo.majorVersion}')" = 16 ] || fail "$e reports pgDataImageInfo.majorVersion '$(cfield $e '{.status.pgDataImageInfo.majorVersion}')', expected 16"
  healthy "$e" || fail "the Postgres cluster of $e is not healthy after dev's failed verification"
  read_data "$e"
done
echo "ok   staging and prod stay on 16 and readable while dev failed its verification"

step "5 Majors: dev verified (the real repo), staging follows (after-dev-smoke), prod last and the entries fold"
take_backup staging   # fresh: the 60-minute rule must hold on a slow runner
if out=$(tmo 1500 $cplat resource upgrade postgres --verify --env dev --repo-dir "$gitops_repo" --context "$ctx" --component-dir upg-api="$work/upg-api" 2>&1 | tee /dev/stderr); then rc=0; else rc=$?; fi
[ "$rc" = 0 ] || fail "resource upgrade postgres --verify --env dev with the real repo exited $rc"
grep -w -q "verified" <<< "$out" || fail "dev's verification did not print 'verified'"
[ "$(system_get "d['resources']['postgres']['instances']['staging']['version']")" = 17 ] || fail "the verified dev step did not write instances.staging.version: 17 (promote: after-dev-smoke)"
commit "postgres: staging to 17"
apply_addons staging
$cplat resource upgrade postgres --verify --env staging --repo-dir "$gitops_repo" --context "$ctx" --component-dir upg-api="$work/upg-api" 2>&1 | tee /dev/stderr >/dev/null \
  || fail "resource upgrade --verify --env staging failed after the major step"
take_backup prod
cplat_run "resource upgrade postgres --to 17 --env prod" 300 $cplat resource upgrade postgres --to 17 --env prod --repo-dir "$gitops_repo" --context "$ctx" >/dev/null
system_get "d['resources']['postgres']['version']" | grep -x -q 17 || fail "system.yaml lacks resources.postgres.version: 17 after the last environment"
system_get "[k for v in (d['resources']['postgres'].get('instances') or {}).values() for k in (v or {}) if k == 'version']" | grep -x -F -q "[]" \
  || fail "per-environment version entries are left in instances after the last step (the entries must fold into version: 17)"
echo "ok   the entries folded: resources.postgres has version: 17 and no instances.*.version"
commit "postgres: prod to 17 (the entries fold)"
apply_addons prod
$cplat resource upgrade postgres --verify --env prod --repo-dir "$gitops_repo" --context "$ctx" --component-dir upg-api="$work/upg-api" 2>&1 | tee /dev/stderr >/dev/null \
  || fail "resource upgrade --verify --env prod failed after the major step"

# ---------------------------------------------------------------------------------------------------------------------------------
step "6 Checks: major, server_version, data, instance verify, doctor, status, CRDs, server-side dry runs"
want_minor=$(table_pin 17 | sed -n 's/^[^:]*:\([0-9][0-9.]*\).*/\1/p')   # 17.11 at the time of writing (design.md, Verified)
[ -n "$want_minor" ] || fail "cannot read the minor of the table's postgres 17 pin"
for e in dev staging prod; do
  [ "$(cfield $e '{.status.pgDataImageInfo.majorVersion}')" = 17 ] || fail "$e reports major '$(cfield $e '{.status.pgDataImageInfo.majorVersion}')', expected 17"
  dbq "$e" "show server_version"
  [ "${Q%% *}" = "$want_minor" ] || fail "server_version of $e is '$Q', expected $want_minor (the table's 17 pin, 17.11 at the time of writing)"
  read_data "$e"
  (cd "$api_repo" && $cplat instance verify "$e" --base-url "http://upg-api.upg-$e.localhost:$port" --no-retry) || fail "cplat instance verify $e failed"
  rec=$(kn "upg-$e" get configmaps/upg-postgres-upgrade -o jsonpath='{.data.state}' 2>/dev/null || true)
  [ "$rec" = verified ] || fail "the upgrade record configmaps/upg-postgres-upgrade of $e reads '$rec', expected verified"
done
echo "ok   every environment is on 17 ($want_minor), its data reads back, instance verify is green"

$cplat platform doctor --context "$ctx" --repo "$gitops_repo" --json > "$work/doctor.json" 2> "$work/doctor.err" || true
python3 - "$work/doctor.json" <<'PY' || fail "doctor --context: an operator row is not ok (see above)"
import json, sys
rows = [r for r in json.loads(open(sys.argv[1]).read()) if r.get("operator")]
if not rows:
    sys.exit("doctor printed no operator row")
bad = [r for r in rows if r["operator"]["state"] != "ok"]
for r in rows:
    print(f"  {r['operator']['state']:7} {r['name']}: {r['detail']}")
if bad:
    sys.exit(f"{len(bad)} operator row(s) with state != ok")
PY
echo "ok   platform doctor --context: every operator row is ok (installed = the table, every CRD serves the table's versions)"
$cplat system status --json --repo-dir "$gitops_repo" --context "$ctx" > "$work/status.json" 2> "$work/status.err" || fail "system status --json failed: $(tail -3 "$work/status.err")"
python3 - "$work/status.json" <<'PY' || fail "system status does not show upgrade.state verified for postgres in every environment (see above)"
import json, sys
d = json.loads(open(sys.argv[1]).read())
row = next(r for r in d["resource_versions"] if r["resource"] == "postgres")
for env in ("dev", "staging", "prod"):
    cell = row["cells"][env]
    print(f"  {env}: version {cell['version']} health {cell['health']} upgrade {cell['upgrade']}")
    if (cell.get("upgrade") or {}).get("state") != "verified" or str(cell["version"]) != "17":
        sys.exit(f"{env}: upgrade.state is not verified on 17")
PY
echo "ok   system status: upgrade.state verified on 17 in dev, staging and prod"
for crd in clusters.postgresql.cnpg.io backups.postgresql.cnpg.io objectstores.barmancloud.cnpg.io; do
  served=$(k get "customresourcedefinitions.apiextensions.k8s.io/$crd" -o jsonpath='{.spec.versions[?(@.served==true)].name}' 2>/dev/null || true)
  grep -w -q v1 <<< "$served" || fail "the CRD $crd serves '$served', expected v1"
done
echo "ok   the Postgres CRDs serve v1"
for e in dev staging prod; do
  for sub in addons overlays; do
    for d in "$app_dir/$sub/$e"/*/; do
      [ -f "${d}kustomization.yaml" ] || continue
      kubectl --context "$ctx" -n "upg-$e" apply --dry-run=server -k "$d" >/dev/null 2>"$work/dryrun.err" || fail "the API server refuses ${d#"$gitops_repo"/}: $(tail -3 "$work/dryrun.err")"
    done
  done
done
echo "ok   every rendered addon and overlay is accepted by the API server (AC-121.22)"

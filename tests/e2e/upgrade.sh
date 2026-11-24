#!/usr/bin/env bash
# Platform upgrade end-to-end test (spec 191, AC-191.6 and AC-191.7; the steps of spec 121, AC-121.24 and AC-121.25, with the cluster halves of
# AC-121.4, .5, .8, .11, .15, .16, .19, .21, .22): a system created by the previous release is updated to this checkout, in the order a person
# would do it. No GitHub, no GHCR, no Argo CD (WITH_ARGO=0): the rendered manifests are applied with kubectl, as tests/e2e/run.sh does.
#
# The update part (AC-191.6, the gate job `e2e upgrade (previous release -> candidate)`), always:
#   1. From      the previous release: $E2E_UPGRADE_FROM, else `scripts/release-check.py from-tag previous`.
#   2. Setup     lib/upgrade-system.sh builds the system with that release's own cplat and templates: `upg`, a python service `upg-api`
#                (dev, staging, prod; staging promotes after-dev-smoke), postgres 16 (+ a bucket, a cache and a broker when that release
#                supports the type); its local cluster (floating defaults), all three environments healthy; every floating reference is
#                resolved and recorded ($work/resolved-<tag>.txt); a row, an object, a cache key and a message per environment.
#   3. Update    this checkout's `cplat platform update`; the report lists dev's moved pin and the held pins of staging and prod; the
#                local cluster's operators move once; dev, then staging, then prod move to this release's Postgres 16 pin, each applied and
#                verified (`platform update --verify`, `resource upgrade --verify`).
#   4. Checks    the data of step 2 reads back unchanged, `cplat instance verify` (the smoke tests) of every instance, doctor (every operator
#                `ok`), every rendered manifest accepted by the API server. Prints UPGRADE E2E OK. It adds no backups and upgrades no major.
#
# The drill (AC-191.7), E2E_UPGRADE_DRILL=1: the update part from the previous release, then tests/e2e/upgrade-drill.sh (the backup guard and
# the Postgres 16 to 17 major upgrade with the forced failed verification of AC-121.25; ends with major 17 and the table's 17 minor in every
# environment, the data unchanged, upgrade state `verified`), then the same checks.
#
# Time budget: about 15 minutes for the update part (setup on the previous release 6, update and pin moves 7, checks 2), about 40 minutes for
# the drill (backups 5, the three major steps with the forced failure 12, more checks); the workflows give it 45 and 75. The pass that applies
# every environment and waits (setup) runs dev, staging and prod in parallel (for_envs, #400). The major-upgrade steps stay ordered. Each step
# prints how long it took.
#
# Needs: docker (running), k3d, kubectl, uv, curl, copier (or uv), git with the release tags. Env: E2E_UPGRADE_FROM=<tag>, E2E_UPGRADE_DRILL=1,
# E2E_KEEP=1 keeps the cluster, E2E_PORT, E2E_WORK, E2E_UPGRADE_SEQUENTIAL=1 applies the environments one after another (a runner short of
# CPU or memory).
set -euo pipefail

root=$(cd "$(dirname "$0")/../.." && pwd)
# shellcheck source=SCRIPTDIR/lib/probe.sh
. "$root/tests/e2e/lib/probe.sh"   # probe_run: probe pods with a component's own variables (#323)
# shellcheck source=SCRIPTDIR/lib/uv-cache.sh
. "$root/tests/e2e/lib/uv-cache.sh"   # a throwaway uv cache per script run (spec 208)
# shellcheck source=SCRIPTDIR/lib/docker-build.sh
. "$root/tests/e2e/lib/docker-build.sh"   # e2e_docker_build: docker build, retried once on a registry 429 (#1045)
work="${E2E_WORK:-$(mktemp -d)}"
e2e_uv_cache_start
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
      if kubectl --context "$ctx" -n "upg-$e" get statefulsets.apps/upg-sessions >/dev/null 2>&1; then   # a cache: who holds which password (hashes only)
        echo "--- cache upg-$e ---"
        for j in $(kubectl --context "$ctx" -n "upg-$e" get jobs.batch -o name 2>/dev/null | grep credentials); do   # the credentials Jobs (what they did, no values)
          echo "--- $j ---"; kubectl --context "$ctx" -n "upg-$e" logs "$j" --tail=15 2>&1
        done
        kubectl --context "$ctx" -n "upg-$e" get secret/upg-sessions-app \
          -o jsonpath='secret: created={.metadata.creationTimestamp} resourceVersion={.metadata.resourceVersion}{"\n"}' 2>&1
        kubectl --context "$ctx" -n "upg-$e" get pods/upg-sessions-0 \
          -o jsonpath='pod: started={.status.startTime} restarts={.status.containerStatuses[0].restartCount}{"\n"}' 2>&1
        echo "password hash: secret=$(kubectl --context "$ctx" -n "upg-$e" get secret/upg-sessions-app -o jsonpath='{.data.password}' 2>/dev/null | base64 -d | sha256sum | cut -c1-12)" \
             "url=$(kubectl --context "$ctx" -n "upg-$e" get secret/upg-sessions-app -o jsonpath='{.data.url}' 2>/dev/null | base64 -d | sed -E 's#^redis://[^:]*:([^@]*)@.*#\1#' | tr -d '\n' | sha256sum | cut -c1-12)" \
             "server=$(kubectl --context "$ctx" -n "upg-$e" exec upg-sessions-0 -- sh -c 'printf %s "$VALKEY_PASSWORD"' 2>/dev/null | sha256sum | cut -c1-12)"
      fi
    done
  ) >&2 || true
}
fail() { echo "UPGRADE E2E FAIL [$step_name]: $*" >&2; [ -n "${in_env:-}" ] || diagnose; exit 1; }   # in_env: inside for_envs, which diagnoses once

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
    if [ -s "$work/skipped.txt" ]; then   # #323: what this run did not exercise because the previous release lacked a type
      echo; echo "Skipped (the previous release lacks the resource type):"; sed 's/^/  skipped: /' "$work/skipped.txt"
    fi
    if [ "${E2E_UPGRADE_DRILL:-0}" = 1 ]; then limit=2700 lim_min=45 budget=40; else limit=1200 lim_min=20 budget=15; fi
    [ "$total" -le "$limit" ] || echo "WARNING: the run took more than $lim_min minutes in the log (budget: about $budget)"
    echo; echo "UPGRADE E2E OK"
  else
    echo; echo "UPGRADE E2E FAILED at step '$step_name' (work dir: $work)"
  fi
  e2e_uv_cache_end
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
FROM="${E2E_UPGRADE_FROM:-$(uv run "$root/scripts/release-check.py" from-tag previous)}"   # the rule lives in release-check.py (spec 191)
[ -n "$FROM" ] || fail "no previous release tag found (v5.0.*)"
echo "previous release: $FROM"
# shellcheck source=SCRIPTDIR/lib/upgrade-system.sh
. "$root/tests/e2e/lib/upgrade-system.sh"   # upg_types, upg_needs_type, upg_create, upg_update: the system builder, no cluster
needs_type() { upg_needs_type "$work" "$@"; }   # type step: FROM_TYPES has the type; else "skipped: <step>" once (#323)

# ---------------------------------------------------------------------------------------------------------------------------------
step "2 Setup on $FROM: system upg, python service upg-api, postgres 16, its local cluster with the floating defaults"
upg_create "$FROM" "$work" "$port" "$registry:$regport" || fail "creating the system on $FROM (lib/upgrade-system.sh) failed"
for e in dev staging prod; do echo "$e=$(image_name_of $e)"; done > "$work/pins-before.txt"
echo "database references of $FROM:"; cat "$work/pins-before.txt"

step "2 Setup on $FROM: the local cluster, with the floating defaults of that release (no version variables)"
(cd "$gitops_repo" && LOCAL_CLUSTER=$cluster LOCAL_HTTP_PORT=$port WITH_ARGO=0 REGISTRY_PORT=$regport bash scripts/local-cluster.sh up 2>&1 | tee /dev/stderr >/dev/null) \
  || fail "local-cluster.sh up (previous release) failed"
k get nodes >/dev/null || fail "the cluster $ctx is not reachable"

step "2 Setup on $FROM: build and push upg-api"
(cd "$api_repo" && uv lock -q) || fail "uv lock in upg-api failed"      # --skip-tasks left no uv.lock and the Dockerfile needs it
e2e_docker_build -q -t "localhost:$regport/upg-api:latest" "$api_repo" >/dev/null || fail "docker build upg-api failed"
docker push -q "localhost:$regport/upg-api:latest" >/dev/null || fail "docker push upg-api failed"

# ---- probes: plain Pods that carry upg-api's own variables, as the component sees them ----
S3_IMAGE=amazon/aws-cli:2.22.35
NATS_IMAGE=natsio/nats-box:0.14.5
# every probe gets these too (the AWS CLI reads them; the other images ignore them)
probe_env=(-e HOME=/tmp -e AWS_PAGER= -e AWS_EC2_METADATA_DISABLED=true -e AWS_REQUEST_CHECKSUM_CALCULATION=when_required
           -e AWS_RESPONSE_CHECKSUM_VALIDATION=when_required)
P_OUT=""
podrun() { # env image env-regex script: output in P_OUT, success when the pod Succeeded
  local rc=0   # up to 270 s (the first run pulls the image); FILES_S3_* and FILES_AWS_* reach the script as S3_* and AWS_*
  probe_run -k "kn upg-$1" -d upg-api -i "$2" -m "$3" -p FILES_ -l upgprobe -w 90:3 -F fail "${probe_env[@]}" "$4" || rc=$?
  P_OUT=$PROBE_OUT
  return $rc
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
# the bucket files: bare S3_*/AWS_* while upg-api uses one bucket, FILES_S3_*/FILES_AWS_* once step 4 adds the bucket backups (AC-115.8);
# podrun gives the prefixed ones the bare names (probe_run -p FILES_)
s3pre='set -e; [ "$S3_FORCE_PATH_STYLE" = true ] && aws configure set default.s3.addressing_style path; A="aws --endpoint-url $S3_ENDPOINT"; '
natspre='N="nats --server $NATS_URL --user $NATS_USER --password $NATS_PASSWORD --inbox-prefix $NATS_INBOX_PREFIX"; '   # replies only in the component's own inbox

write_data() { # env: a row, an object, a cache key and a message (only for the types that release supports)
  dbq "$1" "create table if not exists upg_check (id int primary key, tag text); insert into upg_check values (1, '$1-before') on conflict do nothing"
  if needs_type bucket "bucket write in $1"; then
    podmust "bucket write in $1" "$1" "$S3_IMAGE" '^(FILES_)?(S3|AWS)_' "$s3pre"'printf %s '"$1-before"' > /tmp/in; $A s3api put-object --bucket "$S3_BUCKET" --key upg/'"$1"'.txt --body /tmp/in >/dev/null'
  fi
  if needs_type cache "cache write in $1"; then
    # with the server's own password: an instance of the previous release that is already in the #316 state cannot fail the setup; the
    # component's way in (REDIS_URL, REDIS_HOST/PORT/PASSWORD) is checked after the update
    kn "upg-$1" exec upg-sessions-0 -- sh -c 'valkey-cli -a "$VALKEY_PASSWORD" --no-auth-warning SET upg:'"$1 $1-before" | grep -w OK >/dev/null \
      || fail "cache write in $1 (with the server's own password) failed"
  fi
  if needs_type broker "stream message in $1"; then
    podmust "stream message in $1" "$1" "$NATS_IMAGE" '^(NATS|EVENTS)_' "$natspre"'$N pub "$EVENTS_ORDERS_SUBJECT_PREFIX.created" '"$1-before"
  fi
}
read_data() { # env: the data of write_data reads back unchanged (the cache key is not required)
  dbq "$1" "select tag from upg_check where id = 1"
  [ "$Q" = "$1-before" ] || fail "the row of $1 reads '$Q', expected '$1-before'"
  if needs_type bucket "bucket read in $1"; then
    podmust "bucket read in $1" "$1" "$S3_IMAGE" '^(FILES_)?(S3|AWS)_' "$s3pre"'$A s3api get-object --bucket "$S3_BUCKET" --key upg/'"$1"'.txt /tmp/out >/dev/null; echo "CONTENT=$(cat /tmp/out)"'
    grep -w -F -q "CONTENT=$1-before" <<< "$P_OUT" || fail "the object upg/$1.txt of $1 does not read $1-before: $P_OUT"
  fi
  if needs_type broker "stream message read in $1"; then
    podmust "stream message read in $1" "$1" "$NATS_IMAGE" '^(NATS|EVENTS)_' "$natspre"'$N consumer next "$EVENTS_ORDERS_STREAM" "$EVENTS_ORDERS_CONSUMER" --count 1 --no-ack'
    grep -w -F -q "$1-before" <<< "$P_OUT" || fail "the message of $1 is gone from the stream: $P_OUT"
  fi
  echo "ok   $1: the data of step 2 reads back unchanged"
}

# ---- apply what the renderer wrote (what Argo CD would sync) ----
# What Argo CD does for a directory with credentials-job.yaml (spec 128): the five credentials-*.yaml (the PreSync hook objects) are
# applied first and the Job runs to completion (it writes every password Secret once, create if absent), then the whole directory is
# applied. A directory of the previous release's render has none of them and is applied as before. A forced write (rerun_credentials)
# runs the Job again; the checks compare the Secret's resourceVersion and value hashes before and after. No server is restarted here.
hash_of() { if command -v sha256sum >/dev/null 2>&1; then sha256sum; else shasum -a 256; fi | cut -d' ' -f1; }
credentials_files() { local f; for f in serviceaccount role rolebinding configmap job; do echo "$1/credentials-$f.yaml"; done; }
credentials_apply() { # namespace dir: applies the five credentials-*.yaml and waits for the Job (its logs on failure)
  local ns_=$1 d=$2 args=() f out job
  for f in $(credentials_files "$d"); do [ -f "$f" ] || fail "render did not write $f"; args+=(-f "$f"); done
  # like Argo CD's hook-delete-policy BeforeHookCreation: the Job runs on every sync, also when its name is unchanged (a previous
  # release that already rendered it, 5.5.0 on); without this an existing Job stays "unchanged" and nothing repairs #316 (AC-128.10)
  job=$(awk '/^metadata:/{m=1} m && /^  name: /{print $2; exit}' "$d/credentials-job.yaml")
  [ -n "$job" ] || fail "$d/credentials-job.yaml names no Job"
  kn "$ns_" delete job "$job" --ignore-not-found --wait=true >/dev/null || fail "could not delete the credentials Job $job before its run"
  out=$(kn "$ns_" apply "${args[@]}" -o name) || fail "applying the credentials-*.yaml of $d failed"
  job=$(sed -n 's#^job.batch/##p' <<< "$out" | head -1)
  [ -n "$job" ] || fail "$d/credentials-job.yaml did not apply a Job"
  kn "$ns_" wait --for=condition=complete job/$job --timeout=180s >/dev/null || {
    kn "$ns_" logs job/$job --tail=40 || true; kn "$ns_" describe job/$job | tail -20; fail "the credentials Job $job in $ns_ did not complete"; }
  CRED_JOB=$job
}
rerun_credentials() { # namespace dir: a forced write (AC-128.3): delete the finished Job and apply its five files again
  local job
  credentials_apply "$1" "$2"; job=$CRED_JOB
  kn "$1" delete job "$job" --ignore-not-found --wait=true >/dev/null || fail "could not delete the credentials Job $job"
  credentials_apply "$1" "$2"
}
secret_rv() { kn "$1" get secret "$2" -o jsonpath='{.metadata.resourceVersion}'; }   # namespace secret
secret_hash() { kn "$1" get secret "$2" -o jsonpath='{.data}' | hash_of; }              # the hash of all values; no value is printed

# the Secrets the new render plans for an environment (plan.json of every credentials ConfigMap under addons or overlays), their hashes
# recorded when the new render is applied there for the first time, and compared after it
new_render() { ls "$app_dir/$2/$1"/*/credentials-job.yaml >/dev/null 2>&1; }   # env addons|overlays
plan_secrets() {
  yaml_py - "$app_dir/$2/$1" <<'PY'
import glob, json, sys, yaml
for path in sorted(glob.glob(sys.argv[1] + "/*/credentials-configmap.yaml")):
    for s in json.loads(yaml.safe_load(open(path))["data"]["plan.json"])["secrets"]:
        print(s["name"])
PY
}
record_hashes() { # env addons|overlays: before the new render is applied (not right after forcing, and nothing waits for a Secret)
  local s h
  new_render "$1" "$2" && [ ! -f "$work/hashes-$1-$2" ] || return 0
  : > "$work/hashes-$1-$2"
  for s in $(plan_secrets "$1" "$2"); do
    h=$(secret_hash "upg-$1" "$s" 2>/dev/null) || continue   # a Secret that does not exist yet has no hash to keep
    echo "$s $h" >> "$work/hashes-$1-$2"
  done
}
check_kept() { # env addons|overlays: every existing Secret has the value hashes it had before the new render (AC-128.9)
  local s h
  [ -f "$work/hashes-$1-$2" ] && [ ! -f "$work/kept-$1-$2" ] || return 0
  while read -r s h; do
    [ "$(secret_hash "upg-$1" "$s")" = "$h" ] || fail "AC-128.9: the Secret $s in upg-$1 changed its values when the new render was applied"
  done < "$work/hashes-$1-$2"
  echo "ok   $1 $2: $(wc -l < "$work/hashes-$1-$2" | tr -d ' ') Secrets keep their values (AC-128.9)"
  touch "$work/kept-$1-$2"
}
within() { # seconds what command...: tries again until it works; an attempt may start up to that many seconds after the first
  local secs=$1 what=$2 end; shift 2; end=$((SECONDS + secs))
  until "$@"; do
    [ $SECONDS -lt $end ] || fail "$what: not within ${secs}s ($(echo "$P_OUT" | tail -4 | tr '\n' ' ' | cut -c1-400))"
    sleep 3
  done
}
cache_probe='u=$(printf %s "$REDIS_URL" | sed "s#^redis://:#redis://default:#"); a=$(valkey-cli -u "$u" --no-auth-warning PING 2>&1); b=$(valkey-cli -h "$REDIS_HOST" -p "$REDIS_PORT" --user default -a "$REDIS_PASSWORD" --no-auth-warning PING 2>&1); w=$(valkey-cli -h "$REDIS_HOST" -p "$REDIS_PORT" --user default -a "wrong-$REDIS_PASSWORD" --no-auth-warning PING 2>&1); echo "URL=$a HOST=$b WRONG=$w"; [ "$a" = PONG ] && [ "$b" = PONG ] && case "$w" in *WRONGPASS*) ;; *) exit 1;; esac'
nats_probe='nats --server "$NATS_URL" --user "$NATS_USER" --password "$NATS_PASSWORD" rtt || exit 1; w=$(nats --server "$NATS_URL" --user "$NATS_USER" --password "wrong-$NATS_PASSWORD" rtt 2>&1); echo "WRONG=$w"; case "$w" in *uthorization*|*uthentication*) ;; *) exit 1;; esac'
cache_ok() { # env: fresh probe pod with the component's REDIS_* variables
  local img; img=$(kn "upg-$1" get statefulsets.apps/upg-sessions -o jsonpath='{.spec.template.spec.containers[0].image}')
  podrun "$1" "$img" '^REDIS_' "$cache_probe"
}
nack_ready() { # env: NACK 0.24 sets no status on an Account; every stream is Ready only when NACK logged in as _nack with the Secret's password
  local st; st=$(kn "upg-$1" get streams.jetstream.nats.io -o jsonpath='{range .items[*]}{.status.conditions[?(@.type=="Ready")].status}{"\n"}{end}' 2>/dev/null)
  [ -n "$st" ] && ! grep -qv '^True$' <<< "$st"
}
check_servers() { # env: once, after the new render of the addons is applied: the servers accept the Secrets' passwords (AC-128.10, AC-128.1/.2/.4)
  local e=$1 dir rv h
  [ ! -f "$work/servers-$e" ] || return 0
  new_render "$e" addons || return 0
  if needs_type cache "the cache's password checks in $e (AC-128.1, AC-128.2, AC-128.3, AC-128.10)"; then
    # AC-128.1 and AC-128.2: the server accepts the Secret's password and refuses another; the component's REDIS_URL and its
    # REDIS_HOST/PORT/PASSWORD get PONG (a WRONGPASS here fails); a server in the #316 state is repaired within 60 s (AC-128.10)
    within 60 "AC-128.1/.2/.10: the cache of $e answers PONG to the component's variables" cache_ok "$e"
    echo "ok   $e: the cache accepts the Secret's password and refuses another; REDIS_URL and REDIS_HOST/PORT/PASSWORD get PONG (AC-128.1, AC-128.2)"
    if mkdir "$work/forced-write" 2>/dev/null; then   # AC-128.3: one more write of a cache's Secret, once (mkdir: atomic under for_envs)
      dir="$app_dir/addons/$e/sessions"; rv=$(secret_rv "upg-$e" upg-sessions-app); h=$(secret_hash "upg-$e" upg-sessions-app)
      rerun_credentials "upg-$e" "$dir"
      [ "$(secret_rv "upg-$e" upg-sessions-app)" = "$rv" ] && [ "$(secret_hash "upg-$e" upg-sessions-app)" = "$h" ] \
        || fail "AC-128.3: the Secret upg-sessions-app of $e was written again by a second credentials Job run"
      podmust "AC-128.3 cache after a forced write in $e" "$e" "$(kn "upg-$e" get statefulsets.apps/upg-sessions -o jsonpath='{.spec.template.spec.containers[0].image}')" '^REDIS_' "$cache_probe"
      echo "ok   $e: a forced write left resourceVersion and hash of upg-sessions-app unchanged and the server accepts the password (AC-128.3)"
    fi
  fi
  if needs_type broker "the broker's password checks in $e (AC-128.4, AC-128.10)"; then
    # AC-128.4: the component user authenticates with the password of its Secret and no other; _nack's Account is Ready
    within 60 "AC-128.4/.10: upg-api's NATS_USER authenticates in $e" podrun "$e" "$NATS_IMAGE" '^(NATS|EVENTS)_' "$nats_probe"
    within 60 "AC-128.4: NACK (_nack) has every stream of $e Ready" nack_ready "$e"
    echo "ok   $e: the component user authenticates (a wrong password is refused) and _nack's Account is Ready (AC-128.4)"
  fi
  touch "$work/servers-$e"
}
force_password() { # env secret: the server keeps its password, the Secret gets a new one (password and url); no value is printed
  kn "upg-$1" get "secret/$2" -o json | python3 -c '
import base64, json, secrets, string, sys
d = json.load(sys.stdin)["data"]
old = base64.b64decode(d["password"]).decode()
new = "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(32))
enc = lambda t: base64.b64encode(t.encode()).decode()
out = {"password": enc(new)}
if "url" in d:
    out["url"] = enc(base64.b64decode(d["url"]).decode().replace(old, new))
print(json.dumps({"data": out}))' > "$work/force.json" || fail "could not prepare the new password of $2 in $1"
  kn "upg-$1" patch "secret/$2" --type merge --patch-file "$work/force.json" >/dev/null || fail "could not patch $2 in $1"
  rm -f "$work/force.json"
}
restart_component() { # env: a new pod of upg-api (a component, not a server): in #316 the components start after the rewrite and hold the Secret's value
  kn "upg-$1" patch deployments.apps/upg-api -p "{\"spec\":{\"template\":{\"metadata\":{\"annotations\":{\"e2e.upgrade/restarted-at\":\"$(date +%s)\"}}}}}" >/dev/null \
    || fail "could not start new upg-api pods in $1"
  kn "upg-$1" rollout status deployments.apps/upg-api --timeout=300s >/dev/null 2>&1 || echo "note: upg-api in $1 is not ready with the forced Secret (the update must repair it)"
}

apply_bucket() { # env bucket: the key generators and the ExternalSecret first, then the store, the bucket and the identity, then the credentials
  local e=$1 b=$2 d="$app_dir/addons/$1/$2" f kk
  for f in seaweed.yaml bucket.yaml identity.yaml credentials.yaml kustomization.yaml; do
    [ -f "$d/$f" ] || fail "render did not write addons/$e/$b/$f"
  done
  if [ -f "$d/credentials-job.yaml" ]; then credentials_apply "upg-$e" "$d"   # the keys, written once
  else   # the previous release: the generators and the ExternalSecret
    for f in access-key-generator.yaml secret-key-generator.yaml externalsecret.yaml; do [ -f "$d/$f" ] || fail "render did not write addons/$e/$b/$f"; done
    kn "upg-$e" apply -f "$d/access-key-generator.yaml" -f "$d/secret-key-generator.yaml" -f "$d/externalsecret.yaml" >/dev/null || fail "applying the key generators of $b in $e failed"
  fi
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
    elif ((d.get("metadata") or {}).get("annotations") or {}).get("argocd.argoproj.io/hook"):
        continue   # the credentials objects: the script applies them from their files and waits for the Job
    else:
        first.append(d)
first.sort(key=lambda d: d["kind"] != "Password")   # generators before the ExternalSecrets that use them
if not chart:
    sys.exit("no Application (the NATS server) in the addon")
for name, items in (("1.yaml", first), ("chart.yaml", chart), ("2.yaml", second)):
    open(f"{out}/{name}", "w").write(yaml.safe_dump_all(items))
PY
  kn "upg-$e" kustomize "$d" | yaml_py -c "$py" "$out" "$e" || fail "could not turn addons/$e/$b into objects to apply"
  if [ -f "$d/credentials-job.yaml" ]; then credentials_apply "upg-$e" "$d"; fi   # the Secrets of the broker, written once
  [ ! -s "$out/1.yaml" ] || kn "upg-$e" apply -f "$out/1.yaml" >/dev/null || fail "applying the Secrets of $b in $e failed"
  k apply -f "$out/chart.yaml" >/dev/null || fail "applying the HelmChart of $b in $e failed"
  wait_for 180 "the StatefulSet upg-$b of $e" kn "upg-$e" get statefulsets.apps "upg-$b"
  kn "upg-$e" rollout status "statefulsets.apps/upg-$b" --timeout=240s >/dev/null || fail "the NATS server upg-$b of $e did not become ready"
  wait_for 180 "the objects of $b in $e (NACK)" kn "upg-$e" apply -f "$out/2.yaml"
}
apply_addons() { # env: every rendered addon of the environment
  local e=$1 d="$app_dir/addons/$1" a
  record_hashes "$e" addons
  for a in $(ls "$d"); do
    [ -f "$d/$a/kustomization.yaml" ] || continue
    if [ -f "$d/$a/bucket.yaml" ]; then apply_bucket "$e" "$a"
    elif [ -f "$d/$a/server.yaml" ]; then apply_bus "$e" "$a"   # a broker: its server is an Argo CD Application (no Argo CD here)
    else
      if [ -f "$d/$a/credentials-job.yaml" ]; then credentials_apply "upg-$e" "$d/$a"; fi
      for g in "$d/$a"/*generator*.yaml; do   # generators before the ExternalSecrets that use them: ESO generates exactly once
        [ -f "$g" ] && { kn "upg-$e" apply -f "$g" >/dev/null || fail "applying $(basename "$g") of addons/$e/$a failed"; }
      done
      kn "upg-$e" apply -k "$d/$a" 2>&1 | tee /dev/stderr >/dev/null || fail "applying addons/$e/$a failed"
    fi
  done
  check_kept "$e" addons
  # the probe pods copy the component's Deployment: before apply_api created it (the setup on a release that already
  # renders credentials Jobs, 5.5.0 on), apply_api checks the servers after its rollout instead
  if kn "upg-$e" get deployments.apps/upg-api >/dev/null 2>&1; then check_servers "$e"; fi
}
apply_api() { # env: the overlay, then wait for the rollout and the answer through the Gateway
  local e=$1 out=""
  record_hashes "$e" overlays
  if [ -f "$app_dir/overlays/$e/upg-api/credentials-job.yaml" ]; then credentials_apply "upg-$e" "$app_dir/overlays/$e/upg-api"; fi
  kn "upg-$e" apply -k "$app_dir/overlays/$e/upg-api" 2>&1 | tee /dev/stderr >/dev/null || fail "applying overlays/$e/upg-api failed"
  check_kept "$e" overlays
  kn "upg-$e" rollout status deployments.apps/upg-api --timeout=300s 2>&1 | tee /dev/stderr >/dev/null || fail "upg-api did not become ready in $e (waited 300s)"
  check_servers "$e"   # once per environment; a no-op when apply_addons already checked
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
# for_envs FUNCTION: runs FUNCTION dev, staging and prod at once (#400: about 13 of the 35 minutes were these passes one after another),
# each in a background subshell whose lines carry "[env] " and are kept in $work/<FUNCTION>-<env>.log; waits for all three (on their
# PIDs) and fails naming every environment that failed, with its failure lines and the end of its log, then the diagnostics once.
# E2E_UPGRADE_SEQUENTIAL=1 runs them one after another as before (a runner short of CPU or memory). The environments share nothing but
# the cluster: their state files in $work are per environment, the one shared marker (forced-write) is taken with mkdir, and the probe
# pods of each call get their own number range so a later probe never reuses the name of one still terminating.
for_envs_n=0
for_envs() {
  local fn=$1 e i rc failed="" pids=() envs=(dev staging prod) t0=$SECONDS
  if [ "${E2E_UPGRADE_SEQUENTIAL:-0}" = 1 ]; then
    echo "E2E_UPGRADE_SEQUENTIAL=1: $fn for dev, staging and prod one after another"
    for e in "${envs[@]}"; do "$fn" "$e"; done
    return 0
  fi
  for_envs_n=$((for_envs_n + 1))
  echo "$fn: dev, staging and prod in parallel (E2E_UPGRADE_SEQUENTIAL=1 runs them one after another); lines start with [env]"
  for e in "${envs[@]}"; do
    (
      # a pipeline: with pipefail its status is the function's; the log keeps the lines without the prefix
      { in_env=$e; step_name="$step_name [$e]"; probe_n=$((1000000 + for_envs_n * 10000)); "$fn" "$e"; } 2>&1 \
        | tee "$work/$fn-$e.log" | awk -v p="[$e] " '{ print p $0; fflush() }'
    ) &
    pids+=($!)
  done
  for i in 0 1 2; do
    rc=0; wait "${pids[$i]}" || rc=$?
    if [ $rc -eq 0 ]; then echo "ok   ${envs[$i]}: $fn done ($((SECONDS - t0)) s since the start of the three)"
    else echo "FAIL ${envs[$i]}: $fn exited $rc after $((SECONDS - t0)) s" >&2; failed="$failed ${envs[$i]}"; fi
  done
  [ -n "$failed" ] || return 0
  for e in $failed; do
    {
      echo "--- $e: what failed ---"; grep -F "UPGRADE E2E FAIL" "$work/$fn-$e.log" || echo "(no failure line; exit status only)"
      echo "--- $e: the last 60 lines of $work/$fn-$e.log ---"; tail -60 "$work/$fn-$e.log"
    } >&2
  done
  fail "$fn failed in:$failed (logs: $work/$fn-<env>.log)"
}

step "2 Setup on $FROM: apply dev, staging and prod in parallel and wait until each is healthy"
for_envs apply_env

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

step "2 Setup on $FROM: force the state of #316 (the server runs with another password than its Secret holds) in staging's cache and prod's broker"
if needs_type cache "force the #316 state in staging's cache"; then
  force_password staging upg-sessions-app
  [ "$(kn upg-staging get secret/upg-sessions-app -o jsonpath='{.data.password}' | base64 -d | hash_of)" != "$(kn upg-staging exec upg-sessions-0 -- sh -c 'printf %s "$VALKEY_PASSWORD"' | hash_of)" ] \
    || fail "staging's cache still runs with the password of its Secret after the forced change"
  restart_component staging
fi
if needs_type broker "force the #316 state in prod's broker"; then
  force_password prod upg-bus-upg-api-app
  restart_component prod
fi

# ---------------------------------------------------------------------------------------------------------------------------------
step "3 Update: this checkout's cplat platform update, merged"
upg_update "$work" || fail "the update of the system (lib/upgrade-system.sh) failed"   # platform update, merged, rendered, committed; a candidate equal to $FROM leaves nothing to update
table16=$(table_pin 16)
moves=1   # the pin-move steps need a release whose versions table moves postgres 16 (5.3.0 -> 5.4.0 did; 5.4.0 -> 5.5.0 does not)
[ "$(sed -n 's/^dev=//p' "$work/pins-before.txt")" != "$table16" ] || moves=0
if [ $moves = 0 ]; then
  echo "postgres 16 is pinned to $table16 in $FROM and in this checkout: no pin moves; the pin-move checks are skipped"
  ! grep -E -q '^[[:space:]]*(dev|staging|prod)[[:space:]]+postgres 16: .*moves now' "$work/update.out" \
    || fail "the update report says postgres 16 moves, but $FROM and this checkout pin the same reference"
  for e in dev staging prod; do
    want=$(sed -n "s/^$e=//p" "$work/pins-before.txt")
    [ "$(image_name_of $e)" = "$want" ] || fail "$e's imageName moved to '$(image_name_of $e)' although the versions table did not"
  done
  echo "ok   the report announces no pin move and every environment keeps $FROM's reference"
else
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
[ "$(image_name_of dev)" = "$table16" ] || fail "dev's imageName is '$(image_name_of dev)', the table's postgres 16 is '$table16'"
for e in staging prod; do
  want=$(sed -n "s/^$e=//p" "$work/pins-before.txt")
  [ "$(image_name_of $e)" = "$want" ] || fail "$e's imageName moved to '$(image_name_of $e)'; it must keep '$want' (held pin) until /resource:upgrade postgres --to 16 --env $e"
done
echo "ok   dev's imageName is the table's 16 pin; staging and prod keep $FROM's reference (AC-121.11)"
fi

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
[ $moves = 0 ] || grep -w -q "verified" "$verify_out" || fail "platform update --verify did not print 'verified' for postgres in dev"
echo "ok   platform update --verify: operators at the table's versions, dev verified, smoke of every environment passed"

step "3 Update: staging and prod move to this release's Postgres 16 pin, one at a time (AC-121.11)"
if [ $moves = 0 ]; then
  echo "no pin moves between $FROM and this checkout: nothing to move in staging and prod"
  [ -z "$(gitops_dirty)" ] || fail "platform update --verify changed the gitops repo although no pin moves: $(gitops_dirty)"
  apply_addons staging   # this release's render: the credentials Jobs keep the Secrets and repair a forced server (AC-128.9, AC-128.10)
  apply_addons prod
  for e in dev staging prod; do read_data "$e"; done
else
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
fi

# ---------------------------------------------------------------------------------------------------------------------------------
# The drill (AC-191.7): the guard, the 16 -> 17 major upgrade with the forced failed verification (AC-121.25) and its checks of 17.
if [ "${E2E_UPGRADE_DRILL:-0}" = 1 ]; then
  # shellcheck source=SCRIPTDIR/upgrade-drill.sh
  . "$root/tests/e2e/upgrade-drill.sh"
fi

final_checks() { # the data reads back, every instance verifies, every operator is ok, the API server accepts every manifest (AC-191.6)
for e in dev staging prod; do
  read_data "$e"
  (cd "$api_repo" && $cplat instance verify "$e" --base-url "http://upg-api.upg-$e.localhost:$port" --no-retry) || fail "cplat instance verify $e failed"
done
echo "ok   every environment's data reads back and instance verify is green"
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
for e in dev staging prod; do
  for sub in addons overlays; do
    for d in "$app_dir/$sub/$e"/*/; do
      [ -f "${d}kustomization.yaml" ] || continue
      if [ -f "${d}server.yaml" ]; then   # a broker: its server is an Argo CD Application (no Argo CD here, apply_bus installs it as a HelmChart)
        kubectl --context "$ctx" -n "upg-$e" kustomize "$d" \
          | yaml_py -c 'import sys, yaml; print(yaml.safe_dump_all([d for d in yaml.safe_load_all(sys.stdin) if d and d["kind"] != "Application"]))' \
          | kubectl --context "$ctx" -n "upg-$e" apply --dry-run=server -f - >/dev/null 2>"$work/dryrun.err" \
          || fail "the API server refuses ${d#"$gitops_repo"/} (without its Application): $(tail -3 "$work/dryrun.err")"
        continue
      fi
      kubectl --context "$ctx" -n "upg-$e" apply --dry-run=server -k "$d" >/dev/null 2>"$work/dryrun.err" || fail "the API server refuses ${d#"$gitops_repo"/}: $(tail -3 "$work/dryrun.err")"
    done
  done
done
echo "ok   every rendered addon and overlay is accepted by the API server (AC-121.22)"
}

step "4 Checks: the data, instance verify, doctor, server-side dry runs"
final_checks

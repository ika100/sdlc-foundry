# shellcheck shell=bash
# Probe pods for the e2e scripts (#323), sourced by tests/e2e/run.sh and tests/e2e/upgrade.sh.
#
# A probe pod is a plain Pod (not a Deployment: the guard rails do not cover it) that carries a component's own variables, as the
# component sees them, and runs one script. It copies Secret references and plain values alike (EVENTS_<API>_* are plain), and it
# resolves prefixed names: with `-p FILES_`, FILES_S3_BUCKET reaches the script as S3_BUCKET (a component that uses two resources of a
# type gets prefixed variables). The script goes into the pod's command: Kubernetes turns "$$" into "$" there, so a script must not
# use "$$" (scripts/check-e2e-probes.py rejects it).
#
#   probe_run [options] SCRIPT      output in PROBE_OUT; returns 0 when the pod Succeeded
#     -k "CMD ARGS"   kubectl with context and namespace bound, as one word list (e.g. "kn upg-dev" or "kc")      required
#     -i IMAGE        the probe's image                                                                             required
#     -d DEPLOYMENT   copy the variables of this live Deployment (kubectl get -o json)
#     -f FILE         or: copy the variables of this JSON list of env entries
#     -m REGEX        copy only the variables whose names match (Python re.match); default: every variable
#     -p PREFIX       resolve prefixed names: PREFIX<NAME> is given as <NAME> and replaces a bare <NAME>
#     -e NAME=VALUE   one more plain variable (repeatable; after the copied ones)
#     -u UID          run as UID:UID, non-root, with a restricted security context (read-only root, no capabilities)
#     -c sh|python    the interpreter of SCRIPT (sh -c or python -c); default sh
#     -l LABEL        the pod's app label and name prefix; default probe
#     -w TRIES:SECS   how long to wait for the pod to finish; default 60:3
#     -F FUNC         call FUNC "could not start the probe pod NAME" when the pod cannot be created; default: return 2
#     -v              show the tail of `kubectl describe pod` when the pod did not succeed

PROBE_OUT=""
probe_n=0

read -r -d '' probe_pod_py <<'PY' || true
import json, re, sys
name, image, interp, script, regex, prefix, uid, label, envfile = sys.argv[1:10]
extra = sys.argv[10:]
if envfile:
    with open(envfile) as fh:
        env = json.load(fh)
else:
    env = json.loads(sys.stdin.read())["spec"]["template"]["spec"]["containers"][0].get("env", [])
env = [e for e in env if not regex or re.match(regex, e["name"])]   # Secret references and plain values alike
if prefix:
    resolved = {e["name"][len(prefix):] for e in env if e["name"].startswith(prefix)}
    env = [dict(e, name=e["name"][len(prefix):]) if e["name"].startswith(prefix) else e
           for e in env if e["name"].startswith(prefix) or e["name"] not in resolved]
for kv in extra:
    k, _, v = kv.partition("=")
    env.append({"name": k, "value": v})
container = {"name": "probe", "image": image, "command": [interp, "-c", script], "env": env}
spec = {"restartPolicy": "Never", "containers": [container]}
if uid:
    spec["securityContext"] = {"runAsNonRoot": True, "runAsUser": int(uid), "runAsGroup": int(uid), "seccompProfile": {"type": "RuntimeDefault"}}
    container["securityContext"] = {"allowPrivilegeEscalation": False, "readOnlyRootFilesystem": True, "capabilities": {"drop": ["ALL"]}}
print(json.dumps({"apiVersion": "v1", "kind": "Pod", "metadata": {"name": name, "labels": {"app": label}}, "spec": spec}))
PY

probe_run() {
  local k="" image="" dep="" envfile="" regex="" prefix="" uid="" interp=sh label=probe wait=60:3 failfn="" describe="" opt
  local -a extra=() kube=()
  local OPTIND=1
  while getopts 'k:i:d:f:m:p:e:u:c:l:w:F:v' opt; do
    case "$opt" in
      k) k=$OPTARG;; i) image=$OPTARG;; d) dep=$OPTARG;; f) envfile=$OPTARG;; m) regex=$OPTARG;; p) prefix=$OPTARG;;
      e) extra+=("$OPTARG");; u) uid=$OPTARG;; c) interp=$OPTARG;; l) label=$OPTARG;; w) wait=$OPTARG;; F) failfn=$OPTARG;;
      v) describe=1;;
      *) echo "probe_run: unknown option" >&2; return 2;;
    esac
  done
  shift $((OPTIND - 1))
  if [ $# != 1 ] || [ -z "$k" ] || [ -z "$image" ] || { [ -z "$dep" ] && [ -z "$envfile" ]; }; then
    echo "probe_run: needs -k, -i, -d or -f, and one script" >&2; return 2
  fi
  read -r -a kube <<< "$k"
  local script=$1 name phase="" tries=${wait%%:*} secs=${wait##*:} pod
  probe_n=$((probe_n + 1)); name="$label-$probe_n"
  if [ -n "$envfile" ]; then
    pod=$(python3 -c "$probe_pod_py" "$name" "$image" "$interp" "$script" "$regex" "$prefix" "$uid" "$label" "$envfile" ${extra[@]+"${extra[@]}"} < /dev/null)
  else
    pod=$("${kube[@]}" get deployments.apps "$dep" -o json | python3 -c "$probe_pod_py" "$name" "$image" "$interp" "$script" "$regex" "$prefix" "$uid" "$label" "" ${extra[@]+"${extra[@]}"})
  fi || pod=""
  if [ -z "$pod" ] || ! "${kube[@]}" apply -f - <<< "$pod" >/dev/null; then
    PROBE_OUT="could not start the probe pod $name"
    [ -z "$failfn" ] || "$failfn" "$PROBE_OUT"
    return 2
  fi
  for _ in $(seq 1 "$tries"); do
    phase=$("${kube[@]}" get "pods/$name" -o jsonpath='{.status.phase}' 2>/dev/null || true)
    case "$phase" in Succeeded|Failed) break;; esac; sleep "$secs"
  done
  PROBE_OUT=$("${kube[@]}" logs "pods/$name" 2>&1 || true)
  if [ "$phase" != Succeeded ]; then
    PROBE_OUT="$PROBE_OUT (pod phase: ${phase:-unknown}; $("${kube[@]}" get "pods/$name" -o jsonpath='{.status.containerStatuses[*].state.waiting.reason}' 2>/dev/null))"
    [ -z "$describe" ] || "${kube[@]}" describe "pods/$name" | tail -15
  fi
  "${kube[@]}" delete "pods/$name" --wait=false >/dev/null 2>&1 || true
  [ "$phase" = Succeeded ]
}

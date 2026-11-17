# shellcheck shell=bash
# The upgrade system builder (spec 191), shared by the upgrade render check and tests/e2e/upgrade.sh. It never starts a container or a cluster.
#
#   bash tests/e2e/lib/upgrade-system.sh create <tag> <work>   worktree <work>/from at <tag>; <work>/upg-gitops and <work>/upg-api, rendered and committed
#   bash tests/e2e/lib/upgrade-system.sh update <work>         this checkout's `platform update --skip-tasks`, merged into main, rendered, committed
#
# Sourced, it defines (paths are arguments; the only variables it sets are FROM_TYPES and UPG_NOTHING_CHANGED):
#   upg_types <from-dir>                          sets FROM_TYPES: the resource types that release supports (RESOURCE_TYPES minus PLANNED_TYPES, read with ast)
#   upg_needs_type <work> <type> <step>           returns 0 when FROM_TYPES has the type, else prints "skipped: <step> (...)" once and records it in <work>/skipped.txt
#   upg_create <tag> <work> [<port> [<registry>]] the system of the previous release: system `upg`, python service `upg-api` in dev, staging and prod
#                                                 (staging after-dev-smoke, generated upg-api-auth=JWT_KEY), postgres 16, and a bucket `files`, a cache
#                                                 `sessions` and a broker `bus` (api `orders`) where the release has the type; defaults 8098, k3d-upg-local-registry:5112
#   upg_update <work>                             writes <work>/update.out; sets UPG_NOTHING_CHANGED=1 when the update made no branch, else 0
# A failure returns non-zero (exits, in script mode) with the failing command's output on stderr; the last line names what failed.

_upg_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)

_upg_fail() { echo "upgrade-system: $*" >&2; return 1; }
_upg_run() { # what command...: runs it; on failure its whole output goes to stderr, then one line naming it
  local what=$1 out; shift
  out=$("$@" 2>&1) || { printf '%s\n' "$out" >&2; _upg_fail "$what failed"; return 1; }
}
_upg_commit() { # repo message
  (cd "$1" && git add -A && { git diff --cached --quiet || git -c user.name=e2e -c user.email=e2e@example.com commit -qm "$2"; })
}

upg_types() { # from-dir: sets FROM_TYPES
  FROM_TYPES=$(python3 - "$1" <<'PY'
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
  ) || { _upg_fail "reading the resource types of $1 failed"; return 1; }
}

upg_needs_type() { # work type step
  grep -w -q "$2" <<< "$FROM_TYPES" && return 0
  local why="$3 (previous release has no $2)"
  grep -qxF -- "$why" "$1/skipped.txt" || { echo "skipped: $why"; echo "$why" >> "$1/skipped.txt"; }
  return 1
}

upg_create() { # tag work [port] [registry]
  local tag=$1 work=$2 port=${3:-8098} registry=${4:-k3d-upg-local-registry:5112}
  local gitops_repo="$work/upg-gitops" from_cplat pair typ name
  mkdir -p "$work"
  (cd "$_upg_root" && git worktree add --detach "$work/from" "$tag") >/dev/null 2>&1 || { _upg_fail "git worktree add $work/from $tag failed"; return 1; }
  from_cplat="uv run $work/from/scripts/cplat/cplat.py"   # the previous release's own cplat and templates
  upg_types "$work/from" || return 1
  echo "$tag supports: $FROM_TYPES"
  : > "$work/skipped.txt"

  printf '%s\n' 'system: upg' 'owner: upg' 'components:' \
    '  - {name: upg-api, description: "upg api", type: service, lang: python}' > "$work/system.yml"
  _upg_run "system new (previous release)" $from_cplat system new "$work/system.yml" --no-github --skip-tasks --dir "$work" --org upg || return 1
  [ -f "$gitops_repo/applications/upg/system.yaml" ] || { _upg_fail "system new did not write applications/upg/system.yaml"; return 1; }
  git -C "$gitops_repo" config user.name e2e
  git -C "$gitops_repo" config user.email e2e@example.com

  _upg_run "resource add postgres --version 16" $from_cplat resource add postgres --version 16 --repo-dir "$gitops_repo" || return 1
  _upg_commit "$gitops_repo" "postgres 16" || { _upg_fail "commit postgres 16 failed"; return 1; }
  for pair in bucket:files cache:sessions broker:bus; do
    typ=${pair%%:*}; name=${pair##*:}
    if upg_needs_type "$work" "$typ" "resource add $name --type $typ, and every step that uses it"; then
      _upg_run "resource add $name --type $typ" $from_cplat resource add "$name" --type "$typ" --repo-dir "$gitops_repo" || return 1
      _upg_commit "$gitops_repo" "$name" || { _upg_fail "commit $name failed"; return 1; }
    fi
  done

  # environments, the component and its instances (one Python edit with the previous release's own modules, as /component:add does)
  _upg_run "describing the component and rendering (previous release)" \
    bash -c 'cd "$1" && FROM_TYPES="$2" uv run --with pyyaml --with ruamel.yaml python - "$3" "$4" "$5" && uv run scripts/render.py' \
    upg-edit "$gitops_repo" "$FROM_TYPES" "$work/from" "$port" "$registry" <<'PY' || return 1
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
ns.env, ns.secret, ns.secret_ref = [], [], []
ns.generate = ["upg-api-auth=JWT_KEY"]   # a generated component secret, so that the update covers it (AC-128.9)
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
  _upg_commit "$gitops_repo" "upg-api in dev, staging and prod" || { _upg_fail "commit of the component failed"; return 1; }
  [ -f "$gitops_repo/applications/upg/addons/dev/postgres/cluster.yaml" ] || { _upg_fail "render did not write addons/dev/postgres/cluster.yaml"; return 1; }
}

upg_update() { # work
  local work=$1 gitops_repo="$1/upg-gitops" main_branch upd_branch
  main_branch=$(git -C "$gitops_repo" symbolic-ref --short HEAD) || { _upg_fail "no branch in $gitops_repo"; return 1; }
  [ -z "$(cd "$gitops_repo" && git status --porcelain)" ] || { _upg_fail "the gitops repo is not clean before the update"; return 1; }
  if ! uv run "$_upg_root/scripts/cplat/cplat.py" platform update --repo "$gitops_repo" --skip-tasks > "$work/update.out" 2>&1; then
    cat "$work/update.out" >&2; _upg_fail "cplat platform update failed"; return 1
  fi
  cat "$work/update.out"
  upd_branch=$(git -C "$gitops_repo" symbolic-ref --short HEAD)
  if [ "$upd_branch" = "$main_branch" ] && grep -q 'already up to date with platform .* nothing changed' "$work/update.out"; then
    # A candidate whose templates equal the previous release leaves nothing to update: no branch is made, the render stays the same.
    UPG_NOTHING_CHANGED=1
    echo "ok   the candidate's templates equal the previous release: nothing to update, the repo stays on $main_branch"
  else
    UPG_NOTHING_CHANGED=0
    [ "$upd_branch" != "$main_branch" ] || { _upg_fail "platform update left the repo on $main_branch (it should have made a branch)"; return 1; }
    _upg_run "merging $upd_branch into $main_branch" bash -c 'git -C "$1" checkout -q "$2" && git -C "$1" merge -q --ff-only "$3"' upg-merge "$gitops_repo" "$main_branch" "$upd_branch" || return 1
  fi
  _upg_run "render.py of the updated repo" bash -c 'cd "$1" && uv run scripts/render.py' upg-render "$gitops_repo" || return 1
  _upg_commit "$gitops_repo" "render after the platform update" || { _upg_fail "commit after the update failed"; return 1; }
}

if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  set -euo pipefail
  export PATH="$PATH:$HOME/.local/bin"
  case "${1:-}" in
    create) [ $# -eq 3 ] || { echo "usage: upgrade-system.sh create <tag> <work>" >&2; exit 2; }; upg_create "$2" "$3" || exit 1 ;;
    update) [ $# -eq 2 ] || { echo "usage: upgrade-system.sh update <work>" >&2; exit 2; }; upg_update "$2" || exit 1 ;;
    *) echo "usage: upgrade-system.sh create <tag> <work> | update <work>" >&2; exit 2 ;;
  esac
fi

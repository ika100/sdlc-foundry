# shellcheck shell=bash
# The upgrade drill (spec 191, AC-191.7; the steps of spec 121, AC-121.25): sourced by tests/e2e/upgrade.sh when E2E_UPGRADE_DRILL=1, after its
# step 3 (the whole update part of AC-191.6, from the previous release) and before its final checks. It has no logic of its own to start:
# it uses the functions, variables and the cluster of upgrade.sh.
#
#   4 Guard    a bucket `backups` and `backup` on all three instances: `resource upgrade postgres --to 17` is refused without a recent
#              backup and changes nothing; then the backups run and every environment has a last_success.
#   5 Majors   dev goes to 17; a forced failing verification keeps staging and prod on 16 and readable; the real verification lets
#              staging follow; prod last, which folds the per-environment entries into `version: 17`.
#   6 Major    major 17 and server_version 17.11 (the table's 17 minor) everywhere, the upgrade record `verified`, system status
#              (upgrade.state verified), the Postgres CRDs. The data and the other checks follow in upgrade.sh.

system_get() { # python expression over `d`, the parsed system.yaml (yaml.safe_load)
  yaml_py - "$app_dir/system.yaml" "$1" <<'PY'
import sys, yaml
d = yaml.safe_load(open(sys.argv[1]))
print(eval(sys.argv[2]))
PY
}

# a copy of the service whose smoke recipe always fails (step 5: the forced failed verification)
rm -rf "$work/upg-api-failing"; cp -R "$api_repo" "$work/upg-api-failing"
python3 - "$work/upg-api-failing/devbox.json" <<'PY'
import json, sys
path = sys.argv[1]
d = json.load(open(path))
d["shell"]["scripts"]["smoke"] = "echo 'FAIL forced'; exit 1"
json.dump(d, open(path, "w"), indent=2)
PY

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

step "4 Guard: apply the backups in dev, staging and prod in parallel, take the first backup of every environment, wait for last_success"
for_envs apply_env
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
step "6 Major: 17 and its server_version in every environment, the upgrade record, system status, CRDs"
want_minor=$(table_pin 17 | sed -n 's/^[^:]*:\([0-9][0-9.]*\).*/\1/p')   # 17.11 at the time of writing (design.md, Verified)
[ -n "$want_minor" ] || fail "cannot read the minor of the table's postgres 17 pin"
for e in dev staging prod; do
  [ "$(cfield $e '{.status.pgDataImageInfo.majorVersion}')" = 17 ] || fail "$e reports major '$(cfield $e '{.status.pgDataImageInfo.majorVersion}')', expected 17"
  dbq "$e" "show server_version"
  [ "${Q%% *}" = "$want_minor" ] || fail "server_version of $e is '$Q', expected $want_minor (the table's 17 pin, 17.11 at the time of writing)"
  rec=$(kn "upg-$e" get configmaps/upg-postgres-upgrade -o jsonpath='{.data.state}' 2>/dev/null || true)
  [ "$rec" = verified ] || fail "the upgrade record configmaps/upg-postgres-upgrade of $e reads '$rec', expected verified"
done
echo "ok   every environment is on 17 ($want_minor) and its upgrade record is verified (AC-191.7)"

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

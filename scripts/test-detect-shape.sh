#!/usr/bin/env bash
# Fixture tests for detect-shape.sh: every shape in shapes.yml must resolve via
# (a) .copier-answers.yml and (b) the sniffing fallback; ambiguous trees must not.
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
detect="$here/detect-shape.sh"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
fail=0

expect() { # name expected dir
  local got
  got=$("$detect" "$3" 2>/dev/null || true)
  if [ "$got" = "$2" ]; then echo "ok   $1 -> ${got:-<none>}"; else echo "FAIL $1: expected '$2', got '$got'"; fail=1; fi
}

mk() { local d="$tmp/$1"; mkdir -p "$d"; echo "$d"; }

# (a) copier answers — local path form (what /component:new produces) and gh: form
shapes=$(uv run "$here/shapes.py" ids 2>/dev/null || python3 - <<'PY'
print("service-python library-python web-nextjs gitops-app service-java service-go cluster-gitops")
PY
)
for s in $(echo "$shapes"); do
  d=$(mk "answers-$s"); printf '_src_path: /tmp/tmp.abc/templates/%s\n_commit: v1\n' "$s" > "$d/.copier-answers.yml"
  expect "copier local path $s" "$s" "$d"
  d=$(mk "answers-gh-$s"); printf '_src_path: gh:ika100/sdlc-foundry/templates/%s\n' "$s" > "$d/.copier-answers.yml"
  expect "copier gh: path $s" "$s" "$d"
done

# (b) sniffing fallback
d=$(mk sniff-gitops);  mkdir -p "$d/applications/app"; touch "$d/applications/app/applicationset.yaml"; expect "sniff gitops-app" gitops-app "$d"
d=$(mk sniff-cluster); mkdir -p "$d/cluster"; touch "$d/cluster.yaml" "$d/cluster/operators-root.yaml"; expect "sniff cluster-gitops" cluster-gitops "$d"
d=$(mk sniff-next-cfg); touch "$d/next.config.mjs"; expect "sniff next.config" web-nextjs "$d"
d=$(mk sniff-next-pkg); echo '{"dependencies":{"next":"15.0.0"}}' > "$d/package.json"; expect "sniff package.json next" web-nextjs "$d"
d=$(mk sniff-pom);      touch "$d/pom.xml"; expect "sniff pom.xml" service-java "$d"
d=$(mk sniff-gradle);   touch "$d/build.gradle.kts"; expect "sniff build.gradle.kts" service-java "$d"
d=$(mk sniff-go);       touch "$d/go.mod"; expect "sniff go.mod" service-go "$d"
d=$(mk sniff-pysvc);    touch "$d/pyproject.toml" "$d/Dockerfile"; expect "sniff python service" service-python "$d"
d=$(mk sniff-pylib);    touch "$d/pyproject.toml"; expect "sniff python library" library-python "$d"

# Precedence + negatives
d=$(mk prec-python-with-admin-ui); touch "$d/pyproject.toml" "$d/Dockerfile"; printf '_src_path: gh:ika100/sdlc-foundry/templates/service-python\n' > "$d/.copier-answers.yml"; touch "$d/next.config.js"
expect "copier answers beat sniffing" service-python "$d"
d=$(mk unknown-answers-falls-back); printf '_src_path: gh:other/tpl\n' > "$d/.copier-answers.yml"; touch "$d/go.mod"; expect "unknown _src_path falls back to sniff" service-go "$d"
d=$(mk empty); expect "empty repo -> no shape" "" "$d"

exit $fail

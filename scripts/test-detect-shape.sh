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
shapes=$(bash "$here/uv-script.sh" "$here/shapes.py" ids 2>/dev/null || python3 - <<'PY'
print("service-python library-python web-nextjs gitops-app service-java library-java service-go service-typescript library-typescript service-dotnet library-dotnet cluster-gitops")
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
d=$(mk sniff-fastify);  echo '{"dependencies":{"fastify":"^5.0.0"}}' > "$d/package.json"; expect "sniff package.json fastify" service-typescript "$d"
d=$(mk sniff-next-fastify); echo '{"dependencies":{"next":"16.0.0","fastify":"^5.0.0"}}' > "$d/package.json"; expect "next with fastify is a website" web-nextjs "$d"
d=$(mk sniff-pom);      touch "$d/pom.xml" "$d/Dockerfile"; expect "sniff pom.xml + Dockerfile" service-java "$d"
d=$(mk sniff-pom-boot); echo '<project><parent><artifactId>spring-boot-starter-parent</artifactId></parent></project>' > "$d/pom.xml"; expect "sniff pom.xml with spring-boot" service-java "$d"
d=$(mk sniff-javalib);  echo '<project><artifactId>utils</artifactId></project>' > "$d/pom.xml"; expect "sniff bare pom.xml library" library-java "$d"
d=$(mk sniff-gradle);   touch "$d/build.gradle.kts"; expect "sniff build.gradle.kts" service-java "$d"
d=$(mk sniff-go);       touch "$d/go.mod"; expect "sniff go.mod" service-go "$d"
d=$(mk sniff-slnx);     mkdir -p "$d/src/Orders"; touch "$d/Orders.slnx" "$d/src/Orders/Orders.csproj" "$d/Dockerfile"; expect "sniff .slnx + Dockerfile" service-dotnet "$d"
d=$(mk sniff-csproj);   mkdir -p "$d/Orders"; touch "$d/Orders/Orders.csproj" "$d/Dockerfile"; expect "sniff csproj one level below + Dockerfile" service-dotnet "$d"
d=$(mk sniff-dotnet-lib); touch "$d/Orders.csproj"; expect "a .NET project without a Dockerfile is a library" library-dotnet "$d"
d=$(mk sniff-pysvc);    touch "$d/pyproject.toml" "$d/Dockerfile"; expect "sniff python service" service-python "$d"
d=$(mk sniff-pylib);    touch "$d/pyproject.toml"; expect "sniff python library" library-python "$d"
d=$(mk sniff-tslib);    echo '{"name":"@acme/types","devDependencies":{"typescript":"~5.9.3"}}' > "$d/package.json"; expect "sniff package.json library" library-typescript "$d"
d=$(mk sniff-py-with-pkg); touch "$d/pyproject.toml"; echo '{"devDependencies":{"prettier":"3.0.0"}}' > "$d/package.json"; expect "python repo with a package.json stays python" library-python "$d"

# Precedence + negatives
d=$(mk prec-python-with-admin-ui); touch "$d/pyproject.toml" "$d/Dockerfile"; printf '_src_path: gh:ika100/sdlc-foundry/templates/service-python\n' > "$d/.copier-answers.yml"; touch "$d/next.config.js"
expect "copier answers beat sniffing" service-python "$d"
d=$(mk unknown-answers-falls-back); printf '_src_path: gh:other/tpl\n' > "$d/.copier-answers.yml"; touch "$d/go.mod"; expect "unknown _src_path falls back to sniff" service-go "$d"
d=$(mk empty); expect "empty repo -> no shape" "" "$d"

exit $fail

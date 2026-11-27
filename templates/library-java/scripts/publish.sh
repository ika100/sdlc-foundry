#!/usr/bin/env bash
# Publish the release (spec 217, ADR-125): check that the commit built is the tagged one, build the jar (with its sources and
# javadoc jars) with the tag's version,
# then deploy it to GitHub Packages (maven.pkg.github.com, pom.xml's distributionManagement). The `publish` CI job runs it on a
# v* tag, after every gate of the same run passed, so the build skips the tests.
#   devbox run publish vX.Y.Z             check, build, deploy (needs GH_TOKEN with packages: write)
#   devbox run publish vX.Y.Z --dry-run   check and build only; prints what it would deploy, no registry call
# The tag is the version: pom.xml keeps its development version; only the build carries X.Y.Z.
set -euo pipefail

usage() { echo "usage: publish.sh vX.Y.Z [--dry-run]" >&2; exit 2; }
[ $# -ge 1 ] && [ $# -le 2 ] || usage
tag="$1"
dry_run=0
if [ $# -eq 2 ]; then [ "$2" = "--dry-run" ] || usage; dry_run=1; fi
[[ "$tag" =~ ^v[0-9]+\.[0-9]+\.[0-9]+([-.+][0-9A-Za-z.+-]+)?$ ]] || usage
version="${tag#v}"

HELP=org.apache.maven.plugins:maven-help-plugin:3.6.0:evaluate
VERSIONS=org.codehaus.mojo:versions-maven-plugin:2.25.2:set
pom() { mvn -B -q "$HELP" -Dexpression="$1" -DforceStdout; }

manifest=$(pom project.version)

# The version this commit builds: the tag's only when HEAD carries the tag and nothing is changed, else pom.xml's.
built="$manifest"
tagged=$(git rev-parse -q --verify "refs/tags/$tag^{commit}" 2>/dev/null || true)
if [ -n "$tagged" ] && [ "$tagged" = "$(git rev-parse HEAD)" ] && [ -z "$(git status --porcelain)" ]; then
  built="$version"
fi
if [ "$built" != "$version" ]; then
  echo "publish: the built version is $built but the tag is $tag ($version); nothing was published" >&2
  echo "fix: tag the commit you build (git tag $tag on HEAD), fetch the tags (actions/checkout with fetch-depth: 0), and commit or stash local changes" >&2
  exit 1
fi

group=$(pom project.groupId)
artifact=$(pom project.artifactId)
registry=$(pom project.distributionManagement.repository.url)
case "$registry" in
  https://maven.pkg.github.com/*) ;;
  *) echo "publish: pom.xml deploys to '$registry', not to GitHub Packages; nothing was published" >&2
     echo "fix: set distributionManagement/repository (id github) to https://maven.pkg.github.com/<owner>/<repo> (ADR-125)" >&2
     exit 1 ;;
esac
jar="target/$artifact-$version.jar"
# the jar with its sources and javadoc jars: consumers' IDEs show both (#1058)
jars=("$jar" "target/$artifact-$version-sources.jar" "target/$artifact-$version-javadoc.jar")

# set the tag's version for this build only: pom.xml is restored whatever happens
settings=$(mktemp)
cp pom.xml .pom.xml.orig
trap 'mv -f .pom.xml.orig pom.xml; rm -f "$settings"' EXIT
mvn -B -q "$VERSIONS" -DnewVersion="$version" -DgenerateBackupPoms=false >&2
set_to=$(pom project.version)
if [ "$set_to" != "$version" ]; then
  echo "publish: the built version is $set_to but the tag is $tag ($version); nothing was published" >&2
  echo "fix: keep the project's own <version> element in pom.xml so that versions:set can change it" >&2
  exit 1
fi

if [ "$dry_run" -eq 1 ]; then
  mvn -B -DskipTests -Djacoco.skip=true package >&2
  for f in "${jars[@]}"; do
    [ -f "$f" ] || { echo "publish: the build wrote no $f" >&2; exit 1; }
  done
  echo "publish: would publish ${jars[0]}, ${jars[1]} and ${jars[2]} as $group:$artifact:$version to $registry"
  exit 0
fi

: "${GH_TOKEN:?publish: GH_TOKEN is not set (the publish CI job passes GITHUB_TOKEN with packages: write)}"
user="${GITHUB_ACTOR:-x-access-token}"
path="$(printf '%s' "$group" | tr . /)/$artifact/$version/$artifact-$version.pom"
if curl -fsS -o /dev/null -u "$user:$GH_TOKEN" "$registry/$path" 2>/dev/null; then
  echo "publish: $group:$artifact:$version is already in $registry; nothing to do (a rerun of the same tag)"
  exit 0
fi
# the token stays in the environment: the settings file names it, it never holds it
cat > "$settings" <<EOF
<settings>
  <servers>
    <server>
      <id>github</id>
      <username>$user</username>
      <password>\${env.GH_TOKEN}</password>
    </server>
  </servers>
</settings>
EOF
mvn -B -s "$settings" -DskipTests -Djacoco.skip=true deploy >&2
echo "publish: published $group:$artifact:$version to $registry"

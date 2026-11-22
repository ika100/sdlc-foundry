#!/usr/bin/env bash
# Publish the release (spec 215, ADR-125): build dist/, pack the package with the tag's version, check that the commit
# built is the tagged one, then publish it to GitHub Packages (npm.pkg.github.com). The `publish` CI job runs it on a v* tag.
#   devbox run publish vX.Y.Z             build, check, publish (needs NODE_AUTH_TOKEN with packages: write)
#   devbox run publish vX.Y.Z --dry-run   build and check only; prints what it would publish, no network call
# The tag is the version: package.json keeps its development version; only the packed package.json carries X.Y.Z.
set -euo pipefail

usage() { echo "usage: publish.sh vX.Y.Z [--dry-run]" >&2; exit 2; }
[ $# -ge 1 ] && [ $# -le 2 ] || usage
tag="$1"
dry_run=0
if [ $# -eq 2 ]; then [ "$2" = "--dry-run" ] || usage; dry_run=1; fi
[[ "$tag" =~ ^v[0-9]+\.[0-9]+\.[0-9]+([-.+][0-9A-Za-z.+-]+)?$ ]] || usage
version="${tag#v}"
registry="https://npm.pkg.github.com"

name=$(node -p 'require("./package.json").name')
manifest=$(node -p 'require("./package.json").version')

# The version this commit builds: the tag's only when HEAD carries the tag and nothing is changed, else package.json's.
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

rm -rf dist .pack
pnpm build >&2
# stamp the tag's version into the packed package only: package.json is restored whatever happens
cp package.json .package.json.orig
trap 'mv -f .package.json.orig package.json' EXIT
npm pkg set version="$version"
pnpm pack --pack-destination .pack >&2
mv -f .package.json.orig package.json
trap - EXIT

tarball=$(find .pack -maxdepth 1 -name '*.tgz' | head -1)
packed=$(tar -xOzf "$tarball" package/package.json | node -e 'let s="";process.stdin.on("data",d=>s+=d).on("end",()=>console.log(JSON.parse(s).version))')
if [ "$packed" != "$version" ]; then
  echo "publish: the built version is $packed but the tag is $tag ($version); nothing was published" >&2
  echo "fix: check that package.json's version can be set by npm pkg set and that pnpm pack keeps it" >&2
  exit 1
fi

if [ "$dry_run" -eq 1 ]; then
  echo "publish: would publish $tarball as $name@$version to $registry"
  exit 0
fi

: "${NODE_AUTH_TOKEN:?publish: NODE_AUTH_TOKEN is not set (the publish CI job passes GITHUB_TOKEN with packages: write)}"
npmrc=$(mktemp)
trap 'rm -f "$npmrc"' EXIT
printf '%s\n' "${registry#https:}/:_authToken=\${NODE_AUTH_TOKEN}" "${name%%/*}:registry=$registry" > "$npmrc"
if NPM_CONFIG_USERCONFIG="$npmrc" npm view "$name@$version" version --registry "$registry" >/dev/null 2>&1; then
  echo "publish: $name@$version is already in $registry; nothing to do (a rerun of the same tag)"
  exit 0
fi
NPM_CONFIG_USERCONFIG="$npmrc" npm publish "$tarball" --registry "$registry"
echo "publish: published $name@$version to $registry"

#!/usr/bin/env bash
# Publish the release (spec 213, ADR-125): build the wheel and the source archive, check that their version is the tag's,
# then attach both to the GitHub release of the tag (created when missing). The `publish` CI job runs it on a v* tag.
#   devbox run publish vX.Y.Z             build, check, upload (needs GH_TOKEN)
#   devbox run publish vX.Y.Z --dry-run   build and check only; prints what it would upload
set -euo pipefail

usage() { echo "usage: publish.sh vX.Y.Z [--dry-run]" >&2; exit 2; }
[ $# -ge 1 ] && [ $# -le 2 ] || usage
tag="$1"
dry_run=0
if [ $# -eq 2 ]; then [ "$2" = "--dry-run" ] || usage; dry_run=1; fi
[[ "$tag" =~ ^v[0-9]+\.[0-9]+\.[0-9]+([-.+][0-9A-Za-z.+-]+)?$ ]] || usage
version="${tag#v}"

rm -rf dist
uv build --out-dir dist >&2   # the version comes from the git tag (hatch-vcs, spec 138)

count() { echo $#; }   # the file is rendered by Copier, so it avoids Jinja's comment opener
shopt -s nullglob
wheels=(dist/*-"$version"-py3-none-any.whl)
sdists=(dist/*-"$version".tar.gz)
# the ${a[@]+...} form keeps an empty array legal under `set -u` in bash 3.2 (macOS)
if [ "$(count ${wheels[@]+"${wheels[@]}"})" -ne 1 ] || [ "$(count ${sdists[@]+"${sdists[@]}"})" -ne 1 ]; then
  built=$(find dist -maxdepth 1 -name '*.whl' -exec basename {} \; | sed -E 's/^[^-]+-([^-]+)-.*/\1/' | head -1)
  echo "publish: the built version is ${built:-unknown} but the tag is $tag ($version); nothing was published" >&2
  echo "fix: tag the commit you build (git tag $tag on HEAD), fetch the tags (actions/checkout with fetch-depth: 0), and commit or stash local changes" >&2
  exit 1
fi
files=("${wheels[0]}" "${sdists[0]}")

if [ "$dry_run" -eq 1 ]; then
  echo "publish: would upload ${files[*]} to the GitHub release $tag"
  exit 0
fi

gh release view "$tag" >/dev/null 2>&1 || gh release create "$tag" --verify-tag --title "$tag" --generate-notes
gh release upload "$tag" "${files[@]}" --clobber
echo "publish: uploaded ${files[*]} to the GitHub release $tag"

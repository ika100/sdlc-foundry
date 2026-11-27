#!/usr/bin/env bash
# Publish the release (spec 221, ADR-125): check that the commit built is the tagged one, pack the library with the tag's
# version, then push the package to GitHub Packages (https://nuget.pkg.github.com/<owner>/index.json, <owner> from the
# project's RepositoryUrl). The `publish` CI job runs it on a v* tag, after every gate of the same run passed, so the pack
# skips the tests.
#   devbox run publish vX.Y.Z             check, pack, push (needs GH_TOKEN with packages: write)
#   devbox run publish vX.Y.Z --dry-run   check and pack only; prints what it would push, no registry call
# The tag is the version: the project keeps its development version; only the pack carries X.Y.Z.
set -euo pipefail

usage() { echo "usage: publish.sh vX.Y.Z [--dry-run]" >&2; exit 2; }
[ $# -ge 1 ] && [ $# -le 2 ] || usage
tag="$1"
dry_run=0
if [ $# -eq 2 ]; then [ "$2" = "--dry-run" ] || usage; dry_run=1; fi
[[ "$tag" =~ ^v[0-9]+\.[0-9]+\.[0-9]+([-.+][0-9A-Za-z.+-]+)?$ ]] || usage
version="${tag#v}"

projects=(src/*/*.csproj)
if [ ${#projects[@]} -ne 1 ] || [ ! -f "${projects[0]}" ]; then
  echo "publish: expected exactly one project under src/, found: ${projects[*]}; nothing was published" >&2
  echo "fix: keep the library in src/<Namespace>/<Namespace>.csproj (one package per repo, spec 221)" >&2
  exit 1
fi
project="${projects[0]}"
prop() { dotnet msbuild "$project" -nologo "-getProperty:$1" | tr -d '\r' | tail -n 1; }

manifest=$(prop Version)

# The version this commit builds: the tag's only when HEAD carries the tag and nothing is changed, else the project's.
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

id=$(prop PackageId)
repo_url=$(prop RepositoryUrl)
case "$repo_url" in
  https://github.com/*/*) owner=$(printf '%s' "${repo_url#https://github.com/}" | cut -d/ -f1 | tr '[:upper:]' '[:lower:]') ;;
  *) echo "publish: the project's RepositoryUrl is '$repo_url', not a GitHub repo; nothing was published" >&2
     echo "fix: set <RepositoryUrl>https://github.com/<owner>/<repo></RepositoryUrl> in $project (ADR-125)" >&2
     exit 1 ;;
esac
registry="https://nuget.pkg.github.com/$owner/index.json"
package="artifacts/$id.$version.nupkg"

# pack with the tag's version: the project file is never edited
dotnet restore --locked-mode >&2
dotnet pack "$project" -c Release --no-restore "-p:Version=$version" -o artifacts >&2
[ -f "$package" ] || { echo "publish: the pack wrote no $package" >&2; exit 1; }

if [ "$dry_run" -eq 1 ]; then
  echo "publish: would publish $package as $id $version to $registry"
  exit 0
fi

: "${GH_TOKEN:?publish: GH_TOKEN is not set (the publish CI job passes GITHUB_TOKEN with packages: write)}"
user="${GITHUB_ACTOR:-x-access-token}"
# the token goes into a temporary NuGet config outside the repo, removed whatever happens
config_dir=$(mktemp -d)
trap 'rm -rf "$config_dir"' EXIT
(umask 077 && cat > "$config_dir/nuget.config" <<EOF
<?xml version="1.0" encoding="utf-8"?>
<configuration>
  <packageSources>
    <clear />
    <add key="github" value="$registry" />
  </packageSources>
  <packageSourceCredentials>
    <github>
      <add key="Username" value="$user" />
      <add key="ClearTextPassword" value="$GH_TOKEN" />
    </github>
  </packageSourceCredentials>
</configuration>
EOF
)
# the API key comes from the environment (NUGET_API_KEY), never from the command line
out=$(NUGET_API_KEY="$GH_TOKEN" dotnet nuget push "$package" --source github --configfile "$config_dir/nuget.config" --skip-duplicate 2>&1) || {
  printf '%s\n' "$out" >&2
  echo "publish: the push of $id $version to $registry failed" >&2
  exit 1
}
printf '%s\n' "$out" >&2
if grep -Eiq 'already (exists|contains)|conflict' <<< "$out"; then
  echo "publish: $id $version is already in $registry; nothing to do (a rerun of the same tag)"
  exit 0
fi
echo "publish: published $id $version to $registry"

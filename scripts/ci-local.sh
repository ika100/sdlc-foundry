#!/usr/bin/env bash
# The cheap CI checks, locally: for contributors without CI minutes and for a quick check before pushing.
#   scripts/ci-local.sh          fast checks (about a minute)
#   scripts/ci-local.sh --render also render every template (needs copier: uv tool install copier)
#   scripts/ci-local.sh --site   also build the documentation site (needs node 24: cd site && npm ci first time)
# The cluster test (tests/e2e/run.sh) and the per-template smoke jobs (devbox, Docker, Maven, pnpm) stay in CI.
set -euo pipefail
cd "$(dirname "$0")/.."

step() { printf '\n==> %s\n' "$*"; }

step "manifest JSON and plugin versions"
jq -e . .claude-plugin/marketplace.json > /dev/null
for plugin in plugins/*/; do
  name=$(basename "$plugin")
  have=$(jq -r .version "${plugin}.claude-plugin/plugin.json")
  want=$(jq -r ".plugins[] | select(.name == \"$name\") | .version" .claude-plugin/marketplace.json)
  [ "$have" = "$want" ] || { echo "version mismatch for $name: plugin.json=$have marketplace.json=$want" >&2; exit 1; }
done
echo "OK: plugin manifests match the marketplace"

step "shape registry, templates, plugins, descriptions"
uv run scripts/shapes.py check

step "4.x slash-command tombstones"
python3 scripts/tombstones.py check

step "GitHub Actions pinned by SHA, workflows have permissions"
python3 scripts/pin-actions.py --check

step "relative Markdown links"
python3 scripts/check-links.py

step "license and copyright metadata (REUSE)"
uvx --quiet --from "reuse[charset-normalizer]" reuse lint | tail -3

step "cplat tests (Kyverno CLI tests skip without the kyverno binary)"
uv run --with-requirements requirements-test.txt pytest tests/cplat -q -n auto

if [ "${1:-}" = "--site" ]; then
  step "documentation site (unit tests + build with link validation)"
  (cd site && { [ -d node_modules ] || npm ci --ignore-scripts; } && npm test && npm run build)
fi

if [ "${1:-}" = "--render" ]; then
  step "render every template"
  tmp=$(mktemp -d)
  trap 'rm -rf "$tmp"' EXIT
  for t in service-python library-python service-java service-go web-nextjs gitops-app; do
    copier copy "./templates/$t" "$tmp/$t" --defaults --trust --skip-tasks --data project_name="check-$t" > /dev/null
    echo "rendered $t"
  done
fi
printf '\nOK: local CI checks passed\n'

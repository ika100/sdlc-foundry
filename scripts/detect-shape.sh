#!/usr/bin/env bash
# detect-shape.sh — print the platform shape id of a repo (ADR-008).
#
# Usage: detect-shape.sh [repo-dir]      (default: current directory)
#
# Primary:  `_src_path` tail in .copier-answers.yml (e.g. .../templates/web-nextjs).
# Fallback: sniff the tree, most distinctive marker first.
# Exit 0 + shape id on stdout; exit 1 (nothing on stdout) if no shape resolves —
# callers must then ask the user rather than guess.
#
# Adding a shape: extend BOTH the case below and the sniff list (ADR-008), and shapes.yml.
set -euo pipefail

dir="${1:-.}"
cd "$dir"

answers=".copier-answers.yml"
if [ -f "$answers" ]; then
  src=$(sed -n 's/^_src_path:[[:space:]]*//p' "$answers" | head -1 | tr -d "\"'" | sed 's#/*$##')
  case "$src" in
    */templates/service-python|templates/service-python) echo service-python; exit 0 ;;
    */templates/library-python|templates/library-python) echo library-python; exit 0 ;;
    */templates/web-nextjs|templates/web-nextjs)         echo web-nextjs; exit 0 ;;
    */templates/gitops-app|templates/gitops-app)         echo gitops-app; exit 0 ;;
    */templates/cluster-gitops|templates/cluster-gitops) echo cluster-gitops; exit 0 ;;
    */templates/service-java|templates/service-java)     echo service-java; exit 0 ;;
    */templates/service-go|templates/service-go)         echo service-go; exit 0 ;;
  esac
fi

# Sniffing fallback — first match wins.
shopt -s nullglob
if [ -f cluster.yaml ] && [ -f cluster/operators-root.yaml ]; then echo cluster-gitops; exit 0; fi
appsets=(applications/*/applicationset.yaml)
if [ ${#appsets[@]} -gt 0 ]; then echo gitops-app; exit 0; fi

nextcfg=(next.config.*)
if [ ${#nextcfg[@]} -gt 0 ] || { [ -f package.json ] && grep -Eq '"next"[[:space:]]*:' package.json; }; then
  echo web-nextjs; exit 0
fi

gradle=(build.gradle*)
if [ -f pom.xml ] || [ ${#gradle[@]} -gt 0 ]; then echo service-java; exit 0; fi

if [ -f go.mod ]; then echo service-go; exit 0; fi

if [ -f pyproject.toml ]; then
  if [ -f Dockerfile ]; then echo service-python; else echo library-python; fi
  exit 0
fi

exit 1

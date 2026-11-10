#!/usr/bin/env bash
# The platform's test-fast recipe (spec 172, AC-172.3): the cplat tests, or only the tests given as arguments.
#   no arguments                      -> tests/cplat
#   arguments naming no existing path -> tests/cplat <args>   (e.g. -k expr)
#   otherwise                         -> <args> alone          (e.g. a test file or node id)
set -euo pipefail

named=0
for a in "$@"; do
  case "$a" in -*) continue ;; esac
  if [ -e "${a%%::*}" ]; then
    named=1
  fi
done

if [ "$#" -eq 0 ] || [ "$named" -eq 0 ]; then
  exec uv run --with-requirements requirements-test.txt pytest -q -n auto tests/cplat "$@"
fi
exec uv run --with-requirements requirements-test.txt pytest -q -n auto "$@"

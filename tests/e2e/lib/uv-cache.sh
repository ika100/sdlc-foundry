# shellcheck shell=bash
# A throwaway uv cache for the e2e scripts (spec 208), sourced by tests/e2e/run.sh, cluster.sh and upgrade.sh.
#
# The scripts run inline scripts through `uv run`, and every one leaves an environment in uv's cache. A script run gets a cache of its
# own, outside $work (which E2E_WORK may name and a failed run keeps), and removes it when it ends, pass or fail.
#
#   e2e_uv_cache_start   exports UV_CACHE_DIR, a fresh directory under ${TMPDIR:-/tmp}; remembers it in E2E_UV_CACHE
#   e2e_uv_cache_end     removes that directory (uv keeps read-only files); does nothing when none was started; never fails

e2e_uv_cache_start() {
  E2E_UV_CACHE="$(mktemp -d "${TMPDIR:-/tmp}/e2e-uv-cache.XXXXXX")"
  export UV_CACHE_DIR="$E2E_UV_CACHE"
}

e2e_uv_cache_end() {
  [ -n "${E2E_UV_CACHE:-}" ] || return 0
  chmod -R u+w "$E2E_UV_CACHE" 2>/dev/null || true
  rm -rf "$E2E_UV_CACHE" 2>/dev/null || true
  E2E_UV_CACHE=
}

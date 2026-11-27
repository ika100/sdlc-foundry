# shellcheck shell=bash
# `docker build` that retries once on a registry rate limit (#1045), sourced by tests/e2e/run.sh, clusters.sh and upgrade.sh.
#
# Docker Hub limits anonymous pulls: a build then fails with "invalid response status 429" (often "failed to load cache key") or
# "429 Too Many Requests", and a rerun a minute later passes. Any other failure is not retried.
#
#   e2e_docker_build <docker build arguments>   runs `docker build`; on a 429 in its output waits E2E_BUILD_RETRY_WAIT seconds
#                                               (default 30) and builds once more; returns the build's exit status

e2e_docker_build() {
  local log rc
  log="$(mktemp "${TMPDIR:-/tmp}/e2e-docker-build.XXXXXX")"
  docker build "$@" 2>"$log" && { rm -f "$log"; return 0; }
  rc=$?
  cat "$log" >&2
  if grep -Eq '(status|error|HTTP|code:?) 429|429 Too Many Requests|toomanyrequests' "$log"; then
    echo "e2e: docker build hit a registry rate limit (429); retrying once in ${E2E_BUILD_RETRY_WAIT:-30}s" >&2
    sleep "${E2E_BUILD_RETRY_WAIT:-30}"
    rm -f "$log"
    docker build "$@"
    return $?
  fi
  rm -f "$log"
  return "$rc"
}

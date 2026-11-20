# ADR-123: Local test runs select by recorded dependencies

**Status:** Accepted (2026-11-20, spec 212)

## Context

The cplat suite grew to about 12,400 tests and a full local run to about 8 minutes, close to the 9-minute limit of
`cplat quiet test-fast` ([ADR-108](108-test-time-is-bounded.md)). A build or ship of a platform spec ran it several times,
mostly after changes that a few dozen test files can see, while every pull request runs the whole suite in CI anyway.
Selecting by names or imports does not work in this repo: about half of the test files run cplat as a subprocess, and many
read prompts, templates and docs, so the import graph misses most dependencies. Spec 103's `cplat validate` selects by file
names and plan tasks, which does not fit the platform repo (its shape has no selector).

## Decision

1. **Local runs select, CI does not.** `devbox run test-fast` without arguments and `scripts/ci-local.sh` run the test files a
   change can affect; `devbox run test-fast --full`, `devbox run test` and `ci-local.sh --full` run every test. The CI test
   jobs, the shards and a plain `pytest tests/cplat` run every test and record nothing.
2. **Dependencies are recorded, not guessed.** A full run started through `test-fast` traces what each test file touches: the
   import statements it runs (also of modules already imported), the files it opens, the folders it lists, the repo paths it
   hands to a subprocess, and everything a cplat process started from it imports, opens or lists. Fixtures of a wider scope
   and shared renders count for every test that uses them. Module-level imports are added statically. Imports made by the
   suite's own autouse fixtures (which only patch) are no dependency.
3. **Unknown means everything.** The whole suite runs when there is no map, when a shared file of the suite changed, when a
   changed code or configuration file is a dependency of no test, or when the selection would hold more than half of the
   test files. A changed file that is neither code nor configuration and that no test reads (a page, an image) selects
   nothing; the run says so, and CI still runs every test, so this does not weaken [ADR-074](074-a-gate-that-checked-nothing-fails.md),
   which covers the gates of the generated repos.
4. **Maps belong to the clone.** Maps live in the git common directory, shared by every worktree; a selection compares the
   working tree with the map's commit (plus the files that were uncommitted while it was recorded) and uses the map with
   the fewest changes. Only full runs record, so a map always describes one tree.

## Consequences

- A fix round in a platform build runs seconds to a minute of tests instead of the whole suite; the first run in a new
  clone, and any run after a change to the suite's setup, still runs everything.
- A test that reaches a repo file in a way the trace cannot see (a non-cplat program reading a file it was not handed, a
  subprocess started with an environment that drops the trace variable) can be left out locally; CI catches it. Such a gap
  is fixed by handing the path over or by tracing that program, not by a list of exceptions.
- The trace variable does not start with `CPLAT_`, because the suite removes those before each test.
- Making the whole suite faster (cplat in-process instead of subprocesses) stays a separate change.

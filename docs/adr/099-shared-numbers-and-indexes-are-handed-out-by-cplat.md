# ADR-099: Shared numbers and indexes are handed out by cplat, and a replaced criterion is marked

**Status:** Proposed (2026-11-11, spec 183)
**Builds on:** [ADR-026](026-feature-specs.md) (feature specs), the ADR number rule of #337 (`cplat spec adr-next`)

## Context

Parallel sessions share spec numbers, ADR numbers and the ADR index, and each of these broke when picked or edited by
hand: `cplat spec new` gave out 176 twice while 176 and 177 sat on open PRs (#659), an architect overwrote the ADR index
with one line and parallel branches conflict at its end (#660). A later spec that changes a criterion of an earlier one
left the old criterion active, so trace, verify and the done count checked behaviour that no longer holds (#477). A cplat
command piped into `head` died with a traceback that the platform then filed as an issue (#577).

## Decision

- **One scan for shared numbers.** Every number that parallel branches share (spec numbers, ADR numbers) is the highest of
  the working tree, the base branch, every pushed branch as of the last fetch, and the files of every open PR
  (`gh pr list`), plus one. The scan lives in one module (`refscan`); `cplat spec new` and `cplat spec adr-next` use it,
  and `cplat spec check` reports a number this branch adds that another branch or open PR also adds. No lock service and
  no reservation file: a number is only as free as the last fetch and the PR list say, and the check catches the rest.
  When the PR list cannot be read, the numbers come from git alone and one warning says so.
- **ADRs are written by `cplat adr add`.** The command takes the number from the scan, writes the ADR from the
  platform's template and appends exactly one row to the end of `docs/adr/README.md`. Agents fill in the sections of the
  file it wrote; they never pick a number or edit the index, so the only index change of a branch is one appended line.
- **A replaced criterion is marked, not reopened.** The new criterion ends with `(replaces AC-<NNN>.<n>)`; in the same
  change the old one is struck through as `~~**AC-<NNN>.<n>**~~ superseded by AC-<MMM>.<m> on <date>: <its old text>`
  and its spec gets one Changelog line, keeping its status. A struck-through criterion counts as withdrawn everywhere;
  keeping the old text after the colon keeps the old spec's `spec_hash` and its plan valid. `cplat spec check` refuses a
  `(replaces …)` whose target is still active or does not exist. A slice of a system plan (`cplat spec new --from-plan`)
  strikes the replaced criterion itself, because the system planner never edits a component repo.
- **A closed pipe is not a crash.** A cplat command whose standard output is closed by its reader exits 141 (the shell's
  SIGPIPE status) with nothing on standard error, and files nothing.

## Consequences

- A new shared counter (any `<NNN>-` folder or file that branches add in parallel) goes through `refscan`, not a local
  directory listing.
- `cplat spec new` and `cplat spec check` on a branch that adds a spec call `gh` once; without GitHub they still work
  from git and warn.
- The ADR index can only grow by appended rows; a branch that rewrites it shows up in review as more than one line.
- Specs carry their replacement history in the criteria themselves; a behaviour change without a `(replaces …)` marker
  is not detected (spec 183 non-goal).
- Scripts that pipe cplat into `head` see status 141 under `set -o pipefail`, as with any other Unix tool.

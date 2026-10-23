# ADR-032 — Every run is recorded in a private run store

**Status:** accepted (2026-10-23, spec 087)

## Context

Ship, build, headless and PR-wait runs left no history. The ship state was overwritten by the next run, headless logs
stayed on one machine, and every hardening spec from 062 to 084 started from a failure someone happened to notice.
Specs 088–097 (platform-failure issues, agent quality, the weekly retro, smoke results, auto-promotion, fleet updates)
all need a durable record of every run that can be compared across runs. That record must never reach the public
platform repo, and writing it must never cost a run.

## Decision

- Each run (`ship`, `build`, `headless`, `pr-wait`, and later `fleet`, `retro`, `product-ship`) ends with exactly one
  JSON record, written once, at the end. Records have a versioned schema (`schema: 1`), the common fields of spec 087,
  and room for sections that later specs add. Readers ignore what they don't know.
- The store is a private GitHub repo that each owner configures (`CPLAT_RUNS_REPO=owner/name`, created by
  `cplat runs init`). There is no default store.
  - Each record is its own file, `runs/YYYY/MM/DD/<run_id>.json`.
  - A flush writes all pending files in one commit through the Git Data API and moves the branch with a non-forced
    ref update. When the ref moved, it retries.
  - Paths are unique per run, so concurrent writers never lose a record, and a repeated flush writes the same bytes to
    the same path.
- Before every write, the store's visibility is checked. Only a private repo is ever written.
- An unreachable or unconfigured store never fails a run. The record goes to a local buffer (at most 1000 records,
  oldest dropped first), and the run prints one warning line. The next write or `cplat runs flush` empties the buffer.
  Recording adds at most 20 s.
- Strings in a record go through the same redaction as `cplat feedback`. Records never contain logs, diffs, prompts or
  issue text.
- In-progress state is local (`~/.local/state/sdlc-foundry/runs/active/`), so events can change until the run ends. A
  run started inside another one (a PR wait or build inside a ship, a ship inside a headless run) attaches to it
  instead of writing its own record.

## Consequences

- `cplat runs report` can say which phase is slow, which escalation reasons and causes recur, and which checks need
  reruns, across all of an owner's repos.
- Specs 088–097 extend one record format and one write path instead of each inventing storage.
- The store grows by one small file per run. Retention is out of scope; deleting old day directories is safe.
- A store repo that is made public stops all writes (doctor `fail`) until it is private again.

## Not included

- Dashboards, retention, and recording other commands (`/svc:spec`, `/svc:plan`).
- Classifying escalation causes and filing issues (spec 088). This ADR only stores their results.

---
spec_id: 220-a-docs-only-land-does-not-wait-for-a
title: A docs-only land does not wait for a code PR's catch-up e2e
status: building
priority: P1
shape: platform
tracks: [280]
explored: true
---

# 220 — A docs-only land does not wait for a code PR's catch-up e2e

## Problem

Every merge into `main` that cplat makes holds the repo's merge lock (ADR-089). Inside it, `merge_lock.catch_up` (`scripts/cplat/merge_lock.py`) updates a branch that is behind and waits for **all** checks of the new head, so a code PR in the e2e scope (spec 134, `scripts/e2e-scope.py`) waits for a full cluster e2e (median 25 min, p90 32 min since 2026-11-16) while it holds the lock. Every other land queues behind it, also PRs that change only docs, specs or changelog fragments and that skip the e2e themselves. The dispatcher logs show lock waits of 26, 21, 11 and 4 min in one week (PRs #805, #799, #798, #687), and three spec-only PRs waited about 35 min behind #801 (#280, 2026-11-17). With three dispatcher slots and several sessions merging, these waits grow. The catch-up e2e is also often wasted: when the commits that came into `main` since the PR's last green are all outside the e2e scope, the e2e of the previous head already covers everything the e2e exercises. Docs-only PRs already skip the e2e (spec 134, #814, #815); this spec removes the two waits that are left. It is one step of #280; batching e2e across PRs stays open there.

## Stories

As someone landing a docs, spec or changelog-only PR, I want it to merge in minutes even while a code PR is catching up with `main`, so that small PRs do not sit behind a cluster e2e they do not need.

As someone landing a code PR that fell behind `main` only by docs-like commits, I want its earlier green e2e to count, so that the land does not re-run a 25-minute e2e that cannot fail differently.

As the platform maintainer, I want lock waits measured per land, so that I can see whether this was enough or a batching queue is needed.

**Repos:** sdlc-foundry (the platform: `cplat` merge lock and land; the behaviour reaches every repo that lands with cplat).

## Acceptance criteria

Keeping the previous e2e result.

- **AC-220.1** Given a PR whose head had all checks green, including a cluster e2e that ran (not skipped), and that is behind its base, when the land catches up inside the merge lock and every file changed between the base it was judged on and the current base is outside the e2e scope (as `scripts/e2e-scope.py` decides for that range), then the land updates the branch as today and waits only for the checks of the new head that are not e2e checks. It merges when those are green, and prints one line `e2e: kept the green e2e of <old head short sha>; <n> commit(s) since are outside the e2e scope`.
- **AC-220.2** Given the same catch-up, when any file changed between the judged base and the current base is inside the e2e scope, or the scope cannot be decided (an error of `e2e-scope.py`, an unknown base), then the land waits for every check of the new head, as today, and prints which path put the range in scope, or that the scope could not be decided.
- **AC-220.3** Given a kept e2e result (AC-220.1), when the land merges, then the e2e run started on the new head no longer holds the merge: the land does not wait for it, and it is cancelled so that the runner is free. A red non-e2e check of the new head still stops the land as today.

The fast lane.

- **AC-220.4** Given a land A that holds the merge lock and is waiting on the checks of its updated head, when another land B starts whose PR is outside the e2e scope (`e2e-scope.py` prints `run=false` for B's change), then B does not wait for A's checks. B catches up and merges by today's rules, inside the merge lock for its own merge step only, and A's wait goes on. While B waits, it prints `fast lane: <A's PR> waits on its checks; merging <B's PR> outside the e2e scope`.
- **AC-220.5** Given land A of AC-220.4, when B has merged and A's checks are green, then A finds its base moved and catches up again by AC-220.1 or AC-220.2. A merge of A therefore never contains a base that its checks did not see, apart from the out-of-scope commits that AC-220.1 allows.
- **AC-220.6** Given a land B that is inside the e2e scope (`run=true`), or whose scope cannot be decided, when A holds the lock, then B waits for the lock as today. Only one land at a time waits on catch-up checks of an in-scope PR.
- **AC-220.7** Given a platform release hold (spec 198), when any land, fast lane included, is about to merge, then the hold is checked inside the lock right before the merge, as today, and a held merge waits for the hold. A land in RELEASE mode keeps its behaviour: no catch-up, no fast lane, no kept e2e.

Measuring.

- **AC-220.8** Given any land that cplat runs, when it ends, then its run record holds the minutes it waited for the merge lock, the minutes it spent in catch-up checks, whether it took the fast lane and whether it kept an e2e result. `cplat platform runs report` shows the median and p90 lock wait for docs-only and code lands of the period.
- **AC-220.9** Given the run records of the first 7 days after the release that carries this spec, when the report is read, then no docs-only land waited more than 5 min for the merge lock while a code PR was catching up, and no code land that was behind only by out-of-scope commits waited for a catch-up e2e. The result is written into #280.

Tests.

- **AC-220.10** Given fakes of `gh` (PR heads, check runs, the e2e run, update-branch) and of the base's history, when the tests run, then they cover: a catch-up behind only out-of-scope commits (AC-220.1, AC-220.3); behind by an in-scope commit and an undecidable scope (AC-220.2); a docs-only land merging while a code land waits on its checks, and the code land catching up again after it (AC-220.4, AC-220.5); two in-scope lands (AC-220.6); a release hold during a fast-lane merge and a RELEASE-mode land (AC-220.7). They run without network.

## Non-goals

- Batching e2e across PRs, the full merge queue of #280.
- Releasing the merge lock for code PRs during their catch-up checks (optimistic release); decided 2026-11-23: not until the fast lane is measured.
- Changing what `e2e-scope.py` counts as in scope, or the e2e of a PR's own first head.
- Branch protection or required checks on GitHub (the repo is on the Free plan; cplat decides what is green).

## Assumptions

- **A1** The e2e scope of the commits that came in is decided with `scripts/e2e-scope.py` over the range from the base the PR's checks were judged on to the current base, read from the code at the current base (other option: a separate list of docs paths; affects AC-220.1, AC-220.2).
- **A2** "e2e checks" are the check runs of the `e2e` workflow (and the upgrade e2e workflows) named by the shape's CI, as the CheckWatch already tells them apart for the skipped-check rule of #815 (other option: a name pattern; affects AC-220.1, AC-220.3).
- **A3** The e2e run on the new head of a kept result is cancelled, because the self-hosted runner is shared and the result would not change the merge (other option: let it run and only report it; affects AC-220.3).
- **A4** The fast lane needs no second lock file: A marks in the lock record that it waits on checks, and B may take the merge step while that mark is set; the merge step itself stays exclusive (other option: a separate docs lock; affects AC-220.4, AC-220.6).
- **A5** The measure counts a land as docs-only when `e2e-scope.py` printed `run=false` for its change (other option: by file paths; affects AC-220.8, AC-220.9).

## Open questions

## Changelog

- 2026-11-23 created
- 2026-11-23 priority P1 given by you
- 2026-11-23 approved
- 2026-11-23 building

# ADR-129: A system ship's mechanical loop runs in cplat

**Status:** Accepted (2026-11-24, spec 216)
**Amends:** [ADR-082](082-a-coordinator-waits-with-a-cplat-wait-never-a-polling-loop.md) (`cplat` itself counts the repo `TIMEOUT:` results), [ADR-086](086-a-system-ships-repos-run-in-their-own-sessions.md) (the driver starts the repo sessions)

## Context

Journey 23 spent 24.4 M tokens and 51 minutes on the step "One spec for the whole system". The coordinator of `/system:ship` used 8.0 M of them in 78 calls, 31 of which only relayed what `cplat system ship` had already decided: `next --json`, `repo start`, `next --wait`, `phase complete`, `complete` and `finish`. Each call carried the whole conversation again. Every one of those steps is a rule of the prompt that a program can apply.

## Decision

After phase `plan` a system ship's publish, repos, land and completion run in a detached `cplat` driver (`cplat system ship drive`) that starts no model. The session builds the gitops entry, waits with `cplat system ship wait` and hands over. The driver reacts to the exit code and output of each `cplat system ship` step, the signals the session reacts to today, and writes a progress file that `wait` reads. An entry, a stop rule, an escalation or `finish` ends it.

## Consequences

- **Amends ADR-082 and ADR-086:** the driver, not the session, runs `next --wait`, counts three `TIMEOUT:` in a row (escalation cause `environment`) and starts the repo sessions through `repo start`. The session waits with one verb and acts on `WAIT:`, `TIMEOUT:`, `ENTRY:`, `ENDED:`, `DONE:`, `ESCALATED:` or `STOPPED:`.
- **The switch:** `CPLAT_SYSTEM_DRIVER=0` makes `drive` print `driver: off` and the session runs today's loop from `plugins/system/references/ship-loop.md`. A person who wants to answer a held repo's questions takes the same path.
- **Prompt size:** `ship.md` ends shorter; the moved rules stay in the reference with their register entries.
- **Kill rule (AC-216.12):** the measure runs on the first journey after the release with `cplat platform runs journey measure`. The coordinator of "One spec for the whole system" must use at most 40 calls and 4.0 M tokens, with no more escalations or stops than journey 23. Otherwise the default flips to off in the next release and this change is reverted.

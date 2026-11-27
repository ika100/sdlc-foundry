# ADR-131: Fix entries name their cause

**Status:** Proposed (2026-11-27)

## Context

The platform measures how often a release needs a fix, but a changelog `fixed` entry does not say which change caused it. Attributing fixes by guessing from text or timing is unreliable, and 11 `fixed` fragments already on main carry no cause, so the release step cannot start refusing them.

## Decision

A platform fix entry names its cause in a closing Caused by: line; change-quality derives the change-failure rate from it.

The line is checked only on fragments a branch adds: its form in CI (offline) and its target on GitHub in `cplat platform pr-check` (an unreachable GitHub gives a warning, not a failure). Release assembly is unchanged, so existing fragments still release. Forms: a PR, a tag, `none`, `unknown`.

## Consequences

- Authors of a `fixed` fragment add one line; `none` and `unknown` stay honest answers.
- `cplat platform change-quality` can report fixes caused per release, blast radius and the change-failure rate from data, not guesses.
- Old entries without a cause count as unattributed; a later change must not make the release step require the line without a migration.

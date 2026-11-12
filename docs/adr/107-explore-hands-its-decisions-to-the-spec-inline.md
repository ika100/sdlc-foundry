# ADR-107: Explore hands its decisions to the spec inline

**Status:** Accepted (2026-11-12), with spec 188

## Context

A person who talks an idea through before writing a spec makes decisions in
that chat. When the spec command runs afterwards, those decisions are lost
unless the person retypes them. The spec then decides the same points again,
and the person finds out at review: the work comes back as revised
assumptions and amendments to the approved spec.

[ADR-084](084-a-spec-decides-by-default.md) made a spec decide by default and
ask only what it may not decide. That keeps unattended runs moving, but it
leaves no place for a person who wants to settle a point first.

## Decision

Exploration (`/component:explore`, `/system:explore`) is read-only and started
by a person only. It writes no file. When the person is done it hands its
decisions to the spec inline, as a `DECIDED:` block in the request of the spec
command. Each decision is sorted into one of three kinds:

- **behaviour**: becomes an acceptance criterion;
- **constraint**: a binding assumption in the spec, ending
  `(decided in explore)`;
- **hint**: a non-binding bullet under `## Notes for the architect`, which the
  architect may depart from with a named reason in `design.md`.

Explore is the person-only path for what the spec would otherwise decide under
ADR-084. The default is unchanged: without a `DECIDED:` block the spec decides
as before.

## Consequences

- A spec gains a `## Notes for the architect` section. It sits outside the
  criteria hash, so a hint can change without invalidating the approval.
- A spec made from an exploration carries `explored: true`. The retro compares
  explored specs with other specs (revisions and amendments after approval).
  If the explored specs are not better 6 weeks after the release, the feature
  is removed (kill rule).
- The explore prompts are person-only: they are absent from unattended
  allowlists, so an unattended run cannot start one.
- Nothing is stored between explore and spec, so a decision not carried in the
  `DECIDED:` block is lost; the explore prompt must list them before handing
  over.

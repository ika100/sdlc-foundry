# Specs of sdlc-foundry

The platform's own features, as feature specs ([ADR-026](../adr/026-feature-specs.md)). Each folder `<NNN>-<slug>/` holds `spec.md` (problem, stories, acceptance criteria `AC-<NNN>.<n>`, non-goals, open questions, changelog) and, for work planned after the migration, `design.md`, `plan.md` and `verification.md`. The index is the table in [`../backlog.md`](../backlog.md).

- New platform work: `/component:spec <description>` in this repo (it declares `shape: platform`, so spec, plan, build, verify and ship work as in a component repo; releases follow [CONTRIBUTING.md](../../CONTRIBUTING.md#releases)), then an ADR where a decision outlives the feature, and a PR that passes `devbox run ci-local`.
- `cplat spec check` validates every spec here; `cplat spec list --all` shows status and the next step.
- The formats are in the `svc:spec-format` skill: [`plugins/svc/skills/spec-format/`](../../plugins/svc/skills/spec-format/SKILL.md).

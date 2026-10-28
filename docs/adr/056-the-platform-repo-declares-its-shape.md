# ADR-056: The platform repo declares its own shape: a template-less registry entry, set only in the committed settings file

**Status:** Accepted (2026-10-26)
**Builds on:** [ADR-008](008-shape-detection.md) (shape detection), [ADR-015](015-shape-registry-as-code.md) (the shape registry), [ADR-026](026-feature-specs.md) (feature specs), [ADR-036](036-coordinator-model-default-and-settings.md) (settings files), spec 123

## Context

Every `/component:*` command starts with `cplat shape`. A repo's shape comes from `.copier-answers.yml`, else from sniffing its files (ADR-008), and every shape in `shapes.yml` has a template, a plugin and a sniff rule (ADR-015). The sdlc-foundry repo is none of these: it was never generated, it must never be updated from a template or by the fleet, and sniffing for it (a `scripts/cplat/`, a `shapes.yml`) would risk mistaking a component repo for the platform. So `cplat shape` fails here, and `/component:build` and `/component:ship` cannot run on the platform's own specs.

Many parts of `cplat` iterate the registry and assume a template: `/component:new`, `/system:new`, `cplat adopt`, the fleet, the type/lang pairs of the domain model, the shape contract check, the site's shapes table.

## Decision

1. **A shape may be declared instead of detected, and only in the repo's committed `.platform-settings.yml`.** Its registry entry has `template: null` and `detection: {declared: .platform-settings.yml}` instead of `copier_src` and `sniff`. `platform` is the only such shape. A `shape:` key in the personal settings file, an unknown value, a component shape, or a declaration next to a `.copier-answers.yml` that names a template are errors, never a fallback: a component repo's shape keeps coming from `.copier-answers.yml` (or `cplat adopt`).
2. **The registry has two views.** `shapes.load()` returns the template shapes, as before, so every caller that creates, adopts, updates or lists repos never sees a declared shape. `shapes.load_all()` and `shapes.get(id)` include it; only shape resolution, routing and spec checking use them.
3. **The registry check accepts a template-less entry only when it is declared.** It still needs a plugin, and it must not be deployable, a library, or carry runtime, smoke or stack defaults. Any other entry without a template, plugin or detection rule still fails.
4. **A declared shape has no release role.** `/component:release` refuses in the platform repo; the platform keeps its own release procedure (CONTRIBUTING.md, Releases).

## Consequences

- The platform's own specs go through the same build, verification, ship and run records as component specs; deploy ends at once with `not deployable (platform)`.
- Specs written before the declaration keep no `shape:` line and are checked as before; only new specs record `shape: platform`.
- A future template-less shape would need the same opt-in and its own spec; the check makes it explicit instead of letting it slip in.
- Code that must see every shape calls `load_all()`. Calling `load()` stays the safe default.

## Not included

- Recognising the platform repo from its files or its name.
- A template for the platform repo, stamping it with `.platform-version`, or updating it through `/platform:update` or the fleet.
- Deploying anything from the platform repo.

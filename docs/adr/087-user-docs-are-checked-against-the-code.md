# ADR-087: User docs are checked against the code

**Status:** Accepted (2026-11-09, spec 161)
**Builds on:** [ADR-054](054-five-zero-interface-and-proved-migration.md) (the 5.0 interface and its tombstones)

## Context

The README quickstart and the user journey told newcomers to install only `shared` and then run `/platform:doctor` and
`/system:new`, which have lived in the `platform` and `system` plugins since 5.0. The site's getting-started page installed
those but not `shared`, which carries the `cplat` launcher. Both survived several releases, because the only checks on the
docs were link checks and single-sentence assertions per spec. A first run of a docs check found 80 problems: tombstoned
commands, an undocumented flag, a flag that does not exist, a plugin README that bootstrapped with a 4.x command, and three
getting-started paths that disagreed.

## Decision

`scripts/check-docs.py` runs in CI, `devbox run quality` and `ci-local`. On every user-facing page (README, the guides in
`docs/`, the hand-written site pages, the READMEs of live plugins) it fails on:

- a slash command that does not exist or is a tombstone (allowed in a `## … 4.x …` section or next to its replacement);
- a flag written after a command in code that the command's file does not name;
- a `/plugin install` of a plugin that is only tombstones, and a fenced install block without the starter set
  (`shared`, `system`, `component`, `platform`), defined once in the script;
- a `devbox run` recipe that neither this repo nor a template defines;
- a YAML block shaped like a system manifest that `cplat system new` would refuse;
- a spec number or criterion id in the body of a newcomer page, outside a closing "Background" section.

The quickstart lives in one file, `docs/QUICKSTART.md`; the site shows it as the first "Get started" page, and the README and
the user journey link to it. A fast test runs its own manifest through `cplat system new --no-github`. Pages that record
history carry `<!-- historical -->` and stay off the site.

## Consequences

- A renamed command, a removed flag or a new tombstone fails the pull request that leaves a page behind, not a newcomer.
- A command's file is the source of its flags: a flag `cplat` accepts but the command file never names fails the docs that
  use it, so the command file gets fixed (as `--secret-ref` of `/component:add` was).
- The check proves that names and manifests exist, not that a step behaves as described; the cluster e2e and the recorded
  journeys still cover behaviour.

## Addendum (2026-11-10, spec 173)

The spec-number rule covers every guide in `docs/`, not only the newcomer pages. The measurement records
(`PERFORMANCE.md`, `BASELINES.md`), `## … 4.x …` history sections and closing "Background" sections keep their spec numbers.

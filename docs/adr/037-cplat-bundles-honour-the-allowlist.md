# ADR-037 — cplat commands that bundle steps never widen the session's permissions

**Status:** accepted (2026-10-25, spec 100)

## Context

Every platform repo allowlists `Bash(cplat *)`. Spec 100 turns multi-command steps the coordinator ran one by one
(`git add`, `git commit -s`, `git push`, `gh issue view`, `gh pr create`; running a test recipe) into single cplat
commands to save turns. Each separate command was limited by the repo's allowlist: pushes only to the allowed branch
prefixes, `gh pr create` only where the repo allows it, no force push, no arbitrary shell. A cplat command runs under
the one `cplat *` rule, so it could do more than the allowlist permits without anyone noticing.

## Decision

- A cplat command that bundles steps runs only fixed, named operations. It never accepts a free-form command or extra
  arguments that reach a shell (`cplat quiet` takes a `devbox.json` script name and nothing else).
- Outward actions follow the same limits the allowlist sets for the separate commands: push only branches with the
  template prefixes (`feature/`, `fix/`, `chore/`, `docs/`, `refactor/`, `perf/`, `test/`, `release/`), never force;
  open a PR only when the repo's `.claude/settings.json` (or `settings.local.json`) allows `gh pr create` and does not
  deny or ask for it, else stop at a ready PR (spec 051).
- Commits made by cplat are always signed off (`-s`).

## Consequences

- Bundling saves coordinator turns without a second, wider permission path.
- A repo that tightens its allowlist also tightens the cplat bundles, as long as the bundle reads the same rule; new
  bundles must name the rule they mirror.
- The allowlist and the bundles can drift apart; the template's allowlist and these commands are tested together.

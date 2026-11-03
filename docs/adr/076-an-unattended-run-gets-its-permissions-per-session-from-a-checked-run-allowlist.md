# ADR-076: An unattended run gets its git and gh permissions per session from a checked run allowlist, never from a settings file

**Status:** Accepted (2026-11-03)
**Amends:** [ADR-037](037-cplat-bundles-honour-the-allowlist.md) (cplat bundles also honour the run allowlist); spec 131

## Context

A non-interactive `claude -p` session cannot ask for approval. When it tries an action that no allowlist grants, the
action is refused, and the run escalates after it has already spent its budget. Between 3 and 4 escalations a week were
git or `gh` actions refused this way (retro #207). The platform repo has no committed allowlist at all. Editing a user's
or a repo's settings to fix this would change files the user owns and would grant the actions to every later session too.

## Decision

1. **The run allowlist is fixed per command.** It covers only what an unattended run needs beyond file edits:
   - create and switch to the spec's feature branch;
   - stage and commit with sign-off;
   - push that branch without force;
   - `gh pr create`;
   - merge only through `cplat component ship land` (and `cplat system ship entry land`), which merge on green checks.

   `/system:ship` uses `feature/*`, because its repo branches are not known in advance.
2. **It is granted per session.** Every session of the run is started with `--allowedTools <run allowlist>` and
   `--disallowedTools <refused rules>` (force push, push to the default branch, `gh pr merge`, `gh api …merge…`,
   `cplat pr wait --merge`). This is in addition to the repo's committed allowlist. No settings file is created or
   changed.
3. **A preflight runs before anything is spent.** Before the first session it checks:
   - the repo's committed allowlist;
   - the deny and ask rules of every settings layer (managed, user, project, local) against a representative command of
     each action;
   - the git author identity, the `gh` login for the remote's host, and push access.

   A failure starts no session and prints `preflight failed: <category>: <detail>`. The run is recorded as escalated with
   the cause `environment`.
4. **cplat's bundles read the same grant.** Sessions get `CPLAT_RUN_ALLOWLIST`, and `cplat pr open` accepts its rules
   the way it accepts the settings files' allow rules (ADR-037). A deny or ask rule in a file still wins.

## Consequences

- An unattended run no longer stops on an approval nobody can give, and what it cannot be granted fails at second 0 with
  $0 spent.
- A user who wants an action refused keeps that power: a deny or ask rule anywhere makes the preflight fail with the rule
  and its file named, and it never overrides the rule.
- The refused rules are glob patterns, and a wrong pattern could refuse a legitimate push. The matcher and the patterns are
  tested together.

## Not included

- Writing or proposing changes to any settings file (making a repo's committed allowlist fit stays a template change).
- A preflight for fleet commands.

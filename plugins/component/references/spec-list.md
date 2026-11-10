# Spec: list, index, migrate

Read from `/component:spec` with no argument, `--all`, `index` or `migrate` (no tree check, no branch). One `cplat spec` call per Bash invocation.

- **(no argument) / `--all`**: run `cplat spec list`. Print the output verbatim. If it is empty, suggest `/component:spec <description>`; if `docs/backlog.md` contains `STORY-NNN` stories, suggest `/component:spec migrate`.
- **`index`**: run `cplat spec index`, show `git diff --stat docs/backlog.md`, and commit it as `docs(backlog): refresh spec index` once the user agrees.
- **`migrate`**: converts legacy `STORY-NNN` stories in `docs/backlog.md` into `docs/specs/<NNN>-<slug>/spec.md` (numbers kept, criteria numbered `AC-<NNN>.<n>`, legacy metadata and plan links kept; the backlog keeps every non-story section and gets the generated table).
  1. `git status --porcelain` must be empty so that the diff shows only the migration.
  2. Run `cplat spec migrate` (dry run) and show the output verbatim.
  3. After the user confirms: `git checkout -b docs/migrate-specs` (from `main`), run `cplat spec migrate --write`, then `cplat spec check`. Show `git diff --stat`, and commit `docs(spec): migrate backlog stories to docs/specs` on the user's OK. Migrated specs keep their status: `done` stays `done`, open stories become `draft` (they need review and approval before planning).

Never edit specs from these modes, since an edit needs a new approval; to change one, use `/component:spec --amend <id> <change>`.

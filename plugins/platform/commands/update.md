---
description: "Pull the latest platform skeleton (CI, Dockerfile, devbox, CLAUDE.md) into this repo on a review branch; --migrate converts a 4.x repo to 5.0. Usage: /platform:update [--ref <tag>] [--data k=v] [--migrate]"
---

Update the current repo with the platform script. **Request:** $ARGUMENTS

`cplat` is on the Bash PATH while the shared plugin is enabled and runs the platform script at the version your plugins were installed from (no fetch); one call per Bash invocation:

```bash
cplat platform update <ARGS>
```

With `--ref <tag>`, prefix every call with `CPLAT_REF=<tag>` (for example `CPLAT_REF=v5.0.0 cplat platform update --ref v5.0.0 --dry-run`) so the templates come from that release.

**`--migrate` (4.x → 5.0).** A repo stamped below 5.0 is refused without `--migrate` (`this repo is on platform <old>: 5.0 changes its files and plugins`). With it, the update also converts the two model files of a gitops-app repo (4.x kept the application and its services apart) into one `system.yaml`, proves that the 5.0 render is byte-identical to 4.7 (any difference stops the migration and changes nothing), and switches the repo's plugins to the 5.0 nouns. A component repo only gets the template update and the plugin switch. On an already migrated repo `--migrate` does nothing extra. Always preview a migration with `--dry-run --migrate`: it prints the `system.yaml` it would write. Comments of the old files are not carried over; say so.

1. **Preview** with `--dry-run`; show it verbatim. Stop on errors (they carry a `fix:` line; typical: dirty tree, no `.copier-answers.yml`, a key that cannot be converted).
2. **Run** without `--dry-run` (the user asked for the update; nothing is pushed).
3. **Report** the script's output. Then run the repo's own checks if `devbox` is available (`devbox run quality && devbox run test-fast`) and report failures without fixing them. Relay verbatim the `moved to ci-extra` line (gates the repo had in `ci` now live in its own `ci-extra` recipe), the lines about `.claude/settings.json` entries kept or removed by the platform, the `plugins added: …; removed: …` line, and every `replaced …` line: each names a customisation the template's version overwrote and where it belongs now (spec 086). With `--json`, an empty `lost` means nothing the repo added was lost. Relay the `devbox.json` lines as they are: what was kept, and every replaced template recipe with the project's old line (spec 060). `README.md` is project-owned and never updated; pass on the command that shows the template's version when the output prints it. Pass on any `GITOPS_TOKEN` or auto-merge step (spec 062) verbatim. After a migration, tell the user that Claude Code must be restarted to load the new plugins.

**Versions.** The update re-renders with the new renderer and prints a block per environment of the versions that change (`cplat platform versions` shows the whole table). Only dev follows the new minor and patch pins; staging and prod keep their held pins until `/resource:upgrade <name> --to <major> --env <env>` moves them. After the PR is merged and synced, run `cplat platform update --verify [--context [ENV=]CTX]` to check the operators once per cluster and every environment; relay its output verbatim.

Rules: never push or open a PR unless asked; never edit the update's result by hand — the template is the source of truth.

> If a step fails because a platform template, script or command misbehaves (not because of the user's code), stop, summarize it in two lines and offer `/issue:report` so the user can file it. Never file anything without their OK.

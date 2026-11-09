---
description: "Pull the latest platform skeleton (CI, Dockerfile, devbox, CLAUDE.md) into this repo on a review branch; --migrate converts a 4.x repo to 5.0. Usage: /platform:update [--ref <tag>] [--data k=v] [--migrate]"
---

Update the current repo with the platform script. **Request:** $ARGUMENTS

A rule marked **Hard rule:** is never departed from. Any other rule is a practice: where its stated purpose does not apply, depart from it and name each departure and its reason in one line of your report.

`cplat` is on the Bash PATH and runs the platform script at your plugins' version; one call per Bash invocation, its output read whole (never piped into `grep`, `head` or `tail`, because its last lines carry the decisions and next steps; use `--json` where offered):

```bash
cplat platform update <ARGS>
```

With `--ref <tag>`, prefix every call with `CPLAT_REF=<tag>` so the templates come from that release.

**`--migrate` (4.x → 5.0).** A repo stamped below 5.0 is refused without `--migrate`. With it, the update also converts the two model files of a gitops-app repo into one `system.yaml`, proves that the 5.0 render is byte-identical to 4.7 (any difference stops the migration and changes nothing), and switches the repo's plugins to the 5.0 nouns. Always preview a migration with `--dry-run --migrate`, because it prints the `system.yaml` it would write. Comments of the old files are not carried over; say so.

1. **Preview** with `--dry-run`; show it verbatim. Stop on errors (they carry a `fix:` line).
2. **Run** without `--dry-run` (nothing is pushed).
3. **Report** the script's output. Then run the repo's own checks if `devbox` is available (`devbox run quality && devbox run test-fast`) and report failures without fixing them. Relay verbatim the `moved to ci-extra` line, the lines about `.claude/settings.json` entries kept or removed, the `plugins added: …; removed: …` line, every `replaced …` line (a customisation the template overwrote and where it belongs now), the `devbox.json` lines and any `GITOPS_TOKEN` or auto-merge step. With `--json`, an empty `lost` means nothing the repo added was lost. `README.md` is project-owned and left alone; pass on the command that shows the template's version when the output prints it. After a migration, tell the user that Claude Code needs a restart to load the new plugins.

**Versions.** The update prints a block per environment of the versions that change (`cplat platform versions` shows the whole table). Dev follows the new minor and patch pins; staging and prod keep their held pins until `/resource:upgrade <name> --to <major> --env <env>` moves them. After the PR is merged and synced, run `cplat platform update --verify [--context [ENV=]CTX]` to check the operators once per cluster and every environment; relay its output verbatim.

Never push or open a PR, because the update ends on a review branch the user reviews first. Never edit the update's result by hand, because the template is the source of truth.

> If a platform template, script or command misbehaves (not the user's code), stop, summarize it in two lines and offer `/issue:report`. **Hard rule:** never file an issue without the user's OK, because the platform repository is public; a `platform` escalation is the one issue the platform files itself (ADR-033).

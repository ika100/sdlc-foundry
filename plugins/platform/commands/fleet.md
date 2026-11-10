---
description: "Bring every repo built from the platform up to the current release: one PR per repo, merged on green CI when routine. Usage: /platform:fleet update [--owner <o>] [--only <owner/name>] [--ref <tag>] [--timeout <s>] [--dry-run]"
---

Update the fleet of platform repos. **Request:** $ARGUMENTS

A rule marked **Hard rule:** is never departed from. Any other rule is a practice: where its stated purpose does not apply, depart from it and name each departure and its reason in one line of your report.

`cplat` is on the Bash PATH and runs the platform script at your plugins' version; one call per Bash invocation, its output read whole (never piped into `grep`, `head` or `tail`, because its last lines carry the decisions and next steps; use `--json` where offered):

```bash
cplat platform fleet update <ARGS>
```

With `--ref <tag>`, prefix every call with `CPLAT_REF=<tag>` so that the update comes from that release.

1. **Preview** with `--dry-run` first; show the table verbatim. Stop on errors (they carry a `fix:` line). For repos on 4.x the preview says `5.0 migration: merges on green CI when proved`: the update runs `--migrate` for them.
2. **Run** without `--dry-run` once the user wants it. A run waits for each PR's CI and can outlast one Bash call: start it in the background and read its output until it ends.
3. **Report** the table, every `next:` line under a repo and the exit status verbatim (0: all up to date or merged; 1: some left open or failed). For each `left open` row, name the reason and the PR link. A repo whose migration failed is `failed`, with no PR and nothing changed.

Never merge, label, comment on or edit a PR by hand, because the labelled open PR and its comment are the work item. Never resolve a conflict or restore a customisation for the user, because the repo's owner decides what stays.

> If a platform template, script or command misbehaves (not the user's code), stop, summarize it in two lines and offer `/issue:report`. **Hard rule:** never file an issue without the user's OK, because the platform repository is public; a `platform` escalation is the one issue the platform files itself (ADR-033).

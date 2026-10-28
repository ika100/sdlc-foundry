---
description: "Bring every repo built from the platform up to the current release: one PR per repo, merged on green CI only when routine. Usage: /platform:fleet update [--owner <o>] [--only <owner/name>] [--ref <tag>] [--timeout <s>] [--dry-run]"
---

Update the fleet of platform repos. **Request:** $ARGUMENTS

`cplat` is on the Bash PATH while the shared plugin is enabled and runs the platform script at the version your plugins were installed from (no fetch); one call per Bash invocation:

```bash
cplat platform fleet update <ARGS>
```

With `--ref <tag>`, prefix every call with `CPLAT_REF=<tag>` (for example `CPLAT_REF=v5.0.0 cplat platform fleet update --ref v5.0.0 --dry-run`) so the update comes from that release; `--ref` must name the release the command runs.

1. **Preview** with `--dry-run` first; show the table verbatim. Stop on errors (they carry a `fix:` line; typical: `gh` not logged in). For repos on 4.x the preview says `5.0 migration: merges on green CI when proved`: the update runs `--migrate` for them.
2. **Run** without `--dry-run` once the user wants it. A run waits for each PR's CI and can outlast one Bash call: start it in the background and read its output until it ends.
3. **Report** the table, every `next:` line under a repo and the exit status verbatim (0: every repo up to date or merged; 1: some repo is left open or failed). For each `left open` row, name the reason and the PR link. A repo whose migration failed is `failed` with no PR and nothing changed; its first error line says why, and the user fixes it by hand.

Rules: never merge, label, comment on or edit a PR by hand; the labelled open PR and its comment are the work item. Never resolve a conflict or restore a customisation for the user unless asked.

> If a step fails because a platform template, script or command misbehaves (not because of the user's code), stop, summarize it in two lines and offer `/issue:report` so the user can file it. Never file anything without their OK.

---
description: "Build the weekly platform retro from the run store and post it. Usage: /platform:retro [--week W] [--json] [--out DIR] | propose --dir DIR | post [--dir DIR]"
---

Run the weekly platform retro. **Request:** $ARGUMENTS

A rule marked **Hard rule:** is never departed from. Any other rule is a practice: where its stated purpose does not apply, depart from it and name each departure and its reason in one line of your report.

`cplat` is on the Bash PATH; make one call per Bash invocation and read its output whole (never piped into `grep`, `head` or `tail`, because its last lines carry the decisions and next steps; use `--json` where offered).

1. **Report**: `cplat platform retro <ARGS>` without a subcommand builds the report of the last complete week and prints it; `--out DIR` also writes it to `DIR`. Show it verbatim.
2. **Propose**: `cplat platform retro propose --dir DIR` lets a headless Claude write `DIR/proposals.json`.
3. **Post**: `cplat platform retro post [--dir DIR]` checks the proposals, posts the public issue and stores the full report in the run store. **Hard rule:** never run it unless the user asked for it, because the issue it posts is public; show what it will post first.

> If a platform template, script or command misbehaves (not the user's code), stop, summarize it in two lines and offer `/issue:report`. **Hard rule:** never file an issue without the user's OK, because the platform repository is public; a `platform` escalation is the one issue the platform files itself (ADR-033).

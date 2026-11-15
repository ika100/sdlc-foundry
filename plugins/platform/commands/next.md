---
description: "Where you are in the process and what waits for you, as choices. Usage: /platform:next [--ascii]"
---

Show where the delivery process stands and what waits for the person. **Arguments:** $ARGUMENTS

A rule marked **Hard rule:** is never departed from. Any other rule is a practice: where its stated purpose does not apply, depart from it and name each departure and its reason in one line of your report.

`cplat` is on the Bash PATH. Run `cplat next --json $ARGUMENTS`.

When `judgement_wanted` is true, write for each entry of `drafts` one `you_get` line (what the person gets, from its `problem`) and its most important `assumption`, as JSON keyed by the draft's `spec`, to a temp file, and run the command again with `--judgement <file>`, so that the screen says in plain words what each draft means.

Then follow `how`.

**Hard rule:** never choose an option for the person, because approval exists only in the person's own words.

Read `cplat`'s output whole, never through `grep`, `head` or `tail`, because its last lines carry the decisions and fixes; use `--json` where offered.

> If a platform template, script or command misbehaves (not the user's code), stop, summarize it in two lines and offer `/issue:report`. **Hard rule:** never file an issue without the user's OK, because the platform repository is public; a `platform` escalation is the one issue the platform files itself (ADR-033).

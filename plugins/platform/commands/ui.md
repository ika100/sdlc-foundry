---
description: "Start the local console: Inbox, Board and System in the browser. Usage: /platform:ui [--no-open] [--port N]"
---

Start the local console. **Arguments:** $ARGUMENTS

A rule marked **Hard rule:** is never departed from. Any other rule is a practice: where its stated purpose does not apply, depart from it and name each departure and its reason in one line of your report.

`cplat` is on the Bash PATH. Run `cplat platform ui $ARGUMENTS` in the background (Bash `run_in_background`), because it serves until stopped.

Read its first output lines and tell the user the URL (`http://127.0.0.1:<port>/`). Run it from a `gitops-app` clone; without `applications/<system>/system.yaml` it says so and exits. The console reads the system and starts `cplat headless` runs, each after the user confirms; stop it with the user menu or by stopping the background task. More: `docs/console.md`.

Read `cplat`'s output whole, never through `grep`, `head` or `tail`, because its last lines carry the decisions and fixes; use `--json` where offered.

> If a platform template, script or command misbehaves (not the user's code), stop, summarize it in two lines and offer `/issue:report`. **Hard rule:** never file an issue without the user's OK, because the platform repository is public; a `platform` escalation is the one issue the platform files itself (ADR-033).

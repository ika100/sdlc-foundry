---
description: "Show the platform's run records: outcomes, agent metrics, tokens and cost. Usage: /platform:runs [report] [--since DAYS] [--repo R] [--agents] [--json]"
---

Report on the private run store. **Request:** $ARGUMENTS

A rule marked **Hard rule:** is never departed from. Any other rule is a practice: where its stated purpose does not apply, depart from it and name each departure and its reason in one line of your report.

`cplat` is on the Bash PATH; make one call per Bash invocation and read its output whole (never piped into `grep`, `head` or `tail`, because its last lines carry the decisions and next steps; use `--json` where offered).

Show the output of `cplat platform runs report <ARGS>` verbatim. Other forms: `cplat platform runs report --agents [--by-version] [--agent NAME]`, `cplat platform runs report --benchmarks`, `cplat platform runs journey begin|stage <id> start|end|wait person|external start|end|pr <url>|round <kind> --cause C|show|end --outcome O` (record a journey's stages, waits, PRs and extra rounds; `--at <UTC time>` back-dates), `cplat platform runs usage <run_id>` (tokens and cost of one run), `cplat platform runs report --pr <run-id>` (the "How this was built" block of one run on this machine, as `cplat pr open` adds it to a build PR), and `cplat platform runs flush` (send buffered records). Without a reachable store, `cplat platform doctor` says what is missing; `cplat platform runs init <owner/name>` creates one. Do not paste the run store's content into public issues, because the store is private.

> If a platform template, script or command misbehaves (not the user's code), stop, summarize it in two lines and offer `/issue:report`. **Hard rule:** never file an issue without the user's OK, because the platform repository is public; a `platform` escalation is the one issue the platform files itself (ADR-033).

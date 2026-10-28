---
description: "Show the platform's run records: outcomes, agent metrics, tokens and cost. Usage: /platform:runs [report] [--since DAYS] [--repo R] [--agents] [--json]"
---

Report on the private run store. **Request:** $ARGUMENTS

`cplat` is on the Bash PATH while the shared plugin is enabled; one call per Bash invocation:

```bash
cplat platform runs report <ARGS>
```

Show the report verbatim. Other forms the user may ask for: `cplat platform runs report --agents [--by-version] [--agent NAME]` (agent metrics), `cplat platform runs report --benchmarks`, `cplat platform runs usage <run_id>` (tokens and estimated cost of one run), and `cplat platform runs flush` (send buffered records to the store). Without a reachable store, `cplat platform doctor` says what is missing; `cplat platform runs init <owner/name>` creates the private store. The run store is private: do not paste its content into public issues.

> If a step fails because a platform template, script or command misbehaves (not because of the user's code), stop, summarize it in two lines and offer `/issue:report` so the user can file it. Never file anything without their OK.

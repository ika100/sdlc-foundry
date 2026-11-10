---
description: "Create a cluster repo that owns a cluster's shared operators and lists its systems. Usage: /cluster:new <name> [--org <owner>] [--public] [--no-github] [--server <url>] [--operators <a,b>] [--secret-store <name>]"
---

Create a cluster repo with the platform script (all logic and tests live in `scripts/cplat`). **Request:** $ARGUMENTS

A rule marked **Hard rule:** is never departed from. Any other rule is a practice: where its stated purpose does not apply, depart from it and name each departure and its reason in one line of your report.

`<name>` is lowercase DNS-style (at most 40 characters). The repo is private (`--public` is the user's own request) and starts with a `cluster.yaml` that lists no systems. Pass the cluster's properties when the user names them: `--server <url>`, `--operators <a,b>` (the cluster-level operators) and `--secret-store <name>` (needs `external-secrets` in `--operators`). Without them `cluster.yaml` gets the defaults and is edited later.

One `cplat` call per Bash invocation:

```bash
cplat cluster new <ARGS>
```

Read `cplat`'s output whole, never through `grep`, `head` or `tail`, because its last lines carry the decisions and fixes; use `--json` where offered.

1. **Preview.** Run it with `--dry-run` and the user's arguments. Show the output verbatim. If it exits non-zero, show the error and its `fix:` line and stop; do not retry with guesses, because a guess can create the wrong repo.
2. **Run.** The user's request is the confirmation. Run the same command without `--dry-run`.
3. **Report.** Relay the script's output including the next steps; add nothing else. Details: `docs/CLUSTERS.md`.

An existing repo of that name changes nothing.

> If a platform template, script or command misbehaves (not the user's code), stop, summarize it in two lines and offer `/issue:report`. **Hard rule:** never file an issue without the user's OK, because the platform repository is public; a `platform` escalation is the one issue the platform files itself (ADR-033).

---
description: "Create a cluster repo that owns a cluster's shared operators and lists its systems. Usage: /cluster:new <name> [--org <owner>] [--public] [--no-github] [--server <url>] [--operators <a,b>] [--secret-store <name>]"
---

Create a cluster repo with the platform script (all logic and tests live in `scripts/cplat`). **Request:** $ARGUMENTS

`<name>` is lowercase DNS-style (at most 40 characters). The repo is private unless the user asked for `--public`, and starts with a `cluster.yaml` that lists no systems. Pass the cluster's properties when the user names them: `--server <url>` (the API server Argo CD deploys to), `--operators <a,b>` (the cluster-level operators; the first commit then holds their rendered applications) and `--secret-store <name>` (needs `external-secrets` in `--operators`). Without them `cluster.yaml` gets the defaults and is edited later.

`cplat` is on the Bash PATH while the shared plugin is enabled; one call per Bash invocation:

```bash
cplat cluster new <ARGS>
```

1. **Preview.** Run it with `--dry-run` and the user's arguments. Show the output verbatim. If it exits non-zero, show the error and its `fix:` line and stop; do not retry with guesses.
2. **Run.** The user's request is the confirmation. Run the same command without `--dry-run`.
3. **Report.** Relay the script's output including the next steps; add nothing else. Details: `docs/CLUSTERS.md`.

Rules: never create a public repo unless the user asked; never overwrite a non-empty directory; an existing repo of that name changes nothing.

> If a step fails because a platform template, script or command misbehaves (not because of the user's code), stop, summarize it in two lines and offer `/issue:report` so the user can file it. Never file anything without their OK.

---
description: "Preflight check of the platform setup (tools, gh scopes, Docker, kube context, plugin and platform versions) with a fix per problem. Usage: /platform:doctor"
---

Run the platform doctor with one Bash call, `cplat platform doctor`.

A rule marked **Hard rule:** is never departed from. Any other rule is a practice: where its stated purpose does not apply, depart from it and name each departure and its reason in one line of your report.

Show the output verbatim. If it reports outdated plugins, say plainly that Claude Code needs a restart to load updated plugin prompts. On a cluster with scaled instances it also lists `operator keda`, `operator metrics-server` and `resource metrics`. With `--context [ENV=]CTX` it also reads that cluster: each operator the environment needs is listed with the expected version, the installed version and its CRD versions, marked `ok`, `missing`, `older` or `newer`; `missing`, or `older` by a major, makes the exit code non-zero. A `plugins (4.x)` or `system.yaml` warning means the repo is still on 4.x: its fix is `cplat platform update --migrate`. Offer to run the `fix:` commands that are safe (`gh auth refresh -s …`, `claude plugin update …`, `open -a Docker`); never run anything that touches a non-local kube context, because that could change a cluster the user did not mean.

Read `cplat`'s output whole, never through `grep`, `head` or `tail`, because its last lines carry the decisions and fixes; use `--json` where offered.

> If a platform template, script or command misbehaves (not the user's code), stop, summarize it in two lines and offer `/issue:report`. **Hard rule:** never file an issue without the user's OK, because the platform repository is public; a `platform` escalation is the one issue the platform files itself (ADR-033).

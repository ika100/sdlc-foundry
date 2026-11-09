---
description: "Create a component repo from its template plus a private GitHub repo. Usage: /component:new <name> <description> [--type service|website|library] [--lang python|java|go|typescript] [--system OWNER/REPO] [--public] [--data k=v]"
---

Create a repo with the platform script (all logic and tests live in `scripts/cplat`). **Request:** $ARGUMENTS

A rule marked **Hard rule:** is never departed from. Any other rule is a practice: where its stated purpose does not apply, depart from it and name each departure and its reason in one line of your report.

One `cplat` call per Bash invocation:

```bash
cplat component new <ARGS>
```

Read `cplat`'s output whole, never through `grep`, `head` or `tail`, because its last lines carry the decisions and fixes; use `--json` where offered.

Without `--type` and `--lang` the component is a `service` in `python`; an invalid pair fails and lists the valid ones (show them). `--system OWNER/REPO` links the repo to its system's gitops repo and creates it under OWNER (or the owner `--org` names). The 4.x flags (`--web`, `--gitops`, `--library`, `--type <shape id>`, `--app`) fail naming their replacement: show that line and use it.

With `--ref <tag>`, prefix every call with `CPLAT_REF=<tag>` so the templates come from that release.

1. **Preview.** Run it with `--dry-run` and the user's arguments (quote the description words). Show the output verbatim. If it exits non-zero, show the error and its `fix:` line and stop; do not retry with guesses, because a guess can create the wrong repo. A missing name/description is the one question you may ask the user, once, in plain text, since the script cannot guess it.
2. **Run.** The preview lists steps marked `[outward]` (GitHub repo creation, topic). Do not ask again for them, because the user's request to create the repo is the confirmation; ask when the preview shows something they did not ask for. Run the same command without `--dry-run`.
3. **Report.** Relay the script's *What happened / Next / To undo* output; add nothing else. The repo is ready to work in as soon as it is created: development starts on a feature branch, so never wait for the bootstrap pipeline on `main`, because the feature branch does not depend on it. The first feature is planned before it is built: `/component:spec "<description>"` in the new repo, then `/component:plan <NNN>` and `/component:build <NNN>`; never suggest building it without a plan, because the plan fixes what the build does.

With `gh` missing the script prints the GitHub commands instead of failing.

> If a platform template, script or command misbehaves (not the user's code), stop, summarize it in two lines and offer `/issue:report`. **Hard rule:** never file an issue without the user's OK, because the platform repository is public; a `platform` escalation is the one issue the platform files itself (ADR-033).

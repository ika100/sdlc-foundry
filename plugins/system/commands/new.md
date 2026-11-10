---
description: "Create a system from a manifest: the gitops-app repo plus every component repo. Usage: /system:new <manifest> [--resume] [--public] [--no-github]"
---

Create a system with the platform script. **Request:** $ARGUMENTS

A rule marked **Hard rule:** is never departed from. Any other rule is a practice: where its stated purpose does not apply, depart from it and name each departure and its reason in one line of your report.

The manifest is a YAML file: `system` (name of the gitops-app repo), `owner`, optional `org` and `visibility`, and `components` (each with `name`, `description`, `type`, `lang`, optional `data` of template options). A component with `shape` is refused: use `type` and `lang`. If the user has no manifest yet, write one from what they describe (valid pairs: service/python, service/java, service/go, website/typescript, library/python; the gitops-app repo is implicit) and show it before using it.

Run `cplat` one call per Bash invocation. Read `cplat`'s output whole, never through `grep`, `head` or `tail`, because its last lines carry the decisions and fixes; use `--json` where offered.

```bash
cplat system new <ARGS>
```

1. **Preview.** Run it with `--dry-run` and the user's arguments. Show the output verbatim. If it exits non-zero, show the error and its `fix:` line and stop; do not retry with guesses, because a wrong guess creates the wrong repos.
2. **Run.** The user's request is the confirmation, so the user is asked once; a preview that shows something they did not ask for goes back to them first. Run the same command without `--dry-run`.
3. **If it fails midway**, nothing is rolled back. Show the error (it lists what was created) and offer `--resume`, which skips the repos that exist and continues.
4. **Report.** Relay the script's *What happened / Next / To undo* output; add nothing else. The system's first feature starts with a system spec: `/system:spec` in the gitops-app repo, then `/system:plan` and `/system:ship` (components build their part from the plan with `/component:spec --from-plan`, never from a free-text request, because the plan carries the contract).

Never create public repos without `--public` or `visibility: public`, because making code public is the user's choice. Never overwrite a non-empty directory, so that no user file is lost.

> If a platform template, script or command misbehaves (not the user's code), stop, summarize it in two lines and offer `/issue:report`. **Hard rule:** never file an issue without the user's OK, because the platform repository is public; a `platform` escalation is the one issue the platform files itself (ADR-033).

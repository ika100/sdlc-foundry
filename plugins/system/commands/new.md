---
description: "Create a whole system from a manifest: the gitops-app repo with its system.yaml plus every component repo. Usage: /system:new <manifest> [--resume] [--public] [--no-github]"
---

Create a system with the platform script (all logic and tests live in `scripts/cplat`). **Request:** $ARGUMENTS

The manifest is a YAML file: `system` (name of the gitops-app repo), `owner`, optional `org` and `visibility`, and `components` (each with `name`, `description`, `type`, `lang`, optional `data` of template options). A component with `shape` is refused: use `type` and `lang`. If the user has no manifest yet, write one from what they describe (valid pairs: service/python, service/java, service/go, website/typescript, library/python; the gitops-app repo is implicit) and show it before using it.

`cplat` is on the Bash PATH while the shared plugin is enabled and runs the platform script at the version your plugins were installed from (no fetch); one call per Bash invocation:

```bash
cplat system new <ARGS>
```

1. **Preview.** Run it with `--dry-run` and the user's arguments. Show the output verbatim. If it exits non-zero, show the error and its `fix:` line and stop; do not retry with guesses.
2. **Run.** The preview lists the repos in creation order and the `[outward]` steps. The user's request is the confirmation; do not ask again unless the preview shows something they did not ask for. Run the same command without `--dry-run`. It takes a few minutes (one bootstrap per repo).
3. **If it fails midway**, nothing is rolled back. Show the error (it lists what was created) and offer `--resume`, which skips the repos that exist and continues, including the pull request that adds the components to `system.yaml`.
4. **Report.** Relay the script's *What happened / Next / To undo* output; add nothing else. The system's first feature starts with a system spec: `/system:spec` in the gitops-app repo, then `/system:plan` and `/system:ship` (components build their part from the plan with `/component:spec --from-plan`, never from a free-text request).

Rules: never create public repos unless the user asked (`--public` or `visibility: public`); never overwrite a non-empty directory; if `gh` is missing the script renders locally and prints the GitHub commands instead.

> If a step fails because a platform template, script or command misbehaves (not because of the user's code), stop, summarize it in two lines and offer `/issue:report` so the user can file it. Never file anything without their OK.

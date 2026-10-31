---
description: "Release the platform: checks, release PR, CI, merge, tag and GitHub release, resumable, asking before the merge and the tag. Usage: /platform:release [--version X.Y.Z] [--dry-run]"
---

Release the platform. **Request:** $ARGUMENTS

`cplat` is on the Bash PATH while the shared plugin is enabled; one call per Bash invocation:

```bash
cplat platform release <ARGS>
```

The command keeps no state file: it reads its progress from git and GitHub and continues at the first step not done, so running it again resumes an interrupted release. The CI waits can outlast one Bash call: start it in the background and read its output until it ends.

1. **Run** `cplat platform release $ARGUMENTS`. Show the output verbatim. Exit 0: a dry run was printed or the release finished (`RELEASED:`).
2. **Exit 3** is a stop at a confirmation: the output ends with a `CONFIRM: merge` or `CONFIRM: tag` block. Show the block and ask the user whether to go on. Only when the user agrees in this conversation, run the command again with the same `--version` (if one was given) plus `--confirm merge` or `--confirm tag`, matching the stop. If the user declines, stop and say that running `/platform:release` again resumes here.
3. **Exit 1**: report the `ERROR:` line (and its `fix:` line, if any) and stop. Exit 2 is a usage error: show it and stop.

Rules: never merge, tag, push or create a release by hand. Never pass `--confirm` without the user's yes.

> If a step fails because a platform template, script or command misbehaves (not because of the user's code), stop, summarize it in two lines and offer `/issue:report` so the user can file it. Never file anything without their OK.

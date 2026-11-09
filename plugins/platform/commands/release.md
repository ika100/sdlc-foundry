---
description: "Release the platform: checks, release PR, CI, merge, tag, GitHub release; resumable, asks before merge and tag. Usage: /platform:release [--version X.Y.Z] [--dry-run]"
---

Release the platform. **Request:** $ARGUMENTS

A rule marked **Hard rule:** is never departed from. Any other rule is a practice: where its stated purpose does not apply, depart from it and name each departure and its reason in one line of your report.

`cplat` is on the Bash PATH; make one call per Bash invocation and read its output whole (never piped into `grep`, `head` or `tail`, because its last lines carry the decisions and next steps; use `--json` where offered). The command keeps no state file and continues at the first step not done, so running it again resumes an interrupted release. CI waits can outlast one Bash call: start it in the background and read its output until it ends.

1. **Run** `cplat platform release $ARGUMENTS`. Show the output verbatim. Exit 0: a dry run was printed or the release finished (`RELEASED:`).
2. **Exit 3** is a stop at a confirmation: the output ends with a `CONFIRM: merge` or `CONFIRM: tag` block. Show the block and ask the user whether to go on. Once the user agrees in this conversation, run the command again with the same `--version` (if one was given) plus `--confirm merge` or `--confirm tag`, matching the stop. If the user declines, stop; running `/platform:release` again resumes here.
3. **Exit 1**: report the `ERROR:` line (and its `fix:` line, if any) and stop. Exit 2 is a usage error: show it and stop.

Never merge, tag, push or create a release by hand, because the command checks each step first. Never pass `--confirm` without the user's yes, because a merge or a tag cannot be undone.

> If a platform template, script or command misbehaves (not the user's code), stop, summarize it in two lines and offer `/issue:report`. **Hard rule:** never file an issue without the user's OK, because the platform repository is public; a `platform` escalation is the one issue the platform files itself (ADR-033).

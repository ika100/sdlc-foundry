---
description: "Build the weekly platform retro from the run store and post it. Usage: /platform:retro [--week W] [--json] [--out DIR] | propose --dir DIR | post [--dir DIR]"
---

Run the weekly platform retro. **Request:** $ARGUMENTS

`cplat` is on the Bash PATH while the shared plugin is enabled; one call per Bash invocation:

```bash
cplat platform retro <ARGS>
```

1. **Report**: without a subcommand it builds the report of the last complete week (reads only) and prints it; `--out DIR` also writes it to `DIR`. Show it verbatim.
2. **Propose**: `cplat platform retro propose --dir DIR` lets a headless Claude write `DIR/proposals.json` (always exit 0).
3. **Post**: `cplat platform retro post [--dir DIR]` checks the proposals, posts the public issue and stores the full report in the run store. It is public: only run it when the user asked for it, and show what it will post first.

> If a step fails because a platform template, script or command misbehaves (not because of the user's code), stop, summarize it in two lines and offer `/issue:report` so the user can file it. Never file anything without their OK.

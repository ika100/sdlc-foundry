# Build: after a red round (spec 102)

Read by `/component:build` Phase 3 after each red `cplat quiet ci`.

1. Run `cplat budget attempt ci --failing <n> --names <a,b> --error-file <the gate's log>` (n = failing checks, names = their names).
2. Exit 3 means the same failure came back twice without progress: it printed the reason and, in a ship run, escalated. Stop the build and report that reason.
3. Exit 0: go on with the next fix round.

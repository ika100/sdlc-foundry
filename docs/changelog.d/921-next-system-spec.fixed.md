**`cplat next` shows the next step of an approved system spec in a gitops repo (#921).** Right after a system spec was approved,
`cplat next` in the gitops repo said "Nothing is waiting for you", although the spec still needed `/system:plan <n>` and then
`/system:ship <n>`. An approved system spec now places the bar at Build and recommends `/system:plan <n>` while it has no
`docs/plan/<id>.md`, and `/system:ship <n>` once it is planned and no system ship runs it, or to resume a stopped one. A running
system ship or a done spec waits for nothing.

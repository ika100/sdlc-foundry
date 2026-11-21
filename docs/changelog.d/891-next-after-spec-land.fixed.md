**`cplat next` puts an approved spec that nothing builds at Build and no longer waits 20 s for the run queue (#891).** Right after
`cplat spec land` of an approved spec without a plan or build, `cplat next` showed Build and Dev as done, placed "you are here" at
Staging and recommended releasing the spec documents; it also reported the run queue unreadable after waiting 20 s. Now an approved
spec of a component repo that is not running, queued or stopped places the bar at Build and recommends `/component:ship <n>` (or
`/component:plan <n>` when it has no plan), a commit that changes only `docs/specs/` is no release change, and the run queue reads only
this repo's runs (it built a row for every run of every repo in the run store, each of which may ask GitHub).

# Build: the user approves an acceptance-test change

Read from `/component:build` when `cplat spec test-diff` exited 1 and the user, shown the file and the reason, approves the change.

**Hard rule:** Only the user approves; never decide yourself that a change is fine, attended or not, because a changed test is a changed spec. Record the approval, then go on where the build stopped:

```bash
cplat spec test-diff $RED --approve <file>... --task <task> --reason '<the user's words>'
```

It records each file's current content for the red commit `$RED` and adds an `approved_test_diffs` entry to the run record, which the PR's "How this was built" block lists. Later `cplat spec test-diff $RED` runs report the file as `approved by the user` and pass; any further change to it is flagged again and needs a new approval.

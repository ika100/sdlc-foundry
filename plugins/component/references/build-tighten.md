# Build: tighten an acceptance test the reviewer found looser than its criterion

Read from `/component:build` Phase 4 when the reviewer's `NOT MET` names a criterion with `TEST LOOSER`: its acceptance test checks less than the criterion as written. Spec 165 decides this by default: the test is tightened to the criterion, without asking the user, and the PR lists it.

1. **tester** (`agents.tester`): "**Acceptance mode.** Tighten only the tests of `<AC>` in `<file>` so that they assert the criterion as written: `<the reviewer's reason>`. Keep every test, assertion and criterion id; add no skip; change nothing else. Commit as `test(<slug>): tighten <AC> to its criterion`." Brief: the criterion in full and the file.
2. `cplat spec test-diff $RED --tighten <file>... --task <task> --reason '<AC>: <the reviewer's reason>'`. Exit 1 (a test, an assertion or a criterion id gone, or a skip added) → the change is not a tightening: `git revert --no-edit HEAD` and escalate as a changed test (the user decides, `build-test-approval.md`).
3. `cplat quiet test-fast`. A tightened test that fails now is a criterion the code does not meet: it goes to a coder of a covering task like any `NOT MET` item (`cplat platform runs agent fix-round verification --task <task>`).
4. The reviewer runs again (a new cycle); pass it `TIGHTENED`: each file with its reason, which it lists in `verification.md`.

**Hard rule:** Never loosen, delete or skip an acceptance test this way, because that is always the user's decision.

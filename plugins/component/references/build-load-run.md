# Build: flaky under load

Read from `/component:build` 2.6 on exit 3.

1. **tester** (`agents.tester`): "**Harness mode.** Flaky under load: `<each test>`; the runs' failure output is in the logs `cplat quiet` printed. Fix only fixtures, helpers, fakes and process clean-up, in files that are not frozen, so that the tests pass on every run. **Hard rule:** never change an assertion, because the assertions are the approved criteria."
2. `cplat spec test-diff $RED`; exit 1 → the person approves as in `build-test-approval.md`.
3. Run the repeated run again; after 2 rounds `cplat platform runs end --outcome escalated --reason 'flaky under load: <tests>'`.

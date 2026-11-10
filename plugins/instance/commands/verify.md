---
description: "Run the component's smoke tests against one of its instances. Usage: /instance:verify [<env>] [--base-url URL] [--json]"
---

Run the smoke tests of the current component repo. **Request:** $ARGUMENTS

A rule marked **Hard rule:** is never departed from. Any other rule is a practice: where its stated purpose does not apply, depart from it and name each departure and its reason in one line of your report.

```bash
cplat instance verify <ARGS>
```

The environment defaults to `dev`. Without `--base-url` the URL comes from the linked system's model for any environment the component has an instance in. Show the output verbatim; the exit code is the result (0 passed). On a failure report the failing check and wait for the user to ask for a fix; the script retries once (`--no-retry` skips that). Outside `dev` the smoke is read-only (#474): writing tests are left out, and a run in which no read-only test passed is `not run` (exit 3, `no read-only smoke test ran in <env>`); relay it and suggest a read-only smoke check, never rerun it against dev's data, because dev's data says nothing about `<env>`. A green run in `dev` whose system sets staging to `after-dev-smoke` also promotes staging to that build, as after a ship (spec 142): relay its `Promotion (staging)` line.

Read `cplat`'s output whole, never through `grep`, `head` or `tail`, because its last lines carry the decisions and fixes; use `--json` where offered.

> If a platform template, script or command misbehaves (not the user's code), stop, summarize it in two lines and offer `/issue:report`. **Hard rule:** never file an issue without the user's OK, because the platform repository is public; a `platform` escalation is the one issue the platform files itself (ADR-033).

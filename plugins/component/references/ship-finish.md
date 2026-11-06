# Ship: the final report

Read from `/component:ship` Finish.

When deploy printed `not deployable (<shape>): nothing to deploy`, the `dev`, `Promotion (staging)`, `Smoke (staging)` and `Smoke (dev)` rows read `not deployable`; leave out the Unchecked line and every `Next:` line that names `/instance:promote`.

```
## Shipped: <spec_id> — <title>

| Step | Result |
|---|---|
| Plan | <n> tasks |
| Build | <m>/<m> criteria met (verification.md) |
| PR | <url> — merged after <k> CI round(s) |
| dev | <service>:sha-<40> (pin PR <url>) · Argo <state> | not linked |
| Promotion (staging) | <the `Promotion (staging):` line from deploy: `sha-<40> (<pin PR url>)`, or `not promoted: <reason>` (spec 093)> |
| Smoke (staging) | <the `Smoke (staging):` value, or `-` when nothing was promoted> |
| Smoke (dev) | <the `Smoke (dev):` value from deploy: `<p>/<total> passed`, `passed on retry` or `not run: <reason>`> |

Dependency patches: the bumps of `cplat deps report` (package, from → to, CVE), a major bump marked "major bump"; leave out when none.

Human steps: the `human_steps` checklist from deploy's last lines; leave out when none.

Unchecked (smoke) criteria: <ids>   (only when smoke did not run; "none" otherwise)

Next: check staging, then promote with /instance:promote <component> --to prod in the gitops-app repo.     (staging promoted)
Next: promote with /instance:promote <component> --to staging in the gitops-app repo.     (smoke passed, staging not promoted)
Next: check the unchecked criteria in dev by hand; then promote with /instance:promote <component> --to staging.     (smoke did not run)
```

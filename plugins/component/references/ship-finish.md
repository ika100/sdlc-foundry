# Ship: the final report

The rows come from the `report:` block of `cplat component ship status`, on both paths.

For `not deployable (<shape>): nothing to deploy` the `dev`, `Promotion (staging)`, `Smoke (staging)` and `Smoke (dev)` rows read `not deployable`; leave out the Unchecked line and the `Next:` line.

```
## Shipped: <spec_id> — <title>

| Step | Result |
|---|---|
| Plan | <n> tasks |
| Build | <m>/<m> criteria met |
| PR | <url> — merged after <k> CI round(s) |
| dev | <service>:sha-<40> (pin PR <url>) · Argo <state> | not linked |
| Promotion (staging) | <sha-<40> (<pin PR url>), or `not promoted: <reason>`> |
| Smoke (staging) | <value, or `-` when nothing was promoted> |
| Smoke (dev) | <`<p>/<total> passed`, `passed on retry` or `not run: <reason>`> |

Dependency patches: the bumps of `cplat deps report`, a major bump marked "major bump"; leave out when none.

Human steps: the checklist; leave out when none.

Unchecked (smoke) criteria: <ids>, or "none"

Next: after checking staging, /instance:promote <component> --to prod in the gitops-app repo (staging promoted); `--to staging` instead (staging not promoted), after checking the unchecked criteria in dev by hand (smoke did not run).
```

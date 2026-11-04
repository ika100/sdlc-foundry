# 126 — Measurements (AC-126.15)

Window: the first 7 days after the release that ships this spec. Release and date: v5.4.0, 2026-10-28 (measured 2026-11-04 over 2026-10-28 to 2026-11-04: 176 records in ika100/sdlc-runs). Fill each table after running the
command; an empty result is the pass.

## Run report

```bash
cplat platform runs report --since 7
```

## Check 1 — no escalation reads `gave up after`

Look in the report's escalation reasons for `gave up after`.

| Escalations in window | With `gave up after` | Result |
|---|---|---|
| 5 | 0 | pass |

## Check 2 — no escalation from a non-owning session

No escalation records a session that did not start or resume the run (`owner` in the run state against the escalating session).

| Escalations in window | From a non-owning session | Result |
|---|---|---|
| 5 | 0 | pass |

All five are escalations a run wrote itself with its reason (repos left open for review, a lint-fixed acceptance test, a cost
budget, a pin PR held for workflow approval); none came from the Stop hook, which stays silent for a session that does not own
the run (`scripts/cplat/stopgate.py`, `check`).

## Check 3 — cause `environment` only with a matched rule

Stop-gate and headless `no progress` escalations: cause `environment` is allowed only together with a matched AC-088.16 rule
(`cause_source: given`, the rule named in the record).

| No-progress escalations | Cause `environment` | Of those, with a matched rule | Result |
|---|---|---|---|
| 0 | 0 | 0 | pass |

The one `environment` escalation in the window is the held pin PR (workflow runs awaiting approval), not a no-progress stop.

## Check 4 — no red `pr-title` or `spec-required` on platform-command PRs

```bash
gh pr list -R ika100/sdlc-foundry --state all --search "created:>=<release date>" --json number,title,createdAt
gh pr checks <number> -R ika100/sdlc-foundry --json name,bucket \
  --jq '.[] | select((.name=="pr-title" or .name=="spec-required") and .bucket=="fail")'
```

Run the second command for each PR opened by a platform command (`cplat component ship pr`, `cplat pr open`, `spec_pr`).

| PRs opened by platform commands | With a red `pr-title` | With a red `spec-required` | Result |
|---|---|---|---|
| 6 (#317, #327, #329, #343, #403, #405) | 0 | 0 | pass |

Platform-command PRs are those whose body carries a `<!-- cplat:` marker or whose title is a build PR's `feat|fix(NNN):`;
every check run of their heads was read (`filter=all`), superseded runs included. The report's 7 red `pr-title` pr-waits are
three cancelled duplicate runs (#322, fixed in #381) and four waits on PRs opened by hand or by Dependabot, matched by time
(likely #342, #357, #376 and #401; #357, #376 and #401 had titles over 72 characters).

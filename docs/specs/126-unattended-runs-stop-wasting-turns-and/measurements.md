# 126 — Measurements (AC-126.15)

Window: the first 7 days after the release that ships this spec. Release and date: _to fill_. Fill each table after running the
command; an empty result is the pass.

## Run report

```bash
cplat platform runs report --since 7
```

## Check 1 — no escalation reads `gave up after`

Look in the report's escalation reasons for `gave up after`.

| Escalations in window | With `gave up after` | Result |
|---|---|---|
| | | |

## Check 2 — no escalation from a non-owning session

No escalation records a session that did not start or resume the run (`owner` in the run state against the escalating session).

| Escalations in window | From a non-owning session | Result |
|---|---|---|
| | | |

## Check 3 — cause `environment` only with a matched rule

Stop-gate and headless `no progress` escalations: cause `environment` is allowed only together with a matched AC-088.16 rule
(`cause_source: given`, the rule named in the record).

| No-progress escalations | Cause `environment` | Of those, with a matched rule | Result |
|---|---|---|---|
| | | | |

## Check 4 — no red `pr-title` or `spec-required` on platform-command PRs

```bash
gh pr list -R ika100/sdlc-foundry --state all --search "created:>=<release date>" --json number,title,createdAt
gh pr checks <number> -R ika100/sdlc-foundry --json name,bucket \
  --jq '.[] | select((.name=="pr-title" or .name=="spec-required") and .bucket=="fail")'
```

Run the second command for each PR opened by a platform command (`cplat component ship pr`, `cplat pr open`, `spec_pr`).

| PRs opened by platform commands | With a red `pr-title` | With a red `spec-required` | Result |
|---|---|---|---|
| | | | |

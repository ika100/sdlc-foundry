---
spec_id: 090-a-weekly-retro-proposes-the-next-specs
title: A weekly retro proposes the next specs
status: building
priority: P1
---

# 090 — A weekly retro proposes the next specs

## Problem

The platform maintainer picks the next platform specs by memory. Of the last 23 specs (062–084), 18 started from a failure someone happened to notice by hand. Specs 087, 088 and 089 make runs, platform failures and agent quality visible as data, but data that nobody reads changes nothing. A weekly retro turns that data into a short, ranked list of proposed specs and agent-prompt changes, each backed by evidence. The maintainer then only decides what to build; nobody has to go looking for what hurts. Depends on 087 (run records and store), 088 (deduplicated platform issues) and 089 (agent metrics).

## Stories

As the platform maintainer, I want one weekly report that ranks what cost the most time and failed most often across every repo built on the platform, so that I can choose the next specs from evidence instead of from memory.

As the platform maintainer, I want the retro to propose concrete specs and agent-prompt changes, each citing the numbers behind it, so that turning a finding into work takes one decision, not an investigation.

As the platform maintainer, I want the retro to run every week without me starting it, and to say clearly when it could not read its data, so that a silent recorder or a broken store gets noticed.

## Acceptance criteria

- **AC-090.1** Given run records in the run store (087), when the maintainer runs `cplat retro` without asking it to post, then it prints the report for the last complete ISO week (Monday 00:00 to Sunday 24:00 UTC) before the current date, and creates, changes or comments on nothing on GitHub or in the run store.
- **AC-090.2** Given the run records of the covered week and of the week before, when the report is built, then it contains: runs per `kind` and per `outcome` (`done`, `escalated`, `failed`, `abandoned`); median and longest duration per phase; CI rounds and reruns per run; escalations per cause (`platform`, `code`, `decision`, `environment`, `unknown`) and, within each cause, the reasons ranked by number of runs (identical texts grouped, ties broken by the total duration of those runs); reruns ranked by reason (`stale`, `stuck`, `transient`) and by check name. Each figure shows the previous week's value next to it. The same records always produce the same report, apart from the generation timestamp.
- **AC-090.3** Given issues in the platform repo labelled `auto-filed` whose `Signature: platform:<hex>` line was filed or counted again during the covered week (088), when the report is built, then it lists each one with issue number, title, occurrences in the covered week, total occurrences, open or closed, and whether triage has routed it (it carries a decision label rather than only `triage`). The list is ranked by occurrences in the covered week.
- **AC-090.4** Given agent metrics (089) in the covered week's records, when the report is built, then it shows one row per agent × shape × model with the number of runs and the same per-run metrics as `cplat runs report --agents --json`. Each metric has the previous week's value and the difference next to it, metrics that were not measured show `n/a`, and rows with fewer than 5 runs are marked `few runs`.
- **AC-090.5** Given a covered week with no run records, records without agent metrics, or no platform issues, when the report is built, then each affected section says "no data for this week" and the report is still produced. A week with zero runs is stated in the report's first line.
- **AC-090.6** Given the run store is not configured, or cannot be read, when `cplat retro` runs, then it exits non-zero with a message that names the missing setting or the read error and the setup hint `cplat doctor` gives for the store, and posts nothing.
- **AC-090.7** Given the deterministic report, when the retro agent adds its proposals, then the result has at most 5 proposed specs, ranked 1 to n. Each one has a title, a problem statement of at most five sentences, a suggested priority (P0, P1 or P2), a one-line description ready to pass to `/svc:spec`, and the evidence: at least one figure or issue number that appears in the report. `cplat retro` refuses to post a proposal without such evidence and names it.
- **AC-090.8** Given a finding that an existing spec which is not `done`, or an open issue in the platform repo, already covers, when the agent proposes work for it, then the proposal names that spec or issue ("amends spec NNN" or "see #N") instead of proposing a new spec.
- **AC-090.9** Given an agent whose 089 metrics are cited as evidence, when the agent proposes a prompt change for it, then the proposal names the agent, the shape, the cited metrics and the proposed change in prose. There are at most 3 such proposals per retro, and the retro changes no agent file and opens no pull request.
- **AC-090.10** Given `cplat retro` is asked to post, when no retro issue for the covered week exists in the platform repo, then it creates one issue titled `Weekly retro <YYYY>-W<ww>` with the label `retro` and without the label `triage`. When that issue already exists, it replaces that issue's body instead of creating a second one.
- **AC-090.11** Given the platform repo is public and the run store is private, when the retro is posted, then the platform-repo issue contains no consumer repo names, no consumer spec ids or titles, no text copied from run records, and no name of or link to the run store. Repos appear only as counts per shape, and runs only by run id. The full report with per-repo detail is committed to the run store, and the store's list of retros links to the issue. All posted text has passed the redaction of `cplat feedback`.
- **AC-090.12** Given the run store has the retro schedule and a Claude credential secret, when Monday 06:00 UTC arrives, then a scheduled workflow in the run store repo runs on the self-hosted runner without anyone starting it. It runs `cplat retro`, then a headless Claude run that writes the proposals, and posts the issue for the week just ended. If the Claude credential is missing or the proposal step fails, the deterministic report is still posted with "Proposals: not generated (<reason>)". If `cplat retro` itself fails, the workflow run is red and no issue is created or changed.
- **AC-090.13** Given an open retro issue for an earlier week, when the retro for a later week is posted, then the earlier issue gets one comment linking to the new issue and is closed. Retro issues for other weeks, and issues without the label `retro`, are not touched.
- **AC-090.14** Given the setup that creates the run store (087's `cplat runs init`), when it runs, then the store repo gets the weekly retro schedule. Run again on an existing store, it adds the schedule when missing and changes nothing else. `cplat doctor` warns, naming what is missing, when the store has no retro schedule or no Claude credential secret.

## Non-goals

- Writing specs, approving them, or starting builds from proposals. The maintainer turns a proposal into a spec with `/svc:spec`.
- Routing the retro issue through `/shared:triage`, or filing each proposal as its own issue.
- Editing agent prompts, or opening pull requests for prompt changes (AC-090.9 only proposes them).
- Retros for a consumer product or a single consumer repo. This retro is about the platform.
- Collecting run data, filing platform issues or measuring agents. Those are 087, 088 and 089.
- Smoke-failure and alert issues in service repos (091, 092).
- Notifications other than the GitHub issue (mail, chat).
- Dashboards or charts. The report is text and tables.

## Open questions

- ~~Where does the weekly run happen, and what runs the proposal agent?~~ Answered: a scheduled workflow in the private runs repo on the self-hosted runner, Mondays 06:00 UTC, running `cplat retro` and then a headless Claude run with a Claude credential secret in the runs repo; see AC-090.12, AC-090.14.
- ~~What happens to last week's retro issue when the new one is posted?~~ Answered: the new retro comments on it with a link and closes it; see AC-090.13.
- ~~Should the retro issue go through `/shared:triage`, or should each proposal be its own issue?~~ Answered: neither. One issue labelled `retro` only, and each proposal carries a one-line `/svc:spec` description; see AC-090.7, AC-090.10.
- ~~Confirm: at most 5 proposed specs and 3 agent-prompt proposals per retro.~~ Confirmed; see AC-090.7, AC-090.9.
- ~~Confirm: the retro covers the last complete ISO week in UTC and runs Mondays at 06:00 UTC.~~ Confirmed; see AC-090.1, AC-090.12.
- ~~Confirm: the public platform-repo issue shows repos only as counts per shape, and all per-repo detail stays in the private run store.~~ Confirmed. The issue also does not name or link the run store, consistent with 088; see AC-090.11.

## Changelog

- 2026-10-23 created
- 2026-10-23 open questions answered: schedule in the runs repo with a headless Claude run (AC-090.12, new AC-090.14), previous retro issue closed (new AC-090.13), `retro` label without triage and `/svc:spec` line per proposal (AC-090.7, AC-090.10), limits and window confirmed; AC-090.2 to AC-090.4 aligned with 087, 088 and 089; the public issue no longer links the run store (AC-090.11)
- 2026-10-23 approved
- 2026-10-24 building

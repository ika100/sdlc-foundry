---
spec_id: 090-a-weekly-retro-proposes-the-next-specs
title: A weekly retro proposes the next specs
status: draft
priority: P1
---

# 090 — A weekly retro proposes the next specs

## Problem

The platform maintainer picks the next platform specs by memory. Of the last 23 specs (062–084), 18 started from a failure someone happened to notice by hand. Specs 087, 088 and 089 make runs, platform failures and agent quality visible as data, but data that nobody reads changes nothing. A weekly retro turns that data into a short, ranked list of proposed specs and agent-prompt changes, each backed by evidence. The maintainer then only decides what to build; nobody has to go looking for what hurts. Depends on 087 (run records), 088 (deduplicated platform issues) and 089 (agent metrics).

## Stories

As the platform maintainer, I want one weekly report that ranks what cost the most time and failed most often across every repo built on the platform, so that I can choose the next specs from evidence instead of from memory.

As the platform maintainer, I want the retro to propose concrete specs and agent-prompt changes, each citing the numbers behind it, so that turning a finding into work takes one decision, not an investigation.

As the platform maintainer, I want the retro to run every week without me starting it, and to say clearly when it could not read its data, so that a silent recorder or a broken store gets noticed.

## Acceptance criteria

- **AC-090.1** Given run records in the run store (087), when the maintainer runs `cplat retro` without asking it to post, then it prints the report for the last complete ISO week (Monday 00:00 to Sunday 24:00 UTC) before the current date, and creates, changes or comments on nothing on GitHub or in the run store.
- **AC-090.2** Given the records of the covered week and of the week before, when the report is built, then it contains: runs per outcome (finished, escalated, abandoned); median and longest duration per phase; CI rounds and reruns per run; escalation reasons ranked by number of runs (ties broken by total time lost); rerun causes ranked the same way. Each figure shows the previous week's value next to it. The same records always produce the same report, apart from the generation timestamp.
- **AC-090.3** Given platform issues filed or +1'd by 088 during the covered week, when the report is built, then it lists each of them with issue number, title, occurrences in the covered week, total occurrences and whether it has been routed in triage, ranked by occurrences in the covered week.
- **AC-090.4** Given agent metrics from 089 in the covered week's records, when the report is built, then it shows per agent, shape and model the number of runs and each 089 metric, with the previous week's value and the difference.
- **AC-090.5** Given a covered week with no run records, records without agent metrics, or no platform issues, when the report is built, then each affected section says "no data for this week" and the report is still produced. A week with zero runs is stated in the report's first line.
- **AC-090.6** Given the run store is not configured, or cannot be read, when `cplat retro` runs, then it exits non-zero with a message that names the missing setting or the read error and the setup step from `cplat doctor`, and posts nothing.
- **AC-090.7** Given the deterministic report, when the retro agent adds its proposals, then the result has at most 5 proposed specs, ranked 1 to n. Each one has a title, a problem statement of at most five sentences, a suggested priority (P0, P1 or P2) and the evidence: at least one figure or issue number that appears in the report. `cplat retro` refuses to post a proposal without such evidence and names it.
- **AC-090.8** Given a finding that an existing spec which is not `done`, or an open issue in the platform repo, already covers, when the agent proposes work for it, then the proposal names that spec or issue ("amends spec NNN" or "see #N") instead of proposing a new spec.
- **AC-090.9** Given an agent whose 089 metrics are cited as evidence, when the agent proposes a prompt change for it, then the proposal names the agent, the shape, the cited metrics and the proposed change in prose. There are at most 3 such proposals per retro, and the retro changes no agent file and opens no pull request.
- **AC-090.10** Given `cplat retro` is asked to post, when no retro issue for the covered week exists in the platform repo, then it creates one issue titled `Weekly retro <YYYY>-W<ww>` with the label `retro`. When that issue already exists, it replaces that issue's body instead of creating a second one.
- **AC-090.11** Given the platform repo is public and the run store is private, when the retro is posted, then the platform-repo issue contains no consumer repo names, consumer spec ids or titles, and no text copied from run records. Repos appear only as counts per shape. The full report with per-repo detail is committed to the run store, the issue links to it, and the run store's retro list links back to the issue. All posted text has passed the redaction of `cplat feedback`.
- **AC-090.12** Given the weekly schedule, when Monday 06:00 UTC arrives, then the retro runs on the self-hosted runner without anyone starting it and posts the issue for the week just ended. If the proposal step fails, the deterministic report is still posted with "Proposals: not generated (<reason>)". If `cplat retro` itself fails, the run is marked failed and no issue is created or changed.

## Non-goals

- Writing specs, approving them, or starting builds from proposals. The maintainer turns a proposal into a spec with `/svc:spec`.
- Editing agent prompts, or opening pull requests for prompt changes (AC-090.9 only proposes them).
- Retros for a consumer product or a single consumer repo. This retro is about the platform.
- Collecting run data, filing platform issues or measuring agents. Those are 087, 088 and 089.
- Notifications other than the GitHub issue (mail, chat).
- Dashboards or charts. The report is text and tables.

## Open questions

- Where does the weekly run happen, and what runs the proposal agent? (suggested: a scheduled workflow in the private runs repo on the self-hosted runner runs `cplat retro`, then a headless Claude run adds the proposals; this needs a Claude credential stored as a secret of the runs repo. The alternative is a Claude scheduled routine, which needs no runner but splits the retro across two systems; affects AC-090.12)
- What happens to last week's retro issue when the new one is posted? (suggested: the new retro comments on it with a link to the new issue and closes it. Retro issues are generated reports, not intake, so ADR-025's "the tooling never closes an issue" does not apply to them; affects AC-090.10, new criterion)
- Should the retro issue go through `/shared:triage` (label `triage`), or should each proposal be filed as its own issue? (suggested: neither. One issue labelled `retro` only, and each proposal carries a one-line description ready for `/svc:spec`, because triage routes one decision per issue and a retro holds several; affects AC-090.10, AC-090.7)
- Confirm: at most 5 proposed specs and 3 agent-prompt proposals per retro. (suggested: yes; affects AC-090.7, AC-090.9)
- Confirm: the retro covers the last complete ISO week in UTC and runs Mondays at 06:00 UTC, one hour after `bump-template-pins`. (suggested: yes; affects AC-090.1, AC-090.10, AC-090.12)
- Confirm: the public platform-repo issue shows repos only as counts per shape, and all per-repo detail stays in the private run store. (suggested: yes, because run records must never reach the public repo; affects AC-090.11)

## Changelog

- 2026-10-23 created

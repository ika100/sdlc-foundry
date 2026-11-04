---
spec_id: 135-a-ship-stops-for-approval-when-the
title: A ship stops for approval when the design is risky
status: draft
priority: P1
shape: platform
---

# 135 — A ship stops for approval when the design is risky

## Problem

Today approving the spec is the only human decision in an unattended delivery (ADR-028). The architect then decides alone on API contracts, data models and ADRs, and the run builds, merges and deploys them to dev before the user sees them. These are the decisions that are expensive to undo: other repos build against a contract in parallel, a migration changes stored data, and an ADR binds later features. A plan approval for every plan was considered before (spec 036, superseded) and dropped because it would stop every run. This spec adds a stop only where the design is risky. cplat detects the risk from the plan's files, not by an agent's judgement. Every other plan keeps running unattended.

## Stories

As a founder who ships unattended, I want the run to stop for my approval when the architect adds or changes an API contract or a data model, or writes an ADR, so that I see those decisions before code is built against them.

As a founder, I want plans without such changes to go on without me, so that the gate costs me nothing on routine features.

As a founder, I want to approve, or send the design back with comments, from the console Inbox or from Claude Code, and the run to continue on its own after my decision.

As a system owner, I want a system ship to stop once for the cross-repo design before any repo starts, so that no repo builds against a contract I have not seen.

## Acceptance criteria

Detection (the plan gate check is done by cplat. It reads only the committed plan: design.md, plan.md, the spec folder and the branch's changes against `main`.)

- **AC-135.1** Given a planned spec whose design.md has a `## Contract` or a `## Data` section with any text other than exactly `none` (case-insensitive), when the plan gate check runs, then it reports `approval needed` with one reason per section, e.g. `contract: design.md ## Contract`, `data model: design.md ## Data`.
- **AC-135.2** Given a feature branch whose commits since it left `main` add or change a file in the ADR directory, when the plan gate check runs, then it reports `approval needed` with the reason `ADR: <path> (new|changed)` for each file.
- **AC-135.3** Given a plan whose spec folder contains a contract file, or one of whose tasks lists in `files:` a contract file or a data-model file, when the plan gate check runs, then it reports `approval needed` with the reason `contract file: <path> (<task id>)` or `data model file: <path> (<task id>)`. Contract files are OpenAPI, AsyncAPI, protobuf, GraphQL schema, Avro and JSON Schema files (`*.openapi.{yaml,yml,json}`, `*.asyncapi.{yaml,yml,json}`, `*.proto`, `*.graphql`, `*.graphqls`, `*.avsc`, `*.schema.json`). Data-model files are any path with a `migrations/` or `migration/` segment, `db/changelog/`, `*.sql` and `schema.prisma`.
- **AC-135.4** Given a plan with no design.md, or one whose `## Contract` and `## Data` sections are missing or read `none`, no ADR change, no matching file and no API change of AC-135.20, when the plan gate check runs, then it reports `not needed`, and an unattended ship goes on to the build exactly as it does today. Run twice on the same commit, the check gives the same result and the same reasons in the same order, and it can be run on its own for any planned spec with human-readable and JSON output.

Unattended ship

- **AC-135.5** Given `/component:ship` whose plan gate reports `approval needed`, when the plan is committed and checked, then the run does not start the build. It pushes the feature branch and opens the spec's PR as a draft, so the plan, the design and the ADRs can be read on GitHub; this same PR later becomes the ship's PR (the `pr` phase reuses it). Its state shows the phase `plan` waiting for `plan approval` with every reason. The output names the draft PR and the two actions, `/component:plan <NNN> --approve` and `/component:plan <NNN> --changes "<comments>"`. The Stop hook lets the session end, and nothing is counted as an escalation.
- **AC-135.6** Given a run waiting for plan approval, then the console Inbox lists it as a decision of kind **plan**. The entry shows the spec id and title, every gate reason, the design's Contract and Data sections, the title of each new or changed ADR, the task count, a link to the draft PR, and the buttons **Approve plan** and **Request changes**, which run `/component:plan <NNN> --approve` and `/component:plan <NNN> --changes "<comments>"` and show those commands. A `plan` notification event is sent through the channels of `notify.yaml` (in the `recommended` preset it goes where `approve` goes), and the entry and notification are resolved when the user decides.
- **AC-135.7** Given a run waiting for plan approval, when the user approves it with `/component:plan <NNN> --approve` (an approval of the draft PR on GitHub does not count), then the approval is recorded in the plan's metadata (who, when, and a fingerprint of the parts that triggered the gate) and committed on the feature branch. Resuming with `/component:ship <NNN>` continues with the build without re-planning, and the console's approve action approves and resumes the run in one step.
- **AC-135.8** Given a run waiting for plan approval, when the user requests changes with `/component:plan <NNN> --changes "<comments>"`, then the architect re-plans. Its input is those comments plus the comments of any "request changes" review on the draft PR. The re-plan follows the usual plan-check rules (at most 2 check rounds), and the plan gate check runs again on the new plan: it waits again or goes on to the build. A comment that needs a spec change makes the architect report a blocker, and the run escalates with cause `decision` and the hint to amend the spec.
- **AC-135.9** Given a run waiting for plan approval, when it is resumed without a decision (`/component:ship <NNN>`, `cplat headless`), then it prints `waiting for plan approval` with the reasons and ends at once. It starts no session, subagent or re-plan.
- **AC-135.10** Given a run waiting for plan approval, then the wall-clock time from the stop to the decision is not counted against the run tree's `minutes` limit (ADR-043), and no invocation is counted while it waits. `cplat budget show` shows the run as paused for plan approval since a given time, and after approval the usage continues from where it stopped.
- **AC-135.11** Given a run that passed the plan gate, then its run record has a `plan_gate` section with the result, the reasons, the setting in force, the time requested, the time decided, the decision (`approved`, `changes-requested`, `not-needed`), the number of change requests, and the wait time. The wait time is left out of the phase durations, a stop at the gate is not counted as an escalation or a failure, and `cplat platform runs report` shows per week how many gates were triggered and approved, how many requested changes, and the median wait.
- **AC-135.12** Given an approved plan that is re-planned later in the same run (the build's re-plan after a merge conflict, or a request for changes), when the parts that triggered the gate are unchanged (same fingerprint), then the run does not stop again. When they changed, or a new reason appears, the run stops for approval again before the next build task starts.
- **AC-135.13** Given the approve action, when it is run from inside an unattended run (a headless session, a ship or build agent) or by an autonomy engine, then it refuses with `plan approval needs a person` and changes nothing. When the spec changed after planning (its hash no longer matches the plan), or there is no waiting gate for the spec, it refuses and says which (`plan is stale: re-plan` or `nothing to approve`).
- **AC-135.14** Given `cplat headless` driving a ship in units (spec 131), when the plan unit ends with the gate waiting, then the supervisor starts no further session and ends with the stop reason `plan-approval` and exit code 0. The next `cplat headless` for the spec after approval starts with the build unit.

Setting

- **AC-135.15** Given the setting `plan_gate` in `.platform-settings.yml` with the value `risky` (the default when absent, in every repo shape including the platform repo), `always` or `never`: `risky` gates as in AC-135.1 to AC-135.4, `always` gates every plan with the reason `setting: always`, and `never` never stops, but the ship output and the run record still list the reasons that would have triggered. Any other value fails the ship start with an error that names the key and the three allowed values, and changes nothing.

Manual flow

- **AC-135.16** Given `/component:plan` run by hand, then its summary ends with the line `Plan gate: approval needed (<reasons>)` or `Plan gate: not needed`. Given `/component:build` run by hand on a gated plan that is not approved, then it asks exactly once whether to approve the plan, listing the reasons. Yes records the approval as in AC-135.7, no stops the build. A headless build of such a plan refuses it with the approve hint.

System ship

- **AC-135.17** Given `/system:ship` whose system plan reports `approval needed` under the gitops-app repo's `plan_gate` setting, then the run stops before `publish`. Nothing is published, no repo starts, and the Inbox entry and `/system:plan <NNN> --approve` and `/system:plan <NNN> --changes "<comments>"` work for the system spec as in AC-135.6 to AC-135.8. At the gate the system ship opens the publish PR (spec and plan) as a draft and does not merge it. After approval the run resumes at `publish`, which reuses that PR.
- **AC-135.18** Given a repo shipped inside `/system:ship` whose own plan reports `approval needed` under that repo's setting, then only that repo waits, shown in the repo table as `waiting: plan approval`. Repos that do not depend on it go on, and repos that depend on it do not start. A repo's `## Contract` section that only restates the contract of the approved system plan does not trigger the repo's gate, but its Data section, ADRs and files do.

Docs

- **AC-135.19** Given the release that ships this spec, then HOW-IT-WORKS names plan approval as a decision that applies only to risky designs, next to routing an issue, approving the spec and promoting to prod. unattended-delivery.md has a "Plan gate" section with the triggers, the setting, the budget and record behaviour, and how to decide. console.md lists **plan** among the Inbox kinds and the Plan stage as a decision. A new ADR amends ADR-028, and ADR-028's "Amended by" line names it.

Detection, continued

- **AC-135.20** Given a plan with a gitops task, or a system plan with a gitops operation, that adds, removes or changes an API a component provides or consumes (`--provides`, `--consumes`), when the plan gate check runs, then it reports `approval needed` with the reason `API: <component> provides|consumes <api> (<task id>)`. A gitops task or operation that only adds or uses a resource does not trigger the gate.

## Non-goals

- No human review of every plan by default. `always` exists for repos that want it.
- No pull request review gate: the feature PR still merges on green checks (ADR-028). `--no-merge` stays the way to read a PR first.
- No risk scoring by an agent. The gate uses only the file and section rules above.
- No automatic approval or escalation after a waiting time.
- No per-run flag that skips the gate, and no change to how specs are approved.
- No gate for small changes and fixes outside a plan (spec 015), or for autonomy engine fix PRs (ADR-063).

## Open questions

- ~~Where does the user read the design at the gate?~~ Answered: in the draft PR that the ship opens at the gate and in the console. Comments from a "request changes" review go to the architect. The decision is the approve or changes action, not a GitHub PR approval, and the same PR later becomes the ship's PR. See AC-135.5 to AC-135.8 and AC-135.17.
- ~~What are the approve and request-changes actions called?~~ Answered: `/component:plan <NNN> --approve` and `/component:plan <NNN> --changes "<comments>"`, with the same flags on `/system:plan`. The console buttons run them. See AC-135.5 to AC-135.8 and AC-135.17.
- ~~Confirm: the default is `risky` in every repo, including this platform repo.~~ Answered: yes, see AC-135.15.
- ~~Confirm the file patterns, and do provides/consumes changes trigger?~~ Answered: the patterns as listed in AC-135.3. API provides/consumes changes trigger (AC-135.20); adding a resource does not.
- ~~Confirm: a restated system contract does not trigger a repo's gate in a system ship.~~ Answered: yes, see AC-135.18.
- ~~Confirm: a hand-run `/component:build` asks once and records "yes" as the approval.~~ Answered: yes, see AC-135.16.
- ~~Confirm: `cplat headless` ends with exit code 0 and stop reason `plan-approval`.~~ Answered: yes, see AC-135.14.

## Changelog

- 2026-11-04 created
- 2026-11-04 amended: open questions answered. Folded in the draft PR at the gate and the `--approve` / `--changes` flags of `/component:plan` and `/system:plan` (AC-135.5 to AC-135.8, AC-135.17), and the `risky` default in every repo (AC-135.15). Added AC-135.20: a change to the APIs a component provides or consumes triggers the gate.

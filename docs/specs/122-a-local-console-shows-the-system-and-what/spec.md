---
spec_id: 122-a-local-console-shows-the-system-and-what
title: A local console shows the system, its process and what needs you
status: approved
priority: P2
---

# 122 — A local console shows the system, its process and what needs you

## Problem

Since 5.0 the platform speaks the domain model (spec 114): a system with components, APIs and resources, three environments with instances, and specs that runs ship through a fixed process. Everything about it is reachable only through slash commands and their text output. A system owner who wants to answer the three questions of the model (what is my system made of, where does it run at which version, how does it change) has to know which command answers which question. `/system:status` covers the second; `/component:spec index`, `cplat spec list` and `/platform:runs` each cover a part of the third; nothing answers it in one place.

Most of the process runs unattended. A person is needed at three decision points only: approving a spec, an escalated run, and promoting to prod. Today nothing collects these points. A draft waiting for approval, a run stopped after three CI fix rounds and a release verified in staging are found by reading terminal output, GitHub issues or `/system:status` at the right moment.

Starting work has the same gap. A user with an idea has to choose between `/system:spec` and `/component:spec`. Adding a component, an API or a resource means knowing `system.yaml` keys and command flags. None of it shows what will change before it happens.

A UI mockup was discussed on 2026-10-26 (six screens: Home, Approve, Spec, New, Specs board, Notifications), then revised after a developer-experience review into three places: Inbox, Board and System. This spec turns its decisions into criteria. The console is a view on top of the existing commands: it adds no second source of truth, and every change still goes through a slash command and a pull request.

This spec is an additive 5.x extension of spec 114. It adds `cplat ui`, `cplat needs` and `cplat runs --json` to the CLI, and `ui` to the `platform` verbs of AC-114.59.

## Stories

- As a system owner, I want one place that shows what needs my decision, with everything I need to decide in the same place, so that a morning check takes a minute and not five commands.
- As a developer, I want the console to use one set of stage names, explain failures where they appear, show what a decision changes and how to undo it, and hand me over to Claude Code, GitHub, Argo CD or Grafana with one click or key, so that I trust it and do not need a terminal to double-check.
- As a system owner, I want to approve a draft spec after answering its open questions in the same place, and see what approval sets off, so that I approve knowingly and the run can start at once.
- As a developer, I want to follow one spec through the process: its stage, the run per repo, each criterion with its test and verdict, and the chain from issue to running instance, so that I know where my change is and why.
- As a user with an idea, I want to describe a change in a sentence, or add a component, API, resource or environment rule through a form that shows the `system.yaml` diff and the command first, so that I can start work without learning the flags.
- As a team member, I want to choose per event which channel reaches me, and have an event cleared everywhere once someone acts on it, so that I am told once and not four times.
- As the platform maintainer, I want the console to be a local, read-mostly view over `cplat` JSON and the existing commands, so that it adds no server, no telemetry and no second place where state lives.

## Acceptance criteria

### Start and data

- **AC-122.1** Given a system's gitops repo with `applications/<system>/system.yaml`, when `cplat ui` runs, then it starts a web server bound to `127.0.0.1` on a free port, prints the URL and opens it in the default browser (`--no-open` skips that). Outside such a repo it fails, naming `system.yaml` and the directory it searched.
- **AC-122.2** Given the console running, when its network traffic is observed, then it connects only to GitHub (through `gh`), the clusters of the current kube contexts, and the notification endpoints configured in AC-122.22. It sends no telemetry.
- **AC-122.3** Given the console, when it shows any page, then every value comes from `cplat model show --json` (schema 2), `cplat system status --json`, `cplat spec list --json`, `cplat runs --json` and `cplat needs --json`, never from its own store. Each page shows the time its data was read and refreshes within 30 seconds of a change in run records or in the repo's `main` branch.
- **AC-122.4** Given a system, when `cplat needs --json` runs, then it lists every open decision point with `kind` (`approve`, `answer`, `escalation`, `promote`, `triage`), the object (spec id, run id, issue number, or component and version), `since`, a one-line reason and the command that resolves it. A draft spec with open questions is `answer`; a draft with none is `approve`; an escalated run is `escalation`; a release whose digest staging verified and prod does not run is `promote`; an issue opened from a firing alert (spec 092) or a failed smoke (spec 091) that `/issue:triage` has not routed yet is `triage`, and it leaves the list once it is routed.
- **AC-122.5** Given a system, when `cplat runs --json` runs, then it lists each active and recent run with spec id, repo, phase (`plan`, `build`, `pr`, `land`, `deploy`, `staging`, `done` or `escalated`), budget used and limit, and its last ten activity entries with time and agent.

### Three places and one vocabulary

- **AC-122.31** Given the console, when any page is shown, then the sidebar offers exactly three places: Inbox, Board and System. The details of a spec, run, issue or instance open as a side panel next to the place they were selected in, so the place stays visible. Describing a change, adding to the model, going to an object and asking are in one "New or ask" palette, opened by its button or `⌘K` from every page. Settings are in the user menu. There are no other top-level pages.
- **AC-122.32** Given any item the console shows, when its state is shown, then it is named by one of the eight stages Issue, Spec, Plan, Build, Land, Dev, Staging, Prod and by nothing else: a draft spec is in Spec; an approved spec without a run, and a run in its `plan` phase, are in Plan; `build` is Build; `pr` and `land` are Land; `deploy` is Dev; `staging` is Staging; a release waiting for prod is in Prod. An escalated run stays in the stage where it stopped and is marked as stopped. Spec statuses and run phases are not shown as names of their own.

### Inbox

- **AC-122.6** Given open decision points, when the Inbox is shown, then it lists them oldest first, each with its kind, stage, age and reason. Selecting one shows its detail next to the list, and the decision can be made there (answer, approve, promote, take over, fix, dismiss) without leaving the Inbox. The sidebar badge shows the same count as `cplat needs --json`.

### Board

- **AC-122.9** Given active runs, when the Board is shown, then each run's card shows its repo, its stage and its budget used of its limit, and a stopped run says why in one line.
- **AC-122.10** Given the system's issues, specs and runs, when the Board is shown, then it has one column per stage in the order of AC-122.32, and each open item is in exactly one column by that rule. The Spec, Build and Prod columns are marked as decision columns.
- **AC-122.11** Given the Board, when "List" is chosen, then the same items are shown as a table with stage and current state.
- **AC-122.12** Given a column header, when it is selected, then the console explains that stage: what happens, the agents involved, the commands, and what the user decides there if it is a decision column.
- **AC-122.13** Given a card on the Board, when it is selected, then a side panel shows the item's stage strip, one line per repo slice from the plan (one for a component spec) with its stage and budget, the criteria at a glance, and the selected slice's activity from AC-122.5.
- **AC-122.14** Given a spec with criteria, when its side panel is shown, then each criterion shows its id, text, the test that names it and its verdict from `verification.md`, or `not judged` when there is none. A `(smoke)` criterion shows the instance it is checked on and the smoke result.
- **AC-122.15** Given a spec with a run, when its side panel is shown, then it shows the evidence chain issue → spec → plan → run → pull request → image → instance, and the API contract change from the plan when there is one.

### System

- **AC-122.7** Given a system, when System is shown, then "Where it runs" has one row per component that has instances and per resource, and one column per environment in promotion order with the environment's `promote` and `policy`. Each cell shows the instance's version and its state (`pinned`, `healthy`, `verified`, `NOT VERIFIED`, `alert`) as `cplat system status --json` reports it. A library is listed with the components that use it, without cells. System also lists the components, APIs and resources with their relations, and "Add to the model" opens the forms of AC-122.20 in place.
- **AC-122.8** Given a cell whose version is verified and whose next environment promotes `manual`, when System is shown, then the cell offers "Promote", which follows AC-122.18 and AC-122.34.

### Failures explained where they appear

- **AC-122.33** Given an escalated run, a smoke that failed or did not run, or an issue waiting for triage, when its detail is shown, then it shows why it stopped in one sentence, the failing test or check with the criterion it belongs to, the last error from the compact failure summary (spec 108), and the agent's diagnosis in one line. It then offers ways forward, each with its command: for an escalation "Take over" (AC-122.36), "More budget" and "Amend the spec"; for a triage issue "Fix now" (`/component:fix`), "Make a spec" and "Dismiss" with a reason.

### Consequence and way back

- **AC-122.34** Given a decision, when its detail is shown and before it is confirmed, then it shows the consequence: for a promotion, the specs, criteria, number of commits and database migrations between the running and the new version, and that the digest is the one staging verified; for an approval, the repos the spec touches, the stages that will run without the user, and the expected cost and duration as the median of the last three or more comparable runs (or "no estimate yet"); for a change to the model, the repos and pull requests it creates and the environments that render it.
- **AC-122.35** Given a decision, when its detail is shown, then it names the way back: for a promotion, the command that promotes the previous version again, with a warning when a migration in between is not additive; for "Approve & ship", that the run can be paused at any stage and nothing reaches prod without the user; for stopping a run, what stays (branch, pull request) and that nothing was deployed; for a change to the model, closing its pull request or the matching `remove` command.

### Hand-off to developer tools

- **AC-122.36** Given a run, when "Open in Claude Code" is chosen, then Claude Code resumes that run's session (the session id from its run record) in the run's repo with the failure summary of AC-122.33 loaded. Without a recorded session it starts a new session in the repo with the spec, the run record and the failure summary as context.
- **AC-122.37** Given any action, when it is shown, then its command is shown next to it with a copy button.
- **AC-122.38** Given any page, when the keyboard is used, then `⌘K` opens "New or ask", `j` and `k` move through the Inbox, the arrow keys move through Board columns, `enter` opens the selected item and `esc` closes a side panel. On a selected decision, `a` approves, `p` promotes, `t` takes over and `o` opens in Claude Code; single-key shortcuts act only when no text field has focus, and each is shown next to its button.
- **AC-122.39** Given an item or an instance, when its detail is shown, then it links to where its evidence lives: the pull request, the CI run and the run record for work; the Argo CD application, the Grafana panel and the logs for an instance. Each link opens that tool.

### Approving

- **AC-122.16** Given a draft spec with open questions, when its detail is shown in the Inbox, then each question is shown with the options the product manager agent proposed and a free-text answer. An answer is recorded in the spec's open questions the same way `/component:spec --amend` (or `/system:spec --amend`) records it.
- **AC-122.17** Given a draft spec, when its detail is shown in the Inbox, then "Approve & ship" is disabled while an open question is unanswered or `cplat spec check` fails for the spec, and says why. Once enabled, it runs `spec approve <id>` and then `ship <id>` at the system or component level with the budget chosen on the page. "Approve only" runs just the approval; "Request changes" sends the user's comment to an amend.

### Starting work

- **AC-122.18** Given any action in the console that changes something (approve, ship, promote, add, set, remove, answer), when the user starts it, then the console shows the exact command and, where `system.yaml` changes, the diff before it runs. On confirm it runs the command through Claude Code (`claude -p`) in the repo and shows a link to the run and the resulting pull request. The console never writes files in a repo or calls `kubectl` itself.
- **AC-122.19** Given "Describe a change", when the user enters a sentence and confirms, then the console runs `/system:spec` or `/component:spec` with it (the user's choice, or the product manager agent's when the user chooses "Let Claude decide"). The new draft appears on the Board in the Spec column and in the Inbox. Open issues whose title matches the sentence are shown before confirming, so the user can link one.
- **AC-122.20** Given the forms for a component, an API, a resource, environment rules or a new system, when a field changes, then the diff and the checks are recomputed with the same rules `render.py` applies. An invalid value names the key and the rule, and the confirm button stays disabled.

### Ask bar

- **AC-122.21** Given the ask bar, when the user asks a question, then Claude answers using read-only tools over the model, the specs and the runs. When the answer suggests an action, it is shown as a command (and diff) with a confirm button that follows AC-122.18. Nothing runs from the ask bar without that confirm.

### Notifications

- **AC-122.22** Given `~/.config/sdlc-foundry/notify.yaml`, when the console reads it, then each event (`approve`, `answer`, `escalation`, `promote`, `alert`, `smoke`, `run-done`, `retro`) has per channel (`github`, `slack`, `email`, `desktop`) one of `off`, `instant` or `digest` (`digest` only for `slack` and `email`). The console channel is always on. Without the file, the "Recommended" preset applies. Slack is reached through an incoming webhook per channel. Webhook URLs and SMTP credentials are read from the environment or the OS keychain, never from a repo.
- **AC-122.23** Given an event with channels set, when it occurs, then each channel set to `instant` gets one notification for it. A GitHub notification for `approve` and `answer` is a review request on the spec's draft pull request (AC-122.30); for the other events it is an issue assigned to the user, as the platform creates them today.
- **AC-122.24** Given a notified event, when anyone resolves it through any channel or command, then the console card disappears, the GitHub issue is closed or the review request resolved, the desktop notification is withdrawn where the OS allows it, and the next digest lists the event as done. A Slack message already sent through a webhook is not changed; the next digest marks the event as done.
- **AC-122.25** Given a digest channel, when its time comes (default weekdays 09:00 local), then it sends one message listing open decision points and what shipped since the last digest. An empty digest is not sent.
- **AC-122.26** Given quiet hours, when an event occurs inside them, then no `instant` notification is sent except an `alert` on a prod instance. The others wait for the next digest and stay in the Inbox.
- **AC-122.27** Given a channel set to `instant` or `digest` whose endpoint or credentials are missing, when `/platform:doctor` runs, then it reports the channel and the missing setting.

### Systems and specs on GitHub

- **AC-122.29** Given the console, when the system switcher is opened, then it lists the repos of the `gh` account and its organisations that carry the `gitops-app` topic. Choosing one opens its console from a local clone under the configured workspace directory, or offers to clone it there first.
- **AC-122.30** Given `/system:spec` or `/component:spec` creating a draft, when the draft is written, then it is pushed on its own branch with a draft pull request that holds `spec.md`, and the system owner is requested as reviewer. Approving the spec (in the console or by command) approves that review and merges the spec; "Request changes" leaves a review comment that the amend reads. This extends spec 114's spec commands additively.

### When things are not normal

- **AC-122.40** Given a system with no specs, runs or open issues, when the Inbox, the Board or System is shown, then none of them is an empty table: the Inbox lists the next steps to a first change (what already runs, "Describe your first change" opening "New or ask", choosing notifications), the Board shows its columns with one line each on what happens there, and System shows the parts and instances that exist.
- **AC-122.41** Given `claude` not on the PATH, `gh` not logged in, or no kube context for an environment, when the console starts, then it starts anyway and shows a banner that names each missing piece with the fix `/platform:doctor` gives for it. Every action that needs the missing piece is disabled and says which piece it needs, its command can still be copied, and everything that does not need it works.
- **AC-122.42** Given a source the console reads (a cluster, GitHub, or a `cplat` call) that fails or cannot be reached, when a page shows data from it, then the affected part says since when it is unavailable, offers the error and "Retry now", and retries every 30 seconds. Its last data is marked stale; health it cannot read is shown as `unknown`, never as the last known value; and an action that depends on that health (such as "Promote") is disabled until it is known again. The other parts of the page stay live.
- **AC-122.43** Given any page, when it is shown, then it shows the time its data was read, and data older than 2 minutes is marked stale.

### Actions you started

- **AC-122.44** Given an action the user confirmed (AC-122.18), when it runs, then an activity indicator on every page shows how many actions run and how many failed. Its panel lists each action with its command, the time it has run, the current step from its output, and its result: on success the links to the run and the pull request; on failure the reason, the last lines of output, "Retry" and "Open in Claude Code".
- **AC-122.45** Given an action running on an object (a spec, run, issue, instance or release), when the same object is shown, then other actions on it are disabled until the first one ends, and say so.
- **AC-122.46** Given actions still running, when `cplat ui` is asked to stop, then it lists them and asks for confirmation before it stops; a confirmed stop ends them, and the next start shows them as stopped.

### Releases and history

- **AC-122.47** Given a component whose version is verified in Staging and newer than its last release, when its Board card or its System cell is shown, then it offers "Cut release". Before confirming, it shows the version derived from the commits, the specs and fixes the changelog will list, and that a release pull request is opened and the tag is set on the digest Staging verified after it merges; its way back is closing the release pull request. Confirming runs `/component:release` in the component's repo, and the release then appears in the Prod column as waiting for promotion.
- **AC-122.48** Given the Board, when "Done" is chosen, then it lists the specs, fix runs, issues and releases closed in the chosen period (30 days by default; 90 days or all), newest first, each with the date, the stage it reached, its release and links to its evidence.
- **AC-122.49** Given the Board's search, when the user types an id, a title word, a component name or an issue number, then open and done items that match are shown, with their stage or the stage they reached.

### Usable by everyone

- **AC-122.28** Given any page, when it is used with the keyboard only, then every action is reachable and operable, text meets WCAG 2.2 AA contrast, and the layout works at 390 px width without horizontal page scroll (wide tables scroll inside their box).

## Non-goals

- A hosted or multi-user server, logins or roles. The console is local and acts as the user with the user's `gh` and kube credentials.
- Editing `system.yaml`, specs or manifests directly in the console. Every change goes through a command and a pull request (AC-122.18).
- Replacing GitHub for code review, or Argo CD and Grafana for cluster and telemetry detail. The console links to them.
- Showing more than one system at once. The system switcher (AC-122.29) opens another system's console.
- A Slack app that updates or withdraws messages, or acts from buttons in Slack. 5.x uses webhooks; an app is a later spec.
- Cutting releases automatically once Staging verified a version. 5.x offers "Cut release" (AC-122.47).
- A cost page per week, spec or agent. 5.x shows the budget on each run; "Runs & cost" links to `/platform:runs`.
- A Backstage plugin or any dependency on Backstage (the domain model takes its shape only).
- Running actions without Claude Code installed: without `claude` on the PATH the console is read-only and says so.

## Open questions

- ~~Which systems does the switcher list?~~ Answered: the repos with the `gitops-app` topic of the `gh` account and its organisations, opened from a local clone or cloned on demand. See AC-122.29.
- ~~Should a GitHub notification for `approve` be a review request on a PR, or an issue?~~ Answered: a review request on a draft PR that the spec commands open. See AC-122.23, AC-122.30.
- ~~Slack: webhook or app?~~ Answered: an incoming webhook in 5.x; resolved events are marked in the next digest. A Slack app is a later spec. See AC-122.22, AC-122.24 and Non-goals.
- ~~Should alerts and smoke failures count as decision points?~~ Answered: yes, as `triage` while nobody has routed the issue. See AC-122.4.
- ~~Does the console need its own cost view?~~ Answered: no; the budget on each run is enough for 5.x. See AC-122.9 and Non-goals.

## Changelog

- 2026-10-26 created from the console mockup discussion. Decided there: Home leads with "Needs you"; one spec page for system and component specs; changes only through commands and PRs; Process and the spec list are one board; a local app started by `cplat ui`; "Approve & ship" as the default; notifications in the console, GitHub, Slack or e-mail digest and desktop; the ask bar answers and proposes but never acts alone.
- 2026-10-26 amended: answers folded in (switcher by `gitops-app` topic, draft PR with review request for specs, Slack by webhook, `triage` as a fifth decision kind, no cost page in 5.x); added AC-122.29 and AC-122.30
- 2026-10-26 approved
- 2026-10-26 draft: amendment: developer UX review (three places, one vocabulary, failures, consequences, hand-off)
- 2026-10-26 amended after a developer-experience review: three places (Inbox, Board, System) with side panels and a `⌘K` palette; one stage vocabulary; failures explained with ways forward; consequence and way back for every decision; hand-off to Claude Code, keyboard and deep links. AC-122.6 to AC-122.15 reworded for the three places, AC-122.11's "Needs me" filter replaced by the Inbox; added AC-122.31 to AC-122.39
- 2026-10-26 approved
- 2026-10-26 draft: amendment: v1 gaps (first run and degraded states, action feedback, releases, history)
- 2026-10-26 amended: v1 gaps added: first run, missing prerequisites and unreachable sources (AC-122.40 to AC-122.43); feedback on actions the user started (AC-122.44 to AC-122.46); cutting a release and the Done view with search (AC-122.47 to AC-122.49)
- 2026-10-26 approved

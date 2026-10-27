---
spec_id: 124-autonomy-is-declared-per-environment-and
title: Autonomy is declared per environment and supervised in the console
status: building
priority: P2
---

# 124 — Autonomy is declared per environment and supervised in the console

## Problem

The platform delivers planned work unattended once a person approves a spec (spec 067, spec 097), but the running system is only watched by people: an alert becomes an issue (spec 092) and waits. ai-ops, a service built from the platform's `service-go` template, already does more in its own cluster: it watches workloads, turns signals into findings, triages them with an agent, opens fix pull requests from L2 on, and keeps a hash-chained audit. It does so in its own language (Component, Finding, Remediation, AutonomyPolicy L0–L4), with its own budgets, change window, mail and operator UI. Its ADR-004 (proposed) makes it the always-on, in-cluster engine of sdlc-foundry and renames its nouns to the 5.x model.

Two things are missing on the platform side for that. First, there is no place to declare how much may happen without a person: the AutonomyPolicy lives in a cluster, outside `system.yaml`, and can disagree with the promotion rules there (spec 093, spec 114). Second, the console (spec 122) shows only work people started: an issue an engine made, a fix it wrote, a rollback it did and the reason it stopped have no place in the Inbox, the Board or System, and a person has no single switch to stop it all.

This spec adds autonomy to the model: a level per environment with guardrails in `system.yaml`, one command to set, pause and resume it, the contract an engine (ai-ops) reads and writes, and the console's views to supervise it. It is an additive 5.x extension of spec 114 (a new environment key and a new `system` verb) and of spec 122 (new decision kinds, notifications and the Autonomy tab). The engine's own behaviour (how it detects, triages and fixes) is specified in the engine's repository against this contract.

## Stories

- As a system owner, I want to declare per environment how much may happen without me, in `system.yaml` next to the environment's other rules, so that autonomy is reviewed, versioned and the same for every tool that reads it.
- As a system owner, I want guardrails (what may merge on its own, size and test limits, a budget and a change window) that every autonomous action stays within, so that raising a level never means "anything goes".
- As a system owner, I want one switch that pauses all autonomy of a system at once, so that I can stop it in an incident without editing files.
- As a developer, I want issues an engine made, fixes it wrote and the reason it stopped to appear in the same Inbox and Board as my own work, in the same stages, so that I supervise one flow and not two tools.
- As a system owner, I want to see everything that happened on its own, with the policy that allowed it and a way to undo it, so that I can trust a higher level.

## Acceptance criteria

### Declared in system.yaml

- **AC-124.1** Given `environments.<env>.autonomy` in `system.yaml`, when the system is rendered, then it accepts `level` with one of `observe`, `advise`, `propose`, `act`, `improve`, the keys `autoMerge`, `riskGate`, `budget`, `window` and `undoWindow`, and `engine`, the address of the engine that serves the environment; any other key fails the render naming the key and the allowed ones. Without `autonomy` an environment is `observe`.
- **AC-124.2** Given the levels, when an engine and the platform read them, then they mean, in order and each including the one before: `observe` records issues from signals; `advise` triages them and notifies; `propose` opens fix pull requests that a person merges; `act` merges fixes within the guardrails, rolls back after a failed smoke and lets a person undo. `improve` is accepted and, until a later spec defines it, acts as `act`; `cplat model show --json` reports it as declared `improve`, effective `act`. `cplat model show --json` reports each environment's level and guardrails.
- **AC-124.3** Given `prod`, when its `autonomy.level` is `improve`, then the render fails naming `act` as the highest level allowed in prod.
- **AC-124.4** Given `autoMerge`, when it is set, then it takes `routes` (a subset of `fix`; `spec` is refused, since a spec always needs a person's approval) and `maxCriticality` (`low`, `medium`, `high`); `riskGate` takes `maxFiles`, `maxLines`, `regressionTest` and `secondReview`; `budget` takes `runsPerDay`, `mergesPerDay` and `perRun` (in the unit of spec 102); `window` takes `days`, `from`, `to` and `timezone`; `undoWindow` is a duration (default `24h`). Every omitted field has a documented default, and `cplat model show --json` reports the effective values.
- **AC-124.5** Given an environment's `promote` rule (spec 093), when autonomy is set, then the rule still decides promotion: no level promotes into an environment whose `promote` is `manual`, and prod is promoted only by a person.

### Setting, pausing and resuming

- **AC-124.6** Given `/system:autonomy set <env> <level>` (or with guardrail flags), when it runs, then it opens one pull request in the gitops repo that changes only that environment's `autonomy`, and its description lists the old and new level and guardrails and what the new level allows. A higher level or a looser guardrail takes effect only after the merge. A lower level or a tighter guardrail takes effect at once, by the signal of AC-124.7, and the pull request records it.
- **AC-124.7** Given `/system:autonomy pause`, when it runs, then it sends a pause signal to the engine of every environment (at its `engine` address), and every environment acts as `observe` within 60 seconds; runs an engine already started stop at their next step and are recorded as stopped by the pause. It then opens a pull request that records `autonomy: {paused: true}` at the top of `system.yaml`, so git stays the record. `/system:autonomy resume` sends the resume signal and opens the pull request that removes `paused`; the levels in `system.yaml` apply again. Pausing and resuming are audited with who and when. Pausing, resuming and lowering (AC-124.6) are the only changes that act before their pull request merges: an extension of AC-122.18 for safety.
- **AC-124.21** Given an engine that cannot be reached by a pause or lowering signal, when the command runs, then it says which environments did not confirm within 60 seconds, still opens the pull request, and the console shows those environments as not confirmed until the engine confirms or the merged pull request reaches it.
- **AC-124.8** Given `/system:autonomy show`, when it runs, then it prints per environment the declared level, whether autonomy is paused, the guardrails, today's budget used and the engine that serves it with its last heartbeat.

### The contract with an engine

- **AC-124.9** Given an engine serving a system, when it reads the policy, then it reads it only from `cplat model show --json` (or the same JSON rendered into the cluster); a change to `system.yaml` is in effect for the engine within 5 minutes of the merge and is audited with the commit. Signals (AC-124.7) are the only other input, and a signal never raises autonomy.
- **AC-124.10** Given an engine that makes an issue from a signal, when the issue is created, then it is a GitHub issue in the component's repository with the instance (component and environment), category, criticality, dedupe key and redacted evidence links in the platform's issue format; a repeat of the same dedupe key adds to the existing issue instead of opening a new one.
- **AC-124.11** Given an engine that starts a fix, when it runs, then the engine writes it into the platform's run records (spec 087) as a run of kind `fix` with `actor` set to the engine, the issue it serves, its budget and phases as for any run, and its pull request carries the regression test's before and after result.
- **AC-124.12** Given an engine action (an issue made, a triage, a run started, a merge, a rollback, a dismissal, a pause honoured), when it happens, then the engine writes an audit event into the platform's run records with time, actor, object, the policy level and guardrail values that allowed it, the commit of the policy, and a reference to the entry in its own tamper-evident audit store; `cplat` reads it from the run records within 60 seconds and never from the engine directly, so it stays readable when the cluster is not.
- **AC-124.13** Given an engine whose heartbeat is older than 5 minutes, when the console or `/system:autonomy show` reads it, then the engine is shown as unreachable and the environments it serves as not supervised, following AC-122.42.

### Guardrails hold

- **AC-124.14** Given a fix at level `act`, when it is outside any guardrail (route not in `autoMerge.routes`, criticality above `maxCriticality`, more files or lines than `riskGate` allows, no regression test that fails before and passes after, a finding from the second review, budget used up, or outside the `window`), then it is not merged on its own: it becomes a `review` decision (AC-124.17) naming each guardrail it is outside.
- **AC-124.15** Given a merge done on its own, when the smoke in the first environment after it fails, then at level `act` the previous version is promoted back with `/instance:promote --version <previous>` (a pin pull request as any other), the fix's issue is reopened with the smoke result, and the rollback is audited.
- **AC-124.16** Given an action done on its own at level `act`, when a person chooses "Undo" within the environment's `undoWindow` (24 hours by default), then it is reverted the platform's way (a revert pull request for a merge, a promotion of the previous version for a promotion, reopening for a dismissal) and both the action and its undo stay in the audit.

### In the console

- **AC-124.17** Given an engine's fix that waits for a person (level `propose`, or outside a guardrail at `act`), when the Inbox is shown, then it is a decision of kind `review` (added to the kinds of AC-122.4) showing why it needs the person, the regression test result, CI, the second review, the agent's summary, the consequence and the way back; approving approves the pull request.
- **AC-124.18** Given items an engine made or runs it started, when the Inbox or the Board shows them, then they sit in the eight stages of AC-122.32 like any other item and carry an engine badge; an issue from a signal shows its evidence, category, criticality, how often it was seen, the triage (route, confidence, suspected files) and the policy decision that applies to it.
- **AC-124.19** Given System, when its Autonomy tab is shown, then it shows per environment the level as a choice of the five levels (levels above the environment's cap disabled), the effective guardrails, the `system.yaml` diff of a change with its command and "Open PR" (AC-122.18), "Pause all autonomy" or "Resume" with what pausing means, the engine's status, and the actions done on its own in the last 24 hours with who, what, the policy that allowed it and "Undo" where AC-124.16 allows it. A component capped below its environment (AC-124.22) shows its cap next to the level.
- **AC-124.20** Given notifications (AC-122.22), when an engine is active, then the events `review`, `signal` (on an instance, with prod signals allowed through quiet hours) and `done-on-its-own` are available per channel; the engine sends no message itself, it emits events and the platform delivers them.

### Per component

- **AC-124.22** Given `components.<c>.instances.<env>.autonomy: {max: <level>}`, when the engine acts on that instance, then it acts at the lower of the environment's level and `max`; `max` never raises a component above its environment, and any other key under a component's `autonomy` fails the render naming `max`. `cplat model show --json` reports each instance's effective level.

## Non-goals

- How an engine detects, triages and fixes: that is specified in the engine's repository (ai-ops) against this contract.
- Promotion to prod without a person, at any level (AC-124.5).
- Raising one component above its environment's level; a component can only be capped (AC-124.22).
- Defining `improve`: a later spec, with the weekly retro (spec 090) as its input; until then it acts as `act` (AC-124.2).
- A second engine or engines from other vendors; the contract does not exclude them, but only ai-ops is served in 5.x.
- Migrating ai-ops' `AutonomyPolicy` resources: the engine's rename (its ADR-004) does that.

## Open questions

- ~~Should pause be a signal the engine reads, or a pull request with an expedited merge?~~ Answered: a signal at once, recorded by a pull request after. See AC-124.7, AC-124.21.
- ~~Where do an engine's runs and audit events live for `cplat` to read?~~ Answered: in the platform's run records (spec 087), written by the engine; the engine's own store stays the tamper-evident copy. See AC-124.11, AC-124.12.
- ~~Is 24 hours the right undo window, and configurable?~~ Answered: 24 hours by default, `undoWindow` per environment. See AC-124.4, AC-124.16.
- ~~Should lowering a level take effect at once?~~ Answered: yes, like a pause; raising waits for the merge. See AC-124.6.
- ~~Should `improve` be part of this spec?~~ Answered: no, a later spec; until then it acts as `act`. See AC-124.2 and Non-goals.
- ~~Does a component need its own override?~~ Answered: a cap only, never higher than its environment. See AC-124.22.

## Changelog

- 2026-10-26 created from the console and ai-ops integration discussion (mockup screens Inbox, Board, System › Autonomy, the ai-ops rename map and the integration diagram; ai-ops ADR-004, proposed)
- 2026-10-26 amended: answers folded in (pause and lowering as a signal recorded by a pull request, engine address per environment, engine writes runs and audit into the run records, `undoWindow`, `improve` deferred, per-component cap); added AC-124.21 and AC-124.22
- 2026-10-26 approved
- 2026-10-26 renumbered from 123 (the number was taken by spec 123, the platform repo declares its own shape); criteria AC-123.n are now AC-124.n, otherwise unchanged
- 2026-10-27 building

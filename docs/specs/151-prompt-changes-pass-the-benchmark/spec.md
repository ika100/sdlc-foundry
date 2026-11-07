---
spec_id: 151-prompt-changes-pass-the-benchmark
title: Prompt changes pass the benchmark before a release
status: done
priority: P1
shape: platform
---

# 151 — Prompt changes pass the benchmark before a release

## Problem

The agents' behaviour is set by Markdown: agent definitions, slash commands, their references and skills. A change to them is tested by unit tests only for its wording; whether a run still finishes, and at what cost, shows only in the next journey, four hours and about 46 M tokens later, or in a user's run. The platform already has a benchmark (spec 099, [ADR-035](../../adr/035-token-usage-from-session-transcripts.md)): fixed tasks on a pinned sample repo, run through `cplat headless`, recorded with outcome and tokens, and runnable with the plugins of a checkout (`--plugins`). Nothing requires it. Changes such as "decide by default" (spec 149) change prompts that every run reads; Anthropic's and others' guidance for agent systems is to gate prompt changes on evals.

## Stories

As the person releasing the platform, I want a release that changed the prompts to show that the benchmark still finishes with them, within the token cost of the last release, so that a prompt regression is found in minutes, before users meet it.

## Acceptance criteria

- **AC-151.1** Given a platform checkout, when `cplat platform eval-gate [--base REF] [--workflow W]` runs and no file under `plugins/*/{agents,commands,references,skills}/` changed since REF (default: the newest `v*` tag), then it passes and says no benchmark is needed.
- **AC-151.2** Given changed prompts, when no benchmark record of a named workflow (default `quick-task` and `build`) ran with a `plugins/` tree equal to this checkout's (from `benchmark.plugins.commit`, not dirty), then the gate fails with the `cplat platform runs benchmark <w> --plugins plugins --reset-first` command to run.
- **AC-151.3** Given such a record, when its outcome is not `done`, or its tokens are more than 1.5 times the median of the `done` runs of the version REF names, then the gate fails and names the run, or both token counts.
- **AC-151.4** Given `cplat platform release` from a clean `main`, when the eval gate fails, then the release stops before it creates the release branch, with the gate's failures; `--skip-eval "<why>"` releases anyway and writes the reason into the release PR.

## Non-goals

- The benchmark does not run in CI: it needs a Claude session and costs tokens; the person releasing runs it.
- No new benchmark task in this spec; replaying past escalations as tasks is a follow-up.

## Open questions

- ~~How much more may a run cost?~~ Answered (recommended, self-approved for the 5.13 round on 2026-11-07): 1.5 times the last release's median; runs vary by about a third.
- ~~Which workflows by default?~~ Answered: `quick-task` and `build` (minutes each); `ship` takes up to four hours and stays optional.

## Changelog

- 2026-11-07 created from the strategy after journey 5 (item A1, "evals gate prompt changes"); approved with the recommended answers, as the user asked for this round.
- 2026-11-07 building
- 2026-11-07 done

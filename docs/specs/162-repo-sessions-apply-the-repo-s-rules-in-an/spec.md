---
spec_id: 162-repo-sessions-apply-the-repo-s-rules-in-an
title: Repo sessions apply the repo's rules in an untrusted clone
status: done
priority: P1
shape: platform
tracks: [588]
---

# 162 — Repo sessions apply the repo's rules in an untrusted clone

## Problem

`/system:ship` runs each repo in its own headless `cplat headless` session in a fresh clone (spec 155). Claude Code ignores a repo's `.claude/settings.json` in a folder whose trust dialog was never accepted, so those sessions get none of the repo's allow rules: every cplat command is refused and the ship escalates (#588, found by journey 7 on 5.14.0). The system-ship benchmark did not show it because its sample folders are trusted by hand (spec 156).

## Stories

As someone shipping a system unattended, I want each repo session to run with the repo's committed permission rules even in a clone made for the run, so that a new system ships without me opening every repo once to trust it.

## Acceptance criteria

- **AC-162.1** Given a repo whose committed `.claude/settings.json` has permission rules, when `cplat headless` starts a session there, then the session gets those rules (`allow`, `deny`, `ask`) as `--settings`, merged with the plugin Read rules it already passes, in one `--settings` value.
- **AC-162.2** Given an uncommitted change to `.claude/settings.json`, when `cplat headless` starts a session, then the rules come from the HEAD version, so the change grants nothing.
- **AC-162.3** Given a repo without `.claude/settings.json`, or with one that is not valid JSON or has no permission rules, when `cplat headless` starts a session, then it passes no repo rules and starts as before.

## Non-goals

- Changing which folders Claude Code trusts (`~/.claude.json` is never written).
- Applying the file's hooks or other settings: they stay gated by trust.
- The benchmark's trust check (spec 156) stays as it is.

## Assumptions

- **A1** Passing the repo's own committed rules is acceptable without trust, because cplat only starts sessions in repos the person asked it to ship (decided with the user on 2026-11-09; other option: keep trust required and stop at a preflight check per repo; affects AC-162.1).

## Open questions

None.

## Changelog

- 2026-11-09 building
- 2026-11-09 done

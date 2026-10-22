---
spec_id: 066-unattended-runs-stop-only-when-done
title: Unattended runs stop only when done or blocked
status: done
priority: P1
---

# 066 — Unattended runs stop only when done or blocked

## Problem

A long run ends whenever the model decides to stop: after a red test it reports "tests failing, next steps …" and hands the work back, although the next step is obvious. In the stock-manager watch and in ai-ops the user restarted such sessions by hand. Instructions in a prompt ("continue until the tests pass") are not enforced; Claude Code's `Stop` hook is.

## Stories

As a founder, I want a ship run to keep going until its tests pass, its PR is merged and `dev` runs it, or until a rule needs me, so that I approve a spec and come back to a result.

## Acceptance criteria

- **AC-066.1** Given an unfinished ship run, when the session tries to stop, then the shared plugin's `Stop` hook blocks it and its reason names the next step; in the build phase it also lists criteria without a test and the tail of a red `devbox run test-fast`.
- **AC-066.2** Given a run that was escalated (`cplat ship escalate`), is done, or was blocked N times in a row (default 8), when the session tries to stop, then it may; the cap is recorded as the escalation reason and a re-run of `/svc:ship` resumes and clears it.
- **AC-066.3** Given a session in a repository without a ship run, when it stops, then the hook does not block and exits before starting Python.

## Non-goals

- Blocking subagents (`SubagentStop`); the orchestrator handles their results.

## Open questions

None.

## References

- [Review of stock-manager, stock-manager-gitops and ai-ops](../../e2e/2026-10-22-review-unattended-delivery.md)
- [ADR-028](../../adr/028-unattended-delivery-without-branch-protection.md)

## Changelog

- 2026-10-22 created from the review of the three lan repos
- 2026-10-22 approved
- 2026-10-22 building
- 2026-10-22 done

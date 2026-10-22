# ADR-028: Unattended delivery without branch protection

**Status:** Accepted
**Date:** 2026-10-22
**Amends:** [ADR-027](027-dev-follows-main-through-pin-prs.md) (pin PRs no longer depend on auto-merge), [ADR-026](026-feature-specs.md) (a spec can be shipped unattended after approval)

## Context

A review of three repos on the lan cluster (stock-manager, stock-manager-gitops, ai-ops; [review](../e2e/2026-10-22-review-unattended-delivery.md)) found that the platform's delivery chain breaks in two places for a founder on GitHub Free with private repos:

1. **No branch protection, no auto-merge.** ADR-027's pin PRs call `gh pr merge --auto`, which a private repo on the free plan refuses, so `dev` never follows `main`. Nothing makes any merge wait for CI. ai-ops worked around it by pushing images from a laptop and pinning them by hand.
2. **Runs end at "PR opened", or earlier.** `/svc:build` stops at the PR; the user then waits for CI, fixes red checks, merges, waits for the pin and checks `dev`. Sessions also end whenever the model decides to stop, for example after a red test. stock-manager's user ran a launchd job with `claude -p --permission-mode dontAsk` and all of Bash allowlisted to get some of this unattended.

## Options

1. **Pay for GitHub Pro/Team.** It restores protection and auto-merge, but the platform should not need a paid plan to be safe.
2. **The platform merges, after it checked.** Code that waits for every check and merges only on green: in the gitops-app's workflow for pin PRs, in `cplat` for feature PRs. **(chosen)**
3. **Merge queues or rulesets.** These are not available on the free plan for private repos either.

## Decision

1. **pin-dev merges itself.** The gitops-app's `ci.yml` is also a reusable workflow (`workflow_call` with a `ref`). `pin-dev` runs it on the pin branch and merges the PR in a following job only when it succeeded; a red CI comments the run on the PR and leaves `dev` on the old image. Where branch protection exists and refuses the direct merge, it falls back to CI on the PR plus auto-merge (spec 065). Chaining jobs instead of polling means no runner waits for another, which matters on small self-hosted runner sets.
2. **`/svc:ship <spec>`** takes an approved spec through plan, build, PR, CI, merge and the `dev` pin (spec 067). The judgement stays in the command (plan and build as before, the CI fix loop with at most 3 rounds). Everything that can be code is in `cplat ship`: the run's state in the git directory, the push of the feature branch only, the PR, waiting for checks, merging only when at least one check was reported and none is pending, failed or cancelled, and waiting for the merged pin PR and Argo health.
3. **A Stop hook** in the shared plugin blocks the session from ending while a ship run is unfinished, and says what is next and what is red (spec 066). The run may stop only when it is done, after `cplat ship escalate` (a rule needs the user), or after 8 blocked stops. Without a run the hook exits in shell.
4. **`cplat headless`** runs a prompt with `claude -p --permission-mode dontAsk` (only the repo's committed allowlist applies; nothing prompts) and starts fresh sessions while the ship state is unfinished, outside a quiet window, with a log, a summary line and a notification (spec 070).
5. **`done` needs a passing `verification.md`** (spec 068), so an unattended run cannot close a spec without the reviewer's evidence.

## Consequences

- One human decision per feature: approving the spec. After that the run ends merged and deployed to `dev`, or escalated with a reason. Staging and prod stay reviewed `/gitops:promote` PRs.
- **`main` is still writable by humans on the free plan.** Agents stay off it: `git push origin main` is in the template's `ask` list, so headless `dontAsk` runs refuse it, and `cplat ship pr` pushes only `feature/<spec>`.
- `cplat ship` can push and open PRs although `git push` and `gh pr create` are `ask` rules: `cplat` is allowlisted by the shared plugin. That widens what an unattended run may do, but only to these narrow, tested steps.
- A merge happens on green checks without a human review of the PR. The spec, the acceptance tests written before the code, and the reviewer's verification are the review. Use `--no-merge` where a human should read the PR first.
- The check that pin PRs pass is in the pin-dev run, not on the PR's own checks tab; the comment on a red pin links the run.

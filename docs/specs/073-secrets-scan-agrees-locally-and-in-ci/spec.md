---
spec_id: 073-secrets-scan-agrees-locally-and-in-ci
title: Secrets scan agrees locally and in CI
status: approved
priority: P1
tracks: [103]
---

# 073 — Secrets scan agrees locally and in CI

## Problem

The templates install `detect-secrets@latest`. A baseline refreshed on the Mac picks up the gibberish filter (the Mac's detect-secrets can import `gibberish-detector`), the lan runner cannot apply it, and the same tree is green locally and red in CI (ai-ops#23, stock-manager-gitops#38, 2026-10-22). The template baselines ship `filters_used: []` (or none at all), which turns every heuristic filter off, including `is_line_allowlisted`, so the `# pragma: allowlist secret` the hook recommends does nothing.

## Stories

As an agent fixing a red security job, I want the local scan to give exactly CI's answer and the pragma to work, so that a secrets finding costs one local run, not a CI round.

## Acceptance criteria

- **AC-073.1** Given any template, when its devbox.json is read, then detect-secrets and trivy are pinned to one version each (no `@latest`), the same version in every template.
- **AC-073.2** Given any template's `.secrets.baseline.json`, when it is loaded, then `filters_used` lists the standard heuristic filters including `detect_secrets.filters.allowlist.is_line_allowlisted` and no gibberish filter, so a line with `pragma: allowlist secret` is not reported.
- **AC-073.3** Given any template, when `devbox run secrets-baseline` runs, then the baseline is regenerated over the tracked files with fixed flags (gibberish filter disabled, the standard filters kept, audited results kept), and CLAUDE.md and the security agent tell agents to use it instead of `detect-secrets scan`.

## Non-goals

- Pinning every other devbox package (decided 2026-10-22: scanners only).
- Changing which plugins (detectors) run.

## Open questions

None.

## References

- Issue #103

## Changelog

- 2026-10-22 created from issue #103
- 2026-10-22 approved

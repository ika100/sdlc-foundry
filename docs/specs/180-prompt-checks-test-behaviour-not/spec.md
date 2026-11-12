---
spec_id: 180-prompt-checks-test-behaviour-not
title: Prompt checks test behaviour not sentences
status: done
priority: P1
shape: platform
---

# 180 — Prompt checks test behaviour not sentences

## Problem

About 67 test files in the platform's test suite check that an exact sentence occurs in a plugin prompt (agents, commands, references, skills). Those checks prove only that the wording stayed the same, not that an agent still behaves correctly, and they break with every prompt change: specs 168, 171 and 172 each had to restore or re-pin phrases several times. Spec 168 also capped the total prompt size at a byte baseline in the rule register, and the prompts are now 7 bytes under it. A needed sentence cannot be added, and nothing offers a sanctioned way to raise the cap. Behaviour is already proven by the eval gate (spec 151). The tests should check structure: that the references, commands and headings a prompt points to exist. They should pin a literal only where code depends on it.

## Stories

As a platform maintainer, I want the tests to check that a prompt points to the references, commands and headings it needs instead of pinning its sentences, so that I can reword a prompt without rewriting unrelated tests.

As a platform maintainer, I want one sanctioned command that raises the prompt byte baseline only when the eval gate passes, and records why, so that a needed sentence can be added without editing the register by hand.

As a platform maintainer, I want a check that refuses new sentence pins unless they are marked as an interface, so that the pins do not grow back.

## Acceptance criteria

- **AC-180.1** Given a plugin prompt that links to a file or a heading anchor that does not exist, names a `cplat <noun> <verb>` that `cplat` does not offer, or names a slash command `/<plugin>:<command>` that no plugin defines, when `cplat platform rules check` runs, then it fails with the prompt file, the line and the missing target; with all targets present, this part of the check passes.
- **AC-180.2** Given a Python test file under `tests/` with a string literal of at least 4 words that occurs verbatim in a plugin prompt (whitespace collapsed), when `cplat platform rules check` runs, then it fails with the test file, the line, the literal and the hint to check structure or mark the literal as an interface, unless the literal's line or the line directly above carries the comment `# interface: <reason>` with a reason of at least 3 words.
- **AC-180.3** Given an `# interface:` marker whose reason has fewer than 3 words, or a marker on a line with no literal that occurs in a prompt, when `cplat platform rules check` runs, then it fails with the test file and the line.
- **AC-180.4** Given the platform repo once this spec is built, when `cplat platform rules check` runs on `main` and in CI, then it passes, and its report (text and `--json`) gives the number of interface pins. Every criterion id of an earlier spec that had a test before the rewrite still has at least one test, and `cplat spec check` stays green.
- **AC-180.5** Given a clean checkout whose prompts total more bytes than `baseline.prompt_bytes`, when the eval gate of spec 151 passes for this tree and `cplat platform rules rebaseline --reason "<why>"` runs, then the register's baseline holds the current total and the current commit. It also gains a history entry with the date, the old and new byte counts, the reason and the benchmark run ids that passed the gate, and the command prints the old and new count.
- **AC-180.6** Given `cplat platform rules rebaseline`, when the eval gate fails, the tree is dirty, or the reason has fewer than 3 words, then it exits non-zero with the gate's failures (including the benchmark command to run) or the reason for refusing, and the register is unchanged. When the prompts are not larger than the baseline, it says that nothing needs raising, exits 0 and changes nothing.
- **AC-180.7** Given a change that raises `baseline.prompt_bytes`, when `cplat platform pr-check` runs, then it shows the old and new count, the reason and the run ids from the newest history entry. It fails, naming the register line, when the raise has no matching history entry (a hand edit) or the entry's new count differs from the baseline.

## Non-goals

- Rewording or shortening the prompts themselves; this spec changes only how they are tested and how the baseline moves.
- Tests in generated repos and the templates' own test files.
- Running the benchmark in CI (spec 151's non-goal stands); the gate runs locally, as for retirements (AC-168.7).
- Lowering the baseline automatically when prompts shrink.
- Checking pins in languages other than Python; the platform's tests are Python.

## Assumptions

- **A1** A test marks a literal as an interface with the comment `# interface: <reason>` on the literal's line or the line directly above, with a reason of at least 3 words (other option: a helper function such as `pin_interface(...)`, or a list of allowed pins in the register; affects AC-180.2, AC-180.3).
- **A2** A sentence pin is any string literal in a Python test file under `tests/` with at least 4 words that occurs verbatim, whitespace collapsed, in a plugin prompt. This catches pins without parsing assertions. A literal that matches by chance (such as a `cplat` output line that a prompt also quotes) is marked as an interface (other option: only literals inside `in` assertions on text read from a prompt file, which misses pins built through helpers; affects AC-180.2).
- **A3** The structural checks and the pin guard are part of `cplat platform rules check`, so they run in CI and in `pr-check` without a new command (other option: plain tests in the test suite; affects AC-180.1 to AC-180.4).
- **A4** The structural checks cover links to files and heading anchors, `cplat <noun> <verb>` names, and slash commands. A rule's class is already covered by the register check of spec 168 (other option: also check that phase names mentioned in prose exist as headings, which is hard to detect reliably; affects AC-180.1).
- **A5** A rewritten test keeps the criterion id it traced to, so traceability does not drop. Where a pinned sentence asserted agent behaviour, the test is replaced by a structural check that the prompt points to the governing reference or heading, and the behaviour itself is left to the eval gate (other option: withdraw those criteria in their specs; affects AC-180.4).
- **A6** `rebaseline` uses the same gate as `cplat platform eval-gate` (workflows `quick-task` and `build`, plugin tree equal to this checkout) and needs a clean tree. It keeps the history of raises in the register next to the baseline, newest last (other option: history only in the changelog fragment; affects AC-180.5, AC-180.6, AC-180.7).
- **A7** A reason shorter than 3 words is refused, the same threshold spec 168 uses for reasons (other option: any non-empty reason; affects AC-180.3, AC-180.6).
- **A8** When the prompts are not larger than the baseline, `rebaseline` does nothing and exits 0. It never lowers the baseline (other option: lower it to the current total; affects AC-180.6).

## Open questions

## Changelog

- 2026-11-10 created
- 2026-11-10 approved
- 2026-11-11 building
- 2026-11-12 done

---
spec_id: 088-platform-failures-become-deduplicated
title: Platform failures become deduplicated issues
status: draft
priority: P1
---

# 088 — Platform failures become deduplicated issues

## Problem

When an unattended run stops because a template, script or command of the platform misbehaves, the run only escalates and *offers* `/shared:report-issue`; nothing reaches the platform repo unless someone reads the escalation, judges it a platform defect and files it by hand. The SDLC map of 2026-10-23 found that 18 of the last 23 specs (062–084) started from such failures that a person happened to notice (#102–#132). Failures nobody files are lost, and the same failure seen in five repos looks like one anecdote. Depends on 087: the run record is where a failure's evidence and its filed issue are linked.

## Stories

As the platform maintainer, I want every platform failure of an unattended run to arrive as an issue in the platform repo, with one issue per distinct failure and a count of how often it recurs, so that I fix the most frequent defects first instead of the ones someone happened to report.

As a user running `/svc:ship` unattended, I want a run that stopped on a platform defect to have filed that defect already, so that my escalation report tells me only what *I* must decide.

As the weekly retro (spec 090), I want each filed platform failure to carry a stable signature and a link to its run records, so that I can rank failures by occurrence across repos and weeks.

As the authors of specs 091 and 092, I want one signature-and-dedupe convention to reuse, so that smoke failures and firing alerts become issues the same way.

## Acceptance criteria

- **AC-088.1** Given an unattended ship run, when the orchestrator escalates it with cause `platform` and a one-line reason, then exactly one of these happens in the platform repo: a new issue is filed, or one comment is added to the open issue with the same signature; and the escalation output prints that issue's URL followed by `new` or `+1`, instead of offering `/shared:report-issue`.
- **AC-088.2** Given an escalation with cause `code` (the user's code or tests), `decision` (the spec or a rule needs the user) or `environment` (runner, cluster, network, missing secret or login), when it is recorded, then nothing is filed in any repo and the run record (087) carries that cause and its reason.
- **AC-088.3** Given an escalation that names no cause or an unknown one, when it is recorded, then its cause is `unknown`, nothing is filed, and the output says the cause is missing and lists the allowed causes `platform`, `code`, `decision`, `environment`.
- **AC-088.4** Given a recorded run (087), when a platform command it runs ends in an internal crash (a stack trace, not an error the platform reports with a hint), then the crash is filed or +1'd as cause `platform` at once, with the exception type and the last 20 lines of the stack trace as evidence, whether or not the run escalates afterwards; a crash outside a recorded run (for example a manual `cplat new-service`) files nothing and prints the `/shared:report-issue` hint as today.
- **AC-088.5** Given two failures, when their signatures are computed, then they are equal when the failures differ only in volatile parts (numbers, commit and image hashes, PR and issue numbers, dates and durations, URLs, file paths, repo, spec and branch names, platform version) and differ when the failing command, the run phase or the remaining failure text differ; for a crash (AC-088.4) the inputs are the command, the exception type and the innermost stack frame in the platform's own code.
- **AC-088.6** Given any issue filed by this spec, when it is read, then its body contains exactly one line `Signature: <kind>:<16 lowercase hex characters>` with kind `platform`, and its title is `[auto] ` followed by the redacted one-line reason, at most 100 characters in total; specs 091 and 092 use the same line with kinds `smoke` and `alert`.
- **AC-088.7** Given one or more open issues in the target repo carrying a signature, when the same signature is filed again, also within one minute of the first filing, then no new issue is created and one comment is added to the oldest of them, stating the occurrence number (2, 3, …), the date, the platform version, the shape and the run id.
- **AC-088.8** Given that the only issues carrying a signature are closed, when the signature is filed again, then a new issue is filed whose body says `Seen again after #<n> was closed`, unless the most recently closed one carries the label `wontfix`, in which case nothing is filed and the run record notes `suppressed by #<n>`.
- **AC-088.9** Given evidence that contains a GitHub token, a password assignment, an e-mail address, a home-directory path, the consumer repo's `owner/name`, its spec id or its branch name, when the issue or comment is written, then none of them appears in it: the redaction of `/shared:report-issue` applies to every piece of text, and the repo, spec and branch are replaced by `<repo>`, `<spec>` and `<branch>`.
- **AC-088.10** Given a new filed issue, when it is read, then its body has the sections reason, command and phase, evidence (at most the last 80 lines and 6000 characters), environment (platform version, shape, OS, tool availability) and run id, and it carries the labels `triage`, `bug` and `auto-filed`; `cplat triage setup-labels` creates `auto-filed`, and `cplat triage list` shows the issue in the intake queue like a form-filed one.
- **AC-088.11** Given a run that filed or +1'd an issue, when its run record (087) is read, then its `filed` section contains the signature, the issue URL and whether it was `new`, `+1`, `suppressed` or `pending`; and the issue or comment names the run id but contains no link to the private runs repo.
- **AC-088.14** Given that 10 new auto-filed issues were already created from one machine within the last 24 hours, when a further new signature is filed, then no issue is created, the filing is kept pending and retried once the 24-hour window allows it, and the output warns `cap of 10 new issues per 24 h reached`; +1 comments on existing open issues are not capped.
- **AC-088.12** Given that filing fails (`gh` missing or not logged in, no network, the API refuses), when a run escalates with cause `platform`, then the escalation completes with the same exit status it has without filing, its output says `not filed: <reason>`, and the filing is kept and retried the next time the run store's buffered records are flushed (087), still deduplicated per AC-088.7.
- **AC-088.13** Given automatic filing switched off by configuration (`CPLAT_AUTO_ISSUES=off`), when a run escalates with cause `platform`, then nothing is sent, the output prints the draft issue and the `/shared:report-issue` hint as today; given `CPLAT_FEEDBACK_REPO` set, issues are filed in and deduplicated against that repo instead of `ika100/sdlc-foundry`.

## Non-goals

- Deciding by heuristics or a model whether a failure is the platform's: the orchestrator states the cause; only crashes (AC-088.4) are classified without it.
- Building or fixing anything from a filed issue: the user routes it in `/shared:triage`, as decided for this round.
- Closing or relabelling issues automatically when a failure stops recurring (resolution for alerts is spec 092's).
- Deduplicating issues filed by hand with `/shared:report-issue`.
- Filing in service repos: smoke failures (091) and alerts (092) reuse this convention in their own specs.
- Strict exactly-once filing when two runs file the same new signature at the same instant; AC-088.7 lets later filings converge on the oldest issue.

## Open questions

- ~~Confirm: `environment` escalations are not filed in the platform repo.~~ Answered: yes, see AC-088.2.
- ~~New issue after a closed one, silent only after `wontfix`?~~ Answered: yes, see AC-088.8.
- ~~Confirm: filed issues never name the consumer repo, spec or branch.~~ Answered: yes, see AC-088.9.
- ~~Link the private run record or only name the run id?~~ Answered: run id only, see AC-088.11.
- ~~Cap on new auto-filed issues?~~ Answered: 10 per 24 hours per machine, see AC-088.14.
- ~~File crashes outside a recorded run automatically?~~ Answered: no, see AC-088.4.
- ~~Confirm: label name `auto-filed`.~~ Answered: yes (the retro, spec 090, finds these issues by it), see AC-088.10.
- ~~Confirm: the shape is not part of the signature.~~ Answered: yes, see AC-088.5.

## Changelog

- 2026-10-23 created
- 2026-10-23 amended: open questions answered with the suggested answers; AC-088.4 and AC-088.11 clarified (no filing outside a recorded run; `filed` section, run id without link); AC-088.14 added (cap of 10 new issues per 24 h per machine)

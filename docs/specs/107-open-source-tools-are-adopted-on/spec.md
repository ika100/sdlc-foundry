---
spec_id: 107-open-source-tools-are-adopted-on
title: Open-source tools are adopted on measured value
status: draft
priority: P1
tracks: [164]
---

# 107 — Open-source tools are adopted on measured value

## Problem

Several open-source tools promise to cut cost or defects in the platform's agent workflows. Adopting them on reputation adds dependencies, setup and failure modes to every generated repo, with no proof that clients gain anything. The platform now measures tokens, cost and outcomes per run (spec 087 run store, spec 099 `cplat runs benchmark quick-task|build|ship` and `cplat runs report`), so a tool can be judged against a baseline. This spec defines the evaluation: which candidates, what evidence, and the decision record per candidate. It integrates nothing.

## Stories

As the platform owner, I want each candidate tool evaluated against a measured baseline, so that I adopt only tools with evidence-backed benefit.

As the platform owner, I want one decision record per candidate (adopt, pilot further, defer or reject), so that the reasons survive and the same tool is not re-argued.

As a client of the platform, I want only tools that measurably help me to reach my repos, so that my setup stays lean.

## Acceptance criteria

Candidates, exactly the ones issue #164 names: (1) Codebase-Memory MCP, for code intelligence and change impact; (2) pytest-testmon and pytest-impact, for change-aware test selection (one candidate area; #142); (3) Semgrep and Trivy, for quality and security evidence; (4) a lean LLM tracing/evaluation tool, only if the review in AC-107.5 finds a gap OpenTelemetry export (spec 101) leaves open.

- **AC-107.1** Given the evaluation, when it starts, then a baseline is recorded before any tool is tried: for each workflow the candidate affects, at least 5 `cplat runs benchmark` runs (`quick-task`, `build`, `ship`) on the platform version in use, with median tokens, median cost, outcomes and gate results from `cplat runs report --benchmarks`. The baseline names the platform version and the sample repo revision.
- **AC-107.2** Given a candidate, when it is evaluated, then it runs on the same benchmark tasks and revision as the baseline, at least 5 runs per affected workflow, and the same report gives the same figures. A difference is called a benefit only if it exceeds the spread of the baseline runs (min to max); otherwise the record says "no measurable difference".
- **AC-107.3** Given a candidate, when its record is written, then it states the hypothesis before the trial, the measure that decides it, and the result of that measure. Each candidate has its own decisive measure:
  - Codebase-Memory MCP: tokens and cost per delivered run, and defects found by the acceptance and security gates, against a minimal native alternative (as in #139).
  - pytest-testmon / pytest-impact: validation time saved, and affected-test recall measured against the full suite (a missed failing test is a failure of the candidate).
  - Semgrep / Trivy: findings that the existing gates do not already report, with false positives counted, and no weakening of any existing gate.
- **AC-107.4** Given a candidate that affects quality or security evidence, when it is trialled, then the existing gates stay in force and unchanged during the trial; the candidate is judged on what it adds (findings, auditability) and what it costs (run time, tokens, false positives).
- **AC-107.5** Given the tracing/evaluation candidate, when it is considered, then the record first lists the specific agent-visibility questions the run store (087, 099) and the OTel export (spec 101) cannot answer, with a concrete example run each. With no such gap the decision is "reject: no demonstrated gap" and no tool is trialled.
- **AC-107.6** Given a finished trial, when the decision is recorded, then it is exactly one of `adopt`, `pilot further`, `defer` or `reject`, with the figures from AC-107.1 and AC-107.2, the licence, the maintenance state (last release date) and the added setup the client would carry.
- **AC-107.7** Given a decision `adopt`, then it requires a measured benefit under AC-107.2, no regression in the benchmark outcomes or gate results, and no weakened gate. Given `pilot further`, the record names what to measure next and a stop date. Given `defer` or `reject`, the record names the reason and what new evidence would reopen it.
- **AC-107.8** Given the decision records, when someone looks for them, then they are in one place, one per candidate, each listed in an index with candidate, decision, date and platform version; the index also states the baseline of AC-107.1.
- **AC-107.9** Given a trial, when it runs, then it uses only the benchmark sample repo and local trials; no client repo, generated template or plugin default changes during the evaluation, and benchmark runs are marked so they stay out of the normal report (AC-099.11).
- **AC-107.10** Given a record that cites a figure, when a reader checks it, then the figure names the run ids it came from, so it can be reproduced from the run store.
- **AC-107.11** Given a decision `adopt`, when the evaluation closes, then a follow-up spec for the integration is proposed (not written here) and the record links to it; until it ships, nothing in templates, plugins or `cplat` depends on the tool.

## Non-goals

- Integrating any tool into templates, plugins or `cplat`; each adopted tool gets its own follow-up spec.
- Agent observability and OpenTelemetry export, which spec 101 covers; the tracing candidate only fills a gap proven under AC-107.5.
- Requirements-to-evidence traceability (kept native, per the issue) and any tool the issue does not name.
- Token or cost budgets and enforcement (#144) and context pruning (#139) beyond serving as the comparison for candidate 1.
- Changing the benchmark tasks or the price table of spec 099.

## Open questions

- Is 5 runs per workflow and arm enough, given run cost? (suggested: 5, and the spread rule of AC-107.2 guards against noise; affects AC-107.1, AC-107.2)
- Should the "minimal native alternative" for Codebase-Memory MCP be built as part of the evaluation or compared on paper? (suggested: on paper unless the tool shows a benefit, then a cheap native baseline is a follow-up; affects AC-107.3)
- Where do the decision records live: a new `docs/evaluations/` folder, or as ADRs? (suggested: ADRs, since decisions outlive the change, with the index in the ADR README; affects AC-107.8)
- Should pytest-testmon and pytest-impact count as one decision or two? (suggested: two records, one per tool, same trial; affects AC-107.3, AC-107.6)
- Should all candidates be evaluated in one pass, or in order of expected value? (suggested: change-aware tests first, then Semgrep/Trivy, then Codebase-Memory MCP, tracing last; affects AC-107.1)

## Changelog

- 2026-10-25 created

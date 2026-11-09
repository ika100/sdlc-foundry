---
spec_id: 168-agent-rules-state-their-reason-and-can
title: Agent rules state their reason and can retire
status: approved
priority: P1
shape: platform
---

# 168 — Agent rules state their reason and can retire

## Problem

Agents read every sentence of a plugin prompt (agents, commands, references, skills) as a rule and follow it faithfully, also where it does not fit. Rules written as condition lists ("tester only when the touched files add internals that no unit test covers … security only when a Dockerfile changed", build Phase 3) can never list every case, while a stated purpose covers the cases nobody listed. Many rules carry only an issue number as their reason ("never poll for one in a shell loop (#496)"); the command, reference and agent prompts hold about 161 references to issues, specs and ADRs, and the build command alone is 14.5 KB. Every incident adds a rule and none is ever removed, because nobody can tell whether a rule's reason still holds; true hard rules ("never decide yourself that it is a false alarm", spec 048; frozen acceptance tests, spec 165; no Kubernetes manifests in component repos, ADR-017) drown among them. This is the prompt step of the token-usage plan (specs 099, 100, 102): the benchmark and eval gate (spec 151) now prove whether a removal is safe.

## Stories

As a platform maintainer, I want every rule in the plugin prompts classified and carrying a reason an agent can evaluate, so that agents apply the purpose to cases nobody listed and I can tell which rules may go.

As a platform maintainer, I want a check that refuses new condition lists and rules without a reason, so that the prompts do not grow back into a list of exceptions.

As a platform maintainer, I want the weekly retro to propose rules to retire with evidence, and every retirement proven by the eval gate, so that the prompts get smaller without runs getting worse.

As an agent running a build, I want to see which rules are hard and which are practices with a purpose, so that I never bend a hard rule and do not follow a practice where its purpose does not apply.

## Acceptance criteria

- **AC-168.1** Given the plugin prompts (every file under the agents, commands, references and skills of every plugin, as spec 151 defines them), when `cplat platform rules check` runs, then every rule sentence (a sentence or bullet containing "never", "always", "must", "do not", "don't", "only", "unless" or "except") has exactly one entry in the rule register, classed `hard`, `practice`, `experience` or `not a rule`; a rule sentence without an entry, or an entry whose quoted rule text no longer occurs in its file, fails the check with the file, the line and the text.
- **AC-168.2** Given a rule classed `hard`, `practice` or `experience`, when the check runs, then it fails, naming file and line, when the rule's sentence or bullet in the prompt has no reason clause (introduced by "so that", "because", "since" or "otherwise"), or when the reason clause, with issue, spec and ADR references (`#496`, `spec 048`, `ADR-017`) removed, has fewer than 3 words.
- **AC-168.3** Given a rule classed `practice` or `experience`, when its sentence contains a condition clause ("only when", "only if", "unless", "except"), then the check fails with the file, the line and the hint to state the purpose instead; a `hard` rule may keep a condition clause.
- **AC-168.4** Given a rule classed `hard`, when the check runs, then it fails unless the register names either the `cplat` command or CI job that enforces it (a command that `cplat` offers, or a job defined in the platform repo's or a template's workflows) or marks it `intentional prose rule` with a reason of at least 3 words why no tool can enforce it; it also fails when the register holds more than 20 distinct `hard` rules (one rule repeated in several prompts counts once).
- **AC-168.5** Given any agent definition or command prompt, when an agent reads it, then each `hard` rule's sentence carries the visible marker "**Hard rule:**" and the prompt states once that a hard rule is never departed from, and that a practice may be departed from when its stated purpose does not apply, the agent naming each such departure and its reason in one line of its report; the check fails on a `hard` rule without the marker, a marker on a rule not classed `hard`, or a prompt without the statement.
- **AC-168.6** Given the platform repo once this spec is built, when `cplat platform rules check` runs on `main` and in the platform's CI, then it passes; each rule the sweep removed is listed in the register as `retired` with the date, the reason it no longer holds and the enforcing `cplat` command or CI job where there is one; and the total size in bytes of the plugin prompts is not larger than at the commit before the sweep.
- **AC-168.7** Given a change that retires or removes one or more register entries, when `cplat platform pr-check` runs, then it applies the eval gate (spec 151, workflows `quick-task` and `build`) to the change's plugin tree and fails with the gate's failures, including the benchmark command to run, unless the gate passes; each retired entry records the benchmark run id that passed it.
- **AC-168.8** Given the weekly retro (spec 090), when its proposals are written, then it adds a section "Rules to retire" with at most 3 register entries, ranked by prompt bytes saved, each naming the entry, its reason and its evidence: either the `cplat` command or CI job that now enforces a `practice` or `experience` rule, with that check's failures in the covered week, or an `experience` rule whose source issue is closed and whose cause (its auto-filed issue signature or an escalation reason citing it) occurred in 0 run records over the last 4 complete weeks, with the number of runs in that window; with no such entry the section says "none this week". The retro changes no prompt or register file and the posted issue follows AC-090.11.

## Non-goals

- The instructions rendered into generated repos by the templates (their `CLAUDE.md` and similar) and a consumer repo's own instructions.
- Procedure steps that are not rules (decision tables such as "exit 3 → set aside", command sequences); they are not rewritten unless a rule sentence sits in them.
- Building new `cplat` or CI enforcement for a hard rule that is today prose only; this spec marks it `intentional prose rule` or names an existing enforcement, and a new enforcement is a follow-up spec per rule.
- Retiring rules automatically: the retro only proposes (AC-090.9), the maintainer decides and the eval gate proves.
- Running the benchmark in CI (spec 151 non-goal stands).
- The dispatcher of spec 167; the two specs are independent.

## Assumptions

- **A1** The classification lives in one rule register in the platform repo, outside the prompt text, so agents never load it; each entry holds the file, the quoted rule text, the class, the source (issue, spec or ADR, optional) and, for hard rules, the enforcement (other option: an inline marker per rule in every prompt, which costs tokens on every turn; affects AC-168.1, AC-168.4, AC-168.6).
- **A2** The reason itself stays in the prompt sentence, so the agent reads it where it applies; the register does not repeat it (other option: reasons only in the register; affects AC-168.2).
- **A3** A rule sentence is found by the word list "never", "always", "must", "do not", "don't", "only", "unless", "except"; a matched sentence that is not a rule is entered as `not a rule` (other option: a shorter list without "only", which misses rules such as "Only approved specs are built"; affects AC-168.1).
- **A4** A reason clause starts with "so that", "because", "since" or "otherwise", and a reason with fewer than 3 words besides references counts as missing (other option: any clause after a dash or colon; affects AC-168.2).
- **A5** The check fails in CI rather than only warning, for missing entries, missing reasons and condition clauses in practices alike (other option: warn on condition clauses; affects AC-168.1 to AC-168.5).
- **A6** At most 20 distinct hard rules, enforced by the check (other option: no ceiling, or a warning only; affects AC-168.4).
- **A7** Hard rules are marked in the prompt with "**Hard rule:**" so an agent can tell them from practices; practices and experience rules carry no marker (other option: a "Hard rules" section per prompt; affects AC-168.5).
- **A8** The sweep may not grow the prompts: total bytes after it are at most the bytes before (other option: a fixed cut, such as 10 %; affects AC-168.6).
- **A9** The eval gate for a retirement runs through the existing local `cplat platform pr-check`, since the benchmark needs a Claude session and cannot run in CI (other option: only before a release, as spec 151 does today; affects AC-168.7).
- **A10** Retirement proposals are a separate retro section with their own cap of 3, besides the 3 prompt-change proposals of AC-090.9; the evidence window is the last 4 complete ISO weeks (other option: share the cap of 3; a window of 8 weeks; affects AC-168.8).
- **A11** `cplat platform rules check` is the command name, beside `eval-gate` and `pr-check` (other option: a step of `cplat platform pr-check` only; affects AC-168.1 to AC-168.6).

## Open questions

## Changelog

- 2026-11-09 created
- 2026-11-09 approved

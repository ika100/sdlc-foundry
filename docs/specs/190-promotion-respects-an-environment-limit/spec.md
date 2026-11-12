---
spec_id: 190-promotion-respects-an-environment-limit
title: Promotion respects an environment limit in the spec
status: approved
priority: P1
shape: platform
tracks: [688]
---

# 190 — Promotion respects an environment limit in the spec

## Problem

In journey 11 (platform 5.18.0) a system spec's one open question was whether people may use the app without a login. The
suggested answer, taken unattended, was "Yes for dev", so the spec allowed anonymous use in dev only and the session said an
authentication spec must come before staging. Later `/instance:promote` promoted both components to staging and prod
without a login: the limit lived in prose, nothing read it, and nothing flagged it. Two things went wrong: a suggested answer
created an environment limit nobody had asked for, and promotion ignored the limit once it existed. Both cost the user a
system running in prod against a decision they had approved.

## Stories

- As the person who promotes a system, I want promotion refused when an approved spec limits the system to environments
  the target is not in, so that a decision like "anonymous use in dev only" cannot reach staging or prod by accident.
- As that person, I want to override the limit deliberately, with a reason that is recorded in the PR, so that a conscious
  exception stays possible and visible.
- As someone approving a spec, I want to see at approval when an answer limits the environments, so that I do not approve a
  limit I did not ask for.

## Acceptance criteria

- **AC-190.1** Given a spec whose front matter carries `environments: [<env>, …]` (the environments its behaviour may run
  in, out of dev, staging, prod), when `cplat spec check` runs, then an unknown environment name or an empty list is an
  error naming the spec and the bad value; a spec without the field limits nothing.
- **AC-190.2** Given a gitops-app repo where a system spec with status `building` or `done` carries `environments:` without
  the target environment, when `cplat instance promote <component…|--all> --to <env>` runs (with or without `--pr`), then it
  exits 1, opens no PR and changes nothing, and prints one line per limiting spec,
  `environment limit: <spec_id> allows <envs>, not <target> (<title>)`, plus a `fix:` line naming the two ways on
  (widen the spec with `/system:spec --amend` once the work that lifts the limit has shipped, or the override of AC-190.3);
  with `--dry-run` the same lines appear as `REFUSED:` lines in the preview and it exits 1.
- **AC-190.3** Given the refusal of AC-190.2, when the person passes `--accept-environment-limit "<reason>"` with a reason of
  at least one sentence (3 or more words, ending in `.`, `!` or `?`), then the promotion proceeds and both the output and
  the PR body carry `environment limit accepted: <spec_id> (<envs>): <reason>` for each limiting spec; given the flag with
  a shorter reason, then it is refused before anything is read or written.
- **AC-190.4** Given a system whose staging moves automatically after a green dev smoke (`promote: after-dev-smoke`, spec
  093) and a limiting spec as in AC-190.2 without staging, when the dev smoke is green, then no staging pin is dispatched and
  the ship's output says `staging: not promoted: environment limit <spec_id> allows <envs>`; the ship does not count this
  as a red step.
- **AC-190.5** Given a spec carrying `environments:`, when it is shown or approved (`cplat spec show`, `cplat spec approve`,
  and the approval summary of `/system:spec` and `/component:spec`), then the output contains the line
  `Environment limit: <envs> (promotion to <the other environments> is refused)`, and `--json` carries the list as
  `environments`.
- **AC-190.6** Given the product-manager writing an open question whose suggested answer would keep the feature out of an
  environment, when it writes the question, then the question text names the limit (`limits to <envs>`), the suggested
  answer never limits an environment the request asked for (for example "reachable in every environment"), and once such
  an answer is taken the spec carries the matching `environments:` field; a benchmark case with a request for every
  environment shows no suggested answer that limits one.
- **AC-190.7** Given the `/instance:promote` command text and the promotion guide, when they describe promotion, then they
  state the environment-limit rule, the refusal, the dry-run output and the override.

## Non-goals

- Reading limits from prose: only the `environments:` field counts.
- Limits on resources, exposure or secrets per environment, or any check after deploy.
- Removing a limit automatically when a later spec ships: widening the field is an amendment the person makes.
- Changing the digest rule (spec 106), the prod evidence summary or the production confirmation.

## Assumptions

- **A1** The limit refuses the promotion, with an explicit override, rather than warning (other option: warn and proceed;
  affects AC-190.2, AC-190.3).
- **A2** A system spec's limit applies to every component of its system, whichever components are promoted (other option:
  only the components named in its stories' `**Repos:**` lines; affects AC-190.2, AC-190.4).
- **A3** Only specs with status `building` or `done` limit a promotion, because their code may be in the images; `draft`,
  `approved` and `superseded` specs do not (other option: `approved` too; affects AC-190.2).
- **A4** Promotion reads the system specs of the gitops-app repo only, not the component repos' specs (other option: read
  each promoted component's specs from its clone too; affects AC-190.2).
- **A5** The override reuses the digest override's reason rule (one sentence, 3 or more words) and one flag covers every
  limiting spec of that promotion (other option: one flag per spec id; affects AC-190.3).
- **A6** The automatic staging promotion has no override; a person promotes with `/instance:promote` and the flag (other
  option: an `instances.staging` setting that accepts the limit; affects AC-190.4).
- **A7** The field is named `environments` and lists the allowed environments, not the forbidden ones (other option:
  `not_in: [staging, prod]`; affects AC-190.1, AC-190.5).
- Decided by the user (2026-11-12): only a person may override. An agent passes `--accept-environment-limit` only after the user's explicit yes and reason, a hard rule in `/instance:promote` as for `--accept-digest-mismatch`; an unattended run stops and asks.

## Open questions

None.

## Changelog

- 2026-11-12 created
- 2026-11-12 approved

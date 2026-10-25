# ADR-039 — The weekly retro: a deterministic report in code, agent proposals checked against it

**Status:** accepted (2026-10-24, spec 090)

## Context

Specs 087, 088 and 089 turn runs, platform failures and agent quality into data: run records in a private run store
(ADR-032) and auto-filed issues with a signature line in the public platform repo (ADR-033). The platform maintainer
still picks the next specs from memory. Spec 090 adds a weekly retro that ranks what hurt most and proposes the next
specs and agent-prompt changes. Three tensions shape it:

- Ranking and counting must be reproducible, but turning findings into proposals is judgement.
- The data is private (consumer repos, spec ids, run text), but the proposals should land where the platform work is
  planned: the public platform repo.
- The retro must run without anyone starting it, yet a broken store or a missing credential must be noticed.

## Decision

- **The report is code, the proposals are an agent's.** `cplat retro` builds the report as a pure function of the run
  records, the platform issues, the platform's specs and the covered ISO week. The same inputs always give the same
  report, apart from its timestamp. A headless Claude run reads that report and writes proposals as a JSON file. It
  never computes a figure.
- **Every proposal must cite the report.** The report publishes an evidence index: a flat map from a stable reference
  (`escalations.platform`, `issues.#123`, `agents.svc:coder|service-python|sonnet.fix_rounds.avg`, …) to its value.
  `cplat retro post` posts only proposals whose evidence references exist in the index with the cited value. It
  enforces the limits (5 specs, 3 prompt changes), the format, and the link to an existing spec or open issue. It
  names every proposal it refuses. An agent mistake costs one proposal, never the report.
- **Public counts, private detail.** The platform-repo issue shows repos only as counts per shape and runs only by run
  id. It contains no record text, no consumer repo or spec names, and no name of or link to the run store. Free text
  from records (escalation reasons, check names) appears there only as ranked placeholders such as `reason 1`, with
  run ids. The full report, with that text and per-repo detail, is committed to the run store under `retros/`. The
  store's `retros/README.md` links each week to its issue. Everything posted passes `feedback.redact` and the private
  names of ADR-033, and a final leak check refuses to post a body that still names a consumer repo, a spec id from a
  record, or the store.
- **The schedule lives in the private store repo.** `cplat runs init` installs `.github/workflows/cplat-retro.yml` there.
  It runs Mondays 06:00 UTC on the store repo's self-hosted runner, with a Claude credential secret and a GitHub token
  secret of the store repo. The report step failing makes the run red and posts nothing. A failing proposal step only
  replaces the proposals with `Proposals: not generated (<reason>)`. `cplat doctor` warns when the schedule or a
  secret is missing.
- **One issue per week, labelled `retro` only.** A re-run replaces that week's issue body. Posting a week closes the
  open retro issues of earlier weeks with one linking comment. Retro issues never get `triage`. Nothing goes through
  `/shared:triage`, no proposal is filed as its own issue, and no agent file or pull request is ever changed.

## Consequences

- The maintainer reads one issue per week and starts a spec from a proposal's `/svc:spec` line. Every number in it can
  be traced to the private report in the store.
- The proposal prompt and the evidence references are a contract. Renaming a report field breaks references in the
  prompt, so report fields change only with a spec.
- The store repo needs a self-hosted runner, a `CLAUDE_CODE_OAUTH_TOKEN` (or `ANTHROPIC_API_KEY`) secret and a
  `RETRO_GH_TOKEN` secret (issues on the platform repo, contents on the store). Without them the retro is reported
  as not scheduled, or as having no proposals. It never fails silently.
- Writing a workflow file through the API needs a token with the `workflow` scope. `cplat runs init` warns and names the
  fix when the token lacks it.

## Not included

- Retros for consumer products or single repos, notifications other than the issue, dashboards.
- Applying proposals: writing specs, editing agent prompts, opening pull requests.
- Reading smoke-failure or alert issues (091, 092) into the retro.

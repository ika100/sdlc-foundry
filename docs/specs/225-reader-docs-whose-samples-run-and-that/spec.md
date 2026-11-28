---
spec_id: 225-reader-docs-whose-samples-run-and-that
title: Reader docs whose samples run and that read well
status: draft
priority: P1
shape: platform
---

# 225 — Reader docs whose samples run and that read well

## Problem

The quickstart's manifest and install block are tested, and `check-docs.py` checks that the named commands, flags, plugins and recipes exist. Nothing runs the other samples: the shell sessions, the manifests, YAML snippets and shown output on the guides and site pages. Nothing checks either whether a sentence about what a command does, which files it writes, which agents it calls or which environments and autonomy levels apply still matches the code. Samples and statements drift with every release, and a newcomer who copies a wrong one loses trust in the rest. The pages also differ in tone and density: some open without saying who they are for, some carry long sentences and undefined jargon, and many are walls of text where steps, asides, tables or a diagram would read faster. The site theme, the diagrams and the recordings have not been reworked since the site launched, and several recordings predate the current commands.

## Stories

As a newcomer, I want every sample I copy from the docs to work as shown, so that I can follow a page without guessing what changed.

As a reader, I want what a page says about a command, a template or an environment to be true for the version I installed, so that I can rely on the docs instead of reading the code.

As a reader, I want each page to say up front who it is for and what I get, in plain language with defined terms, so that I find the right page and understand it on first reading.

As a visitor of the site, I want structured pages, clear diagrams of the key flows and a polished theme in light and dark mode, so that the platform is easy to grasp and looks trustworthy.

As the maintainer, I want CI to keep samples, statements and the style bar from drifting, so that the docs stay right without another review round.

## Acceptance criteria

In scope everywhere below are the reader pages: `README.md`, `docs/QUICKSTART.md`, the guides in `docs/` that the site sync publishes, and the hand-written site pages, without the exclusions listed under Non-goals.

Samples.

- **AC-225.1** Given a fenced shell, console or YAML block on a reader page, when `check-docs.py` runs, then the block must carry one sample marker: `fast` (runs without cluster and network), `e2e` (needs the local cluster), `output` (shown output of the block before it), `illustration` (a fragment or a usage line not meant to run as written) or `manual: <reason>`; a block without a marker, or `manual` without a reason, fails with file and line. An `illustration` stays honest: a YAML illustration must still parse as YAML (and a system manifest still validates as in AC-161.2), and a shell or console illustration must contain at least one `<placeholder>`; one without fails as an unmarked runnable block. On the site a `manual` block shows its reason in a visible note ("Not run automatically: <reason>").
- **AC-225.2** Given the `fast` blocks, when the fast test suite runs, then each runs in a fresh scratch area, in repos generated from the templates where the page says so, without network, and a block that exits non-zero, or whose following `output` block does not match the produced output after normalising ids, times, hashes and paths, fails the suite naming page and line.
- **AC-225.3** Given the `e2e` blocks, when the cluster e2e runs on the local kind cluster, then each runs in page order against the e2e's system, and a failing block fails the e2e with page and line; the e2e prints how many doc blocks it ran.
- **AC-225.4** Given the change lands, when the verification record in the spec folder is read, then it lists every marked block of every reader page with its marker and result from one real run on fresh repos and the local cluster (`passed`, `fixed: <what was wrong>` or `manual: <reason>`), names the platform version and date of the run, and no block on the pages is left in a state the record shows as failing.

Consistency with the code.

- **AC-225.5** Given each reader page, when the change lands, then every statement about behaviour (what a command does, its flags and defaults, the files it writes, the agents it calls, the order of steps, the environments, the autonomy levels, the template contents, versions and requirements) has been compared with the current commands, agents, `cplat`, templates, shape registry and `devbox.json`; wrong or outdated statements are fixed, user-facing behaviour a reader needs and the page lacks is added, and the verification record lists each page as `consistent`, `fixed: <what>` or `not checkable: <why>`.
- **AC-225.6** Given a reader page, when `check-docs.py` runs, then it fails with file and line on a `cplat <subcommand>` that `cplat` does not define, a `--flag` after a `cplat` subcommand that its argument parser does not accept, a shape name that the shape registry does not list, and a `<plugin>:<agent>` in code that names no agent file; the shape list and the starter plugin set on the pages come from the registry and the starter plugin, generated like the command reference, so they cannot drift.

Readability.

- **AC-225.7** Given a reader page, when `check-docs.py` runs, then it fails with file and line when the page has no lead paragraph before its first heading of at most 2 sentences and 50 words, when a prose sentence (outside code, tables and headings) is longer than 35 words, when the page's mean prose sentence length is above 20 words, when a prose paragraph is longer than 100 words, or when the page uses a term the style guide lists as replaced, naming the domain-model term to use instead.
- **AC-225.8** Given the docs, when they are read, then a style guide states the rules of AC-225.7 with their numbers and the term list taken from the domain model, a glossary page on the site under Reference defines every term in that list in one or two plain sentences, and the first use of a glossary term on a reader page links to its glossary entry; `check-docs.py` fails a first use without that link, with file and line. A glossary term is an entry heading of the glossary plus the aliases the entry lists; its first use is its first match on the page, whole word, case-insensitive, singular or plural, in prose only (not in code, headings, image alt text or the text of another link); the link must point to that entry's anchor; the glossary itself and the page an entry names as the term's home page are exempt.

Look.

- **AC-225.9** Given the built site, when a visitor opens the quickstart and the local-cluster page, then their numbered steps render as Starlight steps, prerequisites, warnings and failure hints as asides, and alternative commands (macOS and Linux) as tabs; the landing page shows a hero with one call to action to the quickstart (AC-161.9 stays) and cards to Get started, Concepts, Scenarios and Guides.
- **AC-225.10** Given the built site, when a visitor reads the pages of the SDLC loop, GitOps and promotion, environments and the domain model, then each shows one diagram of that flow as SVG with alt text, that uses the theme's colours so it reads in light and dark mode, and the built site makes no request to a third-party host (AC-032.3 stays); a test of the build fails on an external script, style, font or image URL.
- **AC-225.11** Given the site theme in light and dark mode, when the contrast test runs on its colour settings, then body text, links, code and code-block backgrounds reach a contrast of at least 4.5:1 and headings at least 3:1, the fonts come from the site itself, and code blocks show a copy button and a title where the page gives one.
- **AC-225.12** Given a terminal recording or screenshot on a reader page, when the change lands, then each has alt text, shows only steps and output of a real run, shows no GitHub account, organisation or home path of the maintainer (neutral names such as `~/work` and `demo-org` replace them in the shown output, and steps that need GitHub are `manual` and not recorded), and is listed in the verification record with the command it shows, the platform version and the date it was made; an image on a reader page missing from the record or without alt text fails `check-docs.py`.

## Non-goals

- Content for pages outside the reader pages: ADRs, specs, the changelog, `PERFORMANCE.md`, `BASELINES.md`, `AGENTS.md`, the backlog, plugin READMEs and the generated reference pages; the reference generator changes only for looks.
- The web console: no console feature work and no console screenshots, because the user is reworking the UI; its guide is checked for consistency and readability only.
- Translating the docs.
- A new docs framework or a client-side diagram renderer that loads code at view time.
- Running samples that need GitHub, a paid service or production; they carry a `manual` reason.
- A platform release; another session releases.

## Assumptions

- **A1** Samples are proven by running them for real on fresh repos and the local kind cluster, wrong ones are fixed, runnable ones become permanent checks, unrunnable ones are marked with a visible reason (affects AC-225.1, AC-225.2, AC-225.3, AC-225.4) (decided in explore)
- **A2** The scope is the reader pages named above; generated reference pages change only in their looks (affects all criteria) (decided in explore)
- **A3** Every behaviour statement on the reader pages is checked against the current code, fixed or completed, and kept consistent by checks where feasible (affects AC-225.5, AC-225.6) (decided in explore)
- **A4** Guides name ADRs, not spec numbers; the rule of spec 173 stays (affects AC-225.7, AC-225.8) (decided in explore)
- **A5** Recordings and screenshots come from real runs only, never invented steps or output (affects AC-225.12) (decided in explore)
- **A6** The work lands as one PR per area (samples and consistency, text, look), merged on green CI, built unattended after approval (affects all criteria) (decided in explore)
- **A7** A marker is an HTML comment on the line before the block, so the page renders unchanged on GitHub (other option: a fence attribute such as ```` ```bash fast ````; affects AC-225.1).
- **A8** The e2e scope rule is unchanged: a docs-only PR does not start the cluster e2e (spec 220), so an edited `e2e` block is proven by the next e2e run on a code PR or on `main` (other option: reader pages with `e2e` blocks join the e2e scope; affects AC-225.3).
- **A9** The readability bar is sentence and paragraph length plus a term list, not a readability formula, because the numbers are deterministic and easy to fix against (other option: a Flesch reading-ease floor; affects AC-225.7).
- **A10** The limits are 35 words per sentence, a mean of 20 per page, 100 words per paragraph and a lead of at most 2 sentences and 50 words (other option: 30 / 18 / 80; affects AC-225.7).
- **A11** Diagrams are committed SVGs (the existing ones refreshed where they fit), styled with the theme's colour variables, not Mermaid rendered in the browser, so no script loads at view time (other option: Mermaid rendered at build time; affects AC-225.10).
- **A12** `docs/console.md` is a reader page for consistency and readability, but gets no screenshots (other option: leave it out entirely; affects AC-225.5, AC-225.12).
- **A13** A change to the site's dependencies keeps the lock file change additive: the PR removes no package entry, checked before merge, because an `npm install` on macOS drops Linux-only packages (other option: regenerate the lock file in Linux CI; affects AC-225.10, AC-225.11).
- **A14** Recordings and screenshots use neutral names (`~/work`, `demo-org`), replace the maintainer's account, organisation and home path in the shown output, and leave GitHub steps as `manual` (affects AC-225.12) (decided by the user).
- **A15** Syntax fragments and usage lines get an `illustration` marker instead of `manual`, because they are not meant to run and a reason on each would be noise; they stay checked by parsing and the placeholder rule (other option: `manual: illustration`; affects AC-225.1).

## Notes for the architect

- Extend `check-docs.py` and the fast test that already reads `docs/QUICKSTART.md` (spec 161) instead of adding a second checker; the site still builds with `npm ci` and the build, and links stay checked by `check-links.py` and the site's link validator.
- The fonts are bundled; keep them so.
- `AGENTS.md` is synced to the site but out of scope by the user's decision; leave it unmarked and exclude it from the new checks.

## Open questions

- ~~May recordings and screenshots from real runs show the maintainer's GitHub account, organisation or home path on the public site? (suggested: no; record with neutral names and replace the account and home path in the shown output, and record GitHub steps only as `manual`; affects AC-225.12)~~ Answered 2026-11-28: no; folded into AC-225.12 and A14.

## Changelog

- 2026-11-28 created
- 2026-11-28 priority P1 proposed: P1: normal bug or feature
- 2026-11-28 amended: recordings show no maintainer account, organisation or home path (open question answered); an `illustration` marker for fragments; glossary first use defined precisely.

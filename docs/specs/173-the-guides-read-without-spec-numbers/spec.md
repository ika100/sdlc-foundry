---
spec_id: 173-the-guides-read-without-spec-numbers
title: The guides read without spec numbers
status: approved
priority: P2
shape: platform
tracks: []
---

# 173 — The guides read without spec numbers

## Problem

Spec 161 removed spec numbers and criterion ids from the newcomer pages and left the deep guides for a later round. They still carried about 110: `docs/unattended-delivery.md` 26, `DOMAIN-MODEL.md` 20, `AGENTS.md` 12, `ADOPTING.md` 9 and a few in six more guides. A reader of the site cannot open `docs/specs/`, so "(spec 102)" says nothing, and several references were stale: `DOMAIN-MODEL.md` said a cache or broker downgrade "is not refused before spec 121", although spec 121 shipped and `/resource:upgrade` refuses it; `UPGRADES.md` pointed to "the order of AC-121.20 … stated for a later spec". The ADR links next to most references already give the provenance a reader can follow.

## Stories

As a reader of a guide, I want plain statements without internal spec numbers, so that every sentence means something to me.

As the maintainer, I want the docs check to keep it that way for every guide, so that new references do not creep back.

## Acceptance criteria

- **AC-173.1** Given a guide in `docs/` that `check-docs.py` checks, when it runs, then a spec number (`spec NNN`) or criterion id (`AC-NNN.n`) in the body text fails with file and line, as on the newcomer pages of spec 161 (AC-161.10).
- **AC-173.2** Given the measurement records `docs/PERFORMANCE.md` and `docs/BASELINES.md`, a `## … 4.x …` history section, or a closing section whose heading starts with "Background", when `check-docs.py` runs, then spec numbers there pass: they name where a number or a mapping came from.
- **AC-173.3** Given the repository's guides, when `check-docs.py` runs, then none names a spec outside AC-173.2's exceptions; a reference next to an ADR link keeps only the ADR link, and a stale "not before spec N" or "comes with spec N" says what is true today.

## Non-goals

- The site's generated reference pages, the ADRs, the specs and the changelog, which record provenance by design.
- Rewriting the guides beyond the references.

## Assumptions

- **A1** The two measurement records keep their spec numbers (other option: rewrite them too; affects AC-173.2).

## Open questions

## Changelog

- 2026-11-10 drafted and approved: the user asked to improve the documentation further; this is spec 161's open follow-up.

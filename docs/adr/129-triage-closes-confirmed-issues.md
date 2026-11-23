# ADR-129: Triage closes confirmed issues

**Status:** Proposed (2026-11-23)

## Context

ADR-025 point 5 said triage never closes an issue. Confirmed questions, duplicates and wontfix issues, and `needs-info` issues the reporter never answers, then stay open for ever and bury real work. Outside reporters also get comments full of internal terms and asks for fields the issue form already holds (spec 177).

## Decision

Triage closes confirmed question, duplicate and wontfix issues and silent needs-info issues as not planned; comments to outside reporters use plain words.

## Consequences

- The hard rule keeps its register id `triage-never-closes`; only its text changes, because the spec 168 tests pin the id list.
- `act` closes only the rows a person names in `--rows`; an unattended run closes nothing.
- A closed `needs-info` issue the reporter comments on again is reopened, so a close is never final.
- The days of silence come from `needs_info_close_days` in `.platform-settings.yml` (default 14).
- Supersedes point 5 of ADR-025.

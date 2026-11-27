---
spec_id: 902-a-status-page-shows-whether-the-site-is-ready
title: A status page shows whether the site is ready
status: approved
priority: P2
shape: web-nextjs
---

# 902 — A status page shows whether the site is ready

This is the fixed spec of the `ux-plan` benchmark (spec 222). It must not change within a task version.

## Problem

A person who wonders whether bench-files-web works has to open `/api/ready` and read raw JSON. A page that says it in words, reachable from the header, answers that without a tool.

## Stories

- As a visitor, I want a status page linked from the header that tells me whether the site is ready, so that I know whether to try again later.

## Acceptance criteria

- **AC-902.1** Given the site is open on any page, when a person looks at the header, then it has a link "Status" that opens `/status`; on `/status` that link is marked as the current page.
- **AC-902.2** Given `/api/ready` answers `200`, when a person opens `/status`, then the page shows the heading "Status" and the text "Everything is working." with the time of the check.
- **AC-902.3** Given `/api/ready` answers anything but `200` or does not answer within 3 seconds, when a person opens `/status`, then the page shows "The site is not ready yet. Try again in a minute." and a button "Check again" that repeats the check without a page reload.
- **AC-902.4** Given a check is running after "Check again", when the page is read, then the button is disabled and a screen reader announces "Checking…" once.

## Non-goals

- A change to `/api/ready` or `/api/health`, history of past checks, or a check of other services.
- A gitops or configuration change.

## Open questions

None.

## Changelog

- 2026-11-24 created
- 2026-11-24 approved

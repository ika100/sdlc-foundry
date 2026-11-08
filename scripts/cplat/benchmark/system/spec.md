---
spec_id: 001-labels-on-file-records
title: Labels on file records
status: approved
priority: P1
shape: gitops-app
---

# 001 — Labels on file records

## Problem

The bench-files system has three components that do nothing yet: an API, a report worker and a web UI. People want to record files with labels, see which labels are used and how much they hold, and browse the files of one label in the browser. Today none of that exists, so the system cannot answer "what is stored under `invoices`?".

## Stories

As someone recording files, I want to store a file record with labels through the API, so that the files can be found by label later.
**Repos:** bench-files-api

As someone planning storage, I want a report of every label with its number of files and bytes, so that I see where the space goes.
**Repos:** bench-files-worker, bench-files-api, bench-files-gitops

As someone browsing, I want to see the file records in the web UI and narrow them to one label, so that I find files without using the API by hand.
**Repos:** bench-files-web, bench-files-api, bench-files-gitops

## Acceptance criteria

- **AC-001.1** Given a client sends `POST /files` with `{"name": "q3.pdf", "size_bytes": 1536, "labels": ["Invoices", "q3", "invoices"]}`, when the API answers, then the response is `201` with `id`, `name`, `size_bytes`, `labels` and `created_at`, where `labels` are lower-cased, without duplicates and sorted (`["invoices", "q3"]`).
- **AC-001.2** Given a client sends `POST /files` with an empty name or one longer than 200 characters, a negative `size_bytes`, more than 10 labels, or a label that is not 1 to 30 characters of `a-z`, `0-9` and `-` after lower-casing, when the API answers, then the response is `422` naming the field, and no record is stored.
- **AC-001.3** Given records were created in the order A, B, C, when a client sends `GET /files`, then the response is `200` with all three in creation order; with `?label=x` only the records that carry label `x`, in the same order (an empty list when none does).
- **AC-001.4** Given the API holds records, when a client sends `GET /reports/labels` to the worker, then the response is `200` with `{"labels": [{"label", "files", "bytes"}]}`: one entry per label in use, `files` the number of records with it and `bytes` the sum of their `size_bytes`, sorted by `files` (most first), then by `label`; it is computed from the API at request time.
- **AC-001.5** Given the API is unreachable or answers with a `5xx` status, when a client sends `GET /reports/labels`, then the worker answers `502` with a JSON error body.
- **AC-001.6** Given records exist, when a user opens the web UI's root URL, then the page lists every record in creation order with its name, its size in bytes and its labels; with no records it shows "No files yet".
- **AC-001.7** Given the list is shown, when the user selects a label of a record, then the page shows only the records with that label, the URL carries `?label=<label>`, and a "Show all" link returns to the full list.
- **AC-001.8** Given the API is unreachable or answers with a `5xx` status, when a user opens the web UI, then the page loads and shows "Files could not be loaded. Please try again later." instead of the list.

## Non-goals

- Changing or deleting records, uploading file contents, users or authentication.
- Persistence: records live in the API's memory, as a first version.
- Pagination, search beyond one label, or live updates of the page.

## Assumptions

- **A1** The worker and the web UI reach the API through its in-cluster address, set in `system.yaml` as an environment variable of each (other option: a public host; affects AC-001.4, AC-001.6).
- **A2** Labels are normalized by the API, so the worker and the web UI never normalize them again (other option: each component normalizes; affects AC-001.1, AC-001.4, AC-001.7).
- **A3** UI texts are in English, with the wording given in the criteria (affects AC-001.6, AC-001.8).

## Open questions

## Changelog

- 2026-11-08 created for the system-ship benchmark (spec 156)
- 2026-11-08 approved

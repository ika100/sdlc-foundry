---
plan_id: 001-labels-on-file-records
spec: 001-labels-on-file-records
feature: Labelled file records in the API, a label report in the worker and a label-filtered list in the web UI
gitops_app: ika100-demo/bench-files-gitops
status: draft
repos:
  - id: bench-files-api
    shape: service-python
    summary: Store file records with normalized labels and list them, optionally by label
    acs: [AC-001.1, AC-001.2, AC-001.3]
    criteria:
      - "Given an empty store, when a client sends `POST /files` with `{\"name\": \"q3.pdf\", \"size_bytes\": 1536, \"labels\": [\"Invoices\", \"q3\", \"invoices\"]}`, then the response is `201` with `id` (a non-empty string), `name` `q3.pdf`, `size_bytes` `1536`, `labels` `[\"invoices\", \"q3\"]` and `created_at` (RFC 3339, UTC, ending in `Z`) (system AC-001.1)"
      - "Given a client sends `POST /files` with a valid name and size and no `labels` field, when the API answers, then the response is `201` with `labels` `[]` (system AC-001.1)"
      - "Given a client sends `POST /files` with a missing or empty `name` or one of 201 characters, a missing, non-integer or negative `size_bytes`, 11 labels, or a label that after lower-casing is empty, longer than 30 characters or has a character outside `a-z`, `0-9` and `-` (for example `q_3`), when the API answers, then the response is `422` with `{\"error\": \"validation_failed\", \"message\": <text>, \"field\": <\"name\" | \"size_bytes\" | \"labels\">}` naming the offending field, and a following `GET /files` does not contain the record (system AC-001.2)"
      - "Given records A, B and C were created in that order, when a client sends `GET /files`, then the response is `200` with `{\"files\": [A, B, C]}`, each record with the same fields as the `201` of its creation (system AC-001.3)"
      - "Given A carries `invoices`, B does not and C does, when a client sends `GET /files?label=invoices` (or `?label=Invoices`), then the response is `200` with `{\"files\": [A, C]}`; with `?label=nothing-here` it is `200` with `{\"files\": []}` (system AC-001.3)"
    arguments: |
      Records live in process memory (spec non-goal: persistence); a lock around the store is enough. The component
      runs with one replica, keep it that way. Creation order is insertion order, never a sort by `created_at`.
      Replace the framework's default 422 body with the contract's error format.
    depends_on: []
    done: false
  - id: bench-files-worker
    shape: service-go
    summary: Report every label in use with its number of files and bytes, computed from the API
    acs: [AC-001.4, AC-001.5]
    criteria:
      - "Given the API's `GET /files` returns `q3.pdf` (1536 bytes, labels `invoices`, `q3`), `a.pdf` (100 bytes, `invoices`) and `b.txt` (10 bytes, `misc`), when a client sends `GET /reports/labels`, then the response is `200` with `{\"labels\": [{\"label\": \"invoices\", \"files\": 2, \"bytes\": 1636}, {\"label\": \"misc\", \"files\": 1, \"bytes\": 10}, {\"label\": \"q3\", \"files\": 1, \"bytes\": 1536}]}`: sorted by `files` (most first), then by `label` ascending (system AC-001.4)"
      - "Given the API returns `{\"files\": []}` or only records without labels, when a client sends `GET /reports/labels`, then the response is `200` with `{\"labels\": []}` (system AC-001.4)"
      - "Given a report was served, when a record is added to the API and the client sends `GET /reports/labels` again, then the new record is counted (each request reads `GET /files` from `BENCH_FILES_API_URL`, nothing is cached) (system AC-001.4)"
      - "Given `BENCH_FILES_API_URL` points at an address that refuses the connection, the API answers `500` or `503`, or it does not answer within 3 seconds, when a client sends `GET /reports/labels`, then the response is `502` with `Content-Type: application/json` and `{\"error\": \"upstream_unavailable\", \"message\": <text>}` (system AC-001.5)"
      - "Given the API answers a status the contract does not list for `GET /files` (for example `404`) or a `200` whose body is not `{\"files\": [...]}`, when a client sends `GET /reports/labels`, then the response is the same `502` JSON error (system AC-001.5)"
    arguments: |
      New env var `BENCH_FILES_API_URL` (base URL without trailing slash, e.g. `http://bench-files-api`); add it to
      docs/env-vars.md and internal/config. Labels arrive normalized (spec A2): never lower-case or dedupe them again.
    depends_on: []
    done: false
  - id: bench-files-web
    shape: web-nextjs
    summary: List the file records in the browser and narrow them to one label
    acs: [AC-001.6, AC-001.7, AC-001.8]
    criteria:
      - "Given the API's `GET /files` returns records A, B and C in that order, when a user opens `/`, then the page lists A, B and C in that order, each with its name, its size as `<size_bytes> bytes` (for example `1536 bytes`) and each of its labels as a link (system AC-001.6)"
      - "Given the API returns `{\"files\": []}`, when a user opens `/`, then the page shows \"No files yet\" and no list (system AC-001.6)"
      - "Given the image was built without `BENCH_FILES_API_URL` and the server is started with it set, when a user opens `/`, then the page lists the records of that API (the URL is read on the server at request time) (system AC-001.6)"
      - "Given the list is shown, when the user selects the label `invoices` of a record, then the URL is `/?label=invoices`, the page shows only the records the API returns for `GET /files?label=invoices`, in that order, and a \"Show all\" link to `/` that brings back the full list (system AC-001.7)"
      - "Given no record carries label `x`, when a user opens `/?label=x`, then the page shows \"No files with label x\" and the \"Show all\" link (system AC-001.7)"
      - "Given the API refuses the connection, answers a `5xx` status or a status the contract does not list, or does not answer within 3 seconds, when a user opens `/` or `/?label=invoices`, then the page answers `200` and shows \"Files could not be loaded. Please try again later.\" instead of the list (system AC-001.8)"
    arguments: |
      New env var `BENCH_FILES_API_URL` (server-only, never `NEXT_PUBLIC_*`); add it to docs/env-vars.md. The page must
      render dynamically (no build-time prerender of `/`). The browser never calls the API.
    depends_on: [bench-files-api]
    done: false
  - id: bench-files-gitops
    shape: gitops-app
    summary: Wire the worker and the web UI to the API and publish both through the Gateway
    acs: [AC-001.4, AC-001.6]
    gitops:
      - {env: {BENCH_FILES_API_URL: 'http://bench-files-api'}, component: bench-files-worker}
      - {env: {BENCH_FILES_API_URL: 'http://bench-files-api'}, component: bench-files-web}
      - {expose: bench-files-web, host: bench-files-web}
      - {expose: bench-files-worker, host: bench-files-worker}
    depends_on: []
    done: false
gitops_pin:
  - service: bench-files-api
    overlay: staging
    apply_after: merge_of_all
    note: the worker and the web UI need the API's endpoints; promote the three together
  - service: bench-files-worker
    overlay: staging
    apply_after: merge_of_all
    note: reads GET /files of the API pinned in the same PR
  - service: bench-files-web
    overlay: staging
    apply_after: merge_of_all
    note: reads GET /files of the API pinned in the same PR
---

The feature touches all three components of the system plus this repo's wiring. No shared library: the only shared
shape is the JSON of a file record, small enough to live in the contract. No new repo is needed. The API and the worker
build in parallel against the contract below; the web UI starts after the API has passed (pinned for the system-ship
benchmark, spec 156, so that a run covers both concurrency and ordering).

## bench-files-api — Store file records with normalized labels and list them, optionally by label

**Shape:** `service-python` · **Criteria:** AC-001.1, AC-001.2, AC-001.3 · **Depends on:** []

The API owns the records and is the only place labels are normalized (spec A2): lower-case, dedupe, sort. It owns
validation (AC-001.2) and the creation order of the list (AC-001.3). Records are in memory (non-goal: persistence), so
the deployment stays at one replica. Test concerns: the `422` body is the contract's, not the framework default; a
rejected request leaves the store unchanged; ordering is insertion order even when two records share a `created_at`.

## bench-files-worker — Report every label in use with its number of files and bytes, computed from the API

**Shape:** `service-go` · **Criteria:** AC-001.4, AC-001.5 · **Depends on:** []

The worker aggregates `GET /files` on every request (no cache, no background job) and owns the sort order of the
report. It owns the failure mapping of AC-001.5: anything other than a valid `200` from the API becomes a `502` JSON
error. Tests stub the API with `httptest`; the timeout case uses a stub that sleeps past 3 seconds.

## bench-files-web — List the file records in the browser and narrow them to one label

**Shape:** `web-nextjs` · **Criteria:** AC-001.6, AC-001.7, AC-001.8 · **Depends on:** [bench-files-api]

A Server Component at `/` fetches `GET /files` (or `GET /files?label=<label>` when the URL carries `label`) from
`BENCH_FILES_API_URL` on the server; the label filter is a plain link, so no client JavaScript is required. The page
never filters or normalizes labels itself (spec A2). Texts are English, exactly as in the criteria (spec A3). Tests
mock the API at the fetch boundary; e2e/smoke runs against the deployed page (read-only smoke: `/` loads).

## bench-files-gitops — Wire the worker and the web UI to the API and publish both through the Gateway

**Shape:** `gitops-app` · **Criteria:** AC-001.4, AC-001.6 · **Depends on:** []

Per spec A1 both callers reach the API through its in-cluster Service `http://bench-files-api` (Service port 80 to
container port 8080). The API stays internal. The web UI and the worker's report are published through the Gateway
(dev: `bench-files-web.bench-files-dev.localhost`, `bench-files-worker.bench-files-dev.localhost`). No resources: the
records live in memory.

## Contract

All bodies are JSON (`Content-Type: application/json`, UTF-8). Base URLs: the API is `BENCH_FILES_API_URL`
(in cluster `http://bench-files-api`), the worker and the web UI are reached through the Gateway.

### File record

```json
{"id": "6f1c...", "name": "q3.pdf", "size_bytes": 1536, "labels": ["invoices", "q3"], "created_at": "2026-11-08T10:15:30.123Z"}
```

- `id`: string, opaque, unique (the API uses a UUID4); clients never parse it.
- `name`: string, 1 to 200 characters, stored and returned exactly as sent (no trimming).
- `size_bytes`: integer, `>= 0`.
- `labels`: array of strings, each matching `^[a-z0-9-]{1,30}$`, no duplicates, sorted ascending; may be `[]`.
- `created_at`: RFC 3339 timestamp in UTC with a `Z` suffix, set by the API.

### bench-files-api

**`POST /files`** — create a record.

- Request: `{"name": string, "size_bytes": integer, "labels": [string]}`. `name` and `size_bytes` are required,
  `labels` is optional (default `[]`). Unknown fields are ignored.
- Validation, in this order, the first failure is reported:
  - `name`: missing, not a string, empty, or longer than 200 characters → `field: "name"`.
  - `size_bytes`: missing, not an integer (`1.5`, `"10"`, `true` are rejected), or negative → `field: "size_bytes"`.
  - `labels`: not an array, more than 10 entries as sent (counted before deduplication), an entry that is not a
    string, or an entry that after lower-casing does not match `^[a-z0-9-]{1,30}$` → `field: "labels"`.
  - A body that is not a JSON object → `422` with `field: "body"`.
- Normalization: each label is lower-cased, duplicates are removed, the result is sorted ascending.
- `201`: the file record. `422`: the error body (see Errors), nothing is stored.

**`GET /files`** — list records.

- Query: optional `label`. The API lower-cases it before matching; an empty `label=` means no filter. A value that is
  not a valid label simply matches nothing.
- `200`: `{"files": [record, ...]}` in creation (insertion) order; with `label`, only records whose `labels` contain it,
  same order; `{"files": []}` when none.

**Probes:** `GET /health`, `GET /ready` (unchanged).

### bench-files-worker

**`GET /reports/labels`**

- Reads `GET {BENCH_FILES_API_URL}/files` (no `label`) once per request.
- `200`: `{"labels": [{"label": string, "files": integer, "bytes": integer}, ...]}`: one entry per label carried by at
  least one record; `files` = number of records carrying it; `bytes` = sum of their `size_bytes`. Sorted by `files`
  descending, then by `label` ascending (byte order). `{"labels": []}` when no record carries a label.
- `502`: `{"error": "upstream_unavailable", "message": string}` when the API call fails (see Errors and Timeouts).

### bench-files-web

**`GET /`** and **`GET /?label=<label>`** (HTML)

- Without `label`: calls `GET {BENCH_FILES_API_URL}/files`; with `label`: `GET {BENCH_FILES_API_URL}/files?label=<label>`
  (URL-encoded). Server side only, at request time.
- Each record is shown in API order with its `name`, `<size_bytes> bytes` and one link per label to `/?label=<label>`.
- Unfiltered and empty: the text `No files yet`. Filtered and empty: `No files with label <label>`.
- Filtered: a link `Show all` with `href="/"`. Unfiltered: no `Show all` link.
- API failure: HTTP `200` page with the text `Files could not be loaded. Please try again later.` and no list.

### Errors

- Error body of the API and the worker: `{"error": <code>, "message": <human text>}`, plus `"field"` on the API's
  `422`. Codes: `validation_failed` (API, `422`), `upstream_unavailable` (worker, `502`), `not_found` (any unknown
  route, `404`), `internal` (`500`). Clients branch on the status and `error`, never on `message`.
- A caller treats any response the contract does not list for that call as a failure of the other side:
  - the worker, for `GET /files`: anything other than `200` with a body `{"files": [...]}` of valid records (a
    `4xx`, a `5xx`, a redirect, invalid JSON, a missing `files` array) → its own `502` `upstream_unavailable`; it logs
    the upstream status, never the body.
  - the web UI, for `GET /files`: the same cases → the "Files could not be loaded" page.
- Neither caller retries.

### Timeouts

- worker → API `GET /files`: 3 seconds total (connect plus response). Connection refused, DNS failure or timeout →
  `502` immediately; the worker's `/ready` does not depend on the API, so the worker stays in service while the API is
  down.
- web → API `GET /files`: 3 seconds total, via an abort signal on the server-side fetch. Failure or timeout → the
  error text on a `200` page; `/api/ready` does not depend on the API.
- The API makes no outbound calls. It must answer `POST /files` and `GET /files` well inside 3 seconds (in memory).

## gitops-app PR

The `/system:ship` compose PR (`compose/001-labels-on-file-records`) applies the four operations: `BENCH_FILES_API_URL`
on the worker and the web UI, and Gateway routes for `bench-files-web` and `bench-files-worker`, then pins the three
builds in `dev`. After Argo reconciles in dev, verify:

- `http://bench-files-web.bench-files-dev.localhost:8088/` loads and shows "No files yet" (fresh, in-memory API) or the
  smoke records; `?label=<label>` narrows the list.
- `http://bench-files-worker.bench-files-dev.localhost:8088/reports/labels` answers `200` with `{"labels": [...]}`.

Staging: the three components get their staging pin together after all three repos merged (`merge_of_all`), since
the worker and the web UI are useless against an older API. Libraries: none.

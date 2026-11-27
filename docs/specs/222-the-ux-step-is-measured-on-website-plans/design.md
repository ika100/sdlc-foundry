# Design — 222 The UX step is measured on website plans

## The ux-plan benchmark (#1059)

- **Sample.** `tasks.json` gives the workflow `sample_component: ika100-demo/bench-files-web`; `runs_bench.sample_of` takes that component's repo and pin from the `system-ship` entry, so there is one pin to keep current (A1). `runs_bench.clone_of` puts the clone in the system-ship folder (`--dir`, `$CPLAT_BENCH_SYSTEM_DIR`, `<state dir>/benchmark/system-ship`): that clone is already trusted in Claude Code, which a benchmark folder needs and which only a person can grant. A missing clone is refused before anything runs; an untrusted one by the existing trust check.
- **Task.** `spec-902.md`, a `web-nextjs` spec for a status page (header link, ready / not ready, "Check again", a disabled button and a screen-reader announcement), small enough to plan in minutes and with states a UX design has to cover. The only step is `/component:plan 902` (A2).
- **Result check.** `ux_planned` checks out `feature/902-…` in the clone and decides in-process with the same functions `cplat spec ux` and `cplat spec check` use: `ux.md` exists, `decide` is `done` (current `spec_hash`), `check` has no error, and `design.md` or `plan.md` names `ux.md` (the architect read it). The first missing item becomes the record's `result_check`. The reset and the record are the shared path of every single-repo workflow, so the record has the per-agent children (ux-designer, architect) with tokens and time.
- **Cost and gate.** `evalgate.selected` keeps the defaults (`quick-task`, `build`) and adds `ux-plan` only when `ux_changes` finds a changed prompt under `plugins/web/` or `scripts/cplat/spec_ux.py` (A3). A change to `spec_ux.py` alone is not a prompt change, so it asks for `ux-plan` only. `--workflow` names win; `rules_rebaseline` and `rules_retire` keep their own `("quick-task", "build")`. A release without a web or UX change therefore runs exactly what it ran before.

## The UX word rule (#1060)

Data: the 29 website specs of the journey and demo repos (`ika100-demo/taskboard*-web`, `ika100/demo-taskboard-web`, `ika100/todo-web`; 279 distinct active criteria). At spec level the spec-219 list already chose `needed` for all 29, which is right: each changes a page. At criterion level it missed wording a later spec may use alone and fired on server and build wording:

| Before (spec 219) | Criterion (source) | Kind |
|---|---|---|
| missed | "… in edit mode with a changed input, when the user chooses Edit …" (todo-web AC-002.3) | input, edit mode |
| missed | "… then keyboard focus is on that todo's edit control …" (todo-web AC-002.25) | keyboard focus |
| missed | "… when the user presses Escape in the input …" (todo-web AC-002.8) | a person pressing |
| missed | "… the created task appears at the end of the list …" (taskboard-web AC-001.4) | appears |
| missed | "… when a person opens /, then the board lists every task …" (taskboard5-web AC-001.1) | a person opening |
| false hit | "… so the page stays reachable" for `/api/health` (taskboard16-web AC-001.8) | page served |
| false hit | "… the web site keeps serving its pages" (taskboard23-web AC-001.8) | pages served |
| false hit | "Given the todo list page is deployed, when a client requests `GET /api/health` …" (todo-web AC-001.2) | page deployed |

Change, deterministic (A4):

- `VISIBLE` gains inputs, rows, labels, headings, header, footer, edit mode, empty and loading states, keyboard, focus, screen readers, accessible names, colours, themes, dark mode, appears.
- `ACTING`, searched after `VISIBLE` so the reason names the thing on screen when there is one: a user, person, visitor or "they" typing, pressing, entering, selecting, submitting, choosing, opening or saving.
- `NOT_VISIBLE` is removed from the text first: container, Docker, base, OCI or runtime images and image tags, digests, scans and sizes; JSON, request, response, body, query, payload or schema fields, "the field `x`", missing, unknown or extra fields; page size, number, token, cursor or parameter, `page`, `?page=`, per page; HTTP, request or response headers and "`X-…` header"; database or table rows; Kubernetes, pod, GitHub or issue labels; something appearing in the logs; logs, metrics, traces or dashboards showing; HTML or static pages, serving pages, a page that stays reachable, is served or deployed.

On the 41 labelled cases (`tests/cplat/fixtures/ux_cases.json`: 27 real criteria with their repo and id, 14 written ones), the spec-219 rule has 15 misses and 7 false hits; the tuned rule has none. The cases were collected and labelled in this change, so the tuned rule fits them by construction: the measure of future misses is the next website specs, and the `ux:` field stays the override. On all 279 real criteria the tuned rule marks 269 as visible; the 10 others are health, readiness, routing and server-log criteria.

## Not changed

The ux-designer prompt (the measured run showed no defect it needed, see verification.md), system specs, the default benchmarks.

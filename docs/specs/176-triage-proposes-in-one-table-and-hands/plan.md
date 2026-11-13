---
spec_id: 176-triage-proposes-in-one-table-and-hands
shape: platform
spec_hash: db64346f76c7
summary: cplat issue triage reads the queue in one batch with script facts, renders one grouped overview and one confirmation, applies confirmed rows, and hands fixes to the dispatcher through a Triage comment
tasks:
  - id: t1
    title: Triage facts (role, duplicates, engine route, reply state, status, handled)
    files: [scripts/cplat/triage_facts.py]
    covers: [AC-176.1, AC-176.5, AC-176.6, AC-176.7]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t5
    title: The dispatcher's fix run takes its task from a writer's Triage comment
    files: [scripts/cplat/triage_task.py, scripts/cplat/dispatch_units.py]
    covers: [AC-176.9]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t2
    title: cplat issue triage batch, list --waiting reply state, show duplicates, priority labels
    files: [scripts/cplat/triage_batch.py, scripts/cplat/triage.py]
    covers: [AC-176.1, AC-176.5, AC-176.6, AC-176.7]
    parallel_safe: true
    depends_on: [t1]
    done: true
  - id: t3
    title: Grouped overview, question pages, confirmation plan and per-row actions
    files: [scripts/cplat/triage_view.py, scripts/cplat/triage.py]
    covers: [AC-176.2, AC-176.3, AC-176.8]
    parallel_safe: true
    depends_on: [t2]
    done: true
  - id: t4
    title: act applies confirmed rows with the hand-over summary; publish-specs opens one docs PR
    files: [scripts/cplat/triage_act.py, scripts/cplat/triage.py]
    covers: [AC-176.3, AC-176.4, AC-176.8, AC-176.15]
    parallel_safe: true
    depends_on: [t3]
    done: true
  - id: t6
    title: /issue:triage runs the new flow; register, docs, ADR, versions, changelog
    files: [plugins/issue/commands/triage.md, docs/rules/plugins/issue/commands/triage.yml, plugins/issue/README.md, plugins/issue/.claude-plugin/plugin.json, .claude-plugin/marketplace.json, docs/dispatch.md, docs/adr/README.md, docs/changelog.d/176-triage-proposes-in-one-table.changed.md]
    covers: [AC-176.2, AC-176.3, AC-176.4, AC-176.8, AC-176.15]
    parallel_safe: true
    depends_on: [t4, t5]
---

# Plan — 176 Triage proposes in one table and hands off to the dispatcher

The contract is [design.md](design.md); every name, field and screen line below refers to it.

## t1 — Triage facts (role, duplicates, engine route, reply state, status, handled)

**Files:** scripts/cplat/triage_facts.py
**Covers:** AC-176.1, AC-176.5, AC-176.6, AC-176.7
**Goal:** the pure functions behind every fact of the batch, with no GitHub access, so that `batch`, `show` and `list --waiting` share one implementation.

**Implementation notes:**
- Input is the normalised issue of design "GitHub reads": `{"number", "title", "body", "author", "authorAssociation", "createdAt", "labels": [{"name"}], "comments": [{"author", "authorAssociation", "body", "createdAt"}]}`; `now` is a parameter so tests fix the clock.
- `role(association) -> str`, `is_writer(role) -> bool`, `age(seconds) -> str` exactly as in design "Facts".
- `duplicates(issue, open_issues, closed_issues, now) -> list[dict]` with `RECENT_DAYS`, `STOPWORDS`, `TITLE_THRESHOLD`; never the issue itself, one entry per other issue.
- `engine(issue) -> dict | None` through `engine_issue.parse`, with `ENGINE_SURE = 0.7` and the route-to-class map.
- `reply(issue, now) -> dict | None` and `new_since(issue, reply)` (which comments are new).
- `status(issue, specs, open_numbers, merged_prs) -> dict` (specs as `spec.all_specs` gives them; `claim.holder` for the claim) and `handled(status) -> dict | None` in the design's order.

**Done when:** unit tests for each function pass (`cplat quiet test-fast`), `cplat quiet quality` is clean; the acceptance tests of the covered criteria pass after t2.

## t5 — The dispatcher's fix run takes its task from a writer's Triage comment

**Files:** scripts/cplat/triage_task.py, scripts/cplat/dispatch_units.py
**Covers:** AC-176.9
**Goal:** a fix unit started for a triaged issue runs `/component:fix <task>` where the task is the newest `Triage:` comment by a user with write access and the reporter's text arrives only fenced.

**Implementation notes:**
- `triage_task.task_for(issue, can_write)` as in design "The fix run's task"; uses `triage.fenced` and `triage.BODY_LIMIT`; pure.
- In `dispatch_units.start`, for `kind == "fix"` only and before `spawn`: read the issue through `dispatch_units.gh`, build `can_write` from `gh api repos/<slug>/collaborators/<login>/permission` (cached per login for the call), store `task` in the unit dict when not None.
- `headless_cmd`: `/component:fix <task>` when `unit.get("task")`, else today's `/component:fix <item>`; a restart reuses the stored unit, so the task is not re-read.
- The `started …` line shows the prompt cut to its first line; no other change to slots, budget or landing (non-goal).
- `triage_task.py` must not name the explore commands (AC-188.11 scans `dispatch*.py`; keep it that way here too).

**Done when:** the AC-176.9 acceptance tests pass, and the existing dispatcher tests (`tests/cplat/test_dispatch*`) still pass.

## t2 — cplat issue triage batch, list --waiting reply state, show duplicates, priority labels

**Files:** scripts/cplat/triage_batch.py, scripts/cplat/triage.py
**Covers:** AC-176.1, AC-176.5, AC-176.6, AC-176.7
**Goal:** one call returns every queued issue with its fenced text, author role, duplicates, engine route, reply state and status facts, from one GitHub request, and saves the batch for the next steps.

**Implementation notes:**
- `triage_batch.read(slug) -> dict`: the one `gh api graphql` call of the design through `triage.gh`; normalise nodes (labels to `[{"name"}]`, missing author `ghost`); an `errors` key raises `PlatformError`.
- `triage_batch.build(raw, *, new, root, now) -> dict`: the queue (`triage.queue` plus answered `needs-info`), `skipped`, per-issue facts from `triage_facts`, redaction and fencing with today's limits, `priority_labels`, `missing_labels` from the same answer.
- `path(slug)`, `save(batch)`, `load(slug, max_age=7200)`; `load` refuses a missing or older batch with the hint to run `batch` again.
- `triage.py`: `batch [--new] [--json]` subcommand; slug from `-R` or `dispatch_state.slug_of(Path.cwd())`.
- `list --waiting`: add `comments` to the `--json` fields, attach `reply` per item and end each text line with `answered <age>` / `silent <age>`.
- `show`: one extra `gh issue list --state all --limit 200 …` call and `duplicates` in its output.
- `LABELS` gains `p0`, `p1`, `p2` with the design's colours and descriptions.

**Done when:** the acceptance tests of AC-176.1, AC-176.5, AC-176.6, AC-176.7 pass, and `tests/cplat/test_triage.py` still passes.

## t3 — Grouped overview, question pages, confirmation plan and per-row actions

**Files:** scripts/cplat/triage_view.py, scripts/cplat/triage.py
**Covers:** AC-176.2, AC-176.3, AC-176.8
**Goal:** cplat renders the overview and the confirmation from the saved batch and the triager's proposals, and computes the exact labels and comment of each row, so screens are the same on every run.

**Implementation notes:**
- `load_proposals(path, batch, *, for_act=False) -> list[dict]`: every validation rule of design "Proposals file", all errors in one `PlatformError`; engine defaults for class and mark.
- `group(batch, rows) -> dict` and the action words, plan phrases and auto question for `check` rows of design "Groups and wording".
- `overview(batch, rows) -> str` and `pages(...)`: 80 columns (`textwrap`, 8-space continuation), no ANSI codes, the folded `Already handled` lines, `Skipped:`, the last line on the questions; `--json` as specified.
- `actions(issue, row) -> {"add", "remove", "comment"}` per the design's table, including the `Triage:` comment text and the replacement of other priority labels; handled issues get their fixed actions without a row.
- `plan(batch, rows) -> list[dict]` and `confirm --show N` text.
- `triage.py`: subcommands `overview --proposals F [--json]` and `confirm --proposals F [--show N] [--json]`; move the body of `apply` into `apply_one(slug, n, add, remove, comment, dry_run) -> Report` (the `apply` subcommand calls it, behaviour unchanged).
- A test asserts no rendered screen holds the words of design "Words never on screen".

**Done when:** the acceptance tests of AC-176.2 and AC-176.3 (overview, pages, plan, show) and the label/comment parts of AC-176.8 pass.

## t4 — act applies confirmed rows with the hand-over summary; publish-specs opens one docs PR

**Files:** scripts/cplat/triage_act.py, scripts/cplat/triage.py
**Covers:** AC-176.3, AC-176.4, AC-176.8, AC-176.15
**Goal:** one call applies exactly the confirmed rows and prints what was done per group, the next step per kind with who takes it, the undo lines and the person's next step as a choice; new specs of the run go out as one draft PR.

**Implementation notes:**
- `act(slug, batch, rows, numbers, dry_run) -> dict`: validate all named issues first (`for_act=True`), then `triage.apply_one` per issue in group order; `needs-exploring` and handled `claimed`/`fixed` make no call; never close.
- Render `Done` / `Will do`, `Next`, `Undo` as in the design; collect each `apply_one` undo line; add the specs undo line when `specs_pr` is set.
- `choice` per the design's three cases; `--json` as specified.
- `publish_specs(root, slug, ids) -> dict`: branch-name check, signed-off commit per spec folder, push without force, find-or-create the draft PR by `<!-- cplat:triage-specs -->`, write `specs_pr` into `batch.json`; git and gh through the seams `triage_act.git` / `triage_act.gh`.
- `triage.py`: subcommands `act --proposals F --rows all|<n>,… [--dry-run] [--json]` and `publish-specs <id>… [--json]`.
- The `Next` line of fixes points to `cplat dispatch status` and the console Board (AC-176.8).

**Done when:** the acceptance tests of AC-176.4, AC-176.15 and the apply parts of AC-176.3 and AC-176.8 pass.

## t6 — /issue:triage runs the new flow; register, docs, ADR, versions, changelog

**Files:** plugins/issue/commands/triage.md, docs/rules/plugins/issue/commands/triage.yml, plugins/issue/README.md, plugins/issue/.claude-plugin/plugin.json, .claude-plugin/marketplace.json, docs/dispatch.md, docs/adr/README.md, docs/changelog.d/176-triage-proposes-in-one-table.changed.md
**Covers:** AC-176.2, AC-176.3, AC-176.4, AC-176.8, AC-176.15
**Goal:** the command walks batch → proposals file → overview printed verbatim → questions as choices (AskUserQuestion, at most 4 per screen, `<n> of <m>`) → confirmation (`OK, do it` / `Change one` / `Cancel`, typed answers accepted, `confirm --show` on request) → new specs on one `docs/triage-<date>` branch with `publish-specs` → `act` → the hand-over choice; no fix starts in the session.

**Implementation notes:**
- Without an issue number: `batch --json`; empty queue ends the run; missing labels → `setup-labels` after the user agrees. Write the proposals file (the class table stays as judgement guidance; handled issues get no row; engine rows may omit the class). With an issue number keep a one-issue path through `show` and `apply`.
- Typed answers ("ok", "all ok except 560 feature") update the proposals file; ask again only about rows the answer leaves unclear; `act --rows` names exactly the confirmed issues.
- Features: product-manager `MODE: fold` / `MODE: new` as today, `cplat spec new "<title>" --tracks N --priority <P>` on the one docs branch, then `publish-specs`, then set `spec` / `new_spec` in the row before `act`.
- Remove the `/component:fix` hand-off and the per-shape fix branch; keep `/component:explore #<n>`, `/system:explore #<n>` and the "stays in the queue" sentence (AC-188.10 tests), the untrusted-text hard rule and "Never close an issue" (spec 177 changes it).
- The prompt may not grow: the changed prompt files together stay within their bytes before the change (`cplat platform rules check`); every new or reworded rule sentence gets an entry in `triage.yml` (retire the replaced ones with date and reason); run the two benchmarks for retirements (`cplat platform pr-check --fix` writes their ids).
- `cplat adr add triage-hands-off-through-a-writer-comment --decision "<the design's one line>"`, then fill Status, Context, Decision, Consequences (builds on ADR-025).
- `docs/dispatch.md`: a fix run's task is the newest writer's `Triage:` comment, the reporter's text fenced; the README row of `/issue:triage` says it hands fixes to the dispatcher.
- Bump `issue` (minor) in `plugin.json` and `marketplace.json`; changelog fragment `176-triage-proposes-in-one-table.changed.md`.

**Done when:** `cplat platform rules check` passes, `tests/cplat/test_188_prompts.py` still passes, `cplat platform pr-check` reports no version or fragment problem, and the prompt-structure acceptance tests of the covered criteria pass.

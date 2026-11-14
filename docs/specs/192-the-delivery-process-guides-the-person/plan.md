---
spec_id: 192-the-delivery-process-guides-the-person
shape: platform
spec_hash: 6105b952f74e
summary: cplat next and /platform:next print one screen (process bar, what is happening, your part) with choices, record the person's answers as run-store follow-ups, and every triage, approval, build, ship and release ends with that hand-over
tasks:
  - id: t1
    title: Stages - the bar vocabulary, Release and the plain terms in the console
    files: [scripts/cplat/stages.py, scripts/cplat/console/glossary.py, docs/console.md]
    covers: [AC-192.2]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t2
    title: nextstate - every source read-only, grouping, item descriptions and plain words
    files: [scripts/cplat/nextstate.py, scripts/cplat/needs.py]
    covers: [AC-192.1, AC-192.3, AC-192.4, AC-192.5, AC-192.9]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t5
    title: Person answers as run-store follow-ups and the report's person time
    files: [scripts/cplat/runs.py, scripts/cplat/runs_report.py]
    covers: [AC-192.10]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t3
    title: nextscreen - the three parts, ASCII, width and list cuts
    files: [scripts/cplat/nextscreen.py]
    covers: [AC-192.1, AC-192.2, AC-192.3, AC-192.4, AC-192.5, AC-192.9]
    parallel_safe: true
    depends_on: [t1, t2]
    done: true
  - id: t4
    title: nextquestions - options, outward actions, undo, pages and record argv
    files: [scripts/cplat/nextquestions.py]
    covers: [AC-192.5, AC-192.6, AC-192.7, AC-192.10]
    parallel_safe: true
    depends_on: [t2]
    done: true
  - id: t6
    title: cplat next and cplat next answer
    files: [scripts/cplat/nextcmd.py, scripts/cplat/cplat.py]
    covers: [AC-192.1, AC-192.6, AC-192.7, AC-192.8, AC-192.10]
    parallel_safe: true
    depends_on: [t3, t4, t5]
    done: true
  - id: t7
    title: The /platform:next command
    files: [plugins/platform/commands/next.md, docs/rules/plugins/platform/commands/next.yml, plugins/platform/README.md]
    covers: [AC-192.1, AC-192.6, AC-192.7]
    parallel_safe: true
    depends_on: [t6]
  - id: t8
    title: Hand-over at the end of component spec approval, build, ship and release
    files: [plugins/component/commands/spec.md, plugins/component/commands/build.md, plugins/component/commands/ship.md, plugins/component/commands/release.md, docs/rules/plugins/component/commands/spec.yml, docs/rules/plugins/component/commands/build.yml, docs/rules/plugins/component/commands/ship.yml, docs/rules/plugins/component/commands/release.yml]
    covers: [AC-192.8]
    parallel_safe: true
    depends_on: [t7]
  - id: t9
    title: Hand-over at the end of triage, platform release, system spec approval and system ship
    files: [plugins/issue/commands/triage.md, plugins/platform/commands/release.md, plugins/system/commands/spec.md, plugins/system/commands/ship.md, docs/rules/plugins/issue/commands/triage.yml, docs/rules/plugins/platform/commands/release.yml, docs/rules/plugins/system/commands/spec.yml, docs/rules/plugins/system/commands/ship.yml]
    covers: [AC-192.8]
    parallel_safe: true
    depends_on: [t7]
  - id: t10
    title: Plugin versions, quickstart, ADR and changelog fragment
    files: [plugins/platform/.claude-plugin/plugin.json, plugins/component/.claude-plugin/plugin.json, plugins/issue/.claude-plugin/plugin.json, plugins/system/.claude-plugin/plugin.json, .claude-plugin/marketplace.json, docs/QUICKSTART.md, docs/adr/README.md, docs/changelog.d/192-the-delivery-process-guides-the-person.added.md]
    covers: [AC-192.1, AC-192.8]
    parallel_safe: true
    depends_on: [t7]
human_steps:
  - "Before the PR merges: t7-t9 add /platform:next and eight hand-over sentences, so the prompts pass `baseline.prompt_bytes`. In a Claude session on the branch run `cplat platform runs benchmark quick-task --plugins plugins --reset-first` and `cplat platform runs benchmark build --plugins plugins --reset-first`, then `cplat platform rules rebaseline --reason \"/platform:next and the hand-over (spec 192)\"` and commit docs/rules/register.yml."
---

# Plan — 192 The delivery process guides the person from triage to release

Contract: [design.md](design.md). Levels: t1, t2, t5 → t3, t4 → t6 → t7 → t8, t9, t10.

Every new module follows the `cplat` conventions: standard library plus what `cplat` already imports, a module
docstring with its public API, the clock and `gh`/`git` through the existing replaceable seams (`runs.utcnow`,
`notify.now`, `needs.gh`) or a module-level `git(repo, *args)` the tests replace.

Every prompt task (t7–t9) gives each new rule sentence its reason and a register entry (next free `R<n>`, `source:
spec 192`), keeps phrases existing tests pin verbatim, makes the changed existing prompts byte-neutral within their own
files (shorten other sentences of the same file), and passes `cplat platform rules check --only <file>`; the total
byte raise is the human step.

## t1 — Stages - the bar vocabulary, Release and the plain terms in the console

**Files:** scripts/cplat/stages.py, scripts/cplat/console/glossary.py, docs/console.md
**Covers:** AC-192.2
**Goal:** one source for the bar's steps and texts, shown the same in the terminal and the console.

**Implementation notes:**
- `stages.py`: the two shape sets of design.md (The screen, 1); `bar(shape) -> tuple[str, ...]`;
  `bar_step(stage, shape) -> str`; `_EXPLAIN["Release"]` (what: the release tags main and publishes it with its
  changelog; decision: release now or collect more); `explain` accepts it; `STAGES` and `earliest` unchanged.
- `PLAIN = {"runs_on_its_own": (title, text), "two_at_a_time": …, "needs_you": …}`: plain sentences, no word of the
  AC-192.9 list.
- `glossary.TERMS`: `release` (text of `explain("Release")["what"]`) and the three `PLAIN` keys, their texts taken
  from `stages`; a new `SECTIONS` entry ("Delivering in a repo") holds the four keys, so existing sections stay.
- `glossary._process`: after the eight stages, one line: in a platform or library repo Dev, Staging and Prod are one
  step, Release, with its text.
- `docs/console.md`: the four terms in the glossary part and one paragraph on `/platform:next` (relative links only).

**Done when:** the AC-192.2 tests on `stages.bar`, `bar_step`, `explain("Release")` and the glossary texts pass;
`test_console*.py` and `test_stages*.py` pass.

## t2 — nextstate - every source read-only, grouping, item descriptions and plain words

**Files:** scripts/cplat/nextstate.py, scripts/cplat/needs.py
**Covers:** AC-192.1, AC-192.3, AC-192.4, AC-192.5, AC-192.9
**Goal:** `collect(repo_dir) -> state`, the read-only input of the screen and the questions, and the grouping both
use.

**Implementation notes:**
- `needs.py`: module dict `_PARSED`; `_drafts` stores each parsed draft under `(slug, spec_id)` (the PR wins, as the
  list does); `draft_spec(slug, spec_id) -> Spec | None`. The needs document does not change.
- Needs: `needs.collect(repo_dir)` when `applications/*/system.yaml` exists, else `needs.collect_repo(repo_dir)`; a
  raise becomes an `unavailable` entry (`github`), never an exception.
- Per draft item a `draft` dict: title, tracks, active criteria count, size, unstruck assumptions, open questions
  (`spec._question`), problem (≤ 600 chars), pr, url.
- Release items (`kind: release`, `stage: Release`): platform: fragments in `docs/changelog.d/` other than
  `README.md`, `since` from the oldest adding commit; library-python: commits since the last `v*` tag not matching
  `comprelease.FOLLOW_UP`. Other shapes none.
- Running: `dispatch_view.status_doc` units plus active `runlist.collect` rows, one per spec or issue; slots total;
  parked = `len(dispatch_state.load(slug)["steering"]["skipped"])`.
- Notified: earliest non-`held` `sent[*].at` of the item id in `notify.state_path(<needs system>)` and
  `dispatch_notify.notify_path(slug)`; `waiting_minutes` against `notify.now()`.
- Channels: `notify_config.cells_for(notify_config.load(), "escalation", shape)`; a bad file is `unavailable`
  (`notifications`).
- Estimates per size from done run rows (design.md, Size); none below 3.
- Exported for t3 and t4: `what` per item and running entry (design.md); `plain(text)`; `groups(state, later) ->
  (group, shown items, also counts, later count)` with the group order of design.md Decisions, oldest `since` first.
- Each source in its own `try`, so one failing source never hides the others; nothing in this module writes.

**Done when:** the AC-192.1 read-only tests (no `gh` writing verb, no file under the state dirs, no run record or
claim) and the state-level tests of AC-192.3/.4/.5/.9 pass; `test_needs*.py` and `test_dispatch*.py` pass.

## t5 — Person answers as run-store follow-ups and the report's person time

**Files:** scripts/cplat/runs.py, scripts/cplat/runs_report.py
**Covers:** AC-192.10
**Goal:** an answer adds one question and its minutes to each item it concerns, and the report shows them.

**Implementation notes:**
- `runs.person_answer(*, shown_at, answered_at, option, refs, minutes_total) -> str | None`: one follow-up line per
  ref (design.md, Person records), each with a fresh `run_id`, buffered under the lock and flushed once, like
  `followup`; returns the warning line or None; never raises.
- `runs_report.aggregate_person(followups, kept)`: delivered rows from `kept`, person lines from all `followups` with
  `followup == "person"`; `aggregate` adds `out["person"]`; `render_text` adds the block before the "Buffered locally"
  line.
- Person lines must not reach the `filed` counting in `aggregate` (their `run_id` matches no record; verify).
- Update both module docstrings.

**Done when:** the AC-192.10 tests on the line, the minutes split and the report (JSON and text, `–`) pass;
`test_runs*.py` pass.

## t3 — nextscreen - the three parts, ASCII, width and list cuts

**Files:** scripts/cplat/nextscreen.py
**Covers:** AC-192.1, AC-192.2, AC-192.3, AC-192.4, AC-192.5, AC-192.9
**Goal:** `render(state, *, ascii, later, judgement, show=None, choose=None) -> dict` with `bar`, `waiting`, `screen`
exactly as design.md (The screen).

**Implementation notes:**
- Grouping through `nextstate.groups` (t2).
- Bar from `stages.bar`/`bar_step`; marks and label placement; ASCII symbols and numbers.
- Part texts per case, `Also waiting`, `put off for later`, `Also running`, unavailable lines.
- Draft blocks with judgement or without it (no empty field).
- `wrap(line, indent)` at 80 columns; lists cut at 5 with `and <n> more`; `nextstate.plain` over every line last.
- Sub-screens: `show="assumptions"` (every unstruck assumption per spec, ≤ 5 each, and the approve actions with
  targets and undo), `show="details:<QID>"` (the question's actions), `choose="approve"`; the actions come in as data
  from t4's tables through the caller, so this module does not import `nextquestions`.
- Pure: no I/O.

**Done when:** the AC-192.1–.5 and .9 screen tests pass (fixtures of `state` dicts).

## t4 — nextquestions - options, outward actions, undo, pages and record argv

**Files:** scripts/cplat/nextquestions.py
**Covers:** AC-192.5, AC-192.6, AC-192.7, AC-192.10
**Goal:** `build(state, *, shown_at, later, args, page, show=None, choose=None, attended=True) -> (questions, page)`
and `actions(item) -> list[dict]`, exactly as design.md (Questions per group, Actions).

**Implementation notes:**
- Grouping through `nextstate.groups` (t2).
- Options table, `recommended` first, `header` ≤ 12, ≤ 4 options, ≤ 4 questions per page, `page.text`.
- Actions table, `cannot_undo`, `undo` lines, `description` order (cannot-undo first, then `Runs …`).
- `then` argv repeats `args` (`--later`, `--ascii`, `--judgement`); "Later" appends `--later <id>` per item.
- `record` argv with refs; `attended=False` → `[]`.
- `answer` steps: replace `<answers>` in the item's command.
- `nextstate.plain` over question and option texts.

**Done when:** the AC-192.5/.6/.7 question tests and the AC-192.10 `record` argv tests pass.

## t6 — cplat next and cplat next answer

**Files:** scripts/cplat/nextcmd.py, scripts/cplat/cplat.py
**Covers:** AC-192.1, AC-192.6, AC-192.7, AC-192.8, AC-192.10
**Goal:** the CLI of design.md (CLI, `--json` document, `how`).

**Implementation notes:**
- `cplat.py`: `PLUMBING["next"] = "nextcmd"` and one docstring line.
- `main(argv)`: `answer` → the answer verb; else parse, `nextstate.collect`, `nextscreen.render` (with the actions of
  `nextquestions.actions` for the sub-screens), `nextquestions.build`, print `screen` or the JSON document.
- ASCII detection from the environment and `--ascii`; `CPLAT_HEADLESS=1` → `attended: false`.
- `--judgement` read here; unreadable → the line of design.md.
- `HOW`: the fixed paragraph of design.md.
- `answer`: parse `--shown-at` (UTC `Z`), compute minutes with `runs.utcnow()`, `runs.person_answer`, print the line.

**Done when:** the end-to-end tests of `cplat next [--json]` and `cplat next answer` pass; the same state prints the
same screen twice and from another working directory of the repo; `test_cplat*.py` pass.

## t7 — The /platform:next command

**Files:** plugins/platform/commands/next.md, docs/rules/plugins/platform/commands/next.yml, plugins/platform/README.md
**Covers:** AC-192.1, AC-192.6, AC-192.7
**Goal:** the thin command: run `cplat next --json`, add the judgement, follow `how`.

**Implementation notes:**
- Description (≤ 260 chars, valid YAML): "Where you are in the process and what waits for you, as choices. Usage:
  /platform:next [--ascii]".
- Body: the standard header lines of the platform commands (hard-rule legend, `cplat` on PATH, read whole); then:
  run `cplat next --json $ARGUMENTS`; when `judgement_wanted`, write for each of `drafts` one `you_get` line (what the
  person gets, from `problem`) and the most important `assumption` to a temp JSON file and run it again with
  `--judgement <file>`; then follow `how`.
- **Hard rule:** never choose an option for the person, because approval exists only in the person's own words
  (`hard: user-decides-approval`).
- The issue-report footer as in the other platform commands.
- README row for `/platform:next`.

**Done when:** `cplat platform rules check --only plugins/platform/commands/next.md` passes and the AC tests that
read the command's structure pass.

## t8 — Hand-over at the end of component spec approval, build, ship and release

**Files:** plugins/component/commands/spec.md, plugins/component/commands/build.md, plugins/component/commands/ship.md, plugins/component/commands/release.md, docs/rules/plugins/component/commands/spec.yml, docs/rules/plugins/component/commands/build.yml, docs/rules/plugins/component/commands/ship.yml, docs/rules/plugins/component/commands/release.yml
**Covers:** AC-192.8
**Goal:** each command ends with `/platform:next`'s first step offered as a choice.

**Implementation notes:**
- One sentence in each file's last step, replacing its "Next step: …" line where there is one: "End with the
  hand-over: run `cplat next --json` and follow its `how`, so that the person goes on by choosing, not by typing a
  command." An unattended run gets no questions from `cplat next`, so the sentence needs no condition.
- spec.md: A step 4 and the "Otherwise the next step" sentence of F; build.md and ship.md: the final report step;
  release.md: after the release.
- Byte-neutral per file; register entries per new sentence.

**Done when:** `cplat platform rules check --only <each file>` passes and the AC-192.8 structure tests (each prompt
points to `cplat next`) pass.

## t9 — Hand-over at the end of triage, platform release, system spec approval and system ship

**Files:** plugins/issue/commands/triage.md, plugins/platform/commands/release.md, plugins/system/commands/spec.md, plugins/system/commands/ship.md, docs/rules/plugins/issue/commands/triage.yml, docs/rules/plugins/platform/commands/release.yml, docs/rules/plugins/system/commands/spec.yml, docs/rules/plugins/system/commands/ship.yml
**Covers:** AC-192.8
**Goal:** as t8, for these four commands.

**Implementation notes:**
- The sentence of t8, at the end of the triage run (after the last issue), after the release is published, after a
  system spec approval, and in the system ship's final report.
- Byte-neutral per file; register entries per new sentence; keep the `triage-never-closes` and
  `release-never-tags-or-commits-main` hard-rule sentences verbatim.

**Done when:** `cplat platform rules check --only <each file>` passes and the AC-192.8 structure tests pass.

## t10 — Plugin versions, quickstart, ADR and changelog fragment

**Files:** plugins/platform/.claude-plugin/plugin.json, plugins/component/.claude-plugin/plugin.json, plugins/issue/.claude-plugin/plugin.json, plugins/system/.claude-plugin/plugin.json, .claude-plugin/marketplace.json, docs/QUICKSTART.md, docs/adr/README.md, docs/changelog.d/192-the-delivery-process-guides-the-person.added.md
**Covers:** AC-192.1, AC-192.8
**Goal:** versions, the decision record and the release note.

**Implementation notes:**
- Minor bump of `platform`, `component`, `issue` and `system` in each `plugin.json` and the matching marketplace
  entries.
- ADR: `cplat adr add delivery-screens-are-printed-by-cplat --decision "<the line in design.md>"` (it writes the file
  and its `docs/adr/README.md` row); fill Status (Accepted), Context, Decision (screens in code, judgement from the
  session, the procedure in `how`, answers as follow-ups), Consequences. The new `docs/adr/<NNN>-…md` is not in
  `files` because its number is known only when `cplat adr add` runs; no other task touches `docs/adr/`.
- `docs/QUICKSTART.md`: one sentence that `/platform:next` shows where you are and what waits for you (no spec
  numbers: `check-docs.py`).
- Fragment per `docs/changelog.d/README.md`: bold summary ending `(spec 192).`; plugins update with
  `/plugin marketplace update`.

**Done when:** `devbox run validate`, `python3 scripts/check-links.py` and `python3 scripts/check-docs.py` pass, and
`cplat platform pr-check` reports no fragment or version problem.

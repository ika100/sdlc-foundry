---
spec_id: 177-triage-asks-reporters-plainly-and-closes
shape: platform
spec_hash: a91f1aa639cf
summary: Triage names the missing form fields, checks plain reporter comments with a days-and-reopen sentence, closes confirmed question, duplicate, wontfix and silent needs-info issues as not planned, and requeues a closed needs-info issue its reporter answered
tasks:
  - id: t1
    title: triage_reporter module (forms, missing fields, internal terms, fixed comment texts)
    files: [scripts/cplat/triage_reporter.py]
    covers: [AC-177.1, AC-177.2, AC-177.4]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t2
    title: needs_info_close_days project setting
    files: [scripts/cplat/settings.py]
    covers: [AC-177.4]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t3
    title: close_one, reopen_one and the unattended close refusal
    files: [scripts/cplat/triage.py]
    covers: [AC-177.3, AC-177.4]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t4
    title: Batch carries forms, missing fields, silent and reopened needs-info issues
    files: [scripts/cplat/triage_batch.py]
    covers: [AC-177.1, AC-177.4]
    parallel_safe: true
    depends_on: [t1, t2]
  - id: t5
    title: Rows validate missing fields and plain comments; actions close and reopen
    files: [scripts/cplat/triage_view.py]
    covers: [AC-177.1, AC-177.2, AC-177.3, AC-177.4]
    parallel_safe: true
    depends_on: [t1, t4]
  - id: t6
    title: act reopens, labels, comments and closes the confirmed rows
    files: [scripts/cplat/triage_act.py]
    covers: [AC-177.3, AC-177.4]
    parallel_safe: true
    depends_on: [t3, t5]
  - id: t7
    title: /issue:triage asks only what the user may know; changed hard rule, register, docs, versions, changelog
    files: [plugins/issue/commands/triage.md, docs/rules/plugins/issue/commands/triage.yml, docs/rules/register.yml, scripts/cplat/cplat.py, plugins/issue/README.md, plugins/shared/README.md, docs/adr/025-issue-triage.md, plugins/issue/.claude-plugin/plugin.json, .claude-plugin/marketplace.json, docs/changelog.d/177-triage-asks-reporters-plainly-and-closes.added.md]
    covers: [AC-177.1, AC-177.2, AC-177.3, AC-177.4]
    parallel_safe: true
    depends_on: [t6]
---

# Plan — 177 Triage asks reporters plainly and closes what needs no work

Contract and texts: [design.md](design.md). Levels: t1, t2, t3 → t4 → t5 → t6 → t7.

## t1 — triage_reporter module

**Files:** scripts/cplat/triage_reporter.py
**Covers:** AC-177.1, AC-177.2, AC-177.4
**Goal:** the pure functions every other task uses: the repo's issue forms, the missing required fields of a body, the internal terms of a comment, and the two fixed texts (the needs-info footer and the final comment of a silent close).

**Implementation notes:**
- `forms(root)`, `form_of(body, forms)`, `internal_terms(text)`, `thanks(text)`, `footer(days)`, `final_comment(days)`, `PUBLIC_COMMANDS` exactly as in the design's contract.
- Forms: `yaml.safe_load` each `.github/ISSUE_TEMPLATE/*.y?ml` except `config.yml`; skip `type: markdown`; `required` from `validations.required`; a broken file is skipped, never raises.
- Body sections: split on `^### (.+?)\s*$` (multiline); a section is empty when its text stripped is `""` or `_No response_`. Compare labels stripped and case-insensitive.
- `internal_terms` imports `triage.LABELS` for the backticked-label check; no GitHub access, no clock.

**Done when:** the AC-177.1 and AC-177.2 acceptance tests that call these functions directly pass; `devbox run test-fast` is green.

## t2 — needs_info_close_days project setting

**Files:** scripts/cplat/settings.py
**Covers:** AC-177.4
**Goal:** the repository's number of days after which a silent `needs-info` issue is proposed for closing.

**Implementation notes:**
- `needs_info_close_days(repo: Path) -> int`: project file only (`.platform-settings.yml`), default 14; a bool, a non-integer or a value below 1 raises the design's `PlatformError`.
- Document the key in the module docstring next to the others.

**Done when:** the AC-177.4 setting tests (default 14, a configured value, an invalid value) pass.

## t3 — close_one, reopen_one and the unattended close refusal

**Files:** scripts/cplat/triage.py
**Covers:** AC-177.3, AC-177.4
**Goal:** the two state changes `act` needs, each one gh call with its undo, and the refusal that keeps an unattended run from closing.

**Implementation notes:**
- `close_one(repo, number, dry_run)` runs `gh issue close N [-R repo] --reason "not planned"`; `reopen_one` runs `gh issue reopen N [-R repo]`; both return a `Report` with `did`/`will_do` and `undo` as in the design.
- `refuse_unattended_close()` mirrors `refuse_unattended_priority`.
- The module docstring and the `act` help say "closes only the confirmed rows"; the `apply` help keeps "never closes" (it still never does).

**Done when:** the AC-177.3 tests of the gh calls (close reason, reopen, dry run, headless refusal) pass.

## t4 — Batch carries forms, missing fields, silent and reopened needs-info issues

**Files:** scripts/cplat/triage_batch.py
**Covers:** AC-177.1, AC-177.4
**Goal:** the batch gives the triager the facts of this spec: the forms, each issue's matched form and missing fields, the silent issues due for closing and the closed ones their reporter answered.

**Implementation notes:**
- Add the `waiting_closed` alias to `QUERY` (design); `read()` returns `waiting_closed` normalised, `[]` when the answer lacks it.
- `build()`: top-level `close_after_days = settings.needs_info_close_days(root)` and `forms = triage_reporter.forms(root)`.
- `_entry()`: `state` (`"closed"` for `waiting_closed` issues, else `"open"`) and `form = form_of(raw body)` computed before fencing.
- A silent `needs-info` issue whose `reply.since` lies at least `close_after_days` whole days back and that has no other `handled` becomes an entry with `handled = {"kind": "silent", "line": ...}`; younger silent ones stay in `skipped`.
- A `waiting_closed` issue with `stateReason == "NOT_PLANNED"` and an author comment after `closedAt` is queued (sorted with the rest); others are ignored.

**Done when:** the AC-177.1 batch tests (missing fields of a form-filed issue, none for a no-form issue) and the AC-177.4 batch tests (silent at 14 days proposed, 13 days skipped, configured days, a reporter comment on a closed issue requeues it) pass.

## t5 — Rows validate missing fields and plain comments; actions close and reopen

**Files:** scripts/cplat/triage_view.py
**Covers:** AC-177.1, AC-177.2, AC-177.3, AC-177.4
**Goal:** the proposals file carries the missing fields and plain comments, and every screen and `act` share one set of actions that now includes closing and reopening.

**Implementation notes:**
- `_row()` gets the batch (or its `forms` and the entry) to check `missing`, `form` and the comment rules with the exact error lines of the design; the role test is `triage_facts.is_writer(issue["role"])`.
- `actions()` returns `close` and `reopen`; needs-info comment + `footer(days)`; duplicate comment prefixed `Duplicate of #N`; handled `silent` gives `final_comment(days)` and `close: True`, no label change. `days` comes from `batch["close_after_days"]` (pass it in; default 14 when the batch lacks it).
- `_plan_text` / `confirm` / `show` / `overview` texts as in the design (close suffix, reopen prefix, `state:` line, `missing:` part, silent line in Already handled).
- Keep `CLOSE_CLASSES = ("question", "duplicate", "wontfix")` here; `triage_act` imports it.

**Done when:** the AC-177.1 row tests (missing required, superset of the form's missing, `form` for no-form issues), the AC-177.2 comment tests (internal terms refused, public commands allowed, thanks, each missing item, footer with the days, writers exempt) and the confirm/show parts of AC-177.3 and AC-177.4 pass.

## t6 — act reopens, labels, comments and closes the confirmed rows

**Files:** scripts/cplat/triage_act.py
**Covers:** AC-177.3, AC-177.4
**Goal:** `act` performs the close and reopen of exactly the rows named in `--rows`, after the comment, and says so in its summary and undo list.

**Implementation notes:**
- In the pre-write pass call `triage.refuse_unattended_close()` when any named row's actions close.
- Per issue: `reopen_one` when `reopen`, then `apply_one` when labels or a comment change, then `close_one` when `close`; collect each report's undo.
- Handled `silent` entries go through this path (they are not skipped like `claimed`/`fixed`).
- `done` entries gain `closed`/`reopened`; `_phrase` and `DONE_TEXT` use the design's phrases; closed issues fall into the `nothing` next-step group.
- Update the module docstring (it no longer "never closes").

**Done when:** the AC-177.3 tests (confirmed duplicate/question/wontfix posted and closed as not planned, duplicate with the original's link, unconfirmed row untouched) and the AC-177.4 act tests (silent closed only when named, reopen before labels) pass.

## t7 — /issue:triage asks only what the user may know; hard rule, register, docs, versions, changelog

**Files:** plugins/issue/commands/triage.md, docs/rules/plugins/issue/commands/triage.yml, docs/rules/register.yml, scripts/cplat/cplat.py, plugins/issue/README.md, plugins/shared/README.md, docs/adr/025-issue-triage.md, plugins/issue/.claude-plugin/plugin.json, .claude-plugin/marketplace.json, docs/changelog.d/177-triage-asks-reporters-plainly-and-closes.added.md
**Covers:** AC-177.1, AC-177.2, AC-177.3, AC-177.4
**Goal:** the command uses the new facts and rules, and the platform's records say triage now closes confirmed rows.

**Implementation notes:**
- Step 2: a `needs-info` row has `missing` (and `form` for an issue filed without one); ask the user only what the user may know (who the reporter is, whether the problem is known), every other question goes into the comment; a comment to a reporter outside the repo thanks them, asks for each missing item in plain words, names no spec numbers, labels or commands other than `/platform:doctor` and `/issue:report`; the script adds the days sentence. Register this as a practice rule with its reason in `triage.yml`.
- Step 4: the hard rule becomes "Never close an issue without the user's confirmation, because a closed issue leaves the queue unseen." Update R4's text; keep `hard: triage-never-closes`; add the new ADR to its `source` in `register.yml`.
- Step 1/5: silent `needs-info` issues arrive as proposals with a final comment; `act` closes only named rows.
- Keep the prompt bytes at or below the `register.yml` baseline by tightening other lines of `triage.md`; `cplat platform rules check` must pass. Do not rebaseline.
- `cplat.py` help line: "never closes" → "closes only confirmed rows". `plugins/shared/README.md`: document `needs_info_close_days` next to the other settings. ADR-025 point 5: one line "Amended by ADR-<n>" pointing to the ADR the orchestrator created.
- Bump the `issue` plugin to 1.7.0 in both `plugin.json` and `marketplace.json`; changelog fragment per `docs/changelog.d/README.md`.

**Done when:** the AC-177 prompt-structure tests and the existing spec 176 prompt tests pass, `cplat platform rules check` and `devbox run validate` pass.

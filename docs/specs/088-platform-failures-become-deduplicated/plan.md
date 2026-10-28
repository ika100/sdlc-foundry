---
spec_id: 088-platform-failures-become-deduplicated
spec_hash: 41994fcdb011
summary: autoissue.py files platform failures as deduplicated issues (Signature line, oldest-open +1, closed → linked new unless wontfix, 10 per 24 h cap, pending retry through the run store); ship escalate files cause platform, cplat crashes inside a recorded run file at once; amendment 2026-10-26 (#207) classifies escalations without a cause by fixed reason rules (cause_source), names environment for the stop gate and headless no progress, and shows the unclassified share in the report and the weekly retro
tasks:
- id: t1
  title: autoissue module (signature, redaction, dedupe, cap, pending retry, GitHub seam)
  files: [scripts/cplat/autoissue.py, tests/cplat/conftest.py]
  covers: [AC-088.4, AC-088.5, AC-088.6, AC-088.7, AC-088.8, AC-088.9, AC-088.10, AC-088.11, AC-088.12, AC-088.13, AC-088.14]
  parallel_safe: true
  depends_on: []
  done: true
- id: t2
  title: runs.current and the suppressed note in filed
  files: [scripts/cplat/runs.py]
  covers: [AC-088.4, AC-088.8, AC-088.11, AC-088.12]
  parallel_safe: true
  depends_on: []
  done: true
- id: t3
  title: auto-filed triage label
  files: [scripts/cplat/triage.py]
  covers: [AC-088.10]
  parallel_safe: true
  depends_on: []
  done: true
- id: t4
  title: ship escalate files cause platform and coerces unknown causes
  files: [scripts/cplat/ship.py]
  covers: [AC-088.1, AC-088.2, AC-088.3, AC-088.9, AC-088.11, AC-088.12, AC-088.13, AC-088.14]
  parallel_safe: true
  depends_on: [t1]
  done: true
- id: t5
  title: cplat crash hook files inside a recorded run
  files: [scripts/cplat/cplat.py]
  covers: [AC-088.4]
  parallel_safe: true
  depends_on: [t1, t2]
  done: true
- id: t6
  title: ship command text and docs for auto-filed issues
  files: [plugins/svc/commands/ship.md, docs/CHANGELOG.md, docs/unattended-delivery.md]
  covers: [AC-088.1]
  parallel_safe: true
  depends_on: []
  done: true
- id: t7
  title: escalation_rules module (rule table, classify, resolve, effective)
  files: [scripts/cplat/escalation_rules.py]
  covers: [AC-088.15, AC-088.16, AC-088.17, AC-088.21]
  parallel_safe: true
  depends_on: []
  done: true
- id: t8
  title: runs.finish records cause_source and the matching rule
  files: [scripts/cplat/runs.py]
  covers: [AC-088.15, AC-088.16, AC-088.17]
  parallel_safe: true
  depends_on: [t2, t7]
  done: true
- id: t9
  title: ship escalate prints the rule; stop gate and headless no progress name environment
  files: [scripts/cplat/ship.py, scripts/cplat/headless.py]
  covers: [AC-088.15, AC-088.17, AC-088.18]
  parallel_safe: true
  depends_on: [t4, t8]
  done: true
- id: t10
  title: runs report counts effective causes and shows unclassified escalations
  files: [scripts/cplat/runs_report.py]
  covers: [AC-088.19, AC-088.21]
  parallel_safe: true
  depends_on: [t7]
  done: true
- id: t11
  title: weekly retro shows the unknown share week over week
  files: [scripts/cplat/retro_report.py]
  covers: [AC-088.20, AC-088.21]
  parallel_safe: true
  depends_on: [t10]
  done: true
- id: t12
  title: docs for classified escalations
  files: [docs/CHANGELOG.md, docs/unattended-delivery.md]
  covers: []
  parallel_safe: true
  depends_on: [t6]
  done: true
---

The contract for every task is [design.md](design.md). ADR: [033](../../adr/033-auto-filed-issues-with-signatures.md).
Filing must never change an escalation's or a crash's exit code. `autoissue.file()` never raises and never prints:
callers print `Outcome.lines`. No test may reach GitHub. Every GitHub call goes through `autoissue.tracker()` /
`autoissue.gh()`, and the clock goes through `autoissue.now()` / `autoissue.monotonic()`.

Tasks t1 to t6 are the original plan ([plan.v1.md](plan.v1.md)), built and merged. Tasks t7 to t12 implement the
amendment of 2026-10-26 (#207, AC-088.15 to AC-088.21); their contract is design.md "Amendment 2026-10-26 (#207)".
Each new task depends on the done task whose module it extends (so no level holds two tasks on one file) and on the
new task whose module it imports. Levels: t7, t12 → t8, t10 → t9, t11.

Note for the test phase: adding `cause_source` changes every existing test that compares a whole `escalation` dict.
The tester updates them (list in design.md "Back-compat and test changes"), and adds `unclassified` after `pr_wait` to
the key list of `tests/cplat/test_runs_report.py::test_json_output_has_stable_keys_and_nothing_else_on_stdout`.
Coders do not edit tests.

## t1 — autoissue module (signature, redaction, dedupe, cap, pending retry, GitHub seam)

**Files:** scripts/cplat/autoissue.py, tests/cplat/conftest.py
**Covers:** AC-088.4, AC-088.5, AC-088.6, AC-088.7, AC-088.8, AC-088.9, AC-088.10, AC-088.11, AC-088.12, AC-088.13, AC-088.14
**Goal:** the public API of design.md "Python API". Done; see plan.v1.md for the implementation notes.

## t2 — runs.current and the suppressed note in filed

**Files:** scripts/cplat/runs.py
**Covers:** AC-088.4, AC-088.8, AC-088.11, AC-088.12
**Goal:** `runs.current` and the `suppressed by #<n>` note. Done; see plan.v1.md.

## t3 — auto-filed triage label

**Files:** scripts/cplat/triage.py
**Covers:** AC-088.10
**Goal:** `cplat triage setup-labels` creates `auto-filed`. Done; see plan.v1.md.

## t4 — ship escalate files cause platform and coerces unknown causes

**Files:** scripts/cplat/ship.py
**Covers:** AC-088.1, AC-088.2, AC-088.3, AC-088.9, AC-088.11, AC-088.12, AC-088.13, AC-088.14
**Goal:** `cplat ship escalate --cause platform` files or +1's; unknown causes become `unknown`. Done; see plan.v1.md.

## t5 — cplat crash hook files inside a recorded run

**Files:** scripts/cplat/cplat.py
**Covers:** AC-088.4
**Goal:** a crash inside a recorded run is filed at once. Done; see plan.v1.md.

## t6 — ship command text and docs for auto-filed issues

**Files:** plugins/svc/commands/ship.md, docs/CHANGELOG.md, docs/unattended-delivery.md
**Covers:** AC-088.1
**Goal:** the orchestrator states the cause; users learn what gets filed. Done; see plan.v1.md.

## t7 — escalation_rules module (rule table, classify, resolve, effective)

**Files:** scripts/cplat/escalation_rules.py
**Covers:** AC-088.15, AC-088.16, AC-088.17, AC-088.21
**Goal:** the pure module of design.md "Python API — `scripts/cplat/escalation_rules.py`" with the four rules of the
"Rule table", in that order and with those names. No I/O; imports only `re` and `dataclasses`. t8, t9, t10 and t11
import it, so keep the names exactly.

**Implementation notes:**
- `ALLOWED`, `SOURCES`, `Rule` (frozen; `patterns` compiled with `re.IGNORECASE`; `matches` = every pattern
  `.search()`es), `RULES`, `Resolved`, `classify`, `resolve`, `effective`, `message`.
- The patterns exactly as in the table; rules 1 and 4 are one pattern each with the alternatives joined by `|`.
- `assert all(r.cause in ("environment", "decision") for r in RULES)` at import (no rule yields `platform`).
- `classify` returns `None` for a non-string or empty reason. `resolve` treats `None`, `""`, `"unknown"` and any
  value outside `ALLOWED` as not stated.
- `effective` tolerates a malformed escalation dict (missing or non-string fields): anything not an allowed cause goes
  through `resolve(None, reason)`.
- Module docstring: the rule table is extended from the report's unclassified list; never add a rule for `platform`.

**Acceptance tests (new file `tests/cplat/test_escalation_rules.py`, docstrings start with the AC id):**
- `test_a_git_action_awaiting_approval_is_environment` — AC-088.16, AC-088.15 (the three examples)
- `test_a_dirty_working_tree_is_environment` — AC-088.16
- `test_a_spec_test_conflict_is_decision` — AC-088.16
- `test_a_build_left_open_for_review_is_decision` — AC-088.16
- `test_rules_match_case_insensitively` — AC-088.15
- `test_a_reason_without_a_match_stays_unknown_with_source_none` — AC-088.15
- `test_a_git_word_alone_stays_unknown` — AC-088.17 (`tests fail after commit 1a2b3c`, `git push failed`)
- `test_a_stated_cause_always_wins` — AC-088.17 (`working tree is dirty` with `code` → `code`, `given`)
- `test_no_rule_yields_platform` — AC-088.17
- `test_effective_classifies_an_older_unknown_record_without_cause_source` — AC-088.21
- `test_effective_keeps_a_stored_allowed_cause` — AC-088.21, AC-088.17

**Done when:** those tests pass.

## t8 — runs.finish records cause_source and the matching rule

**Files:** scripts/cplat/runs.py
**Covers:** AC-088.15, AC-088.16, AC-088.17
**Goal:** every escalation written to the store carries `cause`, `cause_source` and, for a rule match, `rule`, as in
design.md "Record field". This covers ship, app-ship, headless, fleet and `cplat runs end --outcome escalated` in one
place.

**Implementation notes:**
- In `finish`, replace the `cause if cause in CAUSES else "unknown"` line with
  `res = escalation_rules.resolve(escalation.get("cause"), str(escalation.get("reason", "")))` and write
  `{"reason", "cause": res.cause, "cause_source": res.source}` plus `"rule": res.rule` only when `res.source == "rule"`.
- Classify the reason as passed, before `_scrub` (which still redacts the stored reason).
- `cplat runs end` keeps passing `ns.cause or "unknown"`; nothing else in `runs.py` changes. Update the module
  docstring's description of `finish` to mention `cause_source`.

**Acceptance tests (new file `tests/cplat/test_runs_cause_source.py`, fixtures from `test_runs.py`):**
- `test_a_record_without_a_cause_is_classified_by_rule` — AC-088.15, AC-088.16
- `test_a_record_without_a_matching_rule_has_cause_source_none` — AC-088.15
- `test_a_stated_cause_has_cause_source_given` — AC-088.15, AC-088.17
- `test_runs_end_escalated_without_cause_is_classified` — AC-088.15 (the `/svc:build` path)
- `test_a_classified_escalation_is_never_filed` — AC-088.17, AC-088.2 (through `ship escalate` with a fake tracker
  that fails on any call)

**Done when:** those tests pass, and `test_runs.py`, `test_autoissue_ship.py`, `test_budget.py`,
`test_appship_097.py` and `test_smoke_091_ship.py` pass with the tester's `cause_source` updates.

## t9 — ship escalate prints the rule; stop gate and headless no progress name environment

**Files:** scripts/cplat/ship.py, scripts/cplat/headless.py
**Covers:** AC-088.15, AC-088.17, AC-088.18
**Goal:** `cplat ship escalate` prints `classified as <cause> by rule <name>` after the AC-088.3 message; the
platform's own escalations (stop gate giving up, headless "no progress") are recorded as `environment`, `given`. See
design.md "`cplat ship escalate` output" and "Where causes are set and read".

**Implementation notes:**
- `ship.escalate`: after appending the `_coerce_cause` message, when the coerced cause is `unknown`, append
  `escalation_rules.message(escalation_rules.resolve(None, reason))` if it is not `None`. The state keeps the coerced
  cause; filing still keys on the coerced cause (`platform` only).
- `ship.gate`: when it gives up, set `st["cause"] = "environment"` next to `st["escalated"]`, before `save_state`.
- `headless._drive`: `ship.escalate(repo, result, "environment")` for "no progress".
- `headless.main` `finally`: `esc = {"reason": state["result"], "cause": "environment"}` when the result starts with
  `no progress` (the budget case stays `decision`; other stops unchanged).
- No other text, exit code or stdout line changes.

**Acceptance tests (new file `tests/cplat/test_ship_escalate_rules.py`; headless parts built like `test_headless.py`):**
- `test_escalate_without_cause_prints_the_rule_after_the_message` — AC-088.15
- `test_escalate_without_a_match_prints_only_the_message` — AC-088.15
- `test_escalate_with_a_stated_cause_prints_no_rule_line_and_records_given` — AC-088.17
- `test_the_stop_gate_giving_up_records_environment_given` — AC-088.18
- `test_headless_no_progress_records_environment_given` — AC-088.18 (ship record and headless record)

**Done when:** those tests pass and `test_ship.py`, `test_ship_checks.py`, `test_headless.py`,
`test_autoissue_ship.py` (with the tester's updates) stay green.

## t10 — runs report counts effective causes and shows unclassified escalations

**Files:** scripts/cplat/runs_report.py
**Covers:** AC-088.19, AC-088.21
**Goal:** `MAX_UNCLASSIFIED`, `effective_escalation` and `aggregate_unclassified`, and their use in `aggregate` and
`render_text`, exactly as in design.md "Report — `cplat runs report`". Pure functions, tolerant of records without
`cause_source` and of malformed escalation dicts.

**Implementation notes:**
- `aggregate`: `causes` counts `effective_escalation(r).cause`; `reasons` (top escalation reasons) unchanged; add
  `"unclassified": aggregate_unclassified(kept)` after `"pr_wait"` (before the conditional `validation`).
- `render_text`: the `Unclassified escalations:` block right after the `Top escalation reasons:` block; percentage
  `floor(100 * n / m + 0.5)`; at most 20 reasons, then `  … and <k> more`; `none` when `m == 0`.
- `effective_escalation` and `aggregate_unclassified` are public: t11 imports them. `aggregate_agents` and
  `runs_usage_report` are not touched.

**Acceptance tests (new file `tests/cplat/test_runs_report_unclassified.py`, built on `rec`/`put`/`store` from
`test_runs_report.py`):**
- `test_the_report_shows_unclassified_escalations_n_of_m_with_percent` — AC-088.19
- `test_the_report_shows_the_classified_by_rule_count` — AC-088.19
- `test_unknown_reasons_are_listed_most_frequent_first_at_most_20` — AC-088.19 (`… and <k> more`)
- `test_no_escalation_in_the_window_reads_none` — AC-088.19
- `test_the_json_report_has_the_unclassified_key` — AC-088.19
- `test_older_unknown_records_are_counted_under_the_rules_cause` — AC-088.21
- `test_reading_does_not_rewrite_the_store` — AC-088.21
- Existing: `test_json_output_has_stable_keys_and_nothing_else_on_stdout` gains `unclassified` after `pr_wait`
  (tester change).

**Done when:** those tests pass and the rest of `test_runs_report.py`, `test_runs_report_pr_wait.py`,
`test_runs_report_agents.py` and `test_runs_usage_report.py` stay green.

## t11 — weekly retro shows the unknown share week over week

**Files:** scripts/cplat/retro_report.py
**Covers:** AC-088.20, AC-088.21
**Goal:** the retro's escalations are by effective cause, `report.json` gains `unclassified`, and `## Escalations`
opens with the share line for the covered week and the week before, as in design.md "Retro".

**Implementation notes:**
- `_cause` → `escalation_rules.effective(esc).cause` (still mapped into `CAUSES`).
- `build`: `"unclassified"` right after `"escalations"`, from `runs_report.aggregate_unclassified` on each week, as
  `_fig(cur, prev)` per field (`count`, `escalations`, `share`, `by_rule`; no `reasons`).
- `_index`: refs `unclassified.count`, `unclassified.share`, `unclassified.by_rule` for both sides; tolerate a
  report without the key.
- `_render`: the share line first in `## Escalations`, identical in private and public; `n/a` for a week without
  escalations; no line for a report without the key. The cause blocks render as today (private: reasons; public:
  `reason <n>`).

**Acceptance tests (new file `tests/cplat/test_retro_unclassified.py`, built like `test_retro_report.py`):**
- `test_the_retro_shows_the_unknown_share_for_the_week_and_the_week_before` — AC-088.20
- `test_the_private_retro_lists_every_still_unknown_reason_with_its_count` — AC-088.20
- `test_the_public_issue_shows_counts_and_share_and_reason_n_only` — AC-088.20
- `test_older_unknown_records_count_under_the_rules_cause_in_the_retro` — AC-088.21
- `test_unclassified_figures_are_evidence_refs` — AC-088.20

**Done when:** those tests pass and `test_retro_report.py`, `test_retro_pr_wait.py`, `test_retro_proposals.py` and
`test_retro_cli.py` stay green.

## t12 — docs for classified escalations

**Files:** docs/CHANGELOG.md, docs/unattended-delivery.md
**Covers:** none (documentation)
**Goal:** users learn how escalations without a cause are classified and where to read what is still unknown.

**Implementation notes:**
- `docs/CHANGELOG.md`: one bullet under `[Unreleased]`: **Feature (088): escalations without a cause are classified by
  reason rules.** The four rules and their causes; `cause_source` (`given` / `rule` / `none`) and `rule` in the record;
  a stated cause always wins and no rule yields `platform`; the stop gate and headless "no progress" record
  `environment`; `cplat runs report` shows `Unclassified escalations:` (`--json`: `unclassified`); the weekly retro
  shows the unknown share; older records are classified when read. Only this task edits the CHANGELOG.
- `docs/unattended-delivery.md`: in "Run records", one short paragraph on `cause_source` and the rules (where they live:
  `scripts/cplat/escalation_rules.py`); in "Weekly retro", one line on the unknown share (reasons only in the private
  retro).
- No plugin or marketplace version bumps.

**Done when:** `devbox run validate` and the Markdown link check pass.

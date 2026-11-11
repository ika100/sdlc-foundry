---
spec_id: 181-journey-measurements-count-waiting
shape: platform
spec_hash: fa5d7bdc5872
summary: "The journey measurement becomes `cplat platform runs journey measure` (journey_timeline: threads, wait-call table, exact split; journey_sources: run records, system ship tree, repo sessions, Actions runs, record evidence; journey_measure: per-step table, JSON, --journey writes a `journey_split` follow-up); repo sessions and their subagents count as agent time (children), waiting minutes get a kind from evidence or `unattributed`; `runs report --benchmarks` shows split medians per stage; the performance record's recipe and a corrected note for journeys 9 and 10; ADR-096"
tasks:
  - id: t1
    title: journey_timeline.py — transcript threads, the wait-call table and the exact split of one span
    files: [scripts/cplat/journey_timeline.py]
    covers: [AC-181.1, AC-181.2, AC-181.3, AC-181.4]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t2
    title: journey_sources.py — run records, system ship tree, repo sessions, Actions runs, record evidence; runs.followup
    files: [scripts/cplat/journey_sources.py, scripts/cplat/runs.py, scripts/cplat/runs_store.py]
    covers: [AC-181.1, AC-181.3, AC-181.4, AC-181.6]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t3
    title: journey_measure.py — the `runs journey measure` verb, per-step table, JSON, --journey follow-up; measure.py forwards
    files: [scripts/cplat/journey_measure.py, scripts/cplat/runs_journey.py, scripts/journey/measure.py]
    covers: [AC-181.1, AC-181.2, AC-181.3, AC-181.4, AC-181.5, AC-181.6]
    parallel_safe: true
    depends_on: [t1, t2]
    done: true
  - id: t4
    title: report --benchmarks — split medians per stage, part and journey from the journey_split follow-ups
    files: [scripts/cplat/runs_journey_report.py, scripts/cplat/runs_usage_report.py, scripts/cplat/runs.py]
    covers: [AC-181.6]
    parallel_safe: true
    depends_on: [t2]
    done: true
  - id: t6
    title: performance record — recipe with the per-step table, corrected split of journeys 9 and 10; ADR index, changelog
    files: [docs/PERFORMANCE.md, docs/adr/README.md, docs/changelog.d/181-journey-measurements-count-waiting.changed.md]
    covers: [AC-181.7]
    parallel_safe: true
    depends_on: [t3]
    done: true
human_steps:
  - "If the t6 session cannot read the journey 9 and 10 transcripts under ~/.claude/projects (a headless session may only read the repo), run `cplat platform runs journey measure ... --steps <steps.tsv> --json` for both journeys by hand and hand the output to the session"
---

# Plan — 181 Journey measurements count waiting correctly

[design.md](design.md) is the contract; [ADR-096](../../adr/096-journey-waiting-is-attributed-from-evidence.md) records the
attribution rules.

**Levels:**

| Level | Tasks |
|---|---|
| 1 | t1, t2 |
| 2 | t3, t4 |
| 3 | t6 |

t4 depends on t2 only because both change `scripts/cplat/runs.py` (t2 adds `followup`, t4 changes `_report`).

## t1 — journey_timeline.py

**Files:** scripts/cplat/journey_timeline.py
**Covers:** AC-181.1, AC-181.2, AC-181.3, AC-181.4
**Goal:** the pure core: read one transcript into a `Thread`, recognise wait calls, and split a span into person, agents
(coordinator, children) and waiting per kind, exactly.

**Implementation notes:**
- `KINDS = ("ci", "deploy", "promotion", "restore", "cluster", "smoke")`, `WAITING = KINDS + ("unattributed", "no_transcript")`.
- `command_wait(cmd) -> str | None` implements design § Threads and wait calls (table order, word-bounded; the loop rule of
  today's `category()` without its name-based kinds).
- `read_thread(path, *, role: "coordinator" | "child", main: bool) -> Thread` with `span`, `waits: [(a, b, kind | None)]`,
  `agents: [(a, b)]` (Agent/Task calls), `tools: [(a, b)]` (all other tool calls), `person: [(a, b)]` (main coordinator only:
  prompt gaps and AskUserQuestion). Port `thread()` from `scripts/journey/measure.py`; epoch seconds throughout.
- `Evidence` dataclass: `no_transcript: [(a, b)]`, `kinds: [(a, b, kind)]` (record evidence), `actions: [(a, b)]`.
- `split(threads, evidence, a, b) -> dict` returns the design's split object: collect every endpoint inside `[a, b)`, classify
  each elementary segment at its midpoint in the order of design § Classification, sum the segment lengths. Use sorted
  interval lists with `bisect` so a 150-minute journey with ~40 threads splits in seconds.
- Round to 2 decimals only at the end; every key present.

**Done when:** the acceptance tests for the split, the classification order and the wait-call table pass (unit level).

## t2 — journey_sources.py and runs.followup

**Files:** scripts/cplat/journey_sources.py, scripts/cplat/runs.py, scripts/cplat/runs_store.py
**Covers:** AC-181.1, AC-181.3, AC-181.4, AC-181.6
**Goal:** everything the measurement reads from outside the transcripts, and the follow-up writer.

**Implementation notes:**
- `load_records(start, end, records_file: Path | None) -> (records, followups)`: design § CLI `--records`; store through
  `runs.open_store(runs.configured_repo())` and `runs_report.parse`; buffer through `runs._read_buffer()`; dedupe by `run_id`;
  an unreachable store is skipped silently (the buffer still counts).
- `system_tree(records, coordinator_sessions, repos, start, end) -> list[dict]` and
  `repo_sessions(tree, coordinator_sessions, root) -> (sessions, warnings)` per design § Children; a session is
  `{repo, session, path | None, span}`; the warning text is the design's, verbatim.
- `record_evidence(records, tree, repos, start, end) -> [(a, b, kind)]` per design § Record evidence (import
  `journey_timeline.command_wait` lazily, or take it as a parameter, so t2 does not wait for t1).
- `gh_runs(repo) -> list[dict]` is the seam tests replace (`gh run list -R <repo> --limit 1000 --json createdAt,startedAt,updatedAt,conclusion`
  through `core.run`); `actions(repos, start, end) -> (runs, intervals)` with `createdAt`..`updatedAt` intervals.
- `journey_record(records, run_id) -> dict | None`.
- `runs.followup(run_id, kind, data)` per design § Follow-up, built on `_buffer_add`, `flush` and `_warning`; add `followup` to the
  module docstring's API list.
- `runs_store.record_path`: a follow-up's file name uses `record["followup"]` instead of the literal `filed`.

**Done when:** the acceptance tests for repo-session discovery, the missing-transcript warning and the follow-up line pass.

## t3 — journey_measure.py, the verb

**Files:** scripts/cplat/journey_measure.py, scripts/cplat/runs_journey.py, scripts/journey/measure.py
**Covers:** AC-181.1–AC-181.6
**Goal:** `cplat platform runs journey measure` as in design § CLI, § JSON output and § Text output.

**Implementation notes:**
- Argument parsing as today's `measure.py` plus `--journey` and `--records`; `PlatformError` for the exit-1 cases.
- Build threads: coordinator mains and their subagents, then each found repo session and its subagents (`role="child"`);
  build `Evidence` from t2; split the window, each step, and the step total.
- Port `tokens`, `questions` and the GitHub counts (`merged_prs` keeps its own `gh pr list` call; the run counts reuse
  `actions()`'s runs) from `scripts/journey/measure.py`.
- Warnings to stderr, one line each, and into `warnings`; exit 0 with warnings.
- `--journey`: read the record's `journey.stages`, `parts`, `total` spans, split each, call
  `runs.followup(run_id, "journey_split", {"split": ...})`; print `journey split written to <run_id>` or the returned warning
  line; `journey.written` in the JSON.
- `runs_journey.main`: `measure` goes to `journey_measure.main(argv[1:])` before the parser; add the verb to the docstring.
- `scripts/journey/measure.py` becomes a forwarder: put `scripts/cplat` on `sys.path`, call `journey_measure.main(sys.argv[1:])`,
  exit with its code and print a `PlatformError` like `cplat` does.

**Done when:** the acceptance tests for AC-181.1–AC-181.5 and the writing half of AC-181.6 pass.

## t4 — report --benchmarks

**Files:** scripts/cplat/runs_journey_report.py, scripts/cplat/runs_usage_report.py, scripts/cplat/runs.py
**Covers:** AC-181.6
**Goal:** the split medians per stage, part and journey, as in design § Report.

**Implementation notes:**
- `runs._report`: pass `follows` to `aggregate_benchmarks(..., followups=follows)`; `aggregate_benchmarks` passes them to
  `runs_journey_report.aggregate(kept, followups)` (both default to no follow-ups, so other callers keep working).
- Latest `journey_split` follow-up per journey `run_id`; `split_runs`, `agents_median`, `waiting_median` on every row.
- `render_lines`: the new columns after `PRs`, `–` for `null`; nothing else in the lines changes. Update the footer sentence only
  by appending one clause about the new columns.

**Done when:** the acceptance tests for the reading half of AC-181.6 pass, and the existing spec 136 report tests still pass.

## t6 — the performance record

**Files:** docs/PERFORMANCE.md, docs/adr/README.md, docs/changelog.d/181-journey-measurements-count-waiting.changed.md
**Covers:** AC-181.7
**Goal:** the recipe uses the per-step table and the waits by kind; journeys 9 and 10 get a corrected split.

**Implementation notes:**
- "Recording a journey", step 3: `cplat platform runs journey measure <sessions> <start> <end> <repos> --steps <steps.tsv> --journey <run_id>`;
  describe the per-step table (agents with coordinator and children, waits by kind, `unattributed`, `no-tr`) and that waits by
  kind in the tables come from it.
- Re-measure journeys 9 and 10 from their saved coordinator transcripts, steps files and run records (`--records` with the
  records exported from the run store if the store is not reachable). Do not change any row; add one note under the
  "Where the wall clock went" table giving each journey's corrected split: person, agents (coordinator, children), waiting per
  kind. Keep the line 39 tool reference pointing at a path that still works (`scripts/journey/measure.py` forwards).
- `docs/adr/README.md`: restore it first if it still holds the overwrite marker (`git checkout -- docs/adr/README.md`), then add
  the ADR-096 row after 095.
- Changelog fragment (`changed`): the measurement counts repo sessions as agent time and waits by evidence; the new verb.

**Done when:** `cplat platform pr-check` passes the fragment, `scripts/shapes.py check` finds ADR-096 in the index, and the note
carries numbers from a real measurement of both journeys.

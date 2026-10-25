---
spec_id: 090-a-weekly-retro-proposes-the-next-specs
spec_hash: 2649dcf7d9c3
summary: cplat retro (report / propose / post), a pure weekly report over run records, platform issues and agent
  metrics, evidence-checked proposals, a public retro issue plus the full report in the run store, and the weekly
  workflow that cplat runs init installs in the store repo
tasks:
- id: t1
  title: Store transport reads single files
  files: [scripts/cplat/runs_store.py]
  covers: [AC-090.11, AC-090.14]
  parallel_safe: true
  depends_on: []
  done: true
- id: t2
  title: Pure weekly report (build, evidence index, private and public rendering)
  files: [scripts/cplat/retro_report.py]
  covers: [AC-090.1, AC-090.2, AC-090.3, AC-090.4, AC-090.5, AC-090.11]
  parallel_safe: true
  depends_on: []
  done: true
- id: t3
  title: Proposal format, validation, rendering and the agent prompt
  files: [scripts/cplat/retro_proposals.py, scripts/cplat/assets/retro-prompt.md]
  covers: [AC-090.7, AC-090.8, AC-090.9, AC-090.12]
  parallel_safe: true
  depends_on: []
  done: true
- id: t4
  title: GitHub access for the retro (issues, retro issues, label)
  files: [scripts/cplat/retro_github.py]
  covers: [AC-090.3, AC-090.10, AC-090.13]
  parallel_safe: true
  depends_on: []
  done: true
- id: t5
  title: Retro schedule asset and its installation by cplat runs init
  files: [scripts/cplat/retro_setup.py, scripts/cplat/assets/workflows/cplat-retro.yml, scripts/cplat/runs.py, scripts/pin-actions.py]
  covers: [AC-090.12, AC-090.14]
  parallel_safe: true
  depends_on: [t1]
  done: false
- id: t6
  title: Doctor checks the retro schedule and shares the store hint
  files: [scripts/cplat/doctor.py]
  covers: [AC-090.6, AC-090.14]
  parallel_safe: true
  depends_on: [t5]
  done: false
- id: t7
  title: The cplat retro command (report, propose, post)
  files: [scripts/cplat/retro.py]
  covers: [AC-090.1, AC-090.5, AC-090.6, AC-090.7, AC-090.9, AC-090.10, AC-090.11, AC-090.12, AC-090.13]
  parallel_safe: true
  depends_on: [t1, t2, t3, t4, t6]
  done: false
- id: t8
  title: Register cplat retro and document the retro
  files: [scripts/cplat/cplat.py, docs/CHANGELOG.md, docs/unattended-delivery.md, docs/self-hosted-runners.md]
  covers: [AC-090.1]
  parallel_safe: true
  depends_on: []
  done: true
human_steps:
- Give the run store repo its own self-hosted runner (an ARC scale set; personal accounts only have repo-level runners)
  with devbox, and set the repo variable CI_RUNNER to its name
- "Set the store repo secrets: CLAUDE_CODE_OAUTH_TOKEN (from `claude setup-token`) and RETRO_GH_TOKEN (fine-grained:
  Issues read/write on the platform repo, Contents read/write on the store)"
- Run `gh auth refresh -h github.com -s workflow`, then `cplat runs init <store>` once more, so the schedule is added to
  the existing store
---

The contract for every task is [design.md](design.md): the CLI, `report.json`, the evidence index, `proposals.json`,
the post order, the store layout and the workflow asset. ADR:
[036](../../adr/036-weekly-retro-evidence-checked-proposals.md). The acceptance tests in `tests/cplat/` exist before
coding starts. They fake `runs.open_store` (the `MemStore` of `test_runs.py`, extended with `read_file`),
`runs_store.gh`, `retro_github.tracker()` and `runs.utcnow`. No test touches GitHub.

## t1 — Store transport reads single files

**Files:** scripts/cplat/runs_store.py
**Covers:** AC-090.11, AC-090.14
**Goal:** the store can read one file by path, which the retro index and the schedule check need. A rejected workflow
write is reported as such, not as a concurrent write.

**Implementation notes:**
- `Store.read_file(path, deadline=None) -> str | None` in the protocol.
- `GitHubStore.read_file`:
  - `self._call(["api", f"repos/{slug}/contents/{path}", "-H", "Accept: application/vnd.github.raw+json"], deadline=…)`;
  - exit 0 → stdout;
  - `404` / `Not Found` in stderr → `None`;
  - anything else → `StoreUnreachable(_last_line(...))`.
- `_ApiError.race` additionally requires `"workflow" not in low`.
- Nothing else changes: `put`, `read` and `visibility` behave exactly as before.

**Done when:** the read-file parts of the AC-090.14 tests (present vs missing workflow) pass through a faked
`runs_store.gh`, and `tests/cplat/test_runs*.py` stay green.

## t2 — Pure weekly report (build, evidence index, private and public rendering)

**Files:** scripts/cplat/retro_report.py
**Covers:** AC-090.1, AC-090.2, AC-090.3, AC-090.4, AC-090.5, AC-090.11
**Goal:** `build`, `render_text`, `render_private`, `render_public`, `private_names`, `leaks` and the week helpers,
exactly as in design.md "Report". There is no I/O, so the same inputs always give the same JSON apart from
`generated_at`.

**Implementation notes:**
- Week helpers use `datetime.date.fromisocalendar` and `isocalendar()`; the week string is `%G-W%V`.
- Dedupe by `run_id` first, then split by `ended_at` into the covered and previous week. Every figure is
  `{"current", "previous"}`.
- Kinds × all four outcomes (+ `unknown`); phases with count, median and max; CI totals and per-run values.
- Escalations: all five causes. Reasons are ranked by runs, then total duration, then text, with at most 5 `run_ids`.
- Reruns: by reason, and by check (ranked).
- Repos per shape: from the first non-`none` `agents[].shape`, else `unknown`.
- Issues: only `auto-filed` issues with a `Signature: platform:` line. An occurrence is the creation or an
  `**Occurrence ` comment, dated by `created_at`. `routed` means a label in `triage.DECISION_LABELS`.
- Agents: call `runs_report.aggregate_agents` once per week on the pre-filtered records (`since_days=7`,
  `now=<week end>`). Match rows by `(agent, shape, model)`; build `previous` and the `diff` tree.
- `no_data`, `context`, and the evidence index with the `SAFE` token rule.
- Rendering as in the layout and the private/public table. Run `render_public` through `autoissue.scrub` with
  `private_names`. `leaks` is a case-insensitive substring check for every record `repo`, every record `spec` and the
  store slug.

**Done when:** the AC-090.2, .3, .4, .5 tests pass, and so do the rendering parts of AC-090.1 and AC-090.11 (the public
body has no repo, spec or store name, uses placeholders and counts per shape, and `leaks` finds a planted name).

## t3 — Proposal format, validation, rendering and the agent prompt

**Files:** scripts/cplat/retro_proposals.py, scripts/cplat/assets/retro-prompt.md
**Covers:** AC-090.7, AC-090.8, AC-090.9, AC-090.12
**Goal:** `load`, `validate`, `render_public_section`, `render_private_section`, `not_generated` and `prompt`, as in
design.md "Proposals". The prompt asset tells the headless agent what to read, what to write and the rules.

**Implementation notes:**
- `validate` works on spec proposals in file order:
  - format: title, problem (≤ 5 sentences), priority, spec_line;
  - evidence pairs against `report["evidence"]` (`math.isclose` for numbers);
  - `covers`: explicit spec or issue, else derived from an `issues.#N` ref (a tracking spec first, then the open
    issue);
  - the limit of 5. `rank` is 1..n.
- Prompt proposals: agent and shape must be a report row, with at least one matching `agents.<agent>|<shape>|` ref and
  a non-empty change. The limit is 3.
- Refused lines use the exact format of the contract.
- Public section rendering: `amends spec NNN` / `see #N`, evidence with previous values from the report, the
  `/svc:spec <spec_line>` line, and the refused count line.
- `not_generated(reason)` returns `Proposals: not generated (<reason>)`.
- `retro-prompt.md` uses `{dir}`, `{week}`, `{max_specs}` and `{max_prompts}` placeholders, filled by
  `prompt(report_dir)`. It forbids editing other files, running commands and copying record text.

**Done when:** the AC-090.7, .8 and .9 validation and rendering tests pass, including refusals that name the proposal,
limits beyond 5 / 3, and the derived `amends spec` / `see #N`.

## t4 — GitHub access for the retro (issues, retro issues, label)

**Files:** scripts/cplat/retro_github.py
**Covers:** AC-090.3, AC-090.10, AC-090.13
**Goal:** the `RetroTracker` protocol, `GhRetroTracker` over the module's `gh()` seam, and `tracker()`, as in design.md
"GitHub".

**Implementation notes:**
- Reuse `autoissue._json_values` / `_items` / `_check` for pagination and errors. Drop pull requests.
- `auto_issues(repo, since)` returns the issue fields plus `comments: [{"created_at", "body"}]`.
- `create` adds `--label retro`. On "not found", it creates the label (`5319e7`, `Weekly platform retro (spec 090)`)
  and retries once. Never `triage`.
- `edit_body`, `comment` and `close` go through `gh issue edit|comment|close -R`. Bodies are passed via `--body-file -`.
- Failures raise `autoissue.TrackerError`.

**Done when:** the tracker-level tests for AC-090.10 and .13 (the gh calls made, the label created when missing, no
`triage`) and the issue-reading part of AC-090.3 pass with a faked `retro_github.gh`.

## t5 — Retro schedule asset and its installation by cplat runs init

**Files:** scripts/cplat/retro_setup.py, scripts/cplat/assets/workflows/cplat-retro.yml, scripts/cplat/runs.py, scripts/pin-actions.py
**Covers:** AC-090.12, AC-090.14
**Goal:** the workflow asset exactly as in design.md "Schedule", `retro_setup` (`workflow_text`, `install_schedule`,
`secret_names`, `missing`), and `runs.init` installing the schedule.

**Implementation notes:**
- The asset uses the platform's checkout pin (`3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1`), top-level
  `permissions: contents: read`, and the cron `0 6 * * 1`.
  - Step order: report → install Claude Code → proposals → post.
  - `continue-on-error` only on the two middle steps. The proposals step overrides `GH_TOKEN: ""`.
  - `__PLATFORM_REPO__` is replaced by `workflow_text`.
- `install_schedule(store, slug)` never raises and returns the lines of the contract. No line contains `created`.
- `missing(store, slug)` returns the three entries in contract order, or `None` when the secrets cannot be read. It
  uses `runs_store.gh(["secret", "list", "-R", slug, "--json", "name"])`.
- `runs.init`: after the visibility check / `create_private`, extend the lines with `install_schedule(store, slug)`.
  The `export` line stays last. A public repo still raises before any write.
- `pin-actions.py`: default paths become `[".github", "templates", "scripts/cplat/assets"]`.
- `runs.py` docstring: `init` also installs the weekly retro schedule (spec 090).

**Done when:**
- The AC-090.14 init tests pass: a new store gets the file, an existing store without it gets it, and an existing store
  with it gets no write.
- The AC-090.12 workflow-file tests pass: schedule, self-hosted `runs-on`, step order, `continue-on-error`, and no
  GitHub token in the proposal step.
- `python3 scripts/pin-actions.py --check` passes, and the AC-087.20 init tests stay green.

## t6 — Doctor checks the retro schedule and shares the store hint

**Files:** scripts/cplat/doctor.py
**Covers:** AC-090.6, AC-090.14
**Goal:** `run_store_check(st)` (today's mapping, pure) and `check_retro_schedule()`, as in design.md "`cplat doctor`".

**Implementation notes:**
- `check_run_store()` becomes a `try` around `run_store_check(runs.store_status(timeout=10.0))`. Its output stays
  identical for every state.
- `check_retro_schedule()`:
  - `[]` unless `store_status().state == "ok"`;
  - otherwise `retro_setup.missing(runs.open_store(slug), slug)`;
  - warn/ok details and fixes exactly as in the contract; never `fail`.
- `run_checks` appends `*check_retro_schedule()` after `check_run_store()`.
- Reuse one `store_status` result inside `run_checks` if that is easy. Otherwise accept the second visibility call.

**Done when:** the AC-090.14 doctor tests pass (warns naming the missing schedule, the Claude secret and the GitHub
token secret; ok when all are there; silent without a store). The AC-087.11 doctor tests in `test_runs.py` stay green.

## t7 — The cplat retro command (report, propose, post)

**Files:** scripts/cplat/retro.py
**Covers:** AC-090.1, AC-090.5, AC-090.6, AC-090.7, AC-090.9, AC-090.10, AC-090.11, AC-090.12, AC-090.13
**Goal:** `main(argv)` with the default report mode and the `propose` and `post` subcommands, as in design.md "CLI",
"Propose" and "Post".

**Implementation notes:**
- Week: `retro_report.last_complete_week(runs.utcnow().date())`, or `--week`, validated as in the contract.
- Store: `runs.store_status()`. Anything other than `ok` raises `PlatformError` with `doctor.run_store_check(st)["fix"]`
  as hint. Then `runs.open_store(slug).read(<14 days: the previous Monday … the covered Sunday>)` and
  `runs_report.parse`. A `StoreError` raises the "cannot be read" error.
- Issues: `retro_github.tracker()` with `auto_issues(repo, since=<previous Monday>)` and `open_issues(repo)`, where repo
  is `autoissue.default_repo()`. A `TrackerError` raises the "cannot be read" error.
- Specs: `spec.scan(core.PLATFORM_ROOT)`, keeping the specs that are not `done` and not `superseded`
  (`number`, `id`, `title`, `status`, `tracks`).
- Report mode: print, or write `DIR/report.json` / `report.md` / `prompt.md` and remove stale proposals files. Report
  mode makes no write call to any seam.
- `propose`: the six-step contract. The claude command comes from `CPLAT_CLAUDE` (tests point it at a fake script).
  The child's environment is stripped of `GH_TOKEN`, `GITHUB_TOKEN` and `RETRO_GH_TOKEN`. It always returns 0.
- `post`:
  - load and validate (refused lines on stderr), then render and run the leak check, all before any write;
  - find, edit or create the issue for the week;
  - comment on and close the open earlier-week retro issues;
  - one `store.put` of `retros/<week>.md`, `.json` and `README.md` (upserted from `read_file`);
  - print the result line;
  - without `--dir`, build first and use "no proposal step ran".
- `generated_at` is `runs.utcnow()` formatted `%Y-%m-%dT%H:%M:%SZ`.

**Done when:**
- AC-090.1: report mode prints the week and makes no write call to the store or the tracker.
- AC-090.6: no store, an unreachable store or a failed read → exit 1, with the doctor hint, and nothing posted.
- AC-090.10: create, then replace.
- AC-090.11: the posted body passes the leak check; the store gets the three files and the index links the issue.
- AC-090.12: a missing credential or failed proposals still posts `Proposals: not generated (…)`; a failing report
  step posts nothing.
- AC-090.13: earlier retro issues are commented on and closed; others are untouched.
- The CLI parts of AC-090.5, .7 and .9 pass.

## t8 — Register cplat retro and document the retro

**Files:** scripts/cplat/cplat.py, docs/CHANGELOG.md, docs/unattended-delivery.md, docs/self-hosted-runners.md
**Covers:** AC-090.1
**Goal:** `cplat retro` is a registered command, and users learn how the weekly retro works and how to set it up.

**Implementation notes:**
- `cplat.py`: `"retro": "retro"` in `COMMANDS`. Docstring line:
  `cplat.py retro [--week W] [--json] [--out DIR] | propose --dir DIR | post [--dir DIR]   weekly platform retro (spec 090)`.
- `docs/CHANGELOG.md`: one bullet under `[Unreleased]`: **Feat (090): a weekly retro proposes the next specs.** It
  names:
  - `cplat retro`;
  - the Monday 06:00 UTC workflow that `cplat runs init` installs in the store repo;
  - the `retro` issue (counts only, earlier weeks closed);
  - the full report under `retros/` in the store;
  - the secrets `CLAUDE_CODE_OAUTH_TOKEN` and `RETRO_GH_TOKEN`;
  - the doctor warning.

  Only this task edits the CHANGELOG.
- `docs/unattended-delivery.md`: a "Weekly retro" subsection under "Run records". It covers:
  - the three steps;
  - what the report contains;
  - how proposals are checked (evidence refs, limits, `amends spec` / `see #N`);
  - what is public and what stays private;
  - the setup (the runner, both secrets, `gh auth refresh -s workflow`, `cplat runs init`);
  - running it by hand (`cplat retro`, `--week`).
- `docs/self-hosted-runners.md`: one paragraph. The run store repo needs its own runner (`CI_RUNNER`) for the weekly
  retro, with devbox; Claude Code is installed by the workflow when missing.
- No plugin or marketplace version bumps.

**Done when:** the registration test of AC-090.1 (`cplat.COMMANDS["retro"]`, docstring) passes. `devbox run validate`
and the Markdown link check pass.

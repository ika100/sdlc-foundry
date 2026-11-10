---
spec_id: 167-a-dispatcher-runs-the-backlog-in
shape: platform
spec_hash: 9e3e456df94c
summary: cplat dispatch runs approved specs and triaged issues in parallel slots from .platform/dispatch.yml, merging one at a time on green CI
tasks:
  - id: t1
    title: Policy file .platform/dispatch.yml (load, validate, defaults)
    files: [scripts/cplat/dispatch_policy.py]
    covers: [AC-167.1, AC-167.2]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t2
    title: Dispatcher state, steering, unit files, events, history and locks
    files: [scripts/cplat/dispatch_state.py]
    covers: [AC-167.5, AC-167.9, AC-167.11]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t3
    title: Headless writes the dispatch result file and stops at a checkpoint on the stop flag
    files: [scripts/cplat/headless.py, scripts/cplat/supervisor.py]
    covers: [AC-167.6, AC-167.8, AC-167.10, AC-167.11]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t4
    title: Dispatcher claims in claim.py and the approver in spec.approve
    files: [scripts/cplat/claim.py, scripts/cplat/spec.py]
    covers: [AC-167.3, AC-167.6]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t5
    title: Triage adds the triaged label; labels needs-decision and stale-premise
    files: [scripts/cplat/triage.py, plugins/issue/commands/triage.md, plugins/issue/.claude-plugin/plugin.json, .claude-plugin/marketplace.json]
    covers: [AC-167.3]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t6
    title: Notify events triage, budget, stuck and a reusable notify pass
    files: [scripts/cplat/notify_config.py, scripts/cplat/notify.py]
    covers: [AC-167.12]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t7
    title: Console Inbox panels and glossary terms for budget and stuck
    files: [scripts/cplat/console/inbox.py, scripts/cplat/console/glossary.py]
    covers: [AC-167.12]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t8
    title: Repo merge lock with behind check in pr wait --merge and ship land
    files: [scripts/cplat/merge_lock.py, scripts/cplat/pr.py, scripts/cplat/ship.py]
    covers: [AC-167.7]
    parallel_safe: true
    depends_on: [t1]
    done: true
  - id: t9
    title: cplat needs repo scope, kinds budget and stuck, issue escalations
    files: [scripts/cplat/needs.py]
    covers: [AC-167.8, AC-167.10, AC-167.12]
    parallel_safe: true
    depends_on: [t2]
    done: true
  - id: t10
    title: Backlog snapshot and candidate list
    files: [scripts/cplat/dispatch_backlog.py]
    covers: [AC-167.2, AC-167.3]
    parallel_safe: true
    depends_on: [t1, t2, t4]
    done: true
  - id: t11
    title: Premise and mode checks (the two agent calls)
    files: [scripts/cplat/dispatch_agent.py]
    covers: [AC-167.2, AC-167.4, AC-167.6]
    parallel_safe: true
    depends_on: [t2]
    done: true
  - id: t12
    title: Daily token ledger, unit usage, unknown usage and the 7-day hint
    files: [scripts/cplat/dispatch_budget.py]
    covers: [AC-167.2, AC-167.10]
    parallel_safe: true
    depends_on: [t2, t3]
    done: true
  - id: t13
    title: Readiness verdicts and priority order
    files: [scripts/cplat/dispatch_ready.py]
    covers: [AC-167.3, AC-167.5, AC-167.6]
    parallel_safe: true
    depends_on: [t1, t2, t4, t10]
    done: true
  - id: t14
    title: Unit lifecycle (start, adopt, observe, land, restart, pause, done, escalate, stale close, self-approval)
    files: [scripts/cplat/dispatch_units.py]
    covers: [AC-167.4, AC-167.6, AC-167.7, AC-167.8, AC-167.9, AC-167.11]
    parallel_safe: true
    depends_on: [t2, t3, t4, t8, t12]
    done: true
  - id: t15
    title: Dispatcher inbox, needs file, notification pass and daily digest
    files: [scripts/cplat/dispatch_notify.py]
    covers: [AC-167.10, AC-167.12]
    parallel_safe: true
    depends_on: [t2, t6, t9, t12]
    done: true
  - id: t16
    title: One cycle and its read-only evaluation for plan
    files: [scripts/cplat/dispatch_cycle.py]
    covers: [AC-167.2, AC-167.4, AC-167.5, AC-167.6, AC-167.10]
    parallel_safe: true
    depends_on: [t10, t11, t12, t13, t14, t15]
    done: true
  - id: t17
    title: Status, report, wait and plan documents and their text
    files: [scripts/cplat/dispatch_view.py]
    covers: [AC-167.2, AC-167.11]
    parallel_safe: true
    depends_on: [t2, t9, t12, t14]
    done: true
  - id: t18
    title: cplat dispatch CLI, the loop, steering verbs and registration
    files: [scripts/cplat/dispatch.py, scripts/cplat/cplat.py]
    covers: [AC-167.1, AC-167.2, AC-167.5, AC-167.9, AC-167.11]
    parallel_safe: false
    depends_on: [t16, t17]
    done: true
  - id: t19
    title: Dispatcher guide, AGENTS.md, ADR index and changelog fragment
    files: [docs/dispatch.md, docs/unattended-delivery.md, docs/AGENTS.md, docs/adr/README.md, docs/changelog.d/167-dispatcher.added.md]
    covers: []
    parallel_safe: true
    depends_on: []
    done: true
---

# Plan — 167 A dispatcher runs the backlog in parallel slots

The contract is [design.md](design.md): policy keys, verdicts, unit and result files, the merge lock, needs items,
CLI output. Every module is new and small except the changed shared ones (t3 to t9). Level 0 builds the foundations
in parallel; level 1 the readers and the merge lock; level 2 readiness, units and notifications; then the cycle, the
view and the CLI. Seams the tests replace: `dispatch_backlog.gh`, `dispatch_agent.ask`, `dispatch_state.now`,
`dispatch_units.spawn`/`alive`, `$CPLAT_DISPATCH_HEADLESS`, `merge_lock.sleep`, plus the existing `claim.gh`,
`ship.gh`, `runs.utcnow`.

## t1 — Policy file .platform/dispatch.yml (load, validate, defaults)

**Files:** scripts/cplat/dispatch_policy.py
**Covers:** AC-167.1, AC-167.2
**Goal:** read `.platform/dispatch.yml` into a typed `Policy` with the defaults of A2, refuse unknown keys and values
naming the dotted key and the allowed values, and say which keys were defaulted and which are unset.

**Implementation notes:**
- `load(repo, *, require_file=False, require_budget=False) -> Policy`; `Policy` has `values` (the full effective
  mapping of the design), `file` (path or None), `defaulted` (dotted keys), `unset` (`budget.tokens_per_day` when missing).
- Errors exactly as the design's "Errors" list; `require_file`/`require_budget` are set by `start` and `resume`.
- Allowed: `slots` int 1..10; `budget.tokens_per_day` int >= 1; `budget.per_unit` keys minutes, invocations, reruns,
  cost with a number > 0 or `off`; `sources` non-empty subset of issues, specs; `ready.labels`/`ready.exclude_labels`
  lists of strings; `priority` non-empty list of `label:<name>`, `spec-order`, `oldest`; `gates.approve_specs` human |
  self; `gates.merge` green-ci; `serialize` subset of merge, e2e containing merge.
- `budget_args(policy) -> list[str]`: `--budget k=v` pairs for headless.
- `serialize(repo) -> list[str]`: never raises; a missing or broken file is `["merge"]`.
- YAML through `yaml.safe_load`; a non-mapping top level is an error naming `(top level)`.

**Done when:** the AC-167.1 tests (missing file, missing key, unknown key, bad values, serialize without merge) and the
policy part of AC-167.2 (defaults marked, `unset`) pass at module level.

## t2 — Dispatcher state, steering, unit files, events, history and locks

**Files:** scripts/cplat/dispatch_state.py
**Covers:** AC-167.5, AC-167.9, AC-167.11
**Goal:** every piece of local state the dispatcher keeps, with atomic writes under a lock, so steering, pins and skips
survive a restart and units are found again from their worktrees.

**Implementation notes:**
- `base(slug) -> Path` = `${XDG_STATE_HOME:-~/.local/state}/sdlc-foundry/dispatch/<owner>__<name>/`; `worktree_path`,
  `log_path(unit)`, `needs_path(slug)`, `needs_files() -> list[Path]` (all repos, for needs.py), `merge_lock_path(slug)`.
- `update(slug, fn)` read-modify-write of `state.json` under `state.lock` (schema of the design's Data section);
  `load(slug)` returns the empty state for a missing or unreadable file.
- Steering helpers: `pause(drain)`, `resume()`, `resume_item(key)`, `set_slots(n)`, `pin(key)`, `unpin(key)`,
  `skip(key, reason)`, `hold(key, reason, unit)`; item parsing `parse_item("#123" | "123" | "spec-123" | "<spec id>")`.
- Unit files: `write_unit(worktree, data)`, `read_unit(worktree)`, file names `cplat-dispatch-unit.json`,
  `cplat-dispatch-result.json`, `cplat-dispatch-stop` in the worktree's git dir (`core.git_dir`).
- `events_add`, `events_unseen(kinds)`, `mark_seen(seq)` (last 500); `history_add`; `days_held(day, item, reason)`;
  pruning of ledger, history and days after 90 days.
- `loop_lock(slug)` context manager (non-blocking flock on `loop.lock`; `Busy` with the holder pid) and `loop_alive(slug)`.
- `now()` seam (local time) used by every module.

**Done when:** the state parts of AC-167.5 (pin and skip survive a reload), AC-167.11 (steering recorded) and AC-167.9
(unit files read back from a worktree) pass at module level.

## t3 — Headless writes the dispatch result file and stops at a checkpoint on the stop flag

**Files:** scripts/cplat/headless.py, scripts/cplat/supervisor.py
**Covers:** AC-167.6, AC-167.8, AC-167.10, AC-167.11
**Goal:** a unit's headless run tells the dispatcher its run id, its end and its tokens, and a pause stops it before its
next session.

**Implementation notes:**
- With `CPLAT_DISPATCH_RESULT` set, write the start record right after `runlog.start` and the end record in `main`'s
  `finally` (also on an exception), fields as the design's "Result file"; `tokens` from
  `runs_usage.for_run(runs.active(rid), peek=True)` totals before `runlog.finish`, null when incomplete.
- With `CPLAT_DISPATCH_UNIT` set, record the field `dispatch_unit` on the headless run record.
- `stop_requested(repo) -> bool`: the stop flag exists in the repo's git dir. Checked before each session in `_drive`
  and in `supervisor.drive`; then result `paused at a checkpoint by cplat dispatch`, exit 1.
- `stop_of`: `paused at a checkpoint` maps to stop reason `paused`, outcome `abandoned`, no escalation.
- Nothing changes without the two variables (existing headless tests stay green).

**Done when:** headless tests with a fake claude show the result file at start and end (tokens or null), the stop flag
ending a unit run and a legacy run before the next session with stop reason `paused`, and the existing headless and
supervisor tests pass.

## t4 — Dispatcher claims in claim.py and the approver in spec.approve

**Files:** scripts/cplat/claim.py, scripts/cplat/spec.py
**Covers:** AC-167.3, AC-167.6
**Goal:** tell a dispatcher claim from a manual one, and record who approved a spec.

**Implementation notes:**
- `DISPATCH = "cplat dispatch"`; `holder_by(issue) -> tuple[str | None, bool]`: the branch of the last unreleased claim
  and whether that claim comment contains `(cplat dispatch)`; `holder` keeps its behaviour.
- `claim(..., what="cplat dispatch")` already writes `Claimed for branch \`<b>\` (cplat dispatch).`; no change beyond a test.
- `spec.approve(spec, shape, by=None)`: changelog line `approved by <by>` when given, else `approved` as today.

**Done when:** claim tests for `holder_by` (manual label, manual claim, dispatcher claim, released claim) and a
`spec.approve(by="cplat dispatch")` test pass; existing claim and spec tests pass.

## t5 — Triage adds the triaged label; labels needs-decision and stale-premise

**Files:** scripts/cplat/triage.py, plugins/issue/commands/triage.md, plugins/issue/.claude-plugin/plugin.json, .claude-plugin/marketplace.json
**Covers:** AC-167.3
**Goal:** candidates exist: `/issue:triage` labels every issue it routes to a fix or a spec `triaged`, and the platform's
label set knows the dispatcher's labels.

**Implementation notes:**
- `triage.LABELS` gains `triaged` ("Routed by triage: ready for a fix or a spec (spec 167)"), `needs-decision`
  ("A decision of the user holds this issue (spec 167)"), `stale-premise` ("Closed: already resolved on main (spec 167)").
- `triaged` is not a decision label (`DECISION_LABELS` unchanged), so `list` behaves as before.
- triage.md step 5: `bug / small-change` apply `--add bug --add triaged --remove triage`; `feature` apply
  `--add tracked --add enhancement --add triaged --remove triage`.
- Bump the issue plugin to 1.1.0 in plugin.json and the marketplace entry.

**Done when:** `cplat issue triage setup-labels` creates the three labels, `apply --add triaged` is accepted, `devbox run
validate` passes, and the existing triage tests pass.

## t6 — Notify events triage, budget, stuck and a reusable notify pass

**Files:** scripts/cplat/notify_config.py, scripts/cplat/notify.py
**Covers:** AC-167.12
**Goal:** the dispatcher can run the same notification machinery (instant, quiet hours, resolve, digest) over its own
document and state, and the new events are configurable.

**Implementation notes:**
- `EVENTS` gains `triage`, `budget`, `stuck`; Recommended preset as the design (`triage` and `budget` desktop instant;
  `stuck` GitHub and desktop instant).
- `events_of(doc, kinds=("approve", "answer", "escalation", "promote", "review"))`: needs items of `kinds`; `triage`,
  `budget`, `stuck` map to their own event names.
- `process(cfg, doc, path, *, kinds, digest=None)`: the body of `run_once` (new events, quiet hours, held, resolve,
  `_why_dropped`, save); `digest(cfg, state, doc, when)` is called when due and not quiet; `run_once` calls `process`
  with today's kinds and `_send_digest`, so the console notifier is unchanged.
- `digest_due(cfg, state, when, *, every_day=False)` for A11's daily digest; `digest_channels(cfg)` = slack/email with
  at least one event set to `digest`.

**Done when:** notify tests for the three events (preset, unknown values refused), `process` with a custom document and
kinds (instant only for those kinds, held in quiet hours) and the existing notify tests pass.

## t7 — Console Inbox panels and glossary terms for budget and stuck

**Files:** scripts/cplat/console/inbox.py, scripts/cplat/console/glossary.py
**Covers:** AC-167.12
**Goal:** the Inbox lists `budget` and `stuck` items like any other and opens a panel for them.

**Implementation notes:**
- `panel_need` builders `_budget` (used of limit, running units, the command as a copyable block, no action button)
  and `_stuck` (reason, log path, the command; a "Copy command" action like `_escalation`).
- Glossary terms `budget` ("the dispatcher's daily token budget is used up; starts continue after midnight") and `stuck`
  ("a dispatcher unit ended twice without finishing"), added to the decision group.
- The table row needs no change (generic by kind).

**Done when:** console tests render an Inbox with a `budget` and a `stuck` item and open both panels; existing console
tests pass.

## t8 — Repo merge lock with behind check in pr wait --merge and ship land

**Files:** scripts/cplat/merge_lock.py, scripts/cplat/pr.py, scripts/cplat/ship.py
**Covers:** AC-167.7
**Goal:** merges into main from any unit or manual session happen one at a time per repo on the machine, and a branch
behind main has its CI run again on top before it merges.

**Implementation notes:**
- `merge_lock.held(slug, who, timeout, interval=5)`, `Busy`, holder file, waiting line once a minute; `sleep` seam.
- `merge_lock.merge(repo, url, watch, timeout, interval)`: behind check via `gh api repos/<slug>/compare/<base>...<head>
  --jq .behind_by`, `gh pr update-branch`, wait for the new head's checks with `ship.wait_checks`, merge with
  `--match-head-commit`; a conflict raises `merge_lock.Conflict` (a `PlatformError`: a human decision).
- `pr._wait`: with `merge`, take the lock around the merge (or before the first check wait when `e2e` is in
  `dispatch_policy.serialize(repo)`), then `merge_lock.merge`; the `who` names the PR and `$CPLAT_DISPATCH_UNIT`.
- `ship.land`: the same around the before-merge gitops PRs and the PR merge; after an update fast-forward the local
  feature branch; a `Busy` raises before any fix round is counted.
- No lock without `--merge`; `appship_merge.slot` (gitops repos) stays as it is.

**Done when:** the AC-167.7 tests pass: two concurrent merges (threads or processes with a fake gh) merge one after the
other, the second updates a behind branch and waits for green on the new head, a red check never merges, `e2e` in
`serialize` holds the lock from the first check wait; existing pr wait and ship land tests pass.

## t9 — cplat needs repo scope, kinds budget and stuck, issue escalations

**Files:** scripts/cplat/needs.py
**Covers:** AC-167.8, AC-167.10, AC-167.12
**Goal:** `cplat needs --json` lists `escalation`, `budget` and `stuck` items of dispatcher units, inside a system and in
a repo with a policy file but no system.

**Implementation notes:**
- `collect` reads `dispatch_state.needs_files()` and adds items whose `object.repo` is one of the system's repos.
- Repo scope: no `applications/*/system.yaml` and `.platform/dispatch.yml` present → `collect_repo(repo_dir)` over the
  origin slug: drafts, escalations of rows with that repo, `_triage(slug, all_triage=True)`, budget and stuck; the
  AC-122.4 error stays for a directory with neither file.
- `_escalations`: a row with an `issue` section gets `gh issue edit <N> --remove-label needs-decision` (kind
  `dispatch`) or `/component:fix #<N>`; "newer" must serve the same issue; a `dispatch` row whose `escalation.run` names
  another escalated row is skipped.
- `render` unchanged; the item shapes are the design's.

**Done when:** needs tests for repo scope, the two new kinds (object, reason, command), issue escalations from a
`dispatch` record and the skip of a ship unit's duplicate pass; existing needs tests pass.

## t10 — Backlog snapshot and candidate list

**Files:** scripts/cplat/dispatch_backlog.py
**Covers:** AC-167.2, AC-167.3
**Goal:** one snapshot of everything readiness needs, read from GitHub at most every 300 s, and the candidates it yields.

**Implementation notes:**
- `snapshot(repo, slug, *, max_age=300, fetch=True) -> Snapshot`: cached in the state; `plan` passes `fetch=False`
  (no `git fetch`, cache or a fresh GitHub read only); a failing source lands in `unavailable`.
- Sources and calls exactly as the design's Data section; comments only for issues with `in-progress` or a dispatcher marker.
- Specs from `origin/main` (`git ls-tree`, `git show`, parsed with `spec`'s helpers); drafts from open PRs with the
  `cplat:spec` marker via `gh api .../contents/...?ref=<head>`.
- `worktrees(repo)` from `git worktree list --porcelain` (path and branch), for `claimed` (branch checked out elsewhere).
- `candidates(snap, policy) -> list[Candidate]` (key, item, kind, title, labels, created, text, spec meta, tracks,
  status) per the design's candidate rule; a spec absorbs the issues it tracks.
- `gh` seam; no write calls in this module.

**Done when:** backlog tests with a fake gh and a temp git repo produce the candidate list of AC-167.2 (issues by label,
specs by status, drafts from PRs, spec + tracked issue as one) and leave labels, branches and worktrees unchanged.

## t11 — Premise and mode checks (the two agent calls)

**Files:** scripts/cplat/dispatch_agent.py
**Covers:** AC-167.2, AC-167.4, AC-167.6
**Goal:** the only two model calls, short, read-only, cached and counted.

**Implementation notes:**
- `ask(prompt, cwd, tools) -> tuple[str, int | None]` seam: `claude -p <prompt> --output-format json --max-turns 8
  --model <settings.coordinator_model> --allowedTools Read Grep Glob "Bash(git log:*)" "Bash(git show:*)"`,
  executable `$CPLAT_CLAUDE` or `claude`, timeout 180 s; tokens from the answer's `usage`.
- `premise(repo, issue, main_sha) -> {verdict, evidence, why, tokens}`: hints = commits on `origin/main` since the
  issue's creation mentioning `#N`; issue text redacted (`feedback.redact`) and fenced (`triage.fenced`); evidence
  validated (`git merge-base --is-ancestor <sha> origin/main`, or a merged PR via gh), else `holds`; a failed call is `holds`.
- `mode(repo, spec) -> {mode, why, tokens}`: a checking plan decides without a call (`units._task_units` at cap 3 has a
  `batch:` unit → team); else the agent; a failed call is `single`.
- Cache in the state keyed by item and (`main_sha`, issue `updatedAt`) or plan sha. The caller (t16) books the returned
  tokens with `dispatch_budget.book_agent`.

**Done when:** tests with a fake `ask` cover holds, resolved with valid and invalid evidence, a failed call, the
deterministic team/single from a plan, the agent fallback, and the cache reuse.

## t12 — Daily token ledger, unit usage, unknown usage and the 7-day hint

**Files:** scripts/cplat/dispatch_budget.py
**Covers:** AC-167.2, AC-167.10
**Goal:** know today's tokens of every unit and agent call since local midnight, know when a usage is unknown, and give
`plan` the last 7 days.

**Implementation notes:**
- `unit_tokens(unit_file, result_file) -> int | None`: running per the design (peek on the headless run's active
  record; no session yet = 0); ended: result `tokens`, else the record's `usage` from `runs._safe_buffer()`.
- `book(slug, units)`: the growth since `counted[unit]` goes to today's ledger; returns `Usage(day, used, unknown: list)`.
- `book_agent(slug, tokens | None)`: missing usage books 200 000.
- `reached(usage, policy) -> bool`; unknown blocks starts until known or the day changes.
- `history_hint(slug, days=7) -> list[{day, tokens | None}]`: top-level records (no `parent`) of the repo by local start
  day from buffer and store (`runlist` helpers); unreadable days null.
- `budget_need(slug, usage, policy, running) -> dict | None`: the `budget` item of the design for today.

**Done when:** the AC-167.10 tests at module level (sum since midnight across units and agent calls, unknown usage named,
midnight resets, one need per day) and the 7-day hint of AC-167.2 pass.

## t13 — Readiness verdicts and priority order

**Files:** scripts/cplat/dispatch_ready.py
**Covers:** AC-167.3, AC-167.5, AC-167.6
**Goal:** the verdict and reason of every candidate and the order of the ready ones, pure functions over the snapshot,
the state and the units.

**Implementation notes:**
- `judge(cands, snap, state, units, policy) -> list[Verdict]` with the reasons and their order from the design's table
  (skipped, needs-decision, stuck, claimed, blocked, duplicate, needs-spec, needs-approval); `ship-busy` and `stale`
  are applied during slot assignment (t16) through `hold_ship_busy` / `hold_stale` helpers here.
- `claimed` uses `claim.holder_by`, active run rows not belonging to a unit, and `snap.worktrees`.
- `blocked` regex `(?i)\b(?:blocked by|depends on)\s+#(\d+)` against the open issue numbers.
- Items with a unit not ended are excluded; items whose last unit ended after `snap.read_at` wait for the next snapshot.
- `order(ready, policy.priority, pins)`: pins first, then the rules as tie-breakers (`label:`, `spec-order`, `oldest`,
  then key), as the design.
- `text(verdict)` gives `ready`, `held: <reason> (<detail>)`, `held: skipped: <text>`.

**Done when:** the AC-167.3 tests (each held reason, no label/comment/claim written) and AC-167.5 tests (default order,
tie-breaking, prioritize, skip) pass at module level.

## t14 — Unit lifecycle (start, adopt, observe, land, restart, pause, done, escalate, stale close, self-approval)

**Files:** scripts/cplat/dispatch_units.py
**Covers:** AC-167.4, AC-167.6, AC-167.7, AC-167.8, AC-167.9, AC-167.11
**Goal:** everything that happens to one unit and the GitHub writes it makes, idempotent so that a restart of the loop
never repeats a start, a claim or a comment.

**Implementation notes:**
- `start(repo, slug, item, mode, slot, policy)`: claim, worktree, unit file, unit run record, `spawn` (design steps 1
  to 4); a refused claim returns `claimed` and leaves nothing; `headless_cmd` honours `$CPLAT_DISPATCH_HEADLESS`.
- `observe(unit) -> running | ended(classification)` per the design's table; `alive(pid)` seam as `appship_proc.alive`
  (also matching `dispatch land`).
- `land(unit)` for the hidden verb: `pr.wait(worktree, pr, True, 7200, 20, ship.QUEUE_TIMEOUT)`, record `landed`;
  `spawn_land(unit)` starts it detached.
- `finish_done`, `escalate(unit, reason, cause)`, `restart(unit)` (stash, `starts: 2`), `make_stuck(unit)` with the
  claim release, `needs-decision` label and marker comment, unit record end and events of the design.
- `pause_flags(units)` / `clear_flags(units)`; `resume_paused(unit)` restarts without counting.
- `adopt(repo, slug) -> list[unit]` from `git worktree list --porcelain` and unit files; a dispatcher claim on a unit
  branch without worktree is restarted without a new claim.
- `close_stale(repo, issue, evidence, why)` and `self_approve(worktree, spec)` (`spec.approve(by=...)`, `git commit -s`).

**Done when:** the AC-167.6 test with a fake headless (two overlapping units, the third waiting, claims naming `cplat
dispatch` and the branch), AC-167.8 (escalation label/comment/needs entry, restart once, stuck), AC-167.9 (kill and
adopt without a second claim or comment), AC-167.4 (stale close, reopened never again) and the land part of AC-167.7 pass.

## t15 — Dispatcher inbox, needs file, notification pass and daily digest

**Files:** scripts/cplat/dispatch_notify.py
**Covers:** AC-167.10, AC-167.12
**Goal:** the user hears only about the six kinds and gets one daily digest.

**Implementation notes:**
- `write_needs(slug, items)`: the repo's `needs.json` (budget for today, stuck items still open); resolved items dropped.
- `inbox(repo) -> doc`: `needs.collect_repo` filtered to approve, answer, escalation, triage, budget, stuck.
- `notify_pass(repo, slug, doc)`: `notify.process` with state `notify/dispatch-<owner>__<name>.json`, kinds all six, or
  only budget and stuck when `.platform-app.yml` exists.
- `digest(cfg, state, doc, when)`: daily at `digest.at`, sections Delivered, Escalated, Held, Queue, Tokens since
  `last_digest` from the dispatcher state's history, events, last cycle and ledger; all empty → not sent.

**Done when:** the AC-167.12 tests (inbox kinds, instant only for those kinds, quiet hours kept, digest content, empty
digest not sent) and the needs-entry part of AC-167.10 pass.

## t16 — One cycle and its read-only evaluation for plan

**Files:** scripts/cplat/dispatch_cycle.py
**Covers:** AC-167.2, AC-167.4, AC-167.5, AC-167.6, AC-167.10
**Goal:** `run_cycle` does one scheduling pass; `evaluate` computes the same decisions without any write to GitHub,
branches, worktrees or claims, for `plan`.

**Implementation notes:**
- `run_cycle(repo, policy) -> CycleResult`: observe units and act on ends (t14), book tokens (t12), snapshot (t10),
  judge and order (t13), then fill free slots in order: ship-busy, premise check for issues (stale → `close_stale`),
  mode check for specs, self-approval for drafts, `start`; record `last_cycle`, `days` held, events; write needs and run
  the notification pass (t15).
- No start and no agent call when paused, drained, the budget is reached or a usage is unknown; `why_not` says which.
- Paused units are resumed first after `resume`; free slots = effective slots (override or policy) minus units not ended.
- `evaluate(repo, policy) -> PlanDoc` (the design's `plan --json` without rendering): snapshot with `fetch=False`, the
  agent checks only for the would-start items (cached, booked), slot numbers, `premise: unchecked` for the rest.
- Agent tokens are booked with `dispatch_budget.book_agent` after each call.

**Done when:** cycle tests with fakes show the plan document of AC-167.2 (GitHub, branches, worktrees and claims equal
before and after), stale handling of AC-167.4 in `start` only, order and pins of AC-167.5, ship-busy, `--parallel 3/1`
and self-approval of AC-167.6, and no start/no agent call at the limit of AC-167.10.

## t17 — Status, report, wait and plan documents and their text

**Files:** scripts/cplat/dispatch_view.py
**Covers:** AC-167.2, AC-167.11
**Goal:** the documents and the text of `plan`, `status`, `report`, `inbox` and `wait`, exactly as the contract.

**Implementation notes:**
- `status_doc(repo, slug, policy)` from the state, unit files, processes and `dispatch_budget`; a ship unit's phase from
  its worktree's ship state or units file.
- `report_doc(slug, since_days)` from history, `days` and the ledger.
- `wait_result(slug, since) -> (code, lines)`: IDLE / ESCALATED / RED / TIMEOUT per the design, marking events seen.
- `render_plan`, `render_status`, `render_report` (text), `needs.render` reused for `inbox`; numbers with thousands
  separators only in text, never in JSON.

**Done when:** view tests render the documents of AC-167.2 and AC-167.11 (`status` fields, `report` per day, `wait`
first lines and exit codes) from fixture state.

## t18 — cplat dispatch CLI, the loop, steering verbs and registration

**Files:** scripts/cplat/dispatch.py, scripts/cplat/cplat.py
**Covers:** AC-167.1, AC-167.2, AC-167.5, AC-167.9, AC-167.11
**Goal:** `cplat dispatch start|plan|status|wait|report|inbox|pause|resume|slots|prioritize|skip` and the hidden `land`.

**Implementation notes:**
- argparse verbs with `--repo`, `--json`, `--once`, `--drain`, `--timeout` (default 540, `waits.record`), `--since`,
  `--reason`; policy loaded with `require_file`/`require_budget` for `start` and `resume`.
- `start`: `loop_lock`, `adopt`, then a tick every 5 s; a cycle when 60 s passed or a unit process ended; SIGINT/SIGTERM
  end the loop with exit 0, units keep running; `--once` runs one cycle.
- Steering verbs call `dispatch_state` and print one line; `resume` with an item resumes only that item.
- `land <unit>` calls `dispatch_units.land`.
- `cplat.py`: `"dispatch": "dispatch"` in `PLUMBING` and a doc line
  `cplat dispatch start|plan|status|wait|report|inbox|pause|resume|slots|prioritize|skip ...   run the backlog in slots (spec 167)`.
- Action lines on stdout as the design's `start` section.

**Done when:** end-to-end CLI tests pass for AC-167.1 (exit 1 cases through `cplat.main`), AC-167.2 (`plan` without a
file), AC-167.5 (prioritize/skip survive a restart), AC-167.9 (start after a kill adopts) and AC-167.11 (each steering
verb takes effect within one cycle, `wait` exit codes).

## t19 — Dispatcher guide, AGENTS.md, ADR index and changelog fragment

**Files:** docs/dispatch.md, docs/unattended-delivery.md, docs/AGENTS.md, docs/adr/README.md, docs/changelog.d/167-dispatcher.added.md
**Covers:** none (documentation)
**Goal:** a user can turn the dispatcher on step by step (plan only, one slot for fixes, more) from the docs.

**Implementation notes:**
- `docs/dispatch.md`: the policy file with every key and default, the rollout (plan → `slots: 1` issues → specs and more
  slots), the verbs, held reasons, labels, the merge lock, budget, notifications and digest; from design.md.
- `docs/unattended-delivery.md` and `docs/AGENTS.md`: a short section "The dispatcher (spec 167)" linking the guide.
- `docs/adr/README.md`: rows for ADR-088 and ADR-089.
- Changelog fragment per `docs/changelog.d/README.md`.

**Done when:** `devbox run validate` and the Markdown link check pass.

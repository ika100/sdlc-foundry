---
spec_id: 124-autonomy-is-declared-per-environment-and
shape: platform
spec_hash: b56c981f84f4
summary: Autonomy per environment in system.yaml (validated by render.py, rendered to autonomy.json, reported by model show),
  the command cplat system autonomy show, set, pause, resume, undo and approve behind /system:autonomy with signals that only
  lower, the engine contract (HTTP signals and status, issue format, fix run records and audit events in the run store), the
  review decision, engine badges, signal facts, three notification events and the System › Autonomy tab
tasks:
  - id: t1
    title: render.py — validate autonomy keys (environment, top-level paused, instance max) and write autonomy.json
    files: [templates/gitops-app/scripts/render.py]
    covers: [AC-124.1, AC-124.3, AC-124.4, AC-124.9, AC-124.22]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t2
    title: autonomy.py — levels, caps, defaults, validate, effective, compare/tighten, allows, outside
    files: [scripts/cplat/autonomy.py]
    covers: [AC-124.1, AC-124.2, AC-124.3, AC-124.4, AC-124.5, AC-124.6, AC-124.14, AC-124.22]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t3
    title: engine_issue.py — the engine's issue format, signature and parser; the signal label
    files: [scripts/cplat/engine_issue.py, scripts/cplat/triage.py]
    covers: [AC-124.10, AC-124.18]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t4
    title: run store — audit/ prefix, record_audit with buffer and flush, kind fix
    files: [scripts/cplat/runs_store.py, scripts/cplat/runs.py]
    covers: [AC-124.11, AC-124.12]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t5
    title: engine.py — signal and status client, token lookup, 60 s confirmation, heartbeat cache
    files: [scripts/cplat/engine.py]
    covers: [AC-124.7, AC-124.9, AC-124.13, AC-124.21]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t6
    title: instance promote --to dev --version <previous dev pin> (the rollback and its undo)
    files: [scripts/cplat/promote.py]
    covers: [AC-124.15, AC-124.16]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t7
    title: console/html.py — engine badge and guardrail list fragments
    files: [scripts/cplat/console/html.py]
    covers: [AC-124.18, AC-124.19]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t8
    title: model.py and model show — autonomy per environment and instance, paused
    files: [scripts/cplat/model.py, scripts/cplat/modelcmd.py]
    covers: [AC-124.1, AC-124.2, AC-124.4, AC-124.5, AC-124.9, AC-124.22]
    parallel_safe: true
    depends_on: [t2]
    done: true
  - id: t9
    title: audit.py — event schema, read from the run store, undo eligibility
    files: [scripts/cplat/audit.py]
    covers: [AC-124.7, AC-124.12, AC-124.16]
    parallel_safe: true
    depends_on: [t2, t4]
  - id: t10
    title: runlist.py — engine fix runs (actor, issue, facts, active from the store)
    files: [scripts/cplat/runlist.py]
    covers: [AC-124.7, AC-124.11, AC-124.18]
    parallel_safe: true
    depends_on: [t4]
    done: true
  - id: t11
    title: autonomy_actions.py — undo (revert PR, pin back, reopen) and approve (review, merge when green)
    files: [scripts/cplat/autonomy_actions.py]
    covers: [AC-124.16, AC-124.17]
    parallel_safe: true
    depends_on: [t6, t9, t10]
  - id: t12
    title: cplat system autonomy show|set|pause|resume (+ undo|approve routing), dispatch and /system:autonomy
    files: [scripts/cplat/autonomycmd.py, scripts/cplat/cplat.py, plugins/system/commands/autonomy.md]
    covers: [AC-124.5, AC-124.6, AC-124.7, AC-124.8, AC-124.13, AC-124.21]
    parallel_safe: true
    depends_on: [t2, t5, t8, t9, t10, t11]
  - id: t13
    title: needs.py — review decisions, signal issues in triage, issue signal facts, engine escalations
    files: [scripts/cplat/needs.py]
    covers: [AC-124.5, AC-124.7, AC-124.14, AC-124.17, AC-124.18]
    parallel_safe: true
    depends_on: [t2, t3, t8, t10]
  - id: t14
    title: notifications — review, signal and done-on-its-own events
    files: [scripts/cplat/notify_config.py, scripts/cplat/notify.py]
    covers: [AC-124.20]
    parallel_safe: true
    depends_on: [t3, t9, t13]
  - id: t15
    title: console plumbing — autonomy source, pause/resume/undo/review-approve actions, autonomy preview form
    files: [scripts/cplat/console/sources.py, scripts/cplat/console/actions.py, scripts/cplat/console/preview.py]
    covers: [AC-124.6, AC-124.7, AC-124.16, AC-124.17, AC-124.19]
    parallel_safe: true
    depends_on: [t12]
  - id: t16
    title: System › Autonomy tab — levels, guardrails, diff and Open PR, pause/resume, engine, caps, done on its own with Undo
    files: [scripts/cplat/console/autonomy_page.py, scripts/cplat/console/system_page.py]
    covers: [AC-124.13, AC-124.15, AC-124.16, AC-124.19, AC-124.21, AC-124.22]
    parallel_safe: true
    depends_on: [t7, t12, t15]
  - id: t17
    title: Inbox — review decision, engine badge, signal facts in the triage detail
    files: [scripts/cplat/console/inbox.py]
    covers: [AC-124.14, AC-124.17, AC-124.18]
    parallel_safe: true
    depends_on: [t7, t13, t15]
  - id: t18
    title: Board and panels — engine badge on cards and rows, signal facts in the issue panel, engine actor on the run panel
    files: [scripts/cplat/console/board.py, scripts/cplat/console/panels.py]
    covers: [AC-124.11, AC-124.15, AC-124.18]
    parallel_safe: true
    depends_on: [t7, t10, t13]
  - id: t19
    title: docs, ADR index, CHANGELOG and plugin versions
    files: [docs/autonomy.md, docs/console.md, docs/DOMAIN-MODEL.md, docs/adr/README.md, docs/CHANGELOG.md, plugins/system/README.md, plugins/system/.claude-plugin/plugin.json, .claude-plugin/marketplace.json]
    covers: [AC-124.2, AC-124.4, AC-124.9]
    parallel_safe: false
    depends_on: [t1, t2, t3, t4, t5, t6, t7, t8, t9, t10, t11, t12, t13, t14, t15, t16, t17, t18]
human_steps:
  - "Run /platform:update in each gitops-app repo that will declare autonomy, so its scripts/render.py knows the new keys and renders autonomy.json"
  - "Create an engine token per engine; put it in CPLAT_ENGINE_TOKEN or the OS keychain (service sdlc-foundry, account engine:<host of the engine URL>) on every machine that runs /system:autonomy, and give the engine the same token"
  - "Give the engine's GitHub identity write access to the private run store repo (CPLAT_RUNS_REPO), plus issues and pull requests in the system's repos"
  - "In ika100/ai-ops (its ADR-004): implement the engine side of design.md and contract.openapi.yaml (read autonomy.json, /v1/signals and /v1/status, the issue format, fix run records and audit events); it is a separate repo and not part of this build"
---

# Plan — 124 Autonomy is declared per environment and supervised in the console

The contract in [design.md](design.md) and [contract.openapi.yaml](contract.openapi.yaml) binds every task. It covers the `system.yaml` keys and their errors, `autonomy.json` and the `model show` additions, the guardrail rules, the engine's issue, run record and audit event, the engine HTTP, `cplat system autonomy`, the `needs` additions, the three notification events and the console markup. The decision that outlives this spec is [ADR-060](../../adr/060-autonomy-in-system-yaml-and-the-engine-contract.md). The levels are:

- **0:** t1, t2, t3, t4, t5, t6, t7
- **1:** t8, t9, t10
- **2:** t11, t13
- **3:** t12, t14, t18
- **4:** t15
- **5:** t16, t17
- **6:** t19

The console views (t16–t18) do not import `needs.py`, `runlist.py`, `audit.py` or `autonomycmd.py`. They read JSON through `console/sources.py`, and their tests use fixtures of the contract. ai-ops is not built here. The engine side is a contract boundary: its examples are the fixture issue bodies, run records, audit events and OpenAPI examples that the acceptance tests use, with a fake engine HTTP server and a faked run store.

**Acceptance tests outside this spec:** adding `/system:autonomy` changes AC-114.59's command count. The tester updates `WORKING` in `tests/cplat/test_plugins_114.py` in the red commit: `"autonomy"` goes under `system`, and the count in `test_exactly_the_32_working_commands_exist_ac_114_59` becomes 33 (rename the test to match). Coders do not touch it. AC-114.52 scans commands, READMEs and `docs/*.md`. In-scope prose never writes the two words `cplat runs` together and avoids "addon" and "product" as nouns.

## t1 — render.py

**Files:** templates/gitops-app/scripts/render.py
**Covers:** AC-124.1, AC-124.3, AC-124.4, AC-124.9, AC-124.22
**Goal:** the renderer accepts and validates the three autonomy keys with exactly the messages of design.md, and writes `applications/<system>/autonomy.json` when autonomy is declared.

**Implementation notes:**
- Add `autonomy` to `TOP_KEYS`, `ENV_KEYS` and `INSTANCE_KEYS`, and to the keys an external component's instance takes (`["promote", "autonomy"]`).
- Add `validate_autonomy(env, block)` with the key, value and type rules of the design table. Keep the error texts verbatim, including the prod cap message and the refusal of the `spec` route. Accept the integer YAML 1.1 makes of an unquoted `HH:MM`. Validate the timezone with `zoneinfo.ZoneInfo`.
- Validate the top-level `autonomy` (only `paused`, a boolean) and `components.<c>.instances.<env>.autonomy` (only `max`, a level).
- Compute the effective objects (defaults merged per key, `effective`, `cap`, `paused`, `promotion`, instance `effective` = the lower of the environment's effective level and `max`) in the renderer's own code. It must not import `cplat`.
- Write `autonomy.json` (sorted keys, 2-space indent, trailing newline) only when `system.yaml` has any of the three keys. Make it a managed file: `--check` compares it, and a render without autonomy removes it. A system without autonomy must render byte for byte as before.
- Document the keys in the module docstring's `system.yaml` example, next to `promote`.
- No Kubernetes manifest changes.

**Done when:** the render tests for AC-124.1, AC-124.3, AC-124.4 and AC-124.22 pass (valid fixtures render, each invalid one fails with its message), the existing renderer tests pass unchanged, and the equality test between `autonomy.json` and `cplat model show --json` (AC-124.9) passes once t8 is merged.

## t2 — autonomy.py

**Files:** scripts/cplat/autonomy.py
**Covers:** AC-124.1, AC-124.2, AC-124.3, AC-124.4, AC-124.5, AC-124.6, AC-124.14, AC-124.22
**Goal:** one pure module (standard library only, no I/O) with every autonomy rule `cplat` needs.

**Implementation notes:**
- `LEVELS`, `CAP`, `DEFAULTS`, `ROUTES = ("fix",)`, `CRITICALITY = ("low", "medium", "high")`, `DAYS`.
- `validate(env, block) -> None` raises `PlatformError` with the same messages as t1. `validate_instance(component, env, block)` and `validate_top(block)` do the same for their keys.
- `effective(env, block, *, paused, promotion) -> dict` returns the environment object of design.md. `instance(env_obj, max_) -> {"max", "effective"}`.
- `compare(old, new) -> {field: "tighter"|"looser"|"same"}` and `tighten(old, new) -> dict` follow the "tighter" rules of design.md `set`. `tighten` never returns a field looser than `old`.
- `allows(level) -> str` uses the texts of the level table.
- `outside(policy, fix, *, merges_today, runs_today, now) -> list[str]` returns the guardrail names in the design's order, and a missing fact counts as outside.
- `parse_duration("24h") -> timedelta` and `in_window(window, now) -> bool` (overnight windows, `zoneinfo`).

**Done when:** the unit-level acceptance tests for the level order and `improve` → `act` (AC-124.2), the prod cap (AC-124.3), defaults (AC-124.4), compare and tighten (AC-124.6), each guardrail of AC-124.14 and the instance cap (AC-124.22) pass.

## t3 — engine_issue.py

**Files:** scripts/cplat/engine_issue.py, scripts/cplat/triage.py
**Covers:** AC-124.10, AC-124.18
**Goal:** the platform's issue format for an engine's issue, as code that both the parser and the fixture tests use.

**Implementation notes:**
- `title(component, env, category) -> str` (at most 100 characters), `labels(engine, env, criticality) -> list[str]`, and `body(facts) -> str`, which renders the design's sections in order and redacts every value with `autoissue.scrub`.
- `signature(dedupe_key) -> "signal:<16 hex of sha256>"` and `SIGNATURE_RE`.
- `parse(body, labels) -> dict | None` with exactly the keys of design.md. `(none)` sections become `None`, `seen` is an int and `confidence` a float.
- `seen_again(body, at) -> (new_body, comment)` rewrites `- seen:` and `- last seen:` and returns the `**Seen again** (occurrence n) at …` comment. It is the reference for "a repeat adds to the existing issue".
- Add `"signal": ("5319e7", "Filed by an autonomy engine from a signal (spec 124)")` to `triage.LABELS`. `engine:`, `env:` and `criticality:` labels are made by the engine, like `env:` labels in spec 092.

**Done when:** the AC-124.10 format and dedupe tests (render, parse round trip, signature, seen again) pass.

## t4 — run store: audit and kind fix

**Files:** scripts/cplat/runs_store.py, scripts/cplat/runs.py
**Covers:** AC-124.11, AC-124.12
**Goal:** the run store reads and writes the `audit/` prefix, and `cplat` can record its own audit events without ever failing a command.

**Implementation notes:**
- `runs_store.audit_path(event) -> "audit/YYYY/MM/DD/<event_id>.json"` (day of `at`).
- `GitHubStore.read(days, deadline=None, prefix="runs")` uses the same GraphQL listing for `audit/`, and existing callers are unchanged. Extend the `Store` protocol to match.
- `runs.record_audit(event) -> str | None` validates the required keys, scrubs text with the existing redaction, and puts the file in one commit. When the store is unset, public or unreachable, it appends to `audit-buffer.jsonl` in `state_dir()` and returns the reason. It never raises and never prints to stdout.
- `runs.flush()` also writes the audit buffer (same deadline, same batch size), so `cplat platform runs flush` covers it. `buffered_count()` includes it.
- Add `"fix"` to `KINDS` (documentation only).

**Done when:** the AC-124.12 store tests (path, read with prefix, buffered write and flush with the faked store) and the AC-124.11 record-path tests pass.

## t5 — engine.py

**Files:** scripts/cplat/engine.py
**Covers:** AC-124.7, AC-124.9, AC-124.13, AC-124.21
**Goal:** the only code that talks to an engine over HTTP.

**Implementation notes:**
- `token(url) -> str | None`: `CPLAT_ENGINE_TOKEN`, else `notify_config.secret(None, f"engine:{host}")` (keychain).
- `send(targets: dict[env, url], kind, *, system, actor, policy_of: dict[env, dict] | None, pr, deadline_s=60) -> {env: {"confirmed": bool, "effective": str | None, "reason": str | None, "signal": id}}`. It sends to all environments in parallel threads, each POST with a 10 s timeout, retried until the deadline. It never raises. It refuses to send `lower` with a policy that `autonomy.compare` finds looser than the declared one, as a guard against a bug in the caller.
- `status(url, system, timeout=10) -> dict | None` and `state(status_doc, now) -> "ok"|"unreachable"` (heartbeat older than 5 minutes is `unreachable`).
- Cache in `${XDG_STATE_HOME}/sdlc-foundry/autonomy/<system>.json`: the last heartbeat per URL, and the pending signals sent from this machine.
- `confirmed_later(pending, status_doc, events) -> bool` applies the three rules of design.md.
- HTTP through `urllib.request` behind one replaceable `_http(method, url, body, token, timeout)`, which tests fake. No new dependency.

**Done when:** the AC-124.7 and AC-124.21 signal tests (confirmed, unconfirmed after 60 s with a fake clock, 409 on a loosening lower, no token) and the AC-124.13 heartbeat tests pass against a fake engine.

## t6 — promote: the dev rollback

**Files:** scripts/cplat/promote.py
**Covers:** AC-124.15, AC-124.16
**Goal:** `cplat instance promote <c> --to dev --version <tag>` pins dev back to a tag it ran before, as one pin pull request.

**Implementation notes:**
- `--to dev` without `--version` keeps today's error. With `--version`, the tag must appear as a `newTag` in an earlier revision of `overlays/dev/<c>/kustomization.yaml` (`git log -p` of that file in `--repo-dir`). Otherwise exit 1 with `<tag> is not a version dev ran before; dev follows main (a rollback pins only a previous dev version)`.
- `--version` accepts `sha-<40>` and `X.Y.Z` tags for dev. Only one component, no `--all`.
- Branch, title and body follow the existing promote PR, with the word `rollback` in the title. No digest check for dev.
- `--dry-run --json` names the previous and the new tag.

**Done when:** the AC-124.15 rollback tests and the pin-back tests of AC-124.16 pass on a fixture gitops repo.

## t7 — console/html.py fragments

**Files:** scripts/cplat/console/html.py
**Covers:** AC-124.18, AC-124.19
**Goal:** shared fragments, so the Inbox, the Board, the panels and the Autonomy tab render the same markup.

**Implementation notes:**
- `engine_badge(name) -> '<span class="badge" data-engine="…">…</span>'` (escaped; `""` for `None`).
- `guardrails(policy) -> '<dl data-guardrails>…'` with one `<dt>`/`<dd data-key="<group>.<field>">` per effective guardrail and `undoWindow`, in the design order.
- `level_name(level)` and `level_sentence(level)`, the text of `autonomy.allows`, kept in sync by a test. html.py does not import `autonomy.py`.

**Done when:** the markup tests for the engine badge and the guardrail list pass.

## t8 — model and model show

**Files:** scripts/cplat/model.py, scripts/cplat/modelcmd.py
**Covers:** AC-124.1, AC-124.2, AC-124.4, AC-124.5, AC-124.9, AC-124.22
**Goal:** `cplat model show --json` reports the declared and effective policy of every environment and instance.

**Implementation notes:**
- `Environment.autonomy: dict`, `Instance.autonomy: dict` and `Model.paused: bool`, built leniently through `autonomy.effective` and `autonomy.instance`. A malformed block falls back to the defaults (the renderer is the validator).
- `to_dict()` adds the top-level `autonomy`, `environments[].autonomy` and `instances[].autonomy` exactly as in design.md, also for a system without autonomy. Every existing key keeps its meaning, and `SCHEMA` stays 2.
- `promotion` in the autonomy object is `Environment.promotion`.
- `modelcmd.render` adds the text lines of design.md.

**Done when:** the AC-124.1, AC-124.2 (`improve` declared and `act` effective), AC-124.4 (effective defaults), AC-124.5 (`promotion` stays `manual` in prod at `act`) and AC-124.22 model tests pass, and so does the `autonomy.json` equality test with t1.

## t9 — audit.py

**Files:** scripts/cplat/audit.py
**Covers:** AC-124.7, AC-124.12, AC-124.16
**Goal:** read the audit events, build the platform's own events, and decide where Undo is allowed.

**Implementation notes:**
- `KINDS_ENGINE`, `KINDS_PERSON`, `UNDOABLE = ("merge", "promotion", "rollback", "dismissal")`.
- `read(since_days=1) -> list[dict]` reads the store's `audit/` (t4) and the local buffer, newest first. A store that cannot be read gives `[]` and `state()` reports it like `runlist._store`.
- `person_event(kind, *, actor, system, environment, object, policy, detail, undoes=None) -> dict` with `event_id` = `<UTC stamp>-cplat-<8 hex>`.
- `undo_state(event, model_doc, events, now) -> {"allowed", "reason", "command"}` with exactly the reasons of design.md, and the undo window from the event's environment in the current model.
- `done_on_its_own(events, now, hours=24)` returns the engine events of the undoable kinds.

**Done when:** the AC-124.12 read tests and the AC-124.16 undo-eligibility tests pass with fixture events.

## t10 — runlist: engine runs

**Files:** scripts/cplat/runlist.py
**Covers:** AC-124.7, AC-124.11, AC-124.18
**Goal:** engine fix runs appear in the run list in the eight stages, with their actor and facts.

**Implementation notes:**
- Add the row keys `actor`, `engine`, `issue`, `system`, `component`, `environment` and `fix` of design.md. They are `null` for platform runs.
- A store record with `actor.type == "engine"`, `outcome: null` and `started_at` less than 24 hours ago is `active: true`.
- Kind `fix` derives its phase like `build`. An escalated engine run (stopped by a pause, its budget or a guardrail) keeps `escalation` and `stopped_in`.
- `_pr` must not look up `feature/<spec>` for a record without `spec`. It uses the record's `pr`.

**Done when:** the AC-124.11 run-list tests (row keys, active from the store, phases and stage) and the stopped-by-pause row test of AC-124.7 pass.

## t11 — autonomy_actions.py: undo and approve

**Files:** scripts/cplat/autonomy_actions.py
**Covers:** AC-124.16, AC-124.17
**Goal:** the two person actions on things an engine did, as functions that `autonomycmd.py` routes to.

**Implementation notes:**
- `undo(repo_dir, event_id, *, dry_run, json) -> int` finds the event (`audit.read(30)`), requires `undo_state(...).allowed`, and then for a merge calls GraphQL `revertPullRequest` through `gh api graphql`. For a promotion or rollback it runs `promote.main([...,"--pr"])` with the event's `previous`. For a dismissal it runs `gh issue reopen` with the comment. Then it writes `audit.person_event("undo", undoes=…)` via `runs.record_audit`.
- `approve(repo_dir, target, *, dry_run, json) -> int` parses `<owner/repo>#<n>`, requires an engine `fix` run in `runlist.collect(30)` with that PR and the PR open, then runs `gh pr review --approve` (author fallback as in `spec_pr.land`) and `cplat pr wait <n> -R <repo> --merge`. It writes the `approve` event.
- `gh` goes through one replaceable `gh()`. Every refusal exits 1 with the reason from design.md.
- `--dry-run --json` gives `{"will_do": [...]}` and changes nothing.

**Done when:** the AC-124.16 undo tests (merge → revert PR, promotion/rollback → pin PR, dismissal → reopen, refused outside the window, already undone) and the AC-124.17 approve tests pass with a faked `gh`.

## t12 — cplat system autonomy and /system:autonomy

**Files:** scripts/cplat/autonomycmd.py, scripts/cplat/cplat.py, plugins/system/commands/autonomy.md
**Covers:** AC-124.5, AC-124.6, AC-124.7, AC-124.8, AC-124.13, AC-124.21
**Goal:** the command behind `/system:autonomy`, with `show`, `set`, `pause` and `resume`, routing `undo` and `approve` to t11.

**Implementation notes:**
- `NOUNS["system"]["autonomy"] = ("autonomycmd", [])` and the docstring line in `cplat.py`.
- `show` builds the design's JSON from `model.load_dir`, `engine.status` per distinct URL, `audit.read(1)`, `runlist.collect(1)` (budget today) and the pending signals from the engine cache. It exits 0 when an engine or the store fails. The text output has one block per environment, with `not supervised` and `not confirmed` lines.
- `set` validates through `autonomy.validate`, edits only `environments.<env>.autonomy` with round-trip YAML (quoted times, `"off"`-style quoting where YAML 1.1 needs it), renders, and restores byte for byte on failure (reuse `systemset.snapshot`/`restore`). It sends `lower` (only with `--pr`) for the tighter fields, opens the PR with the design's branch, title and body, and records `set`.
- `pause` and `resume` work as in design.md: the signal first, then the PR (or closing the open pause PR on resume), then the audit event. Unconfirmed environments are named and do not fail the command.
- `--dry-run --json` output as in design.md. `undo` and `approve` call `autonomy_actions`.
- `autonomy.md`: the usage line `/system:autonomy show | set <env> <level> [flags] | pause | resume | undo <event> | approve <repo>#<n>`, preview with `--dry-run`, run with `--pr`, report verbatim. Pause is urgent: run it at once after the preview.

**Done when:** the AC-124.6 tests (one PR touching only that environment's `autonomy` plus `autonomy.json`, body with old and new values and allows, lower sent only for tighter fields), the AC-124.7 pause and resume tests, the AC-124.21 unconfirmed tests, the AC-124.8 and AC-124.13 `show` tests and the AC-124.5 check (`set prod act` keeps `promote: manual`) pass with a fake engine, store and `gh`.

## t13 — needs.py

**Files:** scripts/cplat/needs.py
**Covers:** AC-124.5, AC-124.7, AC-124.14, AC-124.17, AC-124.18
**Goal:** what waits for a person includes engine fixes outside the guardrails, engine issues and stopped engine runs, as design.md specifies.

**Implementation notes:**
- `_reviews(rows, model, gitops_slug)` returns the `review` items. It takes engine `fix` rows with an open PR (`gh pr view --json state,statusCheckRollup`) and the policy of the instance the issue names (`instances[].autonomy.effective` and the environment's guardrails). At `propose`, or at `act` with a non-empty `autonomy.outside(...)` (merges and runs today from the rows), the item lists each guardrail in `why`.
- `TRIAGE_LABELS` gains `signal`. A triage item of a signal issue has `object.detail.signal = engine_issue.parse(...)` and `object.engine`.
- `_issues` asks for `body` as well, and adds `engine` (from the `engine:<name>` label) and `signal` (the parse) to each row.
- `_escalations`: an engine `fix` row gets the command `/component:fix #<issue>` and `cwd_repo` = the issue's repo.
- The `promote` item logic is unchanged at every level (AC-124.5). A test fixture at `act` proves it.

**Done when:** the AC-124.14 (each guardrail named), AC-124.17 (review item shape), AC-124.18 (signal facts and engine on issues), AC-124.7 (a stopped run escalates) and AC-124.5 needs tests pass.

## t14 — notifications

**Files:** scripts/cplat/notify_config.py, scripts/cplat/notify.py
**Covers:** AC-124.20
**Goal:** the events `review`, `signal` and `done-on-its-own` per channel. The platform delivers them, and the engine sends nothing.

**Implementation notes:**
- `EVENTS` grows by the three names, and the Recommended preset follows design.md.
- `collect` adds the open `signal` issues to its label sweep and `audit.done_on_its_own(audit.read(1), now)`.
- `events_of` turns `review` items, `signal` issues (with `prod` from `env:prod`) and done-on-its-own events into events with the keys of design.md.
- GitHub delivery: `review` requests the user's review on the PR (`gh pr edit --add-reviewer`), `signal` assigns the user to the issue, and `done-on-its-own` opens a `notify` issue as `run-done` does. Resolution follows the table.
- Quiet hours: a `signal` with `prod` goes through, like an `alert` with `env:prod`.

**Done when:** the AC-124.20 notify tests (config accepts the events, preset, detection, quiet hours for prod signals, resolution) pass.

## t15 — console plumbing

**Files:** scripts/cplat/console/sources.py, scripts/cplat/console/actions.py, scripts/cplat/console/preview.py
**Covers:** AC-124.6, AC-124.7, AC-124.16, AC-124.17, AC-124.19
**Goal:** the console can read the autonomy state, run the four new actions, and preview `/system:autonomy set`.

**Implementation notes:**
- `default_sources` gets `"autonomy"`: `cplat system autonomy show --json --repo-dir <snapshot(None)>`.
- `actions._slash` gets the kinds `pause`, `resume`, `undo` (event id pattern of design.md) and `review-approve` (`REPO` pattern for `pr_repo`, `NUMBER` for `pr`). They join `SINGLE_SESSION`, and `"/system:autonomy set "` joins `MODEL_COMMANDS`.
- `_lock_key` includes `event`, `pr_repo` and `pr`.
- `preview.FORMS` gets `autonomy`. `command_of` builds `/system:autonomy set <env> <level> --<flag> <value>…` from the design's fields, and `consequence_of`/`way_back_of` give the autonomy texts. The scratch run has no `--pr`, so no signal is sent.

**Done when:** the AC-124.19 preview tests (command, diff of only that environment, render checks), the action tests for AC-124.7, AC-124.16 and AC-124.17 (argv, validation, 400 on a bad event id) and the source test pass.

## t16 — System › Autonomy tab

**Files:** scripts/cplat/console/autonomy_page.py, scripts/cplat/console/system_page.py
**Covers:** AC-124.13, AC-124.15, AC-124.16, AC-124.19, AC-124.21, AC-124.22
**Goal:** the Autonomy tab of AC-124.19 with the markup contract of design.md.

**Implementation notes:**
- `system_page.page` reads `query["tab"]` (`overview` by default), renders `<nav aria-label="System sections">` with the two tabs, and for `autonomy` returns `autonomy_page.body(ctx)` inside the same layout. An unknown tab gives `404` (`LookupError`).
- `autonomy_page.body(ctx)` reads only the `autonomy` and `model` sources. It renders the pause banner, the button and what pausing means, then per environment the level form, `html.guardrails`, the preview area with the Open PR confirm, the engine state with its heartbeat, `not confirmed`, and the component caps.
- An unreachable engine uses `html.unavailable` with `data-source="engine:<env>"` and the words "not supervised". A failing `autonomy` source is the standard unavailable part of AC-122.42.
- "Done on its own (last 24 hours)" is a table of `show.actions` with who, what, the policy (level and short commit) and Undo, enabled or disabled with `undo.reason`. Rollbacks show the pinned and previous versions (AC-124.15).
- Levels above the cap are disabled with the reason, as AC-122.44 requires for disabled actions.

**Done when:** the AC-124.19 markup tests, the AC-124.13 and AC-124.21 not supervised and not confirmed tests, the AC-124.22 cap test and the AC-124.16 Undo-button tests pass against fixture sources.

## t17 — Inbox

**Files:** scripts/cplat/console/inbox.py
**Covers:** AC-124.14, AC-124.17, AC-124.18
**Goal:** the `review` decision and engine items in the Inbox.

**Implementation notes:**
- Add a `_review(ctx, item, d)` decision. It shows the why list (each guardrail named), regression before and after, CI, second review, summary, consequence and way back, and Approve as `data-action="review-approve"` with key `a`.
- Every row whose item has `object.engine` gets `html.engine_badge`.
- The triage decision of a signal issue shows `<dl data-signal>` (evidence, category, criticality, seen, instance), `<dl data-triage>` and the policy decision.
- The engine's stopped run uses the existing escalation decision with its `/component:fix` command.

**Done when:** the AC-124.17 review-decision tests, the AC-124.14 why-list test and the AC-124.18 Inbox badge and signal-facts tests pass.

## t18 — Board and panels

**Files:** scripts/cplat/console/board.py, scripts/cplat/console/panels.py
**Covers:** AC-124.11, AC-124.15, AC-124.18
**Goal:** engine items sit in the eight stages like any other, with a badge, and their panels show what the engine knew and did.

**Implementation notes:**
- Board cards and list rows of runs with `engine`, and of issues with `engine`, get `html.engine_badge`. Their stage comes from the existing run and issue mapping, with no new column.
- `panel_issue` shows the signal facts (from `needs.issues[].signal` or the triage item), with the same markup as the Inbox.
- `panel_run` of an engine run shows "by <engine>", the issue link, the policy level and commit, the regression result, and the decision with its `outside` list. A rollback shows the smoke result and the pinned and previous versions when the run carries them.

**Done when:** the AC-124.18 Board tests (stage, badge) and the AC-124.11 run-panel tests pass.

## t19 — docs and versions

**Files:** docs/autonomy.md, docs/console.md, docs/DOMAIN-MODEL.md, docs/adr/README.md, docs/CHANGELOG.md, plugins/system/README.md, plugins/system/.claude-plugin/plugin.json, .claude-plugin/marketplace.json
**Covers:** AC-124.2, AC-124.4, AC-124.9
**Goal:** a person can declare, change, pause and supervise autonomy from the docs alone, and an engine author can find the contract.

**Implementation notes:**
- `docs/autonomy.md` (new): the five levels and what each allows, every key with its default (the design table), the prod cap, the per-component cap, pause, resume and lowering (signals, then the PR), not confirmed and not supervised, Undo, the engine token, and a link to design.md and contract.openapi.yaml for engine authors.
- `docs/console.md`: the Autonomy tab, the review decision and the engine badge. `docs/DOMAIN-MODEL.md`: autonomy on Environment and Instance.
- `docs/adr/README.md`: the row for ADR-060. `docs/CHANGELOG.md`: the entry for this release.
- `plugins/system/README.md`: `/system:autonomy`. Bump the system plugin's minor version in `plugin.json` and `marketplace.json`.
- Keep the AC-114.52 prose rules.

**Done when:** `devbox run validate` and the doc link check pass, and the doc tests for the defaults table (AC-124.4) pass.

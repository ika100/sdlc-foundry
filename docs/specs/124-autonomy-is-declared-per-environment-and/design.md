# Design — 124 Autonomy is declared per environment and supervised in the console

## Decisions

- **The policy lives in `system.yaml` and the renderer is its validator (ADR-054).** `environments.<env>.autonomy`, the top-level `autonomy: {paused: true}` and `components.<c>.instances.<env>.autonomy: {max}` are new keys of `templates/gitops-app/scripts/render.py`. Every key, value and default below is checked there, and a render failure names the key and the allowed values (AC-124.1, AC-124.3, AC-124.4, AC-124.22). `cplat` has one pure module, `scripts/cplat/autonomy.py`, with the same table. `model.py`, the `set` command and the console use it. The two copies are held equal by a test that renders fixtures and compares (the existing pattern of `check_promote` in both places). ADR: [docs/adr/060-autonomy-in-system-yaml-and-the-engine-contract.md](../../adr/060-autonomy-in-system-yaml-and-the-engine-contract.md).
- **The engine reads one rendered JSON, never `system.yaml` (AC-124.9).** When a system declares autonomy (any of the three keys), `render.py` writes `applications/<system>/autonomy.json`. It equals the autonomy part of `cplat model show --json` (shape below). A system without any of the keys gets no file, so its render stays byte for byte what it is today, and an engine reads a missing file as `observe` everywhere. The engine reads the file from the gitops repo's `main` at most every 5 minutes, together with that commit's SHA, and audits every action with that SHA. This is the "same JSON rendered" of AC-124.9. It is rendered into the repo the cluster syncs from, not into a cluster object: a ConfigMap could not carry its own commit, and the engine would have to work out effective values that the platform already computes.
- **Signals act at once, git records them (AC-124.6, AC-124.7, AC-124.21).** `cplat system autonomy pause|resume|set` sends an HTTP signal to each environment's `engine` address (contract below), then opens the pull request. A signal can only set an environment *at or below* the level and guardrails declared in the merged `system.yaml`. A `lower` signal carries the tighter value of each field, old or new, and the engine refuses one that would loosen anything (`409`). `resume` only lifts a signalled or merged pause back to the declared policy. That is how AC-124.7's "the levels in `system.yaml` apply again" and AC-124.9's "a signal never raises autonomy" both hold: no signal goes above what a person merged.
- **Runs and audit events of an engine live in the private run store (spec 087, AC-124.11, AC-124.12).** The engine writes them, and `cplat` reads them through `runs_store` (new `audit/` prefix) and never asks the engine for its history. Only the heartbeat and the signal answer come from the engine's HTTP address. A heartbeat is liveness, which has to fail when the cluster cannot be reached (AC-124.13).
- **One command, `/system:autonomy`, runs in the gitops-app clone.** `cplat system autonomy show|set|pause|resume|undo|approve` (module `autonomycmd.py`; undo and approve in `autonomy_actions.py`). The console runs each through `cplat headless` like every other action (ADR-055). The model form "Autonomy" previews `set` on a scratch copy, and no signal is sent without `--pr`. Pause, resume and lowering are the only actions that change behaviour before their pull request merges, which extends AC-122.18 (AC-124.7).
- **Approving a review merges it.** The `review` decision's approve runs `/system:autonomy approve <repo>#<n>`. It does `gh pr review --approve`, then `cplat pr wait <n> -R <repo> --merge`, so the merge happens only when every check passed. At `propose` a person merges every fix (AC-124.2), and a review at `act` is outside a guardrail, so the engine will not merge it either. Without the merge the console's approval would leave the fix waiting.
- **The rollback of AC-124.15 is the one promotion into dev.** `cplat instance promote <c> --to dev --version <tag>` is allowed only when `<tag>` is a tag that `overlays/dev/<c>/kustomization.yaml` pinned before, according to the gitops repo's git history. It makes the same pin pull request as any promotion. Any other `--to dev` keeps today's error "dev follows main". The undo of a promotion (AC-124.16) uses this form for dev, and `--sha <previous>` (staging) or `--version <previous>` (prod) for the other environments.
- **The guardrail rules are code in `autonomy.outside()`.** It is the binding definition of each guardrail of AC-124.14. `cplat needs` uses it to decide whether an engine's fix waits for a person and to name each guardrail it is outside. The engine implements the same rules. The fixture tests of this spec are the shared examples.
- **Which policy applies to a fix:** the policy of the instance its issue names (`component` and `environment` of the issue, AC-124.10), capped by that instance's `max` (AC-124.22). The fix itself merges to `main` and reaches dev first.
- **Engine items reuse the existing kinds and stages.** An engine's issue is `triage` while it carries the `triage` label. An engine's stopped run is `escalation`, with the command `/component:fix #<issue>`. A fix that waits for a person is the new kind `review` in stage `Land`. `stages.py` is unchanged: no new stage and no new decision column (AC-124.18).

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `templates/gitops-app/scripts/render.py` | validate the three new keys, write `applications/<system>/autonomy.json` | changed |
| `scripts/cplat/autonomy.py` | levels, caps, defaults, `validate`, `effective`, `tighter`/`compare`, `allows(level)`, `outside(...)`, durations, windows | new |
| `scripts/cplat/model.py`, `modelcmd.py` | `Environment.autonomy`, `Instance.autonomy`, `Model.paused`; JSON and text of `model show` | changed |
| `scripts/cplat/engine_issue.py` | the engine's issue format: title, labels, body sections, `Signature: signal:…`, `parse(body, labels)` | new |
| `scripts/cplat/triage.py` | label `signal` in `LABELS` | changed |
| `scripts/cplat/runs_store.py`, `runs.py` | `audit_path`, `read(days, prefix=…)`; `record_audit(event)` with the local buffer and flush; `fix` in `KINDS` | changed |
| `scripts/cplat/audit.py` | audit event schema, `read(since)`, `undo_state(event, model, events, now)` | new |
| `scripts/cplat/engine.py` | HTTP client: `send(env, kind, …)`, `status(url, system)`, token lookup, heartbeat cache | new |
| `scripts/cplat/runlist.py` | engine runs: `actor`, `issue`, `environment`, `component`, `engine`, facts; active engine runs from the store | changed |
| `scripts/cplat/needs.py` | kind `review`; signal issues in `triage`; `issues[].signal`/`engine`; engine escalations | changed |
| `scripts/cplat/promote.py` | `--to dev --version <previous dev pin>` (rollback) | changed |
| `scripts/cplat/autonomycmd.py`, `autonomy_actions.py`, `cplat.py` | `cplat system autonomy show|set|pause|resume|undo|approve` | new / changed |
| `plugins/system/commands/autonomy.md` | `/system:autonomy` | new |
| `scripts/cplat/notify_config.py`, `notify.py` | events `review`, `signal`, `done-on-its-own` | changed |
| `scripts/cplat/console/html.py` | `engine_badge`, `guardrails` fragments | changed |
| `scripts/cplat/console/sources.py`, `actions.py`, `preview.py` | source `autonomy`; action kinds `pause`, `resume`, `undo`, `review-approve`; form `autonomy` | changed |
| `scripts/cplat/console/system_page.py`, `autonomy_page.py` | System tabs, the Autonomy tab | changed / new |
| `scripts/cplat/console/inbox.py`, `board.py`, `panels.py` | `review` decision, engine badges, signal facts, engine actor on runs | changed |

## Contract

### `system.yaml` (AC-124.1, AC-124.3, AC-124.4, AC-124.22)

```yaml
autonomy: {paused: true}             # optional, top level; only key `paused` (true|false); written by /system:autonomy pause
environments:
  dev:
    autonomy:
      level: act                     # observe | advise | propose | act | improve (prod: at most act)
      engine: https://ai-ops.dev.example.com   # http(s) URL of the engine that serves this environment
      autoMerge: {routes: [fix], maxCriticality: low}
      riskGate: {maxFiles: 5, maxLines: 200, regressionTest: true, secondReview: true}
      budget: {runsPerDay: 5, mergesPerDay: 2, perRun: {minutes: 60, invocations: 20, reruns: 2, cost: 3}}
      window: {days: [mon, tue, wed, thu, fri], from: "09:00", to: "17:00", timezone: Europe/Berlin}
      undoWindow: 24h
components:
  shop-api:
    instances:
      prod: {autonomy: {max: propose}}   # only `max`; also allowed on external components
```

| Key | Values | Default |
|---|---|---|
| `level` | `observe`, `advise`, `propose`, `act`, `improve`; prod at most `act` | `observe` (also for an environment without `autonomy`) |
| `engine` | `http://` or `https://` URL | none (no engine: nothing acts) |
| `autoMerge.routes` | list, subset of `[fix]` | `[fix]` |
| `autoMerge.maxCriticality` | `low`, `medium`, `high` | `low` |
| `riskGate.maxFiles` / `maxLines` | integer ≥ 1 | `5` / `200` |
| `riskGate.regressionTest` / `secondReview` | `true`, `false` | `true` / `true` |
| `budget.runsPerDay` / `mergesPerDay` | integer ≥ 0 | `5` / `2` |
| `budget.perRun` | mapping of `minutes`, `invocations`, `reruns`, `cost` (spec 102 units, numbers > 0) | `{minutes: 60, invocations: 20, reruns: 2, cost: 3}` |
| `window.days` | non-empty list of `mon`…`sun`, no duplicates | `[mon, tue, wed, thu, fri]` |
| `window.from` / `to` | `"HH:MM"` (00:00–23:59, `from` ≠ `to`; `to` < `from` spans midnight) | `"09:00"` / `"17:00"` |
| `window.timezone` | IANA name (`zoneinfo`) | `UTC` |
| `undoWindow` | `<n>m`, `<n>h` or `<n>d`, n from 1 to 9999 | `24h` |
| `components.<c>.instances.<env>.autonomy.max` | a level | none (the environment's level) |

Each nested mapping is merged key by key with its defaults, so `perRun: {cost: 5}` keeps the other three defaults. YAML 1.1 reads an unquoted `17:00` as the number 1020, and the renderer accepts such a number as that time (as it accepts an unquoted `off` for `policy`). `cplat` always writes quoted times. Render failures (each prefixed `applications/<system>/system.yaml: `, as today):

- `environments.<env>.autonomy: unknown key '<k>' (allowed: level, autoMerge, riskGate, budget, window, undoWindow, engine)`; nested: `environments.<env>.autonomy.riskGate: unknown key '<k>' (allowed: maxFiles, maxLines, regressionTest, secondReview)`, and the same form for `autoMerge`, `budget`, `budget.perRun` and `window`.
- `environments.<env>.autonomy.level must be one of observe, advise, propose, act, improve, got '<v>'`
- `environments.prod.autonomy.level: act is the highest level allowed in prod, got 'improve'` (AC-124.3)
- `environments.<env>.autonomy.autoMerge.routes: spec is refused: a spec always needs a person's approval (allowed: fix)`; any other value: `…routes: '<v>' is not a route (allowed: fix)`
- `autonomy: unknown key '<k>' (allowed: paused)`, `autonomy.paused must be true or false`
- `components.<c>.instances.<env>.autonomy: unknown key '<k>' (allowed: max)`, `….autonomy.max must be one of observe, advise, propose, act, improve, got '<v>'`
- Type errors name the key and the expected form, e.g. `….window.from must be "HH:MM", got '9am'`, `….undoWindow must be a duration like 24h, 90m or 2d, got '1 day'`, `….engine must be an http(s) URL`.

`autonomy` is added to `TOP_KEYS`, `ENV_KEYS`, `INSTANCE_KEYS` and the keys of an external component's instance (`promote`, `autonomy`). Autonomy changes no Kubernetes manifest.

### Meaning of the levels (AC-124.2, AC-124.5)

`autonomy.LEVELS = ("observe", "advise", "propose", "act", "improve")`, and each level includes the ones before it. `autonomy.CAP = {"dev": "improve", "staging": "improve", "prod": "act"}`. `autonomy.allows(level) -> str` is the one-sentence text below, used in pull request bodies, `show` and the console:

| Level | The engine may |
|---|---|
| `observe` | record issues from signals |
| `advise` | also triage them and notify |
| `propose` | also open fix pull requests that a person merges |
| `act` | also merge fixes within the guardrails, roll back after a failed smoke, and let a person undo |
| `improve` | act as `act` until a later spec defines it |

Effective level of an environment: `observe` when paused (in git, or by a signal the engine holds), else `act` for a declared `improve`, else the declared level. Effective level of an instance: the lower of its environment's effective level and its `max`. Promotion stays with `promote` (spec 093): an engine never promotes forward into any environment. Its only pin changes are the dev rollback of AC-124.15. A person's undo of AC-124.16 is a pin back to a version the environment ran before. `promotion` is reported next to the policy so that an engine reads both from one document.

### `cplat model show --json` additions and `applications/<system>/autonomy.json` (AC-124.1, AC-124.2, AC-124.4, AC-124.9, AC-124.22)

New keys only (schema stays 2), always present, also for a system without autonomy:

```json
{"autonomy": {"paused": false, "levels": ["observe", "advise", "propose", "act", "improve"]},
 "environments": [{"name": "dev", "…existing keys…": "…",
   "autonomy": {"declared": "improve", "effective": "act", "cap": "improve", "paused": false,
                "engine": "https://ai-ops.dev.example.com",
                "autoMerge": {"routes": ["fix"], "maxCriticality": "low"},
                "riskGate": {"maxFiles": 5, "maxLines": 200, "regressionTest": true, "secondReview": true},
                "budget": {"runsPerDay": 5, "mergesPerDay": 2, "perRun": {"minutes": 60, "invocations": 20, "reruns": 2, "cost": 3}},
                "window": {"days": ["mon", "tue", "wed", "thu", "fri"], "from": "09:00", "to": "17:00", "timezone": "UTC"},
                "undoWindow": "24h", "promotion": "main"}}],
 "instances": [{"component": "shop-api", "environment": "prod", "…existing keys…": "…",
                "autonomy": {"max": "propose", "effective": "propose"}}]}
```

`promotion` is `main` (dev), `after-dev-smoke` or `manual`. The text output adds per environment `autonomy <declared>[ (effective <e>)] engine <url|->`, and per instance with a `max` the line `autonomy max <m> (effective <e>)`.

`autonomy.json` is rendered only when `system.yaml` has a top-level `autonomy`, an `environments.<env>.autonomy` or an instance `autonomy`. It is a managed file: a render without any of those keys removes it. It has sorted keys, a 2-space indent and a trailing newline:

```json
{"schema": 1, "system": "shop", "paused": false, "levels": ["observe", "advise", "propose", "act", "improve"],
 "environments": {"dev": {"…": "exactly environments[].autonomy above"}, "staging": {}, "prod": {}},
 "instances": {"shop-api/prod": {"max": "propose", "effective": "propose"}}}
```

`instances` holds every instance of a non-library component, external ones included. Binding equality: for any valid `system.yaml` that declares autonomy, `autonomy.json.environments[e]` == the model's `environments[e].autonomy`, and `autonomy.json.instances["c/e"]` == the model's `instances[c,e].autonomy`.

### Guardrails (AC-124.14)

`autonomy.outside(policy: dict, fix: dict, *, merges_today: int, runs_today: int, now: datetime) -> list[str]` returns the guardrails a fix is outside, in this order and with these names:

| Name | Outside when |
|---|---|
| `autoMerge.routes` | `fix.route` not in `routes` |
| `autoMerge.maxCriticality` | `fix.criticality` above `maxCriticality` |
| `riskGate.maxFiles` | `fix.change.files > maxFiles` |
| `riskGate.maxLines` | `fix.change.lines > maxLines` (added + deleted) |
| `riskGate.regressionTest` | `regressionTest` is true and not (`fix.regression.before == "failed"` and `fix.regression.after == "passed"`) |
| `riskGate.secondReview` | `secondReview` is true and `fix.second_review.result != "passed"` |
| `budget.mergesPerDay` | `merges_today >= mergesPerDay` |
| `budget.runsPerDay` | `runs_today > runsPerDay` (this run included) |
| `window` | `now` in `window.timezone` is not on one of `days` or not in `[from, to)` |

`fix` is the engine's run record (below). A missing fact counts as outside, e.g. no `change` means outside `maxFiles` and `maxLines`. "Today" is the UTC day. An engine fix merges on its own only at effective level `act` with an empty list. At `propose`, or at `act` with a non-empty list, it waits as a `review` decision.

### The engine's issue (AC-124.10)

`engine_issue.py` owns the format and `parse`. The engine writes it in the component's repository (the gitops-app repo when the instance has no repo):

- Title: `[auto] [signal] <category>: <component> in <env>`, at most 100 characters.
- Labels: `triage`, `auto-filed`, `signal`, `engine:<engine name>`, `env:<env>`, `criticality:<low|medium|high>`.
- Body, in this order. Every value is one line, redacted with `autoissue.scrub`, and evidence is links only:

```markdown
## Signal
- component: shop-api
- environment: prod
- category: error-rate
- criticality: high
- dedupe key: shop-api/prod/error-rate/HTTP 500 on POST /cart
- seen: 3
- first seen: 2026-10-26T07:00:00Z
- last seen: 2026-10-26T09:12:00Z
- engine: ai-ops

## Evidence
- [Grafana: error rate](https://grafana.example.com/d/abc)

## Triage
- route: fix
- confidence: 0.82
- suspected files: src/shop_api/cart.py, src/shop_api/totals.py

## Policy
- level: act
- decision: review: outside riskGate.maxLines
- commit: 1a2b3c4d5e6f…

_Filed automatically by ai-ops (spec 124). Secrets were removed. Route it with /issue:triage._

Signature: signal:<first 16 hex of sha256(dedupe key)>
```

`## Triage` and `## Policy` are added when the engine triages (level `advise` and up), with `(none)` before then. A repeat of the dedupe key finds the issue by its `Signature:` line, in open issues and in issues closed within 7 days (it reopens those). It rewrites `- seen:` and `- last seen:` and adds the comment `**Seen again** (occurrence <n>) at <RFC3339>`. It never opens a second issue. `engine_issue.signature(dedupe_key) -> "signal:<16 hex>"` and `engine_issue.parse(body, labels) -> {"component", "environment", "category", "criticality", "dedupe_key", "seen": int, "first_seen", "last_seen", "engine", "evidence": [{"text", "url"}], "triage": {"route", "confidence": float, "suspected_files": [str]} | None, "policy": {"level", "decision", "commit"} | None}`. A body without `## Signal` gives `None`. The engine keeps `triage` until it routes the issue: at `propose` and up it removes `triage` when it starts a fix.

### Engine run record (AC-124.11)

A file `runs/YYYY/MM/DD/<run_id>.json` (day of `started_at`) in the run store holds one JSON line. The engine rewrites it at each phase and at the end. Platform records are written once (spec 087), and this is the only rewritten kind. Keys beyond schema 1 of spec 087:

```json
{"schema": 1, "run_id": "20261026T091500Z-1a2b3c4d", "kind": "fix", "repo": "acme/shop-api", "spec": null,
 "actor": {"type": "engine", "name": "ai-ops", "id": "ai-ops@shop"},
 "system": "shop", "component": "shop-api", "environment": "prod",
 "issue": {"repo": "acme/shop-api", "number": 57, "url": "https://github.com/acme/shop-api/issues/57"},
 "started_at": "…", "ended_at": null, "outcome": null,
 "phases": [{"name": "build", "started_at": "…", "ended_at": "…"}, {"name": "pr", "started_at": "…", "ended_at": null}],
 "budget": {"used": {"minutes": 12, "invocations": 6, "reruns": 0, "cost": 0.9}, "limits": {"minutes": 60, "invocations": 20, "reruns": 2, "cost": 3}},
 "pr": {"number": 88, "url": "https://github.com/acme/shop-api/pull/88"}, "ci_url": "…|null",
 "route": "fix", "criticality": "high", "change": {"files": 3, "lines": 412},
 "regression": {"test": "tests/test_cart.py::test_total_rounding", "before": "failed", "after": "passed"},
 "second_review": {"result": "passed|findings|not-run", "findings": ["…"]},
 "summary": "Round the cart total once, at the end.",
 "policy": {"level": "act", "commit": "<sha of autonomy.json>"},
 "decision": {"action": "merge|review|stop", "outside": ["riskGate.maxLines"]},
 "smoke": {"outcome": "passed|failed|not-run"},
 "escalation": null}
```

Phase names are the top-level phases of spec 087 (`build`, `pr`, `land`, `deploy`, `done`). The pull request body carries the regression test's before and after result in a section `## Regression test` with the lines `- test:`, `- before:` and `- after:`. A run stopped by a pause ends with `outcome: "escalated"`, `escalation: {"reason": "stopped by the pause <signal id> of <login>", "cause": "decision"}`. One stopped by its budget or a guardrail mid-run ends the same way with its reason.

`cplat runs --json` row additions (AC-122.5 contract, new keys only): `"actor": null | {"type": "engine", "name", "id"}`, `"engine": "ai-ops" | null`, `"issue": {"repo", "number", "url"} | null`, `"system"`, `"component"`, `"environment"` (null for platform runs), `"fix": {"route", "criticality", "change", "regression", "second_review", "summary", "policy", "decision"} | null`. A store record with `actor.type == "engine"` and `outcome: null` whose `started_at` is less than 24 hours ago is `active: true`. Kind `fix` derives its phase like `build` records.

### Audit events (AC-124.12, AC-124.7, AC-124.16)

A file `audit/YYYY/MM/DD/<event_id>.json` (day of `at`) in the run store holds one JSON line and is written once:

```json
{"schema": 1, "event_id": "20261026T091733Z-ai-ops-3f9c2a71", "at": "2026-10-26T09:17:33Z",
 "actor": {"type": "engine|person", "name": "ai-ops|<github login>", "id": "ai-ops@shop|<login>"},
 "system": "shop", "environment": "prod", "component": "shop-api",
 "kind": "issue|triage|run|merge|rollback|promotion|dismissal|signal-honoured|pause|resume|set|undo|approve",
 "object": {"type": "issue|pr|run|instance|signal|policy", "repo": "acme/shop-api", "number": 88, "url": "…",
            "run_id": "…|null", "version": "…|null", "previous": "…|null", "signal": "sig-…|null"},
 "policy": {"level": "act", "effective": "act", "guardrails": {"autoMerge": {}, "riskGate": {}, "budget": {}, "window": {}, "undoWindow": "24h"},
            "commit": "<sha>"},
 "store_ref": {"store": "ai-ops", "id": "…", "hash": "sha256:…"},
 "detail": {}, "undoes": null}
```

- Engine kinds: `issue` (made or seen again), `triage`, `run` (started or stopped), `merge`, `rollback` (with `object.version` = the pinned tag and `object.previous` = the tag before it, and `detail.smoke` = the failed smoke), `promotion`, `dismissal`, `signal-honoured` (`object.signal`). `store_ref` is required for engine events and is the entry in the engine's tamper-evident store.
- Person kinds, written by `cplat`: `pause`, `resume`, `set`, `undo` (`undoes` = the undone event), `approve`. `store_ref` is `null`. `detail` of `pause`/`resume`/`set`: `{"signal": "sig-…|null", "confirmed": ["dev"], "unconfirmed": ["prod"], "pr": "url|null", "old": {…}, "new": {…}}`.
- `cplat` writes its events through `runs.record_audit(event)`, which writes at once and falls back to the local buffer `audit-buffer.jsonl` in `runs.state_dir()`. The buffer is flushed by the next write and by `cplat platform runs flush`. Recording never changes a command's exit code.
- `audit.read(since_days) -> list[dict]` reads `audit/` for those days through `runs_store` (same GraphQL listing as `runs/`) plus the local buffer, newest first. It is re-read by every `show` and every console refresh (30 s), within the 60 s of AC-124.12.
- Undo (AC-124.16), `audit.undo_state(event, model, events, now) -> {"allowed": bool, "reason": str | None, "command": "/system:autonomy undo <event_id>" | None}`. Allowed when `actor.type == "engine"`, `kind` is `merge`, `promotion`, `rollback` or `dismissal`, `policy.effective == "act"`, `now - at <= undoWindow` of the event's environment (current model), and no event has `undoes == event_id`. Otherwise `reason` is one of `not done on its own`, `this kind cannot be undone`, `the undo window of <d> has passed`, `already undone by <login> at <t>`.

### Engine HTTP (AC-124.7, AC-124.13, AC-124.21)

Full schema: [contract.openapi.yaml](contract.openapi.yaml). The base URL is `environments.<env>.autonomy.engine`. Every request has `Authorization: Bearer <token>`. The token comes from `CPLAT_ENGINE_TOKEN`, else from the OS keychain (service `sdlc-foundry`, account `engine:<host of the URL>`, through `notify_config.secret`). Without a token no signal is sent, and that environment is `unconfirmed` with the reason `no engine token`.

- `POST /v1/signals` body `{"id": "sig-<12 hex>", "kind": "pause|resume|lower", "system", "environment", "at": RFC3339, "actor": "<login>", "policy": <environment autonomy object, the tighter of each field> | null, "pr": "url" | null}` gives `200 {"id", "environment", "confirmed": true, "effective": "<level>", "at"}`. Errors: `400`, `401`/`403`, `404 {"error": "unknown system or environment"}`, and `409 {"error": "raises autonomy", "fields": [...]}` for a `lower` that loosens a field. All errors are `{"error": str, "detail": str|null}`. The engine is idempotent per `id`. A pause makes the environment act as `observe` before it answers, and its running runs stop at their next step (recorded as above).
- `GET /v1/status?system=<name>` gives `200 {"engine": {"name", "version"}, "heartbeat_at": RFC3339, "environments": {"<env>": {"policy_commit": "<sha>", "applied_at", "declared", "effective", "paused": bool, "signals": [{"id", "kind", "at"}]}}}`.
- `engine.send(...)` sends to all environments in parallel. Each POST has a 10 s timeout and is retried until 60 s after the command started. An environment is `confirmed` only with a `200` and `confirmed: true`.
- An environment that was not confirmed counts as confirmed later when one of these is true: an engine `signal-honoured` event with that signal id exists; the engine status lists the id; or its status shows the requested state (`paused: true` for pause, `effective` at or below the requested level for lower, `paused: false` for resume). Until then `show` and the console report it as not confirmed (AC-124.21).
- Engine state for `show`: `ok` when `heartbeat_at` is at most 5 minutes old; `unreachable` when the call fails or the heartbeat is older (AC-124.13); `none` without an `engine`. The last heartbeat seen is cached in `${XDG_STATE_HOME}/sdlc-foundry/autonomy/<system>.json`, so an unreachable engine still shows when it was last heard from. An environment is `supervised` only when its engine is `ok`.

### `cplat system autonomy …` (AC-124.6, AC-124.7, AC-124.8, AC-124.16, AC-124.17, AC-124.21)

Common flags: `--repo-dir DIR` (a gitops-app clone, default `.`), `--system NAME`, `--json`. The actor is `gh api user -q .login`.

- `show [--json]` exits 0 even when an engine or the store is unreachable:

```json
{"schema": 1, "system": "shop", "read_at": "…", "paused": false, "paused_by_signal": false,
 "environments": [{"name": "prod", "declared": "act", "effective": "act", "cap": "act",
   "guardrails": {"autoMerge": {}, "riskGate": {}, "budget": {}, "window": {}}, "undoWindow": "24h",
   "budget_today": {"runs": 2, "merges": 1, "cost": 3.4, "runsPerDay": 5, "mergesPerDay": 2},
   "engine": {"url": "…|null", "state": "ok|unreachable|none", "name": "ai-ops|null", "version": "…|null", "heartbeat_at": "…|null"},
   "supervised": true, "confirmed": true,
   "pending": [{"signal": "sig-…", "kind": "pause|resume|lower", "at": "…", "pr": "url|null"}],
   "override": {"kind": "pause|lower", "level": "propose", "signal": "sig-…", "at": "…", "pr": "url|null"} | null,
   "caps": [{"component": "shop-api", "max": "propose", "effective": "propose"}]}],
 "actions": [{"…audit event (engine actor, last 24 h)…": "…", "undo": {"allowed": true, "reason": null, "command": "/system:autonomy undo 2026…"}}],
 "store": {"state": "ok|unset|unreachable|public"},
 "unavailable": [{"source": "engine:prod|runs", "error": "…"}]}
```

  `budget_today` counts the engine's `fix` runs started today (UTC) for that environment, `merge` events of today, and the sum of `budget.used.cost`. Without `--json` it prints one block per environment: level (declared and effective), paused, guardrails, budget used, engine with last heartbeat, and the line `not supervised` or `not confirmed` where it applies (AC-124.8).
- `set <env> <level> [--routes fix|none] [--max-criticality C] [--max-files N] [--max-lines N] [--regression-test true|false] [--second-review true|false] [--runs-per-day N] [--merges-per-day N] [--per-run KEY=VALUE]… [--days mon,tue,…] [--from HH:MM] [--to HH:MM] [--timezone TZ] [--undo-window D] [--engine URL] [--pr] [--dry-run]`
  - It validates with `autonomy.validate` before any edit and exits 1 with the renderer's message. Only `environments.<env>.autonomy` changes (round-trip YAML, as in `systemset.py`), and `render.py` then regenerates. A render failure restores everything byte for byte. A change that changes nothing exits 1 with `nothing to change`.
  - `autonomy.compare(old, new)` classifies each field as `tighter`, `looser` or `same`. Tighter means: a lower level; a subset of routes; a lower criticality; smaller numbers; `true` for the two booleans; a longer `undoWindow`; a window with the same timezone, a subset of its days and an interval within the old one. Any other window change, and any `engine` change, is looser.
  - With `--pr`, and only then: when a field is tighter and the environment has an `engine`, it first sends `lower` with `autonomy.tighten(old, new)` (the tighter of each field). It then opens one PR: branch `system/autonomy-<env>`, title `chore(system): autonomy <env> <old level> → <new level>`. The body has the old and new level, a table of every guardrail with old and new value, `allows(new level)`, and either "Takes effect after the merge." or "In effect now by signal <id> (confirmed | not confirmed: <reason>); the rest after the merge." The diff touches `environments.<env>.autonomy` in `system.yaml` and the rendered `autonomy.json`, nothing else. Last, it writes the audit event `set`.
  - `--dry-run --json` gives `{"will_do": [...], "signal": {"kind": "lower", "policy": {…}} | null, "effect": "now|after-merge|mixed", "pr": null}`.
- `pause [--pr] [--dry-run]` sends `pause` to the engine of every environment that has one. It prints a line per environment (`confirmed`, or `not confirmed within 60 s: <reason>`). Then, even when some did not confirm, it opens a PR (branch `system/autonomy-pause`, title `chore(system): pause all autonomy`) that sets the top-level `autonomy: {paused: true}`, and writes the audit event `pause`. Exit 0 when the PR opened, also with unconfirmed environments, which are named in the output and in `show`.
- `resume [--pr] [--dry-run]` sends `resume` the same way. When the pause PR (branch `system/autonomy-pause`) is still open, it closes it with the comment `Resumed by <login> at <t> before this merged.` and opens no PR. Otherwise it opens a PR (branch `system/autonomy-resume`, title `chore(system): resume autonomy`) that removes `paused` (and the top-level `autonomy` when it is then empty). It writes the audit event `resume`.
- `undo <event_id> [--dry-run]` requires `audit.undo_state(...).allowed`, else exits 1 with the reason.
  - `merge`: GitHub GraphQL `revertPullRequest` on the merged PR (title `Revert "<title>"`, body `Undo of <event_id> by <login> (spec 124).`); prints the revert PR's URL.
  - `promotion` and `rollback`: `cplat instance promote <component> --to <env> --version|--sha <object.previous> --pr` in the same clone.
  - `dismissal`: `gh issue reopen <n> -R <repo>` with the comment `Reopened: undo of <event_id> by <login>.`
  - Then it writes the audit event `undo` with `undoes`. The undone event stays as it was.
- `approve <owner/repo>#<n> [--dry-run]` requires an engine `fix` run whose `pr` is that PR, and that PR open, else exits 1. It runs `gh pr review <n> -R <repo> --approve --body "Approved by <login> in the review decision (spec 124)."`, then `cplat pr wait <n> -R <repo> --merge`, then writes the audit event `approve`. When GitHub refuses the review because the user is the PR's author, it comments `approved by <login>` and merges the same way, as `cplat spec land` does.

`/system:autonomy` (`plugins/system/commands/autonomy.md`) runs `set`, `pause` and `resume` with `--dry-run` first, shows the plan, then runs them with `--pr`. It runs `show` as is, and `undo` and `approve` after showing `--dry-run`.

### `cplat needs --json` additions (AC-124.14, AC-124.17, AC-124.18, AC-124.5)

The kinds become `approve|answer|escalation|promote|triage|review`.

| kind | when | stage | `since` | command |
|---|---|---|---|---|
| `review` | an engine `fix` run whose PR is open and not merged, where the instance's effective level is `propose`, or is `act` and `autonomy.outside(...)` is not empty | Land | the run's `pr` phase start | `/system:autonomy approve <repo>#<n>` |
| `triage` (extended) | open issue labelled `triage` and one of `alert`, `smoke-failure`, `signal` | Issue | `createdAt` | `/issue:triage <n>` |
| `escalation` (extended) | an escalated engine `fix` run: as today, with command `/component:fix #<issue>` and `cwd_repo` = the issue's repo | stage of `stopped_in` | `ended_at` | `/component:fix #<n>` |

`review` item (`cwd_repo` is the gitops repo):

```json
{"id": "review:acme/shop-api#88", "kind": "review", "stage": "Land",
 "object": {"type": "run", "repo": "acme/shop-api", "spec": null, "run_id": "…", "issue": 57, "component": "shop-api",
            "version": null, "pr": 88, "url": "https://github.com/acme/shop-api/pull/88", "engine": "ai-ops", "environment": "prod"},
 "since": "…", "reason": "outside riskGate.maxLines (412 lines, at most 200)",
 "command": "/system:autonomy approve acme/shop-api#88", "cwd_repo": "acme/shop-gitops",
 "consequence": {"why": [{"guardrail": "riskGate.maxLines", "text": "412 lines, at most 200"}],
                 "level": "act", "regression": {"test": "…", "before": "failed", "after": "passed"},
                 "ci": "passed|failed|pending|unknown", "second_review": {"result": "passed", "findings": []},
                 "summary": "…", "merges_to": "dev"},
 "way_back": {"text": "After the merge, Undo or a revert pull request takes the change back; the issue stays linked."}}
```

At `propose` `why` is `[{"guardrail": "level", "text": "level propose: a person merges every fix"}]`. CI comes from `gh pr view <n> -R <repo> --json statusCheckRollup,state`. A `promote` item is computed exactly as before, at any autonomy level (AC-124.5).

`issues[]` rows gain `"engine": "<name>|null"` (from the `engine:<name>` label) and `"signal": engine_issue.parse(...) | null`. The issue list asks for `body` as well. A `triage` item of a signal issue carries `object.detail.signal` (the parse) and `object.engine`.

### Notifications (AC-124.20)

`notify_config.EVENTS` grows by `review`, `signal`, `done-on-its-own`. In the Recommended preset, `review` is `github: instant, desktop: instant`, `signal` is `github: instant, desktop: instant`, and `done-on-its-own` is `desktop: instant` with everything else `off`.

| Event | Key | From | GitHub delivery | Resolution |
|---|---|---|---|---|
| `review` | `review:<repo>#<n>` | `needs` items of kind `review` | request review from the user on the PR | the item leaves `needs` |
| `signal` | `signal:<repo>#<n>` | open issues labelled `signal` | assign the user to the issue | issue closed or routed |
| `done-on-its-own` | `done-on-its-own:<event_id>` | audit events by an engine of kind `merge`, `rollback`, `promotion`, `dismissal` in the last 24 h | an issue labelled `notify`, as for `run-done` | undone, or its `undoWindow` passed |

Quiet hours let a `signal` through only when the issue has `env:prod`, as for `alert`. The engine sends no message.

### Console (AC-124.17, AC-124.18, AC-124.19, AC-124.13, AC-124.21, AC-124.22)

- **Source** `autonomy`: `cplat system autonomy show --json --repo-dir <snapshot of the gitops repo>`, 60 s timeout, refreshed with the others every 30 s.
- **Actions** (`POST /api/actions`, run in the gitops repo's clone through `cplat headless`, `--max-runs 1`):

  | Kind | Object | Args | Command |
  |---|---|---|---|
  | `pause` | `{"repo": <gitops>}` | — | `/system:autonomy pause` |
  | `resume` | `{"repo": <gitops>}` | — | `/system:autonomy resume` |
  | `undo` | `{"repo": <gitops>, "event": "<event_id>"}` | — | `/system:autonomy undo <event_id>` (`event_id` must match `^[0-9]{8}T[0-9]{6}Z-[a-z0-9-]{1,40}$`) |
  | `review-approve` | `{"repo": <gitops>, "pr_repo": "<owner/repo>", "pr": n}` | — | `/system:autonomy approve <pr_repo>#<pr>` |
  | `model` | as today | `{"command": "/system:autonomy set …"}` | the previewed command (`/system:autonomy set ` joins `MODEL_COMMANDS`) |

  The lock key also includes `event`, `pr_repo` and `pr`, so two reviews do not lock each other.
- **Preview** form `autonomy` takes the fields `env`, `level` and the optional `routes`, `maxCriticality`, `maxFiles`, `maxLines`, `regressionTest`, `secondReview`, `runsPerDay`, `mergesPerDay`, `perRun.<k>`, `days`, `from`, `to`, `timezone`, `undoWindow` and `engine`. It turns them into `/system:autonomy set <env> <level> --<flag> <value>…` and runs that without `--pr` on the scratch copy, so no signal is sent. The result is the usual `{"command", "diff", "checks", "valid", "consequence", "way_back"}`. `consequence` is `["<allows(level)>", "Takes effect after the merge." | "Takes effect at once by a signal: <fields>."]`, and `way_back` is `["/system:autonomy set <env> <old level>"]`.
- **System tabs:** `GET /system?tab=overview|autonomy` (default `overview`, which is today's page). `<nav aria-label="System sections">` has exactly two `<a data-tab="overview|autonomy">`, and the current one has `aria-current="page"`.
- **Autonomy tab markup** (`autonomy_page.py`):
  - The banner when paused is `<section data-paused="true">`. `<button data-action="pause" data-object='{"repo": …}' data-confirm="…">Pause all autonomy</button>` (or `data-action="resume"` "Resume") sits next to `<p data-pause-means>`, which says: every environment acts as `observe` within 60 seconds, running fixes stop at their next step, a pull request records it, and Resume brings back the levels in `system.yaml`.
  - Per environment `<section data-env="<env>" data-level="<effective>" data-supervised="true|false" data-confirmed="true|false">`:
    - the level as `<form data-form="autonomy" data-post="/api/preview" data-wrap>` with five `<input type="radio" name="level" value="<level>">`. A level above the cap gets `disabled aria-disabled="true"` and `<span data-disabled-reason>act is the highest level allowed in prod</span>`;
    - the guardrail fields;
    - the effective guardrails as `<dl data-guardrails>` with `<dd data-key="riskGate.maxLines">200</dd>` per field;
    - the preview's `<pre data-diff>` and `<code data-command>`, and the confirm `<button data-action="model" …>Open PR</button>`;
    - the engine as `<span data-engine-state="ok|unreachable|none">` with `<time data-heartbeat="ISO">`; when it is unreachable, the `unavailable` part of AC-122.42 with `data-source="engine:<env>"` and the words "not supervised";
    - `<span data-unconfirmed>not confirmed</span>` while a signal is pending;
    - `<span data-cap="<component>">max <level></span>` per capped component, next to the level (AC-124.22).
  - "Done on its own (last 24 hours)" is a table in `<div class="scroll-x">`. Each row is `<tr data-event="<event_id>" data-event-kind="<kind>">` with when, who (`actor.name`), what (kind and object link), the policy (`level` and short commit) and `<button data-action="undo" data-object='{"repo": …, "event": …}'>Undo</button>`, or the same button disabled with `<span data-disabled-reason>` = `undo.reason`.
- **Engine badge:** `<span class="badge" data-engine="<name>">ai-ops</span>` on every Inbox row, Board card and List row of an item whose issue has an `engine:` label or whose run has `actor.type == "engine"`.
- **Review decision** (Inbox detail, `panel_need`): the why list `<ul data-why>` with `<li data-guardrail="riskGate.maxLines">`, `<dl data-regression>` (test, before, after), the CI state, `<section data-second-review>`, the summary, the consequence and the way back. Approve is `<button data-action="review-approve" aria-keyshortcuts="a">` with `<kbd>a</kbd>`.
- **Signal facts** (Inbox triage detail and the issue panel): `<dl data-signal>` with category, criticality, seen, instance and the evidence links. The triage block `<dl data-triage>` has route, confidence and suspected files, and `<p data-policy-decision>` shows the policy decision. Before triage it shows `(none)`.
- **Run panel** of an engine run: the actor ("by ai-ops"), the issue link, the policy level and commit, and the regression result.

## Data

- `system.yaml`: the new keys, changed only by `/system:autonomy` PRs (or by hand); `applications/<system>/autonomy.json` is generated when autonomy is declared.
- Run store: `runs/…` engine fix records (written and rewritten by the engine), `audit/YYYY/MM/DD/<event_id>.json` (engine and `cplat`).
- Local: `${XDG_STATE_HOME:-~/.local/state}/sdlc-foundry/runs/audit-buffer.jsonl` (unsent `cplat` audit events), `${XDG_STATE_HOME}/sdlc-foundry/autonomy/<system>.json` (last heartbeat per engine, pending signals sent from this machine).

## Risks

- **Gitops repos need the new `render.py`.** Until `/platform:update` runs there, `/system:autonomy set` fails in the render with `unknown key 'autonomy'`, which is the right refusal. A system that declares no autonomy renders exactly as before, so the update changes no generated file there.
- **A dev rollback is undone by the next build of `main`.** `pin-dev` pins every new `main` build. After a rollback the broken commit is still on `main`, so the engine's reopened issue (AC-124.15) is the follow-up, and a revert or fix has to land before the next merge. The engine owns that order. It is recorded here because the platform cannot enforce it.
- **Pause latency.** The console runs pause through `cplat headless`, which adds Claude's start time, usually a few seconds. The 60 s of AC-124.7 count from the command, and `cplat system autonomy pause` from a terminal is the fastest path. Both are documented in `docs/autonomy.md`.
- **The engine must be reachable from where the command runs.** Signals and heartbeats go to the `engine` URL from the person's machine. An in-cluster-only address is always `unreachable` and not supervised, and the PR still records the pause (AC-124.21).
- **ai-ops is built in its own repository against this contract.** The fixture tests of this spec (issue bodies, run records, audit events, the OpenAPI examples) are the shared examples. A change to any of them is a contract change and needs a spec in both repositories.

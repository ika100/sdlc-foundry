# Autonomy per environment

Autonomy lets an always-on **engine** fix a running system without waiting for a person, within limits you declare per environment. It is optional and off by default: every environment is at `observe` until you say otherwise, and a system that never mentions autonomy renders exactly as before. Everything on the platform still works from Claude Code alone; the console and an engine only add to it.

The decision behind it is [ADR-063](adr/063-autonomy-in-system-yaml-and-the-engine-contract.md). The full contract for engine authors is in [design.md](specs/124-autonomy-is-declared-per-environment-and/design.md) and [contract.openapi.yaml](specs/124-autonomy-is-declared-per-environment-and/contract.openapi.yaml).

## The five levels

Each level includes the ones before it.

| Level | The engine may |
|---|---|
| `observe` | record issues from signals |
| `advise` | also triage them and notify |
| `propose` | also open fix pull requests that a person merges |
| `act` | also merge fixes within the guardrails, roll back after a failed smoke, and let a person undo |
| `improve` | act as `act` until a later spec defines it |

Two rules hold at every level. A spec always needs a person's approval, so the only auto-merge route is `fix`. And an engine never promotes forward into any environment: promotion stays with the rules in [DOMAIN-MODEL.md](DOMAIN-MODEL.md#one-file-per-system). Its only pin change is a rollback in dev (see Undo).

## Declare it in `system.yaml`

```yaml
autonomy: {paused: true}             # optional, top level; written by /system:autonomy pause
environments:
  dev:
    autonomy:
      level: act
      engine: https://ai-ops.dev.example.com
      autoMerge: {routes: [fix], maxCriticality: low}
      riskGate: {maxFiles: 5, maxLines: 200, regressionTest: true, secondReview: true}
      budget: {runsPerDay: 5, mergesPerDay: 2, perRun: {minutes: 60, invocations: 20, reruns: 2, cost: 3}}
      window: {days: [mon, tue, wed, thu, fri], from: "09:00", to: "17:00", timezone: Europe/Berlin}
      undoWindow: 24h
components:
  shop-api:
    instances:
      prod: {autonomy: {max: propose}}
```

Every key is optional. Nested mappings are merged key by key with their defaults, so `perRun: {cost: 5}` keeps the other three defaults.

| Key | Values | Default |
|---|---|---|
| `level` | `observe`, `advise`, `propose`, `act`, `improve`; prod at most `act` | `observe` (also for an environment without `autonomy`) |
| `engine` | `http://` or `https://` URL | none (no engine: nothing acts) |
| `autoMerge.routes` | list, subset of `[fix]` | `[fix]` |
| `autoMerge.maxCriticality` | `low`, `medium`, `high` | `low` |
| `riskGate.maxFiles` / `maxLines` | integer of 1 or more | `5` / `200` |
| `riskGate.regressionTest` / `secondReview` | `true`, `false` | `true` / `true` |
| `budget.runsPerDay` / `mergesPerDay` | integer of 0 or more | `5` / `2` |
| `budget.perRun` | `minutes`, `invocations`, `reruns`, `cost` (numbers above 0) | `{minutes: 60, invocations: 20, reruns: 2, cost: 3}` |
| `window.days` | non-empty list of `mon`...`sun`, no duplicates | `[mon, tue, wed, thu, fri]` |
| `window.from` / `to` | `"HH:MM"`; `to` before `from` spans midnight | `"09:00"` / `"17:00"` |
| `window.timezone` | IANA name | `UTC` |
| `undoWindow` | `<n>m`, `<n>h` or `<n>d` | `24h` |
| `components.<c>.instances.<env>.autonomy.max` | a level | none (the environment's level) |
| top-level `autonomy.paused` | `true`, `false` | `false` |

Quote times (`"17:00"`): YAML reads an unquoted `17:00` as a number. The renderer accepts it, but `cplat` always writes quoted times. A wrong key or value fails the render and names the key and the allowed values.

### Caps

- **Prod cap.** `environments.prod.autonomy.level` is at most `act`. `improve` in prod fails the render.
- **Per-component cap.** `instances.<env>.autonomy.max` lets one component act below its environment, for example `propose` for a payment service in an environment at `act`. It can only lower the level, never raise it. It is also allowed on external components.
- **Pause.** While paused (in git or by a signal), every environment acts as `observe`.

The effective level of an environment is `observe` when paused, otherwise `act` for a declared `improve`, otherwise the declared level. An instance acts at the lower of its environment's effective level and its `max`.

## Guardrails

At `act`, an engine merges a fix on its own only when it is inside every guardrail. A fix outside any of them, and every fix at `propose`, waits as a **review** decision for a person (Inbox in the console, `cplat needs`). A missing fact counts as outside.

| Guardrail | Outside when |
|---|---|
| `autoMerge.routes` | the fix's route is not listed |
| `autoMerge.maxCriticality` | the issue's criticality is above the maximum |
| `riskGate.maxFiles` / `maxLines` | the change touches more files, or adds plus deletes more lines |
| `riskGate.regressionTest` | the fix has no test that failed before and passes after |
| `riskGate.secondReview` | the second review did not pass |
| `budget.mergesPerDay` / `runsPerDay` | today's (UTC) merges or runs are used up |
| `window` | now is outside the days and hours, in the window's time zone |

The rules are the code in `scripts/cplat/autonomy.py` (`outside()`); an engine implements the same rules.

## Show, change, pause and resume

Run these in the system's gitops-app clone, or use the System > Autonomy tab of the [console](console.md#autonomy-the-system-tab-for-what-runs-on-its-own).

```bash
/system:autonomy show
/system:autonomy set prod propose --max-files 3 --engine https://ai-ops.example.com
/system:autonomy pause
/system:autonomy resume
```

(`cplat system autonomy <verb>` is the underlying command.) `set <env> <level>` takes `--routes`, `--max-criticality`, `--max-files`, `--max-lines`, `--regression-test`, `--second-review`, `--runs-per-day`, `--merges-per-day`, `--per-run KEY=VALUE`, `--days`, `--from`, `--to`, `--timezone`, `--undo-window` and `--engine`. Add `--dry-run` to see the plan, and `--pr` to signal the engines and open the pull request. Only `environments.<env>.autonomy` changes.

How a change takes effect:

- **Raising** a level or loosening a guardrail takes effect after the pull request is merged.
- **Lowering**, tightening and **pausing** also act at once: the command sends a signal to each environment's engine, then opens the pull request that records it. A signal can only set an environment at or below what is merged in `system.yaml`, and the engine refuses one that would loosen anything.
- **Resume** lifts a pause back to the merged policy. It never goes above it.

If an engine cannot be reached, the pull request still records your intent and the command and console report that environment as **not confirmed** until the engine catches up. An environment with an engine that does not answer is **not supervised**: the level is declared, but nothing acts on it. An environment with no `engine` is also not supervised.

## What it did, and Undo

An engine writes its runs and audit events to the private run store. `/system:autonomy show` and the console list what it did on its own in the last 24 hours, with the policy level and commit that allowed each action.

- `/system:autonomy undo <event>` takes back an action done at level `act`, inside the environment's `undoWindow`, once. An undo is a pin back to a version the environment ran before, through a pull request: `--sha <previous>` in staging and `--version <previous>` in prod, as with any promotion.
- **Dev rollback.** Dev normally follows main, so `/instance:promote <component> --to dev` fails with "dev follows main". The one exception is `--to dev --version <tag>`, allowed only when `<tag>` is a version the dev overlay pinned before, according to the gitops repo's git history. The engine's rollback after a failed smoke and the undo of a dev action use it.
- `/system:autonomy approve <owner/repo>#<n>` approves an engine's fix pull request and merges it once every check passed. It is what the console's review decision runs.

## The engine token

`cplat` talks to each engine's HTTP address (`/v1/signals`, `/v1/status`) with a bearer token. Create one token per engine, give the engine the same token, and put it on every machine that runs `/system:autonomy`:

- in the environment variable `CPLAT_ENGINE_TOKEN`, or
- in the OS keychain: service `sdlc-foundry`, account `engine:<host of the engine URL>` (for `https://ai-ops.dev.example.com` that is `engine:ai-ops.dev.example.com`).

Without a token, a signal is reported as not sent ("no engine token") and the pull request is still opened. The token is never written to a file in the repo.

## One-time setup

1. Run `/platform:update` in each gitops-app repo that will declare autonomy, so its `scripts/render.py` knows the keys and writes `applications/<system>/autonomy.json`.
2. Create an engine token per engine (above).
3. Give the engine's GitHub identity write access to the private run store repo (`CPLAT_RUNS_REPO`), plus issues and pull requests in the system's repos.
4. Install and run the engine itself. It is a separate project (ai-ops, per its own ADR-004) and not part of this repository.

## For engine authors

An engine reads one rendered file, `applications/<system>/autonomy.json`, from the gitops repo's `main` (at most every 5 minutes, together with that commit's SHA), never `system.yaml`. The file exists only when a system declares autonomy; a missing file means `observe` everywhere. It holds the defaults filled in, the effective level of each environment and instance, and the promotion rule, and equals the autonomy part of `cplat model show --json`. The engine then implements the signal and status endpoints, the issue format, and the fix run and audit event records. All of it is in [design.md](specs/124-autonomy-is-declared-per-environment-and/design.md) and [contract.openapi.yaml](specs/124-autonomy-is-declared-per-environment-and/contract.openapi.yaml).

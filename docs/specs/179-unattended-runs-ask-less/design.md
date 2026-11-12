# Design — 179 Unattended runs ask less

## Decisions

- **Instance settings are operations of the system plan's gitops entry**, not a separate gitops PR: the entry is the
  one gitops change `/system:ship` already builds, checks and lands before the component changes reach dev (in a joint
  run as the one dev PR, otherwise merged first; ship-entry.md). Two new operations, `replicas` and `resources`, join
  `resource`, `uses`, `expose` (which carries `host`) and `env`. "The task names the criterion" means the entry lists
  the criterion in its `acs` (AC-179.1). The entry gets `order: before-merge`, the only value `/system:ship` supports
  (A2).
- **`cplat component set` gets `--resources`**: A1 counts `resources` as a key `/component:set` accepts, but it had no
  flag for it; the renderer already reads a component's `resources:` mapping (render_v4), so the flag only writes that
  mapping. Without it a `resources` criterion could be planned but never applied.
- **Instance-scoped replicas never touch `prod`**: an operation with `instance: prod` is refused by the plan check,
  because prod changes go through its promotion (Non-goals).
- **`git rm` is one more rule of the run allowlist** with force removal on the refused list; git itself refuses
  untracked files and paths outside the repo (A3).
- **Type-only is a classification of `cplat spec test-diff`**, like `test helper` (spec 171): the build records it with
  `--tighten` and goes on. The comparison is the line comparison of A4, nothing more (Non-goals).
- **The pre-freeze review is the reviewer agent in test-review mode; the freeze point is a marker commit** written by a
  `cplat` command, so the red-tests unit cannot end without the review. ADR:
  [101](../../adr/101-acceptance-tests-are-reviewed-once-before-they-freeze.md).
- **Smoke findings are a separate reviewer line** (`SMOKE:`), handled by the tester in the existing verification fix
  round (A8); a finding on a frozen acceptance test stays `TEST LOOSER` (spec 165).
- **The platform preset is applied per event**: a run record carries the shape of the repo it ran in; the notifier
  turns `escalation` on `github` off and `desktop` on for events whose shape is `platform`, unless the user's
  `notify.yaml` sets that cell (A7). Auto-filing (ADR-033) is a different path and is not touched (AC-179.8).

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `templates/gitops-app/scripts/plan.py` | `replicas` and `resources` operations, entry `order`, the instance-setting check | changed |
| `scripts/cplat/compose.py` | `component set --resources` | changed |
| `scripts/cplat/appship.py` | `entry_ops` maps the two new operations | changed |
| `scripts/cplat/spec.py` | `provided_by_system` lists the new operations; `type_only` and its `test-diff` line | changed |
| `scripts/cplat/preflight.py` | `git rm` allowed, forced `git rm` refused | changed |
| `scripts/cplat/testreview.py` | the reviewed marker commit: write, find, read unresolved findings | new |
| `scripts/cplat/buildcmd.py` | dispatches `cplat component build reviewed` to `testreview` | changed |
| `scripts/cplat/units.py` | the red-tests unit needs the reviewed commit | changed |
| `scripts/cplat/runs_agents.py` | `cplat platform runs agent smoke` | changed |
| `scripts/cplat/runs_built.py` | PR block lists unresolved test-review findings and tightened smoke tests | changed |
| `scripts/cplat/runs.py`, `runlist.py`, `needs.py` | run record, run row and escalation item carry `shape` | changed |
| `scripts/cplat/notify_config.py`, `notify.py` | explicit cells, the platform escalation preset per event | changed |
| `plugins/component/commands/build.md`, `references/unit-mode.md`, `references/build-tighten.md` | the build flow | changed |
| `plugins/component/commands/set.md` | documents `--resources` | changed |
| `plugins/svc/agents/reviewer.md` | test-review mode, `SMOKE:` line, `TEST REVIEW` input | changed |
| `plugins/system/agents/planner.md`, `references/ship-entry.md` | instance settings become entry operations | changed |

## Contract

### 1. System plan: instance settings (AC-179.1, AC-179.2)

Two new operations in a gitops-app entry's `gitops:` list, and an optional entry key:

```yaml
repos:
  - id: shop-gitops
    shape: gitops-app
    order: before-merge                                        # optional; the only allowed value
    acs: [AC-200.3, AC-200.4]
    gitops:
      - {replicas: 2, component: shop-api, instance: staging}  # instance optional (dev | staging); no instance = the component
      - {resources: {requests: {cpu: 100m, memory: 256Mi}, limits: {memory: 512Mi}}, component: shop-api}
      - {expose: shop-web, host: shop}                         # host: unchanged operation
      - {env: {LOG_LEVEL: debug}, component: shop-api}         # env: unchanged operation
```

`plan.py validate` (added to `check_gitops` and `check_all`):

| Input | Result (ERROR line text after `repo <rid>: ` unless noted) |
|---|---|
| `replicas` not an int ≥ 1 | `gitops operation 'replicas' needs a whole number of at least 1` |
| `replicas` without `component` / unknown component | the existing `needs a component` / `unknown component '<c>'` messages |
| `instance` not `dev` or `staging` | `gitops operation 'replicas': instance must be dev or staging (prod changes go through its promotion)` |
| `resources` not a mapping, or a key other than `requests`/`limits` × `cpu`/`memory`, or a value not a quantity (`^\d+(\.\d+)?(m|k|M|G|T|Ki|Mi|Gi|Ti)?$`) | `gitops operation 'resources' takes requests/limits of cpu and memory as quantities (e.g. {requests: {cpu: 100m}})` |
| `order` present and not `before-merge` | `order must be before-merge (/system:ship applies the gitops entry before the components merge)` |
| instance-setting check (below) fails | no `repo` prefix: `AC-200.3 names the instance setting \`replicas\` but no gitops-app entry lists it in acs: add the operation to the gitops entry and AC-200.3 to its acs (spec 179)` |

The allowed list in the "unknown gitops operation" and "needs a `gitops:` list" messages names `replicas` and
`resources` too.

**Instance-setting check:** for every active criterion of the system spec, the setting keys found in its text as whole
words (`\b(replicas|host|resources|env)\b`, case-insensitive), in order of first appearance, deduplicated. A criterion
with at least one key needs a repo with `shape: gitops-app` whose `acs` contains it; otherwise one error per criterion,
the keys joined as `` `replicas`, `env` `` in the message above. The check reads the criterion text, so `spec_criteria`
returns the text with each id. Like the spec 045/053 findings, it is an error for `draft` and `in_progress` plans and a
warning for `completed` and `abandoned` ones (`late` list).

**`entry_ops` (appship.py)**, the commands `cplat system ship entry apply` runs:

| Operation | Command |
|---|---|
| `{replicas: N, component: C}` | `component set C --replicas N` |
| `{replicas: N, component: C, instance: E}` | `component set C --instance E --replicas N` |
| `{resources: {requests: {cpu: A, memory: B}, limits: {memory: D}}, component: C}` | `component set C --resources requests.cpu=A --resources requests.memory=B --resources limits.memory=D` (mapping order) |

**`cplat component set <c> --resources KEY=VALUE`** (repeatable; KEY one of `requests.cpu`, `requests.memory`,
`limits.cpu`, `limits.memory`; VALUE a quantity as above): merges into `components.<c>.resources.<a>.<b>` of
`system.yaml` and re-renders; other keys of the mapping stay. A bad key or value → `PlatformError` naming it, fix
`--resources requests.cpu=100m`. With `--instance` it is refused like every option but `--replicas` (existing rule).

**`spec.provided_by_system`** adds, for the slice's repo: `- replicas \`N\`` (with ` in \`E\`` for an instance) and
`- resources \`requests.cpu=A, limits.memory=D\``, so the component build relies on them and never asks for them.

**Planner (planner.md, step 4):** a criterion that states an instance setting becomes the matching operation of the
gitops entry, with the criterion in the entry's `acs` and `order: before-merge`; never a separate gitops PR or a
question, because the approved spec already decided it.

### 2. Run allowlist (AC-179.3)

`preflight.run_allowlist` adds `Bash(git rm *)` right after `Bash(git commit -s *)`, for every covered command.
`preflight.refused_rules` adds, after the push rules:
`Bash(git rm -f*)`, `Bash(git rm --force*)`, `Bash(git rm -rf*)`, `Bash(git rm -fr*)`, `Bash(git rm * -f*)`,
`Bash(git rm * --force*)`, `Bash(git rm * -rf*)`, `Bash(git rm * -fr*)`.
`git rm src/a.py`, `git rm -r src/old` and `git rm src/my-file.py` match no refused rule; `git rm -f a`, `git rm -rf d`,
`git rm -r -f d`, `git rm --force a` each match one. `_self_check` keeps passing. Removing a frozen acceptance test is
still `new or deleted file` in `cplat spec test-diff` (unchanged).

### 3. Type-only changes to frozen tests (AC-179.4)

`spec.type_only(old: str, new: str, name: str) -> tuple[bool, str]` is true when all hold:

1. the criterion ids are equal as a multiset (`AC_ANY`);
2. the test definitions are equal as a multiset: the full text of each `_TEST_DEFS` match, whitespace-trimmed (the
   match ends at the test's name, so annotations on its parameters may change);
3. no skip was added (`_SKIPS` count not higher);
4. the assertion lines are equal as a multiset, each whitespace-trimmed: every line matching `_ASSERTS`, plus the lines
   that continue it until its brackets `()[]{}` balance;
5. `old != new`.

Else false with the first failed rule (`criterion ids changed`, `test definitions changed`, `adds a skip`,
`assertion lines changed`, `unchanged`).

In `test_diff`, a refused file (not formatting, not a suppression, not approved, and not a test helper) for which
`type_only` holds gets the reason
`type-only (test definitions, assertion lines and criterion ids unchanged)`; the CLI prints
`<file>: changed — type-only (test definitions, assertion lines and criterion ids unchanged)` and exits 1, as it does
for a test helper. The build then runs, without asking:
`cplat spec test-diff $RED --tighten <file> --task <task> --reason '<why: e.g. type annotation the type check needs>'`;
a later `test-diff` reports the file `tightened by an agent: <reason>` and the PR block lists it as
`test tightened by an agent \`<file>\` (task <task>): <reason>` (existing `kind: tightened` path, AC-165.3).

The coder prompt in build.md allows exactly this change to a frozen test: a type annotation, cast or import the type
check needs, with no assertion line touched.

### 4. Review before the freeze (AC-179.5, AC-179.6)

**Phase 1 order** (build.md): tester (acceptance mode) → `cplat spec trace` → `cplat quiet test-fast` (new tests fail)
→ e2e check → `cplat platform runs agent tester …` → `TRACE` → **test review** → **at most one tester round** →
`cplat quiet lint-fix` + commit → **`cplat component build reviewed <id> …`** → `RED=$(git log -1 --format=%H --grep 'acceptance tests for')`.
Phase 1 is skipped when the reviewed commit exists; when only `cplat spec trace` passes, it starts at the test review.

**Reviewer, test-review mode** (prompt starts `**Test-review mode.**`). Inputs: the active criteria in full, the
design's contract verbatim (or `none`), `TRACE`. Reads the traced test files only; writes nothing. For each acceptance
test, checks at least: fixture or setup data that contradicts the test's own assertion; an asserted message, field or
status the contract does not define; an expected text the specified behaviour cannot produce. Reply:

```
TEST FINDINGS: <test file>::<test name> | <AC id> | <what contradicts, one line>   (one per line) | none
```

**Tester round** (only with findings; once): "**Acceptance mode.** Resolve only these test-review findings, changing
only the tests named: <findings>. Keep every test, criterion id and assertion that the finding does not name; add no
skip. Commit as `test(<number>): resolve test-review findings for <spec id>`. Reply `UNRESOLVED: <finding> — <why>`
per line, or `UNRESOLVED: none`." After it, `cplat spec trace <id>` must pass; if it does not, `git revert --no-edit HEAD`
and every finding counts as unresolved. The review is not run again.

**`cplat component build reviewed <spec> [--findings N] [--unresolved '<test> | <AC id> | <what>']...`** (module
`testreview`, dispatched from `buildcmd.main` like `tests`):

- Refuses (exit 1, `ERROR:` line with the fix) when tracked files have uncommitted changes (`commit the tests first`),
  when no commit with `acceptance tests for` naming the spec is on `merge-base(main, HEAD)..HEAD`, or when an
  `--unresolved` value does not have three non-empty `|`-separated parts or names an id that is not an active criterion
  of the spec.
- When a reviewed commit of the spec already exists in that range: prints `already reviewed at <short sha>`, exit 0,
  writes nothing.
- Otherwise commits with `core.git_identity` and `-s --allow-empty`:
  subject `test(<spec number>): reviewed acceptance tests for <spec id>`; body lines `findings: <N>` (default 0), then
  one `unresolved: <test> | <AC id> | <what>` per `--unresolved`, in the given order. Prints
  `REVIEWED <short sha>: <N> findings, <M> unresolved`, exit 0.

`testreview` API:

```python
REVIEWED_MSG = "reviewed acceptance tests for"
def reviewed_commit(repo: Path, spec_id: str, head: str = "HEAD") -> str | None   # newest such commit in merge-base(main|origin/main, head)..head
def unresolved(repo: Path, spec_id: str, head: str = "HEAD") -> list[dict]        # [{"test", "criterion", "what"}] from its body; [] without one
def commit(repo: Path, spec_ref: str, findings: int, unresolved: list[str]) -> str  # the sha; raises PlatformError on a refusal above
```

**Units (units.py):** the `red-tests` rule becomes: `cplat spec trace` passes **and** `testreview.reviewed_commit(repo,
spec_id, head)` is not None; else the reason `no commit 'reviewed acceptance tests for <spec id>' on feature/<spec id>
(the test review of build Phase 1)`. `next_step("red-tests", …)` names the review and `cplat component build reviewed`.
A unit already recorded `done` stays done (existing validity rule). The checkpoint is the feature head at the end of the
session, that is the reviewed commit, so `frozen_base` (spec 169) compares against it.

**Verification (Phase 4):** the reviewer gets `TEST REVIEW`: the `unresolved:` lines of
`git log -1 --format=%b --grep 'reviewed acceptance tests for'`, or `none`. With lines, `verification.md` gets
`## Unresolved test-review findings`: a table `| Test | Criterion | Finding |`, one row per line.

**PR block (runs_built.py):** under "Hand-backs and fix rounds", one line per unresolved finding of the run's spec,
read with `testreview.unresolved(repo, <spec id>)`: `test review left open: <test> (<AC id>): <what>`. A repo or spec
without the commit adds nothing.

### 5. Smoke-test findings (AC-179.9)

**Reviewer** (verification): a test that is not in `TRACE` (not a frozen acceptance test) and can pass without the
feature (for example a locator that also matches elements the feature does not render) is reported as

```
SMOKE: <test file> — <finding, one line>   (one per line) | none
```

It is not a `NOT MET` and does not make `RESULT: fail`. A test that is in `TRACE` and checks less than its criterion
stays `NOT MET … TEST LOOSER` (spec 165), a type-only issue stays section 3.

**Build (Phase 4 step 3):** each `SMOKE` item goes to the **tester** (`agents.tester`, normal mode) in the same round as
the coders' `NOT MET` fixes: "Tighten only `<file>` so that it fails without the feature: `<finding>`. Change no other
test." Then `cplat platform runs agent smoke <file> --finding '<finding>'` and run the test (`cplat quiet test-fast --
<file>`, or `cplat quiet e2e` for a file only e2e runs). A smoke test that then fails goes to the tester once more as
an ordinary fix round (A8). With `RESULT: pass` and only `SMOKE` items, no further reviewer cycle runs. The user is
never asked about a smoke finding.

**`cplat platform runs agent smoke <file> --finding <text>`**: adds an event `{"kind": "smoke", "test": <file>,
"finding": <text>}` to the tester's entry (metric `tester_events`); silent, always exit 0, like the other `agent`
subcommands. **PR block:** `smoke test tightened <file>: <finding>` under "Hand-backs and fix rounds".

### 6. Notifications of platform-repo runs (AC-179.7, AC-179.8)

- **Run record:** `runs.start(..., shape=None)` stores `"shape"` when known: the given value, else
  `spec.repo_shape(<git toplevel of the current directory>)`; any error → no key. Records without `shape` stay valid.
- **Run row** (`runlist.row`): `"shape"` = the record's, else `spec.repo_shape(repo_dir)` when the session's
  `repo_dir` exists; the key is present only when known.
- **Escalation item** (`needs._escalations`): `object.shape` = the row's `shape`, present only when known.
- **Event** (`notify.events_of`): an escalation event carries `"shape": object.shape` (or None).
- **Config** (`notify_config`): `Config.explicit: set[str]` holds `"<event>.<channel>"` for every cell the user's file
  sets under `events:`. New function:

```python
PLATFORM_ESCALATION = {"github": "off", "desktop": "instant"}
def cells_for(cfg: Config, event: str, shape: str | None) -> dict[str, str]:
    """cfg.events[event], with PLATFORM_ESCALATION applied to an `escalation` of a `platform` repo for every cell
    the user did not set."""
```

- **`notify.process`** sends each event on `cells_for(cfg, ev["event"], ev.get("shape"))` instead of
  `cfg.events[ev["event"]]`. Effect:

| Event | Shape | User's file | github | desktop |
|---|---|---|---|---|
| escalation (any cause) | `platform` | no `escalation.github` | off: no issue, no comment | instant |
| escalation | `platform` | `escalation: {github: instant}` | instant | as set / preset |
| escalation | any other or unknown | any | as today | as today |

- Auto-filing (`autoissue`, cause `platform` and internal crashes, AC-088.1, AC-088.4) is unchanged and independent of
  `notify.yaml` (AC-179.8).

## Data

No new persistent store. New committed artefact: the empty reviewed commit per build (section 4). New optional keys:
`shape` in run records and run rows, `object.shape` in escalation needs items, `order` in system plan gitops entries,
`resources` in a component's `system.yaml` entry (already read by the renderer).

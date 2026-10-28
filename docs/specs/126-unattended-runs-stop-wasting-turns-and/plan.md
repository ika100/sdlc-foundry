---
spec_id: 126-unattended-runs-stop-wasting-turns-and
shape: platform
spec_hash: 3a31d17b57f1
summary: "A pure stopgate module (owner = the session that started or resumed the run, progress = a new feature-branch commit or a phase change, two stops without progress escalate, cause by the AC-088.16 rule on the last message, else code on red tests or required checks, else decision) used by the component and product Stop hooks and cplat headless; one stdlib pr_rules module for the PR title rule, title fitting (72 characters and bytes) and the spec rule, run by the platform CI jobs, by a new devbox run ci step and by every PR-opening command; ship pr refuses before devbox run ci, adds --no-spec and retitles an open PR; ADR-070, docs, changelog, plugin bumps, and the post-release measurement"
tasks:
  - id: t1
    title: pr_rules.py (title rule, fit, spec rule) and the CI entry points check-pr-title.py / check-spec-required.py
    files: [scripts/cplat/pr_rules.py, scripts/check-pr-title.py, scripts/check-spec-required.py, .github/workflows/ci.yml]
    covers: [AC-126.11, AC-126.14]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t2
    title: stopgate.py — owner, progress check, verdict, last message, no-progress reason, cause rule
    files: [scripts/cplat/stopgate.py]
    covers: [AC-126.1, AC-126.2, AC-126.3, AC-126.4, AC-126.5, AC-126.6, AC-126.7]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t3
    title: plugin commands (ship, fix, build, system ship) and version bumps
    files: [plugins/component/commands/ship.md, plugins/component/commands/fix.md, plugins/component/commands/build.md, plugins/system/commands/ship.md, plugins/component/.claude-plugin/plugin.json, plugins/system/.claude-plugin/plugin.json, .claude-plugin/marketplace.json]
    covers: [AC-126.5, AC-126.10]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t4
    title: docs — AGENTS.md, unattended-delivery.md, ADR index and ADR-028 note, changelog, measurements.md for AC-126.15
    files: [docs/AGENTS.md, docs/unattended-delivery.md, docs/adr/README.md, docs/adr/028-unattended-delivery-without-branch-protection.md, docs/CHANGELOG.md, docs/specs/126-unattended-runs-stop-wasting-turns-and/measurements.md]
    covers: [AC-126.15]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t5
    title: check-pr-local.py and its step in scripts/ci-local.sh (devbox run ci)
    files: [scripts/check-pr-local.py, scripts/ci-local.sh]
    covers: [AC-126.13, AC-126.14]
    parallel_safe: true
    depends_on: [t1]
    done: true
  - id: t6
    title: component ship Stop hook — owner on start/resume, gate on stopgate, session in status, code-red evidence
    files: [scripts/cplat/ship.py, tests/cplat/test_ship.py, tests/cplat/test_autoissue_ship.py, tests/cplat/test_ship_escalate_rules.py, tests/cplat/test_runs.py]
    covers: [AC-126.1, AC-126.2, AC-126.3, AC-126.4, AC-126.5, AC-126.6, AC-126.7]
    parallel_safe: true
    depends_on: [t2]
    done: true
  - id: t7
    title: product ship Stop hook and owner (appship_state), built titles in appship
    files: [scripts/cplat/appship_state.py, scripts/cplat/appship.py, tests/cplat/test_appship_097.py]
    covers: [AC-126.8, AC-126.11]
    parallel_safe: true
    depends_on: [t1, t2]
    done: true
  - id: t8
    title: built PR titles through pr_rules.fit — spec draft PRs, gitops, resource upgrade, cluster repo, platform update
    files: [scripts/cplat/spec_pr.py, scripts/cplat/gitops.py, scripts/cplat/upgrade.py, scripts/cplat/clusterrepo.py, scripts/cplat/fleet_pr.py]
    covers: [AC-126.11]
    parallel_safe: true
    depends_on: [t1]
    done: true
  - id: t9
    title: cplat pr open — title rule, spec rule in the platform repo, --no-spec
    files: [scripts/cplat/pr_open.py, scripts/cplat/pr.py]
    covers: [AC-126.9, AC-126.10, AC-126.11]
    parallel_safe: true
    depends_on: [t1]
    done: true
  - id: t10
    title: cplat component ship pr — spec rule before devbox run ci, --no-spec, retitle an open PR, PR env for devbox run ci
    files: [scripts/cplat/ship.py, tests/cplat/test_ship.py, tests/cplat/test_platform_shape_123.py]
    covers: [AC-126.9, AC-126.10, AC-126.11, AC-126.12, AC-126.13]
    parallel_safe: true
    depends_on: [t1, t6]
    done: true
  - id: t11
    title: cplat headless — CPLAT_SESSION_ID, progress key without owner/stop_gate, no-progress cause by the rule
    files: [scripts/cplat/headless.py, tests/cplat/test_headless.py]
    covers: [AC-126.2, AC-126.7]
    parallel_safe: true
    depends_on: [t2, t6]
    done: true
human_steps:
  - "AC-126.15, seven days after the release that ships spec 126: run the commands in docs/specs/126-unattended-runs-stop-wasting-turns-and/measurements.md (cplat platform runs report --since 7 and the gh query for red pr-title / spec-required checks on PRs opened by platform commands), fill its table, and open an issue for any line that fails."
  - "After updating the plugins: resume each ship run that was open before the update once (/component:ship <spec> or /system:ship <spec>); until then the Stop hook only prints a notice for it and holds no session (AC-126.3)."
---

# Plan — 126 Unattended runs stop wasting turns and CI rounds

Design: [design.md](design.md) is the contract every task and test follows. ADR:
[ADR-070](../../adr/070-the-stop-hook-holds-only-the-owning-session-until-it-stops-progressing.md) is written with this plan. t4
indexes it in `docs/adr/README.md` and points ADR-028 to it.

Levels: t1, t2, t3, t4 → t5, t6, t7, t8, t9 → t10, t11. Each hot file has one owner per level. `scripts/cplat/ship.py` belongs to t6
(stop hook) and then t10 (PR). `.github/workflows/ci.yml` belongs to t1, `.claude-plugin/marketplace.json` to t3 and
`docs/CHANGELOG.md` to t4.

The testers write the acceptance tests first, in `tests/cplat/test_stopgate_126.py`, `test_ship_gate_126.py`,
`test_appship_gate_126.py`, `test_headless_126.py`, `test_pr_rules_126.py` and `test_ship_pr_126.py`, one criterion id per test. They
fake `gh` with PATH stubs and drive the gates with hook JSON that carries `session_id`, `transcript_path` and
`last_assistant_message`. AC-126.14 is one table of sample titles and bodies (valid, invalid, subject of 72 and 73 characters, a
multibyte subject, with and without `no-spec`, closing and not closing an issue, with and without a spec in the diff). It runs through
`scripts/check-pr-title.py` and `scripts/check-spec-required.py` exactly as the CI jobs call them, through `scripts/check-pr-local.py`
with handed values, and through `pr_rules`. All of them must give the same verdict. A static test asserts that the `pr-title` job runs
`python3 scripts/check-pr-title.py`.

Existing tests that encode the replaced behaviour (8 blocked stops, `gate(repo, {}, n)`, the `environment` cause) are updated by the
task that changes the code they test. Those files are listed in that task's `files`.

## t1 — pr_rules.py and the CI entry points

**Files:** scripts/cplat/pr_rules.py, scripts/check-pr-title.py, scripts/check-spec-required.py, .github/workflows/ci.yml
**Covers:** AC-126.11, AC-126.14
**Goal:** One standard-library module holds the PR title rule, title fitting and the spec rule, and the platform CI jobs run it.

**Implementation notes:**
- `pr_rules.py` exactly as in design § `pr_rules.py`. Standard library only: no `core`, no `yaml`. The two check scripts load it by file
  path.
- `title_error` returns the three lines of the old shell job, without `ERROR: `. `fit` follows the cut rule of the design (72 characters
  and 72 UTF-8 bytes, `...` suffix, trailing ` -—–:;,.` stripped before the suffix). It raises `ValueError` on a prefix that is not a
  type (a programming error of the caller).
- `check-spec-required.py`: the docstring and `main()` stay. `CLOSES`, `CODE` and `verdict` come from `pr_rules` (`verdict =
  pr_rules.spec_error`), so `tests/cplat/test_claims.py` keeps working unchanged.
- `check-pr-title.py`: reads `PR_TITLE` and prints `ERROR: <lines>` with exit 1, or `OK: PR title is valid.` with exit 0.
- `ci.yml` `pr-title` job: keep its `name`, `if` and `runs-on`. Add the checkout step (same pinned SHA as `spec-required`, no fetch
  depth needed) and run `python3 scripts/check-pr-title.py` with the `PR_TITLE` env. `scripts/pin-actions.py --check` must stay green.

**Done when:** the AC-126.14 table and the AC-126.11 `fit` tests pass (every fitted title passes `title_error`, the spec draft example
over 72 characters gets a valid title, and short titles come back unchanged). `tests/cplat/test_claims.py` and `test_workflows.py` are
green.

## t2 — stopgate.py

**Files:** scripts/cplat/stopgate.py
**Covers:** AC-126.1 to AC-126.7
**Goal:** One pure module decides every stop of an owned run and the cause of a no-progress escalation.

**Implementation notes:**
- Exactly the contract of design § `stopgate.py`: `session_of_env`, `claim`, `Verdict`, `check`, `last_message`, `excerpt`,
  `no_progress_reason`, `cause`, `NO_PROGRESS_LIMIT = 2`, `EXCERPT = 200`.
- `check` writes nothing to `st` for `silent` and `notice`.
- `last_message` reads the transcript JSONL from the end. It takes the last line with `"type": "assistant"` whose `message.content`
  has a `text` block, and joins that entry's text blocks. Any error returns `""`.
- `excerpt` uses `feedback.redact`. `cause` uses `escalation_rules.classify`. Import nothing from `ship` or `appship_state`.

**Done when:** the stopgate unit tests pass. They cover owner, non-owner, no owner, the first stop after `claim`, progress by head, by
phase, none, the count reaching 2, the reason text with and without a message, redaction and the 200-character cut, and the cause
order (a rule match beats code-red, code-red beats decision, never `platform` or `unknown`).

## t3 — plugin commands and versions

**Files:** plugins/component/commands/ship.md, plugins/component/commands/fix.md, plugins/component/commands/build.md, plugins/system/commands/ship.md, plugins/component/.claude-plugin/plugin.json, plugins/system/.claude-plugin/plugin.json, .claude-plugin/marketplace.json
**Covers:** AC-126.5, AC-126.10
**Goal:** The coordinators know the new stop rule and the `--no-spec` choice.

**Implementation notes:**
- `component/commands/ship.md` and `system/commands/ship.md`: the Stop hook holds only the session that started or resumed the run. A
  stop without a new commit or a phase change counts. After two such stops the run escalates by itself, so commit each finished task.
  `cplat component ship pr … --no-spec` is for a platform-repo PR that closes an issue with a one-line fix or docs only.
- `fix.md` and `build.md`: next to the `cplat pr open` line, `--no-spec` (platform repo only, same meaning), and that the title is
  checked before anything is pushed.
- Bump `component` by a minor version and `system` by a patch version from the values in the files at build time, in `plugin.json`
  and `marketplace.json` alike.

**Done when:** `devbox run validate` and the version-match loop of `devbox run quality` pass, and `scripts/shapes.py check` is clean.

## t4 — docs, changelog, measurement sheet

**Files:** docs/AGENTS.md, docs/unattended-delivery.md, docs/adr/README.md, docs/adr/028-unattended-delivery-without-branch-protection.md, docs/CHANGELOG.md, docs/specs/126-unattended-runs-stop-wasting-turns-and/measurements.md
**Covers:** AC-126.15
**Goal:** The documentation states the new stop rule and the local PR checks, and the post-release measurement is ready to run.

**Implementation notes:**
- `AGENTS.md` § Stop hook and `unattended-delivery.md`: replace "after 8 blocked stops" with the owner, progress and two-stop rule and
  the cause rule. Link ADR-070.
- `docs/adr/README.md`: the row for ADR-070 after 069. Add one line to ADR-028's header: `**Amended by:** ADR-070 (the 8-stop limit)`.
- `CHANGELOG.md` `[Unreleased]`: a paragraph **Unattended runs stop wasting turns and CI rounds** (spec 126, ADR-070). It names the
  owner rule, two stops without progress, the new causes, `--no-spec`, the local `pr-title`/`spec-required` step in `devbox run ci`,
  and the shortened built titles. Add the plugin versions from t3 to the **Plugins** line. Action: resume runs that were open before
  the update once. Not breaking.
- `measurements.md`: the AC-126.15 checks as commands with an empty result table, in the style of spec 112's measurements. The checks:
  `cplat platform runs report --since 7` (no escalation reason containing `gave up after`; no escalation from a non-owning session;
  stop-gate and headless `no progress` escalations with cause `environment` only together with a matched rule), and a `gh pr list` /
  `gh pr checks` query for PRs opened by platform commands in the platform repo with a red `pr-title` or `spec-required`.

**Done when:** `python3 scripts/check-links.py` and `scripts/shapes.py check` (ADR index) pass, and the AC-126.15 doc test passes:
`measurements.md` exists with the report command and the four checks.

## t5 — check-pr-local.py in devbox run ci

**Files:** scripts/check-pr-local.py, scripts/ci-local.sh
**Covers:** AC-126.13, AC-126.14
**Goal:** `devbox run ci` in the platform repo fails on a PR title or spec rule that the CI jobs would fail, before any push.

**Implementation notes:**
- Exactly design § `scripts/check-pr-local.py`: handed `PR_TITLE`/`PR_BODY`/`PR_LABELS` first, else `gh pr view` of the current
  branch (state `OPEN` only), else the two `skipped (no pull request yet)` lines and exit 0. A missing `gh` or a `gh` error also
  skips. Use a 30 s timeout per `gh` call.
- Load `pr_rules.py` by file path, as t1's scripts do. The output is the CI output lines, prefixed `pr-title: ` and `spec-required: `.
- `ci-local.sh`: a `step "pull request title and spec rule (spec 126)"` right after the manifest step, running
  `python3 scripts/check-pr-local.py`.

**Done when:** the AC-126.13 tests pass with a stubbed `gh` (open PR with a bad title, a missing spec, `no-spec`, no PR, handed values),
and the `check-pr-local.py` column of the AC-126.14 table agrees with the CI entry points.

## t6 — component ship Stop hook

**Files:** scripts/cplat/ship.py, tests/cplat/test_ship.py, tests/cplat/test_autoissue_ship.py, tests/cplat/test_ship_escalate_rules.py, tests/cplat/test_runs.py
**Covers:** AC-126.1 to AC-126.7
**Goal:** `cplat component ship gate` holds only the owner, while it makes progress, and escalates with the rule's cause.

**Implementation notes:**
- `start`: `stopgate.claim(st, stopgate.session_of_env())` on a new run and on every resume, before `save_state`.
- `gate(repo, hook_input, run_tests=True)`: remove `max_blocks`, `DEFAULT_MAX_BLOCKS` and `--max-blocks`. The mark is
  `{"head": <git rev-parse --verify -q refs/heads/<branch> or None>, "phase": st["phase"]}`. Answers exactly as the design table.
  `silent` returns `None` without saving. `notice` returns the systemMessage without saving.
- Block reason: first line `The ship run of <spec> is not finished (phase <phase>, stops without progress: <n>/2).`, then the existing
  next step, build status and escalate lines.
- Escalation: `no_progress_cause(repo, st, message, run_tests)` (new, design § Code-red evidence), save the `stop_gate` first, then
  `escalate(repo, stopgate.no_progress_reason(phase, message), cause)` with stdout and stderr captured. Return the systemMessage.
- `build_status` keeps its lines. Add a red flag for the cause: a small `build_red(repo, spec) -> tuple[list[str], bool]`, reused by
  `build_status`. `required_red(repo, pr) -> bool` via `gh pr checks --required`.
- Remove the `blocks` writes in `set_phase`, `open_pr` and `_done`. Only `open_pr`'s single line changes there; t10 owns the rest of
  `open_pr`.
- `describe`: the `session:` line of the design.
- Update the existing gate tests in the listed files to the new contract (hook input with `session_id`, a claimed owner, two stops
  without progress instead of N blocks, the cause `decision` or `code` instead of `environment`).

**Done when:** the AC-126.1 to AC-126.7 ship gate tests pass (non-owner silent with the state unchanged, takeover on resume, no-owner
notice, `0/2` after progress, `1/2` then an escalation with the reason and excerpt, no escalation while every stop progresses, the cause
order with a matched rule, red test-fast and a red required check, and `cause_source` `given` on the run record), and the updated
existing tests are green.

## t7 — product ship Stop hook and titles

**Files:** scripts/cplat/appship_state.py, scripts/cplat/appship.py, tests/cplat/test_appship_097.py
**Covers:** AC-126.8, AC-126.11
**Goal:** `/system:ship` follows the same stop rules, and the titles it builds are valid.

**Implementation notes:**
- `appship_state.start`: `stopgate.claim` on a new run and on a resume (inside the locked save).
- `appship_state.gate(repo, hook_input)`: the mark is `{"head": git rev-parse HEAD, "phase": st["phase"] + " " + json.dumps(<sorted
  repo id → state>)}`. The answers follow the design with `product ship`, `/system:ship` and `The product ship of <spec> …`. Write
  `stop_gate` through `update()` (the lock), and only for the owner.
- Product code-red: `gh pr view --json url,state` on the current branch, then `gh pr checks <url> --required --json bucket`.
  Escalate through `escalate(repo, reason, stopgate.cause(message, red))` with stderr captured, as today.
- Remove `DEFAULT_MAX_BLOCKS`, the `blocks` writes and `--max-blocks` in `appship.py`'s `gate` parser.
- `describe`: the `session:` line with `/system:ship`.
- `appship.py`: `open_pr` applies `pr_rules.fit` to its title. `publish` and the completion use the fitted title for the commit subject
  too. `entry_pr` keeps `ship.check_title`.
- `test_appship_097.py`: update `test_the_stop_hook_gives_up_after_max_blocks` to the two-stop rule.

**Done when:** the AC-126.8 product gate tests pass (the same cases as t6, plus a repo-state change counting as progress) and the
appship title tests of AC-126.11 pass (a long spec id still gives a valid publish title). `test_appship_097.py` is green.

## t8 — built titles through fit

**Files:** scripts/cplat/spec_pr.py, scripts/cplat/gitops.py, scripts/cplat/upgrade.py, scripts/cplat/clusterrepo.py, scripts/cplat/fleet_pr.py
**Covers:** AC-126.11
**Goal:** Every PR title a platform command builds itself satisfies the rule.

**Implementation notes:**
- `spec_pr.py`: `title = pr_rules.fit(f"docs(spec): {spec.id} — {title}")`, used for the commit and the draft PR.
- `gitops.open_pr`, `upgrade.open_pr` and `clusterrepo._pr`: fit the title on entry and use it for the commit and `gh pr create`.
- `fleet_pr.py`: fit the `chore: platform update …` title for both `pr create` and `pr edit`.
- Callers keep building titles as they do. Only the openers fit them.

**Done when:** the AC-126.11 opener tests pass. With a stubbed `gh`, each opener sends a title that passes `title_error`, and the spec
draft PR of an id and title over 72 characters gets a valid title. The existing tests of these modules are green.

## t9 — cplat pr open

**Files:** scripts/cplat/pr_open.py, scripts/cplat/pr.py
**Covers:** AC-126.9, AC-126.10, AC-126.11
**Goal:** The finishing command of quick-task and fix-bug refuses a bad title and, in the platform repo, a missing spec before anything
changes.

**Implementation notes:**
- Replace `TITLE` with `pr_rules.title_error`: a `Refused` that carries the rule's message.
- The platform repo is `settings.declared_shape(repo) == "platform"`. Resolve `{{CLOSES}}` in memory first, without writing the body
  file. Then check `pr_rules.spec_error(body, labels, files)`, where labels are `[no-spec]` with `--no-spec`, and files are
  `<base_ref>...HEAD` plus the paths of `git status --porcelain`. Only then write the body, commit and push.
- `Opts.no_spec`. `create` gets `--label no-spec` when it is set (also in the `ready` command). Outside the platform repo `--no-spec`
  is ignored with a note in `Result.lines()`.
- `pr.py`: `--no-spec` on `open`.

**Done when:** the AC-126.9, AC-126.10 and AC-126.11 `pr open` tests pass (refusal exit 2 with the job's message and an untouched
tree, the label on create, a refused title naming the rule), and the existing `pr open` tests are green.

## t10 — cplat component ship pr

**Files:** scripts/cplat/ship.py, tests/cplat/test_ship.py, tests/cplat/test_platform_shape_123.py
**Covers:** AC-126.9, AC-126.10, AC-126.11, AC-126.12, AC-126.13
**Goal:** `ship pr` refuses a missing spec before `devbox run ci`, opens the PR with `no-spec` when asked, retitles an open PR, and hands
the PR to `devbox run ci`.

**Implementation notes:**
- `check_title` delegates to `pr_rules.title_error` (`appship` keeps calling it). `gitops_pr` uses it unchanged.
- `open_pr(repo, title, body_file, no_spec=False)` follows design § `cplat component ship pr` steps 1 to 6. Platform repo:
  `st.get("shape") == "platform"` or `settings.declared_shape(repo) == "platform"`.
- `run_ci(repo, env=None)` passes `PR_TITLE`, `PR_BODY` and `PR_LABELS`.
- Retitle with `gh pr edit <url> --title <title>` only when the open PR's title differs. Add the label only when it is missing.
- CLI: `pr --no-spec`, and the module docstring line.
- Update the `gh` fakes in the listed tests if they only break on the new `--json number,url,title,labels` call.

**Done when:** the AC-126.9 (refused before `devbox run ci` and the push, phase unchanged), AC-126.10 (label on create and on an open PR),
AC-126.11 (refused title naming the rule), AC-126.12 (retitle) and AC-126.13 (env handed to `devbox run ci`) tests pass. The existing
ship tests are green.

## t11 — cplat headless

**Files:** scripts/cplat/headless.py, tests/cplat/test_headless.py
**Covers:** AC-126.2, AC-126.7
**Goal:** Headless sessions own the runs they resume, and a headless no-progress stop gets the rule's cause.

**Implementation notes:**
- `run_once`: env `CPLAT_SESSION_ID=<sid>`. `run_once` gets the session id passed in, or reads it from `--session-id` in `cmd`.
- `progress_key` also ignores `owner` and `stop_gate`.
- The last message is the log text written after this session's `===` header: note the log size before the session, read from there
  after it.
- No progress: the reason gets `; last message: <stopgate.excerpt(msg)>` when the message is not empty. The cause is
  `ship.no_progress_cause(repo, st, msg)`, passed to `ship.escalate` and kept in `state` for the run record. The `finally` block uses
  that cause instead of `environment`.
- `test_headless.py`: adjust the existing no-progress test to the new cause if it asserts one.

**Done when:** the AC-126.2 headless test (each session exports its id, and the run's owner is the latest session) and the AC-126.7
headless tests pass (two sessions without change: `decision`, `code` with a red required check, the rule's cause with a matching last
message, the headless run record with the same cause and never `environment` by default). `test_headless.py` is green.

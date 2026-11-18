---
spec_id: 207-preflight-checks-trust-and-subagent
shape: platform
spec_hash: 2014a9debcb1
summary: The unattended preflight also checks folder trust, subagent shell permissions and definitions, the agent worktree location and the models, and retries a gh login that fails for a moment
tasks:
  - id: t1
    title: Add preflight_trust (trust record, committed settings, plugin locations, AC-207.1 check)
    files: [scripts/cplat/preflight_trust.py]
    covers: [AC-207.1]
    parallel_safe: true
    depends_on: []
  - id: t4
    title: Retry a gh login that reports not logged in (15 s, 30 s) before failing gh-auth
    files: [scripts/cplat/preflight.py, tests/cplat/conftest.py, tests/cplat/test_preflight_131.py]
    covers: [AC-207.7]
    parallel_safe: true
    depends_on: []
  - id: t7
    title: Document the new preflight categories and add the changelog fragment
    files: [docs/unattended-delivery.md, docs/changelog.d/207-preflight-checks-trust-and-subagent.added.md]
    covers: [AC-207.8]
    parallel_safe: true
    depends_on: []
  - id: t2
    title: Add preflight_agents (agents per command, winning definition, Bash grant, model exclusion)
    files: [scripts/cplat/preflight_agents.py]
    covers: [AC-207.3, AC-207.5]
    parallel_safe: true
    depends_on: [t1]
  - id: t3
    title: Add preflight_probe (agent worktree probe, cached model check call, preflight log section)
    files: [scripts/cplat/preflight_probe.py]
    covers: [AC-207.4, AC-207.6]
    parallel_safe: true
    depends_on: [t1]
  - id: t5
    title: Add preflight_rules (effective permission layers and the coder command sample)
    files: [scripts/cplat/preflight_rules.py]
    covers: [AC-207.2]
    parallel_safe: true
    depends_on: [t1, t2]
  - id: t6
    title: Run the new checks in order from preflight.check, check_repo and headless
    files: [scripts/cplat/preflight.py, scripts/cplat/headless.py, tests/cplat/conftest.py, tests/cplat/units131_support.py, tests/cplat/seam178_world.py, tests/cplat/dispatch_world.py]
    covers: [AC-207.1, AC-207.2, AC-207.3, AC-207.4, AC-207.5, AC-207.6, AC-207.8]
    parallel_safe: false
    depends_on: [t2, t3, t4, t5]
---

# Plan — 207 Preflight checks trust and subagent tools before a ship

[design.md](design.md) holds the contract: line texts, order, interfaces and algorithms. The change touches no agent or
command prompt, template or plugin file. So, as in spec 206, there is no plugin version bump and no rules-register
entry. Levels: t1, t4, t7 → t2, t3 → t5 → t6.

## t1 — Add preflight_trust (trust record, committed settings, plugin locations, AC-207.1 check)

**Files:** scripts/cplat/preflight_trust.py
**Covers:** AC-207.1
**Goal:** a read-only module that can tell whether a folder is trusted, and whether everything trust would give a run
reaches it anyway.

**Implementation notes:**
- `config_file()`, `plugins_dir()`: as in design (`CLAUDE_CONFIG_DIR` first). They are module functions, so the tests
  replace them.
- `trusted(folder)`: load `config_file()` as JSON, read-only. Walk `folder.resolve()` and its parents, and return True
  at the first `projects[str(p)]["hasTrustDialogAccepted"] is True`. A missing or invalid file is `False`. Never open the
  file for writing.
- `committed_settings(repo)`: `git show HEAD:.claude/settings.json`, parsed, `{}` on any error (the same source as
  `headless.repo_rules`).
- `installed_plugins()`: `plugins_dir()/installed_plugins.json`. Accept version 2 (`{"plugins": {key: [{"installPath":
  ...}]}}`) and a flat `{key: {"installPath": ...}}`, and return `{key: [Path]}` for install paths that exist.
- `plugin_dir_names(dirs)`: `name` from each `<dir>/.claude-plugin/plugin.json`.
- `check(folder, plugin_dirs)`: return `(None, None)` when trusted. Otherwise check in this order: a non-empty `env`
  mapping, a non-empty `permissions.additionalDirectories`, and each `enabledPlugins` key whose value is true and that
  is neither in `installed_plugins()` nor has its name part in `plugin_dir_names`. Return the first failure detail
  exactly as the design's table gives it (env keys sorted). With no failure, return the pass line
  `preflight: <folder> is not trusted; its permission rules are passed to the session`.
- Stdlib and `core.run` only, and no import of `preflight`.

**Done when:** the unit-level acceptance tests of AC-207.1 pass: trusted, trusted through a parent, untrusted with
installed plugins, untrusted with plugins passed through `--plugin-dir`, and each failure case. A test that compares the
file's bytes and mtime before and after shows that `config_file()` is never written.

## t4 — Retry a gh login that reports not logged in (15 s, 30 s) before failing gh-auth

**Files:** scripts/cplat/preflight.py, tests/cplat/conftest.py, tests/cplat/test_preflight_131.py
**Covers:** AC-207.7
**Goal:** a gh login that fails only for a moment, for example while the macOS keychain is locked, no longer escalates
a run.

**Implementation notes:**
- Add `sleep(seconds)` (calls `time.sleep`, and the tests replace it) and `GH_LOGIN_WAITS = (15, 30)` to `preflight.py`.
- Rewrite `_auth` as in the design's pseudocode. A network error returns today's network detail at once (A5). The pass
  line is printed with `flush=True`.
- The final detail is `gh is not logged in for <host> (3 tries over 45 s): gh auth login --hostname <host>`. On Darwin,
  append `; if gh is logged in, unlock the login keychain`.
- `tests/cplat/conftest.py`: add an autouse fixture `no_real_preflight_waits` that replaces `preflight.sleep` with a
  no-op. The docstring says that spec 207's own tests record the waits themselves.
- `tests/cplat/test_preflight_131.py`, the `gh-auth` line test: expect the new detail, with the macOS suffix when
  `platform.system() == "Darwin"`. The comment says that spec 207 (AC-207.7) changed the text on purpose.

**Done when:** the acceptance tests of AC-207.7 pass: pass on try 2, pass on try 3, three failures with waits of
exactly `[15, 30]`, and no "not logged in" retry for an offline error. `test_preflight_131.py`, `test_headless_131.py`,
`test_206_deny_rules.py` and `test_appship_131.py` stay green with no real sleep (the spec-185 guard).

## t7 — Document the new preflight categories and add the changelog fragment

**Files:** docs/unattended-delivery.md, docs/changelog.d/207-preflight-checks-trust-and-subagent.added.md
**Covers:** AC-207.8
**Goal:** a person whose run stops on a new category finds the cause and the fix.

**Implementation notes:**
- `docs/unattended-delivery.md`, the category table: add rows for `untrusted-folder`, `subagent-tools`, `agent-worktree`
  and `model-unreachable`, each with the fix from the design. Extend the `gh-auth` row: the login is tried three times
  over 45 s, and on macOS a locked keychain is a possible cause.
- Below the table, add one paragraph:
  - the order of the checks, and that a model check call happens only when every other check passed;
  - the check call is not counted in the budget, is cached for an hour, and its tokens are under `preflight` in the
    run's log;
  - cplat never accepts a trust dialog itself.
  - Do not use spec numbers in the guide.
- Write the fragment in the style of `206-deny-rules-checked-before-a-run.fixed.md`:
  - a bold summary sentence ending in `(spec 207).`;
  - then the week-46 stops it catches (subagents without the shell, unreachable reviewer models, untrusted folders,
    the momentary gh login), and that combined shell commands blocked by the worktree guard are out of scope.

**Done when:** `devbox run quality` (link check, `check-docs.py`) passes.

## t2 — Add preflight_agents (agents per command, winning definition, Bash grant, model exclusion)

**Files:** scripts/cplat/preflight_agents.py
**Covers:** AC-207.3, AC-207.5
**Goal:** cplat knows which definition each agent of a run resolves to, whether it may use the shell, and which model it
runs on, and refuses a model the settings exclude without calling it.

**Implementation notes:**
- `roles(folder, command)`: the design's role table from `shapecmd.route(folder)["agents"]`. Return `[]` for a folder
  whose route carries `unsupported` (gitops-app, cluster-gitops). Use the svc/shared fallback when `route` raises
  `PlatformError`.
- `resolve(folder, role, type_, plugin_dirs)`: the five-step lookup of the design. Read the front matter with
  `yaml.safe_load` (already a cplat dependency), and accept `tools` both as a comma-separated string and as a list.
- `bash` follows the design: no `tools` means every tool, an item `Bash` or `Bash(…)` grants it, and `disallowedTools`
  revokes it.
- `model`: `None` for `inherit` or a missing model. `CLAUDE_CODE_SUBAGENT_MODEL` replaces it when set.
- `check_definitions(agents)`: the first agent with `bash == False` gives the AC-207.3 detail of the design's table.
- `models(agents_by_folder, coordinator)`: return `{model: [roles]}` with `coordinator` first. An agent with
  `model is None` adds its role to the coordinator's model. Skip a `None` coordinator (`check_repo`).
- `check_models(models, repo)`: alias matching as in the design. Check the managed layer, then the user layer, through
  `preflight.layers(repo)`, imported inside the function to avoid an import cycle at load time. Use the details of the
  table.
- Stdlib, `yaml`, `core`, `shapecmd` and `preflight_trust` only.

**Done when:** the acceptance tests of AC-207.3 (repo override without Bash fails, plugin-dir and installed definitions
win in order, missing `tools` passes) and AC-207.5 (availableModels without the model, deniedModels with it, alias
against full id, no model call made) pass.

## t3 — Add preflight_probe (agent worktree probe, cached model check call, preflight log section)

**Files:** scripts/cplat/preflight_probe.py
**Covers:** AC-207.4, AC-207.6
**Goal:** before a run, cplat proves that an agent worktree can be created where the session may work. It also proves
that each model answers with this machine's credentials, at most once per model per hour.

**Implementation notes:**
- `worktree_location(repo)` and `check_worktree(repo, add_dirs)`: follow the design's pseudocode exactly. Use
  `--detach`, so no branch is created. Always remove in `finally`, and remove `.claude/worktrees` only if the probe
  created it. Run git through `core.run(..., check=False)`.
- `model_call(model)`: argv, cwd, env and timeout as in the design. Parse the JSON usage
  (`usage.input_tokens`, `usage.output_tokens`, `usage.cache_read_input_tokens`, `usage.cache_creation_input_tokens`,
  `total_cost_usd`), with zeros when they are absent. A missing executable gives an `ok=False` result with the error
  `` `claude` is not installed or not on PATH ``. Set `REAL_MODEL_CALL = model_call` at module end.
- `check_models(models, run_id)`: for each model in insertion order, skip it when the cache holds a fresh entry for it.
  Otherwise call it (looked up as a module global at call time) and retry offline results as in the design through
  `core.sleep` and `core.NETWORK_RETRY_MAX_WAIT`. On a pass, write the cache. On a failure, return the design's detail.
  Either way, write the `preflight` section through `runs.set_section` before returning, with each model checked so far.
- The cache fingerprint reads `oauthAccount.accountUuid` through `preflight_trust.config_file()`. Write the cache with
  a temporary file and `os.replace`.
- Never write any settings file or the Claude config.

**Done when:** the acceptance tests of AC-207.4 pass, including worktree list, branches and `git status` identical before
and after, a failing `git worktree add`, and a symlinked location outside the repo. The acceptance tests of AC-207.6
pass: one call per distinct model, cache hit within 60 min, a new call after 60 min or with other credentials, an auth
failure, offline retry then the network detail, and tokens under `preflight` in the run record.

## t5 — Add preflight_rules (effective permission layers and the coder command sample)

**Files:** scripts/cplat/preflight_rules.py
**Covers:** AC-207.2
**Goal:** a run whose coders would be refused `git add`, `git commit`, the reset or the plan's devbox scripts in their
worktree stops before it starts, naming the rule to add or remove.

**Implementation notes:**
- `coder_commands(folder, specs)`: build the sample as in the design. Get the scripts with
  `re.findall(r"devbox run ([A-Za-z0-9][\w:.-]*)", text)` over the committed `plan.md` at `units.feature_head`, read
  the same way as `envprefix._show`.
- Allow layers: managed and user (`preflight.layers`, imported inside the function),
  `preflight_trust.committed_settings(folder)`, local only when `preflight_trust.trusted(folder)`, and the run
  allowlist. Deny and ask layers: managed, user, project, local, then `run_deny` as layer `run`.
- Check in the design's order: whole shell, agent deny (`Agent`/`Task`, bare or with the role or type), then for each
  command a deny or ask rule through `denyrules.refuses`, then a missing allow rule through `preflight.matches`.
- Use the details of the design's table. In the missing-allow fix, the `*` pattern is the one the design gives per
  command.

**Done when:** the acceptance tests of AC-207.2 pass for these cases:
- a deny rule in each layer;
- an ask rule;
- a refused rule;
- `Bash` denied;
- `Agent(svc:coder)` denied;
- a missing `devbox run <script>` allow rule;
- a plan with no devbox script (falls back to `devbox run test`);
- local allow rules that count only in a trusted folder.

## t6 — Run the new checks in order from preflight.check, check_repo and headless

**Files:** scripts/cplat/preflight.py, scripts/cplat/headless.py, tests/cplat/conftest.py, tests/cplat/units131_support.py, tests/cplat/seam178_world.py, tests/cplat/dispatch_world.py
**Covers:** AC-207.1, AC-207.2, AC-207.3, AC-207.4, AC-207.5, AC-207.6, AC-207.8
**Goal:** an unattended build, ship or system ship runs every new check in the spec's order. The first failure stops the
run with the existing outcome. Only a run whose other checks passed makes a model call.

**Implementation notes:**
- `preflight.RunContext` and `RunContext.from_env(repo)` as in the design. `check(..., run=None)` and
  `check_repo(clone, slug, run=None)` follow the design's "Order" section, and the new categories are wrapped in
  `Failure`.
  - Print the AC-207.1 pass line once per untrusted folder that passes, with `flush=True`.
  - Collect the agents per folder once, and use them for AC-207.2, AC-207.3 and AC-207.5.
- `headless._main`: build `RunContext(allow=allow, deny=deny, plugin_dirs=dirs, add_dirs=system_clones(...) for
  /system:ship else [], model=model, run_id=rid)` and pass it as `run=`. The failure path stays as it is (AC-131.11,
  AC-131.12, and dispatch cause `environment` are already handled). Name the new checks in the module docstring's
  preflight sentence.
- `tests/cplat/conftest.py`: add an autouse fixture `no_real_claude_home` that does three things:
  - replaces `preflight_trust.config_file` and `plugins_dir` with an empty per-test folder;
  - replaces `preflight_probe.model_call` with a pass with zero usage;
  - keeps the originals as `REAL_*` for spec 207's own tests.
- The fake worlds (`units131_support.py`, `seam178_world.py`, `dispatch_world.py`):
  - their fake `claude` answers the check call as the design's "Test seams" section says;
  - their fake repos' committed settings allow `Bash(devbox run *)`;
  - nothing else changes.
- `appship_sched.start_repo` needs no change, because `check_repo` builds its context from the environment of the
  headless session.

**Done when:** the acceptance tests of AC-207.8 pass: the order of the checks, the first failure wins, a model call only
after every other check passed, the one-line output, exit 1, `escalated` with cause `environment`, the dispatch result's
cause, no settings file or trust record changed, and 0 invocations and $0. The headless-level tests of AC-207.1 to
AC-207.6 pass, including a system ship clone checked by `check_repo` under `CPLAT_HEADLESS=1`. `devbox run test-fast`
is green, which means every existing headless, dispatch and seam test still passes.

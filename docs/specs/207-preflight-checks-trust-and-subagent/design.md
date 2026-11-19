# Design — 207 Preflight checks trust and subagent tools before a ship

## Decisions

- The new checks live in three new modules next to `preflight.py` (`preflight_trust.py`, `preflight_agents.py`,
  `preflight_probe.py`, plus `preflight_rules.py` for AC-207.2). `preflight.py` keeps `Failure`, the order and the gh
  retry. Reason: `preflight.py` is already 300 lines, and each check needs its own seams for the tests. The new modules
  return a detail string (or `None`). They never import `preflight`, so there is no import cycle; `preflight` wraps
  each detail in `Failure(<category>, detail)`.
- The new checks run only when the caller passes a `RunContext` (headless does, and so does `check_repo` inside a
  headless session). A call without one, such as the existing unit tests or an attended `check_repo`, runs only the
  spec-131 checks. Reason: the spec's non-goal says interactive sessions get no model call and no worktree probe.
- Trust is read from Claude Code's global config: `$CLAUDE_CONFIG_DIR/.claude.json` when that variable is set, else
  `~/.claude.json`. A folder counts as trusted when its own entry, or the entry of any parent folder, under `projects`
  has `hasTrustDialogAccepted: true`. That is how Claude Code inherits trust. A file that is missing or unreadable means
  "not trusted". The file is opened read-only and never written (AC-207.1, AC-207.8, spec 162 non-goals).
- "The repo's committed permission rules are passed to the session" (AC-207.1) holds by construction:
  `headless.claude_cmd` always passes `repo_rules(repo)` as `--settings` (spec 162). The trust check therefore tests only
  the plugins, `env` and `permissions.additionalDirectories`.
- The model check call is a real `claude -p` call, outside the budget, cached for 60 minutes per model and credentials
  (A4). It runs with `cwd` set to a fresh temporary folder and with every `CPLAT_*` variable removed (`core.repo_env()`).
  So no repo hook, no unit environment and no run transcript attribution reaches it, and AC-131.12's 0 invocations and
  $0 stay true. This extends ADR-076, which says the preflight of an unattended run checks what its sessions need; it
  adds no new principle, so it needs no new ADR.
- The agent worktree probe uses `git worktree add --detach`, so no branch is created and none needs to be removed
  (AC-207.4: branches exactly as before).
- Note "check the logs of the 4 week-46 runs": followed, with the logs on this machine (`~/.cache/sdlc-foundry/headless`).
  - The bench-files system ship (2026-11-09) shows `svc:coder` subagents "refused the Bash tool" as a whole in fresh,
    never-trusted clones. The clones' allow rules were lost, which is a permission cause that AC-207.1 and AC-207.2 catch.
  - sdlc-foundry-662 (2026-11-12) and laneb (2026-11-17) show blocked combined commands (`… && …`). That is the
    worktree guard or compound-command matching, which is a non-goal.
  - AC-207.2 therefore stays as written, and the evidence for each cause goes in the changelog fragment.
- When the repo's shape cannot be resolved (`shapecmd.route` raises), the agent checks use the `svc` plugin for coder,
  tester and reviewer and `shared` for quality and security, with no deployment agent. This matches `svc:<role>`
  "without a shape" in the commands. A `gitops-app` or `cluster-gitops` folder (the start folder of a system ship) starts
  no coder, so it gets the trust check only.

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `scripts/cplat/preflight_trust.py` | Claude config and plugin locations, the trust record (read only), the committed settings at HEAD, AC-207.1 | new |
| `scripts/cplat/preflight_agents.py` | the agents a command starts, the definition that wins for each, tools and model, AC-207.3, AC-207.5 | new |
| `scripts/cplat/preflight_rules.py` | the effective permission layers and the coder command sample, AC-207.2 | new |
| `scripts/cplat/preflight_probe.py` | agent worktree probe (AC-207.4), the model check call, its cache and its log section (AC-207.6) | new |
| `scripts/cplat/preflight.py` | `RunContext`, the gh login retry (AC-207.7), the order of the checks (AC-207.8), `check_repo` | changed |
| `scripts/cplat/headless.py` | builds the `RunContext` and passes it to `preflight.check` | changed |

## Contract

### Output lines (stdout of `cplat headless`)

The failure line is the one AC-131.11 already defines: `preflight failed: <category>: <cause>: <fix>`. The fix is the
text after the last `: ` and never contains a colon, while the cause may contain colons (in error lines or rules). The
lines that are printed on a pass are these:

```
preflight: <folder> is not trusted; its permission rules are passed to the session     # AC-207.1, once per untrusted folder that passes
preflight: gh login answered on try <n>                                                 # AC-207.7, n = 2 or 3
```

### Categories, causes and fixes (exact texts; `<…>` are filled in)

| AC | Category | Detail (after `preflight failed: <category>: `) |
|---|---|---|
| 207.1 env | `untrusted-folder` | `<folder> is not trusted and its committed settings set env (<KEY>, <KEY>), which Claude Code ignores without trust: open claude in <folder> once and accept the trust dialog` |
| 207.1 dirs | `untrusted-folder` | `<folder> is not trusted and its committed settings set permissions.additionalDirectories, which Claude Code ignores without trust: open claude in <folder> once and accept the trust dialog` |
| 207.1 plugin | `untrusted-folder` | `<folder> is not trusted and plugin <name>@<marketplace>, which its committed settings enable, is neither installed on this machine nor passed with --plugin-dir: open claude in <folder> once and accept the trust dialog` |
| 207.2 deny/ask | `subagent-tools` | `<agent> runs "<command>", which <kind> rule "<rule>" in <layer> settings (<path>) matches: remove or narrow "<rule>"` |
| 207.2 missing allow | `subagent-tools` | `<agent> runs "<command>", which no allow rule permits: add "Bash(<command pattern>)" to permissions.allow in <folder>/.claude/settings.json` |
| 207.2 whole shell | `subagent-tools` | `deny rule "<rule>" in <layer> settings (<path>) denies the shell tool to every agent: remove "<rule>"` |
| 207.2 agent | `subagent-tools` | `deny rule "<rule>" in <layer> settings (<path>) denies the <agent> agent this run starts: remove "<rule>"` |
| 207.3 | `subagent-tools` | `<agent> resolves to <path> (<layer> definition), which does not grant Bash: add Bash to its tools, or remove the override` |
| 207.4 create | `agent-worktree` | `cannot create an agent worktree at <path> (<last git error line>): run git worktree prune in <repo>, then run again` |
| 207.4 outside | `agent-worktree` | `agent worktrees go to <real path>, outside the folders the session may work in (<repo>[, <add-dir>…]): make <repo>/.claude/worktrees a plain folder inside the repo` |
| 207.5 available | `model-unreachable` | `<model> (used by <agent>, <agent>) is not in availableModels of <layer> settings (<path>): add <model> to availableModels, or set a model the settings allow` |
| 207.5 denied | `model-unreachable` | `<model> (used by <agent>, <agent>) is in deniedModels of <layer> settings (<path>): remove <model> from deniedModels, or set a model the settings allow` |
| 207.6 auth | `model-unreachable` | `<model> (used by <agent>, <agent>) cannot be called (<last line of the error>): run claude /login, or set a model the account may use` |
| 207.6 network | `model-unreachable` | `could not reach the model API (<last line of the error>): check the network, then run again` |
| 207.7 | `gh-auth` | `gh is not logged in for <host> (3 tries over 45 s): gh auth login --hostname <host>`, and on macOS (`platform.system() == "Darwin"`) `; if gh is logged in, unlock the login keychain` appended |

`<agent>` is the role name (`coder`, `tester`, `reviewer`, `security`, `quality`, `deployment`), with `coordinator` for
the session's own model. `<layer>` is one of `managed`, `user`, `project`, `local`, `run` (the run allowlist or refused
rules passed as flags). Agents in a list are named in the order of the role table below, with `coordinator` first.

A failure is handled as AC-131.11 and AC-131.12 say, with no change in `headless`. The result is
`preflight failed: <category>`, the stop reason is `preflight`, the run is escalated with cause `environment`, and the
dispatch result carries `cause: environment`. The run exits 1 and starts no session.

### Order (AC-207.8)

`preflight.check(repo, command, specs, targets, deny, run)`. The first failure wins. `folders` = the repo, then each
target clone:

1. The existing checks, unchanged: deny-rules, no-repo-allowlist (each folder), blocked-by-settings (each folder),
   git-identity, gh-auth (now with the retry), no-push-access (each folder).
2. If `run` is given: AC-207.1 for each folder, then AC-207.2 for each folder, then AC-207.3 for each folder.
3. AC-207.4 for the repo, for `/component:build` and `/component:ship` only.
4. AC-207.5 for the coordinator model and every agent of every folder.
5. AC-207.6 for the distinct models of step 4, once per run (never in `check_repo`).

`check_repo(clone, slug, run=None)`: the existing checks. When `run` is `None` and `CPLAT_HEADLESS == "1"`, it uses
`RunContext.from_env(clone)`. When a `RunContext` is present, it then runs AC-207.1, AC-207.2 and AC-207.3 for the clone
with command `/system:ship` (A7). It runs no probe and makes no model call.

### Python interfaces

```python
# preflight.py
@dataclass
class RunContext:
    allow: list[str]            # the run allowlist (--allowedTools)
    deny: list[str]             # the refused rules (--disallowedTools)
    plugin_dirs: list[str]      # resolved --plugin-dir folders
    add_dirs: list[str]         # --add-dir folders (a system ship's clones)
    model: str | None           # the coordinator model; None in check_repo
    run_id: str | None
    @classmethod
    def from_env(cls, repo: Path) -> "RunContext": ...  # CPLAT_RUN_ALLOWLIST, CPLAT_PLUGIN_DIRS, refused_rules(default_branch(repo))

def sleep(seconds: float) -> None: ...                   # tests replace this (time.sleep)
GH_LOGIN_WAITS = (15, 30)
def check(repo, command, specs, targets=None, deny=None, run: RunContext | None = None) -> Failure | None
def check_repo(clone, slug, run: RunContext | None = None) -> Failure | None

# preflight_trust.py
def config_file() -> Path                                # $CLAUDE_CONFIG_DIR/.claude.json, else ~/.claude.json (tests replace)
def plugins_dir() -> Path                                # $CLAUDE_CONFIG_DIR/plugins, else ~/.claude/plugins (tests replace)
def trusted(folder: Path) -> bool
def committed_settings(repo: Path) -> dict               # `git show HEAD:.claude/settings.json`, {} when missing or invalid
def installed_plugins() -> dict[str, list[Path]]         # "name@marketplace" -> install paths, from plugins/installed_plugins.json
def plugin_dir_names(plugin_dirs: list[str]) -> dict[str, Path]   # plugin.json "name" -> folder
def check(folder: Path, plugin_dirs: list[str]) -> tuple[str | None, str | None]   # (failure detail, pass line)

# preflight_agents.py
@dataclass
class Agent:
    role: str                   # "coder"
    type: str                   # "svc:coder"
    path: Path | None           # the winning definition
    layer: str                  # "project" | "user" | "plugin-dir" | "installed" | "platform"
    bash: bool                  # grants the shell tool
    model: str | None           # its model; None = inherits the coordinator's
def roles(folder: Path, command: str) -> list[tuple[str, str]]   # [(role, type)] in table order; [] for gitops/cluster folders
def resolve(folder: Path, role: str, type_: str, plugin_dirs: list[str]) -> Agent
def check_definitions(agents: list[Agent]) -> str | None          # AC-207.3
def models(agents_by_folder: dict[Path, list[Agent]], coordinator: str | None) -> dict[str, list[str]]  # model -> roles
def check_models(models: dict[str, list[str]], repo: Path) -> str | None   # AC-207.5, layers from preflight.layers(repo)

# preflight_rules.py
def coder_commands(folder: Path, specs: list[str]) -> list[str]
def check(folder: Path, specs: list[str], agents: list[Agent], run_allow: list[str], run_deny: list[str]) -> str | None

# preflight_probe.py
def worktree_location(repo: Path) -> Path                # repo/.claude/worktrees
def check_worktree(repo: Path, add_dirs: list[str]) -> str | None
@dataclass
class CallResult:
    ok: bool
    error: str                  # last line of the error, "" when ok
    offline: bool               # the error reads like a dropped network
    usage: dict                 # input_tokens, output_tokens, cache_read_input_tokens, cache_creation_input_tokens, cost_usd
def model_call(model: str) -> CallResult                 # tests replace this; REAL_MODEL_CALL keeps the original
def check_models(models: dict[str, list[str]], run_id: str | None) -> str | None   # AC-207.6
```

### Roles per command (AC-207.3, AC-207.2, AC-207.5)

The agent types come from `shapecmd.route(folder)["agents"]`.

| Command | Roles |
|---|---|
| `/component:build` | coder, tester, reviewer, security, quality |
| `/component:ship` | the same, plus deployment when `route` lists it (deployable shapes) |
| `/system:ship` (each component clone) | as `/component:ship`, for the clone's own shape |

### The winning definition (AC-207.3)

Look for the first match, in this order:

1. A file in `<folder>/.claude/agents/*.md` whose front matter `name` equals the role or the type (`project`).
2. The same in the user agents folder (`plugins_dir().parent / "agents"`, `user`).
3. `agents/<role>.md` in the `--plugin-dir` folder whose `plugin.json` name is the type's plugin (`plugin-dir`).
4. The same in an install path of `<plugin>@*` from `installed_plugins()`. When there are several, prefer the
   marketplace the folder's committed settings enable (`installed`).
5. `core.PLATFORM_ROOT / "plugins" / <plugin> / "agents" / <role>.md`: the plugin set this cplat belongs to
   (`platform`).

The front matter is the YAML between the first two `---` lines. Without `tools` the definition grants every tool. With
`tools` it grants Bash when an item is `Bash` or starts with `Bash(`. A `disallowedTools` entry that names `Bash`
revokes it. `model` is `opus`, `sonnet`, `haiku`, a full model id, or `inherit`/missing, which inherits the coordinator's
model. When `CLAUDE_CODE_SUBAGENT_MODEL` is set, it replaces every agent's model.

### Model exclusion (AC-207.5)

`availableModels` and `deniedModels` are lists of strings in the managed and user layers (`preflight.layers`). A model
`m` matches an entry `e` when `e == m`, or when one of the two is an alias (`opus`, `sonnet`, `haiku`) and the other is
a full id that contains that alias as a `-`-separated word (`claude-opus-4-5` matches `opus`). A model is excluded when
some layer has an `availableModels` list with no matching entry, or a `deniedModels` list with a matching entry. The
managed layer is checked first. No model call is made.

### The coder command sample (AC-207.2)

`coder_commands`: `cplat component build reset 0123abc`, `git add src/x.py`, `git commit -s -m "<subject>"`, and
`devbox run <script>` for each distinct script named as `devbox run <script>` in the committed `plan.md` of each spec (at
`units.feature_head(folder, spec)`, in order of appearance). When no script is named, or for a system ship clone, the
sample uses `devbox run test`.

The layers are these:

- **allow:** the managed and user `allow` rules, the folder's committed `allow` rules (`committed_settings`, which reach
  the session through `--settings` whatever the trust), the `local` `allow` rules only when `trusted(folder)`, and the
  run allowlist.
- **deny and ask:** `deny` and `ask` from the managed, user, project (the working file, as `_blocked` reads it) and local
  layers, then the refused rules (layer `run`, kind `deny`).

The checks, with the first failure winning:

1. A deny rule `Bash` or `Bash(*)` blocks the whole shell.
2. A deny rule `Agent`, `Task`, `Agent(<x>)` or `Task(<x>)`, with `x` equal to the role or the type of one of the
   agents, blocks that agent.
3. For each agent that runs shell commands (all of them), and for each command, in the order above: a deny or ask rule
   with `denyrules.refuses(rule, command)` blocks it.
4. A command that no allow rule with `preflight.matches(rule, command)` permits is missing an allow rule. The fix names
   the command with its variable part as `*`: `Bash(git add *)`, `Bash(git commit -s *)`,
   `Bash(cplat component build reset *)`, and `Bash(devbox run <script>)`.

The command is checked once, and the failure names the first agent that runs it. That is `coder` for the sample.

### Agent worktree probe (AC-207.4)

```
loc = repo/.claude/worktrees; created_loc = not loc.exists()
path = loc / f"cplat-preflight-{os.getpid()}"
before = (git worktree list --porcelain, git for-each-ref refs/heads, git status --porcelain)
git worktree add --detach <path> HEAD          -> on failure: the "create" detail with the last stderr line
real = path.resolve(); allowed = [repo.resolve(), *(Path(d).resolve() for d in add_dirs)]
outside = not any(real.is_relative_to(a) for a in allowed)
finally: git worktree remove --force <path>; git worktree prune; rmdir loc if created_loc
outside -> the "outside" detail
```

After the probe, `before` must equal the state then. A difference is a bug in the probe and not a user failure, so the
tests assert it.

### Model check call (AC-207.6)

```
argv = [CPLAT_CLAUDE or "claude", "-p", "Reply with the single word ok.", "--model", m,
        "--output-format", "json", "--max-turns", "1"]
cwd  = tempfile.mkdtemp(prefix="cplat-preflight-"), removed afterwards; env = core.repo_env(); timeout 120 s
ok   = exit 0 and (stdout is not JSON or its "is_error" is not true)
error = the last non-empty line of stderr, else of the JSON "result", else f"claude exited {code}"
offline = core.NETWORK_DOWN or core.NETWORK_FLAKY matches stderr + stdout
```

- **Retry:** an offline result is retried as `core.run` retries a dropped network. The waits are 10 s, doubling, at most
  60 s each, through `core.sleep`, and the call stops once the next wait would pass `core.NETWORK_RETRY_MAX_WAIT`. Then
  the "network" detail applies. Any other failure gets the "auth" detail at once. The spec defines no third outcome, and
  a model the run cannot call must not start the run.
- **Cache:** `$XDG_CACHE_HOME/sdlc-foundry/preflight/models.json` (else `~/.cache/...`), a JSON object
  `{"<sha256(model + "\0" + fingerprint)>": "<ISO-8601 UTC of the pass>"}`. Only passes are written, and entries older
  than 60 minutes are dropped on write. The `fingerprint` is the sha256 of the values of `ANTHROPIC_API_KEY`,
  `ANTHROPIC_AUTH_TOKEN`, `CLAUDE_CODE_OAUTH_TOKEN`, `ANTHROPIC_BASE_URL`, `CLAUDE_CODE_USE_BEDROCK`,
  `CLAUDE_CODE_USE_VERTEX`, `CLAUDE_CONFIG_DIR`, and `oauthAccount.accountUuid` of `config_file()`. No secret is
  written. A model with an entry from the last 60 minutes is not called.
- **Log:** `runs.set_section(run_id, "preflight", {"model_calls": [{"model": m, "cached": bool, "input_tokens": int,
  "output_tokens": int, "cache_read_input_tokens": int, "cache_creation_input_tokens": int, "cost_usd": float}]})`, with
  one entry per distinct model (cached entries have zero tokens). Nothing goes to `budget`, and the call is not run
  through `run_once`, so it is no invocation.

### gh login retry (AC-207.7)

```
for n, wait in enumerate((0, *GH_LOGIN_WAITS), start=1):
    if wait: sleep(wait)
    code, _, err = _retried(["auth", "status", "--hostname", host], repo)
    if code == 0: (n > 1 and print(f"preflight: gh login answered on try {n}")); return None
    if _offline(err): return <today's network detail>     # no "not logged in" retry for a network error (A5)
return Failure("gh-auth", <the 3-tries detail>)
```

## Test seams

The tests use these seams, and a conftest autouse fixture installs them for every other test:

- `preflight_trust.config_file` and `plugins_dir`: an empty folder per test.
- `preflight_probe.model_call`: a pass with zero usage. The original is kept as `preflight_probe.REAL_MODEL_CALL`.
- `preflight.sleep`: a no-op.

Subprocess worlds whose fake `claude` (`CPLAT_CLAUDE`) is reached through `cplat headless` answer the check call,
recognised by `--max-turns 1` and the prompt `Reply with the single word ok.`, with
`{"type":"result","is_error":false,"result":"ok","usage":{...}}` and exit 0.

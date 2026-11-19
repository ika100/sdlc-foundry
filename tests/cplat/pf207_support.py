"""Spec 207 acceptance tests: shared helpers (seams, a repo world for `preflight.check`, agent definitions).

The new modules (`preflight_trust`, `preflight_agents`, `preflight_rules`, `preflight_probe`) are imported inside the tests and
helpers, so that a module that does not exist yet fails the test that needs it and not the collection of the others.
Nothing here calls a real model, sleeps for real or touches the real home or Claude config: `Seams.install` replaces
`preflight_trust.config_file` / `plugins_dir`, `preflight_probe.model_call` and `preflight.sleep` (design.md "Test seams").
"""
import importlib
import importlib.util
import json
import os
import stat
import subprocess
from pathlib import Path

import core
from units131_support import SPEC_ID, git, make_repo
from waiting import with_prelude

ZERO = {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0, "cost_usd": 0.0}
ROLES = ["coder", "tester", "reviewer", "security", "quality", "deployment"]
BASE_SETTINGS = {"permissions": {"allow": ["Bash(devbox run *)", "Bash(cplat *)", "Read(~/.claude/plugins/**)"]}}
CREDENTIALS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_BASE_URL",
               "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CONFIG_DIR", "CLAUDE_CODE_SUBAGENT_MODEL")


def mod(name):
    return importlib.import_module(name)


def fresh(name):
    """A pristine copy of a cplat module (the conftest of spec 207 replaces functions of the imported one)."""
    path = core.PLATFORM_ROOT / "scripts" / "cplat" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"{name}_fresh", path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class Seams:
    """The home folder of Claude Code, the model call and the waits of one test."""

    def __init__(self, tmp_path, monkeypatch):
        self.mp = monkeypatch
        self.tmp = tmp_path
        self.home = tmp_path / "claude-home"
        self.home.mkdir()
        self.config = self.home / ".claude.json"
        self.plugins = self.home / "plugins"
        self.calls: list[str] = []
        self.script: dict = {}            # model (or "*") -> a result dict, or a list of them (the last one repeats)
        self.waits: list[float] = []      # preflight.sleep
        self.net_waits: list[float] = []  # core.sleep

    # ---- installation
    def sleeps(self):
        self.mp.setattr(mod("preflight"), "sleep", self.waits.append, raising=False)
        self.mp.setattr(core, "sleep", self.net_waits.append)

    def install(self):
        pt, pp = mod("preflight_trust"), mod("preflight_probe")
        self.sleeps()
        self.mp.setattr(pt, "config_file", lambda: self.config, raising=False)
        self.mp.setattr(pt, "plugins_dir", lambda: self.plugins, raising=False)
        self.mp.setattr(pp, "model_call", self._call, raising=False)
        self.mp.setenv("XDG_CACHE_HOME", str(self.tmp / "cache"))
        for name in CREDENTIALS:
            self.mp.delenv(name, raising=False)
        return self

    def _call(self, model):
        pp = mod("preflight_probe")
        self.calls.append(model)
        entry = self.script.get(model, self.script.get("*", {}))
        if isinstance(entry, list):
            entry = entry.pop(0) if len(entry) > 1 else entry[0]
        result = {"ok": True, "error": "", "offline": False, "usage": dict(ZERO), **entry}
        return pp.CallResult(**result)

    # ---- the Claude config
    def _load(self):
        return json.loads(self.config.read_text()) if self.config.is_file() else {}

    def trust(self, *folders):
        data = self._load()
        for f in folders:
            data.setdefault("projects", {})[str(Path(f).resolve())] = {"hasTrustDialogAccepted": True}
        self.config.write_text(json.dumps(data))

    def account(self, uuid):
        data = self._load()
        data["oauthAccount"] = {"accountUuid": uuid}
        self.config.write_text(json.dumps(data))

    def install_plugin(self, key, *, agents: dict[str, str] | None = None) -> Path:
        """An installed plugin `<name>@<marketplace>` (installed_plugins.json, version 2) with optional agent files."""
        path = self.tmp / "installs" / key.replace("@", "-at-")
        path.mkdir(parents=True, exist_ok=True)
        for role, text in (agents or {}).items():
            (path / "agents").mkdir(exist_ok=True)
            (path / "agents" / f"{role}.md").write_text(text)
        self.plugins.mkdir(parents=True, exist_ok=True)
        f = self.plugins / "installed_plugins.json"
        data = json.loads(f.read_text()) if f.is_file() else {"version": 2, "plugins": {}}
        data["plugins"].setdefault(key, []).append({"scope": "user", "installPath": str(path), "version": "1.0.0"})
        f.write_text(json.dumps(data))
        return path

    def user_agents(self) -> Path:
        d = self.home / "agents"
        d.mkdir(exist_ok=True)
        return d


def agent_text(name, *, tools="Read, Write, Bash", model=None, extra=""):
    lines = ["---", f'name: "{name}"', "description: test agent"]
    if tools is not None:
        lines.append(f"tools: {tools}")
    if model:
        lines.append(f"model: {model}")
    if extra:
        lines.append(extra)
    return "\n".join([*lines, "---", "", "You are a test agent.", ""])


def write_agent(folder, role, **kw) -> Path:
    d = Path(folder) / ".claude" / "agents"
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"{role}.md"
    f.write_text(agent_text(kw.pop("name", role), **kw))
    return f


def override_all(folder, model="haiku"):
    """A project definition with the shell tool and `model` for every role: the models of a run are then known."""
    for role in ROLES:
        write_agent(folder, role, model=model)


def plugin_dir(tmp_path, name, agents: dict[str, str] | None = None) -> Path:
    d = tmp_path / f"plugin-{name}"
    (d / ".claude-plugin").mkdir(parents=True)
    (d / ".claude-plugin" / "plugin.json").write_text(json.dumps({"name": name, "version": "1.0.0"}))
    for role, text in (agents or {}).items():
        (d / "agents").mkdir(exist_ok=True)
        (d / "agents" / f"{role}.md").write_text(text)
    return d


def commit_settings(repo, data=None, **extra):
    """Commit `.claude/settings.json` = `data` (default: the repo's current one) updated with `extra` top-level keys."""
    f = Path(repo) / ".claude" / "settings.json"
    cur = json.loads(f.read_text()) if data is None else data
    cur = {**cur, **extra}
    f.write_text(json.dumps(cur))
    git(repo, "add", ".claude/settings.json")
    git(repo, "commit", "-qm", "settings", "--allow-empty")
    return f


GH_COUNTING = '''#!/bin/sh
# stub gh: `auth status` fails FAKE_GH_AUTH_FAILS times with "not logged in", FAKE_GH_AUTH=offline -> the network is down
echo "$@" >> "$FAKE_GH_LOG"
case "$1 $2" in
  "auth status")
    [ "$FAKE_GH_AUTH" = "offline" ] && { echo "error connecting to api.github.com" >&2; exit 1; }
    n=$(cat "$FAKE_GH_LOG.auth" 2>/dev/null || echo 0)
    n=$((n+1))
    echo $n > "$FAKE_GH_LOG.auth"
    [ "$n" -le "${FAKE_GH_AUTH_FAILS:-0}" ] && { echo "You are not logged in" >&2; exit 1; }
    exit 0 ;;
esac
if [ "$1" = "api" ]; then
  case "$*" in
    *permissions.push*) echo true ;;
    *) echo tester ;;
  esac
  exit 0
fi
exit 0
'''


class Env:
    """A git repo `shop-api` (committed allowlist, identity, a gh stub) whose settings layers are replaced; `check` runs
    `preflight.check` with a `RunContext` like the one `cplat headless` builds."""

    def __init__(self, tmp_path, monkeypatch, name="shop-api"):
        self.tmp, self.mp = tmp_path, monkeypatch
        self.repo = make_repo(tmp_path, name=name)
        git(self.repo, "config", "user.name", "Tester")
        git(self.repo, "config", "user.email", "tester@example.test")
        (self.repo / ".gitignore").write_text(".claude/settings.local.json\n")
        git(self.repo, "add", ".gitignore")
        git(self.repo, "commit", "-qm", "ignore local settings")
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        gh = bin_dir / "gh"
        gh.write_text(with_prelude(GH_COUNTING))
        gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
        self.gh_log = tmp_path / "gh.log"
        self.gh_log.write_text("")
        monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
        monkeypatch.setenv("FAKE_GH_LOG", str(self.gh_log))
        for var in ("FAKE_GH_AUTH", "FAKE_GH_AUTH_FAILS"):
            monkeypatch.delenv(var, raising=False)
        self.user = tmp_path / "user.json"
        self.user.write_text("{}")
        self.managed = tmp_path / "managed.json"

    def layers(self, r=None):
        base = Path(r or self.repo)
        return [("managed", self.managed), ("user", self.user), ("project", base / ".claude" / "settings.json"),
                ("local", base / ".claude" / "settings.local.json")]

    def arm(self):
        self.mp.setattr(mod("preflight"), "layers", self.layers)

    def set_layer(self, layer, data):
        path = dict(self.layers())[layer]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data))
        return path

    def auth_calls(self):
        return sum(1 for ln in self.gh_log.read_text().splitlines() if ln.startswith("auth status"))

    def ctx(self, command="/component:ship", **kw):
        pf = mod("preflight")
        fields = dict(allow=pf.run_allowlist(command, pf.branches_of(command, [SPEC_ID])), deny=pf.refused_rules("main"),
                      plugin_dirs=[], add_dirs=[], model="sonnet", run_id=None)
        fields.update(kw)
        return pf.RunContext(**fields)

    def check(self, command="/component:ship", ctx=None, targets=None):
        pf = mod("preflight")
        self.arm()
        ctx = ctx or self.ctx(command)
        return pf.check(self.repo, command, [SPEC_ID], targets, deny=ctx.deny, run=ctx)


def state_of(repo):
    """The repo's worktree list, branches and working tree (AC-207.4: exactly as before)."""
    def out(*args):
        return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True).stdout
    return (out("worktree", "list", "--porcelain"), out("for-each-ref", "refs/heads"), out("status", "--porcelain"))


def fix_of(line: str) -> str:
    """The fix of a failure line: the text after the last `: `."""
    return line.rsplit(": ", 1)[1]

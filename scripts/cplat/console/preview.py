"""Console preview (spec 122): what a model form would do, shown before anything runs.

`preview(snapshot_dir, form, fields)` turns the fields of one "Add to the model" form into the exact slash command, runs that
command (without `--pr`) on a scratch copy of the repo and reports the `system.yaml` diff, the checks, the consequence and the way
back. The repo itself is never touched. The preview applies no rule of its own (ADR-054): every check is the message of the command
or of `scripts/render.py --check` in the scratch copy."""
from __future__ import annotations

import contextlib
import difflib
import io
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

import yaml

from . import actions

FORMS = ("component", "api", "resource", "environment", "system")
COPIED = ("applications", "bootstrap")
_LOCK = threading.Lock()   # the commands print to the process streams
_API_RE = re.compile(r"--(?:provides|consumes) ([\w-]+)(?::\w+)?: (.+)")
_KEY_RE = re.compile(r"(?<![\w.-])([A-Za-z_][\w-]*(?:\.[\w\[\]-]+)+|--[\w-]+|[\w-]+): (.+)")


class BadForm(ValueError):
    """The form or its fields cannot become a command (HTTP 400)."""


# ---------------- form -> command ----------------

def _text(fields: dict, key: str) -> str:
    return str(fields.get(key) or "").strip()


def _list(fields: dict, key: str) -> list[str]:
    value = fields.get(key) or []
    items = [value] if isinstance(value, str) else list(value)
    return [str(i).strip() for i in items if str(i).strip()]


def _action(fields: dict, allowed: tuple[str, ...], default: str) -> str:
    action = _text(fields, "action") or default
    if action not in allowed:
        raise BadForm(f"unknown action {action!r}")
    return action


def command_of(form: str, fields: dict) -> list[str]:
    """The slash command as words: ['/component:add', 'todo-api']."""
    if form == "component":
        action = _action(fields, ("add", "set", "remove"), "add")
        return [f"/component:{action}", _need(fields, "component")]
    if form == "api":
        action = _action(fields, ("add", "set"), "set")
        words = [f"/component:{action}", _need(fields, "component")]
        for item in _list(fields, "provides"):
            words += ["--provides", item]
        for item in _list(fields, "consumes"):
            words += ["--consumes", item]
        return words
    if form == "resource":
        action = _action(fields, ("add", "remove"), "add")
        words = [f"/resource:{action}", _need(fields, "resource")]
        for flag in ("type", "version"):
            if _text(fields, flag):
                words += [f"--{flag}", _text(fields, flag)]
        return words
    if form == "environment":
        words = ["/system:set", "--env", _need(fields, "env")]
        for flag in ("promote", "policy", "host"):
            if _text(fields, flag):
                words += [f"--{flag}", _text(fields, flag)]
        return words
    if form == "system":
        return ["/system:new", _need(fields, "name")]
    raise BadForm(f"unknown form {form!r}")


def _need(fields: dict, key: str) -> str:
    value = _text(fields, key)
    if not value:
        raise BadForm(f"missing {key}")
    return value


def shown(words: list[str]) -> str:
    """The command as a user would type it (quoted only where a word has spaces or quotes)."""
    return " ".join(f'"{w}"' if re.search(r"""[\s"']""", w) else w for w in words)


def cplat_argv(words: list[str]) -> list[str]:
    """`/component:add x` -> ['component', 'add', 'x']."""
    noun, verb = words[0].lstrip("/").split(":", 1)
    return [noun, verb, *words[1:]]


# ---------------- the scratch copy ----------------

def _git(scratch: Path, *args: str) -> str:
    ident = ["-c", "user.name=preview", "-c", "user.email=preview@localhost", "-c", "commit.gpgsign=false"]
    proc = subprocess.run(["git", *ident, *args], cwd=scratch, text=True, capture_output=True, check=False)
    return proc.stdout


def make_scratch(snapshot: Path, scratch: Path) -> None:
    """Copy what the commands read and write, and make it a clean git tree (the commands refuse a dirty one)."""
    for name in COPIED:
        if (snapshot / name).is_dir():
            shutil.copytree(snapshot / name, scratch / name, symlinks=True)
    for rel in ("scripts/render.py", ".copier-answers.yml"):
        if (snapshot / rel).is_file():
            (scratch / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(snapshot / rel, scratch / rel)
    import gitops  # noqa: PLC0415 - scripts/cplat is on sys.path when cplat runs

    gitops.scratch_tree(scratch)


def system_yaml(root: Path) -> Path | None:
    found = sorted((root / "applications").glob("*/system.yaml"))
    return found[0] if found else None


def _read(path: Path | None) -> str:
    return path.read_text() if path and path.is_file() else ""


def run_command(argv: list[str], scratch: Path) -> tuple[int, str]:
    """Run the real command in-process on the scratch copy; (exit code, its error output)."""
    import cplat
    full = [*argv, "--repo-dir", str(scratch)]
    err = io.StringIO()
    with _LOCK, contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
        if full[:2] == ["system", "set"]:
            import core
            import systemset
            try:
                rc = systemset.main(full[2:])
            except core.PlatformError as e:
                print(f"ERROR: {e}", file=sys.stderr)
                if e.hint:
                    print(f"  fix: {e.hint}", file=sys.stderr)
                rc = 1
            except SystemExit as e:   # argparse
                rc = int(e.code) if isinstance(e.code, int) else 2
        else:
            try:
                rc = cplat.main(full)
            except SystemExit as e:
                rc = int(e.code) if isinstance(e.code, int) else 2
    return rc, err.getvalue()


def render_check(scratch: Path) -> str:
    """The renderer's own verdict on the scratch copy ('' when it passes)."""
    script = scratch / "scripts" / "render.py"
    if not script.is_file():
        return ""
    proc = subprocess.run([sys.executable, str(script), "--check"], cwd=scratch, text=True, capture_output=True, check=False)
    return "" if proc.returncode == 0 else (proc.stderr or proc.stdout).strip()


# ---------------- checks ----------------

def _checks_of(message: str, fallback_key: str) -> list[dict]:
    """The failing messages as {key, rule, ok: false}; key and rule are the words of the command or the renderer."""
    out = []
    lines = [ln.strip() for ln in re.split(r"\s\|\s|\n", message) if ln.strip()]
    for line in lines:
        line = re.sub(r"^(ERROR|error|fail(ed)?):\s*", "", line)
        line = re.sub(r"^`[^`]+` failed \(exit \d+\):\s*", "", line)    # the wrapper of a failed subprocess
        line = re.sub(r"^(?:\S+/)?system\.yaml:\s*(?=\w+\.)", "", line)
        if not line or line.startswith(("fix:", "Traceback")) or re.match(r"(Installed|Resolved|Downloaded|Prepared|Audited) \d+", line):
            continue
        api = _API_RE.match(line)    # the command names the flag; the model key it sets is apis.<name>
        match = _KEY_RE.search(line)
        if api:
            key, rule = f"apis.{api.group(1)}", api.group(2)
        else:
            key, rule = (match.group(1), match.group(2)) if match else (fallback_key, line)
        out.append({"key": key, "rule": rule, "ok": False})
    return out or [{"key": fallback_key, "rule": message.strip() or "failed", "ok": False}]


# ---------------- consequence and way back ----------------

def _app_name(snapshot: Path) -> str:
    path = snapshot / ".copier-answers.yml"
    try:
        data = yaml.safe_load(path.read_text()) or {}
    except (OSError, yaml.YAMLError):
        data = {}
    return str(data.get("project_name") or snapshot.name)


def _changed_envs(scratch: Path) -> list[str]:
    envs: set[str] = set()
    for line in _git(scratch, "status", "--porcelain", "-uall").splitlines():
        match = re.search(r"overlays/([^/]+)/", line[3:])
        if match:
            envs.add(match.group(1))
    return sorted(envs)


def consequence_of(form: str, fields: dict, snapshot: Path, envs: list[str]) -> list[str]:
    repo = _app_name(snapshot)
    lines = [f"Opens one pull request in {repo} with the regenerated files; nothing changes until it is merged."]
    if form == "environment":
        env = _text(fields, "env")
        envs = sorted({*envs, env})
        lines.append(f"The rules of {env} change; Argo applies them after the merge.")
    if form == "system":
        lines = ["Creates the system repo and its first pull request; the components come later."]
    elif envs:
        lines.append("Generated overlays change in: " + ", ".join(envs) + ".")
    else:
        lines.append("No generated overlay changes.")
    return lines


def way_back_of(form: str, fields: dict, words: list[str], snapshot: Path) -> list[str]:
    close = "Close its pull request before it is merged."
    if form in ("component", "api") and words[0] == "/component:add":
        return [close, f"After the merge, run /component:remove {words[1]}."]
    if form == "resource" and words[0] == "/resource:add":
        return [close, f"After the merge, run /resource:remove {words[1]}."]
    if form == "environment":
        env = _text(fields, "env")
        doc = yaml.safe_load(_read(system_yaml(snapshot))) or {}
        before = (doc.get("environments") or {}).get(env) or {}
        parts = []
        for flag in ("promote", "policy", "host"):
            if _text(fields, flag) and flag in before:
                parts += [f"--{flag}", str(before[flag])]
        back = [close]
        if parts:
            back.append("After the merge, run " + shown(["/system:set", "--env", env, *parts]) + ".")
        return back
    return [close, "After the merge, change it back with a new pull request."]


# ---------------- entry point ----------------

def _system_manifest(fields: dict) -> list[str]:
    """`/system:new` takes a manifest: write the form to the cache and name the file."""
    manifest = {k: v for k, v in fields.items() if v not in (None, "", [])}
    path = actions.state_dir() / "manifests" / f"{_need(fields, 'name')}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(manifest, sort_keys=False))
    return ["/system:new", str(path)]


def preview(snapshot_dir: Path, form: str, fields: dict) -> dict:
    """The document of `POST /api/preview`; raises BadForm for a form that cannot become a command."""
    snapshot = Path(snapshot_dir)
    fields = fields or {}
    if form == "system":
        words = _system_manifest(fields)
        return {"command": shown(words), "diff": "", "checks": [], "valid": True,
                "consequence": consequence_of(form, fields, snapshot, []),
                "way_back": ["Close its pull request and delete the new repo."]}
    words = command_of(form, fields)
    with tempfile.TemporaryDirectory(prefix="console-preview-") as tmp:
        scratch = Path(tmp)
        make_scratch(snapshot, scratch)
        before = _read(system_yaml(scratch))
        rc, err = run_command(cplat_argv(words), scratch)
        checks = _checks_of(err, words[1]) if rc != 0 else []
        if rc == 0:
            problem = render_check(scratch)
            if problem:
                checks = _checks_of(problem, "render")
        target = system_yaml(scratch)
        after = _read(target)
        diff = "".join(difflib.unified_diff(before.splitlines(True), after.splitlines(True),
                                            "a/system.yaml", "b/system.yaml")) if rc == 0 else ""
        envs = _changed_envs(scratch) if rc == 0 else []
    if not checks:
        checks = [{"key": "render", "rule": "scripts/render.py --check passes", "ok": True}]
    return {"command": shown(words), "diff": diff, "checks": checks, "valid": all(c["ok"] for c in checks),
            "consequence": consequence_of(form, fields, snapshot, envs), "way_back": way_back_of(form, fields, words, snapshot)}

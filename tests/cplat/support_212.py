"""Spec 212: a scratch repo with the real selector, trace module, recording plugin and test-fast recipe, and a small suite.

The scratch repo has the platform's layout (scripts/cplat, tests/cplat, scripts/test-fast.sh), so the copied files find
their repo root as they do in the platform repo, and its maps live in its own .git. Its suite exercises every kind of
dependency of AC-212.2; `Repo.record()` runs it in a nested pytest with `--deps-record`.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from system_fixtures import ROOT

COPIED = ("scripts/cplat/depstrace.py", "tests/cplat/depsmap.py", "tests/cplat/shared_render.py", "scripts/testselect.py",
          "scripts/test-fast.sh", "devbox.json")

FILES = {
    # cplat stand-in: the same two lines as scripts/cplat/cplat.py, then the command's module, imported by name
    "scripts/cplat/cplat.py": '''import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if os.environ.get("SDLC_DEPS_TRACE"):
    import depstrace
    depstrace.child()
module = __import__(sys.argv[1])
module.main()
''',
    "scripts/cplat/cmd_show.py": '''from pathlib import Path
import cmd_helper
def main():
    print(cmd_helper.helper(), (Path(__file__).parents[2] / "plugins" / "prompt.md").read_text())
''',
    "scripts/cplat/cmd_helper.py": "def helper():\n    return 'helper'\n",
    "scripts/cplat/mod_a.py": "import mod_c\nVALUE = mod_c.VALUE + 1\n",
    "scripts/cplat/mod_c.py": "VALUE = 1\n",
    "scripts/cplat/mod_lazy.py": "VALUE = 'lazy'\n",
    "scripts/cplat/mod_patched.py": "def ask():\n    return 'real'\n",
    "scripts/cplat/mod_fixture.py": "VALUE = 'fixture'\n",
    "scripts/cplat/mod_render.py": '''from pathlib import Path
def build(workdir):
    out = Path(workdir) / "out"
    out.mkdir()
    (out / "copy.txt").write_text((Path(__file__).parents[2] / "templates" / "t" / "file.txt").read_text())
    return out
''',
    "scripts/cplat/mod_unread.py": "VALUE = 'no test reads me'\n",
    "plugins/prompt.md": "the prompt\n",
    "plugins/listed/one.md": "one\n",
    "templates/t/file.txt": "template\n",
    "templates/tree/inner/deep.txt": "deep\n",
    "data/session.txt": "session\n",
    "docs/page.md": "nobody reads this page\n",
    "tests/cplat/pytest.ini": "[pytest]\n",
    ".gitignore": "__pycache__/\n",
    "requirements-test.txt": "pytest\n",
    "tests/cplat/conftest.py": '''import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "cplat"))
pytest_plugins = ["depsmap"]
import pytest


@pytest.fixture(autouse=True)
def patched(monkeypatch):
    import mod_patched
    monkeypatch.setattr(mod_patched, "ask", lambda: "patched")


@pytest.fixture(scope="session")
def session_data():
    import mod_fixture
    return (ROOT / "data" / "session.txt").read_text() + mod_fixture.VALUE


@pytest.fixture(scope="session")
def renders(tmp_path_factory):
    from shared_render import SharedRenders
    return SharedRenders(tmp_path_factory.mktemp("shared-renders"))
''',
    "tests/cplat/test_static.py": "import mod_a\n\ndef test_static():\n    assert mod_a.VALUE == 2\n",
    "tests/cplat/test_lazy_first.py": "def test_first():\n    import mod_lazy\n    assert mod_lazy.VALUE\n",
    "tests/cplat/test_lazy_second.py": "def test_second():\n    import mod_lazy\n    assert mod_lazy.VALUE == 'lazy'\n",
    "tests/cplat/test_reads.py": '''from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]

def test_reads():
    assert (ROOT / "plugins" / "prompt.md").read_text()
    assert sorted(p.name for p in (ROOT / "plugins" / "listed").iterdir()) == ["one.md"]
''',
    "tests/cplat/test_subprocess_arg.py": '''import subprocess, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]

def test_hands_a_directory():
    subprocess.run([sys.executable, "-c", "import sys; print(sys.argv[1])", str(ROOT / "templates" / "tree")], check=True)
''',
    "tests/cplat/test_cplat_child.py": '''import subprocess, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]

def test_runs_cplat():
    out = subprocess.run([sys.executable, str(ROOT / "scripts" / "cplat" / "cplat.py"), "cmd_show"], capture_output=True,
                         text=True, check=True).stdout
    assert "the prompt" in out
''',
    "tests/cplat/test_session_one.py": "def test_one(session_data):\n    assert 'session' in session_data\n",
    "tests/cplat/test_session_two.py": "def test_two(session_data):\n    assert 'fixture' in session_data\n",
    "tests/cplat/test_render_one.py": '''import mod_render

def test_render_one(renders, tmp_path):
    assert (renders.copy("t", mod_render.build, tmp_path / "r") / "copy.txt").read_text() == "template\\n"
''',
    "tests/cplat/test_render_two.py": '''def test_render_two(renders, tmp_path):
    import mod_render
    assert (renders.copy("t", mod_render.build, tmp_path / "r") / "copy.txt").exists()
''',
    "tests/cplat/test_patched_only.py": "def test_patched_only():\n    assert True\n",
    "tests/cplat/test_red.py": "import os\n\ndef test_red():\n    assert not os.environ.get('SCRATCH_RED')\n",
    "tests/cplat/test_env.py": '''import json, os

def test_env():
    out = os.environ.get("SCRATCH_ENV_OUT")
    if out:
        open(out, "w").write(json.dumps(sorted(k for k in os.environ if k.startswith("SDLC_DEPS"))))
''',
}

ALL_TESTS = sorted(p for p in FILES if p.startswith("tests/cplat/test_"))


def clean_env(**extra: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("SDLC_DEPS", "SCRATCH_", "PYTEST_ADDOPTS", "PYTEST_XDIST"))}
    env.update(extra)
    return env


class Repo:
    def __init__(self, root: Path):
        self.root = root
        for rel, text in FILES.items():
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)
        for rel in COPIED:
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / rel, root / rel)
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.email", "t@example.com")
        self.git("config", "user.name", "t")
        self.git("config", "commit.gpgsign", "false")
        self.commit("base")

    def git(self, *args: str) -> str:
        return subprocess.run(["git", *args], cwd=self.root, capture_output=True, text=True, check=True).stdout

    def commit(self, message: str) -> str:
        self.git("add", "-A")
        self.git("commit", "-q", "--allow-empty", "-m", message)
        return self.git("rev-parse", "HEAD").strip()

    def write(self, rel: str, text: str) -> None:
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)

    @property
    def store(self) -> Path:
        return self.root / ".git" / "sdlc-test-deps"

    def pytest(self, *args: str, workers: int = 2, **env: str) -> subprocess.CompletedProcess:
        dist = ["-n", str(workers)] if workers else ["-p", "no:xdist"]
        return subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *dist, *args], cwd=self.root,
                              capture_output=True, text=True, env=clean_env(**env), timeout=110)

    def record(self, name: str = "m.json", workers: int = 2, **env: str) -> dict:
        self.store.mkdir(parents=True, exist_ok=True)
        path = self.store / name
        r = self.pytest("--deps-record", str(path), "tests/cplat", workers=workers, **env)
        assert r.returncode in (0, 1), r.stdout + r.stderr
        return json.loads(path.read_text())

    def plan(self, *args: str, cwd: Path | None = None) -> tuple[str, list[str], str]:
        """(`full <map to record>`, `select` or `none`; the selected test files; the message on stderr) from the scratch
        repo's own selector, read from the pytest arguments it prints."""
        r = subprocess.run([sys.executable, "scripts/testselect.py", "args", *args], cwd=cwd or self.root, capture_output=True,
                           text=True, env=clean_env())
        assert r.returncode == 0, r.stderr
        out = r.stdout.strip()
        if out.startswith("--deps-record "):
            return "full " + out.split(" ", 1)[1], [], r.stderr.strip()
        assert out.startswith("--deps-select="), out
        tests = [t for t in out.split("=", 1)[1].split(",") if t]
        return ("select" if tests else "none"), tests, r.stderr.strip()

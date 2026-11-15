"""Spec 199 test helpers (not a test module, never collected): a fake `docker` first on PATH.

`docker port k3d-<cluster>-serverlb 80/tcp` answers what the test scripted (default: the container does not exist, exit 1);
every call's argv is logged, so a test counts how often `cplat` asked. Spec 199's test files are exempt from the conftest
fixture that stubs `localport.docker_port`, so the real `subprocess` path runs against this executable."""
import json
import os
import stat
import sys
from pathlib import Path

from waiting import with_prelude

PORT = 8089

SCRIPT = '''#!%(py)s
import json, os, sys
d = os.environ["FAKE_DOCKER_DIR"]
cfg = json.load(open(d + "/cfg.json"))
open(d + "/calls", "a").write(json.dumps(sys.argv[1:]) + "\\n")
if sys.argv[1:2] == ["port"] and len(sys.argv) >= 4:
    out = cfg["ports"].get(sys.argv[2])
    if cfg.get("exit"):
        sys.stdout.write(out or "")
        sys.exit(cfg["exit"])
    if out is None:
        sys.stderr.write("Error response from daemon: No such container: " + sys.argv[2] + "\\n")
        sys.exit(1)
    sys.stdout.write(out)
    sys.exit(0)
sys.exit(cfg.get("exit") or 1)
'''


def isolate(tmp_path: Path, monkeypatch) -> None:
    """No personal settings file and no settings file of the current directory can change the cluster."""
    (tmp_path / "xdg-isolated").mkdir(exist_ok=True)
    (tmp_path / "cwd-isolated").mkdir(exist_ok=True)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg-isolated"))
    monkeypatch.chdir(tmp_path / "cwd-isolated")


class FakeDocker:
    def __init__(self, tmp_path: Path, monkeypatch):
        self.mp = monkeypatch
        self.dir = tmp_path / "fake-docker"
        self.dir.mkdir()
        self.cfg = {"ports": {}, "exit": 0}
        self._save()
        exe = self.dir / "docker"
        exe.write_text(with_prelude(SCRIPT % {"py": sys.executable}))
        exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
        monkeypatch.setenv("FAKE_DOCKER_DIR", str(self.dir))
        monkeypatch.setenv("PATH", f"{self.dir}{os.pathsep}{os.environ['PATH']}")
        monkeypatch.delenv("LOCAL_HTTP_PORT", raising=False)
        monkeypatch.delenv("LOCAL_CLUSTER", raising=False)
        monkeypatch.delenv("CPLAT_KUBE_CONTEXT", raising=False)
        isolate(tmp_path, monkeypatch)

    def _save(self):
        (self.dir / "cfg.json").write_text(json.dumps(self.cfg))

    def reports(self, cluster: str, port: int = PORT) -> "FakeDocker":
        """The load balancer of `k3d-<cluster>` publishes `port` (IPv4 and IPv6 lines, as `docker port` prints them)."""
        return self.says(cluster, f"0.0.0.0:{port}\n[::]:{port}\n")

    def says(self, cluster: str, text: str) -> "FakeDocker":
        self.cfg["ports"][f"k3d-{cluster}-serverlb"] = text
        self._save()
        return self

    def fails(self, code: int = 1) -> "FakeDocker":
        self.cfg["exit"] = code
        self._save()
        return self

    @property
    def calls(self) -> list[list[str]]:
        f = self.dir / "calls"
        return [json.loads(ln) for ln in f.read_text().splitlines()] if f.is_file() else []

    def asked(self, cluster: str | None = None) -> list[list[str]]:
        want = ["port", f"k3d-{cluster}-serverlb", "80/tcp"] if cluster else None
        return [c for c in self.calls if (c == want if want else c[:1] == ["port"])]

    def clear(self) -> None:
        (self.dir / "calls").unlink(missing_ok=True)


def no_docker(tmp_path: Path, monkeypatch) -> Path:
    """PATH without any `docker` (the executable is missing)."""
    empty = tmp_path / "empty-bin"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    monkeypatch.delenv("LOCAL_HTTP_PORT", raising=False)
    monkeypatch.delenv("LOCAL_CLUSTER", raising=False)
    monkeypatch.delenv("CPLAT_KUBE_CONTEXT", raising=False)
    isolate(tmp_path, monkeypatch)
    return empty

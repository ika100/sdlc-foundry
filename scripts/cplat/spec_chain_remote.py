"""Every remote read of `cplat spec trace --chain` (spec 109): one `gh` seam, one probe, one "down" flag.

Only read commands run: `gh auth token`, `gh api` GETs, `gh issue view`, `gh pr list`, and `git remote get-url`. Nothing is
written, nothing is fetched, no cache file is kept. Once GitHub is found down no further `gh` call is made in the run."""
from __future__ import annotations
import json
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
import yaml
import model

TIMEOUT = 10
NOT_AUTH = "gh not authenticated"
UNREACHABLE = "GitHub not reachable"
NO_ORIGIN = "no GitHub origin remote"


def gh(args: list[str], *, cwd: Path, timeout: float = TIMEOUT) -> tuple[int, str, str]:
    """The seam: (rc, stdout, stderr). rc 124 on timeout, 127 when gh is missing. Tests replace it."""
    try:
        p = subprocess.run(["gh", *args], cwd=cwd, capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        return 124, "", "timed out"
    except OSError as ex:
        return 127, "", str(ex)
    return p.returncode, p.stdout, p.stderr


def which(tool: str) -> str | None:
    """The seam for `shutil.which`. Tests replace it."""
    return shutil.which(tool)


def _slug_of(url: str) -> str | None:
    m = re.search(r"github\.com[:/](.+?)(?:\.git)?/?$", url.strip())
    return m.group(1) if m else None


def _origin_slug(repo: Path) -> str | None:
    try:
        p = subprocess.run(["git", "remote", "get-url", "origin"], cwd=repo, capture_output=True, text=True, check=False)
    except OSError:
        return None
    return _slug_of(p.stdout) if p.returncode == 0 else None


def _first_line(text: str) -> str:
    return next((ln.strip() for ln in text.splitlines() if ln.strip()), "")


@dataclass
class Pins:
    source: str  # "<slug> (default branch)" or "<path> (local checkout)"
    system: str | None  # None when no system lists the component
    component: str | None
    tags: dict[str, str | None]  # env -> pinned tag; an env without an instance is absent


class Remote:
    def __init__(self, repo: Path):
        self.repo = Path(repo)
        self.unreached = []
        self._down = None
        self._probed = False
        self._slug = None
        self._slug_read = False

    @property
    def slug(self) -> str | None:
        if not self._slug_read:
            self._slug, self._slug_read = _origin_slug(self.repo), True
        return self._slug

    # ---- the one budget ----
    def _mark_down(self, reason: str) -> None:
        if self._down is None:
            self._down = reason
        if not any(u["what"] == "gh" for u in self.unreached):
            self.unreached.append({"what": "gh", "reason": reason})

    def down(self) -> str | None:
        """None when gh is usable, else the reason. Probes once: which gh, gh auth token, gh api rate_limit."""
        if self._probed:
            return self._down
        self._probed = True
        if not which("gh"):
            self._mark_down("gh not installed")
        else:
            rc, _, _ = gh(["auth", "token"], cwd=self.repo)
            if rc != 0:
                self._mark_down(NOT_AUTH)
            else:
                rc, out, err = gh(["api", "rate_limit"], cwd=self.repo, timeout=TIMEOUT)
                if rc != 0:
                    text = f"{out}\n{err}"
                    bad = "HTTP 401" in text or "Bad credentials" in text
                    self._mark_down(NOT_AUTH if bad else UNREACHABLE)
        return self._down

    def _call(self, args: list[str]) -> tuple[int, str, str]:
        """One gh call after the probe said up. A timeout marks GitHub down for the rest of the run."""
        if self.down():
            return 1, "", self._down or UNREACHABLE
        rc, out, err = gh(args, cwd=self.repo)
        if rc == 124:
            self._mark_down(UNREACHABLE)
        return rc, out, err

    def _why(self, rc: int, err: str) -> str:
        return self._down if self._down else (_first_line(err) or f"gh exited {rc}")

    # ---- readers ----
    def issues(self, numbers: list[int]) -> dict[int, str] | str:
        if self.down():
            return self._down  # type: ignore[return-value]
        if not self.slug:
            return NO_ORIGIN
        found: dict[int, str] = {}
        for n in numbers:
            rc, out, err = self._call(["issue", "view", str(n), "-R", self.slug, "--json", "number,state"])
            if rc != 0:
                return self._why(rc, err)
            try:
                found[n] = str(json.loads(out)["state"]).lower()
            except (ValueError, KeyError, TypeError):
                return f"issue #{n} not readable"
        return found

    def merged_prs(self, branch: str) -> list[dict] | str:
        if self.down():
            return self._down  # type: ignore[return-value]
        if not self.slug:
            return NO_ORIGIN
        rc, out, err = self._call(["pr", "list", "-R", self.slug, "--head", branch, "--state", "merged",
                                   "--json", "number,url,mergeCommit,mergedAt", "--limit", "20"])
        if rc != 0:
            return self._why(rc, err)
        try:
            data = json.loads(out or "[]")
        except ValueError:
            return "pr list not readable"
        prs = [{"number": p.get("number"), "url": p.get("url"),
                "merge_commit": (p.get("mergeCommit") or {}).get("oid"), "merged_at": p.get("mergedAt") or ""}
               for p in data if isinstance(p, dict)]
        return sorted(prs, key=lambda p: p["merged_at"], reverse=True)

    # ---- gitops-app pins ----
    def _remote_models(self, app: str) -> tuple[list[model.Model], str | None]:
        """The models of every system of a gitops-app, read through gh at its default branch; (models, None) or ([], reason)."""
        rc, out, err = self._call(["api", f"repos/{app}"])
        if rc != 0:
            return [], self._why(rc, err)
        try:
            branch = json.loads(out).get("default_branch") or ""
        except (ValueError, AttributeError):
            branch = ""
        ref = f"?ref={branch}" if branch else ""
        rc, out, err = self._call(["api", f"repos/{app}/contents/applications{ref}"])
        if rc != 0:
            return [], self._why(rc, err)
        try:
            entries = json.loads(out)
        except ValueError:
            entries = None
        if not isinstance(entries, list):
            return [], "applications/ not readable"
        systems = [e["name"] for e in entries if isinstance(e, dict) and e.get("type") == "dir" and e.get("name")]

        def read(path: str) -> dict | None:
            rc2, text, _ = self._call(["api", f"repos/{app}/contents/{path}{ref}", "-H", "Accept: application/vnd.github.raw"])
            if rc2 != 0 or not text.strip():
                return None
            try:
                data = yaml.safe_load(text)
            except yaml.YAMLError:
                return None
            return data if isinstance(data, dict) else None

        models: list[model.Model] = []
        for s in systems:
            try:
                models.append(model.load_remote(s, read))
            except model.ModelError:
                continue
        return models, None

    def _local_checkout(self, app: str) -> Path | None:
        """The sibling directory of the repo whose origin is the gitops-app (the clone layout); read as it is, never fetched."""
        name = app.rsplit("/", 1)[-1]
        for cand in (self.repo.resolve().parent / name,):
            if cand.is_dir() and _origin_slug(cand) == app:
                return cand
        return None

    def _local_models(self, app: str) -> tuple[list[model.Model], Path | None]:
        d = self._local_checkout(app)
        if d is None:
            return [], None
        models: list[model.Model] = []
        apps = d / "applications"
        for sub in sorted(apps.iterdir()) if apps.is_dir() else []:
            if sub.is_dir() and ((sub / "system.yaml").is_file() or (sub / "app.yaml").is_file() or (sub / "services.yaml").is_file()):
                try:
                    models.append(model.load_dir(sub))
                except model.ModelError:
                    continue
        return models, d

    def pins(self, apps: list[str], service: str) -> Pins | str:
        me = self.slug or ""
        readable: Pins | None = None
        reasons: list[str] = []
        for app in apps:
            models: list[model.Model] = []
            source: str | None = None
            reason: str | None = None
            if not self.down():
                models, reason = self._remote_models(app)
                if reason is None:
                    source = f"{app} (default branch)"
            if source is None:
                models, d = self._local_models(app)
                if d is not None:
                    source = f"{d} (local checkout)"
                else:
                    reasons.append(f"gitops-app {app} not reachable ({reason or self._down or 'no local checkout'})")
                    if not any(u["what"] == f"gitops-app {app}" for u in self.unreached):
                        self.unreached.append({"what": f"gitops-app {app}", "reason": reason or self._down or "no local checkout"})
                    continue
            if readable is None:
                readable = Pins(source, None, None, {})
            for m in models:
                comp = m.find_component(me, service)
                if comp is None:
                    continue
                tags = {i.environment: i.tag for i in m.instances_of(comp.name)}
                return Pins(source, m.system, comp.name, tags)
        if readable is not None:
            return readable
        return reasons[0] if reasons else "no gitops-app linked"

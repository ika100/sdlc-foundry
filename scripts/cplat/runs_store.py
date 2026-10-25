"""The transport of the run store (spec 087, ADR-032): a private GitHub repo written through `gh api`.

One file per run, one commit per batch (Git Data API), a non-forced ref update that is retried when another machine
moved the branch. Every subprocess call goes through `gh()`, so tests can fake GitHub.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import subprocess
import time
from typing import Protocol

MAX_ATTEMPTS = 3
DAYS_PER_QUERY = 40


class StoreError(Exception):
    """Any failure of the run store transport."""


class StoreMissing(StoreError):
    """404: no such repo, or no access."""


class StoreUnreachable(StoreError):
    """gh missing, not logged in, timeout, 5xx, rejected write."""


def monotonic() -> float:   # the one clock of the 20 s budget (runs reads it too; tests replace it)
    return time.monotonic()


def gh(args: list[str], *, input: str | None = None, timeout: float = 10.0) -> tuple[int, str, str]:
    """`gh <args>` -> (exit code, stdout, stderr). Never raises: a timeout is (124, "", "timeout"), a missing gh 127."""
    try:
        proc = subprocess.run(["gh", *args], input=input, text=True, capture_output=True, timeout=max(timeout, 0.1))
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"
    except FileNotFoundError:
        return 127, "", "gh is not installed"
    except Exception as e:  # noqa: BLE001  (recording must never crash a run)
        return 127, "", f"{type(e).__name__}: {e}"
    return proc.returncode, proc.stdout, proc.stderr


class Store(Protocol):
    slug: str

    def visibility(self, deadline: float | None = None) -> str: ...
    def create_private(self) -> None: ...
    def put(self, files: dict[str, str], message: str, deadline: float | None = None) -> None: ...
    def read(self, days: list[datetime.date], deadline: float | None = None) -> list[tuple[str, str]]: ...
    def read_file(self, path: str, deadline: float | None = None) -> str | None: ...


def _last_line(text: str) -> str:
    lines = [ln.strip() for ln in text.strip().splitlines() if ln.strip()]
    return lines[-1] if lines else "no output"


def record_path(record: dict) -> str:
    """runs/YYYY/MM/DD/<run_id>.json (day = ended_at), or the `.filed.<sha1(signature)[:12]>.json` form of a follow-up."""
    if record.get("followup"):
        day = str(record.get("at", ""))[:10]
        name = f"{record['run_id']}.filed.{hashlib.sha1(str(record['signature']).encode()).hexdigest()[:12]}.json"
    else:
        day = str(record.get("ended_at", ""))[:10]
        name = f"{record['run_id']}.json"
    y, m, d = day.split("-")
    return f"runs/{y}/{m}/{d}/{name}"


class GitHubStore:
    def __init__(self, slug: str):
        self.slug = slug
        self.branch: str | None = None

    def _call(self, args: list[str], *, body: dict | None = None, deadline: float | None = None) -> tuple[int, str, str]:
        timeout = 10.0
        if deadline is not None:
            timeout = min(10.0, deadline - monotonic())
            if timeout < 1.0:
                return 124, "", "timeout"
        if body is not None:
            return gh([*args, "--input", "-"], input=json.dumps(body), timeout=timeout)
        return gh(args, timeout=timeout)

    def _api(self, path: str, *, method: str = "GET", body: dict | None = None, deadline: float | None = None) -> dict:
        args = ["api", f"repos/{self.slug}/{path}".rstrip("/")]
        if method != "GET":
            args += ["-X", method]
        code, out, err = self._call(args, body=body, deadline=deadline)
        if code != 0:
            raise _ApiError(code, err or out)
        try:
            return json.loads(out) if out.strip() else {}
        except ValueError:
            return {}

    def visibility(self, deadline: float | None = None) -> str:
        code, out, err = self._call(["api", f"repos/{self.slug}"], deadline=deadline)
        if code != 0:
            if "404" in err or "Not Found" in err:
                raise StoreMissing(f"{self.slug} not found")
            raise StoreUnreachable(_last_line(err or out))
        try:
            data = json.loads(out)
        except ValueError:
            raise StoreUnreachable("unreadable answer from gh api") from None
        self.branch = data.get("default_branch") or self.branch or "main"
        vis = data.get("visibility")
        if not vis:
            vis = "private" if data.get("private") else "public"
        return str(vis)

    def create_private(self) -> None:
        code, out, err = gh(["repo", "create", self.slug, "--private", "--add-readme", "--description",
                             "sdlc-foundry run records (private)"], timeout=30.0)
        if code != 0:
            raise StoreUnreachable(_last_line(err or out))

    def _head(self, deadline: float | None) -> str:
        path = f"git/ref/heads/{self.branch}"
        try:
            return self._api(path, deadline=deadline)["object"]["sha"]
        except _ApiError as e:
            if not e.empty_repo:
                raise StoreUnreachable(e.reason) from None
        try:
            self._api("contents/README.md", method="PUT", deadline=deadline,
                      body={"message": "init", "content": "IyBSdW4gcmVjb3JkcwoK"})   # "# Run records\n\n"
        except _ApiError:
            pass   # someone else initialised it meanwhile; the next read tells
        try:
            return self._api(path, deadline=deadline)["object"]["sha"]
        except (_ApiError, KeyError) as e:
            raise StoreUnreachable(getattr(e, "reason", "no branch head")) from None

    def put(self, files: dict[str, str], message: str, deadline: float | None = None) -> None:
        if self.branch is None:
            self.visibility(deadline)
        tree_entries = [{"path": p, "mode": "100644", "type": "blob", "content": t} for p, t in files.items()]
        for _ in range(MAX_ATTEMPTS):
            try:
                head = self._head(deadline)
                base = self._api(f"git/commits/{head}", deadline=deadline)["tree"]["sha"]
                tree = self._api("git/trees", method="POST", body={"base_tree": base, "tree": tree_entries}, deadline=deadline)["sha"]
                commit = self._api("git/commits", method="POST", body={"message": message, "tree": tree, "parents": [head]},
                                   deadline=deadline)["sha"]
                self._api(f"git/refs/heads/{self.branch}", method="PATCH", body={"sha": commit, "force": False}, deadline=deadline)
                return
            except _ApiError as e:
                if e.race:
                    continue
                raise StoreUnreachable(e.reason) from None
            except KeyError:
                raise StoreUnreachable("unexpected answer from gh api") from None
        raise StoreUnreachable("concurrent writes")

    def read_file(self, path: str, deadline: float | None = None) -> str | None:
        """The text of one file of the default branch, or None when it does not exist."""
        code, out, err = self._call(["api", f"repos/{self.slug}/contents/{path}", "-H", "Accept: application/vnd.github.raw+json"],
                                    deadline=deadline)
        if code == 0:
            return out
        if "404" in err or "Not Found" in err:
            return None
        raise StoreUnreachable(_last_line(err or out))

    def read(self, days: list[datetime.date], deadline: float | None = None) -> list[tuple[str, str]]:
        out: list[tuple[str, str]] = []
        owner, _, name = self.slug.partition("/")
        for i in range(0, len(days), DAYS_PER_QUERY):
            chunk = days[i:i + DAYS_PER_QUERY]
            dirs = {f"d{n}": f"runs/{d:%Y/%m/%d}" for n, d in enumerate(chunk)}
            fields = " ".join(
                f'{alias}: object(expression: "HEAD:{path}") {{ ... on Tree {{ entries {{ name object {{ ... on Blob {{ text }} }} }} }} }}'
                for alias, path in dirs.items())
            query = f"query($owner: String!, $name: String!) {{ repository(owner: $owner, name: $name) {{ {fields} }} }}"
            code, text, err = self._call(["api", "graphql", "-f", f"query={query}", "-f", f"owner={owner}", "-f", f"name={name}"],
                                         deadline=deadline)
            if code != 0:
                raise StoreUnreachable(_last_line(err or text))
            try:
                repo = json.loads(text)["data"]["repository"] or {}
            except (ValueError, KeyError, TypeError):
                raise StoreUnreachable("unreadable answer from gh api graphql") from None
            for alias, path in dirs.items():
                for entry in (repo.get(alias) or {}).get("entries") or []:
                    blob = entry.get("object") or {}
                    if blob.get("text") is not None:
                        out.append((f"{path}/{entry['name']}", blob["text"]))
        return out


class _ApiError(Exception):
    def __init__(self, code: int, text: str):
        super().__init__(text)
        self.code, self.reason = code, _last_line(text)
        low = text.lower()
        self.race = any(m in low for m in ("not a fast forward", "http 422", "http 409")) and "readme" not in low \
            and "workflow" not in low
        self.empty_repo = "404" in low or "409" in low or "empty" in low or "not found" in low

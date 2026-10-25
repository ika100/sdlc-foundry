"""GitHub access of the weekly retro (spec 090, ADR-039): the platform repo's issues over `gh`.

Everything goes through `gh()` and `tracker()`, so tests fake GitHub. Failures raise `autoissue.TrackerError`.
"""
from __future__ import annotations

import subprocess
from typing import Protocol

import autoissue

LABEL, LABEL_COLOR, LABEL_DESCRIPTION = "retro", "5319e7", "Weekly platform retro (spec 090)"


def gh(args: list[str], *, input: str | None = None, timeout: float = 30.0) -> tuple[int, str, str]:
    """(exit code, stdout, stderr). Never raises: a timeout is 124, a missing binary 127. Tests replace this."""
    try:
        p = subprocess.run(["gh", *args], input=input, capture_output=True, text=True, timeout=timeout, check=False)
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"
    except FileNotFoundError:
        return 127, "", "gh is missing"
    except Exception as e:  # noqa: BLE001
        return 1, "", f"{type(e).__name__}: {e}"


class RetroTracker(Protocol):
    def auto_issues(self, repo: str, since: str) -> list[dict]: ...
    def open_issues(self, repo: str) -> list[dict]: ...
    def retro_issues(self, repo: str) -> list[dict]: ...
    def create(self, repo: str, title: str, body: str, labels: list[str]) -> str: ...
    def edit_body(self, repo: str, number: int, body: str) -> str: ...
    def comment(self, repo: str, number: int, body: str) -> None: ...
    def close(self, repo: str, number: int) -> None: ...


def _labels(item: dict) -> list[str]:
    return [str(lb.get("name")) if isinstance(lb, dict) else str(lb) for lb in item.get("labels") or []]


def _url(item: dict) -> str:
    return str(item.get("html_url") or item.get("url") or "")


class GhRetroTracker:
    def _get(self, path: str) -> list[dict]:
        code, out, err = gh(["api", "--paginate", path])
        autoissue._check(code, err or out)
        return autoissue._items(out)

    def _issues(self, query: str, repo: str) -> list[dict]:
        return [i for i in self._get(f"repos/{repo}/issues?{query}") if "pull_request" not in i]

    def auto_issues(self, repo: str, since: str) -> list[dict]:
        stamp = since if len(since) > 10 else f"{since}T00:00:00Z"
        out = []
        for i in self._issues(f"labels=auto-filed&state=all&since={stamp}&per_page=100", repo):
            comments = self._get(f"repos/{repo}/issues/{i['number']}/comments?per_page=100")
            out.append({"number": int(i["number"]), "title": str(i.get("title") or ""), "url": _url(i),
                        "state": str(i.get("state") or "open"), "labels": _labels(i), "created_at": str(i.get("created_at") or ""),
                        "body": str(i.get("body") or ""),
                        "comments": [{"created_at": str(c.get("created_at") or ""), "body": str(c.get("body") or "")} for c in comments]})
        return out

    def open_issues(self, repo: str) -> list[dict]:
        return [{"number": int(i["number"]), "title": str(i.get("title") or ""), "labels": _labels(i)}
                for i in self._issues("state=open&per_page=100", repo)]

    def retro_issues(self, repo: str) -> list[dict]:
        return [{"number": int(i["number"]), "title": str(i.get("title") or ""), "url": _url(i),
                 "state": str(i.get("state") or "open"), "labels": _labels(i)}
                for i in self._issues(f"labels={LABEL}&state=all&per_page=100", repo)]

    def create(self, repo: str, title: str, body: str, labels: list[str]) -> str:
        args = ["issue", "create", "-R", repo, "--title", title, "--body-file", "-"]
        for lb in labels:
            args += ["--label", lb]
        code, out, err = gh(args, input=body)
        if code != 0 and "not found" in (err or out).lower():
            for lb in labels:
                if lb == LABEL:
                    c2, o2, e2 = gh(["label", "create", LABEL, "-R", repo, "--color", LABEL_COLOR,
                                     "--description", LABEL_DESCRIPTION, "--force"])
                    autoissue._check(c2, e2 or o2)
            code, out, err = gh(args, input=body)
        autoissue._check(code, err or out)
        return out.strip().splitlines()[-1].strip() if out.strip() else ""

    def edit_body(self, repo: str, number: int, body: str) -> str:
        code, out, err = gh(["issue", "edit", str(number), "-R", repo, "--body-file", "-"], input=body)
        autoissue._check(code, err or out)
        return out.strip().splitlines()[-1].strip() if out.strip() else f"https://github.com/{repo}/issues/{number}"

    def comment(self, repo: str, number: int, body: str) -> None:
        code, out, err = gh(["issue", "comment", str(number), "-R", repo, "--body-file", "-"], input=body)
        autoissue._check(code, err or out)

    def close(self, repo: str, number: int) -> None:
        code, out, err = gh(["issue", "close", str(number), "-R", repo])
        autoissue._check(code, err or out)


def tracker() -> RetroTracker:
    return GhRetroTracker()

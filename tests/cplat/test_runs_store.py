"""Spec 087: the GitHub transport of the run store, against a fake `gh api` that behaves like a tiny Git Data API."""
import datetime as dt
import hashlib
import json
import subprocess

import pytest

import runs_store

NOT_FOUND = (1, "", "gh: Not Found (HTTP 404)")
NOT_FF = (1, "", "gh: Update is not a fast forward (HTTP 422)")


class FakeGitHub:
    """Replaces `runs_store.gh`: repo metadata, refs, commits, trees, the Contents API for an empty repo, GraphQL reads."""

    def __init__(self, slug="acme/runs", visibility="private", empty=False):
        self.slug, self.vis, self.branch = slug, visibility, "main"
        self.trees: dict[str, dict] = {}
        self.commits: dict[str, dict] = {}
        self.pending: dict[str, dict] = {}
        self.head: str | None = None
        self.n = 0
        self.calls: list[list[str]] = []
        self.before_patch = None            # called before each PATCH of the ref: a concurrent writer
        self.missing = False
        self.down = False
        self.readme_puts = 0
        self.dirs: dict[str, dict] = {}     # "runs/YYYY/MM/DD" -> {name: text} for GraphQL reads
        if not empty:
            self._commit({"README.md": "# runs\n"}, None)

    def sha(self, kind):
        self.n += 1
        return f"{kind}{self.n:03d}"

    def _commit(self, files, parent):
        t, c = self.sha("t"), self.sha("c")
        self.trees[t] = dict(files)
        self.commits[c] = {"tree": t, "parent": parent}
        self.head = c
        return c

    def files(self):
        return self.trees[self.commits[self.head]["tree"]]

    @staticmethod
    def out(obj, args):
        for flag in ("--jq", "-q"):
            if flag in args:
                cur = obj
                for part in [p for p in args[args.index(flag) + 1].split(".") if p]:
                    cur = cur[part]
                return cur if isinstance(cur, str) else json.dumps(cur)
        return json.dumps(obj)

    def __call__(self, args, *, input=None, timeout=10.0):
        self.calls.append(list(args))
        if args[:2] == ["repo", "create"]:
            return 0, "", ""
        assert args[0] == "api", args
        path = next(a for a in args[1:] if a == "graphql" or a.startswith("repos/"))
        method = "GET"
        for flag in ("-X", "--method"):
            if flag in args:
                method = args[args.index(flag) + 1]
        body = json.loads(input) if input else {}
        base = f"repos/{self.slug}"
        if self.down:
            return 1, "", "gh: error connecting to api.github.com"
        if path == "graphql":
            return self.graphql(args)
        if path == base:
            if self.missing:
                return NOT_FOUND
            return 0, self.out({"visibility": self.vis, "private": self.vis != "public", "default_branch": self.branch}, args), ""
        if path == f"{base}/git/ref/heads/{self.branch}":
            return NOT_FOUND if self.head is None else (0, self.out({"object": {"sha": self.head}}, args), "")
        if path.startswith(f"{base}/git/commits/") and method == "GET":
            c = self.commits[path.rsplit("/", 1)[1]]
            return 0, self.out({"sha": path.rsplit("/", 1)[1], "tree": {"sha": c["tree"]}}, args), ""
        if path == f"{base}/git/trees":
            files = dict(self.trees[body["base_tree"]])
            for e in body["tree"]:
                assert e["mode"] == "100644" and e["type"] == "blob"
                files[e["path"]] = e["content"]
            t = self.sha("t")
            self.trees[t] = files
            return 0, self.out({"sha": t}, args), ""
        if path == f"{base}/git/commits" and method == "POST":
            c = self.sha("c")
            self.pending[c] = {"tree": body["tree"], "parent": body["parents"][0]}
            return 0, self.out({"sha": c}, args), ""
        if path == f"{base}/git/refs/heads/{self.branch}" and method == "PATCH":
            assert body.get("force") is False
            if self.before_patch:
                self.before_patch(self)
            if self.pending[body["sha"]]["parent"] != self.head:
                return NOT_FF
            self.commits[body["sha"]] = self.pending.pop(body["sha"])
            self.head = body["sha"]
            return 0, self.out({"object": {"sha": self.head}}, args), ""
        if path == f"{base}/contents/README.md" and method == "PUT":
            self.readme_puts += 1
            if self.head is not None:
                return 1, "", "gh: conflict (HTTP 409)"
            self._commit({"README.md": "# runs\n"}, None)
            return 0, "{}", ""
        raise AssertionError((method, path))

    def graphql(self, args):
        import re
        query = next(a for a in args if "object(expression" in a)
        data = {}
        for alias, directory in re.findall(r'(d\d+): object\(expression: "HEAD:([^"]+)"\)', query):
            entries = self.dirs.get(directory)
            data[alias] = None if entries is None else {"entries": [{"name": n, "object": {"text": t}} for n, t in entries.items()]}
        return 0, json.dumps({"data": {"repository": data}}), ""


@pytest.fixture()
def hub(monkeypatch):
    h = FakeGitHub()
    monkeypatch.setattr(runs_store, "gh", h)
    return h


def concurrent_writer(h):
    """Another machine moves the branch once, between our tree and our ref update."""
    h.before_patch = None
    files = dict(h.files())
    files["runs/2026/10/24/other.json"] = "other\n"
    h._commit(files, h.head)


def test_visibility_reads_private_public_and_internal(hub):
    """AC-087.9: the transport reports the repo's visibility so a public store is never written."""
    store = runs_store.GitHubStore("acme/runs")
    assert store.visibility() == "private"
    for v in ("public", "internal"):
        hub.vis = v
        assert runs_store.GitHubStore("acme/runs").visibility() == v


def test_a_missing_repo_and_an_unreachable_one_are_different_errors(hub):
    """AC-087.20 AC-087.9: 404 is StoreMissing (init may create it); anything else is StoreUnreachable."""
    hub.missing = True
    with pytest.raises(runs_store.StoreMissing):
        runs_store.GitHubStore("acme/runs").visibility()
    hub.missing, hub.down = False, True
    with pytest.raises(runs_store.StoreUnreachable):
        runs_store.GitHubStore("acme/runs").visibility()
    assert issubclass(runs_store.StoreMissing, runs_store.StoreError) and issubclass(runs_store.StoreUnreachable, runs_store.StoreError)


def test_create_private_creates_a_private_repo(hub):
    """AC-087.20: the repo is created with `gh repo create <slug> --private`."""
    runs_store.GitHubStore("acme/runs").create_private()
    (call,) = hub.calls
    assert call[:3] == ["repo", "create", "acme/runs"] and "--private" in call and "--public" not in call


def test_create_private_failure_is_unreachable(monkeypatch):
    """AC-087.20: a failing `gh repo create` is a StoreUnreachable, not a crash."""
    monkeypatch.setattr(runs_store, "gh", lambda args, **kw: (1, "", "gh: no permission"))
    with pytest.raises(runs_store.StoreUnreachable):
        runs_store.GitHubStore("acme/runs").create_private()


def test_put_writes_every_file_in_one_commit_with_few_calls(hub):
    """AC-087.8: a batch of any size is one commit; the write costs about five Git Data calls."""
    store = runs_store.GitHubStore("acme/runs")
    store.visibility()
    hub.calls.clear()
    files = {f"runs/2026/10/24/20261024T080000Z-{i:08x}.json": f'{{"n":{i}}}\n' for i in range(50)}
    before = hub.head
    store.put(files, "runs: 50 records")
    assert len(hub.calls) <= 6
    assert hub.commits[hub.head]["parent"] == before
    assert all(hub.files()[p] == t for p, t in files.items()) and "README.md" in hub.files()


def test_a_lost_race_is_retried_and_no_file_is_lost(hub):
    """AC-087.8: when another writer moves the branch (not a fast forward), the write starts again and lands; nothing is lost."""
    hub.before_patch = concurrent_writer
    store = runs_store.GitHubStore("acme/runs")
    store.visibility()
    store.put({"runs/2026/10/24/a.json": "A\n", "runs/2026/10/24/b.json": "B\n"}, "msg")
    files = hub.files()
    assert files["runs/2026/10/24/other.json"] == "other\n" and files["runs/2026/10/24/a.json"] == "A\n" and files["runs/2026/10/24/b.json"] == "B\n"


def test_writes_give_up_after_three_attempts(hub):
    """AC-087.8: a branch that keeps moving ends in StoreUnreachable after at most three attempts."""
    hub.before_patch = lambda h: (lambda f: h._commit({**f, f"runs/x/{h.n}.json": "x"}, h.head))(dict(h.files()))
    store = runs_store.GitHubStore("acme/runs")
    store.visibility()
    with pytest.raises(runs_store.StoreUnreachable):
        store.put({"runs/2026/10/24/a.json": "A\n"}, "msg")
    assert sum(1 for c in hub.calls if "PATCH" in c) == 3


def test_the_same_files_written_twice_are_identical(hub):
    """AC-087.8: a flush repeated after an interruption lands on the same paths with the same content."""
    store = runs_store.GitHubStore("acme/runs")
    store.visibility()
    files = {"runs/2026/10/24/a.json": "A\n"}
    store.put(files, "first")
    snapshot = dict(hub.files())
    store.put(files, "again")
    assert hub.files() == snapshot


def test_an_empty_repo_gets_a_readme_first(monkeypatch):
    """AC-087.8: a repo without a branch yet (created without --add-readme) is initialised through the Contents API once."""
    h = FakeGitHub(empty=True)
    monkeypatch.setattr(runs_store, "gh", h)
    store = runs_store.GitHubStore("acme/runs")
    store.visibility()
    store.put({"runs/2026/10/24/a.json": "A\n"}, "msg")
    assert h.readme_puts == 1 and h.files()["runs/2026/10/24/a.json"] == "A\n"


def test_record_paths_are_per_run_and_per_day_of_ending():
    """AC-087.8: one file per run at runs/YYYY/MM/DD/<run_id>.json (day = ended_at); a follow-up gets its own name."""
    r = {"run_id": "20261023T101500Z-3f9c2a71", "ended_at": "2026-10-24T00:00:05Z"}
    assert runs_store.record_path(r) == "runs/2026/10/24/20261023T101500Z-3f9c2a71.json"
    f = {"followup": "filed", "run_id": "20261023T101500Z-3f9c2a71", "signature": "sig", "at": "2026-10-25T08:00:00Z"}
    assert runs_store.record_path(f) == f"runs/2026/10/25/20261023T101500Z-3f9c2a71.filed.{hashlib.sha1(b'sig').hexdigest()[:12]}.json"


def test_read_returns_path_and_text_of_every_file_of_the_days_asked(hub):
    """AC-087.17: reading goes by day directory, skips days without one, and batches the days into few queries."""
    hub.dirs["runs/2026/10/23"] = {"a.json": "A\n", "b.json": "B\n"}
    hub.dirs["runs/2026/10/24"] = {"c.json": "C\n"}
    days = [dt.date(2026, 10, 22), dt.date(2026, 10, 23), dt.date(2026, 10, 24)]
    got = runs_store.GitHubStore("acme/runs").read(days)
    assert sorted(got) == [("runs/2026/10/23/a.json", "A\n"), ("runs/2026/10/23/b.json", "B\n"), ("runs/2026/10/24/c.json", "C\n")]
    assert len([c for c in hub.calls if "graphql" in c]) == 1
    hub.calls.clear()
    many = [dt.date(2026, 10, 24) - dt.timedelta(days=i) for i in range(45)]
    runs_store.GitHubStore("acme/runs").read(many)
    assert len([c for c in hub.calls if "graphql" in c]) == 2                      # at most 40 days per query


def test_gh_never_raises(monkeypatch):
    """AC-087.7: a missing gh or a timeout is an exit code, so recording can never crash a run."""
    def missing(*a, **k):
        raise FileNotFoundError("gh")

    def slow(*a, **k):
        raise subprocess.TimeoutExpired(["gh"], 1)
    monkeypatch.setattr(runs_store.subprocess, "run", missing)
    assert runs_store.gh(["api", "x"])[0] == 127
    monkeypatch.setattr(runs_store.subprocess, "run", slow)
    assert runs_store.gh(["api", "x"], timeout=1) == (124, "", "timeout")

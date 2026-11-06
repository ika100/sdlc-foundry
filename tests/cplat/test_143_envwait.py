"""Spec 143 acceptance tests: `cplat system wait --env` and `cplat cluster wait` as design.md "Contract" describes them.

Seams: real git on a local bare "origin" (the wanted revision comes from one `git fetch origin main`), a scripted Argo CD
(`envwait.kubectl`, one list of applications per poll), the clock of `waits` (`waits.now` / `waits.sleep`) and `ship.gh`, which
fails the test when called: the wait reads nothing from GitHub but the fetch. Every wait is called through `cplat.main`.
"""
import json
import subprocess

import pytest

import cplat
import runs
import ship
from test_runs import clock, mem, store, stored  # noqa: F401  (fixtures)

CTX = "k3d-shop"
SYSTEM_YAML = """system: shop
owner: acme
environments:
  dev: {host: '{component}.localhost'}
  staging: {}
components:
  todo-api: {type: service, lang: python, repo: acme/todo-api, uses: [postgres], instances: {dev: {}}}
resources:
  postgres: {type: database}
"""


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()


def kustomization(tag):
    return f"images:\n- name: ghcr.io/acme/todo-api\n  newTag: {tag}\n"


class Argo:
    """A scripted Argo CD: `polls` is a list of {app: status}; each `get applications` returns the next one (the last repeats)."""

    def __init__(self):
        self.polls: list[dict] = []
        self.calls: list[list[str]] = []
        self.refreshed: list[str] = []
        self.current = CTX
        self.fail: str | None = None       # stderr of a failing `get applications`

    def __call__(self, args, context=None, check=False):
        self.calls.append([context or "", *args])
        if args[:2] == ["config", "current-context"]:
            return subprocess.CompletedProcess(args, 0 if self.current else 1, (self.current or "") + "\n", "")
        if "annotate" in args:
            self.refreshed.append(args[args.index("application") + 1] if "application" in args else args[-2])
            return subprocess.CompletedProcess(args, 0, "", "")
        if "applications" in args and "get" in args:
            if self.fail:
                return subprocess.CompletedProcess(args, 1, "", self.fail)
            n = sum(1 for c in self.calls if "applications" in c and "get" in c) - 1
            poll = self.polls[min(n, len(self.polls) - 1)] if self.polls else {}
            items = [{"metadata": {"name": name}, "status": st} for name, st in poll.items()]
            return subprocess.CompletedProcess(args, 0, json.dumps({"items": items}), "")
        return subprocess.CompletedProcess(args, 1, "", f"unexpected kubectl {args}")


def app(rev, sync="Synced", health="Healthy", images=(), conditions=(), op=None):
    st = {"sync": {"status": sync, "revision": rev}, "health": {"status": health}, "summary": {"images": list(images)},
          "conditions": list(conditions)}
    if op:
        st["operationState"] = op
    return st


class World:
    def __init__(self, tmp_path, monkeypatch, capsys):
        self.mp, self.capsys = monkeypatch, capsys
        self.origin = tmp_path / "origin.git"
        self.repo = tmp_path / "shop-gitops"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(self.origin)], check=True)
        self.repo.mkdir()
        git(self.repo, "init", "-q", "-b", "main")
        git(self.repo, "config", "user.name", "t")
        git(self.repo, "config", "user.email", "t@t")
        git(self.repo, "remote", "add", "origin", str(self.origin))
        d = self.repo / "applications" / "shop"
        (d / "overlays" / "dev" / "todo-api").mkdir(parents=True)
        (d / "system.yaml").write_text(SYSTEM_YAML)
        self.old = self.commit("sha-" + "9" * 40)
        self.head = self.commit("sha-" + "4f2a91c" + "0" * 33)
        self.argo = Argo()
        monkeypatch.setattr("envwait.kubectl", self.argo)
        self.t = {"now": 1000.0, "slept": 0.0}
        monkeypatch.setattr("waits.now", lambda: self.t["now"])
        monkeypatch.setattr("waits.sleep", self.sleep)
        monkeypatch.setattr(ship, "gh", self.no_github)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        monkeypatch.delenv("CPLAT_KUBE_CONTEXT", raising=False)
        self.fetches = 0
        import envwait
        real = envwait.git

        def counting(repo, *args, **kw):
            if args and args[0] == "fetch":
                self.fetches += 1
            return real(repo, *args, **kw)
        monkeypatch.setattr(envwait, "git", counting)

    def commit(self, tag):
        (self.repo / "applications" / "shop" / "overlays" / "dev" / "todo-api" / "kustomization.yaml").write_text(kustomization(tag))
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", f"pin {tag}")
        git(self.repo, "push", "-q", "origin", "main")
        return git(self.repo, "rev-parse", "HEAD")

    def sleep(self, s):
        self.t["now"] += s
        self.t["slept"] += s

    @staticmethod
    def no_github(*a, **k):
        raise AssertionError(f"the wait asked GitHub: {a}")

    @property
    def image(self):
        return "ghcr.io/acme/todo-api:sha-4f2a91c" + "0" * 33

    def ready(self, rev=None):
        rev = rev or self.head
        return {"todo-api-dev": app(rev, images=[self.image]), "addon-postgres-dev": app(rev)}

    def wait(self, *args, context=True):
        argv = ["system", "wait", *args, "--repo-dir", str(self.repo)] + (["--context", CTX] if context else [])
        self.capsys.readouterr()
        rc = cplat.main(argv)
        cap = self.capsys.readouterr()
        return rc, cap.out.splitlines(), cap.err, argv


@pytest.fixture()
def w(tmp_path, monkeypatch, capsys):
    return World(tmp_path, monkeypatch, capsys)


def block(lines, first):
    """The result block: from the first line starting with `first`."""
    i = next(i for i, ln in enumerate(lines) if ln.startswith(first))
    return lines[i:]


# ---------------- AC-143.1 ----------------

def test_every_app_ready_exits_0_at_once_with_one_line_per_app_ac_143_1(w):  # AC-143.1
    w.argo.polls = [w.ready()]
    rc, out, _, _ = w.wait("--env", "dev")
    assert rc == 0 and w.t["slept"] == 0
    api = [ln for ln in out if ln.startswith("todo-api-dev:")]
    pg = [ln for ln in out if ln.startswith("addon-postgres-dev:")]
    assert len(api) == 1 and len(pg) == 1
    assert w.head[:7] in api[0] and "runs sha-4f2a91c" in api[0] and w.head[:7] in pg[0]
    assert block(out, "READY:")[0].startswith("READY:")


def test_a_later_commit_that_contains_the_wanted_revision_counts_ac_143_1(w):  # AC-143.1
    w.argo.polls = [w.ready()]
    rc, out, _, _ = w.wait("--env", "dev", "--revision", w.old)
    assert rc == 0 and w.t["slept"] == 0


def test_named_components_limit_the_wait_to_their_apps_ac_143_1(w):  # AC-143.1
    w.argo.polls = [{"todo-api-dev": app(w.head, images=[w.image])}]       # postgres missing, but not asked for
    rc, out, _, _ = w.wait("--env", "dev", "todo-api")
    assert rc == 0 and not any(ln.startswith("addon-postgres-dev") for ln in out)


# ---------------- AC-143.2 ----------------

def test_one_line_per_state_change_and_exit_0_at_the_last_app_ac_143_2(w):  # AC-143.2
    old_image = "ghcr.io/acme/todo-api:sha-" + "9" * 40
    w.argo.polls = [
        {"todo-api-dev": app(w.old, images=[old_image]), "addon-postgres-dev": app(w.head)},
        {"todo-api-dev": app(w.head, sync="OutOfSync", images=[old_image]), "addon-postgres-dev": app(w.head)},
        {"todo-api-dev": app(w.head, health="Progressing", images=[w.image]), "addon-postgres-dev": app(w.head)},
        {"todo-api-dev": app(w.head, health="Progressing", images=[w.image]), "addon-postgres-dev": app(w.head)},
        w.ready(),
    ]
    rc, out, _, _ = w.wait("--env", "dev", "--timeout", "300")
    assert rc == 0
    api = [ln for ln in out if ln.startswith("todo-api-dev:")]
    assert len(api) == 4, api                              # four different states, the repeated one printed once
    assert f"Synced/Progressing at {w.head[:7]}, runs sha-4f2a91c" in api[2]
    assert "Synced/Healthy" in api[3]
    assert len([ln for ln in out if ln.startswith("addon-postgres-dev:")]) == 1
    assert block(out, "READY:")


# ---------------- AC-143.3 ----------------

@pytest.mark.parametrize("state, message", [
    (dict(sync="OutOfSync", conditions=[{"type": "SyncError", "message": "one or more objects failed to apply"}]),
     "one or more objects failed to apply"),
    (dict(sync="OutOfSync", op={"phase": "Failed", "message": "Deployment is invalid", "syncResult": {"revision": "HEAD"}}),
     "Deployment is invalid"),
    (dict(health="Degraded"), "Degraded"),
])
def test_a_red_app_at_the_wanted_revision_stops_at_once_ac_143_3(w, state, message):  # AC-143.3
    if "op" in state:
        state["op"]["syncResult"]["revision"] = w.head
    w.argo.polls = [{"todo-api-dev": app(w.head, images=[w.image], **state), "addon-postgres-dev": app(w.head)}]
    rc, out, _, _ = w.wait("--env", "dev")
    assert rc == 1 and w.t["slept"] == 0
    red = block(out, "RED:")[0]
    assert "todo-api-dev" in red and w.head[:7] in red and message in red


def test_a_failed_sync_of_an_older_revision_is_not_red_ac_143_3(w):  # AC-143.3
    op = {"phase": "Failed", "message": "old failure", "syncResult": {"revision": w.old}}
    w.argo.polls = [{"todo-api-dev": app(w.old, sync="OutOfSync", op=op), "addon-postgres-dev": app(w.head)}, w.ready()]
    rc, out, _, _ = w.wait("--env", "dev")
    assert rc == 0 and not any(ln.startswith("RED:") for ln in out)


# ---------------- AC-143.4 ----------------

def test_the_timeout_names_what_each_app_waits_for_and_the_refresh_command_ac_143_4(w):  # AC-143.4
    w.argo.polls = [{"todo-api-dev": app(w.old, images=["ghcr.io/acme/todo-api:sha-" + "9" * 40])}]
    rc, out, _, argv = w.wait("--env", "dev", "--timeout", "60")
    assert rc == 2 and w.t["slept"] >= 60
    res = block(out, "TIMEOUT:")
    assert f"waiting for revision {w.head[:7]}, Argo CD is at {w.old[:7]}" in "\n".join(res)
    assert any("addon-postgres-dev" in ln and "missing" in ln for ln in res)
    assert res[-1] == "cplat " + " ".join(argv) + " --refresh"


def test_the_timeout_names_the_wanted_image_against_the_running_one_ac_143_4(w):  # AC-143.4
    old_image = "ghcr.io/acme/todo-api:sha-" + "9" * 40
    w.argo.polls = [{"todo-api-dev": app(w.head, images=[old_image]), "addon-postgres-dev": app(w.head)}]
    rc, out, _, _ = w.wait("--env", "dev", "--timeout", "60")
    assert rc == 2
    line = next(ln for ln in block(out, "TIMEOUT:") if "todo-api-dev" in ln)
    assert "sha-4f2a91c" in line and old_image in line
    assert not block(out, "TIMEOUT:")[-1].startswith("cplat ")     # not behind on the revision: no refresh hint


def test_with_refresh_given_the_timeout_prints_no_refresh_command_ac_143_4(w):  # AC-143.4
    w.argo.polls = [{"todo-api-dev": app(w.old), "addon-postgres-dev": app(w.old)}]
    rc, out, _, _ = w.wait("--env", "dev", "--timeout", "30", "--refresh")
    assert rc == 2 and not block(out, "TIMEOUT:")[-1].endswith("--refresh")


# ---------------- AC-143.5 ----------------

def test_refresh_asks_once_for_each_app_behind_on_the_revision_ac_143_5(w):  # AC-143.5
    w.argo.polls = [{"todo-api-dev": app(w.old), "addon-postgres-dev": app(w.head)}, w.ready()]
    rc, out, _, _ = w.wait("--env", "dev", "--refresh")
    assert rc == 0 and w.argo.refreshed == ["todo-api-dev"]
    said = [ln for ln in out if "hard refresh" in ln]
    assert len(said) == 1 and "todo-api-dev" in said[0] and "addon-postgres-dev" not in said[0]
    annotate = next(c for c in w.argo.calls if "annotate" in c)
    assert "argocd.argoproj.io/refresh=hard" in annotate


# ---------------- AC-143.6 ----------------

def test_a_current_context_without_the_systems_apps_is_refused_at_once_ac_143_6(w):  # AC-143.6
    w.argo.current = "kind-other"
    w.argo.polls = [{"x-dev": app("abc")}]
    rc, out, err, _ = w.wait("--env", "dev", context=False)
    assert rc != 0 and w.t["slept"] == 0 and "kind-other" in err and "shop" in err


@pytest.mark.parametrize("stderr, words", [
    ("Unable to connect to the server: dial tcp 127.0.0.1:6443: connect: connection refused", "does not answer"),
    ('error: the server doesn\'t have a resource type "applications"', "no Argo CD"),
])
def test_a_cluster_that_does_not_answer_or_has_no_argo_cd_is_refused_at_once_ac_143_6(w, stderr, words):  # AC-143.6
    w.argo.fail = stderr
    rc, out, err, _ = w.wait("--env", "dev", context=False)
    assert rc != 0 and w.t["slept"] == 0 and words in err and CTX in err


def test_the_configured_context_is_used_without_context_ac_143_6(w, monkeypatch):  # AC-143.6
    monkeypatch.setenv("CPLAT_KUBE_CONTEXT", "k3d-configured")
    w.argo.current = "kind-other"
    w.argo.polls = [w.ready()]
    rc, _, _, _ = w.wait("--env", "dev", context=False)
    assert rc == 0 and all(c[0] in ("k3d-configured", "") for c in w.argo.calls)


# ---------------- AC-143.7 ----------------

class Cluster(World):
    def __init__(self, tmp_path, monkeypatch, capsys):
        super().__init__(tmp_path, monkeypatch, capsys)
        self.crepo = tmp_path / "shop-cluster"
        corigin = tmp_path / "cluster.git"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(corigin)], check=True)
        self.crepo.mkdir()
        git(self.crepo, "init", "-q", "-b", "main")
        git(self.crepo, "config", "user.name", "t")
        git(self.crepo, "config", "user.email", "t@t")
        git(self.crepo, "remote", "add", "origin", str(corigin))
        (self.crepo / "cluster.yaml").write_text("cluster: shop-cluster\nowner: acme\nsystems: {}\n")
        git(self.crepo, "add", "-A")
        git(self.crepo, "commit", "-qm", "init")
        self.cold = git(self.crepo, "rev-parse", "HEAD")
        (self.crepo / "cluster.yaml").write_text("cluster: shop-cluster\nowner: acme\nsystems: {shop: {repo: acme/shop-gitops}}\n")
        git(self.crepo, "commit", "-qam", "add shop")
        git(self.crepo, "push", "-q", "origin", "main")
        self.chead = git(self.crepo, "rev-parse", "HEAD")

    def cwait(self, *args, context=True):
        argv = ["cluster", "wait", *args, "--repo-dir", str(self.crepo)] + (["--context", CTX] if context else [])
        self.capsys.readouterr()
        rc = cplat.main(argv)
        cap = self.capsys.readouterr()
        return rc, cap.out.splitlines(), cap.err, argv


@pytest.fixture()
def c(tmp_path, monkeypatch, capsys):
    return Cluster(tmp_path, monkeypatch, capsys)


def roots(rev, **kw):
    return {"platform-operators": app(rev), "platform-systems": app(rev, **kw)}


def test_the_cluster_wait_is_ready_when_the_roots_run_main_ac_143_7(c):  # AC-143.7
    c.argo.polls = [roots(c.cold), roots(c.chead)]
    rc, out, _, _ = c.cwait()
    assert rc == 0
    assert any(ln.startswith("platform-systems:") and c.chead[:7] in ln for ln in out) and block(out, "READY:")


def test_the_cluster_wait_is_red_on_a_degraded_root_ac_143_7(c):  # AC-143.7
    c.argo.polls = [roots(c.chead, health="Degraded")]
    rc, out, _, _ = c.cwait()
    assert rc == 1 and "platform-systems" in block(out, "RED:")[0]


def test_the_cluster_wait_times_out_with_the_refresh_command_ac_143_7(c):  # AC-143.7
    c.argo.polls = [roots(c.cold)]
    rc, out, _, argv = c.cwait("--timeout", "30")
    res = block(out, "TIMEOUT:")
    assert rc == 2 and f"Argo CD is at {c.cold[:7]}" in "\n".join(res) and res[-1] == "cplat " + " ".join(argv) + " --refresh"


def test_the_cluster_wait_refreshes_the_roots_behind_ac_143_7(c):  # AC-143.7
    c.argo.polls = [roots(c.cold), roots(c.chead)]
    rc, out, _, _ = c.cwait("--refresh")
    assert rc == 0 and sorted(c.argo.refreshed) == ["platform-operators", "platform-systems"]


def test_the_cluster_wait_refuses_a_context_without_the_roots_ac_143_7(c):  # AC-143.7
    c.argo.current = "kind-other"
    c.argo.polls = [{"x-dev": app("abc")}]
    rc, _, err, _ = c.cwait(context=False)
    assert rc != 0 and "kind-other" in err and c.t["slept"] == 0


# ---------------- AC-143.10 ----------------

def test_the_wait_asks_github_once_for_mains_head_ac_143_10(w):  # AC-143.10
    w.argo.polls = [{"todo-api-dev": app(w.old)}, {"todo-api-dev": app(w.head)}, w.ready()]
    rc, _, _, _ = w.wait("--env", "dev")
    assert rc == 0 and w.fetches == 1               # ship.gh fails the test on any other GitHub call


def test_inside_a_run_the_minutes_count_as_waiting_time_ac_143_10(w, monkeypatch, store):  # AC-143.10
    rid = runs.start("product-ship", repo="acme/shop-gitops", spec="012-shop")
    monkeypatch.setenv("CPLAT_RUN_PARENT", rid)
    w.argo.polls = [{"todo-api-dev": app(w.old)}, {"todo-api-dev": app(w.old)}, w.ready()]
    rc, _, _, _ = w.wait("--env", "dev")
    rec = runs.active(rid)
    assert rc == 0 and stored(store) == []
    assert rec["waiting_s"] == pytest.approx(w.t["slept"]) and rec["waiting_s"] > 0
    assert rec["waits"][-1]["wait"] == "system wait" and rec["waits"][-1]["result"] == "reached"


@pytest.mark.parametrize("polls, result, outcome", [
    ("ready", "reached", "done"), ("behind", "timeout", "failed"), ("red", "red", "failed")])
def test_outside_a_run_the_wait_records_its_own_run_ac_143_10(w, store, polls, result, outcome):  # AC-143.10
    w.argo.polls = [{"ready": w.ready(), "behind": {"todo-api-dev": app(w.old)},
                     "red": {"todo-api-dev": app(w.head, health="Degraded")}}[polls]]
    w.wait("--env", "dev", "--timeout", "30")
    (r,) = stored(store)
    assert r["kind"] == "wait" and r["outcome"] == outcome
    assert r["wait"]["command"] == "system wait" and r["wait"]["result"] == result


# ---------------- #506: a ComparisonError with a network cause is pending until the timeout ----------------

DNS = "Failed to load target state: rpc error: dial tcp: lookup github.com on 10.43.0.10:53: read udp 10.42.0.9:41234: i/o timeout"


@pytest.mark.parametrize("message", [DNS, "rpc error: code = Unknown desc = read tcp 10.42.0.9:443: connection reset by peer",
                                     "Get \"https://github.com/acme/shop-gitops/info/refs\": net/http: TLS handshake timeout",
                                     "dial tcp 140.82.121.4:443: connect: connection refused"])
def test_a_network_comparison_error_waits_for_argo_to_retry_506(w, message):  # #506
    flaky = {"todo-api-dev": app(w.head, images=[w.image], conditions=[{"type": "ComparisonError", "message": message}]),
             "addon-postgres-dev": app(w.head)}
    w.argo.polls = [flaky, flaky, w.ready()]
    rc, out, _, _ = w.wait("--env", "dev", "--timeout", "300")
    assert rc == 0 and w.t["slept"] > 0 and not any(ln.startswith("RED:") for ln in out)
    assert block(out, "READY:")


def test_a_network_comparison_error_still_there_at_the_timeout_is_red_with_its_message_506(w):  # #506
    w.argo.polls = [{"todo-api-dev": app(w.head, images=[w.image], conditions=[{"type": "ComparisonError", "message": DNS}]),
                     "addon-postgres-dev": app(w.head)}]
    rc, out, _, _ = w.wait("--env", "dev", "--timeout", "60")
    assert rc == 1 and w.t["slept"] >= 60
    red = block(out, "RED:")[0]
    assert "todo-api-dev" in red and w.head[:7] in red and "ComparisonError" in red and "i/o timeout" in red
    assert "still failing after 60s" in red


def test_another_comparison_error_is_still_red_at_once_506(w):  # #506
    bad = "Unable to generate manifests: kustomize build failed: accumulating resources: missing.yaml: no such file or directory"
    w.argo.polls = [{"todo-api-dev": app(w.head, images=[w.image], conditions=[{"type": "ComparisonError", "message": bad}]),
                     "addon-postgres-dev": app(w.head)}]
    rc, out, _, _ = w.wait("--env", "dev")
    assert rc == 1 and w.t["slept"] == 0 and "kustomize build failed" in block(out, "RED:")[0]

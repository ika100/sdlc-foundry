"""Spec 120 acceptance tests, the platform side: the model and `cplat model show` (AC-120.16, .21), `cplat system status` (AC-120.22),
`cplat component set` (AC-120.5), `/platform:doctor` (AC-120.17, .18, .25, .27), the cluster scripts, the copier answer and the cluster
repos (AC-120.17, .25, .27), the e2e script text (AC-120.5, .6, .10, .12 .. .15, .17, .19 .. .23, .25, .27), the docs, plugins and
changelog (AC-120.5, .18, .22, .24).

Contract: design.md "Contract: model, `cplat model show`, status", "Contract: `cplat component set`", "Contract: doctor", "Contract: local
cluster and bootstrap", "Contract: the gitops repo answer", "Contract: docs" and "Contract: e2e". Everything runs through `cplat.main` or
the modules on hand-built checkouts; `gh`, `kubectl` and the network are faked or not used. The e2e script is only read (it needs a cluster).
Domain-like names are matched with word-bounded regular expressions, never with `"a.b.c" in text`."""
import json
import re
import shutil
import subprocess
import sys
from types import SimpleNamespace

import pytest
import yaml

import cplat
from cluster_fixtures import base, cluster_repo, render, render_ok, script, stubs, sys_doc, system_repo, write_cluster
from resources_fixtures import APP, comp, platform_render_module, system
from scale_fixtures import KEDA, METRICS, RES, cache, cache_system, cpu, expected_operator, lag, length, queue_system, sdoc
from system_fixtures import ROOT, files, git, mod, write_system
from test_commands_114 import commit, gitops5, render_check, run, sysdoc  # noqa: F401  (gitops5 is a fixture)

T = ROOT / "templates" / "gitops-app"
EN = "–"     # U+2013, the dash of `3 (1–5)`


def model_of(path):
    return mod("model").load_dir(path / APP)


def show_json(path, capsys) -> dict:
    assert cplat.main(["model", "show", "--repo-dir", str(path), "--json"]) == 0
    return json.loads(capsys.readouterr().out)


def show_text(path, capsys) -> list[str]:
    assert cplat.main(["model", "show", "--repo-dir", str(path)]) == 0
    return capsys.readouterr().out.splitlines()


# ---------------- AC-120.16 / .21: the model ----------------

def model_doc() -> dict:
    """api: component default {memory}, dev its own cpu scale, prod a fixed 3; worker (dev, staging): queue scale from the component,
    staging its own cache scale; plain: replicas 2."""
    api = comp("api", provides=["jobs"], resources=RES, scale={"max": 4, "on": {"memory": 60}})
    api["instances"]["dev"] = {"scale": {"min": 2, "max": 6, "on": {"cpu": 70}}}
    api["instances"]["prod"] = {"replicas": 3}
    worker = comp("worker", ["sessions"], consumes=["jobs"], resources=RES, envs=("dev", "staging"), scale={"min": 0, "max": 5, "on": {"consumes": "jobs", "lag": 10}})
    worker["instances"]["staging"] = {"scale": {"max": 3, "on": {"cache": "sessions", "list": "jobs", "length": 7}}}
    plain = comp("plain", resources=RES, replicas=2)
    doc = system({"bus": {"type": "broker"}, "sessions": cache()}, {"api": api, "worker": worker, "plain": plain}, apis={"jobs": {"type": "events"}})
    return doc


@pytest.fixture()
def mrepo(tmp_path):
    write_system(tmp_path, model_doc())
    return tmp_path


def by(m):
    return {(i.component, i.environment): i for i in m.instances}


def test_a_scaled_instance_has_its_effective_scale_and_no_replicas_ac_120_21(mrepo):  # AC-120.21
    inst = by(model_of(mrepo))
    assert inst[("api", "dev")].scale == {"min": 2, "max": 6, "on": {"cpu": 70}} and inst[("api", "dev")].replicas is None
    assert list(inst[("api", "dev")].scale) == ["min", "max", "on"]
    assert inst[("worker", "dev")].scale == {"min": 0, "max": 5, "on": {"consumes": "jobs", "lag": 10}} and inst[("worker", "dev")].replicas is None


def test_the_component_scale_is_inherited_with_min_defaulting_to_one_ac_120_21(mrepo):  # AC-120.21
    inst = by(model_of(mrepo))
    assert inst[("api", "staging")].scale == {"min": 1, "max": 4, "on": {"memory": 60}} and inst[("api", "staging")].replicas is None


def test_an_instance_scale_replaces_the_component_scale_as_a_whole_ac_120_21(mrepo):  # AC-120.21
    assert by(model_of(mrepo))[("worker", "staging")].scale == {"min": 1, "max": 3, "on": {"cache": "sessions", "list": "jobs", "length": 7}}


def test_an_unscaled_instance_shows_its_replicas_and_scale_none_ac_120_21(mrepo):  # AC-120.21
    inst = by(model_of(mrepo))
    assert (inst[("api", "prod")].replicas, inst[("api", "prod")].scale) == (3, None)
    assert all((inst[("plain", e)].replicas, inst[("plain", e)].scale) == (2, None) for e in ("dev", "staging", "prod"))


def test_the_model_json_has_scale_after_replicas_for_every_instance_ac_120_21(mrepo, capsys):  # AC-120.21
    d = show_json(mrepo, capsys)
    assert d["schema"] == 2
    rows = {(i["component"], i["environment"]): i for i in d["instances"]}
    assert all("scale" in i for i in rows.values())
    for i in rows.values():
        keys = list(i)
        assert keys.index("scale") == keys.index("replicas") + 1
    assert rows[("api", "dev")]["scale"] == {"min": 2, "max": 6, "on": {"cpu": 70}} and rows[("api", "dev")]["replicas"] is None
    assert rows[("worker", "staging")]["scale"]["on"] == {"cache": "sessions", "list": "jobs", "length": 7}
    assert rows[("api", "prod")]["scale"] is None and rows[("api", "prod")]["replicas"] == 3
    assert rows[("plain", "dev")]["scale"] is None and rows[("plain", "dev")]["replicas"] == 2


def test_the_model_json_has_autoscaling_after_backup_for_every_environment_ac_120_16(mrepo, capsys):  # AC-120.16
    envs = {e["name"]: e for e in show_json(mrepo, capsys)["environments"]}
    assert {n: e["autoscaling"] for n, e in envs.items()} == {"dev": "keda", "staging": "keda", "prod": None}
    for e in envs.values():
        keys = list(e)
        assert keys.index("autoscaling") == keys.index("backup") + 1


def test_cpu_and_memory_only_systems_and_unscaled_ones_show_autoscaling_null_ac_120_16(tmp_path, capsys):  # AC-120.16
    write_system(tmp_path / "a", sdoc(cpu(5)))
    assert {e["name"]: e["autoscaling"] for e in show_json(tmp_path / "a", capsys)["environments"]} == {"dev": None, "staging": None, "prod": None}
    write_system(tmp_path / "b", sdoc(None, replicas=2))
    assert {e["name"]: e["autoscaling"] for e in show_json(tmp_path / "b", capsys)["environments"]} == {"dev": None, "staging": None, "prod": None}


def test_the_model_environment_object_carries_autoscaling_ac_120_16(mrepo):  # AC-120.16
    envs = {e.name: e for e in model_of(mrepo).environments}
    assert [envs[n].autoscaling for n in ("dev", "staging", "prod")] == ["keda", "keda", None]


@pytest.mark.parametrize("bad", [5, None, [1], {"max": "x", "on": {"cpu": 70}}, {"max": 5}, {"max": 5, "on": 3}], ids=["int", "null", "list", "string-max", "no-on", "scalar-on"])
def test_a_malformed_scale_never_breaks_the_model_ac_120_21(tmp_path, bad):  # AC-120.21
    assert hasattr(mod("model").Instance, "__dataclass_fields__") and "scale" in mod("model").Instance.__dataclass_fields__
    write_system(tmp_path, system(None, {"api": comp("api", resources=RES, scale=bad)}))
    assert [i.environment for i in model_of(tmp_path).instances] == ["dev", "staging", "prod"]


def test_a_non_integer_max_is_kept_as_declared_ac_120_21(tmp_path):  # AC-120.21
    write_system(tmp_path, system(None, {"api": comp("api", resources=RES, scale={"max": "x", "on": {"cpu": 70}})}))
    assert by(model_of(tmp_path))[("api", "dev")].scale == {"min": 1, "max": "x", "on": {"cpu": 70}}


def test_an_external_component_never_scales_in_the_model_ac_120_21(tmp_path):  # AC-120.21
    from broker_fixtures import ext_comp
    write_system(tmp_path, system(None, {"stock": ext_comp("stock")}))
    assert by(model_of(tmp_path))[("stock", "dev")].scale is None


def test_the_model_agrees_with_the_renderer_on_scaled_instances_and_autoscaling_ac_120_16(mrepo):  # AC-120.16
    r = platform_render_module("render_120_agree")
    s = r.load_system(mrepo / APP)
    m = model_of(mrepo)
    assert s["cfg"]["autoscaling"] == {e.name: e.autoscaling for e in m.environments}
    for env in ("dev", "staging", "prod"):
        assert r.scaled_instances(s["services"], env) == [i.component for i in m.instances if i.environment == env and i.scale is not None], env
    for svc in s["services"]:
        for env in svc["environments"]:
            want = by(m)[(svc["name"], env)].scale
            got = svc["_eff"][env]["scale"]
            assert (got is None) == (want is None)
            if got:
                assert {"min": got["min"], "max": got["max"], "on": got["on"]} == want


# ---------------- AC-120.16 / .21: cplat model show (text) ----------------

def test_an_environment_line_ends_with_autoscaling_keda_when_derived_ac_120_16(mrepo, capsys):  # AC-120.16
    out = show_text(mrepo, capsys)
    envs = out[out.index("Environments (promotion order):") + 1:][:3]
    assert envs[0].startswith("  dev  host ") and envs[0].endswith("  autoscaling keda")
    assert envs[1].startswith("  staging  ") and envs[1].endswith("  autoscaling keda")
    assert envs[2].startswith("  prod  ") and "autoscaling" not in envs[2]


def test_an_environment_without_keda_prints_no_autoscaling_text_ac_120_16(tmp_path, capsys):  # AC-120.16
    write_system(tmp_path, sdoc(cpu(5)))
    out = show_text(tmp_path, capsys)
    assert not [ln for ln in out if "autoscaling" in ln]
    assert inst_line(out, "api", "dev").endswith(f"  replicas -  namespace shop-dev  url -  scale 1{EN}5 on cpu 70%")


def inst_line(out, component, env):
    return next(ln for ln in out if ln.startswith(f"  {component}  {env}  "))


def test_a_scaled_instance_line_prints_replicas_dash_and_its_bounds_and_trigger_ac_120_21(mrepo, capsys):  # AC-120.21
    out = show_text(mrepo, capsys)
    assert inst_line(out, "api", "dev") == f"  api  dev  not pinned  replicas -  namespace shop-dev  url -  scale 2{EN}6 on cpu 70%"
    assert inst_line(out, "api", "staging") == f"  api  staging  not pinned  replicas -  namespace shop-staging  url -  scale 1{EN}4 on memory 60%"
    assert inst_line(out, "worker", "dev") == f"  worker  dev  not pinned  replicas -  namespace shop-dev  url -  scale 0{EN}5 on consumes jobs lag 10"
    assert inst_line(out, "worker", "staging") == (f"  worker  staging  not pinned  replicas -  namespace shop-staging  url -  "
                                                   f"scale 1{EN}3 on cache sessions list jobs length 7")


def test_an_unscaled_instance_line_does_not_change_ac_120_21(mrepo, capsys):  # AC-120.21
    out = show_text(mrepo, capsys)
    assert "scale" in inst_line(out, "api", "dev"), "while a scaled one in the same table does"
    assert inst_line(out, "api", "prod") == "  api  prod  not pinned  replicas 3  namespace shop-prod  url -"
    assert inst_line(out, "plain", "dev") == "  plain  dev  not pinned  replicas 2  namespace shop-dev  url -"


# ---------------- AC-120.22: system status ----------------

class Kube:
    """Answers `kubectl --context C ... get applications` (every Argo application Synced/Healthy) and the Deployment's `.spec.replicas`."""

    def __init__(self, apps, counts, good=("ctx-good",), no_count=False):
        self.apps, self.counts, self.good, self.no_count, self.calls = apps, counts, set(good), no_count, []

    def __call__(self, cmd):
        self.calls.append(list(cmd))
        if cmd[0] != "kubectl":
            return None
        ctx = cmd[cmd.index("--context") + 1]
        if ctx not in self.good:
            return None
        if "deployments.apps" in cmd:
            ns, name = cmd[cmd.index("-n") + 1], cmd[cmd.index("deployments.apps") + 1]
            return None if self.no_count else self.counts.get((ns, name))
        return json.dumps({"items": [{"metadata": {"name": a}, "status": {"sync": {"status": "Synced"}, "health": {"status": "Healthy"}}} for a in self.apps]})

    def scale_calls(self):
        return [c for c in self.calls if "deployments.apps" in c]


@pytest.fixture()
def world(tmp_path, monkeypatch):
    import status
    d = write_system(tmp_path, queue_system(lag()))     # worker scaled 1..5 in every environment, api unscaled
    m = mod("model").load_dir(d)
    apps = [i.argo_application for i in m.instances]
    kube = Kube(apps, {("shop-dev", "worker"): "3", ("shop-staging", "worker"): "1", ("shop-prod", "worker"): "5"})
    monkeypatch.setattr(status, "sh", kube)
    w = SimpleNamespace(repo=tmp_path, kube=kube)
    return w


def status_json(w, capsys, *extra) -> dict:
    assert cplat.main(["system", "status", "--json", "--repo-dir", str(w.repo), *extra]) == 0
    return json.loads(capsys.readouterr().out)


def cell(doc, component, env):
    return next(r for r in doc["rows"] if r["component"] == component)["cells"][env]


def status_text(w, capsys, *extra) -> str:
    assert cplat.main(["system", "status", "--repo-dir", str(w.repo), *extra]) == 0
    return capsys.readouterr().out


def test_a_scaled_cell_carries_the_replica_count_and_the_bounds_ac_120_22(world, capsys):  # AC-120.22
    doc = status_json(world, capsys, "--context", "ctx-good")
    assert cell(doc, "worker", "dev")["scale"] == {"replicas": 3, "min": 1, "max": 5}
    assert list(cell(doc, "worker", "dev")["scale"]) == ["replicas", "min", "max"]
    assert cell(doc, "worker", "prod")["scale"] == {"replicas": 5, "min": 1, "max": 5}


def test_the_replica_count_is_read_from_the_deployment_spec_of_the_environment_ac_120_22(world, capsys):  # AC-120.22
    status_json(world, capsys, "--context", "ctx-good")
    want = ["kubectl", "--context", "ctx-good", "-n", "shop-dev", "get", "deployments.apps", "worker", "-o", "jsonpath={.spec.replicas}"]
    assert want in world.kube.scale_calls()
    assert {c[c.index("-n") + 1] for c in world.kube.scale_calls()} == {"shop-dev", "shop-staging", "shop-prod"}
    assert {c[c.index("deployments.apps") + 1] for c in world.kube.scale_calls()} == {"worker"}


def test_the_text_cell_ends_with_the_count_and_the_bounds_ac_120_22(world, capsys):  # AC-120.22
    out = status_text(world, capsys, "--context", "ctx-good")
    assert f"argo Synced/Healthy  replicas 3 (1{EN}5)" in out and f"replicas 5 (1{EN}5)" in out


def test_a_cluster_that_cannot_be_reached_shows_a_question_mark_ac_120_22(world, capsys):  # AC-120.22
    doc = status_json(world, capsys, "--context", "ctx-bad")
    assert cell(doc, "worker", "dev")["scale"] == {"replicas": None, "min": 1, "max": 5}
    out = status_text(world, capsys, "--context", "ctx-bad")
    assert f"replicas ? (1{EN}5)" in out and not re.search(r"replicas \d", out)


def test_a_failing_deployment_read_shows_a_question_mark_ac_120_22(world, capsys):  # AC-120.22
    world.kube.no_count = True
    doc = status_json(world, capsys, "--context", "ctx-good")
    assert cell(doc, "worker", "dev")["scale"]["replicas"] is None
    assert f"replicas ? (1{EN}5)" in status_text(world, capsys, "--context", "ctx-good")


def test_an_environment_without_a_context_shows_a_question_mark_and_reads_nothing_ac_120_22(world, capsys):  # AC-120.22
    doc = status_json(world, capsys, "--context", "dev=ctx-good")
    assert cell(doc, "worker", "dev")["scale"]["replicas"] == 3
    assert cell(doc, "worker", "staging")["scale"] == {"replicas": None, "min": 1, "max": 5}
    assert {c[c.index("-n") + 1] for c in world.kube.scale_calls()} == {"shop-dev"}


def test_without_any_context_nothing_is_read_and_the_count_is_unknown_ac_120_22(world, capsys):  # AC-120.22
    doc = status_json(world, capsys)
    assert cell(doc, "worker", "dev")["scale"] == {"replicas": None, "min": 1, "max": 5}
    assert world.kube.scale_calls() == []
    assert f"replicas ? (1{EN}5)" in status_text(world, capsys)


def test_the_bounds_show_zero_for_a_scale_to_zero_instance_ac_120_22(tmp_path, monkeypatch, capsys):  # AC-120.22
    import status
    d = write_system(tmp_path, queue_system(lag(min=0)))
    apps = [i.argo_application for i in mod("model").load_dir(d).instances]
    monkeypatch.setattr(status, "sh", Kube(apps, {("shop-dev", "worker"): "0"}))
    w = SimpleNamespace(repo=tmp_path)
    assert cell(status_json(w, capsys, "--context", "ctx-good"), "worker", "dev")["scale"] == {"replicas": 0, "min": 0, "max": 5}
    assert f"replicas 0 (0{EN}5)" in status_text(w, capsys, "--context", "ctx-good")


def test_cells_of_unscaled_instances_do_not_change_ac_120_22(world, capsys):  # AC-120.22
    doc = status_json(world, capsys, "--context", "ctx-good")
    assert all("scale" not in c for c in next(r for r in doc["rows"] if r["component"] == "api")["cells"].values())
    out = status_text(world, capsys, "--context", "ctx-good")
    api_line = next(ln for ln in out.splitlines() if ln.strip().startswith("api "))
    assert "replicas" not in api_line
    assert world.kube.scale_calls() and all(c[c.index("deployments.apps") + 1] == "worker" for c in world.kube.scale_calls())


# ---------------- AC-120.5: component set ----------------

SCALED = "scale and replicas exclude each other"


def edit(repo, fn):
    doc = sysdoc(repo)
    fn(doc["components"]["todo-api"])
    (repo / APP / "system.yaml").write_text(yaml.safe_dump(doc, sort_keys=False))
    commit(repo)


@pytest.fixture()
def api(gitops5):
    assert run("component", "add", "todo-api", "--repo-dir", gitops5) == 0
    commit(gitops5)

    def declare(c):
        c["resources"] = RES
        c["instances"] = {"dev": {}, "staging": {}, "prod": {}}
    edit(gitops5, declare)
    return gitops5


def snapshot(repo):
    return files(repo), git(repo, "rev-parse", "HEAD"), git(repo, "branch", "--show-current"), git(repo, "status", "--porcelain")


def refuse(repo, capsys, *argv, needle, hint="edit applications/shop/system.yaml, then run component set again"):
    before = snapshot(repo)
    rc, _, err = run("component", "set", "todo-api", *argv, "--repo-dir", repo, capsys=capsys)
    assert rc == 1 and needle in err, err
    assert f"fix: {hint}" in err
    assert snapshot(repo) == before
    return err


def test_replicas_on_an_instance_with_its_own_scale_is_refused_naming_the_key_ac_120_5(api, capsys):  # AC-120.5
    edit(api, lambda c: c["instances"].update({"staging": {"scale": cpu(4)}}))
    refuse(api, capsys, "--instance", "staging", "--replicas", "3",
           needle=f"todo-api is scaled in staging (components.todo-api.instances.staging.scale): {SCALED}; "
                  f"remove components.todo-api.instances.staging.scale from system.yaml first")


def test_replicas_on_an_instance_that_inherits_the_component_scale_names_the_component_key_ac_120_5(api, capsys):  # AC-120.5
    edit(api, lambda c: c.update({"scale": cpu(4)}))
    refuse(api, capsys, "--instance", "staging", "--replicas", "3",
           needle=f"todo-api is scaled in staging (components.todo-api.scale): {SCALED}; remove components.todo-api.scale from system.yaml first")


def test_replicas_without_an_instance_is_refused_while_the_component_has_a_scale_ac_120_5(api, capsys):  # AC-120.5
    edit(api, lambda c: c.update({"scale": cpu(4)}))
    refuse(api, capsys, "--replicas", "3",
           needle=f"todo-api is scaled (components.todo-api.scale): {SCALED}; remove components.todo-api.scale from system.yaml first")


def test_a_dry_run_refuses_the_same_way_and_writes_nothing_ac_120_5(api, capsys):  # AC-120.5
    edit(api, lambda c: c.update({"scale": cpu(4)}))
    refuse(api, capsys, "--instance", "dev", "--replicas", "2", "--dry-run", needle="todo-api is scaled in dev (components.todo-api.scale)")


def test_an_instance_with_its_own_replicas_under_a_component_scale_may_be_changed_ac_120_5(api):  # AC-120.5
    edit(api, lambda c: (c.update({"scale": cpu(4)}), c["instances"].update({"staging": {"replicas": 1}})))
    assert run("component", "set", "todo-api", "--instance", "staging", "--replicas", "3", "--repo-dir", api) == 0
    c = sysdoc(api)["components"]["todo-api"]
    assert c["instances"]["staging"] == {"replicas": 3} and c["scale"] == cpu(4)
    assert render_check(api).returncode == 0


def test_an_unscaled_instance_next_to_a_scaled_one_may_be_changed_ac_120_5(api):  # AC-120.5
    edit(api, lambda c: c["instances"].update({"staging": {"scale": cpu(4)}}))
    assert run("component", "set", "todo-api", "--instance", "prod", "--replicas", "2", "--repo-dir", api) == 0
    assert sysdoc(api)["components"]["todo-api"]["instances"]["prod"] == {"replicas": 2}


def test_replicas_on_the_component_is_fine_when_only_an_instance_is_scaled_ac_120_5(api):  # AC-120.5
    edit(api, lambda c: c["instances"].update({"staging": {"scale": cpu(4)}}))
    assert run("component", "set", "todo-api", "--replicas", "2", "--repo-dir", api) == 0
    assert sysdoc(api)["components"]["todo-api"]["replicas"] == 2 and render_check(api).returncode == 0


def test_the_refusal_is_not_a_crash_and_other_options_still_work_on_a_scaled_component_ac_120_5(api):  # AC-120.5
    edit(api, lambda c: c.update({"scale": cpu(4)}))
    assert run("component", "set", "todo-api", "--env", "LOG_LEVEL=DEBUG", "--repo-dir", api) == 0
    assert sysdoc(api)["components"]["todo-api"]["env"]["LOG_LEVEL"] == "DEBUG"


# ---------------- AC-120.18 / .17 / .25 / .27: doctor ----------------

def kube(monkeypatch, keda=None, metrics_server=None, metrics=None, kubectl=True, ctx="k3d-shop"):
    """Fakes doctor's kubectl: the images behind the operator selectors, the metrics APIService and the current context."""
    import doctor
    monkeypatch.setattr(doctor.shutil, "which", lambda t: f"/usr/bin/{t}" if kubectl else None)
    seen: list[list[str]] = []

    def out(text, rc=0):
        return SimpleNamespace(stdout=text, stderr="", returncode=rc)

    def fake_run(cmd, *a, **k):
        cmd = [str(c) for c in cmd]
        seen.append(cmd)
        if "-l" in cmd:
            sel = cmd[cmd.index("-l") + 1]
            if sel == "app.kubernetes.io/name=keda-operator":     # spec 120 design: the chart labels its Deployment keda-operator
                return out(f"ghcr.io/kedacore/keda:{keda}") if keda else out("")
            if sel == "app.kubernetes.io/name=metrics-server":
                return out(f"registry.k8s.io/metrics-server/metrics-server:v{metrics_server}") if metrics_server else out("")
            return out("")
        if any(arg == "v1beta1.metrics.k8s.io" for arg in cmd):   # an argv element (CodeQL read `in` as URL sanitizing)
            return out(metrics or "", 0 if metrics else 1)
        if cmd[:3] == ["kubectl", "config", "current-context"]:
            return out(ctx + "\n")
        return out("")
    monkeypatch.setattr(doctor, "run", fake_run)
    return seen


def keda_rows(repo):
    import doctor
    return [c for c in doctor.check_operators(repo) if c["name"] == "operator keda"]


def queue_dev(**top):
    """worker scales on a cache list in dev only."""
    return cache_system(None, {"dev": {"scale": length()}}, **top)


def owner(doc, *envs):
    for e in envs:
        doc["environments"][e]["operators"] = "owner"
    return doc


def test_doctor_is_ok_when_keda_matches_and_names_the_queue_triggered_instances_ac_120_18(tmp_path, monkeypatch):  # AC-120.18
    kube(monkeypatch, keda="2.19.0")
    write_system(tmp_path, queue_dev())
    [row] = keda_rows(tmp_path)
    assert row["status"] == "ok"
    assert row["detail"] == "installed 2.19.0, expected 2.19.0 (Argo CD application operator-keda); queue-triggered: worker (dev)"


def test_doctor_warns_naming_a_missing_keda_ac_120_18(tmp_path, monkeypatch):  # AC-120.18
    kube(monkeypatch)
    write_system(tmp_path, queue_dev())
    [row] = keda_rows(tmp_path)
    assert row["status"] == "warn"
    assert row["detail"] == "not installed in the current kube context, expected 2.19.0 (Argo CD application operator-keda); queue-triggered: worker (dev)"
    assert row["fix"] == "apply operators/root.yaml once: KUBE_CONTEXT=k3d-shop devbox run bootstrap (local: devbox run cluster-up)"


def test_doctor_warns_naming_both_versions_when_keda_differs_ac_120_25(tmp_path, monkeypatch):  # AC-120.25
    kube(monkeypatch, keda="2.18.0")
    write_system(tmp_path, queue_dev())
    [row] = keda_rows(tmp_path)
    assert row["status"] == "warn"
    assert row["detail"] == "installed 2.18.0, expected 2.19.0 (Argo CD application operator-keda); queue-triggered: worker (dev)"
    assert row["fix"] == "sync operator-keda in Argo CD"


def test_doctor_checks_an_owner_managed_environment_and_names_instances_and_version_ac_120_18(tmp_path, monkeypatch):  # AC-120.18
    write_system(tmp_path, owner(queue_dev(), "dev"))
    kube(monkeypatch)
    [row] = keda_rows(tmp_path)
    assert row["status"] == "warn"
    assert row["detail"] == "not installed in the current kube context, expected 2.19.0 (operators: owner in dev); queue-triggered: worker (dev)"
    assert row["fix"] == "install the keda chart 2.19.0 (operator 2.19.0)"
    kube(monkeypatch, keda="2.20.1")
    [row] = keda_rows(tmp_path)
    assert row["status"] == "warn" and "installed 2.20.1, expected 2.19.0 (operators: owner in dev)" in row["detail"]
    assert row["fix"] == "move the keda chart to 2.19.0 (operator 2.19.0)"
    kube(monkeypatch, keda="2.19.0")
    [row] = keda_rows(tmp_path)
    assert row["status"] == "ok" and row["detail"].endswith("(operators: owner in dev); queue-triggered: worker (dev)")


def test_the_keda_row_lists_every_queue_triggered_instance_in_model_order_and_no_cpu_ones_ac_120_18(tmp_path, monkeypatch):  # AC-120.18
    kube(monkeypatch, keda="2.19.0")
    b = comp("b", ["sessions"], resources=RES, scale=length())
    a = comp("a", ["sessions"], resources=RES, envs=("dev", "staging"), scale=length())
    c = comp("c", resources=RES, scale=cpu(3))
    write_system(tmp_path, system({"sessions": cache()}, {"b": b, "a": a, "c": c}))
    [row] = keda_rows(tmp_path)
    assert row["detail"].endswith("; queue-triggered: b (dev), b (staging), b (prod), a (dev), a (staging)")


def test_doctor_has_no_keda_row_without_a_queue_trigger_or_kubectl_ac_120_18(tmp_path, monkeypatch):  # AC-120.18
    kube(monkeypatch)
    write_system(tmp_path / "with", queue_dev())
    assert len(keda_rows(tmp_path / "with")) == 1, "a queue-triggered instance does get one"
    write_system(tmp_path / "cpu", sdoc(cpu(5)))
    write_system(tmp_path / "none", sdoc(None, replicas=2))
    for d in ("cpu", "none"):
        assert keda_rows(tmp_path / d) == [], d
    kube(monkeypatch, kubectl=False)
    write_system(tmp_path / "queue", queue_dev())
    assert keda_rows(tmp_path / "queue") == []


def test_doctor_lists_keda_after_nack_and_before_metrics_server_ac_120_25(tmp_path, monkeypatch):  # AC-120.25
    import doctor
    kube(monkeypatch)
    (tmp_path / ".copier-answers.yml").write_text("resource_metrics: install\n")
    doc = queue_system(comps={"api": comp("api", provides=["jobs"], resources=RES, scale=cpu(3)),
                              "worker": comp("worker", consumes=["jobs"], resources=RES, envs=("dev",), scale=lag())})
    write_system(tmp_path, doc)
    assert [c["name"] for c in doctor.check_operators(tmp_path)] == ["operator nack", "operator keda", "operator metrics-server"]


def ms_rows(repo):
    import doctor
    return [c for c in doctor.check_operators(repo) if c["name"] == "operator metrics-server"]


def test_doctor_checks_metrics_server_only_for_the_install_answer_and_a_cpu_instance_ac_120_27(tmp_path, monkeypatch):  # AC-120.27
    kube(monkeypatch, metrics_server="0.9.0")
    doc = sdoc(None, dev={"scale": cpu(5)})
    write_system(tmp_path / "a", doc)
    assert ms_rows(tmp_path / "a") == [], "no answer means provided"
    write_system(tmp_path / "b", doc)
    (tmp_path / "b" / ".copier-answers.yml").write_text("resource_metrics: provided\n")
    assert ms_rows(tmp_path / "b") == []
    write_system(tmp_path / "c", doc)
    (tmp_path / "c" / ".copier-answers.yml").write_text("resource_metrics: install\n")
    [row] = ms_rows(tmp_path / "c")
    assert row["status"] == "ok" and row["detail"] == "installed 0.9.0, expected 0.9.0 (Argo CD application operator-metrics-server)"
    write_system(tmp_path / "d", queue_dev())
    (tmp_path / "d" / ".copier-answers.yml").write_text("resource_metrics: install\n")
    assert ms_rows(tmp_path / "d") == [], "a queue trigger needs no resource metrics"


def test_doctor_warns_when_metrics_server_is_missing_or_at_another_version_ac_120_25(tmp_path, monkeypatch):  # AC-120.25
    write_system(tmp_path, sdoc(None, dev={"scale": cpu(5)}))
    (tmp_path / ".copier-answers.yml").write_text("resource_metrics: install\n")
    kube(monkeypatch)
    [row] = ms_rows(tmp_path)
    assert row["status"] == "warn" and row["detail"] == "not installed in the current kube context, expected 0.9.0 (Argo CD application operator-metrics-server)"
    kube(monkeypatch, metrics_server="0.8.0")
    [row] = ms_rows(tmp_path)
    assert row["status"] == "warn" and row["detail"] == "installed 0.8.0, expected 0.9.0 (Argo CD application operator-metrics-server)"
    assert row["fix"] == "sync operator-metrics-server in Argo CD"


def metrics_rows(repo):
    import doctor
    return doctor.check_metrics(repo)


def test_doctor_says_when_the_cluster_serves_resource_metrics_ac_120_17(tmp_path, monkeypatch):  # AC-120.17
    kube(monkeypatch, metrics="True")
    write_system(tmp_path, sdoc(None, dev={"scale": cpu(5)}))
    [row] = metrics_rows(tmp_path)
    assert row["name"] == "resource metrics" and row["status"] == "ok"
    assert row["detail"] == "the cluster serves metrics.k8s.io; cpu and memory triggers: api (dev)"


def test_doctor_reads_the_apiservice_condition_ac_120_17(tmp_path, monkeypatch):  # AC-120.17
    seen = kube(monkeypatch, metrics="True")
    write_system(tmp_path, sdoc(None, dev={"scale": cpu(5)}))
    metrics_rows(tmp_path)
    assert ["kubectl", "get", "apiservices.apiregistration.k8s.io", "v1beta1.metrics.k8s.io", "-o",
            'jsonpath={.status.conditions[?(@.type=="Available")].status}'] in seen


@pytest.mark.parametrize("answer", ["False", "Unknown", ""])
def test_doctor_warns_when_the_cluster_serves_no_resource_metrics_ac_120_17(tmp_path, monkeypatch, answer):  # AC-120.17
    kube(monkeypatch, metrics=answer)
    write_system(tmp_path, sdoc(None, dev={"scale": cpu(5)}, staging={"scale": {"max": 3, "on": {"memory": 50}}}))
    [row] = metrics_rows(tmp_path)
    assert row["name"] == "resource metrics" and row["status"] == "warn"
    assert row["detail"] == ("the current kube context serves no resource metrics (metrics.k8s.io); "
                             "the cpu and memory triggers of api (dev), api (staging) cannot scale")
    assert row["fix"] == ("set resource_metrics: install in .copier-answers.yml and run devbox run render (the platform then installs metrics-server 3.14.0), "
                          "or install a metrics server yourself")


def test_the_fix_changes_when_the_answer_is_already_install_ac_120_17(tmp_path, monkeypatch):  # AC-120.17
    kube(monkeypatch, metrics="")
    write_system(tmp_path, sdoc(None, dev={"scale": cpu(5)}))
    (tmp_path / ".copier-answers.yml").write_text("resource_metrics: install\n")
    [row] = metrics_rows(tmp_path)
    assert row["status"] == "warn"
    assert row["fix"] == "apply operators/root.yaml once: KUBE_CONTEXT=k3d-shop devbox run bootstrap (local: devbox run cluster-up)"


def test_there_is_no_resource_metrics_row_without_a_cpu_or_memory_instance_or_kubectl_ac_120_17(tmp_path, monkeypatch):  # AC-120.17
    kube(monkeypatch, metrics="True")
    write_system(tmp_path / "queue", queue_dev())
    write_system(tmp_path / "none", sdoc(None, replicas=2))
    assert metrics_rows(tmp_path / "queue") == [] and metrics_rows(tmp_path / "none") == []
    kube(monkeypatch, metrics="True", kubectl=False)
    write_system(tmp_path / "cpu", sdoc(cpu(5)))
    assert metrics_rows(tmp_path / "cpu") == []


def test_the_metrics_check_runs_after_the_broker_check_in_both_doctor_paths_ac_120_17():  # AC-120.17
    src = (ROOT / "scripts" / "cplat" / "doctor.py").read_text()
    calls = [m.start() for m in re.finditer(r"out \+= check_brokers\(repo\)", src)]
    assert len(calls) == 2
    for at in calls:
        assert re.match(r"out \+= check_brokers\(repo\)\n\s+out \+= check_metrics\(repo\)", src[at:])


# ---------------- AC-120.17 / .25 / .27: the cluster scripts ----------------

def local() -> str:
    return (T / "scripts" / "local-cluster.sh").read_text()


def test_cluster_up_installs_or_waits_for_keda_ac_120_17():  # AC-120.17
    text = local()
    for needle in ("WITH_KEDA", "KEDA_VERSION", "operators/apps/keda.yaml", "2.19.0", "deploy/keda-operator", "deploy/keda-operator-metrics-apiserver",
                   "deploy/keda-admission-webhooks", 'with_keda" = 1', "operators/root.yaml", "targetNamespace: keda", "name: keda", "chart: keda",
                   "createNamespace: true"):
        assert needle in text, f"local-cluster.sh lacks {needle!r}"
    assert re.search(r"\bscaledobjects\.keda\.sh\b", text) and re.search(r"https://kedacore\.github\.io/charts", text)


def test_cluster_up_forces_keda_only_when_asked_and_defaults_to_the_operator_file_ac_120_17():  # AC-120.17
    text = local()
    assert re.search(r"(?m)^#\s+WITH_KEDA\s+1 = ", text) and re.search(r"(?m)^#\s+KEDA_VERSION\s", text)
    assert "exists" in re.search(r"(?m)^#\s+WITH_KEDA.*$", text).group(0)


def test_cluster_up_handles_the_metrics_server_like_the_other_operators_ac_120_17():  # AC-120.17
    text = local()
    for needle in ("WITH_METRICS_SERVER", "METRICS_SERVER_VERSION", "operators/apps/metrics-server.yaml", "3.14.0", "name: metrics-server", "targetNamespace: kube-system"):
        assert needle in text, f"local-cluster.sh lacks {needle!r}"
    assert re.search(r"(?m)^#\s+WITH_METRICS_SERVER\s+1 = .*exists", text) and re.search(r"(?m)^#\s+METRICS_SERVER_VERSION\s", text)
    assert re.search(r"https://kubernetes-sigs\.github\.io/metrics-server", text)


def test_a_new_cluster_without_k3s_own_metrics_server_only_when_the_pinned_one_is_installed_ac_120_17():  # AC-120.17
    text = local()
    assert '--k3s-arg "--disable=metrics-server@server:*"' in text
    assert re.search(r"(?is)WITH_METRICS_SERVER.{0,1500}--disable=metrics-server@server|--disable=metrics-server@server.{0,1500}WITH_METRICS_SERVER", text)


def test_cluster_up_waits_for_the_resource_metrics_and_only_warns_ac_120_17():  # AC-120.17
    text = local()
    warning = ("WARNING: the cluster serves no resource metrics yet (v1beta1.metrics.k8s.io is not Available); "
               "cpu and memory triggers cannot scale until it is")
    assert re.search(re.escape(warning), text)
    assert re.search(r"\bapiservices\.apiregistration\.k8s\.io/v1beta1\.metrics\.k8s\.io\b", text) and "Available" in text
    assert re.search(r"(?s)v1beta1\.metrics\.k8s\.io.{0,600}120|120.{0,600}v1beta1\.metrics\.k8s\.io", text)


def test_the_script_default_pins_match_the_versions_table_ac_120_25():  # AC-120.25
    r = platform_render_module("render_120_scripts")
    text = local()
    for name in ("keda", "metrics-server"):
        op = r.OPERATORS[name]
        assert op["chart_version"] in text and re.search(re.escape(op["repo_url"]), text), name


def test_the_cluster_repo_copy_of_the_cluster_script_is_byte_equal_ac_120_17():  # AC-120.17
    src, dst = T / "scripts" / "local-cluster.sh", ROOT / "templates" / "cluster-gitops" / "scripts" / "local-cluster.sh"
    assert "WITH_KEDA" in dst.read_text() and dst.read_bytes() == src.read_bytes()


def test_the_cluster_scripts_parse_ac_120_17():  # AC-120.17
    if not shutil.which("bash"):
        pytest.skip("no bash")
    for name in ("bootstrap.sh", "local-cluster.sh"):
        assert re.search(r"(?i)keda", (T / "scripts" / name).read_text()), name
        p = subprocess.run(["bash", "-n", str(T / "scripts" / name)], capture_output=True, text=True)
        assert p.returncode == 0, p.stderr


def test_bootstrap_waits_for_the_keda_crd_and_skips_the_metrics_server_ac_120_27():  # AC-120.27
    text = (T / "scripts" / "bootstrap.sh").read_text()
    assert re.search(r"(?m)^\s*keda\) crd=scaledobjects\.keda\.sh ;;", text)
    assert re.search(r"(?m)^\s*nack\) crd=streams\.jetstream\.nats\.io ;;", text) and re.search(r"(?m)^\s*\*\) continue ;;", text)
    assert not re.search(r"(?m)^\s*metrics-server\)", text), "metrics-server has no CRD and falls through"
    assert re.search(r"(?i)keda", text.split("set -euo", 1)[0]) and re.search(r"(?i)metrics-server", text.split("set -euo", 1)[0])


# ---------------- AC-120.17 / .27: the copier answer ----------------

QUESTION = ("Does the cluster already serve resource metrics (metrics.k8s.io)? provided: yes (k3s, k3d, GKE, AKS, EKS with its metrics-server add-on); "
            "install: the platform installs metrics-server when an instance scales on cpu or memory.")


def test_the_gitops_template_asks_resource_metrics_after_cluster_server_ac_120_27():  # AC-120.27
    doc = yaml.safe_load((T / "copier.yml").read_text())
    assert doc.get("resource_metrics") == {"type": "str", "help": QUESTION, "choices": ["provided", "install"], "default": "provided"}
    assert list(doc["resource_metrics"]) == ["type", "help", "choices", "default"]
    keys = list(doc)
    assert keys.index("resource_metrics") == keys.index("cluster_server") + 1


# ---------------- AC-120.25 / .27: cluster repos ----------------

@pytest.fixture()
def crepo(shared_renders, tmp_path, monkeypatch):
    repo = cluster_repo(shared_renders, tmp_path)
    s = stubs(tmp_path, monkeypatch)
    (repo / ".platform-version").write_text("platform: 5.1.0\n")
    return repo, s


def keda_doc(name="alpha", scale=None):
    doc = sys_doc(name)
    doc["resources"] = {"sessions": {"type": "cache"}}
    doc["components"]["api"] = comp("api", ["sessions"], resources=RES, scale=scale or length())
    return doc


def test_a_cluster_repo_may_list_keda_and_metrics_server_and_renders_the_same_applications_ac_120_25(shared_renders, tmp_path):  # AC-120.25
    repo = cluster_repo(shared_renders, tmp_path)
    got = render_ok(repo, base(operators=["keda", "metrics-server"]))
    assert yaml.safe_load(got["cluster/operators/keda.yaml"]) == expected_operator(KEDA)
    assert yaml.safe_load(got["cluster/operators/metrics-server.yaml"]) == expected_operator(METRICS)


def test_the_crds_flag_skips_an_operator_without_a_crd_ac_120_25(shared_renders, tmp_path):  # AC-120.25
    repo = cluster_repo(shared_renders, tmp_path)
    write_cluster(repo, base(operators=["cloudnative-pg", "keda", "metrics-server"]))
    p = render(repo, None, "--crds")
    assert p.returncode == 0, p.stderr
    assert p.stdout.splitlines() == ["cloudnative-pg clusters.postgresql.cnpg.io", f"keda {KEDA['crd']}"]


def test_the_cluster_check_asks_for_keda_for_a_queue_triggered_system_ac_120_27(crepo):  # AC-120.27
    repo, s = crepo
    system_repo(s["fixtures"], "acme/alpha-gitops", keda_doc())
    write_cluster(repo, base(systems={"alpha": {"repo": "acme/alpha-gitops"}}))
    render_ok(repo, repo.joinpath("cluster.yaml").read_text())
    p = script(repo, "check.py")
    out = p.stdout + p.stderr
    assert p.returncode == 1
    assert "ERROR: alpha (dev): needs keda, which cluster.yaml does not list in operators" in out
    assert "ERROR: alpha (staging): needs keda, which cluster.yaml does not list in operators" in out
    assert "needs metrics-server" not in out


def test_the_cluster_check_is_quiet_when_keda_is_listed_ac_120_27(crepo):  # AC-120.27
    repo, s = crepo
    system_repo(s["fixtures"], "acme/alpha-gitops", keda_doc())
    write_cluster(repo, base(operators=["keda", "external-secrets"], systems={"alpha": {"repo": "acme/alpha-gitops"}}))
    render_ok(repo, repo.joinpath("cluster.yaml").read_text())
    p = script(repo, "check.py")
    assert "needs keda" not in p.stdout + p.stderr


def test_the_cluster_check_asks_for_no_keda_without_a_queue_trigger_and_never_for_metrics_server_ac_120_27(crepo):  # AC-120.27
    repo, s = crepo
    doc = keda_doc(scale={"max": 3, "on": {"cpu": 60}})
    system_repo(s["fixtures"], "acme/alpha-gitops", doc)
    write_cluster(repo, base(systems={"alpha": {"repo": "acme/alpha-gitops"}}))
    render_ok(repo, repo.joinpath("cluster.yaml").read_text())
    out = script(repo, "check.py")
    assert "needs keda" not in out.stdout + out.stderr and "needs metrics-server" not in out.stdout + out.stderr


# ---------------- the e2e script ----------------

def e2e() -> str:
    return (ROOT / "tests" / "e2e" / "run.sh").read_text()


def need(text: str, *needles: str) -> None:
    for n in needles:
        assert n in text, f"tests/e2e/run.sh lacks {n!r}"


def test_the_e2e_script_declares_the_scaled_consumer_with_scale_to_zero_ac_120_23():  # AC-120.23 (needs a cluster)
    need(e2e(), "sstep", "sfail", "WITH_KEDA=1", "e2e-worker", "e2e-jobs", "e2e-worker:latest", "WORK_SECONDS", "min", "lag", "consumes")
    assert re.search(r"(?s)'min': 0.{0,40}'max': 5|\"min\": 0.{0,40}\"max\": 5|min: 0, max: 5", e2e())


def test_the_e2e_script_proves_the_pins_the_rendered_files_and_the_model_ac_120_25():  # AC-120.25 (needs a cluster)
    need(e2e(), "operators/apps/keda.yaml", "2.19.0", "keda-operator", "scaledobject.yaml", "operators/apps/metrics-server.yaml", "autoscaling")
    assert re.search(r"\bhelmcharts\.helm\.cattle\.io\b", e2e()) and re.search(r"\btriggerauthentications\.keda\.sh\b", e2e())
    assert re.search(r"\bscaledobjects\.keda\.sh\b", e2e())


def test_the_e2e_script_wakes_the_consumer_within_60_seconds_ac_120_14():  # AC-120.14 (needs a cluster)
    need(e2e(), "e2e.jobs.one", "readyReplicas")
    assert re.search(r"(?is)e2e\.jobs\.one.{0,1500}60", e2e())


def test_the_e2e_script_bursts_to_five_replicas_within_two_minutes_ac_120_10():  # AC-120.10 (needs a cluster)
    need(e2e(), "100", ".spec.replicas", "/jsz")
    assert re.search(r"(?is)(publish|burst).{0,2500}\b120\b", e2e())


def test_the_e2e_script_returns_to_zero_five_to_seven_minutes_after_the_queue_empties_ac_120_15():  # AC-120.15 (needs a cluster)
    assert re.search(r"(?s)\b295\b.{0,300}\b420\b|\b420\b.{0,300}\b295\b", e2e())


def test_the_e2e_script_ends_at_zero_replicas_and_checks_the_maximum_ac_120_23():  # AC-120.23 (needs a cluster)
    assert re.search(r"(?is)(maximum|max).{0,200}\b5\b", e2e())
    assert re.search(r"(?i)back to zero|reach(es|ed)? 0|zero replicas|replicas.{0,20}\b0\b", e2e())


def test_the_e2e_script_emulates_the_sync_with_the_live_replica_count_ac_120_19():  # AC-120.19 (needs a cluster)
    need(e2e(), "RespectIgnoreDifferences", ".metadata.generation", "ignoreDifferences")
    assert re.search(r"(?is)(unchanged|does not change|not change)", e2e())


def test_the_e2e_script_reads_the_status_of_a_scaled_instance_ac_120_22():  # AC-120.22 (needs a cluster)
    need(e2e(), "system status", "--json", "scale", f"0{EN}5")


def test_the_e2e_script_proves_the_cpu_horizontal_pod_autoscaler_and_the_metrics_source_ac_120_6():  # AC-120.6 (needs a cluster)
    need(e2e(), "hpa.yaml", "averageUtilization", "currentMetrics", "horizontalpodautoscalers.autoscaling")
    assert re.search(r"\bv1beta1\.metrics\.k8s\.io\b|resource metrics", e2e())


def test_the_e2e_script_runs_doctor_and_expects_the_keda_and_metrics_rows_ac_120_18():  # AC-120.18 (needs a cluster)
    need(e2e(), "operator keda", "resource metrics")
    assert re.search(r"(?is)operator keda.{0,800}e2e-worker|e2e-worker.{0,800}operator keda", e2e())


def test_the_e2e_script_refuses_replicas_on_a_scaled_instance_ac_120_5():  # AC-120.5 (needs a cluster)
    need(e2e(), "component set e2e-worker --instance dev --replicas 2", "components.e2e-worker.instances.dev.scale")


def test_the_e2e_script_proves_the_cache_trigger_with_30_entries_ac_120_12():  # AC-120.12 (needs a cluster)
    need(e2e(), "RPUSH", "e2e-sessions-app", "triggerauthentication.yaml")
    assert re.search(r"(?is)\b30\b.{0,800}RPUSH|RPUSH.{0,800}\b30\b", e2e())


def test_the_e2e_script_finds_no_credential_value_in_the_scaler_objects_ac_120_13():  # AC-120.13 (needs a cluster)
    assert re.search(r"(?is)scaledobject\.yaml.{0,3000}secret_val", e2e())


def test_the_e2e_script_switches_back_to_replicas_and_samples_the_count_ac_120_20():  # AC-120.20 (needs a cluster)
    need(e2e(), "keda-hpa-e2e-worker", "horizontalpodautoscalers.autoscaling")
    assert re.search(r"(?i)replicas['\"]?: 1\b", e2e())


def test_the_e2e_script_cleans_up_the_scaling_objects_before_the_remaining_steps_ac_120_27():  # AC-120.27 (needs a cluster)
    need(e2e(), "operators/apps/keda.yaml", "resource remove bus", "streams.jetstream.nats.io")
    assert re.search(r"(?i)clean-?up", e2e())


def test_the_e2e_script_header_budgets_the_scaling_steps_and_the_job_gets_90_minutes_ac_120_23():  # AC-120.23 (needs a cluster)
    assert re.search(r"(?is)(scal|keda).{0,400}13 minutes", e2e()[:9000])
    assert re.search(r"(?m)^\s*timeout-minutes:\s*90\b", (ROOT / ".github" / "workflows" / "e2e.yml").read_text())


# ---------------- docs, changelog, plugins ----------------

def domain_model() -> str:
    return (ROOT / "docs" / "DOMAIN-MODEL.md").read_text()


def scaling_section() -> str:
    text = domain_model()
    m = re.search(r"(?m)^(#{2,4}) Scaling an instance\s*$", text)
    assert m, "DOMAIN-MODEL.md has no section 'Scaling an instance'"
    rest = text[m.end():]
    nxt = re.search(rf"(?m)^#{{2,{len(m.group(1))}}} ", rest)
    return rest[:nxt.start()] if nxt else rest


def scale_forms(section: str) -> set[str]:
    """The `on:` forms of every YAML example that declares a scale (selected by content, not by position)."""
    forms: set[str] = set()

    def walk(node):
        if isinstance(node, dict):
            s = node.get("scale")
            if isinstance(s, dict) and isinstance(s.get("on"), dict):
                forms.add("+".join(sorted(s["on"])))
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
    for block in re.findall(r"```ya?ml\n(.*?)```", section, re.S):
        try:
            walk(yaml.safe_load(block))
        except yaml.YAMLError:
            continue
    return forms


def test_the_domain_model_has_a_scaling_section_with_one_example_per_trigger_form_ac_120_24():  # AC-120.24
    assert scale_forms(scaling_section()) >= {"cpu", "memory", "consumes+lag", "cache+length+list"}


def test_the_scaling_section_describes_the_rules_ac_120_24():  # AC-120.24
    text = scaling_section()
    for pattern in (r"\bmin\b", r"\bmax\b", r"1 to 20|1\.\.20|1-20", r"(?i)default", r"(?i)component", r"(?i)whole|replaces?", r"\breplicas\b", r"(?i)exclu|not both|together",
                    r"\bautoscaling\b", r"(?i)derived", r"(?i)scale to zero|zero replicas|min: 0", r"(?i)queue", r"(?i)exposed|request API|openapi",
                    r"(?i)keda", r"resource_metrics", r"(?i)ignoreDifferences|Argo CD", r"(?i)external broker", r"315|345|5 minutes"):
        assert re.search(pattern, text), f"the section lacks {pattern!r}"
    assert re.search(r"environments\.<env>\.autoscaling", text) and re.search(r"(?i)refus|fails?|unknown key", text)


def test_the_keys_tables_list_scale_for_components_and_instances_ac_120_24():  # AC-120.24
    rows = [ln for ln in domain_model().splitlines() if ln.startswith("| service or website component") or ln.startswith("| `components.<c>.instances.<env>`")]
    assert len(rows) == 2 and all("`scale`" in ln for ln in rows)
    assert "`scale`" not in next(ln for ln in domain_model().splitlines() if ln.startswith("| external component"))


def test_the_renderer_docstring_documents_scale_ac_120_24():  # AC-120.24
    doc = platform_render_module("render_120_doc").__doc__
    assert re.search(r"scale:\s*\{min: \d+, max: \d+, on: \{cpu: \d+\}\}", doc)
    for pattern in (r"on: \{memory: \d+\}", r"on: \{consumes: [\w-]+, lag: \d+\}", r"on: \{cache: [\w-]+, list: [\w-]+, length: \d+\}", r"resource_metrics", r"1\.\.20|1 to 20|1-20|at most 20"):
        assert re.search(pattern, doc), pattern


def test_the_user_journey_the_site_and_the_cluster_guide_describe_scaling_ac_120_24():  # AC-120.24
    assert "Scale an instance on load or on a queue" in (ROOT / "docs" / "USER-JOURNEY.md").read_text()
    site = (ROOT / "site" / "src" / "content" / "docs" / "concepts" / "domain-model.md").read_text()
    assert re.search(r"`scale`", site) and re.search(r"(?i)autoscal|replicas", site)
    clusters = (ROOT / "docs" / "CLUSTERS.md").read_text()
    assert re.search(r"\bkeda\b", clusters) and re.search(r"\bmetrics-server\b", clusters)


def plugin_versions(name):
    manifest = json.loads((ROOT / f"plugins/{name}/.claude-plugin/plugin.json").read_text())["version"]
    market = next(p["version"] for p in json.loads((ROOT / ".claude-plugin/marketplace.json").read_text())["plugins"] if p["name"] == name)
    return manifest, market


def test_the_component_system_and_platform_plugins_are_bumped_in_both_places_ac_120_5():  # AC-120.5
    assert plugin_versions("component") == ("1.3.0", "1.3.0")
    assert plugin_versions("system") == ("1.5.0", "1.5.0")   # spec 121: system plugin 1.5.0
    assert plugin_versions("platform") == ("1.3.0", "1.3.0")   # spec 121: platform plugin 1.3.0


def description(path) -> str:
    return re.search(r'(?m)^description:\s*"(.*)"\s*$', (ROOT / path).read_text()).group(1)


def test_the_component_set_docs_say_scaled_instances_refuse_replicas_ac_120_5():  # AC-120.5
    text = (ROOT / "plugins/component/commands/set.md").read_text()
    assert "scale" in text and re.search(r"(?i)exclude each other|refus", text) and "system.yaml" in text
    assert len(description("plugins/component/commands/set.md")) < 260
    assert "scale" in (ROOT / "plugins/component/README.md").read_text()


def test_the_status_docs_describe_the_replica_count_and_bounds_ac_120_22():  # AC-120.22
    text = (ROOT / "plugins/system/commands/status.md").read_text()
    assert f"replicas <n> (<min>{EN}<max>)" in text.replace("`", "") and re.search(r"\?", text)
    assert "replicas" in (ROOT / "plugins/system/README.md").read_text() and len(description("plugins/system/commands/status.md")) < 260


def test_the_doctor_docs_list_the_keda_and_metrics_rows_ac_120_18():  # AC-120.18
    text = (ROOT / "plugins/platform/commands/doctor.md").read_text()
    for needle in ("operator keda", "operator metrics-server", "resource metrics"):
        assert needle in text, needle
    assert re.search(r"(?i)keda", (ROOT / "plugins/platform/README.md").read_text()) and len(description("plugins/platform/commands/doctor.md")) < 260


def test_the_changelog_lists_scaling_above_the_broker_in_a_minor_section_that_is_not_breaking_ac_120_25():  # AC-120.25
    text = (ROOT / "docs" / "CHANGELOG.md").read_text()
    sections = re.split(r"(?m)^(?=## \[)", text)
    hits = [s for s in sections if s.startswith("## [") and re.search(r"(?i)spec 120|ADR-066", s)]
    assert hits, "the change is listed"
    assert re.match(r"## \[(Unreleased|5\.[1-9]\d*\.0)\]", hits[0].splitlines()[0])
    entry = next(e for e in re.split(r"\n\s*\n", hits[0]) if re.search(r"(?i)spec 120|ADR-066", e))
    assert "BREAKING" not in entry
    for needle in ("2.19.0", "3.14.0", "resource_metrics", "ADR-066", "ADR-067", "1.3.0", "1.4.0", "1.2.0", "90"):
        assert needle in hits[0], needle
    assert re.search(r"(?i)spec 120", hits[0]).start() < re.search(r"(?i)spec 119", hits[0]).start(), "the 120 entry sits above the 119 entry"

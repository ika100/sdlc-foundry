"""Spec 122 verification round A: doctor rows are named like the console banner keys (`claude`, `gh`, `kube:<env>`)."""
import doctor
from console import sources
from system_fixtures import rich5, write_system


def test_a_logged_out_gh_is_the_row_named_gh(monkeypatch):
    monkeypatch.setattr(doctor.shutil, "which", lambda t: f"/bin/{t}")
    monkeypatch.setattr(doctor, "run", lambda *a, **k: type("P", (), {"returncode": 1, "stdout": "", "stderr": ""})())
    assert [r["name"] for r in doctor.check_tools() if r["name"] == "gh"] == []
    [row] = doctor.check_gh()
    assert (row["name"], row["status"], row["fix"]) == ("gh", doctor.FAIL, "gh auth login")


def test_each_environment_has_a_kube_row(tmp_path, monkeypatch):
    repo = tmp_path / "shop-gitops"
    write_system(repo, rich5())
    monkeypatch.setattr(doctor.shutil, "which", lambda t: f"/bin/{t}")
    monkeypatch.setattr(doctor.settings, "kube_context", lambda r: ("k3d-shop", "user"))
    monkeypatch.setattr(doctor, "_contexts", lambda: {"k3d-shop"})
    rows = doctor.check_kube_envs(repo)
    assert rows and all(r["name"].startswith("kube:") and r["status"] == doctor.OK for r in rows)
    monkeypatch.setattr(doctor, "_contexts", lambda: set())
    assert all(r["status"] == doctor.WARN and r["fix"] for r in doctor.check_kube_envs(repo))


def test_the_banner_lists_the_three_keys_and_not_the_generic_kube_context():
    src = sources.Source("doctor", ["x"])
    src.data = [{"status": "warn", "name": "kube context", "detail": "", "fix": "x"},
                {"status": "fail", "name": "gh", "detail": "", "fix": "gh auth login"},
                {"status": "warn", "name": "kube:prod", "detail": "", "fix": "use-context"},
                {"status": "warn", "name": "claude", "detail": "", "fix": "install"},
                {"status": "ok", "name": "kube:dev", "detail": "", "fix": None}]
    assert [b["piece"] for b in sources.banner(src)] == ["gh", "kube:prod", "claude"]

"""doctor: a broker with an unsupported NATS version gives a WARN row instead of a KeyError (spec 119 review fix)."""
from types import SimpleNamespace

from broker_fixtures import broker, bsys
from system_fixtures import write_system


def test_doctor_warns_on_an_unsupported_broker_version(tmp_path, monkeypatch):
    import doctor
    monkeypatch.setattr(doctor.shutil, "which", lambda t: f"/usr/bin/{t}")
    monkeypatch.setattr(doctor, "run", lambda *a, **k: SimpleNamespace(stdout="", stderr="", returncode=1))
    write_system(tmp_path, bsys({"bus": broker(version="2.13")}))
    rows = doctor.check_brokers(tmp_path)
    assert rows and all(c["status"] == "warn" for c in rows)
    assert "2.13" in rows[0]["detail"] and "2.14" in rows[0]["detail"] and "2.15" in rows[0]["detail"]

"""#1021: the liveness probe before a smoke run is tried again while it times out (the first request after a rollout can be
slow); a refused connection still ends it at once (AC-091.11). Seams: `smoke.reachable`, `smoke.sleep`."""
import json

import smoke

URL = "http://shop-api.shop-dev.localhost:8088"


class Probe:
    def __init__(self, monkeypatch, answers):
        self.answers, self.urls, self.slept = list(answers), [], []
        monkeypatch.setattr(smoke, "reachable", self)
        monkeypatch.setattr(smoke, "sleep", self.slept.append)

    def __call__(self, url, timeout=10.0):
        self.urls.append(url)
        return self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]


def test_a_timed_out_probe_that_answers_on_a_later_try_is_reachable(monkeypatch):
    p = Probe(monkeypatch, ["TimeoutError: timed out", "<urlopen error timed out>", None])
    assert smoke._probe(URL + "/health") is None
    assert len(p.urls) == 3 and p.slept == [smoke.PROBE_DELAY_S] * 2


def test_a_probe_that_keeps_timing_out_is_not_run_after_its_retries(monkeypatch, tmp_path):
    (tmp_path / "devbox.json").write_text(json.dumps({"shell": {"scripts": {"smoke": "true"}}}))
    p = Probe(monkeypatch, ["TimeoutError: timed out"])
    res = smoke.run_smoke(tmp_path, URL, probe="/health")
    assert res.outcome == "not-run" and res.reason == f"dev URL {URL} is not reachable: TimeoutError: timed out"
    assert len(p.urls) == 1 + smoke.PROBE_RETRIES and len(p.slept) == smoke.PROBE_RETRIES


def test_a_refused_connection_is_not_tried_again(monkeypatch):
    p = Probe(monkeypatch, ["[Errno 61] Connection refused"])
    assert smoke._probe(URL + "/health") == "[Errno 61] Connection refused"
    assert len(p.urls) == 1 and p.slept == []

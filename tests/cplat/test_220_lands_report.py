"""Spec 220 acceptance tests: the `lands` block of `cplat platform runs report` (AC-220.8, AC-220.9).

Contract: design.md, "`cplat platform runs report`". AC-220.9 is a measurement after the release; its two counts
(`docs_waited_behind_catch_up_over_5_min`, `code_catch_up_e2e_out_of_scope`) are tested here on run records with `lands` items.
"""
from test_runs import clock, mem, store  # noqa: F401  (fixtures)


def land(pr, scope, wait, *, catch_up=0.0, fast=False, kept=False, e2e=False, rng=None):
    return {"pr": pr, "mode": "catch-up", "scope": scope, "lock_wait_min": wait, "lock_wait_catch_up_min": catch_up,
            "catch_up_min": catch_up, "catch_up_e2e": e2e, "range_scope": rng, "fast_lane": fast, "e2e_kept": kept}


def test_the_report_shows_median_and_p90_lock_wait_for_docs_and_code_lands_ac_220_8(store, capsys):  # AC-220.8
    import runs
    from test_runs_report import put, rec, report_json
    docs = [land(i, "docs", w) for i, w in enumerate([0.2, 0.4, 0.6, 1.0, 1.2], 1)]
    code = [land(10 + i, "code", w, fast=(i == 0), kept=(i == 1)) for i, w in enumerate([2.0, 9.0, 9.5])]
    other = [land(20, "unknown", 40.0), land(21, None, 40.0), "not a dict", {"pr": 22}]
    put(store, rec("r1", "2026-10-23T10:00:00Z", lands=docs[:3]))
    put(store, rec("r2", "2026-10-23T11:00:00Z", lands=docs[3:] + code + other))
    put(store, rec("r3", "2026-10-23T12:00:00Z"))                                # a record without lands items
    out = report_json(capsys)
    assert "lands" in out, "the report has no lands block"
    got = out["lands"]
    assert got["docs"] == {"count": 5, "lock_wait_median_min": 0.6, "lock_wait_p90_min": 1.2}
    assert got["code"] == {"count": 3, "lock_wait_median_min": 9.0, "lock_wait_p90_min": 9.5}   # unknown scope is in neither group
    assert got["fast_lane"] == 1 and got["e2e_kept"] == 1
    assert runs.main(["report"]) == 0
    out = capsys.readouterr().out
    assert "Lands (lock wait median / p90):\n  docs: 0.6 min / 1.2 min (n=5)\n  code: 9.0 min / 9.5 min (n=3)\n" in out
    assert "  fast lane: 1, kept e2e: 1; docs lands > 5 min behind a catch-up: 0; code lands with an out-of-scope catch-up e2e: 0" in out
    assert out.index("Phases (median / p90):") < out.index("Lands (lock wait median / p90):")


def test_the_report_says_none_when_no_record_holds_a_land_ac_220_8(store, capsys):  # AC-220.8
    import runs
    from test_runs_report import put, rec
    put(store, rec("r1", "2026-10-23T10:00:00Z"))
    assert runs.main(["report"]) == 0
    assert "Lands (lock wait median / p90):\n  none" in capsys.readouterr().out


def test_the_ac_220_9_counts_are_zero_when_no_docs_land_waited_behind_a_catch_up_ac_220_9(store, capsys):  # AC-220.9
    from test_runs_report import put, rec, report_json
    lands = [land(1, "docs", 0.3, catch_up=0.0), land(2, "docs", 4.9, catch_up=4.9),
             land(3, "code", 2.0, catch_up=1.0, kept=True, rng="out", e2e=False), land(4, "code", 30.0, catch_up=26.0, e2e=True, rng="in")]
    put(store, rec("r1", "2026-10-23T10:00:00Z", lands=lands))
    out = report_json(capsys)
    assert "lands" in out, "the report has no lands block"
    got = out["lands"]
    assert got["docs_waited_behind_catch_up_over_5_min"] == 0 and got["code_catch_up_e2e_out_of_scope"] == 0


def test_the_ac_220_9_counts_find_the_lands_that_the_spec_wants_gone_ac_220_9(store, capsys):  # AC-220.9
    import runs
    from test_runs_report import put, rec, report_json
    lands = [land(1, "docs", 6.0, catch_up=6.0), land(2, "docs", 5.0, catch_up=5.0), land(3, "code", 26.0, catch_up=26.0, e2e=True, rng="out"),
             land(4, "code", 3.0, catch_up=3.0, e2e=False, rng="out"), land(5, "code", 26.0, catch_up=26.0, e2e=True, rng="in"),
             land(6, "docs", 7.0, catch_up=0.0)]
    put(store, rec("r1", "2026-10-23T10:00:00Z", lands=lands))
    out = report_json(capsys)
    assert "lands" in out, "the report has no lands block"
    got = out["lands"]
    assert got["docs_waited_behind_catch_up_over_5_min"] == 1                  # more than 5 min of lock wait behind catch-up checks
    assert got["code_catch_up_e2e_out_of_scope"] == 1                          # an out-of-scope range whose land still waited for an e2e
    assert runs.main(["report"]) == 0
    assert "docs lands > 5 min behind a catch-up: 1; code lands with an out-of-scope catch-up e2e: 1" in capsys.readouterr().out

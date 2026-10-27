"""Spec 122 acceptance tests: the console's server and its data (AC-122.3, AC-122.42, AC-122.43) and the HTTP rules of design.md
"Console HTTP" (Host 421, X-Console-Token 403, static files, JSON errors).

The sources are file-backed fakes (console_support.Console): the six `cplat ... --json` documents of AC-122.3 and nothing else."""
import datetime as dt
import json
import re
import sys

import pytest

from console_support import Console, doctor_json, needs_json, parse, q, status_json


# ---------------- HTTP rules ----------------

def test_a_wrong_host_is_refused_with_421_ac_122_3(console):  # AC-122.3
    c = console()
    for host in ("evil.example.com", f"localhost:{c.port}", f"127.0.0.1:{c.port + 1}"):
        st, _, _ = c.request("GET", "/inbox", host=host)
        assert st == 421, host
    st, _, _ = c.request("GET", "/inbox")
    assert st == 200


def test_the_host_check_comes_before_everything_else_ac_122_3(console):  # AC-122.3
    c = console()
    assert c.request("POST", "/api/sources/needs/retry", token=False, host="evil.example.com")[0] == 421
    assert c.request("GET", "/static/console.css", host="evil.example.com")[0] == 421


def test_a_post_needs_the_per_start_token_ac_122_3(console):  # AC-122.3
    c = console()
    assert c.request("POST", "/api/sources/needs/retry", token=False)[0] == 403
    assert c.request("POST", "/api/sources/needs/retry", token="not-the-token")[0] == 403
    assert c.request("POST", "/api/sources/needs/retry")[0] == 202


def test_the_token_is_in_the_page_and_differs_between_starts_ac_122_3(console):  # AC-122.3
    a, b = console(), console()
    assert a.token() and b.token() and a.token() != b.token()


def test_root_redirects_to_the_inbox_ac_122_31(console):  # AC-122.31
    st, headers, _ = console().request("GET", "/")
    assert st == 302 and headers["Location"].endswith("/inbox")


def test_pages_are_html_and_static_files_are_the_two_known_ones_ac_122_3(console):  # AC-122.3
    c = console()
    for path in ("/inbox", "/board", "/system", "/board?view=list", "/board?view=done&period=90"):
        st, h, _ = c.request("GET", path)
        assert st == 200 and h["Content-Type"].startswith("text/html"), path
    st, h, body = c.request("GET", "/static/console.css")
    assert st == 200 and "css" in h["Content-Type"] and body
    st, h, body = c.request("GET", "/static/console.js")
    assert st == 200 and "javascript" in h["Content-Type"] and body
    for bad in ("/static/server.py", "/static/../server.py", "/static/%2e%2e/server.py", "/static/", "/static/console.js.map"):
        assert c.request("GET", bad)[0] == 404, bad


def test_errors_are_json_with_error_and_detail_ac_122_3(console):  # AC-122.3
    c = console()
    st, body = c.json("GET", "/api/actions/does-not-exist")
    assert st == 404 and "error" in body and "detail" in body
    st, _ = c.json("GET", "/panel/spec/999-nope")
    assert st == 404
    st, _ = c.json("GET", "/no/such/route")
    assert st == 404


def test_the_state_document_has_the_contract_keys_ac_122_3(console):  # AC-122.3
    c = console()
    st, s = c.json("GET", "/api/state")
    assert st == 200
    assert {"read_at", "stale", "badge", "actions", "sources", "banner", "version"} <= set(s)
    assert s["actions"] == {"running": 0, "failed": 0} and s["badge"] == len(needs_json()["items"])
    assert {"model", "status", "needs", "runs", "doctor"} <= set(s["sources"])
    assert all({"ok", "read_at", "unavailable_since", "error"} <= set(v) for v in s["sources"].values())


# ---------------- AC-122.3: every value from the sources, with the time it was read ----------------

@pytest.mark.parametrize("path", ["/inbox", "/board", "/board?view=list", "/system"])
def test_every_page_shows_the_time_its_data_was_read_ac_122_3(console, path):  # AC-122.3
    root, _ = console().page(path)
    times = q(root, "time", data_read_at=True)
    assert times
    for t in times:
        dt.datetime.fromisoformat(t.attrs["data-read-at"].replace("Z", "+00:00"))


def test_a_page_shows_what_the_source_says_and_nothing_else_ac_122_3(console):  # AC-122.3
    c = console()
    doc = needs_json()
    doc["items"][0]["reason"] = "reason text that only this test knows 7f3a"
    c.set("needs", doc)
    root, text = c.page("/inbox")
    assert "reason text that only this test knows 7f3a" in text


def test_a_change_in_a_source_bumps_the_version_and_shows_on_the_next_load_ac_122_3(console):  # AC-122.3
    c = console()
    _, before = c.json("GET", "/api/state")
    doc = needs_json()
    doc["items"] = doc["items"][:2]
    c.set("needs", doc, read=False)
    assert c.request("POST", "/api/sources/needs/retry")[0] == 202
    for _ in range(100):
        _, after = c.json("GET", "/api/state")
        if after["version"] != before["version"]:
            break
        import time
        time.sleep(0.1)
    assert after["version"] != before["version"] and after["badge"] == 2


def test_the_badge_is_the_number_of_needs_items_ac_122_6(console):  # AC-122.6
    c = console()
    for path in ("/inbox", "/board", "/system"):
        root, _ = c.page(path)
        [badge] = q(root, "span", data_badge="inbox")
        assert badge.text() == str(len(needs_json()["items"]))


# ---------------- AC-122.43: stale ----------------

def test_fresh_data_is_not_marked_stale_ac_122_43(console):  # AC-122.43
    c = console()
    root, text = c.page("/inbox")
    assert not q(root, None, data_stale="true")
    assert c.json("GET", "/api/state")[1]["stale"] is False


def test_data_older_than_two_minutes_is_marked_stale_ac_122_43(console, monkeypatch):  # AC-122.43
    from console import sources
    c = console()
    real = sources.utcnow
    monkeypatch.setattr(sources, "utcnow", lambda: real() + dt.timedelta(minutes=3))
    st, s = c.json("GET", "/api/state")
    assert s["stale"] is True
    root, text = c.page("/inbox")
    marked = q(root, None, data_stale="true")
    assert marked and any("stale" in n.text().lower() for n in marked)


def test_freshness_marks_exactly_after_two_minutes_ac_122_43():  # AC-122.43
    from console import html
    now = dt.datetime(2026, 10, 26, 8, 0, 0, tzinfo=dt.timezone.utc)

    def at(seconds):
        return parse(html.freshness((now - dt.timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z"), now))

    fresh, old = at(119), at(121)
    [t] = q(fresh, "time", data_read_at=True)
    assert t.attrs.get("data-stale") != "true"
    [t] = q(old, "time", data_read_at=True)
    assert t.attrs["data-stale"] == "true" and "stale" in old.text().lower()


# ---------------- AC-122.42: a source that fails ----------------

def test_a_failing_source_keeps_its_last_data_and_says_since_when_ac_122_42(tmp_path):  # AC-122.42
    from console import sources
    good = tmp_path / "good.json"
    good.write_text(json.dumps({"x": 1}))
    s = sources.Source("status", [sys.executable, "-c", "import sys; sys.stdout.write(open(sys.argv[1]).read())", str(good)])
    s.read()
    assert s.data == {"x": 1} and s.error is None and s.unavailable_since is None and s.read_at
    good.unlink()
    s.read()
    first = s.unavailable_since
    assert first and s.error and s.data == {"x": 1}
    s.read()
    assert s.unavailable_since == first                       # since the first failure, not the last retry
    good.write_text(json.dumps({"x": 2}))
    s.read()
    assert s.data == {"x": 2} and s.error is None and s.unavailable_since is None


def test_a_source_that_prints_no_json_is_unavailable_ac_122_42(tmp_path):  # AC-122.42
    from console import sources
    s = sources.Source("runs", [sys.executable, "-c", "print('not json')"])
    s.read()
    assert s.error and s.data is None


def test_a_source_that_hangs_does_not_block_the_server_ac_122_42(console):  # AC-122.42
    from console import sources
    c = console()
    c.sources["runs"] = sources.Source("runs", [sys.executable, "-c", "import time; time.sleep(4)"])
    c.sources["runs"].timeout = 1
    c.sources["runs"].read()
    assert c.sources["runs"].error
    assert c.request("GET", "/inbox")[0] == 200


def test_the_unavailable_part_says_since_when_and_offers_retry_ac_122_42(console):  # AC-122.42
    c = console()
    c.fail("status")
    root, _ = c.page("/system")
    [sec] = q(root, "section", data_source="status")
    assert dt.datetime.fromisoformat(sec.attrs["data-unavailable-since"].replace("Z", "+00:00"))
    assert "unreachable" in sec.text()
    [retry] = q(sec, "button", data_action="retry-source")
    assert "Retry now" in retry.text()


def test_the_last_data_is_marked_stale_and_health_is_unknown_ac_122_42(console):  # AC-122.42
    c = console()
    c.fail("status")
    root, text = c.page("/system")
    sec = q(root, "section", data_source="status")[0]
    assert any(n.attrs.get("data-stale") == "true" for n in [sec, *sec.walk()])
    row = next(tr for tr in q(root, "tr") if "shop-api" in tr.text() and q(tr, "td"))
    cells = {td.attrs.get("data-env"): td.text() for td in q(row, "td", data_env=True)}
    assert cells and all("unknown" in t for t in cells.values())
    for word in ("healthy", "verified", "NOT VERIFIED"):
        assert word not in " ".join(cells.values())


def test_an_action_that_depends_on_that_health_is_disabled_ac_122_42(console):  # AC-122.42
    c = console()
    c.fail("status")
    root, _ = c.page("/system")
    promote = q(root, "button", data_action="promote")
    assert promote and all("disabled" in b.attrs and b.attrs.get("aria-disabled") == "true" for b in promote)


def test_the_other_parts_of_the_page_stay_live_ac_122_42(console):  # AC-122.42
    c = console()
    c.fail("status")
    root, _ = c.page("/inbox")
    assert q(root, None, data_need=True)
    assert not q(root, "section", data_source="needs")


def test_retry_now_reads_the_source_again_and_clears_the_marks_ac_122_42(console):  # AC-122.42
    import time
    c = console()
    c.fail("status")
    assert not c.json("GET", "/api/state")[1]["sources"]["status"]["ok"]
    c.set("status", status_json(), read=False)
    assert c.request("POST", "/api/sources/status/retry")[0] == 202
    for _ in range(100):
        s = c.json("GET", "/api/state")[1]["sources"]["status"]
        if s["ok"]:
            break
        time.sleep(0.1)
    assert s["ok"] and s["unavailable_since"] is None
    root, _ = c.page("/system")
    assert not q(root, "section", data_source="status", data_unavailable_since=True)


def test_state_reports_the_unavailable_source_ac_122_42(console):  # AC-122.42
    c = console()
    c.fail("runs")
    s = c.json("GET", "/api/state")[1]["sources"]["runs"]
    assert s["ok"] is False and s["unavailable_since"] and "unreachable" in s["error"]


def test_a_cluster_that_status_cannot_read_shows_unknown_for_its_cells_ac_122_42(console):  # AC-122.42
    c = console()
    doc = status_json()
    for row in doc["rows"]:
        if row["cells"].get("prod"):
            row["cells"]["prod"]["state"] = "unknown"
    doc["unavailable"] = [{"source": "cluster:prod", "error": "context k3d-prod not found"}]
    c.set("status", doc)
    root, text = c.page("/system")
    assert "k3d-prod not found" in text and "cluster:prod" in text
    row = next(tr for tr in q(root, "tr") if "shop-api" in tr.text() and q(tr, "td"))
    prod = q(row, "td", data_env="prod")[0]
    assert "unknown" in prod.text() and "healthy" not in prod.text()
    assert all(b.attrs.get("aria-disabled") == "true" for b in q(prod, "button", data_action="promote"))

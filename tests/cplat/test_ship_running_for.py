import datetime as dt

import ship


def _at(minutes_ago: int) -> str:
    return (dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=minutes_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def test_a_pending_check_says_how_long_it_has_run_from_its_utc_start():   # #673
    assert ship._running_for({"startedAt": _at(17)}) == " (running 17m)"


def test_a_check_without_a_usable_start_says_nothing():   # #673
    assert ship._running_for({}) == ""
    assert ship._running_for({"startedAt": "0001-01-01T00:00:00Z"}) == ""
    assert ship._running_for({"startedAt": "not a time"}) == ""

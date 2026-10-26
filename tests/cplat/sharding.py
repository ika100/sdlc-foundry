"""Spec 112: `--shard I/N` runs a deterministic round-robin slice of the suite; `--shard-report` records what a shard
collected and ran, so `scripts/check-shards.py` can prove the shards together are the whole suite.

Without `--shard` every hook does nothing. Test k (0-based, in node-id sort order) belongs to shard k % N + 1.
"""
import json
from pathlib import Path

import pytest

_STATE = pytest.StashKey[dict]()


def _parse(value: str) -> tuple[int, int]:
    err = pytest.UsageError(f"--shard must be I/N with 1 <= I <= N, got {value}")
    parts = value.split("/")
    if len(parts) != 2 or not all(p.isdigit() for p in parts):
        raise err
    i, n = int(parts[0]), int(parts[1])
    if not 1 <= i <= n:
        raise err
    return i, n


def _state(config):
    return config.stash.get(_STATE, None)


def _is_worker(config) -> bool:
    return hasattr(config, "workerinput")


def pytest_addoption(parser):
    group = parser.getgroup("sharding")
    group.addoption("--shard", action="store", default=None, metavar="I/N",
                    help="run only shard I of N (round-robin over the sorted node ids)")
    group.addoption("--shard-report", action="store", default=None, metavar="PATH",
                    help="write what this shard collected and ran as JSON (needs --shard)")


def pytest_configure(config):
    value = config.getoption("--shard")
    report = config.getoption("--shard-report")
    if value is None:
        if report is not None:
            raise pytest.UsageError("--shard-report needs --shard")
        return
    index, total = _parse(value)
    path = None
    if report is not None:
        path = Path(report)
        if not path.is_absolute():
            path = Path(config.invocation_params.dir) / path
    config.stash[_STATE] = {"index": index, "total": total, "path": path, "collected": None, "kept": None,
                            "ran": set(), "worker_lists": [], "bad": False}


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(session, config, items):
    st = _state(config)
    if st is None:
        return
    ordered = sorted(items, key=lambda it: it.nodeid)
    st["collected"] = [it.nodeid for it in ordered]
    keep = {it.nodeid for k, it in enumerate(ordered) if k % st["total"] == st["index"] - 1}
    kept = [it for it in items if it.nodeid in keep]
    dropped = [it for it in items if it.nodeid not in keep]
    if dropped:
        config.hook.pytest_deselected(items=dropped)
    items[:] = kept
    st["kept"] = len(kept)


def pytest_report_collectionfinish(config):
    st = _state(config)
    if st is None or st["kept"] is None:
        return None
    return f"shard {st['index']}/{st['total']}: {st['kept']} of {len(st['collected'])} tests"


def pytest_runtest_logreport(report):
    # Called in the controller / serial process through the config of the session; workers also see it, ignore there.
    config = _CONFIG.get("config")
    if config is None or _is_worker(config):
        return
    st = _state(config)
    if st is not None:
        st["ran"].add(report.nodeid)


_CONFIG: dict = {}


@pytest.hookimpl(tryfirst=True)
def pytest_sessionstart(session):
    _CONFIG["config"] = session.config


@pytest.hookimpl(optionalhook=True)
def pytest_testnodedown(node, error):
    config = node.config
    st = _state(config)
    out = getattr(node, "workeroutput", None) or {}
    if st is not None and "shard_collected" in out:
        st["worker_lists"].append(out["shard_collected"])


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session, exitstatus):
    config = session.config
    st = _state(config)
    if st is None:
        return
    if _is_worker(config):
        config.workeroutput["shard_collected"] = st["collected"]
        return
    collected = st["collected"]
    if st["worker_lists"]:
        first = st["worker_lists"][0]
        if any(lst != first for lst in st["worker_lists"]):
            collected = None
            st["bad"] = True
            if session.exitstatus == 0:
                session.exitstatus = 1
        else:
            collected = first
    if st["path"] is not None:
        data = {"shard": st["index"], "total": st["total"], "collected": collected, "ran": sorted(st["ran"])}
        st["path"].parent.mkdir(parents=True, exist_ok=True)
        st["path"].write_text(json.dumps(data), encoding="utf-8")

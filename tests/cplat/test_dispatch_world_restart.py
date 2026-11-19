"""The dispatch world's `restart` purges the `dispatch*` modules for one test only: after the world closes, a later test in the
same worker sees the modules the code under test uses (a leak made the spec 198 hold tests patch a stale `dispatch_state`)."""
import sys

import dispatch_state
from dispatch_world import World


def test_closing_the_world_restores_the_modules_restart_purged(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    w.restart()
    import dispatch_state as fresh
    assert fresh is not dispatch_state
    w.close()
    assert sys.modules["dispatch_state"] is dispatch_state

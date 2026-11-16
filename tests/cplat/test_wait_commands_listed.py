"""Every wait a module records or marks as running is a detached wait under `cplat headless` (spec 202, design "Detached waits")."""
import re
from pathlib import Path

import waitdetach

SRC = Path(__file__).resolve().parents[2] / "scripts" / "cplat"
CALL = re.compile(r"""waits\.(?:record|running)\(\s*(?:\w+(?:\([^)]*\))?\s*,\s*)?f?["']([^"']+)["']""")


def _names() -> set[str]:
    found: set[str] = set()
    for f in SRC.glob("*.py"):
        for name in CALL.findall(f.read_text()):
            found.add(name.removeprefix("cplat "))
    return found


def test_every_caller_of_waits_record_or_running_maps_to_a_wait_command():
    names = _names()
    assert {"component ship land", "dispatch wait"} <= names, names   # the scan finds callers at all
    for name in names:
        if name.startswith("{kind}"):
            candidates = [f"{k} wait" for k in ("system", "cluster")]
        else:
            candidates = [name]
        for c in candidates:
            argv = c.split()
            if argv[:3] == ["system", "ship", "next"]:
                argv.append("--wait")
            assert waitdetach._matches(argv) is not None, f"{c} is not in waitdetach.WAIT_COMMANDS"

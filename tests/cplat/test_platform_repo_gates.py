# SPDX-License-Identifier: Apache-2.0
"""The platform repo carries the devbox gates /svc:ship and /svc:build call."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_devbox_has_the_gate_scripts():
    scripts = json.loads((ROOT / "devbox.json").read_text())["shell"]["scripts"]
    for name in ("test-fast", "ci", "quality", "lint-fix"):
        assert name in scripts, f"devbox.json lacks the '{name}' script"

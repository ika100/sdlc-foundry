"""AC-178.6: the fixture files of scripts/check-test-sleeps.py are exempt for sleep text in string literals only, not for real calls."""
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "scripts" / "check-test-sleeps.py"
CALL = "time" + ".sleep(1)"   # built in two parts so this file holds no sleep text itself


def run(tmp_path, name: str, text: str):
    f = tmp_path / "tests" / "cplat" / name
    f.parent.mkdir(parents=True)
    f.write_text(text)
    return subprocess.run([sys.executable, str(CHECK), "--root", str(tmp_path)], capture_output=True, text=True, timeout=60)


@pytest.mark.parametrize("name", ["test_178_sleeps_check.py", "test_143_waits_docs.py"])
def test_real_sleep_call_in_fixture_file_is_flagged(tmp_path, name):
    r = run(tmp_path, name, f"import time\n\n\ndef test_x():\n    {CALL}\n")
    assert r.returncode == 1
    assert f"{name}:5:" in r.stdout


@pytest.mark.parametrize("name", ["test_178_sleeps_check.py", "test_143_waits_docs.py"])
def test_sleep_in_string_literal_of_fixture_file_is_not(tmp_path, name):
    r = run(tmp_path, name, f'SAMPLE = """\n{CALL}\n"""\n')
    assert r.returncode == 0, r.stdout

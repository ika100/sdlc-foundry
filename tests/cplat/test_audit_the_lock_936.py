"""#936: the Python templates' `audit` and `deps-findings` recipes run pip-audit on an export of uv.lock, never on the
environment that runs it (journey 25: a venv without the dev extra fell back to devbox's pip-audit, which audited its own
Python and blocked the ship on packages the repo does not lock)."""

import json
import os
import re
import shutil
import stat
import subprocess

import pytest

import core
from waiting import with_prelude

TEMPLATES = core.PLATFORM_ROOT / "templates"
PYTHON = ["service-python", "library-python"]

# a stand-in for uv: `uv export` prints the locked requirements, `uv run pip-audit ...` records its arguments and the
# requirements file it was given, and (for -f json -o) writes an empty report
UV = r"""#!/bin/sh
log="$UV_LOG"
if [ "$1" = export ]; then echo "export $*" >> "$log"; printf 'fastapi==0.120.0\nurllib3==2.8.0\n'; exit 0; fi
if [ "$1" = run ] && [ "$2" = pip-audit ]; then
  shift 2; echo "pip-audit $*" >> "$log"
  while [ $# -gt 0 ]; do
    case "$1" in
      -r) cp "$2" "$UV_LOG.req"; shift ;;
      -o) echo '{"dependencies": [], "fixes": []}' > "$2"; shift ;;
    esac
    shift
  done
  exit 0
fi
echo "unexpected uv $*" >> "$log"; exit 9
"""


def recipe(
    template, name
):  # one line of devbox.json; the service template's file holds Jinja, so it is not parsed as JSON
    line = re.search(
        rf'^\s*"{name}":\s*(".*"),?$',
        (TEMPLATES / template / "devbox.json").read_text(),
        re.M,
    ).group(1)
    return json.loads(line)


def run(template, tmp_path, *args):
    work = tmp_path / "repo"
    (work / "scripts").mkdir(parents=True)
    for f in ("deps.sh", "deps_pyproject.py"):
        shutil.copy(TEMPLATES / template / "scripts" / f, work / "scripts" / f)
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "uv").write_text(with_prelude(UV))
    (bindir / "uv").chmod((bindir / "uv").stat().st_mode | stat.S_IEXEC)
    log = tmp_path / "uv.log"
    env = {
        **os.environ,
        "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}",
        "UV_LOG": str(log),
    }
    script = tmp_path / "recipe.sh"
    script.write_text(" ".join(args) + "\n")
    proc = subprocess.run(
        ["sh", str(script)],
        cwd=work,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return proc, log.read_text().splitlines(), log.with_name("uv.log.req")


@pytest.mark.parametrize("template", PYTHON)
def test_audit_checks_what_the_lock_pins(tmp_path, template):
    proc, calls, req = run(template, tmp_path, recipe(template, "audit"))
    assert proc.returncode == 0, proc.stderr
    assert (
        calls[0].startswith("export ")
        and "--frozen" in calls[0]
        and "--all-extras" in calls[0]
    ), calls
    audit = calls[1].split()
    assert (
        audit[0] == "pip-audit"
        and "-r" in audit
        and "--no-deps" in audit
        and "--disable-pip" in audit
    ), calls
    assert req.read_text() == "fastapi==0.120.0\nurllib3==2.8.0\n"


@pytest.mark.parametrize("template", PYTHON)
def test_findings_report_is_on_the_lock_too(tmp_path, template):
    out = tmp_path / "report.json"
    proc, calls, req = run(
        template, tmp_path, recipe(template, "deps-findings").replace('"$@"', str(out))
    )
    assert proc.returncode == 0, proc.stderr
    audit = calls[1].split()
    assert "-r" in audit and "-f" in audit and "json" in audit and str(out) in audit, (
        calls
    )
    assert json.loads(out.read_text())["dependencies"] == [] and req.is_file()

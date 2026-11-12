"""#678: the log tailer's `checksum/tailer` annotation (spec 182) is a generated line like `checksum/config` (#420). The template
baseline skips it, and `cplat platform update` widens the old #420 pattern of an existing repo's baseline, changing nothing else."""
import json
import re
import shutil
import subprocess

import update
from test_scan_generated_420 import BASELINE, COLLECTOR, HOOK, _patterns

TAILER = ["        checksum/tailer: 5f38d30e83bc511a", '        checksum/tailer: "5f38d30e83bc511a"']
NOT_TAILER = ["        checksum/tailer: 5f38d30e83bc511aff", "        checksum/other: 5f38d30e83bc511a"]


def test_the_template_baseline_skips_the_tailer_checksum_and_nothing_else():
    rules = _patterns()
    for line in TAILER:
        assert any(re.search(rx, line) for rx in rules), f"not skipped: {line!r}"
    for line in NOT_TAILER:
        assert not any(re.search(rx, line) for rx in rules), f"the pattern would also hide {line!r}"


def test_detect_secrets_passes_a_collector_with_both_checksums(tmp_path):
    if not shutil.which("uvx"):
        return
    doc = COLLECTOR.replace("checksum/config: c74603420bbec748", "checksum/config: c74603420bbec748\n        checksum/tailer: 5f38d30e83bc511a")
    (tmp_path / "collector.yaml").write_text(doc)
    shutil.copy(BASELINE, tmp_path / ".secrets.baseline.json")
    r = subprocess.run([*HOOK, "--baseline", ".secrets.baseline.json", "collector.yaml"], cwd=tmp_path, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def _old_baseline() -> str:
    return BASELINE.read_text().replace(update.NEW_GENERATED_LINES, update.OLD_GENERATED_LINES)


def test_update_widens_the_old_pattern_and_changes_nothing_else(tmp_path):
    old = _old_baseline()
    (tmp_path / ".secrets.baseline.json").write_text(old)
    assert update.widen_generated_lines(tmp_path) is True
    new = (tmp_path / ".secrets.baseline.json").read_text()
    assert new == BASELINE.read_text()
    assert json.loads(new)["results"] == json.loads(old)["results"]


def test_update_leaves_a_widened_or_missing_baseline_alone(tmp_path):
    assert update.widen_generated_lines(tmp_path) is False
    (tmp_path / ".secrets.baseline.json").write_text(BASELINE.read_text())
    assert update.widen_generated_lines(tmp_path) is False
    assert (tmp_path / ".secrets.baseline.json").read_text() == BASELINE.read_text()

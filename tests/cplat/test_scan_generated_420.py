"""#420: lines the gitops render writes on its own (a collector's config checksum, an S3Credentials' field names) are not
secrets. The template's baseline carries one narrow exclude-lines pattern for exactly those lines, so the repo's secrets scan
does not fail on every collector change or new bucket, and needs no hand-made baseline entry."""
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASELINE = ROOT / "templates" / "gitops-app" / ".secrets.baseline.json"
GENERATED = ["        checksum/config: 8a7db2e42c4c84e6", "      accessKeyField: accessKeyId", "      secretKeyField: secretAccessKey"]
REAL = ["        checksum/config: 8a7db2e42c4c84e6aa", "      secretAccessKey: wJalrXUtnFEMIK7MDENGbPxRfiCYzzQ9",
        "      password: hunter2-hunter2-hunter2", "        checksum/config: not-a-checksum"]
HOOK = ["uvx", "--from", "detect-secrets==1.5.0", "detect-secrets-hook"]


def _patterns() -> list[str]:
    filters = json.loads(BASELINE.read_text())["filters_used"]
    return [rx for f in filters if f["path"] == "detect_secrets.filters.regex.should_exclude_line" for rx in f["pattern"]]


def test_the_baseline_skips_the_generated_lines_and_nothing_else():
    rules = _patterns()
    assert rules, "the template baseline has no exclude-lines pattern"
    for line in GENERATED:
        assert any(re.search(rx, line) for rx in rules), f"not skipped: {line!r}"
    for line in REAL:
        assert not any(re.search(rx, line) for rx in rules), f"the pattern would also hide {line!r}"


def test_detect_secrets_passes_the_generated_lines_with_the_template_baseline(tmp_path):
    (tmp_path / ".secrets.baseline.json").write_text(BASELINE.read_text())
    (tmp_path / "collector.yaml").write_text("\n".join(GENERATED) + "\n")
    (tmp_path / "secret.yaml").write_text(REAL[1] + "\n")
    flags = ["--baseline", ".secrets.baseline.json", "--disable-filter", "detect_secrets.filters.gibberish.should_exclude_secret"]
    ok = subprocess.run([*HOOK, *flags, "collector.yaml"], cwd=tmp_path, capture_output=True, text=True)
    assert ok.returncode == 0, ok.stdout + ok.stderr
    caught = subprocess.run([*HOOK, *flags, "secret.yaml"], cwd=tmp_path, capture_output=True, text=True)
    assert caught.returncode == 1, "a real secret must still fail the scan"

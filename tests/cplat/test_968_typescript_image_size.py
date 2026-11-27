"""#968: the service-typescript image stays small. The platform CI job `smoke-test-service-typescript` fails when the
unpacked filesystem of a built variant exceeds its byte budget.

Seam: the platform CI workflow. The measurement itself runs in that CI job on every variant.
"""
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def _image_step() -> dict:
    wf = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text())
    return next(s for s in wf["jobs"]["smoke-test-service-typescript"]["steps"] if "docker build" in str(s.get("run", "")))


def test_the_ci_smoke_fails_an_image_over_its_byte_budget():
    step = _image_step()
    budget = step["env"]["IMAGE_BUDGET_BYTES"]
    assert isinstance(budget, int) and 150_000_000 < budget <= 300_000_000
    run = step["run"]
    export = run.index("docker export")
    assert run.index("docker build") < export < run.index("docker run -d --name smoke --read-only")   # measured before the service starts
    assert re.search(r'if \[ "\$bytes" -gt "\$IMAGE_BUDGET_BYTES" \]; then\n.*exit 1', run)

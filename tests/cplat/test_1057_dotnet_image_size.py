"""#1057: the service-dotnet image stays small. The image ships only what runs, and the platform CI job
`smoke-test-service-dotnet` fails when the unpacked filesystem of a built variant exceeds its byte budget.

Seams: the rendered template (copier, rendered once per process) and the platform CI workflow. The measurement itself
runs in that CI job on every variant.
"""
import re
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / "templates" / "service-dotnet"


@pytest.fixture()
def rendered(shared_renders, tmp_path):
    def render(workdir: Path) -> Path:
        dest = workdir / "size-api"
        subprocess.run(["uv", "tool", "run", "--from", "copier", "copier", "copy", str(TEMPLATE), str(dest), "--defaults",
                        "--trust", "--skip-tasks", "--data", "project_name=size-api", "--data", "description=check",
                        "--data", "needs_database=true"], check=True, capture_output=True)
        return dest
    return shared_renders.copy("1057 size-api", render, tmp_path / "size-api")


def test_the_published_service_leaves_out_what_does_not_run(rendered):
    csproj = next((rendered / "src").glob("*/*.csproj")).read_text()
    assert "<IsTransformWebConfigDisabled>true</IsTransformWebConfigDisabled>" in csproj
    assert "<PublishDocumentationFile>false</PublishDocumentationFile>" in csproj
    froms = re.findall(r"^FROM (?:--platform=\S+ )?(\S+)", (rendered / "Dockerfile").read_text(), re.M)
    assert froms[-1].endswith("-noble-chiseled"), froms[-1]   # not -extra (ICU), not the SDK


def _image_step() -> dict:
    wf = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text())
    return next(s for s in wf["jobs"]["smoke-test-service-dotnet"]["steps"] if "docker build" in str(s.get("run", "")))


def test_the_ci_smoke_fails_an_image_over_its_byte_budget():
    step = _image_step()
    budget = step["env"]["IMAGE_BUDGET_BYTES"]
    assert isinstance(budget, int) and 130_000_000 < budget <= 150_000_000
    run = step["run"]
    export = run.index("docker export")
    assert run.index("docker build") < export < run.index("docker run -d --name smoke --read-only")   # measured before the service starts
    assert re.search(r'if \[ "\$bytes" -gt "\$IMAGE_BUDGET_BYTES" \]; then\n.*exit 1', run)

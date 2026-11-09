"""The platform CI smoke-tests the service-go template with the Go version the template pins: the template moved to
Go 1.26 while CI stayed on 1.25, and `go mod tidy` refused the rendered go.mod."""
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_ci_sets_up_the_go_version_the_service_go_template_pins():
    default = yaml.safe_load((ROOT / "templates" / "service-go" / "copier.yml").read_text())["go_version"]["default"]
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    assert re.findall(r"go-version: '([^']+)'", ci) == [default]

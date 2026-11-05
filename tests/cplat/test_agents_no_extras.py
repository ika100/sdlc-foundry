"""Found in both journeys of 2026-11-05: a build agent added an `image-smoke` recipe and script nobody asked for, and in
journey 2 it was merged. The coder and deployment agents of every language add nothing beside their task."""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("plugin", ["svc", "svc-go", "svc-java", "web"])
def test_coder_and_deployment_add_nothing_the_task_does_not_ask_for(plugin):
    coder = (ROOT / "plugins" / plugin / "agents" / "coder.md").read_text()
    deploy = (ROOT / "plugins" / plugin / "agents" / "deployment.md").read_text()
    assert "nothing beside it: no extra `devbox.json` recipes, scripts or CI jobs" in coder
    assert "Add no recipe, script or CI job the task does not ask for" in deploy

"""Issue #479: the web template's local e2e run picks its port (E2E_PORT, else PORT, else a free one) instead of the
fixed app port, and gives the same port to the server it starts and to the tests' base URL."""
import json
import re
import shutil
import socket
import subprocess

import newsvc
import pytest


@pytest.fixture(scope="module")
def web_repo(tmp_path_factory):
    root = tmp_path_factory.mktemp("web479")
    newsvc.main(["port-web", "desc", "--type", "website", "--no-github", "--skip-tasks", "--dir", str(root), "--org", "acme"])
    return root / "port-web"


def test_the_e2e_server_and_base_url_share_the_chosen_port(web_repo):
    cfg = (web_repo / "playwright.config.ts").read_text()
    assert "3000" not in re.sub(r"//.*", "", cfg)                      # no fixed port outside the comments
    assert "process.env.E2E_PORT = process.env.PORT || freePort()" in cfg
    assert "if (!smokeBaseUrl && !process.env.E2E_PORT)" in cfg       # an explicit E2E_PORT wins, a deployment needs none
    assert "command: `pnpm build && pnpm exec next start --port ${port}`" in cfg
    assert "url: `http://localhost:${port}/api/health`" in cfg
    assert "baseURL: smokeBaseUrl || `http://localhost:${port}`" in cfg


def test_the_app_keeps_its_own_port(web_repo):
    scripts = json.loads((web_repo / "package.json").read_text())["scripts"]
    assert scripts["start"] == "next start --port 3000" and scripts["dev"] == "next dev --port 3000"


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_the_free_port_helper_returns_a_port_that_is_free(web_repo):
    cfg = (web_repo / "playwright.config.ts").read_text()
    script = re.search(r'const script = "([^"]+)";', cfg).group(1)
    with socket.socket() as busy:                                     # 3000-style clash: some port is taken
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        out = subprocess.run(["node", "-e", script], text=True, capture_output=True, check=True, timeout=30).stdout
        port = int(out.strip())
        assert 0 < port < 65536 and port != busy.getsockname()[1]
    with socket.socket() as s:
        s.bind(("127.0.0.1", port))                                   # still bindable: the helper released it

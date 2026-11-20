"""#869: unattended sessions load only the plugins their shape and command use, and no MCP server."""
import json

import pytest

import headless
import shapecmd


@pytest.fixture()
def home(tmp_path, monkeypatch):
    h = tmp_path / "claude-home"
    h.mkdir()
    (h / "settings.json").write_text(json.dumps({"enabledPlugins": {
        "component@sdlc-foundry": True, "shared@sdlc-foundry": True, "svc@sdlc-foundry": True, "web@sdlc-foundry": True,
        "svc-go@sdlc-foundry": True, "system@sdlc-foundry": True, "resource@sdlc-foundry": True,
        "app@sdlc-foundry": False, "context7@claude-plugins-official": True}}))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(h))
    monkeypatch.delenv("CPLAT_HEADLESS_LEAN", raising=False)
    return h


def web_route(repo):
    return {"shape": "web-nextjs", "plugin": "web",
            "agents": {"coder": "web:coder", "architect": "svc:architect", "quality": "shared:quality"}}


def settings_of(cmd):
    return json.loads(cmd[cmd.index("--settings") + 1])


def test_a_ship_session_switches_off_the_plugins_its_shape_does_not_use(home, tmp_path, monkeypatch):
    monkeypatch.setattr(shapecmd, "route", web_route)
    cmd = headless.claude_cmd("/component:ship 1 --unit plan", "sonnet", repo=tmp_path)
    assert settings_of(cmd)["enabledPlugins"] == {"svc-go@sdlc-foundry": False, "system@sdlc-foundry": False,
                                                  "resource@sdlc-foundry": False, "context7@claude-plugins-official": False}
    assert cmd[cmd.index("--mcp-config") + 1] == '{"mcpServers":{}}' and "--strict-mcp-config" in cmd


def test_the_command_s_own_plugin_stays_on(home, tmp_path, monkeypatch):
    monkeypatch.setattr(shapecmd, "route", web_route)
    assert "system@sdlc-foundry" not in settings_of(headless.claude_cmd("/system:ship 3", "sonnet", repo=tmp_path))["enabledPlugins"]


def test_repo_settings_and_permissions_share_one_settings_flag(home, tmp_path, monkeypatch):
    monkeypatch.setattr(shapecmd, "route", web_route)
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "settings.json").write_text(json.dumps({"enabledPlugins": {"svc-go@sdlc-foundry": False}}))
    cmd = headless.claude_cmd("/component:ship 1", "sonnet", rules={"allow": ["Bash(cplat *)"]}, repo=tmp_path)
    assert cmd.count("--settings") == 1
    s = settings_of(cmd)
    assert s["permissions"] == {"allow": ["Bash(cplat *)"]} and "svc-go@sdlc-foundry" not in s["enabledPlugins"]


def test_an_unknown_shape_keeps_the_plugins_but_still_starts_no_mcp_server(home, tmp_path, monkeypatch):
    def no_shape(repo):
        raise headless.PlatformError("no shape")
    monkeypatch.setattr(shapecmd, "route", no_shape)
    cmd = headless.claude_cmd("/component:fix x", "sonnet", repo=tmp_path)
    assert "--settings" not in cmd and "--strict-mcp-config" in cmd


def test_lean_off_keeps_everything(home, tmp_path, monkeypatch):
    monkeypatch.setattr(shapecmd, "route", web_route)
    monkeypatch.setenv("CPLAT_HEADLESS_LEAN", "0")
    cmd = headless.claude_cmd("/component:ship 1", "sonnet", repo=tmp_path)
    assert "--settings" not in cmd and "--strict-mcp-config" not in cmd

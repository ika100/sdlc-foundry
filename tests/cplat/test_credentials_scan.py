"""The credentials ConfigMap passes the gitops repo's own secrets scan.

detect-secrets reads a YAML file structurally and reports a whole value at its key line; the credentials Job's create.py (spec 128)
looks like a secret to it (an alphabet constant, names such as SA_DIR), so every repo with a cache, broker, bucket or generated component
secret had a red `security` check. The renderer writes create.py as a literal block whose header line carries the allowlist pragma;
plan.json and every other value stay scanned. No credential value is ever rendered (ADR-072)."""
import pytest
import yaml
from broker_fixtures import bdir, broker, bsys
from cache_fixtures import csys
from credentials_fixtures import addon, files_in, overlay, script_text
from resources_fixtures import ENVS, comp, ok, system

PRAGMA = "  create.py: |  # pragma: allowlist secret"


def bucket_sys():
    return system({"files": {"type": "bucket"}}, {"api": comp("api", ["files"])})


def gen_sys():
    return system(None, {"api": comp("api", secrets=[{"name": "api-auth", "generate": ["JWT_KEY"]}])})


OWNERS = {
    "cache": (csys, lambda env: addon(env, "sessions")),
    "broker": (lambda: bsys({"bus": broker()}), bdir),
    "bucket": (bucket_sys, lambda env: addon(env, "files")),
    "component": (gen_sys, lambda env: overlay(env, "api")),
}


@pytest.mark.parametrize("owner", sorted(OWNERS))
def test_create_py_is_a_literal_block_with_the_allowlist_pragma_on_its_header(tmp_path, owner):
    make, directory = OWNERS[owner]
    g = ok(tmp_path, make())
    for env in ENVS:
        text = files_in(g, directory(env))["credentials-configmap.yaml"]
        lines = text.splitlines()
        assert PRAGMA in lines, text[:400]
        assert sum("pragma: allowlist secret" in line for line in lines) == 1, "only the create.py header is allowlisted"
        data = yaml.safe_load(text)["data"]
        assert data["create.py"] == script_text(), "the pragma is a YAML comment: the script is unchanged"
        assert "plan.json" in data and "pragma" not in data["plan.json"]


def test_no_other_rendered_file_carries_the_pragma(tmp_path):
    g = ok(tmp_path, csys())
    marked = [p for p, t in g.items() if isinstance(t, str) and "pragma: allowlist secret" in t]
    assert marked and all(p.endswith("/credentials-configmap.yaml") for p in marked), marked

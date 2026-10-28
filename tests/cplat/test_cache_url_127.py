"""Spec 127 acceptance tests, the cache URL part: AC-127.1 (the rendered Secret template names the user `default`) and AC-127.3
(the e2e cluster test probes with the component's variable unchanged).

Contract: docs/specs/127-.../design.md "Rendered Secret template". The renderer runs as a script in a hand-built checkout; nothing
touches the network or a cluster. AC-127.3 is a file-content check of tests/e2e/run.sh and tests/e2e/upgrade.sh."""
import re

import pytest

from cache_fixtures import CKEYS, cache, cdoc, csys, expected_externalsecret
from resources_fixtures import ENVS, comp, ok
from system_fixtures import ROOT

E2E = ROOT / "tests" / "e2e"


def new_form(env="dev", name="sessions") -> str:
    return "redis://default:{{ .password }}@" + f"shop-{name}.shop-{env}.svc:6379/0"


def test_the_cache_secret_template_names_the_default_user_in_every_environment_ac_127_1(tmp_path):  # AC-127.1
    g = ok(tmp_path, csys())
    for env in ENVS:
        data = cdoc(g, env, "externalsecret.yaml")["spec"]["target"]["template"]["data"]
        assert data["url"] == new_form(env), env


def test_every_cache_of_a_system_gets_the_new_url_ac_127_1(tmp_path):  # AC-127.1
    g = ok(tmp_path, csys({"sessions": cache(), "ratelimit": cache(persistence=True)},
                          {"api": comp("api", ["sessions", "ratelimit"])}))
    for env in ENVS:
        for name in ("sessions", "ratelimit"):
            data = cdoc(g, env, "externalsecret.yaml", name)["spec"]["target"]["template"]["data"]
            assert data["url"] == new_form(env, name), (env, name)


def test_only_the_url_changes_keys_secret_name_policy_and_generator_stay_ac_127_1(tmp_path):  # AC-127.1
    g = ok(tmp_path, csys())
    for env in ENVS:
        es = cdoc(g, env, "externalsecret.yaml")
        want = expected_externalsecret(env)
        want["spec"]["target"]["template"]["data"]["url"] = new_form(env)
        assert es == want, env
        assert list(es["spec"]["target"]["template"]["data"]) == CKEYS
        assert es["metadata"]["name"] == "shop-sessions-app" and es["spec"]["refreshPolicy"] == "CreatedOnce"


def test_the_old_empty_user_form_is_gone_from_the_rendered_cache_files_ac_127_1(tmp_path):  # AC-127.1
    g = ok(tmp_path, csys())
    cache_files = {k: t for k, t in g.items() if "/sessions/" in k}
    assert cache_files
    for k, t in cache_files.items():
        assert not re.search(r"redis://:", t), k


@pytest.mark.parametrize("path", ["templates/gitops-app/scripts/render.py", "templates/cluster-gitops/scripts/system_render.py"])
def test_both_renderer_copies_write_the_default_user_ac_127_1(path):  # AC-127.1
    text = (ROOT / path).read_text()
    assert "redis://default:{{ .password }}@" in text, path
    assert "redis://:{{ .password }}@" not in text, path


# ---------------- AC-127.3: the e2e scripts ----------------

def e2e_run() -> str:
    return (E2E / "run.sh").read_text()


def test_run_sh_expects_the_default_user_in_the_secret_ac_127_3():  # AC-127.3
    text = e2e_run()
    assert "redis://default:${pw_sessions}@e2e-sessions.e2e-dev.svc:6379/0" in text
    assert "redis://:${pw_sessions}" not in text


def test_run_sh_no_longer_rewrites_the_url_before_probing_ac_127_3():  # AC-127.3
    text = e2e_run()
    assert not re.search(r"sed\s+\"s#\^redis://:#redis://default:#\"", text), "the rewrite to redis://default: is still in run.sh"
    assert "redis://:#redis://default:#" not in text
    assert not re.search(r"\blocal fix=|\$fix\b|\$\{fix\}", text), "the `fix` prefix of the probe script is still there"


def test_run_sh_probes_with_the_components_variable_unchanged_ac_127_3():  # AC-127.3
    text = e2e_run()
    assert 'valkey-cli -u "$SESSIONS_REDIS_URL"' in text
    assert 'valkey-cli -u "$RATELIMIT_REDIS_URL"' in text


def test_upgrade_sh_keeps_the_rewrite_for_a_cache_made_by_the_previous_release_ac_127_3():  # AC-127.3
    text = (E2E / "upgrade.sh").read_text()
    assert "s#^redis://:#redis://default:#" in text

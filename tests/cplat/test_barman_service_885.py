"""#885: the backup plugin wait job dialled `<release>.cnpg-system.svc`, which only worked because the release happens to be called
`barman-cloud`. The chart's Service name is fixed in its values (`service.name: barman-cloud`, "DO NOT CHANGE"), and the local
cluster installs the chart under another release (`plugin-barman-cloud`), so the job now dials the chart's Service, whatever the
release is called."""
from resources_fixtures import platform_render_module


def test_the_wait_job_dials_the_charts_service_not_the_release_885():
    r = platform_render_module("render_885")
    r.OPERATORS["plugin-barman-cloud"]["release"] = "plugin-barman-cloud"   # the local cluster's HelmChart name
    env = {e["name"]: e["value"] for e in r.plugin_wait_job("orders-db", {})["spec"]["template"]["spec"]["containers"][0]["env"]}
    assert env["PLUGIN_HOST"] == "barman-cloud.cnpg-system.svc" and env["PLUGIN_PORT"] == "9090"

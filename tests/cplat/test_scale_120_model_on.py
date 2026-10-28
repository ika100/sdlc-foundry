"""Spec 120: the model reads a scale whose `on` key YAML 1.1 parsed as the boolean True (an unquoted `on:`)."""
import yaml

from resources_fixtures import comp, system
from scale_fixtures import RES
from system_fixtures import mod, write_system


def test_an_unquoted_on_key_read_as_true_is_the_on_trigger_ac_120_21(tmp_path):  # AC-120.21
    doc = system(None, {"api": comp("api", resources=RES, scale={"max": 4, True: {"cpu": 70}})})
    app = write_system(tmp_path, doc)
    assert True in yaml.safe_load((app / "system.yaml").read_text())["components"]["api"]["scale"]
    inst = {(i.component, i.environment): i for i in mod("model").load_dir(app).instances}
    assert inst[("api", "dev")].scale["on"] == {"cpu": 70}

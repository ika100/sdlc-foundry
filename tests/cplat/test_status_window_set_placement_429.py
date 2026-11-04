"""#429: two small output issues. The restore window in status read backwards right after the first backup, and
`system set` wrote a new key below the comment lines that follow an environment's block."""
import io

import backupstate
import systemset
from ruamel.yaml import YAML

TEXT = """environments:
  dev:
    host: "{component}.{system}-dev.localhost"
    policy: "off"
  prod:
    policy: "off"
    # host: "{component}.example.com"
# components: add with `/component:new`; each runs in the environments listed under its `instances`.
components: {}
"""


def test_the_newest_restore_point_is_never_before_the_earliest():
    assert backupstate.ordered_latest("2026-11-04T20:37:56Z", "2026-11-04T20:30:06Z") == "2026-11-04T20:37:56Z"
    assert backupstate.ordered_latest("2026-11-04T20:37:56Z", "2026-11-04T21:05:00Z") == "2026-11-04T21:05:00Z"
    assert backupstate.ordered_latest("2026-11-04T20:37:56Z", None) is None
    assert backupstate.ordered_latest(None, "2026-11-04T21:05:00Z") == "2026-11-04T21:05:00Z"


def _set(text: str, env: str, key: str, value: str) -> str:
    y = YAML()
    y.preserve_quotes = True
    data = y.load(text)
    systemset.add_key(data["environments"][env], key, value)
    out = io.StringIO()
    y.dump(data, out)
    return out.getvalue()


def test_a_new_key_goes_inside_its_environment_before_the_trailing_comments():
    out = _set(TEXT, "prod", "host", "{component}.{system}-prod.localhost")
    lines = out.splitlines()
    i = lines.index("  prod:")
    assert lines[i + 1:i + 3] == ['    policy: "off"', "    host: '{component}.{system}-prod.localhost'"] \
        or lines[i + 1:i + 3] == ['    policy: "off"', "    host: {component}.{system}-prod.localhost"], out
    assert lines.index("# components: add with `/component:new`; each runs in the environments listed under its `instances`.") \
        > lines.index("    # host: \"{component}.example.com\""), out
    assert YAML().load(out)["environments"]["prod"]["host"] == "{component}.{system}-prod.localhost"


def test_an_existing_key_is_changed_in_place():
    out = _set(TEXT, "dev", "policy", "audit")
    assert YAML().load(out)["environments"]["dev"] == {"host": "{component}.{system}-dev.localhost", "policy": "audit"}
    assert out.index("audit") < out.index("  prod:")      # changed where it was, in the dev block

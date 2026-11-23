"""#1027: /system:plan starts its spec branch fresh from main, because `/system:spec approve` squash-merged the old one.

Journey 28: the local `docs/spec-<id>` branch outlived the squash merge, the coordinator switched to it, its
`--ff-only` merge of main failed, and it reset the branch and tried a force push by itself."""
import core

PLAN = core.PLATFORM_ROOT / "plugins/system/commands/plan.md"


def _preflight() -> str:
    text = PLAN.read_text()
    return text.split("## 1. Pre-flight", 1)[1].split("\n## ", 1)[0]


def test_preflight_branches_from_main_before_the_spec_check():
    steps = _preflight()
    # a plain "switch to" reused the stale branch, so the git command itself is the interface
    branch = steps.index("git switch -C docs/spec-<spec_id> main")  # interface: the command the coordinator runs
    check = steps.index("cplat spec check <id>")  # interface: the command the coordinator runs
    assert branch < check

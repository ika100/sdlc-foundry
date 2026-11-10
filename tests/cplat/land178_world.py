"""Spec 178: the land world of spec 171 with a stricter fake GitHub (not a test file).

`land171_world.World` is reused as it is; only the `gh` stub it installs is extended (the extension is applied to the stub text
before the world is built, so the 171 tests keep their own stub):

  `pr checks --required --json name`   answers from `state["required"]` and moves no poll
  `api …/protection/required_status_checks`  answers the same names as the branch's required checks
  per-head check scripts               `state["scripts"][sha]` or, for any head but `state["orig_head"]`, `state["moved_script"]`:
                                       one `{check name: bucket}` answer per poll (the last one repeats)
  `state["strict"]`                    a merge is refused like GitHub does while a required check of the head is not `pass` in
                                       the last answer given for it (a check that was never reported is pending)
  `state["refuse_next"]`               reasons of merges to refuse, one per merge call, before anything else is looked at

Every merge call is logged as `merge-attempt` with `pending`: the required checks of the head that were not green when it came.
"""
import fcntl
import json

import land171_world
from land171_world import BRANCH, PR_URL, World  # noqa: F401  (re-exported for the tests)

import dispatch_state

NEW_CHECKS = '''if cmd == ["pr", "checks"]:
    h = head()
    if "--required" in args:
        log(args=args, kind="required", sha=h)
        out([{"name": n} for n in st.get("required", [])])
    st["checks_calls"] += 1
    script = st.get("scripts", {}).get(h)
    if script is None and st.get("moved_script") and h != st.get("orig_head"):
        script = st["moved_script"]
    if script is not None:
        n = st["polls"].get(h, 0)
        st["polls"][h] = n + 1
        poll = script[min(n, len(script) - 1)]
    else:
        b = bucket_of(h)
        poll = {n: b for n in st.get("check_names", ["test"])}
    rid = int(h[:7], 16)
    st["rids"][str(rid)] = h
    st.setdefault("reported", {})[h] = poll
    vals = list(poll.values())
    st["last_bucket"][h] = "fail" if "fail" in vals else "pending" if "pending" in vals else "pass"
    save()
    log(args=args, kind="checks", sha=h, bucket=st["last_bucket"][h], names=sorted(poll))
    states = {"pass": "SUCCESS", "fail": "FAILURE", "pending": "IN_PROGRESS"}
    link = "https://github.com/" + st["slug"] + "/actions/runs/" + str(rid) + "/job/1"
    out([{"name": n, "state": states[b], "bucket": b, "link": link} for n, b in poll.items()])
'''

OLD_ATTEMPT = 'log(args=args, kind="merge-attempt", head=h, match=match, delete_branch="--delete-branch" in args)\n'
NEW_ATTEMPT = '''rep = st.get("reported", {}).get(h) or {}
    pending = [n for n in st.get("required", []) if rep.get(n) != "pass"]
    log(args=args, kind="merge-attempt", head=h, match=match, delete_branch="--delete-branch" in args, pending=pending)
    if st.get("refuse_next"):
        reason = st["refuse_next"].pop(0)
        save()
        fail(reason)
    if st.get("strict") and pending:
        fail("Required status check " + chr(34) + pending[0] + chr(34) + " is expected.")
'''


PROTECTION = '''    if path.endswith("/protection/required_status_checks"):
        log(args=args, kind="protection", path=path)
        out({"contexts": st.get("required", []), "checks": [{"context": n} for n in st.get("required", [])]})
'''


def patched_stub() -> str:
    text = land171_world.STUB
    assert text.count('    print("tester")\n') == 1, "the api fallback of the 171 stub changed"
    text = text.replace('    print("tester")\n', PROTECTION + '    print("tester")\n')
    start, end = text.index('if cmd == ["pr", "checks"]:'), text.index('if cmd == ["run", "view"]:')
    text = text[:start] + NEW_CHECKS + text[end:]
    assert text.count(OLD_ATTEMPT) == 1, "the merge-attempt line of the 171 stub changed"
    return text.replace(OLD_ATTEMPT, NEW_ATTEMPT)


def make_world(tmp_path, monkeypatch) -> World:
    monkeypatch.setattr(land171_world, "STUB", patched_stub())
    world = World(tmp_path, monkeypatch)
    world.configure(strict=True, orig_head=world.pre)
    return world


def lock_is_held(slug: str) -> bool:
    """Whether some open file description holds the repo merge lock of `slug` (a probe on its own descriptor)."""
    path = dispatch_state.merge_lock_path(slug)
    if not path.exists():
        return False
    with open(path, "a") as probe:
        try:
            fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(probe, fcntl.LOCK_UN)
        return False


def state(world) -> dict:
    return json.loads((world.dir / "state.json").read_text())

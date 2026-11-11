"""Spec 167 acceptance tests: the fake `gh` executable of the dispatcher world (see `dispatch_world.py`).

It is a script on PATH, so every module that calls `gh` (snapshot, claims, labels, comments, `pr wait`, the merge lock) is served the
same way, whatever seam it goes through. State lives in the JSON file `$FAKE_GH_STATE` (one flock per call, written atomically
with a temp file and `os.replace`), every call is logged under `log`, and the `merge` of a pull request can take time (`merge_delay`) with the lock released, so two
concurrent merges really overlap when nothing serializes them.
"""
import sys

from waiting import fake_prelude

BODY = r'''
import fcntl, json, os, re, subprocess, sys, time

PATH = os.environ["FAKE_GH_STATE"]
LOCK = open(PATH + ".lock", "a+")
fcntl.flock(LOCK, fcntl.LOCK_EX)
args = sys.argv[1:]


def load():
    with open(PATH) as fh:
        return json.load(fh)


S = load()
if S.get("closed"):                      # the world of the test is over: nothing of a leftover process reaches it
    print("fake gh: world closed", file=sys.stderr)
    sys.exit(1)


def save():
    tmp = f"{PATH}.{os.getpid()}.tmp"      # atomic: a reader sees the old or the new document, never half of one
    with open(tmp, "w") as fh:
        json.dump(S, fh)
    os.replace(tmp, PATH)


S["log"].append({"argv": args, "t": time.time(), "cwd": os.getcwd()})
save()


def unlock():
    save()
    fcntl.flock(LOCK, fcntl.LOCK_UN)


def relock():
    global S
    fcntl.flock(LOCK, fcntl.LOCK_EX)
    S = load()


def opt(*names, multi=False, default=None):
    vals = []
    for i, a in enumerate(args):
        for n in names:
            if a == n and i + 1 < len(args):
                vals.append(args[i + 1])
            elif a.startswith(n + "=") and n.startswith("--"):
                vals.append(a.split("=", 1)[1])
    if multi:
        return [x for v in vals for x in v.split(",")]
    return vals[-1] if vals else default


def jq(expr, obj):
    if not re.fullmatch(r"\.[A-Za-z_][\w.]*", expr or ""):
        return json.dumps(obj)
    for part in expr.strip(".").split("."):
        obj = obj.get(part) if isinstance(obj, dict) else None
    if obj is None:
        return ""
    return obj if isinstance(obj, str) else json.dumps(obj)


def emit(obj):
    fields = opt("--json")
    if fields and isinstance(obj, dict):
        obj = {k: obj.get(k) for k in fields.split(",")}
    elif fields and isinstance(obj, list):
        obj = [{k: o.get(k) for k in fields.split(",")} for o in obj]
    expr = opt("--jq", "-q")
    print(jq(expr, obj) if expr else json.dumps(obj))


def issue_view(i):
    return {"number": i["number"], "title": i["title"], "body": i.get("body", ""), "state": i["state"],
            "labels": [{"name": n} for n in i["labels"]], "assignees": [{"login": a} for a in i.get("assignees", [])],
            "createdAt": i["createdAt"], "updatedAt": i.get("updatedAt") or i["createdAt"], "comments": i["comments"],
            "url": f"https://github.com/{S['slug']}/issues/{i['number']}", "stateReason": None,
            "closed": i["state"] == "CLOSED"}


def pr_view(p):
    merged = p["state"] == "MERGED"
    return {"number": p["number"], "url": p["url"], "title": p.get("title", ""), "body": p.get("body", ""), "state": p["state"],
            "isDraft": p.get("isDraft", False), "headRefName": p["headRefName"], "baseRefName": "main", "headRefOid": p["head"],
            "mergeable": "MERGEABLE", "mergeCommit": {"oid": "m" + str(p["number"])} if merged else None,
            "closingIssuesReferences": [{"number": n} for n in p.get("closes", [])],
            "labels": [{"name": n} for n in p.get("labels", [])], "statusCheckRollup": [], "reviewDecision": ""}


def find_pr(ref):
    ref = str(ref)
    m = re.search(r"/pull/(\d+)", ref) or re.fullmatch(r"#?(\d+)", ref)
    if m:
        return S["prs"].get(m.group(1))
    return next((p for p in S["prs"].values() if p["headRefName"] == ref), None)


def checks_of(p):
    s = p["seqs"].setdefault(p["head"], {"seq": json.loads(json.dumps(S["default_checks"])), "i": 0})
    snap = s["seq"][min(s["i"], len(s["seq"]) - 1)]
    s["i"] += 1
    p.setdefault("last", {})[p["head"]] = snap
    return snap


def body_text():
    b = opt("--body", "-b")
    f = opt("--body-file", "-F")
    if b is not None:
        return b
    if f:
        return sys.stdin.read() if f == "-" else open(f).read()
    return ""


def now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


cmd = args[:2]
if cmd == ["issue", "list"]:
    state = opt("--state", "-s", default="open")
    want = opt("--label", "-l", multi=True)
    rows = [i for i in S["issues"].values() if state == "all" or i["state"].lower() == state]
    rows = [i for i in rows if all(w in i["labels"] for w in want)]
    emit([issue_view(i) for i in sorted(rows, key=lambda i: i["number"])])
elif cmd == ["issue", "view"]:
    i = S["issues"].get(args[2].lstrip("#"))
    if not i:
        print("issue not found", file=sys.stderr)
        sys.exit(1)
    emit(issue_view(i))
elif cmd == ["issue", "edit"]:
    i = S["issues"][args[2].lstrip("#")]
    for n in opt("--add-label", multi=True):
        if n not in i["labels"]:
            i["labels"].append(n)
        if n not in S["labels"]:
            S["labels"].append(n)
    for n in opt("--remove-label", multi=True):
        if n in i["labels"]:
            i["labels"].remove(n)
    for a in opt("--add-assignee", multi=True):
        i.setdefault("assignees", []).append("me" if a == "@me" else a)
    for a in opt("--remove-assignee", multi=True):
        i["assignees"] = [x for x in i.get("assignees", []) if x != ("me" if a == "@me" else a)]
elif cmd == ["issue", "comment"]:
    i = S["issues"][args[2].lstrip("#")]
    i["comments"].append({"body": body_text(), "createdAt": now_iso(), "author": {"login": "me"}})
elif cmd == ["issue", "close"]:
    i = S["issues"][args[2].lstrip("#")]
    c = opt("--comment", "-c")
    if c:
        i["comments"].append({"body": c, "createdAt": now_iso(), "author": {"login": "me"}})
    i["state"] = "CLOSED"
elif cmd == ["issue", "reopen"]:
    S["issues"][args[2].lstrip("#")]["state"] = "OPEN"
elif cmd == ["label", "create"]:
    if args[2] not in S["labels"]:
        S["labels"].append(args[2])
elif cmd == ["label", "list"]:
    emit([{"name": n} for n in S["labels"]])
elif cmd == ["pr", "list"]:
    state = opt("--state", "-s", default="open")
    head = opt("--head", "-H")
    rows = [p for p in S["prs"].values() if state == "all" or p["state"].lower() == state]
    rows = [p for p in rows if not head or p["headRefName"] == head]
    emit([pr_view(p) for p in sorted(rows, key=lambda p: p["number"])])
elif cmd == ["pr", "view"]:
    p = find_pr(args[2])
    if not p:
        print("no pull requests found", file=sys.stderr)
        sys.exit(1)
    emit(pr_view(p))
elif cmd == ["pr", "checks"]:
    p = find_pr(args[2])
    snap = checks_of(p)
    print(json.dumps([{"name": c["name"], "state": c["bucket"].upper(), "bucket": c["bucket"],
                       "link": f"https://github.com/{S['slug']}/actions/runs/42/job/{c['name']}"} for c in snap]))
elif cmd == ["pr", "create"]:
    n = str(max([int(k) for k in S["prs"]] + [99]) + 1)
    head = opt("--head", "-H") or subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True, text=True).stdout.strip()
    body = body_text()
    closes = [int(x) for x in re.findall(r"(?i)\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#(\d+)", body)]
    sha = f"sha{n}-0"
    S["prs"][n] = {"number": int(n), "url": f"https://github.com/{S['slug']}/pull/{n}", "title": opt("--title", "-t", default=""),
                   "body": body, "state": "OPEN", "isDraft": "--draft" in args, "headRefName": head, "head": sha, "behind": 0,
                   "closes": closes, "labels": [], "seqs": {}, "after_update_checks": None}
    print(S["prs"][n]["url"])
elif cmd == ["pr", "update-branch"]:
    p = find_pr(args[2])
    if S.get("update_conflict"):
        print("merge conflict", file=sys.stderr)
        sys.exit(1)
    k = p.get("updates", 0) + 1
    p["updates"], p["behind"] = k, 0
    p["head"] = f"{p['head'].split('u')[0]}u{k}"
    p["seqs"][p["head"]] = {"seq": json.loads(json.dumps(p.get("after_update_checks") or [[{"name": "ci", "bucket": "pending"}],
                                                                                          [{"name": "ci", "bucket": "pass"}]])), "i": 0}
    S["events"].append({"ev": "updated", "pr": p["number"], "t": time.time()})
    print("Branch updated")
elif cmd == ["pr", "merge"]:
    p = find_pr(args[2])
    mh = opt("--match-head-commit")
    S["events"].append({"ev": "merge-start", "pr": p["number"], "t": time.time()})
    unlock()
    time.sleep(S.get("merge_delay", 0))  # fake-delay: the merge takes merge_delay seconds with the lock released, so two merges overlap
    hold = S.get("merge_hold_for_checks_of")
    if hold:                              # the merge stays under way until the call named here has been logged (an event, not a timing)
        end = time.time() + 60
        while time.time() < end and not any(a["argv"][:2] == ["pr", "checks"] and a["argv"][2].endswith(hold) for a in load()["log"]):
            time.sleep(0.02)  # fake-delay: polls the call log until the other pull request has asked for its checks
    relock()
    p = find_pr(args[2])
    if mh and mh != p["head"]:
        print("Head branch was modified (match-head-commit)", file=sys.stderr)
        sys.exit(1)
    last = p.get("last", {}).get(p["head"])
    green = bool(last) and all(c["bucket"] in ("pass", "skipping") for c in last)
    S["events"].append({"ev": "merged", "pr": p["number"], "head": p["head"], "behind": p["behind"], "green": green, "t": time.time()})
    p["state"] = "MERGED"
    S["main"] += 1
    for q in S["prs"].values():
        if q["state"] == "OPEN":
            q["behind"] += 1
    for n in p.get("closes", []):
        if str(n) in S["issues"]:
            S["issues"][str(n)]["state"] = "CLOSED"
    print(f"Merged {p['url']}")
elif cmd in (["pr", "close"], ["pr", "ready"], ["pr", "edit"], ["pr", "comment"]):
    p = find_pr(args[2])
    if p and cmd[1] == "close":
        p["state"] = "CLOSED"
elif cmd == ["repo", "view"]:
    owner, name = S["slug"].split("/")
    emit({"nameWithOwner": S["slug"], "name": name, "owner": {"login": owner}, "defaultBranchRef": {"name": "main"}})
elif args[:1] == ["api"]:
    path = args[1]
    m = re.search(r"/compare/[^/]+\.\.\.(.+)$", path)
    if m:
        p = next((q for q in S["prs"].values() if q["head"] == m.group(1)), None)
        emit({"behind_by": p["behind"] if p else 0, "ahead_by": 1})
    elif path == "user":
        emit({"login": "me"})
    else:
        m = re.search(r"/issues/(\d+)/comments$", path)
        emit(S["issues"][m.group(1)]["comments"] if m else {})
elif args[:2] in (["run", "list"], ["secret", "list"]):
    print("[]")
save()
'''


def script() -> str:
    return f"#!{sys.executable}\n{fake_prelude()}\n{BODY}"

"""`cplat spec trace <id> --chain` (spec 109): the chain per active criterion, from issue to environment, read-only.

Links: issue, spec, criterion, tests, verdict, pr, release, env dev/staging/prod. Each has one state: ok, missing, stale,
unknown (with the reason) or n/a (with the reason). Local links come from the repo and git; every remote read goes through
`spec_chain_remote.Remote` (one `gh` seam, one probe), so this module never runs `gh`. Nothing is written, nothing fetched.
What cannot be read is `unknown`, never guessed. The exit code is 0 whenever the chain was printed (AC-109.11).
See docs/specs/109-*/design.md."""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import core
import evidence
import model
import ship
import spec as specmod
import spec_chain_remote as remote_mod

STATES = ("ok", "missing", "stale", "unknown", "n/a")
NA_LATER = {"draft": "spec not yet built", "approved": "spec not yet built", "building": "spec not yet done",
            "superseded": "spec superseded"}
PRODUCT_NA = "product spec: traced in its component repos"
COMMIT_HDR = re.compile(r"\*\*Commit:\*\*\s*([0-9a-f]{7,40})")
UNVERIFIED = re.compile(r"^-\s+\S+\s+done:\s*unverified:\s*(.+?)\s*$", re.M)
SEPARATOR = re.compile(r"^:?-{2,}:?$")
VERDICT_CELL = re.compile(r"^(not met|partial|met)\b(.*)$", re.I | re.S)
SHA_PIN = re.compile(r"^sha-([0-9a-f]{7,40})$")
RELEASE_TAG = re.compile(r"^v\d+\.\d+\.\d+$")
MAX_WALK = 500


# ---------------- small helpers ----------------

def _link(name: str, state: str, text: str, **extra) -> dict:
    return {"link": name, "state": state, "text": text, **extra}


def _guard(name: str, defaults: dict, fn) -> dict:
    """A resolver that raises never ends the run: the link becomes `unknown: <Type>: <message>`."""
    try:
        return fn()
    except Exception as ex:  # noqa: BLE001 - by contract any resolver failure is one unknown link
        return _link(name, "unknown", f"{type(ex).__name__}: {ex}", **defaults)


def _git(root: Path, *args: str) -> tuple[int, str]:
    try:
        p = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=False)
    except OSError:
        return 127, ""
    return p.returncode, p.stdout


def _rel(root: Path, path: Path) -> str:
    return "./" + path.relative_to(root).as_posix()


# ---------------- verdict reader ----------------

def _cells(line: str) -> list[str]:
    s = line.strip()
    s = s[1:] if s.startswith("|") else s
    s = s[:-1] if s.endswith("|") else s
    return [c.strip() for c in s.split("|")]


def _norm(cell: str) -> str:
    return cell.replace("*", "").replace("`", "").strip().lower()


def read_rows(text: str) -> list[tuple[str, str]]:
    """(AC id, verdict cell) for every row, in file order. Any table whose header has a Criterion and a Verdict cell counts
    (any column positions, several tables); files without such a header fall back to the first and second cell."""
    headed: list[tuple[str, str]] = []
    fallback: list[tuple[str, str]] = []
    in_table, cols, saw_header = False, None, False
    for line in text.splitlines():
        if not line.lstrip().startswith("|"):
            in_table = False
            continue
        cells = _cells(line)
        if cells and all(SEPARATOR.match(c.replace(" ", "")) for c in cells if c) and any(cells):
            continue
        if not in_table:
            in_table = True
            names = [_norm(c) for c in cells]
            cols = (names.index("criterion"), names.index("verdict")) if "criterion" in names and "verdict" in names else None
            saw_header = saw_header or cols is not None
            continue
        if len(cells) < 2:
            continue
        if cols is not None and max(cols) < len(cells):
            m = specmod.AC_ANY.search(cells[cols[0]])
            if m:
                headed.append((m.group(0), cells[cols[1]]))
        elif cols is None:
            m = specmod.AC_ANY.search(cells[0])
            if m:
                fallback.append((m.group(0), cells[1]))
    return headed if saw_header else fallback


def parse_verdict(cell: str) -> tuple[str, str] | None:
    """('met'|'not met'|'partial', qualifier) or None when not readable."""
    clean = cell.replace("`", "").replace("*", "").strip()
    m = VERDICT_CELL.match(clean)
    if not m:
        return None
    rest = m.group(2).strip().lstrip(":-–— ").strip()
    if rest.startswith("(") and rest.endswith(")"):
        rest = rest[1:-1].strip()
    return m.group(1).lower(), rest


# ---------------- the chain ----------------

class Chain:
    def __init__(self, root: Path, spec: specmod.Spec):
        self.root, self.spec = root, spec
        self.remote = remote_mod.Remote(root)
        self.status = spec.status
        self.repo_shape = specmod.repo_shape(root)
        self.own_shape = specmod.spec_shape(spec, self.repo_shape)
        self.product = spec.meta.get("shape") == "gitops-app"
        self.done = self.status == "done"
        self._cache: dict[str, dict] = {}
        self._pins = None

    # ---- spec-level links, resolved once ----
    def once(self, name: str, defaults: dict, fn) -> dict:
        if name not in self._cache:
            self._cache[name] = _guard(name, defaults, fn)
        return self._cache[name]

    def na(self, name: str, **extra) -> dict | None:
        """The n/a state for links that cannot exist yet; None when the link has to be resolved."""
        if self.product:
            return _link(name, "n/a", PRODUCT_NA, **extra)
        if self.status in NA_LATER:
            return _link(name, "n/a", NA_LATER[self.status], **extra)
        return None

    def issue(self) -> dict:
        d = {"issues": []}

        def run() -> dict:
            tracks = [int(n) for n in (self.spec.meta.get("tracks") or [])]
            if not tracks:
                return _link("issue", "n/a", "no tracked issue", issues=[])
            got = self.remote.issues(tracks)
            nums = ", ".join(f"#{n}" for n in tracks)
            if isinstance(got, str):
                return _link("issue", "unknown", f"{got} ({nums})", issues=[])
            issues = [{"number": n, "state": got[n]} for n in tracks]
            opened = [i["number"] for i in issues if i["state"] != "closed"]
            if self.done and opened:
                return _link("issue", "stale", f"issue still open ({', '.join(f'#{n}' for n in opened)})", issues=issues)
            return _link("issue", "ok", ", ".join(f"#{i['number']} {i['state']}" for i in issues), issues=issues)
        return self.once("issue", d, run)

    # ---- tests ----
    def tests(self) -> dict[str, dict]:
        def run() -> dict:
            globs = specmod.test_globs(self.own_shape)
            traced = specmod.trace(self.root, self.spec, globs)
            smoke = specmod._smoke_traced(self.root, self.spec, self.own_shape)
            out = {}
            for ac, files in traced.items():
                if not files:
                    state, text = "missing", "no test names it"
                elif ac in smoke and not smoke[ac]:
                    state, text = "missing", "no smoke-tagged test"
                else:
                    out[ac] = _link("tests", "ok", ", ".join(files), files=files)
                    continue
                if self.status == "draft":
                    state, text = "n/a", "spec not yet approved"
                elif self.status == "superseded":
                    state, text = "n/a", "spec superseded"
                elif self.product:
                    state, text = "n/a", PRODUCT_NA
                out[ac] = _link("tests", state, text, files=files)
            if self.product:
                return {ac: _link("tests", "n/a", PRODUCT_NA, files=files) for ac, files in traced.items()}
            return out
        try:
            return run()
        except Exception as ex:  # noqa: BLE001
            msg = f"{type(ex).__name__}: {ex}"
            return {ac: _link("tests", "unknown", msg, files=[]) for ac in self.spec.active_acs()}

    # ---- verdicts ----
    def _unverified_reason(self) -> str | None:
        found = UNVERIFIED.findall(self.spec.body)
        return found[-1] if found else None

    def _verified_commit(self, vfile: Path, vtext: str) -> tuple[str | None, str | None]:
        """(commit, unknown reason). commit None = the working tree counts as the verified state."""
        m = COMMIT_HDR.search(vtext)
        commit = None
        if m:
            rc, out = _git(self.root, "rev-parse", "--verify", "-q", f"{m.group(1)}^{{commit}}")
            commit = out.strip() if rc == 0 and out.strip() else None
        if commit is None:
            rc, out = _git(self.root, "log", "-1", "--format=%H", "--", _rel(self.root, vfile))
            if rc != 0:
                return None, "git history not available"
            commit = out.strip() or None
        if commit is None:
            return None, None
        rc, out = _git(self.root, "rev-parse", "--git-path", "shallow")
        if rc == 0 and out.strip():
            sh = Path(out.strip())
            sh = sh if sh.is_absolute() else self.root / sh
            if sh.is_file() and commit in sh.read_text().split():
                return None, "shallow clone: verification history not available"
        return commit, None

    def _hash_at(self, commit: str, rel: str) -> str | None:
        rc, out = _git(self.root, "show", f"{commit}:{rel}")
        if rc != 0:
            return None
        m = specmod.FRONT.match(out)
        return specmod.Spec(self.spec.dir, {}, m.group(2) if m else out).ac_hash()

    def _criteria_changed_at(self, rel: str, current: str) -> str:
        rc, out = _git(self.root, "log", "--format=%H %h", "--", rel)
        commits = [ln.split() for ln in out.splitlines() if ln.strip()] if rc == 0 else []
        commits = commits[:MAX_WALK]
        if not commits or self._hash_at(commits[0][0], rel) != current:
            return "uncommitted"
        for i, (full, short) in enumerate(commits):
            if i + 1 >= len(commits) or self._hash_at(commits[i + 1][0], rel) != current:
                return short
        return commits[-1][1]

    def verdicts(self) -> dict[str, dict]:
        """Verdict link per active criterion; only for a `done` spec."""
        acs = self.spec.active_acs()

        def all_links(state: str, text: str) -> dict[str, dict]:
            return {ac: _link("verdict", state, text, verdict=None) for ac in acs}
        try:
            vfile = self.spec.dir / "verification.md"
            if not vfile.is_file():
                reason = self._unverified_reason()
                return all_links("missing", f"no verification.md (unverified: {reason})" if reason else "no verification.md")
            vtext = vfile.read_text()
            rows = read_rows(vtext)
            commit, why = self._verified_commit(vfile, vtext)
            if why:
                return all_links("unknown", why)
            spec_rel = _rel(self.root, self.spec.dir / "spec.md")
            if commit:
                then = self._hash_at(commit, spec_rel)
                if then is None:
                    return all_links("unknown", f"spec.md not readable at {commit[:7]}")
                current = self.spec.ac_hash()
                if then != current:
                    return all_links("stale", f"criteria changed after verification ({self._criteria_changed_at(spec_rel, current)})")
            known = {a.id: a for a in self.spec.acs()}
            for ac_id, _ in rows:
                if ac_id[3:].split(".", 1)[0] != self.spec.number:
                    continue
                if ac_id not in known or known[ac_id].withdrawn:
                    kind = "a withdrawn" if ac_id in known else "an unknown"
                    return all_links("stale", f"verified {kind} criterion ({ac_id})")
            first: dict[str, str] = {}
            for ac_id, cell in rows:
                first.setdefault(ac_id, cell)
            out = {}
            for ac in acs:
                if ac not in first:
                    out[ac] = _link("verdict", "missing", "not verified", verdict=None)
                    continue
                got = parse_verdict(first[ac])
                if got is None:
                    out[ac] = _link("verdict", "missing", f"verdict '{first[ac]}' not readable", verdict=None)
                    continue
                kind, qual = got
                text = f"{kind} ({qual})" if qual else kind
                out[ac] = _link("verdict", "ok" if kind == "met" else "missing", text, verdict=kind)
            return out
        except Exception as ex:  # noqa: BLE001
            return all_links("unknown", f"{type(ex).__name__}: {ex}")

    # ---- pr, release ----
    def pr(self) -> dict:
        d = {"number": None, "url": None, "merge_commit": None, "merged_at": None, "others": []}

        def run() -> dict:
            branch = f"feature/{self.spec.id}"
            got = self.remote.merged_prs(branch)
            if isinstance(got, str):
                return _link("pr", "unknown", got, **d)
            if not got:
                return _link("pr", "missing", f"no merged PR from {branch}", **d)
            top, others = got[0], [p["number"] for p in got[1:]]
            merge = top.get("merge_commit")
            text = f"#{top['number']} merged {str(top.get('merged_at') or '')[:10]} (merge {(merge or '')[:7]})"
            if others:
                text += "; also merged: " + ", ".join(f"#{n}" for n in others)
            return _link("pr", "ok", text, number=top["number"], url=top.get("url"), merge_commit=merge,
                         merged_at=top.get("merged_at"), others=others)
        return self.once("pr", d, run)

    def _needs_pr(self, name: str, extra: dict) -> dict | None:
        pr = self.pr()
        if pr["state"] == "ok":
            return None
        if pr["state"] == "missing":
            return _link(name, "n/a", "no merged PR", **extra)
        return _link(name, "unknown", f"needs the PR ({pr['text']})", **extra)

    def release(self) -> dict:
        d = {"tag": None}

        def run() -> dict:
            if (blocked := self._needs_pr("release", d)):
                return blocked
            merge = self.pr().get("merge_commit")
            if not merge or _git(self.root, "cat-file", "-e", f"{merge}^{{commit}}")[0] != 0:
                return _link("release", "unknown", "merge commit not fetched", **d)
            rc, out = _git(self.root, "tag", "--list", "v*", "--contains", merge)
            tags = [t for t in out.split() if RELEASE_TAG.match(t)] if rc == 0 else []
            if not tags:
                return _link("release", "missing", "merged, not in a release", **d)
            tag = min(tags, key=lambda t: core.vtuple(t[1:]))
            return _link("release", "ok", tag, tag=tag)
        return self.once("release", d, run)

    # ---- environments ----
    def _service(self) -> str:
        slug = self.remote.slug
        return slug.rsplit("/", 1)[-1] if slug else self.root.name

    def _pin_judge(self, env: str, tag: str) -> dict:
        d = {"tag": tag}
        rel, pr = self.release(), self.pr()
        merge = pr.get("merge_commit")
        older = f"older than {rel['text']}" if rel["state"] == "ok" else f"older than merge {(merge or '')[:7]}"
        m = evidence.RELEASE.match(tag)
        sha = SHA_PIN.match(tag)
        if not m and not sha:
            return _link(f"env {env}", "unknown", f"tag {tag} is neither a release nor sha-<commit>", **d)
        if rel["state"] == "unknown":
            return _link(f"env {env}", "unknown", rel["text"], **d)
        if m:
            if rel["state"] == "ok":
                ok = core.vtuple(m.group(1)) >= core.vtuple(rel["tag"][1:])
            else:
                ok = _git(self.root, "tag", "--list", f"v{m.group(1)}", "--contains", merge or "HEAD")[1].strip() != ""
            return _link(f"env {env}", "ok" if ok else "missing", f"runs {tag}" + ("" if ok else f", {older}"), **d)
        hexsha = sha.group(1)
        rc, out = _git(self.root, "rev-parse", "--verify", "-q", f"{hexsha}^{{commit}}")
        if rc != 0 or not out.strip():
            return _link(f"env {env}", "unknown", f"pinned commit {hexsha[:7]} not fetched", **d)
        if not merge or _git(self.root, "cat-file", "-e", f"{merge}^{{commit}}")[0] != 0:
            return _link(f"env {env}", "unknown", "merge commit not fetched", **d)
        rc, _ = _git(self.root, "merge-base", "--is-ancestor", merge, out.strip())
        if rc == 0:
            return _link(f"env {env}", "ok", f"runs {tag}", **d)
        if rc == 1:
            return _link(f"env {env}", "missing", f"runs {tag}, {older}", **d)
        return _link(f"env {env}", "unknown", f"cannot compare {tag} with the merge commit", **d)

    def env(self, env: str) -> dict:
        name, d = f"env {env}", {"tag": None}

        def run() -> dict:
            if (n := self.na(name, **d)):
                return n
            if model.type_lang(self.repo_shape or self.own_shape)[0] == "library":
                return _link(name, "n/a", "library: no environments", **d)
            apps = ship.gitops_apps(self.root)
            if not apps:
                return _link(name, "n/a", "not linked to a gitops-app (no .platform-app.yml)", **d)
            if (blocked := self._needs_pr(name, d)):
                return blocked
            if self._pins is None:
                self._pins = self.remote.pins(apps, self._service())
            pins = self._pins
            if isinstance(pins, str):
                return _link(name, "unknown", pins, **d)
            if pins.component is None:
                return _link(name, "missing", f"{self.remote.slug or self._service()} is not a component in {', '.join(apps)}", **d)
            tag = pins.tags.get(env)
            if not tag:
                return _link(name, "n/a", f"not deployed to {env}", **d)
            return self._pin_judge(env, tag)
        return _guard(name, d, run)


# ---------------- the document ----------------

def build(root: Path, spec: specmod.Spec) -> dict:
    c = Chain(root, spec)
    acs = spec.active_acs()
    tests = c.tests()
    verdicts = c.verdicts() if c.done and not c.product else {}
    criteria = []
    for ac in acs:
        verdict = verdicts.get(ac) or c.na("verdict", verdict=None) or _link("verdict", "n/a", "spec not yet done", verdict=None)
        pr = c.pr() if c.done and not c.product else c.na("pr", number=None, url=None, merge_commit=None, merged_at=None, others=[])
        rel = c.release() if c.done and not c.product else c.na("release", tag=None)
        links = [
            c.issue(),
            _link("spec", "ok", spec.status),
            _link("criterion", "ok", ac),
            tests.get(ac) or _link("tests", "unknown", "not resolved", files=[]),
            verdict, pr, rel,
            *[c.env(e) for e in model.ENVIRONMENTS],
        ]
        criteria.append({"id": ac, "complete": all(link["state"] in {"ok", "n/a"} for link in links), "links": links})
    count = {s: sum(1 for cr in criteria for link in cr["links"] if link["state"] == s) for s in ("missing", "stale", "unknown")}
    gaps = [{"criterion": cr["id"], "link": link["link"], "state": link["state"], "text": link["text"]}
            for cr in criteria for link in cr["links"] if link["state"] in {"missing", "stale"}]
    try:
        orphans = [{"file": o.file, "id": o.id, "kind": o.kind, "state": "stale", "text": f"names {o.kind} {o.id}"}
                   for o in specmod.orphan_tests(root, [spec], specmod.test_globs(c.own_shape))]
    except Exception as ex:  # noqa: BLE001
        orphans = [{"file": "", "id": "", "kind": "unknown", "state": "unknown", "text": f"{type(ex).__name__}: {ex}"}]
    unreached = list(c.remote.unreached)
    note = None
    if unreached:
        note = ("not reached: " + ", ".join(f"{u['what']} ({u['reason']})" for u in unreached)
                + "; the links that need them are unknown")
    verification = None
    if c.done:
        verification = specmod.verification_result(spec) or "none"
    return {
        "spec": spec.id, "status": spec.status, "verification": verification, "repo": c.remote.slug,
        "criteria": criteria,
        "summary": {"criteria": len(criteria), "complete": sum(1 for cr in criteria if cr["complete"]), **count},
        "gaps": gaps, "orphans": orphans, "unreached": unreached, "note": note,
    }


def render(doc: dict) -> str:
    head = f"chain: {doc['spec']} ({doc['status']}"
    head += f", verification: {doc['verification']})" if doc["verification"] else ")"
    lines = [head]
    for cr in doc["criteria"]:
        lines.append(cr["id"])
        lines += [f"  {link['link']:<12} {link['state']}: {link['text']}" for link in cr["links"]]
    s = doc["summary"]
    lines.append(f"summary: {s['complete']}/{s['criteria']} criteria have a complete chain "
                 f"({s['missing']} missing, {s['stale']} stale, {s['unknown']} unknown links)")
    if doc["gaps"]:
        lines.append("missing or stale:")
        lines += [f"  {g['criterion']} {g['link']}: {g['state']}: {g['text']}" for g in doc["gaps"]]
    else:
        lines.append("missing or stale: none")
    if doc["orphans"]:
        lines.append("orphan tests:")
        lines += [f"  {o['file']} {o['id']}: {o['state']}: {o['text']}" for o in doc["orphans"]]
    else:
        lines.append("orphan tests: none")
    if doc["note"]:
        lines.append(f"note: {doc['note']}")
    return "\n".join(lines)


def main_chain(root: Path, spec: specmod.Spec, *, as_json: bool = False) -> int:
    doc = build(Path(root), spec)
    print(json.dumps(doc, indent=2) if as_json else render(doc))
    return 0

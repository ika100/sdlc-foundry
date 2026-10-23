"""`spec`: feature specs in docs/specs/<NNN>-<slug>/ (ADR-026) — create, check, approve, trace, index, list, migrate.

A spec folder holds spec.md (what: stories, acceptance criteria AC-<NNN>.<n>, non-goals, open questions), optional
design.md (how, contract) and plan.md (tasks with `covers: [AC-…]`). The slash commands do the judgement; every
check and every state change of a spec goes through this module so it is deterministic and tested.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

import core
from core import PlatformError

SPECS_DIR = Path("docs") / "specs"
BACKLOG = Path("docs") / "backlog.md"
STATUSES = ["draft", "approved", "building", "done", "superseded"]
RANK = {s: i for i, s in enumerate(STATUSES[:4])}
# Allowed by `set-status`; draft -> approved only through `approve` (it checks the spec first).
TRANSITIONS = {"draft": {"superseded"}, "approved": {"building", "draft", "superseded"},
               "building": {"done", "draft", "superseded"}, "done": {"draft", "superseded"}, "superseded": set()}
PRIORITIES = {"P0", "P1", "P2"}
DEFAULT_TEST_GLOBS = ["tests/**/*"]
FRONT = re.compile(r"\A---\n(.*?)\n---\n?(.*)\Z", re.S)
SPEC_ID = re.compile(r"^(\d{3,})-[a-z0-9][a-z0-9-]*$")
AC_LINE = re.compile(r"^\s*[-*]\s+(~~)?\*\*(AC-(\d{3,})\.(\d+))\*\*")
SECTION = re.compile(r"^## +(.+?)\s*$", re.M)
START, END = "<!-- spec-index:start -->", "<!-- spec-index:end -->"


def _literal(dumper: yaml.Dumper, data: str):
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|" if "\n" in data else None)


class _Dumper(yaml.SafeDumper):
    pass


def _seq(dumper: yaml.Dumper, data: list):  # `covers: [AC-007.1]` stays on one line; lists of tasks stay block
    flat = all(not isinstance(x, (dict, list)) for x in data)
    return dumper.represent_sequence("tag:yaml.org,2002:seq", data, flow_style=flat)


_Dumper.add_representer(str, _literal)
_Dumper.add_representer(list, _seq)


QUOTE_HINT = "quote the value on that line, e.g. title: \"a: b\""
COLON_HINT = "values that contain ': ' must be quoted, e.g. title: \"a: b\""
FENCE_HINT = "front matter must be: a `---` line, `key: value` lines, a `---` line"


class BrokenSpec(PlatformError):
    """A spec.md or plan.md whose front matter cannot be read; names the file, the line and the fix."""

    def __init__(self, sdir: Path, rel: str, line: int, problem: str, hint: str):
        super().__init__(f"{rel}, line {line}: {problem}", hint=hint)
        self.dir, self.id, self.rel, self.line, self.problem = sdir, sdir.name, rel, line, problem

    def one_line(self) -> str:
        return f"{self.rel}, line {self.line}: {self.problem} (fix: {self.hint})"


def load(path: Path, root: Path | None = None) -> tuple[dict, str]:
    rel = str(path.relative_to(root)) if root else str(path)
    m = FRONT.match(path.read_text())
    if not m:
        raise BrokenSpec(path.parent, rel, 1, "missing front matter", FENCE_HINT)
    try:
        meta = yaml.safe_load(m.group(1))
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None) or getattr(e, "context_mark", None)
        line = mark.line + 2 if mark else 1
        problem = str(getattr(e, "problem", None) or "invalid YAML").strip()
        hint = COLON_HINT if problem == "mapping values are not allowed here" else QUOTE_HINT
        raise BrokenSpec(path.parent, rel, line, f"front matter is not valid YAML: {problem}", hint) from None
    if not isinstance(meta, dict):
        raise BrokenSpec(path.parent, rel, 1, "front matter is not a mapping of keys to values", FENCE_HINT)
    return meta, m.group(2)


def save(path: Path, meta: dict, body: str) -> None:
    front = yaml.dump(meta, Dumper=_Dumper, sort_keys=False, default_flow_style=False, width=120).rstrip("\n")
    path.write_text(f"---\n{front}\n---\n{body}")


def sections(body: str) -> dict[str, str]:
    """`## Heading` -> text up to the next `## ` heading (lower-cased headings). HTML comments are guidance, not content."""
    body = re.sub(r"<!--.*?-->", "", body, flags=re.S)
    marks = list(SECTION.finditer(body))
    return {m.group(1).strip().lower(): body[m.end():marks[i + 1].start() if i + 1 < len(marks) else len(body)]
            for i, m in enumerate(marks)}


@dataclass
class AC:
    id: str
    spec_no: str
    withdrawn: bool


@dataclass
class Spec:
    dir: Path
    meta: dict
    body: str
    plan: tuple[dict, str] | None = None
    errors: list[str] = field(default_factory=list)

    @property
    def id(self) -> str:
        return self.dir.name

    @property
    def number(self) -> str:
        return self.id.split("-", 1)[0]

    @property
    def status(self) -> str:
        return str(self.meta.get("status", ""))

    def acs(self) -> list[AC]:
        text = sections(self.body).get("acceptance criteria", "")
        return [AC(m.group(2), m.group(3), bool(m.group(1))) for m in map(AC_LINE.match, text.splitlines()) if m]

    def active_acs(self) -> list[str]:
        return [a.id for a in self.acs() if not a.withdrawn]

    def open_questions(self) -> list[str]:
        text = sections(self.body).get("open questions", "")
        items = [ln.strip()[2:].strip() for ln in text.splitlines() if re.match(r"^\s*[-*]\s+\S", ln)]
        return [i for i in items if not i.startswith("~~") and i.rstrip(".").lower() not in {"none", "n/a"}]

    def ac_hash(self) -> str:
        text = sections(self.body).get("acceptance criteria", "")
        return hashlib.sha256(" ".join(text.split()).encode()).hexdigest()[:12]


# ---------------- discovery ----------------

def specs_dir(root: Path) -> Path:
    return root / SPECS_DIR


def scan(root: Path) -> tuple[list[Spec], list[BrokenSpec]]:
    """Readable specs and the broken ones (never drops either)."""
    d = specs_dir(root)
    good: list[Spec] = []
    bad: list[BrokenSpec] = []
    for p in sorted(d.iterdir()) if d.is_dir() else []:
        if (p / "spec.md").is_file():
            try:
                good.append(read(p))
            except BrokenSpec as e:
                bad.append(e)
    return good, bad


def all_specs(root: Path) -> list[Spec]:
    return scan(root)[0]


def read(sdir: Path) -> Spec:
    root = sdir.parents[2]
    meta, body = load(sdir / "spec.md", root)
    plan = load(sdir / "plan.md", root) if (sdir / "plan.md").is_file() else None
    return Spec(sdir, meta, body, plan)


def find(root: Path, ref: str) -> Spec:
    """A spec by full id (`007-price-alerts`), number (`007`, `7`) or slug."""
    specs, bad = scan(root)
    num = ref.zfill(3) if ref.isdigit() else None
    hits = [s for s in [*specs, *bad] if s.id == ref or s.id.split("-", 1)[0] == num or s.id.split("-", 1)[-1] == ref]
    if len(hits) != 1:
        known = ", ".join(sorted(s.id for s in [*specs, *bad])) or "none"
        raise PlatformError(f"no single spec matches '{ref}' (specs: {known})", hint="run `cplat spec list`")
    if isinstance(hits[0], BrokenSpec):
        raise hits[0]
    return hits[0]


def next_number(root: Path) -> int:
    specs, bad = scan(root)
    nums = [int(s.id.split("-", 1)[0]) for s in [*specs, *bad]]
    backlog = root / BACKLOG
    if backlog.is_file():  # continue after legacy STORY-NNN ids so old references stay unique
        nums += [int(n) for n in re.findall(r"STORY-(\d+)", backlog.read_text())]
    return max(nums, default=0) + 1


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    if len(slug) > 40:  # cut at a word boundary
        slug = slug[:41].rsplit("-", 1)[0] if "-" in slug[:41] else slug[:40]
    return slug.rstrip("-") or "spec"


def repo_shape(root: Path) -> str | None:
    import shapecmd
    try:
        return shapecmd.route(root)["shape"]
    except PlatformError:
        return None  # shape-less repo (the platform itself): specs work, shape matching is skipped


def test_globs(shape: str | None) -> list[str]:
    entry = next((s for s in core.registry.load() if s["id"] == shape), None) if shape else None
    return (entry or {}).get("test_globs") or DEFAULT_TEST_GLOBS


# ---------------- check ----------------

def check(spec: Spec, *, require: str | None = None, shape: str | None = None) -> list[str]:
    errs: list[str] = []
    meta = spec.meta
    for k in ("spec_id", "title", "status", "priority"):
        if k not in meta:
            errs.append(f"spec.md: missing key '{k}'")
    if not SPEC_ID.match(spec.id):
        errs.append(f"folder '{spec.id}' must be <NNN>-<slug> (lowercase, hyphens)")
    if meta.get("spec_id") != spec.id:
        errs.append(f"spec.md: spec_id '{meta.get('spec_id')}' must equal the folder name '{spec.id}'")
    if spec.status not in STATUSES:
        errs.append(f"spec.md: status must be one of {STATUSES}")
    if meta.get("priority") not in PRIORITIES:
        errs.append(f"spec.md: priority must be one of {sorted(PRIORITIES)}")
    known = {s["id"] for s in core.registry.load()}
    if meta.get("shape") and meta["shape"] not in known:
        errs.append(f"spec.md: unknown shape '{meta['shape']}' (valid: {', '.join(sorted(known))})")
    if shape and meta.get("shape") and meta["shape"] != shape:
        errs.append(f"spec.md: shape '{meta['shape']}' but this repo is '{shape}'")
    acs = spec.acs()
    ids = [a.id for a in acs]
    for dup in sorted({i for i in ids if ids.count(i) > 1}):
        errs.append(f"duplicate acceptance criterion {dup}")
    for a in acs:
        if a.spec_no != spec.number:
            errs.append(f"{a.id} belongs to spec {a.spec_no}, not {spec.number} (ids are AC-{spec.number}.<n>)")
    rank = RANK.get(spec.status, -1)  # superseded has no rank: it never satisfies --require
    if require and rank < RANK[require]:
        errs.append(f"status is '{spec.status}', needs '{require}' or later"
                    + (f" — approve it with `/svc:spec approve {spec.number}`" if require == "approved" else ""))
    if spec.status == "superseded":
        return errs
    if rank >= RANK["approved"]:
        if not spec.active_acs():
            errs.append("an approved spec needs at least one acceptance criterion (AC-<NNN>.<n>)")
        if spec.open_questions():
            errs.append(f"{len(spec.open_questions())} open question(s) left; answer them before approving")
    if spec.plan:
        errs += [f"plan.md: {e}" for e in check_plan(spec, *spec.plan)]
    return errs


def check_plan(spec: Spec, meta: dict, _body: str) -> list[str]:
    errs: list[str] = []
    for k in ("spec_id", "spec_hash", "tasks"):
        if k not in meta:
            errs.append(f"missing key '{k}'")
    if errs:
        return errs
    if meta["spec_id"] != spec.id:
        errs.append(f"spec_id '{meta['spec_id']}' must be '{spec.id}'")
    if spec.meta.get("shape") and meta.get("shape") != spec.meta["shape"]:
        errs.append(f"shape '{meta.get('shape')}' must equal the spec's shape '{spec.meta['shape']}'")
    if meta["spec_hash"] != spec.ac_hash():
        errs.append("the acceptance criteria changed after this plan was written; re-plan with `/svc:plan "
                    f"{spec.number}` (or set spec_hash: {spec.ac_hash()} if the change does not affect the tasks)")
    tasks = meta["tasks"]
    if not isinstance(tasks, list) or not tasks:
        return errs + ["tasks must be a non-empty list"]
    tids = [t.get("id") for t in tasks]
    if len(tids) != len(set(tids)):
        errs.append("duplicate task ids")
    active, all_ids = set(spec.active_acs()), {a.id for a in spec.acs()}
    covered: set[str] = set()
    for t in tasks:
        tid = t.get("id", "<no id>")
        for k in ("id", "title", "files", "covers", "parallel_safe", "depends_on"):
            if k not in t:
                errs.append(f"task {tid}: missing '{k}'")
        for d in t.get("depends_on") or []:
            if d not in tids:
                errs.append(f"task {tid}: depends_on unknown task '{d}'")
        for c in t.get("covers") or []:
            if c not in all_ids:
                errs.append(f"task {tid}: covers unknown criterion '{c}'")
            elif c not in active:
                errs.append(f"task {tid}: covers withdrawn criterion '{c}'")
        covered |= set(t.get("covers") or [])
        if "done" in t and not isinstance(t["done"], bool):
            errs.append(f"task {tid}: done must be true/false")
        if "repo" in t:
            errs += _gitops_task_errors(spec, t)
    steps = meta.get("human_steps")
    if steps is not None and not (isinstance(steps, list) and all(isinstance(s, str) and s.strip() for s in steps)):
        errs.append("human_steps must be a list of non-empty strings")
    for a in sorted(active - covered):
        errs.append(f"{a} is not covered by any task")
    if errs:
        return errs
    try:
        levels = topo_levels(tasks)
    except PlatformError as e:
        return [str(e)]
    by_id = {t["id"]: t for t in tasks}
    for level in levels:
        par = [by_id[i] for i in level if by_id[i].get("parallel_safe")]
        for i, a in enumerate(par):
            for b in par[i + 1:]:
                both = sorted(set(a["files"]) & set(b["files"]))
                if both:
                    errs.append(f"tasks {a['id']} and {b['id']} are parallel_safe at the same level but share {', '.join(both)}")
    return errs


GITOPS_ORDERS = ("before-merge", "after-release")


def _gitops_task_errors(spec: Spec, t: dict) -> list[str]:
    """Spec 076: a task with `repo:` changes a linked gitops-app repo; ship opens and merges it around the deploy."""
    tid, errs = t.get("id", "<no id>"), []
    if t.get("order") not in GITOPS_ORDERS:
        errs.append(f"task {tid}: a gitops task needs order: {' | '.join(GITOPS_ORDERS)}")
    if not t.get("files"):
        errs.append(f"task {tid}: a gitops task needs the files it changes in {t['repo']}")
    apps = t.get("apps", [])
    if not (isinstance(apps, list) and all(isinstance(a, str) for a in apps)):
        errs.append(f"task {tid}: apps must be a list of Argo CD application names")
    link = spec.dir.parents[2] / ".platform-app.yml"
    linked = re.findall(r"^\s*-\s*([^\s#]+/[^\s#]+)", link.read_text(), re.M) if link.is_file() else []
    if t["repo"] not in linked:
        errs.append(f"task {tid}: repo {t['repo']} is not a gitops-app of this repo (.platform-app.yml lists: "
                    f"{', '.join(linked) or 'none'})")
    return errs


def topo_levels(tasks: list[dict]) -> list[list[str]]:
    deps = {t["id"]: set(t.get("depends_on") or []) for t in tasks}
    levels: list[list[str]] = []
    done: set[str] = set()
    while len(done) < len(deps):
        ready = sorted(i for i, d in deps.items() if i not in done and d <= done)
        if not ready:
            raise PlatformError("dependency cycle among tasks: " + ", ".join(sorted(set(deps) - done)))
        levels.append(ready)
        done |= set(ready)
    return levels


# ---------------- trace ----------------

def trace(root: Path, spec: Spec, globs: list[str]) -> dict[str, list[str]]:
    """AC id -> test files that mention it (by name or comment). `AC-007.1` never matches `AC-007.10`."""
    files = sorted({p for g in globs for p in root.glob(g) if p.is_file() and not _ignored(p.relative_to(root))})
    texts = {p: p.read_text(errors="ignore") for p in files}
    out: dict[str, list[str]] = {}
    for ac in spec.active_acs():
        pat = re.compile(re.escape(ac) + r"(?!\d)")
        out[ac] = [str(p.relative_to(root)) for p, t in texts.items() if pat.search(t)]
    return out


def _ignored(rel: Path) -> bool:
    return rel.suffix in {".pyc", ".pyo", ".class"} or any(
        part in {"node_modules", ".venv", ".devbox", ".git", "target", "dist", ".next", "__pycache__"} for part in rel.parts)


# ---------------- test-diff (spec 048) ----------------

AC_ANY = re.compile(r"AC-\d{3,}\.\d+(?!\d)")


def _py_shape(src: str) -> list[str]:
    """Top-level statements as AST dumps: formatting, comments and line numbers do not count; runs of top-level
    imports are sorted (formatters reorder them); string constants are compared with whitespace collapsed."""
    import ast

    class _Strings(ast.NodeTransformer):
        def visit_Constant(self, node):
            if isinstance(node.value, str):
                return ast.copy_location(ast.Constant(" ".join(node.value.split())), node)
            return node

    tree = _Strings().visit(ast.parse(src))
    out, run = [], []
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            run.append(ast.dump(node))
            continue
        out += sorted(run)
        run = []
        out.append(ast.dump(node))
    return out + sorted(run)


def formatting_only(old: str, new: str, name: str) -> tuple[bool, str]:
    """True when `new` differs from `old` only in formatting (spec 048); else False and the first difference."""
    if sorted(AC_ANY.findall(old)) != sorted(AC_ANY.findall(new)):
        return False, f"criterion ids changed: {sorted(set(AC_ANY.findall(old)) ^ set(AC_ANY.findall(new)))}"
    if name.endswith(".py"):
        try:
            a, b = _py_shape(old), _py_shape(new)
        except SyntaxError as e:
            return False, f"does not parse: {e.msg} (line {e.lineno})"
        if a == b:
            return True, ""
        i = next((i for i, (x, y) in enumerate(zip(a, b)) if x != y), min(len(a), len(b)))
        return False, f"top-level statement {i + 1} differs" + (" (statements added or removed)" if len(a) != len(b) else "")
    squash = lambda t: re.sub(r"\s+", "", t)  # noqa: E731
    if squash(old) == squash(new):
        return True, ""
    a, b = squash(old), squash(new)
    i = next((i for i, (x, y) in enumerate(zip(a, b)) if x != y), min(len(a), len(b)))
    return False, f"differs near …{b[max(0, i - 20):i + 20]}…"


def test_diff(root: Path, base: str, files: list[str]) -> dict[str, tuple[bool, str]]:
    """Each changed test file against `base`. Default: files under the shape's `test_globs` (never `docs/` or `*.md`, spec 063)
    that name a criterion of a `building` spec."""
    import subprocess
    if not files:
        changed = subprocess.run(["git", "-C", str(root), "diff", "--name-only", base], capture_output=True, text=True,
                                 check=True).stdout.split()
        ids = {a for s in all_specs(root) if s.status == "building" for a in (x.id for x in s.acs())}
        tests = {str(p.relative_to(root)) for g in test_globs(repo_shape(root)) for p in root.glob(g)}   # spec 063
        files = [f for f in changed if f in tests and (root / f).is_file() and not _ignored(Path(f))
                 and not f.startswith("docs/") and not f.endswith(".md")
                 and set(AC_ANY.findall((root / f).read_text(errors="ignore"))) & ids]
    out = {}
    for f in files:
        old = subprocess.run(["git", "-C", str(root), "show", f"{base}:{f}"], capture_output=True, text=True)
        new = (root / f).read_text() if (root / f).is_file() else ""
        out[f] = (False, "new or deleted file") if old.returncode != 0 or not new else formatting_only(old.stdout, new, f)
    return out


# ---------------- writing ----------------

def today() -> str:
    return dt.date.today().isoformat()


def add_changelog(body: str, line: str) -> str:
    entry = f"- {today()} {line}\n"
    m = re.search(r"^## +Changelog\s*$", body, re.M)
    if not m:
        return body.rstrip("\n") + f"\n\n## Changelog\n\n{entry}"
    nxt = SECTION.search(body, m.end())
    end = nxt.start() if nxt else len(body)
    head = body[:end].rstrip("\n")
    return f"{head}\n{entry}" + ("\n" + body[end:] if nxt else "")


def skeleton(number: str, title: str) -> str:
    return f"""
# {number} — {title}

## Problem

<!-- Who has the problem, what it costs them today, why now. -->

## Stories

<!-- As a <persona>, I want <goal>, so that <benefit>. -->

## Acceptance criteria

<!-- One line each, ids never reused or renumbered; withdraw with ~~**AC-{number}.n**~~ and a reason.
- **AC-{number}.1** Given <context>, when <action>, then <observable outcome>. -->

## Non-goals

## Open questions

<!-- One bullet per question the user must answer; approval is refused while any is open. Strike answered ones (~~…~~) and fold the answer into the criteria. -->

## Changelog

- {today()} created
"""


def new(root: Path, title: str, *, shape: str | None, priority: str, tracks: list[int], parent: str | None) -> Spec:
    number = f"{next_number(root):03d}"
    sdir = specs_dir(root) / f"{number}-{slugify(title)}"
    if sdir.exists():
        raise PlatformError(f"{sdir} already exists")
    sdir.mkdir(parents=True)
    meta = {"spec_id": sdir.name, "title": title, "status": "draft", "priority": priority}
    if shape:
        meta["shape"] = shape
    if tracks:
        meta["tracks"] = tracks
    if parent:
        meta["parent"] = parent
    save(sdir / "spec.md", meta, skeleton(number, title))
    spec = read(sdir)
    back = spec.meta.get("title")
    if not isinstance(back, str) or back != title:
        raise PlatformError(f"{sdir.name}: the title {title!r} did not read back as typed (got {back!r})",
                            hint="quote it differently or report this as a platform defect")
    return spec


def addon_env(app_root: Path, addon: str) -> list[str]:
    """Env variables an addon gives a service that uses it: render.py's ADDONS table (the contract, ADR-020)."""
    for render in (app_root / "scripts" / "render.py", core.PLATFORM_ROOT / "templates" / "gitops-app" / "scripts" / "render.py"):
        if render.is_file():
            block = render.read_text().split("ADDONS = {", 1)[-1]
            m = re.search(rf'^    "{re.escape(addon)}": \{{.*?"env": \{{([^}}]*)\}}', block, re.M | re.S)
            if m:
                return re.findall(r'"([A-Z0-9_]+)":', m.group(1))
    return []


def provided_by_product(app_root: Path, repos: list[dict], repo_id: str) -> list[str]:
    """Spec 052: what the plan's gitops entry wires for this repo (env, addons with their env, exposure)."""
    lines = []
    for entry in repos:
        if entry.get("shape") != "gitops-app":
            continue
        for op in entry.get("gitops") or []:
            if not isinstance(op, dict):
                continue
            if op.get("uses") and op.get("service") == repo_id:
                names = addon_env(app_root, op["uses"])
                lines.append(f"- addon `{op['uses']}`" + (f": env {', '.join(f'`{n}`' for n in names)}" if names else ""))
            elif isinstance(op.get("env"), dict) and op.get("service") == repo_id:
                lines += [f"- env `{k}={v}`" for k, v in op["env"].items()]
            elif op.get("expose") == repo_id:
                lines.append(f"- exposed through the Gateway at host `{op.get('host') or repo_id}`")
    return lines


def slice_from_plan(plan_path: Path, repo_id: str) -> dict:
    """This repo's part of a product plan (ADR-026): title, priority, parent and the Product context section.

    The plan lives in the gitops-app repo (docs/plan/<spec_id>.md); its spec next to it in docs/specs/<spec_id>/.
    Plans written before ADR-026 have no `spec:`; their `arguments` prompt is then the whole context.
    """
    if not plan_path.is_file():
        raise PlatformError(f"no such plan: {plan_path}", hint="pass the path to docs/plan/<id>.md in the gitops-app repo")
    meta, body = load(plan_path)
    repo = next((r for r in meta.get("repos") or [] if r.get("id") == repo_id), None)
    if repo is None:
        ids = ", ".join(str(r.get("id")) for r in meta.get("repos") or [])
        raise PlatformError(f"plan {plan_path.name} has no repo '{repo_id}' (repos: {ids})")
    app_root = plan_path.resolve().parents[2]
    parts = [f"Slice of the product plan `{meta.get('plan_id')}` in `{meta.get('gitops_app')}` for `{repo_id}` "
             f"({repo.get('shape')}). The product criteria and the contract below are binding: every criterion of this "
             "spec implements one of them and names it: `(product AC-<NNN>.<n>)`."]
    priority, problem = "P1", ""
    if meta.get("spec"):
        product = read(app_root / SPECS_DIR / str(meta["spec"]))
        priority = product.meta.get("priority", "P1")
        problem = sections(product.body).get("problem", "").strip()
        wanted = set(repo.get("acs") or [])
        lines = [ln for ln in sections(product.body).get("acceptance criteria", "").splitlines()
                 if (m := AC_LINE.match(ln)) and m.group(2) in wanted and not m.group(1)]
        parts.append("### Product criteria\n\n" + ("\n".join(lines) or "(none assigned)"))
        design = product.dir / "design.md"
        contract = sections(design.read_text()).get("contract", "").strip() if design.is_file() else ""
    else:
        contract = ""
    contract = contract or sections(body).get("contract", "").strip()
    if contract:
        parts.append("### Contract\n\n" + contract)
    provided = provided_by_product(app_root, meta.get("repos") or [], repo_id)
    if provided:
        parts.append("### Provided by the product\n\nThe gitops part of this plan wires these for this repo; rely on them, "
                     "do not ask for them again:\n\n" + "\n".join(provided))
    if repo.get("arguments"):
        parts.append("### Notes for this repo\n\n" + str(repo["arguments"]).strip())
    parent = f"{meta.get('gitops_app')}:{meta.get('spec') or meta.get('plan_id')}"
    return {"title": str(repo.get("summary") or repo_id), "priority": priority if priority in PRIORITIES else "P1",
            "parent": parent, "problem": problem, "context": "\n\n".join(parts)}


def new_from_plan(root: Path, plan_path: Path, repo_id: str, *, shape: str | None) -> Spec:
    sl = slice_from_plan(plan_path, repo_id)
    spec = new(root, sl["title"], shape=shape, priority=sl["priority"], tracks=[], parent=sl["parent"])
    body = spec.body.replace("## Stories", f"## Product context\n\n{sl['context']}\n\n## Stories", 1)
    if sl["problem"]:
        body = re.sub(r"(## Problem\n\n)<!--.*?-->", lambda m: m.group(1) + sl["problem"], body, count=1, flags=re.S)
    save(spec.dir / "spec.md", spec.meta, body)
    return read(spec.dir)


def approve(spec: Spec, shape: str | None) -> None:
    if spec.status != "draft":
        raise PlatformError(f"{spec.id} is '{spec.status}', only a draft can be approved")
    trial = Spec(spec.dir, {**spec.meta, "status": "approved"}, spec.body, spec.plan)
    errs = check(trial, shape=shape)
    if errs:
        raise PlatformError(f"{spec.id} cannot be approved: " + "; ".join(errs),
                            hint=f"fix the spec (`/svc:spec --amend {spec.number}`), then approve again")
    spec.meta["status"] = "approved"
    save(spec.dir / "spec.md", spec.meta, add_changelog(spec.body, "approved"))


VERDICT = re.compile(r"^\*\*Result:\*\*\s*(pass|fail)\b", re.M)


def verification_result(spec: Spec) -> str | None:
    """`pass` / `fail` from verification.md (written by the reviewer), None when there is none."""
    f = spec.dir / "verification.md"
    if not f.is_file():
        return None
    m = VERDICT.search(f.read_text())
    return m.group(1) if m else "fail"


def set_status(spec: Spec, status: str, reason: str | None, *, unverified: bool = False) -> None:
    if status not in TRANSITIONS.get(spec.status, set()):
        allowed = ", ".join(sorted(TRANSITIONS.get(spec.status, set()))) or "none"
        raise PlatformError(f"{spec.id}: '{spec.status}' -> '{status}' is not allowed (allowed: {allowed})",
                            hint="draft -> approved goes through `cplat spec approve`")
    if status == "done" and spec.meta.get("shape") != "gitops-app":   # spec 068: done means verified
        result = verification_result(spec)
        if result != "pass" and not unverified:
            why = "has no verification.md" if result is None else "verification.md does not say **Result:** pass"
            raise PlatformError(f"{spec.id} {why}; done means a reviewer checked every criterion",
                                hint=f"run `/svc:verify {spec.number}` (or `--unverified --reason <why>` to record an exception)")
        if result != "pass":
            if not reason:
                raise PlatformError("--unverified needs --reason: the exception is recorded in the spec's changelog")
            reason = f"unverified: {reason}"
    spec.meta["status"] = status
    save(spec.dir / "spec.md", spec.meta, add_changelog(spec.body, status + (f": {reason}" if reason else "")))


def task_done(spec: Spec, task_id: str) -> None:
    if not spec.plan:
        raise PlatformError(f"{spec.id} has no plan.md")
    meta, body = spec.plan
    task = next((t for t in meta.get("tasks") or [] if t.get("id") == task_id), None)
    if task is None:
        raise PlatformError(f"{spec.id}: unknown task '{task_id}'")
    task["done"] = True
    save(spec.dir / "plan.md", meta, body)


# ---------------- list / index ----------------

def next_step(spec: Spec) -> str:
    """The command that moves this spec on. Product specs (gitops-app) use /app:*, with the plan in docs/plan/<id>.md."""
    n = spec.number
    product = spec.meta.get("shape") == "gitops-app"
    prefix = "/app" if product else "/svc"
    planned = (spec.dir.parents[2] / "docs" / "plan" / f"{spec.id}.md").is_file() if product else bool(spec.plan)
    if spec.status == "draft":
        return f"{prefix}:spec --amend {n}" if spec.open_questions() or not spec.active_acs() else f"{prefix}:spec approve {n}"
    if spec.status == "approved" and not planned:
        return f"{prefix}:plan {n}"
    if spec.status in {"approved", "building"}:
        return f"{prefix}:build {n}"
    if spec.status == "done" and not product and verification_result(spec) != "pass":
        return f"/svc:verify {n}"   # spec 068: done without evidence
    return "—"


def summary(root: Path, spec: Spec) -> dict:
    tasks = (spec.plan[0].get("tasks") or []) if spec.plan else []
    return {"id": spec.id, "title": spec.meta.get("title", ""), "status": spec.status,
            "priority": spec.meta.get("priority", ""), "acs": len(spec.active_acs()),
            "open_questions": len(spec.open_questions()), "tasks": len(tasks),
            "tasks_done": sum(1 for t in tasks if t.get("done")), "tracks": spec.meta.get("tracks") or [],
            "next": next_step(spec), "path": str(spec.dir.relative_to(root))}


def index_table(root: Path) -> str:
    rows = sorted((summary(root, s) for s in all_specs(root)),
                  key=lambda r: (r["status"] in {"done", "superseded"}, r["priority"], r["id"]))
    lines = ["| Spec | Priority | Status | Criteria | Tracks |", "|---|---|---|---|---|"]
    for r in rows:
        tracks = ", ".join(f"#{t}" for t in r["tracks"]) or ""
        lines.append(f"| [{r['id']}]({Path('specs') / r['id'] / 'spec.md'}) — {r['title']} | {r['priority']} | "
                     f"{r['status']} | {r['acs']} | {tracks} |")
    if not rows:
        lines.append("| (no specs yet: `/svc:spec <description>`) | | | | |")
    return "\n".join(lines)


def write_index(root: Path) -> Path:
    """Regenerate the block between the spec-index markers in docs/backlog.md; the rest of the file is kept."""
    path = root / BACKLOG
    block = f"{START}\n<!-- generated by `cplat spec index`; edit docs/specs/<id>/spec.md, not this table -->\n{index_table(root)}\n{END}"
    text = path.read_text() if path.is_file() else "# Backlog\n\nOne line per feature spec; the specs live in `docs/specs/`.\n\n"
    if START in text and END in text:
        text = text[:text.index(START)] + block + text[text.index(END) + len(END):]
    elif re.search(r"^#{2,4} +STORY-\d+", text, re.M):
        raise PlatformError("docs/backlog.md still holds STORY-NNN stories", hint="convert them first: `cplat spec migrate --write`")
    else:
        text = text.rstrip("\n") + "\n\n" + block + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


# ---------------- migrate (legacy backlog.md stories -> spec folders) ----------------

STORY_HEAD = re.compile(r"^#### +STORY-(\d+)\s*(?:—|-|:)\s*(.+?)\s*$", re.M)
def legacy_status(text: str) -> str:
    """A legacy story's free-text status as a spec status: superseded, done, building (in progress, partial) or draft."""
    t = text.strip().lower()
    if "superseded" in t:
        return "superseded"
    if t.startswith("done"):
        return "done"
    if t.startswith(("in progress", "in_progress", "partial")):
        return "building"
    return "draft"  # open, planned, not built: needs review and approval


def parse_stories(text: str) -> list[dict]:
    heads = list(STORY_HEAD.finditer(text))
    out = []
    for i, m in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        nxt = re.compile(r"^#{1,4} ", re.M).search(text, m.end())
        end = min(end, nxt.start() if nxt else end)
        block = text[m.end():end]
        meta_line = next((ln for ln in block.strip().splitlines() if ln.startswith("**Status:**")), "")
        fields = dict(re.findall(r"\*\*([A-Za-z ]+):\*\*\s*([^·]+?)\s*(?=·|$)", meta_line))
        crit_raw = block.split("**Acceptance criteria:**", 1)[1] if "**Acceptance criteria:**" in block else ""
        crits = [re.sub(r"^\s*[-*]\s+(\[[ xX]\]\s+)?", "", ln).strip() for ln in crit_raw.splitlines() if re.match(r"^\s*[-*]\s+", ln)]
        story = block.split("**Acceptance criteria:**", 1)[0].replace(meta_line, "").strip()
        out.append({"number": f"{int(m.group(1)):03d}", "title": m.group(2), "start": m.start(), "end": end,
                    "status": fields.get("Status", "open").strip().lower(), "priority": fields.get("Priority", "P1").strip(),
                    "tracks": [int(t) for t in re.findall(r"#(\d+)", fields.get("Tracks", ""))],
                    "meta_line": meta_line.strip(), "story": story, "criteria": crits})
    return out


def relink(text: str) -> str:
    """Relative Markdown links written in docs/backlog.md, rewritten for docs/specs/<id>/spec.md (two levels deeper)."""
    return re.sub(r"\]\((?![a-z][a-z0-9+.-]*:|#|/)([^)\s]+)\)", r"](../../\1)", text)


def migrate_plan(root: Path, shape: str | None) -> tuple[list[tuple[Path, dict, str]], str]:
    """(spec files to write, new backlog.md text). Pure: writes nothing."""
    path = root / BACKLOG
    text = path.read_text() if path.is_file() else ""
    stories = parse_stories(text)
    legacy_plans: dict[str, str] = {}
    plan_dir = root / "docs" / "plan"
    for p in sorted(plan_dir.glob("*.md")) if plan_dir.is_dir() else []:
        try:
            meta, _ = load(p)
        except PlatformError:
            continue
        for sid in meta.get("stories") or []:
            legacy_plans.setdefault(str(sid).replace("STORY-", "").zfill(3), str(p.relative_to(root)))
    files = []
    for s in stories:
        sid = f"{s['number']}-{slugify(s['title'])}"
        meta = {"spec_id": sid, "title": s["title"], "status": legacy_status(s["status"]),
                "priority": s["priority"] if s["priority"] in PRIORITIES else "P1"}
        if shape:
            meta["shape"] = shape
        if s["tracks"]:
            meta["tracks"] = s["tracks"]
        acs = "\n".join(f"- **AC-{s['number']}.{i}** {c}" for i, c in enumerate(s["criteria"], 1)) or \
            f"<!-- none in the legacy story; add AC-{s['number']}.1 … before approving -->"
        refs = [f"- Legacy metadata: {s['meta_line']}"] if s["meta_line"] else []
        if s["number"] in legacy_plans:
            refs.append(f"- Legacy plan: `{legacy_plans[s['number']]}`")
        body = (f"\n# {s['number']} — {s['title']}\n\n## Stories\n\n{s['story'] or '<!-- none -->'}\n\n"
                f"## Acceptance criteria\n\n{acs}\n\n## Non-goals\n\n## Open questions\n\n"
                + ("## References\n\n" + "\n".join(refs) + "\n\n" if refs else "")
                + f"## Changelog\n\n- {today()} migrated from STORY-{s['number']} in docs/backlog.md\n")
        files.append((specs_dir(root) / sid / "spec.md", meta, relink(body)))
    rest = text
    for i, s in reversed(list(enumerate(stories))):  # the index takes the place of the first story
        rest = rest[:s["start"]] + (f"{START}\n{END}\n\n" if i == 0 else "") + rest[s["end"]:]
    return files, _drop_empty_headings(rest)


def _drop_empty_headings(text: str) -> str:
    """Remove `##`/`###` headings whose section is left empty after the stories moved out.

    Empty means: only blank lines or `---` rules before the next heading of the same or a higher level, the index
    marker, or the end of the file. A heading whose content is a sub-heading is kept.
    """
    lines = text.split("\n")
    changed = True
    while changed:
        changed = False
        for i, ln in enumerate(lines):
            m = re.match(r"^(#{2,3}) ", ln)
            if not m:
                continue
            j = i + 1
            while j < len(lines) and lines[j].strip() in {"", "---"}:
                j += 1
            nxt = re.match(r"^(#{1,6}) ", lines[j]) if j < len(lines) else None
            if j == len(lines) or lines[j] == START or (nxt and len(nxt.group(1)) <= len(m.group(1))):
                del lines[i:j]
                changed = True
                break
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines))


def migrate(root: Path, shape: str | None, write: bool) -> list[str]:
    files, rest = migrate_plan(root, shape)
    if not files:
        raise PlatformError("docs/backlog.md has no STORY-NNN stories to migrate")
    clash = [str(p.parent.relative_to(root)) for p, _, _ in files if p.exists()]
    if clash:
        raise PlatformError("spec folders already exist: " + ", ".join(clash))
    lines = [f"{'create' if write else 'would create'} {p.relative_to(root)}  [{m['status']}, {body.count('**AC-')} criteria]"
             for p, m, body in files]
    if write:
        for p, meta, body in files:
            p.parent.mkdir(parents=True, exist_ok=True)
            save(p, meta, body)
        (root / BACKLOG).write_text(rest)
        write_index(root)
        lines.append(f"rewrote {BACKLOG} as the spec index (non-story sections kept)")
    else:
        lines.append(f"would rewrite {BACKLOG} as the spec index; run again with --write")
    return lines


# ---------------- CI ----------------

def ci_problems(root: Path) -> list[tuple[Spec, str]]:
    """Everything `check` reports, plus untraced criteria of specs that are being built or done.

    Product specs (gitops-app) are not traced here: their criteria are implemented and tested in the component repos.
    """
    shape = repo_shape(root)
    out: list[tuple[Spec, str]] = []
    for s in all_specs(root):
        out += [(s, e) for e in check(s, shape=shape)]
        own_shape = s.meta.get("shape") or shape
        if s.status in {"building", "done"} and own_shape != "gitops-app":
            out += [(s, f"{ac} is not named by any test") for ac, files in trace(root, s, test_globs(own_shape)).items() if not files]
    return out


def ci(root: Path, strict: bool) -> int:
    """GitHub annotations for the spec-check job: warnings by default, errors (and exit 1) with --strict."""
    if not specs_dir(root).is_dir():
        print("spec-check: no docs/specs/ yet, nothing to check")
        return 0
    problems = ci_problems(root)
    level = "error" if strict else "warning"
    for s, msg in problems:
        print(f"::{level} file={(s.dir / 'spec.md').relative_to(root)},title=spec {s.id}::{msg}")
    n = len(all_specs(root))
    print(f"spec-check: {n} spec(s), {len(problems)} problem(s)" + ("" if strict or not problems else " (warnings only; fix them before this check becomes required)"))
    return 1 if strict and problems else 0


# ---------------- CLI ----------------

def _print_errors(results: dict[str, list[str]]) -> int:
    bad = 0
    for sid, errs in results.items():
        for e in errs:
            print(f"ERROR: {sid}: {e}")
            bad += 1
    print(f"OK: {len(results)} spec(s) valid" if not bad else f"{bad} error(s)")
    return 1 if bad else 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="cplat spec", description=__doc__)
    ap.add_argument("--repo", default=".")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("new", help="create docs/specs/<NNN>-<slug>/spec.md (draft)")
    p.add_argument("title", nargs="*")
    p.add_argument("--from-plan", nargs=2, metavar=("PLAN", "REPO_ID"),
                   help="this repo's slice of a product plan (docs/plan/<id>.md in the gitops-app repo)")
    p.add_argument("--priority", default="P1", choices=sorted(PRIORITIES))
    p.add_argument("--tracks", type=int, nargs="*", default=[])
    p.add_argument("--take-over", action="store_true", help="move a claim on a tracked issue to this spec (spec 082)")
    p.add_argument("--parent")
    p.add_argument("--no-shape", action="store_true", help="do not record the repo's shape")
    p = sub.add_parser("check", help="validate specs and plans (all if none given)")
    p.add_argument("ids", nargs="*")
    p.add_argument("--require", choices=list(RANK))
    p = sub.add_parser("approve", help="check a draft and set it approved")
    p.add_argument("id")
    p = sub.add_parser("set-status")
    p.add_argument("id")
    p.add_argument("status", choices=STATUSES)
    p.add_argument("--reason")
    p.add_argument("--unverified", action="store_true", help="done without a passing verification.md (needs --reason)")
    p = sub.add_parser("task-done")
    p.add_argument("id")
    p.add_argument("task")
    p = sub.add_parser("hash", help="print the acceptance-criteria hash a plan records as spec_hash")
    p.add_argument("id")
    p = sub.add_parser("trace", help="every active criterion must be named by at least one test")
    p.add_argument("id")
    p.add_argument("--json", action="store_true")
    sub.add_parser("index", help="regenerate the spec table in docs/backlog.md")
    p = sub.add_parser("list")
    p.add_argument("--all", action="store_true", help="include done and superseded")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("test-diff", help="acceptance tests changed only in formatting since BASE? (exit 1 otherwise)")
    p.add_argument("base", help="the commit with the red acceptance tests (Phase 1)")
    p.add_argument("files", nargs="*")
    p = sub.add_parser("ci", help="check every spec and trace built ones; GitHub annotations (warnings unless --strict)")
    p.add_argument("--strict", action="store_true")
    p = sub.add_parser("migrate", help="convert STORY-NNN stories in docs/backlog.md into spec folders")
    p.add_argument("--write", action="store_true", help="without it, only show what would happen")
    ns = ap.parse_args(argv)
    root = Path(ns.repo).resolve()

    if ns.cmd == "new":
        shape = None if ns.no_shape else repo_shape(root)
        if ns.from_plan:
            spec = new_from_plan(root, Path(ns.from_plan[0]).expanduser(), ns.from_plan[1], shape=shape)
        elif not ns.title:
            raise PlatformError("a title or --from-plan PLAN REPO_ID is required")
        else:
            spec = new(root, " ".join(ns.title), shape=shape, priority=ns.priority, tracks=ns.tracks, parent=ns.parent)
        print(spec.dir.relative_to(root) / "spec.md")
        if spec.meta.get("tracks"):
            import claim
            for note in claim.claim(root, spec.meta["tracks"], f"feature/{spec.id}", take_over=ns.take_over, what=spec.id):
                print(note)
        return 0
    if ns.cmd == "check":
        specs = [find(root, i) for i in ns.ids] if ns.ids else all_specs(root)
        shape = repo_shape(root)
        return _print_errors({s.id: check(s, require=ns.require, shape=shape) for s in specs})
    if ns.cmd == "approve":
        spec = find(root, ns.id)
        approve(spec, repo_shape(root))
        print(f"{spec.id}: approved")
        return 0
    if ns.cmd == "set-status":
        spec = find(root, ns.id)
        set_status(spec, ns.status, ns.reason, unverified=ns.unverified)
        print(f"{spec.id}: {ns.status}")
        return 0
    if ns.cmd == "task-done":
        spec = find(root, ns.id)
        task_done(spec, ns.task)
        print(f"{spec.id}: {ns.task} done")
        return 0
    if ns.cmd == "hash":
        print(find(root, ns.id).ac_hash())
        return 0
    if ns.cmd == "trace":
        spec = find(root, ns.id)
        result = trace(root, spec, test_globs(spec.meta.get("shape") or repo_shape(root)))
        missing = [a for a, f in result.items() if not f]
        if ns.json:
            print(json.dumps({"spec": spec.id, "criteria": result, "missing": missing}, indent=2))
        else:
            for ac, found in result.items():
                print(f"{'ok  ' if found else 'MISS'} {ac}  {', '.join(found) or '(no test names it)'}")
            print(f"{len(result) - len(missing)}/{len(result)} criteria traced to tests")
        return 1 if missing else 0
    if ns.cmd == "index":
        print(write_index(root).relative_to(root))
        return 0
    if ns.cmd == "list":
        rows = [summary(root, s) for s in all_specs(root) if ns.all or s.status not in {"done", "superseded"}]
        if ns.json:
            print(json.dumps(rows, indent=2))
        elif not rows:
            print("(no open specs — start one with `/svc:spec <description>`)")
        else:
            for r in rows:
                tasks = f"{r['tasks_done']}/{r['tasks']} tasks" if r["tasks"] else "no plan"
                oq = f", {r['open_questions']} open q" if r["open_questions"] else ""
                print(f"{r['id']:40} {r['priority']:3} {r['status']:10} {r['acs']:>2} AC{oq:12} {tasks:12} next: {r['next']}")
        return 0
    if ns.cmd == "test-diff":
        result = test_diff(root, ns.base, ns.files)
        for f, (ok, why) in result.items():
            print(f"{f}: formatting only" if ok else f"{f}: changed — {why}")
        if not result:
            print("no acceptance test changed")
        return 0 if all(ok for ok, _ in result.values()) else 1
    if ns.cmd == "ci":
        return ci(root, ns.strict)
    if ns.cmd == "migrate":
        for line in migrate(root, repo_shape(root), ns.write):
            print(line)
        return 0
    return 2

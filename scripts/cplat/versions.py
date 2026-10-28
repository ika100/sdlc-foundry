"""cplat platform versions [--json] [--diff <git ref>] [--changelog]: the platform's versions table (spec 121, AC-121.1, AC-121.23).

The rows come from `versions_table()` of the platform's templates/gitops-app/scripts/render.py. `--diff REF` compares them with the rows
of that file at a git ref (a release without `versions_table()` is read from its constants; absent rows count as added).
"""
import argparse
import importlib.util
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import core

RENDER = "templates/gitops-app/scripts/render.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _row(name, kind, version, ref, digest=None, app_version=None, crds=None, engine=None, major=None, status=None) -> dict:
    return {"name": name, "kind": kind, "engine": engine, "major": major, "status": status, "version": version, "ref": ref,
            "digest": digest, "app_version": app_version, "crds": crds}


def _split(ref: str) -> tuple[str, str | None]:
    base, _, digest = ref.partition("@")
    return base, digest or None


def _legacy_rows(mod) -> list[dict]:
    """The rows of a render.py without `versions_table()`, from the constants it has."""
    rows = []
    for major, ref in (getattr(mod, "POSTGRES_IMAGES", None) or {}).items():
        base, digest = _split(ref)
        rows.append(_row(f"postgres {major}", "image", base.rsplit(":", 1)[-1].split("-")[0], base, digest, engine="database", major=major))
    for attr, name in (("SEAWEEDFS_IMAGE", "seaweedfs"), ("VELERO_AWS_PLUGIN_IMAGE", "velero-plugin-for-aws")):
        if getattr(mod, attr, None):
            base, digest = _split(getattr(mod, attr))
            rows.append(_row(name, "image", base.rsplit(":", 1)[-1], base, digest))
    collector = ((getattr(mod, "ADDONS", None) or {}).get("observability") or {}).get("image")
    if collector:
        base, digest = _split(collector)
        rows.append(_row("opentelemetry-collector", "image", base.rsplit(":", 1)[-1], base, digest))
    for n, op in (getattr(mod, "OPERATORS", None) or {}).items():
        rows.append(_row(f"operator {n}", "chart", op["chart_version"], f"{op['repo_url']} {op['chart']}",
                         app_version=op.get("operator_version")))
    return rows


def rows_of(mod) -> list[dict]:
    fn = getattr(mod, "versions_table", None)
    return fn() if callable(fn) else _legacy_rows(mod)


def current() -> tuple[list[dict], dict]:
    mod = _load(core.PLATFORM_ROOT / RENDER, "cplat_versions_render")
    return rows_of(mod), (getattr(mod, "OPERATORS", None) or {})


def at_ref(ref: str) -> list[dict]:
    def fail(reason: str):
        return core.PlatformError(f"cannot read the versions table at {ref}: {reason}")
    p = subprocess.run(["git", "-C", str(core.PLATFORM_ROOT), "show", f"{ref}:{RENDER}"], capture_output=True, text=True)
    if p.returncode != 0:
        lines = (p.stderr or "").strip().splitlines()
        raise fail(lines[-1] if lines else "git show failed")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "render_at_ref.py"
        path.write_text(p.stdout)
        try:
            return rows_of(_load(path, "cplat_versions_render_old"))
        except Exception as e:  # noqa: BLE001  (an old file that does not load is "cannot read")
            raise fail(f"{type(e).__name__}: {e}") from e


# ---------------- text ----------------

def _display_name(r: dict) -> str:
    return f"{r['name']} (deprecated)" if r.get("status") == "deprecated" else r["name"]


def _crds_cell(r: dict, operators: dict) -> str:
    crds = r["crds"]
    first = (operators.get(r["name"].removeprefix("operator ")) or {}).get("crd")
    names = sorted(crds, key=lambda c: c != first)       # the operator's own CRD first (sorted() is stable)
    return "crds " + ", ".join(f"{c} {','.join(crds[c])}" for c in names)


def text_lines(release: str, rows: list[dict], operators: dict) -> list[str]:
    table = []
    for r in rows:
        cells = [r["kind"], _display_name(r), r["version"], r["ref"]]
        if r["kind"] == "image" and r["digest"]:
            cells.append(f"sha256:{_short(r['digest'])}…")
        if r.get("app_version"):
            cells.append(f"operator {r['app_version']}")
        if r.get("crds"):
            cells.append(_crds_cell(r, operators))
        table.append(cells)
    widths = [max((len(c[i]) for c in table if len(c) > i + 1), default=0) for i in range(6)]
    out = [f"versions table of platform {release}"]
    for cells in table:
        padded = [c.ljust(widths[i]) if i < len(cells) - 1 else c for i, c in enumerate(cells)]
        out.append("  " + "  ".join(padded))
    return out


# ---------------- diff ----------------

def _nums(v: str) -> list[int]:
    return [int(x) for x in re.findall(r"\d+", v.split("-")[0])]


def is_major(old: str, new: str) -> bool:
    a, b = _nums(old), _nums(new)
    if not a or not b:
        return False
    return (a[0] != b[0]) if a[0] != 0 or b[0] != 0 else (a[1:2] != b[1:2])


def _short(digest: str | None) -> str:
    return digest.split(":", 1)[-1][:8] if digest else "none"


def diff(old_rows: list[dict], new_rows: list[dict]) -> list[dict]:
    """Changes as dicts: kind (changed|added|removed|crds), name, old, new, major, text pieces."""
    old = {r["name"]: r for r in old_rows}
    new = {r["name"]: r for r in new_rows}
    out = []
    for name, n in new.items():
        o = old.get(name)
        if o is None:
            out.append({"kind": "added", "name": name, "new": n["version"]})
            continue
        digest_only = o["version"] == n["version"] and n["kind"] == "image" and o["digest"] != n["digest"]
        if o["version"] != n["version"] or digest_only:
            if n["kind"] == "image" and digest_only:
                ov, nv = f"{o['version']} (digest {_short(o['digest'])})", f"{n['version']} (digest {_short(n['digest'])})"
            else:
                ov, nv = o["version"], n["version"]
            out.append({"kind": "changed", "name": name, "old": ov, "new": nv, "major": is_major(o["version"], n["version"])})
        for crd, versions in (o.get("crds") or {}).items():
            if n.get("crds") is None:
                continue
            for v in versions:
                if v not in (n["crds"].get(crd) or []):
                    out.append({"kind": "crds", "name": name, "crd": crd, "version": v})
    for name, o in old.items():
        if name not in new:
            out.append({"kind": "removed", "name": name, "old": o["version"]})
    return out


def diff_lines(changes: list[dict], changelog: bool) -> list[str]:
    lines = []
    for c in changes:
        k = c["kind"]
        if changelog:
            if k == "changed":
                lines.append(f"- `{c['name']}` {c['old']} → {c['new']}" + (" **(major)**" if c["major"] else ""))
            elif k == "added":
                lines.append(f"- `{c['name']}` {c['new']} (new)")
            elif k == "removed":
                lines.append(f"- `{c['name']}` {c['old']} (removed)")
            else:
                lines.append(f"- `{c['name']}` CRD version removed: {c['crd']} {c['version']}")
        elif k == "changed":
            lines.append(f"changed {c['name']}: {c['old']} → {c['new']}" + (" (major)" if c["major"] else ""))
        elif k == "added":
            lines.append(f"added {c['name']}: {c['new']}")
        elif k == "removed":
            lines.append(f"removed {c['name']}: {c['old']}")
        else:
            lines.append(f"crds {c['name']}: removed {c['crd']} {c['version']}")
    return lines


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="cplat platform versions", description=__doc__)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--diff", metavar="REF")
    ap.add_argument("--changelog", action="store_true")
    ns = ap.parse_args(argv)
    rows, operators = current()
    if ns.diff:
        for line in diff_lines(diff(at_ref(ns.diff), rows), ns.changelog):
            print(line)
        return 0
    if ns.changelog:
        print("ERROR: --changelog needs --diff <git ref>", file=sys.stderr)
        return 2
    release = core.platform_version()
    if ns.json:
        print(json.dumps({"release": release, "rows": rows}, indent=2))
    else:
        print("\n".join(text_lines(release, rows, operators)))
    return 0

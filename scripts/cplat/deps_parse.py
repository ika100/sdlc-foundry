"""Pure part of `cplat deps` (spec 095, ADR-033): version order, per-tool report parsers at the gate's threshold, grouping.

No subprocess calls. The only file reads are the manifests in `declared`.
"""
from __future__ import annotations

import json
import re
import tomllib
import xml.etree.ElementTree as ET
from dataclasses import dataclass, replace
from pathlib import Path

from core import PlatformError


@dataclass
class Finding:
    package: str            # PyPI/npm name, Go module path, Maven "<groupId>:<artifactId>"
    installed: str          # resolved version, e.g. "1.26.5", "v0.17.0"
    fixed: str | None       # lowest fixed version above `installed`; None = no fix released
    advisories: list[str]   # advisory ids, sorted
    severity: str           # CRITICAL | HIGH | MODERATE | LOW | UNRATED
    transitive: bool        # not declared in the manifest
    major: bool             # fixed's major > installed's major
    kind: str = "dependency"   # "toolchain": Go `stdlib` / `toolchain` module, never bumped


TOOLS = {"service-python": "pip-audit", "library-python": "pip-audit", "web-nextjs": "pnpm-audit",
         "service-go": "govulncheck", "service-java": "trivy"}
DEP_FILES = {"service-python": ("pyproject.toml", "uv.lock"), "library-python": ("pyproject.toml", "uv.lock"),
             "web-nextjs": ("package.json", "pnpm-lock.yaml", "pnpm-workspace.yaml"),
             "service-go": ("go.mod", "go.sum"), "service-java": ("pom.xml",)}

SEVERITY_ORDER = ["UNRATED", "LOW", "MODERATE", "HIGH", "CRITICAL"]
_PRE = {"post", "p", "rev", "r"}   # alphabetic parts that sort after the release; every other one sorts before it


# ---------------- versions ----------------

def _strip(v: str) -> str:
    return re.sub(r"^(?:v|go)(?=\d)", "", v.strip(), flags=re.I)


def version_key(v: str) -> tuple:
    """Sort key: numeric parts as ints, pre-releases before their release. Never raises."""
    toks = re.findall(r"\d+|[A-Za-z]+", _strip(str(v)))
    parts = [(1, int(t), "") if t.isdigit() else ((2 if t.lower() in _PRE else -1), 0, t.lower()) for t in toks]
    return (*parts, (0, 0, ""))


def lowest_fixed(installed: str, candidates: list[str]) -> str | None:
    above = [c for c in candidates if c and version_key(c) > version_key(installed)]
    return min(above, key=version_key) if above else None


def _major(v: str) -> int | None:
    m = re.match(r"\d+", _strip(v))
    return int(m.group()) if m else None


def _is_major(installed: str, fixed: str | None) -> bool:
    if not fixed:
        return False
    a, b = _major(installed), _major(fixed)
    return a is not None and b is not None and b > a


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


# ---------------- declared dependencies ----------------

def _py_name(req: str) -> str | None:
    m = re.match(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)", req)
    return _norm(m.group(1)) if m else None


def declared(shape: str, repo: Path) -> set[str]:
    """Names declared in the manifest (normalized for PyPI). A missing or unreadable manifest declares nothing."""
    repo = Path(repo)
    out: set[str] = set()
    try:
        if shape in ("service-python", "library-python"):
            data = tomllib.loads((repo / "pyproject.toml").read_text())
            reqs = list(data.get("project", {}).get("dependencies", []))
            for lst in data.get("project", {}).get("optional-dependencies", {}).values():
                reqs += lst
            for lst in data.get("dependency-groups", {}).values():
                reqs += [r for r in lst if isinstance(r, str)]
            out = {n for n in (_py_name(r) for r in reqs if isinstance(r, str)) if n}
        elif shape == "web-nextjs":
            data = json.loads((repo / "package.json").read_text())
            out = set(data.get("dependencies", {})) | set(data.get("devDependencies", {}))
        elif shape == "service-go":
            out = _go_requires((repo / "go.mod").read_text())
        elif shape == "service-java":
            out = _maven_dependencies((repo / "pom.xml").read_text())
    except (OSError, ValueError):
        return set()
    return out


def _go_requires(text: str) -> set[str]:
    out: set[str] = set()
    in_block = False
    for raw in text.splitlines():
        line = raw.strip()
        if in_block:
            if line.startswith(")"):
                in_block = False
                continue
            spec = line
        elif re.match(r"require\s*\(", line):
            in_block = True
            continue
        elif line.startswith("require "):
            spec = line[len("require "):].strip()
        else:
            continue
        if "// indirect" in spec:
            continue
        parts = spec.split()
        if len(parts) >= 2:
            out.add(parts[0])
    return out


def _maven_dependencies(text: str) -> set[str]:
    root = ET.fromstring(text)
    ns = root.tag[:root.tag.index("}") + 1] if root.tag.startswith("{") else ""
    out: set[str] = set()
    for dep in root.findall(f"{ns}dependencies/{ns}dependency"):
        g, a = dep.findtext(f"{ns}groupId"), dep.findtext(f"{ns}artifactId")
        if g and a:
            out.add(f"{g.strip()}:{a.strip()}")
    return out


# ---------------- parsers ----------------

def _unrecognised(label: str) -> PlatformError:
    return PlatformError(f"deps-findings: unrecognised {label} report")


def _load(text: str, label: str):
    try:
        return json.loads(text)
    except ValueError:
        raise _unrecognised(label) from None


def _make(package: str, installed: str, fixed: str | None, advisory: str, severity: str, trans: bool, kind: str = "dependency") -> Finding:
    return Finding(package, installed, fixed, [advisory], severity, trans, _is_major(installed, fixed), kind)


def _parse_pip_audit(text: str, decl: set[str]) -> list[Finding]:
    data = _load(text, "pip-audit")
    if not isinstance(data, dict) or not isinstance(data.get("dependencies"), list):
        raise _unrecognised("pip-audit")
    out = []
    for dep in data["dependencies"]:
        if not isinstance(dep, dict) or not dep.get("version"):
            continue
        name, ver = dep.get("name", ""), dep["version"]
        for v in dep.get("vulns") or []:
            out.append(_make(name, ver, lowest_fixed(ver, list(v.get("fix_versions") or [])), v["id"], "UNRATED",
                             _norm(name) not in decl))
    return out


def _parse_pnpm(text: str, decl: set[str]) -> list[Finding]:
    data = _load(text, "pnpm audit")
    if not isinstance(data, dict) or not isinstance(data.get("advisories"), dict):
        raise _unrecognised("pnpm audit")
    out = []
    for key, adv in data["advisories"].items():
        sev = str(adv.get("severity", "")).upper()
        if sev not in ("HIGH", "CRITICAL"):
            continue
        bounds = re.findall(r">=\s*([^\s|<>=,]+)", str(adv.get("patched_versions") or ""))
        name = adv.get("module_name", "")
        for f in adv.get("findings") or []:
            ver = f.get("version", "")
            out.append(_make(name, ver, lowest_fixed(ver, bounds), adv.get("github_advisory_id") or f"npm-{key}", sev, name not in decl))
    return out


def _parse_govulncheck(text: str, decl: set[str]) -> list[Finding]:
    dec, pos, objs = json.JSONDecoder(), 0, []
    while True:
        while pos < len(text) and text[pos].isspace():
            pos += 1
        if pos >= len(text):
            break
        try:
            obj, pos = dec.raw_decode(text, pos)
        except ValueError:
            raise _unrecognised("govulncheck") from None
        if not isinstance(obj, dict):
            raise _unrecognised("govulncheck")
        objs.append(obj)
    out, seen = [], set()
    for obj in objs:
        f = obj.get("finding")
        if not isinstance(f, dict):
            continue
        trace = f.get("trace")
        if not trace or not trace[0].get("function"):
            continue   # the vulnerable symbol is not called: the gate does not fail on it
        mod, ver, osv = trace[0].get("module", ""), trace[0].get("version", ""), f.get("osv", "")
        if (mod, osv) in seen:
            continue
        seen.add((mod, osv))
        kind = "toolchain" if mod in ("stdlib", "toolchain") else "dependency"
        out.append(_make(mod, ver, f.get("fixed_version") or None, osv, "UNRATED", mod not in decl, kind))
    return out


def _parse_trivy(text: str, decl: set[str]) -> list[Finding]:
    data = _load(text, "trivy")
    if not isinstance(data, dict) or not ({"Results", "SchemaVersion", "ArtifactName"} & set(data)):
        raise _unrecognised("trivy")
    out, seen = [], set()
    for res in data.get("Results") or []:
        for v in res.get("Vulnerabilities") or []:
            sev = str(v.get("Severity", "")).upper()
            if sev not in ("HIGH", "CRITICAL"):
                continue
            pkg, ver, vid = v.get("PkgName", ""), v.get("InstalledVersion", ""), v.get("VulnerabilityID", "")
            if (pkg, ver, vid) in seen:
                continue
            seen.add((pkg, ver, vid))
            fixed = lowest_fixed(ver, [c.strip() for c in str(v.get("FixedVersion") or "").split(",")])
            out.append(_make(pkg, ver, fixed, vid, sev, pkg not in decl))
    return out


_PARSERS = {"pip-audit": _parse_pip_audit, "pnpm-audit": _parse_pnpm, "govulncheck": _parse_govulncheck, "trivy": _parse_trivy}


def parse(tool: str, text: str, declared: set[str]) -> list[Finding]:
    """One Finding per (package, advisory), at the gate's threshold. An empty report is []."""
    if tool not in _PARSERS:
        raise PlatformError(f"deps-findings: unknown scanner {tool}")
    if not text.strip():
        return []
    return _PARSERS[tool](text, declared)


# ---------------- grouping ----------------

def group(findings: list[Finding]) -> list[Finding]:
    """One Finding per package: the bump that fixes all its advisories. Sorted by package."""
    by: dict[str, list[Finding]] = {}
    for f in findings:
        by.setdefault(f.package, []).append(f)
    out = []
    for pkg in sorted(by):
        fs = by[pkg]
        installed = min((f.installed for f in fs), key=version_key)
        fixes = [f.fixed for f in fs]
        fixed = None if any(x is None for x in fixes) else max(fixes, key=version_key)   # type: ignore[arg-type]
        sev = max((f.severity for f in fs), key=lambda s: SEVERITY_ORDER.index(s) if s in SEVERITY_ORDER else 0)
        out.append(replace(fs[0], installed=installed, fixed=fixed, advisories=sorted({a for f in fs for a in f.advisories}),
                           severity=sev, transitive=all(f.transitive for f in fs), major=_is_major(installed, fixed),
                           kind="toolchain" if any(f.kind == "toolchain" for f in fs) else "dependency"))
    return out

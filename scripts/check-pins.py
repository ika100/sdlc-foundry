#!/usr/bin/env python3
# /// script
# dependencies = ["pyyaml"]
# ///
"""Pin check (spec 121, AC-121.2, ADR-069): every image and chart the platform ships comes from the versions table.

Four parts: (1) every row of `versions_table()` is exact (images `<repo>:<tag>@sha256:<64 hex>`, charts and manifests exact versions,
no floating tag); (2) a coverage render (a temporary gitops-app with every resource type, backups, `ui: lgtm`, `policy: enforce`, a cpu
and a queue `scale`, `resource_metrics: install`, `property_operators: install`) whose every image, `repository`+`tag` pair and Argo
chart source must equal a row; (3) the cluster scripts of both templates: every image reference, chart `version:` and `*_VERSION` default; (4) the test tools: the cplat suite command of `.github/workflows/ci.yml`, `scripts/ci-local.sh` and
`devbox.json` installs them only with `--with-requirements requirements-test.txt` (spec 127), whose every requirement is `==`.

One line per finding, `ERROR: <file>:<line or document path>: <reference>: <reason>`, then `FAILED: <n> reference(s)` (exit 1); else
`OK: <n> references, all from the versions table` (exit 0). Run it from the repository root: `python3 scripts/check-pins.py`.
"""
from __future__ import annotations

import importlib.util
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
RENDER = "templates/gitops-app/scripts/render.py"
SCRIPT_FILES = ["templates/gitops-app/scripts/local-cluster.sh", "templates/gitops-app/scripts/bootstrap.sh",
                "templates/cluster-gitops/scripts/local-cluster.sh", "templates/cluster-gitops/scripts/bootstrap.sh",
                "templates/cluster-gitops/scripts/cluster-up.sh"]
# the script variables whose default is a row of the table
VERSION_VARS = {"ARGOCD_VERSION": "argo-cd", "GATEWAY_API_VERSION": "gateway-api", "ESO_VERSION": "operator external-secrets",
                "KYVERNO_VERSION": "operator kyverno", "CNPG_VERSION": "operator cloudnative-pg",
                "SEAWEEDFS_OPERATOR_VERSION": "operator seaweedfs", "BARMAN_CLOUD_VERSION": "operator plugin-barman-cloud",
                "CERT_MANAGER_VERSION": "operator cert-manager", "VELERO_VERSION": "operator velero", "NACK_VERSION": "operator nack",
                "KEDA_VERSION": "operator keda", "METRICS_SERVER_VERSION": "operator metrics-server"}
FLOATING = {"latest", "stable", "edge", "main", "master", "nightly"}
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
EXACT = re.compile(r"^v?\d+\.\d+\.\d+$")
IMAGE_LINE = re.compile(r"""(?:\bimage:\s*|--image[= ]\s*|\b\w*IMAGE:-|\b\w*_pinned=)["']?([^\s"'}]+)""")
DIGESTED = re.compile(r"\w[\w./-]*:[\w.-]+@sha256:[0-9a-f]{16,}")
VERSION_DEFAULT = re.compile(r"""\$\{(\w+):-(?:\$\(rev_of\s+"[^"]*"\s+([^)\s]+)\)|([^}$]*))\}""")
CHART_VERSION = re.compile(r"^\s*version:\s*[\"']?([^\s\"'#]+)")

findings: list[str] = []
checked = 0


def error(where: str, ref: str, reason: str) -> None:
    findings.append(f"ERROR: {where}: {ref}: {reason}")


def split_ref(ref: str) -> tuple[str, str | None, str | None]:
    """`<repo>[:<tag>][@<digest>]` -> (repo, tag, digest); a registry port is not a tag."""
    body, _, digest = ref.partition("@")
    head, _, last = body.rpartition("/")
    repo, sep, tag = last.partition(":")
    return (f"{head}/{repo}" if head else repo), (tag if sep else None), (digest or None)


def floating(tag: str | None, strict_minor: bool = False) -> str | None:
    if tag is None:
        return "latest"
    if tag in FLOATING or re.fullmatch(r"v?\d+", tag) or (strict_minor and re.fullmatch(r"v?\d+\.\d+", tag)):
        return tag
    return None


def line_of(path: Path, needle: str, last: bool = False) -> int:
    hits = [n for n, line in enumerate(path.read_text().splitlines(), 1) if needle in line]
    return (hits[-1] if last else hits[0]) if hits else 1


def load_renderer(path: Path):
    spec = importlib.util.spec_from_file_location("check_pins_render", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_pins_render"] = module
    spec.loader.exec_module(module)
    return module


def check_image(where: str, ref: str, images: set[str], tags_by_repo: dict[str, set[str]]) -> None:
    """One image reference against the table: floating, digest, membership."""
    global checked
    checked += 1
    _, tag, digest = split_ref(ref)
    if (fl := floating(tag)) is not None:
        return error(where, ref, f"floating tag '{fl}'")
    if digest is None or not DIGEST.match(digest):
        return error(where, ref, "no digest")
    if ref not in images:
        error(where, ref, "not in the versions table")


def table_rows(render: Path) -> list[dict] | None:
    """Part 1: every row exact; returns the rows (None when the table cannot be built, after the findings that say why)."""
    global checked
    mod = load_renderer(render)
    refs = [*mod.POSTGRES_IMAGES.values(), *mod.VALKEY_IMAGES.values(), *mod.NATS_IMAGES.values(), mod.SEAWEEDFS_IMAGE, mod.COLLECTOR_IMAGE,
            mod.LGTM_IMAGE, mod.VELERO_AWS_PLUGIN_IMAGE, mod.CLUSTER_PINS["k3s"]["image"]]
    for ref in refs:       # the constants first: a bad one may keep `versions_table()` from building
        checked += 1
        repo, tag, digest = split_ref(ref)
        where = f"{RENDER}:{line_of(render, ref.split('@')[0], last=True)}"
        strict = repo in ("valkey/valkey", "nats") or repo.endswith("/postgresql")
        if (fl := floating(tag, strict_minor=strict and "-" not in (tag or ""))) is not None:
            error(where, ref, f"floating tag '{fl}'")
        elif digest is None or not DIGEST.match(digest):
            error(where, ref.split("@")[0], "no digest")
    try:
        rows = mod.versions_table()
    except Exception as exc:       # noqa: BLE001 - any failure of the table is a finding
        if not findings:
            error(f"{RENDER}:{line_of(render, 'def versions_table')}", "versions_table()", f"fails: {exc}")
        return None
    for row in rows:
        if row["kind"] == "image":
            continue
        checked += 1
        where = f"{RENDER}:{line_of(render, row['version'], last=True)}"
        if not EXACT.match(row["version"]):
            if (fl := floating(row["version"])) is not None:
                error(where, f"{row['name']} {row['version']}", f"floating tag '{fl}'")
            else:
                error(where, f"{row['name']} {row['version']}", "chart without an exact version" if row["kind"] == "chart"
                      else "not an exact version")
    return rows


def walk(node, path: str, visit) -> None:
    if isinstance(node, dict):
        visit(node, path)
        for key, value in node.items():
            walk(value, f"{path}.{key}" if path else str(key), visit)
    elif isinstance(node, list):
        for i, value in enumerate(node):
            walk(value, f"{path}[{i}]", visit)


COVERAGE = {
    "system": "shop", "owner": "acme",
    "environments": {"dev": {"host": "{component}.{system}-dev.localhost", "policy": "enforce", "observability": {"ui": "lgtm"},
                             "backup": {"to": "backups"}},
                     "staging": {"policy": "enforce", "backup": {"to": "backups"}}, "prod": {"policy": "enforce", "backup": {"to": "backups"}}},
    "secretStore": {"name": "platform-secrets", "kind": "ClusterSecretStore"},
    "apis": {"jobs": {"type": "events"}},
    "resources": {"orders-db": {"type": "database", "version": 17}, "old-db": {"type": "database", "version": 15},
                  "backups": {"type": "bucket"}, "sessions": {"type": "cache"}, "bus": {"type": "broker"}},
    "components": {
        "api": {"type": "service", "lang": "python", "repo": "acme/api", "image": "ghcr.io/acme/api", "port": 8080,
                "probes": {"liveness": "/health", "readiness": "/ready"}, "uses": ["orders-db", "old-db", "sessions", "backups"],
                "provides": ["jobs"], "resources": {"requests": {"cpu": "100m", "memory": "128Mi"}, "limits": {"memory": "256Mi"}},
                "scale": {"max": 5, "on": {"cpu": 70}}, "instances": {"dev": {}, "staging": {}, "prod": {}}},
        "worker": {"type": "service", "lang": "python", "repo": "acme/worker", "image": "ghcr.io/acme/worker", "port": 8080,
                   "probes": {"liveness": "/health", "readiness": "/ready"}, "consumes": ["jobs"],
                   "resources": {"requests": {"cpu": "100m", "memory": "128Mi"}, "limits": {"memory": "256Mi"}},
                   "scale": {"max": 5, "on": {"consumes": "jobs", "lag": 10}}, "instances": {"dev": {}, "staging": {}, "prod": {}}},
    },
}


def coverage_render(render: Path, rows: list[dict]) -> None:
    """Part 2: render everything in a temporary gitops-app and hold every reference to the table."""
    global checked
    images = {f"{r['ref']}@{r['digest']}" for r in rows if r["kind"] == "image"}
    charts = {r["ref"]: r["version"] for r in rows if r["kind"] == "chart"}
    own = {c["image"] for c in COVERAGE["components"].values()}
    with tempfile.TemporaryDirectory(prefix="check-pins-") as tmp:
        root = Path(tmp)
        (root / "scripts").mkdir()
        shutil.copy(render, root / "scripts" / "render.py")
        app = root / "applications" / "shop"
        app.mkdir(parents=True)
        (app / "system.yaml").write_text(yaml.safe_dump(COVERAGE, sort_keys=False))
        (root / ".copier-answers.yml").write_text(yaml.safe_dump({"resource_metrics": "install", "property_operators": "install"}))
        done = subprocess.run([sys.executable, "scripts/render.py"], cwd=root, capture_output=True, text=True)
        if done.returncode != 0:
            error(f"{RENDER}:1", "coverage render", "failed: " + (done.stderr or done.stdout).strip().splitlines()[-1])
            return
        for base in ("applications", "bootstrap", "operators"):
            for path in sorted((root / base).rglob("*")) if (root / base).is_dir() else []:
                if path.suffix not in (".yaml", ".yml") or path.name == "system.yaml":
                    continue
                rel = path.relative_to(root).as_posix()
                try:
                    docs = list(yaml.safe_load_all(path.read_text()))
                except yaml.YAMLError as exc:
                    error(rel, "document", f"unreadable YAML: {str(exc).splitlines()[0]}")
                    continue
                for n, doc in enumerate(docs):
                    prefix = f"{rel}#{n}" if len(docs) > 1 else rel

                    def visit(node: dict, where: str, prefix=prefix) -> None:
                        global checked
                        for key in ("image", "imageName"):
                            value = node.get(key)
                            if isinstance(value, str) and value.split(":")[0] not in own and value not in own:
                                check_image(f"{prefix}:{where + '.' if where else ''}{key}", value, images, {})
                        if isinstance(node.get("repository"), str) and isinstance(node.get("tag"), (str, int, float)):
                            check_image(f"{prefix}:{where + '.' if where else ''}repository", f"{node['repository']}:{node['tag']}", images, {})
                        if "chart" in node and "targetRevision" in node and "repoURL" in node:
                            checked += 1
                            ref = f"{node['repoURL']} {node['chart']}"
                            rev = str(node["targetRevision"])
                            at = f"{prefix}:{where + '.' if where else ''}targetRevision"
                            if not EXACT.match(rev):
                                error(at, f"{ref} {rev}", "chart without an exact version")
                            elif ref not in charts:
                                error(at, f"{ref} {rev}", "not in the versions table")
                            elif charts[ref] != rev:
                                error(at, f"{ref} {rev}", f"differs from the versions table ({ref}: {charts[ref]})")

                    walk(doc, "", visit)


def check_scripts(rows: list[dict]) -> None:
    """Part 3: image references, chart versions and `*_VERSION` defaults of the cluster scripts."""
    global checked
    images = {f"{r['ref']}@{r['digest']}" for r in rows if r["kind"] == "image"}
    by_name = {r["name"]: r for r in rows}
    chart_versions = {r["version"] for r in rows if r["kind"] in ("chart", "manifest")}
    for rel in SCRIPT_FILES:
        path = REPO / rel
        if not path.is_file():
            continue
        for n, line in enumerate(path.read_text().splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue
            where = f"{rel}:{n}"
            seen: set[str] = set()
            for m in [*IMAGE_LINE.finditer(line), *DIGESTED.finditer(line)]:
                ref = m.group(1) if m.re is IMAGE_LINE else m.group(0)
                if "$" in ref or ref in seen or not re.match(r"[\w.-]+(/[\w.-]+)*(:[\w.-]+)?(@sha256:[0-9a-f]+)?$", ref):
                    continue
                seen.add(ref)
                check_image(where, ref, images, {})
            for m in VERSION_DEFAULT.finditer(line):
                var, value = m.group(1), m.group(2) or m.group(3)
                if var not in VERSION_VARS or not value:
                    continue
                checked += 1
                row = by_name[VERSION_VARS[var]]
                if (fl := floating(value)) is not None:
                    error(where, value, f"floating tag '{fl}'")
                elif row["kind"] == "chart" and not EXACT.match(value):
                    error(where, value, "chart without an exact version")
                elif value != row["version"]:
                    error(where, value, f"differs from the versions table ({row['name']}: {row['version']})")
            m = CHART_VERSION.match(line)
            if m and "$" not in m.group(1) and "HelmChart" in path.read_text():
                checked += 1
                value = m.group(1)
                if not EXACT.match(value):
                    error(where, value, "chart without an exact version")
                elif value not in chart_versions:
                    error(where, value, "not in the versions table")


SUITE_FILES = [".github/workflows/ci.yml", "scripts/ci-local.sh", "devbox.json"]
TEST_TOOLS = ["pytest", "pytest-xdist", "pyyaml", "ruamel.yaml"]
REQ_FILE = "requirements-test.txt"
PINNED = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*==[^\s;=]+(\s*;\s*.+)?$")


def check_test_tools() -> None:
    """Part 4: the suite commands install the test tools only from requirements-test.txt, which pins every requirement."""
    global checked
    for rel in SUITE_FILES:
        path = REPO / rel
        lines = [(n, ln) for n, ln in enumerate(path.read_text().splitlines(), 1) if "pytest tests/cplat" in ln] if path.is_file() else []
        if not lines:
            error(f"{rel}:0", "pytest tests/cplat", "the cplat suite command is missing")
            continue
        for n, line in lines:
            checked += 1
            where = f"{rel}:{n}"
            if f"--with-requirements {REQ_FILE}" not in line:
                error(where, line.strip(), "installs the test tools without requirements-test.txt")
            for pkg in TEST_TOOLS:
                if re.search(rf"--with[= ]\s*{re.escape(pkg)}(\s|$|[\"'])", line):
                    checked += 1
                    error(where, f"--with {pkg}", f"installs {pkg} without requirements-test.txt")
    req = REPO / REQ_FILE
    if not req.is_file():
        return error(f"{REQ_FILE}:0", REQ_FILE, "the compiled test-tool pins are missing")
    for n, line in enumerate(req.read_text().splitlines(), 1):
        if not line.strip() or line.lstrip().startswith(("#", "-")) or line.startswith((" ", "\t")):
            continue
        checked += 1
        if not PINNED.match(line.strip()):
            error(f"{REQ_FILE}:{n}", line.strip(), "not pinned to an exact version")


def main() -> int:
    render = REPO / RENDER
    rows = table_rows(render)
    if rows is not None:
        coverage_render(render, rows)
        check_scripts(rows)
    check_test_tools()
    for line in findings:
        print(line)
    if findings:
        print(f"FAILED: {len(findings)} reference(s)")
        return 1
    print(f"OK: {checked} references, all from the versions table")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""`model show`: print the declared domain model of a gitops-app (spec 113, ADR-053). Reads files only, writes nothing."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import gitops
import model


def _d(value: object) -> str:
    return "-" if value is None or value == "" else str(value)


def _observability(o: model.Observability | None) -> str:
    if o is None:
        return "-"
    rules = len(o.rules) if isinstance(o.rules, (list, tuple)) else 0
    return f"ui={_d(o.ui) if o.ui else 'none'} export={_d(o.export_to)} alerts={'off' if o.alerts is False else 'on'} rules={rules}"


def render(m: model.Model) -> str:
    def section(title: str, lines: list[str]) -> str:
        return "\n".join([title, *(lines or ["  (none)"])])

    envs = [f"  {e.name}  host {_d(e.host)}  url-template {_d(e.url_template)}  policy {e.policy}  "
            f"promote {'follows main' if e.promotion == 'main' else e.promotion}  observability {_observability(e.observability)}"
            for e in m.environments]
    comps = []
    for c in m.components:
        ext = f"  external {c.external.kind}" if c.external else ""
        comps.append(f"  {c.name}  type {c.type}  lang {c.lang}  repo {_d(c.repo)}  image {_d(c.image)}{ext}  "
                     f"uses {','.join(c.uses) or '-'}  secrets {','.join(s.name for s in c.secrets) or '-'}  "
                     f"provides {','.join(c.provides) or '-'}  consumes {','.join(c.consumes) or '-'}  "
                     f"libraries {','.join(c.libraries) or '-'}")
    insts = [f"  {i.component}  {i.environment}  {i.tag or 'not pinned'}  replicas {_d(i.replicas)}  namespace {i.namespace}  url {_d(i.url)}"
             for i in m.instances]
    res: list[str] = []
    for r in m.resources:
        used = ",".join(c.name for c in m.components if r.name in c.uses) or "-"
        res.append(f"  {r.name}  type {r.type}  used by {used}")
        for ri in m.resource_instances_of(r.name):
            sizing = "".join(f"  {k} {v}" for k, v in ri.sizing.items())
            res.append(f"    {ri.environment}{sizing}  argo {ri.argo_application}  secret {_d(ri.secret)}")
    apis = [f"  {a.name}  type {a.type}  provider {_d(a.provider)}  consumers {','.join(a.consumers) or '-'}" for a in m.apis]
    return "\n\n".join([f"System: {m.system}\nOwner: {_d(m.owner)}",
                        section("Environments (promotion order):", envs), section("Components:", comps),
                        section("APIs:", apis), section("Instances:", insts), section("Resources:", res)]) + "\n"


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="cplat model", description=__doc__)
    sub = ap.add_subparsers(dest="action", required=True)
    sp = sub.add_parser("show", help="print the declared model")
    sp.add_argument("--json", action="store_true")
    sp.add_argument("--app")
    sp.add_argument("--repo-dir", default=".")
    ns = ap.parse_args(argv)
    m = model.load_dir(gitops.find_app(Path(ns.repo_dir).resolve(), ns.app))
    for w in m.warnings:
        print(f"warning: {w}", file=sys.stderr)
    if ns.json:
        print(json.dumps(m.to_dict(), indent=2))
    else:
        sys.stdout.write(render(m))
    return 0

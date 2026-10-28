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


def _backup(b: dict | None) -> str:
    return f'  backup to {b["to"]} schedule "{b["schedule"]}" retention {b["retention"]}' if b else ""


def _declares(a: dict) -> bool:
    return bool(a) and (a.get("declared") != "observe" or a.get("engine") or a.get("paused"))


def _env_autonomy(e: model.Environment) -> str:
    """The autonomy text of an environment; empty unless it declares autonomy (the old text stays exact)."""
    a = e.autonomy
    if not _declares(a):
        return ""
    eff = f" (effective {a['effective']})" if a["effective"] != a["declared"] else ""
    return f"\n    autonomy {a['declared']}{eff} engine {_d(a['engine'])}"


def _inst_autonomy(i: model.Instance) -> str:
    a = i.autonomy
    if not a or not a.get("max"):
        return ""
    return f"\n    autonomy max {a['max']} (effective {a['effective']})"


def _trigger(on: dict) -> str:
    if "cpu" in on:
        return f"cpu {on['cpu']}%"
    if "memory" in on:
        return f"memory {on['memory']}%"
    if "consumes" in on:
        return f"consumes {on['consumes']} lag {on.get('lag')}"
    return f"cache {on.get('cache')} list {on.get('list')} length {on.get('length')}"


def _scale(i: model.Instance) -> str:
    return f"  scale {i.scale['min']}\u2013{i.scale['max']} on {_trigger(i.scale['on'])}" if i.scale else ""


def render(m: model.Model) -> str:
    def section(title: str, lines: list[str]) -> str:
        return "\n".join([title, *(lines or ["  (none)"])])

    envs = [f"  {e.name}  host {_d(e.host)}  url-template {_d(e.url_template)}  policy {e.policy}  "
            f"promote {'follows main' if e.promotion == 'main' else e.promotion}  observability {_observability(e.observability)}"
            f"{'  operators owner' if e.operators == 'owner' else ''}{_backup(e.backup)}"
            f"{'  autoscaling keda' if e.autoscaling == 'keda' else ''}"
            f"{_env_autonomy(e)}" for e in m.environments]
    comps = []
    for c in m.components:
        ext = f"  external {c.external.kind}" if c.external else ""
        comps.append(f"  {c.name}  type {c.type}  lang {c.lang}  repo {_d(c.repo)}  image {_d(c.image)}{ext}  "
                     f"uses {','.join(c.uses) or '-'}  secrets {','.join(s.name for s in c.secrets) or '-'}  "
                     f"provides {','.join(c.provides) or '-'}  consumes {','.join(c.consumes) or '-'}  "
                     f"libraries {','.join(c.libraries) or '-'}")
    insts = [f"  {i.component}  {i.environment}  {i.tag or 'not pinned'}  replicas {_d(i.replicas)}  namespace {i.namespace}  url {_d(i.url)}"
             f"{_scale(i)}{_inst_autonomy(i)}" for i in m.instances]
    res: list[str] = []
    for r in m.resources:
        used = ",".join(c.name for c in m.components if r.name in c.uses) or "-"
        res.append(f"  {r.name}  type {r.type}  external {str(r.external).lower()}  used by {used}")
        for ri in m.resource_instances_of(r.name):
            sizing = "".join(f"  {k} {str(v).lower() if isinstance(v, bool) else v}" for k, v in ri.sizing.items())
            store = f"  store {ri.store_key}" if ri.external else ""
            res.append(f"    {ri.environment}  type {ri.type}  external {str(ri.external).lower()}{sizing}  "
                       f"argo {_d(ri.argo_application)}  secret {_d(ri.secret)}{store}{_backup(ri.backup)}")
            if ri.broker is not None:
                b = ri.broker
                users = ", ".join(f"{u['component']} ({u['secret']})" for u in b["users"]) or "-"
                res.append(f"      address {_d(b['address'])}  monitoring {_d(b['monitoring'])}")
                res.append(f"      users {users}")
                for st in b["streams"]:
                    cons = ",".join(c["name"] for c in st["consumers"]) or "-"
                    res.append(f"      stream {st['stream']}  subjects {st['subjects']}  consumers {cons}")
    apis = [f"  {a.name}  type {a.type}  provider {_d(a.provider)}  consumers {','.join(a.consumers) or '-'}"
            f"{'  broker ' + a.broker if a.broker else ''}" for a in m.apis]
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

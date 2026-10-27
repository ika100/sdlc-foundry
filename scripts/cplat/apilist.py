"""`api list`: print each declared API with its type, provider and consumers (spec 114). Reads files only, writes nothing."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import gitops
import model


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="cplat api list", description=__doc__)
    ap.add_argument("--system")
    ap.add_argument("--repo-dir", default=".")
    ap.add_argument("--json", action="store_true")
    ns = ap.parse_args(argv)
    m = model.load_dir(gitops.find_app(Path(ns.repo_dir).resolve(), ns.system))
    if ns.json:
        apis = [{"name": a.name, "type": a.type, "provider": a.provider, "consumers": list(a.consumers),
                 **({"broker": a.broker} if a.type == "events" else {})} for a in m.apis]
        print(json.dumps({"system": m.system, "apis": apis}, indent=2))
    elif not m.apis:
        print("no APIs declared")
    else:
        for a in m.apis:
            print(f"{a.name}  type {a.type}  provider {a.provider or '-'}  consumers {','.join(a.consumers) or '-'}"
                  f"{'  broker ' + a.broker if a.broker else ''}")
    return 0

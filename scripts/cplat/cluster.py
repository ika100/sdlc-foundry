"""`cluster`: what a Kubernetes workload runs right now (spec 105).

Public API:

  running_digest(context, namespace, service) -> "sha256:<64 hex>" | None

The digest is taken from the `imageID` of the service's container in the Ready pods labelled
`app.kubernetes.io/name=<service>`. Several different digests, no Ready pod or an unreadable answer give None (never raises).
"""
from __future__ import annotations

import json
import re

from core import PlatformError, run

IMAGE_ID = re.compile(r"@(sha256:[0-9a-f]{64})$")


def running_digest(context: str, namespace: str, service: str) -> str | None:
    try:
        p = run(["kubectl", "--context", context, "-n", namespace, "get", "pods", "-l", f"app.kubernetes.io/name={service}",
                 "-o", "json"], check=False)
        if p.returncode != 0:
            return None
        found: set[str] = set()
        for pod in json.loads(p.stdout).get("items") or []:
            status = pod.get("status") or {}
            if not any(c.get("type") == "Ready" and c.get("status") == "True" for c in status.get("conditions") or []):
                continue
            for cs in status.get("containerStatuses") or []:
                if cs.get("name") == service and (m := IMAGE_ID.search(str(cs.get("imageID") or ""))):
                    found.add(m.group(1))
        return next(iter(found)) if len(found) == 1 else None
    except (PlatformError, ValueError, AttributeError, TypeError):
        return None

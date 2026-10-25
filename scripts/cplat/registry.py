"""`registry`: the digest of an image tag in GHCR (spec 105; spec 106 reuses it).

Public API:

  digest(image, tag) -> "sha256:<64 hex>"     image is `ghcr.io/<owner>/<name>`; raises RegistryError(message, hint)
  RegistryError                               a PlatformError that names the failed call and the fix
  gh(args) -> str                             `gh` wrapper, the one seam tests replace

The digest is the `name` of the package version whose `metadata.container.tags` holds the tag (`gh api
/users|orgs/<owner>/packages/container/<name>/versions`; needs the `read:packages` scope).
"""
from __future__ import annotations

import json
import re
from urllib.parse import quote

from core import PlatformError, run

DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
FIX = "gh auth refresh -s read:packages"


class RegistryError(PlatformError):
    """The digest of an image tag could not be read."""


def gh(args: list[str]) -> str:
    """`gh` wrapper (tests replace this)."""
    return run(["gh", *args]).stdout


def image_name(entry: dict | None, repo_slug: str) -> str:
    """The image of a service: the gitops entry's `image` when it has one, else `ghcr.io/<repo slug lowercased>`."""
    return str((entry or {}).get("image") or f"ghcr.io/{repo_slug.lower()}")


def digest(image: str, tag: str) -> str:
    m = re.match(r"^ghcr\.io/([^/]+)/(.+)$", image)
    if not m:
        raise RegistryError(f"cannot read the digest of non-GHCR image {image}:{tag}", "only ghcr.io/<owner>/<name> images are supported")
    owner, name = m.groups()
    last = "no answer"
    for kind in ("users", "orgs"):
        path = f"/{kind}/{owner}/packages/container/{quote(name, safe='')}/versions"
        call = f"gh api {path}"
        try:
            versions = json.loads(gh(["api", f"{path}?per_page=100"]) or "[]")
        except PlatformError as e:
            last = f"{call} failed: {str(e).strip().splitlines()[-1] if str(e).strip() else type(e).__name__}"
            continue
        except ValueError:
            last = f"{call} returned something other than JSON"
            continue
        for v in versions if isinstance(versions, list) else []:
            tags = (((v or {}).get("metadata") or {}).get("container") or {}).get("tags") or []
            if tag in tags and DIGEST.match(str((v or {}).get("name"))):
                return v["name"]
        raise RegistryError(f"{image}:{tag} is not among the latest 100 versions of the package ({call})",
                            f"is the tag published? check the service's docker-publish run; {FIX} if the package is private")
    raise RegistryError(f"cannot read the digest of {image}:{tag}: {last}", FIX)

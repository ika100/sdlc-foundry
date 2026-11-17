"""`envlimit`: the `environments:` field of a spec's front matter (spec 190) and every line that talks about it.

`spec check` validates it, `spec show` and `spec approve` display it, `instance promote` and the automatic staging promotion
ask which approved specs leave a target environment out. All wording lives here so the entry points cannot drift apart.
The limit is fail-closed: a malformed field allows nothing.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import yaml

import model

ENVIRONMENTS: tuple[str, ...] = model.ENVIRONMENTS
LIMITING = ("building", "done")          # a draft or approved spec does not limit anything yet; a superseded one never does
SPECS = "docs/specs"
VALID = ", ".join(ENVIRONMENTS)


@dataclass(frozen=True)
class Limit:
    spec_id: str
    title: str
    environments: tuple[str, ...]        # the allowed set (known names, in field order)

    @property
    def number(self) -> str:
        return self.spec_id.split("-", 1)[0]


def _flow(value) -> str:
    """A value as YAML flow text: `[]`, `null`, `dev`, `{a: 1}`."""
    text = yaml.safe_dump(value, default_flow_style=True, width=10_000).strip()
    return text[:-4].rstrip() if text.endswith("\n...") else text


def field_errors(meta: dict) -> list[str]:
    if "environments" not in meta:
        return []
    value = meta["environments"]
    if not isinstance(value, list) or not value:
        return [f"spec.md: environments must be a non-empty list out of {VALID} (got {_flow(value)})"]
    return [f"spec.md: environments: unknown environment '{name}' (valid: {VALID})"
            for name in value if name not in ENVIRONMENTS]


def allowed(meta: dict) -> list[str] | None:
    """None without the field, else the known names it lists (a string counts as a one-item list)."""
    if "environments" not in meta:
        return None
    value = meta["environments"]
    items = [value] if isinstance(value, str) else value if isinstance(value, list) else []
    return [i for i in items if isinstance(i, str) and i in ENVIRONMENTS]


def limit_of(spec_id: str, meta: dict, target: str) -> Limit | None:
    envs = allowed(meta)
    if envs is None or str(meta.get("status", "")) not in LIMITING or target in envs:
        return None
    return Limit(spec_id, str(meta.get("title", "")), tuple(envs))


def local_limits(repo: Path, target: str) -> list[Limit]:
    import spec
    found = (limit_of(s.id, s.meta, target) for s in spec.scan(repo)[0])
    return sorted((lim for lim in found if lim), key=lambda lim: lim.spec_id)


def remote_limits(list_dirs: Callable[[str], list[str] | None], read_text: Callable[[str], str | None],
                  target: str) -> tuple[list[Limit], list[str]]:
    import spec
    limits: list[Limit] = []
    unreadable: list[str] = []
    for d in sorted(list_dirs(SPECS) or []):
        text = read_text(f"{SPECS}/{d}/spec.md")
        m = spec.FRONT.match(text) if text is not None else None
        try:
            meta = yaml.safe_load(m.group(1)) if m else None
        except yaml.YAMLError:
            meta = None
        if not isinstance(meta, dict):
            unreadable.append(d)
            continue
        if lim := limit_of(d, meta, target):
            limits.append(lim)
    return limits, unreadable


def envs_text(envs) -> str:
    return ", ".join(envs)


def refusal_line(lim: Limit, target: str) -> str:
    return f"environment limit: {lim.spec_id} allows {envs_text(lim.environments)}, not {target} ({lim.title})"


def fix_text(limits: list[Limit]) -> str:
    amend = " / ".join(f"/system:spec --amend {lim.number}" for lim in limits)
    return (f"widen the spec with {amend} once the work that lifts the limit has shipped, or promote anyway with "
            "--accept-environment-limit \"<reason>\" (a person's decision)")


def accepted_line(lim: Limit, reason: str) -> str:
    return f"environment limit accepted: {lim.spec_id} ({envs_text(lim.environments)}): {reason}"


def skip_reason(limits: list[Limit], unreadable: list[str] = ()) -> str:
    parts = [f"environment limit {lim.spec_id} allows {envs_text(lim.environments)}" for lim in limits]
    parts += [f"environment limit of {d} not readable" for d in unreadable]
    return "; ".join(parts)


def summary_line(envs: list[str]) -> str:
    others = [e for e in ENVIRONMENTS if e not in envs]
    refused = f"promotion to {envs_text(others)} is refused" if others else "no promotion is refused"
    return f"Environment limit: {envs_text(envs)} ({refused})"

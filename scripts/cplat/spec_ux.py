"""`spec ux`: whether a spec gets the UX design step of `/component:plan` (spec 219), and the check of its `ux.md`.

Only a shape that declares `ux_designer` in shapes.yml has the step. There a spec's `ux: needed|none` decides; without it,
an active criterion or a story that names something a user sees or does on screen makes it `needed`. A `ux.md` written for
the current criteria (its `spec_hash`) is `done`; one written for earlier criteria is stale and designed again.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

import core
import spec as specmod

VALUES = ("needed", "none")
SECTIONS = ("Flows", "Screens", "States", "Accessibility")
UX_FILE = "ux.md"
AC_REF = re.compile(r"\bAC-\d{3,}\.\d+\b")
# Things a user sees or does on screen; a word here in a criterion or story is what makes a spec change the UI.
VISIBLE = re.compile(
    r"\b(pages?|screens?|views?|forms?|buttons?|links?|menus?|dialogs?|modals?|banners?|toasts?|tooltips?|tabs?|"
    r"navigation|sidebar|layout|cards?|fields?|checkbox(?:es)?|dropdowns?|icons?|images?|placeholder|spinner|"
    r"shown|shows|displays?|displayed|visible|sees?|clicks?|clicked|taps?|hovers?|scrolls?)\b", re.I)


def field_errors(meta: dict) -> list[str]:
    """The `ux:` field of spec.md, when present, is one of VALUES."""
    if "ux" not in meta or meta["ux"] in VALUES:
        return []
    return [f"spec.md: ux must be one of {', '.join(VALUES)} (got {meta['ux']})"]


def _front(text: str) -> tuple[dict, str] | None:
    m = specmod.FRONT.match(text)
    if not m:
        return None
    try:
        meta = yaml.safe_load(m.group(1))
    except yaml.YAMLError:
        return None
    return (meta if isinstance(meta, dict) else {}), m.group(2)


def _recorded_hash(text: str) -> str | None:
    """Taken from the text, as plan.md's (#536): YAML would read an all-digit hash as a number."""
    m = re.search(r"^spec_hash:\s*[\"']?([0-9a-fA-F]+)", text, re.M)
    return m.group(1) if m else None


def file_errors(spec: specmod.Spec) -> list[str]:
    """Errors of the spec's `ux.md`; none when it has no such file."""
    path = spec.dir / UX_FILE
    if not path.is_file():
        return []
    text = path.read_text()
    parsed = _front(text)
    if parsed is None:
        return [f"{UX_FILE}: needs front matter with spec_id and spec_hash"]
    meta, body = parsed
    errs = []
    if meta.get("spec_id") != spec.id:
        errs.append(f"{UX_FILE}: spec_id '{meta.get('spec_id')}' must equal the folder name '{spec.id}'")
    if not _recorded_hash(text):
        errs.append(f"{UX_FILE}: missing spec_hash (the value of `cplat spec hash {spec.number}`)")
    found = specmod.sections(body)
    errs += [f"{UX_FILE}: missing section '## {s}'" for s in SECTIONS if s.lower() not in found]
    active = set(spec.active_acs())
    errs += [f"{UX_FILE}: {ref} is not an active criterion of {spec.id}"
             for ref in sorted(set(AC_REF.findall(body))) if ref not in active]
    return errs


def _visible_word(spec: specmod.Spec) -> str | None:
    parts = specmod.sections(spec.body)
    active = [ln for ln in parts.get("acceptance criteria", "").splitlines()
              if (m := specmod.AC_LINE.match(ln)) and not m.group(1)]
    for text in (*active, parts.get("stories", "")):
        if m := VISIBLE.search(text):
            return m.group(0).lower()
    return None


def decide(root: Path, spec: specmod.Spec) -> dict:
    """{"spec", "ux": needed|none|done, "reason"} for `spec` in the repo at `root`."""
    shape = specmod.repo_shape(root)
    entry = core.registry.get(shape) if shape else None
    if not (entry or {}).get("ux_designer"):
        return {"spec": spec.id, "ux": "none", "reason": f"{shape or 'no shape'} has no UX design step"}
    path = spec.dir / UX_FILE
    stale = False
    if path.is_file():
        if _recorded_hash(path.read_text()) == spec.ac_hash():
            return {"spec": spec.id, "ux": "done", "reason": f"{UX_FILE} matches the current criteria"}
        stale = True
    stale_note = f"; {UX_FILE} is stale (written for earlier criteria)" if stale else ""
    if spec.meta.get("ux") in VALUES:
        value = spec.meta["ux"]
        return {"spec": spec.id, "ux": value, "reason": f"ux: {value} is set in spec.md" + (stale_note if value == "needed" else "")}
    word = _visible_word(spec)
    if word:
        return {"spec": spec.id, "ux": "needed", "reason": f"a criterion or story names '{word}'{stale_note}"}
    return {"spec": spec.id, "ux": "none", "reason": "no active criterion or story names something a user sees"}


def add_parser(sub) -> None:
    p = sub.add_parser("ux", help="does the spec get the UX design step of /component:plan: needed, none or done (spec 219)")
    p.add_argument("id")
    p.add_argument("--json", action="store_true")


def run(root: Path, ref: str, as_json: bool) -> int:
    out = decide(root, specmod.find(root, ref))
    print(json.dumps(out, indent=2) if as_json else f"{out['spec']}: {out['ux']} — {out['reason']}")
    return 0

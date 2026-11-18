"""The priority scale (spec 196): one source for triage and `cplat spec`."""
from __future__ import annotations

LEVELS: dict[str, dict] = {  # order = urgency
    "P0": {
        "definition": "an outage, data loss, a security problem, or something that blocks all other work",
        "phrases": ["outage", "data loss", "security problem", "blocks all other work"],
    },
    "P1": {
        "definition": "a normal bug or feature; the fallback when nothing signals urgency",
        "phrases": ["normal bug or feature"],
    },
    "P2": {
        "definition": "cosmetic, a convenience, or something with an easy workaround",
        "phrases": ["cosmetic", "convenience", "easy workaround"],
    },
}
FALLBACK_REASON = "P1: normal bug or feature"
MAX_REASON = 60


def proposal_reason_ok(level: str, reason: str) -> bool:
    """True when `reason` is `<level>: <phrase>` for a phrase of that level and fits 60 characters."""
    spec = LEVELS.get(level)
    if spec is None or len(reason) > MAX_REASON:
        return False
    return any(reason == f"{level}: {phrase}" for phrase in spec["phrases"])


def label_of(level: str) -> str:
    return level.lower()


def level_of(label: str) -> str:
    return label.upper()


def most_urgent(labels: list[str]) -> str | None:
    """The most urgent level among p0/p1/p2 labels, None without one."""
    present = set(labels)
    for level in LEVELS:
        if label_of(level) in present:
            return level
    return None


def levels_json() -> list[dict]:
    return [{"level": lv, "definition": s["definition"], "phrases": list(s["phrases"])} for lv, s in LEVELS.items()]


def skeleton_comment() -> str:
    """The one-line HTML comment `spec new` puts into a skeleton."""
    defs = "; ".join(f"{lv} {s['definition']}" for lv, s in LEVELS.items())
    phrases = "; ".join(f"{lv}: {', '.join(s['phrases'])}" for lv, s in LEVELS.items())
    return (
        "<!-- Priority levels (spec 196) for the product-manager's PRIORITY line: "
        f'{defs}. A reason is "P<n>: <phrase>", one of: {phrases}. -->'
    )

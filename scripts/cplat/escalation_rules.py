"""Classify an escalation by its reason (spec 088, amendment #207; AC-088.15 to AC-088.17, AC-088.21).

A pure module: the rule table, `classify`, `resolve` (writer side) and `effective` (reader side). `runs.finish`, `ship
escalate` and the report and retro readers call the same functions, so they cannot disagree. No rule yields `platform`.
"""
import re
from dataclasses import dataclass

ALLOWED = ("platform", "code", "decision", "environment")
SOURCES = ("given", "rule", "none")

_SPEC = r"(spec|ac-\d{3}\.\d+|criteri(on|a)|rule)"
_GIT = r"(git|branch(es)?|commit(s|ting|ted)?|push(es|ing|ed)?|merg(e|es|ing|ed)|rebas(e|es|ing|ed)|checkout|tag(s|ging)?)"
_TREE = r"(working[ -]?tree|worktree|checkout)"
_DIRTY = r"(dirty|unclean|not clean)"


@dataclass(frozen=True)
class Rule:
    name: str
    cause: str
    patterns: tuple

    def matches(self, reason: str) -> bool:
        return all(p.search(reason) for p in self.patterns)


def _rule(name: str, cause: str, *patterns: str) -> Rule:
    return Rule(name, cause, tuple(re.compile(p, re.IGNORECASE) for p in patterns))


RULES: tuple = (
    _rule("spec-test-conflict", "decision",
          rf"\bspec\s*/\s*tests?\s+conflicts?\b"
          rf"|\btests?\b.*\b(contradicts?|contradicting|contradiction with|conflicts? with)\b.*\b{_SPEC}\b"
          rf"|\b{_SPEC}\b.*\b(contradicts?|contradicting|conflicts? with)\b.*\btests?\b"),
    _rule("left-for-review", "decision", r"\bleft\b[^.;]{0,30}\b(for|to)\b[^.;]{0,30}\breview\b"),
    _rule("git-action-awaits-approval", "environment",
          r"\b(wait|waits|waiting|needs?|requires?|requiring|asks?|asking|pending|blocked on)\b",
          r"\b(approval|approve|permissions?|confirmation|confirm)\b",
          rf"\b{_GIT}\b"),
    _rule("dirty-working-tree", "environment",
          rf"\b{_DIRTY}\b.*\b{_TREE}\b|\b{_TREE}\b.*\b{_DIRTY}\b|\b(uncommitted|unstaged) (changes|files)\b"),
)

assert all(r.cause != "platform" for r in RULES), "no classification rule may yield platform"


@dataclass(frozen=True)
class Resolved:
    cause: str
    source: str
    rule: str | None = None


def classify(reason) -> Rule | None:
    """The first rule that matches the reason; None for no match or a non-string reason."""
    if not isinstance(reason, str):
        return None
    return next((r for r in RULES if r.matches(reason)), None)


def resolve(cause, reason) -> Resolved:
    """Writer side: a stated allowed cause wins; otherwise the rules; otherwise unknown."""
    if isinstance(cause, str) and cause in ALLOWED:
        return Resolved(cause, "given", None)
    rule = classify(reason)
    if rule is not None:
        return Resolved(rule.cause, "rule", rule.name)
    return Resolved("unknown", "none", None)


def effective(escalation: dict) -> Resolved:
    """Reader side: a stored allowed cause is kept; anything else is classified with the current rules."""
    esc = escalation if isinstance(escalation, dict) else {}
    cause = esc.get("cause")
    if isinstance(cause, str) and cause in ALLOWED:
        source = esc.get("cause_source")
        if source not in ("given", "rule"):
            source = "given"
        rule = esc.get("rule") if source == "rule" and isinstance(esc.get("rule"), str) else None
        return Resolved(cause, source, rule)
    return resolve(None, esc.get("reason"))


def message(resolved: Resolved) -> str | None:
    """`classified as <cause> by rule <rule>` for a rule match, else None."""
    if resolved.source == "rule":
        return f"classified as {resolved.cause} by rule {resolved.rule}"
    return None

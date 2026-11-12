"""Spec 180: structure helpers of the prompt tests (not a test module): what a platform prompt points to and its headings.

`refs(rel)` is the set of `promptrefs.Target.key` of the prompt at repo-relative `rel`; `points_to(rel, key)` asks for one
(a path key may be plugin-relative, `references/x.md`); `headings(rel)` lists the heading texts in order."""
import core
import promptrefs


def _text(rel: str) -> str:
    return (core.PLATFORM_ROOT / rel).read_text()


def refs(rel: str) -> set[str]:
    return {t.key for t in promptrefs.targets(core.PLATFORM_ROOT, rel, _text(rel))}


def points_to(rel: str, key: str) -> bool:
    found = refs(rel)
    if key in found:
        return True
    if key.startswith(("cplat ", "/")):
        return False
    return any(k == key or k.endswith("/" + key) for k in found)


def headings(rel: str) -> list[str]:
    return promptrefs.heading_texts(_text(rel))

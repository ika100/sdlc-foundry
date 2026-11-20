"""The short summary at the top of every PR body `cplat` opens (spec 157, ADR-079).

Four labelled lines (Changed, Why, Review, Risks and follow-ups) between markers, rendered from records only: the spec,
the branch's changelog fragment, git, the current run and `verification.md`. Every value is redacted, one line and bounded.
`add` never raises: a failure leaves the body unchanged and returns a `note: summary skipped: <why>` line.
"""
from __future__ import annotations

import re
from pathlib import Path

import feedback
import pr_rules
import runs
import runs_built
import spec as specmod
from core import run

START = "<!-- cplat:summary -->"
END = "<!-- /cplat:summary -->"
MAX_LINE = 300          # characters per rendered line, the bullet prefix included
MAX_ITEMS = 3           # closing references in Why, items in Risks and follow-ups

_BLOCK = re.compile(re.escape(START) + r".*?" + re.escape(END) + r"\n*", re.S)
_ITEM = re.compile(r"^(?:[-*]|\d+\.)\s+(.*)$")
_RESULT = re.compile(r"^\*\*Result:\*\*\s*(pass|fail)\b", re.I | re.M)
_SEVERITY_ORDER = ("not met", "partial", "deviation")


def _line(value) -> str:
    """A value as one redacted line that cannot close the block."""
    text = " ".join(feedback.redact(str(value)).split())
    return text.replace("<!--", "").replace("-->", "")


def _first_sentence(text: str) -> str:
    text = " ".join(text.split())
    m = re.search(r"[.!?](?=\s|$)", text)
    return text[:m.end()] if m else text


def _plain(text: str) -> str:
    text = text.replace("**", "").replace("__", "")
    return re.sub(r"(?<![\w*])[*_]|[*_](?![\w*])", "", text)


def _out(cmd: list[str], repo: Path) -> str:
    return (run(cmd, cwd=repo, check=False).stdout or "").strip()


def _files(repo: Path, base: str) -> list[str]:
    names = {f for f in _out(["git", "diff", "--name-only", f"{base}...HEAD"], repo).splitlines() if f}
    for line in (run(["git", "status", "--porcelain"], cwd=repo, check=False).stdout or "").splitlines():
        path = line[3:].split(" -> ")[-1].strip().strip('"')
        if path:
            names.add(path)
    return sorted(names)


def _more(items: list[str], limit: int = MAX_ITEMS) -> str:
    shown = items[:limit]
    if len(items) > limit:
        shown.append(f"… and {len(items) - limit} more")
    return "; ".join(shown)


def _changed(repo: Path, sp, title: str, files: list[str]) -> str:
    text = str(sp.meta.get("title") or "").strip() if sp else ""
    if not text and (repo / "docs" / "changelog.d").is_dir():
        frags = sorted(f for f in files if f.startswith("docs/changelog.d/") and f.endswith(".md")
                       and f != "docs/changelog.d/README.md" and (repo / f).is_file())
        if frags:
            text = _first_sentence(_plain((repo / frags[0]).read_text()))
    text = text or title
    if sp:
        num = re.match(r"\d+", sp.id)
        return f"{text} ({len(sp.active_acs())} criteria of spec {num.group() if num else sp.id}, {len(files)} files)"
    return f"{text} ({len(files)} files)"


def _why(repo: Path, sp, body: str) -> str:
    if sp:
        para: list[str] = []
        for ln in runs_built._section(sp.body, "Stories"):
            if not ln.strip():
                if para:
                    break
                continue
            para.append(ln)
        text = " ".join(" ".join(para).split())
        i = text.find("so that")
        if i >= 0:
            return _first_sentence(text[i:])
    refs: list[str] = []
    for m in pr_rules.CLOSES.finditer(_BLOCK.sub("", body)):
        found = re.search(r"#(\d+)", m.group(0))
        if found and found.group(1) not in refs:
            refs.append(found.group(1))
    items = []
    for n in refs:
        try:
            title = _out(["gh", "issue", "view", n, "--json", "title", "-q", ".title"], repo)
        except Exception:  # noqa: BLE001
            title = ""
        items.append(f"Closes #{n}: {_line(title)}" if title else f"Closes #{n}")
    return _more(items) if items else "not recorded"


def _follow_ups(spec_dir: Path | None) -> list[str]:
    try:
        text = (spec_dir / "verification.md").read_text() if spec_dir else ""
    except OSError:
        return []
    items: list[str] = []
    for ln in runs_built._section(text, "Follow-ups"):
        m = _ITEM.match(ln)
        if m:
            items.append(m.group(1))
        elif items and ln.strip():
            items[-1] += " " + ln.strip()
    out = []
    for item in items:
        plain = item.replace("**", "").strip()
        if plain.rstrip(".").lower() in {"none", "n/a"}:
            continue
        out.append(_first_sentence(plain))
    return out


def _review(sp, spec_dir: Path | None, rec: dict | None, deviations: list[str]) -> str:
    state = "not yet"
    try:
        m = _RESULT.search((spec_dir / "verification.md").read_text()) if spec_dir else None
    except OSError:
        m = None
    if m:
        state = m.group(1).lower()
    if rec is None:
        return f"verification {state}; findings not recorded"
    events = [ev for _, ev in runs_built._events(rec)]
    found = [ev for ev in events if ev.get("kind") == "finding"]
    counts: dict[str, int] = {}
    for ev in found:
        sev = str(ev.get("severity") or "unknown")
        counts[sev] = counts.get(sev, 0) + 1
    order = [s for s in _SEVERITY_ORDER if s in counts] + sorted(s for s in counts if s not in _SEVERITY_ORDER)
    sev_text = ", ".join(f"{counts[s]} {s}" for s in order) or "none"
    fixed = 0
    if any(ev.get("kind") == "fix-round" for ev in events) and sp:
        verdicts = specmod._verdicts(sp)
        fixed = sum(1 for ev in found if ev.get("severity") in ("not met", "partial")
                    and verdicts.get(str(ev.get("criterion"))) == "met")
    return (f"verification {state}; {len(found)} reviewer findings ({sev_text}), {fixed} fixed in fix rounds, "
            f"{len(deviations)} accepted as deviations")


def render(repo: Path, *, body: str, title: str, spec: str | None, base: str) -> str:
    """The block (START … END, ending in a newline). Raises on any failure."""
    repo = Path(repo)
    sp = specmod.find(repo, spec) if spec else None
    spec_dir = sp.dir if sp else None
    files = _files(repo, base)
    rec = runs_built.find(runs.current_run(repo))
    if rec is not None and not runs_built._same_spec(rec.get("spec"), spec):
        rec = None
    deviations = runs_built.accepted_deviations(spec_dir) or []
    values = [
        ("Changed", _changed(repo, sp, title, files)),
        ("Why", _why(repo, sp, body)),
        ("Review", _review(sp, spec_dir, rec, deviations)),
        ("Risks and follow-ups", _more(deviations + _follow_ups(spec_dir)) or "none recorded"),
    ]
    lines = []
    for label, value in values:
        line = f"- **{label}:** {_line(value)}"
        lines.append(line if len(line) <= MAX_LINE else line[:MAX_LINE - 1] + "…")
    return "\n".join([START, "**Summary**", *lines, END]) + "\n"


def apply(body: str, block: str) -> str:
    """Remove every earlier block; the new one goes on top, one blank line before the rest."""
    rest = _BLOCK.sub("", body).lstrip("\n")
    return block + "\n" + rest if rest else block


def add(repo: Path, body: str, *, title: str, spec: str | None, base: str) -> tuple[str, str | None]:
    """(body with the block, None); on any failure (body unchanged, the note line)."""
    try:
        return apply(body, render(repo, body=body, title=title, spec=spec, base=base)), None
    except Exception as e:  # noqa: BLE001
        why = (str(e).splitlines() or [""])[0]
        return body, f"note: summary skipped: {type(e).__name__}: {why}"[:200]

"""Proposals of the weekly retro (spec 090, ADR-039): format, evidence check against the report, covers, limits, rendering.

Pure apart from `load` and `prompt`, which read a file. The agent writes `proposals.json`; nothing in it is trusted until
`validate` has checked it against the same `report.json`.
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path

import retro_report

MAX_SPECS, MAX_PROMPTS, MAX_SENTENCES = 5, 3, 5
PRIORITIES = ("P0", "P1", "P2")
PROMPT_ASSET = Path(__file__).parent / "assets" / "retro-prompt.md"
_ISSUE_REF = re.compile(r"^issues\.#(\d+)$")


@dataclass
class Checked:
    specs: list[dict] = field(default_factory=list)
    prompts: list[dict] = field(default_factory=list)
    refused: list[str] = field(default_factory=list)


def load(path: Path) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as e:
        raise ValueError(f"proposals.json: {e.strerror or e}") from None
    except ValueError as e:
        raise ValueError(f"proposals.json: not valid JSON ({e})") from None
    if not isinstance(data, dict):
        raise ValueError("proposals.json: not a JSON object")
    return data


def not_generated(reason: str) -> str:
    return f"Proposals: not generated ({reason})"


def _same(a, b) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return math.isclose(a, b, rel_tol=0.0, abs_tol=1e-9)
    return a == b


def _matching(items, index: dict, prefix: str = "") -> list[dict]:
    if not isinstance(items, list):
        return []
    out = []
    for it in items:
        if (isinstance(it, dict) and isinstance(it.get("ref"), str) and it["ref"].startswith(prefix) and it["ref"] in index
                and _same(it.get("value"), index[it["ref"]])):
            out.append({"ref": it["ref"], "value": it["value"]})
    return out


def _one_line(v, limit: int) -> bool:
    return isinstance(v, str) and bool(v.strip()) and "\n" not in v and "\r" not in v and len(v) <= limit


def _format_problem(p: dict) -> str | None:
    if not _one_line(p.get("title"), 100):
        return "invalid title (one line, at most 100 characters)"
    problem = p.get("problem")
    if not isinstance(problem, str) or not problem.strip():
        return "invalid problem (empty)"
    if len(re.split(r"(?<=[.!?])\s+", problem.strip())) > MAX_SENTENCES:
        return f"invalid problem (more than {MAX_SENTENCES} sentences)"
    if p.get("priority") not in PRIORITIES:
        return f"invalid priority (one of {', '.join(PRIORITIES)})"
    if not _one_line(p.get("spec_line"), 200):
        return "invalid spec_line (one line, at most 200 characters)"
    return None


def _covers(p: dict, evidence: list[dict], report: dict) -> tuple[dict | None, str | None]:
    ctx = report.get("context") or {}
    specs, opens = ctx.get("specs") or [], ctx.get("open_issues") or []
    open_numbers = {i.get("number") for i in opens if isinstance(i, dict)}
    cov = p.get("covers")
    if cov is None:
        for it in evidence:
            m = _ISSUE_REF.match(it["ref"])
            if not m:
                continue
            n = int(m.group(1))
            for s in specs:
                if n in (s.get("tracks") or []):
                    return {"spec": s["number"]}, None
            if n in open_numbers:
                return {"issue": n}, None
        return None, None
    if isinstance(cov, dict) and len(cov) == 1 and "spec" in cov:
        want = str(cov["spec"]).strip()
        for s in specs:
            if want in (str(s.get("number")), str(s.get("id"))):
                return {"spec": s["number"]}, None
        return None, f"spec {want} does not exist or is done"
    if isinstance(cov, dict) and len(cov) == 1 and "issue" in cov:
        n = cov["issue"]
        if isinstance(n, int) and not isinstance(n, bool) and n in open_numbers:
            return {"issue": n}, None
        return None, f"#{n} is not an open issue"
    return None, "invalid covers"


def _title(p, key: str = "title") -> str:
    return str(p.get(key)) if isinstance(p, dict) and isinstance(p.get(key), str) else "?"


def validate(data: dict, report: dict) -> Checked:
    index = report.get("evidence") or {}
    before = retro_report.previous_index(report)
    out = Checked()
    specs = data.get("specs") if isinstance(data.get("specs"), list) else []
    for i, p in enumerate(specs, 1):
        def refuse(why, p=p, i=i):
            out.refused.append(f'refused spec proposal {i} "{_title(p)}": {why}')
        if not isinstance(p, dict):
            refuse("invalid (not an object)")
            continue
        bad = _format_problem(p)
        if bad:
            refuse(bad)
            continue
        evidence = _matching(p.get("evidence"), index)
        if not evidence:
            refuse("no evidence from this report")
            continue
        covers, why = _covers(p, evidence, report)
        if why:
            refuse(why)
            continue
        if len(out.specs) >= MAX_SPECS:
            refuse(f"over the limit of {MAX_SPECS} proposed specs")
            continue
        out.specs.append({"rank": len(out.specs) + 1, "title": p["title"].strip(), "problem": p["problem"].strip(),
                          "priority": p["priority"], "spec_line": p["spec_line"].strip(), "evidence": evidence, "covers": covers,
                          "previous": {it["ref"]: before.get(it["ref"]) for it in evidence}})
    rows = {(r["agent"], r["shape"]) for r in (report.get("agents") or {}).get("rows", [])}
    prompts = data.get("prompts") if isinstance(data.get("prompts"), list) else []
    for i, p in enumerate(prompts, 1):
        label = f"{_title(p, 'agent')} {_title(p, 'shape')}"

        def refuse(why, label=label, i=i):
            out.refused.append(f'refused prompt proposal {i} "{label}": {why}')
        if not isinstance(p, dict):
            refuse("invalid (not an object)")
            continue
        if (p.get("agent"), p.get("shape")) not in rows:
            refuse("no such agent and shape in this report")
            continue
        metrics = _matching(p.get("metrics"), index, f"agents.{p['agent']}|{p['shape']}|")
        if not metrics:
            refuse("no evidence from this report")
            continue
        if not isinstance(p.get("change"), str) or not p["change"].strip():
            refuse("invalid change (empty)")
            continue
        if len(out.prompts) >= MAX_PROMPTS:
            refuse(f"over the limit of {MAX_PROMPTS} prompt proposals")
            continue
        out.prompts.append({"agent": p["agent"], "shape": p["shape"], "metrics": metrics, "change": p["change"].strip(),
                            "previous": {m["ref"]: before.get(m["ref"]) for m in metrics}})
    return out


# ---------------- rendering ----------------

def _value(v) -> str:
    return f"{v:.2f}" if isinstance(v, float) else str(v)


def _evidence_text(p: dict) -> str:
    parts = []
    for it in p["evidence"]:
        ref, v = it["ref"], it["value"]
        m = _ISSUE_REF.match(ref)
        if m:
            parts.append(f"#{m.group(1)} ({_value(v)} this week)")
            continue
        prev = (p.get("previous") or {}).get(ref)
        parts.append(f"`{ref}` = {_value(v)}" + (f" (prev {_value(prev)})" if prev is not None else ""))
    return ", ".join(parts)


def _metric_text(p: dict) -> str:
    parts = []
    for m in p["metrics"]:
        ref, v = m["ref"], m["value"]
        label = ref.split("|", 2)[-1].partition(".")[2] or ref
        prev = (p.get("previous") or {}).get(ref)
        text = f"`{label}` = {_value(v)}"
        if prev is not None:
            diff = v - prev
            text += f" (prev {_value(prev)}, {diff:+.2f})"
        parts.append(text)
    return ", ".join(parts)


def render_public_section(checked: Checked) -> str:
    lines = ["## Proposed specs"]
    for p in checked.specs:
        cov = p.get("covers")
        tail = f" — amends spec {cov['spec']}" if cov and "spec" in cov else f" — see #{cov['issue']}" if cov else ""
        lines += [f"{p['rank']}. **{p['title']}** ({p['priority']}){tail}", f"   {p['problem']}",
                  f"   Evidence: {_evidence_text(p)}", f"   `/component:spec {p['spec_line']}`"]
    if not checked.specs:
        lines.append("none")
    lines.append("## Agent prompt proposals")
    for p in checked.prompts:
        lines += [f"- **{p['agent']}** on {p['shape']}: {p['change']}", f"  Metrics: {_metric_text(p)}"]
    if not checked.prompts:
        lines.append("none")
    if checked.refused:
        lines.append(f"{len(checked.refused)} proposal(s) refused (no evidence from this report, invalid, or over the limit)")
    return "\n".join(lines) + "\n"


def render_private_section(checked: Checked) -> str:
    return render_public_section(checked) + "".join(f"{line}\n" for line in checked.refused)


def prompt(report_dir: Path) -> str:
    week = "unknown"
    try:
        week = str(json.loads((Path(report_dir) / "report.json").read_text(encoding="utf-8")).get("week") or week)
    except (OSError, ValueError, AttributeError):
        pass
    text = PROMPT_ASSET.read_text(encoding="utf-8")
    for key, value in (("{dir}", str(report_dir)), ("{week}", week), ("{max_specs}", str(MAX_SPECS)),
                       ("{max_prompts}", str(MAX_PROMPTS))):
        text = text.replace(key, value)
    return text

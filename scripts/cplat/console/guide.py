"""The guide inside the console (spec 122, AC-122.52): the documentation where the developer works.

  page(ctx, query) -> str            GET /guide: docs/console.md with its screenshots, the stages and the command reference
  image(name) -> (bytes, type)       GET /guide-img/<name>: a screenshot of docs/img/console/, allowlisted by the folder
  anchor(place) -> str               the guide section of a place, for the "Full guide" link of its help

Everything is read from the platform checkout the console runs from (the repo root above scripts/cplat), so the console,
the documentation site (which syncs the same docs/console.md) and the commands never disagree. The Markdown renderer
covers what the guide uses and escapes every text."""
from __future__ import annotations

import html as _html
import re
from pathlib import Path
from typing import Any

import stages
from console.html import command_block, esc, stage_badge

ROOT = Path(__file__).resolve().parents[3]
GUIDE = ROOT / "docs" / "console.md"
IMAGES = ROOT / "docs" / "img" / "console"
SITE = "https://ika100.github.io/sdlc-foundry/guides/console/"
REPO_DOCS = "https://github.com/ika100/sdlc-foundry/blob/main/docs/"
NOUNS = ("system", "component", "api", "resource", "instance", "issue", "platform")
IMAGE_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".svg": "image/svg+xml"}
PLACE_SECTIONS = {"inbox": "Inbox", "board": "Board", "system": "System"}


# ---------------- Markdown (the subset the guide uses) ----------------

def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _href(target: str) -> str:
    if target.startswith(("http://", "https://", "#")):
        return target
    if target.startswith("img/console/"):
        return "/guide-img/" + target[len("img/console/"):]
    return REPO_DOCS + target  # a link to another doc opens it on GitHub


def inline(text: str) -> str:
    """Escaped inline Markdown: `code`, **bold**, ![alt](src) and [text](url)."""
    codes: list[str] = []

    def keep(m: re.Match) -> str:
        codes.append(f"<code>{esc(m.group(1))}</code>")
        return f"\x00{len(codes) - 1}\x00"

    out = re.sub(r"`([^`]+)`", keep, text)
    out = _html.escape(out, quote=True)
    out = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", out)
    out = re.sub(r"!\[([^\]]*)\]\(([^)\s]+)\)",
                 lambda m: f'<img src="{_href(_html.unescape(m.group(2)))}" alt="{m.group(1)}">', out)

    def link(m: re.Match) -> str:
        href = _href(_html.unescape(m.group(2)))
        ext = ' target="_blank" rel="noopener noreferrer"' if href.startswith("http") else ""
        return f'<a href="{_html.escape(href, quote=True)}"{ext}>{m.group(1)}</a>'

    out = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", link, out)
    return re.sub("\x00(\\d+)\x00", lambda m: codes[int(m.group(1))], out)


def _table(rows: list[str]) -> str:
    cells = [[c.strip() for c in r.strip().strip("|").split("|")] for r in rows]
    head, body = cells[0], [r for r in cells[1:] if not all(re.fullmatch(r":?-+:?", c or "-") for c in r)]
    th = "".join(f"<th>{inline(c)}</th>" for c in head)
    trs = "".join("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>" for r in body)
    return f'<div class="scroll-x"><table><thead><tr>{th}</tr></thead><tbody>{trs}</tbody></table></div>'


def render(md: str) -> tuple[str, list[tuple[int, str, str]]]:
    """HTML of a Markdown text and its table of contents `[(level, anchor, title)]` of the ## and ### headings."""
    lines, out, toc, i = md.splitlines(), [], [], 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("```"):
            j = i + 1
            while j < len(lines) and not lines[j].startswith("```"):
                j += 1
            code = "\n".join(lines[i + 1:j])
            out.append(command_block(code) if "\n" not in code.strip() else f"<pre><code>{esc(code)}</code></pre>")
            i = j + 1
        elif m := re.match(r"^(#{1,3}) (.+)$", line):
            level, title = len(m.group(1)), m.group(2).strip()
            if level == 1:  # the page title is the console's own heading
                i += 1
                continue
            anchor = slug(title)
            toc.append((level, anchor, title))
            out.append(f'<h{level} id="{anchor}">{inline(title)}</h{level}>')
            i += 1
        elif line.startswith("|"):
            j = i
            while j < len(lines) and lines[j].startswith("|"):
                j += 1
            out.append(_table(lines[i:j]))
            i = j
        elif re.match(r"^(- |\d+\. )", line):
            ordered = bool(re.match(r"^\d+\. ", line))
            items: list[list[str]] = []
            while i < len(lines) and (re.match(r"^(- |\d+\. )", lines[i]) or lines[i].startswith("   ") or
                                      (lines[i] == "" and i + 1 < len(lines) and lines[i + 1].startswith("   "))):
                if re.match(r"^(- |\d+\. )", lines[i]):
                    items.append([re.sub(r"^(- |\d+\. )", "", lines[i])])
                else:
                    items[-1].append(lines[i][3:] if lines[i].startswith("   ") else "")
                i += 1
            tag = "ol" if ordered else "ul"
            lis = "".join(f"<li>{_item(it)}</li>" for it in items)
            out.append(f"<{tag}>{lis}</{tag}>")
        elif re.match(r"^!\[[^\]]*\]\([^)]+\)\s*$", line):
            out.append(f"<figure>{inline(line.strip())}</figure>")
            i += 1
        elif line.strip():
            j = i
            while j < len(lines) and lines[j].strip() and not re.match(r"^(#|```|\||- |\d+\. |!\[)", lines[j]):
                j += 1
            out.append(f"<p>{inline(' '.join(lines[i:max(j, i + 1)]))}</p>")
            i = max(j, i + 1)
        else:
            i += 1
    return "\n".join(out), toc


def _item(parts: list[str]) -> str:
    first, rest = parts[0], "\n".join(parts[1:]).strip("\n")
    return inline(first) + (render(rest)[0] if rest else "")


# ---------------- the guide's own sections ----------------

def _stages_section() -> str:
    items = []
    for name in stages.STAGES:
        e = stages.explain(name)
        agents = esc(", ".join(e["agents"]) or "no agent: the platform script, CI and Argo CD")
        commands = " ".join(f"<code>{esc(c)}</code>" for c in e["commands"])
        decide = f'<p class="decide"><strong>You decide:</strong> {esc(e["decision"])}</p>' if e["decision"] else ""
        items.append(f'<li class="guide-stage"><p>{stage_badge(name)} {esc(e["what"])}</p>'
                     f'<p class="muted">Who works: {agents} · Commands: {commands}</p>{decide}</li>')
    return ('<h2 id="the-process">The process</h2><p>Every change goes through these stages. The Board has one column per stage; '
            f'the Inbox collects the three where you decide.</p><ul class="plain guide-stages">{"".join(items)}</ul>')


def _description(path: Path) -> str:
    m = re.search(r'^description:\s*"((?:[^"\\]|\\.)*)"\s*$', path.read_text(), re.M)
    return m.group(1).replace('\\"', '"') if m else ""


def commands() -> list[dict]:
    """Every slash command of the 5.x nouns: `{noun, command, what, usage}`, sorted by noun and name."""
    found = []
    for noun in NOUNS:
        for path in sorted((ROOT / "plugins" / noun / "commands").glob("*.md")):
            desc = _description(path)
            what, _, usage = desc.partition("Usage:")
            found.append({"noun": noun, "command": f"/{noun}:{path.stem}", "what": what.strip(), "usage": usage.strip()})
    return found


def _commands_section() -> str:
    parts = ['<h2 id="command-reference">Command reference</h2><p>Every action of the console is one of these commands; '
             "you can also run them in Claude Code. Each line shows what the command does and how to call it.</p>"]
    for noun in NOUNS:
        rows = [c for c in commands() if c["noun"] == noun]
        if not rows:
            continue
        items = "".join(f'<li class="guide-cmd"><p><code>{esc(c["command"])}</code> {esc(c["what"])}</p>'
                        f'{command_block(c["usage"]) if c["usage"] else ""}</li>' for c in rows)
        parts.append(f'<h3 id="commands-{noun}">{esc(noun)}</h3><ul class="plain guide-commands">{items}</ul>')
    return "".join(parts)


def anchor(place: str) -> str:
    """The guide section of a place (`#inbox-what-needs-your-decision`), or the top."""
    word = PLACE_SECTIONS.get(place)
    if word and GUIDE.is_file():
        for line in GUIDE.read_text().splitlines():
            if line.startswith("### " + word):
                return "#" + slug(line[4:])
    return ""


def page(ctx: Any, query: dict[str, str]) -> str:
    from console import layout  # noqa: PLC0415 - the shell imports the views lazily too

    if GUIDE.is_file():
        body, toc = render(GUIDE.read_text())
    else:
        body, toc = (f'<p>The guide is not in this platform checkout ({esc(str(GUIDE))}). Read it on the '
                     f'<a href="{SITE}" target="_blank" rel="noopener noreferrer">documentation site</a>.</p>'), []
    toc += [(2, "the-process", "The process"), (2, "command-reference", "Command reference")]
    links = "".join(f'<li class="toc-{lvl}"><a href="#{a}">{esc(t)}</a></li>' for lvl, a, t in toc)
    content = (f'<div class="guide"><nav class="guide-toc" aria-label="Guide contents"><ul class="plain">{links}</ul>'
               f'<p class="muted">Also on the <a href="{SITE}" target="_blank" rel="noopener noreferrer">documentation site</a>.</p></nav>'
               f'<article class="guide-body">{body}{_stages_section()}{_commands_section()}</article></div>')
    return layout.page("Guide", "system", content, state=ctx.state())


def image(name: str) -> tuple[bytes, str]:
    """A screenshot by its file name; the path is built from the folder's own entry, never from the request."""
    if IMAGES.is_dir():
        for entry in IMAGES.iterdir():
            if entry.name == name and entry.suffix.lower() in IMAGE_TYPES and entry.is_file():
                return entry.read_bytes(), IMAGE_TYPES[entry.suffix.lower()]
    raise LookupError(f"no image {name!r}")

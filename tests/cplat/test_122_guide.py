"""Spec 122, AC-122.52: the guide is in the console: docs/console.md with screenshots, the stages and every command."""
import re

import stages
from console import guide, help as help_text
from console_support import q


def test_the_guide_page_shows_the_console_guide_with_its_screenshots_and_contents_ac_122_52(console):
    """AC-122.52 the content of docs/console.md, its screenshots served by the console, and a table of contents."""
    c = console()
    root, text = c.page("/guide")
    for line in guide.GUIDE.read_text().splitlines():
        if line.startswith("## "):
            assert f'id="{guide.slug(line[3:])}"' in text, line
    srcs = [i.attrs["src"] for i in q(root, "img")]
    assert srcs and all(s.startswith("/guide-img/") for s in srcs)
    for src in srcs:
        st, raw = c.request("GET", src)[0], c.request("GET", src)[2]
        assert st == 200 and len(raw) > 1000, src
    assert q(root, "nav", aria_label="Guide contents")


def test_the_guide_shows_every_stage_and_every_command_with_its_usage_ac_122_52(console):
    """AC-122.52 the eight stages from stages.py and a command reference of the 5.x nouns with copy buttons."""
    _, text = console().page("/guide")
    for name in stages.STAGES:
        assert f'data-stage="{name}"' in text and stages.explain(name)["what"].split(".")[0].replace("'", "&#x27;") in text
    cmds = guide.commands()
    assert {"/component:spec", "/system:set", "/platform:ui", "/instance:promote"} <= {c["command"] for c in cmds}
    for c in cmds:
        assert c["command"] in text and c["noun"] in guide.NOUNS
    assert text.count("data-copy") >= len([c for c in cmds if c["usage"]])


def test_the_guide_is_reached_from_the_menu_the_key_and_each_help_ac_122_52(console):
    """AC-122.52 Menu → Guide, the key g, and a Full guide link from a page's help to its section."""
    c = console()
    root, _ = c.page("/inbox")
    assert q(root, "a", href="/guide")
    js = (guide.ROOT / "scripts/cplat/console/static/console.js").read_text()
    assert re.search(r'key === "g"', js)
    _, text = c.panel("help", "board")
    assert f'href="/guide{guide.anchor("board")}"' in text and guide.anchor("board").startswith("#board")


def test_without_the_guide_file_it_says_so_and_links_the_site_ac_122_52(console, monkeypatch, tmp_path):
    """AC-122.52 a checkout without docs/console.md names the missing file and links the documentation site."""
    monkeypatch.setattr(guide, "GUIDE", tmp_path / "missing.md")
    _, text = console().page("/guide")
    assert guide.SITE in text and "not in this platform checkout" in text


def test_an_image_outside_the_screenshot_folder_is_404_ac_122_52(console):
    """AC-122.52 images are served only from docs/img/console by their own names."""
    c = console()
    for bad in ("../console.md", "..%2Fconsole.md", "nope.jpg"):
        assert c.request("GET", f"/guide-img/{bad}")[0] == 404, bad


def test_the_renderer_escapes_text_ac_122_52():
    """AC-122.52 the Markdown renderer escapes every text it shows."""
    out, _ = guide.render('A <script>alert(1)</script> and `<b>` and [x](javascript:alert(1))\n')
    assert "<script>" not in out and "&lt;b&gt;" in out
    assert help_text.KEYS and any(k == "g" for k, _ in help_text.KEYS)


def test_link_and_image_targets_cannot_break_out_of_their_attribute_ac_122_52():
    """AC-122.52 a quote in a link or image target stays inside the attribute; javascript: never becomes an href."""
    out, _ = guide.render('![a](https://a"onerror="alert(1)) [b](JavaScript:alert(1))\n')
    assert 'onerror="' not in out and 'href="javascript' not in out.lower()

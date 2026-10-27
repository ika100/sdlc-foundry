"""Spec 122 acceptance tests: the browser side, tested statically (AC-122.28, AC-122.37, AC-122.38, AC-122.43).

Contract: design.md "Markup contract". Browser-only behaviour (keymap, contrast, 390 px) is checked against `console.js`,
`console.css` and the markup the server renders; no browser is started."""
import re

import pytest

from console_support import STATIC, parse, q, row_of

JS = STATIC / "console.js"
CSS = STATIC / "console.css"


def js():
    return JS.read_text()


def css():
    return CSS.read_text()


# ---------------- AC-122.38: the keymap ----------------

def test_command_k_and_control_k_open_the_palette_ac_122_38():  # AC-122.38
    t = js()
    assert re.search(r"metaKey", t) and re.search(r"ctrlKey", t) and re.search(r"""["']k["']""", t)
    assert "palette" in t


@pytest.mark.parametrize("key", ["j", "k", "a", "p", "t", "o"])
def test_every_single_key_shortcut_is_handled_ac_122_38(key):  # AC-122.38
    assert re.search(rf"""["']{key}["']""", js()), key


@pytest.mark.parametrize("key", ["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Enter", "Escape"])
def test_the_navigation_keys_are_handled_ac_122_38(key):  # AC-122.38
    assert key in js()


def test_single_keys_are_ignored_while_a_text_field_has_focus_ac_122_38():  # AC-122.38
    t = js()
    for guard in ("INPUT", "TEXTAREA", "SELECT"):
        assert guard in t, guard
    assert re.search(r"isContentEditable|contenteditable", t, re.I)


def test_the_decision_keys_click_the_matching_data_action_ac_122_38():  # AC-122.38
    t = js()
    assert "data-action" in t and "click()" in t
    for kind in ("approve", "promote", "take-over", "open-in-claude"):
        assert kind in t, kind


def test_the_script_talks_to_the_server_with_the_token_ac_122_3():  # AC-122.3
    t = js()
    assert "X-Console-Token" in t and "console-token" in t
    for route in ("/api/state", "/api/actions", "/panel/", "/palette"):
        assert route in t, route
    assert not re.search(r"https?://", t)


def test_copy_buttons_copy_the_command_ac_122_37():  # AC-122.37
    t = js()
    assert "data-copy" in t and "data-command" in t and ("clipboard" in t)


def test_panels_return_focus_and_close_on_escape_ac_122_28():  # AC-122.28
    t = js()
    assert "focus()" in t and "Escape" in t and "data-panel" in t


# ---------------- AC-122.28: contrast, 390 px, keyboard ----------------

def luminance(hex_color):
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    rgb = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(a, b):
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def root_vars():
    block = re.search(r":root\s*\{(.*?)\}", css(), re.S)
    assert block, "no :root block"
    return dict(re.findall(r"(--[\w-]+)\s*:\s*(#[0-9a-fA-F]{3,6})\s*;", block.group(1)))


def header_pairs():
    header = re.match(r"\s*/\*(.*?)\*/", css(), re.S)
    assert header, "console.css starts with a header comment that lists the contrast pairs"
    return [(m.group(1), m.group(2), "large" in line.lower()) for line in header.group(1).splitlines()
            for m in [re.search(r"(--[\w-]+)\s+on\s+(--[\w-]+)", line)] if m]


def test_colours_are_custom_properties_on_root_only_ac_122_28():  # AC-122.28
    text = css()
    outside = re.sub(r":root\s*\{.*?\}", "", text, flags=re.S)
    outside = re.sub(r"/\*.*?\*/", "", outside, flags=re.S)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", outside)
    assert len(root_vars()) >= 6


def test_every_listed_text_and_background_pair_meets_wcag_aa_ac_122_28():  # AC-122.28
    pairs, vars_ = header_pairs(), root_vars()
    assert len(pairs) >= 4
    for fg, bg, large in pairs:
        assert fg in vars_ and bg in vars_, (fg, bg)
        assert contrast(vars_[fg], vars_[bg]) >= (3.0 if large else 4.5), (fg, bg, contrast(vars_[fg], vars_[bg]))


def test_every_text_colour_in_use_is_in_a_listed_pair_ac_122_28():  # AC-122.28
    text = re.sub(r"/\*.*?\*/", "", css(), flags=re.S)
    used = set(re.findall(r"(?<![\w-])color\s*:\s*var\((--[\w-]+)\)", text))
    listed = {fg for fg, _, _ in header_pairs()}
    assert used and used <= listed, used - listed


def test_there_is_a_visible_focus_ring_ac_122_28():  # AC-122.28
    text = css()
    assert re.search(r":focus-visible\s*\{[^}]*outline", text, re.S)
    assert not re.search(r"outline\s*:\s*(none|0)\b", text)


def test_wide_tables_scroll_inside_their_box_ac_122_28():  # AC-122.28
    assert re.search(r"\.scroll-x\s*\{[^}]*overflow-x\s*:\s*auto", css(), re.S)


def test_below_600_px_the_sidebar_becomes_a_top_bar_ac_122_28():  # AC-122.28
    m = re.search(r"@media[^{]*max-width\s*:\s*600px[^{]*\{(.*)", css(), re.S)
    assert m and "nav" in m.group(1)
    assert not re.search(r"(^|[;{\s])(width|min-width)\s*:\s*(?:[4-9]\d\d|\d{4,})px", re.sub(r"@media.*", "", css(), flags=re.S))


@pytest.mark.parametrize("path", ["/inbox", "/board", "/board?view=list", "/system"])
def test_every_page_has_the_viewport_meta_and_a_landmark_structure_ac_122_28(console, path):  # AC-122.28
    root, _ = console().page(path)
    [meta] = q(root, "meta", name="viewport")
    assert meta.attrs["content"] == "width=device-width, initial-scale=1"
    assert q(root, "html", lang=True) and q(root, "main") and q(root, "nav", aria_label="Places")


@pytest.mark.parametrize("path", ["/inbox", "/board", "/board?view=list", "/system"])
def test_every_table_sits_in_a_scroll_box_ac_122_28(console, path):  # AC-122.28
    root, _ = console().page(path)
    tables = q(root, "table")
    assert tables
    for t in tables:
        assert any("scroll-x" in a.attrs.get("class", "").split() for a in t.ancestors()), path


@pytest.mark.parametrize("path", ["/inbox", "/board", "/system"])
def test_everything_clickable_is_natively_focusable_ac_122_28(console, path):  # AC-122.28
    root, _ = console().page(path)
    for n in root.walk():
        if "onclick" in n.attrs:
            assert n.tag in {"button", "a", "input", "summary"}, (n.tag, n.attrs)
        if "tabindex" in n.attrs:
            assert int(n.attrs["tabindex"]) <= 0, n.attrs
        if n.tag == "img":
            assert "alt" in n.attrs
        if n.tag in {"input", "textarea", "select"} and n.attrs.get("type") not in {"hidden", "submit", "button"}:
            has_label = "aria-label" in n.attrs or "aria-labelledby" in n.attrs or "id" in n.attrs or any(a.tag == "label" for a in n.ancestors())
            assert has_label, n.attrs


def test_buttons_have_a_text_or_a_label_ac_122_28(console):  # AC-122.28
    root, _ = console().page("/inbox")
    for b in q(root, "button"):
        assert b.text() or b.attrs.get("aria-label"), b.attrs


# ---------------- AC-122.43 / AC-122.44: freshness and the activity indicator are on every page ----------------

@pytest.mark.parametrize("path", ["/inbox", "/board", "/board?view=done", "/system"])
def test_every_page_has_the_freshness_stamp_and_the_activity_indicator_ac_122_43(console, path):  # AC-122.43
    root, _ = console().page(path)
    assert q(root, "time", data_read_at=True)
    [ind] = q(root, "button", data_activity=True)
    assert ind.attrs["data-running"] == "0" and ind.attrs["data-failed"] == "0"

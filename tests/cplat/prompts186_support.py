"""Spec 186: shared helpers of the prompt and register tests (not a test module).

A prompt rule of spec 186 is tested by structure, as spec 168 asks: the prompt names the `cplat` command, and its register file
`docs/rules/<prompt path without .md>.yml` holds an entry of the right class and source whose `text` quotes the prompt. No sentence is pinned.
"""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CLASSES = {"practice", "experience"}


def prompt(path: str) -> str:
    return (ROOT / path).read_text()


def collapsed(text: str) -> str:
    return " ".join(text.split())


def entries(path: str) -> list[dict]:
    register = ROOT / "docs" / "rules" / (path[: -len(".md")] + ".yml")
    return (yaml.safe_load(register.read_text()) or {}).get("rules") or [] if register.is_file() else []


def sourced(path: str, source: str) -> list[dict]:
    """The practice or experience entries of the prompt's register file with this `source` whose text quotes the prompt."""
    body = collapsed(prompt(path))
    return [e for e in entries(path) if str(e.get("source")) == source and e.get("class") in CLASSES
            and collapsed(str(e.get("text"))) in body]

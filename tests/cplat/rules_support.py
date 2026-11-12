"""Spec 168: shared builders of the rule-register tests (not a test module).

`good_repo(root)` writes a small platform tree that passes `cplat platform rules check`: one command prompt with the statement,
two practices (one an experience) and one hard rule, its register files, and the workflows the enforcement check reads.
The tests change one thing and look at the failures of exactly that thing. Register files are written by `entries()` and
`register()` as plain text, so the line numbers the check reports are predictable (`line_of`)."""
import importlib
import json
from pathlib import Path

# The statement of AC-168.5, verbatim from the contract (design.md, `STATEMENT`).
# interface: the statement promptrules checks verbatim
STATEMENT = ("A rule marked **Hard rule:** is never departed from. Any other rule is a practice: where its stated "
             "purpose does not apply, depart from it and name each departure and its reason in one line of your report.")
MARKER = "**Hard rule:**"

PROMPT = "plugins/svc/commands/demo.md"
ENTRIES = "docs/rules/plugins/svc/commands/demo.yml"
REGISTER = "docs/rules/register.yml"

R1 = "Always run the tests first, because a red suite hides every later failure."
R2 = "Never skip the lint step, since the CI lint job refuses it otherwise."
# interface: the hard rule marker sentence the check detects
R3 = "**Hard rule:** never file an issue without the user's OK, because the platform repository is public."
GOOD_BODY = f"{R1}\n\n- {R2}\n\n{R3}\n"
PROSE = "consent exists only in the user's own words, which no tool can see"
HARD = {"issue-filing-needs-consent": {"intentional_prose_rule": PROSE, "source": "ADR-033"}}


class Lazy:
    """A module imported on first use, so a missing module fails the test that needs it, not the collection."""

    def __init__(self, name):
        self._name = name

    def __getattr__(self, attr):
        return getattr(importlib.import_module(self._name), attr)


rulescheck = Lazy("rulescheck")
promptrules = Lazy("promptrules")


def e(id, text, cls="practice", **kw):
    """One register entry; any extra key is written as given (the bad-entry tests need keys the schema does not know)."""
    return {"id": id, "text": text, "class": cls, **kw}


GOOD_ENTRIES = [e("R1", "Always run the tests first", "practice", source="#476"),
                e("R2", "Never skip the lint step", "experience", source="#478"),
                e("R3", "never file an issue without the user's OK", "hard", hard="issue-filing-needs-consent")]


def _scalar(key, value):
    if key in ("retired", "id") or isinstance(value, (int, float)):
        return str(value)                      # an ISO date is written bare, as a YAML date
    return json.dumps(value, ensure_ascii=False)


def entries_text(items):
    out = ["rules:"]
    for item in items:
        keys = list(item)
        for i, key in enumerate(keys):
            out.append(f"  - {key}: {_scalar(key, item[key])}" if i == 0 else f"    {key}: {_scalar(key, item[key])}")
    return "\n".join(out) + "\n"


def register_text(hard, baseline_bytes):
    out = ["schema: 1", "baseline:", "  commit: abc1234", f"  prompt_bytes: {baseline_bytes}"]
    if not hard:
        out.append("hard: {}")
    else:
        out.append("hard:")
        for key, fields in hard.items():
            out.append(f"  {key}:")
            out += [f"    {k}: {json.dumps(v)}" for k, v in fields.items()]
    return "\n".join(out) + "\n"


def put(root, rel, text):
    p = Path(root) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def prompt_text(body, *, statement=True):
    head = "---\ndescription: Demo\n---\nYou are the demo.\n\n"
    return head + (STATEMENT + "\n\n" if statement else "") + body


def entries_path(prompt_rel):
    return "docs/rules/" + prompt_rel.removesuffix(".md") + ".yml"


def add_prompt(root, rel, body, items=None, *, statement=True):
    """A prompt and its register file (none when `items` is empty or None)."""
    put(root, rel, prompt_text(body, statement=statement))
    if items:
        put(root, entries_path(rel), entries_text(items))


def good_repo(root, body=GOOD_BODY, items=None, hard=HARD, baseline_bytes=10_000_000):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    add_prompt(root, PROMPT, body, GOOD_ENTRIES if items is None else items)
    put(root, REGISTER, register_text(hard, baseline_bytes))
    put(root, "docs/a/b/c.md", "# Guide\n")      # the link target some fixture reasons point to
    put(root, ".github/workflows/ci.yml",
        "name: ci\njobs:\n  security:\n    name: security\n    runs-on: ubuntu-latest\n  dco:\n    name: DCO sign-off\n    runs-on: ubuntu-latest\n")
    put(root, "templates/service-python/.github/workflows/ci.yml.jinja",
        "name: ci\njobs:\n  tmpl-build:\n    name: \"${{ '{{' }} project_name {{ '}}' }} build\"\n    runs-on: ubuntu-latest\n")
    return root


def line_of(root, rel, needle):
    for n, line in enumerate((Path(root) / rel).read_text(encoding="utf-8").splitlines(), 1):
        if needle in line:
            return n
    raise AssertionError(f"{needle!r} not in {rel}")


def fv(failure, key):
    """A failure field, whether the check returns objects or dicts."""
    return failure[key] if isinstance(failure, dict) else getattr(failure, key)


def kinds(result):
    return sorted(fv(f, "kind") for f in result.failures)


def of_kind(result, kind):
    return [f for f in result.failures if fv(f, "kind") == kind]


def check(root, only=None):
    return rulescheck.check(Path(root), only=only)

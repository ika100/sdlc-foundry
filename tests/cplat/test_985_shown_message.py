"""#985: plan-check refuses a web consumer's decision to hold the provider's error message back from the field, because the
generated contract test (templates/web-nextjs/lib/contract/engine.ts, `responseCase`, AC-110.7) expects that message there.
The decision is prose (a spec assumption, the contract text, the repo's notes); plans are built by support_110."""
import pytest
from support_110 import PLAN_ID, SPEC, contract_text, error_lines, plan_text, validate, world

# Journey 26, assumption A8 as the product-manager wrote it, and the contract line the planner derived from it.
A8_J26 = ("- **A8** The board checks the title before sending (trimmed, 1 to 200 characters) and shows the API's rejections with "
          "its own fixed English messages (other option: show the API's `detail` text verbatim; affects AC-003.2).")
RULES_LINE_J26 = "- The board shows its own fixed English messages, never the API's `detail` text (system A8).\n"


@pytest.fixture()
def root(tmp_path):
    return world(tmp_path)


def _spec(root, *assumptions: str) -> None:
    text = SPEC.replace("## Changelog", "## Assumptions\n\n" + "\n".join(assumptions) + "\n\n## Changelog")
    (root / "docs" / "specs" / PLAN_ID / "spec.md").write_text(text)


def _with_prose(after: str, line: str) -> str:
    """The plan whose contract has `line` as prose after the heading `after` (its yaml block stays first)."""
    text = contract_text()
    head = f"### {after}\n\n"
    start = text.index(head) + len(head)
    end = text.index("```\n", text.index("```yaml", start)) + 4
    return plan_text(text[:end] + "\n" + line + text[end:])


def _shown(proc) -> list[str]:
    return [ln for ln in error_lines(proc) if "(#985)" in ln]


def test_the_journey_26_assumption_is_refused_naming_it_the_rules_and_the_test(root):
    _spec(root, A8_J26)
    proc = validate(root, plan_text())
    assert proc.returncode == 1, proc.stderr
    [line] = _shown(proc)
    assert "repo todo-web: assumption A8 of docs/specs/003-todos/spec.md" in line
    assert "The board checks the title before sending" in line and "(other option" not in line   # the clause, quoted
    assert "rule status-values, title-max, title-required" in line
    assert "lib/contract/engine.ts" in line and "AC-110.7" in line and "`422`" in line
    assert "show the provider's `message` at the field" in line and "or change the contract" in line


def test_the_contract_line_that_hides_the_api_detail_is_refused(root):
    proc = validate(root, _with_prose("Rules", RULES_LINE_J26))
    assert proc.returncode == 1, proc.stderr
    [line] = _shown(proc)
    assert "the contract (`## Contract`)" in line and "never the API's `detail` text" in line


def test_a_message_key_kept_for_logs_only_is_refused(root):
    proc = validate(root, _with_prose("Errors", "Each entry's `message` is a text for logs only.\n"))
    assert proc.returncode == 1, proc.stderr
    assert len(_shown(proc)) == 1 and "for logs only" in _shown(proc)[0]


def test_the_repo_arguments_are_read_too(root):
    text = plan_text().replace(
        "acs: [AC-003.2], depends_on: []",
        "acs: [AC-003.2], arguments: 'Map every 422 to our own wording instead of the API message.', depends_on: []")
    proc = validate(root, text)
    assert proc.returncode == 1 and "its `arguments`" in _shown(proc)[0], proc.stderr


@pytest.mark.parametrize("assumption", [
    # the revised A8 of journey 26: the API's text at the field, the board's own wording elsewhere
    "- **A8** The board shows \"Enter a title\" for what its own check catches; a `422` that names the `title` field shows the "
    "API's `message` next to \"Title\"; every other rejection keeps the board's fixed English messages (other option: fixed "
    "messages only, which the contract check does not accept; affects AC-003.2).",
    "- **A8** The form shows its own fixed messages, except that a `422` naming a field shows the API's `message` there "
    "(affects AC-003.2).",
    # unlisted answers follow `unlisted.message`, which is the board's own text by design
    "- **A8** For a status the contract does not list, the board shows its own fixed message instead of the API's text "
    "(affects AC-003.2).",
    "- **A8** When the API is unreachable or answers 503 the board shows a generic message, never the API's error text "
    "(affects AC-003.2).",
    # struck through, or about the provider's own criteria only
    "- ~~**A8** The board shows its own fixed messages, never the API's `detail` text (affects AC-003.2).~~",
    "- **A8** The API logs its own fixed messages, never the client's input text (affects AC-003.1).",
])
def test_assumptions_the_contract_test_passes_are_accepted(root, assumption):
    _spec(root, assumption)
    proc = validate(root, plan_text())
    assert proc.returncode == 0 and not error_lines(proc), proc.stderr


def test_a_consumer_without_the_generated_response_test_is_not_checked(root):
    _spec(root, A8_J26)
    proc = validate(root, plan_text().replace("shape: web-nextjs", "shape: service-python"))
    assert proc.returncode == 0, proc.stderr
    assert validate(root, plan_text()).returncode == 1   # the same plan with the web consumer is refused


@pytest.mark.parametrize("status", ["completed", "abandoned"])
def test_a_finished_plan_is_not_checked(root, status):
    _spec(root, A8_J26)
    proc = validate(root, plan_text(status=status))
    assert proc.returncode == 0 and "(#985)" not in proc.stdout + proc.stderr, proc.stdout + proc.stderr

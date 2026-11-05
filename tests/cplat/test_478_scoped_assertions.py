"""#478: two acceptance tests asserted that the page shows no list; the template's header navigation is a list, so the coder rebuilt
the header without one and screen readers lost it. Testers scope assertions to the feature's region; the reviewer flags changes to
template-owned layout that the spec does not ask for."""
import pytest

import core

PLUGINS = core.PLATFORM_ROOT / "plugins"


@pytest.mark.parametrize("plugin", ["svc", "svc-java", "svc-go", "web"])
def test_the_tester_scopes_acceptance_assertions_to_the_features_region(plugin):
    text = (PLUGINS / plugin / "agents/tester.md").read_text()
    accept = text[text.index("## Acceptance mode"):]
    assert "test id" in accept and "a landmark such as `main`" in accept and "never the whole page" in accept
    assert "header, footer and navigation" in accept and "the spec does not ask for" in accept


def test_the_web_tester_names_the_locators():
    text = (PLUGINS / "web/agents/tester.md").read_text()
    assert "data-testid" in text and "getByRole('main')" in text


def test_the_reviewer_flags_template_owned_layout_the_spec_does_not_ask_for():
    text = (PLUGINS / "svc/agents/reviewer.md").read_text()
    step = text[text.index("4. Non-goals"):text.index("5. Plan")]
    assert "template-owned layout" in step and "header, footer, navigation" in step and "the spec does not ask for" in step
    assert "not acceptable" in step


def test_the_changelog_fragment_exists():
    import release_support
    _, text = release_support.entry(r"\(#478\)")      # a fragment until the release moves it into its section (#321)
    assert "region" in text

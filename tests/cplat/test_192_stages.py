"""Spec 192 acceptance tests: the process bar vocabulary shared by the terminal and the console (AC-192.2)."""
import importlib

import pytest

import stages

PLATFORM_BAR = ("Issue", "Spec", "Build", "Release")
SERVICE_BAR = ("Issue", "Spec", "Build", "Dev", "Staging", "Prod")


@pytest.mark.parametrize("shape", ["platform", "library-python", "something-unknown"])
def test_bar_release_shapes(shape):  # AC-192.2
    assert tuple(stages.bar(shape)) == PLATFORM_BAR


@pytest.mark.parametrize("shape", ["service-python", "service-java", "service-go", "web-nextjs", "gitops-app"])
def test_bar_service_shapes(shape):  # AC-192.2
    assert tuple(stages.bar(shape)) == SERVICE_BAR


def test_bar_step_folds_plan_build_land_into_build():  # AC-192.2
    for stage in ("Plan", "Build", "Land"):
        assert stages.bar_step(stage, "service-python") == "Build"
        assert stages.bar_step(stage, "platform") == "Build"
    assert stages.bar_step("Issue", "platform") == "Issue"
    assert stages.bar_step("Spec", "platform") == "Spec"
    assert stages.bar_step("Prod", "service-python") == "Prod"
    assert stages.bar_step("Release", "platform") == "Release"


def test_every_bar_name_has_an_explanation():  # AC-192.2
    for name in PLATFORM_BAR + SERVICE_BAR:
        assert stages.explain(name)["what"]
    assert "release" in stages.explain("Release")["what"].lower()


def test_plain_terms_hold_texts_without_banned_words():  # AC-192.2
    assert set(stages.PLAIN) >= {"runs_on_its_own", "two_at_a_time", "needs_you"}
    for title, text in stages.PLAIN.values():
        assert title and text
        for word in ("dispatcher", "slot", "escalation", "escalated", "unit", "claim", "held"):
            assert word not in f"{title} {text}".lower().split()


def test_console_shows_the_same_texts():  # AC-192.2
    glossary = importlib.import_module("console.glossary")
    assert glossary.text("release")[1] == stages.explain("Release")["what"]
    for key, (title, text) in stages.PLAIN.items():
        assert glossary.text(key) == (title, text)
    in_sections = {k for _, _, _, keys in glossary.SECTIONS for k in keys}
    assert {"release", *stages.PLAIN} <= in_sections


def test_console_how_it_works_mentions_release():  # AC-192.2
    glossary = importlib.import_module("console.glossary")
    html = glossary._process()
    import html as htmllib
    assert htmllib.escape(stages.explain("Release")["what"].split(".")[0][:40]) in html

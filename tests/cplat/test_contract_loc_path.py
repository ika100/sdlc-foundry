"""A provider's error may name its field as a path (FastAPI's `loc: ["body", "title"]`); the check matches the path's end.

Seen in journey 23: a plan's contract with `field: loc` could never pass, since FastAPI never sends `loc` as a string."""
import pytest
from test_110_provider import PLAN, base, by_id, engine, failure, provider  # noqa: F401  (provider is a fixture)


def located(loc):
    def send(endpoint, body):
        if endpoint == "POST /todos" and len(body.get("title") or "") > 200:
            return 422, {"errors": [{"field": loc, "rule": "title-max", "message": "too long"}]}
        return 200, {}
    return send


@pytest.mark.parametrize("loc", ["title", ["body", "title"], ["title"]])
def test_a_field_named_by_a_path_ending_in_it_passes(provider, loc):  # noqa: F811
    mod = engine()
    mod.check_case(by_id(mod, provider)[f"{PLAN}:title-max:past-limit"], located(loc), base)


@pytest.mark.parametrize("loc", [["body", "status"], ["title", "body"], ["body"], []])
def test_a_path_ending_in_another_field_fails(provider, loc):  # noqa: F811
    mod = engine()
    case = by_id(mod, provider)[f"{PLAN}:title-max:past-limit"]
    assert "rule title-max field title" in failure(case, located(loc), mod)


def test_a_dotted_field_matches_the_last_parts_of_the_path():
    mod = engine()
    assert mod._names(["body", "address", "city"], "address.city")
    assert not mod._names(["body", "city"], "address.city")

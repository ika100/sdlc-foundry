import retro_report


def test_a_run_without_agent_shapes_reports_its_own_recorded_shape_1117():
    assert retro_report._shape_of({"shape": "service-python"}) == "service-python"
    assert retro_report._shape_of({"agents": [{"shape": "none"}], "shape": "none"}) == "unknown"
    assert retro_report._shape_of({"agents": [{"shape": "library-python"}], "shape": "x"}) == "library-python"

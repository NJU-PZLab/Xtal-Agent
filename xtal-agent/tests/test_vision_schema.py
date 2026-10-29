"""Tests for vision_schema. Implementation must make these pass WITHOUT
modifying the tests."""

import json

import pytest

from xtal_agent.vision_schema import (
    SCHEMA_VERSION,
    SpotExtent,
    VisionReport,
    load_vision_report,
)


def _valid_report_dict() -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "frames_examined": [1, 51, 101, 151],
        "per_frame_observations": [
            {
                "frame": 1,
                "spot_shape": "round",
                "ice_rings": False,
                "overloaded_spots": "few",
                "background": "normal",
                "notes": "",
            },
            {
                "frame": 51,
                "spot_shape": "round",
                "ice_rings": False,
                "overloaded_spots": "none",
                "background": "low",
                "notes": "",
            },
            {
                "frame": 101,
                "spot_shape": "streaky",
                "ice_rings": False,
                "overloaded_spots": "none",
                "background": "normal",
                "notes": "spots elongate after frame ~90",
            },
            {
                "frame": 151,
                "spot_shape": "streaky",
                "ice_rings": True,
                "overloaded_spots": "none",
                "background": "high",
                "notes": "",
            },
        ],
        "per_frame_spot_extent": [
            {
                "frame": 1,
                "spots_beyond_5A": True,
                "spots_beyond_3_5A": True,
                "spots_beyond_2_5A": True,
                "spots_beyond_2A": True,
                "spots_beyond_1_5A": False,
            },
            {
                "frame": 51,
                "spots_beyond_5A": True,
                "spots_beyond_3_5A": True,
                "spots_beyond_2_5A": True,
                "spots_beyond_2A": False,
                "spots_beyond_1_5A": False,
            },
            {
                "frame": 101,
                "spots_beyond_5A": True,
                "spots_beyond_3_5A": True,
                "spots_beyond_2_5A": False,
                "spots_beyond_2A": False,
                "spots_beyond_1_5A": False,
            },
            {
                "frame": 151,
                "spots_beyond_5A": True,
                "spots_beyond_3_5A": False,
                "spots_beyond_2_5A": False,
                "spots_beyond_2A": False,
                "spots_beyond_1_5A": False,
            },
        ],
        "estimated_resolution_A": 2.0,
        "recommended_spot_ranges": [[1, 60]],
        "quality_grade": "B",
        "caveats": "",
    }


def test_valid_report_loads(tmp_path):
    path = tmp_path / "vision_report.json"
    path.write_text(json.dumps(_valid_report_dict()))
    report = load_vision_report(path)
    assert report.quality_grade == "B"
    assert report.recommended_spot_ranges == [(1, 60)]


def test_missing_file_raises(tmp_path):
    with pytest.raises(ValueError, match="not found"):
        load_vision_report(tmp_path / "nope.json")


def test_invalid_json_raises(tmp_path):
    path = tmp_path / "vision_report.json"
    path.write_text("{not json")
    with pytest.raises(ValueError, match="not valid JSON"):
        load_vision_report(path)


def test_wrong_schema_version_rejected(tmp_path):
    data = _valid_report_dict()
    data["schema_version"] = "1.0"
    path = tmp_path / "vision_report.json"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="schema_version"):
        load_vision_report(path)


def test_non_monotonic_extent_rejected():
    with pytest.raises(ValueError, match="inconsistent extent"):
        SpotExtent(
            frame=1,
            spots_beyond_5A=False,   # cannot be beyond 3.5A but not 5A
            spots_beyond_3_5A=True,
            spots_beyond_2_5A=True,
            spots_beyond_2A=True,
            spots_beyond_1_5A=False,
        )


def test_extent_frame_outside_examined_rejected(tmp_path):
    data = _valid_report_dict()
    data["per_frame_spot_extent"][0]["frame"] = 999
    path = tmp_path / "vision_report.json"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="not in frames_examined"):
        load_vision_report(path)


def test_spot_range_outside_examined_span_rejected(tmp_path):
    data = _valid_report_dict()
    data["recommended_spot_ranges"] = [[1, 5000]]
    path = tmp_path / "vision_report.json"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="outside examined frame span"):
        load_vision_report(path)


def test_inverted_spot_range_rejected(tmp_path):
    data = _valid_report_dict()
    data["recommended_spot_ranges"] = [[60, 1]]
    path = tmp_path / "vision_report.json"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="inverted"):
        load_vision_report(path)


def test_report_has_no_twinning_fields(tmp_path):
    """Twinning is judged by xtriage, not by the vision module. A report
    containing twinning claims must be rejected (extra fields forbidden
    at this level of strictness is intentional)."""
    data = _valid_report_dict()
    data["twin_suspicion"] = "high"
    path = tmp_path / "vision_report.json"
    path.write_text(json.dumps(data))
    report = load_vision_report(path)
    # pydantic default ignores extra fields; the contract is that the schema
    # itself defines no twinning field, so downstream can never read one.
    assert not hasattr(report, "twin_suspicion")
    assert "twin" not in VisionReport.model_fields

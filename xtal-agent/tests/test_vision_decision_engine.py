"""Tests for the vision decision functions appended to decision_engine.py.
Implementation must make these pass WITHOUT modifying the tests."""

import pytest

from xtal_agent.decision_engine import (
    RadiationDamageLevel,
    ResolutionCurve,
    assess_radiation_damage,
    per_frame_resolution_curve,
    resolution_from_spot_extent,
    suggest_spot_range_from_vision,
)
from xtal_agent.vision_schema import (
    FrameObservation,
    SpotExtent,
    SpotShape,
    VisionReport,
)


def _extent(frame: int, crossed: int) -> SpotExtent:
    """Build a SpotExtent whose first `crossed` rings (5.0 -> 1.5) are True."""
    flags = [i < crossed for i in range(5)]
    return SpotExtent(
        frame=frame,
        spots_beyond_5A=flags[0],
        spots_beyond_3_5A=flags[1],
        spots_beyond_2_5A=flags[2],
        spots_beyond_2A=flags[3],
        spots_beyond_1_5A=flags[4],
    )


def _obs(frame: int, shape: SpotShape) -> FrameObservation:
    return FrameObservation(
        frame=frame,
        spot_shape=shape,
        ice_rings=False,
        overloaded_spots="none",
        background="normal",
    )


def _report(shapes: list[SpotShape], extents: list[int]) -> VisionReport:
    frames = [1 + i * 50 for i in range(len(shapes))]
    return VisionReport(
        schema_version="2.0",
        frames_examined=frames,
        per_frame_observations=[_obs(f, s) for f, s in zip(frames, shapes)],
        per_frame_spot_extent=[_extent(f, c) for f, c in zip(frames, extents)],
        recommended_spot_ranges=[],
        quality_grade="B",
    )


# --- resolution_from_spot_extent -------------------------------------------

def test_resolution_all_rings_crossed():
    assert resolution_from_spot_extent(_extent(1, 5)) == 1.5


def test_resolution_partial_crossing():
    assert resolution_from_spot_extent(_extent(1, 3)) == 2.5


def test_resolution_no_ring_crossed():
    assert resolution_from_spot_extent(_extent(1, 0)) == 5.0


# --- per_frame_resolution_curve ---------------------------------------------

def test_curve_aligns_frames_and_resolutions():
    report = _report(
        shapes=[SpotShape.ROUND] * 4,
        extents=[4, 3, 2, 1],
    )
    curve = per_frame_resolution_curve(report)
    assert curve.frames == [1, 51, 101, 151]
    assert curve.resolutions == [2.0, 2.5, 3.5, 5.0]


# --- assess_radiation_damage -------------------------------------------------

def test_damage_none_when_flat():
    curve = ResolutionCurve(frames=[1, 51, 101, 151, 201, 251],
                            resolutions=[2.0, 2.0, 2.0, 2.0, 2.0, 2.0])
    assert assess_radiation_damage(curve).level == RadiationDamageLevel.NONE


def test_damage_mild_on_small_degradation():
    curve = ResolutionCurve(frames=[1, 51, 101, 151, 201, 251],
                            resolutions=[2.0, 2.0, 2.0, 2.4, 2.5, 2.5])
    assert assess_radiation_damage(curve).level == RadiationDamageLevel.MILD


def test_damage_significant_on_large_degradation():
    curve = ResolutionCurve(frames=[1, 51, 101, 151, 201, 251],
                            resolutions=[2.0, 2.0, 2.0, 3.2, 3.5, 3.5])
    assessment = assess_radiation_damage(curve)
    assert assessment.level == RadiationDamageLevel.SIGNIFICANT
    assert assessment.degradation_A >= 0.8


def test_damage_not_assessed_with_too_few_frames():
    curve = ResolutionCurve(frames=[1, 2], resolutions=[2.0, 5.0])
    assert assess_radiation_damage(curve).level == RadiationDamageLevel.NONE


# --- suggest_spot_range_from_vision ------------------------------------------

def test_spot_range_picks_longest_good_run():
    report = _report(
        shapes=[SpotShape.STREAKY, SpotShape.ROUND, SpotShape.ROUND,
                SpotShape.ROUND, SpotShape.STREAKY, SpotShape.ROUND],
        extents=[3] * 6,
    )
    suggestion = suggest_spot_range_from_vision(report, "1 301")
    assert suggestion.preferred is True
    assert (suggestion.start_frame, suggestion.end_frame) == (51, 151)


def test_spot_range_fallback_when_no_good_frames():
    report = _report(shapes=[SpotShape.STREAKY] * 4, extents=[1] * 4)
    suggestion = suggest_spot_range_from_vision(report, "1 201")
    assert suggestion.preferred is False
    assert (suggestion.start_frame, suggestion.end_frame) == (1, 101)


def test_spot_range_fallback_when_only_isolated_good_frames():
    report = _report(
        shapes=[SpotShape.STREAKY, SpotShape.ROUND, SpotShape.STREAKY,
                SpotShape.ROUND, SpotShape.STREAKY],
        extents=[3] * 5,
    )
    suggestion = suggest_spot_range_from_vision(report, "1 201")
    assert suggestion.preferred is False


def test_spot_range_reason_recorded():
    report = _report(shapes=[SpotShape.ROUND] * 4, extents=[3] * 4)
    suggestion = suggest_spot_range_from_vision(report, "1 201")
    assert suggestion.reason

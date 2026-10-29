"""Tests for code-layer supervision of LLM-filled vision reports.

The LLM is the source of visual truth; the code enforces structural
and internal-consistency invariants. These tests cover the cross-checks
in `vision_schema.supervise_report`.
"""

import pytest

from xtal_agent.vision_schema import (
    FrameObservation,
    QualityGrade,
    SpotExtent,
    SpotShape,
    VisionReport,
    supervise_report,
)


def _make_observation(frame, shape=SpotShape.ROUND, **kw):
    defaults = dict(
        frame=frame, spot_shape=shape, ice_rings=False,
        overloaded_spots="none", background="normal", notes="",
    )
    defaults.update(kw)
    return FrameObservation(**defaults)


def _make_extent(frame, **kw):
    defaults = dict(
        frame=frame, spots_beyond_5A=True, spots_beyond_3_5A=True,
        spots_beyond_2_5A=False, spots_beyond_2A=False, spots_beyond_1_5A=False,
    )
    defaults.update(kw)
    return SpotExtent(**defaults)


def _report(frames, *, quality=QualityGrade.A, recommended=None):
    return VisionReport(
        schema_version="2.0",
        frames_examined=frames,
        per_frame_observations=[_make_observation(f) for f in frames],
        per_frame_spot_extent=[_make_extent(f) for f in frames],
        estimated_resolution_A=3.5,
        recommended_spot_ranges=recommended or [(frames[0], frames[-1])],
        quality_grade=quality,
        caveats="",
    )


def test_clean_report_passes():
    r = _report([1, 2, 3, 4, 5])
    sup = supervise_report(r)
    assert sup.passed
    assert sup.findings == []


def test_observations_outside_frames_examined_fails():
    r = _report([1, 2, 3])
    # inject an extra observation for frame 99 not in frames_examined
    r.per_frame_observations.append(_make_observation(99))
    sup = supervise_report(r)
    assert not sup.passed
    assert any("99" in f for f in sup.findings)


def test_spot_extent_outside_frames_examined_fails():
    r = _report([1, 2, 3])
    r.per_frame_spot_extent.append(_make_extent(99))
    sup = supervise_report(r)
    assert not sup.passed
    assert any("spot_extent" in f for f in sup.findings)


def test_missing_observations_fails():
    r = _report([1, 2, 3, 4, 5])
    # remove one observation so frames_examined has it but observations don't
    r.per_frame_observations = r.per_frame_observations[:3]
    sup = supervise_report(r)
    assert not sup.passed
    assert any("lack a per_frame_observation" in f for f in sup.findings)


def test_grade_A_with_streaky_frames_fails():
    r = _report([1, 2, 3, 4, 5], quality=QualityGrade.A)
    r.per_frame_observations[2] = _make_observation(3, shape=SpotShape.STREAKY)
    sup = supervise_report(r)
    assert not sup.passed
    assert any("quality_grade=A" in f for f in sup.findings)


def test_grade_C_with_mostly_good_frames_fails():
    r = _report([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], quality=QualityGrade.C)
    # only 1 of 10 streaky (10% < 30%)
    r.per_frame_observations[0] = _make_observation(1, shape=SpotShape.STREAKY)
    sup = supervise_report(r)
    assert not sup.passed
    assert any("quality_grade=C" in f for f in sup.findings)


def test_grade_B_with_no_bad_frames_fails():
    r = _report([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], quality=QualityGrade.B)
    # all round — should be A, not B
    sup = supervise_report(r)
    assert not sup.passed
    assert any("quality_grade=B" in f and "no streaky" in f for f in sup.findings)


def test_grade_B_with_mostly_bad_fails():
    r = _report([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], quality=QualityGrade.B)
    for i in range(7):
        r.per_frame_observations[i] = _make_observation(
            i + 1, shape=SpotShape.STREAKY,
        )
    sup = supervise_report(r)
    assert not sup.passed
    assert any("quality_grade=B" in f and "50%" in f for f in sup.findings)


def test_recommended_spot_range_excludes_streaky_fails():
    r = _report(
        [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
        quality=QualityGrade.B,
        recommended=[(1, 10)],
    )
    # mark frames 5-6 as streaky
    r.per_frame_observations[4] = _make_observation(5, shape=SpotShape.STREAKY)
    r.per_frame_observations[5] = _make_observation(6, shape=SpotShape.STREAKY)
    sup = supervise_report(r)
    assert not sup.passed
    assert any("streaky/diffuse frames" in f and "5" in f and "6" in f
               for f in sup.findings)


def test_recommended_spot_range_correct_split_passes():
    r = _report(
        [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
        quality=QualityGrade.B,
        recommended=[(1, 4), (7, 10)],
    )
    r.per_frame_observations[4] = _make_observation(5, shape=SpotShape.STREAKY)
    r.per_frame_observations[5] = _make_observation(6, shape=SpotShape.STREAKY)
    sup = supervise_report(r)
    assert sup.passed, sup.findings


def test_expected_frame_span_check():
    # frame 500 is outside dataset span [1, 100] — LLM bug
    r = _report([50, 51, 500])
    sup = supervise_report(r, expected_frame_span=(1, 100))
    assert not sup.passed
    assert any("expected dataset span" in f for f in sup.findings)


def test_expected_frame_span_subset_passes():
    # LLM examined a subset (50-52) inside the full dataset [1, 100]
    r = _report([50, 51, 52])
    sup = supervise_report(r, expected_frame_span=(1, 100))
    assert sup.passed


def test_expected_frame_span_passes():
    r = _report([1, 2, 3, 4, 5])
    sup = supervise_report(r, expected_frame_span=(1, 360))
    assert sup.passed


def test_windows_acknowledged_check():
    r = _report([1, 2, 3, 4, 5, 6, 7, 8, 9])  # 9 frames, not multiple of 4
    sup = supervise_report(r, n_expected_windows=4)
    assert not sup.passed
    assert any("sliding-window montages" in f for f in sup.findings)


def test_windows_acknowledged_passes():
    r = _report([1, 2, 3, 4, 5, 6, 7, 8])  # 8 frames, 2 windows
    sup = supervise_report(r, n_expected_windows=4)
    assert sup.passed

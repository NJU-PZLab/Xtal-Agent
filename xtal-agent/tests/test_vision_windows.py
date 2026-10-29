"""Tests for sliding-window partitioning and adaptive bar size."""

import pytest

from xtal_agent.vision_render import (
    MAX_LLM_WINDOWS,
    segment_size_for_target_windows,
    sliding_windows,
)


def test_sliding_windows_covers_full_dataset():
    windows = sliding_windows(360, segment_size=12)
    assert windows[0][0] == 1
    assert windows[-1][1] == 360
    for i in range(len(windows) - 1):
        assert windows[i][1] + 1 == windows[i + 1][0]
    assert len(windows) == 30


def test_sliding_windows_short_dataset():
    assert sliding_windows(5, segment_size=12) == [(1, 5, [1, 2, 3, 4, 5])]
    assert sliding_windows(0, segment_size=12) == []


def test_sliding_windows_consecutive_frames():
    for s, e, fr in sliding_windows(60, segment_size=12):
        assert fr == list(range(s, e + 1))
        assert e - s + 1 == len(fr)


def test_segment_size_scales_with_frame_count():
    """bar (segment_size) must grow with n_frames so window count stays bounded."""
    # 360  → bar=12,  windows=30
    assert segment_size_for_target_windows(360, 30) == 12
    # 720  → bar=24,  windows=30
    assert segment_size_for_target_windows(720, 30) == 24
    # 1800 → bar=60,  windows=30
    assert segment_size_for_target_windows(1800, 30) == 60
    # 3600 → bar=120, windows=30
    assert segment_size_for_target_windows(3600, 30) == 120
    # 7200 → bar=240, windows=30
    assert segment_size_for_target_windows(7200, 30) == 240


def test_segment_size_respects_minimum_12():
    # n_frames <= target_windows: single window (return n_frames)
    assert segment_size_for_target_windows(20, 30) == 20
    # n_frames > target: bar = max(12, ceil(n/target))
    assert segment_size_for_target_windows(120, 30) == 12  # ceil(120/30)=4, min 12
    assert segment_size_for_target_windows(360, 30) == 12  # ceil(360/30)=12
    # very small dataset with default target → 1 window
    assert segment_size_for_target_windows(8, 30) == 8


def test_segment_size_caps_at_100_windows():
    """Hard cap: never produce more than MAX_LLM_WINDOWS montages."""
    # 100000 frames: bar=1000 → 100 windows, not 30 with target=30
    # (because target=30 means 30 windows which is fine, but if user asks
    # for 200 windows we cap at 100)
    assert segment_size_for_target_windows(100000, 200) == 1000
    n_windows = 100000 // 1000
    assert n_windows <= MAX_LLM_WINDOWS


def test_segment_size_handles_pathological_inputs():
    assert segment_size_for_target_windows(0) == 1
    assert segment_size_for_target_windows(-1) == 1
    assert segment_size_for_target_windows(100, 0) > 0  # bad target → defaults to 30
    assert segment_size_for_target_windows(100, -5) > 0  # bad target → defaults to 30

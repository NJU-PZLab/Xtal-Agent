"""Tests for vision_render pure logic and backend wiring.
Backend renderers are mocked — these tests never touch real images.
Implementation must make these pass WITHOUT modifying the tests."""

import json

import pytest

from xtal_agent import vision_render
from xtal_agent.vision_render import (
    RenderBackend,
    densify_around_boundary,
    detect_backend,
    render_dataset,
    sample_frames,
)


# --- sample_frames -----------------------------------------------------------

def test_sample_includes_first_and_last():
    frames = sample_frames(360, max_samples=8)
    assert frames[0] == 1
    assert frames[-1] == 360


def test_sample_respects_max():
    assert len(sample_frames(3600, max_samples=8)) <= 8


def test_sample_small_dataset_returns_all():
    assert sample_frames(5, max_samples=8) == [1, 2, 3, 4, 5]


def test_sample_sorted_unique():
    frames = sample_frames(1000, max_samples=8)
    assert frames == sorted(set(frames))


def test_sample_rejects_zero_frames():
    with pytest.raises(ValueError):
        sample_frames(0)


# --- densify_around_boundary --------------------------------------------------

def test_densify_between_two_frames():
    extra = densify_around_boundary(1, 101)
    assert all(1 < f < 101 for f in extra)
    assert 1 <= len(extra) <= 4


def test_densify_adjacent_frames_returns_empty():
    assert densify_around_boundary(10, 11) == []


# --- detect_backend ------------------------------------------------------------

def test_detect_prefers_adxv(monkeypatch):
    monkeypatch.setattr(
        vision_render.shutil, "which",
        lambda name: "/usr/bin/adxv" if name == "adxv" else None,
    )
    assert detect_backend() == RenderBackend.ADXV


def test_detect_falls_back_to_dials(monkeypatch):
    monkeypatch.setattr(
        vision_render.shutil, "which",
        lambda name: "/usr/bin/dials.export_bitmaps"
        if name == "dials.export_bitmaps" else None,
    )
    assert detect_backend() == RenderBackend.DIALS


def test_detect_raises_when_nothing_available(monkeypatch):
    monkeypatch.setattr(vision_render.shutil, "which", lambda name: None)
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "fabio":
            raise ImportError("no fabio")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(RuntimeError, match="no rendering backend"):
        detect_backend()


# --- render_dataset -------------------------------------------------------------

def test_render_dataset_writes_geometry(tmp_path, monkeypatch):
    monkeypatch.setattr(
        vision_render.shutil, "which",
        lambda name: "/usr/bin/adxv" if name == "adxv" else None,
    )
    result = render_dataset(
        raw_image_pattern="/data/sample_?????.cbf",
        n_frames=360,
        output_dir=tmp_path,
    )
    assert result.backend == RenderBackend.ADXV
    geometry = json.loads(result.geometry_path.read_text())
    assert geometry["backend"] == "adxv"
    assert geometry["sampled_frames"][0] == 1
    assert geometry["sampled_frames"][-1] == 360


def test_render_dataset_does_not_modify_raw_images(tmp_path, monkeypatch):
    """Renderers must only write into output_dir. This test documents the
    contract; Task 3 implementation must keep it true."""
    monkeypatch.setattr(
        vision_render.shutil, "which",
        lambda name: "/usr/bin/adxv" if name == "adxv" else None,
    )
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    sentinel = raw_dir / "sample_00001.cbf"
    sentinel.write_bytes(b"DO NOT TOUCH")
    render_dataset(
        raw_image_pattern=str(raw_dir / "sample_?????.cbf"),
        n_frames=10,
        output_dir=tmp_path / "out",
    )
    assert sentinel.read_bytes() == b"DO NOT TOUCH"

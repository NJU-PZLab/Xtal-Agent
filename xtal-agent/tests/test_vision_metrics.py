"""Tests for the visual-feature quantifier (MontageMetrics).

These tests operate on synthetic montage images (PNG files built in
tmp_path) — no CBF reading, no raw pixel statistics. The quantifier
operates on rendered montage PNGs, exactly what the LLM sees.
"""

import numpy as np
from PIL import Image
import pytest

from xtal_agent.vision_render import (
    MontageMetrics,
    quantify_all_montages,
    quantify_montage,
)


def _save_synthetic_montage(
    path,
    n_tiles: int = 12,
    cell_px: int = 256,
    bg: int = 200,
    spot_brightness: int = 30,
    spots_per_tile: int = 20,
) -> str:
    """Build a synthetic montage PNG: bg + dark spots scattered per tile.

    `bg` is the background gray level; `spot_brightness` is the gray level
    of dark spots. Higher contrast = lower spot_brightness.
    """
    cols = 4
    rows = (n_tiles + cols - 1) // cols
    pad = 4
    canvas_w = cols * cell_px + (cols + 1) * pad
    canvas_h = rows * cell_px + (rows + 1) * pad
    canvas = Image.new("L", (canvas_w, canvas_h), color=bg)
    px = canvas.load()
    rng = np.random.default_rng(seed=42)
    for t in range(n_tiles):
        r, c = divmod(t, cols)
        x0 = pad + c * (cell_px + pad)
        y0 = pad + r * (cell_px + pad)
        for _ in range(spots_per_tile):
            cx = x0 + int(rng.integers(0, cell_px))
            cy = y0 + int(rng.integers(0, cell_px))
            for dy in range(-1, 2):
                for dx in range(-1, 2):
                    if 0 <= cx + dx < canvas_w and 0 <= cy + dy < canvas_h:
                        px[cx + dx, cy + dy] = spot_brightness
    path = str(path)
    canvas.save(path, format="PNG")
    return path


def test_quantify_montage_returns_metrics(tmp_path):
    p = _save_synthetic_montage(tmp_path / "test.png", spots_per_tile=20)
    m = quantify_montage(p)
    assert isinstance(m, MontageMetrics)
    assert m.spot_count > 0
    assert m.mean_intensity > 0
    assert m.intensity_std > 0
    assert m.contrast_p99_minus_p1 > 0
    assert m.histogram_entropy > 0


def test_dense_montage_has_more_spots_than_sparse(tmp_path):
    """Visual notion of 'dense spots' must correlate with spot_count."""
    p_dense = _save_synthetic_montage(tmp_path / "dense.png", spots_per_tile=50)
    p_sparse = _save_synthetic_montage(tmp_path / "sparse.png", spots_per_tile=2)
    m_dense = quantify_montage(p_dense)
    m_sparse = quantify_montage(p_sparse)
    assert m_dense.spot_count > m_sparse.spot_count, (
        f"dense ({m_dense.spot_count}) should have more spots than "
        f"sparse ({m_sparse.spot_count})"
    )
    assert m_dense.spot_density_per_mpx2 > m_sparse.spot_density_per_mpx2


def test_high_contrast_montage_has_higher_std(tmp_path):
    p_low = _save_synthetic_montage(
        tmp_path / "low.png", bg=200, spot_brightness=180,
    )
    p_high = _save_synthetic_montage(
        tmp_path / "high.png", bg=200, spot_brightness=30,
    )
    m_low = quantify_montage(p_low)
    m_high = quantify_montage(p_high)
    assert m_high.intensity_std > m_low.intensity_std
    assert m_high.contrast_p99_minus_p1 > m_low.contrast_p99_minus_p1


def test_quantify_all_montages_in_order(tmp_path):
    paths = []
    for i in range(3):
        p = _save_synthetic_montage(tmp_path / f"montage_{i+1:02d}.png", spots_per_tile=10 + i * 5)
        paths.append(p)
    # an unrelated file should be ignored
    (tmp_path / "geometry.json").write_text("{}")
    metrics = quantify_all_montages(tmp_path)
    assert len(metrics) == 3
    # ordered by filename: montage_01, _02, _03
    spot_counts = [m.spot_count for m in metrics]
    # montage_01 (10 spots) < montage_02 (15) < montage_03 (20)
    assert spot_counts[0] < spot_counts[1] < spot_counts[2]

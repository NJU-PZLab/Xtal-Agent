"""Render sampled raw diffraction frames for LLM visual inspection.

Backend strategy (auto-detected, recorded for reproducibility):
  A. adxv (preferred): ``xvfb-run -a adxv -sa -rings <image> <out.jpg>``
     draws its own resolution rings from header geometry.
  B. dials.export_bitmaps: headless, exact pixels; overlays drawn with Pillow.
  C. fabio + matplotlib: pure-Python fallback.

Never parse CBF/H5 bytes yourself. Never modify raw images.
"""

from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

import numpy as np
from scipy import ndimage


class RenderBackend(StrEnum):
    ADXV = "adxv"
    DIALS = "dials"
    FABIO = "fabio"


@dataclass(frozen=True)
class RenderedFrame:
    frame: int
    image_path: Path
    views: list[Path]  # standard / high-sensitivity / slab views


@dataclass(frozen=True)
class RenderResult:
    backend: RenderBackend
    frames: list[RenderedFrame]
    output_dir: Path
    geometry_path: Path
    warnings: list[str] = field(default_factory=list)


# Resolution rings drawn on rendered frames, from low (inner) to high (outer).
# Order matches vision_schema.RESOLUTION_RINGS so the LLM answers booleans
# in the same order the rings appear.
RENDER_RING_VALUES_A: tuple[float, ...] = (5.0, 3.5, 2.5, 2.0, 1.5)


# ---------------------------------------------------------------------------
# Frame sampling (pure logic — unit tested without any backend)
# ---------------------------------------------------------------------------

def sample_frames(n_frames: int, max_samples: int = 8) -> list[int]:
    """Evenly sample frame numbers, always including first and last frame."""
    if n_frames < 1:
        raise ValueError("n_frames must be >= 1")
    if n_frames <= max_samples:
        return list(range(1, n_frames + 1))
    step = (n_frames - 1) / (max_samples - 1)
    frames = sorted({1 + round(i * step) for i in range(max_samples)})
    return frames


def densify_around_boundary(
    left_frame: int,
    right_frame: int,
    max_extra: int = 4,
) -> list[int]:
    """Extra samples between two sampled frames where spot shape changed,
    to locate the boundary precisely (bisection-style)."""
    if right_frame - left_frame <= 1:
        return []
    candidates = [
        left_frame + round((right_frame - left_frame) * f)
        for f in (0.25, 0.5, 0.75)
    ]
    frames = sorted({f for f in candidates if left_frame < f < right_frame})
    return frames[:max_extra]


# ---------------------------------------------------------------------------
# Frame file resolution
# ---------------------------------------------------------------------------

_FRAME_PATTERN_TOKEN = "{frame:05d}"


def resolve_frame_path(pattern: str, frame: int) -> Path | None:
    """Return the path for a given frame, or None if no file matches.

    Supports three pattern styles:

    1. ``{frame:0Nd}`` placeholder: substituted with the zero-padded frame
       number to N digits (e.g. ``{frame:04d}`` → ``0001``).
    2. ``{frame}`` placeholder: substituted with the bare frame number.
    3. glob pattern (containing ``?``): the first contiguous run of ``?`` is
       replaced with the frame number zero-padded to that many digits.
       If the pattern has no ``?``/``*``, it is returned as-is.
    """
    if "{frame" in pattern:
        out = pattern
        out = re.sub(r"\{frame:0(\d+)d\}", lambda m: f"{frame:0{int(m.group(1))}d}", out)
        out = out.replace("{frame}", str(frame))
        return Path(out)
    if "?" in pattern:
        digits = max(4, len(str(frame)))
        out_chars: list[str] = []
        replaced = False
        for ch in pattern:
            if ch == "?" and not replaced:
                out_chars.append(str(frame).zfill(digits))
                replaced = True
            else:
                out_chars.append(ch)
        return Path("".join(out_chars))
    return Path(pattern)


# ---------------------------------------------------------------------------
# Backend detection (unit tested with monkeypatched shutil.which)
# ---------------------------------------------------------------------------

def detect_backend() -> RenderBackend:
    """Pick the best available rendering backend: adxv > dials > fabio."""
    if shutil.which("adxv"):
        return RenderBackend.ADXV
    if shutil.which("dials.export_bitmaps"):
        return RenderBackend.DIALS
    try:
        import fabio  # noqa: F401
        return RenderBackend.FABIO
    except ImportError:
        pass
    raise RuntimeError(
        "no rendering backend available: install adxv, DIALS, or fabio"
    )


# ---------------------------------------------------------------------------
# Backend renderers
# ---------------------------------------------------------------------------

def _render_with_adxv(
    image: Path,
    out_jpg: Path,
    slabs: int = 1,
    crop: str | None = None,
    rings: bool = True,
    ring_font: str = "-*-lucidatypewriter-bold-r-normal-sans-180-*-*-*-*-*-*-*",
) -> Path:
    """Render a single frame with adxv in standalone (batch) mode.

    Command form (preferred path):
        xvfb-run -a adxv -sa [-rings [-rfont <font>]]
            [-slabs N | -sa_crop WxH+X+Y] <image> <out_jpg>
    """
    if not shutil.which("adxv"):
        raise RuntimeError("adxv not on PATH")
    out_jpg = Path(out_jpg)
    out_jpg.parent.mkdir(parents=True, exist_ok=True)

    cmd: list[str] = ["xvfb-run", "-a", "adxv", "-sa"]
    if rings:
        cmd += ["-rings", "-rfont", ring_font]
    if slabs and slabs > 1:
        cmd += ["-slabs", str(int(slabs))]
    if crop:
        cmd += ["-sa_crop", crop]
    cmd += [str(image), str(out_jpg)]

    proc = subprocess.run(
        cmd,
        check=False,
        timeout=120,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0 or not out_jpg.exists() or out_jpg.stat().st_size == 0:
        raise RuntimeError(
            f"adxv render failed for {image} (exit={proc.returncode}): "
            f"{(proc.stderr or proc.stdout).strip()[:500]}"
        )
    return out_jpg


def _ring_radius_px(d_A: float, wavelength_A: float, distance_mm: float,
                    pixel_size_mm: float) -> float:
    """Convert a resolution ring (Å) to image radius in pixels."""
    if pixel_size_mm <= 0 or d_A <= 0:
        return 0.0
    if wavelength_A <= 0 or distance_mm <= 0:
        return 0.0
    theta = math.asin(min(1.0, wavelength_A / (2.0 * d_A)))
    return distance_mm * math.tan(2.0 * theta) / pixel_size_mm


def _draw_rings_pil(img, geometry: dict) -> None:
    """Overlay resolution rings (and labels) on a Pillow image in-place."""
    from PIL import ImageDraw

    if not geometry:
        return
    wavelength = float(geometry.get("wavelength_A") or 0.0)
    distance = float(geometry.get("detector_distance_mm") or 0.0)
    pixel_size = float(geometry.get("pixel_size_mm") or 0.0)
    beam_x = float(geometry.get("beam_x_px") or img.size[0] / 2.0)
    beam_y = float(geometry.get("beam_y_px") or img.size[1] / 2.0)

    draw = ImageDraw.Draw(img)
    for d in RENDER_RING_VALUES_A:
        r = _ring_radius_px(d, wavelength, distance, pixel_size)
        if r <= 0:
            continue
        draw.ellipse(
            (beam_x - r, beam_y - r, beam_x + r, beam_y + r),
            outline=(255, 255, 0),
            width=2,
        )
        draw.text((beam_x + r + 4, beam_y - 8), f"{d}A", fill=(255, 255, 0))


def _read_cbf_header(image: Path) -> dict:
    """Extract the minimum geometry needed to draw resolution rings.

    Returns a dict with optional keys: wavelength_A, detector_distance_mm,
    pixel_size_mm, beam_x_px, beam_y_px. Values default to None on miss.
    Handles both ``Key: value`` and CBF header ``Key value`` formats.
    """
    out: dict = {
        "wavelength_A": None,
        "detector_distance_mm": None,
        "pixel_size_mm": None,
        "beam_x_px": None,
        "beam_y_px": None,
    }
    try:
        text = image.read_text(errors="ignore")
    except Exception:
        return out
    import re

    # Look at header area only (everything before the first binary '###CBF...binary' marker)
    header_blob = text.split("--CIF_SECTION")[0][:20000]

    def _search(pattern: str, key: str, unit_scale: float = 1.0) -> None:
        m = re.search(pattern, header_blob, flags=re.IGNORECASE)
        if m:
            try:
                out[key] = float(m.group(1)) * unit_scale
            except Exception:
                pass

    _search(r"wavelength[^0-9\-+]*([0-9.eE+-]+)", "wavelength_A")
    # Detector distance can be in metres; CBF PILATUS reports e.g. "0.39301 m"
    m = re.search(
        r"detector[_ ]distance[^0-9\-+]*([0-9.eE+-]+)\s*(m|mm)?",
        header_blob,
        flags=re.IGNORECASE,
    )
    if m:
        try:
            val = float(m.group(1))
            unit = (m.group(2) or "mm").lower()
            if unit == "m":
                val *= 1000.0
            out["detector_distance_mm"] = val
        except Exception:
            pass
    # Pixel size: "172e-6 m x 172e-6 m" — take the first number, convert m→mm
    m = re.search(
        r"pixel[_ ]size[^0-9\-+]*([0-9.eE+-]+)\s*(m|mm)?",
        header_blob,
        flags=re.IGNORECASE,
    )
    if m:
        try:
            val = float(m.group(1))
            unit = (m.group(2) or "m").lower()
            if unit == "m":
                val *= 1000.0
            out["pixel_size_mm"] = val
        except Exception:
            pass
    # Beam_xy (1229.00, 1267.73) pixels
    m = re.search(
        r"beam[_ ]?xy[^0-9\-+]*\(\s*([0-9.eE+-]+)\s*,\s*([0-9.eE+-]+)",
        header_blob,
        flags=re.IGNORECASE,
    )
    if m:
        try:
            out["beam_x_px"] = float(m.group(1))
            out["beam_y_px"] = float(m.group(2))
        except Exception:
            pass
    return out


def _render_with_dials(image: Path, out_png: Path) -> Path:
    """Render via dials.export_bitmaps, then overlay resolution rings."""
    if not shutil.which("dials.export_bitmaps"):
        raise RuntimeError("dials.export_bitmaps not on PATH")
    out_png = Path(out_png)
    out_png.parent.mkdir(parents=True, exist_ok=True)
    tmp_dir = out_png.parent / f"_dials_tmp_{out_png.stem}"
    tmp_dir.mkdir(exist_ok=True)
    proc = subprocess.run(
        [
            "dials.export_bitmaps",
            str(image),
            f"output.directory={tmp_dir}",
            "format=jpeg",
        ],
        check=False,
        timeout=180,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"dials.export_bitmaps failed for {image}: "
            f"{(proc.stderr or proc.stdout).strip()[:500]}"
        )
    produced = list(tmp_dir.glob("*.jpeg")) + list(tmp_dir.glob("*.jpg"))
    if not produced:
        raise RuntimeError(f"dials.export_bitmaps produced no file for {image}")
    src = produced[0]
    try:
        from PIL import Image

        geometry = _read_cbf_header(image) if image.suffix.lower() == ".cbf" else {}
        img = Image.open(src).convert("RGB")
        _draw_rings_pil(img, geometry)
        img.save(out_png, format="PNG")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
    return out_png


def _render_with_fabio(image: Path, out_png: Path) -> Path:
    """Pure-Python fallback: read via fabio, save via matplotlib, draw rings."""
    import fabio
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    out_png = Path(out_png)
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fab = fabio.open(str(image))
    arr = np.asarray(fab.data)
    if arr.size == 0:
        raise RuntimeError(f"fabio returned empty array for {image}")
    lo, hi = np.percentile(arr, [0.5, 99.5])
    arr = np.clip(arr, lo, hi)
    fig, ax = plt.subplots(figsize=(6, 6))
    ax.imshow(arr, cmap="gray", origin="lower", aspect="equal")
    geometry = _read_cbf_header(image) if image.suffix.lower() == ".cbf" else {}
    if geometry:
        wavelength = float(geometry.get("wavelength_A") or 0.0)
        distance = float(geometry.get("detector_distance_mm") or 0.0)
        pixel_size = float(geometry.get("pixel_size_mm") or 0.0)
        beam_x = float(geometry.get("beam_x_px") or arr.shape[1] / 2.0)
        beam_y = float(geometry.get("beam_y_px") or arr.shape[0] / 2.0)
        for d in RENDER_RING_VALUES_A:
            r = _ring_radius_px(d, wavelength, distance, pixel_size)
            if r > 0:
                ax.add_patch(plt.Circle((beam_x, beam_y), r, fill=False,
                                        color="yellow", linewidth=1.5))
                ax.text(beam_x + r + 4, beam_y - 8, f"{d}A", color="yellow")
    ax.set_axis_off()
    fig.tight_layout(pad=0)
    fig.savefig(out_png, format="png", dpi=120, bbox_inches="tight")
    plt.close(fig)
    return out_png


_RENDERERS = {
    RenderBackend.ADXV: _render_with_adxv,
    RenderBackend.DIALS: _render_with_dials,
    RenderBackend.FABIO: _render_with_fabio,
}


# ---------------------------------------------------------------------------
# Dataset-level entry point
# ---------------------------------------------------------------------------

def render_dataset(
    raw_image_pattern: str,
    n_frames: int,
    output_dir: str | Path,
    backend: RenderBackend | None = None,
    max_samples: int = 0,
    slab_width: int = 0,
    frames: list[int] | None = None,
) -> RenderResult:
    """Render sampled frames of a dataset into output_dir.

    raw_image_pattern: glob-style pattern or ``{frame:05d}`` template.
    frames: optional pre-selected frame list (v2 Tier 1 signal-driven
        output). When omitted, falls back to uniform sampling via
        ``sample_frames(n_frames, max_samples)`` — or, if `max_samples`
        is 0 / falsy / >= n_frames, renders ALL frames.
    max_samples: cap when no explicit `frames` is given. **0 or None means
        render ALL frames** — required for v2 strategy "全 cbf 转 jpg".
    slab_width: when > 1, also render a slab-summed view per sampled frame
    (thin oscillation slices); adxv backend maps this to ``-slabs``.

    Writes geometry.json (backend, frames, pattern) for reproducibility.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    chosen = backend or detect_backend()
    renderer = _RENDERERS[chosen]

    if frames is None:
        if not max_samples or max_samples >= n_frames:
            frames = list(range(1, n_frames + 1))
        else:
            frames = sample_frames(n_frames, max_samples)
    rendered: list[RenderedFrame] = []
    warnings: list[str] = []

    for f in frames:
        image = resolve_frame_path(raw_image_pattern, f)
        if image is None or not image.exists():
            warnings.append(f"frame {f}: source file not found at {image}")
            continue
        views: list[Path] = []
        std_jpg = output_dir / f"frame_{f:05d}_std.jpg"
        try:
            renderer(image, std_jpg)
            views.append(std_jpg)
        except Exception as exc:
            warnings.append(f"frame {f}: standard render failed: {exc}")
        if slab_width and slab_width > 1 and chosen == RenderBackend.ADXV:
            slab_jpg = output_dir / f"frame_{f:05d}_slab.jpg"
            try:
                _render_with_adxv(image, slab_jpg, slabs=slab_width)
                views.append(slab_jpg)
            except Exception as exc:
                warnings.append(f"frame {f}: slab render failed: {exc}")
        if views:
            rendered.append(RenderedFrame(frame=f, image_path=image, views=views))

    geometry = {
        "backend": chosen.value,
        "raw_image_pattern": raw_image_pattern,
        "n_frames": n_frames,
        "sampled_frames": frames,
        "slab_width": slab_width,
        "rendered_frame_count": len(rendered),
    }
    geometry_path = output_dir / "geometry.json"
    geometry_path.write_text(json.dumps(geometry, indent=2))

    return RenderResult(
        backend=chosen,
        frames=rendered,
        output_dir=output_dir,
        geometry_path=geometry_path,
        warnings=warnings,
    )

MAX_LLM_WINDOWS = 100  # hard cap on montages (LLM calls) per scan


def segment_size_for_target_windows(
    n_frames: int,
    target_windows: int = 30,
) -> int:
    """Pick segment_size so the dataset produces ~target_windows montages.

    v2 spec: "12-18 LLM calls for 360 frames; 15-25 for 720; 20-35 for
    1800+". The bar (segment_size) must scale with n_frames so the LLM
    call count stays bounded regardless of dataset size. Hard cap:
    `MAX_LLM_WINDOWS` (100) — never produce more montages than that.

    `segment_size = max(12, ceil(n_frames / effective_target))`
    - 360    frames / 30  = 12    → 30 windows
    - 720    frames / 30  = 24    → 30 windows
    - 1800   frames / 30  = 60    → 30 windows
    - 3600   frames / 30  = 120   → 30 windows
    - 36000  frames / 30  = 1200  → 30 windows   (still 30 because target=30)
    - 100000 frames / 100 = 1000  → 100 windows  (capped at 100)
    - < target_windows frames: segment_size = n_frames (single window)
    """
    if n_frames < 1:
        return 1
    if target_windows < 1:
        target_windows = 30
    effective = min(target_windows, MAX_LLM_WINDOWS)
    if n_frames <= effective:
        return max(1, n_frames)
    raw = -(-n_frames // effective)  # ceil
    return max(12, raw)


# Tier 2 — montage / single-call cost compression (v2)
# ---------------------------------------------------------------------------

def build_montage(
    jpg_paths: list[Path],
    out_path: str | Path,
    cols: int = 4,
    cell_px: int = 384,
    pad: int = 4,
    bg: tuple[int, int, int] = (32, 32, 32),
) -> Path:
    """Pack multiple rendered JPGs into a single grid PNG for one-call LLM inspection.

    Resizes each tile to `cell_px` (preserving aspect) and arranges in
    `cols` columns. v2 goal: one LLM call covers many frames.

    Pure function, no detection; the LLM still does the actual judgment.
    """
    from PIL import Image
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if not jpg_paths:
        raise ValueError("build_montage: empty jpg_paths")
    n = len(jpg_paths)
    rows = (n + cols - 1) // cols
    canvas_w = cols * cell_px + (cols + 1) * pad
    canvas_h = rows * cell_px + (rows + 1) * pad
    canvas = Image.new("RGB", (canvas_w, canvas_h), bg)
    for i, p in enumerate(jpg_paths):
        try:
            im = Image.open(p).convert("RGB")
        except Exception:
            continue
        im.thumbnail((cell_px, cell_px))
        r, c = divmod(i, cols)
        x = pad + c * (cell_px + pad) + (cell_px - im.size[0]) // 2
        y = pad + r * (cell_px + pad) + (cell_px - im.size[1]) // 2
        canvas.paste(im, (x, y))
    canvas.save(out_path, format="PNG")
    return out_path


@dataclass(frozen=True)
class MontageMetrics:
    """Quantitative visual features extracted from a rendered montage PNG.

    These are NOT pixel-statistics-of-raw-CBF (forbidden by v2 red line).
    They are features of the SAME JPG the LLM is looking at — the
    goal is to give the LLM a numeric cross-check on its own visual
    judgment, not to replace it.

    Correlation expectation: a montage the LLM judges "good" should have
    higher spot_count, higher spot_density, higher entropy than one
    judged "bad".
    """

    path: Path
    cell_px: int
    n_tiles: int
    spot_count: int             # dark connected components in montage
    mean_intensity: float       # 0-255 mean
    intensity_std: float        # 0-255 std
    contrast_p99_minus_p1: float # dynamic range of pixel values
    histogram_entropy: float    # Shannon entropy of 64-bin histogram
    spot_density_per_mpx2: float  # spot_count per megapixel of montage


def quantify_montage(montage_path: str | Path) -> MontageMetrics:
    """Compute visual features from a montage PNG.

    Reads the rendered montage (which is what the LLM sees) and produces
    numeric descriptors. The LLM cross-checks its visual judgment against
    these numbers; the LLM is the source of truth, the numbers are hints.
    """
    from PIL import Image
    from scipy import ndimage

    path = Path(montage_path)
    img = np.asarray(Image.open(path).convert("L"), dtype=np.float32)  # grayscale
    h, w = img.shape
    n_tiles: int = 0  # unknown from image alone; caller can fill

    # Histogram entropy (64 bins)
    hist, _ = np.histogram(img.ravel(), bins=64, range=(0, 256))
    p = hist / max(1, hist.sum())
    p = p[p > 0]
    entropy = float(-np.sum(p * np.log2(p)))

    # Statistics on the whole montage
    mean_v = float(img.mean())
    std_v = float(img.std())
    # Contrast: full pixel-value range (min vs max). p1/p99 is too brittle
    # when the spot population is small (<1% of pixels) — the percentiles
    # never reach the dark population.
    contrast = float(img.max()) - float(img.min())

    # Spot count: dark connected components (brighter than bg = high values,
    # dark spots = low values; convention: we use INVERTED so dark = signal)
    bg_level = float(np.median(img))
    dark = img < bg_level * 0.85  # threshold relative to background
    labeled, n_spots = ndimage.label(dark)
    # filter tiny noise: only components with >= 4 pixels
    sizes = np.bincount(labeled.ravel())[1:]  # skip background label
    n_spots_real = int(np.sum(sizes >= 4))

    # Spot density per megapixel
    area_mpx2 = (h * w) / 1e6
    spot_density = float(n_spots_real) / max(1e-6, area_mpx2)

    return MontageMetrics(
        path=path,
        cell_px=0,  # caller fills
        n_tiles=n_tiles,
        spot_count=n_spots_real,
        mean_intensity=mean_v,
        intensity_std=std_v,
        contrast_p99_minus_p1=contrast,
        histogram_entropy=entropy,
        spot_density_per_mpx2=spot_density,
    )


def quantify_all_montages(
    vision_frames_dir: str | Path,
) -> list[MontageMetrics]:
    """Compute MontageMetrics for every montage_*.png in a directory.

    Returns metrics in montage filename order (montage_01, _02, ...).
    """
    vision_frames_dir = Path(vision_frames_dir)
    paths = sorted(vision_frames_dir.glob("montage_*.png"))
    return [quantify_montage(p) for p in paths]


def build_montage_from_dir(
    vision_frames_dir: str | Path,
    out_path: str | Path,
    cols: int = 4,
    cell_px: int = 384,
) -> Path:
    """Build a montage of all rendered standard-view JPGs in a directory.

    Convenience helper for the LLM: one PNG ≈ N frames in one image.
    """
    vision_frames_dir = Path(vision_frames_dir)
    paths = sorted(vision_frames_dir.glob("frame_*_std.jpg"))
    if not paths:
        raise RuntimeError(f"no rendered frames in {vision_frames_dir}")
    return build_montage(paths, out_path, cols=cols, cell_px=cell_px)


# ---------------------------------------------------------------------------
# Sliding-window partition (v2: structural, no pixel reading)
# ---------------------------------------------------------------------------

def sliding_windows(
    n_frames: int,
    segment_size: int = 12,
) -> list[tuple[int, int, list[int]]]:
    """Partition the dataset into consecutive-frame windows.

    Each window is `segment_size` consecutive frames. The LLM walks one
    montage per window in frame order, so it can spot local quality
    degradation. No pixel data is read here — purely structural.
    """
    if n_frames < 1 or segment_size < 1:
        return []
    out: list[tuple[int, int, list[int]]] = []
    start = 1
    while start <= n_frames:
        end = min(start + segment_size - 1, n_frames)
        out.append((start, end, list(range(start, end + 1))))
        if end == n_frames:
            break
        start = end + 1
    return out

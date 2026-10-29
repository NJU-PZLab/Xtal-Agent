---
name: crystallography-phase0-image-inspection
description: Use when inspecting raw diffraction images (CBF, H5, diffraction images) for SPOT_RANGE, spot shape, resolution estimate, or radiation damage assessment. Triggered by vision-scan, vision_report.json, or visual inspection of rendered frames.
---

# Crystallography Phase 0: Image Inspection (Vision Module)

The vision module is an **evidence-gathering layer** at the start of Phase 0.
A multimodal LLM agent inspects rendered diffraction frames (JPG/PNG) and
writes `vision_report.json`; code-backed helpers in `decision_engine.py`
derive downstream numbers from that report.

The module is opt-in via `manifest.yaml`:

```yaml
vision:
  enabled: true    # or false
```

If `vision.enabled` is missing from the manifest, `load_manifest` raises
and the LLM must ask the user to set it. **Never infer a default.**

## Hard Rules

- **LLM inspects only rendered JPG/PNG images with its multimodal vision
  capability.** Never let the LLM read raw CBF/H5 pixel data or base
  judgments on intensity-distribution statistics (median / p99 / max) —
  those are blind to spot morphology. Raw files are only read by code
  (renderer: adxv / dials / fabio).
- **Spot shape is relative to the dataset's own quality range.** The
  best frames in a dataset get ROUND or SLIGHTLY_ELONGATED; the worst
  get STREAKY or DIFFUSE. A uniformly weak dataset marks all frames as
  SLIGHTLY_ELONGATED, not STREAKY. The longest contiguous good run
  becomes the SPOT_RANGE recommendation.
- Do not modify any test file in `tests/` to accommodate implementation.
- Do not add twinning fields to any output, schema, or prompt (twinning
  is handled by xtriage).
- The only downstream parameter consumer is `recommended_spot_ranges`
  (and only in simple mode, written to XDS.INP). Resolution suggestions
  and radiation-damage assessments go into the report only.
- Raw .cbf / .h5 files are read-only; rendered output goes exclusively
  to the project's `vision_frames/` directory.

## Token-Cost Warning

The vision module renders ALL diffraction frames to high-resolution JPG,
which is a CPU-only operation. The LLM-cost part is the multimodal
inspection of the sliding-window montages. For a typical dataset:

| Frames | Montages (auto-scaled) | Est. LLM tokens |
|---|---|---|
| 360 | 30 | ~150K |
| 720 | 30 | ~150K |
| 1800 | 30 | ~150K |
| 3600 | 30 | ~150K |

The montage count is bounded at 100 (hard cap). The segment bar scales
with dataset size so the number stays around target (default 30).
Montages use 1024px/cell high-resolution tiles (controlled via
`--montage-cell-px`).

**Gate rule**: the LLM MUST ask the user whether to proceed, must
present the token estimate, and must only run `vision-scan` after
explicit user approval. If the user declines, skip the vision module
and proceed directly to Phase 1.

## Pipeline

1. Render ALL CBFs to JPG (one PNG per frame) — full cache for later
   drill-down.
2. Partition the dataset into sliding windows of consecutive frames
   (segment size auto-scales with frame count). Build one montage PNG
   per window.
3. The LLM walks the montages in frame order, identifies segments with
   degraded quality, drills into individual frames as needed, and
   writes `vision_report.json`.
4. Code validates the report (schema + internal consistency checks) via
   `xtal-agent vision-validate`.
5. Code-side math (`decision_engine`) derives SPOT_RANGE,
   resolution estimates, and radiation-damage assessment from the
   validated report.

## Required Code Calls

```bash
source xtal-agent/env/activate.sh
xtal-agent vision-scan <project_dir>        # render all + build montages
xtal-agent vision-validate <project_dir>   # validate LLM-filled report
xtal-agent phase-guide phase0
xtal-agent guard <project_dir> --before phase0_vision_scan
xtal-agent guard <project_dir> --after phase0_vision_scan
```

## Parameter Discipline

| Field | Allowed consumer |
|---|---|
| `recommended_spot_ranges` | XDS.INP `SPOT_RANGE` (simple mode only) |
| `estimated_resolution_A` | report only |
| `per_frame_spot_extent` | code computes resolution curve; not a parameter |
| radiation-damage assessment | report only |

`assess_radiation_damage()` (decision_engine) folds in spot-shape trend
(streaky-frame ratio in first vs. last third of the sweep) alongside
resolution degradation. Radiation damage may manifest first as spot
elongation / streaking, only later as resolution-limit retreat.

## Code-Layer Supervision

After the LLM fills `vision_report.json`, code-side checks enforce:

1. **Schema compliance** — `vision-validate` rejects malformed reports.
2. **Frame range consistency** — `recommended_spot_ranges` must lie
   inside the dataset frame span.
3. **Observation coverage** — every observed frame must be in
   `frames_examined`, and every spot-extent frame must also be.
4. **Boolean monotonicity** — `spots_beyond_<X>` must satisfy
   "high-resolution ring has spots ⇒ all lower-resolution rings have
   spots".
5. **SPOT_RANGE derivation** — `decision_engine.suggest_spot_range_from_vision`
   uses only the LLM's `per_frame_observations` (not pixel data).
6. **Internal consistency** — `supervise_report()` cross-checks
   quality_grade vs. observation mix, ensures streak frames are
   excluded from recommended ranges, and verifies every sliding-window
   montage is acknowledged.

## Outputs

- `vision_frames/frame_<NNNNN>_std.jpg` — full per-frame JPG cache.
- `vision_frames/montage_<NN>.png` — per-window sliding-window montages,
  one per segment of consecutive frames, in frame order.
- `vision_frames/windows.tsv` — window index (window number, start, end).
- `vision_frames/geometry.json` — rendering provenance.
- `vision_prompt.md` — LLM instruction template.
- `vision_report.json` — LLM-filled, schema-validated.

"""Pydantic schema for vision_report.json.

The vision module is an evidence-gathering layer: an outer LLM agent inspects
rendered diffraction frames and fills vision_report.json. This module defines
and validates that JSON. All downstream numeric decisions live in
decision_engine.py — this file only guarantees the evidence is well-formed.

Parameter discipline (hard rule): downstream consumers may ONLY read
`recommended_spot_ranges`. Every other field is reference-only and must never
be written into XDS.INP or any parameter file.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field, model_validator

SCHEMA_VERSION = "2.0"

# Resolution rings drawn on rendered frames, from low (inner) to high (outer).
# Order matters: decision logic scans this list to find the outermost ring
# that still has spots beyond it.
RESOLUTION_RINGS: tuple[float, ...] = (5.0, 3.5, 2.5, 2.0, 1.5)


class SpotShape(StrEnum):
    ROUND = "round"
    SLIGHTLY_ELONGATED = "slightly_elongated"
    STREAKY = "streaky"
    DIFFUSE = "diffuse"


class OverloadLevel(StrEnum):
    NONE = "none"
    FEW = "few"
    MANY = "many"


class BackgroundLevel(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"


class QualityGrade(StrEnum):
    A = "A"
    B = "B"
    C = "C"


class FrameObservation(BaseModel):
    """Qualitative per-frame observations by the inspecting LLM.

    Judge spot_shape relative to the dataset's own quality range:
    the *best* frames get ROUND or SLIGHTLY_ELONGATED even if they
    are weak; the *worst* frames get STREAKY or DIFFUSE. In a
    uniformly weak dataset, all frames are SLIGHTLY_ELONGATED.
    """

    frame: int = Field(ge=1)
    spot_shape: SpotShape
    ice_rings: bool
    overloaded_spots: OverloadLevel
    background: BackgroundLevel
    notes: str = ""


class SpotExtent(BaseModel):
    """Per-frame booleans: are spots visible beyond each resolution ring?

    Rings are pre-drawn on the image, so the LLM answers yes/no questions
    instead of estimating numeric resolution from raw pixels.
    """

    frame: int = Field(ge=1)
    spots_beyond_5A: bool
    spots_beyond_3_5A: bool
    spots_beyond_2_5A: bool
    spots_beyond_2A: bool
    spots_beyond_1_5A: bool

    def beyond_flags(self) -> list[bool]:
        """Flags ordered like RESOLUTION_RINGS (5.0 -> 1.5)."""
        return [
            self.spots_beyond_5A,
            self.spots_beyond_3_5A,
            self.spots_beyond_2_5A,
            self.spots_beyond_2A,
            self.spots_beyond_1_5A,
        ]

    @model_validator(mode="after")
    def flags_must_be_monotonic(self) -> "SpotExtent":
        """If spots extend beyond a high-resolution ring, they must also
        extend beyond every lower-resolution ring."""
        flags = self.beyond_flags()
        for inner, outer in zip(flags, flags[1:]):
            if outer and not inner:
                raise ValueError(
                    f"frame {self.frame}: inconsistent extent flags "
                    f"(spots beyond a high-resolution ring require spots "
                    f"beyond all lower-resolution rings)"
                )
        return self


class VisionReport(BaseModel):
    """Top-level vision_report.json structure (schema_version 2.0).

    Deliberately contains NO twinning fields: twinning is judged by
    dedicated software (xtriage), never by this module.
    """

    schema_version: str
    frames_examined: list[int] = Field(min_length=1)
    per_frame_observations: list[FrameObservation] = Field(min_length=1)
    per_frame_spot_extent: list[SpotExtent] = Field(min_length=1)
    estimated_resolution_A: float | None = Field(default=None, gt=0)
    recommended_spot_ranges: list[tuple[int, int]] = Field(default_factory=list)
    quality_grade: QualityGrade
    caveats: str = ""

    @model_validator(mode="after")
    def check_consistency(self) -> "VisionReport":
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(
                f"unsupported schema_version {self.schema_version!r}; "
                f"expected {SCHEMA_VERSION!r}"
            )
        examined = set(self.frames_examined)
        if len(examined) != len(self.frames_examined):
            raise ValueError("frames_examined contains duplicates")
        for obs in self.per_frame_observations:
            if obs.frame not in examined:
                raise ValueError(
                    f"observation frame {obs.frame} not in frames_examined"
                )
        for extent in self.per_frame_spot_extent:
            if extent.frame not in examined:
                raise ValueError(
                    f"spot-extent frame {extent.frame} not in frames_examined"
                )
        lo, hi = min(examined), max(examined)
        for start, end in self.recommended_spot_ranges:
            if start > end:
                raise ValueError(
                    f"recommended_spot_ranges entry [{start}, {end}] is inverted"
                )
            if start < lo or end > hi:
                raise ValueError(
                    f"recommended_spot_ranges entry [{start}, {end}] lies "
                    f"outside examined frame span [{lo}, {hi}]"
                )
        return self


def load_vision_report(path: str | Path) -> VisionReport:
    """Load and validate vision_report.json. Raises ValueError on any problem."""
    path = Path(path)
    if not path.exists():
        raise ValueError(f"vision report not found: {path}")
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ValueError(f"vision report is not valid JSON: {exc}") from exc
    try:
        return VisionReport.model_validate(data)
    except Exception as exc:
        raise ValueError(f"vision report failed schema validation: {exc}") from exc


@dataclass(frozen=True)
class SupervisionReport:
    """Code-layer supervision result for an LLM-filled vision report.

    The LLM is the source of truth for visual judgment, but the code
    enforces structural and internal-consistency invariants. Each entry
    in `findings` is a human-readable string; non-empty `findings` means
    the report needs the LLM to fix something.
    """

    passed: bool
    findings: list[str] = field(default_factory=list)


def supervise_report(
    report: "VisionReport",
    expected_frame_span: tuple[int, int] | None = None,
    n_expected_windows: int | None = None,
) -> SupervisionReport:
    """Cross-check the LLM-filled report against the v2 invariants.

    Checks performed:
    1. `frames_examined` covers the same frames as `per_frame_observations`
       and `per_frame_spot_extent`
    2. `recommended_spot_ranges` does not include frames marked as
       streaky/diffuse (bad frames should be excluded)
    3. `quality_grade` is consistent with the observation mix:
       - grade A: no streaky or diffuse observations
       - grade B: at least one streaky/diffuse, but majority still good
       - grade C: many streaky/diffuse
    4. (optional) `frames_examined` spans the expected dataset range
    5. (optional) `frames_examined` length is a multiple of the window
       count — i.e. the LLM acknowledged every sliding-window montage
    """
    findings: list[str] = []

    # 1. coverage consistency
    examined = set(report.frames_examined)
    obs_frames = {o.frame for o in report.per_frame_observations}
    ext_frames = {e.frame for e in report.per_frame_spot_extent}
    if obs_frames - examined:
        findings.append(
            f"per_frame_observations has frames {sorted(obs_frames - examined)} "
            "not in frames_examined"
        )
    if ext_frames - examined:
        findings.append(
            f"per_frame_spot_extent has frames {sorted(ext_frames - examined)} "
            "not in frames_examined"
        )
    missing_obs = examined - obs_frames
    if missing_obs:
        findings.append(
            f"{len(missing_obs)} frames in frames_examined lack a per_frame_observation"
        )

    # 2. recommended_spot_ranges excludes bad-shape frames
    bad_frames = {
        o.frame
        for o in report.per_frame_observations
        if o.spot_shape in {SpotShape.STREAKY, SpotShape.DIFFUSE}
    }
    for s, e in report.recommended_spot_ranges:
        overlap = [f for f in bad_frames if s <= f <= e]
        if overlap:
            findings.append(
                f"recommended_spot_ranges entry [{s}, {e}] includes "
                f"streaky/diffuse frames {overlap}; should be excluded"
            )

    # 3. quality_grade consistency with observation mix
    n_obs = len(report.per_frame_observations)
    if n_obs:
        n_bad = sum(
            1
            for o in report.per_frame_observations
            if o.spot_shape in {SpotShape.STREAKY, SpotShape.DIFFUSE}
        )
        bad_frac = n_bad / n_obs
        grade = report.quality_grade
        if grade == QualityGrade.A and n_bad > 0:
            findings.append(
                f"quality_grade=A but {n_bad}/{n_obs} frames marked "
                "streaky or diffuse; grade should be B or C"
            )
        elif grade == QualityGrade.C and bad_frac < 0.3:
            findings.append(
                f"quality_grade=C but only {n_bad}/{n_obs} frames are "
                "streaky/diffuse (<30%); grade should be B"
            )
        elif grade == QualityGrade.B and bad_frac == 0:
            findings.append(
                "quality_grade=B but no streaky/diffuse frames; "
                "grade should be A"
            )
        elif grade == QualityGrade.B and bad_frac > 0.5:
            findings.append(
                f"quality_grade=B but {n_bad}/{n_obs} bad frames (>50%); "
                "grade should be C"
            )

    # 4. expected span (optional)
    if expected_frame_span is not None and report.frames_examined:
        lo, hi = expected_frame_span
        if min(report.frames_examined) < lo or max(report.frames_examined) > hi:
            findings.append(
                f"frames_examined [{min(report.frames_examined)}, "
                f"{max(report.frames_examined)}] falls outside expected "
                f"dataset span [{lo}, {hi}]"
            )

    # 5. windows acknowledged (optional)
    if n_expected_windows is not None and report.frames_examined:
        if len(report.frames_examined) % n_expected_windows != 0:
            # not a hard fail, but worth flagging
            findings.append(
                f"frames_examined count ({len(report.frames_examined)}) is not "
                f"a multiple of n_expected_windows ({n_expected_windows}); "
                "did the LLM skip some sliding-window montages?"
            )

    return SupervisionReport(passed=not findings, findings=findings)


def report_path_for_project(project_dir: str | Path) -> Path:
    """Canonical location of the vision report inside a project directory."""
    return Path(project_dir) / "vision_report.json"

"""Strict code-backed decision logic for crystallographic branching decisions.

Skill documentation should schedule these functions, not duplicate the logic.
"""

from dataclasses import dataclass, field
from enum import StrEnum
import re
from statistics import median as _median

from xtal_agent.vision_schema import (
    RESOLUTION_RINGS,
    SpotExtent,
    SpotShape,
    VisionReport,
)


class FixAction(StrEnum):
    ADJUST_PIXELS = "adjust_pixels"
    SHIFT_SPOT_RANGE = "shift_spot_range"
    DECREASE_SPOT_RANGE = "decrease_spot_range"
    LOW_RESOLUTION_LIMIT = "low_resolution_limit"
    CORRECT_ONLY = "correct_only"
    REMOVE_IDXREF = "remove_idxref"
    STOP_SIMPLE_MODE = "stop_simple_mode"


class SGConflictAction(StrEnum):
    NO_CONFLICT = "no_conflict"
    RETRY_XDS_WITH_NEW_SG = "retry_xds_with_new_sg"
    ACCEPT_NEW_SG = "accept_new_sg"
    PARALLEL_BRANCHES = "parallel_branches"


class FixOutcome(StrEnum):
    RETRY_XDS = "retry_xds"
    STOP = "stop"


@dataclass(frozen=True)
class SGConflictResult:
    action: SGConflictAction
    reason: str


@dataclass(frozen=True)
class FixResult:
    action: FixAction
    value: str
    result: FixOutcome


_IDXREF_FIX_PIXELS = [8, 7, 6, 5, 4, 3]
_LOW_RES_LIMITS = [50, 40, 30, 20]

# Outer-shell Mn(I/sd) upper bound: when the data is still this strong at the
# current resolution cutoff, the resolution limit was set too low and the
# workflow must return to Phase 1 (XDS/DIALS) to integrate to higher resolution.
OUTER_SHELL_MNISD_UPPER = 2.5


def _parse_range(range_str: str) -> tuple[int, int] | None:
    for sep in (" ", "-"):
        parts = range_str.split(sep)
        if len(parts) == 2:
            try:
                return int(parts[0]), int(parts[1])
            except ValueError:
                continue
    return None


def idxref_failure_fix(
    attempt: int,
    current_pixels: int,
    current_spot_range: str,
    simple_mode: bool = True,
) -> FixResult:
    """Return the next fix action when IDXREF fails, following the exact priority order.

    Priority: 1) adjust MINIMUM_NUMBER_OF_PIXELS_IN_A_SPOT (3-8)
              2) shift/decrease SPOT_RANGE
              3) low-resolution limits (50-20), simple-mode stop at 30
    Never returns FixAction.REMOVE_IDXREF.
    In simple mode, stops before CORRECT-only or resolution limits below 30.
    """
    pixel_index = _IDXREF_FIX_PIXELS.index(current_pixels) + 1 if current_pixels in _IDXREF_FIX_PIXELS else 0

    if pixel_index < len(_IDXREF_FIX_PIXELS):
        return FixResult(
            action=FixAction.ADJUST_PIXELS,
            value=str(_IDXREF_FIX_PIXELS[pixel_index]),
            result=FixOutcome.RETRY_XDS,
        )

    parsed = _parse_range(current_spot_range)
    if parsed and attempt - pixel_index <= 3:
        start, end = parsed
        width = end - start
        if width > 100:
            shift_amount = min(200, width // 10)
            new_end = end - shift_amount
            return FixResult(
                action=FixAction.DECREASE_SPOT_RANGE,
                value=f"{start} {new_end}",
                result=FixOutcome.RETRY_XDS,
            )
        elif width > 2 * max(50, width // 5):
            shift_amount = max(50, width // 5)
            return FixResult(
                action=FixAction.DECREASE_SPOT_RANGE,
                value=f"{start + shift_amount} {end - shift_amount}",
                result=FixOutcome.RETRY_XDS,
            )

    low_res_index = min(attempt - (len(_IDXREF_FIX_PIXELS) - pixel_index + 2), len(_LOW_RES_LIMITS) - 1)
    low_res_value = _LOW_RES_LIMITS[max(0, low_res_index)]

    if simple_mode and low_res_value <= 30:
        return FixResult(
            action=FixAction.STOP_SIMPLE_MODE,
            value=f"{low_res_value}",
            result=FixOutcome.STOP,
        )

    if low_res_index < len(_LOW_RES_LIMITS):
        return FixResult(
            action=FixAction.LOW_RESOLUTION_LIMIT,
            value=str(low_res_value),
            result=FixOutcome.RETRY_XDS,
        )

    if simple_mode:
        return FixResult(
            action=FixAction.STOP_SIMPLE_MODE,
            value="20",
            result=FixOutcome.STOP,
        )

    return FixResult(
        action=FixAction.LOW_RESOLUTION_LIMIT,
        value="20",
        result=FixOutcome.STOP,
    )


@dataclass(frozen=True)
class DataRangeMosaicity:
    frames: list[int]
    mosaicity_values: list[float]


@dataclass(frozen=True)
class DataRangeCandidate:
    start_frame: int
    end_frame: int
    preferred: bool


def sg_conflict_resolution(
    xds_sg: str,
    aimless_sg: str,
    xds_retry_successful: bool | None,
) -> SGConflictResult:
    """Resolve a space group mismatch between XDS and aimless/pointless.

    Order of operations:
    1. If SGs match, no conflict.
    2. If SGs differ and aimless validated:
       a. First, retry XDS with the new SG from aimless.
       b. If XDS succeeds with the new SG, accept it — do not run parallel branches.
       c. If XDS fails with the new SG, fall back to parallel branch comparison.

    Users of this function must first call it with xds_retry_successful=None
    to get RETRY_XDS_WITH_NEW_SG, then run XDS, then call again with
    xds_retry_successful=True/False to get the final action.
    """
    xds_clean = xds_sg.strip().replace(" ", "")
    aimless_clean = aimless_sg.strip().replace(" ", "")

    if xds_clean == aimless_clean:
        return SGConflictResult(
            action=SGConflictAction.NO_CONFLICT,
            reason="SGs match",
        )

    if xds_retry_successful is None:
        return SGConflictResult(
            action=SGConflictAction.RETRY_XDS_WITH_NEW_SG,
            reason=f"Aimless/Poinless SG ({aimless_sg}) differs from XDS SG ({xds_sg}). Retry XDS with new SG.",
        )

    if xds_retry_successful:
        return SGConflictResult(
            action=SGConflictAction.ACCEPT_NEW_SG,
            reason=f"XDS retry with SG {aimless_sg} succeeded. Accept new result.",
        )

    return SGConflictResult(
        action=SGConflictAction.PARALLEL_BRANCHES,
        reason=f"XDS retry with SG {aimless_sg} failed. Run parallel Phaser+refinement comparison for {xds_sg} vs {aimless_sg}.",
    )


def suggest_data_range_from_mosaicity(
    mosaicity: DataRangeMosaicity,
    full_data_range: str,
) -> DataRangeCandidate:
    """Select DATA_RANGE frames where mosaicity is below the median.

    Prefer below-median segments; maximize data included.
    """
    if not mosaicity.mosaicity_values:
        parts = full_data_range.split()
        return DataRangeCandidate(
            start_frame=int(parts[0]) if parts else 1,
            end_frame=int(parts[1]) if len(parts) > 1 else 1,
            preferred=False,
        )

    median = _median(mosaicity.mosaicity_values)

    good_frames = [f for f, m in zip(mosaicity.frames, mosaicity.mosaicity_values) if m <= median]
    if not good_frames:
        parts = full_data_range.split()
        return DataRangeCandidate(
            start_frame=int(parts[0]) if parts else 1,
            end_frame=int(parts[1]) if len(parts) > 1 else 1,
            preferred=False,
        )

    return DataRangeCandidate(
        start_frame=min(good_frames),
        end_frame=max(good_frames),
        preferred=True,
    )


@dataclass(frozen=True)
class TwinningScanResult:
    full_data_range: str
    full_sg: str
    subsets: list["TwinningScanResult"] = field(default_factory=list)
    different_sg_detected: bool = False
    subset_sg: str = ""
    improved_aimless: bool = False

    def best_lower_symmetry_subset(self) -> "TwinningScanResult | None":
        """Return the subset with the most compelling evidence for lower-symmetry SG.

        Prefers subsets where different_sg_detected=True AND improved_aimless=True,
        selecting the narrowest range among them.
        """
        candidates = [
            s for s in self.subsets
            if s.different_sg_detected and s.improved_aimless
        ]
        if not candidates:
            candidates = [s for s in self.subsets if s.different_sg_detected]

        if not candidates:
            return None

        candidates.sort(key=lambda s: int(s.full_data_range.split()[-1]) - int(s.full_data_range.split()[0]))
        return candidates[0]


class PhaserStrength(StrEnum):
    STRONG = "strong"
    BORDERLINE = "borderline"
    WEAK = "weak"


class PhaserFailAction(StrEnum):
    BROADEN_SG = "broaden_sg"
    CHECK_POINTLESS_AIMLESS = "check_pointless_aimless"
    TRY_DIFFERENT_MODEL = "try_different_model"
    STOP = "stop"


@dataclass(frozen=True)
class MatthewsResult:
    cell_volume: float
    sequence_mw: float
    vm_min: float = 1.7
    vm_max: float = 3.5
    vm_opt: float = 2.2
    sg_number: int = 1

    @property
    def z(self) -> int:
        return _z_for_sg(self.sg_number)

    @property
    def asu_volume(self) -> float:
        return self.cell_volume / self.z

    @property
    def plausible_copies(self) -> list[int]:
        """All integer copy numbers in the plausible V_M range, sorted by
        probability (closest to optimal V_M first)."""
        scored: list[tuple[int, float]] = []
        for n in range(1, 100):
            vm = self.asu_volume / (self.sequence_mw * n)
            if self.vm_min <= vm <= self.vm_max:
                score = abs(vm - self.vm_opt)
                scored.append((n, score))
        scored.sort(key=lambda x: x[1])
        return [n for n, _ in scored]

    @property
    def top_copies(self) -> list[int]:
        """Top 3 most probable copy numbers (closest to optimal V_M)."""
        return self.plausible_copies[:3]

    @property
    def full_range(self) -> list[int]:
        return self.plausible_copies


def _z_for_sg(sg_number: int) -> int:
    """Number of asymmetric units per unit cell for a given space group number.

    Accurate Z values for common protein space groups. Falls back to a
    conservative-minimum heuristic for uncommon SG numbers.
    """
    if sg_number in (1, 2):
        return 1
    if 3 <= sg_number <= 15:
        if sg_number in (5, 6, 7, 8, 9, 15):
            return 4
        return 2
    if 16 <= sg_number <= 74:
        if sg_number in (21, 22, 23, 24):
            return 8
        if sg_number in (42, 43, 69, 70):
            return 16
        return 4
    if 75 <= sg_number <= 142:
        if sg_number in (79, 80, 97, 98, 133, 134, 135, 136, 137, 138, 141, 142):
            return 8
        if 89 <= sg_number <= 96:
            return 8
        return 4
    if 143 <= sg_number <= 194:
        if sg_number in (146, 148, 155, 160, 161, 166, 167):
            return 3
        return 6
    if 195 <= sg_number <= 230:
        return 12
    return 1


@dataclass(frozen=True)
class PhaserSolution:
    copy_num: int
    tfz: float
    llg: float
    pak: int
    all_placed: bool


@dataclass(frozen=True)
class PhaserSweepResult:
    solutions: list[PhaserSolution]


def matthews_copy_range(cell_volume: float, sequence_mw: float, sg_number: int = 1) -> MatthewsResult:
    return MatthewsResult(cell_volume=cell_volume, sequence_mw=sequence_mw, sg_number=sg_number)


def interpret_phaser_result(solution: PhaserSolution) -> PhaserStrength:
    if solution.all_placed and solution.pak <= 1 and solution.tfz > 8 and solution.llg > 200:
        return PhaserStrength.STRONG
    if solution.tfz >= 6 and solution.llg >= 100 and solution.pak <= 2:
        return PhaserStrength.BORDERLINE
    return PhaserStrength.WEAK


def select_best_copy_number(sweep: PhaserSweepResult) -> PhaserSolution | None:
    strong = [s for s in sweep.solutions if interpret_phaser_result(s) == PhaserStrength.STRONG and s.pak == 0 and s.all_placed]
    if strong:
        return max(strong, key=lambda s: s.tfz)
    strong_any = [s for s in sweep.solutions if interpret_phaser_result(s) == PhaserStrength.STRONG]
    if strong_any:
        return max(strong_any, key=lambda s: s.tfz)
    borderline = [s for s in sweep.solutions if interpret_phaser_result(s) == PhaserStrength.BORDERLINE]
    if borderline:
        return max(borderline, key=lambda s: s.tfz)
    return None


def phaser_troubleshooting_order(failure_count: int) -> PhaserFailAction:
    if failure_count <= 1:
        return PhaserFailAction.BROADEN_SG
    if failure_count == 2:
        return PhaserFailAction.CHECK_POINTLESS_AIMLESS
    if failure_count == 3:
        return PhaserFailAction.TRY_DIFFERENT_MODEL
    return PhaserFailAction.STOP


@dataclass(frozen=True)
class TwinLawCandidate:
    operator: str
    fraction: float | None = None


class RfreeTrend(StrEnum):
    DECREASING = "decreasing"
    PLATEAU = "plateau"
    NOT_ENOUGH_DATA = "not_enough_data"


class RfreeAction(StrEnum):
    CONTINUE = "continue"
    SWITCH_SOFTWARE = "switch_software"
    TRY_TWIN_REFINEMENT = "try_twin_refinement"
    STOP_USER_INTERVENTION = "stop_user_intervention"


class PredictionTool(StrEnum):
    AF2 = "AF2"
    AF3 = "AF3"


class PredictionRequires(StrEnum):
    NONE = "none"
    USER_GLYCAN_INFO = "user_glycan_info"
    USER_METAL_INFO = "user_metal_info"
    STOP_SIMPLE_MODE = "stop_simple_mode"


_UNSUPPORTED_METALS = {
    "Mo", "W", "V", "Se", "Te", "Pt", "Hg", "Au", "Ag", "Cd", "Pb", "As", "U",
}


@dataclass(frozen=True)
class PredictionDecision:
    tool: PredictionTool
    requires: PredictionRequires = PredictionRequires.NONE
    predict_per_chain: bool = False
    reason: str = ""


def select_prediction_tool(
    is_glycoprotein: bool = False,
    is_metalloprotein: bool = False,
    metal_species: str = "",
    is_protein_nucleic_acid: bool = False,
    is_protein_ligand: bool = False,
    is_hetero_oligomer: bool = False,
) -> PredictionDecision:
    """Return the required prediction tool and any mandatory user input."""
    if is_glycoprotein:
        return PredictionDecision(
            tool=PredictionTool.AF3,
            requires=PredictionRequires.USER_GLYCAN_INFO,
            reason="Glycoproteins require AF3 with glycan CCD codes and covalent bonds.",
        )
    if is_protein_nucleic_acid:
        return PredictionDecision(
            tool=PredictionTool.AF3,
            reason="Protein-nucleic acid complexes require AF3 complex prediction.",
        )
    if is_metalloprotein:
        if metal_species and metal_species.strip() in _UNSUPPORTED_METALS:
            return PredictionDecision(
                tool=PredictionTool.AF2,
                requires=PredictionRequires.STOP_SIMPLE_MODE,
                reason=f"Unsupported metal ion {metal_species}. Stop in simple mode.",
            )
        return PredictionDecision(
            tool=PredictionTool.AF3,
            requires=PredictionRequires.USER_METAL_INFO,
            reason=f"Supported metalloprotein (ion: {metal_species or 'unknown'}). Use AF3.",
        )
    if is_protein_ligand:
        return PredictionDecision(
            tool=PredictionTool.AF3,
            reason="Protein-ligand complex: use AF3 with --ligands or --ligands-smiles.",
        )
    if is_hetero_oligomer:
        return PredictionDecision(
            tool=PredictionTool.AF2,
            predict_per_chain=True,
            reason="Hetero-oligomer: predict distinct chains separately with AF2.",
        )
    return PredictionDecision(
        tool=PredictionTool.AF2,
        reason="Ordinary single-chain protein: use AF2.",
    )


@dataclass(frozen=True)
class RfreeSample:
    round: int
    software: str
    rfree: float


def extract_twin_laws_from_xtriage(text: str) -> list[TwinLawCandidate]:
    """Extract twin laws and fractions from phenix.xtriage output."""
    results: list[TwinLawCandidate] = []
    operators: list[str] = []
    fractions: list[float] = []

    for line in text.splitlines():
        m = re.search(r"^\s*Twin law:\s*([()\w,\-\+]+)", line, re.IGNORECASE)
        if m:
            op = m.group(1).strip()
            if op and op not in operators:
                operators.append(op)
        m = re.search(r"^\s*([()\w,\-\+]+)\s*\(?(merohedral|pseudo.merohedral|twin)\)?", line, re.IGNORECASE)
        if m:
            op = m.group(1).strip()
            if op and "," in op and not op.startswith("Twin") and op not in operators:
                operators.append(op)
        m = re.search(r"Twin fraction:\s*([\d.]+)", line, re.IGNORECASE)
        if m:
            fractions.append(float(m.group(1)))

    for i, op in enumerate(operators):
        frac = fractions[i] if i < len(fractions) else None
        results.append(TwinLawCandidate(operator=op, fraction=frac))

    return results


def detect_rfree_plateau(samples: list[RfreeSample]) -> RfreeTrend:
    """Detect Rfree plateau: if round B > round A and round C >= round A, plateau reached.

    Operates on the last 3 samples. Requires at least 3 rounds.
    """
    if len(samples) < 3:
        return RfreeTrend.NOT_ENOUGH_DATA
    a, b, c = samples[-3], samples[-2], samples[-1]
    if b.rfree > a.rfree and c.rfree >= a.rfree:
        return RfreeTrend.PLATEAU
    return RfreeTrend.DECREASING


def should_use_twin_refinement(twin_laws: list[TwinLawCandidate]) -> bool:
    return len(twin_laws) > 0


def high_rfree_diagnosis(
    rfree: float,
    current_software: str,
    software_already_tried: list[str],
    twin_laws: list[TwinLawCandidate],
) -> RfreeAction:
    """Decide next action when Rfree is high.

    Rule:
    - Rfree <= 0.35: CONTINUE
    - Rfree > 0.35, twin laws available, not yet tried: TRY_TWIN_REFINEMENT
    - Rfree > 0.35, first occurrence with this software, other software not tried: SWITCH_SOFTWARE
    - Rfree > 0.35, both software tried: STOP_USER_INTERVENTION
    """
    if rfree <= 0.35:
        return RfreeAction.CONTINUE

    if twin_laws and (current_software not in software_already_tried or not software_already_tried):
        return RfreeAction.TRY_TWIN_REFINEMENT

    other = "refmac" if current_software == "phenix" else "phenix"
    if other not in software_already_tried:
        return RfreeAction.SWITCH_SOFTWARE

    return RfreeAction.STOP_USER_INTERVENTION


# ---------------------------------------------------------------------------
# Aimless resolution validation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ShellStats:
    shell: int
    dmid: float  # resolution in A
    cc_half: float  # CC(1/2) as fraction (0.961 means 96.1%)
    mn_isd: float  # Mn(I/sd)
    rmeas: float
    rmerge: float
    completeness: float  # %poss


@dataclass(frozen=True)
class ResolutionValidation:
    outer_shell: ShellStats  # highest-resolution shell passing ALL thresholds
    outer_resolution: float  # dmid of the outer shell, in A
    overall_cc_half: float
    overall_mn_isd: float
    overall_completeness: float
    inner_cc_half: float
    inner_mn_isd: float
    validated: bool
    # True when the outer shell Mn(I/sd) is ABOVE the upper bound (2.5),
    # i.e. the resolution limit was set too conservatively. The workflow must
    # return to Phase 1 (XDS/DIALS) and integrate to higher resolution.
    resolution_too_low: bool = False


def validate_resolution_from_aimless(
    aimless_log_text: str,
    total_frames: int = 999,
) -> ResolutionValidation:
    """Parse aimless.log per-shell statistics and determine the validated
    resolution cutoff where all 5 fixed thresholds are met.

    Merges three per-shell tables (CC1/2, Rmerge/Rmeas/Mn(I/sd), completeness)
    by Dmid, then walks shells from low to high resolution. Returns the
    highest-resolution shell that passes every test.
    """
    cc_table = _parse_aimless_cc_table(aimless_log_text)
    r_table = _parse_aimless_r_table(aimless_log_text)
    comp_table = _parse_aimless_completeness_table(aimless_log_text)

    merged = _merge_aimless_tables(cc_table, r_table, comp_table)
    if not merged:
        return ResolutionValidation(
            outer_shell=ShellStats(0, 99.0, 0, 0, 0, 0, 0),
            outer_resolution=99.0,
            overall_cc_half=0,
            overall_mn_isd=0,
            overall_completeness=0,
            inner_cc_half=0,
            inner_mn_isd=0,
            validated=False,
        )

    completeness_exempt = total_frames < 180

    passing: list[ShellStats] = []
    for s in merged:
        cc_ok = s.cc_half > 0.40
        mn_ok = s.mn_isd > 1.6
        rmeas_ok = s.rmeas < 1.8
        rmerge_ok = s.rmerge < 2.0
        comp_ok = completeness_exempt or s.completeness > 70.0
        if cc_ok and mn_ok and rmeas_ok and rmerge_ok and comp_ok:
            passing.append(s)

    if not passing:
        return ResolutionValidation(
            outer_shell=merged[0],
            outer_resolution=merged[0].dmid,
            overall_cc_half=0,
            overall_mn_isd=0,
            overall_completeness=0,
            inner_cc_half=merged[0].cc_half,
            inner_mn_isd=merged[0].mn_isd,
            validated=False,
        )

    outer = passing[-1]  # highest-resolution shell that passes
    inner = merged[0]

    # Upper bound on outer-shell Mn(I/sd): when the data is still this strong
    # at the current cutoff, the resolution limit was set too low. The
    # workflow must return to Phase 1 (XDS/DIALS) and integrate to higher
    # resolution before Phase 2 can be accepted.
    resolution_too_low = outer.mn_isd > OUTER_SHELL_MNISD_UPPER

    n_passing = len(passing)
    w_sum = sum(s.mn_isd * (s.completeness / 100) for s in passing)
    w_total = sum(s.completeness / 100 for s in passing)
    overall_mn = w_sum / w_total if w_total > 0 else 0.0

    cc_sum = sum(s.cc_half for s in passing)
    overall_cc = cc_sum / n_passing

    comp_sum = sum(s.completeness for s in passing)
    overall_comp = comp_sum / n_passing

    return ResolutionValidation(
        outer_shell=outer,
        outer_resolution=outer.dmid,
        overall_cc_half=round(overall_cc * 100, 1),
        overall_mn_isd=round(overall_mn, 1),
        overall_completeness=round(overall_comp, 1),
        inner_cc_half=round(inner.cc_half * 100, 1),
        inner_mn_isd=inner.mn_isd,
        validated=not resolution_too_low,
        resolution_too_low=resolution_too_low,
    )


def _parse_aimless_cc_table(text: str) -> list[dict]:
    """Extract per-shell CC(1/2) values from the first ``CC(1/2)`` block.

    Stops at the first ``$$`` or ``Overall:`` line encountered *after*
    data rows have been collected.
    """
    lines = text.splitlines()
    in_table = False
    rows: list[dict] = []
    for line in lines:
        stripped = line.strip()
        if "$TABLE:" in line and "CC(1/2)" in line:
            in_table = True
            continue
        if not in_table:
            continue
        if stripped.startswith("$") or stripped.startswith(":"):
            continue
        if not stripped:
            continue
        # Stop at trailing $$ or Overall after data was seen
        if (stripped == "$$" or stripped.startswith("Overall")) and rows:
            break
        parts = stripped.split()
        if len(parts) < 7:
            continue
        if not parts[0].isdigit():
            continue
        try:
            rows.append({
                "shell": int(parts[0]),
                "dmid": float(parts[2]),
                "cc_half": float(parts[6]),
            })
        except (ValueError, IndexError):
            continue
    return rows


def _parse_aimless_r_table(text: str) -> list[dict]:
    """Extract per-shell Rmerge / Rmeas / Mn(I/sd) from the first
    resolution-binned table (within I+/I- table, not anomalous "Ov").

    The target table is prefixed by a ``:``-line (no ``$GRAPHS``) with
    the pattern ``:Rmerge, Rfull, Rmeas, Rpim v Resolution``.
    """
    lines = text.splitlines()
    for start, line in enumerate(lines):
        if not line.strip().startswith(":Rmerge, Rfull, Rmeas, Rpim"):
            continue
        rows: list[dict] = []
        for ahead in lines[start + 1:]:
            stripped = ahead.strip()
            if not stripped:
                continue
            if stripped == "$$" and rows:
                break
            if stripped.startswith("$") or stripped.startswith(":"):
                continue
            parts = stripped.split()
            if len(parts) < 14:
                continue
            if not parts[0].isdigit():
                continue
            if "Mn(I/sd)" in stripped:
                continue  # column header
            try:
                rows.append({
                    "shell": int(parts[0]),
                    "dmid": float(parts[2]),
                    "rmerge": float(parts[3]),
                    "rmeas": float(parts[6]),
                    "mn_isd": float(parts[13]),
                })
            except (ValueError, IndexError):
                continue
        if rows and any(r.get("mn_isd", 0) > 0 for r in rows):
            return rows
    return []


def _parse_aimless_completeness_table(text: str) -> list[dict]:
    """Extract per-shell completeness (%poss).

    Locates ``$TABLE: Completeness & multiplicity v. resolution`` and
    stops at the first ``$$`` or ``Overall:`` after data rows.
    """
    lines = text.splitlines()
    in_table = False
    rows: list[dict] = []
    for line in lines:
        stripped = line.strip()
        if "$TABLE:" in line and "Completeness" in line:
            in_table = True
            continue
        if not in_table:
            continue
        if stripped.startswith("$") or stripped.startswith(":"):
            continue
        if not stripped:
            continue
        if (stripped == "$$" or stripped.startswith("Overall")) and rows:
            break
        parts = stripped.split()
        if len(parts) < 7:
            continue
        if not parts[0].isdigit():
            continue
        try:
            rows.append({
                "shell": int(parts[0]),
                "dmid": float(parts[2]),
                "completeness": float(parts[6]),
            })
        except (ValueError, IndexError):
            continue
    return rows


def _merge_aimless_tables(
    cc: list[dict],
    r_table: list[dict],
    comp: list[dict],
) -> list[ShellStats]:
    cc_by_n = {row["shell"]: row for row in cc}
    r_by_n = {row["shell"]: row for row in r_table}
    comp_by_n = {row["shell"]: row for row in comp}

    merged: list[ShellStats] = []
    for n in sorted(set(cc_by_n) & set(r_by_n)):
        cc_row = cc_by_n[n]
        r_row = r_by_n[n]
        comp_row = comp_by_n.get(n)
        completeness = comp_row["completeness"] if comp_row else 100.0
        merged.append(ShellStats(
            shell=n,
            dmid=cc_row["dmid"],
            cc_half=cc_row["cc_half"],
            mn_isd=r_row["mn_isd"],
            rmeas=r_row["rmeas"],
            rmerge=r_row["rmerge"],
            completeness=completeness,
        ))
    return merged


# ---------------------------------------------------------------------------
# Low-resolution refinement branch
# ---------------------------------------------------------------------------

LOW_RES_THRESHOLD = 3.6

@dataclass(frozen=True)
class LowResDecision:
    is_low_res: bool
    resolution: float
    mode: str  # "simple" or "expert"


def detect_low_resolution(validated_resolution: float, mode: str) -> LowResDecision:
    """Determine whether to enter the low-resolution refinement branch.

    Trigger: resolution >= LOW_RES_THRESHOLD (3.6 Å).

    Simple mode: auto-enter the low-resolution branch.
    Expert mode: the decision is deferred to user (caller must prompt).
    """
    return LowResDecision(
        is_low_res=validated_resolution >= LOW_RES_THRESHOLD,
        resolution=validated_resolution,
        mode=mode,
    )


@dataclass(frozen=True)
class LowResRefineStrategy:
    phase: str  # "phase5_lowres" or "phase5"
    rigid_body: bool
    phenix_grouped: bool
    refmac_jelly: bool
    refmac_free: bool
    modelcraft_eligible: bool
    reason: str


def select_low_res_refine_strategy(
    is_low_res: bool, expert_mode: bool, user_accepted: bool = False
) -> LowResRefineStrategy:
    """Select the refinement strategy based on resolution and mode.

    Low-resolution strategy (>= 3.6 Å):
      1. Rigid body optimization
      2. Phenix grouped ADP x4 (skip if no improvement over rigid body)
      3. Refmac jelly x2 + free x2 (from MR model if phenix failed)
      4. Modelcraft (if Rfree <= 0.35 after refmac)
      5. RSC cleanup → delete garbage chains
      6. Phenix rotamer + secondary structure restraint optimization
      7. User selects final → MolProbity → archive

    Normal strategy (< 3.6 Å):
      Standard Phase 5 refinement pipeline.
    """
    if is_low_res:
        if not expert_mode:
            return LowResRefineStrategy(
                phase="phase5_lowres",
                rigid_body=True,
                phenix_grouped=True,
                refmac_jelly=True,
                refmac_free=True,
                modelcraft_eligible=True,
                reason="Resolution >= 3.6 Å, simple mode: auto-entering low-resolution branch",
            )
        if user_accepted:
            return LowResRefineStrategy(
                phase="phase5_lowres",
                rigid_body=True,
                phenix_grouped=True,
                refmac_jelly=True,
                refmac_free=True,
                modelcraft_eligible=True,
                reason="Resolution >= 3.6 Å, expert mode: user accepted low-resolution branch",
            )
        return LowResRefineStrategy(
            phase="phase5",
            rigid_body=False,
            phenix_grouped=False,
            refmac_jelly=True,
            refmac_free=True,
            modelcraft_eligible=False,
            reason="Resolution >= 3.6 Å, expert mode: user declined low-resolution branch, falling back to standard",
        )
    return LowResRefineStrategy(
        phase="phase5",
        rigid_body=False,
        phenix_grouped=False,
        refmac_jelly=True,
        refmac_free=True,
        modelcraft_eligible=True,
        reason="Resolution < 3.6 Å: standard Phase 5 refinement",
    )


# ---------------------------------------------------------------------------
# Vision module decision functions
# ---------------------------------------------------------------------------


class RadiationDamageLevel(StrEnum):
    NONE = "none"
    MILD = "mild"
    SIGNIFICANT = "significant"


@dataclass(frozen=True)
class ResolutionCurve:
    """Per-frame upper-resolution estimates derived from spot extents."""

    frames: list[int]
    resolutions: list[float]  # Å, aligned with frames


@dataclass(frozen=True)
class RadiationDamageAssessment:
    """Reference-only output. Must never become a downstream parameter.

    v2 update: shape degradation (streaky frame ratio rise) is folded into
    the verdict. Radiation damage may manifest FIRST as spot elongation /
    streaking and only later as resolution limit retreat. The LLM still
    observes the JPGs; this function consumes the LLM-filled report only.
    """

    level: RadiationDamageLevel
    first_segment_mean: float
    last_segment_mean: float
    degradation_A: float
    first_segment_streaky_ratio: float
    last_segment_streaky_ratio: float
    streaky_ratio_rise: float
    reason: str


@dataclass(frozen=True)
class SpotRangeSuggestion:
    start_frame: int
    end_frame: int
    preferred: bool  # False when falling back to the default first-half range
    reason: str


def resolution_from_spot_extent(extent: "SpotExtent") -> float:
    """Estimate one frame's upper resolution from its ring booleans.

    Conservative rule: the estimate is the ring value of the outermost ring
    that still has spots beyond it. If no ring is crossed, the data does not
    extend beyond the innermost ring; report that ring's value.
    """
    flags = extent.beyond_flags()  # ordered like RESOLUTION_RINGS (5.0 -> 1.5)
    estimate = RESOLUTION_RINGS[0]
    for ring, crossed in zip(RESOLUTION_RINGS, flags):
        if crossed:
            estimate = ring
    return estimate


def per_frame_resolution_curve(report: "VisionReport") -> ResolutionCurve:
    """Build the frame -> resolution curve from all sampled extents."""
    frames: list[int] = []
    resolutions: list[float] = []
    for extent in sorted(report.per_frame_spot_extent, key=lambda e: e.frame):
        frames.append(extent.frame)
        resolutions.append(resolution_from_spot_extent(extent))
    return ResolutionCurve(frames=frames, resolutions=resolutions)


def assess_radiation_damage(
    curve: ResolutionCurve,
    shape_trend: list[tuple[int, str]] | None = None,
) -> RadiationDamageAssessment:
    """Estimate radiation damage across the sweep.

    v2 update: in addition to resolution degradation, fold in the
    shape-trend signal (fraction of streaky / diffuse frames in the
    first vs last third of the sweep). Radiation damage may manifest
    FIRST as spot elongation / streaking and only later as resolution
    limit retreat — pure resolution curves miss this.

    shape_trend: optional list of (frame, spot_shape) tuples from the
    LLM-filled report. Each spot_shape must be a SpotShape enum value
    (typically "round", "slightly_elongated", "streaky", "diffuse").
    The function is robust to a missing/short trend.

    Reference-only: the result flows to reports, never to parameters.
    """
    n = len(curve.resolutions)
    if n < 3:
        return RadiationDamageAssessment(
            level=RadiationDamageLevel.NONE,
            first_segment_mean=curve.resolutions[0] if n else 0.0,
            last_segment_mean=curve.resolutions[-1] if n else 0.0,
            degradation_A=0.0,
            first_segment_streaky_ratio=0.0,
            last_segment_streaky_ratio=0.0,
            streaky_ratio_rise=0.0,
            reason="fewer than 3 sampled frames; cannot assess degradation",
        )
    third = max(1, n // 3)
    first = curve.resolutions[:third]
    last = curve.resolutions[-third:]
    first_mean = sum(first) / len(first)
    last_mean = sum(last) / len(last)
    degradation = last_mean - first_mean

    # shape degradation: fraction of streaky+diffuse frames in first vs last third
    first_streaky = 0.0
    last_streaky = 0.0
    if shape_trend:
        sorted_trend = sorted(shape_trend, key=lambda x: x[0])
        bad_shapes = {SpotShape.STREAKY, SpotShape.DIFFUSE}
        n_first = max(1, third)
        n_last = max(1, third)
        first_streaky = sum(
            1 for _, sh in sorted_trend[:third] if str(sh) in bad_shapes
        ) / n_first
        last_streaky = sum(
            1 for _, sh in sorted_trend[-third:] if str(sh) in bad_shapes
        ) / n_last
    streaky_rise = last_streaky - first_streaky

    # verdict: combine resolution and shape signals
    if degradation >= 0.8 or streaky_rise >= 0.5:
        level = RadiationDamageLevel.SIGNIFICANT
    elif degradation >= 0.3 or streaky_rise >= 0.25:
        level = RadiationDamageLevel.MILD
    else:
        level = RadiationDamageLevel.NONE

    reason = (
        f"first-segment mean {first_mean:.2f} A vs last-segment mean "
        f"{last_mean:.2f} A (degradation {degradation:.2f} A); "
        f"streaky-frame ratio first={first_streaky:.0%} "
        f"last={last_streaky:.0%} (rise {streaky_rise:+.0%})"
    )

    return RadiationDamageAssessment(
        level=level,
        first_segment_mean=round(first_mean, 3),
        last_segment_mean=round(last_mean, 3),
        degradation_A=round(degradation, 3),
        first_segment_streaky_ratio=round(first_streaky, 3),
        last_segment_streaky_ratio=round(last_streaky, 3),
        streaky_ratio_rise=round(streaky_rise, 3),
        reason=reason,
    )


def suggest_spot_range_from_vision(
    report: "VisionReport",
    full_data_range: str,
) -> SpotRangeSuggestion:
    """Suggest SPOT_RANGE from per-frame spot shapes.

    "Good" is relative to the dataset's own quality range. The LLM marks
    each frame as ROUND / SLIGHTLY_ELONGATED (good) or STREAKY / DIFFUSE
    (bad) compared to the best frames in that dataset. A weak diffraction
    dataset with uniform slight elongation across all frames should mark
    everything as SLIGHTLY_ELONGATED — not as STREAKY.

    The suggestion is the longest contiguous run of good-sampled frames,
    expanded to the span between its first and last good sample.

    Fallback: the default first half of DATA_RANGE (same behaviour as
    generate_XDS.INP today), marked preferred=False with the reason recorded.
    """
    parts = full_data_range.split()
    full_start = int(parts[0]) if parts else 1
    full_end = int(parts[1]) if len(parts) > 1 else full_start
    default_end = full_start + (full_end - full_start) // 2

    def _fallback(reason: str) -> SpotRangeSuggestion:
        return SpotRangeSuggestion(
            start_frame=full_start,
            end_frame=default_end,
            preferred=False,
            reason=reason,
        )

    good_shapes = {SpotShape.ROUND, SpotShape.SLIGHTLY_ELONGATED}
    observations = sorted(report.per_frame_observations, key=lambda o: o.frame)
    if not observations:
        return _fallback("no per-frame observations; using default first half")

    runs: list[tuple[int, int]] = []  # (first_frame, last_frame) per good run
    run_start: int | None = None
    last_frame: int | None = None
    for obs in observations:
        if obs.spot_shape in good_shapes:
            if run_start is None:
                run_start = obs.frame
            last_frame = obs.frame
        else:
            if run_start is not None and last_frame is not None:
                runs.append((run_start, last_frame))
            run_start = None
            last_frame = None
    if run_start is not None and last_frame is not None:
        runs.append((run_start, last_frame))

    if not runs:
        return _fallback("no contiguous good-shape segment found; using default")

    best = max(runs, key=lambda r: r[1] - r[0])
    if best[0] == best[1]:
        return _fallback(
            "only isolated good frames found; too sparse for a SPOT_RANGE suggestion"
        )

    return SpotRangeSuggestion(
        start_frame=best[0],
        end_frame=best[1],
        preferred=True,
        reason=(
            f"longest contiguous segment with round/slightly-elongated spots: "
            f"frames {best[0]}-{best[1]}"
        ),
    )

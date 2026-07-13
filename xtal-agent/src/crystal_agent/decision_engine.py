"""Strict code-backed decision logic for crystallographic branching decisions.

Skill documentation should schedule these functions, not duplicate the logic.
"""

from dataclasses import dataclass, field
from enum import StrEnum
import re
from statistics import median as _median


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

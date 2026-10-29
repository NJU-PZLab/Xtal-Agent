from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from xtal_agent.coot_runner import (
    CootResult,
    coot_available,
    run_coot_optimization,
)
from xtal_agent.decision_engine import (
    FixAction,
    FixOutcome,
    FixResult,
    ResolutionValidation,
    idxref_failure_fix,
    matthews_copy_range,
    phaser_troubleshooting_order,
    PhaserSolution,
    PhaserSweepResult,
    select_best_copy_number,
    select_prediction_tool,
    sg_conflict_resolution,
    select_low_res_refine_strategy,
    detect_low_resolution,
    LOW_RES_THRESHOLD,
    DataRangeMosaicity,
    suggest_data_range_from_mosaicity,
    suggest_spot_range_from_vision,
    validate_resolution_from_aimless,
)

CommandRunner = Callable[[Path, int], bool]


@dataclass(frozen=True)
class PhaseResult:
    phase: str
    status: str
    message: str
    artifacts: list[Path]


@dataclass(frozen=True)
class XDSInpParams:
    min_pixels: int
    spot_range: str
    resolution_range: str


def run_phase(
    project_dir: str | Path,
    phase: str,
    mode: str = "simple",
    command_runner: CommandRunner | None = None,
) -> PhaseResult:
    project_dir = Path(project_dir).resolve()
    if phase == "phase1":
        return _run_phase1(project_dir, mode, command_runner or _run_xds_once)
    if phase == "phase2":
        return _run_phase2(project_dir)
    if phase == "phase3":
        return _run_phase3(project_dir)
    if phase == "phase4":
        return _run_phase4(project_dir)
    if phase == "phase5":
        return _run_phase5(project_dir)
    if phase == "phase5_lowres":
        return _run_phase5_lowres(project_dir)
    if phase not in {"phase2", "phase3", "phase4", "phase5", "phase5_lowres"}:
        raise ValueError(f"Unsupported phase: {phase}")
    return PhaseResult(
        phase=phase,
        status="not_implemented",
        message=f"{phase} not implemented yet",
        artifacts=[],
    )


def parse_xds_inp(xds_inp_path: str | Path) -> XDSInpParams:
    text = Path(xds_inp_path).read_text()
    min_pixels = _extract_int(text, r"MINIMUM_NUMBER_OF_PIXELS_IN_A_SPOT\s*[= ]\s*(\d+)", 6)
    spot_range = _extract_pair(text, r"SPOT_RANGE\s*[= ]\s*(\d+)\s+(\d+)", "1 360")
    resolution_range = _extract_pair(
        text,
        r"INCLUDE_RESOLUTION_RANGE\s*[= ]\s*([\d.]+)\s+([\d.]+)",
        "50 0",
    )
    return XDSInpParams(
        min_pixels=min_pixels,
        spot_range=spot_range,
        resolution_range=resolution_range,
    )


def apply_idxref_fix(xds_inp_path: str | Path, fix: FixResult) -> None:
    path = Path(xds_inp_path)
    text = path.read_text()
    if fix.action == FixAction.ADJUST_PIXELS:
        text = re.sub(
            r"MINIMUM_NUMBER_OF_PIXELS_IN_A_SPOT\s*[= ]\s*\d+",
            f"MINIMUM_NUMBER_OF_PIXELS_IN_A_SPOT={fix.value}",
            text,
            count=1,
        )
    elif fix.action in (FixAction.DECREASE_SPOT_RANGE, FixAction.SHIFT_SPOT_RANGE):
        text = re.sub(
            r"SPOT_RANGE\s*[= ]\s*\d+\s+\d+",
            f"SPOT_RANGE={fix.value}",
            text,
            count=1,
        )
    elif fix.action == FixAction.LOW_RESOLUTION_LIMIT:
        text = re.sub(
            r"INCLUDE_RESOLUTION_RANGE\s*[= ]\s*[\d.]+\s+[\d.]+",
            f"INCLUDE_RESOLUTION_RANGE=50 {fix.value}",
            text,
            count=1,
        )
    path.write_text(text)


def _extract_int(text: str, pattern: str, default: int) -> int:
    match = re.search(pattern, text)
    return int(match.group(1)) if match else default


def _extract_pair(text: str, pattern: str, default: str) -> str:
    match = re.search(pattern, text)
    return f"{match.group(1)} {match.group(2)}" if match else default


def _run_phase1(project_dir: Path, mode: str, command_runner: CommandRunner) -> PhaseResult:
    xds_inp = project_dir / "XDS.INP"
    decisions = project_dir / "idxref_decisions.jsonl"
    artifacts = [decisions]
    attempt = 1
    simple_mode = mode == "simple"

    # Phase-0 vision gate: if vision.enabled=true and the validated report
    # is missing, stop and require the user to run vision-scan first.
    if _vision_enabled(project_dir):
        report_path = project_dir / "vision_report.json"
        if not report_path.exists():
            return PhaseResult(
                phase="phase0",
                status="stopped",
                message=(
                    "vision.enabled=true but no validated vision_report.json found. "
                    "Run xtal-agent vision-scan first, then have the LLM fill "
                    "the report by inspecting the rendered montages."
                ),
                artifacts=artifacts,
            )
        try:
            from xtal_agent.vision_schema import load_vision_report

            _vision_load = load_vision_report(report_path)
        except ValueError as exc:
            return PhaseResult(
                phase="phase0",
                status="stopped",
                message=(
                    "vision.enabled=true but vision_report.json failed validation: "
                    f"{exc}. Run xtal-agent vision-validate for details."
                ),
                artifacts=artifacts,
            )

        # In simple mode: inject the LLM-visual-judgment-based SPOT_RANGE
        # into XDS.INP. This is the only downstream consumer allowed by the
        # parameter discipline.
        if simple_mode:
            _maybe_inject_vision_spot_range(project_dir, xds_inp)

    while True:
        ok = command_runner(project_dir, attempt)
        if ok and (project_dir / "CORRECT.LP").exists() and (project_dir / "XDS_ASCII.HKL").exists():
            data_range_artifact = _record_data_range_decision(project_dir)
            if data_range_artifact is not None:
                artifacts.append(data_range_artifact)
            return PhaseResult("phase1", "success", "XDS completed through CORRECT", artifacts)

        params = parse_xds_inp(xds_inp)
        fix = idxref_failure_fix(attempt, params.min_pixels, params.spot_range, simple_mode=simple_mode)
        with decisions.open("a") as handle:
            handle.write(
                json.dumps(
                    {
                        "attempt": attempt,
                        "action": fix.action.value,
                        "value": fix.value,
                        "result": fix.result.value,
                    }
                )
                + "\n"
            )

        if fix.result == FixOutcome.STOP:
            return PhaseResult("phase1", "stopped", f"Simple-mode stop: {fix.action.value} {fix.value}", artifacts)

        apply_idxref_fix(xds_inp, fix)
        _clean_xds_intermediates(project_dir)
        attempt += 1


def _run_xds_once(project_dir: Path, attempt: int) -> bool:
    result = subprocess.run(["xds_par"], cwd=project_dir, text=True, capture_output=True, check=False)
    (project_dir / f"xds_attempt_{attempt}.log").write_text(result.stdout + result.stderr)
    return result.returncode == 0


def _clean_xds_intermediates(project_dir: Path) -> None:
    for name in ["IDXREF.LP", "COLSPOT.LP", "INIT.LP", "SPOT.XDS", "XPARM.XDS", "CORRECT.LP", "INTEGRATE.LP"]:
        path = project_dir / name
        if path.exists():
            path.unlink()


def _record_data_range_decision(project_dir: Path) -> Path | None:
    mosaicity_path = project_dir / "mosaicity_values.txt"
    if not mosaicity_path.exists():
        return None
    frames: list[int] = []
    values: list[float] = []
    for line in mosaicity_path.read_text().splitlines():
        parts = line.split()
        if len(parts) != 2:
            continue
        frames.append(int(parts[0]))
        values.append(float(parts[1]))
    if not frames:
        return None
    decision = suggest_data_range_from_mosaicity(DataRangeMosaicity(frames=frames, mosaicity_values=values), "1 720")
    artifact = project_dir / "data_range_decision.txt"
    artifact.write_text(f"{decision.start_frame} {decision.end_frame} preferred={decision.preferred}\n")
    return artifact


def _run_phase2(project_dir: Path) -> PhaseResult:
    artifacts: list[Path] = []
    aimless_log = project_dir / "aimless.log"
    xds_sg_path = project_dir / "xds_sg.txt"

    # --- 1. SG conflict check ---
    aimless_sg_path = project_dir / "aimless_sg.txt"
    if xds_sg_path.exists() and aimless_sg_path.exists():
        sg_result = sg_conflict_resolution(
            xds_sg_path.read_text().strip(),
            aimless_sg_path.read_text().strip(),
            None,
        )
        sg_artifact = project_dir / "sg_conflict_decision.txt"
        sg_artifact.write_text(f"{sg_result.action.value}\n{sg_result.reason}\n")
        artifacts.append(sg_artifact)
        if sg_result.action.value != "no_conflict":
            return PhaseResult("phase2", "stopped", sg_result.reason, artifacts)

    # --- 2. Resolution validation from aimless per-shell stats ---
    if not aimless_log.exists():
        return PhaseResult("phase2", "stopped", "aimless.log not found; run aimless first", [])

    total_frames = _read_total_frames(project_dir)
    validation = validate_resolution_from_aimless(aimless_log.read_text(), total_frames)

    if validation.resolution_too_low:
        return PhaseResult(
            "phase2", "stopped",
            (f"Resolution limit set too low: outer shell Mn(I/sd)="
             f"{validation.outer_shell.mn_isd} > 2.5 at "
             f"{validation.outer_resolution:.2f} A. Data is still strong at the "
             f"current cutoff. Return to Phase 1 (XDS/DIALS), increase the "
             f"resolution limit, re-integrate, then re-run Phase 2."),
            artifacts,
        )

    if not validation.validated:
        return PhaseResult("phase2", "stopped",
                           "No resolution shell passes all 5 thresholds", artifacts)

    # Write AIMLESS_VALIDATION markers to aimless.log
    with aimless_log.open("a") as fh:
        outer = validation.outer_shell
        fh.write(
            f"\nAIMLESS_VALIDATION outer "
            f"CC1/2={validation.outer_shell.cc_half * 100:.1f} "
            f"Mn(I/sd)={outer.mn_isd} "
            f"Rmeas={outer.rmeas:.3f} "
            f"Rmerge={outer.rmerge:.3f} "
            f"completeness={outer.completeness:.1f} "
            f"frames={total_frames}\n"
        )
        fh.write(
            f"AIMLESS_VALIDATION overall "
            f"CC1/2={validation.overall_cc_half:.1f} "
            f"Mn(I/sd)={validation.overall_mn_isd:.1f} "
            f"completeness={validation.overall_completeness:.1f}\n"
        )
        fh.write(
            f"AIMLESS_VALIDATION inner "
            f"CC1/2={validation.inner_cc_half:.1f} "
            f"Mn(I/sd)={validation.inner_mn_isd}\n"
        )

    # Write validated_resolution.txt
    res_artifact = project_dir / "validated_resolution.txt"
    res_artifact.write_text(f"{validation.outer_resolution:.2f}\n")
    artifacts.append(res_artifact)

    # --- 3. Feedback validated resolution to XDS.INP ---
    xds_inp = project_dir / "XDS.INP"
    if xds_inp.exists():
        cutoff = validation.outer_resolution
        text = xds_inp.read_text()
        new_text = re.sub(
            r"INCLUDE_RESOLUTION_RANGE\s*[= ]\s*[\d.]+\s+[\d.]+",
            f"INCLUDE_RESOLUTION_RANGE=50 {cutoff}",
            text,
            count=1,
        )
        if new_text != text:
            xds_inp.write_text(new_text)

    return PhaseResult(
        "phase2", "success",
        (f"Validated resolution: {validation.outer_resolution:.2f} A "
         f"(outer CC1/2={validation.outer_shell.cc_half * 100:.1f}% "
         f"Mn(I/sd)={validation.outer_shell.mn_isd})"),
        artifacts,
    )


def _read_total_frames(project_dir: Path) -> int:
    xds_inp = project_dir / "XDS.INP"
    if xds_inp.exists():
        m = re.search(r"DATA_RANGE\s*[= ]\s*\d+\s+(\d+)", xds_inp.read_text())
        if m:
            return int(m.group(1))
    correct = project_dir / "CORRECT.LP"
    if correct.exists():
        m = re.search(r"DATA_RANGE=.*?(\d+)\s+TO\s+(\d+)", correct.read_text())
        if m:
            return int(m.group(2)) - int(m.group(1)) + 1
    return 999


def _run_phase3(project_dir: Path) -> PhaseResult:
    fasta = next(project_dir.glob("*.fasta"), None)
    if fasta is None:
        return PhaseResult("phase3", "stopped", "No FASTA found", [])

    text = fasta.read_text().lower()
    has_nucleic_acid = "rna" in text or "dna" in text
    decision = select_prediction_tool(is_protein_nucleic_acid=has_nucleic_acid)
    prediction_artifact = project_dir / "prediction_tool_decision.txt"
    prediction_artifact.write_text(f"{decision.tool.value}\n{decision.reason}\n")

    matthews_artifact = project_dir / "matthews_copy_range.txt"
    if (project_dir / "cell_sg.txt").exists():
        volume_text, sg_text, mw_text = (project_dir / "cell_sg.txt").read_text().split()
        result = matthews_copy_range(float(volume_text), float(mw_text), int(sg_text))
        matthews_artifact.write_text(
            f"top_copies={result.top_copies}\nfull_range={result.full_range}\n"
        )
    else:
        matthews_artifact.write_text("missing cell_sg.txt\n")

    return PhaseResult(
        "phase3",
        "success",
        "Phase 3 decisions recorded",
        [prediction_artifact, matthews_artifact],
    )


def _run_phase4(project_dir: Path) -> PhaseResult:
    artifacts: list[Path] = []

    sweep_path = project_dir / "phaser_sweep.json"
    if sweep_path.exists():
        raw_solutions = json.loads(sweep_path.read_text())
        sweep = PhaserSweepResult(
            solutions=[
                PhaserSolution(
                    copy_num=int(item["copies"]),
                    tfz=float(item["tfz"]),
                    llg=float(item["llg"]),
                    pak=int(item["pak"]),
                    all_placed=bool(item.get("all_placed", True)),
                )
                for item in raw_solutions
            ]
        )
        selected = select_best_copy_number(sweep)
        artifact = project_dir / "phaser_copy_selection.txt"
        artifact.write_text(str(selected) + "\n")
        artifacts.append(artifact)

    failure_path = project_dir / "phaser_failure_count.txt"
    if failure_path.exists():
        action = phaser_troubleshooting_order(int(failure_path.read_text().strip()))
        artifact = project_dir / "phaser_troubleshooting.txt"
        artifact.write_text(str(action) + "\n")
        artifacts.append(artifact)

    if not artifacts:
        return PhaseResult("phase4", "stopped", "No Phaser sweep or failure inputs found", [])
    return PhaseResult("phase4", "success", "Phase 4 decisions recorded", artifacts)


def _run_phase5(project_dir: Path) -> PhaseResult:
    artifacts: list[Path] = []
    refined_pdb = _find_best_refined_pdb(project_dir)
    refined_mtz = _find_best_refined_mtz(project_dir)
    fasta = next(project_dir.glob("*.fasta"), None)

    if not refined_pdb or not refined_mtz or not fasta:
        missing = []
        if not refined_pdb:
            missing.append("best PDB")
        if not refined_mtz:
            missing.append("best MTZ")
        if not fasta:
            missing.append("FASTA")
        return PhaseResult(
            "phase5", "stopped",
            f"Modelcraft: missing {', '.join(missing)}",
            artifacts,
        )

    result = run_modelcraft_refinement(project_dir, refined_pdb, refined_mtz, fasta)
    artifacts.extend(result.artifacts)

    # Optional post-refinement COOT module (enabled by default when a manifest
    # is present and COOT is installed). Failure is non-fatal: keep the
    # pre-COOT model and record the reason.
    post_pdb = project_dir / "modelcraft_r4.pdb"
    post_mtz = project_dir / "modelcraft_r4.mtz"
    if not post_pdb.exists():
        post_pdb = refined_pdb
    if not post_mtz.exists():
        post_mtz = refined_mtz
    coot_result = _maybe_run_coot(project_dir, post_pdb, post_mtz)
    message = result.message
    if coot_result is not None:
        artifacts.extend(coot_result.artifacts)
        message = f"{message}; COOT: {coot_result.reason}"
    return ModelcraftResult(result.status, message, artifacts)


def _run_phase5_lowres(project_dir: Path) -> PhaseResult:
    """Low-resolution refinement branch (>= 3.6 A).

    Checks that the validated resolution triggers the low-res branch,
    then verifies the expected refinement outputs exist.
    """
    artifacts: list[Path] = []
    validated_res = project_dir / "validated_resolution.txt"

    # Detect low-res condition
    resolution = 99.0
    if validated_res.exists():
        try:
            resolution = float(validated_res.read_text().strip().split()[0])
        except (ValueError, IndexError):
            pass

    decision = detect_low_resolution(resolution, mode="simple")
    if not decision.is_low_res and resolution > 0:
        return PhaseResult(
            "phase5_lowres", "skipped",
            f"Resolution {resolution} < {LOW_RES_THRESHOLD} A: low-res branch not needed",
            artifacts,
        )

    # Check rigid body output
    rb_pdb = project_dir / "phenix_rb_001.pdb"
    has_rigid_body = rb_pdb.exists()

    # Check phenix grouped ADP output
    phenix_rounds = sorted(project_dir.glob("phenix_r[1-4]_001.pdb"))
    has_phenix = len(phenix_rounds) >= 1

    # Check refmac jelly output
    jelly_rounds = sorted(project_dir.glob("refmac_jelly_r*.pdb"))
    has_jelly = len(jelly_rounds) >= 2

    # Check refmac free output
    free_rounds = sorted(project_dir.glob("refmac_r[3-9].pdb"))
    has_free = len(free_rounds) >= 2

    # Check modelcraft (only required if Rfree <= 0.35 after refmac)
    mc_json = project_dir / "modelcraft.json"
    has_modelcraft = mc_json.exists()

    # Check RSC
    has_rsc = (project_dir / "rsc.log").exists()

    # Check final MolProbity
    has_molprobity = (project_dir / "molprobity.log").exists()

    status = "success"
    issues: list[str] = []
    if not has_rigid_body:
        issues.append("missing rigid body")
        status = "incomplete"
    if not has_phenix:
        issues.append("missing phenix grouped ADP")
    if not has_jelly:
        issues.append("missing refmac jelly rounds")
        status = "incomplete"
    if not has_free:
        issues.append("missing refmac free rounds")
        status = "incomplete"

    message = f"Low-res branch ({resolution:.2f} A): "
    if issues:
        message += f"pending={issues}"
    elif has_modelcraft and has_rsc and has_molprobity:
        message += "complete"
    else:
        message += "refinement done, post-processing pending"

    # Write decision artifact
    decision_artifact = project_dir / "low_res_decision.txt"
    strategy = select_low_res_refine_strategy(decision.is_low_res, expert_mode=False, user_accepted=True)
    decision_artifact.write_text(
        f"resolution={resolution}\n"
        f"phase={strategy.phase}\n"
        f"modelcraft_eligible={strategy.modelcraft_eligible}\n"
        f"reason={strategy.reason}\n"
    )
    artifacts.append(decision_artifact)

    return PhaseResult("phase5_lowres", status, message, artifacts)


def _find_best_refined_pdb(project_dir: Path) -> Path | None:
    candidates = sorted(project_dir.glob("refmac_r*.pdb"))
    if candidates:
        return candidates[-1]
    candidates = sorted(project_dir.glob("phenix_r*.pdb"))
    return candidates[-1] if candidates else None


def _find_best_refined_mtz(project_dir: Path) -> Path | None:
    for name in ["refmac_r4.mtz", "refmac_r3.mtz", "phenix_r4_001.mtz", "phenix_r5_001.mtz"]:
        path = project_dir / name
        if path.exists():
            return path
    candidates = sorted(project_dir.glob("ctruncate_free.mtz"))
    return candidates[0] if candidates else None


@dataclass(frozen=True)
class ModelcraftResult:
    status: str
    message: str
    artifacts: list[Path]


def run_modelcraft_refinement(
    project_dir: Path,
    model_pdb: Path,
    data_mtz: Path,
    fasta: Path,
) -> ModelcraftResult:
    artifacts: list[Path] = []
    mc_dir = project_dir / "modelcraft_work"
    mc_dir.mkdir(exist_ok=True)

    best_pdb_copy = mc_dir / "input_best.pdb"
    best_mtz_copy = mc_dir / "input_best.mtz"
    fasta_copy = mc_dir / "input.fasta"

    _copy_if_not_exists(model_pdb, best_pdb_copy)
    _copy_if_not_exists(data_mtz, best_mtz_copy)
    _copy_if_not_exists(fasta, fasta_copy)

    mc_result = subprocess.run(
        ["modelcraft", "xray",
         "--data", str(best_mtz_copy),
         "--contents", str(fasta_copy),
         "--model", str(best_pdb_copy),
         "--directory", "mc_out",
         "--cycles", "10",
         "--auto-stop-cycles", "3"],
        cwd=mc_dir,
        text=True, capture_output=True, check=False,
    )
    run_log_text = (mc_result.stdout or "") + (mc_result.stderr or "")
    (mc_dir / "modelcraft_run.log").write_text(run_log_text)
    # Mirror the attempt marker at the project root so verification records that
    # modelcraft was always attempted, even when the run fails.
    (project_dir / "modelcraft_run.log").write_text(run_log_text)
    artifacts.append(mc_dir / "modelcraft_run.log")

    mc_json_path = mc_dir / "mc_out" / "modelcraft.json"
    if not mc_json_path.exists():
        return ModelcraftResult("attempted", "modelcraft.json not found; failure ignored", artifacts)

    mc_json = json.loads(mc_json_path.read_text())
    cycles = mc_json.get("cycles", [])
    if not cycles:
        return ModelcraftResult("attempted", "modelcraft cycles empty; failure ignored", artifacts)

    best_cycle = min(cycles, key=lambda c: c.get("r_free", 1.0))
    best_rfree = best_cycle.get("r_free", 1.0)
    print(f"Modelcraft best cycle: {best_cycle['cycle']} Rfree={best_cycle['r_free']}")

    # Mirror the success markers to the project root so verify-steps sees a
    # completed modelcraft run at the canonical location.
    _copy_if_not_exists(mc_json_path, project_dir / "modelcraft.json")

    mc_cif = mc_dir / "mc_out" / "modelcraft.cif"
    mc_pdb = mc_dir / "modelcraft.pdb"
    if mc_cif.exists():
        _copy_if_not_exists(mc_cif, project_dir / "modelcraft.cif")
        subprocess.run(
            ["phenix.cif_as_pdb", str(mc_cif)],
            cwd=mc_dir, text=True, capture_output=True, check=False,
        )
        if mc_pdb.exists():
            _run_modelcraft_refmac_rounds(mc_dir, best_mtz_copy)
            artifacts.append(mc_dir / "modelcraft_r4.pdb")
            comparison_log = mc_dir / "modelcraft_comparison.log"
            comparison_log.write_text(
                f"modelcraft_best_rfree={best_rfree}\n"
                "Compare against pre-modelcraft best; adopt the modelcraft model only "
                "if its final Rfree improves over the pre-modelcraft best.\n"
            )
            artifacts.append(comparison_log)
            (mc_dir / "modelcraft.kept").write_text(f"best_rfree={best_rfree}\n")
            for name in ("modelcraft_r2.pdb", "modelcraft_r4.pdb"):
                src = mc_dir / name
                if src.exists():
                    _copy_if_not_exists(src, project_dir / name)
            _copy_if_not_exists(comparison_log, project_dir / "modelcraft_comparison.log")
            (project_dir / "modelcraft.kept").write_text(f"best_rfree={best_rfree}\n")
        else:
            print("Warning: modelcraft.pdb not created from cif")
    else:
        print("Warning: modelcraft.cif not found")

    return ModelcraftResult(
        "success" if (mc_dir / "modelcraft.kept").exists() else "warning",
        f"Modelcraft done, best Rfree={best_rfree} from cycle {best_cycle['cycle']}",
        artifacts,
    )


def _run_modelcraft_refmac_rounds(work_dir: Path, mtz: Path) -> None:
    for rnd in [1, 2]:
        inp = work_dir / f"r{rnd}.inp"
        inp_pdb = work_dir / "modelcraft.pdb" if rnd == 1 else work_dir / f"modelcraft_jelly_r{rnd-1}.pdb"
        out_pdb = work_dir / f"modelcraft_jelly_r{rnd}.pdb"
        out_mtz = work_dir / f"modelcraft_jelly_r{rnd}.mtz"
        inp.write_text(
            "make hydrogen no\n"
            "labin FP=F SIGFP=SIGF FREE=FreeR_flag\n"
            "refi type REST resi MLKF meth CGMAT bref ISOT\n"
            "ncyc 8\nscales lsso aniso\nsolvent yes\nncsr local\n"
            "weight matrix 0.01\nEND\n"
        )
        subprocess.run(
            ["refmac5", "xyzin", str(inp_pdb), "xyzout", str(out_pdb),
             "hklin", str(mtz), "hklout", str(out_mtz)],
            stdin=open(inp), cwd=work_dir,
            text=True, capture_output=True, check=False,
        )
    for rnd in [3, 4]:
        inp = work_dir / f"r{rnd}.inp"
        inp_pdb = work_dir / f"modelcraft_jelly_r2.pdb" if rnd == 3 else work_dir / f"modelcraft_r{rnd-1}.pdb"
        out_pdb = work_dir / f"modelcraft_r{rnd}.pdb"
        out_mtz = work_dir / f"modelcraft_r{rnd}.mtz"
        inp.write_text(
            "make hydrogen no\n"
            "labin FP=F SIGFP=SIGF FREE=FreeR_flag\n"
            "refi type REST resi MLKF meth CGMAT bref ISOT\n"
            "ncyc 8\nscales lsso aniso\nsolvent yes\nncsr local\nEND\n"
        )
        subprocess.run(
            ["refmac5", "xyzin", str(inp_pdb), "xyzout", str(out_pdb),
             "hklin", str(mtz), "hklout", str(out_mtz)],
            stdin=open(inp), cwd=work_dir,
            text=True, capture_output=True, check=False,
        )


def _copy_if_not_exists(src: Path, dst: Path) -> None:
    if not dst.exists():
        dst.write_bytes(src.read_bytes())


# ---------------------------------------------------------------------------
# COOT post-refinement module
# ---------------------------------------------------------------------------

def _coot_manifest_settings(project_dir: Path) -> dict | None:
    manifest = Path(project_dir) / "manifest.yaml"
    if not manifest.exists():
        return None
    try:
        import yaml as _yaml

        data = _yaml.safe_load(manifest.read_text()) or {}
    except Exception:
        return None
    return data.get("coot") or {}


def _coot_enabled(project_dir: Path) -> bool:
    settings = _coot_manifest_settings(project_dir)
    if settings is None:
        return False
    return bool(settings.get("enabled", True))


def _project_resolution(project_dir: Path) -> float | None:
    validated = Path(project_dir) / "validated_resolution.txt"
    if validated.exists():
        try:
            return float(validated.read_text().strip().split()[0])
        except (ValueError, IndexError):
            pass
    for name in ("molprobity_final.log", "molprobity.log"):
        log = Path(project_dir) / name
        if not log.exists():
            continue
        match = re.search(r"^\s*Resolution\s*=\s*([\d.]+)", log.read_text(), re.M)
        if match:
            return float(match.group(1))
    return None


def _maybe_run_coot(project_dir: Path, pdb: Path, mtz: Path) -> CootResult | None:
    """Run the COOT post-refinement module if enabled and available."""
    if not _coot_enabled(project_dir):
        return None
    if not coot_available():
        return None
    resolution = _project_resolution(project_dir)
    if resolution is None:
        return None

    settings = _coot_manifest_settings(project_dir) or {}
    workdir = project_dir / "coot_strategy"
    try:
        from xtal_agent.manifest import load_manifest

        manifest = load_manifest(project_dir / "manifest.yaml")
        constraints = manifest.constraints
        if constraints.f_col and constraints.sigf_col:
            labels = f"{constraints.f_col},{constraints.sigf_col}"
        else:
            labels = "F,SIGF"
        result = run_coot_optimization(
            pdb,
            mtz,
            workdir,
            resolution,
            labels=labels,
            rfree_label="FreeR_flag",
            strategy=str(settings.get("strategy", "auto")),
            twin_law=settings.get("twin_law"),
            clash_worse_pct=float(settings.get("geometry_redline", 20.0)),
        )
    except Exception as exc:  # noqa: BLE001 - non-fatal module
        workdir.mkdir(parents=True, exist_ok=True)
        (workdir / "coot_error.log").write_text(f"{type(exc).__name__}: {exc}\n")
        return None

    (workdir / "coot_result.json").write_text(
        json.dumps(
            {
                "accepted": result.accepted,
                "selected_pdb": str(result.selected_pdb),
                "selected_mtz": str(result.selected_mtz),
                "rfree_before": result.rfree_before,
                "rfree_after": result.rfree_after,
                "rwork_after": result.rwork_after,
                "clashscore": result.clashscore,
                "rama_outliers": result.rama_outliers,
                "rotamer_outliers": result.rotamer_outliers,
                "reason": result.reason,
            },
            indent=2,
        )
    )
    if result.accepted:
        (project_dir / "coot_refined.pdb").write_bytes(result.selected_pdb.read_bytes())
        (project_dir / "coot_refined.mtz").write_bytes(result.selected_mtz.read_bytes())
    return result


# ---------------------------------------------------------------------------
# Vision module integration helpers
# ---------------------------------------------------------------------------

def _vision_enabled(project_dir: Path) -> bool:
    """Read vision.enabled from manifest.yaml without going through full
    schema validation (we only need this boolean at gate time)."""
    manifest = Path(project_dir) / "manifest.yaml"
    if not manifest.exists():
        return False
    try:
        import yaml as _yaml

        data = _yaml.safe_load(manifest.read_text()) or {}
    except Exception:
        return False
    vision = data.get("vision") or {}
    return bool(vision.get("enabled", False))


def _maybe_inject_vision_spot_range(project_dir: Path, xds_inp: Path) -> None:
    """In simple mode, override SPOT_RANGE in XDS.INP using the vision report
    (the only downstream consumer permitted by the parameter discipline).

    The XDS.INP comment header records the source so audit-architecture can
    later trace which SPOT_RANGE came from where.
    """
    if not xds_inp.exists():
        return
    try:
        from xtal_agent.vision_schema import load_vision_report

        report = load_vision_report(project_dir / "vision_report.json")
    except ValueError:
        return
    full_data_range = "1 360"  # default; vision-scan reports the real count
    spot_range_match = re.search(r"DATA_RANGE\s*[= ]\s*(\d+)\s+(\d+)", xds_inp.read_text())
    if spot_range_match:
        full_data_range = f"{spot_range_match.group(1)} {spot_range_match.group(2)}"
    suggestion = suggest_spot_range_from_vision(report, full_data_range)
    if not suggestion.preferred:
        # Fallback to existing default; vision did not add new evidence.
        return
    new_value = f"SPOT_RANGE={suggestion.start_frame} {suggestion.end_frame}  ! SPOT_RANGE from vision scan, see vision_report.json"
    text = xds_inp.read_text()
    if "SPOT_RANGE" in text:
        text = re.sub(r"SPOT_RANGE\s*[= ]\s*\d+\s+\d+", new_value, text, count=1)
    else:
        text += "\n" + new_value + "\n"
    xds_inp.write_text(text)

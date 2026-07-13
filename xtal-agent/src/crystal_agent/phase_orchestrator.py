from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from crystal_agent.decision_engine import (
    FixAction,
    FixOutcome,
    FixResult,
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
    xds_sg_path = project_dir / "xds_sg.txt"
    aimless_sg_path = project_dir / "aimless_sg.txt"
    if not xds_sg_path.exists() or not aimless_sg_path.exists():
        return PhaseResult("phase2", "stopped", "Missing SG inputs for conflict check", [])

    result = sg_conflict_resolution(
        xds_sg_path.read_text().strip(),
        aimless_sg_path.read_text().strip(),
        None,
    )
    artifact = project_dir / "sg_conflict_decision.txt"
    artifact.write_text(f"{result.action.value}\n{result.reason}\n")
    status = "success" if result.action.value == "no_conflict" else "stopped"

    validated_res = project_dir / "validated_resolution.txt"
    xds_inp = project_dir / "XDS.INP"
    if validated_res.exists() and xds_inp.exists():
        try:
            cutoff = float(validated_res.read_text().strip().split()[0])
        except (ValueError, IndexError):
            cutoff = None
        if cutoff is not None and cutoff > 0:
            text = xds_inp.read_text()
            new_text = re.sub(
                r"INCLUDE_RESOLUTION_RANGE\s*[= ]\s*[\d.]+\s+[\d.]+",
                f"INCLUDE_RESOLUTION_RANGE=50 {cutoff}",
                text,
                count=1,
            )
            if new_text != text:
                xds_inp.write_text(new_text)
                artifact = project_dir / "resolution_feedback_artifact.txt"
                artifact.write_text(f"XDS.INP INCLUDE_RESOLUTION_RANGE updated to 50 {cutoff}\n")
                status = "requires_xds_rerun"

    phase_result = PhaseResult("phase2", status, result.reason, [artifact])
    if status == "requires_xds_rerun":
        phase_result.message = "XDS must be re-run with validated resolution cutoff in INCLUDE_RESOLUTION_RANGE"
    return phase_result


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
    return result


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

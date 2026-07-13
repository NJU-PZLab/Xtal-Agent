from pathlib import Path

from crystal_agent.manifest import load_manifest
from crystal_agent.phaser_runner import run_phaser, detect_labels
from crystal_agent.refinement_runner import run_refinement, run_validation
from crystal_agent.ranking import rank_candidates
from crystal_agent.report import render_report
from crystal_agent.schemas import CandidateResult
from crystal_agent.workflow import ensure_autonomous_cli_allowed, ensure_simple_mode_inputs_supported


def _get_labels(manifest, mtz_path: Path) -> tuple[str | None, str | None]:
    f_col = manifest.constraints.f_col
    sigf_col = manifest.constraints.sigf_col
    if f_col is None or sigf_col is None:
        f_col, sigf_col = detect_labels(mtz_path)
    return f_col, sigf_col


def run_project(project_dir: str | Path) -> list[CandidateResult]:
    project_dir = Path(project_dir).resolve()
    manifest_path = project_dir / "manifest.yaml"
    manifest = load_manifest(manifest_path)
    ensure_autonomous_cli_allowed(manifest.workflow_mode)
    ensure_simple_mode_inputs_supported(
        manifest.workflow_mode,
        manifest.inputs.diffraction.type,
    )

    mtz_path = (project_dir / manifest.inputs.diffraction.path).resolve()
    model_path = (project_dir / manifest.inputs.models[0].path).resolve()
    sequence_path = (project_dir / manifest.inputs.sequence.path).resolve()
    output_dir = project_dir / "output"
    reports_dir = project_dir / "reports"

    f_col, sigf_col = _get_labels(manifest, mtz_path)
    candidates = []

    result = run_phaser(
        mtz_path=mtz_path,
        model_path=model_path,
        sequence_path=sequence_path,
        output_dir=output_dir,
        f_col=f_col,
        sigf_col=sigf_col,
        space_group=manifest.constraints.space_group_hint,
    )
    candidates.append(result)

    if result.tfz is not None and result.tfz > 6:
        refined = run_refinement(
            mtz_path=mtz_path,
            pdb_path=output_dir / "phaser_run.1.pdb",
            output_dir=output_dir / "refine",
            f_col=f_col,
            sigf_col=sigf_col,
        )
        refined.tfz = result.tfz
        refined.llg = result.llg
        refined.packing_clashes = result.packing_clashes
        candidates.append(refined)

        val = run_validation(
            output_dir / "refine" / "refined_001.pdb",
            output_dir / "validation",
        )
        refined.molprobity_score = val.get("molprobity_score")
    else:
        candidates.append(CandidateResult(candidate_id="refinement_skipped"))

    ranked = rank_candidates(candidates)

    reports_dir.mkdir(parents=True, exist_ok=True)
    html = render_report(manifest.project_id, ranked)
    (reports_dir / "validation_summary.html").write_text(html)

    return ranked

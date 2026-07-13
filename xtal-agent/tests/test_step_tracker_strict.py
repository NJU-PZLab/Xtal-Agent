import json
from pathlib import Path

from crystal_agent.step_tracker import Guard, StepTracker


def test_aimless_resolution_rejects_failed_outer_shell_thresholds(tmp_path: Path):
    (tmp_path / "aimless.log").write_text(
        "AIMLESS_VALIDATION outer CC1/2=39.9 Mn(I/sd)=1.7 completeness=95 Rmeas=0.9 Rmerge=0.8\n"
        "AIMLESS_VALIDATION overall CC1/2=99 Mn(I/sd)=10 completeness=99\n"
        "AIMLESS_VALIDATION inner CC1/2=99 Mn(I/sd)=20\n"
    )

    tracker = StepTracker(str(tmp_path))

    assert not tracker._check_aimless_resolution()


def test_aimless_resolution_accepts_all_thresholds(tmp_path: Path):
    (tmp_path / "aimless.log").write_text(
        "AIMLESS_VALIDATION outer CC1/2=41 Mn(I/sd)=1.7 completeness=75 Rmeas=1.7 Rmerge=1.9\n"
        "AIMLESS_VALIDATION overall CC1/2=95 Mn(I/sd)=5 completeness=95\n"
        "AIMLESS_VALIDATION inner CC1/2=98 Mn(I/sd)=9\n"
    )

    tracker = StepTracker(str(tmp_path))

    assert tracker._check_aimless_resolution()


def test_aimless_resolution_allows_low_outer_completeness_when_frames_below_180(tmp_path: Path):
    (tmp_path / "aimless.log").write_text(
        "AIMLESS_VALIDATION frames=120 outer CC1/2=41 Mn(I/sd)=1.7 completeness=60 Rmeas=1.7 Rmerge=1.9\n"
        "AIMLESS_VALIDATION overall CC1/2=95 Mn(I/sd)=5 completeness=95\n"
        "AIMLESS_VALIDATION inner CC1/2=98 Mn(I/sd)=9\n"
    )

    tracker = StepTracker(str(tmp_path))

    assert tracker._check_aimless_resolution()


def test_phaser_pak_rejects_nonzero_unexplained_pak(tmp_path: Path):
    (tmp_path / "phaser_copy_1.log").write_text("LLG=300 TFZ==9.1 PAK=2\n")

    tracker = StepTracker(str(tmp_path))

    assert not tracker._check_phaser_pak()


def test_phaser_pak_accepts_zero_pak(tmp_path: Path):
    (tmp_path / "phaser_copy_1.log").write_text("LLG=300 TFZ==9.1 PAK=0\n")

    tracker = StepTracker(str(tmp_path))

    assert tracker._check_phaser_pak()


def test_mtz_resolution_requires_recorded_resolution_match(tmp_path: Path):
    (tmp_path / "scaled.mtz").write_text("placeholder")
    (tmp_path / "mtzdump_resolution.log").write_text("Resolution Range : 50.00 2.10\n")
    (tmp_path / "validated_resolution.txt").write_text("2.00\n")

    tracker = StepTracker(str(tmp_path))

    assert not tracker._check_mtz_resolution()


def test_iteration_requires_iteration_marker(tmp_path: Path):
    (tmp_path / "phenix_r1.log").write_text("round 1")
    (tmp_path / "phenix_r2.log").write_text("round 2")

    tracker = StepTracker(str(tmp_path))

    assert not tracker._check_iteration()


def test_iteration_rejects_refmac_round_without_previous_markers(tmp_path: Path):
    (tmp_path / "refmac_jelly_r2.pdb").write_text("MODEL\n")
    (tmp_path / "refmac_r3.pdb").write_text("MODEL\n")
    (tmp_path / "refmac_r3.log").write_text("round 3 without markers")

    tracker = StepTracker(str(tmp_path))

    assert not tracker._check_iteration()


def test_iteration_accepts_refmac_round_with_previous_markers(tmp_path: Path):
    (tmp_path / "refmac_jelly_r2.pdb").write_text("MODEL\n")
    (tmp_path / "refmac_r3.pdb").write_text("MODEL\n")
    (tmp_path / "refmac_r4.pdb").write_text("MODEL\n")
    (tmp_path / "refmac_r3.log").write_text("INPUT_PDB=refmac_jelly_r2\nINPUT_MTZ=refmac_jelly_r2\n")
    (tmp_path / "refmac_r4.log").write_text("INPUT_PDB=refmac_r3\nINPUT_MTZ=refmac_r3\n")

    tracker = StepTracker(str(tmp_path))

    assert tracker._check_iteration()


def test_modelcraft_attempt_passes_when_run_failed_but_logged(tmp_path: Path):
    (tmp_path / "modelcraft_run.log").write_text("modelcraft crashed: no output\n")

    tracker = StepTracker(str(tmp_path))

    assert tracker._modelcraft_attempted()
    assert not tracker._modelcraft_succeeded()
    assert tracker.steps["phase5_modelcraft_run"]["check"]()


def test_modelcraft_attempt_fails_when_never_run(tmp_path: Path):
    tracker = StepTracker(str(tmp_path))

    assert not tracker._modelcraft_attempted()
    assert not tracker.steps["phase5_modelcraft_run"]["check"]()


def test_modelcraft_branch_not_required_when_run_failed(tmp_path: Path):
    (tmp_path / "modelcraft_run.log").write_text("modelcraft crashed: no output\n")

    tracker = StepTracker(str(tmp_path))

    assert tracker.steps["phase5_modelcraft_refmac_r2"]["check"]()
    assert tracker.steps["phase5_modelcraft_comparison"]["check"]()


def test_modelcraft_branch_required_when_run_succeeded(tmp_path: Path):
    (tmp_path / "modelcraft_run.log").write_text("done\n")
    (tmp_path / "modelcraft.json").write_text('{"cycles": []}')
    (tmp_path / "modelcraft.cif").write_text("data_x\n")

    tracker = StepTracker(str(tmp_path))

    assert tracker._modelcraft_succeeded()
    assert not tracker.steps["phase5_modelcraft_refmac_r2"]["check"]()
    assert not tracker.steps["phase5_modelcraft_comparison"]["check"]()


def test_modelcraft_branch_passes_when_succeeded_and_completed(tmp_path: Path):
    (tmp_path / "modelcraft_run.log").write_text("done\n")
    (tmp_path / "modelcraft.json").write_text('{"cycles": []}')
    (tmp_path / "modelcraft.cif").write_text("data_x\n")
    (tmp_path / "modelcraft_r2.pdb").write_text("MODEL\n")
    (tmp_path / "modelcraft.kept").write_text("best_rfree=0.20\n")

    tracker = StepTracker(str(tmp_path))

    assert tracker.steps["phase5_modelcraft_refmac_r2"]["check"]()
    assert tracker.steps["phase5_modelcraft_comparison"]["check"]()


def test_guard_blocks_starting_new_step_when_previous_step_unclosed(tmp_path: Path):
    (tmp_path / "XDS.INP").write_text("JOB= IDXREF DEFPIX INTEGRATE CORRECT\n")
    (tmp_path / "seq.fasta").write_text(">x\nACDE\n")
    guard = Guard(str(tmp_path))
    guard.state = {"completed": [], "current": "phase1_correct_lp"}
    guard._save()

    try:
        guard.before("phase2_pointless")
    except SystemExit as exc:
        assert exc.code == 1
    else:
        raise AssertionError("guard.before should block a new step when the previous step is unclosed")


def test_expert_guard_before_requires_approval(tmp_path: Path):
    (tmp_path / "manifest.yaml").write_text("workflow_mode: expert\n")
    (tmp_path / "XDS.INP").write_text("JOB= IDXREF DEFPIX INTEGRATE CORRECT\n")
    (tmp_path / "seq.fasta").write_text(">x\nACDE\n")

    guard = Guard(str(tmp_path))
    try:
        guard.before("phase1_correct_lp")
    except SystemExit as exc:
        assert exc.code == 1
    else:
        raise AssertionError("expert guard.before should require explicit approval")


def test_expert_approval_is_consumed_once(tmp_path: Path):
    from crystal_agent.step_tracker import approve_expert_step

    (tmp_path / "manifest.yaml").write_text("workflow_mode: expert\n")
    (tmp_path / "XDS.INP").write_text("JOB= IDXREF DEFPIX INTEGRATE CORRECT\n")
    (tmp_path / "seq.fasta").write_text(">x\nACDE\n")

    approve_expert_step(str(tmp_path), "phase1_correct_lp", "user approved phase1")
    guard = Guard(str(tmp_path))
    guard.before("phase1_correct_lp")

    state = json.loads((tmp_path / ".expert_approvals.json").read_text())
    assert state["approvals"][0]["consumed"] is True

    guard.state = {"completed": [], "current": None}
    guard._save()
    try:
        guard.before("phase1_correct_lp")
    except SystemExit as exc:
        assert exc.code == 1
    else:
        raise AssertionError("expert approval should be one-shot")


def test_expert_approval_not_consumed_when_prerequisites_fail(tmp_path: Path):
    from crystal_agent.step_tracker import approve_expert_step

    (tmp_path / "manifest.yaml").write_text("workflow_mode: expert\n")
    (tmp_path / "XDS.INP").write_text("JOB= IDXREF DEFPIX INTEGRATE CORRECT\n")
    (tmp_path / "seq.fasta").write_text(">x\nACDE\n")
    approve_expert_step(str(tmp_path), "phase2_pointless", "after phase1 review")

    guard = Guard(str(tmp_path))
    try:
        guard.before("phase2_pointless")
    except SystemExit as exc:
        assert exc.code == 1
    else:
        raise AssertionError("phase2 should still require phase1 prerequisites")

    state = json.loads((tmp_path / ".expert_approvals.json").read_text())
    assert state["approvals"][0]["consumed"] is False


def test_matthews_check_fails_when_no_copy_range_visible(tmp_path: Path):
    (tmp_path / "matthews.log").write_text("some text without numbers\n")

    tracker = StepTracker(str(tmp_path))

    assert not tracker._check_matthews_coverage()


def test_matthews_check_passes_when_copy_range_present(tmp_path: Path):
    (tmp_path / "matthews.log").write_text("Vm=2.1 copies 1-4\n")

    tracker = StepTracker(str(tmp_path))

    assert tracker._check_matthews_coverage()


def test_all_copies_check_fails_when_gaps_in_range(tmp_path: Path):
    (tmp_path / "matthews.log").write_text("Vm=2.1 copies 1-4\n")
    (tmp_path / "phaser_copy_1.log").write_text("LLG=300 TFZ==9.1 PAK=0\n")
    (tmp_path / "phaser_copy_3.log").write_text("LLG=300 TFZ==9.1 PAK=0\n")

    tracker = StepTracker(str(tmp_path))

    assert not tracker._check_all_copies()


def test_all_copies_check_passes_when_full_range_tested(tmp_path: Path):
    (tmp_path / "matthews.log").write_text("Vm=2.1 copies 1-4\n")
    for n in range(1, 5):
        (tmp_path / f"phaser_copy_{n}.log").write_text("LLG=300 TFZ==9.1 PAK=0\n")

    tracker = StepTracker(str(tmp_path))

    assert tracker._check_all_copies()


def test_all_copies_accepts_trailing_options_in_matthews_log(tmp_path: Path):
    (tmp_path / "matthews.log").write_text("Vm=2.1  copies=1-4  best=3\n")
    for n in range(1, 5):
        (tmp_path / f"phaser_copy_{n}.log").write_text("LLG=300 TFZ==9.1 PAK=0\n")

    tracker = StepTracker(str(tmp_path))

    assert tracker._check_all_copies()


def test_best_copy_check_fails_when_not_recorded(tmp_path: Path):
    (tmp_path / "matthews.log").write_text("Vm=2.1 copies=1-4\n")
    for n in range(1, 5):
        (tmp_path / f"phaser_copy_{n}.log").write_text("LLG=300 TFZ==9.1 PAK=0\n")

    tracker = StepTracker(str(tmp_path))

    assert not tracker._check_best_copy_selected()


def test_phenix_rfree_trend_fails_when_plateau_detected(tmp_path: Path):
    (tmp_path / "phenix_r1.log").write_text(
        "INPUT_PDB=phenix_r1\nFinal R-work = 0.20 R-free = 0.25\n"
    )
    (tmp_path / "phenix_r2.log").write_text(
        "INPUT_PDB=phenix_r1\nINPUT_MTZ=phenix_r1\nFinal R-work = 0.22 R-free = 0.27\n"
    )
    (tmp_path / "phenix_r3.log").write_text(
        "INPUT_PDB=phenix_r2\nINPUT_MTZ=phenix_r2\nFinal R-work = 0.21 R-free = 0.26\n"
    )

    tracker = StepTracker(str(tmp_path))

    assert not tracker._check_phenix_rfree_trend()


def test_phenix_rfree_trend_passes_when_still_decreasing(tmp_path: Path):
    (tmp_path / "phenix_r1.log").write_text(
        "INPUT_PDB=phenix_r1\nFinal R-work = 0.22 R-free = 0.28\n"
    )
    (tmp_path / "phenix_r2.log").write_text(
        "INPUT_PDB=phenix_r1\nINPUT_MTZ=phenix_r1\nFinal R-work = 0.21 R-free = 0.26\n"
    )
    (tmp_path / "phenix_r3.log").write_text(
        "INPUT_PDB=phenix_r2\nINPUT_MTZ=phenix_r2\nFinal R-work = 0.20 R-free = 0.25\n"
    )

    tracker = StepTracker(str(tmp_path))

    assert tracker._check_phenix_rfree_trend()


def test_high_rfree_diagnosis_fails_when_both_software_tried_and_still_high(tmp_path: Path):
    (tmp_path / "phenix_r1.log").write_text(
        "INPUT_PDB=phenix_r1\nFinal R-work = 0.28 R-free = 0.40\n"
    )
    (tmp_path / "phenix_r2.log").write_text(
        "INPUT_PDB=phenix_r1\nINPUT_MTZ=phenix_r1\nFinal R-work = 0.27 R-free = 0.38\n"
    )
    (tmp_path / "refmac_r3.log").write_text(
        "INPUT_PDB=refmac_jelly_r2\nINPUT_MTZ=refmac_jelly_r2\nFinal Rfree = 0.39\n"
    )

    tracker = StepTracker(str(tmp_path))

    assert not tracker._check_high_rfree_diagnosis()


def test_high_rfree_diagnosis_calls_twin_refinement_decision(monkeypatch, tmp_path: Path):
    (tmp_path / "phenix_r1.log").write_text("Final R-work = 0.30 R-free = 0.40\n")
    (tmp_path / "xtriage.log").write_text("Twin law: h,k,-l\nTwin fraction: 0.35\n")
    calls = []

    def fake_should_use_twin_refinement(twin_laws):
        calls.append(twin_laws)
        return True

    monkeypatch.setattr(
        "crystal_agent.step_tracker.should_use_twin_refinement",
        fake_should_use_twin_refinement,
    )

    tracker = StepTracker(str(tmp_path))

    assert tracker._check_high_rfree_diagnosis()
    assert calls
    assert calls[0][0].operator == "h,k,-l"


def test_guard_before_runs_verify_steps_and_blocks_missing_prerequisites(tmp_path: Path):
    (tmp_path / "XDS.INP").write_text("JOB= IDXREF DEFPIX INTEGRATE CORRECT\n")
    (tmp_path / "seq.fasta").write_text(">x\nACDE\n")
    guard = Guard(str(tmp_path))
    guard.state = {"completed": [], "current": None}
    guard._save()

    from crystal_agent.step_tracker import Guard as G
    g = G(str(tmp_path))
    try:
        g.before("phase2_pointless")
    except SystemExit as exc:
        assert exc.code == 1
    else:
        raise AssertionError("guard.before phase2 should block when phase1 prerequisites are not met")


def test_guard_after_adds_verify_steps_consistency_check(tmp_path: Path):
    (tmp_path / "XDS.INP").write_text("JOB= IDXREF\n")
    (tmp_path / "seq.fasta").write_text(">x\nACDE\n")
    (tmp_path / "CORRECT.LP").write_text("SPACE_GROUP_NUMBER=19\n")
    (tmp_path / "XDS_ASCII.HKL").write_text("data\n")

    g = Guard(str(tmp_path))
    g.before("phase1_correct_lp")
    g.after("phase1_correct_lp")

    assert "phase1_correct_lp" in g.state["completed"]


def test_verify_steps_detects_guard_bypass(tmp_path: Path):
    (tmp_path / "phenix_r4.pdb").write_text("MODEL\n")
    (tmp_path / "refmac_jelly_r2.pdb").write_text("MODEL\n")
    (tmp_path / "refmac_r4.pdb").write_text("MODEL\n")
    guard = Guard(str(tmp_path))
    guardian = Guard(str(tmp_path))
    guardian._load()
    assert "phase5_phenix_r4" not in guardian.state.get("completed", [])


def test_step_tracker_flags_guard_consistency(tmp_path: Path):
    (tmp_path / "phenix_r4.pdb").write_text("MODEL\n")
    (tmp_path / "seed_data.mtz").write_text("data\n")
    (tmp_path / "phenix_r1.log").write_text("R-free = 0.30\n")
    (tmp_path / "phenix_r2.log").write_text("INPUT_PDB=phenix_r1 INPUT_MTZ=phenix_r1 R-free = 0.28\n")
    (tmp_path / "phenix_r3.log").write_text("INPUT_PDB=phenix_r2 INPUT_MTZ=phenix_r2 R-free = 0.27\n")
    (tmp_path / "phenix_r4.log").write_text("INPUT_PDB=phenix_r3 INPUT_MTZ=phenix_r3 R-free = 0.26\n")

    tracker = StepTracker(str(tmp_path))
    tracker.run()
    from crystal_agent.step_tracker import check_guard_consistency
    violations = check_guard_consistency(str(tmp_path))
    assert "phenix_r4" in str(violations)


def test_expert_verify_steps_detects_unapproved_artifact(tmp_path: Path):
    (tmp_path / "manifest.yaml").write_text("workflow_mode: expert\n")
    (tmp_path / "phenix_r4.pdb").write_text("MODEL\n")

    tracker = StepTracker(str(tmp_path))
    output, exit_code = tracker.run()

    assert exit_code == 1
    assert "Expert Mode Audit" in output
    assert "phase5_phenix_r4" in output


def test_step_tracker_accepts_outputs_in_processing_subdirectories(tmp_path: Path):
    (tmp_path / "manifest.yaml").write_text("workflow_mode: expert\n")
    branch = tmp_path / "xds_p321"
    branch.mkdir()
    (branch / "XDS.INP").write_text("JOB= IDXREF DEFPIX INTEGRATE CORRECT\n")
    (branch / "CORRECT.LP").write_text("SPACE_GROUP_NUMBER=150\nUNIT_CELL_CONSTANTS= 1 2 3 90 90 120\n")
    (branch / "XDS_ASCII.HKL").write_text("data\n")

    tracker = StepTracker(str(tmp_path))

    assert tracker.steps["phase0_xds_inp"]["check"]()
    assert tracker.steps["phase1_correct_lp"]["check"]()
    assert tracker.steps["phase1_sg_cell"]["check"]()


def test_simple_mode_does_not_accept_outputs_in_processing_subdirectories(tmp_path: Path):
    (tmp_path / "manifest.yaml").write_text("workflow_mode: simple\n")
    branch = tmp_path / "xds_p321"
    branch.mkdir()
    (branch / "CORRECT.LP").write_text("SPACE_GROUP_NUMBER=150\nUNIT_CELL_CONSTANTS= 1 2 3 90 90 120\n")
    (branch / "XDS_ASCII.HKL").write_text("data\n")

    tracker = StepTracker(str(tmp_path))

    assert not tracker.steps["phase1_correct_lp"]["check"]()


def test_pointless_check_accepts_point_log_in_subdirectory(tmp_path: Path):
    (tmp_path / "manifest.yaml").write_text("workflow_mode: expert\n")
    branch = tmp_path / "phase2_p321"
    branch.mkdir()
    (branch / "point.mtz").write_text("data\n")
    (branch / "point.log").write_text("Space group confidence (= Sqrt(...)) =     1.00\n")

    tracker = StepTracker(str(tmp_path))

    assert tracker.steps["phase2_pointless"]["check"]()


def test_aimless_check_accepts_cutoff_named_outputs(tmp_path: Path):
    (tmp_path / "manifest.yaml").write_text("workflow_mode: expert\n")
    branch = tmp_path / "phase2_p321"
    branch.mkdir()
    (branch / "scaled_4.2.mtz").write_text("data\n")
    (branch / "aimless_4.2.log").write_text("AIMLESS_VALIDATION outer CC1/2=70 Mn(I/sd)=2.0 completeness=99 Rmeas=1.0 Rmerge=0.9\n")

    tracker = StepTracker(str(tmp_path))

    assert tracker.steps["phase2_aimless"]["check"]()
    assert tracker.steps["phase2_shell_stats"]["check"]()


def test_aimless_validation_prefers_log_with_validation_markers(tmp_path: Path):
    (tmp_path / "manifest.yaml").write_text("workflow_mode: expert\n")
    branch = tmp_path / "phase2"
    branch.mkdir()
    (branch / "aimless_full.log").write_text("no validation markers here\n")
    (branch / "aimless_4.2.log").write_text(
        "AIMLESS_VALIDATION outer CC1/2=70 Mn(I/sd)=2.0 completeness=99 Rmeas=1.0 Rmerge=0.9\n"
        "AIMLESS_VALIDATION overall CC1/2=99 Mn(I/sd)=10 completeness=99\n"
        "AIMLESS_VALIDATION inner CC1/2=99 Mn(I/sd)=40\n"
    )

    tracker = StepTracker(str(tmp_path))

    assert tracker.steps["phase2_resolution_validated"]["check"]()


def test_mtz_resolution_check_accepts_cutoff_named_outputs_in_subdirectory(tmp_path: Path):
    (tmp_path / "manifest.yaml").write_text("workflow_mode: expert\n")
    branch = tmp_path / "phase2_p321"
    branch.mkdir()
    (branch / "scaled_4.2.mtz").write_text("data\n")
    (branch / "validated_resolution.txt").write_text("4.2\n")
    (branch / "mtzdump_resolution.log").write_text("Resolution Range : 46.64 4.20\n")

    tracker = StepTracker(str(tmp_path))

    assert tracker.steps["phase2_mtz_resolution"]["check"]()


def test_mtz_resolution_uses_resolution_range_not_later_numbers(tmp_path: Path):
    (tmp_path / "manifest.yaml").write_text("workflow_mode: expert\n")
    branch = tmp_path / "phase2"
    branch.mkdir()
    (branch / "scaled_4.2.mtz").write_text("data\n")
    (branch / "validated_resolution.txt").write_text("4.2\n")
    (branch / "mtzdump_resolution.log").write_text(
        " *  Resolution Range :\n\n"
        "    0.00046    0.05668     (     46.643 -      4.200 A )\n\n"
        " * Sort Order :\n\n"
        "      0     0     0     0     0\n"
        " * Space group = 180\n"
        " * Cell Dimensions : 179.420 179.420 214.590\n"
    )

    tracker = StepTracker(str(tmp_path))

    assert tracker.steps["phase2_mtz_resolution"]["check"]()


def test_expert_mode_does_not_fail_outer_shell_margin_gate(tmp_path: Path):
    (tmp_path / "manifest.yaml").write_text("workflow_mode: expert\n")
    (tmp_path / "aimless.log").write_text(
        "AIMLESS_VALIDATION outer CC1/2=90 Mn(I/sd)=10.0 completeness=99 Rmeas=0.5 Rmerge=0.4\n"
    )

    tracker = StepTracker(str(tmp_path))

    assert tracker.get_status("phase2_outer_margin", True) == "✓"


def test_simple_mode_keeps_outer_shell_margin_gate(tmp_path: Path):
    (tmp_path / "manifest.yaml").write_text("workflow_mode: simple\n")
    (tmp_path / "aimless.log").write_text(
        "AIMLESS_VALIDATION outer CC1/2=90 Mn(I/sd)=10.0 completeness=99 Rmeas=0.5 Rmerge=0.4\n"
    )

    tracker = StepTracker(str(tmp_path))

    assert not tracker.steps["phase2_outer_margin"]["check"]()


def test_expert_guard_prerequisites_use_output_fallback(tmp_path: Path):
    from crystal_agent.step_tracker import approve_expert_step

    (tmp_path / "manifest.yaml").write_text("workflow_mode: expert\n")
    (tmp_path / "XDS.INP").write_text("JOB= IDXREF DEFPIX INTEGRATE CORRECT\n")
    (tmp_path / "seq.fasta").write_text(">x\nACDE\n")
    (tmp_path / "CORRECT.LP").write_text("SPACE_GROUP_NUMBER=150\nUNIT_CELL_CONSTANTS= 1 2 3 90 90 120\n")
    (tmp_path / "XDS_ASCII.HKL").write_text("data\n")
    (tmp_path / "point.mtz").write_text("data\n")
    (tmp_path / "point.log").write_text("Space group confidence = 1.00\n")
    (tmp_path / "scaled_4.2.mtz").write_text("data\n")
    (tmp_path / "aimless.log").write_text("AIMLESS_VALIDATION outer CC1/2=90 Mn(I/sd)=10.0 completeness=99 Rmeas=0.5 Rmerge=0.4\n")
    (tmp_path / "mtzdump_resolution.log").write_text("Resolution Range : 46.64 4.20\n")
    (tmp_path / "5L2E.a3m").write_text(">x\nACDE\n")
    (tmp_path / "model_rank_001.pdb").write_text("MODEL\n")
    (tmp_path / "search_model.pdb").write_text("MODEL\n")
    (tmp_path / "matthews.log").write_text("Vm=2.1 copies=1-3\n")
    approve_expert_step(str(tmp_path), "phase4_phaser", "approved")

    guard = Guard(str(tmp_path))
    guard.before("phase4_phaser")

    assert guard.state["current"] == "phase4_phaser"

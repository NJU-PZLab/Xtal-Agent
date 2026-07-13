from crystal_agent.decision_engine import (
    DataRangeCandidate,
    DataRangeMosaicity,
    FixAction,
    FixOutcome,
    PhaserFailAction,
    PhaserSolution,
    PhaserStrength,
    PhaserSweepResult,
    PredictionRequires,
    PredictionTool,
    RfreeAction,
    RfreeSample,
    RfreeTrend,
    SGConflictAction,
    TwinLawCandidate,
    TwinningScanResult,
    detect_rfree_plateau,
    extract_twin_laws_from_xtriage,
    high_rfree_diagnosis,
    idxref_failure_fix,
    interpret_phaser_result,
    matthews_copy_range,
    phaser_troubleshooting_order,
    select_best_copy_number,
    select_prediction_tool,
    sg_conflict_resolution,
    should_use_twin_refinement,
    suggest_data_range_from_mosaicity,
)


def test_idxref_failure_fix_suggests_minimum_pixels_first():
    result = idxref_failure_fix(attempt=1, current_pixels=8, current_spot_range="10001-12000")
    assert result.action == FixAction.ADJUST_PIXELS
    assert result.value == "7"
    assert result.result == FixOutcome.RETRY_XDS


def test_idxref_failure_fix_shifts_spot_range_when_pixel_range_exhausted():
    result = idxref_failure_fix(attempt=7, current_pixels=3, current_spot_range="10001-12000")
    assert result.action == FixAction.DECREASE_SPOT_RANGE
    assert result.result == FixOutcome.RETRY_XDS


def test_idxref_failure_fix_suggests_low_resolution_in_expert_mode():
    result = idxref_failure_fix(attempt=12, current_pixels=3, current_spot_range="10001-10100", simple_mode=False)
    assert result.action == FixAction.LOW_RESOLUTION_LIMIT
    assert result.result == FixOutcome.RETRY_XDS


def test_idxref_failure_fix_never_suggests_remove_idxref():
    result = idxref_failure_fix(attempt=20, current_pixels=3, current_spot_range="10001-10100", simple_mode=False)
    assert result.action != FixAction.REMOVE_IDXREF


def test_idxref_failure_fix_stops_in_simple_mode_before_correct_only():
    result = idxref_failure_fix(attempt=12, current_pixels=3, current_spot_range="10001-10100", simple_mode=True)
    assert result.action == FixAction.STOP_SIMPLE_MODE
    assert result.result == FixOutcome.STOP


def test_idxref_failure_fix_does_not_generate_invalid_narrow_spot_range():
    result = idxref_failure_fix(attempt=7, current_pixels=3, current_spot_range="60 70", simple_mode=True)
    assert result.action == FixAction.STOP_SIMPLE_MODE
    assert result.result == FixOutcome.STOP


def test_sg_conflict_resolution_returns_no_conflict_when_sgs_match():
    result = sg_conflict_resolution("P212121", "P212121", xds_retry_successful=None)
    assert result.action == SGConflictAction.NO_CONFLICT


def test_sg_conflict_resolution_accepts_new_sg_when_xds_retry_succeeds():
    result = sg_conflict_resolution("P422", "P212121", xds_retry_successful=True)
    assert result.action == SGConflictAction.ACCEPT_NEW_SG


def test_sg_conflict_resolution_falls_back_to_parallel_when_xds_retry_fails():
    result = sg_conflict_resolution("C222", "P212121", xds_retry_successful=False)
    assert result.action == SGConflictAction.PARALLEL_BRANCHES


def test_sg_conflict_resolution_suggests_xds_retry_when_pending():
    result = sg_conflict_resolution("P422", "P212121", xds_retry_successful=None)
    assert result.action == SGConflictAction.RETRY_XDS_WITH_NEW_SG


def test_suggest_data_range_from_mosaicity_returns_below_median():
    mosaicity = DataRangeMosaicity(
        frames=list(range(1, 101)),
        mosaicity_values=[0.5 if i < 50 else 1.5 for i in range(100)],
    )
    result = suggest_data_range_from_mosaicity(mosaicity, full_data_range="1 100")
    assert result.end_frame == 50
    assert result.preferred


def test_twinning_data_range_scan_identifies_lower_symmetry_subset():
    scan = TwinningScanResult(
        full_data_range="1 400", full_sg="P422",
        subsets=[
            TwinningScanResult(full_data_range="1 300", full_sg="P422", subsets=[],
                               different_sg_detected=True, subset_sg="P2", improved_aimless=True),
        ],
    )
    subset = scan.best_lower_symmetry_subset()
    assert subset is not None
    assert subset.subset_sg == "P2"


def test_matthews_copy_range_returns_plausible_integers_descending():
    result = matthews_copy_range(cell_volume=120000.0, sequence_mw=15000.0, sg_number=19)
    assert result.plausible_copies
    assert all(isinstance(n, int) for n in result.plausible_copies)
    assert result.plausible_copies == sorted(result.plausible_copies, reverse=True)


def test_interpret_phaser_result_strong_when_all_pass():
    solution = PhaserSolution(copy_num=4, tfz=10.0, llg=300, pak=0, all_placed=True)
    assert interpret_phaser_result(solution) == PhaserStrength.STRONG


def test_interpret_phaser_result_borderline_when_intermediate():
    solution = PhaserSolution(copy_num=4, tfz=7.0, llg=150, pak=1, all_placed=True)
    assert interpret_phaser_result(solution) == PhaserStrength.BORDERLINE


def test_interpret_phaser_result_weak_when_low():
    solution = PhaserSolution(copy_num=4, tfz=5.0, llg=50, pak=3, all_placed=False)
    assert interpret_phaser_result(solution) == PhaserStrength.WEAK


def test_select_best_copy_prefers_strong_pak_zero_over_high_tfz_pak_nonzero():
    sweep = PhaserSweepResult(solutions=[
        PhaserSolution(copy_num=4, tfz=9.0, llg=250, pak=0, all_placed=True),
        PhaserSolution(copy_num=6, tfz=12.0, llg=400, pak=2, all_placed=True),
        PhaserSolution(copy_num=8, tfz=3.0, llg=20, pak=100, all_placed=False),
    ])
    best = select_best_copy_number(sweep)
    assert best is not None
    assert best.copy_num == 4


def test_select_best_copy_returns_none_when_all_weak():
    sweep = PhaserSweepResult(solutions=[
        PhaserSolution(copy_num=2, tfz=5.0, llg=50, pak=10, all_placed=False),
    ])
    assert select_best_copy_number(sweep) is None


def test_phaser_troubleshooting_order_broadens_sg_first():
    assert phaser_troubleshooting_order(failure_count=1) == PhaserFailAction.BROADEN_SG


def test_phaser_troubleshooting_order_suggests_pointless_aimless_next():
    assert phaser_troubleshooting_order(failure_count=2) == PhaserFailAction.CHECK_POINTLESS_AIMLESS


def test_phaser_troubleshooting_order_suggests_different_model_last():
    assert phaser_troubleshooting_order(failure_count=3) == PhaserFailAction.TRY_DIFFERENT_MODEL


def test_extract_twin_laws_returns_empty_when_no_twinning():
    text = "Wilson B factor: 35.0\nNo twinning detected.\n"
    result = extract_twin_laws_from_xtriage(text)
    assert result == []


def test_extract_twin_laws_parses_law_and_operator():
    text = "Twinning analysis results:\n  Twin law: -h,-k,l\n  Twin fraction: 0.45\n"
    result = extract_twin_laws_from_xtriage(text)
    assert len(result) == 1
    assert result[0].operator == "-h,-k,l"
    assert result[0].fraction == 0.45


def test_extract_twin_laws_parses_multiple_laws():
    text = ("Possible twin laws:\n"
            "  -h,-k,l (merohedral)\n"
            "  h,-h-k,-l  (pseudo-merohedral)\n")
    result = extract_twin_laws_from_xtriage(text)
    assert len(result) == 2
    assert result[0].operator == "-h,-k,l"
    assert result[1].operator == "h,-h-k,-l"


def test_extract_twin_laws_parses_h_k_h_m_l_format():
    text = "Twin law: h,-h-k,-l detected\nTwin fraction: 0.48\n"
    result = extract_twin_laws_from_xtriage(text)
    assert len(result) == 1
    assert result[0].operator == "h,-h-k,-l"
    assert result[0].fraction == 0.48


def test_detect_rfree_plateau_when_continuous_improvement():
    samples = [
        RfreeSample(round=1, software="phenix", rfree=0.28),
        RfreeSample(round=2, software="phenix", rfree=0.26),
        RfreeSample(round=3, software="phenix", rfree=0.25),
    ]
    assert detect_rfree_plateau(samples) == RfreeTrend.DECREASING


def test_detect_rfree_plateau_when_b_higher_c_still_not_below_a():
    samples = [
        RfreeSample(round=1, software="phenix", rfree=0.25),
        RfreeSample(round=2, software="phenix", rfree=0.27),
        RfreeSample(round=3, software="phenix", rfree=0.26),
    ]
    assert detect_rfree_plateau(samples) == RfreeTrend.PLATEAU


def test_detect_rfree_plateau_when_b_higher_c_recovers():
    samples = [
        RfreeSample(round=1, software="phenix", rfree=0.25),
        RfreeSample(round=2, software="phenix", rfree=0.27),
        RfreeSample(round=3, software="phenix", rfree=0.24),
    ]
    assert detect_rfree_plateau(samples) == RfreeTrend.DECREASING


def test_detect_rfree_plateau_drops_to_plat_after_long_improvement():
    samples = [
        RfreeSample(round=1, software="refmac", rfree=0.30),
        RfreeSample(round=2, software="refmac", rfree=0.28),
        RfreeSample(round=3, software="refmac", rfree=0.27),
        RfreeSample(round=4, software="refmac", rfree=0.28),
        RfreeSample(round=5, software="refmac", rfree=0.27),
    ]
    assert detect_rfree_plateau(samples) == RfreeTrend.PLATEAU


def test_detect_rfree_plateau_needs_three_rounds():
    samples = [RfreeSample(round=1, software="phenix", rfree=0.25)]
    assert detect_rfree_plateau(samples) == RfreeTrend.NOT_ENOUGH_DATA


def test_should_use_twin_refinement_with_laws_available():
    assert should_use_twin_refinement(
        twin_laws=[TwinLawCandidate(operator="-h,-k,l", fraction=0.45)]
    )


def test_should_use_twin_refinement_without_laws():
    assert not should_use_twin_refinement(twin_laws=[])


def test_high_rfree_diagnosis_switches_software_on_first_high_plateau():
    action = high_rfree_diagnosis(
        rfree=0.38, current_software="phenix",
        software_already_tried=[],
        twin_laws=[],
    )
    assert action == RfreeAction.SWITCH_SOFTWARE


def test_high_rfree_diagnosis_stops_when_both_tried_and_still_high():
    action = high_rfree_diagnosis(
        rfree=0.40, current_software="refmac",
        software_already_tried=["phenix"],
        twin_laws=[],
    )
    assert action == RfreeAction.STOP_USER_INTERVENTION


def test_high_rfree_diagnosis_tries_twin_first_when_law_available():
    action = high_rfree_diagnosis(
        rfree=0.38, current_software="phenix",
        software_already_tried=[],
        twin_laws=[TwinLawCandidate(operator="-h,-k,l", fraction=0.45)],
    )
    assert action == RfreeAction.TRY_TWIN_REFINEMENT


def test_high_rfree_diagnosis_continues_when_rfree_normal():
    action = high_rfree_diagnosis(
        rfree=0.28, current_software="phenix",
        software_already_tried=["phenix"],
        twin_laws=[],
    )
    assert action == RfreeAction.CONTINUE


def test_select_prediction_tool_ordinary_protein_uses_af2():
    decision = select_prediction_tool(
        is_glycoprotein=False,
        is_metalloprotein=False,
        is_protein_nucleic_acid=False,
        is_protein_ligand=False,
    )
    assert decision.tool == PredictionTool.AF2
    assert decision.requires == PredictionRequires.NONE


def test_select_prediction_tool_glycoprotein_requires_af3():
    decision = select_prediction_tool(
        is_glycoprotein=True,
        is_metalloprotein=False,
        is_protein_nucleic_acid=False,
        is_protein_ligand=False,
    )
    assert decision.tool == PredictionTool.AF3
    assert decision.requires == PredictionRequires.USER_GLYCAN_INFO


def test_select_prediction_tool_protein_nucleic_acid_requires_af3():
    decision = select_prediction_tool(
        is_glycoprotein=False,
        is_metalloprotein=False,
        is_protein_nucleic_acid=True,
        is_protein_ligand=False,
    )
    assert decision.tool == PredictionTool.AF3


def test_select_prediction_tool_supported_metal_uses_af3():
    decision = select_prediction_tool(
        is_glycoprotein=False,
        is_metalloprotein=True,
        metal_species="Zn",
        is_protein_nucleic_acid=False,
        is_protein_ligand=False,
    )
    assert decision.tool == PredictionTool.AF3


def test_select_prediction_tool_unsupported_metal_requires_expert():
    decision = select_prediction_tool(
        is_glycoprotein=False,
        is_metalloprotein=True,
        metal_species="Hg",
        is_protein_nucleic_acid=False,
        is_protein_ligand=False,
    )
    assert decision.requires == PredictionRequires.STOP_SIMPLE_MODE


def test_select_prediction_tool_ligand_complex_uses_af3():
    decision = select_prediction_tool(
        is_glycoprotein=False,
        is_metalloprotein=False,
        is_protein_nucleic_acid=False,
        is_protein_ligand=True,
    )
    assert decision.tool == PredictionTool.AF3


def test_select_prediction_tool_hetero_oligomer_uses_af2_per_chain():
    decision = select_prediction_tool(
        is_glycoprotein=False,
        is_metalloprotein=False,
        is_protein_nucleic_acid=False,
        is_protein_ligand=False,
        is_hetero_oligomer=True,
    )
    assert decision.tool == PredictionTool.AF2
    assert decision.predict_per_chain

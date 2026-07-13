from crystal_agent.parsers import parse_phaser_log, parse_refinement_log


def test_parse_phaser_log_extracts_tfz_llg_and_clashes():
    log = """
    SOLUTION 6DIM ENSE test EULER 1 2 3 FRAC 0.1 0.2 0.3 BFAC 10
    TFZ==12.4 LLG=284
    PACKING CLASHES: 0
    """

    metrics = parse_phaser_log(log)

    assert metrics.tfz == 12.4
    assert metrics.llg == 284
    assert metrics.packing_clashes == 0


def test_parse_refinement_log_extracts_r_values():
    log = """
    Start R-work = 0.3900 R-free = 0.4400
    Final R-work = 0.2475 R-free = 0.3012
    """

    metrics = parse_refinement_log(log)

    assert metrics.initial_rwork == 0.39
    assert metrics.initial_rfree == 0.44
    assert metrics.final_rwork == 0.2475
    assert metrics.final_rfree == 0.3012

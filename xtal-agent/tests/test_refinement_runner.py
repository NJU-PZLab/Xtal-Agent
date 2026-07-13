from crystal_agent.refinement_runner import parse_refinement_log


def test_parse_refinement_log_extracts_all_metrics():
    log = """
 stage r-work r-free bonds angles b_min b_max b_ave n_water shift
Start R-work = 0.2419, R-free = 0.2360
Final R-work = 0.1993, R-free = 0.2522
"""

    result = parse_refinement_log(log)

    assert result["initial_rwork"] == 0.2419
    assert result["initial_rfree"] == 0.2360
    assert result["final_rwork"] == 0.1993
    assert result["final_rfree"] == 0.2522


def test_parse_refinement_log_empty():
    result = parse_refinement_log("")
    assert result == {}

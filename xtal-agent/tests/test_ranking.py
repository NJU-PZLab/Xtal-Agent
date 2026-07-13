from crystal_agent.ranking import rank_candidates, score_candidate
from crystal_agent.schemas import CandidateResult


def test_score_candidate_rewards_good_mr_and_refinement():
    candidate = CandidateResult(
        candidate_id="good",
        tfz=12.0,
        llg=250.0,
        packing_clashes=0,
        final_rwork=0.22,
        final_rfree=0.27,
        molprobity_score=1.7,
    )

    assert score_candidate(candidate) > 0


def test_rank_candidates_orders_best_first():
    weak = CandidateResult(candidate_id="weak", tfz=5.0, llg=20.0, final_rfree=0.45)
    strong = CandidateResult(candidate_id="strong", tfz=14.0, llg=300.0, final_rwork=0.21, final_rfree=0.26)

    ranked = rank_candidates([weak, strong])

    assert [item.candidate_id for item in ranked] == ["strong", "weak"]
    assert ranked[0].score > ranked[1].score

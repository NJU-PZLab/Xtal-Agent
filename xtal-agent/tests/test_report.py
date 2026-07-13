from crystal_agent.report import render_report
from crystal_agent.schemas import RankedCandidate


def test_render_report_contains_ranked_candidate():
    html = render_report(
        project_id="example_project",
        candidates=[
            RankedCandidate(
                candidate_id="candidate_1",
                score=88.5,
                recommendation="continue",
                reasons=["TFZ supports molecular replacement solution"],
                tfz=12.4,
                llg=284,
                final_rwork=0.24,
                final_rfree=0.29,
            )
        ],
    )

    assert "example_project" in html
    assert "candidate_1" in html
    assert "88.5" in html
    assert "TFZ supports molecular replacement solution" in html

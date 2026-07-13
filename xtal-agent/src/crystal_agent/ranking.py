from crystal_agent.schemas import CandidateResult, RankedCandidate


def score_candidate(candidate: CandidateResult) -> float:
    score = 0.0
    if candidate.tfz is not None:
        score += min(candidate.tfz, 20.0) * 3.0
        if candidate.tfz < 6.0:
            score -= 30.0
        elif candidate.tfz < 8.0:
            score -= 10.0
    if candidate.llg is not None:
        score += min(candidate.llg, 500.0) / 10.0
    if candidate.packing_clashes is not None:
        score -= candidate.packing_clashes * 5.0
    if candidate.final_rfree is not None:
        score += max(0.0, 0.5 - candidate.final_rfree) * 100.0
        if candidate.final_rfree > 0.4:
            score -= 25.0
    if candidate.final_rwork is not None and candidate.final_rfree is not None:
        gap = candidate.final_rfree - candidate.final_rwork
        if gap > 0.08:
            score -= 15.0
        elif 0.02 <= gap <= 0.06:
            score += 5.0
    if candidate.map_cc is not None:
        score += candidate.map_cc * 20.0
    if candidate.molprobity_score is not None:
        score += max(0.0, 3.0 - candidate.molprobity_score) * 10.0
    return round(score, 3)


def rank_candidates(candidates: list[CandidateResult]) -> list[RankedCandidate]:
    ranked = [_rank_candidate(candidate) for candidate in candidates]
    return sorted(ranked, key=lambda item: item.score, reverse=True)


def _rank_candidate(candidate: CandidateResult) -> RankedCandidate:
    score = score_candidate(candidate)
    reasons: list[str] = []
    if candidate.tfz is not None and candidate.tfz >= 8.0:
        reasons.append("TFZ supports molecular replacement solution")
    if candidate.final_rfree is not None and candidate.final_rfree <= 0.35:
        reasons.append("Rfree is in a plausible range after refinement")
    if candidate.packing_clashes == 0:
        reasons.append("No packing clashes reported")
    recommendation = "continue" if score >= 50.0 else "review"
    return RankedCandidate(**candidate.model_dump(), score=score, recommendation=recommendation, reasons=reasons)

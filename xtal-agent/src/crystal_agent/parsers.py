import re

from crystal_agent.schemas import PhaserMetrics, RefinementMetrics


def parse_phaser_log(text: str) -> PhaserMetrics:
    tfz = _extract_float(r"TFZ=+\s*([0-9.]+)", text)
    llg = _extract_float(r"LLG=\s*([0-9.]+)", text)
    clashes = _extract_int(r"PACKING CLASHES:\s*([0-9]+)", text)
    return PhaserMetrics(tfz=tfz, llg=llg, packing_clashes=clashes)


def parse_refinement_log(text: str) -> RefinementMetrics:
    start = re.search(r"Start R-work\s*=\s*([0-9.]+)\s*R-free\s*=\s*([0-9.]+)", text)
    final = re.search(r"Final R-work\s*=\s*([0-9.]+)\s*R-free\s*=\s*([0-9.]+)", text)
    return RefinementMetrics(
        initial_rwork=float(start.group(1)) if start else None,
        initial_rfree=float(start.group(2)) if start else None,
        final_rwork=float(final.group(1)) if final else None,
        final_rfree=float(final.group(2)) if final else None,
    )


def _extract_float(pattern: str, text: str) -> float | None:
    match = re.search(pattern, text)
    return float(match.group(1)) if match else None


def _extract_int(pattern: str, text: str) -> int | None:
    match = re.search(pattern, text)
    return int(match.group(1)) if match else None

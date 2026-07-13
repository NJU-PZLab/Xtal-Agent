import re
from pathlib import Path

from crystal_agent.runner import run_command
from crystal_agent.schemas import CandidateResult


def parse_refinement_log(text: str) -> dict:
    result = {}
    for line in text.splitlines():
        if "Start R" in line:
            m = re.search(r"Start R-work\s*=\s*([\d.]+)", line)
            if m:
                result["initial_rwork"] = float(m.group(1))
            m = re.search(r"R-free\s*=\s*([\d.]+)", line)
            if m:
                result["initial_rfree"] = float(m.group(1))
        if "Final R" in line:
            m = re.search(r"Final R-work\s*=\s*([\d.]+)", line)
            if m:
                result["final_rwork"] = float(m.group(1))
            m = re.search(r"R-free\s*=\s*([\d.]+)", line)
            if m:
                result["final_rfree"] = float(m.group(1))
    m = re.search(r"n_water\s*([\d]+)", text)
    if m:
        result["n_water"] = int(m.group(1))
    return result


def parse_molprobity_log(text: str) -> dict:
    result = {}
    m = re.search(r"Clashscore\s*=\s*([\d.]+)", text)
    if m:
        result["clashscore"] = float(m.group(1))
    m = re.search(r"MolProbity score\s*=\s*([\d.]+)", text)
    if m:
        result["molprobity_score"] = float(m.group(1))
    m = re.search(r"Ramachandran outliers\s*=\s*([\d.]+)\s*%", text)
    if m:
        result["rama_outliers"] = float(m.group(1))
    m = re.search(r"Rotamer outliers\s*=\s*([\d.]+)\s*%", text)
    if m:
        result["rotamer_outliers"] = float(m.group(1))
    return result


def run_validation(pdb_path: Path, output_dir: Path) -> dict:
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    result = run_command(
        ["phenix.molprobity", str(pdb_path.resolve()),
         f"output.prefix={output_dir / 'validation'}"],
    )

    return parse_molprobity_log(result.stdout + result.stderr)


def run_refinement(
    mtz_path: Path,
    pdb_path: Path,
    output_dir: Path,
    f_col: str | None = None,
    sigf_col: str | None = None,
    cycles: int = 5,
) -> CandidateResult:
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    mtz_path = mtz_path.resolve()
    pdb_path = pdb_path.resolve()

    if f_col and sigf_col:
        label_args = [f"labels.name={f_col},{sigf_col}"]
    else:
        label_args = []

    prefix = output_dir / "refined"

    run_command(
        ["phenix.refine", str(mtz_path), str(pdb_path),
         *label_args,
         "strategy=individual_sites+individual_adp",
         f"main.number_of_macro_cycles={cycles}",
         f"output.prefix={prefix}"],
    )

    log_path = Path(f"{prefix}_001.log")
    if not log_path.exists():
        log_path = output_dir / f"{prefix.name}_001.log"

    metrics = {}
    if log_path.exists():
        metrics = parse_refinement_log(log_path.read_text())

    return CandidateResult(
        candidate_id="refined_solution_1",
        final_rwork=metrics.get("final_rwork"),
        final_rfree=metrics.get("final_rfree"),
    )

import re
from pathlib import Path

from crystal_agent.runner import run_command
from crystal_agent.schemas import CandidateResult


def detect_labels(mtz_path: Path) -> tuple[str, str]:
    result = run_command(["pointless", "hklin", str(mtz_path)])
    for line in result.stdout.splitlines():
        m = re.search(r"Columns for amplitudes.*:\s*(\S+),\s*(\S+)", line)
        if m:
            return m.group(1), m.group(2)
    raise RuntimeError(f"Could not detect F/SIGF columns in {mtz_path}")


def parse_phaser_sol(text: str) -> CandidateResult:
    llg = None
    tfz = None
    pak = None

    for line in text.splitlines():
        m = re.search(r"LLG=(\d+)", line)
        if m:
            llg = float(m.group(1))
        m = re.search(r"TFZ==([\d.]+)", line)
        if m:
            tfz = float(m.group(1))
        m = re.search(r"PAK=(\d+)", line)
        if m:
            pak = int(m.group(1))

    return CandidateResult(
        candidate_id="phaser_solution_1",
        tfz=tfz,
        llg=llg,
        packing_clashes=pak,
    )


def _phaser_labin(f_col: str, sigf_col: str) -> str:
    f_upper = f_col.upper()
    sigf_upper = sigf_col.upper()
    if f_upper in {"IMEAN", "I", "I-OBS", "IOBS"} or sigf_upper in {"SIGIMEAN", "SIGI", "SIGI-OBS", "SIGIOBS"}:
        return f"LABIN I={f_col} SIGI={sigf_col}"
    return f"LABIN F={f_col} SIGF={sigf_col}"


def build_phaser_input(
    mtz_path: Path,
    model_path: Path,
    sequence_path: Path,
    output_root: Path,
    f_col: str,
    sigf_col: str,
    copy_num: int,
    space_group: str | None = None,
) -> str:
    model_name = model_path.stem.replace("-", "_").replace(" ", "_")[:20]
    lines = [
        "MODE MR_AUTO",
        f"HKLIN {mtz_path}",
        _phaser_labin(f_col, sigf_col),
    ]
    if space_group:
        lines.append(f"SGALTERNATIVE SELECT {space_group}")
    lines.extend(
        [
            f"ENSEMBLE {model_name} PDBFILE {model_path} IDENTITY 100",
            f"COMPOSITION PROTEIN SEQUENCE {sequence_path} NUM {copy_num}",
            f"SEARCH ENSEMBLE {model_name} NUM {copy_num}",
            "JOBS 16",
            f"ROOT {output_root}",
        ]
    )
    return "\n".join(lines) + "\n"


def run_phaser(
    mtz_path: Path,
    model_path: Path,
    sequence_path: Path,
    output_dir: Path,
    f_col: str | None = None,
    sigf_col: str | None = None,
    space_group: str | None = None,
    copy_num: int = 1,
) -> CandidateResult:
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    mtz_path = mtz_path.resolve()
    model_path = model_path.resolve()
    sequence_path = sequence_path.resolve()

    if f_col is None or sigf_col is None:
        f_col, sigf_col = detect_labels(mtz_path)

    phaser_input = build_phaser_input(
        mtz_path=mtz_path,
        model_path=model_path,
        sequence_path=sequence_path,
        output_root=output_dir / "phaser_run",
        f_col=f_col,
        sigf_col=sigf_col,
        copy_num=copy_num,
        space_group=space_group,
    )

    run_command(["phenix.phaser"], stdin=phaser_input)

    sol_path = output_dir / "phaser_run.sol"
    if sol_path.exists():
        candidate = parse_phaser_sol(sol_path.read_text())
        return candidate

    return CandidateResult(candidate_id="phaser_failed")

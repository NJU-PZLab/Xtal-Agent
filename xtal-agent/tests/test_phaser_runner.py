from pathlib import Path

from crystal_agent.phaser_runner import build_phaser_input, parse_phaser_sol


def test_parse_phaser_sol_extracts_all_metrics():
    sol = """
SOLU SET RF*0 TF*0 LLG=1656 TFZ==28.2 PAK=0 LLG=1656 TFZ==28.2
SOLU SPAC P 21 21 21
SOLU 6DIM ENSE model EULER   62.277    0.196  297.932 FRAC 0.00058 -0.00317 0.00229 BFAC 0.07816 #TFZ==28.2
"""

    result = parse_phaser_sol(sol)

    assert result.tfz == 28.2
    assert result.llg == 1656.0
    assert result.packing_clashes == 0


def test_parse_phaser_sol_empty():
    result = parse_phaser_sol("")
    assert result.tfz is None
    assert result.llg is None
    assert result.packing_clashes is None


def test_build_phaser_input_uses_intensity_labels_for_imean():
    text = build_phaser_input(
        mtz_path=Path("scaled.mtz"),
        model_path=Path("search_model.pdb"),
        sequence_path=Path("seq.fasta"),
        output_root=Path("phaser_copy_4"),
        f_col="IMEAN",
        sigf_col="SIGIMEAN",
        copy_num=4,
    )

    assert "LABIN I=IMEAN SIGI=SIGIMEAN" in text
    assert "LABIN F=IMEAN" not in text
    assert "ROOT phaser_copy_4" in text


def test_build_phaser_input_uses_amplitude_labels_for_f_columns():
    text = build_phaser_input(
        mtz_path=Path("scaled.mtz"),
        model_path=Path("search_model.pdb"),
        sequence_path=Path("seq.fasta"),
        output_root=Path("phaser_copy_1"),
        f_col="F",
        sigf_col="SIGF",
        copy_num=1,
    )

    assert "LABIN F=F SIGF=SIGF" in text

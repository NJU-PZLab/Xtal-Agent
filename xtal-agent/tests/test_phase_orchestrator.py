from pathlib import Path
import json

import pytest

from crystal_agent.decision_engine import FixAction, FixOutcome, FixResult
from crystal_agent.phase_orchestrator import PhaseResult, run_phase
from crystal_agent.phase_orchestrator import apply_idxref_fix, parse_xds_inp


def test_run_phase_rejects_unknown_phase(tmp_path: Path):
    with pytest.raises(ValueError, match="Unsupported phase"):
        run_phase(tmp_path, "phase9")


def test_phase_result_records_phase_and_status():
    result = PhaseResult(phase="phase1", status="stopped", message="blocked", artifacts=[])

    assert result.phase == "phase1"
    assert result.status == "stopped"
    assert result.message == "blocked"
    assert result.artifacts == []


def test_parse_xds_inp_reads_idxref_parameters(tmp_path: Path):
    xds_inp = tmp_path / "XDS.INP"
    xds_inp.write_text(
        "MINIMUM_NUMBER_OF_PIXELS_IN_A_SPOT=6 ! comment\n"
        "SPOT_RANGE=1 360\n"
        "INCLUDE_RESOLUTION_RANGE=50 0\n"
    )

    params = parse_xds_inp(xds_inp)

    assert params.min_pixels == 6
    assert params.spot_range == "1 360"
    assert params.resolution_range == "50 0"


def test_apply_idxref_fix_only_applies_returned_pixel_fix(tmp_path: Path):
    xds_inp = tmp_path / "XDS.INP"
    xds_inp.write_text(
        "MINIMUM_NUMBER_OF_PIXELS_IN_A_SPOT=6 ! comment\n"
        "SPOT_RANGE=1 360\n"
        "INCLUDE_RESOLUTION_RANGE=50 0\n"
    )

    fix = FixResult(action=FixAction.ADJUST_PIXELS, value="5", result=FixOutcome.RETRY_XDS)
    apply_idxref_fix(xds_inp, fix)

    text = xds_inp.read_text()
    assert "MINIMUM_NUMBER_OF_PIXELS_IN_A_SPOT=5" in text
    assert "SPOT_RANGE=1 360" in text
    assert "INCLUDE_RESOLUTION_RANGE=50 0" in text


def test_phase1_idxref_failure_calls_decision_engine_and_writes_decision(tmp_path: Path):
    (tmp_path / "XDS.INP").write_text(
        "JOB= XYCORR INIT COLSPOT IDXREF DEFPIX INTEGRATE CORRECT\n"
        "MINIMUM_NUMBER_OF_PIXELS_IN_A_SPOT=6\n"
        "SPOT_RANGE=1 360\n"
        "INCLUDE_RESOLUTION_RANGE=50 0\n"
    )
    calls = []

    def fake_runner(project_dir: Path, attempt: int):
        calls.append(attempt)
        if attempt == 1:
            (project_dir / "IDXREF.LP").write_text("!!! ERROR !!! INSUFFICIENT PERCENTAGE (< 50%)")
            return False
        (project_dir / "CORRECT.LP").write_text("SPACE_GROUP_NUMBER=1\nUNIT_CELL_CONSTANTS= 1 2 3 90 90 90")
        (project_dir / "XDS_ASCII.HKL").write_text("dummy")
        return True

    result = run_phase(tmp_path, "phase1", command_runner=fake_runner)

    assert result.status == "success"
    assert calls == [1, 2]
    decisions = [json.loads(line) for line in (tmp_path / "idxref_decisions.jsonl").read_text().splitlines()]
    assert decisions[0]["action"] == "adjust_pixels"
    assert decisions[0]["value"] == "5"
    assert "MINIMUM_NUMBER_OF_PIXELS_IN_A_SPOT=5" in (tmp_path / "XDS.INP").read_text()


def test_phase2_sg_conflict_records_retry_decision(tmp_path: Path):
    (tmp_path / "xds_sg.txt").write_text("P212121")
    (tmp_path / "aimless_sg.txt").write_text("P222")

    result = run_phase(tmp_path, "phase2")

    assert result.status == "stopped"
    text = (tmp_path / "sg_conflict_decision.txt").read_text()
    assert "retry_xds_with_new_sg" in text
    assert "P222" in text


def test_phase3_records_prediction_tool_and_matthews(tmp_path: Path):
    (tmp_path / "manifest.yaml").write_text("workflow_mode: simple\n")
    (tmp_path / "rcsb.fasta").write_text(">protein\nAAAA\n>rna\nAAAAAA\n")
    (tmp_path / "cell_sg.txt").write_text("1000000 1 50000")

    result = run_phase(tmp_path, "phase3")

    assert result.status == "success"
    assert "AF3" in (tmp_path / "prediction_tool_decision.txt").read_text()
    assert (tmp_path / "matthews_copy_range.txt").exists()


def test_phase4_records_phaser_copy_selection_and_troubleshooting(tmp_path: Path):
    (tmp_path / "phaser_sweep.json").write_text(
        '[{"copies": 1, "tfz": 5, "llg": 100, "pak": 0}, {"copies": 2, "tfz": 9, "llg": 250, "pak": 0}]'
    )
    (tmp_path / "phaser_failure_count.txt").write_text("1")

    result = run_phase(tmp_path, "phase4")

    assert result.status == "success"
    assert "2" in (tmp_path / "phaser_copy_selection.txt").read_text()
    assert (tmp_path / "phaser_troubleshooting.txt").exists()


def test_modelcraft_failure_is_not_a_stop_and_writes_attempt_marker(tmp_path: Path, monkeypatch):
    from crystal_agent import phase_orchestrator as po

    (tmp_path / "refmac_r4.pdb").write_text("MODEL\n")
    (tmp_path / "ctruncate_free.mtz").write_text("data\n")
    (tmp_path / "seq.fasta").write_text(">x\nACDE\n")

    def fake_subprocess_run(cmd, *args, **kwargs):
        class _R:
            stdout = "modelcraft failed to produce output\n"
            stderr = ""
            returncode = 1
        return _R()

    monkeypatch.setattr(po.subprocess, "run", fake_subprocess_run)

    result = run_phase(tmp_path, "phase5")

    assert result.status != "stopped"
    assert (tmp_path / "modelcraft_run.log").exists()


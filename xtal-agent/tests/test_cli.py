from pathlib import Path

from typer.testing import CliRunner

from crystal_agent.cli import _format_check_message, app


runner = CliRunner()


def test_validate_manifest_command(tmp_path: Path):
    project = tmp_path / "project"
    (project / "input" / "diffraction").mkdir(parents=True)
    (project / "input" / "models").mkdir(parents=True)
    (project / "input" / "sequence.fasta").write_text(">target\nACDE\n")
    (project / "input" / "models" / "af_model.pdb").write_text("MODEL        1\nENDMDL\n")
    manifest_path = project / "manifest.yaml"
    manifest_path.write_text(
        """
project_id: cli_project
workflow_mode: expert
inputs:
  diffraction:
    type: raw_images
    path: input/diffraction/
  sequence:
    path: input/sequence.fasta
  models:
    - type: alphafold
      path: input/models/af_model.pdb
constraints:
  ligand_codes: []
  metal_sites: []
policy:
  max_parallel_jobs: 4
""".strip()
    )

    result = runner.invoke(app, ["validate-manifest", str(manifest_path)])

    assert result.exit_code == 0
    assert "cli_project" in result.stdout
    assert "expert" in result.stdout


def test_check_env_command_accepts_minimal_python_check():
    result = runner.invoke(app, ["check-env", "--minimal"])

    assert result.exit_code == 0
    assert "python" in result.stdout


def test_format_check_message_summarizes_phenix_version():
    output = """-------------------------------------------------------------------------------
  Phenix: Python-based Hierarchical ENvironment for Integrated Xtallography
  Version: 2.1
  Release tag: 6048
-------------------------------------------------------------------------------
"""

    assert _format_check_message("phenix.version", output, None) == "Version: 2.1"


def test_format_check_message_summarizes_multiple_gpus():
    output = """0, NVIDIA GeForce RTX 4090, 100 MiB, 49140 MiB, 0 %
1, NVIDIA GeForce RTX 4090, 22334 MiB, 49140 MiB, 100 %
2, NVIDIA GeForce RTX 4090, 80 MiB, 49140 MiB, 0 %
"""

    assert _format_check_message("nvidia-smi", output, None) == "3 GPUs detected"


def test_check_gpu_command_prints_all_detected_gpu_lines(monkeypatch):
    from crystal_agent import cli
    from crystal_agent.schemas import SoftwareCheck

    def fake_check_required_commands(_commands=None):
        return [
            SoftwareCheck(
                name="nvidia-smi",
                command=["nvidia-smi"],
                available=True,
                exit_code=0,
                version_output=(
                    "0, NVIDIA GeForce RTX 4090, 100 MiB, 49140 MiB, 0 %\n"
                    "1, NVIDIA GeForce RTX 4090, 22334 MiB, 49140 MiB, 100 %\n"
                ),
                error=None,
            )
        ]

    monkeypatch.setattr(cli, "check_required_commands", fake_check_required_commands)

    result = runner.invoke(app, ["check-gpu"])

    assert result.exit_code == 0
    assert "GPU 0" in result.stdout
    assert "GPU 1" in result.stdout
    assert "RTX 4090" in result.stdout


def test_run_pipeline_rejects_expert_mode_project(tmp_path: Path):
    project = tmp_path / "project"
    (project / "input" / "diffraction").mkdir(parents=True)
    (project / "input" / "models").mkdir(parents=True)
    (project / "input" / "sequence.fasta").write_text(">target\nACDE\n")
    (project / "input" / "models" / "af_model.pdb").write_text("MODEL        1\nENDMDL\n")
    manifest_path = project / "manifest.yaml"
    manifest_path.write_text(
        """
project_id: cli_project
workflow_mode: expert
inputs:
  diffraction:
    type: raw_images
    path: input/diffraction/
  sequence:
    path: input/sequence.fasta
  models:
    - type: alphafold
      path: input/models/af_model.pdb
constraints:
  ligand_codes: []
  metal_sites: []
policy:
  max_parallel_jobs: 4
""".strip()
    )

    result = runner.invoke(app, ["run-pipeline", str(project)])

    assert result.exit_code == 1
    assert "workflow_mode=expert" in result.stdout
    assert "interactive agent" in result.stdout
    assert "autonomous CLI pipeline" in result.stdout


def test_run_phase_cli_rejects_unknown_phase(tmp_path: Path):
    result = runner.invoke(app, ["run-phase", str(tmp_path), "phase9"])

    assert result.exit_code != 0
    assert "Unsupported phase" in result.output


def test_run_phase_cli_rejects_expert_mode_project_without_approval(tmp_path: Path):
    project = tmp_path / "project"
    (project / "input" / "diffraction").mkdir(parents=True)
    (project / "input" / "models").mkdir(parents=True)
    (project / "input" / "sequence.fasta").write_text(">target\nACDE\n")
    (project / "input" / "models" / "af_model.pdb").write_text("MODEL        1\nENDMDL\n")
    (project / "manifest.yaml").write_text(
        """
project_id: cli_project
workflow_mode: expert
inputs:
  diffraction:
    type: raw_images
    path: input/diffraction/
  sequence:
    path: input/sequence.fasta
  models:
    - type: alphafold
      path: input/models/af_model.pdb
constraints:
  ligand_codes: []
  metal_sites: []
policy:
  max_parallel_jobs: 4
""".strip()
    )

    result = runner.invoke(app, ["run-phase", str(project), "phase1"])

    assert result.exit_code == 1
    assert "workflow_mode=expert" in result.output
    assert "expert-approve" in result.output


def test_expert_approve_cli_records_approval(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "manifest.yaml").write_text("workflow_mode: expert\n")

    result = runner.invoke(
        app,
        ["expert-approve", str(project), "phase1_correct_lp", "--reason", "inspect IDXREF first"],
    )

    assert result.exit_code == 0
    assert "phase1_correct_lp" in result.output
    assert (project / ".expert_approvals.json").exists()


def test_map_ligand_atoms_cli_is_discoverable():
    result = runner.invoke(app, ["map-ligand-atoms", "--help"])

    assert result.exit_code == 0
    assert "ligand atom-name mapping" in result.output


def test_checkpoint_command_uses_canonical_public_name():
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "enforce-checkpoint" in result.output
    assert "enforce-checkpoint-cmd" not in result.output

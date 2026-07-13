from pathlib import Path

import pytest

from crystal_agent.manifest import load_manifest
from crystal_agent.schemas import DiffractionType, ModelType


def test_load_valid_manifest(tmp_path: Path):
    project = tmp_path / "project"
    (project / "input" / "diffraction").mkdir(parents=True)
    (project / "input" / "models").mkdir(parents=True)
    (project / "input" / "sequence.fasta").write_text(">target\nACDE\n")
    (project / "input" / "models" / "af_model.pdb").write_text("MODEL        1\nENDMDL\n")
    manifest_path = project / "manifest.yaml"
    manifest_path.write_text(
        """
project_id: example_project
workflow_mode: simple
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
  space_group_hint: null
  wavelength: null
  expected_oligomer: unknown
  ligand_codes: []
  metal_sites: []
policy:
  max_parallel_jobs: 16
  use_dials: true
  use_xds: false
  allow_model_trimming: true
  require_human_gate_for_ligands: true
""".strip()
    )

    manifest = load_manifest(manifest_path)

    assert manifest.project_id == "example_project"
    assert manifest.inputs.diffraction.type == DiffractionType.RAW_IMAGES
    assert manifest.inputs.models[0].type == ModelType.ALPHAFOLD
    assert manifest.policy.max_parallel_jobs == 16
    assert manifest.workflow_mode.value == "simple"


def test_load_manifest_rejects_missing_sequence(tmp_path: Path):
    project = tmp_path / "project"
    (project / "input" / "diffraction").mkdir(parents=True)
    (project / "input" / "models").mkdir(parents=True)
    (project / "input" / "models" / "af_model.pdb").write_text("MODEL        1\nENDMDL\n")
    manifest_path = project / "manifest.yaml"
    manifest_path.write_text(
        """
project_id: bad_project
workflow_mode: expert
inputs:
  diffraction:
    type: raw_images
    path: input/diffraction/
  sequence:
    path: input/missing.fasta
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

    with pytest.raises(FileNotFoundError, match="Sequence file not found"):
        load_manifest(manifest_path)


def test_load_manifest_requires_workflow_mode(tmp_path: Path):
    project = tmp_path / "project"
    (project / "input" / "diffraction").mkdir(parents=True)
    (project / "input" / "models").mkdir(parents=True)
    (project / "input" / "sequence.fasta").write_text(">target\nACDE\n")
    (project / "input" / "models" / "af_model.pdb").write_text("MODEL        1\nENDMDL\n")
    manifest_path = project / "manifest.yaml"
    manifest_path.write_text(
        """
project_id: example_project
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

    with pytest.raises(ValueError, match="workflow_mode"):
        load_manifest(manifest_path)


def test_load_manifest_accepts_expert_workflow_mode(tmp_path: Path):
    project = tmp_path / "project"
    (project / "input" / "diffraction").mkdir(parents=True)
    (project / "input" / "models").mkdir(parents=True)
    (project / "input" / "sequence.fasta").write_text(">target\nACDE\n")
    (project / "input" / "models" / "af_model.pdb").write_text("MODEL        1\nENDMDL\n")
    manifest_path = project / "manifest.yaml"
    manifest_path.write_text(
        """
project_id: expert_project
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

    manifest = load_manifest(manifest_path)

    assert manifest.workflow_mode.value == "expert"

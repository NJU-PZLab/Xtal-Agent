from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field


class DiffractionType(StrEnum):
    RAW_IMAGES = "raw_images"
    MTZ = "mtz"


class ModelType(StrEnum):
    ALPHAFOLD = "alphafold"
    HOMOLOG = "homolog"


class WorkflowMode(StrEnum):
    SIMPLE = "simple"
    EXPERT = "expert"


class DiffractionInput(BaseModel):
    type: DiffractionType
    path: Path


class SequenceInput(BaseModel):
    path: Path


class ModelInput(BaseModel):
    type: ModelType
    path: Path


class ProjectInputs(BaseModel):
    diffraction: DiffractionInput
    sequence: SequenceInput
    models: list[ModelInput] = Field(min_length=1)


class ProjectConstraints(BaseModel):
    space_group_hint: str | None = None
    wavelength: float | None = None
    expected_oligomer: str = "unknown"
    ligand_codes: list[str] = Field(default_factory=list)
    metal_sites: list[str] = Field(default_factory=list)
    f_col: str | None = None
    sigf_col: str | None = None


class ProjectPolicy(BaseModel):
    max_parallel_jobs: int = Field(default=4, ge=1)
    use_dials: bool = True
    use_xds: bool = False
    allow_model_trimming: bool = True
    require_human_gate_for_ligands: bool = True


class VisionConfig(BaseModel):
    """Manifest-level vision-module gate (stop-and-ask, no inferred defaults).

    Required field on every manifest. Missing field means: ask the user
    whether to enable the visual scan, then have them write the result back
    into manifest.yaml. See ``load_manifest`` in ``manifest.py``.
    """

    enabled: bool


class CootConfig(BaseModel):
    """Post-refinement COOT module (enabled by default)."""

    enabled: bool = True
    strategy: str = "auto"
    geometry_redline: float = Field(default=20.0, ge=0)
    twin_law: str | None = None


class ProjectManifest(BaseModel):
    project_id: str = Field(min_length=1)
    workflow_mode: WorkflowMode
    vision: VisionConfig
    inputs: ProjectInputs
    constraints: ProjectConstraints = Field(default_factory=ProjectConstraints)
    policy: ProjectPolicy = Field(default_factory=ProjectPolicy)
    coot: CootConfig = Field(default_factory=CootConfig)


class CommandResult(BaseModel):
    command: list[str]
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float


class SoftwareCheck(BaseModel):
    name: str
    command: list[str]
    available: bool
    exit_code: int | None
    version_output: str
    error: str | None = None


class PhaserMetrics(BaseModel):
    tfz: float | None = None
    llg: float | None = None
    packing_clashes: int | None = None


class RefinementMetrics(BaseModel):
    initial_rwork: float | None = None
    initial_rfree: float | None = None
    final_rwork: float | None = None
    final_rfree: float | None = None


class CandidateResult(BaseModel):
    candidate_id: str
    tfz: float | None = None
    llg: float | None = None
    packing_clashes: int | None = None
    final_rwork: float | None = None
    final_rfree: float | None = None
    map_cc: float | None = None
    molprobity_score: float | None = None


class RankedCandidate(CandidateResult):
    score: float
    recommendation: str
    reasons: list[str]

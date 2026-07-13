from pathlib import Path

import yaml
from pydantic import ValidationError

from crystal_agent.schemas import DiffractionType, ProjectManifest


def load_manifest(path: str | Path) -> ProjectManifest:
    manifest_path = Path(path)
    data = yaml.safe_load(manifest_path.read_text())
    try:
        manifest = ProjectManifest.model_validate(data)
    except ValidationError as exc:
        if any(err["loc"] == ("workflow_mode",) for err in exc.errors()):
            raise ValueError(
                "Manifest must specify workflow_mode: simple or workflow_mode: expert"
            ) from exc
        raise
    _validate_paths(manifest_path.parent, manifest)
    return manifest


def _validate_paths(project_root: Path, manifest: ProjectManifest) -> None:
    diffraction_path = project_root / manifest.inputs.diffraction.path
    sequence_path = project_root / manifest.inputs.sequence.path

    if manifest.inputs.diffraction.type == DiffractionType.RAW_IMAGES:
        if not diffraction_path.is_dir():
            raise FileNotFoundError(f"Diffraction image directory not found: {diffraction_path}")
    elif not diffraction_path.is_file():
        raise FileNotFoundError(f"MTZ file not found: {diffraction_path}")

    if not sequence_path.is_file():
        raise FileNotFoundError(f"Sequence file not found: {sequence_path}")

    for model in manifest.inputs.models:
        model_path = project_root / model.path
        if not model_path.is_file():
            raise FileNotFoundError(f"Search model file not found: {model_path}")

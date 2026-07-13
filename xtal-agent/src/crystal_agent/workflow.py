from crystal_agent.schemas import DiffractionType, WorkflowMode


class WorkflowModeError(RuntimeError):
    """Base class for workflow mode gating errors."""


class ExpertModeRequired(WorkflowModeError):
    """Raised when an autonomous path is attempted for an expert project."""


class UnsupportedSimpleModeInput(WorkflowModeError):
    """Raised when the lightweight CLI cannot carry a simple-mode project."""


def ensure_autonomous_cli_allowed(workflow_mode: WorkflowMode) -> None:
    if workflow_mode == WorkflowMode.EXPERT:
        raise ExpertModeRequired(
            "Project is configured with workflow_mode=expert. "
            "Use the interactive agent workflow instead of the autonomous CLI pipeline."
        )


def ensure_simple_mode_inputs_supported(
    workflow_mode: WorkflowMode,
    diffraction_type: DiffractionType,
) -> None:
    if workflow_mode == WorkflowMode.SIMPLE and diffraction_type == DiffractionType.RAW_IMAGES:
        raise UnsupportedSimpleModeInput(
            "Simple-mode raw image projects require the interactive agent workflow. "
            "The local autonomous CLI pipeline does not yet implement raw image processing."
        )

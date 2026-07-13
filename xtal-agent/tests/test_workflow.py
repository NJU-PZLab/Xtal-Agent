from crystal_agent.schemas import DiffractionType, WorkflowMode
from crystal_agent.workflow import (
    ExpertModeRequired,
    UnsupportedSimpleModeInput,
    ensure_autonomous_cli_allowed,
    ensure_simple_mode_inputs_supported,
)


def test_ensure_autonomous_cli_allowed_accepts_simple_mode():
    ensure_autonomous_cli_allowed(WorkflowMode.SIMPLE)


def test_ensure_autonomous_cli_allowed_rejects_expert_mode():
    try:
        ensure_autonomous_cli_allowed(WorkflowMode.EXPERT)
    except ExpertModeRequired as exc:
        assert "workflow_mode=expert" in str(exc)
        assert "interactive agent workflow" in str(exc)
    else:
        raise AssertionError("Expected ExpertModeRequired")


def test_ensure_simple_mode_inputs_supported_accepts_mtz():
    ensure_simple_mode_inputs_supported(WorkflowMode.SIMPLE, DiffractionType.MTZ)


def test_ensure_simple_mode_inputs_supported_rejects_raw_images_for_cli():
    try:
        ensure_simple_mode_inputs_supported(WorkflowMode.SIMPLE, DiffractionType.RAW_IMAGES)
    except UnsupportedSimpleModeInput as exc:
        assert "raw image" in str(exc).lower()
        assert "interactive agent workflow" in str(exc)
    else:
        raise AssertionError("Expected UnsupportedSimpleModeInput")


def test_ensure_simple_mode_inputs_supported_skips_expert_mode():
    ensure_simple_mode_inputs_supported(WorkflowMode.EXPERT, DiffractionType.RAW_IMAGES)

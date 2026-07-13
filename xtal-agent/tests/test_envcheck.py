from crystal_agent.envcheck import check_command, check_required_commands


def test_check_required_commands_includes_nvidia_smi_by_default():
    checks = check_required_commands({"nvidia-smi": ["--query-gpu=index", "--format=csv,noheader"]})

    assert len(checks) == 1
    assert checks[0].name == "nvidia-smi"


def test_check_command_reports_available_python():
    check = check_command("python", ["--version"])

    assert check.name == "python"
    assert check.available is True
    assert check.exit_code == 0
    assert "Python" in check.version_output


def test_check_command_reports_missing_command():
    check = check_command("definitely_missing_crystal_tool_12345", ["--version"])

    assert check.name == "definitely_missing_crystal_tool_12345"
    assert check.available is False
    assert check.exit_code is None


def test_check_required_commands_accepts_custom_specs():
    checks = check_required_commands({"python": ["--version"]})

    assert len(checks) == 1
    assert checks[0].name == "python"
    assert checks[0].available is True

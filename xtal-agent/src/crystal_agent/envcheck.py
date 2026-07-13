import shutil

from crystal_agent.runner import run_command
from crystal_agent.schemas import SoftwareCheck


DEFAULT_COMMANDS: dict[str, list[str]] = {
    "dials.version": [],
    "pointless": ["--help"],
    "aimless": ["--help"],
    "refmac5": ["--help"],
    "phenix.version": [],
    "phenix.phaser": [],
    "phenix.refine": ["--help"],
    "nvidia-smi": ["--query-gpu=index,name,memory.used,memory.total,utilization.gpu", "--format=csv,noheader"],
    "coot": ["--version"],
    "xds_par": [],
}


def check_command(name: str, args: list[str]) -> SoftwareCheck:
    found = shutil.which(name)
    if found is None:
        return SoftwareCheck(
            name=name,
            command=[name, *args],
            available=False,
            exit_code=None,
            version_output="",
            error="command not found in PATH",
        )

    result = run_command([name, *args])
    output = (result.stdout + result.stderr).strip()
    return SoftwareCheck(
        name=name,
        command=[name, *args],
        available=True,
        exit_code=result.exit_code,
        version_output=output,
        error=None if result.exit_code == 0 else f"help flag returned exit code {result.exit_code}",
    )


def check_required_commands(commands: dict[str, list[str]] | None = None) -> list[SoftwareCheck]:
    specs = commands if commands is not None else DEFAULT_COMMANDS
    return [check_command(name, args) for name, args in specs.items()]

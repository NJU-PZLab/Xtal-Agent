import subprocess
import time

from crystal_agent.schemas import CommandResult


def run_command(command: list[str], cwd: str | None = None, stdin: str | None = None) -> CommandResult:
    start = time.monotonic()
    completed = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        capture_output=True,
        input=stdin,
        check=False,
    )
    return CommandResult(
        command=command,
        exit_code=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
        duration_seconds=time.monotonic() - start,
    )

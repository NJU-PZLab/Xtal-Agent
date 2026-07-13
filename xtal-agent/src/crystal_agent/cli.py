from pathlib import Path
import json

import typer
from rich.console import Console
from rich.table import Table

from crystal_agent.envcheck import check_required_commands
from crystal_agent.architecture import audit_architecture as run_architecture_audit
from crystal_agent.architecture import collect_backup_targets
from crystal_agent.architecture import get_command_template
from crystal_agent.architecture import get_naming_conventions
from crystal_agent.architecture import get_phase_guide
from crystal_agent.architecture import list_command_templates as get_command_template_names
from crystal_agent.manifest import load_manifest
from crystal_agent.pipeline import run_project
from crystal_agent.phase_orchestrator import run_phase as run_orchestrated_phase
from crystal_agent.step_tracker import (
    StepTracker,
    Guard,
    approve_expert_step,
    enforce_checkpoint,
    is_expert_project,
    resume_gate,
)


app = typer.Typer(help="Local crystallography workflow automation helpers")
console = Console()


def _format_check_message(name: str, output: str, error: str | None) -> str:
    if not output:
        return error or ""

    lines = [line.strip() for line in output.splitlines() if line.strip()]
    if not lines:
        return error or ""

    if name == "phenix.version":
        for line in lines:
            if line.startswith("Version:") or line.startswith("Release tag:"):
                return line
        return lines[0]

    if name == "nvidia-smi":
        return f"{len(lines)} GPUs detected"

    return lines[0]


def _gpu_rows(output: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = [part.strip() for part in line.split(",")]
        if len(parts) < 5:
            continue
        rows.append(parts[:5])
    return rows


@app.command()
def validate_manifest(path: Path) -> None:
    manifest = load_manifest(path)
    console.print(
        f"Manifest valid: [bold]{manifest.project_id}[/bold] "
        f"(workflow_mode={manifest.workflow_mode.value})"
    )


@app.command()
def check_env(minimal: bool = typer.Option(False, help="Only check Python availability")) -> None:
    commands = {"python": ["--version"]} if minimal else None
    checks = check_required_commands(commands)
    table = Table(title="Crystal Agent Environment Check")
    table.add_column("Tool")
    table.add_column("Available")
    table.add_column("Exit Code")
    table.add_column("Message")
    for check in checks:
        table.add_row(
            check.name,
            "yes" if check.available else "no",
            "" if check.exit_code is None else str(check.exit_code),
            _format_check_message(check.name, check.version_output, check.error),
        )
    console.print(table)


@app.command()
def check_gpu() -> None:
    checks = check_required_commands(
        {"nvidia-smi": ["--query-gpu=index,name,memory.used,memory.total,utilization.gpu", "--format=csv,noheader"]}
    )
    check = checks[0]
    if not check.available:
        console.print("nvidia-smi not available")
        raise typer.Exit(code=1)

    table = Table(title="GPU Availability")
    table.add_column("GPU")
    table.add_column("Name")
    table.add_column("Memory Used")
    table.add_column("Memory Total")
    table.add_column("Utilization")
    for gpu_index, name, memory_used, memory_total, utilization in _gpu_rows(check.version_output):
        table.add_row(f"GPU {gpu_index}", name, memory_used, memory_total, utilization)
    console.print(table)


@app.command()
def run_pipeline(project_dir: Path) -> None:
    console.print(f"[bold]Running pipeline for project: {project_dir}[/bold]")
    try:
        ranked = run_project(project_dir)
    except RuntimeError as exc:
        console.print(str(exc))
        raise typer.Exit(code=1) from exc
    table = Table(title="Ranked Candidates")
    table.add_column("Candidate")
    table.add_column("TFZ")
    table.add_column("LLG")
    table.add_column("Rfree")
    table.add_column("Score")
    for item in ranked:
        table.add_row(
            item.candidate_id,
            str(item.tfz) if item.tfz is not None else "-",
            str(item.llg) if item.llg is not None else "-",
            str(item.final_rfree) if item.final_rfree is not None else "-",
            str(item.score) if hasattr(item, "score") else "-",
        )
    console.print(table)
    console.print(f"Report: [bold]{project_dir / 'reports' / 'validation_summary.html'}[/bold]")


@app.command()
def run_phase(project_dir: Path, phase: str, mode: str = typer.Option("simple", help="simple or expert")) -> None:
    """Run one orchestrated crystallography phase with code-backed decisions."""
    if is_expert_project(project_dir):
        console.print(
            "Project is configured with workflow_mode=expert. "
            "Do not use autonomous run-phase. Approve and run named steps with "
            f"crystal-agent expert-approve {project_dir} <step> --reason '<why>' "
            "followed by crystal-agent guard --before/--after."
        )
        raise typer.Exit(code=1)
    try:
        result = run_orchestrated_phase(project_dir, phase, mode=mode)
    except ValueError as exc:
        console.print(str(exc))
        raise typer.Exit(code=1) from exc
    console.print(f"{result.phase}: {result.status} - {result.message}")
    for artifact in result.artifacts:
        console.print(f"artifact: {artifact}")
    if result.status == "stopped":
        raise typer.Exit(code=1)


@app.command(context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def map_ligand_atoms(ctx: typer.Context) -> None:
    """Run AF3-to-CCP4 ligand atom-name mapping helper."""
    from crystal_agent import map_ligand_atoms as mapper

    mapper.main(list(ctx.args))


@app.command()
def verify_steps(project_dir: Path) -> None:
    """Verify all pipeline steps for a project, report skipped/incomplete steps.
    Returns non-zero exit code if any step is skipped or incomplete."""
    tracker = StepTracker(str(project_dir))
    _, exit_code = tracker.run()
    if exit_code != 0:
        raise typer.Exit(code=1)


@app.command()
def guard(
    project_dir: Path,
    before: str = typer.Option(None, help="Step name about to execute"),
    after: str = typer.Option(None, help="Step name just completed"),
    reset: bool = typer.Option(False, help="Reset guard state"),
) -> None:
    """Enforce step-by-step execution. Must be called BEFORE and AFTER each pipeline step.
    Prevents batch-skipping of mandatory steps."""
    g = Guard(str(project_dir))
    if reset:
        g.state = {"completed": [], "current": None}
        g._save()
        console.print("[bold green]Guard state reset.[/bold green]")
        return
    if before:
        g.before(before)
    if after:
        g.after(after)


@app.command()
def expert_approve(
    project_dir: Path,
    step_name: str,
    reason: str = typer.Option(..., "--reason", help="Why the human approved this expert-mode step"),
) -> None:
    """Record one expert-mode approval token for a named guarded step."""
    if not is_expert_project(project_dir):
        console.print("Project is not configured with workflow_mode=expert.")
        raise typer.Exit(code=1)
    approve_expert_step(str(project_dir), step_name, reason)
    console.print(f"Approved expert step: {step_name}")


@app.command()
def backup_targets(root: Path) -> None:
    """List documentation and code targets that should be backed up before edits."""
    for target in collect_backup_targets(root):
        console.print(target)


@app.command()
def audit_architecture(root: Path) -> None:
    """Verify mandatory crystallography rules are still present after docs/skill edits."""
    result = run_architecture_audit(root)
    if result.passed:
        console.print("Architecture audit passed: all mandatory rules found.")
        return
    console.print("Missing mandatory rules:")
    for rule in result.missing_rules:
        console.print(f"- {rule}")
    raise typer.Exit(code=1)


@app.command()
def phase_guide(phase: str) -> None:
    """Print the code-backed command guide for a mandatory workflow phase."""
    try:
        guide = get_phase_guide(phase)
    except KeyError as exc:
        console.print(str(exc))
        raise typer.Exit(code=1) from exc

    console.print(f"[bold]{guide.title}[/bold]")
    console.print("Code calls:")
    for command in guide.code_calls:
        console.print(f"- {command}")
    console.print("Mandatory rules:")
    for rule in guide.mandatory_rules:
        console.print(f"- {rule}")
    console.print("Outputs:")
    for output in guide.outputs:
        console.print(f"- {output}")
    console.print("Command templates:")
    for name in guide.command_templates:
        console.print(f"- crystal-agent command-template {name}")


@app.command()
def command_template(
    name: str,
    output_format: str = typer.Option("text", "--format", help="text, json, or markdown"),
) -> None:
    """Print a canonical crystallography command template by operation name."""
    try:
        template = get_command_template(name)
    except KeyError as exc:
        console.print(str(exc))
        raise typer.Exit(code=1) from exc

    if output_format == "json":
        print(json.dumps(template.__dict__, indent=2))
        return
    if output_format == "markdown":
        console.print(f"# {template.name}\n")
        console.print("## Preconditions")
        console.print(template.preconditions)
        console.print("\n## Command")
        console.print(f"```bash\n{template.command}\n```")
        console.print("\n## Outputs")
        console.print(template.outputs)
        if template.notes:
            console.print("\n## Notes")
            console.print(template.notes)
        return
    if output_format != "text":
        console.print("Unsupported format. Use text, json, or markdown.")
        raise typer.Exit(code=1)

    console.print(f"[bold]{template.name}[/bold]")
    console.print("Preconditions:")
    console.print(template.preconditions)
    console.print("Command:")
    console.print(template.command)
    console.print("Outputs:")
    console.print(template.outputs)
    if template.notes:
        console.print("Notes:")
        console.print(template.notes)


@app.command()
def list_command_templates() -> None:
    """List available canonical crystallography command templates."""
    for name in get_command_template_names():
        console.print(name)


@app.command()
def naming_guide() -> None:
    """Print canonical file naming and resume rules for workflow verification."""
    console.print("[bold]Canonical naming conventions[/bold]")
    for key, value in get_naming_conventions().items():
        console.print(f"- {key}: {value}")
    console.print("Resume rule: continue with the next numeric round and do not renumber existing outputs.")
    console.print("Minimum rule: extra rounds are allowed; fewer than mandatory minimum rounds fail verification.")


@app.command(name="enforce-checkpoint")
def enforce_checkpoint_cmd(project_dir: Path) -> None:
    """Block execution if a guard step is unclosed. Use before any crystallography operation."""
    enforce_checkpoint(str(project_dir))


@app.command()
def resume_barrier(project_dir: Path) -> None:
    """Combined resume gate: enforce-checkpoint + naming-guide + verify-steps. Use after any interruption."""
    from crystal_agent.step_tracker import enforce_checkpoint
    enforce_checkpoint(str(project_dir))
    keys = get_naming_conventions()
    for key, value in keys.items():
        console.print(f"- {key}: {value}")
    console.print("Resume rule: next numeric round, do not renumber.")
    tracker = StepTracker(str(project_dir))
    _, exit_code = tracker.run()
    if exit_code != 0:
        raise typer.Exit(code=1)

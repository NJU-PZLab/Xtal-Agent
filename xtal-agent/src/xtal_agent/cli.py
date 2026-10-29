from pathlib import Path
import json

import typer
from rich.console import Console
from rich.table import Table

from xtal_agent.coot_runner import CootNotAvailable, coot_available, run_coot_optimization
from xtal_agent.envcheck import check_required_commands
from xtal_agent.architecture import audit_architecture as run_architecture_audit
from xtal_agent.architecture import collect_backup_targets
from xtal_agent.architecture import get_command_template
from xtal_agent.architecture import get_naming_conventions
from xtal_agent.architecture import get_phase_guide
from xtal_agent.architecture import list_command_templates as get_command_template_names
from xtal_agent.manifest import load_manifest
from xtal_agent.pipeline import run_project
from xtal_agent.phase_orchestrator import run_phase as run_orchestrated_phase
from xtal_agent.step_tracker import (
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
    table = Table(title="Xtal-Agent Environment Check")
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
            f"xtal-agent expert-approve {project_dir} <step> --reason '<why>' "
            "followed by xtal-agent guard --before/--after."
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
    from xtal_agent import map_ligand_atoms as mapper

    mapper.main(list(ctx.args))


@app.command(name="coot-optimize")
def coot_optimize(
    project_dir: Path,
    pdb: Path = typer.Option(None, help="Input PDB (default: best refined model)"),
    mtz: Path = typer.Option(None, help="Input MTZ (default: companion MTZ)"),
    resolution: float = typer.Option(None, help="Resolution in A (default: validated_resolution.txt)"),
    strategy: str = typer.Option(None, help="COOT strategy: auto, waters, or no_waters"),
) -> None:
    """Run the COOT post-refinement module on a project."""
    import re

    project_dir = Path(project_dir).resolve()
    if not coot_available():
        console.print("COOT is not available. Install COOT or set XTAL_AGENT_COOT_BIN.")
        raise typer.Exit(code=1)

    if pdb is None:
        for pattern in ("refmac_r*.pdb", "phenix_r*.pdb", "modelcraft_r4.pdb", "coot_refined.pdb"):
            found = sorted(project_dir.glob(pattern))
            if found:
                pdb = found[-1]
                break
    if mtz is None:
        for name in ("coot_refined.mtz", "refmac_r4.mtz", "phenix_r4_001.mtz", "ctruncate_free.mtz"):
            if (project_dir / name).exists():
                mtz = project_dir / name
                break
    if pdb is None or mtz is None:
        console.print("Could not infer input PDB/MTZ; pass --pdb and --mtz.")
        raise typer.Exit(code=1)
    if resolution is None:
        validated = project_dir / "validated_resolution.txt"
        if validated.exists():
            try:
                resolution = float(validated.read_text().strip().split()[0])
            except (ValueError, IndexError):
                resolution = None
        if resolution is None:
            for name in ("molprobity_final.log", "molprobity.log"):
                log = project_dir / name
                if log.exists():
                    m = re.search(r"^\s*Resolution\s*=\s*([\d.]+)", log.read_text(), re.M)
                    if m:
                        resolution = float(m.group(1))
                        break
    if resolution is None:
        console.print("Could not infer resolution; pass --resolution.")
        raise typer.Exit(code=1)

    labels = "F,SIGF"
    twin_law = None
    if strategy is None:
        strategy = "auto"
    manifest_path = project_dir / "manifest.yaml"
    if manifest_path.exists():
        try:
            manifest = load_manifest(manifest_path)
            if manifest.constraints.f_col and manifest.constraints.sigf_col:
                labels = f"{manifest.constraints.f_col},{manifest.constraints.sigf_col}"
            if strategy == "auto":
                strategy = manifest.coot.strategy
            twin_law = manifest.coot.twin_law
        except Exception:
            pass

    try:
        result = run_coot_optimization(
            pdb, mtz, project_dir / "coot_strategy", resolution,
            labels=labels, rfree_label="FreeR_flag", strategy=strategy, twin_law=twin_law,
        )
    except CootNotAvailable as exc:
        console.print(str(exc))
        raise typer.Exit(code=1) from exc

    table = Table(title="COOT post-refinement")
    table.add_column("Item")
    table.add_column("Value")
    table.add_row("Accepted", "yes" if result.accepted else "no")
    table.add_row("R-free before", str(result.rfree_before))
    table.add_row("R-free after", str(result.rfree_after))
    table.add_row("Clashscore", str(result.clashscore))
    table.add_row("Rotamer outliers", str(result.rotamer_outliers))
    table.add_row("Selected PDB", str(result.selected_pdb))
    table.add_row("Reason", result.reason)
    console.print(table)
    if not result.accepted:
        raise typer.Exit(code=2)


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
        console.print(f"- xtal-agent command-template {name}")


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
    from xtal_agent.step_tracker import enforce_checkpoint
    enforce_checkpoint(str(project_dir))
    keys = get_naming_conventions()
    for key, value in keys.items():
        console.print(f"- {key}: {value}")
    console.print("Resume rule: next numeric round, do not renumber.")
    tracker = StepTracker(str(project_dir))
    _, exit_code = tracker.run()
    if exit_code != 0:
        raise typer.Exit(code=1)


# ---------------------------------------------------------------------------
# Vision module commands
# ---------------------------------------------------------------------------

import jinja2
from xtal_agent import vision_render as _vision_render
from xtal_agent import vision_schema as _vision_schema


def _resolve_template_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "templates"


def _count_cbf_frames(directory: Path) -> int:
    return sum(1 for p in directory.iterdir() if p.suffix.lower() == ".cbf")


def _build_image_pattern(directory: Path) -> tuple[str, int]:
    """Build a frame-placeholder pattern matching the dataset's filename
    convention, and return the actual frame count observed on disk.

    Strategy: collect every ``.cbf`` filename, find the longest common
    prefix that ends at a digit boundary, and use ``{frame:04d}`` for the
    variable part. Files that don't match the prefix/suffix template are
    ignored — only the canonical series drives the pattern.
    """
    import re

    candidates: list[tuple[str, int]] = []
    for p in directory.iterdir():
        if p.suffix.lower() != ".cbf":
            continue
        m = re.match(r"^(.*?)(\d+)$", p.stem)
        if not m:
            continue
        candidates.append((m.group(1), len(m.group(2))))
    if not candidates:
        raise RuntimeError(f"no numbered .cbf files in {directory}")
    prefix = candidates[0][0]
    for p, _ in candidates[1:]:
        while not p.startswith(prefix):
            prefix = prefix[:-1]
        # Trim back to a clean boundary (must end at or before an underscore
        # so the placeholder is a contiguous run of digits, not a partial
        # of e.g. a run number).
        if not prefix.endswith("_"):
            idx = prefix.rfind("_")
            prefix = prefix[: idx + 1] if idx >= 0 else ""
    digits = max(d for _, d in candidates)
    return str(directory / f"{prefix}{{frame:0{digits}d}}.cbf"), len(candidates)


@app.command(name="vision-scan")
def vision_scan(
    project_dir: Path,
    target_windows: int = typer.Option(30, "--target-windows", help="v2: target number of LLM montages (capped at 100)"),
    montage_cols: int = typer.Option(4, "--montage-cols", help="v2 Tier 2: cells per row in each montage"),
    montage_cell_px: int = typer.Option(1024, "--montage-cell-px", help="v2 Tier 2: tile side per frame in montage"),
    slab_width: int = typer.Option(0, "--slab-width", help="If >1, also render N-frame slab-summed views"),
    segment_size: int = typer.Option(0, "--segment-size", help="Override bar size; 0 = auto from --target-windows (recommended)"),
) -> None:
    """v2 sliding-window pipeline — render ALL CBFs, montage consecutive windows.

    The pipeline divides the dataset into segments of consecutive frames
    and builds one montage per segment. The bar (segment_size) auto-scales
    with dataset size so the LLM call count stays bounded:
    - 360 frames  → bar=12  → 30 montages
    - 1800 frames → bar=60  → 30 montages
    - 3600 frames → bar=120 → 30 montages
    Hard cap: 100 montages (MAX_LLM_WINDOWS).

    v2 red-line: NO code reads .cbf pixel data or computes statistics.
    All quality judgment is the LLM's, from inspecting the rendered JPGs.
    """
    project_dir = Path(project_dir)
    manifest_path = project_dir / "manifest.yaml"
    if not manifest_path.exists():
        console.print(f"Manifest not found: {manifest_path}")
        raise typer.Exit(code=1)
    manifest = load_manifest(manifest_path)
    diffraction = project_dir / manifest.inputs.diffraction.path
    if not diffraction.is_dir():
        console.print(f"Diffraction directory not found: {diffraction}")
        raise typer.Exit(code=1)
    n_frames = _count_cbf_frames(diffraction)
    if n_frames == 0:
        console.print(f"No .cbf files in {diffraction}")
        raise typer.Exit(code=1)
    pattern, observed = _build_image_pattern(diffraction)
    out_dir = project_dir / "vision_frames"

    # Auto-scale segment size if not overridden
    if segment_size <= 0:
        segment_size = _vision_render.segment_size_for_target_windows(
            observed, target_windows=target_windows,
        )
    cap = _vision_render.MAX_LLM_WINDOWS
    console.print(
        f"Bar size: {segment_size} frames/window "
        f"(target={target_windows}, cap={cap})"
    )

    # Render EVERY frame to JPG (cache for LLM drill-down)
    console.print(f"Render: all {observed} frames to JPG (adxv / dials / fabio)...")
    result = _vision_render.render_dataset(
        raw_image_pattern=pattern,
        n_frames=observed,
        output_dir=out_dir,
        slab_width=slab_width,
    )
    console.print(f"  backend: {result.backend.value}; rendered {len(result.frames)} of {observed}")
    for w in result.warnings:
        console.print(f"    warn: {w}")

    # Build one montage per sliding window (in frame order)
    windows = _vision_render.sliding_windows(observed, segment_size)
    n_windows = len(windows)
    if n_windows > cap:
        console.print(
            f"[yellow]WARNING: {n_windows} montages > cap {cap}; consider raising --segment-size[/yellow]"
        )
    console.print(f"Sliding window: {n_windows} windows of {segment_size} frames each")

    index_path = out_dir / "windows.tsv"
    with index_path.open("w") as fh:
        fh.write("window\twindow_start\twindow_end\tframe_count\tmontage_file\n")
        for i, (start, end, frames) in enumerate(windows, start=1):
            fh.write(f"{i}\t{start}\t{end}\t{len(frames)}\tmontage_{i:02d}.png\n")
    console.print(f"  window index: {index_path}")

    rows = (segment_size + montage_cols - 1) // montage_cols
    cell = montage_cell_px
    canvas_w = montage_cols * cell + (montage_cols + 1) * 4
    canvas_h = rows * cell + (rows + 1) * 4
    console.print(
        f"Montage: {n_windows} PNG(s), each {canvas_w}×{canvas_h}px "
        f"({montage_cols}×{rows} grid of {cell}px tiles)"
    )
    for i, (start, end, frames) in enumerate(windows, start=1):
        jpgs = [out_dir / f"frame_{f:05d}_std.jpg" for f in frames]
        jpgs = [p for p in jpgs if p.exists()]
        if not jpgs:
            continue
        out_montage = out_dir / f"montage_{i:02d}.png"
        _vision_render.build_montage(jpgs, out_montage, cols=montage_cols, cell_px=cell)

    # geometry.json
    geometry = {
        "backend": result.backend.value,
        "raw_image_pattern": pattern,
        "n_frames": observed,
        "rendered_frame_count": len(result.frames),
        "slab_width": slab_width,
        "windows_tsv": str(index_path),
        "segment_size": segment_size,
        "n_windows": n_windows,
        "target_windows": target_windows,
        "max_llm_windows_cap": cap,
    }
    geometry_path = out_dir / "geometry.json"
    geometry_path.write_text(json.dumps(geometry, indent=2))
    console.print(f"Geometry: {geometry_path}")

    template_dir = _resolve_template_dir()
    if (template_dir / "vision_prompt.md.j2").exists():
        env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(str(template_dir)),
            autoescape=False,
        )
        tpl = env.get_template("vision_prompt.md.j2")
        report_path = _vision_schema.report_path_for_project(project_dir)
        prompt_text = tpl.render(
            geometry=geometry,
            windows=windows,
            report_path=str(report_path),
            montage_dir=str(out_dir),
            anchor_images=[],
        )
        prompt_file = project_dir / "vision_prompt.md"
        prompt_file.write_text(prompt_text)
        console.print(f"Prompt: {prompt_file}")
    else:
        console.print("Template vision_prompt.md.j2 not found; skipping prompt render.")
    console.print(
        "Next: LLM walks montage_01.png ... montage_<N>.png IN ORDER,\n"
        "  inspects vision_frames/frame_<NNNNN>_std.jpg for details,\n"
        f"  writes vision_report.json to {report_path}, then runs\n"
        "  `xtal-agent vision-validate <project_dir>`."
    )


@app.command(name="vision-validate")
def vision_validate(project_dir: Path) -> None:
    """Validate vision_report.json against the vision schema + run code-layer supervision.

    Two layers:
    1. Schema check (pydantic) — fields, types, monotonicity, frame span
    2. Supervision check — internal consistency:
       - frames_examined covers per_frame_observations and spot_extent
       - recommended_spot_ranges exclude streaky/diffuse frames
       - quality_grade is consistent with the observation mix
       - (if windows.tsv present) every sliding-window montage is acknowledged
    """
    project_dir = Path(project_dir)
    report_path = _vision_schema.report_path_for_project(project_dir)
    try:
        report = _vision_schema.load_vision_report(report_path)
    except ValueError as exc:
        console.print(f"[bold red]Vision report invalid:[/bold red] {exc}")
        raise typer.Exit(code=1) from exc
    console.print(
        f"Schema OK: {len(report.frames_examined)} frames examined, "
        f"schema_version={report.schema_version}, "
        f"quality_grade={report.quality_grade.value}"
    )
    if report.recommended_spot_ranges:
        console.print(
            "Recommended SPOT_RANGES (downstream consumer, simple mode only):"
        )
        for s, e in report.recommended_spot_ranges:
            console.print(f"  - {s} {e}")

    # Code-layer supervision
    expected_span: tuple[int, int] | None = None
    n_windows: int | None = None
    geom_path = project_dir / "vision_frames" / "geometry.json"
    if geom_path.exists():
        try:
            geom = json.loads(geom_path.read_text())
            n = geom.get("n_frames")
            if n:
                expected_span = (1, int(n))
            seg = geom.get("segment_size")
            n_w = geom.get("n_windows")
            if seg and n_w:
                n_windows = int(n_w)
        except Exception:
            pass

    supervision = _vision_schema.supervise_report(
        report, expected_frame_span=expected_span, n_expected_windows=n_windows,
    )
    if supervision.passed:
        console.print("Supervision: PASS (no findings)")
    else:
        console.print(
            f"[bold yellow]Supervision: {len(supervision.findings)} finding(s)[/bold yellow]"
        )
        for f in supervision.findings:
            console.print(f"  - {f}")

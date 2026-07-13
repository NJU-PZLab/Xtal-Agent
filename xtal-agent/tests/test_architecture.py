import json
from pathlib import Path

from typer.testing import CliRunner

from crystal_agent.cli import app
from crystal_agent.architecture import (
    audit_architecture,
    collect_backup_targets,
    extract_placeholders,
    get_command_template,
    get_naming_conventions,
    get_phase_guide,
    list_command_templates,
    validate_template_parameters,
)


runner = CliRunner()


def test_collect_backup_targets_includes_docs_skills_code_and_excludes_raw_data(tmp_path: Path):
    (tmp_path / "AGENTS.md").write_text("manual")
    (tmp_path / "skills").mkdir()
    (tmp_path / "skills" / "demo.md").write_text("skill")
    (tmp_path / "crystal-agent" / "src").mkdir(parents=True)
    (tmp_path / "crystal-agent" / "src" / "code.py").write_text("print('x')")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "note.md").write_text("doc")
    (tmp_path / "example").mkdir()
    (tmp_path / "example" / "case.md").write_text("case")
    (tmp_path / "image_0001.cbf").write_text("raw")
    (tmp_path / "XDS_ASCII.HKL").write_text("large intermediate")

    targets = {path.relative_to(tmp_path).as_posix() for path in collect_backup_targets(tmp_path)}

    assert "AGENTS.md" in targets
    assert "skills" in targets
    assert "crystal-agent/src" in targets
    assert "docs" in targets
    assert "example" in targets
    assert "image_0001.cbf" not in targets
    assert "XDS_ASCII.HKL" not in targets


def test_audit_architecture_reports_missing_mandatory_rules(tmp_path: Path):
    (tmp_path / "AGENTS.md").write_text("Never skip IDXREF")
    (tmp_path / "skills").mkdir()

    result = audit_architecture(tmp_path)

    assert not result.passed
    assert "verify-steps" in result.missing_rules
    assert "aimless thresholds" in result.missing_rules


def test_audit_architecture_passes_when_all_mandatory_rules_are_present(tmp_path: Path):
    (tmp_path / "AGENTS.md").write_text(
        "\n".join(
            [
                "verify-steps",
                "naming-guide",
                "resume with the next numeric round",
                "enforce-checkpoint",
                "step_state.json",
                "Never skip IDXREF",
                "aimless thresholds",
                "invalid-resolution data",
                "4+ Phenix rounds",
                "4+ Refmac rounds",
                "immediately preceding round",
                "TLS optimization",
                "ordered_solvent",
                "real_space_correlation",
                "MolProbity Rfree",
                "lowest Rfree wins",
                "final/ directory",
                "ccp4 ligand",
                "map_ligand_atoms",
                "idxref_failure_fix",
                "suggest_data_range_from_mosaicity",
                "sg_conflict_resolution",
                "select_prediction_tool",
                "matthews_copy_range",
                "select_best_copy_number",
                "phaser_troubleshooting_order",
                "should_use_twin_refinement",
                "crystal-agent run-phase",
            ]
        )
    )
    src = tmp_path / "crystal-agent" / "src" / "crystal_agent"
    src.mkdir(parents=True)
    (src / "phase_orchestrator.py").write_text(
        "idxref_failure_fix\n"
        "suggest_data_range_from_mosaicity\n"
        "sg_conflict_resolution\n"
        "select_prediction_tool\n"
        "matthews_copy_range\n"
        "select_best_copy_number\n"
        "phaser_troubleshooting_order\n"
    )
    (src / "step_tracker.py").write_text("should_use_twin_refinement\n")
    (tmp_path / "skills").mkdir()
    (tmp_path / "skills" / "phase.md").write_text("crystal-agent guard\ncrystal-agent verify-steps")

    result = audit_architecture(tmp_path)

    assert result.passed
    assert result.missing_rules == []


def test_audit_architecture_cli_exits_nonzero_when_rules_missing(tmp_path: Path):
    (tmp_path / "AGENTS.md").write_text("Never skip IDXREF")

    result = runner.invoke(app, ["audit-architecture", str(tmp_path)])

    assert result.exit_code == 1
    assert "Missing mandatory rules" in result.stdout
    assert "verify-steps" in result.stdout


def test_phase_guide_contains_code_calls_and_hard_stop_rules():
    guide = get_phase_guide("phase5")

    assert any("crystal-agent guard" in call for call in guide.code_calls)
    assert any("crystal-agent verify-steps" in call for call in guide.code_calls)
    assert "4+ Phenix rounds" in guide.mandatory_rules
    assert "4+ Refmac rounds" in guide.mandatory_rules
    assert any("immediately preceding round" in rule for rule in guide.mandatory_rules)


def test_phase_guides_include_orchestrator_decision_calls():
    phase1 = "\n".join(get_phase_guide("phase1").code_calls)
    phase2 = "\n".join(get_phase_guide("phase2").code_calls)
    phase3 = "\n".join(get_phase_guide("phase3").code_calls)
    phase4 = "\n".join(get_phase_guide("phase4").code_calls)

    assert "crystal-agent run-phase" in phase1
    assert "idxref_failure_fix" in phase1
    assert "suggest_data_range_from_mosaicity" in phase1
    assert "sg_conflict_resolution" in phase2
    assert "select_prediction_tool" in phase3
    assert "matthews_copy_range" in phase3
    assert "select_best_copy_number" in phase4
    assert "phaser_troubleshooting_order" in phase4


def test_run_phase_command_template_exists():
    template = get_command_template("run-phase")

    assert "crystal-agent run-phase" in template.command


def test_audit_requires_decision_runtime_and_doc_coverage(tmp_path: Path):
    (tmp_path / "AGENTS.md").write_text("idxref_failure_fix\ncrystal-agent run-phase\n")
    src = tmp_path / "crystal-agent" / "src" / "crystal_agent"
    src.mkdir(parents=True)
    (src / "phase_orchestrator.py").write_text(
        "from crystal_agent.decision_engine import idxref_failure_fix\nidxref_failure_fix\n"
    )

    result = audit_architecture(tmp_path)

    assert "sg_conflict_resolution runtime wiring" in result.missing_rules
    assert "sg_conflict_resolution agent documentation" in result.missing_rules


def test_phase_guide_cli_prints_phase_commands():
    result = runner.invoke(app, ["phase-guide", "phase2"])

    assert result.exit_code == 0
    assert "Phase 2" in result.stdout
    assert "aimless" in result.stdout
    assert "mtzdump" in result.stdout
    assert "verify-steps" in result.stdout


def test_command_template_returns_canonical_phaser_command():
    template = get_command_template("phaser-mr")

    assert "phenix.phaser" in template.command
    assert "LABIN I=IMEAN SIGI=SIGIMEAN" in template.command
    assert "ROOT phaser_copy_<copies>" in template.command
    assert "validated truncated MTZ" in template.preconditions


def test_command_templates_cover_full_crystallography_workflow():
    required = {
        "xds-generate-inp": "generate_XDS.INP",
        "xds-run": "xds_par",
        "dials-import": "dials.import",
        "dials-find-spots": "dials.find_spots",
        "dials-index": "dials.index",
        "dials-integrate": "dials.integrate",
        "dials-scale": "dials.scale",
        "dials-export-mtz": "dials.export",
        "xia2-fallback": "xia2 image=",
        "pointless": "pointless",
        "aimless-scale": "aimless",
        "mtzdump-resolution": "mtzdump",
        "matthews": "matthews_coef",
        "phaser-mr": "phenix.phaser",
        "xtriage": "phenix.xtriage",
        "phenix-seed": "phenix.refine",
        "phenix-iterative-refine": "phenix.refine",
        "ctruncate": "ctruncate",
        "freerflag": "freerflag",
        "refmac-jelly": "refmac5",
        "refmac-free": "refmac5",
        "rscc": "phenix.real_space_correlation",
        "molprobity-final": "phenix.molprobity",
        "ligand-elbow": "phenix.elbow",
    }

    for name, expected_command in required.items():
        template = get_command_template(name)
        assert expected_command in template.command
        assert template.preconditions
        assert template.outputs


def test_command_template_cli_prints_refmac_jelly_command():
    result = runner.invoke(app, ["command-template", "refmac-jelly"])

    assert result.exit_code == 0
    assert "refmac5" in result.stdout
    assert "external restraint jelly" in result.stdout
    assert "FreeR_flag" in result.stdout


def test_all_phase_guides_reference_code_templates():
    required_templates = {
        "phase1": "xds-generate-inp",
        "phase2": "aimless-scale",
        "phase3": "matthews",
        "phase4": "phaser-mr",
        "phase5": "phenix-seed",
        "phase6": "molprobity-final",
    }

    for phase, template_name in required_templates.items():
        guide = get_phase_guide(phase)
        assert template_name in guide.command_templates


def test_phase1_guide_exposes_dials_fallback_templates():
    guide = get_phase_guide("phase1")

    assert "dials-import" in guide.command_templates
    assert "dials-index" in guide.command_templates
    assert "xia2-fallback" in guide.command_templates


def test_list_command_templates_returns_sorted_names():
    names = list_command_templates()

    assert names == sorted(names)
    assert "phaser-mr" in names
    assert "dials-index" in names


def test_extract_placeholders_from_template_command():
    template = get_command_template("phaser-mr")

    assert extract_placeholders(template) == {"copies"}


def test_validate_template_parameters_reports_missing_values():
    template = get_command_template("ligand-elbow")

    result = validate_template_parameters(template, {"CCD": "SAM"})

    assert result.missing == ["PUBCHEM_SMILES", "prefix"]
    assert not result.passed


def test_validate_template_parameters_accepts_all_values():
    template = get_command_template("ligand-elbow")
    result = validate_template_parameters(
        template,
        {"PUBCHEM_SMILES": "CS", "prefix": "SAM_de_novo", "CCD": "SAM"},
    )

    assert result.passed
    assert result.missing == []


def test_command_template_cli_can_emit_json():
    result = runner.invoke(app, ["command-template", "phaser-mr", "--format", "json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["name"] == "phaser-mr"
    assert "LABIN I=IMEAN SIGI=SIGIMEAN" in payload["command"]


def test_command_template_cli_can_emit_markdown():
    result = runner.invoke(app, ["command-template", "dials-index", "--format", "markdown"])

    assert result.exit_code == 0
    assert "# dials-index" in result.stdout
    assert "dials.index" in result.stdout


def test_list_command_templates_cli_prints_known_templates():
    result = runner.invoke(app, ["list-command-templates"])

    assert result.exit_code == 0
    assert "phaser-mr" in result.stdout
    assert "dials-index" in result.stdout


def test_skill_command_template_references_exist():
    root = Path(__file__).resolve().parents[2]
    known = set(list_command_templates())
    missing: list[str] = []
    for skill_path in (root / "skills").glob("*/SKILL.md"):
        text = skill_path.read_text()
        for line in text.splitlines():
            marker = "crystal-agent command-template "
            if marker not in line:
                continue
            name = line.split(marker, 1)[1].strip().split()[0].strip("`;,.")
            if name.startswith("<"):
                continue
            if name not in known:
                missing.append(f"{skill_path}: {name}")

    assert missing == []


def test_naming_conventions_define_refinement_round_files():
    conventions = get_naming_conventions()

    assert conventions["phenix_round"] == "phenix_r<N>.pdb / phenix_r<N>.mtz / phenix_r<N>.log"
    assert conventions["refmac_round"] == "refmac_r<N>.pdb / refmac_r<N>.mtz / refmac_r<N>.log"
    assert conventions["refmac_jelly_round"] == "refmac_jelly_r<N>.pdb / refmac_jelly_r<N>.mtz / refmac_jelly_r<N>.log"
    assert conventions["validated_resolution"] == "validated_resolution.txt + mtzdump_resolution.log"


def test_naming_guide_cli_prints_resume_rules():
    result = runner.invoke(app, ["naming-guide"])

    assert result.exit_code == 0
    assert "phenix_r<N>" in result.stdout
    assert "refmac_jelly_r<N>" in result.stdout
    assert "resume" in result.stdout.lower()
    assert "do not renumber" in result.stdout.lower()


def test_naming_conventions_consistent_with_step_tracker_patterns():
    conventions = get_naming_conventions()

    phenix_pat = conventions["phenix_round"]
    refmac_pat = conventions["refmac_round"]
    jelly_pat = conventions["refmac_jelly_round"]
    phaser_pat = conventions["phaser_copy"]

    assert "phenix_r" in phenix_pat and ".pdb" in phenix_pat
    assert "refmac_r" in refmac_pat and ".pdb" in refmac_pat
    assert "refmac_jelly_r" in jelly_pat and ".pdb" in jelly_pat
    assert "phaser_copy_" in phaser_pat


def test_naming_conventions_consistent_with_command_template_outputs():
    conventions = get_naming_conventions()
    template = get_command_template("phaser-mr")

    assert "phaser_copy_" in conventions["phaser_copy"]
    assert "phaser_copy" in template.outputs

    seed_template = get_command_template("phenix-seed")
    assert "seed_data.mtz" in conventions["phenix_seed"]
    assert "seed_data.mtz" in seed_template.outputs

    refmac_template = get_command_template("refmac-jelly")
    assert "refmac_jelly_r" in conventions["refmac_jelly_round"]
    assert "refmac_jelly_r" in refmac_template.outputs


def test_step_tracker_patterns_align_with_naming_conventions():
    from crystal_agent.step_tracker import StepTracker

    tracker = StepTracker("/tmp")
    conventions = get_naming_conventions()

    checks = tracker.steps
    assert "phenix_r" in conventions["phenix_round"]
    assert "refmac_r" in conventions["refmac_round"]
    assert "refmac_jelly_r" in conventions["refmac_jelly_round"]
    assert checks["phase5_phenix_r4"]["label"].lower().find("phenix") != -1
    assert checks["phase5_refmac_jelly_r2"]["label"].lower().find("refmac") != -1


def test_step_tracker_accepts_canonical_naming_prefixes(tmp_path: Path):
    """Verify StepTracker glob patterns accept files named per NAMING_CONVENTIONS."""
    from crystal_agent.step_tracker import StepTracker

    tracker = StepTracker(str(tmp_path))

    (tmp_path / "phenix_r4.pdb").write_text("MODEL\n")
    (tmp_path / "refmac_jelly_r2.pdb").write_text("MODEL\n")
    (tmp_path / "refmac_r4.pdb").write_text("MODEL\n")
    (tmp_path / "seed_data.mtz").write_text("data\n")

    assert tracker.get_status("phase5_phenix_r4", True) == "✓"
    assert tracker.get_status("phase5_refmac_jelly_r2", True) == "✓"
    assert tracker.get_status("phase5_refmac_free_r4", True) == "✓"
    assert tracker.get_status("phase5_seed", True) == "✓"


def test_audit_architecture_requires_resume_naming_gate(tmp_path: Path):
    (tmp_path / "AGENTS.md").write_text(
        "\n".join(
            [
                "verify-steps",
                "Never skip IDXREF",
                "aimless thresholds",
                "invalid-resolution data",
                "4+ Phenix rounds",
                "4+ Refmac rounds",
                "immediately preceding round",
                "TLS optimization",
                "ordered_solvent",
                "real_space_correlation",
                "MolProbity Rfree",
                "lowest Rfree wins",
                "final/ directory",
            ]
        )
    )

    result = audit_architecture(tmp_path)

    assert not result.passed
    assert "resume naming gate" in result.missing_rules

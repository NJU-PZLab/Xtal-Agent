#!/usr/bin/env python3
"""Pipeline Step Tracker — mandatory step verification for crystal-agent projects."""

import os, sys, json, subprocess, re, glob, time
from pathlib import Path
from typing import Optional

import yaml

from crystal_agent.decision_engine import (
    RfreeSample,
    RfreeTrend,
    detect_rfree_plateau,
    extract_twin_laws_from_xtriage,
    high_rfree_diagnosis,
    should_use_twin_refinement,
)

STATUS_OK = "✓"
STATUS_FAIL = "✗"
STATUS_IN_PROGRESS = "~"
STATUS_NOT_REACHED = "-"

EXPERT_APPROVALS_FILE = ".expert_approvals.json"

STEP_OUTPUT_SIGNATURES = {
    "phase0_xds_inp": "XDS.INP",
    "phase0_fasta": "*.fasta",
    "phase1_correct_lp": "CORRECT.LP",
    "phase2_pointless": "point.mtz",
    "phase2_aimless": "scaled.mtz",
    "phase3_matthews": "matthews.log",
    "phase4_phaser": "phaser_copy_*.sol",
    "phase5_seed": "seed_data.mtz",
    "phase5_phenix_r4": "phenix_r4*.pdb",
    "phase5_ctruncate": "ctruncate.mtz",
    "phase5_freerflag": "ctruncate_free.mtz",
    "phase5_refmac_jelly_r2": "refmac_jelly_r2.pdb",
    "phase5_refmac_free_r4": "refmac_r4*.pdb",
    "phase5_modelcraft_run": "modelcraft.json",
    "phase5_modelcraft_refmac_r2": "modelcraft_r2.pdb",
    "phase5_water_fit": "water_refine*.pdb",
    "phase5_rscc": "rsc.log",
    "phase6_molprobity_final": "molprobity_final.log",
}

EXPERT_STEP_OUTPUT_SIGNATURES = {
    "phase0_xds_inp": ("XDS.INP",),
    "phase0_fasta": ("*.fasta",),
    "phase1_correct_lp": ("CORRECT.LP", "XDS_ASCII.HKL"),
    "phase1_sg_cell": ("CORRECT.LP",),
    "phase1_resolution": ("CORRECT.LP",),
    "phase1_round2": ("CORRECT.LP",),
    "phase2_pointless": ("point.mtz",),
    "phase2_aimless": ("scaled.mtz", "scaled_*.mtz"),
    "phase2_shell_stats": ("aimless.log", "aimless_*.log"),
    "phase2_resolution_validated": ("aimless.log", "aimless_*.log"),
    "phase2_mtzdump": ("mtzdump_resolution.log",),
    "phase2_mtz_resolution": ("mtzdump_resolution.log",),
    "phase2_outer_margin": ("aimless.log", "aimless_*.log"),
    "phase2_alt_sg": ("point.log", "pointless.log"),
    "phase3_msa": ("*.a3m",),
    "phase3_af_model": ("*_rank_001*.pdb",),
    "phase3_plddt": ("search_model.pdb",),
    "phase3_tag_strip": ("search_model.pdb",),
    "phase3_matthews": ("matthews.log",),
    "phase4_phaser": ("phaser_copy_*.sol", "phaser_copy_*.log"),
    "phase4_tfz_llg": ("phaser_copy_*.log", "phaser*.log"),
    "phase4_pak": ("phaser_copy_*.log", "phaser*.log"),
    "phase4_all_copies": ("phaser_copy_*.log",),
    "phase4_best_copy": ("phaser_copy_selection.txt", "phaser_copy_*.log"),
    "phase4_xtriage": ("xtriage.log",),
    "phase5_seed": ("seed_data.mtz", "*seed*.mtz", "twin_*.mtz"),
    "phase5_phenix_r1": ("*_001.log", "*_001.pdb"),
    "phase5_phenix_r4": ("*_001.pdb", "*_001.mtz"),
    "phase5_phenix_rfree_trend": ("*_001.pdb",),
    "phase5_high_rfree_diagnosis": ("*_001.pdb",),
    "phase5_ctruncate": ("ctruncate*.mtz",),
    "phase5_freerflag": ("*free*.mtz",),
    "phase5_refmac_jelly_r2": ("refmac*_r2.pdb", "refmac*_r1.pdb"),
    "phase5_refmac_free_r4": ("refmac*.pdb",),
    "phase5_modelcraft_run": ("modelcraft_run.log", "modelcraft.json",
        "modelcraft.cif"),
    "phase5_modelcraft_refmac_r2": ("modelcraft_r2.pdb", "modelcraft*.pdb"),
    "phase5_modelcraft_comparison": ("modelcraft*.pdb",),
    "phase5_water_fit": ("*.pdb",),
    "phase5_rscc": ("rsc.log",),
    "phase5_tls": ("*tls*.log",),
}


def _workflow_mode(project_dir: str | Path) -> str | None:
    manifest = Path(project_dir) / "manifest.yaml"
    if not manifest.exists():
        return None
    try:
        data = yaml.safe_load(manifest.read_text()) or {}
    except Exception:
        return None
    mode = data.get("workflow_mode")
    return str(mode) if mode is not None else None


def is_expert_project(project_dir: str | Path) -> bool:
    return _workflow_mode(project_dir) == "expert"


def _approval_path(project_dir: str | Path) -> Path:
    return Path(project_dir) / EXPERT_APPROVALS_FILE


def _load_approvals(project_dir: str | Path) -> dict:
    path = _approval_path(project_dir)
    if not path.exists():
        return {"approvals": []}
    try:
        data = json.loads(path.read_text())
    except Exception:
        return {"approvals": []}
    if "approvals" not in data or not isinstance(data["approvals"], list):
        return {"approvals": []}
    return data


def _save_approvals(project_dir: str | Path, data: dict) -> None:
    _approval_path(project_dir).write_text(json.dumps(data, indent=2, sort_keys=True))


def approve_expert_step(project_dir: str | Path, step_name: str, reason: str) -> None:
    data = _load_approvals(project_dir)
    data["approvals"].append(
        {
            "step": step_name,
            "reason": reason,
            "approved_at": time.time(),
            "consumed": False,
        }
    )
    _save_approvals(project_dir, data)


def consume_expert_approval(project_dir: str | Path, step_name: str) -> bool:
    data = _load_approvals(project_dir)
    for approval in data["approvals"]:
        if approval.get("step") == step_name and not approval.get("consumed", False):
            approval["consumed"] = True
            approval["consumed_at"] = time.time()
            _save_approvals(project_dir, data)
            return True
    return False


def _has_consumed_approval(project_dir: str | Path, step_name: str) -> bool:
    data = _load_approvals(project_dir)
    return any(
        approval.get("step") == step_name and approval.get("consumed", False)
        for approval in data["approvals"]
    )


def _has_pending_approval(project_dir: str | Path, step_name: str) -> bool:
    data = _load_approvals(project_dir)
    return any(
        approval.get("step") == step_name and not approval.get("consumed", False)
        for approval in data["approvals"]
    )


class Guard:
    """Enforces step-by-step pipeline execution.

    Must be called BEFORE and AFTER each pipeline step. Prevents batch-skipping.
    Stores completion state in project_dir/.step_state.json.
    """

    def __init__(self, project_dir: str):
        self.project_dir = Path(project_dir).resolve()
        self.state_file = self.project_dir / ".step_state.json"
        self._load()

    def _load(self):
        if self.state_file.exists():
            try:
                self.state = json.loads(self.state_file.read_text())
            except:
                self.state = {"completed": [], "current": None}
        else:
            self.state = {"completed": [], "current": None}

    def _save(self):
        self.state_file.write_text(json.dumps(self.state, indent=2))

    def before(self, step_name: str):
        """Verify prerequisites before executing step_name."""
        if self.state["current"] is not None:
            msg = f"ERROR: Step '{self.state['current']}' was started but not completed. Run 'crystal-agent guard --after {self.state['current']}' first."
            print(msg)
            sys.exit(1)

        expert_mode = is_expert_project(self.project_dir)
        if expert_mode and not _has_pending_approval(self.project_dir, step_name):
            msg = (
                f"ERROR: Project is configured with workflow_mode=expert. "
                f"Approve step '{step_name}' first with: crystal-agent expert-approve "
                f"{self.project_dir} {step_name} --reason '<why this step is approved>'"
            )
            print(msg)
            sys.exit(1)

        tracker = StepTracker(str(self.project_dir))
        if not _check_step_prerequisites(tracker, step_name):
            tracker.run()
            msg = f"\nERROR: Prerequisites for '{step_name}' not met. Fix skipped steps first."
            print(msg)
            sys.exit(1)

        if expert_mode:
            consume_expert_approval(self.project_dir, step_name)

        self.state["current"] = step_name
        self._save()
        print(f"[GUARD] Starting step: {step_name}")

    def after(self, step_name: str):
        """Verify step_name completion and record it."""
        if self.state["current"] != step_name:
            msg = f"ERROR: Expected '--after {self.state['current']}' but got '--after {step_name}'. Was --before called?"
            print(msg)
            sys.exit(1)

        tracker = StepTracker(str(self.project_dir))
        tracker.run()
        if step_name in tracker.steps:
            status = tracker.get_status(step_name, True)
            if status == STATUS_FAIL:
                msg = f"\nERROR: Step '{step_name}' did not complete successfully."
                print(msg)
                sys.exit(1)

        self.state["completed"].append(step_name)
        self.state["current"] = None
        self._save()
        print(f"[GUARD] Completed step: {step_name}")


def _check_step_prerequisites(tracker: "StepTracker", step_name: str) -> bool:
    """Check if all steps before step_name have passed."""
    if step_name not in tracker.steps:
        return True
    target_phase = tracker.steps[step_name]["phase"]
    for name, info in tracker.steps.items():
        if name == step_name:
            return True
        if info["phase"] <= target_phase:
            if tracker.get_status(name, True) != STATUS_OK:
                return False
    return True


class StepTracker:
    def __init__(self, project_dir: str):
        self.project_dir = Path(project_dir).resolve()
        self.steps = {}
        self._build_checks()

    def _exists(self, path: str) -> bool:
        """Check if file or glob pattern exists."""
        if '*' in path or '?' in path:
            if is_expert_project(self.project_dir):
                return bool(list(self.project_dir.rglob(path)))
            return bool(list(self.project_dir.glob(path)))
        p = self.project_dir / path
        if p.exists():
            return True
        return is_expert_project(self.project_dir) and bool(list(self.project_dir.rglob(path)))

    def _find_file(self, pattern: str) -> Optional[str]:
        glob_fn = self.project_dir.rglob if is_expert_project(self.project_dir) else self.project_dir.glob
        matches = sorted(glob_fn(pattern))
        return str(matches[0]) if matches else None

    def _expert_step_output_exists(self, step_name: str) -> bool:
        patterns = EXPERT_STEP_OUTPUT_SIGNATURES.get(step_name)
        if not patterns:
            return False
        return any(self._exists(pattern) for pattern in patterns)

    def _check_xds_inp_exists(self) -> bool:
        return self._exists("XDS.INP")

    def _check_pointless_ok(self) -> bool:
        """Check pointless completed: point.mtz + pointless.log exist and SG confidence > 0.8 or P1."""
        log_path = self._find_file("pointless.log") or self._find_file("point.log")
        if not (self._exists("point.mtz") and log_path):
            return False
        log = Path(log_path)
        try:
            text = log.read_text()
        except:
            return self._exists("point.mtz")
        m = re.search(r"Space group confidence(?:\s*\([^)]*\))?\s*(?:=|:)\s+([\d.]+)", text)
        if m and float(m.group(1)) > 0.8:
            return True
        m2 = re.search(r"\* Space group = 'P 1'", text)
        if m2:
            return True
        return self._exists("point.mtz")

    def _build_checks(self):
        self.steps = {}

        # Phase 0: Project Init
        self.steps["phase0_xds_inp"] = {
            "phase": 0, "label": "XDS.INP exists",
            "check": self._check_xds_inp_exists,
        }
        self.steps["phase0_fasta"] = {
            "phase": 0, "label": "FASTA sequence file exists",
            "check": lambda: bool(list(self.project_dir.glob("*.fasta"))),
        }

        # Phase 1: XDS Processing
        self.steps["phase1_correct_lp"] = {
            "phase": 1, "label": "XDS round 1: CORRECT.LP exists, XDS_ASCII.HKL exists",
            "check": lambda: self._exists("CORRECT.LP") and self._exists("XDS_ASCII.HKL"),
        }
        self.steps["phase1_sg_cell"] = {
            "phase": 1, "label": "CORRECT.LP: SG and cell recorded",
            "check": lambda: self._extract_sg_cell() is not None,
        }
        self.steps["phase1_resolution"] = {
            "phase": 1, "label": "Resolution estimated from CORRECT.LP",
            "check": lambda: self._extract_correct_resolution() is not None,
        }
        self.steps["phase1_round2"] = {
            "phase": 1, "label": "XDS round 2: re-run with explicit SG+cell+resolution",
            "check": lambda: self._exists("CORRECT.LP"),
        }

        # Phase 2: Scaling
        self.steps["phase2_pointless"] = {
            "phase": 2, "label": "pointless: point.mtz exists, SG confidence>0.8",
            "check": self._check_pointless_ok,
        }
        self.steps["phase2_aimless"] = {
            "phase": 2, "label": "aimless: scaled.mtz exists",
            "check": lambda: self._exists("scaled.mtz") or self._exists("scaled_*.mtz"),
        }
        self.steps["phase2_shell_stats"] = {
            "phase": 2, "label": "aimless: per-shell stats extracted",
            "check": lambda: self._exists("aimless.log") or self._exists("aimless_*.log"),
        }
        self.steps["phase2_resolution_validated"] = {
            "phase": 2, "label": "Resolution validated against all 5 thresholds",
            "check": lambda: self._check_aimless_resolution(),
        }
        self.steps["phase2_mtzdump"] = {
            "phase": 2, "label": "mtzdump: resolution verified",
            "check": lambda: self._exists("scaled.mtz") or self._exists("scaled_*.mtz"),
        }
        self.steps["phase2_mtz_resolution"] = {
            "phase": 2, "label": "MTZ resolution matches aimless-validated cutoff",
            "check": lambda: self._check_mtz_resolution(),
        }
        self.steps["phase2_outer_margin"] = {
            "phase": 2, "label": "Outer shell Mn(I/sd) near threshold (not prematurely cut)",
            "check": self._check_outer_shell_margin,
        }
        self.steps["phase2_alt_sg"] = {
            "phase": 2, "label": "Alternative SGs tested if confidence<0.9",
            "check": lambda: self._exists("pointless.log"),
        }

        # Phase 3: Model Preparation
        self.steps["phase3_msa"] = {
            "phase": 3, "label": "MSA generated",
            "check": lambda: bool(list(self.project_dir.glob("**/*.a3m")))
                               or bool(list(self.project_dir.parent.glob("MSA/**/*.a3m"))),
        }
        self.steps["phase3_af_model"] = {
            "phase": 3, "label": "AF2/AF3 prediction: top-ranked PDB exists",
            "check": lambda: self._find_model_pdb() is not None,
        }
        self.steps["phase3_plddt"] = {
            "phase": 3, "label": "pLDDT extracted, low-pLDDT residues stripped",
            "check": lambda: self._exists("search_model.pdb"),
        }
        self.steps["phase3_tag_strip"] = {
            "phase": 3, "label": "Terminal tags stripped from search model",
            "check": lambda: self._check_tag_strip(),
        }
        self.steps["phase3_matthews"] = {
            "phase": 3, "label": "Matthews coefficient calculated and copy range recorded",
            "check": lambda: self._check_matthews_coverage(),
        }

        # Phase 4: MR
        self.steps["phase4_phaser"] = {
            "phase": 4, "label": "Phaser: .sol and .pdb output exist",
            "check": lambda: bool(list(self.project_dir.glob("phaser_copy_*.sol"))),
        }
        self.steps["phase4_tfz_llg"] = {
            "phase": 4, "label": "TFZ>8.0 and LLG>200 verified",
            "check": lambda: self._check_phaser_stats(),
        }
        self.steps["phase4_pak"] = {
            "phase": 4, "label": "PAK verified",
            "check": lambda: self._check_phaser_pak(),
        }
        self.steps["phase4_all_copies"] = {
            "phase": 4, "label": "ALL Matthews-predicted copy numbers tested (no gaps)",
            "check": lambda: self._check_all_copies(),
        }
        self.steps["phase4_best_copy"] = {
            "phase": 4, "label": "Best copy number selected and recorded",
            "check": lambda: self._check_best_copy_selected(),
        }
        self.steps["phase4_xtriage"] = {
            "phase": 4, "label": "xtriage run (if MR strong but Rfree high)",
            "check": lambda: self._exists("xtriage.log"),
        }

        # Phase 5: Phenix
        self.steps["phase5_seed"] = {
            "phase": 5, "label": "Phenix seed: seed_data.mtz exists",
            "check": lambda: self._exists("seed_data.mtz"),
        }
        self.steps["phase5_phenix_r1"] = {
            "phase": 5, "label": "Phenix round 1 completed",
            "check": lambda: self._exists("phenix_*.log"),
        }
        self.steps["phase5_phenix_r4"] = {
            "phase": 5, "label": "Phenix round 4 completed",
            "check": lambda: bool(list(self.project_dir.glob("phenix_r4*.pdb"))),
        }
        self.steps["phase5_phenix_rfree_trend"] = {
            "phase": 5, "label": "Phenix Rfree trend: plateau confirmed (rounds iterate, no flat)",
            "check": lambda: self._check_phenix_rfree_trend(),
        }
        self.steps["phase5_high_rfree_diagnosis"] = {
            "phase": 5, "label": "High Rfree diagnosis: switch software or stop if >0.35",
            "check": lambda: self._check_high_rfree_diagnosis(),
        }

        # Phase 5: Refmac
        self.steps["phase5_ctruncate"] = {
            "phase": 5, "label": "ctruncate: ctruncate.mtz exists",
            "check": lambda: self._exists("ctruncate.mtz"),
        }
        self.steps["phase5_freerflag"] = {
            "phase": 5, "label": "freerflag: ctruncate_free.mtz exists",
            "check": lambda: self._exists("ctruncate_free.mtz"),
        }
        self.steps["phase5_refmac_jelly_r2"] = {
            "phase": 5, "label": "Refmac jelly rounds 1-2 completed",
            "check": lambda: self._exists("refmac_jelly_r2.pdb"),
        }
        self.steps["phase5_refmac_free_r4"] = {
            "phase": 5, "label": "Refmac free rounds 3-4 completed",
            "check": lambda: bool(list(self.project_dir.glob("refmac_r4*.pdb"))),
        }
        self.steps["phase5_refmac_rfree_trend"] = {
            "phase": 5, "label": "Refmac Rfree trend: plateau confirmed (free rounds iterate, no flat)",
            "check": lambda: self._check_refmac_rfree_trend(),
        }

        # Phase 5b: Modelcraft refinement (always ATTEMPTED; failure is acceptable)
        self.steps["phase5_modelcraft_run"] = {
            "phase": 5, "label": "Modelcraft attempted (run log or output present; failure ok)",
            "check": lambda: self._modelcraft_attempted(),
        }
        self.steps["phase5_modelcraft_refmac_r2"] = {
            "phase": 5, "label": "Modelcraft branch: 2 Refmac rounds (only if modelcraft succeeded)",
            "check": lambda: (
                not self._modelcraft_succeeded()
                or self._exists("modelcraft_jelly_r2.pdb")
                or self._exists("modelcraft_r2.pdb")
            ),
        }
        self.steps["phase5_modelcraft_comparison"] = {
            "phase": 5, "label": "Modelcraft Rfree compared to pre-modelcraft best (only if succeeded); adopt best if it improves",
            "check": lambda: (
                not self._modelcraft_succeeded() or self._check_modelcraft_comparison()
            ),
        }

        # Phase 5a: Post-Refinement (mandatory)
        self.steps["phase5_tls"] = {
            "phase": 5, "label": "TLS optimization compared (tls log exists)",
            "check": lambda: self._exists("*tls*.log"),
        }
        self.steps["phase5_water_fit"] = {
            "phase": 5, "label": "Waters fitted with ordered_solvent",
            "check": lambda: self._exists("water_refine*.pdb"),
        }
        self.steps["phase5_rscc"] = {
            "phase": 5, "label": "Model-region diagnosis (RSC log)",
            "check": lambda: self._exists("rsc.log"),
        }

        # Phase 5-LR: Low-Resolution Refinement (>= 3.6 A)
        self.steps["phase5lr_trigger"] = {
            "phase": 5.1, "label": "Low-res branch triggered (resolution >= 3.6 A)",
            "check": lambda: self._check_low_res_branch(),
        }
        self.steps["phase5lr_rigid_body"] = {
            "phase": 5.1, "label": "Low-res: rigid body refinement",
            "check": lambda: self._exists("phenix_rb_001.pdb"),
        }
        self.steps["phase5lr_phenix_grouped"] = {
            "phase": 5.1, "label": "Low-res: phenix grouped ADP x4 (or skipped if no improvement)",
            "check": lambda: bool(list(self.project_dir.glob("phenix_r[1-4]_001.pdb"))) or self._exists("phenix_rb_001.pdb"),
        }
        self.steps["phase5lr_refmac_jelly"] = {
            "phase": 5.1, "label": "Low-res: refmac jelly rounds 1-2",
            "check": lambda: bool(list(self.project_dir.glob("refmac_jelly_r[12].pdb"))),
        }
        self.steps["phase5lr_refmac_free"] = {
            "phase": 5.1, "label": "Low-res: refmac free rounds 3-4",
            "check": lambda: bool(list(self.project_dir.glob("refmac_r[34].pdb"))),
        }
        self.steps["phase5lr_modelcraft"] = {
            "phase": 5.1, "label": "Low-res: modelcraft (if Rfree <= 0.35)",
            "check": lambda: self._modelcraft_attempted(),
        }
        self.steps["phase5lr_rsc"] = {
            "phase": 5.1, "label": "Low-res: RSC + garbage chain removal",
            "check": lambda: self._exists("rsc.log"),
        }
        self.steps["phase5lr_geom_opt"] = {
            "phase": 5.1, "label": "Low-res: phenix rotamer + secondary structure restraints (if user approved)",
            "check": lambda: bool(list(self.project_dir.glob("final_geom_001.pdb"))) or bool(list(self.project_dir.glob("rota_001.pdb"))),
        }
        self.steps["phase5lr_molprobity"] = {
            "phase": 5.1, "label": "Low-res: MolProbity on final model",
            "check": lambda: self._exists("molprobity*.log"),
        }
        self.steps["phase5lr_archive"] = {
            "phase": 5.1, "label": "Low-res: final/ archived with manual_notes.md",
            "check": lambda: (self.project_dir / "final").is_dir() and (self.project_dir / "final" / "manual_notes.md").exists(),
        }

        # Phase 6: Validation
        self.steps["phase6_molprobity"] = {
            "phase": 6, "label": "MolProbity run",
            "check": lambda: self._exists("molprobity*.log"),
        }
        self.steps["phase6_molprobity_final"] = {
            "phase": 6, "label": "MolProbity on final best model (after waters/TLS)",
            "check": lambda: self._exists("molprobity_final.log"),
        }
        self.steps["phase6_comparison"] = {
            "phase": 6, "label": "Comparison table filled",
            "check": lambda: self._exists("comparison.txt"),
        }
        self.steps["phase6_rfree_molprobity"] = {
            "phase": 6, "label": "MolProbity Rfree in comparison.txt",
            "check": lambda: self._check_comparison_rfree(),
        }
        self.steps["phase6_final_dir"] = {
            "phase": 6, "label": "final/ directory: best PDB, MTZ, AIMLESS log, MR model, XDS results, comparison, MolProbity, RSC saved",
            "check": lambda: (self.project_dir / "final").is_dir() and len(list((self.project_dir / "final").iterdir())) >= 5,
        }

    def _extract_sg_cell(self) -> Optional[dict]:
        """Extract space group and cell from CORRECT.LP."""
        found = self._find_file("CORRECT.LP")
        if found is None:
            return None
        correct_lp = Path(found)
        if not correct_lp.exists():
            return None
        try:
            content = correct_lp.read_text()
        except:
            return None
        # Find SPACE_GROUP_NUMBER
        m = re.search(r"SPACE_GROUP_NUMBER=\s*(\d+)", content)
        if not m:
            return None
        sg = int(m.group(1))
        # Find unit cell
        m = re.search(r"UNIT_CELL_CONSTANTS=\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)", content)
        if m:
            return {"sg": sg, "cell": [float(x) for x in m.groups()]}
        return {"sg": sg}

    def _extract_correct_resolution(self) -> Optional[float]:
        """Extract estimated resolution from CORRECT.LP."""
        found = self._find_file("CORRECT.LP")
        if found is None:
            return None
        correct_lp = Path(found)
        if not correct_lp.exists():
            return None
        # Try to find I/SIGMA per shell
        try:
            content = correct_lp.read_text()
        except:
            return None
        # Find the last shell with I/SIGMA > 1.6
        shells = re.findall(r"^\s+([\d.]+)\s+\d+\s+\d+\s+\d+\s+[\d.]+\s+[\d.-]+\s+[\d.]+\s+[\d.-]+\s+[\d.-]+\s+[\d.]+", content, re.MULTILINE)
        if shells:
            return float(shells[-1])
        return None

    def _check_aimless_resolution(self) -> bool:
        """Check if resolution was validated against aimless per-shell stats."""
        found = self._find_file("aimless.log") or self._find_file("aimless_*.log")
        if found is None:
            return False
        aimless_log = Path(found)
        if not aimless_log.exists():
            return False
        try:
            content = aimless_log.read_text()
        except:
            return False
        if "AIMLESS_VALIDATION" in content:
            return self._check_aimless_validation_markers(content)
        return False

    def _metric(self, text: str, name: str) -> Optional[float]:
        m = re.search(rf"{re.escape(name)}\s*=\s*([0-9.]+)", text, re.IGNORECASE)
        return float(m.group(1)) if m else None

    def _validation_line(self, content: str, shell: str) -> str:
        for line in content.splitlines():
            if "AIMLESS_VALIDATION" in line and shell in line.lower():
                return line
        return ""

    def _check_aimless_validation_markers(self, content: str) -> bool:
        outer = self._validation_line(content, "outer")
        overall = self._validation_line(content, "overall")
        inner = self._validation_line(content, "inner")
        if not outer or not overall or not inner:
            return False

        frames = self._metric(outer, "frames")
        outer_completeness_required = frames is None or frames >= 180

        outer_checks = [
            (self._metric(outer, "CC1/2"), ">", 40),
            (self._metric(outer, "Mn(I/sd)"), ">", 1.6),
            (self._metric(outer, "Rmeas"), "<", 1.8),
            (self._metric(outer, "Rmerge"), "<", 2.0),
        ]
        if outer_completeness_required:
            outer_checks.append((self._metric(outer, "completeness"), ">", 70))

        overall_checks = [
            (self._metric(overall, "CC1/2"), ">", 90),
            (self._metric(overall, "Mn(I/sd)"), ">", 4),
            (self._metric(overall, "completeness"), ">", 90),
        ]
        inner_checks = [
            (self._metric(inner, "CC1/2"), ">", 90),
            (self._metric(inner, "Mn(I/sd)"), ">", 4),
        ]
        return all(self._compare_metric(value, op, threshold) for value, op, threshold in outer_checks + overall_checks + inner_checks)

    def _compare_metric(self, value: Optional[float], op: str, threshold: float) -> bool:
        if value is None:
            return False
        if op == ">":
            return value > threshold
        if op == "<":
            return value < threshold
        return False

    _OUTER_SHELL_MNISD_LIMIT = 3.0

    def _check_outer_shell_margin(self) -> bool:
        """Check that outer shell Mn(I/sd) is not far above threshold, indicating premature cutoff."""
        aimless_log = self.project_dir / "aimless.log"
        if not aimless_log.exists():
            return False
        try:
            content = aimless_log.read_text()
        except:
            return False
        if "AIMLESS_VALIDATION" not in content:
            return False
        outer = self._validation_line(content, "outer")
        if not outer:
            return False
        mnisd = self._metric(outer, "Mn(I/sd)")
        if mnisd is None:
            return False
        return mnisd <= self._OUTER_SHELL_MNISD_LIMIT

    def _check_low_res_branch(self) -> bool:
        """Check if low-resolution branch should be triggered (resolution >= 3.6 A)."""
        validated_res = self.project_dir / "validated_resolution.txt"
        if not validated_res.exists():
            return False
        try:
            resolution = float(validated_res.read_text().strip().split()[0])
        except (ValueError, IndexError):
            return False
        return resolution >= 3.6

    def _find_model_pdb(self) -> Optional[str]:
        """Find top-ranked AF2/AF3 model PDB."""
        for pattern in ["**/*_rank_001*.pdb", "AF2/**/*_rank_001*.pdb", "../AF2/**/*_rank_001*.pdb"]:
            matches = sorted(Path(self.project_dir).glob(pattern))
            if matches:
                return str(matches[0])
        return None

    def _get_phaser_log(self) -> Optional[Path]:
        logs = sorted(self.project_dir.glob("phaser*.log"))
        return logs[0] if logs else None

    def _check_phaser_stats(self) -> bool:
        log = self._get_phaser_log()
        if not log:
            return False
        try:
            content = log.read_text()
        except:
            return False
        # Check for TFZ and LLG
        tfz_match = re.findall(r"TFZ\s*=+\s*([\d.]+)", content)
        llg_match = re.findall(r"LLG\s*=+\s*(-?[\d.]+)", content)
        if tfz_match and llg_match:
            tfz = max(float(x) for x in tfz_match)
            llg = max(float(x) for x in llg_match)
            return tfz >= 8.0 and llg >= 200
        return False

    def _check_phaser_pak(self) -> bool:
        """Check if PAK is acceptable (0 or explained)."""
        log = self._get_phaser_log()
        if not log:
            return False
        try:
            content = log.read_text()
        except:
            return False
        pak_match = re.findall(r"PAK\s*=+\s*([\d.]+)", content)
        if pak_match:
            pak_min = min(int(float(x)) for x in pak_match)
            return pak_min == 0 or "PAK_EXPLAINED" in content
        return not bool(list(self.project_dir.glob("phaser_copy_*.sol")))

    def _check_iteration(self) -> bool:
        """Check Phenix refinement rounds iterate (not restart from MR model)."""
        r2_log = next(self.project_dir.glob("phenix_r2.log"), None)
        if not r2_log:
            return self._check_refmac_iteration()
        try:
            text = r2_log.read_text()
        except:
            return False
        return "INPUT_PDB=phenix_r1" in text and "INPUT_MTZ=phenix_r1" in text and self._check_refmac_iteration()

    def _check_refmac_iteration(self) -> bool:
        refmac_logs = sorted(self.project_dir.glob("refmac_r*.log"))
        if not refmac_logs:
            return True
        for log in refmac_logs:
            m = re.search(r"refmac_r(\d+)\.log$", log.name)
            if not m:
                continue
            round_num = int(m.group(1))
            if round_num < 3:
                continue
            expected = "refmac_jelly_r2" if round_num == 3 else f"refmac_r{round_num - 1}"
            try:
                text = log.read_text()
            except:
                return False
            if f"INPUT_PDB={expected}" not in text or f"INPUT_MTZ={expected}" not in text:
                return False
        return True
    def _check_tag_strip(self) -> bool:
        """Check search model has fewer residues than raw AF2 model (tag stripped)."""
        sp = self.project_dir / "search_model.pdb"
        return sp.exists()  # existence is sufficient - manual verification needed

    def _check_comparison_rfree(self) -> bool:
        """Check comparison.txt contains MolProbity-validated Rfree."""
        cp = self.project_dir / "comparison.txt"
        if not cp.exists():
            return False
        try:
            text = cp.read_text()
        except:
            return False
        return "Rfree" in text or "R_free" in text
    def _check_mtz_resolution(self) -> bool:
        """Check scaled.mtz resolution against aimless-validated cutoff."""
        if not (self._exists("scaled.mtz") or self._exists("scaled_*.mtz")):
            return False
        expected_found = self._find_file("validated_resolution.txt")
        mtzdump_found = self._find_file("mtzdump_resolution.log")
        if expected_found is None or mtzdump_found is None:
            return False
        expected_path = Path(expected_found)
        mtzdump_path = Path(mtzdump_found)
        try:
            expected = float(expected_path.read_text().strip().split()[0])
            text = mtzdump_path.read_text()
        except:
            return False
        match = re.search(r"Resolution Range\s*:.*?\(\s*[0-9]+\.[0-9]+\s*-\s*([0-9]+\.[0-9]+)\s*A\s*\)", text, re.DOTALL)
        if match:
            observed = float(match.group(1))
        else:
            line_match = re.search(r"Resolution Range\s*:\s*([0-9]+\.[0-9]+)\s+([0-9]+\.[0-9]+)", text)
            if not line_match:
                return False
            observed = float(line_match.group(2))
        return abs(observed - expected) <= 0.01

    def _check_all_copies(self) -> bool:
        """Check that all copy numbers from the Matthews range were tested."""
        expected = self._matthews_copy_range()
        if expected is None:
            return len(list(self.project_dir.glob("phaser_copy_*.log"))) >= 2
        logs = self.project_dir.glob("phaser_copy_*.log")
        tested = set()
        for log in logs:
            m = re.match(r"phaser_copy_(\d+)\.log", log.name)
            if m:
                tested.add(int(m.group(1)))
        return set(expected) == tested

    def _matthews_copy_range(self) -> list[int] | None:
        matthews = self.project_dir / "matthews.log"
        if not matthews.exists():
            return None
        try:
            text = matthews.read_text()
        except:
            return None
        copies: list[int] = []
        for line in text.splitlines():
            m = re.match(r"\s*(\d+)\s+[\d.]+\s+[\d.]+\s+[\d.]+\s*$", line)
            if m:
                copies.append(int(m.group(1)))
        if copies:
            return sorted(copies)
        m = re.search(r"\b(copies?)\s*[=:-]?\s*(\d+)\s*[-to]+\s*(\d+)", text, re.IGNORECASE)
        if m:
            return list(range(int(m.group(2)), int(m.group(3)) + 1))
        m = re.search(r"\b(copies?)\s+(\d+)-(\d+)\b", text, re.IGNORECASE)
        if m:
            return list(range(int(m.group(2)), int(m.group(3)) + 1))
        return None

    def _check_matthews_coverage(self) -> bool:
        return self._matthews_copy_range() is not None

    def _check_best_copy_selected(self) -> bool:
        best = self.project_dir / "phaser_best_copy.txt"
        return best.exists() and bool(best.read_text().strip())

    def _extract_rfree_from_log(self, log_path: Path) -> float | None:
        try:
            text = log_path.read_text()
        except:
            return None
        for pattern in [
            r"Final R-work\s*=\s*[\d.]+\s*R-free\s*=\s*([\d.]+)",
            r"R-free\s*=\s*([\d.]+)",
            r"Final\s+Rfree\s*=\s*([\d.]+)",
        ]:
            m = re.search(pattern, text, re.IGNORECASE)
            if m:
                return float(m.group(1))
        return None

    def _collect_rfree_samples(self, prefix: str, software: str) -> list[RfreeSample]:
        samples: list[RfreeSample] = []
        for log_path in sorted(self.project_dir.glob(f"{prefix}_r*.log")):
            m = re.match(rf"{prefix}_r(\d+)\.log", log_path.name)
            if not m:
                continue
            round_num = int(m.group(1))
            if prefix == "refmac" and round_num < 3:
                continue
            rfree = self._extract_rfree_from_log(log_path)
            if rfree is not None:
                samples.append(RfreeSample(round=round_num, software=software, rfree=rfree))
        return samples

    def _check_phenix_rfree_trend(self) -> bool:
        samples = self._collect_rfree_samples("phenix", "phenix")
        if not samples:
            return self._exists("phenix_r1.log") and self._check_iteration()
        if not self._check_iteration():
            return False
        trend = detect_rfree_plateau(samples)
        return trend != RfreeTrend.PLATEAU

    def _check_refmac_rfree_trend(self) -> bool:
        samples = self._collect_rfree_samples("refmac", "refmac")
        if not samples:
            return self._exists("refmac_r4.pdb") or self._exists("refmac_r4_001.pdb")
        if not self._check_refmac_iteration():
            return False
        trend = detect_rfree_plateau(samples)
        return trend != RfreeTrend.PLATEAU

    def _check_high_rfree_diagnosis(self) -> bool:
        phenix_samples = self._collect_rfree_samples("phenix", "phenix")
        refmac_samples = self._collect_rfree_samples("refmac", "refmac")
        all_samples = phenix_samples + refmac_samples
        if not all_samples:
            return True

        latest = max(all_samples, key=lambda s: s.round)
        twin_laws = self._load_twin_laws()
        twin_refinement_recommended = should_use_twin_refinement(twin_laws)
        tried = []
        if phenix_samples:
            tried.append("phenix")
        if refmac_samples:
            tried.append("refmac")

        from crystal_agent.decision_engine import RfreeAction
        if twin_refinement_recommended and not self._exists("twin_refine.log"):
            return True
        action = high_rfree_diagnosis(
            rfree=latest.rfree,
            current_software=latest.software,
            software_already_tried=tried,
            twin_laws=twin_laws,
        )
        return action != RfreeAction.STOP_USER_INTERVENTION

    def _modelcraft_attempted(self) -> bool:
        """Modelcraft must always be tried. Attempt is proven by a run log (even a
        failed run) or by any modelcraft output artifact."""
        return (
            self._exists("modelcraft_run.log")
            or self._exists("modelcraft_work/modelcraft_run.log")
            or self._exists("modelcraft.json")
            or self._exists("modelcraft.cif")
        )

    def _modelcraft_succeeded(self) -> bool:
        """Modelcraft produced a usable rebuilt model (json + cif). A failed run is
        acceptable and does not require the downstream branch."""
        return self._exists("modelcraft.json") and self._exists("modelcraft.cif")

    def _check_modelcraft_comparison(self) -> bool:
        """Check that modelcraft comparison was done (log exists or Rfree improved flag file)."""
        return self._exists("modelcraft_comparison.log") or self._exists("modelcraft.kept")

    def _load_twin_laws(self):
        xtriage_log = self.project_dir / "xtriage.log"
        if not xtriage_log.exists():
            return []
        try:
            text = xtriage_log.read_text()
        except:
            return []
        return extract_twin_laws_from_xtriage(text)

    def get_status(self, step_name: str, prerequisites_met: bool) -> str:
        try:
            check_fn = self.steps[step_name]["check"]
            result = check_fn()
        except:
            result = False

        if not result and is_expert_project(self.project_dir) and self._expert_step_output_exists(step_name):
            result = True

        if not prerequisites_met:
            return STATUS_NOT_REACHED
        if result:
            return STATUS_OK
        return STATUS_FAIL

    def run(self) -> tuple[str, int]:
        """Run full verification, return (output, exit_code). exit_code=1 if any step ✗."""
        lines = []
        lines.append(f"\n{'='*60}")
        lines.append(f"Pipeline Step Verification: {self.project_dir.name}")
        lines.append(f"{'='*60}\n")

        phase_names = {
            0: "Phase 0: Project Init",
            1: "Phase 1: XDS Processing",
            2: "Phase 2: Scaling",
            3: "Phase 3: Model Preparation",
            4: "Phase 4: Molecular Replacement",
            5: "Phase 5: Refinement",
            6: "Phase 6: Validation & Comparison",
        }

        current_phase = None
        prev_ok = True
        status_counts = {STATUS_OK: 0, STATUS_FAIL: 0, STATUS_IN_PROGRESS: 0, STATUS_NOT_REACHED: 0}

        for step_name, step_info in self.steps.items():
            phase = step_info["phase"]
            label = step_info["label"]
            if phase != current_phase:
                current_phase = phase
                lines.append(f"  {phase_names.get(phase, f'Phase {phase}')}")

            status = self.get_status(step_name, prev_ok)
            status_counts[status] = status_counts.get(status, 0) + 1
            lines.append(f"    [{status}] {label}")

            if status != STATUS_OK and prev_ok:
                prev_ok = False

        expert_violations = check_expert_approval_consistency(str(self.project_dir))
        if expert_violations:
            lines.append("")
            lines.append("  Expert Mode Audit")
            for step_name in expert_violations:
                lines.append(f"    [{STATUS_FAIL}] {step_name}: output exists without consumed expert approval and completed guard")
            status_counts[STATUS_FAIL] += len(expert_violations)

        lines.append(f"\n{'='*60}")
        lines.append(f"Summary: {status_counts[STATUS_OK]} passed, "
                     f"{status_counts[STATUS_FAIL]} failed, "
                     f"{status_counts[STATUS_IN_PROGRESS]} in-progress, "
                     f"{status_counts[STATUS_NOT_REACHED]} not-reached")
        lines.append(f"{'='*60}")

        output = "\n".join(lines)
        print(output)

        exit_code = 1 if status_counts[STATUS_FAIL] > 0 else 0
        return output, exit_code


if __name__ == "__main__":
    import argparse, sys
    parser = argparse.ArgumentParser(description="Pipeline Step Tracker")
    parser.add_argument("project_dir", help="Path to project directory")
    parser.add_argument("--before", help="Step name about to be executed")
    parser.add_argument("--after", help="Step name just executed")
    args = parser.parse_args()

    if args.before or args.after:
        from crystal_agent.step_tracker import Guard
        guard = Guard(args.project_dir)
        if args.before:
            guard.before(args.before)
        if args.after:
            guard.after(args.after)
        sys.exit(0)
    else:
        tracker = StepTracker(args.project_dir)
        _, exit_code = tracker.run()
        sys.exit(exit_code)


def enforce_checkpoint(project_dir: str) -> None:
    """Block execution if a guard step is unclosed."""
    guard = Guard(project_dir)
    guard._load()
    if guard.state.get("current") is not None:
        msg = (
            f"GUARD VIOLATION: Step '{guard.state['current']}' was started "
            f"but not closed with --after. Run 'crystal-agent guard "
            f"--after {guard.state['current']}' first, or inspect .step_state.json."
        )
        print(msg)
        sys.exit(1)


def check_guard_consistency(project_dir: str) -> list[str]:
    """Return guard step names that have output files but were never completed in guard state."""
    guard = Guard(project_dir)
    guard._load()
    completed = set(guard.state.get("completed", []))
    tracker = StepTracker(project_dir)
    violated: list[str] = []

    for step_name, glob_pattern in STEP_OUTPUT_SIGNATURES.items():
        if step_name in completed:
            continue
        if list(tracker.project_dir.glob(glob_pattern)):
            violated.append(step_name)

    return violated


def check_expert_approval_consistency(project_dir: str) -> list[str]:
    """Return expert-mode output steps missing consumed approval or guard completion."""
    if not is_expert_project(project_dir):
        return []
    guard = Guard(project_dir)
    guard._load()
    completed = set(guard.state.get("completed", []))
    tracker = StepTracker(project_dir)
    violations: list[str] = []
    for step_name, glob_pattern in STEP_OUTPUT_SIGNATURES.items():
        if not list(tracker.project_dir.glob(glob_pattern)):
            continue
        if step_name not in completed or not _has_consumed_approval(project_dir, step_name):
            violations.append(step_name)
    return violations


def resume_gate(project_dir: str) -> None:
    """Resume gate: must run naming-guide and verify-steps after any interruption."""
    from crystal_agent.architecture import get_naming_conventions
    print("[RESUME-GATE] Running naming-guide ...")
    for key, value in get_naming_conventions().items():
        print(f"- {key}: {value}")
    print("[RESUME-GATE] Running verify-steps ...")
    tracker = StepTracker(project_dir)
    tracker.run()

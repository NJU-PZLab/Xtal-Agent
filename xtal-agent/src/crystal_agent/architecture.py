"""Architecture maintenance helpers for the crystallography agent."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re


BACKUP_INCLUDE_NAMES = {
    "AGENTS.md",
    "skills",
    "docs",
    "example",
    "crystal-agent/src",
    "crystal-agent/skills",
    "crystal-agent/templates",
    "crystal-agent/pyproject.toml",
}

BACKUP_EXCLUDE_SUFFIXES = {
    ".cbf",
    ".HKL",
    ".pck",
}

BACKUP_EXCLUDE_NAMES = {
    "XDS_ASCII.HKL",
    "INTEGRATE.HKL",
    "SPOT.XDS",
    "ABS.cbf",
    "ABSORP.cbf",
    "BKGPIX.cbf",
    "BKGINIT.cbf",
    "BLANK.cbf",
    "DECAY.cbf",
    "GAIN.cbf",
    "MODPIX.cbf",
}


MANDATORY_RULES: dict[str, tuple[str, ...]] = {
    "verify-steps": ("verify-steps",),
    "IDXREF": ("never skip idxref", "idxref"),
    "aimless thresholds": ("aimless thresholds", "cc1/2 > 40", "mn(i/sd) > 1.6"),
    "invalid-resolution data": ("invalid-resolution data", "invalid resolution data"),
    "4+ Phenix rounds": ("4+ phenix rounds", "at least 4 rounds of phenix"),
    "4+ Refmac rounds": ("4+ refmac rounds", "at least 4 rounds of refmac"),
    "immediately preceding round": (
        "immediately preceding round",
        "immediately preceding output pdb",
        "immediately previous pdb",
    ),
    "TLS optimization": ("tls optimization",),
    "ordered_solvent": ("ordered_solvent", "waters fitted"),
    "real_space_correlation": ("real_space_correlation", "rscc"),
    "MolProbity Rfree": ("molprobity rfree", "molprobity r-free"),
    "lowest Rfree wins": ("lowest rfree wins", "lowest r-free wins"),
    "final/ directory": ("final/ directory", "final directory"),
    "resume naming gate": ("naming-guide", "resume with the next numeric round", "do not renumber"),
    "enforce checkpoint gate": ("enforce-checkpoint", "step_state.json", "unclosed current step"),
    "ligand ccp4 lookup": (
        "ccp4 monomer library",
        "ccp4 ligand",
        "kabsch-map af3 ligand atom names",
        "map_ligand_atoms",
    ),
}

REQUIRED_DECISION_WIRING = {
    "idxref_failure_fix": "phase_orchestrator.py",
    "suggest_data_range_from_mosaicity": "phase_orchestrator.py",
    "sg_conflict_resolution": "phase_orchestrator.py",
    "select_prediction_tool": "phase_orchestrator.py",
    "matthews_copy_range": "phase_orchestrator.py",
    "select_best_copy_number": "phase_orchestrator.py",
    "phaser_troubleshooting_order": "phase_orchestrator.py",
    "should_use_twin_refinement": "step_tracker.py",
}

REQUIRED_AGENT_DOC_REFERENCES = tuple(REQUIRED_DECISION_WIRING.keys()) + ("crystal-agent run-phase",)


@dataclass(frozen=True)
class ArchitectureAuditResult:
    passed: bool
    missing_rules: list[str]


@dataclass(frozen=True)
class PhaseGuide:
    phase: str
    title: str
    code_calls: list[str]
    mandatory_rules: list[str]
    outputs: list[str]
    command_templates: list[str]


@dataclass(frozen=True)
class CommandTemplate:
    name: str
    command: str
    preconditions: str
    outputs: str
    notes: str = ""


@dataclass(frozen=True)
class TemplateValidationResult:
    passed: bool
    missing: list[str]


COMMAND_TEMPLATES: dict[str, CommandTemplate] = {
    "xds-generate-inp": CommandTemplate(
        "xds-generate-inp",
        'crystal-agent/src/crystal_agent/generate_XDS.INP "/path/to/data_?????.cbf"',
        "Raw CBF path exists; detector metadata is present in image headers.",
        "XDS.INP",
        "Do not manually invent detector geometry. SPOT_RANGE is auto-set to first half of DATA_RANGE. Only ask user for SPOT_RANGE when IDXREF fails with INSUFFICIENT PERCENTAGE.",
    ),
    "xds-run": CommandTemplate(
        "xds-run",
        "xds_par > xds_<round>.log 2>&1",
        "XDS.INP exists; JOB includes IDXREF.",
        "CORRECT.LP, XDS_ASCII.HKL, GXPARM.XDS when successful.",
    ),
    "run-phase": CommandTemplate(
        "run-phase",
        "crystal-agent run-phase /path/to/project phase<N>",
        "Project directory exists; manifest and phase prerequisites are satisfied.",
        "Phase-specific decision artifacts and command logs.",
        "Agents must use this before manual branch handling so decision_engine calls are enforced.",
    ),
    "dials-import": CommandTemplate(
        "dials-import",
        'dials.import "/path/to/data_?????.cbf" output.experiments=imported.expt > dials_import.log 2>&1',
        "Raw images exist and XDS/DIALS branch comparison is needed.",
        "imported.expt, dials_import.log",
    ),
    "dials-find-spots": CommandTemplate(
        "dials-find-spots",
        "dials.find_spots imported.expt output.reflections=strong.refl > dials_find_spots.log 2>&1",
        "imported.expt exists.",
        "strong.refl, dials_find_spots.log",
    ),
    "dials-index": CommandTemplate(
        "dials-index",
        "dials.index imported.expt strong.refl output.experiments=indexed.expt output.reflections=indexed.refl > dials_index.log 2>&1",
        "imported.expt and strong.refl exist.",
        "indexed.expt, indexed.refl, dials_index.log",
        "If DIALS gives unexpected P1, compare with XDS plus pointless/aimless before accepting.",
    ),
    "dials-integrate": CommandTemplate(
        "dials-integrate",
        "dials.integrate indexed.expt indexed.refl output.experiments=integrated.expt output.reflections=integrated.refl > dials_integrate.log 2>&1",
        "indexed.expt and indexed.refl exist.",
        "integrated.expt, integrated.refl, dials_integrate.log",
    ),
    "dials-scale": CommandTemplate(
        "dials-scale",
        "dials.scale integrated.expt integrated.refl output.experiments=scaled.expt output.reflections=scaled.refl > dials_scale.log 2>&1",
        "integrated.expt and integrated.refl exist.",
        "scaled.expt, scaled.refl, dials_scale.log",
    ),
    "dials-export-mtz": CommandTemplate(
        "dials-export-mtz",
        "dials.export scaled.expt scaled.refl mtz.hklout=dials_scaled.mtz > dials_export.log 2>&1",
        "scaled.expt and scaled.refl exist.",
        "dials_scaled.mtz, dials_export.log",
    ),
    "xia2-fallback": CommandTemplate(
        "xia2-fallback",
        'xia2 image="/path/to/data_?????.cbf" > xia2.log 2>&1',
        "XDS and DIALS failed or produced unstable indexing.",
        "xia2 output directory and xia2.log",
        "Validate xia2/auto-processing output with pointless, aimless, and xtriage before downstream use.",
    ),
    "pointless": CommandTemplate(
        "pointless",
        "pointless hklin xds_f.mtz hklout point.mtz > point.log 2>&1",
        "XDS/DIALS/exported MTZ exists.",
        "point.mtz, point.log",
    ),
    "aimless-scale": CommandTemplate(
        "aimless-scale",
        "aimless hklin point.mtz hklout scaled_<cutoff>.mtz > aimless_<cutoff>.log 2>&1",
        "point.mtz exists; unique output names selected for resolution scans.",
        "scaled_<cutoff>.mtz, aimless_<cutoff>.log",
        "Do not overwrite scaled.mtz during scans.",
    ),
    "mtzdump-resolution": CommandTemplate(
        "mtzdump-resolution",
        'mtzdump hklin output.mtz <<< "" 2>&1 | grep "Resolution Range"',
        "MTZ exists after aimless, ctruncate, freerflag, or Phenix seed.",
        "Resolution Range line in log/stdout.",
    ),
    "matthews": CommandTemplate(
        "matthews",
        "matthews_coef << 'EOF' > matthews.log 2>&1\nCELL <a> <b> <c> <alpha> <beta> <gamma>\nSYMM <sg_number>\nMOLW <mw_da>\nAUTO\nEND\nEOF",
        "Validated truncated MTZ and FASTA exist.",
        "matthews.log",
        "Use sequence molecular weight, not only PDB residue count. Run CCP4 matthews_coef, not phenix.matthews.",
    ),
    "phaser-mr": CommandTemplate(
        "phaser-mr",
        "phenix.phaser < phaser_copy_<copies>.inp > phaser_copy_<copies>.log 2>&1\nMODE MR_AUTO\nHKLIN scaled.mtz\nLABIN I=IMEAN SIGI=SIGIMEAN\nENSEMBLE 1 PDB search_model.pdb RMS 1\nENSEMBLE 1 ESTIMATOR oeffner\nCOMPOSITION PROTEIN SEQ seq.fasta NUM 1\nSEARCH ENSEMBLE 1\n... repeat SEARCH ENSEMBLE 1 for each copy ...\nJOBS 16\nPEAKS ROT SELECT PERCENT CUTOFF 75\nPEAKS TRA SELECT PERCENT CUTOFF 75\nPURGE ROT PERCENT 75\nPURGE TRA PERCENT 75\nPURGE RNP PERCENT 75\nRESHARPEN PERCENTAGE 100\nELLG HIRES ON\nSGALTERNATIVE SELECT ALL\nTNCS RLIST ADD ON\nROOT phaser_copy_<copies>\nEND\n\nUse multiple SEARCH ENSEMBLE 1 lines (one per copy) instead of SEARCH NUM N.\nUse intensities (I=IMEAN SIGI=SIGIMEAN), not F/SIGF.\nRMS=1 instead of IDENTITY=100 to allow search with ~1A model error.\nRESHARPEN sharpens data; PEAKS/PURGE 75% retains more candidates.",
        "Phase 2 validated truncated MTZ, cleaned search_model.pdb, FASTA, and Matthews copy range exist.",
        "phaser_copy_<copies>.sol, phaser_copy_<copies>.pdb, phaser_copy_<copies>.log",
    ),
    "xtriage": CommandTemplate(
        "xtriage",
        'phenix.xtriage scaled.mtz scaling.input.xray_data.obs_labels="IMEAN,SIGIMEAN" > xtriage.log 2>&1',
        "Strong MR later gives Rfree > 0.35 or twinning/pathology is suspected.",
        "xtriage.log",
    ),
    "twin-refine": CommandTemplate(
        "twin-refine",
        'phenix.refine data.mtz model.pdb labels.name="IMEAN,SIGIMEAN" data_manager.fmodel.xray_data.twin_law="<TWIN_LAW>" strategy=individual_sites+individual_adp secondary_structure.enabled=True ramachandran_restraints=True output.write_map_coefficients=False output.write_mtz_file=False output.prefix=twin_refine overwrite=True nproc=16 > twin_refine.log 2>&1',
        "Twin law extracted from xtriage log via extract_twin_laws_from_xtriage(). Phenix 2.1: disable map coefficients and MTZ output for twinned refinement.",
        "twin_refine_001.pdb, twin_refine.log",
        "Extract twin law candidates with extract_twin_laws_from_xtriage(text) before running.",
    ),
    "phenix-seed": CommandTemplate(
        "phenix-seed",
        'phenix.refine scaled.mtz mr_model.pdb labels.name="IMEAN,SIGIMEAN" xray_data.r_free_flags.generate=True strategy=individual_sites main.number_of_macro_cycles=1 output.prefix=seed overwrite=True nproc=8 > seed.log 2>&1',
        "Validated truncated MTZ and MR model exist.",
        "seed_data.mtz, seed_001.pdb, seed.log",
    ),
    "phenix-iterative-refine": CommandTemplate(
        "phenix-iterative-refine",
        'phenix.refine <previous.mtz> <previous.pdb> labels.name="I-obs,SIGI-obs" xray_data.r_free_flags.label="R-free-flags" strategy=individual_sites+individual_adp ordered_solvent=true output.prefix=phenix_r<N> overwrite=True refinement.main.nproc=16 > phenix_r<N>.log 2>&1',
        "Previous round PDB and companion MTZ exist; do not restart from MR after R1.",
        "phenix_r<N>.pdb, phenix_r<N>.mtz, phenix_r<N>.log",
    ),
    "ctruncate": CommandTemplate(
        "ctruncate",
        'ctruncate -mtzin scaled.mtz -mtzout ctruncate.mtz -colin "/*/*/[IMEAN,SIGIMEAN]" > ctruncate.log 2>&1',
        "Validated truncated intensity MTZ exists.",
        "ctruncate.mtz, ctruncate.log",
    ),
    "freerflag": CommandTemplate(
        "freerflag",
        "freerflag hklin ctruncate.mtz hklout ctruncate_free.mtz << 'EOF' > freerflag.log 2>&1\nfreerfrac 0.05\nEND\nEOF",
        "ctruncate.mtz exists.",
        "ctruncate_free.mtz, freerflag.log",
    ),
    "refmac-jelly": CommandTemplate(
        "refmac-jelly",
        "refmac5 xyzin <previous.pdb> xyzout refmac_jelly_r<N>.pdb hklin <previous.mtz> hklout refmac_jelly_r<N>.mtz << 'EOF' > refmac_jelly_r<N>.log 2>&1\nmake hydrogen no\nlabin FP=F SIGFP=SIGF FREE=FreeR_flag\nrefi type REST resi MLKF meth CGMAT bref ISOT\nncyc 50\nexternal restraint jelly\nEND\nEOF",
        "Previous PDB and companion Refmac MTZ exist; use for rounds 1-2.",
        "refmac_jelly_r<N>.pdb, refmac_jelly_r<N>.mtz, refmac_jelly_r<N>.log",
    ),
    "refmac-free": CommandTemplate(
        "refmac-free",
        "refmac5 xyzin <previous.pdb> xyzout refmac_r<N>.pdb hklin <previous.mtz> hklout refmac_r<N>.mtz << 'EOF' > refmac_r<N>.log 2>&1\nmake hydrogen no\nlabin FP=F SIGFP=SIGF FREE=FreeR_flag\nrefi type REST resi MLKF meth CGMAT bref ISOT\nncyc 50\nEND\nEOF",
        "Previous PDB and companion Refmac MTZ exist; use for rounds 3+.",
        "refmac_r<N>.pdb, refmac_r<N>.mtz, refmac_r<N>.log",
    ),
    "modelcraft-run": CommandTemplate(
        "modelcraft-run",
        'modelcraft xray --data <best_mtz> --contents <fasta> --model <best_pdb> --cycles 10 --auto-stop-cycles 3',
        "Best refined PDB and companion MTZ from winning branch exist; FASTA exists.",
        "modelcraft.json, modelcraft.cif, modelcraft.log",
        "Select the cycle with lowest r_free from modelcraft.json cycles array. Convert output .cif to PDB with phenix.cif_as_pdb. Then run 2 refmac rounds; keep only if final Rfree < pre-modelcraft best.",
    ),
    "modelcraft-refmac": CommandTemplate(
        "modelcraft-refmac",
        "refmac5 xyzin modelcraft.pdb xyzout modelcraft_r<N>.pdb hklin <best_mtz> hklout modelcraft_r<N>.mtz << 'EOF' > modelcraft_r<N>.log 2>&1\nmake hydrogen no\nlabin FP=F SIGFP=SIGF FREE=FreeR_flag\nrefi type REST resi MLKF meth CGMAT bref ISOT\nncsr local\nncyc 8\nweight matrix 0.01\nsolvent yes\nEND\nEOF",
        "modelcraft.pdb and best MTZ with FreeR_flag column exist.",
        "modelcraft_r<N>.pdb, modelcraft_r<N>.mtz, modelcraft_r<N>.log",
        "Round 1-2 use jelly-body (weight matrix 0.01), rounds 3+ drop it. Add ncsr local for homo-oligomers.",
    ),
    "refmac-ncs": CommandTemplate(
        "refmac-ncs",
        "refmac5 xyzin <previous.pdb> xyzout refmac_ncs_r<N>.pdb hklin <previous.mtz> hklout refmac_ncs_r<N>.mtz << 'EOF' > refmac_ncs_r<N>.log 2>&1\nmake hydrogen no\nlabin FP=F SIGFP=SIGF FREE=FreeR_flag\nrefi type REST resi MLKF meth CGMAT bref ISOT\nncsr local\nncyc 50\nEND\nEOF",
        "ASU > 1 copies; previous PDB and MTZ exist.",
        "refmac_ncs_r<N>.pdb, refmac_ncs_r<N>.mtz, refmac_ncs_r<N>.log",
        "NCS restraints are mandatory when ASU contains >1 copy of the same chain. Apply after jelly round 2 for homo-oligomers.",
    ),
    "rscc": CommandTemplate(
        "rscc",
        "phenix.real_space_correlation model.pdb data.mtz detail=residue > rsc.log 2>&1",
        "Refined model and companion MTZ exist.",
        "rsc.log",
    ),
    "molprobity-final": CommandTemplate(
        "molprobity-final",
        "phenix.molprobity final_best.pdb final_best.mtz > molprobity_final.log 2>&1",
        "Final best model after waters/TLS and companion MTZ exist.",
        "molprobity_final.log",
    ),
    "ligand-elbow": CommandTemplate(
        "ligand-elbow",
        'phenix.elbow --smiles="<PUBCHEM_SMILES>" --output=<prefix> --id=<CCD>',
        "PubChem-verified SMILES and three-letter code are known.",
        "<prefix>.pdb, <prefix>.cif",
    ),
    "map-ligand-atoms": CommandTemplate(
        "map-ligand-atoms",
        'python crystal-agent/src/crystal_agent/map_ligand_atoms.py --af3-pdb <af3_model.pdb> --af3-chain <chain> --ccd-code <CODE> --ccp4-monomer-dir <ccp4_monomer_dir> --output <mapped.pdb>',
        "AF3 model PDB with ligand exists; CCD code and CCP4 monomer library path are known.",
        "<mapped.pdb>",
        "Kabsch-aligns AF3 ligand coordinates to CCP4 monomer library 3D coordinates, then nearest-neighbor matches by element type. Falls back to --elbow-cif if CCD code not in CCP4 library. Output PDB uses AF3 coordinates with CCP4/elbow atom names for Refmac/Phenix refinement.",
    ),
}

NAMING_CONVENTIONS: dict[str, str] = {
    "phenix_seed": "seed_data.mtz / seed_001.pdb / seed.log",
    "phenix_round": "phenix_r<N>.pdb / phenix_r<N>.mtz / phenix_r<N>.log",
    "refmac_jelly_round": "refmac_jelly_r<N>.pdb / refmac_jelly_r<N>.mtz / refmac_jelly_r<N>.log",
    "refmac_round": "refmac_r<N>.pdb / refmac_r<N>.mtz / refmac_r<N>.log",
    "phaser_copy": "phaser_copy_<copies>.sol / phaser_copy_<copies>.pdb / phaser_copy_<copies>.log",
    "validated_resolution": "validated_resolution.txt + mtzdump_resolution.log",
    "final_archive": "final/<best_model_and_data_files>",
    "modelcraft_output": "modelcraft.json / modelcraft.cif / modelcraft.log",
    "modelcraft_refmac": "modelcraft_r<N>.pdb / modelcraft_r<N>.mtz / modelcraft_r<N>.log",
}


PHASE_GUIDES: dict[str, PhaseGuide] = {
    "phase1": PhaseGuide(
        phase="phase1",
        title="Phase 1: XDS Processing",
        code_calls=[
            "crystal-agent run-phase <project_dir> phase1  # calls idxref_failure_fix and suggest_data_range_from_mosaicity",
            "crystal_agent.decision_engine.idxref_failure_fix(attempt, current_pixels, current_spot_range, simple_mode=True)",
            "crystal_agent.decision_engine.suggest_data_range_from_mosaicity(mosaicity)",
            "crystal-agent guard <project_dir> --before phase1_correct_lp",
            "crystal-agent/src/crystal_agent/generate_XDS.INP \"/path/to/data_?????.cbf\"",
            "xds_par > xds_round1.log 2>&1",
            "crystal-agent verify-steps <project_dir>",
            "xds_par > xds_round2.log 2>&1",
            "crystal-agent verify-steps <project_dir>",
            "crystal-agent guard <project_dir> --after phase1_correct_lp",
        ],
        mandatory_rules=[
            "Never skip IDXREF",
            "Feed SPACE_GROUP_NUMBER and UNIT_CELL_CONSTANTS from round 1 back into XDS.INP",
            "Inspect CORRECT.LP I/SIGMA and push resolution until outer shell is near 1.6",
            "Do not expand SPOT_RANGE beyond user guidance",
            "If IDXREF fails, adjust MINIMUM_NUMBER_OF_PIXELS_IN_A_SPOT (3-8) first, then shift/decrease SPOT_RANGE",
            "In simple mode, stop before CORRECT-only or resolution limits below 30 A",
            "Inspect INTEGRATE.LP mosaicity and select DATA_RANGE below median; run parallel full vs optimal jobs",
            "For trimmed DATA_RANGE, use JOB=CORRECT with existing INTEGRATE.HKL when IDXREF fails",
        ],
        outputs=["XDS.INP", "CORRECT.LP", "XDS_ASCII.HKL", "GXPARM.XDS"],
        command_templates=[
            "xds-generate-inp",
            "xds-run",
            "dials-import",
            "dials-find-spots",
            "dials-index",
            "dials-integrate",
            "dials-scale",
            "dials-export-mtz",
            "xia2-fallback",
        ],
    ),
    "phase2": PhaseGuide(
        phase="phase2",
        title="Phase 2: Scaling and AIMLESS Validation",
        code_calls=[
            "crystal-agent run-phase <project_dir> phase2  # calls sg_conflict_resolution",
            "crystal_agent.decision_engine.sg_conflict_resolution(xds_sg, aimless_sg, xds_retry_successful)",
            "crystal-agent guard <project_dir> --before phase2_pointless",
            "pointless hklin xds_f.mtz hklout point.mtz > point.log 2>&1",
            "aimless hklin point.mtz hklout scaled.mtz > aimless.log 2>&1",
            "mtzdump hklin scaled.mtz <<< \"\" 2>&1 | grep \"Resolution Range\"",
            "crystal-agent verify-steps <project_dir>",
            "crystal-agent guard <project_dir> --after phase2_pointless",
        ],
        mandatory_rules=[
            "Outer shell must pass CC1/2 > 40, Mn(I/sd) > 1.6, completeness > 70%, Rmeas < 1.8, Rmerge < 2.0",
            "Exception: ignore completeness only when frames < 180",
            "Never use invalid-resolution data downstream",
            "Verify MTZ resolution after every conversion",
            "Record AIMLESS_VALIDATION outer/overall/inner markers, validated_resolution.txt, and mtzdump_resolution.log",
            "If aimless SG differs from XDS, retry XDS with new SG first; fall back to parallel branches only if retry fails",
            "After aimless validates resolution cutoff, feed it back to XDS.INP INCLUDE_RESOLUTION_RANGE and re-run XDS so CORRECT scaling uses only valid data",
        ],
        outputs=["point.mtz", "point.log", "scaled.mtz", "aimless.log"],
        command_templates=["pointless", "aimless-scale", "mtzdump-resolution", "xtriage"],
    ),
    "phase3": PhaseGuide(
        phase="phase3",
        title="Phase 3: Model Preparation",
        code_calls=[
            "crystal-agent run-phase <project_dir> phase3  # calls select_prediction_tool and matthews_copy_range",
            "crystal_agent.decision_engine.select_prediction_tool(...) before choosing AF2/AF3",
            "crystal_agent.decision_engine.matthews_copy_range(cell_volume, sequence_mw, sg_number)",
            "crystal-agent guard <project_dir> --before phase3_msa",
            "Use msa-generator for .a3m generation",
            "Use af2-predictor for ordinary single-chain protein targets",
            "Use alphafold3-predictor for glycoproteins, supported metalloproteins, ligands, and nucleic-acid complexes",
            "Run map_ligand_atoms.py to Kabsch-map AF3 ligand atom names to CCP4 monomer library (or elbow CIF fallback)",
            "crystal-agent verify-steps <project_dir>",
            "crystal-agent guard <project_dir> --after phase3_msa",
        ],
        mandatory_rules=[
            "Glycoproteins must use AF3 with glycan sites/composition",
            "Protein-DNA/RNA complexes must use AF3 complex prediction and full complex MR model",
            "Protein-ligand complexes (small molecule) must use AF3 with --ligands or --ligands-smiles; include ligand in MR",
            "After AF3 prediction, look up ligand CCD code in CCP4 monomer library for native restraints; Kabsch-map AF3 atom names to CCP4 atom names",
            "If CCD code not in CCP4 library, generate restraints with phenix.elbow and Kabsch-map to elbow atom names as fallback",
            "Metalloproteins require metal species and count before prediction choice",
            "Strip pLDDT < 80 residues and terminal tags",
            "Calculate Matthews coefficient before MR",
        ],
        outputs=["*.a3m", "*.done.txt", "search_model.pdb", "matthews.log"],
        command_templates=["matthews", "ligand-elbow", "map-ligand-atoms"],
    ),
    "phase4": PhaseGuide(
        phase="phase4",
        title="Phase 4: Molecular Replacement",
        code_calls=[
            "crystal-agent run-phase <project_dir> phase4  # calls select_best_copy_number and phaser_troubleshooting_order",
            "crystal_agent.decision_engine.select_best_copy_number(phaser_sweep)",
            "crystal_agent.decision_engine.phaser_troubleshooting_order(failure_count)",
            "crystal-agent guard <project_dir> --before phase4_phaser",
            "phenix.phaser < phaser_copy_<N>.inp > phaser_copy_<N>.log 2>&1",
            "phenix.xtriage scaled.mtz scaling.input.xray_data.obs_labels=\"IMEAN,SIGIMEAN\" > xtriage.log 2>&1",
            "crystal-agent verify-steps <project_dir>",
            "crystal-agent guard <project_dir> --after phase4_phaser",
        ],
        mandatory_rules=[
            "Use only the resolution-validated truncated MTZ",
            "Test all plausible copy numbers from Matthews range",
            "Use intensities (LABIN I=IMEAN SIGI=SIGIMEAN), not F/SIGF",
            "Use RMS=1 not IDENTITY=100 to allow ~1A model deviation",
            "Use multiple SEARCH ENSEMBLE 1 lines (one per copy), never SEARCH NUM N",
            "Include RESHARPEN PERCENTAGE 100, ELLG HIRES ON, TNCS RLIST ADD ON",
            "Use PEAKS/PURGE 75% to retain more candidate solutions",
            "Accept strong MR only when TFZ > 8, LLG > 200, PAK = 0 or explained",
            "Prefer strong with PAK=0 and all placed over strong with PAK>0; use select_best_copy_number",
            "Run xtriage before expensive refinement if strong MR later gives Rfree > 0.35",
            "If MR > 30 min and multi-domain model: split into domain PDBs and rerun as separate ENSEMBLEs",
        ],
        outputs=["phaser_*.sol", "phaser_*.pdb", "phaser*.log", "xtriage.log when triggered"],
        command_templates=["phaser-mr", "xtriage"],
    ),
    "phase5_lowres": PhaseGuide(
        phase="phase5_lowres",
        title="Phase 5-LR: Low-Resolution Refinement (>= 3.6 A)",
        code_calls=[
            "crystal-agent run-phase <project_dir> phase5_lowres",
            "crystal-agent phase-guide phase5_lowres",
            "crystal-agent guard <project_dir> --before phase5_lowres_rigid_body",
            "crystal-agent guard <project_dir> --after phase5_lowres_final",
            "crystal_agent.decision_engine.detect_low_resolution(resolution, mode)",
            "crystal_agent.decision_engine.select_low_res_refine_strategy(is_low_res, expert_mode, user_accepted)",
            "crystal-agent verify-steps <project_dir>",
        ],
        mandatory_rules=[
            "Trigger when aimless-validated resolution >= 3.6 A",
            "Simple mode: auto-enter low-resolution branch",
            "Expert mode: prompt user whether to adopt low-resolution strategy",
            "Run 1 round rigid body refinement",
            "Run 4 rounds phenix grouped ADP; if Rfree does not improve over rigid body, skip phenix and start refmac from MR model",
            "Run 2 refmac jelly-body then 2 refmac free rounds (iterative)",
            "If refmac Rfree <= 0.35: run modelcraft for model completion",
            "After modelcraft: delete garbage chains, run RSC, flag RSCC < 0.7 residues",
            "Present geometry stats; if user approves, run phenix rotamer + secondary structure restraints",
            "Let user choose final model; run MolProbity and archive to final/",
            "Do not add water molecules",
            "Refmac lacks rotamer restraint; use phenix for geometry optimization",
        ],
        outputs=["phenix_rb_001.pdb", "phenix_r*.pdb", "refmac_jelly_r*.pdb", "refmac_r*.pdb", "modelcraft.json", "rsc.log", "final_geom_001.pdb", "molprobity.log", "final/", "manual_notes.md"],
        command_templates=[
            "phenix-iterative-refine",
            "ctruncate",
            "freerflag",
            "refmac-jelly",
            "refmac-free",
            "modelcraft-run",
            "modelcraft-refmac",
            "rscc",
            "molprobity-final",
        ],
    ),
    "phase5": PhaseGuide(
        phase="phase5",
        title="Phase 5: Refinement and Post-Refinement",
        code_calls=[
            "crystal-agent guard <project_dir> --before phase5_seed",
            "phenix.refine scaled.mtz mr_model.pdb labels.name=\"IMEAN,SIGIMEAN\" xray_data.r_free_flags.generate=True strategy=individual_sites main.number_of_macro_cycles=1 output.prefix=seed",
            "phenix.refine <previous.mtz> <previous.pdb> labels.name=\"I-obs,SIGI-obs\" xray_data.r_free_flags.label=\"R-free-flags\" strategy=individual_sites+individual_adp output.prefix=phenix_r<N>",
            "ctruncate -mtzin scaled.mtz -mtzout ctruncate.mtz -colin \"/*/*/[IMEAN,SIGIMEAN]\"",
            "freerflag hklin ctruncate.mtz hklout ctruncate_free.mtz",
            "refmac5 xyzin <previous.pdb> xyzout refmac_r<N>.pdb hklin <previous.mtz> hklout refmac_r<N>.mtz",
            "modelcraft xray --data <best_mtz> --contents <fasta> --model <best_pdb> --cycles 10 --auto-stop-cycles 3",
            "phenix.cif_as_pdb modelcraft.cif",
            "refmac5 xyzin modelcraft.pdb xyzout modelcraft_r<N>.pdb hklin <best_mtz> hklout modelcraft_r<N>.mtz",
            "phenix.real_space_correlation model.pdb data.mtz detail=residue > rsc.log",
            "phenix.molprobity final_model.pdb final_data.mtz > molprobity_final.log 2>&1",
            "crystal-agent verify-steps <project_dir>",
            "crystal-agent guard <project_dir> --after phase5_seed",
        ],
        mandatory_rules=[
            "4+ Phenix rounds",
            "4+ Refmac rounds",
            "2 Refmac jelly ON rounds followed by 2+ jelly OFF rounds",
            "Continue winning branch until Rfree is flat for 2 rounds",
            "Every round uses the immediately preceding round model and companion MTZ",
            "Phenix round 2+ logs record INPUT_PDB/INPUT_MTZ from phenix_r<N-1>; Refmac round 3 records refmac_jelly_r2 and round 4+ records refmac_r<N-1>",
            "Modelcraft refinement is ALWAYS attempted but success not required: run modelcraft --cycles 10 --auto-stop-cycles 3 on best model and always write modelcraft_run.log; if it fails, ignore the result (acceptable outcome); if it succeeds, select best cycle, convert to PDB, run 2 refmac rounds, adopt only if Rfree improves",
            "TLS optimization compared and kept only if Rfree drops",
            "Waters fitted with ordered_solvent or Refmac solvent until plateau",
            "Model-region diagnosis flags B-factor > mean+2sigma and RSCC < 0.7",
        ],
        outputs=["seed_data.mtz", "phenix_r*.pdb", "refmac_r*.pdb", "modelcraft.json", "modelcraft_r*.pdb", "water_refine*.pdb", "*tls*.log", "rsc.log"],
        command_templates=[
            "phenix-seed",
            "phenix-iterative-refine",
            "ctruncate",
            "freerflag",
            "refmac-jelly",
            "refmac-free",
            "modelcraft-run",
            "modelcraft-refmac",
            "mtzdump-resolution",
            "rscc",
            "molprobity-final",
        ],
    ),
    "phase6": PhaseGuide(
        phase="phase6",
        title="Phase 6: Final Validation and Archive",
        code_calls=[
            "crystal-agent guard <project_dir> --before phase6_molprobity",
            "phenix.molprobity best_phenix.pdb best_phenix.mtz > molprobity_phenix.log 2>&1",
            "phenix.molprobity best_refmac.pdb best_refmac.mtz > molprobity_refmac.log 2>&1",
            "phenix.molprobity final_best.pdb final_best.mtz > molprobity_final.log 2>&1",
            "crystal-agent verify-steps <project_dir>",
            "crystal-agent guard <project_dir> --after phase6_molprobity",
        ],
        mandatory_rules=[
            "MolProbity Rfree is the reporting value",
            "Lowest Rfree wins",
            "Geometry and packing are diagnostic only",
            "Never compare Rfree across different FreeR flag sets as equivalent",
            "Create final/ directory with best PDB, MTZ, AIMLESS log, MR model, XDS results, comparison, MolProbity, and RSC log",
        ],
        outputs=["molprobity_final.log", "comparison.txt", "final/ directory"],
        command_templates=["molprobity-final", "mtzdump-resolution"],
    ),
}


def get_phase_guide(phase: str) -> PhaseGuide:
    key = phase.lower().replace("-", "_")
    if key not in PHASE_GUIDES:
        available = ", ".join(sorted(PHASE_GUIDES))
        raise KeyError(f"Unknown phase '{phase}'. Available phases: {available}")
    return PHASE_GUIDES[key]


def get_command_template(name: str) -> CommandTemplate:
    key = name.lower().replace("_", "-")
    if key not in COMMAND_TEMPLATES:
        available = ", ".join(sorted(COMMAND_TEMPLATES))
        raise KeyError(f"Unknown command template '{name}'. Available templates: {available}")
    return COMMAND_TEMPLATES[key]


def list_command_templates() -> list[str]:
    return sorted(COMMAND_TEMPLATES)


def get_naming_conventions() -> dict[str, str]:
    return dict(NAMING_CONVENTIONS)


def extract_placeholders(template: CommandTemplate) -> set[str]:
    return set(re.findall(r"<([A-Za-z0-9_.-]+)>", template.command))


def validate_template_parameters(
    template: CommandTemplate,
    values: dict[str, str],
) -> TemplateValidationResult:
    missing = sorted(name for name in extract_placeholders(template) if name not in values)
    return TemplateValidationResult(passed=not missing, missing=missing)


def _should_include_top_level(path: Path, root: Path) -> bool:
    relative = path.relative_to(root).as_posix()
    if path.name in BACKUP_EXCLUDE_NAMES:
        return False
    if path.suffix in BACKUP_EXCLUDE_SUFFIXES:
        return False
    if relative in BACKUP_INCLUDE_NAMES:
        return True
    if path.suffix in {".py", ".js", ".txt", ".md", ".toml"} and path.parent == root:
        return True
    return False


def collect_backup_targets(root: Path) -> list[Path]:
    """Return documentation/code targets to back up, excluding raw data/intermediates."""
    root = root.resolve()
    targets: list[Path] = []
    for path in sorted(root.iterdir()):
        if _should_include_top_level(path, root):
            targets.append(path)

    nested_targets = [
        root / "crystal-agent" / "src",
        root / "crystal-agent" / "skills",
        root / "crystal-agent" / "templates",
        root / "crystal-agent" / "pyproject.toml",
    ]
    for path in nested_targets:
        if path.exists() and path not in targets:
            targets.append(path)
    return targets


def _collect_markdown_text(root: Path) -> str:
    parts: list[str] = []
    agents = root / "AGENTS.md"
    if agents.exists():
        parts.append(agents.read_text(errors="ignore"))
    for directory in [root / "skills", root / "crystal-agent" / "skills", root / "docs"]:
        if directory.exists():
            for path in sorted(directory.rglob("*.md")):
                parts.append(path.read_text(errors="ignore"))
    return "\n".join(parts).lower()


def _source_file_text(root: Path, relative_path: str) -> str:
    path = root / "crystal-agent" / "src" / "crystal_agent" / relative_path
    if not path.exists():
        return ""
    return path.read_text(errors="ignore")


def audit_architecture(root: Path) -> ArchitectureAuditResult:
    """Check that mandatory crystallography guardrails still exist in docs/skills."""
    root = root.resolve()
    text = _collect_markdown_text(root)
    missing = []
    for rule, aliases in MANDATORY_RULES.items():
        if not any(alias.lower() in text for alias in aliases):
            missing.append(rule)
    for function_name, relative_path in REQUIRED_DECISION_WIRING.items():
        source_text = _source_file_text(root, relative_path)
        if function_name not in source_text:
            missing.append(f"{function_name} runtime wiring")
    for reference in REQUIRED_AGENT_DOC_REFERENCES:
        if reference.lower() not in text:
            missing.append(f"{reference} agent documentation")
    return ArchitectureAuditResult(passed=not missing, missing_rules=missing)

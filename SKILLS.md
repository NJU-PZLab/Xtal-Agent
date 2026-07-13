# Skills

## Scope Rule

This section includes all skills required by the workflow.

For publication, skills that were not originally stored in this repository but are actually required by the workflow are bundled into this package under `vendored_skills/`.

Important boundary:
- external crystallography software such as CCP4, Phenix, DIALS, XDS, and Coot is not classified as a skill
- that software belongs to the runtime dependency layer documented in `EXTERNAL_SOFTWARE.md` and `DEPLOYMENT.md`

## Repository Skills

These live under `skills/` and are named directly in `AGENTS.md` and related docs.

### Main workflow skills

- `skills/crystallography-mainline/SKILL.md`
- `skills/crystallography-phase1-xds-processing/SKILL.md`
- `skills/crystallography-phase2-aimless-validation/SKILL.md`
- `skills/crystallography-phase3-model-preparation/SKILL.md`
- `skills/crystallography-phase4-molecular-replacement/SKILL.md`
- `skills/crystallography-phase5-refinement/SKILL.md`
- `skills/crystallography-phase6-final-validation/SKILL.md`
- `skills/crystallography-ligand-generation/SKILL.md`

Why they belong:
- `AGENTS.md` uses them in the Skill Routing Table
- `docs/agent_architecture_coverage_audit.md` treats `skills/*.md` as task-specific workflow instructions
- `architecture.py` scans the `skills/` tree during architecture-audit text collection

## Legacy Compatibility Skills

- `skills/crystallography-raw-processing/SKILL.md`
- `skills/crystallography-aimless-validation/SKILL.md`
- `skills/crystallography-mr-refine/SKILL.md`

Why they still belong:
- they are still stored in the repo
- they remain part of the documented skill surface
- they explicitly serve as compatibility wrappers for older references

## Mirrored Phase Skill Documents

These are not top-level skill invocation files, but they are treated as part of the skill/documentation layer by the repository architecture.

- `xtal-agent/skills/phase1_data_processing.md`
- `xtal-agent/skills/phase2_scaling.md`
- `xtal-agent/skills/phase3_model_prep.md`
- `xtal-agent/skills/phase4_mr.md`
- `xtal-agent/skills/phase5_refinement.md`
- `xtal-agent/skills/phase5_low_res_refinement.md`
- `xtal-agent/skills/phase6_validation.md`

Why they belong:
- `docs/agent_architecture_coverage_audit.md` states these files mirror phase-level checklists for local reference
- `architecture.py` scans `xtal-agent/skills/` during architecture audit coverage collection

## Bundled Workflow Skills

These skills are required by the workflow and have been copied into this publication package under `vendored_skills/` because repository records show that they may supply actual scripts or helper code used during execution.

### `msa-generator`

Bundled location:
- `vendored_skills/msa-generator/`

Why it belongs:
- Phase 3 workflow requires MSA generation before AF2 or AF3 prediction

Repository evidence:
- `skills/crystallography-phase3-model-preparation/SKILL.md`
- dialogue records show actual calls to `run_msa.py`

### `af2-predictor`

Bundled location:
- `vendored_skills/af2-predictor/`

Why it belongs:
- ordinary single-chain model preparation uses AF2 workflow support

Repository evidence:
- `skills/crystallography-phase3-model-preparation/SKILL.md`
- repository dialogue records show actual calls to `run_af2.py`

### `af2-postprocess`

Bundled location:
- `vendored_skills/af2-postprocess/`

Why it belongs:
- available skill inventory and repository dialogue reference this as a companion AF2 workflow skill

### `alphafold3-predictor`

Bundled location:
- `vendored_skills/alphafold3-predictor/`

Why it belongs:
- Phase 3 workflow routes glycoprotein, nucleic-acid, ligand, and supported metalloprotein cases to AF3

Repository evidence:
- `AGENTS.md`
- `skills/crystallography-phase3-model-preparation/SKILL.md`
- dialogue records show actual calls to `run_af3.py`

### `writing-skills`

Bundled location:
- `vendored_skills/writing-skills/`

Why it belongs:
- `AGENTS.md` requires it for agent architecture edits

### `test-driven-development`

Bundled location:
- `vendored_skills/test-driven-development/`

Why it belongs:
- `AGENTS.md` requires it for agent architecture edits
- repository session records reference the corresponding superpowers skill

## Publication Rule For Skills

To keep the published structure consistent with the repository's own model:

- repository skill files are listed as repository contents
- workflow skills not originally stored in this repository are bundled into this package under `vendored_skills/`
- external crystallography software is documented separately as runtime tooling, not as a skill dependency

## Structure Summary

```text
.
├── skills/
│   ├── crystallography-mainline/
│   ├── crystallography-phase1-xds-processing/
│   ├── crystallography-phase2-aimless-validation/
│   ├── crystallography-phase3-model-preparation/
│   ├── crystallography-phase4-molecular-replacement/
│   ├── crystallography-phase5-refinement/
│   ├── crystallography-phase6-final-validation/
│   ├── crystallography-ligand-generation/
│   └── legacy compatibility wrappers
└── xtal-agent/skills/
    └── phase mirror markdown files
```

All workflow-required skills are documented here. Skills whose code was not originally stored in this repository are included in this package under `vendored_skills/` for publication completeness.

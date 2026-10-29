---
name: crystallography-mainline
description: Use when solving a crystal structure from raw images or validated MTZ data, or when the user mentions XDS, AIMLESS, Phaser, Matthews, molecular replacement, refinement, MolProbity, or final crystallographic validation.
---

# Crystallography Mainline

## Required First Calls

```bash
source xtal-agent/env/activate.sh
xtal-agent check-env
xtal-agent enforce-checkpoint <project_dir>
xtal-agent resume-barrier <project_dir>
```
xtal-agent validate-manifest <project_dir>/manifest.yaml
xtal-agent backup-targets <repo_root>
```

If the manifest lacks `workflow_mode: simple` or `workflow_mode: expert`, stop and ask the user to set it. Do not infer workflow mode.

If `workflow_mode: expert`, do not use autonomous `run-phase`. Before each guarded step, ask the user to approve that exact step, record it with `xtal-agent expert-approve <project_dir> <step_name> --reason "<why approved>"`, then use `guard --before`, run only the approved step, and close with `guard --after`. Do not continue if `verify-steps` reports an Expert Mode Audit failure.

## Inputs Gate

Required before processing:

| Input | Required detail |
|---|---|
| Diffraction data | raw image path or validated MTZ |
| Sequence | FASTA path |
| Workflow mode | explicit manifest value |
| Assembly type | monomer, homo-oligomer, hetero-oligomer, or protein-nucleic-acid complex |

Ask immediately for metal species/count, glycosylation sites/glycan composition, hetero-oligomer stoichiometry, nucleic-acid stoichiometry, or user-inspected `SPOT_RANGE` when the corresponding trigger appears.

## Phase Order

Run phases in order. Before each phase, call the code-backed guide.

| Phase | Skill | Code call |
|---|---|---|
| 1 Raw processing | `crystallography-phase1-xds-processing` | `xtal-agent phase-guide phase1` |
| 2 Scaling validation | `crystallography-phase2-aimless-validation` | `xtal-agent phase-guide phase2` |
| 3 Model prep | `crystallography-phase3-model-preparation` plus AF skills | `xtal-agent phase-guide phase3` |
| 4 MR | `crystallography-phase4-molecular-replacement` | `xtal-agent phase-guide phase4` |
| 5 Refinement | `crystallography-phase5-refinement` | `xtal-agent phase-guide phase5` |
| 6 Final validation | `crystallography-phase6-final-validation` | `xtal-agent phase-guide phase6` |

After every step:

```bash
xtal-agent verify-steps <project_dir>
```

If any check fails, stop and fix that step. Do not continue to the next phase.

For concrete operation syntax, call code templates. Do not write commands from memory:

```bash
xtal-agent command-template <operation>
xtal-agent list-command-templates
```

## Non-Negotiable Rules

- Never skip IDXREF.
- Never proceed past invalid AIMLESS thresholds.
- Never use invalid-resolution data downstream.
- Use explicit labels: Phaser `LABIN I=IMEAN SIGI=SIGIMEAN`; Phenix `labels.name="IMEAN,SIGIMEAN"` for intensities.
- Preserve unique output prefixes for every branch.
- Use the validated truncated MTZ for MR, FreeR generation, refinement, maps, and validation.
- For final reporting, lowest MolProbity recalculated Rfree wins.

## Completion Gate

Before reporting completion:

```bash
pytest -q
xtal-agent audit-architecture <repo_root>
xtal-agent verify-steps <project_dir>
```

If the project is not a code/docs edit, omit `pytest -q` but still run `verify-steps`.

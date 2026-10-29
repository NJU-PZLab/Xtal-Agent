---
name: crystallography-phase6-final-validation
description: Use when selecting the final model, running final MolProbity, comparing Rfree/Rwork, building comparison.txt, or assembling the final crystallographic archive.
---

# Crystallography Phase 6: Final Validation

## Required Code Call

```bash
source xtal-agent/env/activate.sh
xtal-agent enforce-checkpoint <project_dir>
xtal-agent phase-guide phase6
```

## Execution Gate

```bash
xtal-agent guard <project_dir> --before phase6_molprobity
xtal-agent verify-steps <project_dir>
xtal-agent guard <project_dir> --after phase6_molprobity
```

## Required Command Templates

```bash
xtal-agent command-template molprobity-final
xtal-agent command-template mtzdump-resolution
```

## Mandatory Rules

- Run MolProbity on best Phenix and best Refmac branches.
- Run final MolProbity on the final best model after waters and TLS.
- Use MolProbity recalculated Rfree for reporting.
- **Twin handling**: when xtriage detected twin laws, run MolProbity with
  `input.twin_law=<law> input.skip_twin_detection=True`. Both flags are
  required — without `skip_twin_detection=True`, MolProbity overwrites the
  law with `Auto` and silently drops it, so its R-free is computed without
  twinning and inflated (e.g. 0.29 vs true 0.23 at ~30% twins). Get the law
  from xtriage via `extract_twin_laws_from_xtriage()`.
- Lowest Rfree wins.
- Geometry, MolProbity score, packing, and map quality are diagnostic only.
- Never compare Rfree across different FreeR flag sets as equivalent.
- Build `comparison.txt` with Rwork, Rfree, clashscore, Rama outliers, and rotamer outliers.

## Final Archive Contents

`final/` must contain best PDB, companion MTZ, chosen AIMLESS log, MR model, Phaser `.sol`, Phaser log, XDS/DIALS reproducibility outputs, `comparison.txt`, final MolProbity log, and `rsc.log`.

---
name: crystallography-phase6-final-validation
description: Use when selecting the final model, running final MolProbity, comparing Rfree/Rwork, building comparison.txt, or assembling the final crystallographic archive.
---

# Crystallography Phase 6: Final Validation

## Required Code Call

```bash
source crystal-agent/env/activate.sh
crystal-agent enforce-checkpoint <project_dir>
crystal-agent phase-guide phase6
```

## Execution Gate

```bash
crystal-agent guard <project_dir> --before phase6_molprobity
crystal-agent verify-steps <project_dir>
crystal-agent guard <project_dir> --after phase6_molprobity
```

## Required Command Templates

```bash
crystal-agent command-template molprobity-final
crystal-agent command-template mtzdump-resolution
```

## Mandatory Rules

- Run MolProbity on best Phenix and best Refmac branches.
- Run final MolProbity on the final best model after waters and TLS.
- Use MolProbity recalculated Rfree for reporting.
- Lowest Rfree wins.
- Geometry, MolProbity score, packing, and map quality are diagnostic only.
- Never compare Rfree across different FreeR flag sets as equivalent.
- Build `comparison.txt` with Rwork, Rfree, clashscore, Rama outliers, and rotamer outliers.

## Final Archive Contents

`final/` must contain best PDB, companion MTZ, chosen AIMLESS log, MR model, Phaser `.sol`, Phaser log, XDS/DIALS reproducibility outputs, `comparison.txt`, final MolProbity log, and `rsc.log`.

# Phase 6: Final Validation and Archive

## Required Code Call

```bash
crystal-agent phase-guide phase6
```

## Required Command Templates

Use `crystal-agent command-template molprobity-final` and `mtzdump-resolution`. Do not invent final validation command syntax from memory.

Wrap the phase with `crystal-agent guard <project_dir> --before phase6_molprobity` and `--after phase6_molprobity`. Run `crystal-agent verify-steps <project_dir>` after every step.

## Mandatory Steps

1. Run MolProbity on the best Phenix model and companion MTZ.
2. Run MolProbity on the best Refmac model and companion MTZ.
3. Run final MolProbity on the final best model after waters and TLS.
4. Extract Rwork, Rfree, clashscore, Rama outliers, and rotamer outliers.
5. Build `comparison.txt`.
6. Select the model with the lowest MolProbity recalculated Rfree.
7. If comparing to a deposited structure, extract published Rwork/Rfree and calculate delta Rfree.
8. Create `final/` with best PDB, companion MTZ, chosen AIMLESS log, MR model, Phaser `.sol`, Phaser log, XDS/DIALS reproducibility outputs, `comparison.txt`, final MolProbity log, and `rsc.log`.

## Rules

- Lowest Rfree wins.
- Use MolProbity recalculated Rfree for reporting, not refinement-log Rfree.
- Geometry, MolProbity score, packing, and map quality are diagnostic only.
- Never compare Rfree across different FreeR flag sets as equivalent.

## Outputs

- `molprobity_final.log`
- `comparison.txt`
- complete `final/` directory

# Phase 4: Molecular Replacement

## Required Code Call

```bash
crystal-agent phase-guide phase4
```

## Required Command Templates

Use `crystal-agent command-template phaser-mr` and `xtriage`. Do not invent Phaser or xtriage command syntax from memory.

Wrap the phase with `crystal-agent guard <project_dir> --before phase4_phaser` and `--after phase4_phaser`. Run `crystal-agent verify-steps <project_dir>` after every step.

## Mandatory Steps

1. Confirm the input is the Phase 2 validated truncated MTZ.
2. Confirm `search_model.pdb` has pLDDT `< 80` residues and tags stripped.
3. Calculate Matthews coefficient with CCP4 `matthews_coef`, sort copies by V_M proximity to 2.2. Test the **top 3** highest-probability copies first. Use `matthews_copy_range()` from `crystal_agent.decision_engine`. If top-3 all fail, iterate remaining plausible copies.
4. **SGALTERNATIVE SELECT ALL is mandatory in every Phaser run.** Pointless SG confidence can be wrong (e.g. 4Z3U: P42212 at 77% was incorrect; P43212 found by Phaser). Do NOT use `SGALT BASE`. Always `SGALTERNATIVE SELECT ALL`.
5. Run Phaser with a unique `ROOT` and log for each copy number.
6. If MR exceeds 30 min (not instructed as full search) and the search model is a multi-domain protein: split into domain-level PDBs, rerun Phaser with each domain as a separate ENSEMBLE (e.g. `ENSEMBLE ec1 … ENSEMBLE ec2 … SEARCH ENSEMBLE ec1 NUM 2`).
7. Collect each result into `PhaserSweepResult` and call `select_best_copy_number()` to pick the winning copy number. The code enforces: strong with PAK=0 and all-placed > strong with PAK>0 > borderline > weak.
8. If no solution found or MR times out, first verify `SGALTERNATIVE SELECT ALL` is present. Then call `phaser_troubleshooting_order()` for the next diagnostic step.
9. Use explicit intensity labels: `LABIN I=IMEAN SIGI=SIGIMEAN`.
10. Extract TFZ, LLG, RFZ, PAK, all-components-placed status, and packing notes.
11. Prefer TFZ `> 8`, LLG `> 200`, PAK `= 0`, and all components placed.
12. If multiple copy numbers are strong, keep branches through identical short refinement comparisons.
13. If strong MR later gives `Rfree > 0.35`, run xtriage with explicit labels before autobuild or long refinement.

## Outputs

- `phaser_*.sol`
- `phaser_*.pdb`
- `phaser*.log`
- copy-number comparison table
- `xtriage.log` when triggered

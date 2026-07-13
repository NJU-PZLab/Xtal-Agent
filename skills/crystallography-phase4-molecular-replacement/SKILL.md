---
name: crystallography-phase4-molecular-replacement
description: Use when running Phaser, testing ASU copy numbers, interpreting TFZ/LLG/RFZ/PAK, checking packing, or deciding whether xtriage is required after MR.
---

# Crystallography Phase 4: Molecular Replacement

## Required Code Call

```bash
source crystal-agent/env/activate.sh
crystal-agent enforce-checkpoint <project_dir>
crystal-agent phase-guide phase4
```

## Execution Gate

```bash
crystal-agent guard <project_dir> --before phase4_phaser
crystal-agent verify-steps <project_dir>
crystal-agent guard <project_dir> --after phase4_phaser
```

## Required Command Templates

```bash
crystal-agent command-template phaser-mr
crystal-agent command-template xtriage
crystal-agent command-template twin-refine
```

## ASU Copy Number Workflow

This workflow is code-backed. Call the decision functions instead of improvising.

1. Run CCP4 `matthews_coef` (not phenix.matthews) with explicit cell, SG, and sequence MW. Use `matthews_copy_range(cell_volume, sequence_mw, sg_number)` from `crystal_agent.decision_engine` to get plausible copy numbers, sorted by probability (closest to optimal V_M=2.2).
2. Run Phaser for the **top 3** highest-probability copies first. If none succeed, iterate the remaining plausible copies. Use a unique `ROOT` per copy number. Do not skip any.
3. Collect each result into a `PhaserSweepResult`.
4. Call `select_best_copy_number(sweep)` to pick the best copy number. The code enforces: strong with PAK=0 and all-placed > strong with PAK>0 > borderline > weak. If no solution is found, call `phaser_troubleshooting_order()` to determine the next diagnostic step.
5. Use the winning copy number's solution for refinement. If multiple copy numbers are strong, keep both branches through identical short refinement comparisons.
6. Record a copy-number comparison table with TFZ, LLG, PAK, all-placed, and interpretation for each tested copy number.

## Outputs

`phaser_*.sol`, `phaser_*.pdb`, `phaser*.log`, copy-number comparison table, `xtriage.log` when triggered.

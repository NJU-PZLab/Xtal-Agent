---
name: crystallography-phase2-aimless-validation
description: Use when validating scaled MTZ data, AIMLESS logs, resolution cutoffs, shell statistics, pointless confidence, or alternative space groups before MR/refinement.
---

# Crystallography Phase 2: AIMLESS Validation

## Required Code Call

```bash
source crystal-agent/env/activate.sh
crystal-agent enforce-checkpoint <project_dir>
crystal-agent phase-guide phase2
```

## Execution Gate

```bash
crystal-agent guard <project_dir> --before phase2_pointless
crystal-agent verify-steps <project_dir>
crystal-agent guard <project_dir> --after phase2_pointless
```

## Required Command Templates

```bash
crystal-agent command-template pointless
crystal-agent command-template aimless-scale
crystal-agent command-template mtzdump-resolution
crystal-agent command-template xtriage
```

## Mandatory Thresholds

Outer shell, all must pass: `CC1/2 > 40`, `Mn(I/sd) > 1.6`, completeness `> 70%`, `Rmeas < 1.8`, `Rmerge < 2.0`.

Overall shell must pass `CC1/2 > 90`, completeness `> 90%`, and `Mn(I/sd) > 4`. Inner shell must pass `CC1/2 > 90` and `Mn(I/sd) > 4`.

Ignore outer-shell completeness only when total frames are fewer than 180.

## Mandatory Rules

- Never proceed to MR/refinement with invalid-resolution data.
- Keep unique filenames during resolution scans; never overwrite `scaled.mtz` in loops.
- Use `crystal-agent command-template mtzdump-resolution` after aimless, ctruncate, freerflag, and Phenix seed generation.
- Record strict validation markers in `aimless.log`: `AIMLESS_VALIDATION outer ...`, `AIMLESS_VALIDATION overall ...`, and `AIMLESS_VALIDATION inner ...`.
- Write the chosen cutoff to `validated_resolution.txt` and save the selected MTZ resolution check as `mtzdump_resolution.log`.
- If pointless confidence is low or absences are ambiguous, test plausible alternative SGs.
- If aimless passes all thresholds but the SG differs from the XDS/DIAILS SG: **do not accept either SG blindly.** First, re-run XDS with the new SG from aimless. If XDS succeeds, accept the new result. If XDS fails, keep both SG branches alive and compare through parallel MR + short refinement. See `sg_conflict_resolution` in `crystal_agent.decision_engine`.
- Carry the chosen `scaled.mtz` and matching `aimless.log` together downstream.

## Outputs

`point.mtz`, `point.log`, validated truncated `scaled.mtz`, matching `aimless.log`, recorded usable cutoff.

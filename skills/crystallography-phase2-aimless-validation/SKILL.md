---
name: crystallography-phase2-aimless-validation
description: Use when validating scaled MTZ data, AIMLESS logs, resolution cutoffs, shell statistics, pointless confidence, or alternative space groups before MR/refinement.
---

# Crystallography Phase 2: AIMLESS Validation

## Required Code Call

```bash
source xtal-agent/env/activate.sh
xtal-agent enforce-checkpoint <project_dir>
xtal-agent phase-guide phase2
```

## Execution Gate

```bash
xtal-agent guard <project_dir> --before phase2_pointless
xtal-agent verify-steps <project_dir>
xtal-agent guard <project_dir> --after phase2_pointless
```

## Required Command Templates

```bash
xtal-agent command-template pointless
xtal-agent command-template aimless-scale
xtal-agent command-template mtzdump-resolution
xtal-agent command-template xtriage
```

## Mandatory Thresholds

Outer shell, all must pass: `CC1/2 > 40`, `Mn(I/sd) > 1.6`, completeness `> 70%`, `Rmeas < 1.8`, `Rmerge < 2.0`.

The outer-shell `Mn(I/sd)` also has an **upper bound**: `Mn(I/sd) < 2.5`. When the outer shell is still this strong at the current cutoff, the resolution limit was set too low — data were cut prematurely. Return to Phase 1 (XDS/DIALS), increase the resolution limit, re-integrate, and re-run Phase 2. The code enforces this via `validate_resolution_from_aimless()` (`resolution_too_low`) and the `phase2_outer_margin` gate.

Overall shell must pass `CC1/2 > 90`, completeness `> 90%`, and `Mn(I/sd) > 4`. Inner shell must pass `CC1/2 > 90` and `Mn(I/sd) > 4`.

Ignore outer-shell completeness only when total frames are fewer than 180.

## Mandatory Rules

- Never proceed to MR/refinement with invalid-resolution data.
- Keep unique filenames during resolution scans; never overwrite `scaled.mtz` in loops.
- Use `xtal-agent command-template mtzdump-resolution` after aimless, ctruncate, freerflag, and Phenix seed generation.
- Record strict validation markers in `aimless.log`: `AIMLESS_VALIDATION outer ...`, `AIMLESS_VALIDATION overall ...`, and `AIMLESS_VALIDATION inner ...`.
- Write the chosen cutoff to `validated_resolution.txt` and save the selected MTZ resolution check as `mtzdump_resolution.log`.
- If pointless confidence is low or absences are ambiguous, test plausible alternative SGs.
- If aimless passes all thresholds but the SG differs from the XDS/DIAILS SG: **do not accept either SG blindly.** First, re-run XDS with the new SG from aimless. If XDS succeeds, accept the new result. If XDS fails, keep both SG branches alive and compare through parallel MR + short refinement. See `sg_conflict_resolution` in `xtal_agent.decision_engine`.
- Carry the chosen `scaled.mtz` and matching `aimless.log` together downstream.

## Outputs

`point.mtz`, `point.log`, validated truncated `scaled.mtz`, matching `aimless.log`, recorded usable cutoff.

# Phase 2: Scaling and Resolution Validation

## Required Code Call

```bash
crystal-agent phase-guide phase2
```

## Required Command Templates

Use `crystal-agent command-template pointless`, `aimless-scale`, `mtzdump-resolution`, and `xtriage`. Do not invent these commands from memory.

Wrap the phase with `crystal-agent guard <project_dir> --before phase2_pointless` and `--after phase2_pointless`. Run `crystal-agent verify-steps <project_dir>` after every step.

## Mandatory Steps

1. Convert XDS output to MTZ only when needed.
2. Run pointless, then aimless, preserving matching logs.
3. Use unique filenames during resolution scans; never overwrite `scaled.mtz` in a loop.
4. Extract outer-shell `CC1/2`, `Mn(I/sd)`, completeness, `Rmeas`, and `Rmerge`.
5. Apply all thresholds: `CC1/2 > 40`, `Mn(I/sd) > 1.6`, completeness `> 70%`, `Rmeas < 1.8`, `Rmerge < 2.0`.
6. Overall shell must pass `CC1/2 > 90`, completeness `> 90%`, and `Mn(I/sd) > 4`; inner shell must pass `CC1/2 > 90` and `Mn(I/sd) > 4`.
7. Ignore outer-shell completeness only when total frames are fewer than 180.
8. If any required threshold fails, return to Phase 1 and reprocess or truncate.
9. Record strict validation markers in `aimless.log`: `AIMLESS_VALIDATION outer ...`, `AIMLESS_VALIDATION overall ...`, and `AIMLESS_VALIDATION inner ...`.
10. Write the chosen cutoff to `validated_resolution.txt`.
11. Run `mtzdump hklin output.mtz <<< "" 2>&1 | grep "Resolution Range"` after aimless, ctruncate, freerflag, and Phenix seed generation, saving the selected check as `mtzdump_resolution.log`.
12. If pointless confidence is low or absences are ambiguous, test plausible alternative SGs.
13. If aimless passes all thresholds but SG differs from XDS/DIAILS: first re-run XDS with the new SG. Accept the new result if it succeeds; keep both branches through parallel MR + short refinement if it fails.
14. After aimless validates the resolution cutoff, write it to `validated_resolution.txt` and feed it back to `XDS.INP` `INCLUDE_RESOLUTION_RANGE`; re-run XDS to ensure CORRECT scaling uses only valid data.

## Low-Resolution Branch Trigger

After aimless validation, check `validated_resolution.txt`:
- **Resolution >= 3.6 Å**: the project enters the **low-resolution refinement branch** (see `phase5_low_res_refinement.md`).
  - *Simple mode*: auto-enter the low-resolution branch without prompting.
  - *Expert mode*: prompt the user whether to adopt the low-resolution refinement strategy.
- **Resolution < 3.6 Å**: continue with standard Phase 5 refinement.

## Outputs

- `point.mtz`
- `point.log`
- validated truncated `scaled.mtz`
- matching `aimless.log`
- recorded usable resolution cutoff
- `validated_resolution.txt`
- `mtzdump_resolution.log`

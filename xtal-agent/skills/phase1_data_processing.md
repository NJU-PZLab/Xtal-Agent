# Phase 1: XDS Processing

## Required Code Call

```bash
crystal-agent phase-guide phase1
```

## Required Command Templates

Use `crystal-agent command-template xds-generate-inp`, `xds-run`, `dials-import`, `dials-find-spots`, `dials-index`, `dials-integrate`, `dials-scale`, `dials-export-mtz`, and `xia2-fallback`. Do not invent these commands from memory.

Wrap the phase with `crystal-agent guard <project_dir> --before phase1_correct_lp` and `--after phase1_correct_lp`. Run `crystal-agent verify-steps <project_dir>` after every step.

## Mandatory Steps

1. Generate `XDS.INP` from CBF headers using `crystal-agent command-template xds-generate-inp`.
2. Run XDS round 1 with `SPACE_GROUP_NUMBER=0`; `JOB` must include `IDXREF`.
3. Extract SG, cell, per-shell `I/SIGMA`, and resolution estimate from `CORRECT.LP`.
4. Feed SG and cell back into `XDS.INP` and run XDS round 2; `JOB` must still include `IDXREF`.
5. Inspect `INTEGRATE.LP` mosaicity and `CORRECT.LP` SNR before changing parameters.
6. Push high-resolution cutoff by 0.2-0.3 A while outer-shell `I/SIGMA > 1.6`; step back when AIMLESS fails.
7. Shrink or shift `DATA_RANGE` only within initial frame coverage. Do not arbitrarily expand.
8. If IDXREF fails, use this exact fix order:
   - Adjust `MINIMUM_NUMBER_OF_PIXELS_IN_A_SPOT` (3-8)
   - Shift or decrease `SPOT_RANGE`
   - Try low-resolution limits between 20 and 50 A
   - Never remove IDXREF from JOB.
9. After round 2, inspect `INTEGRATE.LP` mosaicity. Select `DATA_RANGE` below median mosaicity; run parallel full vs optimal jobs; prefer the optimal solution.
10. If high-symmetry SG appears, test progressively narrower `DATA_RANGE` with SG=0 to check for twinning-inflated symmetry. Keep both hypotheses alive through scaling and refinement.
11. For radiation-damage or subset trimming, use `JOB=CORRECT` with existing `INTEGRATE.HKL` when IDXREF fails on the truncated range.

## Outputs

- `XDS.INP`
- `CORRECT.LP`
- `XDS_ASCII.HKL`
- `GXPARM.XDS`

If XDS and DIALS fail, run xia2 and validate any auto-processing result with pointless, aimless, and xtriage before using it.

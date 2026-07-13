---
name: crystallography-phase1-xds-processing
description: Use when processing raw diffraction images with XDS, generating XDS.INP, handling IDXREF, SPOT_RANGE, DATA_RANGE, CORRECT.LP, INTEGRATE.LP, or xia2 fallback.
---

# Crystallography Phase 1: XDS Processing

## Required Code Call

```bash
source crystal-agent/env/activate.sh
crystal-agent enforce-checkpoint <project_dir>
crystal-agent phase-guide phase1
```

Use this skill before any raw-image processing. Do not write a custom workflow from memory.

## Required Command Templates

Call these code-backed templates for concrete commands:

```bash
crystal-agent command-template xds-generate-inp
crystal-agent command-template xds-run
crystal-agent command-template dials-import
crystal-agent command-template dials-find-spots
crystal-agent command-template dials-index
crystal-agent command-template dials-integrate
crystal-agent command-template dials-scale
crystal-agent command-template dials-export-mtz
crystal-agent command-template xia2-fallback
```

## Execution Gate

```bash
crystal-agent guard <project_dir> --before phase1_correct_lp
crystal-agent verify-steps <project_dir>
crystal-agent guard <project_dir> --after phase1_correct_lp
```

Run `verify-steps` after every meaningful step. Stop on failure.

## Mandatory Rules

- Generate `XDS.INP` using `crystal-agent command-template xds-generate-inp`.
- XDS `JOB` must include `IDXREF`; never remove it.
- Round 1 uses `SPACE_GROUP_NUMBER=0`.
- Feed SG and cell from `CORRECT.LP` back into `XDS.INP` and rerun.
- Inspect `INTEGRATE.LP` mosaicity and `CORRECT.LP` SNR before parameter changes.
- Push resolution by 0.2-0.3 A while outer-shell `I/SIGMA > 1.6`; step back when AIMLESS fails.
- Shrink or shift `DATA_RANGE` only inside original frame coverage.
- If IDXREF fails with user-provided `SPOT_RANGE`, use this exact order of fixes:
  1. Adjust `MINIMUM_NUMBER_OF_PIXELS_IN_A_SPOT` (range 3-8) to reduce noise spots or capture more weak spots.
  2. If that fails, try shifting or decreasing `SPOT_RANGE`.
  3. Do NOT expand `SPOT_RANGE` beyond the user's estimate.
  4. In simple mode, stop before CORRECT-only mode. CORRECT-only (JOB=CORRECT reusing INTEGRATE.HKL) requires expert mode and user approval.
- If three attempts fail or IDXREF repeatedly fails, try low-resolution limits between 20 and 50 A. Never remove IDXREF.

### Mosaicity-Driven DATA_RANGE Optimization

After round 2 (or once mosaicity data is available):

1. Inspect `INTEGRATE.LP` for MOSAICITY variation across frames.
2. Select `DATA_RANGE` segments where MOSAICITY is below the median. Maximize the total amount of data included from below-median segments.
3. Run two parallel XDS jobs, both with the confirmed SG and cell, and same `SPOT_RANGE`:
   - One with default `DATA_RANGE` (full frame coverage)
   - One with the optimal `DATA_RANGE` determined from mosaicity analysis.
4. If the two runs produce different results, prefer the optimal `DATA_RANGE` solution.

### Twinning Detection via DATA_RANGE Scanning

When auto-index with full `DATA_RANGE` yields a high-symmetry space group, test whether that symmetry is inflated by twinning. The signature is: **narrower DATA_RANGE with SG=0 returns a lower-symmetry space group**.

1. Inspect `INTEGRATE.LP` for MOSAICITY variation across frames.
2. Generate a set of progressively narrower `DATA_RANGE` windows by shrinking from the ends where MOSAICITY is highest.
3. Run XDS with SG=0 on each subset and compare the indexed space group.
4. If subset indexing consistently yields a lower-symmetry SG, the full-range high symmetry may be a twinning artifact. Keep both hypotheses alive through scaling and refinement comparison.

### CORRECT-Only Mode for Trimmed Data

When trimming `DATA_RANGE` (e.g. radiation damage, subset analysis) and IDXREF fails despite known SG and cell, skip the IDXREF round by reusing the full-frame `INTEGRATE.HKL`:

```text
JOB= CORRECT
```

Write a minimal `XDS.INP` with `JOB=CORRECT`, the existing SG/cell, and the trimmed `DATA_RANGE`. XDS will reuse the existing `INTEGRATE.HKL`.

### Fallback

- If XDS fails or gives unstable indexing, use the DIALS templates in order. If XDS and DIALS fail, use `xia2-fallback` and validate any auto-processing result with pointless, aimless, and xtriage.

## Outputs

`XDS.INP`, `CORRECT.LP`, `XDS_ASCII.HKL`, `GXPARM.XDS`.

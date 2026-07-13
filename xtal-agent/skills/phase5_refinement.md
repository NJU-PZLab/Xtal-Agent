# Phase 5: Refinement and Post-Refinement

## Required Code Call

```bash
crystal-agent phase-guide phase5
```

## Required Command Templates

Use `crystal-agent command-template phenix-seed`, `phenix-iterative-refine`, `ctruncate`, `freerflag`, `refmac-jelly`, `refmac-free`, `rscc`, `molprobity-final`, and `mtzdump-resolution`.

Use `crystal-agent naming-guide` for canonical round file names and resume rules.

Wrap the phase with `crystal-agent guard <project_dir> --before phase5_seed` and `--after phase5_seed`. Run `crystal-agent verify-steps <project_dir>` after every step.

## Mandatory Minimum

1. Run a Phenix seed from the validated truncated MTZ and MR model.
2. Run 4+ Phenix rounds.
3. Run `ctruncate` and `freerflag` for the Refmac branch.
4. Run 4+ Refmac rounds.
5. Refmac rounds 1-2 use jelly-body restraints.
6. Refmac rounds 3+ run without jelly.
7. Continue the winning branch until Rfree is flat for 2 consecutive rounds.

Extra rounds are allowed. Fewer than the mandatory minimum rounds fail verification. If interrupted, resume with the next numeric round and do not renumber existing files.

### Modelcraft Refinement

After Phenix and Refmac refinement plateau, run modelcraft as a post-refinement optimization:

```bash
modelcraft xray --data <best_mtz> --contents <fasta> --model <best_pdb> --cycles 10 --auto-stop-cycles 3
```

1. Parse `modelcraft.json` for the `cycles` array; select the cycle with lowest `r_free`.
2. Convert the output `.cif` to PDB with `phenix.cif_as_pdb`.
3. Run 2 Refmac jelly-body rounds (`weight matrix 0.01`) with NCS if homo-oligomer.
4. Run 2 Refmac free rounds (no jelly-body).
5. Compare final Rfree to the pre-modelcraft best; discard modelcraft branch if Rfree did not improve.
6. Append `.modelcraft` suffix to output files (e.g. `modelcraft_r4.pdb`).

## Iteration Rule

Every refinement round must use the immediately preceding output PDB and companion MTZ. Only revert when the previous round increased Rfree relative to the round before it. Cross-software refinement uses the best model plus its companion MTZ, generates fresh FreeR flags only for the new branch, runs one stabilization round without ordered solvent, then continues.

Phenix round 2 and later logs must record `INPUT_PDB=phenix_r<N-1>` and `INPUT_MTZ=phenix_r<N-1>`. Refmac round 3 must record `INPUT_PDB=refmac_jelly_r2` and `INPUT_MTZ=refmac_jelly_r2`; Refmac round 4+ must record `INPUT_PDB=refmac_r<N-1>` and `INPUT_MTZ=refmac_r<N-1>` so `verify-steps` can reject skipped iteration.

## Mandatory Post-Refinement

1. Fit waters with `ordered_solvent=true` or Refmac `solvent yes` until water count and Rfree plateau.
2. Run TLS optimization and compare to non-TLS. Keep TLS only if Rfree drops.
3. Run real-space correlation using `crystal-agent command-template rscc`.
4. Flag residues with B-factor `> mean + 2 sigma` and RSCC `< 0.7`.
5. Do not auto-delete flagged residues; report loops and side-chain issues for COOT inspection.
6. Run final MolProbity after waters and TLS.
7. Verify Refmac overfitting: `Rfree - Rwork` should be 1% to 4%.

## Outputs

- `seed_data.mtz`
- `phenix_r*.pdb` and companion MTZ files
- `ctruncate.mtz`
- `ctruncate_free.mtz`
- `refmac_r*.pdb` and companion MTZ files
- `water_refine*.pdb`
- `*tls*.log`
- `rsc.log`

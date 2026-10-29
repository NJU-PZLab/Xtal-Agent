---
name: crystallography-phase5-refinement
description: Use when refining MR solutions with Phenix or Refmac, generating FreeR flags, running jelly-body refinement, continuing branches, fitting waters, TLS, RSCC, or MolProbity before final validation.
---

# Crystallography Phase 5: Refinement

## Required Code Call

```bash
source xtal-agent/env/activate.sh
xtal-agent enforce-checkpoint <project_dir>
xtal-agent phase-guide phase5
```

## Execution Gate

```bash
xtal-agent guard <project_dir> --before phase5_seed
xtal-agent verify-steps <project_dir>
xtal-agent guard <project_dir> --after phase5_seed
```

## Required Command Templates

```bash
xtal-agent command-template phenix-seed
xtal-agent command-template phenix-iterative-refine
xtal-agent command-template ctruncate
xtal-agent command-template freerflag
xtal-agent command-template refmac-jelly
xtal-agent command-template refmac-free
xtal-agent command-template rscc
xtal-agent command-template molprobity-final
xtal-agent command-template mtzdump-resolution
xtal-agent naming-guide
```

## Mandatory Minimum

- Run 4+ Phenix rounds.
- Run 4+ Refmac rounds.
- Refmac rounds 1-2 use jelly-body restraints.
- Refmac rounds 3+ run without jelly.
- Continue the winning branch until Rfree is flat for 2 consecutive rounds. `detect_rfree_plateau()` from `xtal_agent.decision_engine` enforces: if round N > round N-1 and round N+1 >= round N-1, plateau reached.
- If Rfree > 0.35 at plateau: first switch software (Phenix ↔ Refmac). If still > 0.35 after both tried, stop — the MR solution is likely wrong. `verify-steps` flags this via `_check_high_rfree_diagnosis`.
- Before starting refinement, check `xtriage.log` for twin laws with `extract_twin_laws_from_xtriage()`. If twin laws exist, try `command-template twin-refine` first before software switch.
- Extra rounds are allowed. Fewer than the mandatory minimum rounds fail verification. If interrupted, resume with the next numeric round and do not renumber existing files.

## Iteration Rule

Every refinement round must use the immediately preceding output PDB and companion MTZ. Cross-software refinement uses the best model plus its companion MTZ, generates fresh FreeR flags only for that new branch, runs one stabilization round without ordered solvent, then continues.

Phenix round 2 and later logs must record `INPUT_PDB=phenix_r<N-1>` and `INPUT_MTZ=phenix_r<N-1>`. Refmac round 3 must record `INPUT_PDB=refmac_jelly_r2` and `INPUT_MTZ=refmac_jelly_r2`; Refmac round 4+ must record `INPUT_PDB=refmac_r<N-1>` and `INPUT_MTZ=refmac_r<N-1>`. `verify-steps` rejects iteration if these markers are missing.

## Mandatory Post-Refinement

- Fit waters with `ordered_solvent=true` or Refmac `solvent yes` until water count and Rfree plateau.
- Run TLS optimization and keep TLS only if Rfree drops.
- Use `xtal-agent command-template rscc` for real-space correlation.
- Flag residues with B-factor `> mean + 2 sigma` and RSCC `< 0.7`.
- Do not auto-delete flagged residues; report them for COOT inspection.
- Run final MolProbity after waters and TLS.
- Verify Refmac overfitting: `Rfree - Rwork` should be 1% to 4%.

## Outputs

`seed_data.mtz`, `phenix_r*.pdb`, companion MTZ files, `ctruncate_free.mtz`, `refmac_r*.pdb`, `water_refine*.pdb`, `*tls*.log`, `rsc.log`.

## COOT post-refinement module (optional, enabled by default)

After the refinement R-free plateaus and the Modelcraft branch has been
adjudicated, invoke the bundled COOT module:

```bash
xtal-agent coot-optimize <project_dir>
```

or let Phase 5 call `run_coot_optimization()` automatically. The module is
implemented in `xtal_agent.coot_runner` and delegates to
`skills/crystallography-coot-refinement/scripts/run_strategy.py` in headless
COOT. It:

1. identifies rotamer outliers and unmodelled solvent density with
   `phenix.molprobity`;
2. corrects rotamers, performs density-guided real-space fitting, and adds
   ordered waters with scripted COOT sessions;
3. re-refines and re-validates the model.

Acceptance: keep the COOT model only when R-free does not increase and
MolProbity geometry improves; otherwise keep the pre-COOT model and record
`coot_strategy/coot_result.json` with the rejection reason.

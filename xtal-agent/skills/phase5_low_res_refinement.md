# Phase 5-LR: Low-Resolution Refinement (≥ 3.6 Å)

## Trigger

This skill applies when the aimless-validated resolution is **≥ 3.6 Å**.

- **Simple mode**: automatically enters this branch after Phase 2.
- **Expert mode**: prompts user whether to adopt low-resolution refinement strategy.

Use `crystal-agent phase-guide phase5_lowres` for the code-backed guide.

## Required Command Templates

Use `crystal-agent command-template phenix-seed`, `phenix-iterative-refine`, `ctruncate`, `freerflag`, `refmac-jelly`, `refmac-free`, `modelcraft-run`, `modelcraft-refmac`, `rscc`, `molprobity-final`.

## Mandatory Steps

### 1. Rigid Body Optimization

```bash
phenix.refine <mr_model>.pdb <data>.mtz strategy=rigid_body main.number_of_macro_cycles=5 output.prefix=phenix_rb
```

Record Rfree after rigid body.

### 2. Phenix Grouped ADP x4

```bash
phenix.refine <previous>.pdb <previous>.mtz strategy=group_adp optimize_xyz_weight=True optimize_adp_weight=True output.prefix=phenix_r<N>
```

Run 4 iterative rounds, each using the prior round's output.

**Gate**: If Phenix Rfree improves over rigid body at the end of 4 rounds, continue to iterative Refmac. If it does not improve (plateau or worse), skip Phenix and start Refmac directly from the MR model.

### 3. Refmac Jelly-Body + Free

Run 2 rounds of Refmac jelly-body then 2 rounds of Refmac free:

```bash
# Jelly rounds
refmac5 xyzin <input>.pdb xyzout refmac_jelly_r<N>.pdb hklin <input>.mtz hklout refmac_jelly_r<N>.mtz << 'EOF'
make hydrogen no
labin FP=F SIGFP=SIGF FREE=FreeR_flag
refi type REST resi MLKF meth CGMAT bref ISOT
ncyc 50
external restraint jelly
END
EOF

# Free rounds
refmac5 xyzin <input>.pdb xyzout refmac_r<N>.pdb hklin <input>.mtz hklout refmac_r<N>.mtz << 'EOF'
make hydrogen no
labin FP=F SIGFP=SIGF FREE=FreeR_flag
refi type REST resi MLKF meth CGMAT bref ISOT
ncyc 50
END
EOF
```

Iterate: jelly_r1 → jelly_r2 → free_r3 → free_r4, each using prior output.

### 4. Modelcraft Model Completion (if Rfree ≤ 0.35)

If final Refmac Rfree ≤ 0.35:

```bash
modelcraft xray --data <best_mtz> --contents <fasta> --model <best_pdb> --cycles 10 --auto-stop-cycles 3
```

- Parse `modelcraft/modelcraft.json` for the cycle with lowest `r_free`.
- Convert `modelcraft.cif` to PDB with `phenix.cif_as_pdb`.

### 5. Cleanup: RSC + Chain/Residue Pruning

On the modelcraft output (or best Refmac model if modelcraft skipped):

1. Delete garbage chains (non-A chains with only UNK/X residues or very few residues).
2. Keep chain A, including UNK residues (they indicate backbone traced but missing side chains).
3. Generate RSCC: `phenix.real_space_correlation <model>.pdb <mtz> detail=residue > rsc.log`
4. Flag residues with RSCC < 0.7 for manual inspection.

### 6. Optimize: Phenix Secondary Structure + Rama + Rotamer

If user approves, run:

```bash
phenix.refine <model>.pdb <model>.mtz \
  strategy=individual_sites \
  rotamer_restraints=true \
  secondary_structure.enabled=true \
  allow_polymer_cross_special_position=True \
  output.prefix=final_geom
```

### 7. Model Selection and MolProbity

Present comparison table (Rfree vs geometry). User selects final model.

Run MolProbity on the archived structure:

```bash
phenix.molprobity <final>.pdb > molprobity.log
```

Archive to `final/`:
- best PDB + companion MTZ
- aimless.log, validated_resolution.txt
- Phaser .sol + .log
- XDS_ASCII.HKL, XDS.INP
- molprobity.log
- modelcraft output (if used)
- `manual_notes.md` listing UNK residues requiring manual building

## Outputs

- `phenix_rb_001.pdb`, `phenix_rb_001.mtz`
- `phenix_r{1..4}_001.pdb`, phenix MTZ files
- `refmac_jelly_r{1,2}.pdb`, refmac MTZ files
- `refmac_r{3,4}.pdb`, refmac MTZ files
- `modelcraft/` directory (if Rfree ≤ 0.35)
- `rsc.log`
- `molprobity.log`
- `final/` archived outputs

## Notes

- Do not add water molecules at low resolution.
- Refmac lacks explicit rotamer restraint; geometry optimization requires Phenix.
- Rfree and geometry quality have a trade-off at low resolution; prioritize Rfree.
- N-terminal and C-terminal regions often have poor density at low resolution — expect UNK residues.

# Phase 3: Model Preparation

## Required Code Call

```bash
crystal-agent phase-guide phase3
```

## Required Command Templates

Use `crystal-agent command-template matthews` and `ligand-elbow` where applicable. Use AF skills for MSA/AF2/AF3 command syntax.

Wrap the phase with `crystal-agent guard <project_dir> --before phase3_msa` and `--after phase3_msa`. Run `crystal-agent verify-steps <project_dir>` after every step.

## Mandatory Decisions

- Ordinary single-chain non-metallo/non-glyco/non-nucleic-acid protein: AF2/ColabFold.
- Glycoprotein: AF3 with glycan CCD codes and covalent bonds; ask for sites and composition.
- Protein-DNA/RNA complex: AF3 complex prediction; use the full complex for MR.
- Supported metalloprotein ion: AF3 after user confirms metal species and count.
- Unsupported ion such as Mo, W, V, Te, Pt, Hg, Au, Ag, Cd, Pb, As, or U: simple-mode hard stop.
- Hetero-oligomer without nucleic acid: predict distinct protein chains separately.

## Mandatory Steps

1. Generate `.a3m` files for each protein chain using `msa-generator`.
2. Run `af2-predictor` or `alphafold3-predictor` according to the decision table.
3. Verify `.done.txt` and top-ranked model.
4. Convert AF3 CIF to PDB when needed.
5. Strip pLDDT `< 80` residues.
6. Strip terminal expression/purification tags, including N-terminal `MGS`/`MGSS` and C-terminal His-tags.
7. Save cleaned model as `search_model.pdb`.
8. Calculate Matthews coefficient using CCP4 `matthews_coef` (not phenix.matthews) with explicit CELL, SYMM, MOLW, AUTO before MR.

## Outputs

- `.a3m` files
- prediction `.done.txt`
- top-ranked model
- `search_model.pdb`
- `matthews.log`

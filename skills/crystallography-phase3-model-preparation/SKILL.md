---
name: crystallography-phase3-model-preparation
description: Use when preparing MR search models, generating MSAs, choosing AF2 versus AF3, handling glycoproteins, metalloproteins, nucleic-acid complexes, pLDDT trimming, tags, or Matthews estimates.
---

# Crystallography Phase 3: Model Preparation

## Required Code Call

```bash
source crystal-agent/env/activate.sh
crystal-agent enforce-checkpoint <project_dir>
crystal-agent phase-guide phase3
```

## Execution Gate

```bash
crystal-agent guard <project_dir> --before phase3_msa
crystal-agent verify-steps <project_dir>
crystal-agent guard <project_dir> --after phase3_msa
```

## Required Command Templates

```bash
crystal-agent command-template matthews
crystal-agent command-template ligand-elbow
```

Use AF skill code for MSA/AF2/AF3 execution. Do not invent MSA, AF2, or AF3 command lines when the corresponding AF skill provides them.

## Prediction Decision

- Ordinary single-chain non-metallo/non-glyco/non-nucleic-acid protein: use AF2/ColabFold.
- Glycoprotein: use AF3 with glycan CCD codes and covalent bonds; ask for sites and composition.
- Protein-DNA/RNA complex: use AF3 complex prediction and the full predicted complex for MR.
- Supported metalloprotein ion: use AF3 after user confirms metal species and count.
- Protein-ligand complex (small molecule): use AF3 with `--ligands` or `--ligands-smiles`. If ligand pLDDT is reliable, include the ligand coordinates in the MR search model.
- Unsupported ion such as Mo, W, V, Te, Pt, Hg, Au, Ag, Cd, Pb, As, or U: simple-mode hard stop.
- Hetero-oligomer without nucleic acid: predict distinct protein chains separately.

## Mandatory Rules

- Generate `.a3m` MSA files for each protein chain.
- Verify `.done.txt` and top-ranked model.
- Convert AF3 CIF to PDB when needed.
- Strip residues with pLDDT `< 80`.
- Strip N-terminal `MGS`/`MGSS` and C-terminal His-tags.
- Save cleaned model as `search_model.pdb`.
- Calculate Matthews coefficient using CCP4 `matthews_coef` (not phenix.matthews) with explicit CELL, SYMM, MOLW, AUTO before MR.

## Outputs

`.a3m` files, prediction `.done.txt`, top-ranked model, `search_model.pdb`, `matthews.log`.

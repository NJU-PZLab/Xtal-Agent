---
name: crystallography-ligand-generation
description: Use when a ligand, cofactor, inhibitor, substrate, product, or restraint dictionary is needed from chemical identity for crystallographic modeling or refinement.
---

# Crystallography Ligand Generation

## Required Inputs

- PubChem-verifiable chemical identity: SMILES, CAS, or IUPAC name
- three-letter ligand code
- target protonation/tautomer state if known

## Mandatory Steps

1. Obtain PubChem-verified SMILES. Never guess SMILES from memory.

```bash
curl -s "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/<name>/property/CanonicalSMILES/TXT"
```

2. Generate coordinates and restraints with the code-backed template.

```bash
crystal-agent command-template ligand-elbow
```

3. Verify atom count, formal charge, stereochemistry, and chiral centers.
4. Do not extract ligand coordinates from the target deposited PDB. That creates coordinate bias.
5. If CCP4 tools need a different CIF dialect, generate an additional dictionary with `acedrg` or `grade` and document which dictionary was used.

## Outputs

- `<prefix>.pdb`
- `<prefix>.cif`
- verification note containing source identity, SMILES, atom count, charge, stereochemistry check, and limitations

## Limitations

`phenix.elbow` cannot guarantee the correct tautomer or protonation state. Metal-coordinating ligands need extra coordination-geometry validation.

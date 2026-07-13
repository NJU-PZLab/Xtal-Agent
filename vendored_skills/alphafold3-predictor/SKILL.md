---
name: alphafold3-predictor
description: Runs AlphaFold3 structure prediction. Use after msa-generator skill completes MSA generation, or with pre-built AF3 JSON files.
---

# AF3 Predictor

Run AlphaFold3 structure prediction with automatic JSON generation and multi-GPU support. **Run msa-generator first** to generate MSA files.

## Input Modes

### Mode 1: MSA + Entity Specs (Recommended)

Simplest interface. Specify chains, RNA, DNA, ligands, and MSA directory:

```bash
# Monomer
python vendored_skills/alphafold3-predictor/scripts/run_af3.py \
  --msa-dir MSA --chains 'A=MAKET...' --output-dir AF3

# Dimer + 4 calcium ions
python vendored_skills/alphafold3-predictor/scripts/run_af3.py \
  --msa-dir MSA --chains 'A*2=MAKET...' --ligands 'C*4:CA' --output-dir AF3

# Protein-RNA complex
python vendored_skills/alphafold3-predictor/scripts/run_af3.py \
  --msa-dir MSA --chains 'A=MAKET...' --rna 'B=AGCUAGCU' --output-dir AF3

# Protein-DNA complex + SMILES ligand
python vendored_skills/alphafold3-predictor/scripts/run_af3.py \
  --msa-dir MSA --chains 'A=MAKET...' --dna 'C=GACCTCT' \
  --ligands-smiles 'D:CC(=O)O' --output-dir AF3

# Protein + custom CCD ligand with covalent bond
python vendored_skills/alphafold3-predictor/scripts/run_af3.py \
  --msa-dir MSA --chains 'A=MAKET...' --ligands 'C:MY-LIG' \
  --bonds 'A:145:SG-C:1:C04' --user-ccd my_ligand.cif --output-dir AF3
```

### Mode 2: Pre-built JSON Directory

```bash
python vendored_skills/alphafold3-predictor/scripts/run_af3.py \
  --json-dir AF3_json --output-dir AF3 --gpus 0,1,2,3
```

### Mode 3: Single JSON File

```bash
python vendored_skills/alphafold3-predictor/scripts/run_af3.py \
  --json-path fold_input.json --output-dir AF3
```

## Chain Specification (Protein)

| Format | Meaning | Example |
|--------|---------|---------|
| `A=SEQ` | Single chain A | `A=MAKET...` |
| `A*2=SEQ` | Dimer (chains A,B) | `A*2=MAKET...` |
| `A*3=SEQ` | Trimer (chains A,B,C) | `A*3=MAKET...` |
| `A=SEQ1;B=SEQ2` | Heterodimer | `A=SEQ1;B=SEQ2` |

Multiple chains are separated by `;`:
```bash
--chains 'A=SEQ1;B=SEQ2;C*2=SEQ3'
```

## RNA & DNA Chains

### In --chains (with type prefix)
```bash
--chains 'A=MAKET...;rna:B=AGCUAGCU;dna:C=GACCTCT'
```

### Shorthand flags
```bash
--rna 'B=AGCUAGCU'          # Single RNA chain
--rna 'B=AGCU;C=GGCC'       # Two RNA chains
--rna 'B*2=AGCU'            # RNA homodimer
--dna 'C=GACCTCT'           # Single DNA chain
--dna 'C=GACT;D=TTAC'       # Two DNA chains
```

**Sequence validation**: RNA accepts only `A,C,G,U`; DNA accepts only `A,C,G,T`.

**MSA**: RNA supports `unpairedMsa`/`unpairedMsaPath`; DNA has no MSA support.

## Ligand Specification

### CCD Codes
| Format | Meaning | Example |
|--------|---------|---------|
| `C:CA` | One calcium ion | `C:CA` |
| `C*4:CA` | Four calcium ions | `C*4:CA` |
| `C:CA,D:ATP` | Calcium + ATP | `C:CA,D:ATP` |

Common CCD codes: `CA` (calcium), `ZN` (zinc), `MG` (magnesium), `ATP`, `HEM` (heme), `NAG` (N-acetylglucosamine)

Auto-detection: values ≤ 3 uppercase chars are treated as CCD codes.

### SMILES
```bash
--ligands-smiles 'C:CC(=O)O'                    # Acetic acid
--ligands-smiles 'C:CC(=O)O,D:CCO'              # Two SMILES ligands
```

**Note**: SMILES ligands **cannot** participate in covalent bonds. Use user CCD instead.

## Covalent Bonds

Format: `CHAIN1:RES1:ATOM1-CHAIN2:RES2:ATOM2`

```bash
# Single bond: protein CYS to ligand
--bonds 'A:145:SG-C:1:C04'

# Multiple bonds (comma-separated)
--bonds 'A:145:SG-C:1:C04,A:100:NZ-C:2:C01'

# Glycan bonds
--bonds 'A:58:ND2-B:1:O4,B:1:C1-B:2:O4'
```

**Rules**:
- Residue IDs are 1-based integers
- For single-residue ligands, residue ID is always `1`
- SMILES ligands cannot be used in bonds (use user CCD instead)

## User CCD

For custom ligands not in the standard CCD, provide a mmCIF file:

```bash
--user-ccd my_ligand.cif --ligands 'C:MY-LIG'
```

The mmCIF file must follow the CCD format with `_chem_comp`, `_chem_comp_atom`, and `_chem_comp_bond` sections. The `_chem_comp.id` must match the CCD code used in `--ligands`.

## Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `--msa-dir` | - | MSA directory from msa-generator |
| `--chains` | - | Protein/RNA/DNA chain specs |
| `--rna` | - | RNA chain shorthand |
| `--dna` | - | DNA chain shorthand |
| `--ligands` | - | CCD ligand specs, e.g. `C*4:CA` |
| `--ligands-smiles` | - | SMILES ligand specs |
| `--bonds` | - | Covalent bond specs |
| `--user-ccd` | - | Path to user CCD mmCIF file |
| `--seeds` | `1` | Comma-separated model seeds |
| `--output-dir` | `AF3` | Output directory |
| `--gpus` | `0` | Comma-separated GPU IDs |
| `--name` | auto | Job name |
| `--num-recycles` | `10` | Number of recycles |
| `--num-samples` | `5` | Diffusion samples per seed |
| `--flash-attention` | `triton` | triton/cudnn/xla |
| `--save-embeddings` | off | Save embeddings |
| `--save-distogram` | off | Save distogram |

## Complete Workflow

```bash
# 1. Generate MSA
python vendored_skills/msa-generator/scripts/run_msa.py \
  --input inputs.csv --output-dir MSA

# 2. Run AF3 prediction
python vendored_skills/alphafold3-predictor/scripts/run_af3.py \
  --msa-dir MSA --chains 'A*2=MAKET...' --ligands 'C*4:CA' --output-dir AF3
```

## Multi-GPU Parallel Processing

```bash
# Parallel: batch processing with 3 GPUs
python vendored_skills/alphafold3-predictor/scripts/run_af3.py \
  --json-dir json_batch --output-dir AF3 --gpus 1,2,3

# Sequential: single GPU with many samples
python vendored_skills/alphafold3-predictor/scripts/run_af3.py \
  --msa-dir MSA --chains 'A=SEQ' --output-dir AF3 --gpus 1 --num-samples 10
```

Performance (RTX 4090, 123-aa protein): 3 jobs on 3 GPUs = 2.5x speedup, 83% efficiency.

## Output

```
AF3/
├── AF3_inputs/                    # Generated JSON files
├── job_name/                      # Per-job results
│   ├── job_name_model.cif         # Top-ranked structure
│   ├── job_name_summary_confidences.json
│   ├── job_name_confidences.json
│   ├── job_name_ranking_scores.csv
│   └── seed-*_sample-*/           # Per-seed/sample results
```

Key confidence metrics: `ptm` (0-1, overall), `iptm` (0-1, interface), `ranking_score` (higher=better).

**Note**: Single-chain proteins do not output `ptm`/`iptm` (only `pLDDT` and `ranking_score`).

## Notes & Limitations

1. **MSA directory**: Use absolute paths or run from correct directory
2. **Single-chain metrics**: No pTM/ipTM for monomers (use pLDDT + ranking_score)
3. **DNA chains**: No MSA support (AF3 limitation)
4. **SMILES ligands**: Cannot participate in covalent bonds (use user CCD instead)
5. **User CCD IDs**: Avoid underscores in `_chem_comp.id` (use hyphens)
6. **GPU memory**: RTX 4090 (49GB) recommended for large complexes
7. **Multi-GPU**: Use absolute paths in parallel mode

Bundled location for this skill: vendored_skills/alphafold3-predictor
Relative paths in this bundled copy are relative to the vendored skill directory.

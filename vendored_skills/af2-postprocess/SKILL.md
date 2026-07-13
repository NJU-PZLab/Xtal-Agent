---
name: af2-postprocess
description: Post-process AlphaFold2 prediction results. Extract sequences, pLDDT, pTM, iptm, RMSD vs template, and other metrics. Use after af2-predictor completes.
---

# AF2 Post-Process

Extract and summarize AlphaFold2 prediction results including confidence scores, sequences, and RMSD comparisons.

## Usage

### Step 1: Ensure AF2 Results Exist
Results should be in `AF2/AF2_results/` with `*rank_001*.pdb` files.

### Step 2: Run Post-Processing

```bash
cd AF2
python vendored_skills/af2-postprocess/scripts/af2_summary.py \
  --af2-dir . \
  --results-dir AF2_results \
  --template ../input/1TIT.pdb \
  --output results.csv
```

## Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `--af2-dir` | required | Base directory for AF2 results |
| `--results-dir` | `AF2_DIR/AF2_results` | Directory containing PDB/JSON files |
| `--template` | None | Reference PDB for RMSD calculation |
| `--output` | `results.csv` | Output CSV filename |
| `--pdb-dir` | `AF2_DIR/pdb_structure` | Output directory for extracted PDBs |
| `--pdb-pattern` | `*rank_001*.pdb` | Glob pattern for PDB files |

## Output

Generates `results.csv` with columns:

| Column | Description |
|--------|-------------|
| `name` | Design name |
| `sequence` | Protein sequence |
| `plddt` | Mean pLDDT confidence score |
| `ptm` | Per-token TM-score (if available) |
| `iptm` | Interface pTM-score (for complexes) |
| `rmsd` | RMSD vs template (if provided) |
| `hydrophobicity` | Mean hydrophobicity (Kyte-Doolittle) |
| `num_residues` | Number of residues |

## Dependencies

Required packages:
- MDAnalysis
- pandas
- numpy
- Bio.SeqUtils

Install with:
```bash
pip install MDAnalysis pandas numpy biopython
```

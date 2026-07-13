---
name: msa-generator
description: Runs colabfold_search to generate MSAs for AlphaFold2/3. Use when you need to create Multiple Sequence Alignments from input sequences for protein structure prediction.
---

# MSA Generator

Generate Multiple Sequence Alignments (MSA) using colabfold_search for AlphaFold2/3 structure prediction.

## Input Format

Create an `inputs.csv` file with `id,sequence` format (header required):

```csv
id,sequence
1TIT_1,ATTVTEQAKGQTATTGATLTFTVTLTNSGATGTWTINGTTTTPGARVTLTYTGATWTLTITGATAADTGTVTFTAGTATATGTVTGVAA
1TIT_2,AQTCTTQLTGVTVTTGGTATFTAQLTSPGFEGTLSVNGTTPTAGARLTLTQSGSSVTLTITGATTADTGTVTLTAGSCTATGTLTATPP
```

## Usage

### Run MSA Search

```bash
python vendored_skills/msa-generator/scripts/run_msa.py \
  --input inputs.csv \
  --output-dir MSA \
  --threads 64 \
  --gpus 0,1,2,3,4,5,6
```

### Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `--input` | `inputs.csv` | Input CSV file with `id,sequence` format |
| `--output-dir` | `MSA` | Output directory for MSA (.a3m) files |
| `--dbbase` | `MSA_DBBASE` env var | Database base directory |
| `--threads` | `64` | Number of threads to use |
| `--gpus` | `0,1,2,3,4,5,6` | Comma-separated GPU IDs |
| `--gpu` | `1` | Whether to use GPU (1=yes, 0=no) |

### Step 2: Check Output

After successful completion, you will see:

```
[SUCCESS] Generated 10 MSA files:
  - 1TIT_1.a3m
  - 1TIT_2.a3m
  ...
```

## Complete Workflow Example

```bash
# 1. Generate MSA for designs
python vendored_skills/msa-generator/scripts/run_msa.py \
  --input inputs.csv \
  --output-dir MSA

# 2. Run AF2 prediction (see af2-predictor skill)
python vendored_skills/af2-predictor/scripts/run_af2.py \
  --input-dir MSA \
  --output-dir AF2
```

## Troubleshooting

### "No .a3m files found"
- Verify your input CSV has the correct format: `id,sequence` (header required)
- Check that the input file path is correct
- Ensure colabfold_search completed successfully

### "Database not found"
- Verify the `--dbbase` path contains `uniref30_2302_db` and `colabfold_envdb_202108_db`

Bundled location for this skill: vendored_skills/msa-generator
Relative paths in this bundled copy are relative to the vendored skill directory.

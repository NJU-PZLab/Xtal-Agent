---
name: af2-predictor
description: Runs AlphaFold2 structure prediction using colabfold_batch. Use after msa-generator skill completes MSA generation.
---

# AF2 Predictor

Run AlphaFold2 structure prediction using colabfold_batch. **Run msa-generator first** to generate MSA files.

## Input

A directory containing `.a3m` MSA files from msa-generator.

## Usage

### Run AF2 Prediction

```bash
python vendored_skills/af2-predictor/scripts/run_af2.py \
  --input-dir MSA \
  --output-dir AF2 \
  --gpus 0,1,2,3,4,5,6 \
  --af2-data "$AF2_DATA_DIR"
```

### Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `--input-dir` | required | Directory containing MSA (.a3m) files |
| `--output-dir` | `AF2` | Output directory for AF2 results |
| `--gpus` | `0,1,2,3,4,5,6` | Comma-separated GPU IDs |
| `--af2-data` | `AF2_DATA_DIR` env var | AlphaFold2 data directory |

## How It Works

1. Distributes MSA files evenly across specified GPUs
2. Each GPU runs `colabfold_batch` once, processing all its assigned MSAs
3. All results are written to the output directory

## Output Structure

```
AF2/
├── *.pdb                    # Predicted structures
├── AF2_inputs/              # Per-GPU input MSAs
└── AF2_results/            # (may contain additional outputs)
```

## Complete Workflow Example

```bash
# 1. Generate MSA
python vendored_skills/msa-generator/scripts/run_msa.py \
  --input inputs.csv \
  --output-dir MSA

# 2. Run AF2 prediction
python vendored_skills/af2-predictor/scripts/run_af2.py \
  --input-dir MSA \
  --output-dir AF2
```

## Troubleshooting

### "No .a3m files found"
- Verify the input directory contains `.a3m` files
- Check the input directory path is correct

### "AF2 data directory not found"
- Verify `--af2-data` points to a valid AlphaFold2 database directory

Bundled location for this skill: vendored_skills/af2-predictor
Relative paths in this bundled copy are relative to the vendored skill directory.

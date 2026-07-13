#!/usr/bin/env python3
import os
import subprocess
import argparse
import multiprocessing as mp
import shutil
import sys
from pathlib import Path


DEFAULT_COLABFOLD_BATCH = os.environ.get("COLABFOLD_BATCH") or "colabfold_batch"
DEFAULT_AF2_DATA = os.environ.get("AF2_DATA_DIR") or ""

def run_af2(gpu_id, a3m_dir, output_path, af2_data_dir):
    """Run AlphaFold2 on a single GPU."""
    env = os.environ.copy()
    env["CUDA_VISIBLE_DEVICES"] = str(gpu_id)
    env["MPLBACKEND"] = 'agg'
    fold_run_env = DEFAULT_COLABFOLD_BATCH

    result = subprocess.run(
        [fold_run_env,
         str(a3m_dir), str(output_path),
         '--data', af2_data_dir],
        env=env,
        capture_output=True,
        text=True
    )
    return (gpu_id, result.returncode, result.stdout, result.stderr)

def main():
    parser = argparse.ArgumentParser(
        description="Run AlphaFold2 structure prediction using colabfold_batch",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run_af2.py --input-dir MSA --output-dir AF2
  python run_af2.py --input-dir MSA --output-dir AF2 --gpus 0,1,2,3
        """
    )
    parser.add_argument("--input-dir", required=True,
                        help="Input directory containing MSA (.a3m) files")
    parser.add_argument("--output-dir", default="AF2",
                        help="Output directory for AF2 results (default: AF2)")
    parser.add_argument("--gpus", default="0,1,2,3,4,5,6",
                        help="Comma-separated GPU IDs (default: 0,1,2,3,4,5,6)")
    parser.add_argument("--af2-data", default=DEFAULT_AF2_DATA,
                        help="AlphaFold2 data directory (default: AF2_DATA_DIR env var, otherwise required)")

    args = parser.parse_args()

    if not args.af2_data:
        print("[ERROR] --af2-data is required unless AF2_DATA_DIR is set")
        sys.exit(1)

    gpu_lst = [int(g) for g in args.gpus.split(',')]
    input_path = Path(args.input_dir).resolve()
    output_path = Path.cwd() / args.output_dir

    print("=" * 60)
    print("AF2 Predictor - Starting")
    print("=" * 60)
    print(f"Input dir:  {input_path}")
    print(f"Output dir: {output_path}")
    print(f"AF2 data:   {args.af2_data}")
    print(f"GPUs:       {gpu_lst}")
    print("=" * 60)

    if not input_path.exists():
        print(f"[ERROR] Input directory not found: {input_path}")
        sys.exit(1)

    if not Path(args.af2_data).exists():
        print(f"[ERROR] AF2 data directory not found: {args.af2_data}")
        sys.exit(1)

    a3m_files = sorted(input_path.glob('*.a3m'))
    if not a3m_files:
        print(f"[ERROR] No .a3m files found in {input_path}")
        print("Available files:", list(input_path.iterdir()) if input_path.exists() else "[]")
        sys.exit(1)

    print(f"[OK] Found {len(a3m_files)} MSA files")

    output_path.mkdir(parents=True, exist_ok=True)
    af2_inputs_dir = output_path / 'AF2_inputs'
    af2_inputs_dir.mkdir(parents=True, exist_ok=True)

    print(f"\nDistributing MSA files across {len(gpu_lst)} GPUs...")
    gpu_files = {gpu_id: [] for gpu_id in gpu_lst}

    for i, a3m_file in enumerate(a3m_files):
        gpu_id = gpu_lst[i % len(gpu_lst)]
        gpu_target = af2_inputs_dir / str(gpu_id)
        gpu_target.mkdir(parents=True, exist_ok=True)
        shutil.copy(a3m_file, gpu_target / a3m_file.name)
        gpu_files[gpu_id].append(a3m_file.name)

    for gpu_id in gpu_lst:
        print(f"  GPU {gpu_id}: {len(gpu_files[gpu_id])} files")

    print(f"\nRunning AlphaFold2 predictions...")
    with mp.Pool(len(gpu_lst)) as pool:
        results = pool.starmap(
            run_af2,
            [(gpu_id, af2_inputs_dir / str(gpu_id), output_path, args.af2_data) for gpu_id in gpu_lst]
        )

    success_count = sum(1 for _, code, _, _ in results if code == 0)
    failed_gpus = [(gpu_id, stderr) for gpu_id, code, _, stderr in results if code != 0]

    if failed_gpus:
        print(f"\n[WARNING] {len(failed_gpus)} GPU(s) failed:")
        for gpu_id, stderr in failed_gpus:
            print(f"  GPU {gpu_id}: {stderr[-300:] if len(stderr) > 300 else stderr}")

    total_pdbs = len(list(output_path.glob('*.pdb')))
    print(f"\n{'=' * 60}")
    print(f"[DONE] Completed: {success_count}/{len(gpu_lst)} GPUs succeeded")
    print(f"       Total PDB files generated: {total_pdbs}")
    print(f"       Output directory: {output_path}")
    print("=" * 60)

    sys.exit(0 if success_count > 0 else 1)

if __name__ == "__main__":
    mp.set_start_method('fork', force=True)
    sys.exit(main())

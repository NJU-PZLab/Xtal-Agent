#!/usr/bin/env python3
import os
import subprocess
import argparse
import sys
from pathlib import Path


DEFAULT_DBBASE = os.environ.get("MSA_DBBASE") or ""
DEFAULT_COLABFOLD_SEARCH = os.environ.get("COLABFOLD_SEARCH") or "colabfold_search"

def validate_input_csv(csv_path):
    """Validate input CSV has correct format: id,sequence header and at least one sequence."""
    if not csv_path.exists():
        raise FileNotFoundError(f"Input CSV not found: {csv_path}")

    with open(csv_path, 'r') as f:
        header = f.readline().strip()
        if header != 'id,sequence':
            raise ValueError(f"CSV header must be 'id,sequence', got: '{header}'")

    with open(csv_path, 'r') as f:
        lines = f.readlines()
        if len(lines) < 2:
            raise ValueError("CSV must contain at least header and one sequence")

    return True

def main():
    parser = argparse.ArgumentParser(
        description="Run colabfold_search for MSA generation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run_msa.py --input inputs.csv --output-dir MSA
  python run_msa.py --input design.csv --threads 32 --gpus 0,1,2,3
        """
    )
    parser.add_argument("--input", default="inputs.csv",
                        help="Input CSV file with 'id,sequence' format (default: inputs.csv)")
    parser.add_argument("--dbbase", default=DEFAULT_DBBASE,
                        help="Database base directory (default: MSA_DBBASE env var, otherwise required)")
    parser.add_argument("--output-dir", default="MSA",
                        help="MSA output directory (default: MSA)")
    parser.add_argument("--threads", type=int, default=64,
                        help="Number of threads (default: 64)")
    parser.add_argument("--gpus", default="0,1,2,3,4,5,6",
                        help="Comma-separated GPU IDs (default: 0,1,2,3,4,5,6)")
    parser.add_argument("--gpu", type=int, default=1,
                        help="Whether to use GPU: 1=yes, 0=no (default: 1)")
    args = parser.parse_args()

    if not args.dbbase:
        print("[ERROR] --dbbase is required unless MSA_DBBASE is set")
        sys.exit(1)

    script_dir = Path(__file__).parent.parent
    input_path = Path.cwd() / args.input
    output_path = Path.cwd() / args.output_dir

    print("=" * 60)
    print("MSA Generator - Starting")
    print("=" * 60)
    print(f"Input CSV:  {input_path}")
    print(f"Output dir: {output_path}")
    print(f"DB base:    {args.dbbase}")
    print(f"Threads:    {args.threads}")
    print(f"GPUs:       {args.gpus}")
    print("=" * 60)

    try:
        validate_input_csv(input_path)
        print("[OK] Input CSV validated")
    except (FileNotFoundError, ValueError) as e:
        print(f"[ERROR] {e}")
        sys.exit(1)

    if not Path(args.dbbase).exists():
        print(f"[ERROR] Database base directory not found: {args.dbbase}")
        sys.exit(1)

    output_path.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["CUDA_VISIBLE_DEVICES"] = args.gpus

    search_run_env = DEFAULT_COLABFOLD_SEARCH

    print(f"\nRunning colabfold_search...")
    result = subprocess.run(
        [
            search_run_env,
            str(input_path),
            args.dbbase,
            str(output_path),
            '--threads', str(args.threads),
            '--gpu', str(args.gpu),
            '--af3-json'
        ],
        env=env,
        cwd=Path.cwd(),
        capture_output=True,
        text=True
    )

    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)

    if result.returncode != 0:
        print(f"\n[ERROR] colabfold_search failed with return code {result.returncode}")
        sys.exit(1)

    a3m_files = sorted(output_path.glob('*.a3m'))
    if not a3m_files:
        print(f"[WARNING] No .a3m files found in {output_path}")
        sys.exit(1)

    print(f"\n{'=' * 60}")
    print(f"[SUCCESS] Generated {len(a3m_files)} MSA files:")
    for f in a3m_files:
        print(f"  - {f.name}")
    print(f"{'=' * 60}")

    sys.exit(0)

if __name__ == "__main__":
    sys.exit(main())

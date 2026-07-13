#!/usr/bin/env python3
import argparse
import json
import multiprocessing as mp
import shutil
from pathlib import Path

import MDAnalysis as mda
import numpy as np
import pandas as pd
from Bio.SeqUtils import seq1

try:
    from MDAnalysis.analysis import rms
except ImportError:
    rms = None

AA_hydro = {
    'I': 4.5, 'V': 4.2, 'L': 3.8, 'F': 2.8, 'C': 2.5, 'M': 1.9,
    'A': 1.8, 'G': -0.4, 'T': -0.7, 'W': -0.9, 'S': -0.8, 'Y': -1.3,
    'P': -1.6, 'H': -3.2, 'E': -3.5, 'Q': -3.5, 'D': -3.5, 'N': -3.5,
    'K': -3.9, 'R': -4.5
}

def cal_aa_hydro(seq):
    return sum([AA_hydro.get(s, 0) for s in seq]) / len(seq) if seq else 0


def select_ab_backbone(universe):
    """Select backbone atoms for chains A and B when present, else fall back to all protein backbone atoms."""
    ab_backbone = universe.select_atoms("protein and backbone and (chainID A or chainID B)")
    if len(ab_backbone) > 0:
        return ab_backbone
    return universe.select_atoms("protein and backbone")

def get_af2_scores(json_file):
    scores = {}
    if json_file.exists():
        try:
            with open(json_file) as f:
                data = json.load(f)
                if 'plddt' in data:
                    scores['plddt'] = np.mean(data['plddt'])
                if 'ptm' in data:
                    scores['ptm'] = data['ptm']
                if 'iptm' in data:
                    scores['iptm'] = data['iptm']
                scores['has_ligand'] = data.get('has_ligand', False)
        except:
            pass
    return scores

def process_single_design(args):
    fname, template_pdb, output_dir = args
    try:
        name = fname.stem.split("_unrelaxed_")[0]
        
        u = mda.Universe(fname)
        bfactors = u.atoms.bfactors
        plddt = float(np.mean(bfactors)) if bfactors is not None and len(bfactors) > 0 else 0
        
        seq = ''.join([seq1(r.resname) for r in u.select_atoms("protein").residues])
        hydro = cal_aa_hydro(seq)
        
        result = {
            'name': name,
            'sequence': seq,
            'plddt': round(plddt, 2),
            'hydrophobicity': round(hydro, 3),
            'num_residues': len(seq)
        }
        
        if template_pdb and template_pdb.exists():
            try:
                u_ref = mda.Universe(str(template_pdb))
                mobile = select_ab_backbone(u)
                reference = select_ab_backbone(u_ref)
                if len(mobile) > 0 and len(reference) > 0 and len(mobile) == len(reference):
                    rmsd_val = rms.rmsd(
                        mobile.positions,
                        reference.positions,
                        superposition=True,
                        center=True
                    )
                    result['rmsd'] = round(rmsd_val, 3)
                else:
                    result['rmsd'] = None
            except Exception as e:
                result['rmsd'] = None
        else:
            result['rmsd'] = None
        
        json_files = list(fname.parent.glob(f"{name}_scores_rank_001*.json"))
        if json_files:
            scores = get_af2_scores(json_files[0])
            result.update(scores)
        
        shutil.copy(fname, output_dir / f"{name}.pdb")
        
        return result
    except Exception as e:
        return {'name': str(fname), 'error': str(e)}

def main():
    parser = argparse.ArgumentParser(description="Post-process AlphaFold2 results")
    parser.add_argument("--af2-dir", required=True, help="Directory containing AF2 results")
    parser.add_argument("--results-dir", default=None, help="Directory containing PDB/JSON files (default: AF2_DIR/AF2_results)")
    parser.add_argument("--template", default=None, help="Reference PDB for RMSD calculation")
    parser.add_argument("--output", default="results.csv", help="Output CSV file")
    parser.add_argument("--pdb-dir", default=None, help="Output directory for PDB files (default: AF2_DIR/pdb_structure)")
    parser.add_argument("--pdb-pattern", default="*rank_001*.pdb", help="Glob pattern for PDB files")
    args = parser.parse_args()

    af2_dir = Path(args.af2_dir)
    if not af2_dir.exists():
        af2_dir = Path.cwd() / args.af2_dir
    
    results_dir = Path(args.results_dir) if args.results_dir else af2_dir / 'AF2_results'
    if not results_dir.exists():
        results_dir = af2_dir
    
    template_pdb = Path(args.template) if args.template else None
    output_dir = Path(args.pdb_dir) if args.pdb_dir else af2_dir / 'pdb_structure'
    output_dir.mkdir(exist_ok=True, parents=True)

    f_lst = sorted(results_dir.glob(args.pdb_pattern))
    if not f_lst:
        print(f"No rank_001 PDB files found in {results_dir}")
        return 1

    print(f"Found {len(f_lst)} rank_001 structures")
    print(f"Results directory: {results_dir}")
    print(f"Output directory: {output_dir}")

    tasks = [(fname, template_pdb, output_dir) for fname in f_lst]
    
    results = [process_single_design(task) for task in tasks]

    df = pd.DataFrame(results)
    
    cols = ['name', 'sequence', 'plddt', 'ptm', 'iptm', 'rmsd', 'hydrophobicity', 'num_residues']
    existing_cols = [c for c in cols if c in df.columns]
    df = df[existing_cols]

    output_path = af2_dir / args.output
    df.to_csv(output_path, index=False)
    print(f"Results saved to {output_path}")
    print(f"Processed {len(df)} structures")
    if 'iptm' in df.columns and 'rmsd' in df.columns:
        main_hits = df[(df['iptm'] >= 0.8) & (df['rmsd'].notna()) & (df['rmsd'] <= 3.0)]
        print(f"Main hits (iptm >= 0.8 and rmsd <= 3.0): {len(main_hits)}")

    return 0

if __name__ == "__main__":
    mp.set_start_method('fork', force=True)
    exit(main())

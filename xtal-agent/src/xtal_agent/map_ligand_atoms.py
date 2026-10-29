#!/usr/bin/env python3
"""Map AF3-predicted ligand atom names to CCP4 monomer library atom names via Kabsch alignment.

Usage:
    python map_ligand_atoms.py \\
        --af3-pdb af3_model.pdb --af3-chain B \\
        --ccd-code B96 \\
        --ccp4-monomer-dir /path/to/ccp4/lib/data/monomers \\
        --output mapped_ligand.pdb

Or with elbow CIF fallback:
    python map_ligand_atoms.py \\
        --af3-pdb af3_model.pdb --af3-chain B \\
        --ccd-code B96 --elbow-cif B96_elbow.cif \\
        --ccp4-monomer-dir /path/to/ccp4/lib/data/monomers \\
        --output mapped_ligand.pdb

Workflow:
    1. Look up CCD code in CCP4 monomer library
    2. Parse reference 3D coordinates from CCP4 or elbow CIF
    3. Parse AF3-predicted ligand coordinates from PDB
    4. Kabsch-align AF3 coordinates to reference
    5. Nearest-neighbor match by element type
    6. Output PDB with AF3 coordinates + reference atom names
"""

import argparse
import math
import os
import re
import sys

import numpy as np


def parse_ccp4_monomer_cif(cif_path):
    """Parse CCP4 monomer CIF, return list of (atom_name, [x, y, z])."""
    names, coords = [], []
    with open(cif_path) as f:
        in_loop = False
        col_map = {}
        for line in f:
            line = line.strip()
            if line.startswith("loop_"):
                in_loop = True
                col_map = {}
                continue
            if in_loop and line.startswith("_chem_comp_atom."):
                key = line.split(".", 1)[1].strip()
                col_map[key] = len(col_map)
                continue
            if in_loop and line and not line.startswith("_") and not line.startswith("#"):
                parts = line.split()
                ai = col_map.get("atom_id")
                si = col_map.get("type_symbol")
                xi = col_map.get("x")
                yi = col_map.get("y")
                zi = col_map.get("z")
                if all(k is not None for k in [ai, si, xi, yi, zi]):
                    try:
                        aname = parts[ai]
                        sym = parts[si]
                        if aname.startswith("H") or sym in ("H", "D"):
                            continue
                        names.append(aname)
                        coords.append([float(parts[xi]), float(parts[yi]), float(parts[zi])])
                    except (IndexError, ValueError):
                        pass
            elif in_loop and not line:
                if names:
                    break
                in_loop = False
    return names, coords


def parse_af3_ligand_pdb(pdb_path, chain_id):
    """Parse AF3 PDB, extract ligand HETATM from specified chain."""
    names, coords, lines = [], [], []
    with open(pdb_path) as f:
        for line in f:
            if line.startswith("HETATM") and line[21] == chain_id:
                names.append(line[12:16].strip())
                coords.append([float(line[30:38]), float(line[38:46]), float(line[46:54])])
                lines.append(line)
    return names, coords, lines


def kabsch_align(ref_coords, mobile_coords):
    """Kabsch-align mobile_coords to ref_coords. Returns aligned mobile coords + rotation matrix."""
    ref = np.array(ref_coords)
    mob = np.array(mobile_coords)
    rc = ref - ref.mean(axis=0)
    mc = mob - mob.mean(axis=0)
    h = mc.T @ rc
    u, s, vt = np.linalg.svd(h)
    r = vt.T @ u.T
    if np.linalg.det(r) < 0:
        vt[-1] *= -1
        r = vt.T @ u.T
    aligned = mc @ r.T + ref.mean(axis=0)
    return aligned


def match_atoms(af3_names, af3_aligned, ref_names, ref_coords):
    """Nearest-neighbor matching by element type. Returns dict af3_idx -> ref_name."""
    mapping = {}
    used_ref = set()
    for ai, (aname, axyz) in enumerate(zip(af3_names, af3_aligned)):
        elem = aname[0]
        best_dist = float("inf")
        best_ri = None
        for ri in range(len(ref_names)):
            if ri in used_ref:
                continue
            if ref_names[ri][0] != elem:
                continue
            d = math.sqrt(sum((axyz[k] - ref_coords[ri][k]) ** 2 for k in range(3)))
            if d < best_dist:
                best_dist = d
                best_ri = ri
        if best_ri is not None:
            mapping[ai] = {"ref_name": ref_names[best_ri], "dist": best_dist}
            used_ref.add(best_ri)
    return mapping


def find_ccp4_cif(ccd_code, monomer_dir):
    """Find monomer CIF in CCP4 directory structure (e.g., b/B96.cif)."""
    prefix = ccd_code[0].lower()
    path = os.path.join(monomer_dir, prefix, f"{ccd_code}.cif")
    if os.path.exists(path):
        return path
    # Try flat structure
    path = os.path.join(monomer_dir, f"{ccd_code}.cif")
    if os.path.exists(path):
        return path
    return None


def write_mapped_pdb(af3_lines, mapping, ccd_code, output_path):
    """Write PDB with AF3 coordinates and reference atom names."""
    with open(output_path, "w") as f:
        for ai in range(len(af3_lines)):
            if ai in mapping:
                rname = mapping[ai]["ref_name"]
                line = af3_lines[ai]
                elem = rname[0] if rname[0] in "CNOS" else "C"
                # HETATM serial name res chain resid ...
                new_line = (
                    f"HETATM{ai + 1:5d} {rname:<4s}"
                    + line[16:17]
                    + ccd_code
                    + line[20:76]
                    + f"{elem:>2s}"
                    + line[78:]
                )
                f.write(new_line)
        f.write("TER\nEND\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Map AF3 ligand atoms to CCP4/elbow naming")
    parser.add_argument("--af3-pdb", required=True, help="AF3 output PDB containing ligand")
    parser.add_argument("--af3-chain", required=True, help="Chain ID of ligand in AF3 PDB")
    parser.add_argument("--ccd-code", required=True, help="PDB Chemical Component Dictionary code (e.g. B96)")
    parser.add_argument("--ccp4-monomer-dir", help="CCP4 monomer library directory")
    parser.add_argument("--elbow-cif", help="elbow CIF file (fallback if not in CCP4)")
    parser.add_argument("--output", required=True, help="Output PDB with mapped atom names")

    args = parser.parse_args(argv)

    # 1. Parse AF3 ligand
    af3_names, af3_coords, af3_lines = parse_af3_ligand_pdb(args.af3_pdb, args.af3_chain)
    if not af3_names:
        print(f"ERROR: No HETATM found for chain {args.af3_chain} in {args.af3_pdb}", file=sys.stderr)
        sys.exit(1)
    print(f"AF3 ligand: {len(af3_names)} atoms in chain {args.af3_chain}")

    # 2. Look up reference coordinates
    ref_names, ref_coords = None, None
    source = None

    # Try CCP4 first
    if args.ccp4_monomer_dir:
        cif_path = find_ccp4_cif(args.ccd_code, args.ccp4_monomer_dir)
        if cif_path:
            ref_names, ref_coords = parse_ccp4_monomer_cif(cif_path)
            if ref_names:
                source = f"CCP4 ({cif_path})"
                print(f"Found {len(ref_names)} atoms in CCP4 monomer {args.ccd_code}")

    # Fallback: elbow CIF
    if not ref_names and args.elbow_cif:
        if os.path.exists(args.elbow_cif):
            ref_names, ref_coords = parse_ccp4_monomer_cif(args.elbow_cif)
            if ref_names:
                source = f"elbow ({args.elbow_cif})"
                print(f"Found {len(ref_names)} atoms in elbow CIF for {args.ccd_code}")

    if not ref_names:
        if args.ccp4_monomer_dir:
            print(f"ERROR: {args.ccd_code} not found in CCP4 ({args.ccp4_monomer_dir}) and no elbow CIF provided",
                  file=sys.stderr)
        else:
            print(f"ERROR: No CCP4 monomer dir specified and no elbow CIF provided", file=sys.stderr)
        sys.exit(1)

    # 3. Kabsch align
    af3_aligned = kabsch_align(ref_coords, af3_coords)

    # 4. Match atoms
    mapping = match_atoms(af3_names, af3_aligned, ref_names, ref_coords)
    dists = [m["dist"] for m in mapping.values()]
    rmsd = math.sqrt(sum(d * d for d in dists) / len(dists))
    print(f"Mapped {len(mapping)}/{len(af3_names)} atoms, RMSD={rmsd:.2f}A (source: {source})")

    # 5. Write output
    write_mapped_pdb(af3_lines, mapping, args.ccd_code, args.output)
    print(f"Wrote: {args.output}")


if __name__ == "__main__":
    main()

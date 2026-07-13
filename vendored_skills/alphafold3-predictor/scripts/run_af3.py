#!/usr/bin/env python3
"""AlphaFold3 structure prediction script.

Automates the full workflow: MSA -> JSON generation -> multi-GPU inference.
Designed to be simple on the outside, complex on the inside.

Supports: protein, RNA, DNA chains; CCD/SMILES ligands; covalent bonds;
user CCD; multi-GPU parallel; progress display.
"""
import argparse
import json
import multiprocessing as mp
import os
import subprocess
import sys
import time
from pathlib import Path

AF3_PYTHON = os.environ.get('AF3_PYTHON') or 'python'
AF3_RUN_SCRIPT = os.environ.get('AF3_RUN_SCRIPT') or ''
AF3_MODEL_DIR = os.environ.get('AF3_MODEL_DIR') or ''
AF3_DB_DIR = os.environ.get('AF3_DB_DIR') or ''
AF3_BIN_DIR = os.environ.get('AF3_BIN_DIR') or ''


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _expand_chain_ids(base_id, count):
    """Expand a base chain ID into multiple IDs for homomers.

    E.g., 'A' with count 3 -> ['A', 'B', 'C']
    """
    if count == 1:
        return [base_id]
    result = []
    base_ord = ord(base_id)
    for i in range(count):
        result.append(chr(base_ord + i))
    return result


def _parse_entity_spec(spec, expect_type=None):
    """Parse a single chain/ligand entity specification.

    General format:  [type:]id[*N]=value   or   [type:]id[*N]:value
    - 'type' prefix (optional for protein, required for rna/dna): rna:, dna:
    - '=' is used for sequences (protein/rna/dna)
    - ':' is used for ligand codes/smiles

    Examples:
        'A=MAKET...'              -> protein, chain A
        'A*2=MAKET...'            -> protein, dimer A,B
        'rna:A=AGCU'              -> RNA, chain A
        'dna:C=GACCTCT'           -> DNA, chain C
        'C:CA'                    -> CCD ligand, chain C, code CA
        'C*4:CA'                  -> CCD ligand, 4 copies
        'C:CC(=O)O'              -> SMILES ligand (auto-detected)
    """
    spec = spec.strip()
    if not spec:
        return None

    entity_type = 'protein'  # default

    # Check for type prefix
    for prefix in ('rna:', 'dna:'):
        if spec.lower().startswith(prefix):
            entity_type = prefix.rstrip(':').lower()
            spec = spec[len(prefix):]
            break

    # Determine separator: '=' for sequences, ':' for ligands
    if '=' in spec and ':' in spec:
        eq_idx = spec.index('=')
        colon_idx = spec.index(':')
        if eq_idx < colon_idx:
            sep = '='
        else:
            sep = ':'
    elif '=' in spec:
        sep = '='
    elif ':' in spec:
        sep = ':'
    else:
        raise ValueError(f"Invalid entity spec (need '=' or ':'): {spec}")

    sep_idx = spec.index(sep)
    id_part = spec[:sep_idx].strip()
    value = spec[sep_idx + 1:].strip()

    # Parse id*N notation
    if '*' in id_part:
        base_id, count = id_part.split('*')
        count = int(count)
        chain_ids = _expand_chain_ids(base_id.strip(), count)
    else:
        chain_ids = [id_part.strip()]

    # Determine entity details based on separator and type
    if sep == '=':
        # Sequence-based entity (protein, rna, dna)
        if entity_type == 'protein':
            return {'type': 'protein', 'ids': chain_ids, 'sequence': value}
        elif entity_type == 'rna':
            _validate_rna_sequence(value)
            return {'type': 'rna', 'ids': chain_ids, 'sequence': value}
        elif entity_type == 'dna':
            _validate_dna_sequence(value)
            return {'type': 'dna', 'ids': chain_ids, 'sequence': value}
    else:
        # ':' separator -> ligand
        # Auto-detect CCD vs SMILES: CCD codes are short uppercase alphanumeric
        if _is_ccd_code(value):
            return {'type': 'ccd_ligand', 'ids': chain_ids, 'ccdCodes': [value]}
        else:
            return {'type': 'smiles_ligand', 'ids': chain_ids, 'smiles': value}


def _is_ccd_code(value):
    """Check if a value looks like a CCD code.

    CCD codes are typically 1-3 uppercase alphanumeric, but user CCD codes
    can contain hyphens and be longer (e.g. 'MY-LIG', 'X7F-1').
    """
    if not value:
        return False
    # Standard CCD: 1-3 uppercase alphanumeric
    if len(value) <= 3 and value.isupper() and value.isalnum():
        return True
    # User CCD codes: allow hyphens, uppercase letters, digits
    # Must contain at least one letter, no spaces
    if ' ' in value:
        return False
    allowed = set('ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-')
    if not all(c in allowed for c in value):
        return False
    # Must have at least one letter
    if not any(c.isalpha() for c in value):
        return False
    # If it contains lowercase or special chars, it's SMILES
    return True


def _validate_rna_sequence(seq):
    """Validate RNA sequence contains only A, C, G, U."""
    valid = set('ACGU')
    invalid = set(seq.upper()) - valid
    if invalid:
        raise ValueError(f"RNA sequence contains invalid bases: {invalid}. "
                         f"Only A, C, G, U are allowed.")


def _validate_dna_sequence(seq):
    """Validate DNA sequence contains only A, C, G, T."""
    valid = set('ACGT')
    invalid = set(seq.upper()) - valid
    if invalid:
        raise ValueError(f"DNA sequence contains invalid bases: {invalid}. "
                         f"Only A, C, G, T are allowed.")


def parse_entities(chains_str, ligands_str=None, ligands_smiles_str=None,
                   rna_str=None, dna_str=None):
    """Parse all entity specifications into structured lists.

    Returns dict with keys: 'protein', 'rna', 'dna', 'ccd_ligands',
    'smiles_ligands'.
    """
    entities = {
        'protein': [],
        'rna': [],
        'dna': [],
        'ccd_ligands': [],
        'smiles_ligands': [],
    }

    # Parse --chains (protein by default, can prefix with rna:/dna:)
    if chains_str:
        for spec in chains_str.split(';'):
            entity = _parse_entity_spec(spec)
            if entity:
                _add_entity(entities, entity)

    # Parse --rna (shorthand for RNA chains)
    if rna_str:
        for spec in rna_str.split(';'):
            entity = _parse_entity_spec('rna:' + spec if not spec.lower().startswith('rna:') else spec)
            if entity:
                _add_entity(entities, entity)

    # Parse --dna (shorthand for DNA chains)
    if dna_str:
        for spec in dna_str.split(';'):
            entity = _parse_entity_spec('dna:' + spec if not spec.lower().startswith('dna:') else spec)
            if entity:
                _add_entity(entities, entity)

    # Parse --ligands (CCD codes)
    if ligands_str:
        for spec in ligands_str.split(','):
            entity = _parse_entity_spec(spec)
            if entity:
                _add_entity(entities, entity)

    # Parse --ligands-smiles
    if ligands_smiles_str:
        for spec in ligands_smiles_str.split(','):
            spec = spec.strip()
            if not spec:
                continue
            colon_idx = spec.index(':')
            id_part = spec[:colon_idx].strip()
            smiles = spec[colon_idx + 1:].strip()
            if '*' in id_part:
                base_id, count = id_part.split('*')
                count = int(count)
                ligand_ids = _expand_chain_ids(base_id.strip(), count)
            else:
                ligand_ids = [id_part.strip()]
            _add_entity(entities, {'type': 'smiles_ligand', 'ids': ligand_ids,
                                   'smiles': smiles})

    return entities


def _add_entity(entities, entity):
    """Add a parsed entity to the appropriate list."""
    etype = entity['type']
    if etype == 'protein':
        entities['protein'].append(entity)
    elif etype == 'rna':
        entities['rna'].append(entity)
    elif etype == 'dna':
        entities['dna'].append(entity)
    elif etype == 'ccd_ligand':
        entities['ccd_ligands'].append(entity)
    elif etype == 'smiles_ligand':
        entities['smiles_ligands'].append(entity)


# ---------------------------------------------------------------------------
# Covalent bond parsing
# ---------------------------------------------------------------------------

def parse_bonds(bonds_str):
    """Parse covalent bond specifications.

    Format: 'CHAIN1:RES1:ATOM1-CHAIN2:RES2:ATOM2,...'

    Examples:
        'A:145:SG-L:1:C04'                          -> protein CYS to ligand
        'A:145:SG-L:1:C04,A:100:NZ-L:2:C01'         -> two bonds
    """
    if not bonds_str:
        return None

    bonds = []
    for spec in bonds_str.split(','):
        spec = spec.strip()
        if not spec:
            continue
        parts = spec.split('-')
        if len(parts) != 2:
            raise ValueError(f"Invalid bond spec (need '-'): {spec}")
        atom1 = _parse_atom_id(parts[0].strip())
        atom2 = _parse_atom_id(parts[1].strip())
        bonds.append([atom1, atom2])

    return bonds if bonds else None


def _parse_atom_id(atom_str):
    """Parse atom identifier: 'CHAIN:RESIDUE:ATOM_NAME' -> [chain, res_id, atom]."""
    parts = atom_str.split(':')
    if len(parts) != 3:
        raise ValueError(f"Invalid atom ID (need CHAIN:RES:ATOM): {atom_str}")
    chain_id = parts[0].strip()
    try:
        res_id = int(parts[1].strip())
    except ValueError:
        raise ValueError(f"Residue ID must be integer in atom: {atom_str}")
    atom_name = parts[2].strip()
    return [chain_id, res_id, atom_name]


# ---------------------------------------------------------------------------
# JSON building
# ---------------------------------------------------------------------------

def build_af3_json(name, entities, msa_dir=None, model_seeds=None,
                   bonded_atom_pairs=None, user_ccd_path=None):
    """Build an AlphaFold3 input JSON dict.

    Args:
        name: Job name.
        entities: Dict from parse_entities() with protein/rna/dna/ligand lists.
        msa_dir: Directory containing .a3m MSA files.
        model_seeds: List of random seeds.
        bonded_atom_pairs: Covalent bond specifications.
        user_ccd_path: Path to user-provided CCD file.

    Returns:
        dict: AlphaFold3 input JSON.
    """
    sequences = []

    # Protein chains
    for chain in entities.get('protein', []):
        protein_entry = {
            'id': chain['ids'] if len(chain['ids']) > 1 else chain['ids'][0],
            'sequence': chain['sequence'],
        }
        if msa_dir:
            msa_file = _find_msa_file(msa_dir, chain['ids'][0], chain['sequence'])
            if msa_file:
                protein_entry['unpairedMsaPath'] = str(msa_file)
                protein_entry['pairedMsa'] = ''
                protein_entry['templates'] = []
        sequences.append({'protein': protein_entry})

    # RNA chains
    for chain in entities.get('rna', []):
        rna_entry = {
            'id': chain['ids'] if len(chain['ids']) > 1 else chain['ids'][0],
            'sequence': chain['sequence'],
        }
        if msa_dir:
            msa_file = _find_msa_file(msa_dir, chain['ids'][0], chain['sequence'],
                                      ext='.a3m', require_seq_match=True)
            if msa_file:
                rna_entry['unpairedMsaPath'] = str(msa_file)
            else:
                rna_entry['unpairedMsa'] = ''
        sequences.append({'rna': rna_entry})

    # DNA chains
    for chain in entities.get('dna', []):
        dna_entry = {
            'id': chain['ids'] if len(chain['ids']) > 1 else chain['ids'][0],
            'sequence': chain['sequence'],
        }
        sequences.append({'dna': dna_entry})

    # CCD ligands
    for lig in entities.get('ccd_ligands', []):
        ligand_entry = {
            'id': lig['ids'] if len(lig['ids']) > 1 else lig['ids'][0],
            'ccdCodes': lig['ccdCodes'],
        }
        sequences.append({'ligand': ligand_entry})

    # SMILES ligands
    for lig in entities.get('smiles_ligands', []):
        ligand_entry = {
            'id': lig['ids'] if len(lig['ids']) > 1 else lig['ids'][0],
            'smiles': lig['smiles'],
        }
        sequences.append({'ligand': ligand_entry})

    result = {
        'name': name,
        'modelSeeds': model_seeds or [1],
        'sequences': sequences,
        'dialect': 'alphafold3',
        'version': 4,
    }

    if bonded_atom_pairs:
        result['bondedAtomPairs'] = bonded_atom_pairs

    if user_ccd_path:
        result['userCCDPath'] = str(Path(user_ccd_path).resolve())

    return result


def _find_msa_file(msa_dir, chain_id, sequence, ext='.a3m',
                   require_seq_match=False):
    """Find MSA file for a given chain.

    Args:
        msa_dir: Directory with MSA files.
        chain_id: Chain identifier (e.g. 'A').
        sequence: Expected query sequence.
        ext: MSA file extension.
        require_seq_match: If True, only return file whose first sequence
            matches. Used for RNA/DNA to avoid mismatching with protein MSA.
    """
    msa_path = Path(msa_dir)

    # Try exact chain ID match
    candidates = [
        msa_path / f'{chain_id}{ext}',
        msa_path / f'{chain_id.lower()}{ext}',
    ]

    # Try finding any MSA file (for single-chain predictions)
    msa_files = sorted(msa_path.glob(f'*{ext}'))
    if len(msa_files) == 1 and not require_seq_match:
        candidates.append(msa_files[0])

    # Try matching by sequence content (always for require_seq_match)
    for f in msa_files:
        candidates.append(f)

    for candidate in candidates:
        if candidate and candidate.exists():
            resolved = candidate.resolve()
            if require_seq_match:
                if _msa_first_seq_matches(resolved, sequence):
                    return resolved
            else:
                return resolved

    return None


def _msa_first_seq_matches(msa_file, query_sequence):
    """Check if the first sequence in an A3M file matches the query."""
    try:
        with open(msa_file, 'r') as f:
            for line in f:
                line = line.strip()
                if line.startswith('>'):
                    seq_line = f.readline().strip()
                    # Remove lowercase (insertions) for comparison
                    seq_clean = ''.join(c for c in seq_line if c.isupper() and c != '-')
                    return seq_clean == query_sequence
    except (IOError, UnicodeDecodeError):
        pass
    return False


# ---------------------------------------------------------------------------
# AF3 execution
# ---------------------------------------------------------------------------

def run_af3_single(json_path, output_dir, gpu_id, extra_args=None):
    """Run AlphaFold3 on a single JSON file using a specific GPU."""
    env = os.environ.copy()
    env["CUDA_VISIBLE_DEVICES"] = str(gpu_id)
    env['PATH'] = AF3_BIN_DIR + ':' + env.get('PATH', '')

    json_path_abs = json_path.resolve()
    output_dir_abs = output_dir.resolve()

    cmd = [
        AF3_PYTHON,
        AF3_RUN_SCRIPT,
        '--json_path', str(json_path_abs),
        '--model_dir', AF3_MODEL_DIR,
        '--db_dir', AF3_DB_DIR,
        '--jackhmmer_binary_path', os.path.join(AF3_BIN_DIR, 'jackhmmer'),
        '--output_dir', str(output_dir_abs),
        '--gpu_device', '0',
        '--run_inference',
        '--force_output_dir',
        '--norun_data_pipeline',
        '--resolve_msa_overlaps=false',
    ]

    if extra_args:
        cmd.extend(extra_args)

    print(f"  [GPU {gpu_id}] Running: {json_path.name}")
    result = subprocess.run(
        cmd, env=env, capture_output=True, text=True
    )
    return (gpu_id, result.returncode, result.stdout, result.stderr)


def collect_results(output_dir):
    """Collect and summarize prediction results."""
    output_path = Path(output_dir)
    cif_files = list(output_path.rglob('*_model.cif'))
    summary_files = list(output_path.rglob('*_summary_confidences.json'))
    ranking_files = list(output_path.rglob('*_ranking_scores.csv'))

    results = {}
    for summary_file in summary_files:
        try:
            with open(summary_file) as f:
                data = json.load(f)
            job_name = (summary_file.parent.name
                        if summary_file.parent.name != output_path.name
                        else summary_file.stem.replace('_summary_confidences', ''))
            results[job_name] = {
                'ptm': data.get('ptm', 'N/A'),
                'iptm': data.get('iptm', 'N/A'),
                'ranking_score': data.get('ranking_score', 'N/A'),
                'fraction_disordered': data.get('fraction_disordered', 'N/A'),
                'has_clash': data.get('has_clash', 'N/A'),
            }
        except (json.JSONDecodeError, IOError):
            continue

    return cif_files, results, ranking_files


# ---------------------------------------------------------------------------
# Progress display
# ---------------------------------------------------------------------------

class ProgressDisplay:
    """Simple progress display for sequential and parallel runs."""

    def __init__(self, total_jobs, total_samples_per_job):
        self.total_jobs = total_jobs
        self.total_samples_per_job = total_samples_per_job
        self.completed_jobs = 0
        self.start_time = time.time()

    def job_started(self, job_name, gpu_id):
        pass  # print already done by runner

    def job_completed(self, job_name, gpu_id, elapsed, success=True):
        self.completed_jobs += 1
        total_elapsed = time.time() - self.start_time
        if self.total_jobs > 1:
            eta = (total_elapsed / self.completed_jobs
                   * (self.total_jobs - self.completed_jobs))
            status = "OK" if success else "FAIL"
            bar_len = 30
            filled = int(bar_len * self.completed_jobs / self.total_jobs)
            bar = '█' * filled + '░' * (bar_len - filled)
            print(f"  [{bar}] {self.completed_jobs}/{self.total_jobs} "
                  f"jobs | {elapsed:.0f}s this job | "
                  f"ETA {eta:.0f}s | {status} {job_name}")
        else:
            status = "OK" if success else "FAIL"
            print(f"  [{status}] {job_name} in {elapsed:.1f}s on GPU {gpu_id}")

    def all_done(self):
        total_elapsed = time.time() - self.start_time
        print(f"\n  Total time: {total_elapsed:.1f}s "
              f"({self.completed_jobs} jobs, "
              f"{total_elapsed / max(self.completed_jobs, 1):.1f}s avg)")


# ---------------------------------------------------------------------------
# Run modes
# ---------------------------------------------------------------------------

def _run_sequential(json_files, output_path, gpu_lst, extra_args, progress):
    """Run JSON files sequentially, distributing across GPUs."""
    for i, json_file in enumerate(json_files):
        gpu_id = gpu_lst[i % len(gpu_lst)]
        job_name = json_file.stem
        job_output = output_path / job_name
        job_output.mkdir(parents=True, exist_ok=True)

        print(f"\n[Job {i + 1}/{len(json_files)}] {job_name} on GPU {gpu_id}")
        start_time = time.time()

        gpu_id_int, returncode, stdout, stderr = run_af3_single(
            json_file, job_output, gpu_id, extra_args
        )

        elapsed = time.time() - start_time

        if returncode != 0:
            progress.job_completed(job_name, gpu_id, elapsed, success=False)
            print(f"  [ERROR] Job {job_name} failed (code {returncode})")
            if stderr:
                print(f"  stderr (last 500 chars): ...{stderr[-500:]}")
        else:
            progress.job_completed(job_name, gpu_id, elapsed, success=True)


def _gpu_worker(gpu_id, files, output_path, extra_args):
    """Worker function for parallel execution (must be module-level for pickling)."""
    results = []
    for json_file in files:
        job_name = json_file.stem
        job_output = output_path / job_name
        job_output.mkdir(parents=True, exist_ok=True)

        result = run_af3_single(json_file, job_output, gpu_id, extra_args)
        results.append((json_file.name, result))
    return results


def _run_parallel(json_files, output_path, gpu_lst, extra_args, progress):
    """Run JSON files in parallel across multiple GPUs."""
    gpu_assignments = {gpu_id: [] for gpu_id in gpu_lst}
    for i, json_file in enumerate(json_files):
        gpu_id = gpu_lst[i % len(gpu_lst)]
        gpu_assignments[gpu_id].append(json_file)

    for gpu_id in gpu_lst:
        print(f"  GPU {gpu_id}: {len(gpu_assignments[gpu_id])} jobs")

    print(f"\nRunning {len(json_files)} jobs across {len(gpu_lst)} GPUs...")

    with mp.Pool(len(gpu_lst)) as pool:
        all_results = pool.starmap(
            _gpu_worker,
            [(gpu_id, files, output_path, extra_args)
             for gpu_id, files in gpu_assignments.items() if files]
        )

    success = 0
    failed = 0
    for gpu_results in all_results:
        for job_name, (gpu_id, returncode, stdout, stderr) in gpu_results:
            if returncode == 0:
                success += 1
                progress.job_completed(job_name, gpu_id, 0, success=True)
            else:
                failed += 1
                progress.job_completed(job_name, gpu_id, 0, success=False)
                print(f"  [ERROR] {job_name} failed on GPU {gpu_id}")
                if stderr:
                    print(f"  stderr (last 300 chars): ...{stderr[-300:]}")

    print(f"  Results: {success} succeeded, {failed} failed")


# ---------------------------------------------------------------------------
# Job name generation
# ---------------------------------------------------------------------------

def _generate_job_name(entities):
    """Generate a default job name from entity specifications."""
    parts = []

    for chain in entities.get('protein', []):
        if len(chain['ids']) > 1:
            parts.append(f"{chain['ids'][0]}x{len(chain['ids'])}")
        else:
            parts.append(chain['ids'][0])

    for chain in entities.get('rna', []):
        prefix = 'rna'
        if len(chain['ids']) > 1:
            parts.append(f"{prefix}{chain['ids'][0]}x{len(chain['ids'])}")
        else:
            parts.append(f"{prefix}{chain['ids'][0]}")

    for chain in entities.get('dna', []):
        prefix = 'dna'
        if len(chain['ids']) > 1:
            parts.append(f"{prefix}{chain['ids'][0]}x{len(chain['ids'])}")
        else:
            parts.append(f"{prefix}{chain['ids'][0]}")

    for lig in entities.get('ccd_ligands', []):
        code = lig['ccdCodes'][0]
        if len(lig['ids']) > 1:
            parts.append(f"{code}x{len(lig['ids'])}")
        else:
            parts.append(code)

    for lig in entities.get('smiles_ligands', []):
        if len(lig['ids']) > 1:
            parts.append(f"SMIx{len(lig['ids'])}")
        else:
            parts.append('SMI')

    return '_'.join(parts) if parts else 'af3_job'


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Run AlphaFold3 structure prediction",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Chain specification format (use with --chains):
  Protein (default):  'A=SEQ' or 'A*2=SEQ' (dimer)
  RNA:                'rna:A=AGCU' or 'rna:A*2=AGCU'
  DNA:                'dna:C=GACCTCT'
  Multiple chains:    separated by ';', e.g. 'A=SEQ1;B=SEQ2;dna:C=GACT'

Shorthand flags (alternative to type prefix):
  --rna 'A=AGCU'      RNA chain
  --dna 'C=GACCTCT'   DNA chain

Ligand specification format (CCD codes):
  'C:CA'              Single ligand
  'C*4:CA'            N copies, e.g. 4 calcium ions
  Multiple:           separated by ',', e.g. 'C:CA,D:ATP'

SMILES ligand format:
  --ligands-smiles 'C:CC(=O)O,D:CCO'
  Auto-detected in --ligands if value > 3 chars or contains lowercase

Covalent bonds format:
  --bonds 'A:145:SG-L:1:C04'
  Multiple bonds:     separated by ',', e.g. 'A:145:SG-L:1:C04,A:100:NZ-L:2:C01'

Examples:
  # Monomer with MSA
  python run_af3.py --msa-dir MSA --chains 'A=MAKET...' --output-dir AF3

  # Dimer + 4 calcium ions
  python run_af3.py --msa-dir MSA --chains 'A*2=MAKET...' --ligands 'C*4:CA' --output-dir AF3

  # Protein-RNA complex
  python run_af3.py --msa-dir MSA --chains 'A=MAKET...' --rna 'B=AGCUAGCU' --output-dir AF3

  # Protein-DNA complex with covalent bond
  python run_af3.py --msa-dir MSA --chains 'A=MAKET...' --dna 'B=GACCTCT' \\
      --ligands 'C:MYL' --bonds 'A:145:SG-C:1:C04' --user-ccd my_ligand.cif --output-dir AF3

  # SMILES ligand
  python run_af3.py --msa-dir MSA --chains 'A=MAKET...' --ligands-smiles 'C:CC(=O)O' --output-dir AF3

  # Using pre-built JSON files
  python run_af3.py --json-dir AF3_json --output-dir AF3 --gpus 0,1
        """
    )

    input_group = parser.add_argument_group('Input (choose one)')
    input_group.add_argument("--msa-dir",
                             help="Directory with MSA (.a3m) files from msa-generator")
    input_group.add_argument("--json-dir",
                             help="Directory with pre-built AF3 JSON files")
    input_group.add_argument("--json-path",
                             help="Single pre-built AF3 JSON file")

    chain_group = parser.add_argument_group('Chains (use with --msa-dir)')
    chain_group.add_argument("--chains",
                             help="Chain specs: 'A=SEQ;B=SEQ' or 'rna:A=AGCU;dna:C=GACT'")
    chain_group.add_argument("--rna",
                             help="RNA chain(s): 'A=AGCU' or 'A=AGCU;B=GGCC'")
    chain_group.add_argument("--dna",
                             help="DNA chain(s): 'C=GACCTCT' or 'C=GACT;D=TTAC'")

    lig_group = parser.add_argument_group('Ligands')
    lig_group.add_argument("--ligands",
                           help="CCD ligand specs, e.g. 'C*4:CA,D:ATP'")
    lig_group.add_argument("--ligands-smiles",
                           help="SMILES ligand specs, e.g. 'C:CC(=O)O,D:CCO'")

    bond_group = parser.add_argument_group('Covalent Bonds & Custom CCD')
    bond_group.add_argument("--bonds",
                            help="Bond specs: 'CHAIN:RES:ATOM-CHAIN:RES:ATOM,...'")
    bond_group.add_argument("--user-ccd",
                            help="Path to user CCD mmCIF file")

    param_group = parser.add_argument_group('Parameters')
    param_group.add_argument("--seeds", default="1",
                             help="Comma-separated model seeds (default: 1)")
    param_group.add_argument("--output-dir", default="AF3",
                             help="Output directory (default: AF3)")
    param_group.add_argument("--gpus", default="0",
                             help="Comma-separated GPU IDs (default: 0)")
    param_group.add_argument("--name",
                             help="Job name (default: auto from chains)")
    param_group.add_argument("--num-recycles", type=int, default=10,
                             help="Number of recycles (default: 10)")
    param_group.add_argument("--num-samples", type=int, default=5,
                             help="Number of diffusion samples (default: 5)")
    param_group.add_argument("--flash-attention", default="triton",
                             choices=["triton", "cudnn", "xla"],
                             help="Flash attention implementation (default: triton)")
    param_group.add_argument("--save-embeddings", action="store_true",
                             help="Save embeddings")
    param_group.add_argument("--save-distogram", action="store_true",
                             help="Save distogram")

    args = parser.parse_args()

    missing_env = [
        name
        for name, value in (
            ("AF3_RUN_SCRIPT", AF3_RUN_SCRIPT),
            ("AF3_MODEL_DIR", AF3_MODEL_DIR),
            ("AF3_DB_DIR", AF3_DB_DIR),
        )
        if not value
    ]
    if missing_env:
        parser.error(
            "Missing required AlphaFold3 environment variables: "
            + ", ".join(missing_env)
        )

    # Validate inputs
    has_msa = args.msa_dir is not None
    has_json_dir = args.json_dir is not None
    has_json_path = args.json_path is not None

    if not (has_msa or has_json_dir or has_json_path):
        parser.error("Must specify one of: --msa-dir, --json-dir, or --json-path")

    if has_msa and not args.chains and not args.rna and not args.dna:
        parser.error("--chains, --rna, or --dna is required when using --msa-dir")

    gpu_lst = [int(g) for g in args.gpus.split(',')]
    seeds = [int(s) for s in args.seeds.split(',')]
    output_path = Path.cwd() / args.output_dir
    output_path.mkdir(parents=True, exist_ok=True)

    # Build JSON input files
    json_dir = output_path / 'AF3_inputs'
    json_dir.mkdir(parents=True, exist_ok=True)

    if has_msa:
        # Parse all entities
        entities = parse_entities(
            chains_str=args.chains,
            ligands_str=args.ligands,
            ligands_smiles_str=args.ligands_smiles,
            rna_str=args.rna,
            dna_str=args.dna,
        )

        # Check for duplicate chain IDs
        all_ids = []
        for etype in ('protein', 'rna', 'dna', 'ccd_ligands', 'smiles_ligands'):
            for entity in entities.get(etype, []):
                all_ids.extend(entity['ids'])
        seen = set()
        dupes = []
        for cid in all_ids:
            if cid in seen:
                dupes.append(cid)
            seen.add(cid)
        if dupes:
            parser.error(f"Duplicate chain IDs detected: {dupes}. "
                         f"All chain IDs must be unique across proteins, "
                         f"RNA, DNA, and ligands. Used IDs: {sorted(seen)}")

        # Parse bonds
        bonded_atom_pairs = parse_bonds(args.bonds)

        job_name = args.name or _generate_job_name(entities)

        af3_json = build_af3_json(
            name=job_name,
            entities=entities,
            msa_dir=args.msa_dir,
            model_seeds=seeds,
            bonded_atom_pairs=bonded_atom_pairs,
            user_ccd_path=args.user_ccd,
        )

        json_file = json_dir / f'{job_name}.json'
        with open(json_file, 'w') as f:
            json.dump(af3_json, f, indent=2)
        print(f"[OK] Generated AF3 input JSON: {json_file}")

        # Copy user CCD file if specified
        if args.user_ccd:
            import shutil
            ccd_src = Path(args.user_ccd)
            if ccd_src.exists():
                ccd_dest = json_dir / ccd_src.name
                shutil.copy2(ccd_src, ccd_dest)
                print(f"[OK] Copied user CCD: {ccd_src.name}")

        json_files = [json_file]

    elif has_json_dir:
        json_src = Path(args.json_dir)
        json_files = sorted(json_src.glob('*.json'))
        if not json_files:
            print(f"[ERROR] No .json files found in {json_src}")
            sys.exit(1)
        for jf in json_files:
            dest = json_dir / jf.name
            dest.write_text(jf.read_text())
        print(f"[OK] Found {len(json_files)} JSON files in {json_src}")

    elif has_json_path:
        json_src = Path(args.json_path)
        if not json_src.exists():
            print(f"[ERROR] JSON file not found: {json_src}")
            sys.exit(1)
        dest = json_dir / json_src.name
        dest.write_text(json_src.read_text())
        json_files = [dest]
        print(f"[OK] Using JSON file: {json_src}")

    # Print summary
    total_samples = len(seeds) * args.num_samples
    print("\n" + "=" * 60)
    print("AlphaFold3 Predictor - Starting")
    print("=" * 60)
    print(f"JSON files:  {len(json_files)}")
    print(f"Output dir:  {output_path}")
    print(f"GPUs:        {gpu_lst}")
    print(f"Seeds:       {seeds}")
    print(f"Samples:     {args.num_samples} per seed ({total_samples} total)")
    for jf in json_files:
        print(f"  - {jf.name}")
    print("=" * 60)

    # Build extra args for run_alphafold.py
    extra_args = []
    extra_args.extend(['--num_recycles', str(args.num_recycles)])
    extra_args.extend(['--num_diffusion_samples', str(args.num_samples)])
    extra_args.extend(['--flash_attention_implementation', args.flash_attention])
    if args.save_embeddings:
        extra_args.append('--save_embeddings')
    if args.save_distogram:
        extra_args.append('--save_distogram')

    # Progress display
    progress = ProgressDisplay(len(json_files), args.num_samples)

    # Distribute JSON files across GPUs and run
    if len(json_files) == 1 or len(gpu_lst) == 1:
        _run_sequential(json_files, output_path, gpu_lst, extra_args, progress)
    else:
        _run_parallel(json_files, output_path, gpu_lst, extra_args, progress)

    progress.all_done()

    # Collect results
    cif_files, results, ranking_files = collect_results(output_path)

    print(f"\n{'=' * 60}")
    print(f"[DONE] AlphaFold3 prediction complete")
    print(f"  Output:       {output_path}")
    print(f"  CIF files:    {len(cif_files)}")
    if results:
        print(f"  Confidence summary:")
        for job, metrics in results.items():
            ptm = metrics['ptm']
            iptm = metrics['iptm']
            ranking = metrics['ranking_score']

            if isinstance(ptm, (int, float)) and isinstance(iptm, (int, float)):
                print(f"    {job}: pTM={ptm:.3f} ipTM={iptm:.3f} "
                      f"ranking={ranking:.3f}")
            else:
                ranking_str = (f"{ranking:.3f}"
                               if isinstance(ranking, (int, float))
                               else str(ranking))
                print(f"    {job}: pTM={ptm} ipTM={iptm} "
                      f"ranking={ranking_str}")
    print("=" * 60)

    sys.exit(0)


if __name__ == "__main__":
    mp.set_start_method('fork', force=True)
    sys.exit(main())

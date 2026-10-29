---
name: crystallography-autoproc
description: Use when processing raw diffraction images with autoPROC (Global Phasing). Covers process command, image import, indexing, integration, scaling, merging, and STARANISO anisotropic analysis. Triggered by autoPROC, process, XDS via autoPROC, CBF/H5 processing pipeline.
---

# autoPROC — Automated Diffraction Data Processing

autoPROC (Global Phasing Ltd.) is an automated pipeline for X-ray
diffraction data processing. It wraps XDS, POINTLESS, AIMLESS, CTRUNCATE,
and STARANISO into a single `process` command with sensible defaults.

## Quick Start

```bash
source <autoPROC_install>/setup.sh
cd <output_dir>
process -I <image_directory>
```

The `setup.sh` script sets `$autoPROC_home`, puts `autoPROC/bin/linux64`
on `$PATH`, and sets required environment variables (CCP4, etc.).

### Minimum Working Example

```bash
source <autoPROC_install>/setup.sh
cd <project_dir>/autoproc_run
process -I ../images -R 50 2.5
```

This will:
1. Index all `.cbf` / `.img` / `.h5` files in `../images`
2. Integrate with XDS
3. Scale and merge with AIMLESS
4. Run STARANISO for anisotropic analysis
5. Generate `summary.html` and `summary.tar.gz`

After success, the output directory contains a full autoPROC run.

## Command Reference

```
USAGE: process \
    [-checkdeps|-check] [-M <macro|file>] [-I <image directory>] [-d <dir>] \
    [-R <reslow> <reshigh>] [-B] [-ref <MTZ file>] [-free <MTZ file>] \
    [-Id <id>,<dir>,<template>,<from>,<to>] \
    [-h5 <master.h5|*.nxs>] [-nthreads <N>]
```

### Core Options

| Flag | Description |
|---|---|
| `-I <dir>` | Directory containing raw diffraction images (default: `.`) |
| `-d <dir>` | Write output to subdirectory `<dir>` instead of `.` |
| `-R <lo> <hi>` | Low- and high-resolution limits (in Angstrom) |
| `-B` | Batch mode: suppress ANSI highlighting on stdout |
| `-M <macro>` | Apply a pre-defined parameter macro; use `-M list` to list available macros |
| `-nthreads <N>` | Number of parallel threads (negative = all available) |

### Dataset Specification

| Flag | Description |
|---|---|
| `-Id id,dir,template,from,to` | Manual scan definition: identifier, directory, filename template (use `?` for frame number), first frame, last frame |
| `-h5 <master.h5>` | Eiger/HDF5 dataset (Dectris or NeXus/NXmx format). Can be repeated for multi-sweep datasets. |

### Reference / Test-Set

| Flag | Description |
|---|---|
| `-ref <MTZ>` | Reference MTZ for space group, cell, indexing, and optional test-set |
| `-free <MTZ>` | Reference MTZ for test-set only (no SG/cell constraints) |

### Dependency Checking

| Flag | Description |
|---|---|
| `-checkdeps` | List all required external programs and exit |
| `-check` | Check all required external programs; exit with error if any missing |

## Output

After a successful run, the following key outputs are produced:

| File | Description |
|---|---|
| `Data_1_autoPROC_STARANISO_all.cif` | Recommended: anisotropic analysis mmCIF (PDB-deposition ready) |
| `Data_2_autoPROC_TRUNCATE_all.cif` | Deprecated: isotropic analysis mmCIF |
| `autoPROC.db` | SQLite database with all processing results |
| `summary.html` | Interactive HTML summary |
| `summary.tar.gz` | Packaged summary with all referenced files |
| `staraniso_alldata-unique.mtz` | STARANISO-processed MTZ |
| `truncate-unique.mtz` | CTRUNCATE-processed MTZ |
| `aimless.mtz` | AIMLESS output (scaled/unmerged) |
| `CORRECT.LP` | XDS CORRECT output |
| `XDS_ASCII.HKL` | Integrated reflections (XDS format) |

The `summary.html` file is the primary deliverable — it contains
interactive plots of:
- Per-image spot count (`SPOT.XDS`)
- Resolution cut-off surface (STARANISO ellipsoid)
- Rmerge / CC1/2 vs. resolution
- Completeness vs. resolution
- Anomalous signal analysis

## Example: MF42 Dataset (CBF, PILATUS3 6M)

```bash
# Activate the environment
source <autoPROC_install>/setup.sh

# Run autoPROC
cd <project_dir>/autoproc_run
process -I ../ -R 50 2.5

# Results (198 sec for 360 frames):
#   Space group: P6322
#   Unit cell: 72.719 72.719 78.649 90.0 90.0 120.0
#   Resolution: 2.957 A  (CC1/2 outer shell = 0.398)
#   Anomalous completeness: 86.9% (spherical)
```

## Integration with xtal-agent

When processing a project with the xtal-agent workflow, autoPROC
can be used in Phase 1 (XDS Processing) as the primary engine.

```bash
source xtal-agent/env/activate.sh
source <autoPROC_install>/setup.sh

# Equivalent to xtal-agent run-phase phase1, but via autoPROC
xtal-agent enforce-checkpoint <project_dir>
xtal-agent guard <project_dir> --before phase1_correct_lp

mkdir -p <project_dir>/autoproc_run
cd <project_dir>/autoproc_run
process -I <project_dir>/cbf -R 50 2.5

xtal-agent guard <project_dir> --after phase1_correct_lp
xtal-agent verify-steps <project_dir>
```

## License

The license file must be placed at `$autoPROC_home/.licence` (note the
British spelling). The file consists of a `#` header line followed by
6 space-separated integers per line (one line per licensed machine).

```bash
cp /path/to/license_file $autoPROC_home/.licence
process -h   # verify: "This software is licenced to : <institution>"
```

Renewal is handled via [Global Phasing's web portal](https://www.globalphasing.com/autoproc/)
using the original Request ID and registered email address.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `Unable to find valid licence` | `.licence` missing or wrong location | Copy to `$autoPROC_home/.licence` |
| `ERROR: licence key file ".licence" not found` | Same as above | Same as above |
| `module 'XDS.INP' not found` | autoPROC can't read images | Check `-I <dir>` path; verify file naming pattern |
| `Indexing failed` | Poor diffraction, wrong resolution range | Try `-R 50 8` to restrict to low-resolution only |
| `Summary HTML has missing plots` | `gnuplot` not installed | `apt-get install gnuplot` or equivalent |

## References

- [autoPROC Home](https://www.globalphasing.com/autoproc/)
- [autoPROC Wiki](https://www.globalphasing.com/autoproc/wiki/)
- [Installation Guide](https://www.globalphasing.com/autoproc/wiki/index.cgi?AutoProcInstallation)
- [Licensing](https://www.globalphasing.com/autoproc/wiki/index.cgi?AutoProcLicensing)
- Vonrhein et al. (2011) *Acta Cryst.* D67, 293-302
- Tickle et al. (2018) *Acta Cryst.* D74, 1060-1072 (STARANISO)

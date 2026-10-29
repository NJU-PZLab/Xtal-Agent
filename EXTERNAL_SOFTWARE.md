# External Software

## Scope Rule

This package does not redistribute any third-party crystallography software.

It only documents which external software families the `xtal-agent` workflow expects, where users should obtain them, and how those tools should be integrated into a user-managed environment.

## Publication Boundary

This repository publishes:

- the `xtal-agent` code
- workflow documentation
- skill and deployment documentation
- integration instructions for external software

This repository does not publish:

- third-party crystallography software binaries
- third-party source archives
- vendor installers
- repackaged mirrors of upstream software

Users must obtain and install each software package from its official source and under its own license terms.

## Integration Rule

External software must be discoverable by the agent through one of these methods:

1. the command is available on the user's `PATH`
2. the user configures their environment so the command resolves correctly before running the agent

Local install paths used in the original development environment are examples only. They are not part of the public contract for this agent.

## External Software Families

The complete dependency surface has two groups:

1. crystallography software used by the main diffraction, scaling, MR, refinement, and validation workflow
2. AI/prediction runtime dependencies used by bundled workflow skills such as `msa-generator`, `af2-predictor`, and `alphafold3-predictor`

## Crystallography Software

### DIALS

Purpose in workflow:
- diffraction data import, spot finding, indexing, integration, scaling, and MTZ export when the DIALS path is used
- optional fallback renderer for the vision module when adxv is not available

Requirement level:
- required for workflows that need the DIALS fallback or DIALS branch comparison

Official source to consult:
- DIALS official installation and documentation channels

Integration expectation:
- commands such as `dials.import` and related DIALS executables must resolve in the user environment

### adxv (vision-module rendering backend, optional)

Purpose in workflow:
- preferred headless renderer for the vision module; draws resolution rings
  directly from the CBF/H5 header geometry (`-rings -rfont ...`)
- supports slab (`-slabs N`) and corner-crop (`-sa_crop WxH+X+Y`) views
- used by `xtal-agent vision-scan` when present

Requirement level:
- optional — the vision module falls back to `dials.export_bitmaps` or
  `fabio` + matplotlib. With adxv unavailable, vision_scan still runs but
  with less accurate rings.

Official source to consult:
- https://www.scripps.edu/tainer/arvai/adxv.html (Scripps Research)

Integration expectation:
- the binary `adxv` must resolve on `$PATH`; it is **not** redistributed
  with this package, so install it from the official source
- if `adxv` is absent, the vision module falls back to DIALS or fabio
- adxv is an X11/Motif program; headless invocation MUST be wrapped with
  `xvfb-run -a adxv ...` (handled automatically by `vision_render._render_with_adxv`)
- the Pillow, fabio, and hdf5plugin Python packages must be importable for
  the dials/fabio fallback renderers

### CCP4

Purpose in workflow:
- Pointless, Aimless, Refmac, Matthews coefficient calculation, mtzdump, freerflag, ctruncate, and other CCP4-backed crystallographic processing steps

Requirement level:
- required for the standard crystallographic workflow defined by the repository

Official source to consult:
- CCP4 official distribution and documentation channels

Integration expectation:
- commands such as `pointless`, `aimless`, `refmac5`, `matthews_coef`, `mtzdump`, `freerflag`, and `ctruncate` must resolve in the user environment

### Phenix

Purpose in workflow:
- molecular replacement, xtriage, refinement, validation, and MolProbity-related reporting paths used by the agent

Requirement level:
- required for the standard workflow defined by the repository

Official source to consult:
- Phenix official distribution and documentation channels

Integration expectation:
- commands such as `phenix.phaser`, `phenix.refine`, `phenix.xtriage`, and `phenix.version` must resolve in the user environment

### XDS

Purpose in workflow:
- raw-image processing path and XDS-based indexing/integration/correction steps

Requirement level:
- required for XDS-based raw image workflows

Official source to consult:
- XDS official distribution and documentation channels

Integration expectation:
- commands such as `xds_par` must resolve in the user environment

### Coot

Purpose in workflow:
- **automatic post-refinement module**: after the refinement R-free plateaus,
  MolProbity-guided COOT scripts correct rotamer outliers, perform
  electron-density-guided real-space fitting, and add ordered waters;
  the model is then re-refined and re-validated
- interactive model inspection and manual follow-up when needed

Requirement level:
- **enabled by default** for the post-refinement module
- can be disabled per project with `coot: {enabled: false}` in `manifest.yaml`
- if COOT is unavailable the module is skipped with a recorded warning

Version and mode:
- tested with COOT 0.9.8.x
- headless invocation uses `coot --no-graphics -s <script> --no-guano`
- the embedded COOT Python interpreter is Python 2.7; do not import the
  host Python modules from COOT scripts

Official source to consult:
- Coot official distribution and documentation channels

Integration expectation:
- the `coot` executable must resolve in the user environment
- optional explicit locations:
  - `XTAL_AGENT_COOT_BIN=/path/to/coot`
  - `XTAL_AGENT_COOT_SCRIPTS=/path/to/skills/crystallography-coot-refinement/scripts`
  - `XTAL_AGENT_PHENIX_BIN=/path/to/phenix.refine`
  - `XTAL_AGENT_CCP4_SETUP=/path/to/ccp4.setup-sh`

## AI And Prediction Runtime Dependencies

### colabfold_search

Purpose in workflow:
- MSA generation for bundled `msa-generator`

Requirement level:
- required when using the bundled MSA generation workflow

Official source to consult:
- ColabFold official installation and documentation channels

Integration expectation:
- `colabfold_search` must resolve in the user environment or be provided through the `COLABFOLD_SEARCH` environment variable

### colabfold_batch

Purpose in workflow:
- AlphaFold2 prediction for bundled `af2-predictor`

Requirement level:
- required when using the bundled AlphaFold2 prediction workflow

Official source to consult:
- ColabFold official installation and documentation channels

Integration expectation:
- `colabfold_batch` must resolve in the user environment or be provided through the `COLABFOLD_BATCH` environment variable

### AlphaFold2 Data Directory

Purpose in workflow:
- model and database data required by bundled `af2-predictor`

Requirement level:
- required when using the bundled AlphaFold2 prediction workflow

Official source to consult:
- AlphaFold2 or ColabFold official setup documentation

Integration expectation:
- user must provide the path via `--af2-data` or the `AF2_DATA_DIR` environment variable

### AlphaFold3 Runtime

Purpose in workflow:
- structure prediction for bundled `alphafold3-predictor`

Requirement level:
- required when using the bundled AlphaFold3 workflow

Official source to consult:
- AlphaFold3 official installation and documentation channels

Integration expectation:
- user must provide environment configuration for:
  - `AF3_PYTHON`
  - `AF3_RUN_SCRIPT`
  - `AF3_MODEL_DIR`
  - `AF3_DB_DIR`
  - `AF3_BIN_DIR`

## Operational Rule

The supported public deployment model is:

- users install external crystallography software themselves
- users install AI/prediction runtime dependencies themselves when they intend to use bundled prediction skills
- users connect those tools to `xtal-agent` through environment setup
- users verify availability with `xtal-agent check-env`

If a required command is missing, the environment is incomplete and must be fixed before running workflow phases.

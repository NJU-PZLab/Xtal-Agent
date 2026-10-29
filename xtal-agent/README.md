# Xtal-Agent

Local MVP for AI-assisted protein crystallography workflow automation.

The first version focuses on molecular replacement projects with:

- diffraction data as raw images or existing MTZ files
- FASTA sequence
- AlphaFold or homolog PDB/mmCIF search models

The MVP provides:

- manifest validation
- local crystallography software checks (including COOT)
- structured stage-result schemas
- simple Phaser/refinement log parsing
- deterministic candidate ranking
- HTML report generation
- Snakemake workflow skeleton
- COOT post-refinement module (rotamer correction, real-space fitting,
  ordered-water addition, Rfree/geometry adjudication)
- vision module for raw diffraction-frame inspection (`vision-scan`,
  `vision-validate`)

## Setup

```bash
conda create -n xtal-agent python=3.11
conda activate xtal-agent
pip install -e '.[dev,vision]'
```

External crystallography tools should be installed separately:

- DIALS
- CCP4
- Phenix
- COOT 0.9.8.x (headless mode; enabled by default for post-refinement)
- XDS, optional for MVP
- adxv / fabio, optional for vision rendering

COOT is enabled by default. If it is not on `PATH`, set:

```bash
export XTAL_AGENT_COOT_BIN=/path/to/coot
export XTAL_AGENT_COOT_SCRIPTS=/path/to/skills/crystallography-coot-refinement/scripts
export XTAL_AGENT_PHENIX_BIN=/path/to/phenix.refine
export XTAL_AGENT_CCP4_SETUP=/path/to/ccp4.setup-sh
```

## Commands

```bash
xtal-agent check-env
xtal-agent validate-manifest projects/example_project/manifest.yaml
xtal-agent vision-scan projects/example_project
xtal-agent vision-validate projects/example_project
xtal-agent coot-optimize projects/example_project
```

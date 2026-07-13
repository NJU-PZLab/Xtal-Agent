# Crystal Agent

Local MVP for AI-assisted protein crystallography workflow automation.

The first version focuses on molecular replacement projects with:

- diffraction data as raw images or existing MTZ files
- FASTA sequence
- AlphaFold or homolog PDB/mmCIF search models

The MVP provides:

- manifest validation
- local crystallography software checks
- structured stage-result schemas
- simple Phaser/refinement log parsing
- deterministic candidate ranking
- HTML report generation
- Snakemake workflow skeleton

## Setup

```bash
conda create -n crystal-agent python=3.11
conda activate crystal-agent
pip install -e '.[dev]'
```

External crystallography tools should be installed separately:

- DIALS
- CCP4
- Phenix
- XDS, optional for MVP
- Coot, optional for MVP

## Commands

```bash
crystal-agent check-env
crystal-agent validate-manifest projects/example_project/manifest.yaml
```

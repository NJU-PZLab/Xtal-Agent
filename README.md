# Xtal-Agent Publication Package

This package is a publication-oriented full local-deployable bundle of the `xtal-agent` repository.

It is organized to match the structure defined by the agent's own code and operating documents, rather than an ad hoc grouping. The four sections used here are:

- code
- templates
- documentation
- skills

This package does not modify the original project files. It is a generated
publication bundle that includes the agent source tree, required workflow
skills, and deployment documentation.

## Features (v0.2.0)

- **COOT post-refinement module** — after the refinement R-free plateaus, the
  agent runs MolProbity-guided COOT scripts for rotamer correction,
  electron-density-guided real-space fitting, and ordered-water addition,
  followed by re-refinement and re-validation. A COOT model is kept only when
  R-free does not increase and geometry improves.
- **Vision module** — renders raw diffraction frames (adxv / DIALS / fabio),
  supports `vision-scan` and `vision-validate`, and writes a validated
  `vision_report.json` for Phase 0 image inspection.
- Both modules are optional at runtime and can be disabled in `manifest.yaml`;
  COOT is enabled by default.

## Source Of Truth

The structure in this package is derived from the following repository sources:

- `xtal-agent/pyproject.toml`
- `AGENTS.md`
- `xtal-agent/README.md`
- `docs/agent_architecture_coverage_audit.md`
- `xtal-agent/src/xtal_agent/architecture.py`
- `xtal-agent/src/xtal_agent/cli.py`

## Package Contents

- `CODE.md`: packaged code surface and runtime modules
- `TEMPLATES.md`: runtime template assets and code-backed template registries
- `DOCUMENTATION.md`: operator docs, package docs, and architecture docs
- `SKILLS.md`: all skills required by the workflow, including bundled skill code copied into this package
- `EXTERNAL_SOFTWARE.md`: third-party crystallography software inventory and integration boundary
- `DEPLOYMENT.md`: public deployment model, path rules, and environment check flow
- `AGENTS.md`: primary operating manual copied into the bundle
- `skills/`: repository workflow skills copied into the bundle
- `xtal-agent/`: main local-deployable agent package, including source, templates, env, tests, workflows, and package metadata
- `docs/`: selected documentation copied into the bundle
- `vendored_skills/`: bundled skill code and assets required by the workflow
- `STRUCTURE.json`: machine-readable structure summary

## Notes

## Environment Requirements

Required for the standard crystallography workflow:

- Python 3.11
- XDS and/or DIALS
- CCP4 (Pointless, Aimless, Refmac5, mtzdump, freerflag, ctruncate)
- Phenix (phaser, refine, xtriage, molprobity)
- COOT 0.9.8.x with headless mode (`coot --no-graphics -s <script>`)

Optional:

- adxv, or DIALS / fabio, for vision rendering
- AlphaFold2/ColabFold and AlphaFold3 runtimes for bundled prediction skills

COOT/Phenix/CCP4 can be located through `PATH` or explicitly via:

```bash
export XTAL_AGENT_COOT_BIN=/path/to/coot
export XTAL_AGENT_PHENIX_BIN=/path/to/phenix.refine
export XTAL_AGENT_CCP4_SETUP=/path/to/ccp4.setup-sh
export XTAL_AGENT_COOT_SCRIPTS=/path/to/skills/crystallography-coot-refinement/scripts
```

- All workflow-required skills are documented in `SKILLS.md`.
- Skill code and assets that were not originally stored in the repository are bundled into `vendored_skills/` in this publication package.
- The main agent source code is included under `xtal-agent/` so the bundle is locally deployable.
- External crystallography software is documented as a runtime dependency but is not redistributed by this package.
- Original local installation paths are not part of the public deployment contract; public users should rely on `PATH` or their own environment configuration.
- External crystallography software binaries and installers are intentionally excluded from this publication package.

## Quick Deployment

After extracting this bundle into a local working directory:

1. enter the bundled Python package directory and install the agent locally:

```bash
cd xtal-agent
pip install -e .
cd ..
```

2. make sure the bundled skill directories are available to your LLM workflow:
- repository skills are included under `skills/`
- bundled vendored skills are included under `vendored_skills/`

3. start the agent from that local path
4. instruct the LLM to read `EXTERNAL_SOFTWARE.md`
5. provide the LLM with the local installation paths or environment details for each required software package
6. let the LLM use those user-provided paths to guide environment configuration
7. activate the bundled environment script:

```bash
source xtal-agent/env/activate.sh
```

8. continue with environment verification and deployment steps from `DEPLOYMENT.md`

Important:
- this package does not assume the original development paths
- the user must provide local software locations for externally installed tools
- the Python package must be installed locally before using the `xtal-agent` CLI
- deployment is complete only after the local environment has been configured against those user-provided software paths

# Code

## Scope Rule

This section includes the code surface that the repository itself defines as part of the agent through packaging, CLI wiring, orchestration, and architecture helpers.

## Packaging Entry

### `xtal-agent/pyproject.toml`

Role:
- Defines the installable Python project `xtal-agent`
- Registers the console entry point `xtal-agent = "xtal_agent.cli:app"`
- Declares package discovery from `src`

Why this belongs in code:
- It is the canonical packaging boundary for the agent runtime.

### `xtal-agent/env/`

Role:
- Activation helpers for the packaged agent environment

Why this belongs in code:
- the operating manual and deployment flow explicitly use `xtal-agent/env/activate.sh`

### `xtal-agent/tests/`

Role:
- Automated verification suite for the packaged agent

Why this belongs in code:
- it is part of the locally deployable source bundle and is required for verification and maintenance workflows

### `xtal-agent/workflows/`

Role:
- Workflow scaffolding included with the packaged agent

Why this belongs in code:
- it ships with the local deployable package and is part of the repository's agent implementation surface

## Core Package

### `xtal-agent/src/xtal_agent/`

Role:
- Main packaged Python code for the agent

Why this belongs in code:
- `pyproject.toml` discovers packages from `src`
- `cli.py` is the public CLI entry surface
- workflow, guards, architecture audit, command templates, and phase logic all live here

## Key Runtime Modules

### `xtal-agent/src/xtal_agent/coot_runner.py`

Role:
- COOT post-refinement module wrapper
- generates the COOT strategy config, invokes the bundled
  `crystallography-coot-refinement` skill, parses `strategy_summary.json`,
  and applies the Rfree/geometry acceptance rule

### `xtal-agent/src/xtal_agent/vision_schema.py`

Role:
- Pydantic schema and validation for `vision_report.json`

### `xtal-agent/src/xtal_agent/vision_render.py`

Role:
- headless rendering of raw diffraction frames for multimodal inspection
  (adxv, DIALS, or fabio fallback)

### `xtal-agent/src/xtal_agent/cli.py`

Role:
- Public CLI command registration

Exposes commands used throughout the docs:
- `validate-manifest`
- `check-env`
- `check-gpu`
- `run-pipeline`
- `run-phase`
- `map-ligand-atoms`
- `verify-steps`
- `guard`
- `expert-approve`
- `backup-targets`
- `audit-architecture`
- `phase-guide`
- `command-template`
- `list-command-templates`
- `naming-guide`
- `enforce-checkpoint`
- `resume-barrier`
- `vision-scan`
- `vision-validate`
- `coot-optimize`

### `xtal-agent/src/xtal_agent/architecture.py`

Role:
- Code-backed architecture registry

Owns:
- command templates
- phase guides
- naming conventions
- backup target collection
- architecture audit rules

This file is part of the agent's functional structure, not just metadata.

### `xtal-agent/src/xtal_agent/step_tracker.py`

Role:
- Step verification and guard enforcement

Owns:
- `verify-steps`
- checkpoint enforcement
- guard state tracking
- expert approval consumption checks

### `xtal-agent/src/xtal_agent/phase_orchestrator.py`

Role:
- Phase-by-phase execution wiring

Owns:
- orchestrated `phase1` to `phase5_lowres`
- mandatory decision-engine call paths required by the docs

### `xtal-agent/src/xtal_agent/decision_engine.py`

Role:
- Evidence-based branch and recovery decisions

Referenced by docs for:
- IDXREF failure handling
- data-range selection
- SG conflict handling
- Matthews copy range
- MR troubleshooting
- refinement branching

### `xtal-agent/src/xtal_agent/pipeline.py`

Role:
- Autonomous pipeline runner and report producer

### `xtal-agent/src/xtal_agent/report.py`

Role:
- HTML report rendering from Jinja template

### `xtal-agent/src/xtal_agent/manifest.py`

Role:
- Manifest loading and validation

### `xtal-agent/src/xtal_agent/schemas.py`

Role:
- Typed manifest, workflow, and result schemas

### `xtal-agent/src/xtal_agent/map_ligand_atoms.py`

Role:
- AF3-to-CCP4 ligand atom mapping helper

### `xtal-agent/src/xtal_agent/generate_XDS.INP`

Role:
- XDS input generation helper referenced by Phase 1 command templates

## Additional Runtime Support Modules

The following modules are part of the packaged code surface and support the main workflow:

- `xtal-agent/src/xtal_agent/envcheck.py`
- `xtal-agent/src/xtal_agent/parsers.py`
- `xtal-agent/src/xtal_agent/phaser_runner.py`
- `xtal-agent/src/xtal_agent/refinement_runner.py`
- `xtal-agent/src/xtal_agent/ranking.py`
- `xtal-agent/src/xtal_agent/runner.py`
- `xtal-agent/src/xtal_agent/workflow.py`

## Structure Summary

The publication structure for code is therefore:

```text
xtal-agent/
├── env/
├── pyproject.toml
├── src/
│   └── xtal_agent/
├── templates/
├── tests/
└── workflows/
```

Everything in this section is in-repo.

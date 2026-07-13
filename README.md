# Crystal Agent Publication Package

This package is a publication-oriented full local-deployable bundle of the `crystal-agent` repository.

It is organized to match the structure defined by the agent's own code and operating documents, rather than an ad hoc grouping. The four sections used here are:

- code
- templates
- documentation
- skills

This package does not modify the original project files. It is a generated publication bundle that includes the agent source tree, required workflow skills, and deployment documentation.

## Source Of Truth

The structure in this package is derived from the following repository sources:

- `xtal-agent/pyproject.toml`
- `AGENTS.md`
- `xtal-agent/README.md`
- `docs/agent_architecture_coverage_audit.md`
- `xtal-agent/src/crystal_agent/architecture.py`
- `xtal-agent/src/crystal_agent/cli.py`

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
- the Python package must be installed locally before using the `crystal-agent` CLI
- deployment is complete only after the local environment has been configured against those user-provided software paths

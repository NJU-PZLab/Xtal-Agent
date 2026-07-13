# Deployment

## Goal

Help external users run `crystal-agent` without redistributing any third-party crystallography software and without requiring the original development paths.

## Supported Public Deployment Model

The public deployment model for this project is:

1. install `crystal-agent`
2. install third-party crystallography software from official upstream sources
3. install AI/prediction runtime dependencies if using bundled MSA/AF2/AF3 skills
3. expose those tools to the runtime environment
4. run environment checks before starting workflow execution

## Non-Redistribution Rule

This project does not ship or mirror:

- CCP4
- Phenix
- DIALS
- XDS
- Coot
- ColabFold executables
- AlphaFold2 data directories
- AlphaFold3 runtime, weights, or databases
- any other third-party crystallography software

Users are responsible for obtaining those tools from official sources and complying with their license terms.

## Path Rule

Do not treat the original development machine paths as public requirements.

Public deployments should assume only this contract:

1. required commands are available on `PATH`
2. or the user has configured their shell or environment so those commands resolve correctly before agent execution

This means a user may install software in:

- a workstation conda environment
- a lab-managed shared filesystem
- a module-managed HPC environment
- another user-controlled location

As long as the required commands resolve, the deployment is compatible with the public agent contract.

## Recommended User Flow

### 1. Install the agent

Follow the package setup documented by the repository for `crystal-agent` itself.

### 2. Install external software from official sources

Use the software inventory in `EXTERNAL_SOFTWARE.md` to identify:

- crystallography software required by the main workflow
- AI/prediction runtime dependencies required by bundled `msa-generator`, `af2-predictor`, and `alphafold3-predictor`

### 3. Expose the tools in the environment

Recommended approach:
- make required commands available on `PATH`

Alternative approach:
- source the user's own shell/module/environment activation scripts before using the agent

For bundled prediction skills, users may also need to set environment variables such as:

- `MSA_DBBASE`
- `COLABFOLD_SEARCH`
- `COLABFOLD_BATCH`
- `AF2_DATA_DIR`
- `AF3_PYTHON`
- `AF3_RUN_SCRIPT`
- `AF3_MODEL_DIR`
- `AF3_DB_DIR`
- `AF3_BIN_DIR`

### 4. Run environment checks

Before workflow execution, run:

```bash
source xtal-agent/env/activate.sh
crystal-agent check-env
```

If a required command is missing, fix the user environment first.

### 5. Run workflow-specific gates

After environment setup succeeds, continue with the repository's documented execution gate and workflow process.

## Troubleshooting Rule

If a command listed by `check-env` does not resolve:

1. verify the corresponding third-party software is actually installed
2. verify the command is exposed on `PATH` or by the user's activation process
3. rerun `crystal-agent check-env`
4. only continue when the environment check confirms the required commands are available

If a bundled prediction skill fails due to missing model/database/runtime configuration:

1. verify the corresponding runtime dependency is installed
2. verify the required environment variables are set or command-line arguments are provided
3. rerun the skill command

## Relationship To Skills

External crystallography software is a runtime dependency class.

It is not the same thing as:

- workflow skills documented in `SKILLS.md`
- bundled workflow skill code shipped in `vendored_skills/`

The workflow therefore has two separate dependency layers:

1. software tools used by crystallographic commands
2. skill resources and bundled skill code used by the agent reasoning and orchestration layer

# Documentation

## Scope Rule

This section includes the operating manuals, package-facing documentation, and architecture documentation that define how the agent is supposed to be used and maintained.

## Primary Operating Manual

### `AGENTS.md`

Role:
- Main operating manual for the crystallography agent

Defines:
- execution gate
- workflow mode gate
- hard rules
- phase checklist
- diagnostic triggers
- command hygiene
- architecture maintenance rules

Why it belongs in documentation:
- it is the highest-level repo document describing the intended agent behavior and structure

## Package Documentation

### `xtal-agent/README.md`

Role:
- Package-level introduction to the installable `crystal-agent`

Documents:
- project scope
- setup
- external crystallography software requirements
- basic commands

Publication note:
- this is the package-level README for the installable `crystal-agent` Python package, not the repository-wide publication README

### `xtal-agent/AGENTS.md`

Role:
- package-local mirrored operating manual copied with the bundled source tree

Why it belongs in documentation:
- it ships inside the bundled `xtal-agent/` tree and may be used by tools or users working inside that subtree

## Architecture Documentation

### `docs/agent_architecture_coverage_audit.md`

Role:
- Crosswalk between AGENTS rules, skill files, mirrored phase docs, and code-backed checks

Why it is important for publication:
- it is the clearest explicit statement that the agent structure spans:
  - `AGENTS.md`
  - `skills/*.md`
  - `xtal-agent/skills/phase*.md`
  - bundled workflow skill assets when needed for execution completeness
  - `crystal_agent.architecture`
  - `crystal_agent.step_tracker`

## Publication Package Deployment Documentation

The generated publication package adds two deployment-facing documents so external users can understand runtime prerequisites without changing the repository's internal structure.

### `EXTERNAL_SOFTWARE.md`

Role:
- publication-facing inventory of third-party crystallography software required by the workflow

Why it belongs in documentation:
- it explains the non-redistribution boundary
- it lists upstream software families and integration expectations
- it separates runtime software dependencies from repository-owned code and skills

### `DEPLOYMENT.md`

Role:
- publication-facing deployment guide for external users

Why it belongs in documentation:
- it explains the supported public deployment model
- it removes any assumption that original local paths are public requirements
- it defines the environment-check flow using `crystal-agent check-env`

## Documentation Trees Included In The Agent Surface

### `docs/`

Role:
- Architecture-scanned documentation tree

Why it belongs:
- `xtal-agent/src/crystal_agent/architecture.py` scans `docs/` when collecting markdown for architecture audit coverage

### `example/`

Role:
- Example/reference project material included in protected backup targets

Why it belongs:
- `architecture.py` includes `example` in `BACKUP_INCLUDE_NAMES`

## Structure Summary

```text
.
├── AGENTS.md
├── skills/
├── docs/
│   └── agent_architecture_coverage_audit.md
└── xtal-agent/
    ├── AGENTS.md
    └── README.md
```

Everything in this section is included from in-repo sources.

The two deployment documents are generated publication-package documents, not original repository source documents.

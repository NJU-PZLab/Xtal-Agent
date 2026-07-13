# Templates

## Scope Rule

This section includes on-disk template assets that the runtime loads as templates, plus the code-backed template registry that the CLI exposes through `command-template` and `list-command-templates`.

## Runtime Template Files

### `xtal-agent/templates/report.html.j2`

Role:
- Jinja2 template used to render the validation HTML report

Why this belongs in templates:
- `xtal-agent/src/crystal_agent/report.py` loads templates from the package-adjacent `templates` directory
- the template name is referenced explicitly as `report.html.j2`

## Code-Backed Template Registry

### `xtal-agent/src/crystal_agent/architecture.py`

Role:
- Stores the `COMMAND_TEMPLATES` registry used by:
  - `crystal-agent command-template <operation>`
  - `crystal-agent list-command-templates`

Important publication note:
- These command templates are part of the agent's template system, but they are defined in code rather than as standalone files.
- For publication consistency, they are documented here as template infrastructure while the file itself remains listed under `CODE.md` as packaged code.

Representative command-template families defined there include:

- XDS and DIALS setup and execution
- Aimless and mtzdump validation
- Matthews coefficient calculation
- Phaser MR
- xtriage
- Phenix and Refmac refinement rounds
- Modelcraft and MolProbity helpers

## Structure Summary

```text
xtal-agent/
├── templates/
│   └── report.html.j2
└── src/crystal_agent/architecture.py  # code-backed command-template registry
```

Everything in this section is in-repo.

In this publication bundle, the full `xtal-agent/templates/` directory is included so the package can be deployed locally.

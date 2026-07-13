---
name: crystallography-mr-refine
description: Legacy compatibility wrapper. Use only when older docs or user text explicitly names crystallography-mr-refine; otherwise use phase3, phase4, phase5, or phase6 crystallography skills.
---

# Legacy Wrapper: MR and Refinement

This skill is kept only for backward compatibility with older references.

For current work, immediately use the specific phase skill:

| Need | Current skill | Code call |
|---|---|---|
| Search model, MSA, AF2/AF3, pLDDT, Matthews | `crystallography-phase3-model-preparation` | `crystal-agent phase-guide phase3` |
| Phaser and ASU copy-number testing | `crystallography-phase4-molecular-replacement` | `crystal-agent phase-guide phase4` |
| Phenix/Refmac refinement, waters, TLS, RSCC | `crystallography-phase5-refinement` | `crystal-agent phase-guide phase5` |
| Final MolProbity, comparison, final archive | `crystallography-phase6-final-validation` | `crystal-agent phase-guide phase6` |

Do not continue from this wrapper. The canonical workflows now live in the phase-specific skills and `crystal-agent phase-guide phase<N>`.

# Changelog

## 0.2.0

### Added

- COOT post-refinement module (`xtal_agent.coot_runner`) with a bundled
  `crystallography-coot-refinement` skill: MolProbity-guided rotamer
  correction, real-space density fitting, ordered-water addition, and
  Rfree/geometry-based accept-or-fallback adjudication.
- Phase 5 hook that runs the COOT module after refinement reaches a plateau.
- `xtal-agent coot-optimize` CLI command.
- COOT module step in `verify-steps`.
- Vision module (diffraction-frame rendering, `vision-scan`,
  `vision-validate`, `vision_report.json`, Phase 0 image-inspection skill)
  is now part of the released package.
- Optional `vision` dependency extra (Pillow, matplotlib, fabio, h5py,
  hdf5plugin).

### Changed

- Manifest gains an optional `coot` block; COOT is enabled by default.
- COOT, Phenix, and CCP4 binaries can be configured with
  `XTAL_AGENT_COOT_BIN`, `XTAL_AGENT_PHENIX_BIN`, and
  `XTAL_AGENT_CCP4_SETUP` instead of hard-coded development paths.
- Environment check covers `coot --version` alongside the existing
  crystallography tools.
- Version bumped to 0.2.0; package name is `xtal-agent` / import name
  `xtal_agent`.

# Agent Architecture Coverage Audit

This audit maps mandatory rules from the previous `AGENTS.md` into the simplified operating manual, code-backed skills, and helper commands.

## Summary

- `AGENTS.md` now holds the hard gates, workflow mode requirements, thresholds, phase checklist, diagnostic triggers, and maintenance rules.
- `skills/*.md` now hold task-specific workflow instructions and required code calls.
- `xtal-agent/skills/phase*.md` mirror phase-level checklists for local reference.
- `crystal_agent.architecture` provides `backup-targets`, `phase-guide`, and `audit-architecture` command support.
- `crystal_agent.step_tracker` continues to enforce project step completion through `verify-steps` and `guard`.

## Mandatory Rule Mapping

| Previous mandatory rule or detail | New `AGENTS.md` location | New SKILL location | Code/check location |
|---|---|---|---|
| Backup before editing docs, records, skills, or code | Section 0 | `crystallography-mainline` Required First Calls | `collect_backup_targets`, `backup-targets` |
| Run `verify-steps` after every project step | Section 1 | all crystallography skills | `StepTracker`, `verify-steps` |
| Use `guard --before/--after` around phases | Section 1 | all phase skills | `Guard`, `guard` |
| Never skip IDXREF | Sections 2 and 7 Phase 1 | `crystallography-raw-processing`, phase1 doc | `phase-guide phase1`, `StepTracker` Phase 1 checks |
| IDXREF failure response | Section 7 Phase 1 | `crystallography-raw-processing`, phase1 doc | `phase-guide phase1` |
| Generate `XDS.INP` from CBF headers | Section 7 Phase 1 | `crystallography-raw-processing`, phase1 doc | `generate_XDS.INP`, `phase-guide phase1` |
| Round 1 SG=0 then feed SG/cell back for round 2 | Section 7 Phase 1 | `crystallography-raw-processing`, phase1 doc | `phase-guide phase1` |
| Inspect `INTEGRATE.LP` and `CORRECT.LP` before parameter changes | Section 7 Phase 1 | `crystallography-raw-processing`, phase1 doc | `phase-guide phase1` |
| Optimize `DATA_RANGE` only by shrinking/shifting | Section 7 Phase 1 | `crystallography-raw-processing`, phase1 doc | `phase-guide phase1` |
| Push resolution by 0.2-0.3 A while I/SIGMA passes | Section 7 Phase 1 | `crystallography-raw-processing`, phase1 doc | `phase-guide phase1` |
| xia2 fallback after XDS/DIALS failure | Section 7 Phase 1 | `crystallography-raw-processing`, phase1 doc | manual command from skill |
| Fixed AIMLESS outer-shell thresholds | Section 3 and Phase 2 | `crystallography-aimless-validation`, phase2 doc | `phase-guide phase2`, `audit-architecture` |
| Overall and inner shell thresholds | Section 3 and Phase 2 | `crystallography-aimless-validation`, phase2 doc | `phase-guide phase2` |
| Completeness exception when frames < 180 | Section 3 | `crystallography-aimless-validation`, phase2 doc | `phase-guide phase2` |
| Never use invalid-resolution data downstream | Sections 2 and 7 Phase 2 | `crystallography-aimless-validation`, `crystallography-mr-refine` | `audit-architecture`, `phase-guide phase2` |
| Unique filenames during resolution scans | Section 7 Phase 2 | `crystallography-aimless-validation` | skill instruction |
| `mtzdump` after aimless, ctruncate, freerflag, seed | Sections 3 and 7 Phase 2 | `crystallography-aimless-validation`, phase2 doc | `phase-guide phase2` |
| Alternative SG testing when confidence is low or absences ambiguous | Section 7 Phase 2 | `crystallography-aimless-validation` | skill instruction |
| Workflow mode must be explicit | Section 4 | `crystallography-mainline` | `validate-manifest` |
| Simple-mode hard stops | Section 4 | `crystallography-mainline`, `crystallography-mr-refine` | manifest validation plus manual stop |
| Required inputs | Section 5 | `crystallography-mainline` | manifest schema where available |
| Ask for metal species/count | Section 5 | `crystallography-mr-refine` | skill stop gate |
| Ask for glycosylation sites/composition | Section 5 | `crystallography-mr-refine` | skill stop gate |
| FASTA with multiple proteins requires stoichiometry clarification | Section 5 | `crystallography-mr-refine` | skill stop gate |
| Protein-DNA/RNA must use AF3 complex prediction | Sections 5 and 7 Phase 3 | `crystallography-mr-refine`, phase3 doc | `phase-guide phase3` |
| Glycoprotein must use AF3 | Sections 5 and 7 Phase 3 | `crystallography-mr-refine`, phase3 doc | `phase-guide phase3` |
| Unsupported metalloprotein ions are hard stops | Sections 4 and 7 Phase 3 | `crystallography-mr-refine`, phase3 doc | `phase-guide phase3` |
| Generate MSA for each chain | Section 7 Phase 3 | `crystallography-mr-refine`, phase3 doc | `phase-guide phase3` |
| Verify `.done.txt` and top-ranked model | Section 7 Phase 3 | `crystallography-mr-refine`, phase3 doc | `StepTracker` Phase 3 checks |
| Strip pLDDT < 70 residues | Section 7 Phase 3 | `crystallography-mr-refine`, phase3 doc | `StepTracker` `search_model.pdb` check |
| Strip terminal tags | Section 7 Phase 3 | `crystallography-mr-refine`, phase3 doc | `StepTracker` tag-strip check |
| Calculate Matthews before MR | Section 7 Phase 3 | `crystallography-mr-refine`, phase3 doc | `StepTracker` `matthews.log` check |
| Use validated truncated MTZ for MR | Section 7 Phase 4 | `crystallography-mr-refine`, phase4 doc | `phase-guide phase4` |
| Test all plausible copy numbers | Section 7 Phase 4 | `crystallography-mr-refine`, phase4 doc | `StepTracker` `_check_all_copies` |
| Save every Phaser run with unique root/log | Section 7 Phase 4 | `crystallography-mr-refine`, phase4 doc | `phase-guide phase4` |
| Record TFZ, LLG, RFZ, PAK, all placed, packing | Section 7 Phase 4 | `crystallography-mr-refine`, phase4 doc | `StepTracker` Phaser checks |
| Prefer TFZ > 8, LLG > 200, PAK = 0 | Section 7 Phase 4 | `crystallography-mr-refine`, phase4 doc | `StepTracker` `_check_phaser_stats` and `_check_phaser_pak` |
| Strong MR with Rfree > 0.35 triggers xtriage before autobuild | Sections 7 Phase 4 and 8 | `crystallography-mr-refine`, phase4 doc | `phase-guide phase4`, `StepTracker` xtriage check |
| 4+ Phenix rounds | Section 7 Phase 5 | `crystallography-mr-refine`, phase5 doc | `phase-guide phase5`, `StepTracker` Phase 5 |
| 4+ Refmac rounds | Section 7 Phase 5 | `crystallography-mr-refine`, phase5 doc | `phase-guide phase5`, `StepTracker` Phase 5 |
| Refmac rounds 1-2 jelly, 3+ no jelly | Section 7 Phase 5 | `crystallography-mr-refine`, phase5 doc | `phase-guide phase5`, `StepTracker` Phase 5 |
| Continue winning branch until Rfree flat for two rounds | Section 7 Phase 5 | `crystallography-mr-refine`, phase5 doc | `phase-guide phase5` |
| Every round uses immediately preceding PDB and companion MTZ | Section 7 Phase 5 | `crystallography-mr-refine`, phase5 doc | `phase-guide phase5`, `audit-architecture` |
| Cross-software branch uses best model plus companion MTZ and fresh flags only for the new branch | Section 7 Phase 5 | `crystallography-mr-refine`, phase5 doc | skill instruction |
| TLS comparison, keep only if Rfree drops | Section 7 Phase 5 | `crystallography-mr-refine`, phase5 doc | `phase-guide phase5`, `StepTracker` TLS log check |
| Waters until plateau; try alternate software if needed | Section 7 Phase 5 | `crystallography-mr-refine`, phase5 doc | `phase-guide phase5`, `StepTracker` water check |
| RSCC/B-factor region diagnosis | Section 7 Phase 5 | `crystallography-mr-refine`, phase5 doc | `phase-guide phase5`, `StepTracker` `rsc.log` check |
| Do not auto-delete flagged residues | Section 7 Phase 5 | `crystallography-mr-refine`, phase5 doc | skill instruction |
| Refmac overfitting check | Section 7 Phase 5 | `crystallography-mr-refine`, phase5 doc | skill instruction |
| Final MolProbity after waters and TLS | Sections 7 Phase 5 and 7 Phase 6 | `crystallography-mr-refine`, phase6 doc | `StepTracker` final MolProbity check |
| Lowest Rfree wins | Sections 7 Phase 6 and 12 | `crystallography-mr-refine`, phase6 doc | `audit-architecture` |
| MolProbity recalculated Rfree is final reporting value | Section 7 Phase 6 | `crystallography-mr-refine`, phase6 doc | `audit-architecture` |
| Never compare Rfree across different FreeR flags | Sections 7 Phase 5 and 7 Phase 6 | `crystallography-mr-refine`, phase6 doc | skill instruction |
| Final directory contents | Section 7 Phase 6 | `crystallography-mr-refine`, phase6 doc | `StepTracker` final directory check |
| Diagnostic triggers | Section 8 | `crystallography-mr-refine`, raw-processing skill | skill instruction |
| Command hygiene and explicit labels | Section 9 | all skills where relevant | phase guides and command examples |
| Parallel jobs only with unique prefixes/directories | Section 10 | `crystallography-mainline`, MR/refine skill | skill instruction |
| Lesson extraction only on explicit completion/summarize/new project | Section 11 | `AGENTS.md` | manual gate |
| Architecture audit after manual/skill/helper edits | Section 12 | `crystallography-mainline` | `audit-architecture` |

## Conflict Resolution

The older `crystallography-mr-refine` skill contained wording that restarted every real refinement branch from the original MR PDB. That conflicted with the stricter operating rule that each refinement round must use the immediately preceding output PDB and companion MTZ. The new architecture resolves this as follows:

- R1 starts from the MR model and seed data.
- R2 and later rounds must use the previous round PDB and companion MTZ.
- Cross-software branches start from the best model plus its companion MTZ and generate fresh flags only for that new branch.

This rule is now present in `AGENTS.md`, `skills/crystallography-mr-refine/SKILL.md`, `xtal-agent/skills/phase5_refinement.md`, and `crystal_agent.architecture.PHASE_GUIDES`.

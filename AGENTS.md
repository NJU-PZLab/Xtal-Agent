# Crystal Agent Operating Manual

AI-assisted crystallographic structure solution. The agent makes decisions from evidence; Python and crystallography programs perform the calculations.

## 0. EXECUTION GATE — MUST RUN FIRST

Before any operation — starting fresh, resuming after interruption, or processing batched instructions — run the barrier:

```bash
source xtal-agent/env/activate.sh
crystal-agent enforce-checkpoint <project_dir>
crystal-agent resume-barrier <project_dir>
```

If it fails, fix the reported problem before doing anything else. If any step reports `x` or `✗`, stop.

Use the guard around every major phase:

```bash
crystal-agent guard <project_dir> --before <step_name>
crystal-agent guard <project_dir> --after <step_name>
```

Use the code-backed phase guide before each phase:

```bash
crystal-agent phase-guide phase1
crystal-agent phase-guide phase2
crystal-agent phase-guide phase3
crystal-agent phase-guide phase4
crystal-agent phase-guide phase5
crystal-agent phase-guide phase6
```

For concrete command syntax, never improvise from memory. Ask the code for the canonical template:

```bash
crystal-agent command-template <operation>
crystal-agent command-template <operation> --format json
crystal-agent command-template <operation> --format markdown
crystal-agent list-command-templates
crystal-agent naming-guide
```

Use canonical names from `crystal-agent naming-guide`. If a run is interrupted, resume with the next numeric round and do not renumber existing files.

Resume gate after any interruption or inserted instruction:

```bash
crystal-agent naming-guide
crystal-agent verify-steps <project_dir>
```

Then inspect the active guard state. If `.step_state.json` shows an unfinished `current` step, complete or repair that step before starting anything else. Do not rename old outputs to fit a new plan.

## 1. Three Hard Rules

1. Never skip IDXREF. XDS `JOB` must include `IDXREF`. If IDXREF fails, adjust spot finding, `SPOT_RANGE`, or low-resolution limits. Do not remove IDXREF.
2. Never ignore aimless thresholds. The validated outer shell must pass all required thresholds before MR or refinement.
3. Never use invalid-resolution data downstream. MR, FreeR generation, Phenix, Refmac, maps, and validation must use the truncated MTZ matching the validated cutoff.

## 2. Fixed Resolution Validity Thresholds

Outer shell, all must pass:

| Metric | Required value |
|---|---:|
| `CC1/2` | `> 40` |
| `Mn(I/sd)` | `> 1.6` |
| Completeness | `> 70%` |
| `Rmeas` | `< 1.8` |
| `Rmerge` | `< 2.0` |

Exception: ignore outer-shell completeness only when total frames are fewer than 180.

Overall shell must satisfy `CC1/2 > 90`, completeness `> 90%`, and `Mn(I/sd) > 4`.

Inner shell must satisfy `CC1/2 > 90` and `Mn(I/sd) > 4`.

Verify MTZ resolution at every conversion step:

```bash
mtzdump hklin output.mtz <<< "" 2>&1 | grep "Resolution Range"
```

## 3. Workflow Mode Gate

Every project `manifest.yaml` must explicitly contain:

```yaml
workflow_mode: simple
```

or:

```yaml
workflow_mode: expert
```

Never infer workflow mode. If it is absent, stop and ask the user to set it.

`simple` mode proceeds autonomously only for routine projects. Switch to `expert` mode only when the user edits the manifest. Hard stops in simple mode include unresolved indexing failure, strong twinning, unstable space-group interpretation, MR copy-number ambiguity, invalid scaling statistics, unsupported metalloprotein ions, or conflicting refinement evidence.

In `expert` mode, do not use autonomous `run-phase`. Before every guarded step, first get explicit user approval and record it with `crystal-agent expert-approve <project_dir> <step_name> --reason "<why approved>"`, then run `crystal-agent guard <project_dir> --before <step_name>`, execute the approved step, and close it with `crystal-agent guard <project_dir> --after <step_name>`. `verify-steps` and `resume-barrier` must fail if expert-mode outputs exist without a consumed approval and completed guard record.

**Low-resolution branching**: after Phase 2 aimless validation, if the validated resolution is >= 3.6 Å:
- **Simple mode**: automatically enters the low-resolution refinement branch (`phase5_lowres`). No user prompt.
- **Expert mode**: prompts the user whether to adopt the low-resolution refinement strategy. If declined, falls back to standard Phase 5.

## 4. Required Inputs

Minimum inputs before processing:

| Input | Required detail |
|---|---|
| Diffraction data | Raw CBF/image path or validated MTZ |
| Sequence | FASTA file |
| Workflow mode | `simple` or `expert` in manifest |
| Assembly type | monomer, homo-oligomer, hetero-oligomer, or protein-nucleic-acid complex |

Ask immediately when applicable:

| Trigger | Required user information |
|---|---|
| Metalloprotein | metal species and count per chain |
| Glycoprotein | glycosylation sites and glycan composition |
| FASTA has multiple protein sequences | whether chains form a hetero-oligomeric complex and stoichiometry |
| FASTA has DNA/RNA or user says protein-DNA/RNA | confirm nucleic-acid stoichiometry; use AF3 complex mode |
| XDS IDXREF insufficient percentage | user-provided `SPOT_RANGE` from image inspection |

Do not infer metal identity, glycosylation, complex stoichiometry, or workflow mode from data content alone.

## 5. Skill Routing Table

Use these skills and code calls instead of inventing a workflow from memory.

| Situation | Required skill | Required code call |
|---|---|---|
| Whole project orchestration | `crystallography-mainline` | `crystal-agent phase-guide phase<N>` and `verify-steps` |
| Raw images, XDS, DIALS, `SPOT_RANGE`, `DATA_RANGE` | `crystallography-phase1-xds-processing` | `crystal-agent run-phase <project_dir> phase1`; `crystal-agent phase-guide phase1`; `idxref_failure_fix()`; `suggest_data_range_from_mosaicity()`; `command-template xds-*`, `dials-*`, `xia2-fallback` |
| Scaling, aimless, resolution cutoff | `crystallography-phase2-aimless-validation` | `crystal-agent run-phase <project_dir> phase2`; `crystal-agent phase-guide phase2`; `sg_conflict_resolution()`; `command-template pointless`, `aimless-scale`, `mtzdump-resolution` |
| Search model, MSA, AF2/AF3, pLDDT, Matthews | `crystallography-phase3-model-preparation` plus AF skills | `crystal-agent run-phase <project_dir> phase3`; `crystal-agent phase-guide phase3`; `select_prediction_tool()`; `matthews_copy_range()`; `command-template matthews` |
| Phaser, ASU copy-number testing | `crystallography-phase4-molecular-replacement` | `crystal-agent run-phase <project_dir> phase4`; `crystal-agent phase-guide phase4`; `select_best_copy_number()`; `phaser_troubleshooting_order()`; `command-template phaser-mr`, `xtriage` |
| Refinement, waters, TLS, RSCC | `crystallography-phase5-refinement` | `crystal-agent phase-guide phase5`; `should_use_twin_refinement()` when xtriage twin laws are present; `command-template phenix-*`, `refmac-*`, `rscc` |
| Low-resolution refinement (>= 3.6 A) | `phase5_low_res_refinement` | `crystal-agent phase-guide phase5_lowres`; `detect_low_resolution()`; `select_low_res_refine_strategy()`; `command-template phenix-*`, `refmac-*`, `modelcraft-run`, `rscc` |
| Final comparison, MolProbity reporting, final archive | `crystallography-phase6-final-validation` | `crystal-agent phase-guide phase6`; `command-template molprobity-final` |
| Ligand restraints from chemical identity | `crystallography-ligand-generation` | `phenix.elbow` command generated from verified PubChem SMILES; look up CCP4 ligand/CCP4 monomer library restraints; run `crystal-agent map-ligand-atoms` / `map_ligand_atoms` for AF3-to-CCP4 atom mapping |
| Agent architecture edits | `writing-skills` and `test-driven-development` | `crystal-agent audit-architecture <root>` |

## 6. Phase Checklist

### Phase 0: Project Initialization

Required outputs:

- `XDS.INP` or validated input MTZ exists
- raw data path accessible
- FASTA exists
- manifest validates and declares workflow mode

### Phase 1: XDS Processing

Code guide:

```bash
crystal-agent phase-guide phase1
```

Mandatory steps:

1. Generate `XDS.INP` with `crystal-agent command-template xds-generate-inp`.
2. Run XDS round 1 with `SPACE_GROUP_NUMBER=0`; `JOB` must include `IDXREF`.
3. Extract SG, unit cell, per-shell `I/SIGMA`, and resolution estimate from `CORRECT.LP`.
4. Feed SG and cell back into `XDS.INP` and run round 2; `JOB` must still include `IDXREF`.
5. Inspect `INTEGRATE.LP` mosaicity and `CORRECT.LP` SNR; use METRICS only below median mosaicity when selecting `DATA_RANGE`.
6. Optimize `DATA_RANGE` by shrinking or shifting within the initial frame coverage; do not arbitrarily expand.
7. Run two parallel XDS jobs (full vs optimal `DATA_RANGE`); prefer the optimal solution when they differ.
8. If three attempts fail or IDXREF repeatedly fails, use this exact fix order:
   - Adjust `MINIMUM_NUMBER_OF_PIXELS_IN_A_SPOT` (range 3-8)
   - Shift or decrease `SPOT_RANGE`
   - Try low-resolution limits between 20 and 50 A
   - Never remove IDXREF from JOB.
   - In simple mode, stop and request user intervention before CORRECT-only mode or resolution limits below 30 A.

If XDS fails or gives unstable indexing, use DIALS templates: `dials-import`, `dials-find-spots`, `dials-index`, `dials-integrate`, `dials-scale`, and `dials-export-mtz`. If XDS and DIALS fail, run `crystal-agent command-template xia2-fallback` before using pre-existing auto-processing results. Validate any auto-processed result with pointless, aimless, and xtriage before using it.

### Phase 2: Scaling and Resolution Validation

Code guide:

```bash
crystal-agent phase-guide phase2
```

Mandatory steps:

1. Convert XDS output to MTZ only when needed, then run pointless and aimless.
2. Preserve unique filenames during resolution scans; do not overwrite `scaled.mtz` in a loop.
3. Extract outer-shell `CC1/2`, `Mn(I/sd)`, completeness, `Rmeas`, and `Rmerge`.
4. Apply all fixed thresholds. If any fail, return to Phase 1 and reprocess/truncate.
5. Record strict validation lines in `aimless.log`: `AIMLESS_VALIDATION outer ...`, `overall ...`, and `inner ...`, and write the chosen cutoff to `validated_resolution.txt`.
6. Run `mtzdump` after aimless, ctruncate, freerflag, and Phenix seed generation; save the selected MTZ check as `mtzdump_resolution.log`.
7. If pointless confidence is low or absences are ambiguous, test plausible alternative SGs.
8. If aimless passes all thresholds but SG differs from XDS/DIAILS: first feed the new SG back to XDS. If XDS succeeds with the new SG, accept the new result. If XDS fails, keep both SG branches and compare via parallel MR + short refinement.

### Phase 3: Model Preparation

Code guide:

```bash
crystal-agent phase-guide phase3
```

Mandatory decisions:

- Ordinary single-chain non-metallo/non-glyco/non-nucleic-acid protein: use AF2/ColabFold.
- Glycoprotein: use AF3 with glycan CCD codes and covalent bonds. AF2 is not acceptable.
- Protein-DNA/RNA complex: use AF3 complex prediction and the full predicted complex for MR.
- Supported metalloprotein ion: use AF3. AF3 supports the following metal ions (CCD codes in ligand_constants.py): Al, As, Au, B, Be, Br, Ca, Cl, Co, Cr, Cu, Fe, Hg, I, Ir, K, Li, Mg, Mn, Mo, N, Ni, O, Os, P, Pb, Pd, Pr, Pt, Re, Rh, Ru, S, Sb, Se, Si, Sn, Tb, Te, U, W, V, Y, Zn. Unsupported ion (not in AF3 atom_types): Ag, Cd. These two are a simple-mode hard stop.
- Protein-ligand complex (small molecule): use AF3 with `--ligands` or `--ligands-smiles`. If the ligand pLDDT is reliable, include the ligand coordinates in the MR search model.
- Hetero-oligomer: predict distinct protein chains separately unless nucleic acid requires complex prediction.

Mandatory preparation:

1. Generate MSA files for each protein chain.
2. Verify prediction `.done.txt` and top-ranked model.
3. Strip residues with pLDDT `< 80`.
4. Strip expression and purification tags, including common N-terminal `MGS`/`MGSS` and C-terminal His-tags.
5. Save cleaned model as `search_model.pdb`.
6. Calculate Matthews coefficient using CCP4 `matthews_coef` (not phenix.matthews) with explicit cell, SG number, and sequence molecular weight. Record all plausible copy numbers sorted by probability (closest to optimal V_M).

### Phase 4: Molecular Replacement

Code guide:

```bash
crystal-agent phase-guide phase4
```

Mandatory steps:

1. Use the Phase 2 validated truncated MTZ.
2. Run Matthews coefficient with CCP4 `matthews_coef`. Sort copies by V_M proximity to 2.2. **Test the top 3 highest-probability copies first.** If none succeed, iterate the remaining plausible copies. Use `matthews_copy_range()` and `select_best_copy_number()` from `crystal_agent.decision_engine`.
3. **SGALT SELECT ALL is mandatory.** Never run Phaser without `SGALTERNATIVE SELECT ALL`. Pointless space group confidence can be wrong (e.g. 4Z3U: P42212 at 77% was incorrect, P43212 found by Phaser SGALT). Always include `SGALTERNATIVE SELECT ALL` in every Phaser input. Do NOT use `SGALT BASE` — it only tests alternatives within the base group, missing enantiomorphic SGs that differ by screw axes.
4. Save every Phaser run with a unique root and log.
5. Record TFZ, LLG, RFZ, PAK, whether all components placed, and packing notes.
6. Prefer TFZ `> 8`, LLG `> 200`, PAK `= 0`, all components placed.
7. If multiple copy numbers are strong, keep branches through identical short refinement comparisons.
8. If strong MR later gives `Rfree > 0.35`, run xtriage with explicit observation labels before autobuild or long refinement.
9. If Phaser repeatedly fails or times out, first verify `SGALTERNATIVE SELECT ALL` is present. Then call `phaser_troubleshooting_order()` for the next diagnostic step.
10. If MR exceeds 30 min (not instructed as full search) and the search model is a multi-domain protein: split into domain-level PDBs, rerun Phaser with each domain as a separate ENSEMBLE (e.g. `ENSEMBLE ec1 … ENSEMBLE ec2 … SEARCH ENSEMBLE ec1 NUM 2`).

### Phase 5: Refinement and Post-Refinement

Code guide:

```bash
crystal-agent phase-guide phase5
```

Mandatory minimum:

- Run 4+ Phenix rounds.
- Run 4+ Refmac rounds.
- Refmac rounds 1-2 use jelly-body restraints.
- Refmac rounds 3+ run without jelly.
- When ASU contains >1 copy of the same chain (homo-oligomer), apply NCS restraints: add `ncsr local` to all Refmac rounds (jelly, free, and ncs). Code template: `refmac-ncs`.
- Continue the winning branch until Rfree is flat for 2 consecutive rounds. Code-level plateau detection (`detect_rfree_plateau`) enforces: if round N > round N-1 and round N+1 >= round N-1, plateau is reached.
- If Rfree > 0.35 at plateau: first switch software (Phenix ↔ Refmac). If still > 0.35 after both tried, stop and request user intervention — the MR solution is likely wrong.
- If twin laws were detected by xtriage, try twin refinement before switching software.
- Extra rounds are allowed. Fewer than the mandatory minimum rounds fail verification.
- Modelcraft refinement is ALWAYS attempted (mandatory step), but its success is not required. Take the best output from the winning refinement branch and run `modelcraft xray --data <mtz> --contents <fasta> --model <pdb> --cycles 10 --auto-stop-cycles 3`. Always write a `modelcraft_run.log` so the attempt is recorded even if modelcraft crashes. If the run fails (no `modelcraft.json`/`modelcraft.cif`, or empty cycles), ignore the result and keep the pre-modelcraft best — this is an acceptable outcome, not a verification failure. If the run succeeds, select the cycle with lowest Rfree from modelcraft's JSON output, convert the output `.cif` to PDB, run 2 Refmac jelly-body rounds then 2 Refmac free rounds on it, and adopt the modelcraft branch only if its final Rfree improves over the pre-modelcraft best.

Iteration rule:

- Every refinement round must use the immediately preceding output PDB and companion MTZ.
- Phenix logs from round 2 onward must record `INPUT_PDB=phenix_r<N-1>` and `INPUT_MTZ=phenix_r<N-1>` so `verify-steps` can reject skipped iteration.
- Refmac free-round logs must record `INPUT_PDB=refmac_jelly_r2` and `INPUT_MTZ=refmac_jelly_r2` for round 3, then `INPUT_PDB=refmac_r<N-1>` and `INPUT_MTZ=refmac_r<N-1>` for round 4+.
- Only revert when the previous round increased Rfree relative to the round before it.
- Cross-software refinement uses the best model plus its companion MTZ. Generate fresh FreeR flags only for that new branch, run one stabilization round without ordered solvent, then continue.

Required post-refinement:

1. TLS optimization: compare TLS vs non-TLS Rfree; keep TLS only if Rfree drops.
2. Waters: run `ordered_solvent=true` or Refmac `solvent yes` until water count and Rfree plateau. If the best model software fails, try the other software.
3. Region diagnosis: run `phenix.real_space_correlation model.pdb data.mtz detail=residue > rsc.log` and flag residues with B-factor `> mean + 2 sigma` and RSCC `< 0.7`.
4. Do not auto-delete flagged residues. Report loops and side-chain issues for COOT inspection.
5. Run final MolProbity after waters and TLS.

Refmac overfitting check:

- Verify `Rfree - Rwork` is between 1% and 4%.
- If gap exceeds 4%, cross-check with a one-cycle Phenix validation seed using fresh flags. Do not continue the Refmac model with incompatible Phenix flags.

### Phase 5-LR: Low-Resolution Refinement (>= 3.6 Å)

Code guide:

```bash
crystal-agent phase-guide phase5_lowres
```

Trigger: after Phase 2 aimless validation, if `validated_resolution.txt` >= 3.6 Å.

Branching:
- **Simple mode**: auto-enter low-resolution refinement branch.
- **Expert mode**: prompt user whether to adopt low-resolution strategy; if declined, fall back to standard Phase 5.

Mandatory steps:

1. **Rigid body** (1 round): `phenix.refine <mr>.pdb <data>.mtz strategy=rigid_body`
2. **Phenix grouped ADP** (4 rounds): `strategy=group_adp optimize_xyz_weight=True optimize_adp_weight=True`. **Gate**: if Rfree does not improve over rigid body after 4 rounds, skip phenix and start refmac directly from the MR model.
3. **Refmac jelly-body** (2 rounds) + **Refmac free** (2 rounds), iterative.
4. **Modelcraft** (if Rfree <= 0.35 after refmac): `modelcraft xray --data <mtz> --contents <fasta> --model <pdb> --cycles 10 --auto-stop-cycles 3`. Delete garbage chains (B-I), keep chain A including UNK residues.
5. **RSC cleanup**: run `phenix.real_space_correlation`, flag RSCC < 0.7 residues.
6. **Geometry optimization** (if user approves): `phenix.refine rotamer_restraints=true secondary_structure.enabled=true`. Compare Rfree vs geometry; let user select final model.
7. **MolProbity** + **archive** to `final/` with `manual_notes.md` listing UNK residues.

Notes:
- Do not add water molecules.
- Refmac lacks explicit rotamer restraint; use Phenix for geometry optimization.
- At low resolution Rfree and geometry have a trade-off; prioritize Rfree.

### Phase 6: Final Validation and Archive

Code guide:

```bash
crystal-agent phase-guide phase6
```

Rules:

- Lowest Rfree wins.
- Use MolProbity recalculated Rfree for final reporting, not refinement-log Rfree.
- Geometry, MolProbity score, packing, and map quality are diagnostic; they do not override lowest Rfree.
- Never compare Rfree values across different FreeR flag sets as equivalent.

Required final directory contents:

- best PDB and companion MTZ
- chosen AIMLESS log
- MR model, Phaser `.sol`, and Phaser log
- XDS/DIALS processing outputs needed to reproduce the data route
- `comparison.txt`
- final MolProbity log
- `rsc.log`

## 7. Diagnostic Triggers

| Symptom | Required check | Do not do first |
|---|---|---|
| Strong MR but `Rfree ~0.35-0.45` | `phenix.xtriage`, label and FreeR check | autobuild or simulated annealing grid |
| Multiple suitable arrays | `phenix.mtz.dump` or `mtzdump`; explicit labels | guess labels |
| DIALS gives unexpected `P1` | XDS plus pointless/aimless comparison | accept P1 blindly |
| Rwork improves but Rfree worsens | stop branch and compare geometry/contacts | continue same strategy |
| Chain deletion lowers Rfree | xtriage, packing, density around copy | permanently delete chain |
| AF2 secondary structure collapses | DSSP plus restraint control | force AF2 restraints blindly |
| Suspected twinning | xtriage with explicit observation labels | compare ordinary/twinned R naively |
| Space group changes with frame subset | compare lower and higher symmetry through aimless, MR, and short refinement | accept full-range high symmetry alone |
| Refinement plateaus above Rfree 0.25 with better than 2.5 A data | ask user to inspect radiation damage and trim `DATA_RANGE` if confirmed | continue same refinement blindly |
| XDS/DIALS/xia2 cannot index | check validated beamline auto-processing if available | repeat same failed parameters |

## 8. Command Hygiene

- Confirm all input paths exist before long commands.
- Use unique output directories, prefixes, and logs for parallel jobs.
- Quote paths with spaces.
- Redirect long tool output to logs and inspect the first real error.
- Use explicit labels: Phaser uses `LABIN I=IMEAN SIGI=SIGIMEAN`; Phenix uses `labels.name="IMEAN,SIGIMEAN"` for intensities.
- Do not use `F=IMEAN` or `SIGF=SIGIMEAN`.
- Do not mix Phenix versions unless documented and revalidated. Default is Phenix 2.1 (tag 6048) from `xtal-agent/env/activate.sh`.
- Do not delete raw diffraction images. Never use `rm -f *.cbf`.

## 9. Parallel Execution

Parallelize only independent experiments with unique output prefixes and directories. Good batches include resolution cutoffs, alternative SG short MR/refine runs, chain deletion diagnostics, and independent MolProbity/RSC validations. Do not parallelize jobs writing to the same prefix or directory.

## 10. Project Completion and Knowledge Capture

Trigger reusable lesson extraction only when the user explicitly says the project is complete, asks for lessons, says `summarize`, or switches to a new project. Do not trigger merely because Rfree plateaued.

Before editing this manual or skills:

1. Propose 2-5 reusable lessons and their target files/sections.
2. Wait for user approval.
3. Apply changes.
4. Sync changed files to backup.
5. Run `crystal-agent audit-architecture <repo_root>`.

## 11. Architecture Maintenance

After changing `AGENTS.md`, SKILL files, or workflow helper code, run:

```bash
source xtal-agent/env/activate.sh
pytest -q
crystal-agent audit-architecture <repo_root>
```

The architecture audit must pass before the work is reported complete.

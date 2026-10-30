# R1_15A2 - persistent instructions for Codex

## Purpose, roles, and scope

This repository implements R1_15A2, a Python calibration system for a PTV Visum road-transport demand model. It combines trip generation (TG), native trip distribution (TD), route/assignment feedback, traffic-count fitting, survey-distance/FineCDF diagnostics, and verified acceptance/rollback.

- The user is the system/methodology architect and authorizes changes to scope and calibration policy.
- Codex is the implementation and offline-verification engineer. Work directly on the actual project files, not on text reconstructed from chat transcripts.
- ChatGPT may independently review your diff, tests, numerical behavior, and safety implications.
- PTV Visum runs separately on the user's work computer. The Codex development environment must not assume Visum, Windows COM, a loaded `.ver`, or access to the live model.
- For each request, implement the *one approved bounded task*. Do not automatically proceed to the next roadmap item.

## Establish the authoritative baseline before editing

1. Locate the active code root containing the launchers, `r1_15a2_*.py`, `tests/`, `tools/`, and `V24917_RUNTIME_MANIFEST.json`. In the 2026-10-27 delivery archive, this directory is `R1_MOBILITYZONE1/`. Keep this `AGENTS.md` at that root.
2. Inspect Git state (`git status --short`, branch, uncommitted changes) if Git exists. Preserve other people's work; never discard, reset, overwrite, or commit changes not owned by the current task. Do not initialize Git without approval.
3. Identify the *actual* checked-out/installed release from its files, manifest and launch chain. The reference baseline for these instructions is the `SAFETYFIX2 + LONGGUARD1 + MOBILITYZONE1` V24917 package dated 2026-10-27, not a claim about future versions. The historical `CURRENT_RELEASE.txt` inside that package may refer to V24915; it does not override `V24917_RUNTIME_MANIFEST.json` or the active code.
4. Inspect only files needed for the task, their callers, existing tests and relevant manifests. Do not read the entire historical archive for every small edit. Historical release notes, old scripts, and stored test outputs are evidence, not proof that the currently selected code is executable.
5. If only `R1_15A2_COMPLETE_SOURCE_BUNDLE.txt` is available, treat it as a concatenated reference snapshot, *not* a writable/reconstructable working tree. Ask for/extract the actual matching source package before implementing or claim only a proposed patch. Never silently repair encoding or regenerate missing source from the transcript.
6. Confirm which files are in scope and the invariants at risk. If task assumptions conflict with current source, report the conflict and favor the verified existing contract until the user authorizes a methodological change.

## Architecture: locate the real owners

Read these when relevant, not all by default:

| Area | Primary entry points / contracts |
| --- | --- |
| Launch and runtime | `01_SPUSTIT_V24917_TDJOINT1.py`, `02_SPUSTIT_V24917_TDJOINT1_60_40.py`, `01_SPUSTIT_V24917_PREFLIGHTIOFIX1.py`, `r1_15a2_v24917_runtime.py` |
| Targeted TG / zonal count fitting | `r1_15a2_zonal_count_fit_v24917.py`, `r1_15a2_targeted_generation_v24917.py`, `r1_15a2_trial_adapter_v24917.py` |
| Zonal mobility and aggregate safeguards | `r1_15a2_mobility_zone_v24917.py`, `r1_15a2_mobility_guard_v24917.py`, `r1_15a2_step_search_v24917.py` |
| LONG/SCHOOL generation | `r1_15a2_long_school_generation_v24917.py`, `r1_15a2_long_distance_guard_v24917.py` |
| Assignment-coupled skim identity | `r1_15a2_dynamic_skim_v24916p2c.py`, `r1_15a2_skim_v24916p2c.py` |
| TD, FineCDF, recovery | `r1_15a2_finecdf_bridge_v24916.py`, `r1_15a2_td_joint_v24917.py`, `r1_15a2_td_joint_runtime_v24917.py`, `r1_15a2_parent_equivalence_v24917.py` |
| Tests, release | `tests/`, `diagfast_tests/`, `genfix2_audit_tests/`, `tools/run_genfix2_checks.py`, `tools/refresh_v24917_manifests.py`, `V24917_RUNTIME_MANIFEST.json` |

Check names against the working tree. Do not invent missing modules or interfaces. The V24917 package contains many historical revisions; the most recent filename alone is not sufficient to establish runtime ownership.

## Scientific and data invariants (never change implicitly)

- Maintain P/A marginal balance, total mass, dimensional integrity and zone identity, except for the explicitly authorized LONG post-TD clipping described below. Distinguish persons/trips, vehicle OD, profile flow, and occupancy; the AMDY formula divisor `2.8` is **not** evidence of average vehicle occupancy.
- Respect calibrated count-location roster, actual role/weights and source units. Never silently substitute older 488/498-profile rosters or new survey targets for the active one. The active V24917 roster in this baseline contains 248 CAL profiles; confirm live/current authority for a different release.
- The mobility reference is immutable within a run. For domestic WORK/SERVICE/SCHOOL the canonical ADD_PROD coefficient is `1.0`; for LONG `ADD_PROD_L` it is `0.3`. The active `MOBILITYZONE1` band is `[0.75, 2.0]` relative to these fixed references, subject to actual runtime options. Existing out-of-band parent states must not drift further away; structural zeros stay zero. Do not turn per-cycle growth limits into new reference points.
- LONG matrices are **9111-9115**. FOREIGN **9116**, EXOG and other frozen strata stay frozen unless explicitly authorized. Do not invent components or derive vehicle conversions from a demand divisor.
- By user decision on 2026-10-29, LONG admissibility/support uses **fixed OSRM matrix 9697 / R1_OSRM_DIST_KM**: `distance >= MIN_KM` (currently 80 km). `distance > MAX_CDF_KM` (currently 200 km) remains **allowed**. Native NATIVE_CL/DIS remains the separate assignment-coupled IDP/FineCDF distance authority. The 80-100 km tolerance band is allowed by support; the conditional 100-200 km CDF remains unchanged and cannot prove absence of forbidden OSRM support.
- Reuse `MIN_KM` and `MAX_CDF_KM` from `r1_15a2_long_distance_guard_v24917.py` and project `ordered_zone_hash()` / `matrix_values_hash()` from `r1_15a2_skim_v24916p2c.py`. Verify OSRM NO/CODE, dimensions and zone order; pin its content/zone hashes within a run. Never substitute another distance matrix. For FineCDF, retain `DynamicSkimManager.require_current()` and diagnostic/assignment epoch binding. A caller-supplied `verified=True` is not evidence.
- User decision 2026-10-29 explicitly authorizes multiplying LONG person matrices 9111-9115 by the OSRM >=80 km mask AFTER the one unified native TD operation, accepting removed volume and changed realized P/A WITHOUT redistribution or renormalization. The native OD-pair filter is no longer required for this method. Keep the native operation definition, position, strata and b/c untouched by the masking operation.
- After 20A/20B realization, apply the same mask to LONG vehicle components 9291-9295 and rebuild their aggregate 9305 before assignment. Audit removed totals and production/attraction by zone at each stage; preserve allowed values, FOREIGN and other strata. Restore original ACTIVE flags after execution slices and own partially completed matrix writes through verified restoration and accepted-parent recomputation. Do not claim a live-verified result from offline mocks.
- User decision 2026-10-29 authorizes porting W/S proposal principles to zonal LONG Generation: use the shared two-mode NATIVE_CL path cache, current M9291-9295/M9305, inline OD/profile/source checks, and the existing native trial/accept/reject/rollback chain. No separate audit launcher is required. Frozen paths are a labelled proposal basis, not a claim of a fresh export or an analytic TG derivative. Missing support/share or failed profile parity permits one normal shared-cache refresh; unresolved evidence defers LONG while W/S/SCHOOL continue.
- LONG Generation uses per-zone ADD_PROD_L/ADD_ATT_L steps capped at +/-10%, the fixed 0.3 production reference with [0.15,0.45] admissible band, and the configured [0.5,1.5] multiplier band around immutable run-start attraction values. Existing out-of-band parents may hold or recover only. Native assignment and fresh diagnostics decide acceptance; keep all LONG OSRM/FineCDF and mobility guards. Shared LONG TD b/c calibration remains pending its own count-response model and is not enabled by this Generation port.

- Preserve the active acceptance objective, protected profile constraints, survey metrics, count/IDP blending, convergence definition, freezes and safety thresholds unless the task explicitly authorizes a methodological change. Do not loosen guards or hide failed cases to obtain a green run.

## Visum, transactions, and operational safety

- User decision 2026-10-29: ZAHR_PROD_WORK, ZAHR_ATR_WORK, ZAHR_PROD_SERV and ZAHR_ATR_SERV use [0.5, 10.0] times each coefficient's immutable run-start value. The aligned REFINE soft band is also [0.5, 10.0]. Preserve structural zeros and phase step caps. Boundary P/A volume inputs retain their separate [0.5, 2.0] run-start envelope.

- No launching or attaching to Visum, `LoadVersion()`, `.ver` mutation, COM writes, remote deployment, or long-running live calibration without explicit user authorization and the appropriate Windows environment.
- Never use `LoadVersion()` to repair a rejected candidate inside an active calibration. Preserve the one live Visum instance and implement in-memory transaction snapshot / apply / readback / full recomputation / verify-parent rollback. If exact or policy-approved equivalence cannot be demonstrated, fail closed and require manual reopening of the last verified accepted checkpoint.
- Direct `SetValues()` is authorized only for the explicitly scoped LONG post-TD multiplication/rebuild and its in-memory restoration above. Other native TD operator modifications, demand OD writes and temporary matrices require explicit authorization and a transaction/rollback/readback plan.
- Respect live assignment/skims epoch invalidation after changes. Never reuse stale paths, skims, FlowBundle incidence or diagnostics as current. Do not bypass the freshness checks or import historic cache evidence as a live authority.
- Checkpoints are accepted only after verified native calculation and established acceptance gates. Never save or label an unverified candidate as ACCEPTED, BEST or production-ready. Prevent partial checkpoint publication and protect previous accepted checkpoints.

## Implementation workflow for each bounded task

1. **Preflight:** inspect relevant code paths, dependencies, tests, version/manifest coverage, and pre-existing changes. State any material contradiction or missing contract.
2. **Plan briefly:** define proposed files, behavior, unchanged invariants, test cases and expected effect. For normal small tasks, implement without writing a lengthy plan file. For large cross-cutting tasks, propose a phase plan before changing runtime code.
3. **Implement narrowly:** prefer pure, testable computation at the boundary; separate it from Visum/COM adapters. Follow existing naming/error conventions, use the project's established numeric/hash mechanisms, validate shapes, identities and units strictly, and avoid silent defaults for authoritative inputs.
4. **Test:** start with syntax/import checks and focused regression tests against the actual production module; then run relevant suites. Use separate processes for suites whose `conftest.py` clash. `tools/run_genfix2_checks.py` can run `tests`, `diagfast_tests`, and `genfix2_audit_tests` separately; examine its behavior before invoking it. Do not automatically install dependencies or run live scripts.
5. **Assess release integrity:** application-file changes can invalidate `V24917_RUNTIME_MANIFEST.json` and other sealed hashes. Never disable verification or simply rewrite hashes to disguise changed authorities. Identify required, approved manifest/release work (including `tools/refresh_v24917_manifests.py`) and verify exact before/after file identities.
6. **Audit changed files:** inspect `git diff --check`, `git status --short` (if Git is present), module compilation, test logs and unrelated-file modifications. Store logs outside the source root where possible. Do not silently reformat or change unrelated historical/authority files.
7. **Stop at task boundary:** do not merge changes into a live release, run Visum or start the next milestone without an explicit request. The user's standing instruction below authorizes GitHub backup commits/pushes of completed task-owned changes.

Suggested offline commands from the actual source root, when dependencies are available:

```text
python -m py_compile path/to/changed_module.py
python -m pytest -q -p no:cacheprovider tests/test_relevant.py
python tools/run_genfix2_checks.py --output <OUTSIDE_SOURCE_TREE_DIRECTORY>
```

Prefer Python's `PYTHONPYCACHEPREFIX` or `PYTHONDONTWRITEBYTECODE=1` to avoid untracked bytecode in source. Full suite is not a substitute for a targeted regression test that proves the changed behavior. Report tests as `PASS`, `FAIL`, `SKIPPED` or `NOT_RUN` only from observed execution; offline mocks do not prove Windows COM/Visum functionality.

## Handoff format to the user / ChatGPT reviewer

Respond in Czech, preserving exact English code symbols, filenames and error identifiers. Provide:

1. **Baseline / task:** actual release, task ID, branch/working tree state, scope and assumptions.
2. **Implementation:** each changed/added file and why, key design decisions, compatibility/API changes and a complete unified diff (or a patch file; include all new files).
3. **Evidence:** exact commands executed, exit codes, passed/failed/skipped totals, paths to logs, relevant numerical checks and untouched authority/manifest proof.
4. **Safety:** impact on Visum/COM, TD, OD matrices, assignment epoch, native acceptance and rollback; clearly distinguish offline tests from `LIVE_VISUM_NOT_RUN`.
5. **Outstanding blockers:** anything unverified, environment-specific, methodologically ambiguous or requiring live validation.
6. **Next step:** one clearly bounded follow-up; do not implement it automatically.

Never report `PASS` or "fully validated" based on generated code, prior evidence, or hypothetical commands. A concise honest partial deliverable is better than invented assurance.

## Immediate project status (context, not authorization)

Current user-selected baseline (2026-10-30): branch `codex/v24917-school-td-finecdf-active-20261030`, commit `0f2204a3f0a4a4c74bda0f32c8ea7323320e0f70`, supersedes the historical LONG TD freeze noted above. LONG TG and shared LONG_COMPOSITE TD are opt-in enabled in its run options. SCHOOL Generation stays fixed at original AMDY FP_5_SCHOOL/FA_5_SCHOOL; unused ADD_PROD_SCH/ADD_ATT_SCH are not optimized. SCHOOL TD may optimize only native 5_SCHOOL b/c (M9117), with fixed a and the original DIRECT_PURPOSE 512-point 0.1–100 km FineCDF target. SCHOOL TD requires measured DYNAMIC assignment; no W/S frozen incidence may serve as its count response. The unified native TD must retain LONG >=80 km masking even in SCHOOL-only probes. Verify unchanged SCHOOL FP/FA throughout the inner stage. Keep original live acceptance and in-memory rollback.

At this baseline, `LONGGUARD1` and `MOBILITYZONE1` exist; the hard native LONG OD support and a per-zone LONG generation actuator are not yet proven implemented. The planned next development unit is `LONG_OD_MASK1` (pure, hash-bound mask and tests), followed only after review by native `LONG_OD_NATIVE1`, feasible restricted TD, composite FineCDF calibration and the later per-zone mobility changes. Confirm the task with the user prompt and actual tree, not with this historical note alone.

## Standing GitHub backup instruction (user, 2026-10-29)

Upload all completed task-owned changes, patches and validation evidence to GitHub automatically. The user cannot download workspace-local links. Provide a GitHub branch/commit link and a complete downloadable GitHub ZIP archive; do not rely on local paths for handoff. Use a separate task branch, preserve previous history, verify remote/local tree equality, and do not merge or run live Visum without separate authorization.

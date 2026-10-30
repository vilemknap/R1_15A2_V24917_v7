# V24917 SupplyMix preventive review — 2026-10-30

**Scope:** r1_15a2_supply_mix_v24917.py, its demand-policy/controller
wrappers, reviewed run options, uploaded 2026-10-30 RUN_STATUS/EFFECTIVE_CONFIG.
**Source branch:** codex/a0001-hard-disk-reload-20261030.
**Changes:** only completion/status isolation in a SEPARATE branch, no production
scientific acceptance threshold, no COM operation, no accepted state, no
Source A0001 checkpoint or SQLite edit.

## Verified properties

- The runtime installs SupplyMix on top of the demand-policy generation
  wrapper. It runs INSIDE the TG/TD cycle after the Generation step.
- Reviewed R1_RUN_OPTIONS.json:
  sp_enabled=true, sp_start_cycle=2, sp_every_n_cycles=2, sp_drivers=BOTH,
  sp_max_trials=2, sp_step_units=[8,4], sp_max_groups=12, sp_max_edges=120,
  sp_cold_reset_position=15.
- Live procseq preflight in the supplied RUN_STATUS lists op15 active type9
  assignment reset, op17-20 active type101 and op20 in the approved supply
  assignment scope. The cold-plan builder requires reset/assignment presence.
- SupplyMix designs only from proved ON/OFF path sequences. It does not round
  a fractional negative ADDVAL1 beyond a proved path step: integer ValueType
  fallback is restrictive, and check_addval_change requires positive
  generalized minimum cost and unchanged parent/baseline.
- Each candidate requires fresh native assignment, diagnostics, shared objective
  improvement and Supply ADDVAL acceptance. Rejected/failed candidates have
  parameter restoration and verified rollback. Strong guards are retained.
- The last uploaded RUN_STATUS shows cycle 1 TD_RUNNING and no SupplyMix trial
  evidence. This is NOT a live SupplyMix test; earliest due is cycle 2 unless
  the host's options file or environment differs.

## Critical, deterministic controller-contract defect — corrected here

Original code:
  if SupplyMix.search_complete is False:
      generation_record.search_complete = False
      generation_record.stationarity_confirmed = False

SupplyMix returns search_complete=False for NO_COST_SAFE_CANDIDATE,
DESIGN_FAILED_NO_WRITE, and even a verified no-write recovery. Those failures
are NOT failed TG designs. Nonetheless, controller computes

    search_complete = generation_record.search_complete is True and
                      td_inner.search_complete is True

and if TD finished normally but search_complete=False returns
DEMAND_SEARCH_INCOMPLETE_SUPPLY_LOCKED. With SupplyMix due on cycle 2, a legal
branch exhaustion can therefore prematurely stop the TG/TD run without ever
writing ADDVAL1. With retries/progress, it can also repeatedly lose the
stationarity streak.

**Fix:** Preserve original Generation search_complete on a no-write SupplyMix
incomplete result. Do NOT certify stationarity in that cycle. Keep SupplyMix's
own search_complete=false and reason as an explicit separate namespace:
v24917_supplymix_search_incomplete,
v24917_supplymix_incomplete_reason,
v24917_supplymix_tg_completion_preserved.
Also clear DemandPolicy.last_generation_complete, because SupplyMix remains
unverified for JOINT stationarity. A truly incomplete Generation remains
incomplete and is not accidentally promoted.

No acceptance criterion, physical-cost guard, supply candidate, path basis,
TD, native operation, or verified rollback has been relaxed.

## Remaining review observations (no active-run edits)

1. The code's separate full Supply phase is intentionally disabled by
   FRESH100 TGTD-only. SupplyMix is injected inside Generation; that can
   modify ADDVAL1 while RUN_STATUS.supply_started remains false. This is an
   important semantic distinction in reporting, not evidence of model
   corruption. It should be explicitly approved as a mixed-demand actuator.
2. R1_RUN_OPTIONS sp_drivers=BOTH allows underloaded drivers even while
   model/obs passage ratio is about 0.46 (CATCH_UP threshold 0.80).
   AUTO would select overloaded drivers only during CATCH_UP. Changing that
   option is a methodological choice, not part of this technical patch.
3. The module and its existing 39 offline SupplyMix tests do not establish
   actual Visum COM performance or rollback fidelity on 863,272 restored
   routes. The first real supplymix attempt should be inspected.
4. Use DEMAND_CYCLE_02_SUPPLYMIX/SUPPLYMIX_BLOCK_RESULT.json together with
   RUN_STATUS.json; if any write/recompute occurred, inspect accepted-state,
   rollback and path-epoch transition evidence before declaring success.

## Deployment restriction

DO NOT modify the code or R1_RUN_OPTIONS inside a currently running Visum
process. Python modules are already loaded in memory; silently replacing
files is not a safe hotfix. This branch is for the NEXT verified restart or
deployment after offline test success. The running checkpoint and SQLite
remain untouched.

The full regression suite and DIAGFAST/GENFIX2 audits must pass independently.
No Windows PTV Visum has been executed in the audit environment.

"""Hierarchical full overnight trial-assignment calibration controller for R1 15A2 V2.4.1.

Methodological order is hard-gated:
  1. Trip generation converges.
  2. Trip distribution converges with generation frozen except for ordinary recomputation.
  3. Supply / route-choice ADDVAL1 calibration starts only after both demand phases converge.

Saved-path geometry proposes supply candidates only. Candidate acceptance always uses a
fresh real Visum recomputation and live diagnostics. Rejected trials are rolled back in
place by restoring calibrated parameters and recomputing; LoadVersion is never used.
"""
from __future__ import annotations

from pathlib import Path
import traceback

from r1_15a2_supply import SupplyContractError, SupplyPolicy, number
from r1_15a2_controller_v22 import atomic_json, build_reference, ledger, diagnostic_hash
from r1_15a2_overnight_controller_v240 import (
    OvernightControl, UserStopRequested, TimeBudgetReached,
    _science_hash, _baseline_parameter_guard, _planned_generation_rows,
    _evaluate_candidate, _adopt_candidate, _save_rotating_checkpoint,
)

EXPECTED_PHASES = [
    ("TRIP_GENERATION", ["GENERATION"]),
    ("TRIP_DISTRIBUTION", [
        "TD_COMPONENT_WORK", "TD_COMPONENT_SERVICE",
        "TD_COMPONENT_SCHOOL", "TD_COMPONENT_LONG",
    ]),
    ("SUPPLY_ROUTE_CHOICE", ["SUPPLY_ADDVAL1"]),
]


def _validated_phase_plan(cfg):
    phases = cfg.get("calibration_phases")
    if not isinstance(phases, list) or len(phases) != len(EXPECTED_PHASES):
        raise SupplyContractError("V241_INVALID_OR_MISSING_CALIBRATION_PHASES")
    normalized = []
    flattened = []
    for raw, (expected_name, expected_blocks) in zip(phases, EXPECTED_PHASES):
        if not isinstance(raw, dict):
            raise SupplyContractError("V241_PHASE_NOT_OBJECT:" + expected_name)
        name = str(raw.get("name", ""))
        blocks = list(raw.get("blocks", []))
        if name != expected_name or blocks != expected_blocks:
            raise SupplyContractError("V241_PHASE_ORDER_AUTHORITY_MISMATCH:" + expected_name)
        max_cycles = int(raw.get("max_cycles", 0))
        if max_cycles <= 0:
            raise SupplyContractError("V241_PHASE_MAX_CYCLES_INVALID:" + expected_name)
        if raw.get("must_converge_before_next_phase") is not True:
            raise SupplyContractError("V241_PHASE_ADVANCE_NOT_FAIL_CLOSED:" + expected_name)
        normalized.append({
            "name": name,
            "blocks": blocks,
            "max_cycles": max_cycles,
            "convergence_rule": raw.get("convergence_rule"),
        })
        flattened.extend(blocks)
    if list(cfg.get("block_schedule", [])) != flattened:
        raise SupplyContractError("V241_FLATTENED_BLOCK_SCHEDULE_MISMATCH")
    if flattened[-1] != "SUPPLY_ADDVAL1" or "SUPPLY_ADDVAL1" in flattened[:-1]:
        raise SupplyContractError("V241_SUPPLY_MUST_BE_FINAL_PHASE_ONLY")
    required = cfg.get("trial_calibration", {}).get("supply_start_requires_converged_phases", [])
    if list(required) != ["TRIP_GENERATION", "TRIP_DISTRIBUTION"]:
        raise SupplyContractError("V241_SUPPLY_START_GATE_CONFIGURATION_MISMATCH")
    return normalized


def _phase_checkpoint(adapter, root, phase_name, state, diag, value, accepted_count):
    root = Path(root)
    pdir = root / "PHASE_CHECKPOINTS"
    pdir.mkdir(parents=True, exist_ok=True)
    target = pdir / (phase_name + "_CONVERGED.ver")
    if target.exists():
        target.unlink()
    cp = adapter.save(target)
    record = {
        "schema": "R1_15A2_V241_PHASE_CHECKPOINT_V1",
        "phase": phase_name,
        "accepted_count": accepted_count,
        "state_hash": state["state_hash"],
        "diagnostic_hash": diagnostic_hash(diag),
        "ledger": value,
        "checkpoint": cp,
    }
    atomic_json(pdir / (phase_name + "_CONVERGED.json"), record)
    return record


def _phase_has_blocking_error(rec):
    status = str(rec.get("status", ""))
    if status in ("BLOCKED_DESIGN", "BEST_CANDIDATE_ADOPTION_FAILED_ROLLED_BACK"):
        return True
    attempts = rec.get("attempts", [])
    return any(str(a.get("status")) == "FAILED" for a in attempts)


def run_overnight_calibration_hierarchical(adapter, cfg, folder, control):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    policy = SupplyPolicy.from_config(cfg)
    tcfg = cfg.get("trial_calibration", {})
    phases = _validated_phase_plan(cfg)
    result = {
        "schema": "R1_15A2_V241_FULL_OVERNIGHT_HIERARCHICAL_CALIBRATION_V1",
        "status": "STARTED",
        "production_apply": False,
        "trial_writes": True,
        "load_version_called": False,
        "direct_od_matrix_writes": False,
        "accepted_count": 0,
        "phases": [],
        "blocks": [],
        "phase_order_authority": [p[0] for p in EXPECTED_PHASES],
        "supply_started": False,
        "full_network_link_eligibility": True,
        "candidate_edge_limit_is_local_not_global": True,
        "methodology": "TRIP_GENERATION_THEN_TRIP_DISTRIBUTION_THEN_SUPPLY_ADDVAL1",
    }
    atomic_json(folder / "EFFECTIVE_CONFIG.json", cfg)
    active_parent = None
    diag = None
    state = None
    value = None
    current_phase = None
    completed_phases = []
    try:
        control.checkpoint("LIVE_PREFLIGHT", force=True)
        result["preflight"] = adapter.preflight(folder / "PREFLIGHT")

        # Normalize the isolated working copy using the full active Procedure Sequence.
        # No calibration candidate is written before this baseline recomputation.
        pre_recompute = adapter.snapshot()
        control.checkpoint("BASELINE_FULL_RECOMPUTE", force=True)
        adapter.assign(folder / "BASELINE_FULL_RECOMPUTE", supply_only=False)
        state = adapter.snapshot()
        _baseline_parameter_guard(pre_recompute, state)
        control.checkpoint("BASELINE_DIAGNOSTICS", force=True)
        diag = adapter.diagnostics(folder / "BASELINE_DIAGNOSTICS", "BASELINE")
        if adapter.snapshot() != state:
            raise SupplyContractError("BASELINE_DIAGNOSTICS_CHANGED_MODEL")
        reference = build_reference(diag, cfg)
        anchors = dict(state["addval1"])
        value = ledger(diag, state, anchors, policy, reference, cfg)
        atomic_json(folder / "OBJECTIVE_REFERENCE.json", reference)
        atomic_json(folder / "ORIGINAL_ADDVAL1_ANCHORS.json", anchors)
        atomic_json(folder / "BASELINE_LEDGER.json", value)
        cp = _save_rotating_checkpoint(adapter, folder, 0)
        active_parent = {"snapshot": state, "diag": diag, "value": value, "checkpoint": cp}

        max_accepted = int(tcfg.get("max_accepted_states", 100))
        trials_cfg = tcfg.get("max_trials_per_block", {})

        for phase_index, phase in enumerate(phases, start=1):
            current_phase = phase["name"]
            if current_phase == "SUPPLY_ROUTE_CHOICE":
                if completed_phases != ["TRIP_GENERATION", "TRIP_DISTRIBUTION"]:
                    raise SupplyContractError("V241_SUPPLY_STARTED_BEFORE_DEMAND_PHASES_CONVERGED")
                result["supply_started"] = True
            phase_rec = {
                "phase_index": phase_index,
                "phase": current_phase,
                "blocks": list(phase["blocks"]),
                "status": "RUNNING",
                "cycles": [],
                "accepted_start": result["accepted_count"],
                "objective_start": value["total"],
            }
            result["phases"].append(phase_rec)
            control.checkpoint("PHASE_START", force=True, phase_name=current_phase,
                               accepted_count=result["accepted_count"], objective=value["total"])

            converged = False
            for phase_cycle in range(1, int(phase["max_cycles"]) + 1):
                control.checkpoint("PHASE_CYCLE_START", force=True, phase_name=current_phase,
                                   phase_cycle=phase_cycle, accepted_count=result["accepted_count"],
                                   objective=value["total"])
                accepted_this_cycle = 0
                cycle_had_blocking_error = False
                cycle_rec = {
                    "phase_cycle": phase_cycle,
                    "accepted": 0,
                    "objective_start": value["total"],
                    "blocks": [],
                }
                phase_rec["cycles"].append(cycle_rec)

                for block in phase["blocks"]:
                    control.checkpoint("BLOCK_DESIGN", force=True, phase_name=current_phase,
                                       phase_cycle=phase_cycle, block=block,
                                       accepted_count=result["accepted_count"], objective=value["total"])
                    if result["accepted_count"] >= max_accepted:
                        phase_rec["status"] = "MAX_ACCEPTED_STATES_REACHED"
                        result["status"] = "MAX_ACCEPTED_STATES_REACHED_DURING_" + current_phase
                        return result
                    before = adapter.snapshot()
                    if before != state:
                        raise SupplyContractError("ACCEPTED_STATE_MUTATED_BETWEEN_BLOCKS")
                    out = folder / ("PHASE_%02d_%s_CYCLE_%03d_%s" % (
                        phase_index, current_phase, phase_cycle, block))
                    out.mkdir(parents=True, exist_ok=True)
                    rec = {
                        "phase": current_phase,
                        "phase_cycle": phase_cycle,
                        "block": block,
                        "status": "DESIGNING",
                        "attempts": [],
                    }
                    result["blocks"].append(rec)
                    cycle_rec["blocks"].append(rec)
                    context = None
                    try:
                        if block == "SUPPLY_ADDVAL1":
                            design = adapter.supply_design(diag, out / "DESIGN", before)
                            candidates = list(design.get("candidates", []))
                            planned_rows = [None] * len(candidates)
                        elif block == "GENERATION":
                            context = adapter.generation_design(diag, out / "DESIGN")
                            candidates = [{"scale": float(s)} for s in cfg.get("backtracking_scales", [1.0, .5, .25])]
                            planned_rows = []
                            for cand in candidates:
                                preview, rows = _planned_generation_rows(adapter, context, cand["scale"])
                                atomic_json(out / ("GENERATION_PREVIEW_%s.json" % str(cand["scale"]).replace(".", "_")), preview)
                                planned_rows.append(rows)
                        else:
                            candidates = [{"scale": float(s)} for s in cfg.get("backtracking_scales", [1.0, .5, .25])]
                            planned_rows = []
                            for cand in candidates:
                                d = adapter.td_design(diag, block, cand["scale"], out / "DESIGN")
                                planned_rows.append(list(d.get("candidate_rows", [])))
                    except Exception as exc:
                        rec.update(status="BLOCKED_DESIGN", error=str(exc), traceback=traceback.format_exc())
                        cycle_had_blocking_error = True
                        atomic_json(out / "BLOCK_RESULT.json", rec)
                        continue

                    limit = int(trials_cfg.get(block, len(candidates)))
                    candidates = candidates[:max(0, limit)]
                    planned_rows = planned_rows[:len(candidates)]
                    if not candidates:
                        rec["status"] = "NO_CANDIDATE"
                        atomic_json(out / "BLOCK_RESULT.json", rec)
                        continue

                    best = None
                    baseline_diag = diag
                    for ordinal, (candidate, rows0) in enumerate(zip(candidates, planned_rows), start=1):
                        control.checkpoint("TRIAL_START", force=True, phase_name=current_phase,
                                           phase_cycle=phase_cycle, block=block, trial=ordinal)
                        if adapter.snapshot() != before:
                            raise SupplyContractError("TRIAL_NOT_FROM_IDENTICAL_ACCEPTED_PARENT")
                        if block == "SUPPLY_ADDVAL1":
                            rows = []
                        else:
                            rows = list(rows0 or [])
                            if not rows:
                                rec["attempts"].append({
                                    "trial": ordinal,
                                    "status": "NO_PARAMETER_CANDIDATE",
                                    "candidate": candidate,
                                })
                                continue
                        ev, rolled_diag, error = _evaluate_candidate(
                            adapter, cfg, policy, block, candidate, rows, context, before,
                            baseline_diag, value, anchors, reference,
                            out / ("TRY_%02d" % ordinal), control,
                        )
                        diag = rolled_diag
                        attempt_rec = {
                            "trial": ordinal,
                            "candidate": candidate,
                            "status": "FAILED" if ev is None else ("ELIGIBLE" if ev["eligible"] else "REJECTED"),
                        }
                        if error:
                            attempt_rec["error"] = error
                            cycle_had_blocking_error = True
                        if ev is not None:
                            attempt_rec["ledger"] = ev["after_value"]
                            attempt_rec["decision"] = ev["decision"]
                            if ev["eligible"] and (best is None or ev["after_value"]["total"] < best["after_value"]["total"]):
                                best = ev
                        rec["attempts"].append(attempt_rec)
                        atomic_json(out / "BLOCK_RESULT.json", rec)

                    if best is None:
                        rec["status"] = "NO_ACCEPTED_CANDIDATE"
                        atomic_json(out / "BLOCK_RESULT.json", rec)
                        continue

                    control.checkpoint("ADOPT_BEST", force=True, phase_name=current_phase,
                                       phase_cycle=phase_cycle, block=block)
                    try:
                        new_state, new_diag, new_value, adopted_rows, gap = _adopt_candidate(
                            adapter, cfg, policy, block, best, context, before, diag, value,
                            anchors, reference, out / "ADOPTED", control,
                        )
                    except Exception as exc:
                        rec.update(status="BEST_CANDIDATE_ADOPTION_FAILED_ROLLED_BACK",
                                   error=str(exc), traceback=traceback.format_exc())
                        cycle_had_blocking_error = True
                        atomic_json(out / "BLOCK_RESULT.json", rec)
                        diag = adapter.diagnostics(out / "POST_ADOPTION_FAILURE_BASELINE_DIAGNOSTICS", "BASELINE")
                        if adapter.snapshot() != before or diagnostic_hash(diag) != diagnostic_hash(baseline_diag):
                            raise SupplyContractError("POST_ADOPTION_FAILURE_BASELINE_NOT_IDENTICAL")
                        continue

                    state, diag, value = new_state, new_diag, new_value
                    if hasattr(adapter, "invalidate_cache"):
                        adapter.invalidate_cache("ACCEPTED_STATE_CHANGED", clear_proof=True)
                    result["accepted_count"] += 1
                    accepted_this_cycle += 1
                    cycle_rec["accepted"] = accepted_this_cycle
                    cp = _save_rotating_checkpoint(adapter, folder, result["accepted_count"])
                    active_parent = {"snapshot": state, "diag": diag, "value": value, "checkpoint": cp}
                    accepted_record = {
                        "schema": "R1_15A2_V241_ACCEPTED_STATE_V1",
                        "accepted_count": result["accepted_count"],
                        "phase": current_phase,
                        "phase_cycle": phase_cycle,
                        "block": block,
                        "candidate": best["candidate"],
                        "candidate_signature": best["signature"],
                        "state_hash": state["state_hash"],
                        "diagnostic_hash": diagnostic_hash(diag),
                        "ledger": value,
                        "gap": gap,
                        "checkpoint": cp,
                        "production_apply": False,
                        "trial_working_copy": True,
                    }
                    atomic_json(folder / "ACCEPTED_STATE.json", accepted_record)
                    rec.update(status="ACCEPTED", accepted_count=result["accepted_count"],
                               selected_signature=best["signature"], ledger=value,
                               gap=gap, checkpoint=cp)
                    atomic_json(out / "BLOCK_RESULT.json", rec)
                    control.checkpoint("BLOCK_ACCEPTED", force=True, phase_name=current_phase,
                                       phase_cycle=phase_cycle, block=block,
                                       accepted_count=result["accepted_count"], objective=value["total"])

                cycle_rec["objective_end"] = value["total"]
                cycle_rec["blocking_error"] = cycle_had_blocking_error
                if accepted_this_cycle == 0:
                    if cycle_had_blocking_error:
                        phase_rec["status"] = "BLOCKED_NO_ACCEPTED_WITH_ERRORS"
                        result["status"] = current_phase + "_BLOCKED_SUPPLY_NOT_ADVANCED"
                        return result
                    converged = True
                    phase_rec["status"] = "CONVERGED"
                    phase_rec["converged_cycle"] = phase_cycle
                    break

            if not converged:
                phase_rec["status"] = "MAX_CYCLES_REACHED_BEFORE_CONVERGENCE"
                result["status"] = current_phase + "_MAX_CYCLES_REACHED_SUPPLY_NOT_ADVANCED"
                return result

            phase_rec["accepted_end"] = result["accepted_count"]
            phase_rec["accepted_in_phase"] = result["accepted_count"] - phase_rec["accepted_start"]
            phase_rec["objective_end"] = value["total"]
            phase_cp = _phase_checkpoint(adapter, folder, current_phase, state, diag, value, result["accepted_count"])
            phase_rec["phase_checkpoint"] = phase_cp
            completed_phases.append(current_phase)
            result["completed_phases"] = list(completed_phases)
            if hasattr(adapter, "invalidate_cache"):
                adapter.invalidate_cache("PHASE_CONVERGED_TRANSITION", clear_proof=True)
            control.checkpoint("PHASE_CONVERGED", force=True, phase_name=current_phase,
                               accepted_count=result["accepted_count"], objective=value["total"])

        result["status"] = "CONVERGED_TG_THEN_TD_THEN_SUPPLY"
        return result

    except UserStopRequested:
        result["status"] = "USER_STOPPED_DURING_%s_AT_LAST_VERIFIED_ACCEPTED_STATE" % (current_phase or "STARTUP")
        return result
    except TimeBudgetReached:
        result["status"] = "TIME_BUDGET_REACHED_DURING_%s_AT_LAST_VERIFIED_ACCEPTED_STATE" % (current_phase or "STARTUP")
        return result
    except Exception as exc:
        result.update(status="FAILED", error=str(exc), traceback=traceback.format_exc(), current_phase=current_phase)
        if active_parent is not None:
            try:
                result["live_matches_last_accepted"] = adapter.snapshot() == active_parent["snapshot"]
                if not result["live_matches_last_accepted"]:
                    result["status"] = "FAILED_MANUAL_REOPEN_LATEST_ACCEPTED_REQUIRED"
            except Exception as verify_exc:
                result["live_matches_last_accepted"] = None
                result["accepted_state_verify_error"] = str(verify_exc)
                result["status"] = "FAILED_MANUAL_REOPEN_LATEST_ACCEPTED_REQUIRED"
        return result
    finally:
        result["elapsed_seconds"] = round(control.elapsed(), 3)
        result["completed_phases"] = list(completed_phases)
        if state is not None:
            result["final_state_hash"] = state["state_hash"]
        if diag is not None:
            result["final_diagnostic_hash"] = diagnostic_hash(diag)
        if active_parent is not None:
            result["latest_accepted_checkpoint"] = active_parent["checkpoint"]
        atomic_json(folder / "RUN_STATUS.json", result)

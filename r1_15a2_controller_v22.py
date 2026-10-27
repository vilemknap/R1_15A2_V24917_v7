"""One accepted-state authority for supply, generation and component TD.

Every trial starts from the same saved PRE state, is assigned, evaluated and
rolled back. Only the best eligible, actually evaluated state is published.
"""
from __future__ import annotations
import copy
import json
import math
import numbers
import os
from pathlib import Path
import traceback

import r1_15a2_core as core
import r1_15a2_multiblock as mb
from r1_15a2_supply import (SupplyContractError, SupplyPolicy, canonical_hash,
                          number, key_text, observation_identity, shared_ledger)


def report_safe(value):
    """Represent unavailable diagnostic metrics as null, not a selection failure.

    Scientific state and objective values are separately validated as finite.
    In particular a missing/zero-observation VALID report must not veto CAL.
    """
    if isinstance(value, dict):
        return {str(k): report_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [report_safe(x) for x in value]
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return value
    if isinstance(value, numbers.Integral):
        return int(value)
    if isinstance(value, numbers.Real):
        return float(value) if math.isfinite(float(value)) else None
    if hasattr(value, "tolist"):
        return report_safe(value.tolist())
    return value


def atomic_json(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    with temp.open("w", encoding="utf-8") as f:
        json.dump(report_safe(value), f, ensure_ascii=False, indent=2, allow_nan=False)
        f.flush(); os.fsync(f.fileno())
    os.replace(temp, path)


def json_read(path):
    with Path(path).open(encoding="utf-8-sig") as f:
        return json.load(f)


def target_identity(signals, components):
    values = []
    for comp in components:
        sig = signals.get(comp)
        if not sig or not sig.get("calibratable"):
            raise SupplyContractError("SHARED_COMPONENT_AUTHORITY_LOST:" + comp)
        bins = [{k: r[k] for k in ("bin_low", "bin_high", "target_share")} for r in sig["model_bins"]]
        values.append({"component": comp, "authority_id": sig.get("authority_id"),
                       "target_status": sig.get("target_status"), "bins": bins})
    return canonical_hash(values)


def build_reference(diag, cfg):
    components = sorted(k for k, v in diag["signals"].items() if v.get("calibratable"))
    if not components:
        raise SupplyContractError("NO_COMPONENT_OBJECTIVE_AUTHORITY")
    metrics = mb.td_component_metrics(diag["signals"], components, cfg)
    weights = {r["component"]: number(r["weight"]) for r in metrics["components"]}
    if len(weights) != len(components):
        raise SupplyContractError("MISSING_COMPONENT_REFERENCE")
    cal_metrics = core.csd_metrics(diag["d12"]["rows"])
    return {"schema": "R1_15A2_SHARED_OBJECTIVE_V22", "components": components,
            "component_weights": weights, "target_hash": target_identity(diag["signals"], components),
            "observation_hash": observation_identity(diag["d12"]["rows"]),
            "cal_objective_metric": core.csd_objective_metric(cfg),
            "cal_objective_key": core.csd_objective_key(cfg),
            "cal_scale": max(1.0, number(core.csd_objective_value(cal_metrics, cfg)))}


def ledger(diag, state, anchors, policy, reference, cfg):
    if target_identity(diag["signals"], reference["components"]) != reference["target_hash"]:
        raise SupplyContractError("COMPONENT_TARGET_CHANGED")
    if observation_identity(diag["d12"]["rows"]) != reference["observation_hash"]:
        raise SupplyContractError("OBSERVATION_AUTHORITY_CHANGED")
    metrics = mb.td_component_metrics(diag["signals"], reference["components"], cfg)
    if metrics["n"] != len(reference["components"]):
        raise SupplyContractError("INCOMPLETE_COMPONENT_OBJECTIVE")
    weights = reference["component_weights"]
    total = sum(number(r["objective"])*weights[r["component"]] for r in metrics["components"])
    component_loss = total / sum(weights.values())
    return shared_ledger(diag["d12"]["rows"], component_loss, state["addval1"], anchors, policy, reference, cfg)


def diagnostic_hash(diag):
    return canonical_hash({"counts": observation_identity(diag["d12"]["rows"], include_model=True),
                           "signals": report_safe(diag["signals"])})


def assert_freeze(before, after, block, rows=None, candidate=None, cfg=None):
    for name in ("fixed_link_hash", "dseg_hash", "operations_hash"):
        if before[name] != after[name]:
            raise SupplyContractError("FIXED_CONTEXT_CHANGED:" + name)
    if block == "SUPPLY_ADDVAL1" or block == "BASELINE_ASSIGNMENT":
        for name in ("matrix_hash", "generation_hash", "td_hash"):
            if before[name] != after[name]:
                raise SupplyContractError("SUPPLY_MUTATED_DEMAND:" + name)
        expected = dict(before["addval1"])
        for row in (candidate or {}).get("changes", []):
            k = key_text(row["key"])
            if k not in expected or expected[k] != number(row["expected_old"]):
                raise SupplyContractError("SUPPLY_EXPECTED_OLD_CHANGED")
            expected[k] = number(row["new"])
        if expected != after["addval1"]:
            raise SupplyContractError("SUPPLY_ADDITIONAL_OR_OVERWRITTEN_LINK_CHANGE")
        return
    if before["addval1"] != after["addval1"]:
        raise SupplyContractError("DEMAND_MUTATED_ADDVAL1")
    if block == "GENERATION":
        if before["td_hash"] != after["td_hash"]:
            raise SupplyContractError("GENERATION_MUTATED_TD")
        expected = copy.deepcopy(before["generation_values"])
        for row in rows or []:
            attr = row["attr"]; z = str(row["zone_no"])
            if abs(expected[attr][z]-number(row["current"])) > 1e-10:
                raise SupplyContractError("GENERATION_EXPECTED_OLD_CHANGED")
            expected[attr][z] = number(row["proposed"])
        if canonical_hash(expected) != canonical_hash(after["generation_values"]):
            raise SupplyContractError("UNREQUESTED_GENERATION_PARAMETER_CHANGE")
    else:
        if before["generation_hash"] != after["generation_hash"]:
            raise SupplyContractError("TD_MUTATED_GENERATION")
        expected = copy.deepcopy(before["td_values"])
        bycomp = {r["component"]: r for r in expected}
        for row in rows or []:
            bycomp[row["component"]]["current_b"] = number(row["candidate_b"])
            bycomp[row["component"]]["current_c"] = number(row["candidate_c"])
        if canonical_hash(expected) != canonical_hash(after["td_values"]):
            raise SupplyContractError("UNREQUESTED_TD_PARAMETER_CHANGE")
    bmap = {r["matrix_no"]: r for r in before["matrices"]}
    amap = {r["matrix_no"]: r for r in after["matrices"]}
    if set(bmap) != set(amap):
        raise SupplyContractError("MATRIX_SET_CHANGED")
    # These exogenous classes are not actuators of either demand block.
    protected = {9116}
    protected.update(int(no) for code, no in before.get("dseg_map", {}).items()
                     if code.startswith("EXOG_EE_") or code in ("LNV", "NV"))
    protected.update(int(no) for no in (cfg or {}).get("fixed_demand_matrix_nos", []))
    for no in protected & set(bmap):
        if bmap[no] != amap[no]:
            raise SupplyContractError("DEMAND_MUTATED_FIXED_MATRIX:%s" % no)
    scope = (cfg or {}).get("matrix_scope_by_block", {}).get(block, {})
    required_nos = set(scope.get("matrix_nos", []))
    for code in scope.get("dseg_codes", []):
        no = before["dseg_map"].get(core.norm_code(code))
        if no is None:
            raise SupplyContractError("BLOCK_DSEG_MISSING")
        required_nos.add(int(no))
    changed = [no for no in required_nos if no in bmap and bmap[no]["sha256_float64_le"] != amap[no]["sha256_float64_le"]]
    if not required_nos or len(changed) < int((cfg or {}).get("min_changed_matrices_by_block", {}).get(block, 1)):
        raise SupplyContractError("REQUIRED_BLOCK_MATRICES_UNCHANGED")


def publish(folder, checkpoint, state, diag, reference, anchors, cfg_hash, block, cycle, value):
    payload = {"schema": "R1_15A2_ACCEPTED_STATE_V22", "checkpoint": checkpoint, "snapshot": state,
               "diagnostic_hash": diagnostic_hash(diag), "reference": reference,
               "original_addval_anchors": anchors, "config_hash": cfg_hash,
               "block": block, "cycle": cycle, "ledger": value}
    payload["accepted_state_hash"] = canonical_hash(payload)
    atomic_json(Path(folder) / "ACCEPTED_STATE.json", payload)
    return payload


def restore_published(adapter, folder, cfg_hash):
    record = json_read(Path(folder) / "ACCEPTED_STATE.json")
    raw = {k: v for k, v in record.items() if k != "accepted_state_hash"}
    if canonical_hash(raw) != record.get("accepted_state_hash") or record.get("config_hash") != cfg_hash:
        raise SupplyContractError("RECOVERY_AUTHORITY_MISMATCH")
    adapter.restore(record["checkpoint"], record["snapshot"])
    adapter.baseline_addval = {tuple(int(x) for x in k.split("|")): v for k, v in record["original_addval_anchors"].items()}
    return record


def run_calibration(adapter, cfg, folder, *, resume_from=None):
    folder = Path(folder); folder.mkdir(parents=True, exist_ok=True)
    policy = SupplyPolicy.from_config(cfg)
    science = {k: v for k, v in cfg.items() if k not in
               ("apply", "max_cycles", "max_accepted_blocks", "resume_from", "config_path", "config_sha256") and not k.endswith("_path")}
    cfg_hash = canonical_hash(science)
    result = {"status": "STARTED", "apply": bool(cfg.get("apply")), "blocks": [], "cycles": [],
              "accepted_count": 0, "config_hash": cfg_hash, "writes_direct_od_matrix": False,
              "runtime_backend": getattr(adapter, "runtime_backend", "UNSPECIFIED_ADAPTER")}
    atomic_json(folder / "EFFECTIVE_CONFIG.json", cfg)
    active_restore = None
    try:
        if cfg.get("apply") and not cfg.get("run_procseq", True):
            raise SupplyContractError("APPLY_REQUIRES_REAL_ASSIGNMENT_EXECUTION")
        if cfg.get("supply", {}).get("enabled") is False and "SUPPLY_ADDVAL1" in cfg.get("block_schedule", []):
            raise SupplyContractError("DISABLED_SUPPLY_IN_ACTIVE_SCHEDULE")
        allowed = {"SUPPLY_ADDVAL1", "GENERATION", "TD_COMPONENT_WORK", "TD_COMPONENT_SERVICE", "TD_COMPONENT_SCHOOL", "TD_COMPONENT_LONG"}
        schedule = cfg.get("block_schedule", [])
        if not schedule or len(set(schedule)) != len(schedule) or not set(schedule) <= allowed:
            raise SupplyContractError("INVALID_BLOCK_SCHEDULE")
        for budget in ("max_cycles", "max_accepted_blocks"):
            x = number(cfg.get(budget, 1))
            if x != int(x) or not 1 <= x <= 100:
                raise SupplyContractError("INVALID_BUDGET:" + budget)
        scales = cfg.get("backtracking_scales", [])
        if not scales or any(not 0 < number(x) <= 1 for x in scales):
            raise SupplyContractError("INVALID_BACKTRACKING_SCALES")
        # A read-only design must NEVER LoadVersion into a session with live
        # network-element COM proxies. Recovery requires reopening a .ver manually.
        if not cfg.get("apply") and resume_from:
            raise SupplyContractError("DESIGN_ONLY_RESUME_COM_LOADVERSION_FORBIDDEN")
        resumed = restore_published(adapter, resume_from, cfg_hash) if resume_from else None
        if resumed:
            result["recovery_semantics"] = "RESTART_CYCLE_FROM_ACCEPTED_WITH_PRESERVED_ANCHORS"
        result["preflight"] = adapter.preflight(folder)
        if resumed:
            adapter.baseline_addval = {tuple(int(x) for x in k.split("|")): v for k, v in resumed["original_addval_anchors"].items()}
        baseline_folder = folder / "BASELINE"; baseline_folder.mkdir()
        if cfg.get("apply"):
            initial = adapter.snapshot(); initial_checkpoint = adapter.save(baseline_folder / "BEFORE_ASSIGNMENT.ver")
            active_restore = (initial_checkpoint, initial)
            adapter.assign(baseline_folder, supply_only=True)
            assert_freeze(initial, adapter.snapshot(), "BASELINE_ASSIGNMENT")
            active_restore = None
        diag_parent = adapter.snapshot()
        diag_pre = adapter.save(baseline_folder / "READ_ONLY_GUARD.ver")
        # The checkpoint remains available for MANUAL reopening if needed.
        # Auto-LoadVersion in read-only mode is counterproductive: exception
        # frames can retain thousands of network objects referenced from COM.
        active_restore = (diag_pre, diag_parent) if cfg.get("apply") else None
        diag = adapter.diagnostics(baseline_folder)
        state = adapter.snapshot()
        if state != diag_parent:
            raise SupplyContractError("BASELINE_DIAGNOSTICS_CHANGED_MODEL")
        active_restore = None
        reference = resumed["reference"] if resumed else build_reference(diag, cfg)
        anchors = resumed["original_addval_anchors"] if resumed else dict(state["addval1"])
        value = ledger(diag, state, anchors, policy, reference, cfg)
        atomic_json(folder / "OBJECTIVE_REFERENCE.json", reference)
        atomic_json(folder / "ORIGINAL_ADDVAL1_ANCHORS.json", anchors)
        if not cfg.get("apply"):
            result["read_only_recovery_policy"] = (
                "NO_AUTOMATIC_LOADVERSION; SNAPSHOT_VERIFY_EVERY_BLOCK; "
                "MANUAL_REOPEN_SAVED_VER_ON_DRIFT")
            for block in cfg["block_schedule"]:
                out = folder / ("DESIGN_" + block); out.mkdir()
                rec = {"block": block}
                try:
                    checkpoint = getattr(adapter, "design_checkpoint", None)
                    if checkpoint is not None:
                        checkpoint("DESIGN_" + block)
                    if block == "SUPPLY_ADDVAL1":
                        design = adapter.supply_design(diag, out, state)
                        scope_qa = design.get("duplicate_scope_audit", {})
                        rec.update(status="DESIGNED", candidates=len(design["candidates"]),
                                   provisional_geometry=bool(design.get("provisional", False)),
                                   conflicting_same_source_groups=scope_qa.get("conflicting_same_source_groups", 0),
                                   overlapping_directed_link_group_count=scope_qa.get("overlapping_directed_link_group_count", 0),
                                   duplicate_scope_review_required=bool(
                                       scope_qa.get("conflicting_same_source_groups", 0) or
                                       scope_qa.get("overlapping_directed_link_group_count", 0)))
                    elif block == "GENERATION":
                        ctx = adapter.generation_design(diag, out)
                        # The existing generation implementation is only designed here.
                        design = adapter.generation_preview(ctx, 1.0)
                        atomic_json(out / "GENERATION_PROPOSAL.json", design)
                        rec.update(status="DESIGNED", candidates=len(design["candidate_rows"]))
                    else:
                        design = adapter.td_design(diag, block, 1.0, out)
                        atomic_json(out / "TD_PROPOSAL.json", design)
                        rec.update(status="DESIGNED" if design["candidate_rows"] else "NO_COMPONENT_CANDIDATE",
                                   candidates=len(design["candidate_rows"]))
                except Exception as exc:
                    rec.update(status="STOPPED" if getattr(exc, "stop_design_run", False) else "BLOCKED",
                               error=str(exc), error_type=type(exc).__name__,
                               stop_design_run=bool(getattr(exc, "stop_design_run", False)))
                # Verify even after a failed design. Snapshot failure or drift
                # stops immediately; NEVER LoadVersion over live COM references.
                try:
                    current_state = adapter.snapshot()
                except Exception as check_exc:
                    rec.update(status="UNVERIFIED_STOP", snapshot_error=str(check_exc))
                    result["blocks"].append(rec)
                    raise SupplyContractError(
                        "DESIGN_ONLY_POST_BLOCK_SNAPSHOT_UNREADABLE_MANUAL_REOPEN_REQUIRED:" + block) from check_exc
                if current_state != state:
                    rec.update(status="STATE_DRIFT_STOP", model_unchanged=False)
                    result["blocks"].append(rec)
                    raise SupplyContractError(
                        "DESIGN_ONLY_STATE_DRIFT_MANUAL_REOPEN_REQUIRED:" + block)
                rec["model_unchanged"] = True
                rec["rollback_action"] = "NOT_REQUIRED_READ_ONLY"
                result["blocks"].append(rec)
                atomic_json(folder / "RUN_STATUS.json", result)
                if rec.get("stop_design_run"):
                    result["status"] = "DESIGN_ONLY_STOPPED"
                    result["stop_reason"] = rec["error"]
                    return result
            result["status"] = (
                "DESIGN_ONLY_BLOCKERS" if any(x["status"] == "BLOCKED" for x in result["blocks"]) else
                "DESIGN_ONLY_COMPLETE_PROVISIONAL_GEOMETRY" if any(x.get("provisional_geometry") for x in result["blocks"]) else
                "DESIGN_ONLY_NEEDS_DUPLICATE_SCOPE_QA" if any(
                    x.get("duplicate_scope_review_required") for x in result["blocks"]) else
                "DESIGN_ONLY_READY_FOR_LIVE_APPLY_GATE")
            return result
        cp = adapter.save(baseline_folder / "ACCEPTED_BASELINE.ver")
        publish(folder, cp, state, diag, reference, anchors, cfg_hash, "BASELINE", 0, value)
        max_accepted = int(cfg.get("max_accepted_blocks", 1))
        for cycle in range(1, int(cfg.get("max_cycles", 2))+1):
            accepted_this_cycle = 0; examined = []
            for block in cfg["block_schedule"]:
                if (folder / "STOP_REQUESTED").exists():
                    result["status"] = "SAFE_STOP_AT_BLOCK_BOUNDARY"
                    return result
                if result["accepted_count"] >= max_accepted:
                    result["status"] = "BOUNDED_ACCEPTED_LIMIT"
                    return result
                examined.append(block)
                out = folder / ("CYCLE_%02d_%s" % (cycle, block)); out.mkdir()
                rec = {"cycle": cycle, "block": block, "attempts": []}; result["blocks"].append(rec)
                before = adapter.snapshot()
                if before != state:
                    raise SupplyContractError("ACCEPTED_STATE_MUTATED_BETWEEN_BLOCKS")
                context = None
                try:
                    if block == "SUPPLY_ADDVAL1":
                        design = adapter.supply_design(diag, out, state)
                        candidates = design["candidates"]
                    elif block == "GENERATION":
                        context = adapter.generation_design(diag, out)
                        candidates = [{"scale": float(x)} for x in cfg["backtracking_scales"]]
                    else:
                        candidates = [{"scale": float(x)} for x in cfg["backtracking_scales"]]
                except Exception as exc:
                    rec.update(status="BLOCKED_DESIGN", error=str(exc))
                    continue
                if not candidates:
                    rec["status"] = "NO_CANDIDATE"; continue
                pre = adapter.save(out / "PRE.ver")
                if adapter.snapshot() != before:
                    raise SupplyContractError("DESIGN_OR_SAVE_CHANGED_STATE")
                best = None
                for ordinal, candidate in enumerate(candidates, start=1):
                    attempt_folder = out / ("TRY_%02d" % ordinal); attempt_folder.mkdir()
                    trial = {"candidate": candidate, "status": "STARTED"}; rec["attempts"].append(trial)
                    rows = []
                    try:
                        if adapter.snapshot() != before:
                            raise SupplyContractError("TRIAL_NOT_FROM_IDENTICAL_PARENT")
                        if block.startswith("TD_"):
                            design = adapter.td_design(diag, block, candidate["scale"], attempt_folder)
                            rows = design["candidate_rows"]
                            atomic_json(attempt_folder / "TD_DESIGN.json", design)
                            if not rows:
                                trial["status"] = "NO_COMPONENT_CANDIDATE"; continue
                        atomic_json(folder / "IN_FLIGHT.json", {"checkpoint": pre, "snapshot": before,
                                    "config_hash": cfg_hash, "block": block, "cycle": cycle})
                        active_restore = (pre, before)
                        if block == "SUPPLY_ADDVAL1":
                            adapter.apply_supply(candidate, before, attempt_folder)
                        elif block == "GENERATION":
                            rows = adapter.apply_generation(context, candidate["scale"], attempt_folder)
                        else:
                            adapter.apply_td(rows)
                        adapter.assign(attempt_folder, supply_only=(block == "SUPPLY_ADDVAL1"))
                        if block != "SUPPLY_ADDVAL1":
                            adapter.parameter_persistence(block, rows)
                        after = adapter.snapshot()
                        assert_freeze(before, after, block, rows, candidate, cfg)
                        after_diag = adapter.diagnostics(attempt_folder, "AFTER")
                        if adapter.snapshot() != after:
                            raise SupplyContractError("DIAGNOSTICS_CHANGED_MODEL")
                        after_value = ledger(after_diag, after, anchors, policy, reference, cfg)
                        decision = adapter.block_gate(block, diag, after_diag, rows)
                        delta = value["total"]-after_value["total"]
                        decision["shared_ledger_before"] = value; decision["shared_ledger_after"] = after_value
                        if delta <= number(cfg.get("shared_objective", {}).get("minimum_improvement", 1e-8)):
                            decision["accepted"] = False
                            decision["reasons"].append("SHARED_OBJECTIVE_NOT_IMPROVED")
                        atomic_json(attempt_folder / "ACCEPTANCE.json", decision)
                        trial.update(status="ELIGIBLE" if decision["accepted"] else "REJECTED", decision=decision)
                        if decision["accepted"] and (best is None or after_value["total"] < best["value"]["total"]):
                            saved = adapter.save(attempt_folder / "EVALUATED_CANDIDATE.ver")
                            best = {"checkpoint": saved, "snapshot": after, "diag": after_diag, "value": after_value,
                                    "trial": ordinal, "candidate": candidate}
                    except Exception as exc:
                        trial.update(status="FAILED_ROLLED_BACK", error=str(exc), traceback=traceback.format_exc())
                    finally:
                        if active_restore:
                            adapter.restore(pre, before)
                            active_restore = None
                            rollback_diag = adapter.diagnostics(attempt_folder, "ROLLBACK")
                            if diagnostic_hash(rollback_diag) != diagnostic_hash(diag):
                                raise SupplyContractError("ROLLBACK_ASSIGNMENT_DIAGNOSTICS_DIFFER")
                            trial["rollback_verified"] = True
                            atomic_json(attempt_folder / "TRIAL_RESULT.json", trial)
                            if (folder / "IN_FLIGHT.json").exists():
                                (folder / "IN_FLIGHT.json").unlink()
                if best is None:
                    rec["status"] = "NO_ACCEPTED_CANDIDATE"
                    continue
                active_restore = (pre, before)
                adapter.restore(best["checkpoint"], best["snapshot"])
                adopted_diag = adapter.diagnostics(out, "SELECTED")
                if diagnostic_hash(adopted_diag) != diagnostic_hash(best["diag"]):
                    raise SupplyContractError("SELECTED_STATE_ASSIGNMENT_MISMATCH")
                accepted_cp = adapter.save(out / "ACCEPTED.ver")
                if adapter.snapshot() != best["snapshot"]:
                    raise SupplyContractError("SELECTED_CHECKPOINT_CHANGED_PARAMETERS")
                publish(folder, accepted_cp, best["snapshot"], adopted_diag, reference, anchors, cfg_hash,
                        block, cycle, best["value"])
                active_restore = None
                state = best["snapshot"]; diag = adopted_diag; value = best["value"]
                rec.update(status="ACCEPTED", selected_trial=best["trial"], ledger=value,
                           checkpoint=accepted_cp)
                result["accepted_count"] += 1; accepted_this_cycle += 1
            review = {"cycle": cycle, "examined": examined, "accepted": accepted_this_cycle,
                      "scientific_optimum_claimed": False}
            result["cycles"].append(review)
            if not accepted_this_cycle:
                blocked = any(r.get("status") == "BLOCKED_DESIGN" or
                              any(t.get("status", "").startswith("FAILED") for t in r.get("attempts", []))
                              for r in result["blocks"] if r.get("cycle") == cycle)
                result["status"] = "BLOCKED_CYCLE_NO_ACCEPTED_CANDIDATE" if blocked else "COMPLETE_CYCLE_NO_ACCEPTED_IMPROVEMENT"
                return result
        result["status"] = "BOUNDED_CYCLE_LIMIT"
    except Exception as exc:
        result.update(status="BLOCKED_OR_FAILED", error=str(exc), traceback=traceback.format_exc())
        if not cfg.get("apply"):
            result["read_only_automatic_restore"] = "NOT_ATTEMPTED_BY_DESIGN"
            if "diag_parent" in locals():
                try:
                    result["read_only_model_unchanged"] = adapter.snapshot() == diag_parent
                except Exception as snapshot_exc:
                    result["read_only_model_unchanged"] = None
                    result["read_only_verify_error"] = str(snapshot_exc)
            if result.get("read_only_model_unchanged") is not True:
                result["status"] = "DESIGN_ONLY_MODEL_STATE_UNVERIFIED_MANUAL_REOPEN_REQUIRED"
        elif active_restore:
            try:
                adapter.restore(*active_restore)
                result["emergency_rollback_verified"] = True
            except Exception as restore_exc:
                result["emergency_rollback_verified"] = False
                result["rollback_error"] = str(restore_exc)
                result["status"] = "ROLLBACK_FAILED_STOP_MANUAL_RECOVERY_REQUIRED"
    finally:
        atomic_json(folder / "RUN_STATUS.json", result)
    return result

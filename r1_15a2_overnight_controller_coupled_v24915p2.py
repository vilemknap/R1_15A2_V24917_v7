# -*- coding: utf-8 -*-
"""V24915 PERF2 CandidateReadbackBundle coupled demand -> supply controller.

Scientific order:
  accepted joint demand state
    -> one trip-generation coefficient update (counts/GEH objective)
    -> re-calibrate b,c with the exact v1.7 512-point IDP FineCDF objective
    -> full downstream Procedure Sequence + assignment
    -> repeat the joint demand cycle until BOTH substeps are stationary
    -> only then unlock ADDVAL1 route-choice calibration.

Trip generation and trip distribution are therefore not independent phases.
ADDVAL1 can never start from a demand state that has not reached this joint fixed point.
"""
from __future__ import annotations

import copy
import hashlib
import inspect
import json
import math
import os
import shutil
from pathlib import Path
from r1_15a2_safety_v245 import adapter_config_scope, recovery_scope, stationary_td_result
import traceback

import r1_15a2_core as core
from r1_15a2_controller_v22 import atomic_json, build_reference, ledger, diagnostic_hash
from r1_15a2_inplace_transaction_v24915p2 import rollback_and_verify, restore_td_parameters
from r1_15a2_overnight_controller_v24915p2 import (
    UserStopRequested, TimeBudgetReached,
    _planned_generation_rows, _evaluate_candidate, _adopt_candidate,
    _first_sufficient_candidate, _assign_candidate,
    _save_rotating_checkpoint, run_overnight_calibration,
    _final_snapshot_with_retry, _mark_transient_final_verification_failure,
)
import r1_15a2_com_compat as com
from r1_15a2_supply import SupplyContractError, SupplyPolicy, canonical_hash, number
from r1_15a2_finecdf_bridge_v242 import run_finecdf_inner, REF_SHA256


V24914_BOUNDED_INNER_BUDGET_STOP_REASONS = frozenset((
    "MAX_ITERATIONS",
    "TD_EVALUATION_BUDGET",
    "TD_INNER_TIME_BUDGET",
))


def _runtime_demand_continuation(cfg):
    """Return a validated runtime continuation descriptor.

    V24914 injects this descriptor only after the live opened model has passed
    exact semantic comparison with the A0009 authority.  Older releases and
    frozen fixtures omit it and retain cycle-1 / accepted-count-0 behavior.
    """
    raw = cfg.get("runtime_demand_continuation", {}) or {}
    if raw.get("enabled") is not True:
        return {
            "enabled": False,
            "accepted_count": 0,
            "next_outer_cycle": 1,
            "inherited_outer_cycles": 0,
            "inherited_stationary_cycle_streak": 0,
            "inherited_completed_demand_cycles": 0,
        }
    required_ints = (
        "accepted_count", "next_outer_cycle", "inherited_outer_cycles",
        "inherited_stationary_cycle_streak", "inherited_completed_demand_cycles",
        "max_lineage_outer_cycle",
    )
    for name in required_ints:
        try:
            value = int(raw[name])
        except Exception as exc:
            raise SupplyContractError("V24914_CONTINUATION_FIELD_INVALID:" + name) from exc
        if value < 0:
            raise SupplyContractError("V24914_CONTINUATION_FIELD_NEGATIVE:" + name)
    accepted = int(raw["accepted_count"])
    inherited = int(raw["inherited_outer_cycles"])
    next_outer = int(raw["next_outer_cycle"])
    max_lineage = int(raw["max_lineage_outer_cycle"])
    if next_outer != inherited + 1:
        raise SupplyContractError("V24914_CONTINUATION_CYCLE_DISCONTINUITY")
    if next_outer < 1 or next_outer > max_lineage:
        raise SupplyContractError("V24914_CONTINUATION_CYCLE_OUT_OF_RANGE")
    if accepted < 1:
        raise SupplyContractError("V24914_CONTINUATION_ACCEPTED_COUNT_NOT_POSITIVE")
    stop_reasons = tuple(raw.get("bounded_inner_budget_stop_reasons", ()))
    if stop_reasons and set(stop_reasons) != set(V24914_BOUNDED_INNER_BUDGET_STOP_REASONS):
        raise SupplyContractError("V24914_CONTINUATION_BUDGET_REASON_SET_MISMATCH")
    resume_substep = str(raw.get("resume_substep", "GENERATION") or "GENERATION").upper()
    if resume_substep not in ("GENERATION", "TD_FINECDF_V17"):
        raise SupplyContractError("V24915R4_CONTINUATION_RESUME_SUBSTEP_INVALID")
    if resume_substep == "TD_FINECDF_V17":
        if int(raw.get("resume_outer_cycle", -1)) != next_outer:
            raise SupplyContractError("V24915R4_CONTINUATION_RESUME_CYCLE_MISMATCH")
        if raw.get("resume_generation_completed") is not True or raw.get("resume_td_completed") is not False:
            raise SupplyContractError("V24915R4_CONTINUATION_PARTIAL_CYCLE_FLAGS_INVALID")
        if not isinstance(raw.get("resume_generation_changed"), bool):
            raise SupplyContractError("V24915R4_CONTINUATION_GENERATION_CHANGE_FLAG_INVALID")
        reference = raw.get("generation_reference")
        if not isinstance(reference, dict) or reference.get("schema") != "R1_15A2_SHARED_OBJECTIVE_V22":
            raise SupplyContractError("V24915R4_CONTINUATION_GENERATION_REFERENCE_MISSING")
        record = raw.get("resume_generation_record")
        if not isinstance(record, dict) or record.get("search_complete") is not True:
            raise SupplyContractError("V24915R4_CONTINUATION_GENERATION_RECORD_INVALID")
    return copy.deepcopy(dict(raw))


def _bounded_inner_budget_stop(inner):
    reason = str((inner or {}).get("stop_reason", ""))
    return reason in V24914_BOUNDED_INNER_BUDGET_STOP_REASONS


def _bounded_inner_budget_cycle_status(generation_changed, td_changed):
    if generation_changed or td_changed:
        return "PROGRESS_CONTINUE_DEMAND_ACCEPTED_BUDGET"
    return "BOUNDED_SEARCH_CONTINUE_DEMAND_NO_ACCEPTED_CHANGE"


def _generation_step_for_cycle(cfg, outer_cycle=None):
    """Return an explicit generation step stage without mutating the source config.

    A missing schedule preserves the V2.4.5 behavior.  Stages may enlarge early
    proposal bounds, but the final stage must restore the complete configured
    generation search envelope; the V2.4.6 hard validator enforces that rule.
    """
    stages = cfg.get("performance", {}).get("generation_step_schedule", [])
    if not stages or outer_cycle is None:
        return {}
    outer_cycle = int(outer_cycle)
    previous = 0
    for raw in stages:
        stage = dict(raw)
        through = int(stage.get("through_outer_cycle", 0))
        if through <= previous:
            raise SupplyContractError("V246_INVALID_GENERATION_STEP_SCHEDULE")
        previous = through
        if outer_cycle <= through:
            stage.setdefault("name", "GEN_STAGE_%d" % through)
            return stage
    raise SupplyContractError("V246_GENERATION_STEP_SCHEDULE_DOES_NOT_COVER_OUTER_CYCLE")


def _generation_counts_cfg(cfg, outer_cycle=None):
    """Generation is fitted to CAL counts; IDP is repaired immediately by TD."""
    c = copy.deepcopy(cfg)
    stage = _generation_step_for_cycle(cfg, outer_cycle)
    if stage:
        for key in ("max_od_relative_up", "max_od_relative_down",
                    "max_add_log_up", "max_add_log_down"):
            if key in stage:
                c[key] = float(stage[key])
        signed = c.setdefault("generation_signed_refinement", {})
        for stage_key, policy_key in (
                ("signed_max_family_global_log_up", "max_family_global_log_up"),
                ("signed_max_family_global_log_down", "max_family_global_log_down"),
                ("signed_soft_outward_step_factor", "soft_outward_step_factor")):
            if stage_key in stage:
                signed[policy_key] = float(stage[stage_key])
        if "salary_max_abs_delta_per_block" in stage:
            c.setdefault("salary", {})["max_abs_delta_per_block"] = float(
                stage["salary_max_abs_delta_per_block"])
        c.setdefault("performance", {})["active_generation_step_stage"] = stage
    c.setdefault("shared_objective", {})["idp_weight"] = 0.0
    # core.acceptance_decision still reports IDP but must not veto the TG substep;
    # the following FineCDF substep owns the IDP objective in the same demand cycle.
    c["idp_max_mean_degradation"] = 1.0e30
    c["idp_max_component_degradation"] = 1.0e30
    c.setdefault("coupled_demand", {})["generation_acceptance"] = "CAL_COUNTS_ONLY_IDP_DEFERRED_TO_IMMEDIATE_FINECDF_TD"
    if outer_cycle is not None:
        c["runtime_acceptance_outer_cycle"] = int(outer_cycle)
        c["runtime_acceptance_scope"] = "GENERATION"
    return c


def _td_acceptance_cfg_for_cycle(cfg, outer_cycle=None):
    """Bind TD acceptance to the outer-cycle exploration stage without drift."""
    c = copy.deepcopy(cfg)
    if outer_cycle is not None:
        c["runtime_acceptance_outer_cycle"] = int(outer_cycle)
        c["runtime_acceptance_scope"] = "TD"
    return c


def _td_expected_freeze(before, after, changed_rows, cfg=None, audit_path=None):
    """Verify TD authority with exact frozen context and tolerant b/c read-back.

    Only ``current_b``/``current_c`` are compared numerically.  Every other
    frozen context hash and every non-numeric TD-row field remains exact.  This
    fixes the V2.4.8.9 false positive caused by COM floating-point round-trip
    noise without turning genuine cross-component mutations into accepted
    changes.
    """
    cfg = cfg or {}
    fine = cfg.get("coupled_demand", {}).get("finecdf_td", {})
    atol = float(fine.get("realization_parameter_atol", 1.0e-8))
    rtol = float(fine.get("realization_parameter_rtol", 1.0e-10))
    if (not math.isfinite(atol) or atol < 0.0 or
            not math.isfinite(rtol) or rtol < 0.0):
        raise SupplyContractError("V2490_TD_PARAMETER_TOLERANCE_INVALID")

    frozen_names = ("fixed_link_hash", "dseg_hash", "operations_hash",
                    "addval_hash", "generation_hash")
    frozen_failures = []
    for name in frozen_names:
        if before.get(name) != after.get(name):
            frozen_failures.append(name)
    if frozen_failures:
        raise SupplyContractError(
            "V242_TD_CHANGED_FROZEN_CONTEXT:" + ",".join(frozen_failures))

    before_rows = list(before.get("td_values", []))
    after_rows = list(after.get("td_values", []))
    before_map = {str(r.get("component")): r for r in before_rows}
    after_map = {str(r.get("component")): r for r in after_rows}
    if len(before_map) != len(before_rows) or len(after_map) != len(after_rows):
        raise SupplyContractError("V2490_TD_PARAMETER_DUPLICATE_COMPONENT")
    if set(before_map) != set(after_map):
        raise SupplyContractError("V2490_TD_PARAMETER_COMPONENT_SET_CHANGED")

    requested = {str(r.get("component")): r for r in (changed_rows or [])}
    if len(requested) != len(changed_rows or []):
        raise SupplyContractError("V2490_TD_REQUEST_DUPLICATE_COMPONENT")
    unknown = sorted(set(requested) - set(before_map))
    if unknown:
        raise SupplyContractError(
            "V242_TD_CHANGED_UNKNOWN_COMPONENT:" + ",".join(unknown))

    audit = []
    failures = []
    for component in sorted(before_map):
        b = before_map[component]
        a = after_map[component]
        req = requested.get(component)

        # Component metadata/status remain exact.  Only the floating b/c values
        # receive a narrow numeric tolerance.
        meta_before = {k: v for k, v in b.items()
                       if k not in ("current_b", "current_c")}
        meta_after = {k: v for k, v in a.items()
                      if k not in ("current_b", "current_c")}
        metadata_ok = meta_before == meta_after

        expected_b = number(req["candidate_b"]) if req is not None else number(b["current_b"])
        expected_c = number(req["candidate_c"]) if req is not None else number(b["current_c"])
        actual_b = number(a["current_b"])
        actual_c = number(a["current_c"])
        if not all(math.isfinite(v) for v in (expected_b, expected_c, actual_b, actual_c)):
            raise SupplyContractError("V2490_TD_PARAMETER_NONFINITE:" + component)
        tol_b = max(atol, rtol * max(1.0, abs(expected_b), abs(actual_b)))
        tol_c = max(atol, rtol * max(1.0, abs(expected_c), abs(actual_c)))
        db = abs(actual_b - expected_b)
        dc = abs(actual_c - expected_c)
        passes = bool(metadata_ok and db <= tol_b and dc <= tol_c)
        row = {
            "component": component,
            "requested_change": req is not None,
            "before_b": number(b["current_b"]),
            "before_c": number(b["current_c"]),
            "expected_b": expected_b, "expected_c": expected_c,
            "actual_b": actual_b, "actual_c": actual_c,
            "abs_error_b": db, "abs_error_c": dc,
            "tolerance_b": tol_b, "tolerance_c": tol_c,
            "metadata_equal": metadata_ok,
            "passes": passes,
        }
        audit.append(row)
        if not passes:
            failures.append(row)

    # td_hash remains an integrity checksum of the *raw* read-back structure,
    # not an exact-equality acceptance authority.  Verify self-consistency when
    # the snapshot provides it so a stale/corrupted snapshot cannot hide here.
    after_hash = after.get("td_hash")
    if after_hash is not None:
        actual_hash = canonical_hash(sorted(after_rows, key=lambda r: str(r.get("component"))))
        if actual_hash != after_hash:
            raise SupplyContractError("V2490_TD_HASH_SELF_INCONSISTENT")

    evidence = {
        "schema": "R1_15A2_V2490_TD_PARAMETER_FREEZE_AUDIT_V2",
        "comparison": "EXACT_FROZEN_CONTEXT_AND_METADATA__NUMERIC_B_C_ONLY",
        "absolute_tolerance": atol,
        "relative_tolerance": rtol,
        "requested_components": sorted(requested),
        "frozen_context_fields": list(frozen_names),
        "passes": not failures,
        "rows": audit,
    }
    if audit_path is not None:
        atomic_json(Path(audit_path), evidence)
    if failures:
        metadata = [r for r in failures if not r["metadata_equal"]]
        if metadata:
            raise SupplyContractError(
                "V2490_TD_PARAMETER_METADATA_CHANGED:" +
                ",".join(r["component"] for r in metadata))
        unrequested = [r for r in failures if not r["requested_change"]]
        if unrequested:
            raise SupplyContractError(
                "V2490_TD_UNREQUESTED_PARAMETER_CHANGE:" +
                ",".join(r["component"] for r in unrequested))
        raise SupplyContractError(
            "V2490_TD_REQUESTED_PARAMETER_NOT_REALIZED:" +
            ",".join(r["component"] for r in failures))
    return audit


def _all_td_restore_rows(before):
    return [{"component": r["component"]} for r in before["td_values"]]


def _finecdf_budget_for_cycle(cfg, outer_cycle):
    stages = cfg.get("coupled_demand", {}).get("finecdf_td", {}).get("progressive_schedule", [])
    if not stages:
        return {}
    outer_cycle = int(outer_cycle)
    previous = 0
    for raw in stages:
        stage = dict(raw)
        through = int(stage.get("through_outer_cycle", 0))
        if through <= previous:
            raise SupplyContractError("V246_INVALID_PROGRESSIVE_TD_SCHEDULE")
        previous = through
        if outer_cycle <= through:
            stage.setdefault("name", "STAGE_%d" % through)
            return stage
    raise SupplyContractError("V246_PROGRESSIVE_TD_SCHEDULE_DOES_NOT_COVER_OUTER_CYCLE")


def _td_realization_scales(cfg):
    """Return strict, decreasing scales for full downstream TD realization.

    The scale is applied in native parameter coordinates: b linearly and c in
    log(-c), because c is strictly negative and the FineCDF search itself uses
    log(-c).  This is a parameter backtrack only; no IPF or procedure tolerance
    is changed.
    """
    td_cfg = cfg.get("coupled_demand", {}).get("finecdf_td", {})
    raw = td_cfg.get("realization_backtracking_scales", [1.0, 0.5, 0.25, 0.125, 0.0625])
    try:
        scales = [float(v) for v in raw]
    except Exception as exc:
        raise SupplyContractError("V2489_TD_REALIZATION_SCALES_INVALID") from exc
    if (not scales or abs(scales[0] - 1.0) > 1e-12 or
            any((not math.isfinite(v)) or v <= 0.0 or v > 1.0 for v in scales) or
            any(scales[i] <= scales[i + 1] for i in range(len(scales) - 1))):
        raise SupplyContractError("V2489_TD_REALIZATION_SCALES_INVALID")
    return scales


def _td_rows_at_scale(before, target_rows, scale):
    """Interpolate b linearly and c geometrically in log(-c)."""
    scale = float(scale)
    if not math.isfinite(scale) or scale <= 0.0 or scale > 1.0:
        raise SupplyContractError("V2489_TD_REALIZATION_SCALE_OUT_OF_RANGE")
    parent = {str(r["component"]): r for r in before.get("td_values", [])}
    rows = []
    for target in target_rows:
        component = str(target["component"])
        if component not in parent:
            raise SupplyContractError("V2489_TD_REALIZATION_UNKNOWN_COMPONENT:" + component)
        old = parent[component]
        b0 = number(old["current_b"]); c0 = number(old["current_c"])
        b1 = number(target["candidate_b"]); c1 = number(target["candidate_c"])
        if not all(math.isfinite(v) for v in (b0, c0, b1, c1)):
            raise SupplyContractError("V2489_TD_REALIZATION_NONFINITE:" + component)
        if c0 >= 0.0 or c1 >= 0.0:
            raise SupplyContractError("V2489_TD_REALIZATION_C_NOT_NEGATIVE:" + component)
        b = b1 if abs(scale - 1.0) <= 1e-15 else b0 + scale * (b1 - b0)
        if c0 == c1:
            c = c0
        elif abs(scale - 1.0) <= 1e-15:
            c = c1
        else:
            log_c = math.log(-c0) + scale * (math.log(-c1) - math.log(-c0))
            c = -math.exp(log_c)
        rows.append({
            "component": component,
            "candidate_b": b,
            "candidate_c": c,
            "realization_scale": scale,
            "parent_b": b0,
            "parent_c": c0,
            "target_b": b1,
            "target_c": c1,
            "coordinate_system": "B_LINEAR_LOG_NEG_C",
        })
    return rows


def _is_retryable_td_realization_error(exc):
    text = str(exc).upper()
    return ("IPF DID NOT CONVERGE" in text or
            ("20B SILENT FAILED" in text and "MAX_REL_ERR" in text))


def _validate_realized_td_state(adapter, cfg, before, baseline_diag, changed_rows, folder):
    after = adapter.snapshot()
    _td_expected_freeze(before, after, changed_rows, cfg, Path(folder) / "TD_PARAMETER_FREEZE_AUDIT.json")
    bmat = {r["matrix_no"]: r for r in before.get("matrices", [])}
    amat = {r["matrix_no"]: r for r in after.get("matrices", [])}
    if set(bmat) != set(amat):
        raise SupplyContractError("V245_TD_MATRIX_SET_CHANGED")
    protected = {9116}
    protected.update(int(no) for code, no in before.get("dseg_map", {}).items()
                     if code.startswith("EXOG_EE_") or code in ("LNV", "NV"))
    for no in protected & set(bmat):
        if bmat[no] != amat[no]:
            raise SupplyContractError("V245_TD_MUTATED_FIXED_MATRIX:%s" % no)
    after_diag = adapter.diagnostics(folder / "DIAGNOSTICS", "AFTER_FINECDF_TD")
    if adapter.snapshot() != after:
        raise SupplyContractError("V242_TD_DIAGNOSTICS_CHANGED_MODEL")
    if not changed_rows:
        if (not _td_parent_state_equivalent(
                before, after, cfg, Path(folder) / "TD_NOCHANGE_PARENT_FREEZE_AUDIT.json") or
                diagnostic_hash(after_diag) != diagnostic_hash(baseline_diag)):
            raise SupplyContractError("V242_FINECDF_NOCHANGE_DID_NOT_REPRODUCE_PARENT")
    return after, after_diag


def _realize_finecdf_td(adapter, cfg, folder, control, before, baseline_diag, target_rows):
    """Realize FineCDF proposals through the full downstream sequence.

    The survey curve is a SOFT reference in V2.4.9.0.  The inner FineCDF solver
    still supplies the direction of travel, but a fully recomputed candidate is
    adopted only when the live TD/network acceptance gate reports a material
    aggregate improvement with bounded component trade-offs.  A realized but
    repeatedly rejected family of scaled candidates is a verified parent
    plateau, not a calibration crash.  Native 20B/IPF non-convergence remains a
    numerical failure and its tolerance is never relaxed.
    """
    folder = Path(folder); folder.mkdir(parents=True, exist_ok=True)
    scales = _td_realization_scales(cfg)
    attempts = []
    last_error = None
    last_status = None
    soft_policy = cfg.get("td_soft_reference_policy", {})
    soft_enabled = soft_policy.get("enabled") is True
    seen_effective_candidates = set()
    for ordinal, scale in enumerate(scales, start=1):
        attempt_folder = folder / ("TRY_%02d_SCALE_%s" %
                                   (ordinal, str(scale).replace(".", "p")))
        attempt_folder.mkdir(parents=True, exist_ok=True)
        rows = _td_rows_at_scale(before, target_rows, scale)
        effective_signature = canonical_hash([
            (r.get("component"), r.get("candidate_b"), r.get("candidate_c"))
            for r in rows
        ])
        if effective_signature in seen_effective_candidates:
            attempts.append({
                "trial": ordinal, "scale": scale,
                "status": "DUPLICATE_EFFECTIVE_CANDIDATE_SKIPPED",
                "signature": effective_signature,
                "ipf_tolerance_relaxed": False,
                "exact_curve_match_required": False,
            })
            atomic_json(folder / "TD_REALIZATION_ATTEMPTS.json", {
                "status": "DUPLICATE_EFFECTIVE_CANDIDATE_SKIPPED",
                "coordinate_system": "B_LINEAR_LOG_NEG_C",
                "ipf_tolerance_relaxed": False,
                "exact_curve_match_required": False,
                "survey_reference_role": "SOFT_DIRECTIONAL_REFERENCE_NOT_EXACT_FIT",
                "attempts": attempts,
            })
            continue
        seen_effective_candidates.add(effective_signature)
        if hasattr(adapter, "begin_candidate_readback_context"):
            adapter.begin_candidate_readback_context(
                before["state_hash"], "TD_FINECDF", effective_signature,
                parameter_evidence={"scale": scale, "rows": rows})
        try:
            # Reassert the accepted-parent b/c before every trial. The complete
            # downstream procedure then regenerates all dependent matrices.
            restore_td_parameters(adapter, before, _all_td_restore_rows(before),
                                  attempt_folder / "RESTORE_PARENT_BC")
            if rows:
                adapter.apply_td(rows)
            with recovery_scope(control, "REALIZE_FINECDF_TD_SCALE_%s" % scale):
                gap = _assign_candidate(
                    adapter, attempt_folder / "FULL_DOWNSTREAM_RECOMPUTE",
                    "TD_FINECDF")
            if rows:
                adapter.parameter_persistence("TD_FINECDF", rows)
            with recovery_scope(control, "VERIFY_REALIZED_FINECDF_TD_SCALE_%s" % scale):
                after, after_diag = _validate_realized_td_state(
                    adapter, cfg, before, baseline_diag, rows, attempt_folder)

            decision = {"accepted": True, "reasons": [],
                        "policy": "NO_CHANGE_PARENT" if not rows else "LEGACY_INNER_AUTHORITY"}
            if rows and soft_enabled:
                if not hasattr(adapter, "block_gate"):
                    raise SupplyContractError("V2490_TD_SOFT_ACCEPTANCE_AUTHORITY_MISSING")
                decision = adapter.block_gate(
                    "TD_FINECDF_SOFT_REFERENCE", baseline_diag, after_diag, rows)
                atomic_json(attempt_folder / "TD_SOFT_REFERENCE_ACCEPTANCE.json", decision)
                if not decision.get("accepted", False):
                    last_status = "REJECTED_SOFT_REFERENCE_GUARD"
                    attempt = {
                        "trial": ordinal, "scale": scale,
                        "status": last_status, "gap": gap, "rows": rows,
                        "decision": decision, "retryable": True,
                        "ipf_tolerance_relaxed": False,
                        "exact_curve_match_required": False,
                    }
                    attempts.append(attempt)
                    atomic_json(folder / "TD_REALIZATION_ATTEMPTS.json", {
                        "status": "BACKTRACKING_SOFT_REFERENCE" if ordinal < len(scales)
                                  else "SOFT_REFERENCE_REJECTED_ALL_SCALES",
                        "coordinate_system": "B_LINEAR_LOG_NEG_C",
                        "ipf_tolerance_relaxed": False,
                        "exact_curve_match_required": False,
                        "survey_reference_role": "SOFT_DIRECTIONAL_REFERENCE_NOT_EXACT_FIT",
                        "attempts": attempts,
                    })
                    continue

            last_status = "REALIZED"
            attempt = {
                "trial": ordinal, "scale": scale, "status": "REALIZED",
                "gap": gap, "rows": rows, "decision": decision,
                "ipf_tolerance_relaxed": False,
                "exact_curve_match_required": False,
            }
            attempts.append(attempt)
            evidence = {
                "status": "REALIZED", "selected_scale": scale,
                "coordinate_system": "B_LINEAR_LOG_NEG_C",
                "ipf_tolerance_relaxed": False,
                "exact_curve_match_required": False,
                "survey_reference_role": "SOFT_DIRECTIONAL_REFERENCE_NOT_EXACT_FIT",
                "attempts": attempts,
            }
            atomic_json(folder / "TD_REALIZATION_ATTEMPTS.json", evidence)
            return rows, after, after_diag, gap, evidence
        except BaseException as exc:
            last_error = exc
            retryable = _is_retryable_td_realization_error(exc)
            last_status = "RETRYABLE_NATIVE_IPF_NONCONVERGENCE" if retryable else "FAILED_HARD"
            attempts.append({
                "trial": ordinal, "scale": scale,
                "status": last_status,
                "error": str(exc), "retryable": retryable,
                "ipf_tolerance_relaxed": False,
                "exact_curve_match_required": False,
            })
            atomic_json(folder / "TD_REALIZATION_ATTEMPTS.json", {
                "status": "BACKTRACKING" if retryable and ordinal < len(scales) else "FAILED",
                "coordinate_system": "B_LINEAR_LOG_NEG_C",
                "ipf_tolerance_relaxed": False,
                "exact_curve_match_required": False,
                "survey_reference_role": "SOFT_DIRECTIONAL_REFERENCE_NOT_EXACT_FIT",
                "attempts": attempts,
            })
            if not retryable:
                raise

    # If the smallest *realized* candidate is still not a safe material
    # improvement, the correct result is the unchanged accepted parent. This is
    # precisely the soft-reference meaning: do not force the survey curve.
    if last_status == "REJECTED_SOFT_REFERENCE_GUARD":
        rb_state, rb_diag = _rollback_td_all(
            adapter, before, baseline_diag, folder / "SOFT_REFERENCE_PLATEAU_ROLLBACK", cfg)
        evidence = {
            "status": "SOFT_REFERENCE_PLATEAU",
            "selected_scale": None,
            "coordinate_system": "B_LINEAR_LOG_NEG_C",
            "ipf_tolerance_relaxed": False,
            "exact_curve_match_required": False,
            "survey_reference_role": "SOFT_DIRECTIONAL_REFERENCE_NOT_EXACT_FIT",
            "plateau_reason": "NO_SAFE_MATERIAL_FULL_DOWNSTREAM_TD_IMPROVEMENT",
            "attempts": attempts,
        }
        atomic_json(folder / "TD_REALIZATION_ATTEMPTS.json", evidence)
        return [], rb_state, rb_diag, None, evidence

    raise SupplyContractError(
        "V2490_TD_REALIZATION_BACKTRACK_EXHAUSTED:%s" % str(last_error)) from last_error


def _td_parent_state_equivalent(before, after, cfg, audit_path=None):
    """Exact state equality except numerically tolerant TD parameter read-back."""
    excluded = {"td_values", "td_hash", "state_hash"}
    for key in set(before) | set(after):
        if key in excluded:
            continue
        if before.get(key) != after.get(key):
            return False
    try:
        _td_expected_freeze(before, after, [], cfg, audit_path)
    except SupplyContractError:
        return False
    return True


def _rollback_td_all(adapter, before, baseline_diag, folder, cfg=None):
    folder = Path(folder); folder.mkdir(parents=True, exist_ok=True)
    if hasattr(adapter, "begin_candidate_readback_context"):
        signature = canonical_hash({
            "kind": "ROLLBACK_ALL_TD",
            "parent_state_hash": before.get("state_hash"),
            "rows": _all_td_restore_rows(before),
        })
        baseline_rows = list(((baseline_diag or {}).get("d12", {}) or {}).get("rows", []) or [])
        adapter.begin_candidate_readback_context(
            before["state_hash"], "TD_FINECDF", signature,
            parameter_evidence={"rollback_all_td": True},
            baseline_profile_rows=baseline_rows)
    restore_td_parameters(adapter, before, _all_td_restore_rows(before), folder)
    gap = _assign_candidate(adapter, folder / "FULL_RECOMPUTE", "TD_FINECDF")
    state = adapter.snapshot()
    diag = adapter.diagnostics(folder / "DIAGNOSTICS", "ROLLBACK")
    state_equal = _td_parent_state_equivalent(
        before, state, cfg or {}, folder / "TD_PARENT_FREEZE_AUDIT.json")
    state_after_diag = adapter.snapshot()
    state_after_diag_equal = _td_parent_state_equivalent(
        before, state_after_diag, cfg or {}, folder / "TD_PARENT_AFTER_DIAGNOSTICS_FREEZE_AUDIT.json")
    diag_equal = diagnostic_hash(diag) == diagnostic_hash(baseline_diag)
    ok = state_equal and state_after_diag_equal and diag_equal
    atomic_json(folder / "ROLLBACK_ALL_TD_RESULT.json", {
        "passes": ok, "gap": gap, "snapshot_equal": state_equal and state_after_diag_equal,
        "diagnostic_equal": diag_equal,
        "direct_od_matrix_writes": False, "load_version_called": False,
    })
    if not ok:
        raise SupplyContractError("V242_TD_ROLLBACK_NOT_IDENTICAL")
    return state, diag


def _generation_update_once(adapter, cfg, folder, control, state, diag, anchors, reference, policy,
                            outer_cycle=None):
    gen_cfg = _generation_counts_cfg(cfg, outer_cycle=outer_cycle)
    with adapter_config_scope(adapter, gen_cfg):
        return _generation_update_once_impl(adapter, gen_cfg, folder, control, state, diag, anchors, reference, policy)


def _generation_update_once_impl(adapter, cfg, folder, control, state, diag, anchors, reference, policy):
    folder = Path(folder); folder.mkdir(parents=True, exist_ok=True)
    gen_cfg = _generation_counts_cfg(cfg)
    baseline_value = ledger(diag, state, anchors, policy, reference, gen_cfg)
    rec = {"status": "DESIGNING", "attempts": [], "objective_before": baseline_value}
    if gen_cfg.get("performance", {}).get("active_generation_step_stage"):
        rec["generation_step_stage"] = copy.deepcopy(
            gen_cfg["performance"]["active_generation_step_stage"])
    context = adapter.generation_design(diag, folder / "DESIGN")
    if context.get("result") is not None and not context["result"].converged:
        raise SupplyContractError("V245_GENERATION_SOLVER_NOT_CONVERGED_NOT_A_PLATEAU")
    if context.get("projection") is not None:
        fams = context["projection"].family_summaries
        if not fams or not all(row.get("converged") for row in fams):
            raise SupplyContractError("V245_GENERATION_PROJECTION_NOT_CONVERGED_NOT_A_PLATEAU")
    candidates = [{"scale": float(s)} for s in gen_cfg.get("backtracking_scales", [1.0, 0.5, 0.25])]
    planned_count = len(candidates)
    limit = int(gen_cfg.get("trial_calibration", {}).get("max_trials_per_block", {}).get("GENERATION", len(candidates)))
    if limit <= 0 or planned_count == 0:
        raise SupplyContractError("V245_EMPTY_GENERATION_SEARCH")
    candidates = candidates[:limit]
    rec["planned_trials"] = planned_count
    rec["search_complete"] = False
    rec["stationarity_confirmed"] = False
    planned = []
    for cand in candidates:
        preview, rows = _planned_generation_rows(adapter, context, cand["scale"])
        atomic_json(folder / ("GENERATION_PREVIEW_%s.json" % str(cand["scale"]).replace(".", "_")), preview)
        planned.append(rows)
    best = None
    early_complete = False
    for ordinal, (candidate, rows0) in enumerate(zip(candidates, planned), start=1):
        control.checkpoint("COUPLED_DEMAND_GENERATION_TRIAL", force=True, trial=ordinal)
        if adapter.snapshot() != state:
            raise SupplyContractError("V242_GENERATION_TRIAL_PARENT_CHANGED")
        rows = list(rows0 or [])
        if not rows:
            rec["attempts"].append({"trial": ordinal, "candidate": candidate, "status": "NO_PARAMETER_CANDIDATE"})
            continue
        ev, rolled_diag, error = _evaluate_candidate(
            adapter, gen_cfg, policy, "GENERATION", candidate, rows, context,
            state, diag, baseline_value, anchors, reference,
            folder / ("TRY_%02d" % ordinal), control,
        )
        if diagnostic_hash(rolled_diag) != diagnostic_hash(diag):
            raise SupplyContractError("V242_GENERATION_ROLLBACK_DIAGNOSTIC_CHANGED")
        attempt = {"trial": ordinal, "candidate": candidate,
                   "status": "FAILED" if ev is None else ("ELIGIBLE" if ev["eligible"] else "REJECTED")}
        if error:
            attempt["error"] = error
        if ev is not None:
            attempt["decision"] = ev["decision"]
            attempt["counts_objective"] = ev["after_value"]
            if ev["eligible"] and (best is None or ev["after_value"]["total"] < best["after_value"]["total"]):
                best = ev
        rec["attempts"].append(attempt)
        atomic_json(folder / "GENERATION_BLOCK_RESULT.json", rec)
        if ev is None:
            raise SupplyContractError("V245_GENERATION_TRIAL_ERROR_NOT_A_PLATEAU:" + str(error))
        if _first_sufficient_candidate(gen_cfg, "GENERATION", baseline_value, ev):
            early_complete = True
            rec["early_stop_policy"] = "FIRST_SUFFICIENT_GATE_ACCEPTED"
            rec["early_stop_trial"] = ordinal
            rec["early_stop_relative_improvement"] = ev["first_sufficient_relative_improvement"]
            break
    rec["search_complete"] = early_complete or len(rec["attempts"]) == planned_count
    if best is None:
        rec["stationarity_confirmed"] = rec["search_complete"]
        rec["status"] = "CONFIGURED_GENERATION_SEARCH_EXHAUSTED" if rec["search_complete"] else "GENERATION_SEARCH_TRUNCATED"
        if not rec["search_complete"]:
            atomic_json(folder / "GENERATION_BLOCK_RESULT.json", rec)
            raise SupplyContractError("V245_GENERATION_SEARCH_TRUNCATED_NOT_A_PLATEAU")
        atomic_json(folder / "GENERATION_BLOCK_RESULT.json", rec)
        return False, state, diag, baseline_value, rec
    new_state, new_diag, new_value, actual_rows, gap = _adopt_candidate(
        adapter, gen_cfg, policy, "GENERATION", best, context, state, diag,
        baseline_value, anchors, reference, folder / "ADOPTED", control,
    )
    if hasattr(adapter, "accepted_state_changed"):
        cache_transition = adapter.accepted_state_changed(
            new_state, new_diag, reason="V242_ACCEPTED_GENERATION_STATE_CHANGED",
            phase="DEMAND")
    else:
        cache_transition = None
        if hasattr(adapter, "invalidate_cache"):
            adapter.invalidate_cache("V242_ACCEPTED_GENERATION_STATE_CHANGED", clear_proof=True)
    rec.update(status="ACCEPTED", gap=gap, candidate=best["candidate"],
               rows=len(actual_rows), objective_after=new_value,
               path_epoch_transition=cache_transition)
    atomic_json(folder / "GENERATION_BLOCK_RESULT.json", rec)
    return True, new_state, new_diag, new_value, rec


def _finecdf_td_once(adapter, cfg, folder, control, state, diag, package_root,
                     outer_cycle=None):
    td_cfg = _td_acceptance_cfg_for_cycle(cfg, outer_cycle=outer_cycle)
    with adapter_config_scope(adapter, td_cfg):
        return _finecdf_td_once_impl(
            adapter, td_cfg, folder, control, state, diag, package_root)


def _finecdf_td_once_impl(adapter, cfg, folder, control, state, diag, package_root):
    folder = Path(folder); folder.mkdir(parents=True, exist_ok=True)
    before, baseline_diag = state, diag
    try:
        budget = _finecdf_budget_for_cycle(cfg, int(cfg.get("runtime_acceptance_outer_cycle", 1) or 1))
        if budget:
            inner = run_finecdf_inner(adapter, cfg, folder / "FINECDF_INNER", control,
                                      package_root, phase_budget=budget)
        else:
            inner = run_finecdf_inner(adapter, cfg, folder / "FINECDF_INNER", control,
                                      package_root)
        target_rows = [{"component": r["component"],
                        "candidate_b": r["after_b"], "candidate_c": r["after_c"]}
                       for r in inner.get("changed_rows", [])]
        realized_rows, after, after_diag, gap, realization = _realize_finecdf_td(
            adapter, cfg, folder / "REALIZATION", control, before, baseline_diag,
            target_rows)
        inner = copy.deepcopy(inner)
        inner["target_changed_rows"] = target_rows
        inner["changed_rows"] = realized_rows
        inner["realization"] = realization
        inner["td_realization_complete"] = True
        cache_transition = None
        if realized_rows:
            if hasattr(adapter, "accepted_state_changed"):
                cache_transition = adapter.accepted_state_changed(
                    after, after_diag, reason="V2489_ACCEPTED_REALIZED_FINECDF_TD_STATE_CHANGED",
                    phase="DEMAND")
            elif hasattr(adapter, "invalidate_cache"):
                adapter.invalidate_cache("V2489_ACCEPTED_REALIZED_FINECDF_TD_STATE_CHANGED",
                                         clear_proof=True)
        rec = {"status": "ACCEPTED_FINECDF_TD" if realized_rows else "FINECDF_TD_PLATEAU",
               "gap": gap, "inner": inner, "changed_rows": realized_rows,
               "target_changed_rows": target_rows,
               "td_realization_complete": True,
               "realization": realization,
               "progressive_budget": budget,
               "path_epoch_transition": cache_transition,
               "state_hash": after["state_hash"],
               "diagnostic_hash": diagnostic_hash(after_diag)}
        atomic_json(folder / "TD_FINECDF_BLOCK_RESULT.json", rec)
        return bool(realized_rows), after, after_diag, rec
    except BaseException as exc:
        try:
            with recovery_scope(control, "RESTORE_ALL_TD_AFTER_FAILURE"):
                rb_state, rb_diag = _rollback_td_all(
                    adapter, before, baseline_diag,
                    folder / "ROLLBACK_AFTER_TD_FAILURE", cfg)
        except Exception as rb_exc:
            atomic_json(folder / "TD_FINECDF_BLOCK_RESULT.json", {
                "status": "ROLLBACK_FAILED_MANUAL_REOPEN_REQUIRED",
                "td_realization_complete": False,
                "next_generation_permitted": False,
                "error": str(exc), "traceback": traceback.format_exc(),
                "rollback_error": str(rb_exc),
            })
            raise SupplyContractError("V242_FINECDF_ROLLBACK_FAILED_MANUAL_REOPEN") from rb_exc
        atomic_json(folder / "TD_FINECDF_BLOCK_RESULT.json", {
            "status": "FAILED_BUT_ROLLBACK_VERIFIED",
            "td_realization_complete": False,
            "next_generation_permitted": False,
            "error": str(exc), "traceback": traceback.format_exc(),
        })
        raise


def _sha256_file(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _publish_best_so_far_checkpoint(adapter, root, source_checkpoint, snapshot,
                                    objective, accepted_count):
    """Copy an immutable accepted checkpoint to a dedicated best-state authority.

    The exploratory current state may move through a locally worse region.  The
    dedicated copy prevents the two-slot accepted checkpoint rotation from
    deleting the best fixed-reference state found so far.
    """
    root = Path(root)
    store = root / "CHECKPOINTS"
    store.mkdir(parents=True, exist_ok=True)
    source = Path(source_checkpoint.get("path", "")).resolve()
    if not source.is_file():
        raise SupplyContractError("V2496_BEST_SOURCE_CHECKPOINT_MISSING")
    source_sha = _sha256_file(source)
    if source_checkpoint.get("sha256") and source_sha != source_checkpoint.get("sha256"):
        raise SupplyContractError("V2496_BEST_SOURCE_CHECKPOINT_HASH_MISMATCH")
    state_hash = str(snapshot.get("state_hash", ""))
    target = store / ("BEST_SO_FAR_%04d_%s.ver" %
                      (int(accepted_count), state_hash[:12] or source_sha[:12]))
    temp = target.with_name(target.name + ".tmp")
    temp.unlink(missing_ok=True)
    shutil.copy2(source, temp)
    copied_sha = _sha256_file(temp)
    if copied_sha != source_sha or temp.stat().st_size != source.stat().st_size:
        temp.unlink(missing_ok=True)
        raise SupplyContractError("V2496_BEST_CHECKPOINT_COPY_READBACK_MISMATCH")
    os.replace(str(temp), str(target))
    record = {
        "schema": "R1_15A2_V2496_BEST_SO_FAR_CHECKPOINT_V1",
        "role": "BEST_SO_FAR_FIXED_REFERENCE_SHARED_OBJECTIVE",
        "accepted_count": int(accepted_count),
        "state_hash": state_hash,
        "objective": copy.deepcopy(objective),
        "checkpoint": {
            "path": str(target), "sha256": copied_sha,
            "size": int(target.stat().st_size),
        },
        "source_accepted_checkpoint": copy.deepcopy(source_checkpoint),
    }
    restart_cfg = dict(getattr(adapter, "cfg", {}).get("restart_authority", {}) or {})
    if restart_cfg.get("checkpoint_semantic_sidecar") is True:
        from r1_15a2_restart_v2494 import build_authority, sidecar_path
        authority = build_authority(
            snapshot, version_path=target, raw_ver_sha256=copied_sha,
            origin="BEST_SO_FAR_FIXED_REFERENCE_SHARED_OBJECTIVE")
        sidecar = sidecar_path(target)
        atomic_json(sidecar, authority)
        record["semantic_restart_authority"] = {
            "schema": authority["schema"], "path": str(sidecar),
            "semantic_state_hash": authority["semantic_state_hash"],
            "semantic_hashes": authority["semantic_hashes"],
            "raw_ver_sha_role": authority["raw_ver_sha_role"],
            "raw_ver_sha_used_for_restart_acceptance": False,
        }
    pointer = root / "BEST_SO_FAR_CHECKPOINT.json"
    previous = json.loads(pointer.read_text(encoding="utf-8")) if pointer.is_file() else None
    atomic_json(pointer, record)
    if json.loads(pointer.read_text(encoding="utf-8")) != record:
        raise SupplyContractError("V2496_BEST_POINTER_READBACK_MISMATCH")
    if previous:
        old = Path(previous.get("checkpoint", {}).get("path", ""))
        if old != target and old.parent.resolve() == store.resolve() and old.name.startswith("BEST_SO_FAR_"):
            try:
                old.unlink(missing_ok=True)
                old.with_name(old.name + ".semantic.json").unlink(missing_ok=True)
            except OSError:
                pass
    return record


def run_overnight_calibration_coupled(adapter, cfg, folder, control, package_root):
    """A cycle is complete only after both actual TG and TD substeps returned.

    Stationarity is a bounded-search conclusion, not proof of calibration quality
    or of a global optimum. Errors, truncated searches and budgets never count.
    """
    folder = Path(folder); folder.mkdir(parents=True, exist_ok=True)
    policy = SupplyPolicy.from_config(cfg)
    continuation = _runtime_demand_continuation(cfg)
    result = {
        "schema": ("R1_15A2_V24914_CONTINUABLE_COUPLED_DEMAND_STATE_MACHINE"
                   if continuation.get("enabled") is True else
                   ("R1_15A2_V246_ADAPTIVE_COUPLED_DEMAND_STATE_MACHINE"
                    if cfg.get("performance", {}).get("release") == "V2.4.6"
                    else "R1_15A2_V245_COUPLED_DEMAND_STATE_MACHINE")),
        "status": "STARTED", "production_apply": False, "trial_writes": True,
        "load_version_called": False, "direct_od_matrix_writes": False,
        "finecdf_reference_sha256": str(cfg.get("coupled_demand", {}).get(
            "finecdf_td", {}).get("reference_sha256", REF_SHA256)),
        "architecture": "COUPLED_DEMAND_OUTER_LOOP__GENERATION_COUNTS_THEN_FINECDF_TD__THEN_SUPPLY",
        "demand_cycles": [],
        "completed_demand_cycles": int(continuation.get("inherited_completed_demand_cycles", 0)),
        "demand_converged": False, "supply_started": False,
        "accepted_count": int(continuation.get("accepted_count", 0)),
        "stationary_cycle_streak": int(continuation.get("inherited_stationary_cycle_streak", 0)),
        "final_state_verified": False, "calibration_complete": False,
        "demand_continuation": copy.deepcopy(continuation),
        "lineage_outer_cycle_start": int(continuation.get("next_outer_cycle", 1)),
        "inherited_outer_cycles": int(continuation.get("inherited_outer_cycles", 0)),
    }
    atomic_json(folder / "EFFECTIVE_CONFIG.json", cfg)
    state = diag = active_parent = cycle = None
    best_score = float("inf")
    best_record = None
    final_owner = "DEMAND"
    def persist():
        atomic_json(folder / "RUN_STATUS.json", result)
    def remember(snapshot, diagnostics, save=False):
        nonlocal active_parent, best_score, best_record
        cp = (_save_rotating_checkpoint(adapter, folder, result["accepted_count"])
              if save else active_parent["checkpoint"])
        active_parent = {"snapshot": snapshot, "diag": diagnostics, "checkpoint": cp}
        result["current_exploratory_checkpoint"] = copy.deepcopy(cp)
        best_cfg = cfg.get("early_exploration_acceptance", {}).get("best_so_far", {}) or {}
        if best_cfg.get("enabled") is True:
            objective = ledger(diagnostics, snapshot, anchors, policy, gen_reference, cfg)
            score = float(objective.get("total", float("inf")))
            minimum = float(best_cfg.get("minimum_improvement", 1.0e-8))
            if best_record is None or score < best_score - minimum:
                best_record = _publish_best_so_far_checkpoint(
                    adapter, folder, cp, snapshot, objective, result["accepted_count"])
                best_score = score
            result["best_so_far_checkpoint"] = copy.deepcopy(best_record)
            result["best_so_far_objective"] = best_score
    try:
        control.checkpoint("V245_PREFLIGHT", force=True)
        result["preflight"] = adapter.preflight(folder / "PREFLIGHT")
        pre = adapter.snapshot()
        adapter.assign(folder / "BASELINE_FULL_RECOMPUTE", supply_only=False)
        state = adapter.snapshot()
        for name in ("fixed_link_hash", "dseg_hash", "operations_hash", "addval_hash", "generation_hash", "td_hash"):
            if pre[name] != state[name]:
                raise SupplyContractError("V245_BASELINE_RECOMPUTE_CHANGED_PARAMETER_CONTEXT:" + name)
        diag = adapter.diagnostics(folder / "BASELINE_DIAGNOSTICS", "BASELINE")
        if adapter.snapshot() != state:
            raise SupplyContractError("V245_BASELINE_DIAGNOSTICS_CHANGED_MODEL")
        anchors = dict(state["addval1"])
        if continuation.get("generation_reference") is not None:
            gen_reference = copy.deepcopy(continuation["generation_reference"])
            # ledger() below is the authoritative identity check against the
            # live 12D/11D targets and observations. Reusing this sealed
            # reference preserves the fixed-reference objective across runs.
            result["generation_reference_source"] = "CONTINUATION_SEALED_REFERENCE"
            result["generation_reference_sha256"] = continuation.get("generation_reference_sha256")
        else:
            gen_reference = build_reference(diag, _generation_counts_cfg(cfg))
            result["generation_reference_source"] = "LIVE_RUN_START"
        atomic_json(folder / "GENERATION_COUNTS_REFERENCE.json", gen_reference)
        remember(state, diag, save=True)
        dc = cfg.get("coupled_demand", {})
        max_outer = int(dc.get("max_outer_cycles", 12))
        minimum = int(dc.get("min_stationary_cycles", 2))
        start_outer = int(continuation.get("next_outer_cycle", 1))
        if continuation.get("enabled") is True:
            continuation_max = int(continuation.get("max_lineage_outer_cycle", max_outer))
            if continuation_max != max_outer:
                raise SupplyContractError("V24914_CONTINUATION_MAX_OUTER_CONFIG_MISMATCH")
        if minimum < 2 or max_outer < minimum or start_outer < 1 or start_outer > max_outer:
            raise SupplyContractError("V245_INVALID_STATIONARY_CYCLE_BUDGET")
        result["remaining_lineage_outer_cycles"] = max_outer - start_outer + 1
        persist()
        result["td_realization_pending"] = False
        for outer in range(start_outer, max_outer + 1):
            if result.get("td_realization_pending"):
                raise SupplyContractError("V2489_NEXT_GENERATION_BLOCKED_TD_REALIZATION_PENDING")
            control.checkpoint("COUPLED_DEMAND_CYCLE_START", force=True,
                               demand_cycle=outer, accepted_count=result["accepted_count"])
            resume_td_cycle = (
                continuation.get("enabled") is True and
                str(continuation.get("resume_substep", "GENERATION")).upper() == "TD_FINECDF_V17" and
                int(continuation.get("resume_outer_cycle", -1)) == outer
            )
            cycle = {"cycle": outer,
                     "status": "TD_RUNNING" if resume_td_cycle else "GENERATION_RUNNING",
                     "completed": False,
                     "generation_changed": (bool(continuation.get("resume_generation_changed"))
                                            if resume_td_cycle else None),
                     "td_changed": None,
                     "generation_completed": bool(resume_td_cycle),
                     "td_completed": False,
                     "state_hash_start": state["state_hash"]}
            result["demand_cycles"].append(cycle); persist()
            if resume_td_cycle:
                changed = bool(continuation.get("resume_generation_changed"))
                rec = copy.deepcopy(continuation.get("resume_generation_record") or {})
                rec["resumed_from_prior_run"] = True
                rec["generation_replay_skipped"] = True
                cycle.update(generation=rec, generation_completed=True, status="TD_RUNNING",
                             td_realization_required=True, td_realization_complete=False,
                             resume_boundary="POST_ACCEPTED_GENERATION_PRE_TD")
                result["td_realization_pending"] = True
                result["partial_cycle_resume"] = {
                    "cycle": outer,
                    "substep": "TD_FINECDF_V17",
                    "generation_replayed": False,
                    "accepted_count_at_resume": result["accepted_count"],
                    "source_semantic_state_hash": continuation.get("semantic_state_hash"),
                }
                persist()
            else:
                gen_args = (adapter, cfg, folder / ("DEMAND_CYCLE_%02d_GENERATION" % outer),
                            control, state, diag, anchors, gen_reference, policy)
                if "outer_cycle" in inspect.signature(_generation_update_once).parameters:
                    changed, state, diag, value, rec = _generation_update_once(
                        *gen_args, outer_cycle=outer)
                else:
                    # Backward-compatible callable boundary for frozen fixtures and
                    # third-party adapters exposing the pre-v2.4.6 signature.
                    changed, state, diag, value, rec = _generation_update_once(*gen_args)
                cycle.update(generation_changed=changed, generation=rec,
                             generation_completed=True, status="TD_RUNNING",
                             td_realization_required=True,
                             td_realization_complete=False)
                result["td_realization_pending"] = True
                if changed:
                    result["accepted_count"] += 1
                    remember(state, diag, save=True)
                persist()
            td_args = (adapter, cfg, folder / ("DEMAND_CYCLE_%02d_TD_FINECDF" % outer),
                       control, state, diag, package_root)
            if "outer_cycle" in inspect.signature(_finecdf_td_once).parameters:
                td_changed, state, diag, td_rec = _finecdf_td_once(
                    *td_args, outer_cycle=outer)
            else:
                # Compatibility for frozen v2.4.2/v2.4.5 fixtures and third-party
                # adapters that still expose the pre-v2.4.6 callable shape.
                td_changed, state, diag, td_rec = _finecdf_td_once(*td_args)
            # The production V2489 TD function reports this explicitly. Legacy
            # frozen fixtures/third-party adapters predate the field and are
            # treated as implicitly realized only when they returned normally.
            if td_rec.get("td_realization_complete") is False:
                raise SupplyContractError("V2489_TD_RETURNED_WITHOUT_REALIZATION")
            result["td_realization_pending"] = False
            cycle.update(td_changed=td_changed, td=td_rec, td_completed=True,
                         td_realization_complete=True)
            if td_changed:
                result["accepted_count"] += 1
                remember(state, diag, save=True)
            else:
                remember(state, diag)
            inner = td_rec.get("inner", {})
            stop_reason = str(inner.get("stop_reason", ""))
            progress_continue = inner.get("progress_continue") is True
            search_complete = rec.get("search_complete") is True and inner.get("search_complete") is True
            stationary = (not changed and not td_changed and
                          rec.get("stationarity_confirmed") is True and stationary_td_result(inner))
            path_epoch_gate = None
            if stationary and hasattr(adapter, "path_epoch_plateau_gate"):
                path_epoch_gate = adapter.path_epoch_plateau_gate(
                    diag, folder / "PATH_EPOCHS" / ("DEMAND_PLATEAU_%02d" % outer),
                    state, phase="DEMAND")
                if path_epoch_gate.get("stationarity_confirmed") is not True:
                    stationary = False
            if progress_continue:
                # A deliberately bounded early FineCDF stage retained its best live
                # state.  This is useful progress, never convergence, and Supply
                # remains locked until a later full search reaches stationarity.
                cycle.update(status="PROGRESS_CONTINUE_DEMAND", completed=False,
                             search_complete=False, progress_continue=True,
                             progress_continue_reason=stop_reason,
                             progress_continue_policy="CONFIGURED_PROGRESSIVE_STAGE",
                             state_hash_end=state["state_hash"],
                             diagnostic_hash_end=diagnostic_hash(diag),
                             joint_stationary=False)
                result["stationary_cycle_streak"] = 0
                atomic_json(folder / ("DEMAND_CYCLE_%02d_RESULT.json" % outer), cycle)
                persist()
                continue
            if (continuation.get("enabled") is True and
                    (not search_complete) and _bounded_inner_budget_stop(inner)):
                # V24914: a bounded inner FineCDF budget is not a terminal error of
                # the coupled outer search.  The realized/accepted parent is already
                # durable at this boundary.  Continue with the next outer cycle,
                # keep stationarity at zero, and keep Supply locked.  This applies
                # both when a change was accepted and when no change was accepted;
                # the latter is explicitly *not* stationarity because the inner
                # search did not complete.  Global user/time stops and technical
                # errors use different stop reasons and remain fail-closed.
                cycle.update(
                    status=_bounded_inner_budget_cycle_status(changed, td_changed),
                    completed=False, search_complete=False, progress_continue=True,
                    progress_continue_reason=stop_reason,
                    progress_continue_policy=(
                        "V24914_BOUNDED_INNER_BUDGET_CONTINUES_OUTER_LOOP_SUPPLY_LOCKED"),
                    accepted_state_change=bool(changed or td_changed),
                    bounded_inner_budget_exhausted=True,
                    state_hash_end=state["state_hash"],
                    diagnostic_hash_end=diagnostic_hash(diag),
                    joint_stationary=False)
                result["stationary_cycle_streak"] = 0
                result.setdefault("bounded_budget_continuations", []).append({
                    "cycle": outer, "stop_reason": stop_reason,
                    "generation_changed": bool(changed), "td_changed": bool(td_changed),
                    "state_hash": state["state_hash"],
                })
                atomic_json(folder / ("DEMAND_CYCLE_%02d_RESULT.json" % outer), cycle)
                persist()
                continue
            if path_epoch_gate is not None:
                cycle["path_epoch_plateau_gate"] = path_epoch_gate
                if path_epoch_gate.get("stationarity_confirmed") is not True:
                    cycle.update(status="PATH_EPOCH_REFRESHED_CONTINUE_DEMAND",
                                 completed=search_complete,
                                 search_complete=search_complete,
                                 state_hash_end=state["state_hash"],
                                 diagnostic_hash_end=diagnostic_hash(diag),
                                 joint_stationary=False)
                    if search_complete:
                        result["completed_demand_cycles"] += 1
                    result["stationary_cycle_streak"] = 0
                    atomic_json(folder / ("DEMAND_CYCLE_%02d_RESULT.json" % outer), cycle)
                    persist()
                    continue
            cycle.update(status="COMPLETED" if search_complete else "SEARCH_INCOMPLETE",
                         completed=search_complete, search_complete=search_complete,
                         state_hash_end=state["state_hash"], diagnostic_hash_end=diagnostic_hash(diag),
                         joint_stationary=stationary)
            if search_complete:
                result["completed_demand_cycles"] += 1
            result["stationary_cycle_streak"] = result["stationary_cycle_streak"] + 1 if stationary else 0
            atomic_json(folder / ("DEMAND_CYCLE_%02d_RESULT.json" % outer), cycle); persist()
            if not search_complete:
                result["status"] = "DEMAND_SEARCH_INCOMPLETE_SUPPLY_LOCKED:" + stop_reason
                return result
            if result["stationary_cycle_streak"] >= minimum:
                result["demand_converged"] = True
                result["demand_converged_cycle"] = outer
                atomic_json(folder / "DEMAND_CONVERGED.json", {
                    "cycle": outer, "state_hash": state["state_hash"],
                    "diagnostic_hash": diagnostic_hash(diag),
                    "stationary_cycle_streak": result["stationary_cycle_streak"],
                    "criterion": "CONSECUTIVE_COMPLETE_SUCCESSFUL_CONFIGURED_TG_TD_SEARCHES_WITH_NO_CHANGE",
                    "global_optimum_proven": False, "calibration_quality_proven": False,
                })
                break
        if not result["demand_converged"]:
            result["status"] = "DEMAND_MAX_OUTER_CYCLES_REACHED_SUPPLY_LOCKED"
            result["next_outer_cycle"] = max_outer + 1
            result["continuation_required"] = True
            return result
        # Supply is unlocked only by the explicit completed-search gate above.
        control.checkpoint("SUPPLY_ROUTE_CHOICE_START", force=True)
        result["supply_started"] = True
        final_owner = "SUPPLY"; persist()
        supply_cfg = copy.deepcopy(cfg)
        supply_cfg["block_schedule"] = ["SUPPLY_ADDVAL1"]
        supply_cfg.setdefault("trial_calibration", {})["max_cycles"] = int(dc.get("supply_max_cycles", 100))
        supply_cfg["calibration_phases"] = []
        demand_state = state
        supply = run_overnight_calibration(adapter, supply_cfg, folder / "SUPPLY_ROUTE_CHOICE", control)
        result["supply_result"] = supply
        result["accepted_count"] += int(supply.get("accepted_count", 0) or 0)
        supply_status = str(supply.get("status", "UNKNOWN"))
        if supply_status.startswith("FAILED") or supply.get("final_state_verified") is not True:
            result["status"] = "FAILED_SUPPLY:" + supply_status
            return result
        state = adapter.snapshot()
        if state["state_hash"] != supply.get("final_state_hash"):
            raise SupplyContractError("V245_SUPPLY_FINAL_STATE_NOT_IDENTICAL")
        for name in ("matrix_hash", "generation_hash", "td_hash"):
            if state.get(name) != demand_state.get(name):
                raise SupplyContractError("V245_SUPPLY_MUTATED_CONVERGED_DEMAND:" + name)
        with recovery_scope(control, "VERIFY_SUPPLY_HANDOFF"):
            diag = adapter.diagnostics(folder / "SUPPLY_FINAL_DIAGNOSTICS", "FINAL")
        if diagnostic_hash(diag) != supply.get("final_diagnostic_hash") or adapter.snapshot() != state:
            raise SupplyContractError("V245_SUPPLY_FINAL_DIAGNOSTICS_NOT_IDENTICAL")
        active_parent = {"snapshot": state, "diag": diag,
                         "checkpoint": supply.get("latest_accepted_checkpoint")}
        result["calibration_complete"] = (supply_status == "CONVERGED_NO_ACCEPTED_IMPROVEMENT"
                                           and supply.get("stationarity_confirmed") is True)
        result["status"] = ("COMPLETED_CONFIGURED_DEMAND_AND_SUPPLY_SEARCH" if result["calibration_complete"]
                            else "PARTIAL_VERIFIED_SUPPLY:" + supply_status)
        return result
    except (UserStopRequested, TimeBudgetReached) as exc:
        result["status"] = "STOPPED_AT_LAST_VERIFIED_STATE:" + str(exc)
        if cycle is not None and not cycle["completed"]:
            cycle.update(status="INTERRUPTED", error=str(exc))
        return result
    except BaseException as exc:
        result.update(status="FAILED", error=str(exc), traceback=traceback.format_exc(), calibration_complete=False)
        if cycle is not None and not cycle["completed"]:
            cycle.update(status="FAILED", error=str(exc))
        return result
    finally:
        result["elapsed_seconds"] = round(control.elapsed(), 3)
        result["final_state_owner"] = final_owner
        if active_parent is not None:
            result["latest_accepted_checkpoint"] = active_parent["checkpoint"]
            prior_status = str(result.get("status", "UNKNOWN"))
            retry_audit = []
            try:
                expected = active_parent["snapshot"]
                live = _final_snapshot_with_retry(
                    adapter, cfg, "COUPLED_FINAL_STATE_SNAPSHOT", retry_audit)
                if retry_audit:
                    result["final_verification_com_retry_events"] = retry_audit
                live_matches = live == expected
                result["live_matches_last_accepted"] = live_matches
                if not live_matches:
                    result.update(
                        primary_status_before_final_verification=prior_status,
                        status="FAILED_MANUAL_REOPEN_LATEST_ACCEPTED_REQUIRED",
                        final_state_verified=False,
                        manual_reopen_required=True,
                        safe_restart_from_latest_accepted_checkpoint=True,
                    )
                elif result["status"].startswith("FAILED"):
                    result.update(
                        final_state_verified=False,
                        manual_reopen_required=False,
                        safe_restart_from_latest_accepted_checkpoint=True,
                        restart_policy="START_NEW_RUN_FROM_LATEST_ACCEPTED_CHECKPOINT",
                    )
                else:
                    with recovery_scope(control, "FINAL_READ_ONLY_VERIFICATION"):
                        final_diag = adapter.diagnostics(folder / "FINAL_VERIFICATION", "FINAL")
                    post = _final_snapshot_with_retry(
                        adapter, cfg, "COUPLED_POST_DIAGNOSTIC_STATE_SNAPSHOT", retry_audit)
                    if retry_audit:
                        result["final_verification_com_retry_events"] = retry_audit
                    if post != expected or diagnostic_hash(final_diag) != diagnostic_hash(active_parent["diag"]):
                        raise SupplyContractError("V245_FINAL_VERIFICATION_MISMATCH")
                    result.update(final_state_verified=True, final_state_hash=expected["state_hash"],
                                  final_diagnostic_hash=diagnostic_hash(final_diag),
                                  manual_reopen_required=False)
            except BaseException as exc:
                if retry_audit:
                    result["final_verification_com_retry_events"] = retry_audit
                if com.is_retryable_com_error(exc) and active_parent.get("checkpoint"):
                    _mark_transient_final_verification_failure(
                        result, exc, active_parent, prior_status)
                else:
                    result.update(
                        primary_status_before_final_verification=prior_status,
                        status="FAILED_FINAL_VERIFICATION_MANUAL_REOPEN_REQUIRED",
                        final_state_verified=False,
                        final_verification_error=str(exc),
                        final_verification_error_type=type(exc).__name__,
                        manual_reopen_required=True,
                        safe_restart_from_latest_accepted_checkpoint=False,
                    )
        if result["status"].startswith("FAILED"):
            result.update(final_state_verified=False, calibration_complete=False)
            result.pop("final_state_hash", None); result.pop("final_diagnostic_hash", None)
        if cycle is not None:
            atomic_json(folder / ("DEMAND_CYCLE_%02d_RESULT.json" % cycle["cycle"]), cycle)
        persist()


__all__ = ["run_overnight_calibration_coupled", "_generation_counts_cfg",
           "_td_acceptance_cfg_for_cycle", "_td_expected_freeze",
           "_publish_best_so_far_checkpoint", "_runtime_demand_continuation",
           "_bounded_inner_budget_stop", "_bounded_inner_budget_cycle_status",
           "V24914_BOUNDED_INNER_BUDGET_STOP_REASONS"]

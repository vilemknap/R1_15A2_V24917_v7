"""LONG Generation proposals from the same frozen two-mode path store as W/S.

The cache is a proposal basis, not a claim about a fresh saved-path export or an
analytic TG derivative. Native recomputation, live gates and rollback own truth.
"""
from __future__ import annotations

import copy
import math

import numpy as np

import r1_15a2_core as core
import r1_15a2_long_incidence_read_v24917 as reads
import r1_15a2_long_profile_incidence_v24917 as longinc
import r1_15a2_long_support_distance_v24917 as support
import r1_15a2_long_zonal_fit_v24917 as lf
import r1_15a2_zonal_count_fit_v24917 as zf
import r1_15a2_long_school_generation_v24917 as ls
import r1_15a2_mobility_zone_v24917 as mz
import r1_15a2_multiblock as mb
import r1_15a2_runtime_v1 as rt
from r1_15a2_supply import canonical_hash
from r1_15a2_long_distance_guard_v24917 import MIN_KM
from r1_15a2_skim_v24916p2c import matrix_values_hash, ordered_zone_hash

STATUS = "FROZEN_LONG_OD_PROFILE_PROPOSAL"
PARENT_KEYS = ("generation_values", "td_values", "addval1", "fixed_link_hash", "dseg_hash", "operations_hash")


def _parameter_hash(snapshot):
    if not all(key in snapshot for key in PARENT_KEYS):
        return None
    return canonical_hash({key: snapshot[key] for key in PARENT_KEYS})


def capture(adapter):
    """Reweight cached CL path/profile shares by current final vehicle OD.

    Does not export paths, restore an old cache or mutate any model data. A
    missing positive OD/share requests one ordinary shared-cache refresh.
    """
    binding = reads._require_binding(adapter)
    parent = adapter.generation_guard_snapshot()
    cache = adapter.cache
    if (cache is None or not cache.incidence_ready
            or not adapter._cache_context_compatible(parent)
            or not cache.parents.get("NATIVE_CL", {}).get("passes")
            or cache.parents["NATIVE_CL"].get("matrix_no") != 9305):
        raise ValueError("LONG_CACHE_CONTEXT_OR_NATIVE_CL_MISSING")
    profiles = cache.profiles
    reads._validate_profiles(profiles, adapter.cfg)
    matrices = reads._matrices(adapter)
    zones = tuple(adapter.zones)
    pos = {int(z): i for i, z in enumerate(zones)}
    final = matrices[9305]
    component_sum = sum((matrices[no] for no in longinc.COMPONENT_MATRICES), np.zeros_like(final))
    if not np.allclose(component_sum, final, rtol=1.e-8, atol=1.e-6):
        raise ValueError("LONG_CACHE_COMPONENT_TO_FINAL_OD_MISMATCH")
    distance, source = support.read_current(adapter)
    if any(np.any(a[distance < MIN_KM] > 0.0) for a in matrices.values()):
        raise ValueError("LONG_CACHE_OSRM_SUPPORT_NOT_APPLIED")
    stored = np.zeros_like(final)
    for o, d, volume, missing in cache.db.execute('''
        SELECT g.orig,g.dest,SUM(v.volume),
               SUM(CASE WHEN COALESCE(g.edge_count,0)<=0 THEN v.volume ELSE 0 END)
        FROM volumes v JOIN geometry g ON g.gid=v.gid WHERE v.dseg='NATIVE_CL'
        GROUP BY g.orig,g.dest'''):
        if o not in pos or d not in pos or not math.isfinite(volume) or volume < 0.0:
            raise ValueError("LONG_CACHE_INVALID_OD_AXIS_OR_VOLUME")
        if o != d and missing > 0.0:
            raise ValueError("LONG_CACHE_POSITIVE_PATH_WITHOUT_GEOMETRY")
        stored[pos[o], pos[d]] = volume
    positive = final > 0.0
    np.fill_diagonal(positive, False)
    if np.any(positive & (stored <= 0.0)):
        raise ValueError("LONG_CACHE_REFRESH_REQUIRED:NEW_POSITIVE_OD_OR_ZERO_SHARE")
    pairs = [tuple(map(int, pair)) for pair in np.argwhere(positive)]
    if not pairs:
        raise ValueError("LONG_CACHE_NO_INTERZONAL_FLOW")
    index = {pair: i for i, pair in enumerate(pairs)}
    variables = [{"dseg_code": "NATIVE_CL", "family": "LONG", "origin": zones[o],
                  "destination": zones[d], "q_current": float(final[o, d]),
                  "component_vehicle_od": {str(no): float(matrices[no][o, d])
                                           for no in longinc.COMPONENT_MATRICES}}
                 for o, d in pairs]
    rows, cols, values = [], [], []
    for o, d, p, amount in cache.db.execute('''
        SELECT g.orig,g.dest,h.profile_index,SUM(v.volume*h.multiplicity)
        FROM volumes v JOIN geometry g ON g.gid=v.gid JOIN profile_hits h ON h.gid=g.gid
        WHERE v.dseg='NATIVE_CL' GROUP BY g.orig,g.dest,h.profile_index
        ORDER BY g.orig,g.dest,h.profile_index'''):
        if o not in pos or d not in pos or not 0 <= p < len(profiles):
            raise ValueError("LONG_CACHE_PROFILE_OR_OD_AXIS_INVALID")
        if not math.isfinite(amount) or amount < 0.0:
            raise ValueError("LONG_CACHE_PROFILE_AMOUNT_INVALID")
        pair = (pos[o], pos[d])
        c = index.get(pair)
        if c is not None and amount > 0.0:
            rows.append(p); cols.append(c)
            values.append(amount * final[pair] / stored[pair])
    op = core.SparseOperator(np.array(rows, dtype=np.int64), np.array(cols, dtype=np.int64),
                             np.array(values, dtype=float), len(profiles), len(pairs))
    flow = op.forward(np.ones(len(pairs)))
    live = reads._profile_flows(adapter, profiles)
    # Match the ordinary W/S path-profile parity policy, never loosen it here.
    atol = float(adapter.policy.parity_absolute_tolerance)
    rtol = float(adapter.policy.parity_relative_tolerance)
    if not np.isfinite([atol, rtol]).all() or min(atol, rtol) < 0.0:
        raise ValueError("LONG_CACHE_PROFILE_PARITY_POLICY_INVALID")
    tolerances = np.maximum(atol, rtol * np.abs(live))
    if np.any(np.abs(flow - live) > tolerances):
        raise ValueError("LONG_CACHE_REFRESH_REQUIRED:LIVE_PROFILE_PARITY_FAILED")
    after = reads._matrices(adapter)
    _, source_after = support.read_current(adapter)
    if (any(not np.array_equal(matrices[no], after[no]) for no in reads.MATRICES)
            or source != source_after or parent != adapter.generation_guard_snapshot()
            or reads._require_binding(adapter) != binding or cache is not adapter.cache
            or not np.array_equal(live, reads._profile_flows(adapter, profiles))):
        raise ValueError("LONG_CACHE_STATE_CHANGED_DURING_CAPTURE")
    return {"status": STATUS, "source_status": "SHARED_TWO_MODE_CACHE_CURRENT_OD_PROFILE_PARITY",
            "incidence": op, "variables": variables,
            "profile_identity": [p["countlocation_no"] for p in profiles],
            "vehicle_production": final.sum(axis=1), "vehicle_attraction": final.sum(axis=0),
            "vehicle_total": float(final.sum()), "zone_order_sha256": ordered_zone_hash(zones),
            "profile_long_vehicle_flow": flow,
            "component_profile_vehicle_flow": {str(no): op.forward(np.array([
                matrices[no][o, d] / final[o, d] for o, d in pairs]))
                for no in longinc.COMPONENT_MATRICES},
            "matrix_values_sha256": {str(no): matrix_values_hash(a) for no, a in matrices.items()},
            "binding": binding, "cache_parent_hash": cache.parent_hash,
            "parameter_parent_sha256": _parameter_hash(parent),
            "path_epoch": adapter.path_epoch_index,
            "geometry_identity": "PROVISIONAL_SAME_MODE_GEOMETRY_NOT_FULLY_VERIFIED",
            "profile_parity_max_abs": float(np.max(np.abs(flow-live), initial=0.0)),
            "osrm_support": source, "tg_sensitivity_verified": False}


def require_current(adapter, receipt):
    """Check the proposal owner before any coefficient writes, like W/S epochs."""
    if (not receipt or receipt.get("status") != STATUS
            or adapter.cache is None or not adapter.cache.incidence_ready
            or receipt.get("cache_parent_hash") != adapter.cache.parent_hash
            or receipt.get("path_epoch") != adapter.path_epoch_index):
        raise ValueError("LONG_CACHE_GENERATION_PROPOSAL_STALE")
    current = reads._epoch(adapter)
    if current != receipt.get("binding"):
        # W/S backtracking restores parameters before the next full recompute;
        # its frozen proposal intentionally survives the previous trial's OD.
        # Permit exactly that owner's retry, never an unrelated new parent.
        if (getattr(adapter, "_long_generation_transaction_receipt", None) is not receipt
                or receipt.get("parameter_parent_sha256") is None
                or _parameter_hash(adapter.generation_guard_snapshot()) != receipt["parameter_parent_sha256"]):
            raise ValueError("LONG_CACHE_GENERATION_PROPOSAL_STALE")


def begin_apply(adapter, receipt):
    fresh = reads._epoch(adapter) == receipt.get("binding")
    require_current(adapter, receipt)
    if (fresh and receipt.get("parameter_parent_sha256") is not None
            and _parameter_hash(adapter.generation_guard_snapshot()) != receipt["parameter_parent_sha256"]):
        raise ValueError("LONG_CACHE_APPLY_PARENT_PARAMETERS_CHANGED")
    adapter._long_generation_transaction_receipt = receipt


def attach_fit(school, observed, visum, cfg, zones, ws_problem, ws_solution, references, fit_cfg):
    """Fit LONG on the remaining W/S + SCHOOL residual with the same zonal solver."""
    if observed.get("status") != STATUS:
        raise ValueError("LONG_CACHE_PROPOSAL_REQUIRED")
    out = copy.deepcopy(school)
    nrows = len(ws_problem.profile_rows)
    prior = np.asarray(out.get("predicted_change", np.zeros(nrows)), dtype=float)
    current = out.setdefault("current", {})
    for attr in ("ADD_PROD_L", "ADD_ATT_L"):
        values = rt.read_zone_attr_strict(visum, attr, zones, retry_policy=cfg.get("com_resilience"))
        current[attr] = {int(z): float(v) for z, v in zip(zones, values)}
    opts = ls.ls_options()
    up = min(float(cfg.get("max_add_log_up", .03)), math.log1p(min(.10, opts["ls_max_step_up"])))
    down = min(float(cfg.get("max_add_log_down", .03)), -math.log1p(-min(.10, opts["ls_max_step_down"])))
    band = tuple(float(x) for x in opts["ls_long_envelope_ref"])
    authority = fit_cfg["long_mobility_authority"]
    bounds = {}
    for role, attr in (("PROD", "ADD_PROD_L"), ("ATT", "ADD_ATT_L")):
        for z in zones:
            c = current[attr][int(z)]
            entry = authority["entries"].get("LONG|" + str(int(z)))
            if c <= 0.0 or entry is None or "LONG" in authority["unavailable"]:
                bounds[("LONG", role, z)] = (0., 0.); continue
            if role == "PROD":
                reference = .3
            else:
                # Attraction retains the immutable run-start authority; never re-centre.
                reference = mb._reference_coefficient(references, attr, z, float("nan"))
                if not math.isfinite(reference) or reference <= 0.0:
                    raise ValueError("LONG_CACHE_ATTRACTION_REFERENCE_MISSING")
            low, high = min(c, reference*band[0]), max(c, reference*band[1])
            lo, hi = max(-down, math.log(low/c)), min(up, math.log(high/c))
            if role == "PROD":
                lo, hi = mz.bounded_step(entry, lo, authority), mz.bounded_step(entry, hi, authority)
            bounds[("LONG", role, z)] = (lo, hi)
    residual_reference = {"predicted_change": np.asarray(ws_solution["predicted_change"]) + prior}
    try:
        problem = lf.build_problem(observed, ws_problem, residual_reference, zones, bounds)
    except ValueError as exc:
        if str(exc) != "LONG_FIT_NO_ACTUATORS": raise
        out.setdefault("summary", {}).update(long_generation_permitted=True,
            long_search_status="NO_LONG_ACTUATORS_WITHIN_BOUNDS", long_zone_steps=0,
            long_zone_profile_incidence_status=STATUS)
        return out
    solution = zf.solve(problem, {**fit_cfg, "balance_mode": "HARD", "nonlinear_pa_repair": True,
                                 "ridge_relative": float(opts["ls_ridge_relative"])})
    if not np.isfinite(solution["x"]).all() or solution["objective_final"] > solution["objective_initial"] + 1.e-9:
        raise ValueError("LONG_CACHE_FIT_INVALID_OR_WORSE")
    steps = out.setdefault("steps", {})
    for key, step in zip(problem.var_keys, solution["x"]):
        family, role, z = key
        attr = "ADD_PROD_L" if role == "PROD" else "ADD_ATT_L"
        if abs(step) >= 1.e-6: steps.setdefault(attr, {})[int(z)] = float(step)
    effect = out.get("effect_operator", {"keys": [], "G": np.zeros((nrows, 0)).tolist()})
    out["effect_operator"] = {"keys": effect["keys"] + [list(k) for k in problem.var_keys],
                              "G": np.column_stack((np.asarray(effect["G"]), problem.G)).tolist()}
    out["predicted_change"] = (prior + solution["predicted_change"]).tolist()
    out["long_balance_base"] = {"zones": list(zones),
        "production": observed["vehicle_production"].tolist(),
        "attraction": observed["vehicle_attraction"].tolist()}
    out.setdefault("summary", {}).update(status="OK", long_generation_permitted=True,
        long_search_status="ZONAL_LOCAL_PROPOSAL_REQUIRES_LIVE_ACCEPTANCE",
        long_zone_profile_incidence_status=STATUS, long_deferred_reason=None,
        long_zone_steps=sum(len(steps.get(a, {})) for a in ("ADD_PROD_L", "ADD_ATT_L")),
        long_objective_initial=float(solution["objective_initial"]),
        long_objective_final=float(solution["objective_final"]),
        long_solver_converged=bool(solution["converged"]),
        long_native_filter_required=False, long_step_ceiling=.10,
        long_balance_mode=solution["balance_mode"], tg_sensitivity_verified=False,
        linear_ratio_after_ws_and_ls=float(sum(float(r["model"]) for r in ws_problem.profile_rows)
            + np.sum(ws_solution["predicted_change"]) + np.sum(out["predicted_change"])) /
            max(1.e-12, sum(float(r["observed"]) for r in ws_problem.profile_rows)))
    return out


def add_gate_summary(design, ls):
    """Expose the implemented, scaled LONG P/A proposal to the existing TG gate."""
    if not (ls or {}).get("summary", {}).get("long_generation_permitted"):
        return design
    base = (ls or {}).get("long_balance_base")
    if base is None:
        return design  # known zero-actuator case
    steps = {(r["role"], int(r["zone_no"])): math.log(float(r["proposed"])/float(r["current"]))
             for r in design.get("candidate_rows", ()) if r.get("family") == "LONG"}
    p = math.fsum(float(v)*math.expm1(steps.get(("PROD", int(z)), 0.0))
                  for z, v in zip(base["zones"], base["production"]))
    a = math.fsum(float(v)*math.expm1(steps.get(("ATT", int(z)), 0.0))
                  for z, v in zip(base["zones"], base["attraction"]))
    design.setdefault("summary", {}).setdefault("estimated_pa_delta_by_family", {})["LONG"] = {
        "estimated_prod_delta": p, "estimated_att_delta": a, "estimated_abs_gap": abs(p-a),
        "basis": "LOCAL_FINAL_VEHICLE_PROPOSAL_NOT_NATIVE_TG_DERIVATIVE"}
    return design

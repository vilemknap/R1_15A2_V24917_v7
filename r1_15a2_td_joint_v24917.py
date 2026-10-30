# -*- coding: utf-8 -*-
"""TDJOINT1: bounded, component-isolated polling on one shared TD objective.

This is a small alternative search controller, NOT a new demand model.  The
sealed FineCDF reference supplies the native evaluator, parameter coordinates,
bounds, numeric guards and checkpoints.  All targets are scored together; the
count residual is included exactly once.  Native TD writes matrices, never us.
The score is a frozen-path SURROGATE (GEH-squared + 512-point FineCDF), not the
outer live GEH/11D acceptance score.  The latter remains the sole acceptance
 authority.  The existing active-component shortlist is intentionally retained.
"""
from __future__ import annotations

import copy
import functools
import math
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import r1_15a2_long_composite_td_v24917 as long_td

RELEASE = "R1_15A2_V24917_TDJOINT1_20261027"
EPS = 1e-12


def options() -> dict:
    import r1_15a2_demand_policy_v1 as dp
    o = dp.load_options()  # invalid configuration must not disable the feature
    return {"enabled": o.get("td_joint_enabled", False),
            "long_enabled": o.get("long_composite_td_enabled", False),
            "long_generation_enabled": o.get("long_generation_enabled", False),
            "inner_mode": o.get("td_inner_mode"),
            "outer_isolates": o.get("td_joint_outer_isolates", False),
            "max_isolates": o.get("td_joint_max_isolates", 2)}


def validate_count_model(model, targets, active, count_weight):
    """Reject missing/empty attribution, not legitimate zero sensitivity.

    Coverage is reported, not silently represented as exact component paths.
    A partial map remains the inherited approximation.  Both signs of the
    observed count residual are retained in CountModel.q().
    """
    if count_weight <= 0:
        return
    linear = getattr(model, "linear", None)
    if not linear:
        raise RuntimeError("TDJOINT1_COUNT_INCIDENCE_MISSING")
    families = set()
    for key in active:
        for no in targets[key]["matrix_nos"]:
            if 9101 <= int(no) <= 9105 or int(no) == 9117:
                families.add("WORK")
            elif 9106 <= int(no) <= 9110:
                families.add("SERVICE")
    for family in families:
        arrays = linear.get(family)
        if arrays is None or not len(arrays[0]):
            raise RuntimeError("TDJOINT1_COUNT_INCIDENCE_EMPTY_FAMILY:" + family)
        if (len({len(x) for x in arrays}) != 1 or
                not np.all(np.isfinite(arrays[3]))):
            raise RuntimeError("TDJOINT1_COUNT_INCIDENCE_INVALID:" + family)
    if not math.isfinite(float(model.Q_ref)) or model.Q_ref < 0:
        raise RuntimeError("TDJOINT1_COUNT_REFERENCE_INVALID")


def score_blend(blend, out, matrices):
    """Use existing stacked() once; leave every survey metric unmodified."""
    residual, objective, parts = blend.stacked(out, matrices)
    if long_td.GROUP in blend.ref.GROUPS and not blend.measured:
        raise RuntimeError("TDLONG_COMPOSITE_FROZEN_PATH_COUNT_RESPONSE_FORBIDDEN")
    validate_count_model(blend.model, blend.ref.TARGETS, blend.ref.GROUPS,
                         float(blend.opts["w_cnt"]))
    if not (math.isfinite(objective) and np.all(np.isfinite(residual))):
        raise RuntimeError("TDJOINT1_NONFINITE_SCORE")
    mode = "DYNAMIC" if blend.measured else "FROZEN_PATHS"
    blend.last_joint = {
        "release": RELEASE, "objective": float(objective), "parts": dict(parts),
        "w_cnt": float(blend.opts["w_cnt"]), "w_idp": float(blend.opts["w_idp"]),
        "mode": mode, "count_residual_copies": 1,
        "metric": "NORMALIZED_GEH2_PLUS_FINECDF512_SURROGATE",
        "linear_profile_coverage": getattr(blend.model, "linear_profile_coverage", None),
        "fresh_assignment_per_evaluation": bool(blend.measured),
        "component_attribution": "SCALAR_KAPPA_FROZEN_PATH_APPROXIMATION",
    }
    return out


def metric_guards(before: Mapping, after: Mapping, config: Mapping) -> list[str]:
    """Keep inherited fine-CDF and mean-distance bounds, across ALL targets.

    Per-component objective minimisation is deliberately replaced by shared
    objective minimisation.  It is not an extra veto against bounded trade-offs.
    """
    if set(before) != set(after):
        return ["TARGET_SET_CHANGED"]
    reasons = []
    for key in sorted(before):
        a, b = before[key], after[key]
        values = [b["objective"], b["fine_cdf_rmse"], b["mean_relative_error"]]
        if not all(math.isfinite(float(x)) for x in values):
            reasons.append("NONFINITE:" + key)
            continue
        if b["fine_cdf_rmse"] > a["fine_cdf_rmse"] + config["max_fine_cdf_rmse_degradation"]:
            reasons.append("FINECDF_GUARD:" + key)
        mean_limit = max(abs(a["mean_relative_error"]), config["mean_error_floor"])
        if abs(b["mean_relative_error"]) > mean_limit + config["max_mean_error_degradation"]:
            reasons.append("MEAN_GUARD:" + key)
    return reasons


def coordinate_proposals(space, x, components, radius):
    """Small +/- probes in native b and log(-c) coordinates, one group only."""
    for key in components:
        for axis in (0, 1):
            step = min(float(space.probe[key][axis]),
                       float(space.trust[key][axis]) * radius[key])
            for sign in (1, -1):
                lo, hi = space.bounds[key][axis]
                v = float(np.clip(x[key][axis] + sign * step, lo, hi))
                if abs(v - x[key][axis]) <= EPS:
                    continue
                trial = {k: v.copy() for k, v in x.items()}
                trial[key][axis] = v
                yield key, axis, sign, trial


def _signature(x):
    return tuple((k, tuple(float(v) for v in x[k])) for k in sorted(x))


def _score(state):
    return float(state["tdjoint"]["objective"])


def _is_better(base, candidate, config):
    improvement = _score(base) - _score(candidate)
    tol = max(float(config["minimum_objective_improvement"]),
              abs(_score(base)) * float(config["minimum_relative_objective_improvement"]))
    return improvement > tol and not metric_guards(base["metrics"], candidate["metrics"], config)


def optimize(runner, ref):
    """Bounded polling + one combined native verification per complete sweep.

    The baseline plus current base/best arrays are retained. Other probes keep only
    parameters/metrics.  A candidate is never accepted by combining OD cells.
    Budget exhaustion does not imply stationarity.  Numerical failures and
    unexpected exceptions propagate to the GENFIX2 transaction owner.
    """
    baseline = runner.evaluate(runner.space.x, "TDJOINT_BASELINE")
    runner.best = runner.baseline = baseline
    runner.marginals = {n: [a.sum(axis=0), a.sum(axis=1)]
                        for n, a in baseline["matrices"].items()}
    runner.checkpoint(baseline)
    runner.log.summary.update(calibration_baseline="FRESH_NATIVE_TD_TDJOINT1",
                              fresh_baseline_objective_sum=_score(baseline),
                              entry_od_matrices_treated_as_stale=True)
    groups = list(ref.GROUPS)
    if not groups:
        raise RuntimeError("TDJOINT1_EMPTY_ACTIVE_COMPONENTS")
    radius = {k: 1.0 for k in groups}
    poll_history, stagnant = [], 0
    reason = "MAX_ITERATIONS"
    for iteration in range(1, int(ref.CONFIG["max_iterations"]) + 1):
        base = runner.best
        winner = base
        best_by_component = {}
        stop = None
        # Rotate the first group to avoid starvation when the remaining budget
        # permits only part of a sweep.  The original shortlist is unchanged.
        offset = (iteration - 1) % len(groups)
        order = groups[offset:] + groups[:offset]
        proposals = list(coordinate_proposals(runner.space, base["x"], order, radius))
        seen = {_signature(base["x"])}
        records = []
        completed = True
        native_rejections = 0
        at_min_radius = all(radius[k] <= ref.CONFIG["trust_radius_min"] + EPS for k in groups)

        def evaluate_trial(x, label, kind, component=None):
            nonlocal winner, stop, completed, native_rejections
            signature = _signature(x)
            if signature in seen:
                return None
            seen.add(signature)
            try:
                result = runner.evaluate(x, label)
            except ref.StopRequested as exc:
                stop = str(exc)
                completed = False
                return None
            except ref.MarginalGuardError as exc:
                native_rejections += 1
                runner.adapter.restore_state(base["abc"], base["matrices"])
                records.append({"label": label, "kind": kind, "component": component,
                                "status": "REJECTED_NATIVE_MARGIN", "error": str(exc)})
                return None
            guards = metric_guards(base["metrics"], result["metrics"], ref.CONFIG)
            rec = {"label": label, "kind": kind, "component": component,
                   "objective_before": _score(base), "objective": _score(result),
                   "relative_improvement": (_score(base) - _score(result)) / max(EPS, abs(_score(base))),
                   "guard_reasons": guards, "parts": result["tdjoint"]["parts"],
                   "status": "SAFE" if not guards else "REJECTED_SURVEY_GUARD"}
            records.append(rec)
            if _is_better(base, result, ref.CONFIG):
                if _score(result) < _score(winner):
                    # Only keep the winning full matrix snapshot.
                    winner = result
                if component is not None:
                    old = best_by_component.get(component)
                    if old is None or _score(result) < old["objective"]:
                        best_by_component[component] = {
                            "x": result["x"][component].copy(), "objective": _score(result),
                            "label": label, "relative_improvement": rec["relative_improvement"]}
            return rec

        for key, axis, sign, x in proposals:
            evaluate_trial(x, "J%02d_%s_%s_%s" %
                           (iteration, key, "B" if axis == 0 else "LOGC", "P" if sign > 0 else "M"),
                           "ISOLATED", key)
            if stop is not None:
                break
        ranking = sorted(best_by_component, key=lambda k: (best_by_component[k]["objective"], k))
        if stop is None and len(ranking) > 1:
            # At most the two strongest isolated directions: a bounded change,
            # and its joint value is measured rather than assumed additive.
            combo = {k: v.copy() for k, v in base["x"].items()}
            for key in ranking[:2]:
                combo[key] = best_by_component[key]["x"].copy()
            evaluate_trial(combo, "J%02d_COMBINED_TOP2" % iteration, "COMBINED")
        changed = winner is not base
        if changed:
            runner.best = winner
            runner.checkpoint(winner)
            stagnant = 0
        elif completed and native_rejections == 0:
            stagnant += 1
        else:
            stagnant = 0
        runner.adapter.restore_state(runner.best["abc"], runner.best["matrices"])
        changed_groups = [k for k in groups if not np.array_equal(base["x"][k], runner.best["x"][k])]
        for key in groups:
            if key not in changed_groups:
                radius[key] = max(ref.CONFIG["trust_radius_min"],
                                  radius[key] * ref.CONFIG["trust_shrink_rejected"])
        item = {"iteration": iteration, "complete_poll": completed,
                "native_rejections": native_rejections, "polled_at_min_radius": at_min_radius,
                "status": "ACCEPTED_INNER_SURROGATE" if changed else "KEPT_PARENT",
                "changed_components": changed_groups, "ranked_components": ranking,
                "objective_before": _score(base), "objective_after": _score(runner.best),
                "evaluations": runner.evaluations, "trials": records}
        poll_history.append(item)
        runner.log.summary.update(iterations_completed=iteration, stagnant_iterations=stagnant)
        ref.write_json(runner.log.root / "TDJOINT_SEARCH.json", {
            "release": RELEASE, "component_pool": groups, "polls": poll_history,
            "count_residual_copies": 1, "outer_acceptance_authority_changed": False})
        runner.log.event("TDJOINT_ITERATION", "iteration %d %s F=%.9g" %
                         (iteration, item["status"], _score(runner.best)))
        if stop is not None:
            reason = stop
            break
        if (completed and native_rejections == 0 and at_min_radius and
                stagnant >= ref.CONFIG["max_stagnant_iterations"]):
            # Same local-completion contract as the parent, but only after a
            # complete poll of ALL configured active components at min radius.
            # Budget exhaustion, incomplete polls and numerical rejects cannot
            # certify even this local result; global optimality is never claimed.
            reason = "LOCAL_PLATEAU_NOT_PROOF_OF_GLOBAL_OPTIMUM"
            break
    complete = reason == "LOCAL_PLATEAU_NOT_PROOF_OF_GLOBAL_OPTIMUM"
    long_readiness = (long_td.require_live_ready([(long_td.GROUP, [])],
                       bridge=runner.adapter) if long_td.GROUP in groups else None)
    result = {"release": RELEASE, "metric": baseline["tdjoint"]["metric"],
              "objective_start": _score(baseline), "objective_final": _score(runner.best),
              "objective_improvement": _score(baseline) - _score(runner.best),
              "component_pool": groups, "candidate_selection": "MEASURED_SHARED_SURROGATE_WITHIN_EXISTING_MASK",
              "count_residual_copies": 1, "mode": baseline["tdjoint"]["mode"],
              "long_composite_live_readiness": long_readiness,
              "long_full_reference_groups": list(getattr(
                  ref, "_v24917_full_long_reference_groups", ref.GROUPS)),
              "w_cnt": baseline["tdjoint"]["w_cnt"], "w_idp": baseline["tdjoint"]["w_idp"],
              "linear_profile_coverage": baseline["tdjoint"]["linear_profile_coverage"],
              "td_evaluations": runner.evaluations, "stop_reason": reason,
              "search_complete": complete, "stationarity_confirmed": complete,
              "stationarity_scope": "CONFIGURED_ACTIVE_COMPONENT_COORDINATE_POLL_NOT_GLOBAL",
              "fresh_assignment_and_skims_per_finecdf_evaluation": baseline["tdjoint"]["fresh_assignment_per_evaluation"],
              "prediction_is_not_live_acceptance": True,
              "inner_root": str(runner.log.root.resolve()),
              "final_abc": {str(k): dict(v) for k, v in runner.best["abc"].items()},
              "polls_completed": sum(bool(p["complete_poll"]) for p in poll_history)}
    runner.adapter.outer_adapter._tdjoint_stage = result
    ref.write_json(runner.log.root / "TDJOINT_SUMMARY.json", result)
    return reason


def make_runner(parent, ref):
    class JointRunner(parent):
        def evaluate(self, x, label, honor_stop=True):
            # No LONG frozen-route sensitivity claim. The readiness probe
            # reads current native 929x/9305, >=80km support and assignment
            # epoch before any TD parameter mutator is invoked.
            long_td.require_live_ready([(key, []) for key in ref.GROUPS],
                                       bridge=getattr(self, "adapter", None))
            if long_td.GROUP in x and long_td.GROUP not in ref.GROUPS:
                if np.any(np.asarray(x[long_td.GROUP]) != 0):
                    long_td.require_live_ready([(long_td.GROUP, [])])
            result = super().evaluate(x, label, honor_stop=honor_stop)
            impl = getattr(self.metrics, "impl", None)
            blend = getattr(impl, "_v24917_blend_state", None)
            score = getattr(blend, "last_joint", None)
            if score is None:
                raise RuntimeError("TDJOINT1_SHARED_METRIC_NOT_INSTALLED")
            result["tdjoint"] = copy.deepcopy(score)
            ref.write_json(Path(result["folder"]) / "TDJOINT_SCORE.json", score)
            return result

        def optimize(self):
            return optimize(self, ref)
    return JointRunner

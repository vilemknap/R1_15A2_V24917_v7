# -*- coding: utf-8 -*-
"""STEP1: computed Generation step + adoption in place (V24917).

Replaces the discrete backtracking ladder (1, 0.5, 0.25 ... each trial fully
assigned, rolled back, the winner re-applied and re-assigned) by:

1. Predict the profile volumes of the step at scale s
       linear:  m(s) = m0 + s * rho * d          (d = first-order response of the
                                                 zonal fit + LONG/SCHOOL fit, rho =
                                                 learned realisation ratio)
       secant:  m(s) = m0 + s/s_k * (m_k - m0)   (after a measured trial at s_k)
   and run the REAL acceptance gate (core.acceptance_decision, same config, same
   scope) on the predicted rows for a grid of s.  The chosen s maximises the
   predicted weighted-GEH improvement among robustly feasible steps (the gate must
   also pass at s * (1 + margin)).
2. Execute ONE trial at that s (full AMDY recompute + live 12D/11D + block gate,
   exactly as before).  An eligible trial is kept as the new accepted state (no
   rollback, no re-apply, no second assignment).
3. A rejected trial is not rolled back by a recompute: the parent parameters are
   re-written (COM only) and the next trial s is computed from the measured
   secant.  Only when the search ends without an eligible trial is the full
   rollback (recompute + diagnostic verification) executed.

The acceptance decision itself (gate, shared objective, IDP, support risk) is
unchanged; only the order of work and the choice of the scale change.
"""
from __future__ import annotations

import copy
import functools
import json
import math
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np

import r1_15a2_generation_state_v24917 as genstate

RELEASE = "R1_15A2_V24917_STEP1_GENFIX2_20261027"
_STATE: Dict[str, Any] = {"installed": False, "rho": None, "rho_history": [], "blocks": 0,
                          "trials": 0, "kept": 0, "exhausted": 0}


def options() -> Dict[str, Any]:
    try:
        import r1_15a2_demand_policy_v1 as dp
        o = dp.load_options()
    except Exception:
        o = {}
    return {"enabled": bool(o.get("ts_enabled", True)),
            "margin": float(o.get("ts_robust_margin", 0.15)),
            "min_scale": float(o.get("ts_min_scale", 0.05)),
            "max_scale": float(o.get("ts_max_scale", 1.0)),
            "grid": int(o.get("ts_grid_points", 20)),
            "rho_bounds": (0.2, 1.5)}


# ------------------------------------------------------------- prediction
def _ident(row: Mapping[str, Any]) -> str:
    from r1_15a2_td_count_blend_v24917 import cl_key
    for k in ("countlocation_no", "obs_id", "code"):
        v = row.get(k)
        if v not in (None, ""):
            return cl_key(v)
    return ""


def _f(v, default=0.0) -> float:
    try:
        x = float(v)
        return x if math.isfinite(x) else default
    except (TypeError, ValueError):
        return default


def _geh(m: float, o: float) -> float:
    d = m + o
    return math.sqrt(2.0 * (m - o) ** 2 / d) if d > 1e-12 else 0.0


class StepModel:
    """Predicted 12D rows for a Generation step of scale s."""

    def __init__(self, base_rows: Sequence[Mapping[str, Any]], linear: Optional[Mapping[str, Any]],
                 rho: float = 1.0, predictor=None):
        self.predictor = predictor
        self.preview_cache = {}
        self.base_rows = [dict(r) for r in base_rows]
        self.keys = [_ident(r) for r in self.base_rows]
        self.m0 = np.array([_f(r.get("model")) for r in self.base_rows])
        self.obs = np.array([_f(r.get("observed")) for r in self.base_rows])
        self.cal = np.array([str(r.get("role", "")).upper() == "CALIBRATION" and o > 0
                             for r, o in zip(self.base_rows, self.obs)])
        d = np.zeros(len(self.base_rows))
        mapped = 0
        if linear and linear.get("keys") and linear.get("delta_full"):
            by_key: Dict[str, float] = {}
            dup = set()
            for k, v in zip(linear["keys"], linear["delta_full"]):
                if k in by_key:
                    dup.add(k)
                by_key[k] = _f(v)
            for i, k in enumerate(self.keys):
                if k and k in by_key and k not in dup:
                    d[i] = by_key[k]
                    mapped += 1
        self.delta_linear = d
        self.mapped = mapped
        self.rho = float(rho)
        self.measured: Optional[Tuple[float, np.ndarray]] = None   # (s_k, m_k)

    def set_measured(self, scale: float, rows: Sequence[Mapping[str, Any]]) -> None:
        by = {_ident(r): _f(r.get("model")) for r in rows}
        m = np.array([by.get(k, m0) for k, m0 in zip(self.keys, self.m0)])
        self.measured = (float(scale), m)

    def final_prediction(self, s):
        if self.predictor is None or s == 0:
            return s*self.delta_linear, True, []
        key = float(s)
        if key not in self.preview_cache:
            preview = self.predictor(key)
            pred = preview.get("genfix2_prediction") or {}
            proof = preview.get("genfix2_mobility") or {}
            pgate = preview.get("_genfix2_pre_gate") or {"passes": True, "reasons": []}
            ok = proof.get("passes") is True and pgate.get("passes") is True
            reasons = list(pgate.get("reasons", []))
            if proof.get("passes") is not True:
                reasons.append("MOBILITY2_FINAL_ENVELOPE")
            delta = None
            if pred.get("available"):
                keys, vals = pred.get("keys", []), pred.get("delta", [])
                if len(keys) != len(vals) or len(set(keys)) != len(keys):
                    raise ValueError("GENFIX2_PREDICTION_IDENTITY_MISMATCH")
                by = dict(zip(keys, vals))
                delta = np.array([float(by.get(k, 0.0)) for k in self.keys])
                if not np.isfinite(delta).all():
                    raise ValueError("GENFIX2_NONFINITE_PREDICTION")
            self.preview_cache[key] = (delta, ok, reasons)
        return self.preview_cache[key]

    def volumes(self, s: float) -> np.ndarray:
        delta, _, _ = self.final_prediction(s)
        if self.measured is not None:
            sk, mk = self.measured
            old_delta, _, _ = self.final_prediction(sk)
            if delta is not None and old_delta is not None:
                # Account for masks/rebalance at EACH scale, with a secant
                # correction of the measured modelling error, not of stale x.
                m = self.m0 + delta + (s/sk)*(mk-self.m0-old_delta)
            else:
                m = self.m0 + (s/sk)*(mk-self.m0)
        elif delta is not None:
            m = self.m0 + self.rho*delta
        else:
            m = self.m0.copy()  # unavailable prediction -> one real trial, not invented effect
        return np.maximum(m, 0.0)

    def rows(self, s: float) -> List[Dict[str, Any]]:
        out = []
        for r, m, o in zip(self.base_rows, self.volumes(s), self.obs):
            q = dict(r)
            q["model"] = float(m)
            if "geh" in q:
                q["geh"] = _geh(float(m), float(o))
            if "residual" in q:
                q["residual"] = float(o - m)
            out.append(q)
        return out

    def objective(self, s: float) -> float:
        import r1_15a2_core as core
        return float(core.csd_metrics(self.rows(s), "CALIBRATION", True)["objective_geh_mean_weighted"])

    def learn_rho(self, s: float, measured_rows: Sequence[Mapping[str, Any]], bounds=(0.2, 1.5)) -> Optional[float]:
        by = {_ident(r): _f(r.get("model")) for r in measured_rows}
        m = np.array([by.get(k, m0) for k, m0 in zip(self.keys, self.m0)])
        sel = self.cal & (np.abs(self.delta_linear) > 1e-9)
        if s <= 0 or sel.sum() < 5:
            return None
        actual_prediction, _, _ = self.final_prediction(s)
        if actual_prediction is None:
            return None
        dp = actual_prediction[sel]
        dm = m[sel] - self.m0[sel]
        den = float(dp @ dp)
        if den <= 1e-9:
            return None
        return float(min(bounds[1], max(bounds[0], float(dp @ dm) / den)))


def choose_scale(model: StepModel, gate, min_improvement: float, opts: Mapping[str, Any],
                 upper: float) -> Dict[str, Any]:
    """Largest-gain robustly feasible scale in (min_scale, upper] under the model."""
    lo, hi = float(opts["min_scale"]), float(upper)
    n = max(4, int(opts["grid"]))
    grid = sorted({round(x, 6) for x in np.linspace(hi, lo, n)}, reverse=True)
    obj0 = model.objective(0.0)
    margin = float(opts["margin"])
    table = []
    cache: Dict[float, Tuple[bool, List[str], float]] = {}

    def feas(s):
        s = round(float(s), 6)
        if s not in cache:
            rows = model.rows(s)
            dec = gate(model.base_rows, rows)
            obj = model.objective(s)
            rel = (obj0 - obj) / max(abs(obj0), 1e-12)
            _, candidate_ok, candidate_reasons = model.final_prediction(s)
            ok = bool(dec.get("accepted")) and rel >= min_improvement and candidate_ok
            cache[s] = (ok, list(dec.get("reasons") or []) + candidate_reasons, rel)
        return cache[s]

    best = None
    for s in grid:
        ok, reasons, rel = feas(s)
        robust = ok
        if ok:
            s_hi = min(s * (1.0 + margin), float(opts["max_scale"]))
            if model.measured is not None:
                s_hi = min(s_hi, model.measured[0] * 0.999)
            if s_hi > s + 1e-9:
                robust = feas(s_hi)[0]
        table.append({"scale": s, "feasible": ok, "robust": robust, "predicted_rel_improvement": rel,
                      "reasons": reasons[:6]})
        if robust and (best is None or rel > best[1] + 1e-12):
            best = (s, rel)
    return {"scale": None if best is None else best[0],
            "predicted_rel_improvement": None if best is None else best[1],
            "objective_before": obj0, "grid": table,
            "mode": "SECANT_MEASURED" if model.measured is not None else "LINEAR_FIT",
            "rho": model.rho, "mapped_profiles": model.mapped}


# ------------------------------------------------------------- block
def _gate_fn(adapter):
    import r1_15a2_core as core
    d11 = None

    def gate(before_rows, after_rows):
        return core.acceptance_decision(before_rows, after_rows, d11["before"], d11["before"],
                                        adapter.cfg, policy_scope="GENERATION")
    holder = {"before": None}
    d11 = holder
    return gate, holder


def _pre_apply_gate(preview, adapter):
    """The same PA/effect gate plus the final MOBILITY2 envelope. No error-to-PASS fallback."""
    import r1_15a2_supply_visum as sv
    if not isinstance(preview, dict) or "summary" not in preview:
        return None  # legacy adapters without a preview summary retain apply-time gating
    out = sv.base.generation_apply_gate(copy.deepcopy(preview), adapter.cfg)
    mobility = preview.get("genfix2_mobility")
    if mobility is not None and mobility.get("passes") is not True:
        out["passes"] = False
        out["reasons"] = list(out.get("reasons", [])) + ["MOBILITY2_FINAL_ENVELOPE"]
    return out


def _pa_gaps(preview):
    out = {}
    summ = (preview or {}).get("summary", {}) or {}
    if summ.get("v24917_boundary_pa_delta_by_family"):
        out["_boundary"] = summ.get("v24917_boundary_pa_delta_by_family")
        out["_internal"] = {f: {"prod": r.get("estimated_prod_delta"), "att": r.get("estimated_att_delta")}
                            for f, r in (summ.get("v24917_internal_pa_delta_by_family") or {}).items()}
    for fam, row in ((preview or {}).get("summary", {}) or {}).get("estimated_pa_delta_by_family", {}).items():
        try:
            p = abs(float(row.get("estimated_prod_delta", 0.0) or 0.0))
            a = abs(float(row.get("estimated_att_delta", 0.0) or 0.0))
            out[fam] = {"prod": p, "att": a, "rel_gap": float(row.get("estimated_abs_gap", 0.0) or 0.0) / max(1.0, p, a)}
        except Exception:
            pass
    return out


def _generation_block_impl(ctrl, base, tx, adapter, cfg, folder, control, state, diag, anchors, reference, policy):
    """Drop-in replacement of force100._generation_update_once_impl."""
    from r1_15a2_supply import SupplyContractError
    opts = options()
    folder = Path(folder); folder.mkdir(parents=True, exist_ok=True)
    gen_cfg = ctrl._generation_counts_cfg(cfg)
    baseline_value = base.ledger(diag, state, anchors, policy, reference, gen_cfg)
    rec: Dict[str, Any] = {"status": "DESIGNING", "attempts": [], "objective_before": baseline_value,
                           "search_mode": "V24917_STEP1_COMPUTED_STEP_ADOPT_IN_PLACE", "release": RELEASE}

    def write_failure(primary):
        """Keep the model/stop exception authoritative if failure evidence cannot be saved."""
        path = folder / "GENERATION_BLOCK_RESULT.json"
        try:
            base.atomic_json(path, rec)
        except Exception as io_exc:
            detail = {"path": str(path), "error": "%s:%s" % (type(io_exc).__name__, str(io_exc)[:1000])}
            rec.setdefault("failure_record_write_errors", []).append(detail)
            try:
                errors = list(getattr(primary, "generation_failure_write_errors", []))
                errors.append(detail)
                primary.generation_failure_write_errors = errors
                add_note = getattr(primary, "add_note", None)
                if callable(add_note):
                    add_note("GENERATION_FAILURE_RECORD_WRITE_FAILED: " + detail["error"])
            except Exception:
                # Exception metadata is best effort as well; it cannot replace
                # a COM error or KeyboardInterrupt on older Python/COM hosts.
                pass

    if gen_cfg.get("performance", {}).get("active_generation_step_stage"):
        rec["generation_step_stage"] = copy.deepcopy(gen_cfg["performance"]["active_generation_step_stage"])
    design_phase = "BEFORE_DESIGN"
    try:
        genstate.require_parent(adapter, state, folder / "DESIGN_PARENT_CHECK", phase=design_phase)
        design_phase = "GENERATION_DESIGN"
        context = adapter.generation_design(diag, folder / "DESIGN")
        if (context.get("v24917") or {}).get("status") == "BLOCKED_MOBILITY_DATA":
            blocked = context["v24917"]
            rec["mobility_block"] = {k: blocked.get(k) for k in
                ("failure_stage", "exception_type", "error", "detail_path", "status")}
            raise SupplyContractError("MOBILITY2_BLOCKED_DATA_NOT_A_PLATEAU:"
                + str(blocked.get("failure_stage", "UNKNOWN")) + ":"
                + str(blocked.get("error", "NO_DETAIL"))[:1000])
        design_phase = "GENERATION_SOLVER_CHECK"
        if context.get("result") is not None and not context["result"].converged:
            raise SupplyContractError("V245_GENERATION_SOLVER_NOT_CONVERGED_NOT_A_PLATEAU")
        design_phase = "GENERATION_PROJECTION_CHECK"
        if context.get("projection") is not None:
            fams = context["projection"].family_summaries
            if not fams or not all(row.get("converged") for row in fams):
                raise SupplyContractError("V245_GENERATION_PROJECTION_NOT_CONVERGED_NOT_A_PLATEAU")
    except BaseException as exc:
        rec.update(status="FAILED", failure_phase=design_phase, error=str(exc),
                   search_complete=False, stationarity_confirmed=False)
        write_failure(exc)
        raise
    max_trials = max(1, len(gen_cfg.get("backtracking_scales") or [1.0, 0.5, 0.25]))
    limit = int(gen_cfg.get("trial_calibration", {}).get("max_trials_per_block", {}).get("GENERATION", max_trials))
    max_trials = max(1, min(max_trials, limit))
    min_rel = float(((gen_cfg.get("performance", {}) or {}).get("first_sufficient", {}) or {})
                    .get("generation_min_relative_improvement", 0.0) or 0.0)
    rec["planned_trials"] = max_trials
    rec["search_complete"] = False
    rec["stationarity_confirmed"] = False
    rho = _STATE["rho"] if _STATE["rho"] is not None else 1.0
    def final_preview(scale):
        preview = adapter.generation_preview(context, scale)
        preview["_genfix2_pre_gate"] = _pre_apply_gate(preview, adapter)
        return preview
    model = StepModel(diag["d12"]["rows"], context.get("v24917_step_model"), rho,
                      predictor=final_preview if context.get("_genfix2_mobility") else None)
    rec["prediction_authority"] = "FINAL_IMPLEMENTED_EFFECT_ROWS" if model.predictor else "LEGACY_OR_UNAVAILABLE"
    rec["fast_assignment_used"] = False
    rec["fast_assignment_note"] = "STEP1 uses full assignment; fa_enabled applies to legacy scoped evaluator only."
    rec["solver_converged"] = all(x.get("converged") for x in context["projection"].family_summaries) if context.get("projection") else None
    gate, holder = _gate_fn(adapter)
    holder["before"] = diag["d11"]["summary"]
    baseline_diag_hash = base.diagnostic_hash(diag)
    applied_rows: Optional[List[Mapping[str, Any]]] = None     # rows of the trial now live in Visum
    applied_candidate = None
    # Restoring only parameters leaves matrices and loads at the rejected trial.
    # Keep recovery ownership independently until a full rollback is verified or
    # the new live trial is accepted.  Register planned rows before COM writes so
    # a partial apply failure also remains recoverable.
    recovery_rows: Optional[List[Mapping[str, Any]]] = None
    recovery_candidate = None
    demand_dirty = False
    rollback_started = False
    upper = float(opts["max_scale"])
    _STATE["blocks"] += 1

    def own_recovery(rows, candidate):
        nonlocal recovery_rows, recovery_candidate
        retained = {(r["attr"], r["zone_no"]): r for r in (recovery_rows or [])}
        for row in rows:
            retained.setdefault((row["attr"], row["zone_no"]), dict(row))
        recovery_rows = list(retained.values())
        recovery_candidate = dict(candidate)

    def rollback_full(reason):
        nonlocal applied_rows, applied_candidate, recovery_rows, recovery_candidate, demand_dirty
        nonlocal rollback_started, diag, baseline_value, baseline_diag_hash, state
        if recovery_rows is None:
            return
        rollback_started = True
        with base.recovery_scope(control, "STEP1_FINAL_ROLLBACK"):
            rb, rolled = base._rollback_candidate(adapter, "GENERATION", state, baseline_diag_hash,
                                                  folder / "ROLLBACK", recovery_rows, recovery_candidate, diag)
        base.atomic_json(folder / "ROLLBACK_SUMMARY.json", dict(rb, reason=reason))
        import r1_15a2_parent_equivalence_v24917 as eq
        live_state = adapter.snapshot()
        proof = eq.verify_parent(adapter, state, live_state, diag, rolled)
        if not proof["passes"]:
            raise SupplyContractError("V242_GENERATION_ROLLBACK_DIAGNOSTIC_CHANGED")
        # Carry the measured parent diagnostics forward. Never label stale diagnostics exact.
        eq.rebind_verified_parent(adapter, live_state, rolled)
        state, diag = live_state, rolled
        baseline_diag_hash = base.diagnostic_hash(diag)
        baseline_value = base.ledger(diag, state, anchors, policy, reference, gen_cfg)
        rec["rollback_parent_equivalence"] = proof
        applied_rows = recovery_rows = None
        applied_candidate = recovery_candidate = None
        demand_dirty = False

    try:
        for ordinal in range(1, max_trials + 1):
            plan = choose_scale(model, gate, min_rel, opts, upper)
            scale = plan["scale"]
            if scale is None and model.measured is None:
                # the linear model sees no feasible step: measure the full step once
                scale = upper
                plan["fallback"] = "LINEAR_MODEL_NO_ROBUST_STEP_MEASURE_FULL"
            base.atomic_json(folder / ("STEP1_PLAN_%02d.json" % ordinal), plan)
            if scale is None:
                rec["stop_reason"] = "NO_ROBUST_FEASIBLE_SCALE_BELOW_MEASURED_TRIAL"
                break
            candidate = {"scale": float(scale)}
            trial_folder = folder / ("TRY_%02d" % ordinal)
            trial_folder.mkdir(parents=True, exist_ok=True)
            control.checkpoint("COUPLED_DEMAND_GENERATION_TRIAL", force=True, trial=ordinal)
            attempt: Dict[str, Any] = {"trial": ordinal, "candidate": candidate, "plan_mode": plan["mode"],
                                       "predicted_rel_improvement": plan.get("predicted_rel_improvement"),
                                       "rho": plan.get("rho")}
            try:
                if applied_rows is not None:
                    # parent parameters back (COM writes only; the next recompute regenerates all demand)
                    tx.restore_generation_parameters(adapter, state, list(applied_rows),
                                                     trial_folder / "RESTORE_PARENT_PARAMETERS")
                    applied_rows = None
                elif recovery_rows is None:
                    genstate.require_parent(adapter, state, trial_folder / "PARENT_CHECK",
                                            phase="BEFORE_TRIAL_APPLY")
                preview, rows = base._planned_generation_rows(adapter, context, float(scale))
                # GATEFIT1: the pre-apply TG gate (P/A balance per family, projection error) is checked
                # on the preview, before any write or assignment; shrink the step until it passes.
                gate_log = []
                pgate = _pre_apply_gate(preview, adapter)
                while pgate is not None and not pgate["passes"]:
                    gate_log.append({"scale": float(scale), "reasons": pgate["reasons"],
                                     "pa_gaps": _pa_gaps(preview)})
                    nxt = float(scale) * 0.75
                    if nxt < float(opts["min_scale"]):
                        break
                    scale = nxt
                    candidate = {"scale": float(scale)}
                    preview, rows = base._planned_generation_rows(adapter, context, float(scale))
                    pgate = _pre_apply_gate(preview, adapter)
                if gate_log:
                    attempt["pre_apply_gate_shrink"] = gate_log
                    attempt["candidate"] = candidate
                    _STATE["pre_gate_shrinks"] = _STATE.get("pre_gate_shrinks", 0) + len(gate_log)
                if pgate is not None and not pgate["passes"]:
                    attempt["status"] = "REJECTED_PRE_APPLY_GATE_ALL_SCALES"
                    rec["attempts"].append(attempt)
                    rec["stop_reason"] = "PRE_APPLY_GATE_NO_FEASIBLE_SCALE"
                    base.atomic_json(folder / "GENERATION_BLOCK_RESULT.json", rec)
                    break
                base.atomic_json(trial_folder / ("GENERATION_PREVIEW_%s.json" % str(round(scale, 6)).replace(".", "_")),
                                 preview)
                rows = list(rows or [])
                if not rows:
                    attempt["status"] = "NO_PARAMETER_CANDIDATE"
                    rec["attempts"].append(attempt)
                    rec["stop_reason"] = "NO_PARAMETER_CANDIDATE"
                    break
                signature = base._candidate_signature("GENERATION", candidate, rows)
                if hasattr(adapter, "begin_candidate_readback_context"):
                    adapter.begin_candidate_readback_context(
                        state["state_hash"], "GENERATION", signature,
                        parameter_evidence={"candidate": candidate, "rows": rows})
                control.checkpoint("TRIAL_APPLY", block="GENERATION", candidate=signature)
                applied_candidate = candidate
                applied_rows = rows                       # rollback scope even if the write fails halfway
                own_recovery(rows, candidate)
                actual = base._apply_candidate(adapter, "GENERATION", candidate, rows, context, state, trial_folder)
                applied_rows = list(actual)
                own_recovery(applied_rows, candidate)
                control.checkpoint("TRIAL_ASSIGNMENT", block="GENERATION")
                demand_dirty = True
                gap = base._assign_candidate(adapter, trial_folder / "ASSIGNMENT", "GENERATION")
                adapter.parameter_persistence("GENERATION", actual)
                after = adapter.snapshot()
                base.assert_freeze(state, after, "GENERATION", rows=actual, candidate=candidate, cfg=gen_cfg)
                control.checkpoint("TRIAL_DIAGNOSTICS", block="GENERATION")
                import r1_15a2_perf_v24917 as perf
                with perf.deferred_archives() as deferred:
                    after_diag = adapter.diagnostics(trial_folder / "DIAGNOSTICS", "AFTER")
                    if adapter.snapshot() != after:
                        raise SupplyContractError("TRIAL_DIAGNOSTICS_CHANGED_MODEL")
                    after_value = base.ledger(after_diag, after, anchors, policy, reference, gen_cfg)
                    decision = adapter.block_gate("GENERATION", diag, after_diag, actual)
                    improvement = baseline_value["total"] - after_value["total"]
                    decision["shared_ledger_before"] = baseline_value
                    decision["shared_ledger_after"] = after_value
                    decision["shared_objective_improvement"] = improvement
                    minimum = base.number(gen_cfg.get("shared_objective", {}).get("minimum_improvement", 1e-8))
                    nonmono = decision.get("exploration_nonmonotonic_accepted") is True
                    decision["shared_objective_monotonicity_bypassed"] = nonmono
                    if improvement <= minimum and not nonmono:
                        decision["accepted"] = False
                        decision.setdefault("reasons", []).append("SHARED_OBJECTIVE_NOT_IMPROVED")
                    base._write_acceptance(trial_folder / "ACCEPTANCE.json", decision)
                    deferred.keep = bool(decision.get("accepted"))
            except BaseException as exc:
                if isinstance(exc, Exception) and "GENERATION_GATE:" in str(exc):
                    # gate runs before any zone write: parent parameters back (cheap COM writes), smaller step
                    if applied_rows is not None:
                        tx.restore_generation_parameters(adapter, state, list(applied_rows),
                                                         trial_folder / "RESTORE_AFTER_PRE_APPLY_GATE")
                        applied_rows = None
                    if not demand_dirty:
                        # The known pre-write gate did not execute demand.  Release
                        # ownership only after proving that restoration is exact.
                        try:
                            genstate.require_parent(adapter, state, trial_folder / "PRE_APPLY_GATE_PARENT_CHECK",
                                                    phase="AFTER_PRE_APPLY_GATE_RESTORE")
                        except BaseException as restore_exc:
                            rec.update(status="FAILED", failure_phase="PRE_APPLY_GATE_RESTORE",
                                       error=str(restore_exc))
                            attempt.update(status="FAILED", error=str(restore_exc))
                            rec["attempts"].append(attempt)
                            write_failure(restore_exc)
                            rollback_full("PRE_APPLY_GATE_RESTORE_ERROR")
                            raise
                        recovery_rows = None
                        recovery_candidate = None
                    attempt.update(status="REJECTED_PRE_APPLY_GATE", error=str(exc)[:500])
                    rec["attempts"].append(attempt)
                    base.atomic_json(folder / "GENERATION_BLOCK_RESULT.json", rec)
                    upper = float(scale) * 0.75
                    if upper < float(opts["min_scale"]):
                        rec["stop_reason"] = "PRE_APPLY_GATE_NO_FEASIBLE_SCALE"
                        break
                    continue
                attempt["status"] = "FAILED"
                attempt["error"] = str(exc)
                rec["attempts"].append(attempt)
                rec.update(status="FAILED", failure_phase="GENERATION_TRIAL", error=str(exc))
                write_failure(exc)
                if recovery_rows is not None:
                    rollback_full("TRIAL_ERROR")
                if not isinstance(exc, Exception) or isinstance(exc, (base.UserStopRequested, base.TimeBudgetReached)):
                    raise
                raise SupplyContractError("V245_GENERATION_TRIAL_ERROR_NOT_A_PLATEAU:" + str(exc)) from exc
            _STATE["trials"] += 1
            measured_obj = float(after_value.get("raw_cal", after_value.get("cal_metrics", {}).get(
                "objective_geh_mean_weighted", float("nan"))))
            attempt.update(status="ELIGIBLE" if decision.get("accepted") else "REJECTED", gap=gap,
                           decision=decision, counts_objective=after_value,
                           predicted_objective=model.objective(float(scale)), measured_objective=measured_obj)
            if plan["mode"] == "LINEAR_FIT":
                r = model.learn_rho(float(scale), after_diag["d12"]["rows"], opts["rho_bounds"])
                if r is not None:
                    old = _STATE["rho"]
                    _STATE["rho"] = r if old is None else 0.5 * old + 0.5 * r
                    _STATE["rho_history"].append({"measured": r, "used_next": _STATE["rho"]})
                    attempt["rho_measured"] = r
            rec["attempts"].append(attempt)
            base.atomic_json(folder / "GENERATION_BLOCK_RESULT.json", rec)
            if decision.get("accepted"):
                cache_transition = None
                if hasattr(adapter, "accepted_state_changed"):
                    cache_transition = adapter.accepted_state_changed(
                        after, after_diag, reason="V242_ACCEPTED_GENERATION_STATE_CHANGED", phase="DEMAND")
                elif hasattr(adapter, "invalidate_cache"):
                    adapter.invalidate_cache("V242_ACCEPTED_GENERATION_STATE_CHANGED", clear_proof=True)
                rec.update(status="ACCEPTED", gap=gap, candidate=candidate, rows=len(actual),
                           objective_after=after_value, path_epoch_transition=cache_transition,
                           search_complete=True, adopted_in_place=True, early_stop_trial=ordinal,
                           early_stop_policy="STEP1_FIRST_ELIGIBLE_KEPT")
                base.atomic_json(folder / "GENERATION_BLOCK_RESULT.json", rec)
                recovery_rows = None
                recovery_candidate = None
                demand_dirty = False
                _STATE["kept"] += 1
                return True, after, after_diag, after_value, rec
            model.set_measured(float(scale), after_diag["d12"]["rows"])
            upper = float(scale) * 0.95
            if upper < float(opts["min_scale"]):
                rec["stop_reason"] = "SCALE_BELOW_MINIMUM"
                break
        rollback_full("SEARCH_EXHAUSTED")
        _STATE["exhausted"] += 1
        rec["search_complete"] = True
        rec["configured_search_exhausted"] = True
        # A usable or truncated fit is not a stationarity certificate. Only a
        # converged proposal with the complete configured REAL trial budget
        # rejected can satisfy the controller's finite-search contract.
        verified = bool(rec.get("solver_converged") is True
                        and len(rec["attempts"]) == max_trials
                        and all(a.get("status") == "REJECTED" for a in rec["attempts"]))
        rec["stationarity_confirmed"] = verified
        rec["stationarity_verified"] = verified
        rec["stationarity_scope"] = "CONVERGED_PROPOSAL_COMPLETE_CONFIGURED_REAL_SEARCH_NOT_GLOBAL_OPTIMALITY"
        rec["stationarity_reason"] = ("COMPLETE_CONFIGURED_REAL_SEARCH_REJECTED" if verified
                                      else "BOUNDED_OR_UNVERIFIED_SEARCH_NOT_A_STATIONARITY_CERTIFICATE")
        rec["status"] = "CONFIGURED_GENERATION_SEARCH_EXHAUSTED"
        base.atomic_json(folder / "GENERATION_BLOCK_RESULT.json", rec)
        return False, state, diag, baseline_value, rec
    except BaseException as exc:
        # Planning, checkpoints, and acceptance bookkeeping also run while the
        # previous rejected assignment may still be live.  Every exceptional
        # exit must pass through the same transaction owner, including stops.
        rec.update(status="FAILED", search_complete=False, stationarity_confirmed=False)
        rec.setdefault("failure_phase", "GENERATION_SEARCH")
        rec.setdefault("error", str(exc))
        try:
            write_failure(exc)
        finally:
            if recovery_rows is not None and not rollback_started:
                rollback_full("SEARCH_ERROR")
        raise


def generation_block(ctrl, base, tx, adapter, cfg, folder, control, state, diag, anchors, reference, policy):
    import r1_15a2_parent_equivalence_v24917 as eq
    with eq.parent_scope(adapter, state, folder):
        return _generation_block_impl(ctrl, base, tx, adapter, cfg, folder, control, state, diag, anchors, reference, policy)


def install(print_fn=print) -> Dict[str, Any]:
    if _STATE["installed"]:
        return status()
    import r1_15a2_overnight_controller_v24915p2 as base
    import r1_15a2_overnight_controller_coupled_v24915p2_force100 as ctrl
    import r1_15a2_inplace_transaction_v24915p2 as tx
    for name in ("ledger", "diagnostic_hash", "assert_freeze", "atomic_json", "_write_acceptance",
                 "_planned_generation_rows", "_candidate_signature", "_apply_candidate", "_assign_candidate",
                 "_rollback_candidate", "recovery_scope", "number", "UserStopRequested", "TimeBudgetReached"):
        if not hasattr(base, name):
            raise RuntimeError("V24917_STEP1_BASE_SYMBOL_MISSING:" + name)
    orig = ctrl._generation_update_once_impl
    if not getattr(orig, "__r1_step1__", False):
        @functools.wraps(orig)
        def _generation_update_once_impl(adapter, cfg, folder, control, state, diag, anchors, reference, policy):
            if not options()["enabled"]:
                return orig(adapter, cfg, folder, control, state, diag, anchors, reference, policy)
            return generation_block(ctrl, base, tx, adapter, cfg, folder, control, state, diag,
                                    anchors, reference, policy)
        _generation_update_once_impl.__r1_step1__ = True
        ctrl._generation_update_once_impl = _generation_update_once_impl
    _STATE["installed"] = True
    o = options()
    print_fn("V24917 STEP1: %s; computed Generation step (margin %.2f), eligible trial kept in place"
             % ("ON" if o["enabled"] else "OFF", o["margin"]))
    return status()


def status() -> Dict[str, Any]:
    return {k: (list(v) if isinstance(v, list) else v) for k, v in _STATE.items()}


__all__ = ["RELEASE", "install", "status", "StepModel", "choose_scale", "generation_block", "options"]

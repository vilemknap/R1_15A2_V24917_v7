# -*- coding: utf-8 -*-
"""FASTASSIGN1: warm-start PrT assignment for rejected-or-not Generation trials.

Methodology (user, 2026-10-25): the AMDY sequence is reset -> freight preload
(op 17) -> native preloads (ops 18, 19) -> joint assignment of all 14 DSegs
(op 20).  Operation 20 starts from the volumes already present on the network
("princip preloadu").  For a *trial* the parent's converged joint equilibrium is
a better initial solution than the preload chain, so a Generation trial runs:

    TG -> TD -> kappa/symmetrization -> op 20 (warm from the parent equilibrium)
    -> GEH -> skims

i.e. the reset operations (1, 15) and the preload assignments (17, 18, 19) are
switched off for that one execution only.  The assignment quality gate
(``supply.gap_readback.maximum_gap`` on op 20) is unchanged and still enforced.

Exactness is kept where the calibration state is defined:

* rollback recompute after a trial  -> full original sequence (cold), so the
  parent diagnostics are reproduced exactly (hash-equal, as before);
* adoption of the winning candidate -> full original sequence (cold); the
  acceptance decision is re-taken on that authoritative AMDY assignment
  (block gate + shared objective), the warm/cold reproducibility hash check is
  replaced by that re-decision;
* TD realization, supply, baseline, checkpoints -> unchanged (cold).

If the authoritative cold adoption does not confirm the warm trial, the whole
Generation block is repeated once with cold trials (no false plateau).

Every precondition is checked against the live Procedure Sequence; any mismatch
falls back to the unchanged plan (fail-closed to the original behavior).
"""
from __future__ import annotations

import copy
import functools
import threading
from pathlib import Path
from typing import Any, Dict, List, Mapping

RELEASE = "R1_15A2_V24917_FASTASSIGN1_20261025"
RESET_TYPE = 9            # "Initialize assignment" (ops 1, 15, 37)
PRT_ASSIGNMENT_TYPE = 101
DEFAULT_SKIP = (1, 15, 17, 18, 19)
EXPECTED_TYPES = {1: RESET_TYPE, 15: RESET_TYPE, 17: PRT_ASSIGNMENT_TYPE,
                  18: PRT_ASSIGNMENT_TYPE, 19: PRT_ASSIGNMENT_TYPE}

_LOCAL = threading.local()
_STATE: Dict[str, Any] = {"installed": False, "events": [], "cold_retry_blocks": 0,
                          "fast_trials": 0, "fallback_plans": 0}


class FastAdoptionRejected(Exception):
    """Cold AMDY adoption did not confirm a warm-start trial (state rolled back)."""


def options() -> Dict[str, Any]:
    try:
        import r1_15a2_demand_policy_v1 as dp
        o = dp.load_options()
    except Exception:
        o = {}
    return {"enabled": bool(o.get("fa_enabled", True)),
            "skip_positions": list(o.get("fa_skip_positions", DEFAULT_SKIP)),
            "blocks": [str(b).upper() for b in o.get("fa_blocks", ["GENERATION"])]}


def _event(kind: str, **kw) -> None:
    ev = dict(kind=kind, **kw)
    _STATE["events"].append(ev)
    del _STATE["events"][:-200]


def fast_active() -> bool:
    return bool(getattr(_LOCAL, "assign_fast", False))


# ------------------------------------------------------------------ plan
def fast_plan(base_plan: Mapping[str, Any], block: str, opts: Mapping[str, Any]) -> Dict[str, Any]:
    """Derive the warm-trial plan from an audited base plan (pure function)."""
    inventory = list(base_plan.get("inventory") or [])
    by_pos = {int(r["no"]): r for r in inventory}
    selected = {int(v) for v in base_plan.get("selected_operation_positions", [])}
    skip = sorted({int(v) for v in opts.get("skip_positions", DEFAULT_SKIP)})
    reasons: List[str] = []
    approved = [int(v) for v in base_plan.get("approved_assignment_positions", []) or []]
    if not approved:
        approved = sorted(int(r["no"]) for r in inventory
                          if int(r.get("type", -1)) == PRT_ASSIGNMENT_TYPE and int(r.get("active", 0))
                          and int(r["no"]) not in skip)[-1:]
    if not approved:
        reasons.append("NO_APPROVED_ASSIGNMENT")
    joint = max(approved) if approved else None
    for pos in skip:
        row = by_pos.get(pos)
        if row is None:
            reasons.append("SKIP_OPERATION_MISSING:%d" % pos)
            continue
        exp = EXPECTED_TYPES.get(pos)
        typ = int(row.get("type", -1))
        if typ not in (RESET_TYPE, PRT_ASSIGNMENT_TYPE) or (exp is not None and typ != exp):
            reasons.append("SKIP_OPERATION_TYPE:%d:%d" % (pos, typ))
        if joint is not None and pos >= joint:
            reasons.append("SKIP_NOT_BEFORE_JOINT_ASSIGNMENT:%d" % pos)
        if pos in approved:
            reasons.append("SKIP_IS_APPROVED_ASSIGNMENT:%d" % pos)
    if joint is not None and joint not in selected:
        reasons.append("JOINT_ASSIGNMENT_NOT_SELECTED")
    # the joint assignment must not be preceded by another *selected* reset
    if joint is not None:
        other_resets = [p for p in selected if p < joint and p not in skip
                        and int((by_pos.get(p) or {}).get("type", -1)) == RESET_TYPE]
        if other_resets:
            reasons.append("OTHER_RESET_BEFORE_JOINT:%s" % ",".join(map(str, sorted(other_resets))))
    if reasons:
        out = dict(base_plan)
        out["v24917_fast_trial"] = {"applied": False, "reasons": reasons, "release": RELEASE}
        return out
    new_sel = sorted(selected - set(skip))
    out = dict(base_plan)
    out.update({
        "mode": "V24917_FAST_WARM_TRIAL",
        "optimized": True,
        "selected_operation_positions": new_sel,
        "skipped_originally_active_positions": sorted(
            set(base_plan.get("original_active_operation_positions", [])) - set(new_sel)),
        "v24917_fast_trial": {
            "applied": True, "release": RELEASE, "block": str(block),
            "skipped_positions": [p for p in skip if p in selected],
            "joint_assignment": joint,
            "initial_solution": "PARENT_CONVERGED_JOINT_EQUILIBRIUM",
            "quality_gate": "UNCHANGED_SUPPLY_GAP_READBACK",
            "base_plan_mode": base_plan.get("mode"),
        },
    })
    return out


# ------------------------------------------------------------- wrappers
def _wrap_plan(orig):
    @functools.wraps(orig)
    def phase_recompute_plan(visum, cfg, block):
        plan = orig(visum, cfg, block)
        if not fast_active():
            return plan
        opts = options()
        out = fast_plan(plan, block, opts)
        info = out.get("v24917_fast_trial", {})
        if info.get("applied"):
            _STATE["fast_trials"] += 1
        else:
            _STATE["fallback_plans"] += 1
        _event("PLAN", block=str(block), applied=bool(info.get("applied")),
               reasons=info.get("reasons", []))
        return out
    phase_recompute_plan.__r1_fastassign__ = True
    return phase_recompute_plan


def _wrap_assign(orig):
    @functools.wraps(orig)
    def _assign_candidate(adapter, folder, block):
        opts = options()
        use = (getattr(_LOCAL, "eval_scope", False) and opts["enabled"]
               and str(block).upper() in opts["blocks"]
               and not getattr(_LOCAL, "cold_retry", False))
        prev = getattr(_LOCAL, "assign_fast", False)
        _LOCAL.assign_fast = bool(use)
        try:
            return orig(adapter, folder, block)
        finally:
            _LOCAL.assign_fast = prev
    _assign_candidate.__r1_fastassign__ = True
    return _assign_candidate


def _wrap_evaluate(orig):
    @functools.wraps(orig)
    def _evaluate_candidate(adapter, cfg, policy, block, *args, **kwargs):
        prev = getattr(_LOCAL, "eval_scope", False)
        _LOCAL.eval_scope = True
        before = _STATE["fast_trials"]
        try:
            result = orig(adapter, cfg, policy, block, *args, **kwargs)
        finally:
            _LOCAL.eval_scope = prev
        warm = _STATE["fast_trials"] > before
        try:
            ev = result[0]
            if isinstance(ev, dict):
                ev["v24917_fast_warm_trial"] = warm
        except Exception:
            pass
        return result
    _evaluate_candidate.__r1_fastassign__ = True
    return _evaluate_candidate


def _wrap_adopt(orig, SupplyContractError):
    @functools.wraps(orig)
    def _adopt_candidate(adapter, cfg, policy, block, best, *args, **kwargs):
        if not (isinstance(best, dict) and best.get("v24917_fast_warm_trial")):
            return orig(adapter, cfg, policy, block, best, *args, **kwargs)
        cold_cfg = copy.deepcopy(dict(cfg))
        tc = dict(cold_cfg.get("trial_calibration", {}) or {})
        tc["require_reproducible_reapply"] = False
        cold_cfg["trial_calibration"] = tc
        try:
            out = orig(adapter, cold_cfg, policy, block, best, *args, **kwargs)
        except SupplyContractError as exc:
            if str(exc).startswith("ADOPTION_REJECTED"):
                _event("COLD_ADOPTION_REJECTED", block=str(block), error=str(exc))
                raise FastAdoptionRejected(str(exc)) from exc
            raise
        _event("COLD_ADOPTION_CONFIRMED", block=str(block))
        return out
    _adopt_candidate.__r1_fastassign__ = True
    return _adopt_candidate


def _wrap_generation_impl(orig):
    @functools.wraps(orig)
    def _generation_update_once_impl(adapter, cfg, folder, *args, **kwargs):
        try:
            return orig(adapter, cfg, folder, *args, **kwargs)
        except FastAdoptionRejected as exc:
            # state was rolled back to the identical accepted parent inside adoption
            _STATE["cold_retry_blocks"] += 1
            _event("COLD_RETRY_BLOCK", error=str(exc))
            prev = getattr(_LOCAL, "cold_retry", False)
            _LOCAL.cold_retry = True
            try:
                rec = orig(adapter, cfg, Path(folder) / "COLD_RETRY", *args, **kwargs)
            finally:
                _LOCAL.cold_retry = prev
            try:
                rec[4]["v24917_fast_trial_cold_retry"] = str(exc)
            except Exception:
                pass
            return rec
    _generation_update_once_impl.__r1_fastassign__ = True
    return _generation_update_once_impl


def install(print_fn=print) -> Dict[str, Any]:
    if _STATE["installed"]:
        return status()
    import r1_15a2_acceleration_v24915p1 as perf1
    import r1_15a2_overnight_controller_v24915p2 as base_ctrl
    import r1_15a2_overnight_controller_coupled_v24915p2_force100 as ctrl
    from r1_15a2_supply import SupplyContractError
    opts = options()
    if not getattr(perf1.phase_recompute_plan, "__r1_fastassign__", False):
        perf1.phase_recompute_plan = _wrap_plan(perf1.phase_recompute_plan)
    if not getattr(base_ctrl._assign_candidate, "__r1_fastassign__", False):
        base_ctrl._assign_candidate = _wrap_assign(base_ctrl._assign_candidate)
    if not getattr(ctrl._evaluate_candidate, "__r1_fastassign__", False):
        ctrl._evaluate_candidate = _wrap_evaluate(ctrl._evaluate_candidate)
    if not getattr(ctrl._adopt_candidate, "__r1_fastassign__", False):
        ctrl._adopt_candidate = _wrap_adopt(ctrl._adopt_candidate, SupplyContractError)
    if not getattr(ctrl._generation_update_once_impl, "__r1_fastassign__", False):
        ctrl._generation_update_once_impl = _wrap_generation_impl(ctrl._generation_update_once_impl)
    _STATE["installed"] = True
    _STATE["options"] = opts
    print_fn("V24917 FASTASSIGN1: %s; warm Generation trials skip ops %s, adoption/rollback stay full AMDY"
             % ("ON" if opts["enabled"] else "OFF", opts["skip_positions"]))
    return status()


def status() -> Dict[str, Any]:
    return {"release": RELEASE, "installed": _STATE["installed"], "options": _STATE.get("options"),
            "fast_trials": _STATE["fast_trials"], "fallback_plans": _STATE["fallback_plans"],
            "cold_retry_blocks": _STATE["cold_retry_blocks"], "events": list(_STATE["events"][-50:])}


__all__ = ["RELEASE", "install", "status", "fast_plan", "options", "FastAdoptionRejected"]

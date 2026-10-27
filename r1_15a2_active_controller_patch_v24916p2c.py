# -*- coding: utf-8 -*-
"""Minimal controller patch for V24916 TD active-component targeting.

Generation targeting lives entirely in the adapter.  This patch changes only
FineCDF dispatch: obtain a read-only target plan, scope the inner search to the
selected components, and still realize/evaluate/rollback through the exact
parent controller.  Parent acceptance logic is untouched.
"""
from __future__ import annotations

import copy
import traceback
from pathlib import Path

from r1_15a2_finecdf_bridge_v24916 import run_finecdf_inner as targeted_run_finecdf_inner
from r1_15a2_supply import SupplyContractError


def install(parent_module):
    """Patch one already-imported current PERF2 coupled controller module."""
    parent_module.run_finecdf_inner = targeted_run_finecdf_inner

    def _finecdf_td_once_impl(adapter, cfg, folder, control, state, diag, package_root):
        folder = Path(folder); folder.mkdir(parents=True, exist_ok=True)
        before, baseline_diag = state, diag
        targeted_cfg = copy.deepcopy(cfg)
        try:
            target_plan = {"status": "GLOBAL_IDP_FALLBACK", "active_components": [],
                           "reason": "ADAPTER_HAS_NO_TD_TARGET_PLAN"}
            if hasattr(adapter, "td_target_plan"):
                target_plan = adapter.td_target_plan(diag, folder / "TARGETING")
            active_components = [str(x) for x in target_plan.get("active_components", []) if str(x)]
            fine = targeted_cfg.setdefault("coupled_demand", {}).setdefault("finecdf_td", {})
            if target_plan.get("status") == "ACTIVE" and active_components:
                fine["active_components"] = active_components
            else:
                fine.pop("active_components", None)
            parent_module.atomic_json(folder / "TD_TARGET_PLAN.json", target_plan)

            budget = parent_module._finecdf_budget_for_cycle(
                targeted_cfg, int(targeted_cfg.get("runtime_acceptance_outer_cycle", 1) or 1))
            if budget:
                inner = targeted_run_finecdf_inner(
                    adapter, targeted_cfg, folder / "FINECDF_INNER", control,
                    package_root, phase_budget=budget)
            else:
                inner = targeted_run_finecdf_inner(
                    adapter, targeted_cfg, folder / "FINECDF_INNER", control,
                    package_root)
            target_rows = [{"component": r["component"],
                            "candidate_b": r["after_b"], "candidate_c": r["after_c"]}
                           for r in inner.get("changed_rows", [])]
            realized_rows, after, after_diag, gap, realization = parent_module._realize_finecdf_td(
                adapter, targeted_cfg, folder / "REALIZATION", control, before, baseline_diag,
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
                        after, after_diag,
                        reason="V24916_ACCEPTED_REALIZED_FINECDF_TD_STATE_CHANGED",
                        phase="DEMAND")
                elif hasattr(adapter, "invalidate_cache"):
                    adapter.invalidate_cache(
                        "V24916_ACCEPTED_REALIZED_FINECDF_TD_STATE_CHANGED", clear_proof=True)
            rec = {
                "status": "ACCEPTED_FINECDF_TD" if realized_rows else "FINECDF_TD_PLATEAU",
                "gap": gap, "inner": inner, "changed_rows": realized_rows,
                "target_changed_rows": target_rows,
                "td_realization_complete": True,
                "realization": realization,
                "progressive_budget": budget,
                "td_target_plan": target_plan,
                "path_epoch_transition": cache_transition,
                "state_hash": after["state_hash"],
                "diagnostic_hash": parent_module.diagnostic_hash(after_diag),
                "acceptance_authority_changed": False,
                "global_11d_evaluation_required": True,
            }
            parent_module.atomic_json(folder / "TD_FINECDF_BLOCK_RESULT.json", rec)
            return bool(realized_rows), after, after_diag, rec
        except BaseException as exc:
            try:
                with parent_module.recovery_scope(control, "RESTORE_ALL_TD_AFTER_FAILURE"):
                    rb_state, rb_diag = parent_module._rollback_td_all(
                        adapter, before, baseline_diag,
                        folder / "ROLLBACK_AFTER_TD_FAILURE", targeted_cfg)
            except Exception as rb_exc:
                parent_module.atomic_json(folder / "TD_FINECDF_BLOCK_RESULT.json", {
                    "status": "ROLLBACK_FAILED_MANUAL_REOPEN_REQUIRED",
                    "td_realization_complete": False,
                    "next_generation_permitted": False,
                    "error": str(exc), "traceback": traceback.format_exc(),
                    "rollback_error": str(rb_exc),
                })
                raise SupplyContractError(
                    "V24916_FINECDF_ROLLBACK_FAILED_MANUAL_REOPEN") from rb_exc
            parent_module.atomic_json(folder / "TD_FINECDF_BLOCK_RESULT.json", {
                "status": "FAILED_BUT_ROLLBACK_VERIFIED",
                "td_realization_complete": False,
                "next_generation_permitted": False,
                "error": str(exc), "traceback": traceback.format_exc(),
            })
            raise

    parent_module._finecdf_td_once_impl = _finecdf_td_once_impl
    return {
        "installed": True,
        "generation_controller_changed": False,
        "td_dispatch_changed": True,
        "acceptance_changed": False,
        "run_finecdf_inner": "r1_15a2_finecdf_bridge_v24916.run_finecdf_inner",
    }


__all__ = ["install"]

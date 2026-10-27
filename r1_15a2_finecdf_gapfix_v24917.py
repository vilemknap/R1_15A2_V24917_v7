# -*- coding: utf-8 -*-
"""V24917 fix: FineCDF dynamic realization reads the assignment gap too late.

Defect (V24916, live run RUN_20261025_030431, cycle 5, first TD evaluation):
``NoDirectMatrixWriteTDAdapter._execute_dynamic_realization`` executes the
TD -> assignment -> skim plan inside ``activate_operation_plan`` but calls
``outer_adapter.gap()`` AFTER the context restored the isolated TD-only flags.
The PrT quality list of operation 20 is only readable while that operation
is ACTIVE, so the read failed with QUALITY_OPERATION_NOT_ACTIVE_PRT.

Fix: identical method, with the gap read (and its evidence) taken inside the
active plan, right after Procedures.Execute().  Installed in memory on the
class; the sealed V24916 file is unchanged.
"""
from __future__ import annotations

import r1_15a2_finecdf_bridge_v24916 as bridge
import r1_15a2_runtime_v1 as rt
from r1_15a2_supply import canonical_hash

RELEASE = "R1_15A2_V24917_FINECDF_GAP_INSIDE_PLAN_FIX_V1_20261025"


def _execute_dynamic_realization(self):
    plan = self._dynamic_realization_plan()
    if plan is None:
        return None
    self.dynamic_eval_index += 1
    folder = self.root / "DYNAMIC_ASSIGNMENT_SKIMS" / ("EVAL_%03d" % self.dynamic_eval_index)
    folder.mkdir(parents=True, exist_ok=True)
    rt.write_json(folder / "DYNAMIC_REALIZATION_PLAN.json", plan)
    rm = getattr(self.outer_adapter, "readback_manager", None)
    if rm is not None:
        rm.mark_assignment_started(reason="FINECDF_DYNAMIC_TD_ASSIGNMENT_SKIM", procedure_plan=plan)
    try:
        with bridge.perf1.activate_operation_plan(self.v, plan) as active_plan:
            rt.write_json(folder / "DYNAMIC_REALIZATION_PLAN_ACTIVE.json", active_plan)
            rt.execute_procseq(self.v, folder)
            gap = self.outer_adapter.gap()        # V24917: while operation 20 is ACTIVE
    except BaseException as exc:
        if rm is not None:
            rm.mark_assignment_failed(str(exc))
        raise
    if rm is not None:
        rm.mark_assignment_completed({
            "gap": gap,
            "gap_evidence": getattr(self.outer_adapter, "last_gap_evidence", None),
            "block": "TD_FINECDF_DYNAMIC_ASSIGNMENT_SKIM",
            "supply_only": False,
            "procedure_plan": plan,
        })
    token = canonical_hash({
        "dynamic_eval_index": self.dynamic_eval_index,
        "abc": self.read_abc(),
        "gap": float(gap),
        "assignment_epoch": int(getattr(rm, "assignment_epoch", self.dynamic_eval_index) or self.dynamic_eval_index),
    })
    epoch = self.outer_adapter.v24916_dynamic_skims.capture_after_execution(
        folder, token, plan["dynamic_skim_operation_positions"],
        self.outer_adapter._live_generation_matrices())
    self.dynamic_skim_epoch = epoch
    rt.write_json(folder / "DYNAMIC_FINECDF_BINDING.json", {
        "passes": True,
        "gap": float(gap),
        "gap_read_inside_active_plan": True,
        "skim_epoch": int(epoch.epoch),
        "skim_epoch_hash": epoch.epoch_hash,
        "assignment_epoch": int(epoch.assignment_epoch),
        "static_r1_osrm_dist_km_used_for_objective": False,
    })
    return epoch


def install():
    cls = bridge.NoDirectMatrixWriteTDAdapter
    if getattr(cls._execute_dynamic_realization, "__r1_v24917__", False):
        return {"installed": True, "already": True}
    _execute_dynamic_realization.__r1_v24917__ = True
    cls._execute_dynamic_realization = _execute_dynamic_realization
    return {"installed": True, "release": RELEASE}


__all__ = ["RELEASE", "install"]

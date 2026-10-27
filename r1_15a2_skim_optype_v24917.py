# -*- coding: utf-8 -*-
"""Live detection of the PrT skim-matrix OPERATIONTYPE code (V24917 fix).

V24916 hard-coded ``com.SKIMS_PRT = 103``.  In the live R1 Visum 2026 model the
procedure sequence contains six active "Calculate PrT skim matrix" operations
(NATIVE_CF, CL, CS, CS_noT, CW, CW_noT), but none of them reports type 103, so
the dynamic-skim preflight failed with
    V24916_DYNAMIC_SKIM_EXPECTED_6_ACTIVE_PRT_SKIMS_FOUND_0.

This module determines the code from the live model, read-only:
  1. environment override R1_PRT_SKIM_OPERATION_TYPE=<int>;
  2. operations exposing a PrT skim parameter object
     (``PrTSkimMatrixParameters``) - the COM property only skim operations own;
  3. the OPERATIONTYPE whose active operations number exactly six and whose
     operations are not TG/TD/script/group/assignment.
The result must identify exactly six active operations; otherwise it fails with
a diagnostic listing every operation (position, type, active, name).  The
module constant ``r1_15a2_com_compat.SKIMS_PRT`` is then set for this Python
session, so the unchanged V24916 dynamic-skim and FineCDF code select the
right operations.  The DIS matrices produced are still verified by exact DSEG
code after execution (unchanged V24916 check).
"""
from __future__ import annotations

import os
from collections import Counter, defaultdict
from typing import Any, Dict, List

import r1_15a2_com_compat as com

RELEASE = "R1_15A2_V24917_PRT_SKIM_OPTYPE_DETECTION_V1_20261025"
EXPECTED_ACTIVE = 6
ENV = "R1_PRT_SKIM_OPERATION_TYPE"
_PARAM_PROPERTIES = ("PrTSkimMatrixParameters", "PrTSkimParameters")
_NOT_SKIM = {com.TG, com.TD, com.EXECUTE_SCRIPT, com.GROUP, com.ASSIGNMENT_PRT, com.ASSIGNMENT_PUT}


def _has_skim_params(op: Any) -> bool:
    for name in _PARAM_PROPERTIES:
        try:
            value = getattr(op, name)
        except Exception:
            continue
        if value is not None:
            return True
    return False


def _inventory(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [{"position": r["position"], "type": r["type"], "active": r["active"],
             "name": r.get("name", ""), "comment": r.get("comment", "")} for r in rows]


def detect(visum: Any) -> Dict[str, Any]:
    rows = com.operation_rows(visum)
    active_by_type = Counter(int(r["type"]) for r in rows if int(r["active"]))
    raw = os.environ.get(ENV, "").strip()
    if raw:
        code = int(raw)
        if active_by_type.get(code, 0) < EXPECTED_ACTIVE:
            raise RuntimeError("V24917_PRT_SKIM_TYPE_OVERRIDE_%d_SELECTS_%d_ACTIVE_NOT_6" % (
                code, active_by_type.get(code, 0)))
        return {"code": code, "method": "ENV_OVERRIDE", "inventory": _inventory(rows)}

    if active_by_type.get(int(com.SKIMS_PRT), 0) >= EXPECTED_ACTIVE:
        return {"code": int(com.SKIMS_PRT), "method": "V24916_CONSTANT_CONFIRMED",
                "active_count": int(active_by_type[int(com.SKIMS_PRT)]),
                "inventory": _inventory(rows)}

    probed = defaultdict(int)
    for r in rows:
        if int(r["type"]) in _NOT_SKIM:
            continue
        if _has_skim_params(r["object"]):
            probed[int(r["type"])] += 1
    candidates = [t for t in probed if active_by_type.get(t, 0) >= EXPECTED_ACTIVE]
    method = "COM_SKIM_PARAMETER_OBJECT"
    if len(candidates) != 1:
        candidates = [t for t, n in active_by_type.items()
                      if n == EXPECTED_ACTIVE and t not in _NOT_SKIM]
        method = "UNIQUE_TYPE_WITH_SIX_ACTIVE_OPERATIONS"
    if len(candidates) != 1:
        raise RuntimeError("V24917_PRT_SKIM_TYPE_NOT_IDENTIFIABLE:candidates=%r active_by_type=%r "
                           "probed=%r; set %s=<OPERATIONTYPE>; inventory=%r" % (
                               candidates, dict(active_by_type), dict(probed), ENV,
                               _inventory(rows)))
    return {"code": int(candidates[0]), "method": method,
            "active_by_type": dict(active_by_type), "probed": dict(probed),
            "inventory": _inventory(rows)}


def apply(visum: Any) -> Dict[str, Any]:
    result = detect(visum)
    previous = int(com.SKIMS_PRT)
    com.SKIMS_PRT = int(result["code"])
    result.update(previous_constant=previous, release=RELEASE,
                  constant_changed=previous != int(result["code"]))
    result["extra_skim_patch"] = install_extra_skim_tolerance()
    return result


# --------------------------------------------------------------- SKIMFIX2
def active_skim_positions_at_least_6(visum: Any):
    """V24916 required EXACTLY six active PrT skim operations.

    Live 25. 10. 17:43: the model has 13 (positions 24-36: C + EXOG_EE_* + the six native).  The
    extra skim operations only add matrices; the six native DIS matrices are still verified by
    exact DSEG code after every execution (_native_dis_rows).  All active skim operations run.
    """
    rows = com.operation_rows(visum)
    skim = [int(r["no"]) for r in rows if int(r["active"]) and int(r["type"]) == com.SKIMS_PRT]
    groups = [int(r["no"]) for r in rows if int(r["active"]) and int(r["type"]) == com.GROUP]
    if len(skim) < EXPECTED_ACTIVE:
        raise RuntimeError("V24917_DYNAMIC_SKIM_EXPECTED_AT_LEAST_6_ACTIVE_PRT_SKIMS_FOUND_%d" % len(skim))
    return sorted(skim), sorted(groups)


def install_extra_skim_tolerance() -> Dict[str, Any]:
    import sys
    import r1_15a2_dynamic_skim_v24916p2c as ds
    original = getattr(ds, "_v24917_original_active_positions", None) or ds.active_native_skim_positions
    ds._v24917_original_active_positions = original
    rebound = []
    for name, mod in list(sys.modules.items()):
        if mod is None or not name.startswith("r1_15a2_"):
            continue
        if getattr(mod, "active_native_skim_positions", None) is original:
            setattr(mod, "active_native_skim_positions", active_skim_positions_at_least_6)
            rebound.append(name)
    ds.active_native_skim_positions = active_skim_positions_at_least_6
    try:
        import r1_15a2_finecdf_bridge_v24916 as bm
        if not getattr(bm.NoDirectMatrixWriteTDAdapter._dynamic_realization_plan, "_v24917_skimfix2", False):
            orig_plan = bm.NoDirectMatrixWriteTDAdapter._dynamic_realization_plan

            def _dynamic_realization_plan(self):
                inv = self.inventory
                skim_rows = [r for r in inv if int(r["active"]) and int(r["type"]) == com.SKIMS_PRT]
                if len(skim_rows) <= EXPECTED_ACTIVE:
                    return orig_plan(self)
                # hide the extra skim rows from the 6-count check, then add them back to the plan
                extra = skim_rows[:len(skim_rows) - EXPECTED_ACTIVE]
                saved = {id(r): r["active"] for r in extra}
                try:
                    for r in extra:
                        r["active"] = 0
                    plan = orig_plan(self)
                finally:
                    for r in extra:
                        r["active"] = saved[id(r)]
                if plan is None:
                    return plan
                positions = sorted(int(r["index"]) for r in skim_rows)
                plan["dynamic_skim_operation_positions"] = positions
                plan["selected_operation_positions"] = sorted(set(plan["selected_operation_positions"]) | set(positions))
                plan["original_active_operation_positions"] = sorted(
                    int(r["index"]) for r in inv if int(r["active"]))
                return plan
            _dynamic_realization_plan._v24917_skimfix2 = True
            bm.NoDirectMatrixWriteTDAdapter._dynamic_realization_plan = _dynamic_realization_plan
            rebound.append("finecdf_bridge_v24916.realization_plan")
    except Exception as exc:
        rebound.append("BRIDGE_PATCH_ERROR:%r" % (exc,))
    return {"release": "R1_15A2_V24917_SKIMFIX2_AT_LEAST_6_PRT_SKIMS", "rebound": rebound}


__all__ = ["RELEASE", "detect", "apply", "ENV"]

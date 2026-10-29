"""Exact assignment authority for R1 15A2 V2.3.9 safety gates.

The final full-network PrT evaluation assignment is operation position 20 only.
Operations 17-19 are verified as known partial scopes, but are not selected for
SUPPLY trial assignment because operation 20 already covers the complete 14-DSeg
scope used by the calibration objective and GAP readback.
"""
from __future__ import annotations
import re

import r1_15a2_com_compat as com
import r1_15a2_core as core
from r1_15a2_supply import SupplyContractError

TYPE_PRT_ASSIGNMENT = 101
EXPECTED = {
    17: frozenset(("LNV", "NV")),
    18: frozenset(("NATIVE_CF", "NATIVE_CL")),
    19: frozenset(("NATIVE_CS", "NATIVE_CS_NOT", "NATIVE_CW", "NATIVE_CW_NOT")),
    20: frozenset((
        "EXOG_EE_CF", "EXOG_EE_CL", "EXOG_EE_CS", "EXOG_EE_CS_NOT",
        "EXOG_EE_CW", "EXOG_EE_CW_NOT", "LNV", "NATIVE_CF", "NATIVE_CL",
        "NATIVE_CS", "NATIVE_CS_NOT", "NATIVE_CW", "NATIVE_CW_NOT", "NV",
    )),
}


def _tokens(value):
    if not isinstance(value, str) or not value.strip():
        raise SupplyContractError("EMPTY_ASSIGNMENT_DSEGSET")
    raw = [x.strip("\"' ") for x in re.split(r"[,;{}\s]+", value) if x.strip("\"' ")]
    norm = [core.norm_code(x) for x in raw]
    if len(norm) != len(set(norm)):
        raise SupplyContractError("DUPLICATE_ASSIGNMENT_DSEG_TOKEN")
    return frozenset(norm)


def audit_assignment_scope(visum):
    rows = com.operation_rows(visum)
    by_no = {int(r["no"]): r for r in rows}
    details = []
    failures = []
    for no in (17, 18, 19, 20):
        row = by_no.get(no)
        out = {"no": no, "expected_type": TYPE_PRT_ASSIGNMENT,
               "expected_dsegs": sorted(EXPECTED[no])}
        if row is None:
            out["status"] = "MISSING"
            failures.append("OP_%d_MISSING" % no)
            details.append(out)
            continue
        out.update(type=int(row["type"]), active=int(row["active"]),
                   comment=row.get("comment", ""), name=row.get("name", ""))
        if int(row["type"]) != TYPE_PRT_ASSIGNMENT:
            out["status"] = "TYPE_MISMATCH"
            failures.append("OP_%d_TYPE" % no)
            details.append(out)
            continue
        # OP20 is the unique active 14-DSeg final GAP/assignment authority.
        # OP17..19 are optional, *partial* prerequisites; the live 09C source
        # legitimately leaves them inactive. Still verify their type and exact
        # DSEGSET in either state: inactivity is NOT permission for scope drift.
        if not row["active"] and no == 20:
            out["status"] = "INACTIVE_FINAL"
            failures.append("OP_20_INACTIVE")
            details.append(out)
            continue
        try:
            params = com.object_property(row["object"], "PrTAssignmentParameters")
            raw = params.AttValue("DSEGSET")
            live = _tokens(raw)
            out["live_dsegset_raw"] = raw
            out["live_dsegs"] = sorted(live)
            if live != EXPECTED[no]:
                out["status"] = "DSEGSET_MISMATCH"
                out["missing"] = sorted(EXPECTED[no] - live)
                out["extra"] = sorted(live - EXPECTED[no])
                failures.append("OP_%d_DSEGSET" % no)
            else:
                out["status"] = "PASS" if row["active"] else "PASS_INACTIVE_PARTIAL"
        except Exception as exc:
            out["status"] = "UNREADABLE"
            out["error"] = str(exc)
            failures.append("OP_%d_UNREADABLE" % no)
        details.append(out)
    selected = [20] if not failures else []
    return {
        "schema": "R1_15A2_ASSIGNMENT_SCOPE_AUTHORITY_V239",
        "passes": not failures,
        "failures": failures,
        "verified_operations": details,
        "selected_trial_assignment_operations": selected,
        "selection_reason": (
            "OP20_IS_THE_FINAL_JOINT_14_DSEG_PRT_ASSIGNMENT_AND_GAP_SCOPE;_OP17_19_ARE_PARTIAL_SCOPES"
        ),
        "gap_operation_no": 20,
        "required_full_scope": sorted(EXPECTED[20]),
    }


def config_rule_for_op20():
    return {
        "no": 20,
        "operation_type": TYPE_PRT_ASSIGNMENT,
        "dseg_object_path": ["PrTAssignmentParameters"],
        "dseg_attribute": "DSEGSET",
        "expected_dsegs": sorted(EXPECTED[20]),
    }

# -*- coding: utf-8 -*-
"""V24916 compatibility for one active native TD operation with 16 or 17 strata.

The approved source Procedure Sequence may contain either all historical 17 R1
strata, or the 16 mutable/native strata with 4_FOREIGN handled separately.
FOREIGN matrix 9116 remains frozen and hash-guarded; its gravity parameters must
remain independently readable.  Dynamic assignment skims and all V24916 guards
are preserved.
"""
from __future__ import annotations

from pathlib import Path
import hashlib
import inspect
import math
from typing import Any, Dict

import r1_15a2_finecdf_bridge_v24916 as bridge
import r1_15a2_runtime_v1 as rt
from r1_15a2_supply import SupplyContractError, number

RELEASE = "R1_15A2_V24916_TD09C_16OR17_NATIVE_SCOPE_COMPAT_V1_20261023"
PARENT_INIT_SHA256 = "d31f106438c58e61dc3cd2f2ba18183570dee8c0885c6b52d55eff2b88a22165"
_ACTIVE = False
_PARENT_INIT = bridge.NoDirectMatrixWriteTDAdapter.__init__

APPROVED_NATIVE_CODES = frozenset(
    (
        "1_WORK_E_C",
        "1_WORK_E_noC",
        "1_WORK_noE_C",
        "1_WORK_noE_noC",
        "1_WORK_stud",
        "2_SERV_E_C",
        "2_SERV_E_noC",
        "2_SERV_noE_C",
        "2_SERV_noE_noC",
        "2_SERV_stud",
        "3_LONG_E_C",
        "3_LONG_E_noC",
        "3_LONG_noE_C",
        "3_LONG_noE_noC",
        "3_LONG_stud",
        "5_SCHOOL",
    )
)


def policy_payload() -> Dict[str, Any]:
    return {
        "status": "ACTIVE",
        "release": RELEASE,
        "allowed_source_scopes": ["FULL17", "NATIVE16_FOREIGN_SEPARATE"],
        "foreign_dstratum": "4_FOREIGN",
        "foreign_matrix": 9116,
        "foreign_native_td_excluded_during_inner": True,
        "foreign_matrix_hash_guarded": True,
        "foreign_abc_must_be_independently_readable": True,
        "dynamic_assignment_skims_preserved": True,
        "calibration_math_changed": False,
        "assignment_method_changed": False,
    }


def _codes(raw: Any) -> set[str]:
    bits = [str(s).strip() for s in str(raw).split(",") if str(s).strip()]
    if len(bits) != len(set(bits)):
        raise SupplyContractError("V24916_TD09C_DUPLICATE_DSTRAT_CODE")
    return set(bits)


def _compatible_init(
    self,
    visum,
    ref,
    root,
    control=None,
    telemetry=None,
    outer_adapter=None,
):
    # V24916 constructor prefix, unchanged except for the approved 16/17 scope.
    self.v = visum
    self.telemetry = telemetry
    self.ref = ref
    self.root = Path(root)
    self.control = control
    self.outer_adapter = outer_adapter
    self.dynamic_skim_enabled = bool(
        outer_adapter is not None
        and getattr(outer_adapter, "v24916_dynamic_skims", None) is not None
    )
    self.dynamic_skim_epoch = None
    self.dynamic_eval_index = 0
    self.n = int(ref.CONFIG["expected_zone_count"])
    self.ops = rt.get_all(self.v.Procedures.Operations)
    self.inventory = []
    self.controls_changed = False
    self.td_index = None
    self.td = None
    self.original_dset = None

    expected_all = {r["dstrat_code"] for r in ref.COMPONENTS}
    expected_native = {
        r["dstrat_code"] for r in ref.COMPONENTS if int(r["matrix_no"]) != 9116
    }
    if (
        len(expected_all) != 17
        or len(expected_native) != 16
        or expected_all - expected_native != {"4_FOREIGN"}
    ):
        raise SupplyContractError(
            "V24916_TD09C_REFERENCE_STRATA_NOT_APPROVED_17_WITH_FROZEN_FOREIGN"
        )

    candidates = []
    read_failures = []
    for i, op in enumerate(self.ops, 1):
        typ = int(number(rt.att(op, "OPERATIONTYPE", -1)))
        active = bool(number(rt.att(op, "ACTIVE", 0)))
        row = {
            "index": i,
            "type": typ,
            "active": int(active),
            "comment": str(rt.att(op, "COMMENT", "")),
            "is_group": typ == int(ref.CONFIG["td_group_type"]),
        }
        self.inventory.append(row)
        if typ != 46:
            continue
        try:
            td = op.TripDistributionParameters
            raw = str(td.AttValue("DSTRATSET"))
            codes = _codes(raw)
        except Exception as exc:
            row["td09c_error"] = repr(exc)
            read_failures.append("ROW_%d:%r" % (i, exc))
            continue
        row["td09c_stratum_count"] = len(codes)
        row["td09c_dstratset"] = raw
        if codes in (expected_all, expected_native):
            scope = "FULL17" if codes == expected_all else "NATIVE16_FOREIGN_SEPARATE"
            row["td09c_match"] = scope
            candidates.append((i, td, raw, scope))
        else:
            row["td09c_match"] = "MISMATCH"
            row["td09c_missing_from_native"] = ",".join(sorted(expected_native - codes))
            row["td09c_unexpected"] = ",".join(sorted(codes - expected_all))

    ref.write_csv(self.root / "TD_PROCEDURE_INVENTORY.csv", self.inventory)
    if read_failures:
        raise SupplyContractError(
            "V24916_TD09C_DSTRATSET_READ_ERROR:" + ";".join(read_failures)
        )
    if len(candidates) != 1:
        summaries = [
            "%d:%s" % (r["index"], r.get("td09c_match", "UNREADABLE"))
            for r in self.inventory
            if r["type"] == 46
        ]
        raise SupplyContractError(
            "V24916_EXPECTED_ONE_APPROVED_NATIVE_16_OR_FULL_17_TD_OPERATION_FOUND_%d:%s"
            % (len(candidates), ",".join(summaries))
        )

    self.td_index, self.td, self.original_dset, self.td09c_scope = candidates[0]
    if not self.inventory[self.td_index - 1]["active"]:
        raise SupplyContractError("V242_R1_TD_OPERATION_INACTIVE")
    self.active_dset = ",".join(
        r["dstrat_code"] for r in ref.COMPONENTS if int(r["matrix_no"]) != 9116
    )
    self.td09c_contract = {
        "schema": "R1_15A2_V24916_TD09C_NATIVE_SCOPE_16_OR_FULL_17_COMPAT_V1",
        "selected_index": int(self.td_index),
        "source_scope": self.td09c_scope,
        "source_dstratset": self.original_dset,
        "inner_dstratset": self.active_dset,
        "foreign_dstratum": "4_FOREIGN",
        "foreign_matrix": 9116,
        "foreign_native_execution": False,
        "foreign_frozen_by_parameter_readback": True,
        "foreign_frozen_by_matrix_sha256": True,
        "native_mutable_strata_count": 16,
        "dynamic_skim_enabled": bool(self.dynamic_skim_enabled),
    }
    ref.write_json(self.root / "TD09C_NATIVE_SCOPE_CONTRACT.json", self.td09c_contract)

    # Exact V24916 constructor remainder.
    pairs = list(self.v.Net.Zones.GetMultiAttValues("NO"))
    self.zone_order = [int(number(v)) for _k, v in pairs]
    if len(self.zone_order) != self.n or len(set(self.zone_order)) != self.n:
        raise SupplyContractError("V242_INVALID_ZONE_ORDER")
    if set(self.zone_order) != set(range(1, self.n + 1)):
        raise SupplyContractError("V242_EXPECTED_ZONE_NO_1_681")

    self.generation_guard = self._capture_generation_guard()
    self.addval_guard = self._capture_addval_guard()
    self.protected = {no: self.read_matrix(no) for no in (9001, 9697, 9116)}
    self.protected_hashes = {n: ref.sha_array(a) for n, a in self.protected.items()}
    if float(self.protected[9697].min()) < 0:
        raise SupplyContractError("V242_NEGATIVE_DISTANCE_MATRIX")
    if ref.CONFIG.get("require_2022_patch_preflight", True):
        ref.verify_2022_osrm_amdy_patched_inputs(
            self.protected,
            self.zone_order,
            self.root / "PATCHED_INPUT_PREFLIGHT.json",
        )
    try:
        self.entry_abc = self.read_abc()
    except Exception as exc:
        if self.td09c_scope == "NATIVE16_FOREIGN_SEPARATE":
            raise SupplyContractError(
                "V24916_TD09C_16_ONLY_FOREIGN_ABC_READ_FAILED:"
                + repr(exc)
                + "; 4_FOREIGN parameter getter must remain independently readable"
            ) from exc
        raise
    self.initial_matrices = self.read_outputs()


_compatible_init._v24916_td09c_compat = True  # type: ignore[attr-defined]
_compatible_init._v24916_td09c_parent = _PARENT_INIT  # type: ignore[attr-defined]


def read_only_source_preflight(visum) -> Dict[str, Any]:
    """Read-only DSTRATSET and frozen FOREIGN authority check before TG writes."""
    found = []
    for i, op in enumerate(rt.get_all(visum.Procedures.Operations), 1):
        typ = int(number(rt.att(op, "OPERATIONTYPE", -1)))
        if typ != 46 or not bool(number(rt.att(op, "ACTIVE", 0))):
            continue
        td = op.TripDistributionParameters
        raw = str(td.AttValue("DSTRATSET"))
        codes = _codes(raw)
        if codes in (APPROVED_NATIVE_CODES, APPROVED_NATIVE_CODES | {"4_FOREIGN"}):
            found.append((i, td, codes, raw))
    if len(found) != 1:
        raise SupplyContractError(
            "V24916_TD09C_SOURCE_PREFLIGHT_EXPECTED_1_APPROVED_OPERATION_FOUND_%d"
            % len(found)
        )
    index, td, codes, raw = found[0]
    try:
        gravity = td.TripDistributionDStratParameters("4_FOREIGN").GravitationParameters
        values = {}
        for param in ("PARA_A", "PARA_B", "PARA_C"):
            value = float(gravity.AttValue(param))
            if not math.isfinite(value):
                raise ValueError("NONFINITE_" + param)
            values[param] = value
    except Exception as exc:
        raise SupplyContractError(
            "V24916_TD09C_FOREIGN_ABC_READONLY_PREFLIGHT_FAILED:" + repr(exc)
        ) from exc
    return {
        "status": "PASS",
        "selected_operation_index": index,
        "scope": "NATIVE16_FOREIGN_SEPARATE" if len(codes) == 16 else "FULL17",
        "source_dstratset": raw,
        "source_strata_count": len(codes),
        "foreign_abc_readable": True,
        "foreign_abc": values,
        "model_modified": False,
    }


def activate() -> Dict[str, Any]:
    global _ACTIVE
    current = bridge.NoDirectMatrixWriteTDAdapter.__init__
    if getattr(current, "_v24916_td09c_compat", False):
        _ACTIVE = True
        return {
            "active": True,
            "release": RELEASE,
            "idempotent": True,
            "parent_init_sha256": PARENT_INIT_SHA256,
            **policy_payload(),
        }
    actual = hashlib.sha256(inspect.getsource(current).encode("utf-8")).hexdigest()
    if actual != PARENT_INIT_SHA256:
        raise RuntimeError("V24916_TD09C_PARENT_BRIDGE_SOURCE_CHANGED:" + actual)
    bridge.NoDirectMatrixWriteTDAdapter.__init__ = _compatible_init
    _ACTIVE = True
    return {
        "active": True,
        "release": RELEASE,
        "idempotent": False,
        "parent_init_sha256": actual,
        **policy_payload(),
    }


__all__ = [
    "RELEASE",
    "PARENT_INIT_SHA256",
    "APPROVED_NATIVE_CODES",
    "activate",
    "read_only_source_preflight",
    "policy_payload",
    "_compatible_init",
    "_codes",
]

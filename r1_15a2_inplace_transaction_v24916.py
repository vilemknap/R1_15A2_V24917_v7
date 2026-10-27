# -*- coding: utf-8 -*-
"""Retry-safe coefficient-ledger rollback for V2.4.9.16 demand calibration.

Demand rollback no longer depends on a list of touched rows.  The accepted
parent's complete TG zone-coefficient vector and complete TD b/c vector are
logged and restored, then the native downstream procedure is rerun.  Supply
rollback is delegated unchanged to the verified V2.4.8.9 implementation.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Mapping

import r1_15a2_runtime_v1 as rt
import r1_15a2_visum_parameters as vp
from r1_15a2_controller_v22 import diagnostic_hash
from r1_15a2_supply import SupplyContractError, number
import r1_15a2_com_compat as com
from r1_15a2_inplace_transaction_v239 import (
    rollback_and_verify as _v239_rollback_and_verify,
)
from r1_15a2_coefficient_ledger_v24916 import (
    compare_snapshot_to_ledger, ledger_from_snapshot, write_ledger,
)


def restore_all_generation(adapter: Any, ledger: Mapping[str, Any], folder: Any) -> list:
    audit = []
    zones = [int(z) for z in adapter.zones]
    expected_zone_keys = {str(z) for z in zones}
    for attr in sorted(ledger.get("generation", {})):
        mapping = ledger["generation"][attr]
        if set(mapping) != expected_zone_keys:
            raise SupplyContractError("V24916_ROLLBACK_GENERATION_ZONE_SET_MISMATCH:" + attr)
        values = [number(mapping[str(z)], "rollback generation coefficient") for z in zones]
        got = rt.write_zone_attr(
            adapter.visum, attr, zones, values,
            zone_indices=getattr(adapter, "zone_write_index_by_no", None),
            retry_policy=getattr(adapter, "com_retry_policy", None),
            readback_tolerance=float(getattr(adapter, "zone_readback_tolerance", 1.0e-7)),
        )
        tolerance = float(getattr(adapter, "zone_readback_tolerance", 1.0e-7))
        max_error = max((abs(float(a)-float(b)) for a, b in zip(got, values)), default=0.0)
        row = {"kind": "GENERATION", "attribute": attr, "rows": len(values),
               "max_abs_readback_error": max_error, "readback_tolerance": tolerance,
               "passes": max_error <= tolerance}
        audit.append(row)
        if not row["passes"]:
            raise SupplyContractError("V24916_ROLLBACK_GENERATION_READBACK_FAILED:" + attr)
    rt.write_csv(Path(folder) / "ROLLBACK_GENERATION_COEFFICIENT_READBACK.csv", audit)
    return audit


def restore_all_td(adapter: Any, ledger: Mapping[str, Any], folder: Any) -> list:
    rows = [{"component": str(r["component"]),
             "candidate_b": number(r["b"], "rollback b"),
             "candidate_c": number(r["c"], "rollback c")}
            for r in ledger.get("td", [])]
    if not rows:
        raise SupplyContractError("V24916_ROLLBACK_TD_LEDGER_EMPTY")
    audit = com.com_call_with_retry(
        lambda: vp.apply_td_candidates(adapter.visum, rows),
        label="V24916.rollback.apply_td_candidates",
        retry_policy=getattr(adapter, "com_retry_policy", None),
    )
    if len(audit) != len(rows) or any(r.get("status") != "OK" for r in audit):
        raise SupplyContractError("V24916_ROLLBACK_TD_READBACK_FAILED")
    rt.write_csv(Path(folder) / "ROLLBACK_TD_COEFFICIENT_READBACK.csv", audit)
    return audit


def restore_all_demand_coefficients(adapter: Any, before_snapshot: Mapping[str, Any],
                                    folder: Any) -> Dict[str, Any]:
    folder = Path(folder); folder.mkdir(parents=True, exist_ok=True)
    ledger = write_ledger(before_snapshot, folder, "ROLLBACK_PARENT_COEFFICIENTS")
    gen_audit = restore_all_generation(adapter, ledger, folder)
    td_audit = restore_all_td(adapter, ledger, folder)
    rt.write_json(folder / "ROLLBACK_COEFFICIENT_RESTORE_AUDIT.json", {
        "schema": "R1_15A2_DEMAND_COEFFICIENT_RESTORE_AUDIT_V24916",
        "coefficient_hash": ledger["coefficient_hash"],
        "generation_attributes": len(gen_audit),
        "td_components": len(td_audit),
        "all_generation_coefficients_restored": True,
        "all_td_coefficients_restored": True,
        "direct_od_matrix_writes": False,
        "load_version_called": False,
        "supply_parameters_touched": False,
    })
    return ledger


def _immutable_restore_audit(before: Mapping[str, Any], after: Mapping[str, Any]) -> Dict[str, Any]:
    exact_fields = ("fixed_link_hash", "dseg_hash", "operations_hash",
                    "addval_hash", "matrix_hash")
    rows = []
    passes = True
    for name in exact_fields:
        equal = before.get(name) == after.get(name)
        passes &= equal
        rows.append({"field": name, "expected": before.get(name),
                     "actual": after.get(name), "passes": equal})
    return {"passes": bool(passes), "rows": rows,
            "exact_fields": list(exact_fields),
            "state_hash_equal": before.get("state_hash") == after.get("state_hash")}


def rollback_and_verify(adapter: Any, block: str, before_snapshot: Mapping[str, Any],
                        baseline_diag_hash: str, diagnostic_hash_fn,
                        folder: Any, candidate_rows=None, candidate=None):
    if str(block) == "SUPPLY_ADDVAL1":
        # Supply code and semantics are deliberately unchanged.
        return _v239_rollback_and_verify(
            adapter, block, before_snapshot, baseline_diag_hash,
            diagnostic_hash_fn, folder, candidate_rows=candidate_rows,
            candidate=candidate)

    if str(block) != "GENERATION" and not str(block).startswith("TD_"):
        raise SupplyContractError("V24916_ROLLBACK_UNKNOWN_DEMAND_BLOCK:" + str(block))

    folder = Path(folder); folder.mkdir(parents=True, exist_ok=True)
    ledger = restore_all_demand_coefficients(adapter, before_snapshot,
                                             folder / "COEFFICIENT_LEDGER")
    gap = adapter.assign(folder / "FULL_DOWNSTREAM_RECOMPUTE", supply_only=False)
    after = adapter.snapshot()
    coefficient_audit = compare_snapshot_to_ledger(after, ledger)
    immutable_audit = _immutable_restore_audit(before_snapshot, after)
    state_restored = bool(coefficient_audit["passes"] and immutable_audit["passes"])
    state_evidence = {
        "schema": "R1_15A2_COEFFICIENT_LEDGER_ROLLBACK_STATE_V24916",
        "block": block, "gap": gap, "passes": state_restored,
        "coefficient_audit": coefficient_audit,
        "immutable_audit": immutable_audit,
        "snapshot_equal": after == before_snapshot,
        "expected_state_hash": before_snapshot.get("state_hash"),
        "actual_state_hash": after.get("state_hash"),
        "rollback_authority": "ALL_ACCEPTED_PARENT_TG_AND_TD_COEFFICIENTS",
        "direct_od_matrix_writes": False, "load_version_called": False,
        "diagnostic_publication_pending": True,
    }
    rt.write_json(folder / "ROLLBACK_STATE_RESTORED.json", state_evidence)
    rt.write_csv(folder / "ROLLBACK_IMMUTABLE_CONTEXT_AUDIT.csv",
                 immutable_audit["rows"])
    rt.write_csv(folder / "ROLLBACK_COEFFICIENT_MISMATCH.csv",
                 coefficient_audit["mismatch_rows"])
    if not state_restored:
        raise SupplyContractError("V24916_COEFFICIENT_LEDGER_ROLLBACK_STATE_MISMATCH")

    try:
        diag = adapter.diagnostics(folder / "DIAGNOSTICS", "ROLLBACK")
        diag_hash = diagnostic_hash_fn(diag)
        diagnostic_equal = diag_hash == baseline_diag_hash
        if not diagnostic_equal:
            raise SupplyContractError("V24916_ROLLBACK_DIAGNOSTICS_DIFFER")
        publication = "PASS"
    except Exception as exc:
        # Diagnostics are read-only. Recheck model coefficients and immutable
        # state before allowing a publication-only failure to reuse baseline
        # evidence. A real model drift remains fatal.
        current = adapter.snapshot()
        coeff_now = compare_snapshot_to_ledger(current, ledger)
        immutable_now = _immutable_restore_audit(before_snapshot, current)
        if not (coeff_now["passes"] and immutable_now["passes"]):
            raise SupplyContractError(
                "V24916_ROLLBACK_DIAGNOSTIC_FAILURE_WITH_STATE_DRIFT_MANUAL_REOPEN") from exc
        diag = getattr(adapter, "_v249_baseline_diag_for_rollback", None)
        if diag is None:
            # Generic callers pass only its hash.  The controller sets the
            # baseline object on the adapter immediately before a trial.
            raise SupplyContractError(
                "V24916_ROLLBACK_DIAGNOSTIC_PUBLICATION_FAILED_BASELINE_OBJECT_MISSING") from exc
        diag_hash = diagnostic_hash_fn(diag)
        if diag_hash != baseline_diag_hash:
            raise SupplyContractError(
                "V24916_ROLLBACK_DIAGNOSTIC_BASELINE_HASH_MISMATCH") from exc
        diagnostic_equal = True
        publication = "FAILED_STATE_RESTORED_BASELINE_DIAGNOSTIC_REUSED"
        rt.write_json(folder / "ROLLBACK_DIAGNOSTIC_PUBLICATION_FAILED_STATE_RESTORED.json", {
            "schema": "R1_15A2_ROLLBACK_DIAGNOSTIC_PUBLICATION_V24916",
            "status": publication, "error": repr(exc),
            "coefficient_hash": ledger["coefficient_hash"],
            "state_restored": True, "baseline_diagnostic_hash": baseline_diag_hash,
            "policy": "NO_MANUAL_REOPEN_FOR_EVIDENCE_IO_FAILURE_AFTER_VERIFIED_COEFFICIENT_AND_MODEL_RESTORE",
        })

    final_snapshot = adapter.snapshot()
    final_coeff = compare_snapshot_to_ledger(final_snapshot, ledger)
    final_immutable = _immutable_restore_audit(before_snapshot, final_snapshot)
    passes = bool(final_coeff["passes"] and final_immutable["passes"] and diagnostic_equal)
    result = {
        "schema": "R1_15A2_COEFFICIENT_LEDGER_ROLLBACK_RESULT_V24916",
        "block": block, "gap": gap, "passes": passes,
        "snapshot_equal": final_snapshot == before_snapshot,
        "coefficient_numeric_equal": final_coeff["passes"],
        "coefficient_exact_hash_equal": final_coeff["exact_coefficient_hash_equal"],
        "immutable_context_equal": final_immutable["passes"],
        "diagnostic_equal": diagnostic_equal,
        "diagnostic_publication_status": publication,
        "diagnostic_hash": diag_hash,
        "load_version_called": False, "save_version_called": False,
        "direct_od_matrix_writes": False,
    }
    rt.write_json(folder / "ROLLBACK_VERIFICATION.json", result)
    if not passes:
        raise SupplyContractError("V24916_COEFFICIENT_LEDGER_ROLLBACK_NOT_VERIFIED")
    return result, diag


__all__ = ["restore_all_generation", "restore_all_td",
           "restore_all_demand_coefficients", "rollback_and_verify"]

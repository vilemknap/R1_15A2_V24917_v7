"""No-LoadVersion trial transaction helpers for R1 15A2 V2.3.9.

Rollback is parameter restoration followed by the same model recomputation that
produces assignment results. Direct OD matrix writes, SaveVersion and LoadVersion
are intentionally absent.
"""
from __future__ import annotations

from pathlib import Path
import json
import os

import r1_15a2_runtime_v1 as rt
import r1_15a2_visum_parameters as vp
from r1_15a2_supply import SupplyContractError, number, key_text


def atomic_json(path, value):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    t = p.with_name(p.name + ".tmp")
    with t.open("w", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=True, indent=2, allow_nan=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(t, p)


def restore_supply_parameters(adapter, before_snapshot, changes, folder=None):
    links = adapter.read_links()
    audit = []
    attr = adapter.cfg["supply"].get("link_attributes", {}).get("addval1", "ADDVAL1")
    for change in changes:
        key = tuple(int(x) for x in change["key"])
        expected = number(before_snapshot["addval1"][key_text(key)])
        if key not in links:
            raise SupplyContractError("ROLLBACK_SUPPLY_LINK_MISSING")
        obj = links[key]["object"]
        obj.SetAttValue(attr, expected)
        got = number(obj.AttValue(attr), "rollback ADDVAL1")
        row = {"key": list(key), "restored": expected, "readback": got,
               "passes": abs(got-expected) <= 1e-10}
        audit.append(row)
        if not row["passes"]:
            raise SupplyContractError("ROLLBACK_SUPPLY_READBACK_FAILED")
    if folder is not None:
        atomic_json(Path(folder) / "ROLLBACK_PARAMETER_READBACK.json", audit)
    return audit


def restore_generation_parameters(adapter, before_snapshot, candidate_rows, folder=None):
    attrs = sorted({str(r["attr"]) for r in candidate_rows})
    audit = []
    for attr in attrs:
        source = before_snapshot["generation_values"].get(attr)
        if source is None:
            raise SupplyContractError("ROLLBACK_GENERATION_ATTR_NOT_IN_SNAPSHOT:" + attr)
        values = [number(source[str(z)]) for z in adapter.zones]
        got = rt.write_zone_attr(
            adapter.visum, attr, adapter.zones, values,
            zone_indices=getattr(adapter, "zone_write_index_by_no", None),
            retry_policy=getattr(adapter, "com_retry_policy", None),
            readback_tolerance=getattr(adapter, "zone_readback_tolerance", 1.0e-7))
        max_err = max((abs(a-b) for a,b in zip(got,values)), default=0.0)
        audit.append({"attr": attr, "rows": len(values), "max_abs_readback_error": max_err,
                      "passes": max_err <= 1e-7})
        if max_err > 1e-7:
            raise SupplyContractError("ROLLBACK_GENERATION_READBACK_FAILED:" + attr)
    if folder is not None:
        atomic_json(Path(folder) / "ROLLBACK_PARAMETER_READBACK.json", audit)
    return audit


def restore_td_parameters(adapter, before_snapshot, candidate_rows, folder=None):
    by_comp = {r["component"]: r for r in before_snapshot["td_values"]}
    restore_rows = []
    for r in candidate_rows:
        comp = r["component"]
        if comp not in by_comp:
            raise SupplyContractError("ROLLBACK_TD_COMPONENT_NOT_IN_SNAPSHOT:" + str(comp))
        old = by_comp[comp]
        restore_rows.append({"component": comp,
                             "candidate_b": number(old["current_b"]),
                             "candidate_c": number(old["current_c"])})
    audit = vp.apply_td_candidates(adapter.visum, restore_rows)
    if not audit or any(x.get("status") != "OK" for x in audit):
        raise SupplyContractError("ROLLBACK_TD_READBACK_FAILED")
    if folder is not None:
        atomic_json(Path(folder) / "ROLLBACK_PARAMETER_READBACK.json", audit)
    return audit


def restore_parameters(adapter, block, before_snapshot, candidate_rows=None, candidate=None, folder=None):
    if block == "SUPPLY_ADDVAL1":
        changes = list((candidate or {}).get("changes", []))
        if not changes:
            raise SupplyContractError("ROLLBACK_SUPPLY_CHANGES_MISSING")
        return restore_supply_parameters(adapter, before_snapshot, changes, folder)
    if block == "GENERATION":
        return restore_generation_parameters(adapter, before_snapshot, list(candidate_rows or []), folder)
    if block.startswith("TD_"):
        return restore_td_parameters(adapter, before_snapshot, list(candidate_rows or []), folder)
    raise SupplyContractError("ROLLBACK_UNKNOWN_BLOCK:" + str(block))


def recompute_after_restore(adapter, block, folder):
    # Supply has unchanged demand; operation 20 is the exact final joint PrT assignment.
    # Demand blocks must regenerate demand and all downstream assignment results.
    return adapter.assign(folder, supply_only=(block == "SUPPLY_ADDVAL1"))


def rollback_and_verify(adapter, block, before_snapshot, baseline_diag_hash,
                        diagnostic_hash_fn, folder, candidate_rows=None, candidate=None):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    restore_parameters(adapter, block, before_snapshot, candidate_rows, candidate, folder)
    gap = recompute_after_restore(adapter, block, folder)
    after = adapter.snapshot()
    snapshot_equal = after == before_snapshot
    # Persist proof that the mutable model state has been restored BEFORE any
    # file-heavy diagnostics run.  A diagnostic I/O failure must not erase the
    # evidence that parameter restoration + recomputation already succeeded.
    atomic_json(folder / "ROLLBACK_STATE_RESTORED.json", {
        "block": block, "gap": gap, "snapshot_equal": bool(snapshot_equal),
        "load_version_called": False, "save_version_called": False,
        "direct_od_matrix_writes": False,
        "status": "STATE_RESTORED_PENDING_DIAGNOSTIC_VERIFICATION" if snapshot_equal else "STATE_RESTORE_MISMATCH",
    })
    if not snapshot_equal:
        raise SupplyContractError("INPLACE_ROLLBACK_SNAPSHOT_DIFFER")
    diag = adapter.diagnostics(folder, "ROLLBACK")
    diag_hash = diagnostic_hash_fn(diag)
    diagnostic_equal = diag_hash == baseline_diag_hash
    snapshot_equal = snapshot_equal and adapter.snapshot() == before_snapshot
    result = {"block": block, "gap": gap, "snapshot_equal": snapshot_equal,
              "diagnostic_equal": diagnostic_equal, "diagnostic_hash": diag_hash,
              "passes": bool(snapshot_equal and diagnostic_equal),
              "load_version_called": False, "save_version_called": False,
              "direct_od_matrix_writes": False}
    atomic_json(folder / "ROLLBACK_VERIFICATION.json", result)
    if not snapshot_equal:
        raise SupplyContractError("INPLACE_ROLLBACK_SNAPSHOT_DIFFER")
    if not diagnostic_equal:
        raise SupplyContractError("INPLACE_ROLLBACK_DIAGNOSTICS_DIFFER")
    return result, diag

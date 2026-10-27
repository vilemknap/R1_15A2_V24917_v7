# -*- coding: utf-8 -*-
"""Exact accepted-parent coefficient ledger for R1 15A2 V2.4.9.16.

The ledger is the rollback authority for demand calibration parameters only:
all zonal Trip Generation coefficients present in ``generation_values`` and all
Trip Distribution b/c parameters present in ``td_values``.  It never writes OD
matrices, links, VDFs or supply parameters.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import r1_15a2_runtime_io_hotfix_profile488 as runtime_io_hotfix
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence

from r1_15a2_supply import SupplyContractError, canonical_hash, number

SCHEMA = "R1_15A2_DEMAND_COEFFICIENT_LEDGER_V24916"


def _atomic_json(path: Path, payload: Any) -> None:
    runtime_io_hotfix.critical_atomic_json(path, payload)


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    runtime_io_hotfix.critical_runtime_write_csv(path, rows)

def ledger_from_snapshot(snapshot: Mapping[str, Any]) -> Dict[str, Any]:
    generation = snapshot.get("generation_values")
    td = snapshot.get("td_values")
    if not isinstance(generation, Mapping) or not isinstance(td, list):
        raise SupplyContractError("V24916_COEFFICIENT_LEDGER_SOURCE_INCOMPLETE")
    gen = {}
    rows = []
    for attr in sorted(generation):
        values = generation[attr]
        if not isinstance(values, Mapping):
            raise SupplyContractError("V24916_COEFFICIENT_LEDGER_GENERATION_NOT_MAPPING:" + str(attr))
        gen[str(attr)] = {}
        for zone in sorted(values, key=lambda z: int(z)):
            value = number(values[zone], "coefficient ledger generation")
            if not math.isfinite(value):
                raise SupplyContractError("V24916_COEFFICIENT_LEDGER_NONFINITE_GENERATION")
            gen[str(attr)][str(int(zone))] = value
            rows.append({"kind": "GENERATION", "attribute": str(attr),
                         "zone_no": int(zone), "component": "", "b": "", "c": "",
                         "value": value})
    td_rows = []
    seen_components = set()
    for raw in sorted(td, key=lambda r: str(r.get("component", ""))):
        component = str(raw.get("component", ""))
        if not component or component in seen_components:
            raise SupplyContractError("V24916_COEFFICIENT_LEDGER_TD_COMPONENT_IDENTITY")
        seen_components.add(component)
        b = number(raw.get("current_b"), "coefficient ledger b")
        c = number(raw.get("current_c"), "coefficient ledger c")
        if not (math.isfinite(b) and math.isfinite(c) and c < 0.0):
            raise SupplyContractError("V24916_COEFFICIENT_LEDGER_TD_DOMAIN:" + component)
        item = {"component": component, "b": b, "c": c,
                "status": str(raw.get("status", "OK"))}
        td_rows.append(item)
        rows.append({"kind": "TD", "attribute": "", "zone_no": "",
                     "component": component, "b": b, "c": c, "value": ""})
    body = {"generation": gen, "td": td_rows}
    digest = canonical_hash(body)
    return {
        "schema": SCHEMA,
        "source_state_hash": str(snapshot.get("state_hash", "")),
        "source_generation_hash": str(snapshot.get("generation_hash", "")),
        "source_td_hash": str(snapshot.get("td_hash", "")),
        "generation_attribute_count": len(gen),
        "generation_value_count": sum(len(v) for v in gen.values()),
        "td_component_count": len(td_rows),
        "coefficient_hash": digest,
        "generation": gen,
        "td": td_rows,
        "rows": rows,
    }


def write_ledger(snapshot: Mapping[str, Any], folder: Any,
                 stem: str = "ACCEPTED_PARENT_COEFFICIENTS") -> Dict[str, Any]:
    folder = Path(folder); folder.mkdir(parents=True, exist_ok=True)
    ledger = ledger_from_snapshot(snapshot)
    payload = dict(ledger)
    rows = payload.pop("rows")
    _atomic_json(folder / (stem + ".json"), payload)
    _write_csv(folder / (stem + ".csv"), rows)
    _atomic_json(folder / (stem + "_MANIFEST.json"), {
        "schema": "R1_15A2_DEMAND_COEFFICIENT_LEDGER_MANIFEST_V24916",
        "coefficient_hash": ledger["coefficient_hash"],
        "source_state_hash": ledger["source_state_hash"],
        "json": stem + ".json", "csv": stem + ".csv",
        "rollback_authority": "ALL_TG_ZONE_COEFFICIENTS_PLUS_ALL_TD_BC",
        "od_matrix_writes": False, "supply_parameter_writes": False,
    })
    return ledger


def compare_snapshot_to_ledger(snapshot: Mapping[str, Any], ledger: Mapping[str, Any],
                               atol: float = 1.0e-8,
                               rtol: float = 1.0e-10) -> Dict[str, Any]:
    current = ledger_from_snapshot(snapshot)
    rows = []
    passes = True
    expected_gen = ledger.get("generation", {})
    current_gen = current.get("generation", {})
    if set(expected_gen) != set(current_gen):
        passes = False
        rows.append({"kind": "GENERATION_SET", "passes": False,
                     "expected": sorted(expected_gen), "actual": sorted(current_gen)})
    for attr in sorted(set(expected_gen) | set(current_gen)):
        exp = expected_gen.get(attr, {})
        got = current_gen.get(attr, {})
        if set(exp) != set(got):
            passes = False
            rows.append({"kind": "GENERATION_ZONE_SET", "attribute": attr,
                         "passes": False, "expected_count": len(exp),
                         "actual_count": len(got)})
        for zone in sorted(set(exp) & set(got), key=int):
            a = float(exp[zone]); b = float(got[zone])
            tol = atol + rtol * max(abs(a), abs(b))
            ok = abs(a-b) <= tol
            passes &= ok
            if not ok:
                rows.append({"kind": "GENERATION", "attribute": attr,
                             "zone_no": int(zone), "expected": a, "actual": b,
                             "abs_error": abs(a-b), "tolerance": tol,
                             "passes": ok})
    exp_td = {str(r["component"]): r for r in ledger.get("td", [])}
    got_td = {str(r["component"]): r for r in current.get("td", [])}
    if set(exp_td) != set(got_td):
        passes = False
        rows.append({"kind": "TD_SET", "passes": False,
                     "expected": sorted(exp_td), "actual": sorted(got_td)})
    for comp in sorted(set(exp_td) & set(got_td)):
        for key in ("b", "c"):
            a = float(exp_td[comp][key]); b = float(got_td[comp][key])
            tol = atol + rtol * max(abs(a), abs(b))
            ok = abs(a-b) <= tol
            passes &= ok
            if not ok:
                rows.append({"kind": "TD", "component": comp, "parameter": key,
                             "expected": a, "actual": b, "abs_error": abs(a-b),
                             "tolerance": tol, "passes": ok})
    exact_hash_equal = current.get("coefficient_hash") == ledger.get("coefficient_hash")
    return {
        "schema": "R1_15A2_DEMAND_COEFFICIENT_LEDGER_COMPARISON_V24916",
        "passes": bool(passes),
        "numeric_tolerance_atol": float(atol),
        "numeric_tolerance_rtol": float(rtol),
        "exact_coefficient_hash_equal": bool(exact_hash_equal),
        "expected_coefficient_hash": ledger.get("coefficient_hash"),
        "actual_coefficient_hash": current.get("coefficient_hash"),
        "mismatch_rows": rows,
    }


__all__ = ["SCHEMA", "ledger_from_snapshot", "write_ledger",
           "compare_snapshot_to_ledger"]

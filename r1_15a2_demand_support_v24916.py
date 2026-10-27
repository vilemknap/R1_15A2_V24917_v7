# -*- coding: utf-8 -*-
"""Candidate-induced path-support risk and path-epoch diagnostics for V2.4.9.16.

Baseline/current-state support gaps remain owned by the existing path-epoch
refresh logic.  This module is called only after a candidate's fresh Visum
recompute.  A material candidate-induced unsupported OD makes that candidate
ineligible and triggers rollback; it does not immediately enumerate paths.
"""
from __future__ import annotations

import math
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence, Tuple

import numpy as np

import r1_15a2_core as core
from r1_15a2_demand_evidence_v24916 import _write_csv, _write_json


def canonical_dseg(code: Any) -> str:
    return core.norm_code(code)


def _support_for_dseg(collector: Any, code: str) -> Tuple[set, Dict[Tuple[int, int], float]]:
    support = set()
    stored = defaultdict(float)
    query = """SELECT g.orig,g.dest,SUM(v.volume)
               FROM volumes v JOIN geometry g ON g.gid=v.gid
               WHERE v.dseg=? GROUP BY g.orig,g.dest"""
    for origin, destination, volume in collector.db.execute(query, (code,)):
        key = (int(origin), int(destination))
        support.add(key)
        stored[key] += float(volume or 0.0)
    return support, dict(stored)


def audit_live_matrices(collector: Any, live_matrices: Mapping[str, Any],
                        cfg: Mapping[str, Any], folder: Any = None,
                        block: str = "DEMAND",
                        zone_numbers: Sequence[int] = ()) -> Dict[str, Any]:
    policy = cfg.get("two_mode", {}).get("zero_share_residual_policy", {})
    relative_limit = float(policy.get("max_dseg_relative_volume", 0.01))
    min_volume = float(cfg.get("demand_evidence_targeting", {}).get(
        "support_risk", {}).get("min_volume", 1.0e-5))
    rows = []
    by_dseg = []
    material = False
    for raw_code, raw_matrix in sorted((live_matrices or {}).items()):
        code = canonical_dseg(raw_code)
        matrix = np.asarray(raw_matrix, dtype=float)
        if matrix.ndim != 2 or matrix.shape[0] != matrix.shape[1] or not np.isfinite(matrix).all():
            raise RuntimeError("V24916_SUPPORT_RISK_INVALID_LIVE_MATRIX:%s" % code)
        support, stored = _support_for_dseg(collector, code)
        interzonal_total = float(np.sum(matrix) - np.trace(matrix))
        missing_geometry_volume = 0.0
        zero_share_volume = 0.0
        missing_count = 0
        zero_count = 0
        if zone_numbers and len(zone_numbers) != matrix.shape[0]:
            raise RuntimeError("V24916_SUPPORT_RISK_ZONE_ORDER_MISMATCH:%s" % code)
        zones = list(zone_numbers) if zone_numbers else list(range(1, matrix.shape[0] + 1))
        for oi, di in np.argwhere(matrix > min_volume):
            origin, destination = int(zones[int(oi)]), int(zones[int(di)])
            if origin == destination:
                continue
            volume = float(matrix[oi, di])
            key = (origin, destination)
            if key not in support:
                missing_geometry_volume += volume
                missing_count += 1
                if len(rows) < 500:
                    rows.append({"dseg": code, "origin": origin, "destination": destination,
                                 "live_volume": volume, "classification": "MISSING_GEOMETRY",
                                 "material": True})
            elif stored.get(key, 0.0) <= core.EPS:
                zero_share_volume += volume
                zero_count += 1
                if len(rows) < 500:
                    rows.append({"dseg": code, "origin": origin, "destination": destination,
                                 "live_volume": volume, "epoch_volume": stored.get(key, 0.0),
                                 "classification": "EXISTING_GEOMETRY_ZERO_SAVED_SHARE",
                                 "material": False})
        zero_relative = zero_share_volume / max(core.EPS, interzonal_total)
        dseg_material = missing_geometry_volume > min_volume or zero_relative > relative_limit
        if dseg_material:
            material = True
        for row in rows:
            if row.get("dseg") == code and row.get("classification") == "EXISTING_GEOMETRY_ZERO_SAVED_SHARE":
                row["material"] = zero_relative > relative_limit
        by_dseg.append({
            "dseg": code,
            "interzonal_live_volume": interzonal_total,
            "missing_geometry_count": missing_count,
            "missing_geometry_volume": missing_geometry_volume,
            "zero_share_count": zero_count,
            "zero_share_volume": zero_share_volume,
            "zero_share_relative_volume": zero_relative,
            "zero_share_relative_limit": relative_limit,
            "material": dseg_material,
        })
    unsupported_rows = sum(int(r.get("missing_geometry_count", 0)) for r in by_dseg)
    unsupported_volume = sum(float(r.get("missing_geometry_volume", 0.0)) for r in by_dseg)
    result = {
        "schema": "R1_15A2_DEMAND_CANDIDATE_SUPPORT_RISK_V24916",
        "block": str(block),
        "status": "MATERIAL_CANDIDATE_SUPPORT_RISK" if material else "PASS",
        "eligible": not material,
        "decision": ("INELIGIBLE_ROLLBACK_NO_IMMEDIATE_REENUMERATION"
                     if material else "KEEP_CURRENT_PATH_EPOCH"),
        "canonical_acceptance_decision": ("INELIGIBLE_ROLLBACK"
                                          if material else "ALLOW_ACCEPTANCE"),
        "baseline_support_gap_policy": "MANDATORY_ENUMERATION_UNCHANGED",
        "final_plateau_policy": "FRESH_ENUMERATION_PROOF_UNCHANGED",
        "candidate_induced_reenumeration": False,
        "reenumeration_requested": False,
        "unsupported_positive_od_rows": unsupported_rows,
        "unsupported_positive_volume": unsupported_volume,
        "zero_share_residual_policy_reused": True,
        "by_dseg": by_dseg,
        "sample_rows": rows,
    }
    if folder is not None:
        folder = Path(folder); folder.mkdir(parents=True, exist_ok=True)
        canonical_rows = []
        for row in rows:
            rec = dict(row)
            rec.setdefault("epoch_volume", rec.get("epoch_volume", 0.0))
            rec.setdefault("path_count", 0)
            rec.setdefault("geometry_exists", int(rec.get("classification") != "MISSING_GEOMETRY"))
            rec.setdefault("class", rec.get("classification", ""))
            rec.setdefault("reason", ("CANDIDATE_POSITIVE_OD_WITHOUT_GEOMETRY" if
                           rec.get("classification") == "MISSING_GEOMETRY" else
                           "CP12_ZERO_SHARE_RESIDUAL_POLICY"))
            canonical_rows.append(rec)
        _write_json(folder / "13_PATH_SUPPORT_RISK_AUDIT.json", result)
        _write_csv(folder / "13B_PATH_SUPPORT_RISK_ROWS.csv", canonical_rows)
        # Compatibility aliases used by the controller and prior V249 tests.
        _write_json(folder / "CANDIDATE_SUPPORT_RISK.json", result)
        _write_csv(folder / "CANDIDATE_SUPPORT_RISK_ROWS.csv", canonical_rows)
    return result


def path_epoch_validity_report(path_rows: Sequence[Mapping[str, Any]],
                               optional_skim_cache: Any = None,
                               folder: Any = None) -> Dict[str, Any]:
    """Write a non-authoritative cached-vs-skim observability report.

    V24916 deliberately does not use this diagnostic as an enumeration trigger.
    A comparison is emitted only when path rows carry an explicit cached
    impedance and the matching optional IMP skim is available.
    """
    rows = []
    compared = suspicious = 0
    for raw in path_rows or []:
        cached = raw.get("cached_impedance", raw.get("path_impedance"))
        if cached in (None, ""):
            continue
        try:
            cached = float(cached)
            origin = int(raw.get("origin", raw.get("from_zone")))
            destination = int(raw.get("destination", raw.get("to_zone")))
            dseg = canonical_dseg(raw.get("dseg_code", raw.get("dseg")))
        except Exception:
            continue
        authority = None
        if optional_skim_cache is not None:
            authority = getattr(optional_skim_cache, "optional", {}).get((dseg, "IMP"))
        live = None if authority is None else authority.value(origin, destination)
        if live is None or not math.isfinite(cached) or cached < 0.0:
            continue
        gap = (cached - live) / max(abs(live), 1.0e-12)
        flag = gap > 0.10
        compared += 1
        suspicious += int(flag)
        if len(rows) < 1000:
            rows.append({
                "dseg_code": dseg, "origin": origin, "destination": destination,
                "cached_impedance": cached, "live_imp_skim": live,
                "relative_cached_minus_live_gap": gap,
                "diagnostic_suspicious": int(flag),
            })
    result = {
        "schema": "R1_15A2_PATH_EPOCH_VALIDITY_DIAGNOSTIC_V24916",
        "status": "COMPARED" if compared else "NOT_EVALUATED_NO_COMMON_IMPEDANCE_BASIS",
        "compared_od_rows": compared,
        "suspicious_od_rows": suspicious,
        "hard_reenumeration_trigger": False,
        "targeted_path_augmentation": False,
        "role": "SHADOW_DIAGNOSTIC_ONLY",
        "decision": "KEEP_EXISTING_V24915_ENUMERATION_POLICY",
    }
    if folder is not None:
        folder = Path(folder); folder.mkdir(parents=True, exist_ok=True)
        _write_json(folder / "PATH_EPOCH_VALIDITY.json", result)
        _write_csv(folder / "PATH_EPOCH_VALIDITY_ROWS.csv", rows)
    return result


__all__ = ["canonical_dseg", "audit_live_matrices", "path_epoch_validity_report"]

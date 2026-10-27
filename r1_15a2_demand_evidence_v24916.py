# -*- coding: utf-8 -*-
"""Pure demand-evidence targeting mathematics for R1 15A2 V2.4.9.16.

Path incidence remains the numerical count-response authority.  FlowBundle and
DIST_KM are used only to rank/narrow Trip Generation and Trip Distribution
search.  Fresh Visum assignment plus live 12D/11D remains the acceptance
contract.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import tempfile
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
import r1_15a2_runtime_io_hotfix_profile488 as runtime_io_hotfix
from typing import Any, Dict, Mapping, Optional, Sequence, Set, Tuple, List

import r1_15a2_core as core

ODKey = Tuple[str, int, int]

DEFAULT_CONFIG = {
    "enabled": True,
    "supply_enabled": False,
    "flowbundle_target_dsegs": ["NATIVE_CW", "NATIVE_CW_noT", "NATIVE_CS", "NATIVE_CS_noT"],
    "flowbundle_optional_diagnostic_dsegs": ["EXOG_EE_CW", "EXOG_EE_CW_noT", "EXOG_EE_CS", "EXOG_EE_CS_noT"],
    "flowbundle": {
        "enabled": True,
        "max_profiles": 30,
        "max_od_rows_per_profile": 3000,
        "min_profile_geh": 10.0,
        "min_profile_abs_residual": 300.0,
        "min_od_volume": 0.01,
        "retained_volume_coverage": 0.90,
        "minimum_profile_coverage": 0.70,
        "path_parity_relative_tolerance": 0.02,
        "path_parity_absolute_tolerance": 2.0,
        "od_parity_relative_tolerance": 0.10,
        "od_parity_absolute_tolerance": 5.0,
        "fallback": "PATH_ONLY",
    },
    "generation": {
        "enabled": True,
        "non_target_step_multiplier": 0.20,
        "target_step_multiplier": 1.0,
        "maximum_target_zones_per_family_role": 120,
        "require_supported_od": True,
    },
    "td": {
        "enabled": True,
        "families": ["WORK", "SERVICE"],
        "max_active_components_per_family": 2,
        "max_active_components_total": 4,
        "minimum_alignment_score": 0.0,
        "distance_bin_edges_km": [5, 10, 20, 30, 50, 75, 100],
        "school_long_policy": "FROZEN_UNTIL_GLOBAL_IDP_VERIFY",
        "global_11d_evaluation_required": True,
    },
    "support_risk": {
        "candidate_induced_policy": "REJECT_ROLLBACK_NO_IMMEDIATE_REENUMERATION",
        "baseline_policy": "MANDATORY_ENUMERATION_UNCHANGED",
        "final_plateau_policy": "FRESH_ENUMERATION_PROOF_UNCHANGED",
        "min_volume": 1.0e-5,
    },
}


def _f(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if value is None:
            return default
        if isinstance(value, str):
            value = value.strip().replace("\u00a0", "").replace(" ", "").replace(",", ".")
            if not value or value.lower() in ("nan", "none", "null"):
                return default
        result = float(value)
        return result if math.isfinite(result) else default
    except Exception:
        return default


def deep_merge(base: Mapping[str, Any], override: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    out = deepcopy(dict(base))
    for key, value in (override or {}).items():
        if isinstance(value, Mapping) and isinstance(out.get(key), Mapping):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = deepcopy(value)
    return out


def canonical_dseg(code: Any) -> str:
    return core.norm_code(code)


def family_from_code(value: Any) -> str:
    text = str(value or "").upper()
    if "WORK" in text or "CW" in text:
        return "WORK"
    if "SERV" in text or "CS" in text:
        return "SERVICE"
    if "SCHOOL" in text:
        return "SCHOOL"
    if "LONG" in text or "CL" in text:
        return "LONG"
    return "OTHER"


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
    path = Path(path)
    runtime_io_hotfix._ensure_parent(path)
    tmp = runtime_io_hotfix._short_temp_path(path, "eb")
    try:
        with runtime_io_hotfix._OPEN(runtime_io_hotfix._native_path(tmp), "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        runtime_io_hotfix.replace_with_retry(tmp, path)
        if not runtime_io_hotfix._is_file(path):
            raise OSError("V24916_EVIDENCE_ATOMIC_WRITE_READBACK_MISSING:" + str(path))
    finally:
        try:
            if runtime_io_hotfix._exists(tmp):
                runtime_io_hotfix._unlink(tmp)
        except OSError:
            pass


def _write_json(path: Path, payload: Any) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    _atomic_write_bytes(Path(path), text.encode("utf-8"))


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    runtime_io_hotfix.critical_runtime_write_csv(path, rows)


def _sha256_file(path: Path) -> str:
    return runtime_io_hotfix.safe_sha256_file(path)


def _file_record(path: Path) -> Dict[str, Any]:
    path = Path(path)
    return {
        "name": path.name,
        "size_bytes": runtime_io_hotfix._size(path),
        "sha256": _sha256_file(path),
    }

def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def _bin_bounds(label: str) -> Tuple[Any, Any]:
    text = str(label or "")
    if text == "UNKNOWN" or not text.startswith("["):
        return "", ""
    body = text[1:-1]
    left, right = body.split(",", 1)
    return left, "" if right == "INF" else right


def build_supported_od(variable_rows: Sequence[Mapping[str, Any]]) -> Set[ODKey]:
    out: Set[ODKey] = set()
    for row in variable_rows or []:
        try:
            code = canonical_dseg(row.get("dseg_code", row.get("dseg")))
            origin = int(row.get("origin", row.get("from_zone")))
            destination = int(row.get("destination", row.get("to_zone")))
        except Exception:
            continue
        if origin != destination and int(row.get("path_count", 1) or 0) > 0:
            out.add((code, origin, destination))
    return out


def retain_flowbundle_coverage(rows: Sequence[Mapping[str, Any]], target: float,
                               minimum: float) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    grouped: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    for raw in rows or []:
        row = dict(raw)
        key = (str(row.get("profile_id", row.get("countlocation_no", ""))),
               canonical_dseg(row.get("dseg_code")))
        grouped.setdefault(key, []).append(row)
    kept: List[Dict[str, Any]] = []
    audit: List[Dict[str, Any]] = []
    for (profile, dseg), group in sorted(grouped.items()):
        group.sort(key=lambda r: (-abs(_f(r.get("flowbundle_volume"), 0.0) or 0.0),
                                  int(r.get("origin", 0) or 0), int(r.get("destination", 0) or 0)))
        total = sum(abs(_f(r.get("flowbundle_volume"), 0.0) or 0.0) for r in group)
        selected = []
        cumulative = 0.0
        for row in group:
            selected.append(row)
            cumulative += abs(_f(row.get("flowbundle_volume"), 0.0) or 0.0)
            if cumulative / max(total, 1.0e-12) >= target:
                break
        coverage = cumulative / max(total, 1.0e-12)
        passed = coverage >= minimum
        if passed:
            kept.extend(selected)
        audit.append({"profile_id": profile, "dseg_code": dseg,
                      "positive_flow": total, "retained_flow": cumulative,
                      "retained_coverage": coverage, "target_coverage": target,
                      "minimum_coverage": minimum,
                      "status": "PASS" if passed else "PATH_ONLY_PROFILE_FALLBACK"})
    return kept, audit


def path_parity(flowbundle_rows: Sequence[Mapping[str, Any]],
                path_rows: Sequence[Mapping[str, Any]], relative_tolerance: float,
                absolute_tolerance: float, od_relative_tolerance: float = 0.10,
                od_absolute_tolerance: float = 5.0) -> Dict[str, Any]:
    """Two-level profile×DSeg total and retained-OD distribution parity.

    FlowBundle detail is intentionally truncated by cumulative volume coverage.
    The missing FlowBundle and path volume is therefore compared through one
    explicit ``TAIL_BUCKET`` instead of being misclassified as an OD mismatch.
    """
    fb_totals: Dict[Tuple[str, str], float] = {}
    fb_od: Dict[Tuple[str, str, int, int], float] = {}
    fb_retained: Dict[Tuple[str, str], float] = {}
    for raw in flowbundle_rows or []:
        row = dict(raw)
        profile = str(row.get("profile_id", row.get("countlocation_no", "")))
        dseg = canonical_dseg(row.get("dseg_code", row.get("dseg")))
        key = (profile, dseg)
        total = _f(row.get("flowbundle_total"), None)
        if total is None:
            total = (_f(row.get("flowbundle_volume", row.get("volume")), 0.0) or 0.0)
            fb_totals[key] = fb_totals.get(key, 0.0) + total
        elif key in fb_totals and abs(fb_totals[key] - total) > 1.0e-7:
            return {"schema": "R1_15A2_FLOWBUNDLE_PATH_PARITY_V24916",
                    "status": "PATH_ONLY_FALLBACK", "decision": "PATH_ONLY_FALLBACK",
                    "reason": "INCONSISTENT_FLOWBUNDLE_TOTAL_READBACK",
                    "rows": [], "passing_profile_dseg_keys": [],
                    "failed_profile_dseg_keys": []}
        else:
            fb_totals[key] = float(total)
        try:
            od_key = (profile, dseg, int(row.get("origin")), int(row.get("destination")))
            value = max(0.0, _f(row.get("flowbundle_volume"), 0.0) or 0.0)
            fb_od[od_key] = fb_od.get(od_key, 0.0) + value
            fb_retained[key] = fb_retained.get(key, 0.0) + value
        except Exception:
            pass

    path_totals: Dict[Tuple[str, str], float] = {}
    path_od: Dict[Tuple[str, str, int, int], float] = {}
    for raw in path_rows or []:
        row = dict(raw)
        profile = str(row.get("profile_id", row.get("countlocation_no", "")))
        dseg = canonical_dseg(row.get("dseg_code", row.get("dseg")))
        key = (profile, dseg)
        value = 0.0
        for name in ("path_profile_volume", "path_volume", "volume", "od_volume_on_profile"):
            if name in row:
                value = max(0.0, _f(row.get(name), 0.0) or 0.0)
                break
        path_totals[key] = path_totals.get(key, 0.0) + value
        try:
            od_key = (profile, dseg, int(row.get("origin", row.get("from_zone"))),
                      int(row.get("destination", row.get("to_zone"))))
            path_od[od_key] = path_od.get(od_key, 0.0) + value
        except Exception:
            pass

    keys = sorted(fb_totals)
    if not keys:
        return {"schema": "R1_15A2_FLOWBUNDLE_PATH_PARITY_V24916",
                "status": "PATH_ONLY_FALLBACK", "decision": "PATH_ONLY_FALLBACK",
                "reason": "NO_FLOWBUNDLE_TOTALS", "rows": [],
                "passing_profile_dseg_keys": [], "failed_profile_dseg_keys": []}

    rows = []
    passing = []
    failed = []
    for key in keys:
        fb_total = float(fb_totals[key])
        path_total = float(path_totals.get(key, 0.0))
        total_abs = abs(fb_total - path_total)
        total_rel = total_abs / max(abs(fb_total), 1.0e-12)
        total_pass = key in path_totals and (
            total_abs <= float(absolute_tolerance) or
            total_rel <= float(relative_tolerance))

        retained_od_keys = sorted(k for k in fb_od if k[:2] == key)
        od_abs_l1 = sum(abs(fb_od[k] - path_od.get(k, 0.0)) for k in retained_od_keys)
        fb_tail = max(0.0, fb_total - fb_retained.get(key, 0.0))
        retained_path = sum(path_od.get(k, 0.0) for k in retained_od_keys)
        path_tail = max(0.0, path_total - retained_path)
        tail_abs = abs(fb_tail - path_tail)
        od_abs_with_tail = od_abs_l1 + tail_abs
        od_rel_with_tail = od_abs_with_tail / max(abs(fb_total), 1.0e-12)
        od_pass = (
            od_abs_with_tail <= float(od_absolute_tolerance) or
            od_rel_with_tail <= float(od_relative_tolerance))
        passed = bool(total_pass and od_pass)
        key_text = "%s|%s" % key
        (passing if passed else failed).append(key_text)
        rows.append({
            "profile_id": key[0], "dseg_code": key[1],
            "flowbundle_total": fb_total, "path_total": path_total,
            "total_abs_diff": total_abs, "total_rel_diff": total_rel,
            "total_abs_tolerance": float(absolute_tolerance),
            "total_rel_tolerance": float(relative_tolerance),
            "total_parity_passes": int(total_pass),
            "retained_od_count": len(retained_od_keys),
            "retained_flowbundle_volume": fb_retained.get(key, 0.0),
            "retained_path_volume": retained_path,
            "flowbundle_tail_volume": fb_tail, "path_tail_volume": path_tail,
            "od_retained_l1": od_abs_l1, "od_abs_l1": od_abs_l1, "tail_abs_diff": tail_abs,
            "od_l1_with_tail": od_abs_with_tail,
            "od_relative_l1_with_tail": od_rel_with_tail,
            "od_abs_tolerance": float(od_absolute_tolerance),
            "od_rel_tolerance": float(od_relative_tolerance),
            "od_parity_passes": int(od_pass),
            "passes": int(passed),
            "fallback_action": "FLOWBUNDLE_TARGETED" if passed else "PATH_ONLY_PROFILE_FALLBACK",
        })

    if passing and not failed:
        status, decision = "PASS", "FLOWBUNDLE_TARGETING"
    elif passing:
        status, decision = "PASS_WITH_PROFILE_FALLBACKS", "PARTIAL_FLOWBUNDLE_TARGETING"
    else:
        status, decision = "PATH_ONLY_FALLBACK", "PATH_ONLY_FALLBACK"
    return {
        "schema": "R1_15A2_FLOWBUNDLE_PATH_PARITY_V24916",
        "status": status, "decision": decision,
        "parity_basis": "COMPLETE_TOTAL_PLUS_RETAINED_OD_AND_EXPLICIT_TAIL_BUCKET",
        "relative_tolerance": float(relative_tolerance),
        "absolute_tolerance": float(absolute_tolerance),
        "od_relative_tolerance": float(od_relative_tolerance),
        "od_absolute_tolerance": float(od_absolute_tolerance),
        "rows": rows,
        "passing_profile_dseg_keys": passing,
        "failed_profile_dseg_keys": failed,
        "profile_fallback_count": len(failed),
    }

def build_generation_targets(flowbundle_rows: Sequence[Mapping[str, Any]],
                             supported_od: Set[ODKey], cfg: Mapping[str, Any]) -> Dict[str, Any]:
    ecfg = cfg["flowbundle"]
    gcfg = cfg["generation"]
    retained, coverage = retain_flowbundle_coverage(
        flowbundle_rows, float(ecfg.get("retained_volume_coverage", 0.90)),
        float(ecfg.get("minimum_profile_coverage", 0.70)))
    od_rows = []
    zone_scores: Dict[Tuple[str, str, int], float] = {}
    for raw in retained:
        row = dict(raw)
        code = canonical_dseg(row.get("dseg_code"))
        family = family_from_code(code)
        if not code.startswith("NATIVE_") or family not in ("WORK", "SERVICE"):
            continue
        try:
            origin, destination = int(row["origin"]), int(row["destination"])
        except Exception:
            continue
        supported = origin == destination or (code, origin, destination) in supported_od
        if gcfg.get("require_supported_od", True) and not supported:
            continue
        volume = max(0.0, _f(row.get("flowbundle_volume"), 0.0) or 0.0)
        residual = _f(row.get("residual"), 0.0) or 0.0
        if volume <= 0.0 or residual <= 0.0:
            continue
        score = volume * max(residual, 1.0)
        rec = {"profile_id": row.get("profile_id", row.get("countlocation_no", "")),
               "family": family, "dseg_code": code, "origin": origin,
               "destination": destination, "flowbundle_volume": volume,
               "profile_residual": residual, "score": score,
               "distance_km": row.get("distance_km"), "supported": supported}
        od_rows.append(rec)
        zone_scores[(family, "PROD", origin)] = zone_scores.get((family, "PROD", origin), 0.0) + score
        zone_scores[(family, "ATT", destination)] = zone_scores.get((family, "ATT", destination), 0.0) + score
    maximum = int(gcfg.get("maximum_target_zones_per_family_role", 120))
    zone_rows = []
    allowed = set()
    for family in ("WORK", "SERVICE"):
        for role in ("PROD", "ATT"):
            values = sorted(((zone, score) for (fam, rr, zone), score in zone_scores.items()
                             if (fam, rr) == (family, role)), key=lambda x: (-x[1], x[0]))
            for rank, (zone, score) in enumerate(values[:maximum], 1):
                allowed.add((family, role, int(zone)))
                zone_rows.append({"family": family, "role": role,
                                  "zone_no": int(zone), "score": score, "rank": rank})
    return {"status": "ACTIVE" if od_rows and allowed else "PATH_ONLY_FALLBACK",
            "od_rows": od_rows, "profile_coverage": coverage,
            "zone_rows": zone_rows, "allowed_zone_keys": allowed}


def target_projection_rows(rows: Sequence[Mapping[str, Any]], targets: Mapping[str, Any],
                           cfg: Mapping[str, Any]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Apply FlowBundle damping only to positive non-target generation steps.

    The current V24915 signed-generation controller is authoritative. Negative
    proposals are never damped by underload evidence and no sign may flip.
    """
    original = [dict(r) for r in rows or []]
    if not cfg.get("generation", {}).get("enabled", True) or targets.get("status") != "ACTIVE":
        return original, {"schema": "R1_15A2_GENERATION_TARGET_APPLY_AUDIT_V24916",
                          "status": "PATH_ONLY_FALLBACK", "input_rows": len(original),
                          "output_rows": len(original), "reason": "TARGETS_NOT_ACTIVE"}
    allowed = set(targets.get("allowed_zone_keys") or [])
    target_factor = float(cfg["generation"].get("target_step_multiplier", 1.0))
    other_factor = float(cfg["generation"].get("non_target_step_multiplier", 0.20))
    if not (0.0 <= other_factor <= target_factor <= 1.0):
        raise ValueError("V24916_INVALID_GENERATION_TARGET_FACTORS")
    out = []
    targeted = damped = negative_unchanged = zero_unchanged = 0
    for row in original:
        rec = dict(row)
        family = family_from_code(rec.get("family"))
        role = str(rec.get("role", "")).upper()
        zone = int(rec.get("zone_no"))
        old_step = _f(rec.get("log_step"), 0.0) or 0.0
        if old_step < 0.0:
            factor = 1.0
            negative_unchanged += 1
            reason = "NEGATIVE_SIGNED_STEP_UNCHANGED"
        elif old_step == 0.0:
            factor = 1.0
            zero_unchanged += 1
            reason = "ZERO_STEP_UNCHANGED"
        elif (family, role, zone) in allowed:
            factor = target_factor
            targeted += 1
            reason = "POSITIVE_TARGET_ZONE"
        else:
            factor = other_factor
            damped += 1
            reason = "POSITIVE_NON_TARGET_DAMPED"
        new_step = old_step * factor
        if old_step != 0.0 and new_step != 0.0 and math.copysign(1.0, old_step) != math.copysign(1.0, new_step):
            raise ValueError("V24916_GENERATION_TARGETING_SIGN_FLIP")
        rec["v24916_targeted"] = reason == "POSITIVE_TARGET_ZONE"
        rec["v24916_target_factor"] = factor
        rec["v24916_target_reason"] = reason
        rec["pre_target_log_step"] = old_step
        rec["log_step"] = new_step
        rec["multiplier"] = math.exp(new_step)
        # Margin deltas are part of the proposal representation. Apply the same
        # factor only when a positive log-step was actually damped/targeted.
        if old_step > 0.0:
            for name in ("guided_margin_delta", "projected_margin_delta", "raw_relative_margin_change"):
                if _f(rec.get(name), None) is not None:
                    rec["pre_target_" + name] = rec[name]
                    rec[name] = float(rec[name]) * factor
        out.append(rec)
    # Preserve exact incoming write order. Targeting may change values only.
    return out, {
        "schema": "R1_15A2_GENERATION_TARGET_APPLY_AUDIT_V24916",
        "status": "ACTIVE", "input_rows": len(original), "output_rows": len(out),
        "positive_target_rows": targeted,
        "positive_non_target_damped_rows": damped,
        "negative_rows_unchanged": negative_unchanged,
        "zero_rows_unchanged": zero_unchanged,
        "negative_or_zero_rows_unchanged": negative_unchanged + zero_unchanged,
        "target_factor": target_factor, "non_target_factor": other_factor,
        "path_incidence_values_modified": False,
        "signed_generation_authority_preserved": True,
        "sign_flip_possible": False,
    }

def _distance_bin(value: Any, edges: Sequence[float]) -> str:
    distance = _f(value, None)
    if distance is None:
        return "UNKNOWN"
    low = 0.0
    for high in edges:
        high = float(high)
        if distance < high:
            return "[%g,%g)" % (low, high)
        low = high
    return "[%g,INF)" % low


def build_td_targeting(flowbundle_rows: Sequence[Mapping[str, Any]],
                       component_rows: Sequence[Mapping[str, Any]],
                       cfg: Mapping[str, Any]) -> Dict[str, Any]:
    tcfg = cfg["td"]
    families = [str(x).upper() for x in tcfg.get("families", ["WORK", "SERVICE"])]
    edges = [float(x) for x in tcfg.get("distance_bin_edges_km", [])]
    pressure: Dict[str, Dict[str, Any]] = {}
    for family in families:
        bins: Dict[str, float] = {}
        flow = 0.0
        weighted_distance = 0.0
        for row in flowbundle_rows or []:
            if row.get("targeting_eligible") in (False, 0, "0"):
                continue
            if family_from_code(row.get("family", row.get("dseg_code"))) != family:
                continue
            volume = max(0.0, _f(row.get("flowbundle_volume"), 0.0) or 0.0)
            residual = max(0.0, _f(row.get("residual"), 0.0) or 0.0)
            distance = _f(row.get("distance_km"), None)
            if volume <= 0.0 or residual <= 0.0 or distance is None:
                continue
            weight = volume * residual
            label = _distance_bin(distance, edges)
            bins[label] = bins.get(label, 0.0) + weight
            flow += weight
            weighted_distance += weight * distance
        pressure[family] = {"bins": bins, "evidence_weight": flow,
                            "evidence_mean_distance_km": weighted_distance / max(flow, 1.0e-12)}
    alignment = []
    for raw in component_rows or []:
        component = str(raw.get("component", ""))
        family = family_from_code(raw.get("family", component))
        if family not in pressure:
            continue
        if str(raw.get("target_status", "")) != "ACTIVE_COMPONENT_DIST_TARGET":
            continue
        l1 = max(0.0, _f(raw.get("l1_distance_half"), 0.0) or 0.0)
        rmse = max(0.0, _f(raw.get("rmse_share"), 0.0) or 0.0)
        mean_delta = _f(raw.get("mean_delta_model_minus_target"), None)
        if mean_delta is None:
            model = _f(raw.get("mean_model_conditioned"), 0.0) or 0.0
            target = _f(raw.get("mean_target"), 0.0) or 0.0
            mean_delta = model - target
        evidence_weight = pressure[family]["evidence_weight"]
        # FlowBundle selects the family and distance context; 11D error selects
        # components.  This deliberately does not claim exact component attribution.
        score = (l1 + 0.5 * rmse + 0.01 * abs(mean_delta)) * math.log1p(max(0.0, evidence_weight))
        alignment.append({"component": component, "family": family,
                          "alignment_score": score, "l1_distance_half": l1,
                          "rmse_share": rmse,
                          "mean_delta_model_minus_target": mean_delta,
                          "flowbundle_family_evidence_weight": evidence_weight,
                          "flowbundle_family_mean_distance_km": pressure[family]["evidence_mean_distance_km"],
                          "attribution_level": "FAMILY_ONLY_NOT_EXACT_COMPONENT"})
    active: List[str] = []
    maximum_family = int(tcfg.get("max_active_components_per_family", 2))
    minimum = float(tcfg.get("minimum_alignment_score", 0.0))
    for family in families:
        group = sorted((r for r in alignment if r["family"] == family),
                       key=lambda r: (-r["alignment_score"], r["component"]))
        selected = [r["component"] for r in group
                    if r["alignment_score"] >= minimum][:maximum_family]
        active.extend(selected)
    active = active[:int(tcfg.get("max_active_components_total", 4))]
    return {"status": "ACTIVE" if active else "GLOBAL_IDP_FALLBACK",
            "family_pressure": pressure, "alignment_rows": alignment,
            "active_components": active,
            "frozen_components": ["SCHOOL", "LONG_COMPOSITE"],
            "global_11d_evaluation_required": True,
            "finecdf_remains_direction_and_magnitude_authority": True}



def build_shadow_block_classifier(profile_rows: Sequence[Mapping[str, Any]],
                                  flowbundle_rows: Sequence[Mapping[str, Any]],
                                  td_plan: Mapping[str, Any],
                                  parity: Mapping[str, Any],
                                  optional_skim_summary: Optional[Mapping[str, Any]] = None
                                  ) -> Dict[str, Any]:
    """Conservative read-only demand/TD/supply classification.

    The classifier is observability only.  It never changes parameters and is
    intentionally biased toward ``INSUFFICIENT_EVIDENCE`` when no independent
    routing/cost context is available.
    """
    passing = set(parity.get("passing_profile_dseg_keys", []) or [])
    failed = set(parity.get("failed_profile_dseg_keys", []) or [])
    by_profile: Dict[str, Dict[str, Any]] = {}
    for raw in flowbundle_rows or []:
        profile = str(raw.get("profile_id", raw.get("countlocation_no", "")))
        if not profile:
            continue
        rec = by_profile.setdefault(profile, {
            "profile_id": profile, "flowbundle_volume": 0.0,
            "weighted_distance": 0.0, "dseg_keys": set(),
            "families": set(), "targeting_rows": 0,
        })
        volume = max(0.0, _f(raw.get("flowbundle_volume"), 0.0) or 0.0)
        distance = _f(raw.get("distance_km"), None)
        rec["flowbundle_volume"] += volume
        if distance is not None:
            rec["weighted_distance"] += volume * distance
        dseg = canonical_dseg(raw.get("dseg_code"))
        rec["dseg_keys"].add("%s|%s" % (profile, dseg))
        rec["families"].add(family_from_code(raw.get("family", dseg)))
        rec["targeting_rows"] += int(raw.get("targeting_eligible", 0) or 0)

    profile_source = {}
    for raw in profile_rows or []:
        pid = str(raw.get("countlocation_no", raw.get("profile_id", "")))
        if pid:
            profile_source[pid] = dict(raw)

    active_td = set(str(x) for x in td_plan.get("active_components", []) or [])
    optional_selected = (optional_skim_summary or {}).get("selected", []) or []
    optional_codes = {str(r.get("matrix_code", "")).upper() for r in optional_selected}
    cost_context = bool(optional_codes & {"IMP", "TTC", "TT0"})
    rows = []
    counts: Dict[str, int] = {}
    for profile, agg in sorted(by_profile.items()):
        src = profile_source.get(profile, {})
        observed = _f(src.get("observed"), 0.0) or 0.0
        model = _f(src.get("model"), 0.0) or 0.0
        residual = observed - model
        volume = agg["flowbundle_volume"]
        mean_distance = agg["weighted_distance"] / max(volume, 1.0e-12)
        keys = set(agg["dseg_keys"])
        parity_pass = bool(keys) and not (keys & failed) and bool(keys & passing)
        family = sorted(agg["families"])[0] if agg["families"] else "OTHER"
        family_td = any((family == "WORK" and x.startswith("WORK")) or
                        (family == "SERVICE" and (x.startswith("SERV") or x.startswith("SERVICE")))
                        for x in active_td)
        reason = ""
        if not parity_pass:
            classification = "NETWORK_OR_MAPPING_REVIEW"
            reason = "FLOWBUNDLE_PATH_PARITY_NOT_VERIFIED"
        elif residual > 0.0 and family_td:
            classification = "LIKELY_TD"
            reason = "UNDERLOAD_WITH_ACTIVE_11D_COMPONENT_ALIGNMENT"
        elif residual > 0.0 and agg["targeting_rows"] > 0:
            classification = "LIKELY_GENERATION"
            reason = "UNDERLOAD_NATIVE_OD_TARGETS_WITHOUT_ACTIVE_TD_ALIGNMENT"
        elif residual < 0.0 and cost_context:
            classification = "LIKELY_SUPPLY"
            reason = "OVERLOAD_WITH_SHADOW_COST_SKIM_CONTEXT"
        elif residual < 0.0:
            classification = "INSUFFICIENT_EVIDENCE"
            reason = "OVERLOAD_WITHOUT_INDEPENDENT_COST_CONTEXT"
        else:
            classification = "INSUFFICIENT_EVIDENCE"
            reason = "NO_MATERIAL_SIGNED_RESIDUAL"
        counts[classification] = counts.get(classification, 0) + 1
        rows.append({
            "profile_id": profile, "family": family,
            "observed": observed, "model": model, "residual_obs_minus_model": residual,
            "flowbundle_volume": volume, "flowbundle_mean_distance_km": mean_distance,
            "parity_verified": int(parity_pass), "active_td_alignment": int(family_td),
            "optional_cost_context_available": int(cost_context),
            "classification": classification, "reason": reason,
            "role": "SHADOW_DIAGNOSTIC_ONLY",
        })
    return {
        "schema": "R1_15A2_SHADOW_BLOCK_CLASSIFIER_V24916",
        "status": "PASS" if rows else "NO_CLASSIFIABLE_PROFILES",
        "rows": rows, "class_counts": counts,
        "supply_writes": False, "acceptance_role": "NONE",
        "objective_role": "NONE", "automatic_parameter_changes": False,
    }

def evidence_id(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass
class DemandEvidenceSnapshot:
    state_hash: str
    status: str
    evidence_id: str
    path_epoch: Optional[int] = None
    path_basis_hash: Optional[str] = None
    path_basis_comparison_hash: Optional[str] = None
    flowbundle_rows: List[Dict[str, Any]] = field(default_factory=list)
    flowbundle_status: List[Dict[str, Any]] = field(default_factory=list)
    driver_profiles: List[Dict[str, Any]] = field(default_factory=list)
    path_profile_od_rows: List[Dict[str, Any]] = field(default_factory=list)
    generation_targets: Dict[str, Any] = field(default_factory=dict)
    td_targets: Dict[str, Any] = field(default_factory=dict)
    parity: Dict[str, Any] = field(default_factory=dict)
    skim_summary: Dict[str, Any] = field(default_factory=dict)
    flowbundle_contract_hash: str = ""
    config_sha256: str = ""
    implementation_hashes: Dict[str, str] = field(default_factory=dict)
    source_hashes: Dict[str, str] = field(default_factory=dict)
    timings_seconds: Dict[str, float] = field(default_factory=dict)
    fallback_reason: Optional[str] = None


class DemandEvidenceManager:
    def __init__(self, config: Optional[Mapping[str, Any]] = None):
        self.config = deep_merge(DEFAULT_CONFIG, config)
        self.snapshot: Optional[DemandEvidenceSnapshot] = None
        self.telemetry = {"snapshot_builds": 0, "snapshot_reuses": 0,
                          "path_only_fallbacks": 0, "generation_target_calls": 0,
                          "td_target_calls": 0}

    def snapshot_for(self, state_hash: str) -> Optional[DemandEvidenceSnapshot]:
        if self.snapshot is not None and self.snapshot.state_hash == state_hash:
            self.telemetry["snapshot_reuses"] += 1
            return self.snapshot
        return None

    def set_snapshot(self, snapshot: DemandEvidenceSnapshot) -> None:
        self.snapshot = snapshot
        self.telemetry["snapshot_builds"] += 1
        if snapshot.status != "ACTIVE":
            self.telemetry["path_only_fallbacks"] += 1

    def generation_projection(self, rows: Sequence[Mapping[str, Any]]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        self.telemetry["generation_target_calls"] += 1
        targets = self.snapshot.generation_targets if self.snapshot else {}
        return target_projection_rows(rows, targets, self.config)

    def td_mask(self) -> Dict[str, Any]:
        self.telemetry["td_target_calls"] += 1
        return dict(self.snapshot.td_targets) if self.snapshot else {
            "status": "GLOBAL_IDP_FALLBACK", "active_components": []}

    def _profile_dseg_summary(self, snap: DemandEvidenceSnapshot) -> List[Dict[str, Any]]:
        parity_by_key = {
            (str(r.get("profile_id", "")), canonical_dseg(r.get("dseg_code"))): dict(r)
            for r in snap.parity.get("rows", []) or []
        }
        status_by_key = {}
        for row in snap.flowbundle_status or []:
            key = (str(row.get("profile_id", "")),
                   canonical_dseg(row.get("dseg", row.get("dseg_code", ""))))
            status_by_key[key] = dict(row)
        retained = {}
        family = {}
        coverage = {}
        for row in snap.flowbundle_rows or []:
            key = (str(row.get("profile_id", row.get("countlocation_no", ""))),
                   canonical_dseg(row.get("dseg_code")))
            retained[key] = retained.get(key, 0.0) + abs(_f(
                row.get("flowbundle_volume"), 0.0) or 0.0)
            family[key] = family_from_code(row.get("family", key[1]))
            coverage[key] = max(coverage.get(key, 0.0),
                                _f(row.get("retained_coverage"), 0.0) or 0.0)
        keys = sorted(set(parity_by_key) | set(status_by_key) | set(retained))
        out = []
        for key in keys:
            parity = parity_by_key.get(key, {})
            status = status_by_key.get(key, {})
            passed = bool(_safe_int(parity.get("passes"), 0))
            out.append({
                "evidence_id": snap.evidence_id,
                "state_hash": snap.state_hash,
                "path_epoch": snap.path_epoch,
                "profile_id": key[0], "dseg_code": key[1],
                "family": family.get(key, family_from_code(key[1])),
                "flowbundle_total": parity.get(
                    "flowbundle_total", status.get("flowbundle_total", 0.0)),
                "retained_volume": retained.get(key, 0.0),
                "retained_coverage": coverage.get(
                    key, status.get("retained_coverage", 0.0)),
                "path_incidence_live_total": parity.get("path_total", 0.0),
                "absolute_difference": parity.get("total_abs_diff", ""),
                "relative_difference": parity.get("total_rel_diff", ""),
                "parity_passes": int(passed),
                "targeting_mode": ("FLOWBUNDLE_TARGETED" if passed else
                                   "PATH_ONLY_FALLBACK"),
                "fallback_reason": ("" if passed else
                                    status.get("error", status.get("status",
                                    "PROFILE_PARITY_FAILED"))),
            })
        return out

    def _flowbundle_od_output(self, snap: DemandEvidenceSnapshot) -> List[Dict[str, Any]]:
        path_map = {}
        path_count = {}
        for row in snap.path_profile_od_rows or []:
            try:
                key = (str(row.get("profile_id", row.get("countlocation_no", ""))),
                       canonical_dseg(row.get("dseg_code")),
                       int(row.get("origin", row.get("from_zone"))),
                       int(row.get("destination", row.get("to_zone"))))
            except Exception:
                continue
            path_map[key] = path_map.get(key, 0.0) + (_f(
                row.get("path_profile_volume", row.get("path_live_volume")), 0.0) or 0.0)
            path_count[key] = max(path_count.get(key, 0),
                                  _safe_int(row.get("path_count"), 1))
        pass_keys = set(snap.parity.get("passing_profile_dseg_keys", []) or [])
        edges = self.config.get("td", {}).get("distance_bin_edges_km", [])
        grouped = {}
        for raw in snap.flowbundle_rows or []:
            row = dict(raw)
            key = (str(row.get("profile_id", row.get("countlocation_no", ""))),
                   canonical_dseg(row.get("dseg_code")))
            grouped.setdefault(key, []).append(row)
        out = []
        for key in sorted(grouped):
            rows = sorted(grouped[key], key=lambda r: (
                -abs(_f(r.get("flowbundle_volume"), 0.0) or 0.0),
                _safe_int(r.get("origin")), _safe_int(r.get("destination"))))
            total = max(sum(abs(_f(r.get("flowbundle_volume"), 0.0) or 0.0)
                            for r in rows), 1.0e-12)
            cumulative = 0.0
            for row in rows:
                volume = abs(_f(row.get("flowbundle_volume"), 0.0) or 0.0)
                cumulative += volume
                try:
                    od_key = (key[0], key[1], int(row.get("origin")),
                              int(row.get("destination")))
                except Exception:
                    continue
                distance = _f(row.get("distance_km"), None)
                bin_id = _distance_bin(distance, edges)
                supported = bool(row.get("supported", path_count.get(od_key, 0) > 0))
                parity_allowed = "%s|%s" % key in pass_keys
                out.append({
                    "evidence_id": snap.evidence_id,
                    "state_hash": snap.state_hash,
                    "path_epoch": snap.path_epoch,
                    "profile_id": key[0], "dseg_code": key[1],
                    "family": family_from_code(row.get("family", key[1])),
                    "origin": od_key[2], "destination": od_key[3],
                    "flowbundle_volume": volume,
                    "profile_dseg_share": volume / total,
                    "cumulative_share": cumulative / total,
                    "retained": 1,
                    "dist_km": distance if distance is not None else "",
                    "distance_bin_id": bin_id,
                    "path_support_status": ("SUPPORTED" if supported else
                                            "UNSUPPORTED"),
                    "path_count": path_count.get(od_key, 1 if supported else 0),
                    "path_live_volume": path_map.get(od_key, 0.0),
                    "targeting_allowed": int(supported and parity_allowed),
                })
        return out

    def _od_skim_rows(self, snap: DemandEvidenceSnapshot,
                      od_rows: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
        source_hash = snap.skim_summary.get("matrix_sha256", "")
        source_no = snap.skim_summary.get("matrix_no", 9697)
        merged = {}
        edges = self.config.get("td", {}).get("distance_bin_edges_km", [])
        for row in od_rows:
            key = (canonical_dseg(row.get("dseg_code")),
                   _safe_int(row.get("origin")), _safe_int(row.get("destination")))
            rec = merged.setdefault(key, {
                "evidence_id": snap.evidence_id,
                "state_hash": snap.state_hash,
                "path_epoch": snap.path_epoch,
                "dseg_code": key[0], "origin": key[1], "destination": key[2],
                "dist_km": row.get("dist_km", ""),
                "source_matrix_no": source_no,
                "source_matrix_hash": source_hash,
                "flowbundle_retained_volume": 0.0,
                "path_live_volume": 0.0,
            })
            rec["flowbundle_retained_volume"] += (_f(
                row.get("flowbundle_volume"), 0.0) or 0.0)
            rec["path_live_volume"] += (_f(row.get("path_live_volume"), 0.0) or 0.0)
        out = []
        for key in sorted(merged):
            rec = merged[key]
            label = _distance_bin(rec.get("dist_km"), edges)
            low, high = _bin_bounds(label)
            rec.update(distance_bin_id=label, distance_bin_low=low,
                       distance_bin_high=high)
            out.append(rec)
        return out

    def _family_pressure_rows(self, snap: DemandEvidenceSnapshot) -> List[Dict[str, Any]]:
        pressure = snap.td_targets.get("family_pressure", {}) or {}
        profiles_by = {}
        retained_by = {}
        edges = self.config.get("td", {}).get("distance_bin_edges_km", [])
        for row in snap.flowbundle_rows or []:
            family = family_from_code(row.get("family", row.get("dseg_code")))
            label = _distance_bin(row.get("distance_km"), edges)
            key = (family, label)
            profiles_by.setdefault(key, set()).add(str(row.get("profile_id", "")))
            retained_by[key] = retained_by.get(key, 0.0) + (_f(
                row.get("flowbundle_volume"), 0.0) or 0.0)
        out = []
        for family in sorted(pressure):
            bins = pressure[family].get("bins", {}) or {}
            total = max(sum(abs(_f(v, 0.0) or 0.0) for v in bins.values()), 1.0e-12)
            for label, value in sorted(bins.items()):
                signed = _f(value, 0.0) or 0.0
                low, high = _bin_bounds(label)
                key = (family, label)
                out.append({
                    "evidence_id": snap.evidence_id,
                    "state_hash": snap.state_hash,
                    "path_epoch": snap.path_epoch,
                    "family": family, "distance_bin_id": label,
                    "bin_low": low, "bin_high": high,
                    "underload_pressure": max(0.0, signed),
                    "overroute_pressure": max(0.0, -signed),
                    "signed_pressure": signed,
                    "normalized_signed_pressure": signed / total,
                    "contributing_profiles": len(profiles_by.get(key, set())),
                    "retained_flow": retained_by.get(key, 0.0),
                    "driver_weight_coverage": snap.parity.get(
                        "passing_weighted_driver_share", 0.0),
                })
        return out

    def write_outputs(self, folder: Any) -> None:
        """Publish the canonical 00..14 evidence contract atomically.

        Legacy alias files are retained for compatibility with the first V249
        prototype, but the numbered files are the release authority and are the
        only files included in the immutable evidence manifest.
        """
        root = Path(folder); root.mkdir(parents=True, exist_ok=True)
        snap = self.snapshot
        if snap is None:
            summary = {
                "schema": "R1_15A2_DEMAND_EVIDENCE_SUMMARY_V24916",
                "status": "FAILED", "fallback_mode": "SNAPSHOT_LEGACY_V2489",
                "reason": "NOT_BUILT", "supply_touched": False,
                "direct_od_matrix_writes": False,
            }
            _write_json(root / "00_DEMAND_EVIDENCE_SUMMARY.json", summary)
            _write_json(root / "14_DEMAND_EVIDENCE_MANIFEST.json", {
                "schema": "R1_15A2_DEMAND_EVIDENCE_MANIFEST_V24916",
                "status": "NOT_BUILT", "files": [
                    _file_record(root / "00_DEMAND_EVIDENCE_SUMMARY.json")],
                "immutable_after_publication": True,
            })
            return

        driver_rows = sorted((dict(r) for r in snap.driver_profiles or []),
                             key=lambda r: (-_f(r.get("driver_score"), 0.0),
                                            str(r.get("profile_id", ""))))
        for row in driver_rows:
            row.setdefault("evidence_id", snap.evidence_id)
            row.setdefault("state_hash", snap.state_hash)
            row.setdefault("path_epoch", snap.path_epoch)
        execution_rows = []
        for row in snap.flowbundle_status or []:
            rec = dict(row)
            rec.setdefault("evidence_id", snap.evidence_id)
            rec.setdefault("state_hash", snap.state_hash)
            rec.setdefault("path_epoch", snap.path_epoch)
            execution_rows.append(rec)
        execution_rows.sort(key=lambda r: (str(r.get("profile_id", "")),
                                           canonical_dseg(r.get("dseg", r.get("dseg_code", ""))),
                                           str(r.get("status", ""))))
        profile_summary = self._profile_dseg_summary(snap)
        od_rows = self._flowbundle_od_output(snap)
        skim_rows = self._od_skim_rows(snap, od_rows)
        parity_rows = [dict(r, evidence_id=snap.evidence_id,
                            state_hash=snap.state_hash, path_epoch=snap.path_epoch)
                       for r in snap.parity.get("rows", []) or []]
        weighted_coverage = sum(_f(r.get("weighted_driver_share"), 0.0) or 0.0
                                for r in parity_rows if _safe_int(r.get("passes"), 0))
        snap.parity["passing_weighted_driver_share"] = weighted_coverage
        pressure_rows = self._family_pressure_rows(snap)
        generation_od = sorted((dict(r) for r in snap.generation_targets.get("od_rows", [])),
                               key=lambda r: (-_f(r.get("score"), 0.0),
                                              canonical_dseg(r.get("dseg_code")),
                                              _safe_int(r.get("origin")),
                                              _safe_int(r.get("destination"))))
        od_lookup = {(r.get("profile_id"), canonical_dseg(r.get("dseg_code")),
                      _safe_int(r.get("origin")), _safe_int(r.get("destination"))): r
                     for r in od_rows}
        for index, row in enumerate(generation_od):
            evidence_row = od_lookup.get((row.get("profile_id"),
                                          canonical_dseg(row.get("dseg_code")),
                                          _safe_int(row.get("origin")),
                                          _safe_int(row.get("destination"))), {})
            row.setdefault("evidence_id", snap.evidence_id)
            row.setdefault("state_hash", snap.state_hash)
            row.setdefault("path_epoch", snap.path_epoch)
            row.setdefault("variable_index", index)
            row.setdefault("current_live_volume", evidence_row.get("path_live_volume", 0.0))
            row.setdefault("path_count", evidence_row.get("path_count", 0))
            row.setdefault("path_driver_exposure", evidence_row.get("path_live_volume", 0.0))
            row.setdefault("flowbundle_driver_score", row.get("score", 0.0))
            row.setdefault("flowbundle_profile_count", 1)
            row.setdefault("flowbundle_confidence", evidence_row.get("cumulative_share", 0.0))
            row.setdefault("dist_km", evidence_row.get("dist_km", row.get("distance_km", "")))
            row.setdefault("distance_bin_id", evidence_row.get("distance_bin_id", ""))
            row.setdefault("idp_compatibility_score", "")
            row.setdefault("targeting_score", row.get("score", 0.0))
            row.setdefault("support_status", evidence_row.get("path_support_status", "SUPPORTED"))
            row.setdefault("selected_for_solver", 1)
            row.setdefault("selection_reason", "FLOWBUNDLE_SUPPORTED_DRIVER_OD")
            row.setdefault("regularization_multiplier", 1.0)
            row.setdefault("covered_driver_weight", row.get("score", 0.0))
        generation_zone = sorted((dict(r) for r in snap.generation_targets.get("zone_rows", [])),
                                 key=lambda r: (str(r.get("family", "")),
                                                str(r.get("role", "")),
                                                _safe_int(r.get("rank")),
                                                _safe_int(r.get("zone_no"))))
        for row in generation_zone:
            row.setdefault("evidence_id", snap.evidence_id)
            row.setdefault("state_hash", snap.state_hash)
            row.setdefault("path_epoch", snap.path_epoch)
            row.setdefault("flowbundle_score", row.get("score", 0.0))
            row.setdefault("selected_od_volume", "")
            row.setdefault("selected_od_count", "")
            row.setdefault("profile_count", "")
            row.setdefault("projection_prior_multiplier", 1.0)
            row.setdefault("hard_eligible", 1)
            row.setdefault("hard_exclusion_reason", "")
            row.setdefault("pa_balance_group", "%s_%s" % (
                row.get("family", ""), row.get("role", "")))
        alignment_rows = sorted((dict(r) for r in snap.td_targets.get("alignment_rows", [])),
                                key=lambda r: (-_f(r.get("alignment_score"), 0.0),
                                               str(r.get("component", ""))))
        for rank, row in enumerate(alignment_rows, 1):
            row.setdefault("selection_rank", rank)
            row.setdefault("selected", int(row.get("component") in
                                            set(snap.td_targets.get("active_components", []))))
            row.setdefault("selection_reason", ("COUNT_ALIGNED_TARGETED" if
                           row["selected"] else "FROZEN_BY_ACTIVE_COMPONENT_CAP"))
            row.setdefault("reliability_status", "ACTIVE_COMPONENT_DIST_TARGET")
            row.setdefault("evidence_id", snap.evidence_id)
            row.setdefault("state_hash", snap.state_hash)
            row.setdefault("path_epoch", snap.path_epoch)

        selected_drivers = sum(_safe_int(r.get("selected"), 0) for r in driver_rows)
        profile_fallbacks = len(snap.parity.get("failed_profile_dseg_keys", []) or [])
        if snap.status != "ACTIVE":
            summary_status = "LEGACY_FALLBACK"
            fallback_mode = "SNAPSHOT_LEGACY_V2489"
        elif profile_fallbacks:
            summary_status = "PASS_WITH_PROFILE_FALLBACKS"
            fallback_mode = "PROFILE_PATH_ONLY"
        else:
            summary_status = "PASS"
            fallback_mode = "NONE"
        summary = {
            "schema": "R1_15A2_DEMAND_EVIDENCE_SUMMARY_V24916",
            "status": summary_status,
            "evidence_id": snap.evidence_id,
            "state_hash": snap.state_hash,
            "path_epoch": snap.path_epoch,
            "path_basis_hash": snap.path_basis_hash,
            "path_basis_comparison_hash": snap.path_basis_comparison_hash,
            "selected_driver_profiles": selected_drivers,
            "flowbundle_calls": len(execution_rows),
            "flowbundle_retained_od_rows": len(od_rows),
            "flowbundle_weighted_driver_coverage": weighted_coverage,
            "generation_selected_variables": len(generation_od),
            "generation_selected_zones": len(generation_zone),
            "td_selected_components": list(snap.td_targets.get("active_components", [])),
            "fallback_mode": fallback_mode,
            "fallback_reason": snap.fallback_reason,
            "supply_touched": False,
            "direct_od_matrix_writes": False,
            "path_incidence_values_modified": False,
            "ipf_tolerance_relaxed": False,
            "idp_acceptance_relaxed": False,
            "timings_seconds": dict(snap.timings_seconds),
            "source_hashes": dict(snap.source_hashes),
            "flowbundle_contract_hash": snap.flowbundle_contract_hash,
            "config_sha256": snap.config_sha256,
        }

        active_plan = {
            "schema": "R1_15A2_TD_ACTIVE_COMPONENT_PLAN_V24916",
            "evidence_id": snap.evidence_id,
            "state_hash": snap.state_hash,
            "path_epoch": snap.path_epoch,
            "mode": ("COUNT_ALIGNED_TARGETED" if snap.td_targets.get("active_components")
                     else "GLOBAL_IDP_VERIFY"),
            "active_components": list(snap.td_targets.get("active_components", [])),
            "frozen_components": list(snap.td_targets.get("frozen_components", [])),
            "max_active_components": int(self.config.get("td", {}).get(
                "max_active_components_total", 4)),
            "metrics_evaluate_all_components": True,
            "foreign_fixed": True,
            "generation_frozen": True,
            "addval1_frozen": True,
        }
        active_plan["plan_sha256"] = evidence_id(active_plan)
        support_placeholder = {
            "schema": "R1_15A2_DEMAND_CANDIDATE_SUPPORT_RISK_V24916",
            "evidence_id": snap.evidence_id,
            "parent_state_hash": snap.state_hash,
            "path_epoch": snap.path_epoch,
            "status": "NOT_EVALUATED_AT_ACCEPTED_STATE",
            "zero_share_residual_policy_reused": True,
            "decision": "EVALUATE_AFTER_EACH_FRESH_CANDIDATE_RECOMPUTE",
            "reenumeration_requested": False,
        }

        outputs = {
            "00_DEMAND_EVIDENCE_SUMMARY.json": ("json", summary),
            "01_DRIVER_PROFILE_SELECTION.csv": ("csv", driver_rows),
            "02_FLOWBUNDLE_EXECUTION_AUDIT.csv": ("csv", execution_rows),
            "03_FLOWBUNDLE_PROFILE_DSEG_SUMMARY.csv": ("csv", profile_summary),
            "04_FLOWBUNDLE_OD_CONTRIBUTORS.csv": ("csv", od_rows),
            "05_FLOWBUNDLE_PATH_PARITY.csv": ("csv", parity_rows),
            "06_SKIM_AUTHORITY.json": ("json", snap.skim_summary),
            "07_OD_SKIM_EVIDENCE.csv": ("csv", skim_rows),
            "08_FAMILY_DISTANCE_PRESSURE.csv": ("csv", pressure_rows),
            "09_GENERATION_OD_TARGETING.csv": ("csv", generation_od),
            "10_GENERATION_ZONE_TARGETING.csv": ("csv", generation_zone),
            "11_TD_COMPONENT_ALIGNMENT.csv": ("csv", alignment_rows),
            "12_TD_ACTIVE_COMPONENTS.json": ("json", active_plan),
            "13_PATH_SUPPORT_RISK_AUDIT.json": ("json", support_placeholder),
            "13B_PATH_SUPPORT_RISK_ROWS.csv": ("csv", []),
        }
        publication_order = []
        for name, (kind, payload) in outputs.items():
            target = root / name
            (_write_json if kind == "json" else _write_csv)(target, payload)
            publication_order.append(name)
        records = [_file_record(root / name) for name in publication_order]
        manifest = {
            "schema": "R1_15A2_DEMAND_EVIDENCE_MANIFEST_V24916",
            "release": "R1_15A2_V2_4_9_DEMAND_EVIDENCE_COEFFICIENT_ROLLBACK_20261017",
            "evidence_id": snap.evidence_id,
            "state_hash": snap.state_hash,
            "path_epoch": snap.path_epoch,
            "path_basis_hash": snap.path_basis_hash,
            "path_basis_comparison_hash": snap.path_basis_comparison_hash,
            "config_sha256": snap.config_sha256,
            "implementation_hashes": dict(snap.implementation_hashes),
            "source_authority_hashes": dict(snap.source_hashes),
            "files": records,
            "publication_order": publication_order + ["14_DEMAND_EVIDENCE_MANIFEST.json"],
            "manifest_self_hash_omitted_to_avoid_recursive_identity": True,
            "immutable_after_publication": True,
        }
        _write_json(root / "14_DEMAND_EVIDENCE_MANIFEST.json", manifest)

        # Compatibility aliases for prior V249 analysis notebooks.
        _write_json(root / "DEMAND_EVIDENCE_STATE.json", summary)
        _write_csv(root / "FLOWBUNDLE_PROFILE_STATUS.csv", execution_rows)
        _write_csv(root / "FLOWBUNDLE_OD_ATTRIBUTION.csv", od_rows)
        _write_json(root / "FLOWBUNDLE_PATH_PARITY.json", snap.parity)
        _write_json(root / "SKIM_DISTANCE_AUTHORITY.json", snap.skim_summary)
        _write_json(root / "GENERATION_EVIDENCE_TARGETING.json", {
            k: v for k, v in snap.generation_targets.items() if k != "allowed_zone_keys"})
        _write_csv(root / "GENERATION_TARGET_OD.csv", generation_od)
        _write_csv(root / "GENERATION_TARGET_ZONES.csv", generation_zone)
        _write_json(root / "TD_FAMILY_PRESSURE.json", snap.td_targets.get("family_pressure", {}))
        _write_csv(root / "TD_COMPONENT_ALIGNMENT.csv", alignment_rows)
        _write_json(root / "TD_ACTIVE_COMPONENT_MASK.json", active_plan)
        _write_json(root / "DEMAND_EVIDENCE_TELEMETRY.json", self.telemetry)


__all__ = [
    "DEFAULT_CONFIG", "DemandEvidenceSnapshot", "DemandEvidenceManager",
    "deep_merge", "build_supported_od", "retain_flowbundle_coverage",
    "path_parity", "build_generation_targets", "target_projection_rows",
    "build_td_targeting", "evidence_id",
]

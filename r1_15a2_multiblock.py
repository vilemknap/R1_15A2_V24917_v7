# -*- coding: utf-8 -*-
"""Pure multi-block design logic for R1 STEP 15A2 V2.1.

This module has no Visum COM dependency.  It converts actual-path P/A guidance
into bounded generation-parameter candidates and converts fresh 11D component
curve diagnostics into bounded component-specific b/c candidates.

Important contracts
-------------------
* No OD matrix is written here.
* A backtracking scale is applied exactly once to an unscaled proposal.
* Legacy releases require explicit per-component LONG authority. V2.4.9.3 can
  instead activate one LONG_COMPOSITE block against the global LONG mix while
  preserving the five native matrices through a common b offset and c multiplier.
* SCHOOL is supported, but follows the configured authority policy.  AUTO means
  that 11D must report ACTIVE_COMPONENT_DIST_TARGET.
"""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

try:
    import numpy as np
except Exception:  # pragma: no cover
    np = None

EPS = 1.0e-12


def sval(value: Any, default: str = "") -> str:
    if value is None:
        return default
    try:
        return str(value)
    except Exception:
        return default


def fval(value: Any, default: Optional[float] = None) -> Optional[float]:
    if value is None:
        return default
    try:
        if isinstance(value, str):
            text = value.strip().replace("\ufeff", "").replace("\u00a0", "").replace(" ", "").replace(",", ".")
            if not text or text.lower() in ("nan", "none", "null"):
                return default
            value = text
        out = float(value)
        return out if math.isfinite(out) else default
    except Exception:
        return default


def ival(value: Any, default: Optional[int] = None) -> Optional[int]:
    out = fval(value, None)
    if out is None:
        return default
    try:
        return int(round(out))
    except Exception:
        return default


def clamp(value: float, low: float, high: float) -> float:
    return min(float(high), max(float(low), float(value)))


def _live_coefficient_authority(cfg: Mapping[str, Any]) -> bool:
    authority = cfg.get("generation_coefficient_authority", {}) or {}
    mode = sval(authority.get("mode", "")).upper()
    return (authority.get("enabled") is True and mode in {
        "LIVE_CURRENT_VALUE_RELATIVE_LOG_STEP",
        "LIVE_CURRENT_VALUE_SIGNED_RELATIVE_LOG_STEP_WITH_EMPIRICAL_ENVELOPES",
    })


def _signed_generation_policy(cfg: Mapping[str, Any]) -> Mapping[str, Any]:
    policy = cfg.get("generation_signed_refinement", {}) or {}
    if (policy.get("enabled") is True and
            sval(cfg.get("guidance_mode", "POSITIVE_ONLY")).upper() == "SIGNED"):
        return policy
    return {}


def _reference_coefficient(reference_values: Optional[Mapping[str, Any]], attr: str,
                           zone_no: int, fallback: float) -> float:
    if reference_values:
        by_attr = reference_values.get(attr, {}) or {}
        value = fval(by_attr.get(str(int(zone_no)), by_attr.get(int(zone_no))), None)
        if value is not None and value > EPS:
            return float(value)
    return float(fallback)


def _multiplicative_coefficient_bounds(branch: str, cfg: Mapping[str, Any],
                                       current: Optional[float] = None,
                                       reference: Optional[float] = None) -> Tuple[float, float, str]:
    """Return the active numerical domain for a zonal calibration coefficient.

    V2.4.9.2 adds a reviewed, signed refinement envelope.  Standard domestic
    ADD coefficients are kept in an AMDY-like absolute range, while ZAHR raw
    coefficients use a multiplier around the run-start reference because their
    native scale legitimately contains values such as 5, 8 and 10.  A current
    value already outside the envelope is never force-clamped in one jump: the
    effective bound is widened to the current value, which permits only inward
    movement.
    """
    signed = _signed_generation_policy(cfg)
    if signed:
        if sval(branch).upper() == "ZAHR":
            ref = float(reference if reference is not None and reference > EPS
                        else current if current is not None and current > EPS else 0.0)
            low = ref * float(signed.get("zahr_reference_multiplier_min", 0.5))
            high = ref * float(signed.get("zahr_reference_multiplier_max", 2.0))
            policy = "RUN_START_REFERENCE_RELATIVE_MULTIPLIER"
        else:
            low = float(signed.get("domestic_hard_min", 0.5))
            high = float(signed.get("domestic_hard_max", 2.0))
            policy = "AMDY_LIKE_DOMESTIC_ABSOLUTE_ENVELOPE"
        if current is not None and math.isfinite(float(current)):
            low = min(low, float(current))
            high = max(high, float(current))
        return low, high, policy
    if _live_coefficient_authority(cfg):
        authority = cfg.get("generation_coefficient_authority", {}) or {}
        low = float(authority.get("multiplicative_minimum", 0.0))
        return low, float("inf"), "LIVE_CURRENT_VALUE_RELATIVE_LOG_STEP"
    zcfg = cfg.get("zahr", {}) or {}
    if sval(branch).upper() == "ZAHR":
        return float(zcfg.get("min", 0.0)), float(zcfg.get("max", 10.0)), "LEGACY_ABSOLUTE_BOUNDS"
    return float(cfg.get("add_min", 0.0)), float(cfg.get("add_max", 3.0)), "LEGACY_ABSOLUTE_BOUNDS"


def _salary_coefficient_bounds(cfg: Mapping[str, Any],
                               current: Optional[float] = None) -> Tuple[float, float, str]:
    salary_cfg = cfg.get("salary", {}) or {}
    signed = _signed_generation_policy(cfg)
    if signed:
        low = float(signed.get("salary_hard_min", signed.get("domestic_hard_min", 0.5)))
        high = float(signed.get("salary_hard_max", signed.get("domestic_hard_max", 2.0)))
        if current is not None and math.isfinite(float(current)):
            low = min(low, float(current)); high = max(high, float(current))
        return low, high, "AMDY_LIKE_SALARY_ABSOLUTE_ENVELOPE"
    if _live_coefficient_authority(cfg):
        return -float("inf"), float("inf"), "LIVE_CURRENT_VALUE_PLUS_BOUNDED_DELTA"
    return (float(salary_cfg.get("salary_min", 0.0)),
            float(salary_cfg.get("salary_max", 3.0)),
            "LEGACY_ABSOLUTE_BOUNDS")


def _soft_multiplier_bounds(branch: str, cfg: Mapping[str, Any], current: float,
                            reference: Optional[float] = None) -> Tuple[float, float]:
    signed = _signed_generation_policy(cfg)
    if not signed:
        return -float("inf"), float("inf")
    if sval(branch).upper() == "ZAHR":
        ref = float(reference if reference is not None and reference > EPS else current)
        return (ref * float(signed.get("zahr_reference_soft_min", 0.7)),
                ref * float(signed.get("zahr_reference_soft_max", 1.3)))
    return (float(signed.get("domestic_soft_min", 0.8)),
            float(signed.get("domestic_soft_max", 1.25)))


def _damp_outward_log_step(current: float, step: float, soft_low: float,
                            soft_high: float, factor: float) -> Tuple[float, bool]:
    """Damp only the part of a step that moves farther outside the soft band."""
    if not (math.isfinite(current) and current > EPS and math.isfinite(step)):
        return step, False
    factor = clamp(float(factor), 0.0, 1.0)
    proposed = current * math.exp(step)
    adjusted = step
    if step > 0.0 and proposed > soft_high > 0.0:
        boundary = max(0.0, math.log(soft_high / current)) if current < soft_high else 0.0
        adjusted = boundary + factor * (step - boundary)
    elif step < 0.0 and 0.0 < proposed < soft_low:
        boundary = min(0.0, math.log(soft_low / current)) if current > soft_low else 0.0
        adjusted = boundary + factor * (step - boundary)
    return adjusted, abs(adjusted - step) > 1.0e-15


def _require_finite_coefficient(value: float, code: str) -> float:
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(code)
    return value


COMPONENT_REGISTRY: Dict[str, Dict[str, Any]] = {
    "WORK_E_C": {"family": "WORK", "dstrat_code": "1_WORK_E_C", "matrix_no": 9101},
    "WORK_E_noC": {"family": "WORK", "dstrat_code": "1_WORK_E_noC", "matrix_no": 9102},
    "WORK_noE_C": {"family": "WORK", "dstrat_code": "1_WORK_noE_C", "matrix_no": 9103},
    "WORK_noE_noC": {"family": "WORK", "dstrat_code": "1_WORK_noE_noC", "matrix_no": 9104},
    "WORK_stud": {"family": "WORK", "dstrat_code": "1_WORK_stud", "matrix_no": 9105},
    "SERV_E_C": {"family": "SERVICE", "dstrat_code": "2_SERV_E_C", "matrix_no": 9106},
    "SERV_E_noC": {"family": "SERVICE", "dstrat_code": "2_SERV_E_noC", "matrix_no": 9107},
    "SERV_noE_C": {"family": "SERVICE", "dstrat_code": "2_SERV_noE_C", "matrix_no": 9108},
    "SERV_noE_noC": {"family": "SERVICE", "dstrat_code": "2_SERV_noE_noC", "matrix_no": 9109},
    "SERV_stud": {"family": "SERVICE", "dstrat_code": "2_SERV_stud", "matrix_no": 9110},
    "LONG_E_C": {"family": "LONG", "dstrat_code": "3_LONG_E_C", "matrix_no": 9111},
    "LONG_E_noC": {"family": "LONG", "dstrat_code": "3_LONG_E_noC", "matrix_no": 9112},
    "LONG_noE_C": {"family": "LONG", "dstrat_code": "3_LONG_noE_C", "matrix_no": 9113},
    "LONG_noE_noC": {"family": "LONG", "dstrat_code": "3_LONG_noE_noC", "matrix_no": 9114},
    "LONG_stud": {"family": "LONG", "dstrat_code": "3_LONG_stud", "matrix_no": 9115},
    "SCHOOL": {"family": "SCHOOL", "dstrat_code": "5_SCHOOL", "matrix_no": 9117},
}

GENERATION_ATTRS = [
    "ADD_PROD_W", "ADD_ATT_W", "ADD_SALARY", "ADD_PROD_S", "ADD_ATT_S",
    "ZAHR_PROD_WORK", "ZAHR_ATR_WORK", "ZAHR_PROD_SERV", "ZAHR_ATR_SERV",
]

GENERATION_ATTR_MAP = {
    ("WORK", "PROD", "DOMESTIC"): "ADD_PROD_W",
    ("WORK", "ATT", "DOMESTIC"): "ADD_ATT_W",
    ("SERVICE", "PROD", "DOMESTIC"): "ADD_PROD_S",
    ("SERVICE", "ATT", "DOMESTIC"): "ADD_ATT_S",
    ("WORK", "PROD", "ZAHR"): "ZAHR_PROD_WORK",
    ("WORK", "ATT", "ZAHR"): "ZAHR_ATR_WORK",
    ("SERVICE", "PROD", "ZAHR"): "ZAHR_PROD_SERV",
    ("SERVICE", "ATT", "ZAHR"): "ZAHR_ATR_SERV",
}


def _row_map(rows: Sequence[Mapping[str, Any]], key: str) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for row in rows or []:
        name = sval(row.get(key, "")).strip()
        if name:
            out[name] = dict(row)
    return out


def _bin_key(low: Any, high: Any, label: Any = "") -> str:
    lo = fval(low, None); hi = fval(high, None)
    if lo is not None and hi is not None:
        return "%.6f|%.6f" % (float(lo), float(hi))
    return sval(label).strip()


def _normalized_target_bins(rows: Sequence[Mapping[str, Any]]) -> List[Dict[str, float]]:
    out = []
    total = 0.0
    for row in rows or []:
        lo = fval(row.get("bin_low"), None); hi = fval(row.get("bin_high"), None)
        sh = max(0.0, fval(row.get("target_share"), 0.0) or 0.0)
        if lo is None or hi is None:
            continue
        out.append({"bin_low": float(lo), "bin_high": float(hi), "target_share": sh})
        total += sh
    if total <= EPS:
        return []
    for row in out:
        row["target_share"] /= total
    return out


def long_composite_enabled(cfg: Mapping[str, Any]) -> bool:
    mode = sval((cfg.get("td", {}) or {}).get("long_acceptance_mode", "")).strip().upper()
    return mode == "GLOBAL_LONG_COMPOSITE"


def collapse_td_acceptance_components(components: Sequence[str], cfg: Mapping[str, Any]) -> List[str]:
    """Collapse five native LONG rows to one global-mix acceptance block."""
    unique = []
    seen = set()
    long_inserted = False
    for raw in components or []:
        comp = sval(raw).strip()
        if not comp:
            continue
        is_long = comp == "LONG_COMPOSITE" or (COMPONENT_REGISTRY.get(comp, {}).get("family") == "LONG")
        if is_long and long_composite_enabled(cfg):
            if not long_inserted:
                unique.append("LONG_COMPOSITE")
                seen.add("LONG_COMPOSITE")
                long_inserted = True
            continue
        if comp not in seen:
            unique.append(comp); seen.add(comp)
    return unique


def _aggregate_long_model_bins(smap: Mapping[str, Mapping[str, Any]],
                               model_by_comp: Mapping[str, Sequence[Mapping[str, Any]]]) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    contributions: Dict[str, Dict[str, Any]] = {}
    conditioned_total = 0.0
    total_volume = 0.0
    components = []
    for comp, reg in COMPONENT_REGISTRY.items():
        if reg.get("family") != "LONG":
            continue
        summary = dict(smap.get(comp, {}) or {})
        conditioned = max(0.0, fval(summary.get("conditioned_volume"), 0.0) or 0.0)
        total_volume += max(0.0, fval(summary.get("total_volume"), 0.0) or 0.0)
        bins = list(model_by_comp.get(comp, []) or [])
        if conditioned <= EPS or not bins:
            continue
        conditioned_total += conditioned
        components.append({"component": comp, "conditioned_volume": conditioned})
        for row in bins:
            lo = fval(row.get("bin_low"), None); hi = fval(row.get("bin_high"), None)
            if lo is None or hi is None:
                continue
            key = _bin_key(lo, hi, row.get("bin_label"))
            target = contributions.setdefault(key, {
                "bin_low": float(lo), "bin_high": float(hi),
                "weighted_share_numerator": 0.0,
            })
            target["weighted_share_numerator"] += conditioned * max(
                0.0, fval(row.get("share_conditioned"), 0.0) or 0.0)
    rows = []
    for key in sorted(contributions, key=lambda k: (contributions[k]["bin_low"], contributions[k]["bin_high"])):
        row = contributions[key]
        rows.append({
            "bin_low": row["bin_low"], "bin_high": row["bin_high"],
            "share_conditioned": (row["weighted_share_numerator"] / conditioned_total
                                  if conditioned_total > EPS else 0.0),
        })
    summary = {
        "component": "LONG_COMPOSITE",
        "target_status": "ACTIVE_GLOBAL_LONG_MIX_TARGET",
        "conditioned_volume": conditioned_total,
        "total_volume": total_volume,
        "source_components": components,
    }
    return summary, rows


def _component_policy(component: str, family: str, cfg: Mapping[str, Any], target_status: str) -> Tuple[bool, str]:
    td_cfg = cfg.get("td", {})
    policies = td_cfg.get("component_policy", {}) or {}
    mode = sval(policies.get(component, policies.get(family, "AUTO"))).strip().upper()
    if mode in ("OFF", "DISABLED", "FROZEN", "REPORT_ONLY"):
        return False, "POLICY_%s" % mode
    if family == "LONG":
        if component == "LONG_COMPOSITE" and long_composite_enabled(cfg):
            if mode not in ("CALIBRATE", "ON", "ENABLED", "AUTO"):
                return False, "LONG_COMPOSITE_POLICY_%s" % mode
            return True, "GLOBAL_LONG_COMPOSITE_AUTHORITY"
        # Legacy behavior remains fail-closed for individual LONG components.
        if mode not in ("CALIBRATE", "ON", "ENABLED", "AUTO"):
            return False, "LONG_POLICY_%s" % mode
        return True, "LONG_COMPONENT_AUTHORITY_REQUIRED"
    if family == "SCHOOL" and mode == "AUTO":
        return ("ACTIVE_COMPONENT_DIST_TARGET" in target_status.upper(), "SCHOOL_AUTO_REQUIRES_ACTIVE_TARGET")
    if mode == "AUTO":
        return ("ACTIVE_COMPONENT_DIST_TARGET" in target_status.upper(), "AUTO_REQUIRES_ACTIVE_TARGET")
    return mode in ("CALIBRATE", "ON", "ENABLED"), "EXPLICIT_%s" % mode


def _signal_from_bins(component: str, family: str, matrix_no: int, dstrat_code: str,
                      summary: Mapping[str, Any], model_bins: Sequence[Mapping[str, Any]],
                      target_bins: Sequence[Mapping[str, Any]], authority_id: str,
                      authority_status: str, cfg: Mapping[str, Any]) -> Dict[str, Any]:
    tmap = {_bin_key(r.get("bin_low"), r.get("bin_high"), r.get("bin_label")): r for r in target_bins}
    detail = []
    abs_sum = sq_sum = 0.0
    model_mean_num = model_den = 0.0
    target_mean_num = target_den = 0.0
    short_excess = mid_deficit = tail_excess = 0.0
    short_signed = mid_signed = tail_signed = 0.0
    for row in model_bins:
        lo = fval(row.get("bin_low"), None); hi = fval(row.get("bin_high"), None)
        if lo is None or hi is None:
            continue
        key = _bin_key(lo, hi, row.get("bin_label"))
        model = max(0.0, fval(row.get("share_conditioned"), 0.0) or 0.0)
        target = max(0.0, fval((tmap.get(key) or {}).get("target_share"), 0.0) or 0.0)
        diff = model - target
        mid = 0.5 * (float(lo) + float(hi))
        abs_sum += abs(diff); sq_sum += diff * diff
        model_mean_num += mid * model; model_den += model
        target_mean_num += mid * target; target_den += target
        if family != "LONG":
            if float(lo) < 1.0 + 1.0e-9:
                short_excess += max(0.0, diff)
                short_signed += diff
            if float(lo) >= 1.0 - 1.0e-9 and float(hi) <= 15.0 + 1.0e-9:
                mid_deficit += max(0.0, -diff)
                mid_signed += diff
            if float(lo) >= 25.0 - 1.0e-9:
                tail_excess += max(0.0, diff)
                tail_signed += diff
        else:
            if float(lo) < 120.0 + 1.0e-9:
                short_excess += max(0.0, diff)
                short_signed += diff
            if float(lo) >= 120.0 - 1.0e-9 and float(hi) <= 150.0 + 1.0e-9:
                mid_deficit += max(0.0, -diff)
                mid_signed += diff
            if float(lo) >= 150.0 - 1.0e-9:
                tail_excess += max(0.0, diff)
                tail_signed += diff
        detail.append({
            "bin_low": float(lo), "bin_high": float(hi), "model_share": model,
            "target_share": target, "share_diff_model_minus_target": diff,
        })
    model_keys = {_bin_key(r.get("bin_low"), r.get("bin_high"), r.get("bin_label")) for r in model_bins}
    target_keys = set(tmap)
    missing_target_bins = sorted(target_keys - model_keys)
    missing_model_targets = sorted(model_keys - target_keys)
    target_coverage = sum(max(0.0, fval((tmap.get(k) or {}).get("target_share"), 0.0) or 0.0) for k in (target_keys & model_keys))
    authority_complete = bool(target_keys and not missing_target_bins and not missing_model_targets and target_coverage >= 1.0 - 1.0e-6)
    model_mean = model_mean_num / model_den if model_den > EPS else fval(summary.get("mean_model_conditioned"), None)
    target_mean = target_mean_num / target_den if target_den > EPS else fval(summary.get("mean_target"), None)
    l1 = 0.5 * abs_sum
    rmse = math.sqrt(sq_sum / max(1, len(detail))) if detail else float("inf")
    mean_delta = (model_mean - target_mean) if model_mean is not None and target_mean is not None else None
    target_status = sval(summary.get("target_status", authority_status))
    allowed, policy_reason = _component_policy(component, family, cfg, target_status)
    calibratable = bool(allowed and detail and target_den > EPS and authority_complete)
    if allowed and not authority_complete:
        policy_reason = "INCOMPLETE_OR_MISMATCHED_BIN_AUTHORITY"
    return {
        "component": component,
        "family": family,
        "matrix_no": matrix_no,
        "dstrat_code": dstrat_code,
        "target_status": target_status,
        "authority_status": authority_status,
        "authority_id": authority_id,
        "policy_reason": policy_reason,
        "calibratable": calibratable,
        "conditioned_volume": fval(summary.get("conditioned_volume"), 0.0) or 0.0,
        "total_volume": fval(summary.get("total_volume"), 0.0) or 0.0,
        "mean_model": model_mean,
        "mean_target": target_mean,
        "mean_delta": mean_delta,
        "l1_half": l1,
        "rmse_share": rmse,
        "short_excess": short_excess,
        "mid_deficit": mid_deficit,
        "tail_excess": tail_excess,
        "short_signed": short_signed,
        "mid_signed": mid_signed,
        "tail_signed": tail_signed,
        "authority_complete": authority_complete,
        "target_bin_coverage": target_coverage,
        "missing_target_bins": missing_target_bins,
        "missing_model_targets": missing_model_targets,
        "model_bins": detail,
        "objective": l1 + 0.5 * (abs(mean_delta) / max(EPS, target_mean) if mean_delta is not None and target_mean else 0.0) + 0.25 * rmse,
    }


def build_td_signals(summary_rows: Sequence[Mapping[str, Any]],
                     compare_rows: Sequence[Mapping[str, Any]],
                     baseline_rows: Sequence[Mapping[str, Any]],
                     long_authority: Optional[Mapping[str, Any]] = None,
                     config: Optional[Mapping[str, Any]] = None) -> Dict[str, Dict[str, Any]]:
    """Build component signals from fresh 11D output and explicit authorities."""
    cfg = config or {}
    smap = _row_map(summary_rows, "component")
    model_by_comp: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    target_by_comp: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in baseline_rows or []:
        comp = sval(row.get("component", "")).strip()
        if comp:
            model_by_comp[comp].append(dict(row))
    for row in compare_rows or []:
        comp = sval(row.get("component", "")).strip()
        if comp:
            target_by_comp[comp].append(dict(row))

    long_auth = dict(long_authority or {})
    long_components = long_auth.get("component_targets", {}) or {}
    signals: Dict[str, Dict[str, Any]] = {}
    for comp, reg in COMPONENT_REGISTRY.items():
        summary = smap.get(comp, {})
        family = reg["family"]
        model_bins = model_by_comp.get(comp, [])
        if family == "LONG":
            auth = long_components.get(comp)
            if not auth:
                signals[comp] = {
                    "component": comp, "family": family, "matrix_no": reg["matrix_no"],
                    "dstrat_code": reg["dstrat_code"], "target_status": sval(summary.get("target_status", "")),
                    "authority_status": "NO_COMPONENT_LONG_AUTHORITY",
                    "authority_id": sval(long_auth.get("authority_id", "")),
                    "policy_reason": "AGGREGATE_CL_TARGET_IS_GUARD_ONLY",
                    "calibratable": False,
                    "conditioned_volume": fval(summary.get("conditioned_volume"), 0.0) or 0.0,
                    "total_volume": fval(summary.get("total_volume"), 0.0) or 0.0,
                    "mean_model": fval(summary.get("mean_model_conditioned"), None),
                    "mean_target": None, "mean_delta": None,
                    "l1_half": None, "rmse_share": None, "short_excess": 0.0,
                    "mid_deficit": 0.0, "tail_excess": 0.0, "model_bins": [],
                    "objective": float("inf"),
                }
                continue
            target_bins = _normalized_target_bins(auth.get("bins", []))
            signals[comp] = _signal_from_bins(
                comp, family, reg["matrix_no"], reg["dstrat_code"], summary,
                model_bins, target_bins, sval(long_auth.get("authority_id", "LONG_COMPONENT_AUTHORITY")),
                sval(auth.get("status", "ACTIVE_LONG_COMPONENT_TARGET")), cfg,
            )
            continue
        signals[comp] = _signal_from_bins(
            comp, family, reg["matrix_no"], reg["dstrat_code"], summary,
            model_bins, target_by_comp.get(comp, []),
            "11D_ACTIVE_COMPONENT_DIST_TARGET", sval(summary.get("target_status", "")), cfg,
        )

    if long_composite_enabled(cfg):
        composite_summary, composite_model_bins = _aggregate_long_model_bins(smap, model_by_comp)
        aggregate = dict(long_auth.get("aggregate_cl_guard", {}) or {})
        target_bins = _normalized_target_bins(aggregate.get("bins", []))
        signals["LONG_COMPOSITE"] = _signal_from_bins(
            "LONG_COMPOSITE", "LONG", 0, "GLOBAL_LONG_MIX", composite_summary,
            composite_model_bins, target_bins,
            sval(long_auth.get("authority_id", "GLOBAL_LONG_MIX_AUTHORITY")),
            "ACTIVE_GLOBAL_LONG_MIX_TARGET", cfg,
        )
        signals["LONG_COMPOSITE"]["source_components"] = composite_summary.get("source_components", [])
        signals["LONG_COMPOSITE"]["acceptance_role"] = "GLOBAL_LONG_MIX"
    return signals


def _family_min_volume(family: str, td_cfg: Mapping[str, Any]) -> float:
    if family == "LONG":
        return float(td_cfg.get("long_min_conditioned_volume", 80.0))
    if family == "SCHOOL":
        return float(td_cfg.get("school_min_conditioned_volume", 500.0))
    return float(td_cfg.get("min_conditioned_volume", 1000.0))


def design_td_candidates(signals: Mapping[str, Mapping[str, Any]],
                         current_parameters: Mapping[str, Mapping[str, Any]],
                         family: str, cfg: Mapping[str, Any], scale: float = 1.0) -> Dict[str, Any]:
    """Create bounded component-specific b/c proposals.

    The unscaled trust-region delta is computed once.  ``scale`` is applied once
    at materialization, preventing the historical double-backtracking bug.
    """
    td_cfg = cfg.get("td", {})
    family_u = sval(family).upper().replace("SERV", "SERVICE")
    scale = clamp(float(scale), 0.0, 1.0)
    candidates: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    ranked: List[Tuple[float, str, Dict[str, Any]]] = []
    for comp, sig0 in signals.items():
        sig = dict(sig0)
        if sval(sig.get("family", "")).upper().replace("SERV", "SERVICE") != family_u:
            continue
        cur = current_parameters.get(comp)
        if not cur:
            skipped.append({"component": comp, "reason": "TD_PARAMETER_NOT_READ"}); continue
        if not bool(sig.get("calibratable", False)):
            skipped.append({"component": comp, "reason": sval(sig.get("authority_status", "NOT_CALIBRATABLE")), "policy_reason": sig.get("policy_reason", "")}); continue
        volume = float(sig.get("conditioned_volume", 0.0) or 0.0)
        if volume < _family_min_volume(family_u, td_cfg):
            skipped.append({"component": comp, "reason": "LOW_CONDITIONED_VOLUME", "conditioned_volume": volume}); continue
        b = fval(cur.get("current_b"), None); c = fval(cur.get("current_c"), None)
        if b is None or c is None:
            skipped.append({"component": comp, "reason": "B_OR_C_UNREADABLE"}); continue
        l1 = float(sig.get("l1_half", 0.0) or 0.0)
        mean_target = fval(sig.get("mean_target"), None); mean_delta = fval(sig.get("mean_delta"), 0.0) or 0.0
        mean_rel = mean_delta / max(EPS, abs(mean_target)) if mean_target not in (None, 0.0) else 0.0
        if l1 < float(td_cfg.get("min_l1_for_mutation", 0.06)) and abs(mean_rel) < float(td_cfg.get("mean_relative_deadband", 0.01)):
            skipped.append({"component": comp, "reason": "WITHIN_TD_DEADBAND", "l1_half": l1, "mean_relative_error": mean_rel}); continue
        short = float(sig.get("short_excess", 0.0) or 0.0)
        mid_deficit = float(sig.get("mid_deficit", 0.0) or 0.0)
        tail = float(sig.get("tail_excess", 0.0) or 0.0)
        short_signed = float(sig.get("short_signed", short) or 0.0)
        mid_signed = float(sig.get("mid_signed", -mid_deficit) or 0.0)
        tail_signed = float(sig.get("tail_signed", tail) or 0.0)
        # Positive b suppresses an excess of the shortest relations and refills
        # the middle. The signed form also allows b to decrease when the model
        # has too few shortest trips and too much middle-distance mass.
        shape_signal = short_signed - mid_signed
        raw_db = float(td_cfg.get("b_shape_gain", 0.40)) * shape_signal
        # More negative c shortens an overlong distribution; a tail deficit or
        # a too-short mean produces a positive delta (less negative c).
        raw_dc = (
            -float(td_cfg.get("c_mean_gain", 0.18)) * mean_rel
            -float(td_cfg.get("c_tail_gain", 0.12)) * tail_signed
            -float(td_cfg.get("c_b_compensation", 0.35)) * raw_db
        )
        if family_u == "LONG":
            raw_db *= float(td_cfg.get("long_b_gain_multiplier", 0.25))
            raw_dc *= float(td_cfg.get("long_c_gain_multiplier", 0.50))
            max_db = float(td_cfg.get("long_max_abs_b_delta", td_cfg.get("max_abs_b_delta", 0.08)))
            max_dc = float(td_cfg.get("long_max_abs_c_delta", td_cfg.get("max_abs_c_delta", 0.04)))
        else:
            max_db = float(td_cfg.get("max_abs_b_delta", 0.08))
            max_dc = float(td_cfg.get("max_abs_c_delta", 0.04))
        raw_db = clamp(raw_db, -max_db, max_db)
        raw_dc = clamp(raw_dc, -max_dc, max_dc)
        db = raw_db * scale
        dc = raw_dc * scale
        cand_b = clamp(float(b) + db, float(td_cfg.get("b_min", 0.0)), float(td_cfg.get("b_max", 5.0)))
        cand_c = clamp(float(c) + dc, float(td_cfg.get("c_min", -3.0)), float(td_cfg.get("c_max", 0.0)))
        priority = float(sig.get("objective", 0.0) or 0.0) * math.sqrt(max(1.0, volume))
        row = {
            "component": comp, "family": family_u, "dstrat_code": cur.get("dstrat_code", sig.get("dstrat_code", "")),
            "matrix_no": sig.get("matrix_no", ""), "authority_id": sig.get("authority_id", ""),
            "current_b": float(b), "current_c": float(c),
            "raw_delta_b": raw_db, "raw_delta_c": raw_dc,
            "backtracking_scale": scale, "delta_b": cand_b - float(b), "delta_c": cand_c - float(c),
            "candidate_b": cand_b, "candidate_c": cand_c,
            "conditioned_volume": volume, "l1_half": l1, "rmse_share": sig.get("rmse_share"),
            "mean_model": sig.get("mean_model"), "mean_target": mean_target,
            "mean_relative_error": mean_rel, "short_excess": short,
            "mid_deficit": mid_deficit, "tail_excess": tail,
            "short_signed": short_signed, "mid_signed": mid_signed,
            "tail_signed": tail_signed, "shape_signal": shape_signal,
            "priority": priority,
        }
        if abs(row["delta_b"]) <= 1.0e-12 and abs(row["delta_c"]) <= 1.0e-12:
            skipped.append({"component": comp, "reason": "CLAMPED_TO_NO_CHANGE"}); continue
        ranked.append((priority, comp, row))
    ranked.sort(key=lambda x: (-x[0], x[1]))
    max_components = max(1, int(td_cfg.get("max_components_per_block", 2)))
    candidates = [row for _, _, row in ranked[:max_components]]
    for _, comp, row in ranked[max_components:]:
        skipped.append({"component": comp, "reason": "DEFERRED_BY_COMPONENT_LIMIT", "priority": row["priority"]})
    return {
        "candidate_rows": candidates,
        "skipped_rows": skipped,
        "summary": {
            "family": family_u, "candidate_count": len(candidates), "skipped_count": len(skipped),
            "scale_applied_once": True, "backtracking_scale": scale,
            "selected_components": [r["component"] for r in candidates],
        },
    }


def td_component_metrics(signals: Mapping[str, Mapping[str, Any]], components: Sequence[str], cfg: Mapping[str, Any]) -> Dict[str, Any]:
    td_cfg = cfg.get("td", {})
    rows = []
    num = den = 0.0
    for comp in components:
        sig = signals.get(comp)
        if not sig or not bool(sig.get("calibratable", False)):
            continue
        l1 = float(sig.get("l1_half", 0.0) or 0.0)
        rmse = float(sig.get("rmse_share", 0.0) or 0.0)
        target = fval(sig.get("mean_target"), None); delta = fval(sig.get("mean_delta"), 0.0) or 0.0
        mean_rel = abs(delta) / max(EPS, abs(target)) if target not in (None, 0.0) else 0.0
        objective = (
            float(td_cfg.get("td_objective_l1_weight", 1.0)) * l1
            + float(td_cfg.get("td_objective_mean_weight", 0.5)) * mean_rel
            + float(td_cfg.get("td_objective_rmse_weight", 0.25)) * rmse
        )
        weight = math.sqrt(max(1.0, float(sig.get("conditioned_volume", 0.0) or 0.0)))
        num += weight * objective; den += weight
        rows.append({"component": comp, "objective": objective, "weight": weight, "l1_half": l1, "mean_relative_error": mean_rel, "rmse_share": rmse})
    return {"n": len(rows), "weighted_objective": num / den if den > EPS else float("inf"), "components": rows}


def _zone_lookup(zone_rows: Sequence[Mapping[str, Any]]) -> Dict[int, Dict[str, Any]]:
    out = {}
    for row in zone_rows or []:
        z = ival(row.get("zone_no"), None)
        if z is not None:
            out[int(z)] = dict(row)
    return out


def _eligible_zone(row: Mapping[str, Any], cfg: Mapping[str, Any]) -> Tuple[bool, str]:
    z = ival(row.get("zone_no"), None)
    excluded = set(int(x) for x in cfg.get("explicit_excluded_zone_nos", []) or [])
    excluded.update(int(x) for x in cfg.get("zahr", {}).get("explicit_excluded_zone_nos", []) or [])
    if z in excluded:
        return False, "EXPLICIT_EXCLUSION"
    return True, "OK"


def _salary_joint_design(work_rows: Sequence[Dict[str, Any]], zone_map: Mapping[int, Mapping[str, Any]],
                         cfg: Mapping[str, Any], scale: float) -> Tuple[Dict[int, float], Dict[int, float], Dict[str, Any]]:
    """Split WORK attraction log effects into ADD_ATT_W residual and salary basis.

    A single centred log-income coefficient is used.  This avoids a second free
    zone residual that would be non-identifiable with ADD_ATT_W.
    """
    salary_cfg = cfg.get("salary", {})
    if not salary_cfg.get("enabled", True) or not work_rows:
        return {}, {}, {"enabled": False, "status": "DISABLED_OR_EMPTY"}
    income_attr = sval(salary_cfg.get("income_attr", "AV_INCOME"))
    salary_attr = sval(salary_cfg.get("salary_attr", "ADD_SALARY"))
    offset = float(salary_cfg.get("formula_offset", 1000.0))
    denom = float(salary_cfg.get("formula_denominator", 2700.0))
    factor_floor = float(salary_cfg.get("factor_floor", 0.05))
    items = []
    logs = []
    for p in work_rows:
        z = int(p["zone_no"]); zr = zone_map.get(z, {})
        income = fval(zr.get(income_attr), None); salary = fval(zr.get(salary_attr), None)
        add_att_attr = sval(salary_cfg.get("work_attraction_attr", "ADD_ATT_W"))
        add_att = fval(zr.get(add_att_attr), None)
        if income is None or salary is None or add_att is None or income <= 0 or add_att <= EPS:
            continue
        g = 1.0 + (income * salary - offset) / denom
        if g <= factor_floor:
            continue
        logs.append(math.log(max(income, EPS)))
        items.append((z, float(p["requested_log_step"]), income, salary, g, float(p.get("base_margin_volume", 1.0) or 1.0)))
    if len(items) < int(salary_cfg.get("min_eligible_zones", 8)):
        return {}, {}, {"enabled": True, "status": "ADD_ATT_ONLY_FALLBACK", "eligible_zones": len(items)}
    mean_log = sum(logs) / len(logs)
    # Ridge coefficient for u ~= a + h*x*beta.  The ADD_ATT residual a is
    # penalised by zone_add_ridge; beta by basis_ridge.  Closed form after
    # eliminating a: a=(u-hx beta)/(1+lambda_a).
    lam_a = max(0.0, float(salary_cfg.get("zone_add_ridge_lambda", 1.0)))
    lam_b = max(0.0, float(salary_cfg.get("basis_ridge_lambda", 0.2)))
    num = den_beta = 0.0
    packed = []
    for z, u, income, salary, g, weight in items:
        x = math.log(max(income, EPS)) - mean_log
        h = income / (denom * g)
        hx = h * x
        w = max(1.0, weight)
        shrink = lam_a / (1.0 + lam_a) if lam_a > 0 else 0.0
        num += w * shrink * hx * u
        den_beta += w * shrink * hx * hx
        packed.append((z, u, income, salary, g, hx))
    beta = num / max(EPS, den_beta + lam_b)
    max_delta = float(salary_cfg.get("max_abs_delta_per_block", 0.04)) * scale
    salary_delta = {}
    signed_policy = _signed_generation_policy(cfg)
    salary_soft_low = float(signed_policy.get("salary_soft_min", signed_policy.get("domestic_soft_min", 0.8))) if signed_policy else -float("inf")
    salary_soft_high = float(signed_policy.get("salary_soft_max", signed_policy.get("domestic_soft_max", 1.25))) if signed_policy else float("inf")
    salary_soft_factor = float(signed_policy.get("soft_outward_step_factor", 0.25)) if signed_policy else 1.0
    salary_bound_policy = "LIVE_CURRENT_VALUE_PLUS_BOUNDED_DELTA"
    add_att_residual = {}
    max_error = 0.0
    for z, u, income, salary, g, hx in packed:
        ds = clamp(beta * (math.log(max(income, EPS)) - mean_log), -max_delta, max_delta)
        salary_low, salary_high, salary_bound_policy = _salary_coefficient_bounds(cfg, current=salary)
        raw_salary_new = salary + ds
        if signed_policy:
            if ds > 0.0 and raw_salary_new > salary_soft_high:
                boundary = max(0.0, salary_soft_high - salary) if salary < salary_soft_high else 0.0
                ds = boundary + salary_soft_factor * (ds - boundary)
            elif ds < 0.0 and raw_salary_new < salary_soft_low:
                boundary = min(0.0, salary_soft_low - salary) if salary > salary_soft_low else 0.0
                ds = boundary + salary_soft_factor * (ds - boundary)
        salary_new = _require_finite_coefficient(
            clamp(salary + ds, salary_low, salary_high),
            "NONFINITE_SALARY_COEFFICIENT")
        new_factor = 1.0 + (income * salary_new - offset) / denom
        if new_factor <= factor_floor:
            # This is a formula-domain constraint, not an arbitrary coefficient cap.
            domain_floor = (offset + denom * (factor_floor - 1.0 + 1.0e-12)) / income
            salary_new = _require_finite_coefficient(
                clamp(max(salary_new, domain_floor), salary_low, salary_high),
                "NONFINITE_SALARY_DOMAIN_REPAIR")
            new_factor = 1.0 + (income * salary_new - offset) / denom
        exact_salary_log = math.log(max(factor_floor, new_factor) / g)
        residual = u - exact_salary_log
        salary_delta[z] = salary_new - salary
        add_att_residual[z] = residual
        max_error = max(max_error, abs(residual + exact_salary_log - u))
    return salary_delta, add_att_residual, {
        "enabled": True, "status": "JOINT_RIDGE_OK", "eligible_zones": len(items),
        "beta": beta, "max_abs_effect_log_error": max_error,
        "coefficient_authority": salary_bound_policy,
    }



def _generation_requested_margin_delta(row: Mapping[str, Any], alpha: float = 1.0) -> float:
    """Exact marginal change implied by the requested log effect.

    This is used only for the constrained generation proposal.  The accepted
    state is still decided by a fresh Visum recomputation and live diagnostics.
    """
    base = max(0.0, float(fval(row.get("base_margin_volume"), 0.0) or 0.0))
    step = float(fval(row.get("requested_log_step"), 0.0) or 0.0) * float(alpha)
    return base * math.expm1(step)


def _generation_role_scale(rows: Sequence[Mapping[str, Any]], target: float) -> Tuple[Optional[float], float]:
    """Find alpha in [0,1] so scaled role effect reaches ``target``.

    Scaling every log-effect on one P/A side preserves the spatial pattern of
    the path-guided proposal while attenuating only the side that has more
    implementable marginal change after parameter bounds are respected.
    """
    total = sum(_generation_requested_margin_delta(r) for r in rows)
    if abs(target) <= 1.0e-14:
        return 0.0, 0.0
    if abs(total - target) <= 1.0e-12 * max(1.0, abs(total), abs(target)):
        return 1.0, total
    # Attenuation can only reach a target lying between zero and the original
    # total.  Anything else remains a fail-closed gate condition.
    if total == 0.0 or target * total < 0.0 or abs(target) > abs(total) + 1.0e-12:
        return None, total
    lo, hi = 0.0, 1.0
    flo = -target
    fhi = total - target
    if abs(flo) <= 1.0e-14:
        return 0.0, 0.0
    if abs(fhi) <= 1.0e-14:
        return 1.0, total
    if flo * fhi > 0.0:
        return None, total
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        value = sum(_generation_requested_margin_delta(r, mid) for r in rows)
        fm = value - target
        if abs(fm) <= 1.0e-12 * max(1.0, abs(target)):
            return mid, value
        if flo * fm <= 0.0:
            hi = mid
            fhi = fm
        else:
            lo = mid
            flo = fm
    alpha = 0.5 * (lo + hi)
    value = sum(_generation_requested_margin_delta(r, alpha) for r in rows)
    return alpha, value



def _solve_centered_log_pattern(raw_centered: Sequence[float], weights: Sequence[float],
                                lower: Sequence[float], upper: Sequence[float]) -> Tuple[List[float], float, float]:
    """Return bounded centred log effects with zero nonlinear volume change.

    The scalar offset is solved so that ``sum(w * (exp(r)-1)) == 0``.  This is
    the correct centering condition for multiplicative zonal coefficients; a
    simple arithmetic mean would not conserve the family margin.
    """
    vals = [float(x) for x in raw_centered]
    ws = [max(0.0, float(x)) for x in weights]
    lo = [float(x) for x in lower]
    hi = [float(x) for x in upper]
    if not vals or sum(ws) <= EPS:
        return [0.0 for _ in vals], 0.0, 0.0

    def at(offset: float) -> Tuple[List[float], float]:
        out = [min(h, max(l, v - offset)) for v, l, h in zip(vals, lo, hi)]
        f = sum(w * math.expm1(x) for w, x in zip(ws, out))
        return out, f

    # Monotone in offset.  Expand deterministically until a bracket is found.
    left, right = -1.0, 1.0
    _, f_left = at(left)
    _, f_right = at(right)
    for _ in range(40):
        if f_left >= 0.0 and f_right <= 0.0:
            break
        if f_left < 0.0:
            left *= 2.0; _, f_left = at(left)
        if f_right > 0.0:
            right *= 2.0; _, f_right = at(right)
    if not (f_left >= -1.0e-12 and f_right <= 1.0e-12):
        raise ValueError("SIGNED_CENTERING_NO_FEASIBLE_ZERO_TOTAL_PATTERN")

    for _ in range(100):
        mid = 0.5 * (left + right)
        out, f_mid = at(mid)
        if abs(f_mid) <= 1.0e-12 * max(1.0, sum(ws)):
            return out, mid, f_mid
        if f_mid > 0.0:
            left = mid
        else:
            right = mid
    mid = 0.5 * (left + right)
    out, f_mid = at(mid)
    return out, mid, f_mid


def _signed_generation_refinement(normalized: Sequence[Mapping[str, Any]],
                                  zone_map: Mapping[int, Mapping[str, Any]],
                                  cfg: Mapping[str, Any],
                                  reference_values: Optional[Mapping[str, Any]],
                                  skipped: List[Dict[str, Any]],
                                  min_step: float) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Split Generation into shared family scale + centred zonal correction.

    This is the V2.4.9.2 contract requested for later demand refinement.  The
    global family effect controls the total P/A volume.  The centred zonal
    effect can simultaneously increase one zone and decrease another while its
    nonlinear weighted total remains zero.  Production and attraction receive
    one shared family total, so local redistribution cannot create a P/A gap.
    """
    policy = _signed_generation_policy(cfg)
    if not policy:
        return [dict(r) for r in normalized], {
            "enabled": False, "mode": "LEGACY_OR_POSITIVE_ONLY",
            "groups": {}, "families": {}, "soft_damped_count": 0,
        }

    max_up = float(cfg.get("max_add_log_up", 0.04))
    max_down = float(cfg.get("max_add_log_down", 0.04))
    global_up = float(policy.get("max_family_global_log_up", max_up))
    global_down = float(policy.get("max_family_global_log_down", max_down))
    soft_factor = float(policy.get("soft_outward_step_factor", 0.25))
    rows = [dict(r) for r in normalized]
    soft_damped = []

    # Attach per-row domains and damp only outward motion beyond the empirical
    # soft envelope.  These domains are also used by nonlinear centering.
    for row in rows:
        z = int(row["zone_no"]); attr = sval(row["attr"]); branch = sval(row["branch"]).upper()
        current = fval((zone_map.get(z) or {}).get(attr), None)
        if current is None or current <= EPS:
            row["_signed_step_low"] = -max_down
            row["_signed_step_high"] = max_up
            continue
        reference = _reference_coefficient(reference_values, attr, z, float(current))
        low, high, envelope = _multiplicative_coefficient_bounds(
            branch, cfg, current=float(current), reference=reference)
        step_low = max(-max_down, math.log(max(EPS, low) / float(current)) if low > 0.0 else -max_down)
        step_high = min(max_up, math.log(max(EPS, high) / float(current)) if high > 0.0 else -max_down)
        requested = float(row.get("requested_log_step", 0.0) or 0.0)
        soft_low, soft_high = _soft_multiplier_bounds(branch, cfg, float(current), reference)
        damped, changed = _damp_outward_log_step(float(current), requested,
                                                 soft_low, soft_high, soft_factor)
        bounded = min(step_high, max(step_low, damped))
        row.update({
            "signed_raw_requested_log_step": requested,
            "requested_log_step": bounded,
            "_signed_step_low": step_low,
            "_signed_step_high": step_high,
            "coefficient_hard_low": low,
            "coefficient_hard_high": high,
            "coefficient_soft_low": soft_low,
            "coefficient_soft_high": soft_high,
            "coefficient_reference": reference,
            "coefficient_envelope": envelope,
        })
        if changed or abs(bounded - requested) > 1.0e-15:
            soft_damped.append({
                "zone_no": z, "attr": attr, "family": row["family"], "role": row["role"],
                "current": float(current), "reference": reference,
                "raw_log_step": requested, "soft_damped_log_step": damped,
                "bounded_log_step": bounded, "soft_low": soft_low, "soft_high": soft_high,
                "hard_low": low, "hard_high": high,
            })

    groups: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[(sval(row["family"]).upper(), sval(row["role"]).upper())].append(row)

    group_audit: Dict[str, Any] = {}
    group_state: Dict[Tuple[str, str], Dict[str, Any]] = {}

    def apply_group(group_rows: List[Dict[str, Any]], global_log: float) -> Dict[str, Any]:
        weights = [max(0.0, float(r.get("base_margin_volume", 0.0) or 0.0)) for r in group_rows]
        total_base = sum(weights)
        if total_base <= EPS:
            return {"rows": group_rows, "base_total": total_base, "global_log": 0.0,
                    "total_delta": 0.0, "centering_residual": 0.0, "status": "NO_BASE_VOLUME"}
        raw_steps = [float(r.get("requested_log_step", 0.0) or 0.0) for r in group_rows]
        raw_global = math.log(sum(w * math.exp(s) for w, s in zip(weights, raw_steps)) / total_base)
        raw_centered = [s - raw_global for s in raw_steps]
        g = clamp(float(global_log), -global_down, global_up)
        lower = [float(r.get("_signed_step_low", -max_down)) - g for r in group_rows]
        upper = [float(r.get("_signed_step_high", max_up)) - g for r in group_rows]
        centered, offset, residual = _solve_centered_log_pattern(raw_centered, weights, lower, upper)
        for row, raw, centre in zip(group_rows, raw_steps, centered):
            row["signed_pre_center_log_step"] = raw
            row["signed_global_log_step_raw"] = raw_global
            row["signed_global_log_step"] = g
            row["signed_centered_log_step"] = centre
            row["signed_centering_offset"] = offset
            row["requested_log_step"] = g + centre
            row["guided_margin_delta"] = _generation_requested_margin_delta(row)
            row["projected_margin_delta"] = _generation_requested_margin_delta(row)
        total_delta = sum(w * math.expm1(g + c) for w, c in zip(weights, centered))
        return {"rows": group_rows, "base_total": total_base, "raw_global_log": raw_global,
                "global_log": g, "total_delta": total_delta,
                "centering_residual": residual, "status": "CENTERED"}

    # First determine each role's raw/capped global signal.
    for key, group_rows in groups.items():
        weights = [max(0.0, float(r.get("base_margin_volume", 0.0) or 0.0)) for r in group_rows]
        total = sum(weights)
        if total <= EPS:
            state = apply_group(group_rows, 0.0)
        else:
            raw = math.log(sum(w * math.exp(float(r.get("requested_log_step", 0.0) or 0.0))
                               for w, r in zip(weights, group_rows)) / total)
            state = apply_group(group_rows, clamp(raw, -global_down, global_up))
        group_state[key] = state

    family_audit: Dict[str, Any] = {}
    opposite_policy = sval(policy.get("opposite_sign_total_policy",
                                      "ZERO_GLOBAL_KEEP_CENTERED_PATTERN")).upper()
    for family in sorted(set(k[0] for k in group_state)):
        prod = group_state.get((family, "PROD"))
        att = group_state.get((family, "ATT"))
        if not prod or not att:
            family_audit[family] = {"status": "MISSING_ROLE", "target_delta": None}
            continue
        p0 = float(prod["total_delta"]); a0 = float(att["total_delta"])
        if p0 * a0 < 0.0:
            if opposite_policy != "ZERO_GLOBAL_KEEP_CENTERED_PATTERN":
                raise ValueError("SIGNED_OPPOSITE_TOTAL_POLICY_UNSUPPORTED")
            target = 0.0
            status = "OPPOSITE_SIGN_GLOBAL_REMOVED"
        elif abs(p0) <= 1.0e-14 or abs(a0) <= 1.0e-14:
            target = 0.0
            status = "ONE_ROLE_GLOBAL_ZERO"
        else:
            target = math.copysign(min(abs(p0), abs(a0)), p0)
            status = "COMMON_CONSERVATIVE_FAMILY_TOTAL"
        for role, state in (("PROD", prod), ("ATT", att)):
            base_total = float(state["base_total"])
            if base_total <= EPS or target <= -base_total:
                raise ValueError("SIGNED_FAMILY_GLOBAL_TARGET_OUTSIDE_DOMAIN")
            target_global = math.log1p(target / base_total)
            group_state[(family, role)] = apply_group(
                groups[(family, role)], clamp(target_global, -global_down, global_up))
        p1 = float(group_state[(family, "PROD")]["total_delta"])
        a1 = float(group_state[(family, "ATT")]["total_delta"])
        rel = abs(p1 - a1) / max(1.0, abs(p1), abs(a1))
        family_audit[family] = {
            "status": status, "prod_delta_before": p0, "att_delta_before": a0,
            "target_common_delta": target, "prod_delta_after": p1,
            "att_delta_after": a1, "relative_gap_after": rel,
        }

    final_rows = []
    for row in rows:
        for key in ("_signed_step_low", "_signed_step_high"):
            row.pop(key, None)
        if abs(float(row.get("requested_log_step", 0.0) or 0.0)) < min_step:
            skipped.append(dict(row, reason="SIGNED_CENTERING_TO_NO_IMPLEMENTED_EFFECT"))
        else:
            final_rows.append(row)
    for key, state in group_state.items():
        group_audit["%s_%s" % key] = {k: v for k, v in state.items() if k != "rows"}
    return final_rows, {
        "enabled": True,
        "mode": "FAMILY_GLOBAL_PLUS_NONLINEAR_CENTERED_ZONE_LOG_EFFECT",
        "global_total_policy": "COMMON_CONSERVATIVE_FAMILY_TOTAL",
        "opposite_sign_total_policy": opposite_policy,
        "max_family_global_log_up": global_up,
        "max_family_global_log_down": global_down,
        "max_zone_log_up": max_up,
        "max_zone_log_down": max_down,
        "soft_outward_step_factor": soft_factor,
        "soft_damped_count": len(soft_damped),
        "soft_damped_rows": soft_damped,
        "groups": group_audit,
        "families": family_audit,
        "reference_role": "RUN_START_COEFFICIENT_REFERENCE_FOR_ZAHR",
        "acceptance_authority": "FRESH_VISUM_ASSIGNMENT_PLUS_LIVE_12D_11D",
    }


def _constrain_generation_projection(normalized: Sequence[Mapping[str, Any]],
                                     zone_map: Mapping[int, Mapping[str, Any]],
                                     cfg: Mapping[str, Any],
                                     skipped: List[Dict[str, Any]],
                                     min_step: float,
                                     reference_values: Optional[Mapping[str, Any]] = None) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Make generation guidance feasible under hard actuator bounds.

    V2.4.8.4 exposed a case where a ZAHR production coefficient equalled a
    historical configuration value (10.0), yet the balanced P/A projection
    requested a further positive effect.  Treating 10.0 as a hard maximum was
    incorrect because the zonal attributes are calibration coefficients.  The
    legacy mapper clamped that row to no change
    *after* projection, leaving the opposite attraction side intact and thus
    creating a deterministic P/A gap.  Backtracking could not cure the relative
    gap because the same saturated row remained unavailable at every scale.

    V2.4.8.7 uses the current live value plus the configured relative log-step
    as the coefficient authority.  It constrains only real formula domains or
    explicit preserved-zero states, records any lost request, then attenuates the larger P/A
    side within each family to the smaller implementable side.  This preserves
    the proposal's spatial pattern and never invents capacity.  Joint
    WORK-attraction ADD_ATT_W+salary rows are intentionally left to the existing
    exact joint mapper because they have two actuators.
    """
    policy = cfg.get("generation_bound_constrained_projection", {}) or {}
    if policy.get("enabled") is not True:
        return [dict(r) for r in normalized], {
            "enabled": False,
            "policy": "LEGACY_POST_PROJECTION_CLAMP",
            "clipped_count": 0,
            "role_rebalance": {},
            "unresolved_families": [],
        }

    zcfg = cfg.get("zahr", {})
    live_authority = _live_coefficient_authority(cfg)
    preserve_zero_zahr = bool(zcfg.get("preserve_zero", True))
    preserve_zero_domestic = bool(cfg.get("preserve_zero_add", True))
    clipped_audit: List[Dict[str, Any]] = []
    active: List[Dict[str, Any]] = []

    for source in normalized:
        row = dict(source)
        z = int(row["zone_no"]); zr = zone_map[z]
        requested = float(row.get("requested_log_step", 0.0) or 0.0)
        # WORK domestic attraction is normally a joint ADD_ATT_W + ADD_SALARY
        # actuator.  A preserved zero ADD_ATT_W, however, makes the whole
        # multiplicative term unavailable even if salary could move; treat it
        # like every other zero-capacity actuator before P/A balancing.
        joint_work_att = (row["family"], row["role"], row["branch"]) == ("WORK", "ATT", "DOMESTIC")
        current = fval(zr.get(row["attr"]), None)
        reference = _reference_coefficient(reference_values, row["attr"], z,
                                           float(current) if current is not None else 0.0)
        low, high, coefficient_policy = _multiplicative_coefficient_bounds(
            row["branch"], cfg, current=current, reference=reference)
        preserve_zero = preserve_zero_zahr if row["branch"] == "ZAHR" else preserve_zero_domestic
        seed_floor = (float(zcfg.get("seed_floor", 0.0)) if row["branch"] == "ZAHR"
                      else float(cfg.get("add_seed_floor", 0.0)))
        if current is None:
            # Unreadable values remain fail-closed in the existing mapper/gate.
            active.append(row)
            continue
        if float(current) <= EPS:
            if preserve_zero or seed_floor <= EPS:
                audit = dict(row)
                audit.update({
                    "reason": "ZERO_CAPACITY_CONSTRAINED_PROJECTION",
                    "current": float(current),
                    "lower_bound": low,
                    "upper_bound": high if math.isfinite(high) else None,
                    "coefficient_authority": coefficient_policy,
                    "projection_requested_log_step": requested,
                    "constrained_requested_log_step": 0.0,
                    "projection_requested_margin_delta": _generation_requested_margin_delta(row),
                })
                clipped_audit.append(audit)
                skipped.append(dict(audit, reason="PRESERVED_ZERO_CONSTRAINED_PROJECTION"))
                continue
            old = seed_floor
        else:
            old = float(current)
        if joint_work_att and float(current) > EPS:
            active.append(row)
            continue
        lo_log = -float("inf") if low <= 0.0 else math.log(max(EPS, low) / old)
        hi_log = math.log(max(EPS, high) / old) if high > 0.0 else -float("inf")
        constrained = min(hi_log, max(lo_log, requested))
        if abs(constrained - requested) > 1.0e-12:
            audit = dict(row)
            audit.update({
                "reason": "BOUND_CONSTRAINED_PROJECTION",
                "current": old,
                "lower_bound": low,
                "upper_bound": high if math.isfinite(high) else None,
                "coefficient_authority": coefficient_policy,
                "projection_requested_log_step": requested,
                "constrained_requested_log_step": constrained,
                "projection_requested_margin_delta": _generation_requested_margin_delta(row),
            })
            clipped_audit.append(audit)
            row["projection_requested_log_step"] = requested
            row["requested_log_step"] = constrained
            row["projection_guided_margin_delta"] = row.get("guided_margin_delta")
            row["projection_projected_margin_delta"] = row.get("projected_margin_delta")
            row["guided_margin_delta"] = _generation_requested_margin_delta(row)
            row["projected_margin_delta"] = _generation_requested_margin_delta(row)
        if abs(float(row.get("requested_log_step", 0.0) or 0.0)) < min_step:
            audit = dict(row)
            audit.update({"reason": "BOUND_SATURATED_CONSTRAINED_PROJECTION", "current": old,
                          "lower_bound": low,
                          "upper_bound": high if math.isfinite(high) else None,
                          "coefficient_authority": coefficient_policy})
            skipped.append(audit)
            continue
        active.append(row)

    role_audit: Dict[str, Any] = {}
    unresolved: List[str] = []
    balance_tol = float(policy.get("relative_balance_tolerance", 1.0e-10))
    for family in ("WORK", "SERVICE"):
        fam = [r for r in active if r["family"] == family]
        prod = [r for r in fam if r["role"] == "PROD"]
        att = [r for r in fam if r["role"] == "ATT"]
        p0 = sum(_generation_requested_margin_delta(r) for r in prod)
        a0 = sum(_generation_requested_margin_delta(r) for r in att)
        rel0 = abs(p0 - a0) / max(1.0, abs(p0), abs(a0))
        rec: Dict[str, Any] = {
            "requested_prod_delta_before": p0,
            "requested_att_delta_before": a0,
            "relative_gap_before": rel0,
            "scaled_role": None,
            "scale": 1.0,
        }
        if rel0 <= balance_tol:
            rec.update({"requested_prod_delta_after": p0, "requested_att_delta_after": a0,
                        "relative_gap_after": rel0, "status": "ALREADY_BALANCED"})
            role_audit[family] = rec
            continue
        # If the two sides request opposite directions, attenuation cannot make
        # the proposal P/A-consistent without changing its sign.  Leave it for
        # the unchanged hard generation gate to reject.
        if p0 * a0 < 0.0:
            rec.update({"status": "OPPOSITE_SIGN_UNRESOLVED",
                        "requested_prod_delta_after": p0, "requested_att_delta_after": a0,
                        "relative_gap_after": rel0})
            unresolved.append(family)
            role_audit[family] = rec
            continue
        if abs(p0) >= abs(a0):
            scaled_role, rows_to_scale, target = "PROD", prod, a0
        else:
            scaled_role, rows_to_scale, target = "ATT", att, p0
        alpha, achieved = _generation_role_scale(rows_to_scale, target)
        if alpha is None:
            rec.update({"status": "ATTENUATION_UNRESOLVED", "scaled_role": scaled_role,
                        "requested_prod_delta_after": p0, "requested_att_delta_after": a0,
                        "relative_gap_after": rel0})
            unresolved.append(family)
            role_audit[family] = rec
            continue
        for row in rows_to_scale:
            old_step = float(row.get("requested_log_step", 0.0) or 0.0)
            if alpha < 1.0 - 1.0e-15:
                row["pre_pa_rebalance_requested_log_step"] = old_step
                row["pa_rebalance_factor"] = alpha
                row["requested_log_step"] = old_step * alpha
                row["pre_pa_rebalance_guided_margin_delta"] = row.get("guided_margin_delta")
                row["pre_pa_rebalance_projected_margin_delta"] = row.get("projected_margin_delta")
                row["guided_margin_delta"] = _generation_requested_margin_delta(row)
                row["projected_margin_delta"] = _generation_requested_margin_delta(row)
        p1 = sum(_generation_requested_margin_delta(r) for r in prod)
        a1 = sum(_generation_requested_margin_delta(r) for r in att)
        rel1 = abs(p1 - a1) / max(1.0, abs(p1), abs(a1))
        rec.update({
            "status": "BALANCED_BY_ROLE_ATTENUATION" if rel1 <= balance_tol else "BALANCE_TOLERANCE_NOT_MET",
            "scaled_role": scaled_role,
            "scale": alpha,
            "target_delta": target,
            "achieved_scaled_role_delta": achieved,
            "requested_prod_delta_after": p1,
            "requested_att_delta_after": a1,
            "relative_gap_after": rel1,
        })
        if rel1 > balance_tol:
            unresolved.append(family)
        role_audit[family] = rec

    # Remove rows attenuated effectively to zero; keep an explicit audit row.
    final_rows: List[Dict[str, Any]] = []
    for row in active:
        if abs(float(row.get("requested_log_step", 0.0) or 0.0)) < min_step:
            skipped.append(dict(row, reason="PA_REBALANCE_TO_NO_IMPLEMENTED_EFFECT"))
        else:
            final_rows.append(row)
    return final_rows, {
        "enabled": True,
        "policy": ("SIGNED_LIVE_CURRENT_VALUE_WITH_EMPIRICAL_ENVELOPE_THEN_PA_REBALANCE"
                   if _signed_generation_policy(cfg) else
                   "LIVE_CURRENT_VALUE_RELATIVE_LOG_STEP_THEN_DOMAIN_ONLY_PA_REBALANCE"
                   if live_authority else
                   "DIRECT_ACTUATOR_CAPACITY_CLIP_THEN_SAME_FAMILY_ROLE_ATTENUATION"),
        "coefficient_authority": (
            "LIVE_CURRENT_VALUE_SIGNED_RELATIVE_LOG_STEP_WITH_EMPIRICAL_ENVELOPES"
            if _signed_generation_policy(cfg) else
            "LIVE_CURRENT_VALUE_RELATIVE_LOG_STEP" if live_authority else
            "LEGACY_ABSOLUTE_BOUNDS"),
        "legacy_absolute_upper_bounds_enforced": not live_authority,
        "preserve_spatial_pattern": True,
        "acceptance_authority": "FRESH_VISUM_ASSIGNMENT_PLUS_LIVE_12D_11D",
        "clipped_count": len(clipped_audit),
        "clipped_rows": clipped_audit,
        "role_rebalance": role_audit,
        "unresolved_families": sorted(set(unresolved)),
        "relative_balance_tolerance": balance_tol,
    }

def design_generation_candidates(projection_rows: Sequence[Mapping[str, Any]],
                                 zone_rows: Sequence[Mapping[str, Any]], cfg: Mapping[str, Any],
                                 scale: float = 1.0,
                                 reference_values: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """Map balanced P/A guidance to live-authority zonal calibration coefficients.

    The input projection is already balanced in P/A space. Backtracking is
    applied once to its log steps. In V2.4.8.7 the current live coefficient is
    the numerical authority and historical absolute maxima are not enforced.
    Formula-domain and zero policies can make
    the implemented effect differ from the requested effect, so this routine
    recomputes the exact implemented log effect and reports P/A balance from
    that implemented effect rather than from unavailable/skipped rows.
    """
    scale = clamp(float(scale), 0.0, 1.0)
    zone_map = _zone_lookup(zone_rows)
    zcfg = cfg.get("zahr", {})
    threshold = float(zcfg.get("domestic_threshold", 0.5))
    domestic_mask = sval(zcfg.get("domestic_mask_attr", "NOT_ZAHR"))
    neighbour_attr = sval(zcfg.get("neighbour_attr", "ZAHR_SUSED"))
    population_attr = sval(zcfg.get("population_attr", "POP_ZP"))
    live_authority = _live_coefficient_authority(cfg)
    preserve_zero_zahr = bool(zcfg.get("preserve_zero", True))
    preserve_zero_domestic = bool(cfg.get("preserve_zero_add", True))
    min_step = float(cfg.get("min_add_log_step", 5.0e-5))

    normalized: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    work_att_domestic: List[Dict[str, Any]] = []
    for p0 in projection_rows or []:
        p = dict(p0)
        z = ival(p.get("zone_no"), None)
        family = sval(p.get("family", "")).upper()
        role = sval(p.get("role", "")).upper()
        if z is None or family not in ("WORK", "SERVICE") or role not in ("PROD", "ATT"):
            skipped.append({"zone_no": z, "reason": "INVALID_PROJECTION_ROW"}); continue
        zr = zone_map.get(int(z))
        if not zr:
            skipped.append({"zone_no": z, "reason": "ZONE_NOT_FOUND"}); continue
        ok, reason = _eligible_zone(zr, cfg)
        if not ok:
            skipped.append({"zone_no": z, "family": family, "role": role, "reason": reason}); continue
        requested_log_step = float(fval(p.get("log_step"), 0.0) or 0.0) * scale
        if abs(requested_log_step) < min_step:
            continue
        is_domestic = float(fval(zr.get(domestic_mask), 0.0) or 0.0) >= threshold
        branch = "DOMESTIC" if is_domestic else "ZAHR"
        if branch == "ZAHR":
            # Exact TG border terms are multiplied by POP_ZP and ZAHR_SUSED.
            if float(fval(zr.get(neighbour_attr), 0.0) or 0.0) <= 0.0 or float(fval(zr.get(population_attr), 0.0) or 0.0) <= 0.0:
                skipped.append({"zone_no": z, "family": family, "role": role, "reason": "ZAHR_FORMULA_BASE_INACTIVE"}); continue
        attr = GENERATION_ATTR_MAP[(family, role, branch)]
        row = {
            "zone_no": int(z), "family": family, "role": role, "branch": branch, "attr": attr,
            "requested_log_step": requested_log_step,
            "base_margin_volume": float(fval(p.get("base_margin_volume"), 0.0) or 0.0),
            "guided_margin_delta": float(fval(p.get("guided_margin_delta"), 0.0) or 0.0) * scale,
            "projected_margin_delta": float(fval(p.get("projected_margin_delta"), 0.0) or 0.0) * scale,
        }
        normalized.append(row)
        if family == "WORK" and role == "ATT" and branch == "DOMESTIC":
            # Salary is identifiable only jointly with a positive ADD_ATT_W.
            add_att = fval(zr.get(sval(cfg.get("salary", {}).get("work_attraction_attr", "ADD_ATT_W"))), None)
            if add_att is not None and add_att > EPS:
                work_att_domestic.append(row)

    normalized, signed_refinement_audit = _signed_generation_refinement(
        normalized, zone_map, cfg, reference_values, skipped, min_step)
    normalized, bound_constraint_audit = _constrain_generation_projection(
        normalized, zone_map, cfg, skipped, min_step, reference_values=reference_values)
    # Rebuild the joint salary basis after bound-constrained P/A attenuation so
    # salary and ADD_ATT_W implement the constrained attraction request, not the
    # pre-constraint projection.
    work_att_domestic = []
    for row in normalized:
        if (row["family"], row["role"], row["branch"]) != ("WORK", "ATT", "DOMESTIC"):
            continue
        zr = zone_map[row["zone_no"]]
        add_att = fval(zr.get(sval(cfg.get("salary", {}).get("work_attraction_attr", "ADD_ATT_W"))), None)
        if add_att is not None and add_att > EPS:
            work_att_domestic.append(row)

    # requested_log_step is already backtracked and capacity-constrained; do not
    # scale a second time.
    salary_delta, salary_residual, salary_summary = _salary_joint_design(work_att_domestic, zone_map, cfg, scale=1.0)
    salary_cfg = cfg.get("salary", {})
    salary_attr = sval(salary_cfg.get("salary_attr", "ADD_SALARY"))
    income_attr = sval(salary_cfg.get("income_attr", "AV_INCOME"))
    offset = float(salary_cfg.get("formula_offset", 1000.0))
    denom = float(salary_cfg.get("formula_denominator", 2700.0))
    factor_floor = float(salary_cfg.get("factor_floor", 0.05))

    # First materialize salary candidates so exact attraction effects are known.
    salary_candidates: Dict[int, Dict[str, Any]] = {}
    salary_log_effect: Dict[int, float] = {}
    for z, delta in salary_delta.items():
        zr = zone_map[z]
        current = fval(zr.get(salary_attr), None)
        income = fval(zr.get(income_attr), None)
        if current is None or income is None or income <= 0.0:
            skipped.append({"zone_no": z, "family": "WORK", "role": "ATT_SALARY", "reason": "SALARY_OR_INCOME_UNREADABLE"})
            continue
        salary_low, salary_high, salary_policy = _salary_coefficient_bounds(cfg, current=float(current))
        proposed = _require_finite_coefficient(
            clamp(float(current) + float(delta), salary_low, salary_high),
            "NONFINITE_SALARY_CANDIDATE")
        old_factor = 1.0 + (float(income) * float(current) - offset) / denom
        new_factor = 1.0 + (float(income) * proposed - offset) / denom
        if old_factor <= factor_floor or new_factor <= factor_floor:
            skipped.append({"zone_no": z, "family": "WORK", "role": "ATT_SALARY", "reason": "SALARY_FACTOR_OUTSIDE_VALID_DOMAIN"})
            continue
        if abs(proposed - float(current)) > 1.0e-12:
            salary_candidates[z] = {
                "zone_no": z, "family": "WORK", "role": "ATT_SALARY", "branch": "DOMESTIC",
                "attr": salary_attr, "current": float(current), "proposed": proposed, "delta": proposed - float(current),
            }
            salary_log_effect[z] = math.log(new_factor / old_factor)
        else:
            salary_log_effect[z] = 0.0

    candidates: List[Dict[str, Any]] = []
    effect_rows: List[Dict[str, Any]] = []
    implemented_totals: Dict[str, Dict[str, float]] = defaultdict(lambda: {"estimated_prod_delta": 0.0, "estimated_att_delta": 0.0})
    max_effect_error = 0.0
    for row in normalized:
        z = row["zone_no"]; zr = zone_map[z]; attr = row["attr"]
        requested = float(row["requested_log_step"])
        salary_effect = salary_log_effect.get(z, 0.0) if (row["family"], row["role"], row["branch"]) == ("WORK", "ATT", "DOMESTIC") else 0.0
        attr_requested = requested - salary_effect
        # If salary design did not produce a candidate, the whole effect remains on ADD_ATT_W.
        if (row["family"], row["role"], row["branch"]) == ("WORK", "ATT", "DOMESTIC") and z in salary_residual:
            attr_requested = float(salary_residual[z])
        current = fval(zr.get(attr), None)
        if current is None:
            skipped.append(dict(row, reason="ATTRIBUTE_UNREADABLE")); continue
        reference = _reference_coefficient(reference_values, row["attr"], z,
                                           float(current) if current is not None else 0.0)
        low, high, coefficient_policy = _multiplicative_coefficient_bounds(
            row["branch"], cfg, current=current, reference=reference)
        preserve_zero = preserve_zero_zahr if row["branch"] == "ZAHR" else preserve_zero_domestic
        if float(current) <= EPS and preserve_zero:
            skipped.append(dict(row, reason="PRESERVE_ZERO_ATTRIBUTE", current=current)); continue
        if float(current) <= EPS:
            seed_floor = float(zcfg.get("seed_floor", 0.0)) if row["branch"] == "ZAHR" else float(cfg.get("add_seed_floor", 0.0))
            if seed_floor <= EPS:
                skipped.append(dict(row, reason="ZERO_ATTRIBUTE_WITHOUT_SEED_FLOOR", current=current)); continue
            base_value = seed_floor
            old_for_log = seed_floor
        else:
            base_value = float(current)
            old_for_log = float(current)
        proposed = _require_finite_coefficient(
            clamp(base_value * math.exp(attr_requested), low, high),
            "NONFINITE_GENERATION_COEFFICIENT_CANDIDATE")
        if proposed < 0.0:
            raise ValueError("NEGATIVE_GENERATION_COEFFICIENT_CANDIDATE")
        attr_actual = math.log(max(EPS, proposed) / max(EPS, old_for_log))
        total_actual = attr_actual + salary_effect
        error = total_actual - requested
        max_effect_error = max(max_effect_error, abs(error))
        if abs(proposed - float(current)) > 1.0e-12:
            candidates.append(dict(
                row, current=float(current), proposed=proposed,
                requested_attr_log_effect=attr_requested, actual_attr_log_effect=attr_actual,
                multiplier=(proposed / float(current) if abs(float(current)) > EPS else "SEEDED"),
                coefficient_authority=coefficient_policy,
            ))
        elif abs(salary_effect) <= 1.0e-12:
            skipped.append(dict(row, reason="CLAMPED_TO_NO_IMPLEMENTED_EFFECT", current=current))
            continue
        base_margin = max(0.0, float(row.get("base_margin_volume", 0.0) or 0.0))
        actual_delta = base_margin * math.expm1(total_actual)
        implemented_totals[row["family"]]["estimated_prod_delta" if row["role"] == "PROD" else "estimated_att_delta"] += actual_delta
        effect_rows.append({
            "zone_no": z, "family": row["family"], "role": row["role"], "branch": row["branch"],
            "requested_log_effect": requested, "actual_attribute_log_effect": attr_actual,
            "actual_salary_log_effect": salary_effect, "implemented_total_log_effect": total_actual,
            "effect_log_error": error, "base_margin_volume": base_margin,
            "implemented_margin_delta": actual_delta,
        })

    candidates.extend(salary_candidates[z] for z in sorted(salary_candidates))
    for row in implemented_totals.values():
        row["estimated_abs_gap"] = abs(row["estimated_prod_delta"] - row["estimated_att_delta"])
    attrs_changed = sorted(set(sval(r.get("attr")) for r in candidates))
    salary_summary = dict(salary_summary)
    salary_summary["candidate_count"] = len(salary_candidates)
    salary_summary["max_abs_effect_log_error"] = max_effect_error
    return {
        "candidate_rows": candidates, "skipped_rows": skipped, "effect_rows": effect_rows,
        "summary": {
            "candidate_count": len(candidates), "skipped_count": len(skipped),
            "attrs_changed": attrs_changed, "salary": salary_summary,
            "max_abs_effect_log_error": max_effect_error,
            "estimated_pa_delta_by_family": dict(implemented_totals),
            "bound_constrained_projection": bound_constraint_audit,
            "signed_generation_refinement": signed_refinement_audit,
            "generation_coefficient_authority": {
                "mode": (
                    "LIVE_CURRENT_VALUE_SIGNED_RELATIVE_LOG_STEP_WITH_EMPIRICAL_ENVELOPES"
                    if _signed_generation_policy(cfg) else
                    "LIVE_CURRENT_VALUE_RELATIVE_LOG_STEP" if live_authority else
                    "LEGACY_ABSOLUTE_BOUNDS"),
                "legacy_absolute_upper_bounds_enforced": not live_authority,
                "current_live_values_are_authority": live_authority,
                "signed_zone_refinement_enabled": bool(_signed_generation_policy(cfg)),
            },
            "backtracking_scale": scale, "scale_applied_once": True,
            "implemented_effect_row_count": len(effect_rows),
        },
    }


__all__ = [
    "COMPONENT_REGISTRY", "GENERATION_ATTRS", "build_td_signals", "design_td_candidates",
    "td_component_metrics", "long_composite_enabled",
    "collapse_td_acceptance_components", "design_generation_candidates",
    "sval", "fval", "ival", "clamp",
]

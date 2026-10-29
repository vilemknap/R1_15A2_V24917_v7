# -*- coding: utf-8 -*-
"""V24917 targeted catch-up Generation: policy, phases, bounds and design patch.

* Phase CATCH_UP while model/observed (CAL profile sums) < 0.80:
  per-zone step up to +50 % (log 0.4055) and down to -20 % (log -0.2231),
  no soft-band damping.
* Phase REFINE afterwards: the inherited per-cycle stage caps
  (generation_step_schedule) and soft-band damping.
* Coefficient envelope (both phases): domestic ADD_PROD/ATT [0.75, 2.0],
  ZAHR run-start reference x [0.5, 2.0]; soft bands equal hard bands.
  The normalized ZAHR reference is 1; native raw units are preserved.  ADD_SALARY keeps [0.5, 2.0].
* Design mode TARGETED_ZONE_DIRECT replaces the family-global + centred
  pattern: every zone keeps its own fitted step (no uniform family term);
  the inherited bound-constrained P/A rebalance still runs afterwards.

The patch is in memory (r1_15a2_multiblock functions are wrapped) and is
inert unless the active config carries ``v24917_targeted_generation``.
"""
from __future__ import annotations

import copy
import functools
import math
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

RELEASE = "R1_15A2_V24917_TARGETED_CATCHUP_GENERATION_V1_20261025"
POLICY_KEY = "v24917_targeted_generation"
PHASE_KEY = "v24917_generation_phase"
MODE_KEY = "v24917_generation_mode"
MODE = "TARGETED_ZONE_DIRECT"
EPS = 1.0e-12
SALARY_DOMAIN_MARGIN = 0.06   # max salary log effect per block (0.1 * income/(2700*g)) ~ 0.056

DEFAULT_POLICY: Dict[str, Any] = {
    "schema": "R1_15A2_V24917_TARGETED_GENERATION_POLICY_V1",
    "enabled": True,
    "proposal": "V24917_ZONAL_COUNT_FIT",
    "catchup_until_model_obs_ratio": 0.80,
    "catchup_max_log_up": math.log(1.5),
    "catchup_max_log_down": math.log(0.8),
    "refine_uses_stage_caps": True,
    # RELAX1: REFINE steps per zone and cycle up to +25 % / -20 % (stage caps were +-3 %),
    # outward steps beyond the soft band damped to 50 % (was 15 %).
    "refine_max_log_up": math.log(1.25),
    "refine_max_log_down": math.log(0.8),
    "refine_soft_outward_step_factor": 0.5,
    "envelope": {
        "domestic_hard": [0.75, 2.0],
        "zahr_reference_multiplier": [0.5, 2.0],
        "refine_domestic_soft": [0.75, 2.0],
        "refine_zahr_reference_soft": [0.5, 2.0],
    },
    "fit": {"ridge_relative": 0.01, "balance_weight_relative": 50.0,
            "max_iter": 6000, "tolerance": 1.0e-9},
    "flowbundle_mask_non_target_factor": {"CATCH_UP": 1.0, "REFINE": 1.0},
    "fallback_on_fit_error": "INHERITED_PARENT_PROPOSAL",
}


def validate_policy(policy: Mapping[str, Any]) -> Dict[str, Any]:
    p = copy.deepcopy(dict(policy))
    def need(cond, code):
        if not cond:
            raise RuntimeError("V24917_POLICY_INVALID:" + code)
    need(p.get("enabled") in (True, False), "enabled")
    r = float(p["catchup_until_model_obs_ratio"])
    need(0.0 < r <= 1.5, "catchup_until_model_obs_ratio")
    up, dn = float(p["catchup_max_log_up"]), float(p["catchup_max_log_down"])
    need(0.0 < up <= math.log(2.0) + 1e-12, "catchup_max_log_up<=ln2")
    need(math.log(0.5) - 1e-12 <= dn < 0.0, "catchup_max_log_down>=ln0.5")
    rup, rdn = float(p["refine_max_log_up"]), float(p["refine_max_log_down"])
    need(0.0 < rup <= math.log(2.0) + 1e-12, "refine_max_log_up<=ln2")
    need(math.log(0.5) - 1e-12 <= rdn < 0.0, "refine_max_log_down>=ln0.5")
    need(0.0 < float(p["refine_soft_outward_step_factor"]) <= 1.0, "refine_soft_outward_step_factor")
    env = p["envelope"]
    for key in ("domestic_hard", "zahr_reference_multiplier", "refine_domestic_soft",
                "refine_zahr_reference_soft"):
        lo, hi = (float(x) for x in env[key])
        need(0.0 < lo < 1.0 < hi <= 20.0, "envelope." + key)
    need(float(env["refine_domestic_soft"][0]) >= float(env["domestic_hard"][0]) and
         float(env["refine_domestic_soft"][1]) <= float(env["domestic_hard"][1]), "soft_inside_hard")
    for ph in ("CATCH_UP", "REFINE"):
        f = float(p["flowbundle_mask_non_target_factor"][ph])
        need(0.0 <= f <= 1.0, "flowbundle_mask_non_target_factor." + ph)
    fit = p["fit"]
    need(float(fit["ridge_relative"]) > 0.0, "fit.ridge_relative")
    need(int(fit["max_iter"]) >= 100, "fit.max_iter")
    return p


def policy_of(cfg: Mapping[str, Any]) -> Optional[Mapping[str, Any]]:
    p = (cfg or {}).get(POLICY_KEY)
    return p if isinstance(p, Mapping) and p.get("enabled") is True else None


def model_obs_ratio(d12_rows: Sequence[Mapping[str, Any]], role: str = "CALIBRATION") -> Tuple[float, float, float]:
    obs = model = 0.0
    for r in d12_rows or []:
        if str(r.get("role", "")).upper() != role:
            continue
        o = float(r.get("observed", 0.0) or 0.0)
        if o <= 0.0:
            continue
        obs += o
        model += float(r.get("model", 0.0) or 0.0)
    return (model / obs if obs > 0.0 else 1.0), obs, model


def catchup_enabled() -> bool:
    """Run option tg_catchup_enabled (R1_RUN_OPTIONS.json / env R1_TG_CATCHUP)."""
    try:
        import r1_15a2_demand_policy_v1 as dp
    except ImportError:
        return True
    return bool(dp.load_options().get("tg_catchup_enabled", True))


def phase_for(d12_rows, policy: Mapping[str, Any]) -> Tuple[str, float]:
    ratio, _obs, _model = model_obs_ratio(d12_rows)
    if not catchup_enabled():
        return "REFINE", ratio
    return ("CATCH_UP" if ratio < float(policy["catchup_until_model_obs_ratio"]) else "REFINE"), ratio


def overlay_cfg(cfg: Mapping[str, Any], phase: str) -> Dict[str, Any]:
    """Shallow config copy used only inside Generation design/preview/apply."""
    policy = policy_of(cfg)
    out = dict(cfg)
    if policy is None:
        return out
    out[PHASE_KEY] = phase
    out[MODE_KEY] = MODE
    if phase == "CATCH_UP":
        out["max_add_log_up"] = float(policy["catchup_max_log_up"])
        out["max_add_log_down"] = abs(float(policy["catchup_max_log_down"]))
    elif "refine_max_log_up" in policy:
        out["max_add_log_up"] = max(float(cfg.get("max_add_log_up", 0.0)), float(policy["refine_max_log_up"]))
        out["max_add_log_down"] = max(float(cfg.get("max_add_log_down", 0.0)),
                                      abs(float(policy["refine_max_log_down"])))
    return out


# --------------------------------------------------------------- multiblock
def _bounds_patch(orig_hard, orig_soft, mb):
    @functools.wraps(orig_hard)
    def hard(branch, cfg, current=None, reference=None):
        policy = policy_of(cfg)
        if policy is None or not mb._signed_generation_policy(cfg):
            return orig_hard(branch, cfg, current, reference)
        env = policy["envelope"]
        if str(branch).upper() == "ZAHR":
            ref = float(reference if reference is not None and reference > EPS
                        else current if current is not None and current > EPS else 0.0)
            lo, hi = (ref * float(x) for x in env["zahr_reference_multiplier"])
            name = "RUN_START_REFERENCE_RELATIVE_MULTIPLIER"
        else:
            lo, hi = (float(x) for x in env["domestic_hard"])
            name = "AMDY_LIKE_DOMESTIC_ABSOLUTE_ENVELOPE"
        if current is not None and math.isfinite(float(current)):
            lo, hi = min(lo, float(current)), max(hi, float(current))
        return lo, hi, name
    hard.__r1_v24917__ = True

    @functools.wraps(orig_soft)
    def soft(branch, cfg, current, reference=None):
        policy = policy_of(cfg)
        if policy is None or not mb._signed_generation_policy(cfg):
            return orig_soft(branch, cfg, current, reference)
        if cfg.get(PHASE_KEY) == "CATCH_UP":
            lo, hi, _ = hard(branch, cfg, current, reference)
            return lo, hi          # no damping inside the hard envelope
        env = policy["envelope"]
        if str(branch).upper() == "ZAHR":
            ref = float(reference if reference is not None and reference > EPS else current)
            return tuple(ref * float(x) for x in env["refine_zahr_reference_soft"])
        return tuple(float(x) for x in env["refine_domestic_soft"])
    soft.__r1_v24917__ = True
    return hard, soft


def targeted_zone_direct(mb, normalized, zone_map, cfg, reference_values, skipped, min_step):
    """Per-zone steps without family-global term; bounds, caps, soft damping."""
    policy = policy_of(cfg)
    max_up = float(cfg.get("max_add_log_up", 0.04))
    max_down = float(cfg.get("max_add_log_down", 0.04))
    signed = mb._signed_generation_policy(cfg) or {}
    soft_factor = 1.0 if cfg.get(PHASE_KEY) == "CATCH_UP" else float(
        (policy or {}).get("refine_soft_outward_step_factor",
                           signed.get("soft_outward_step_factor", 0.25)))
    out, damped = [], []
    for source in normalized:
        row = dict(source)
        z = int(row["zone_no"]); attr = mb.sval(row["attr"]); branch = mb.sval(row["branch"]).upper()
        current = mb.fval((zone_map.get(z) or {}).get(attr), None)
        requested = float(row.get("requested_log_step", 0.0) or 0.0)
        if current is None or current <= EPS:
            out.append(row)        # zero/unreadable: the inherited constraint stage decides
            continue
        reference = mb._reference_coefficient(reference_values, attr, z, float(current))
        low, high, envelope = mb._multiplicative_coefficient_bounds(
            branch, cfg, current=float(current), reference=reference)
        step_low = max(-max_down, math.log(max(EPS, low) / float(current)))
        step_high = min(max_up, math.log(max(EPS, high) / float(current)))
        soft_low, soft_high = mb._soft_multiplier_bounds(branch, cfg, float(current), reference)
        step, changed = mb._damp_outward_log_step(float(current), requested, soft_low,
                                                  soft_high, soft_factor)
        bounded = min(step_high, max(step_low, step))
        row.update({"targeted_raw_requested_log_step": requested,
                    "requested_log_step": bounded,
                    "coefficient_hard_low": low, "coefficient_hard_high": high,
                    "coefficient_soft_low": soft_low, "coefficient_soft_high": soft_high,
                    "coefficient_reference": reference, "coefficient_envelope": envelope})
        row["guided_margin_delta"] = mb._generation_requested_margin_delta(row)
        row["projected_margin_delta"] = mb._generation_requested_margin_delta(row)
        if changed or abs(bounded - requested) > 1.0e-15:
            damped.append({"zone_no": z, "attr": attr, "raw_log_step": requested,
                           "soft_damped_log_step": step, "bounded_log_step": bounded,
                           "current": float(current)})
        if abs(bounded) < min_step:
            skipped.append(dict(row, reason="V24917_TARGETED_STEP_BOUNDED_TO_NO_EFFECT"))
            continue
        out.append(row)
    totals: Dict[str, float] = {}
    for row in out:
        key = "%s_%s" % (row["family"], row["role"])
        totals[key] = totals.get(key, 0.0) + mb._generation_requested_margin_delta(row)
    return out, {
        "enabled": True, "mode": "V24917_" + MODE,
        "phase": cfg.get(PHASE_KEY),
        "global_total_policy": "NONE_PER_ZONE_FITTED_STEPS_THEN_INHERITED_PA_REBALANCE",
        "max_zone_log_up": max_up, "max_zone_log_down": max_down,
        "soft_outward_step_factor": soft_factor,
        "bounded_or_damped_count": len(damped), "bounded_or_damped_rows": damped[:2000],
        "requested_margin_delta_by_group": totals,
        "envelope": copy.deepcopy(policy["envelope"]) if policy else None,
        "acceptance_authority": "FRESH_VISUM_ASSIGNMENT_PLUS_LIVE_12D_11D",
    }


def patch_multiblock(mb=None) -> Dict[str, Any]:
    if mb is None:
        import r1_15a2_multiblock as mb
    if getattr(mb._multiplicative_coefficient_bounds, "__r1_v24917__", False):
        return {"patched": True, "already": True}
    hard, soft = _bounds_patch(mb._multiplicative_coefficient_bounds, mb._soft_multiplier_bounds, mb)
    orig_refine = mb._signed_generation_refinement

    @functools.wraps(orig_refine)
    def refine(normalized, zone_map, cfg, reference_values, skipped, min_step):
        if policy_of(cfg) is not None and cfg.get(MODE_KEY) == MODE:
            return targeted_zone_direct(mb, normalized, zone_map, cfg, reference_values,
                                        skipped, min_step)
        return orig_refine(normalized, zone_map, cfg, reference_values, skipped, min_step)
    refine.__r1_v24917__ = True
    mb._multiplicative_coefficient_bounds = hard
    mb._soft_multiplier_bounds = soft
    mb._signed_generation_refinement = refine
    return {"patched": True, "already": False, "release": RELEASE}


# --------------------------------------------------------------- zone bounds
def zone_bounds(mb, zone_rows, cfg, reference_values=None) -> Dict[Tuple[str, str, int], Tuple[float, float]]:
    """(family, role, zone) -> (low_log, high_log) for the fit, same rules as the design."""
    zone_map = mb._zone_lookup(zone_rows)
    zcfg = cfg.get("zahr", {})
    threshold = float(zcfg.get("domestic_threshold", 0.5))
    domestic_mask = mb.sval(zcfg.get("domestic_mask_attr", "NOT_ZAHR"))
    neighbour_attr = mb.sval(zcfg.get("neighbour_attr", "ZAHR_SUSED"))
    population_attr = mb.sval(zcfg.get("population_attr", "POP_ZP"))
    max_up = float(cfg.get("max_add_log_up", 0.04))
    max_down = float(cfg.get("max_add_log_down", 0.04))
    out = {}
    for z, zr in zone_map.items():
        ok, _reason = mb._eligible_zone(zr, cfg)
        if not ok:
            continue
        is_domestic = float(mb.fval(zr.get(domestic_mask), 0.0) or 0.0) >= threshold
        branch = "DOMESTIC" if is_domestic else "ZAHR"
        if branch == "ZAHR" and (float(mb.fval(zr.get(neighbour_attr), 0.0) or 0.0) <= 0.0 or
                                 float(mb.fval(zr.get(population_attr), 0.0) or 0.0) <= 0.0):
            continue
        for family in ("WORK", "SERVICE"):
            for role in ("PROD", "ATT"):
                attr = mb.GENERATION_ATTR_MAP[(family, role, branch)]
                current = mb.fval(zr.get(attr), None)
                if current is None or current <= EPS:
                    continue
                reference = mb._reference_coefficient(reference_values, attr, int(z), float(current))
                low, high, _ = mb._multiplicative_coefficient_bounds(
                    branch, cfg, current=float(current), reference=reference)
                dom_lo = math.log(max(EPS, low) / float(current))
                dom_hi = math.log(max(EPS, high) / float(current))
                if (family, role, branch) == ("WORK", "ATT", "DOMESTIC"):
                    # The joint salary design may move part of the effect off
                    # ADD_ATT_W; keep the coefficient domain reachable so the
                    # implemented-effect gate (0.01) is not violated by a clamp.
                    dom_lo += SALARY_DOMAIN_MARGIN
                    dom_hi -= SALARY_DOMAIN_MARGIN
                lo = max(-max_down, dom_lo)
                hi = min(max_up, dom_hi)
                if hi - lo > EPS:
                    out[(family, role, int(z))] = (min(0.0, lo), max(0.0, hi))
    return out


__all__ = ["RELEASE", "DEFAULT_POLICY", "POLICY_KEY", "PHASE_KEY", "MODE_KEY", "MODE",
           "validate_policy", "policy_of", "model_obs_ratio", "phase_for", "overlay_cfg",
           "patch_multiblock", "targeted_zone_direct", "zone_bounds"]

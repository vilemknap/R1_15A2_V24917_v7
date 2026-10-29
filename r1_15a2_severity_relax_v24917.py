# -*- coding: utf-8 -*-
"""SEVRELAX1: relaxed baseline-relative GEH-jump budgets for TG, TD and ADDVAL1.

User decision 2026-10-26: the single-profile and high-GEH jump budgets block steps that
improve the calibration as a whole (TG cycle 1: 912135 +10.1 at limit 10; TD cycle 1:
four profiles +22..24 at limit 15).  The sealed configuration keeps its values (the
start-up safety validators check them); the per-call acceptance configurations of
Generation, TD and the in-loop ADDVAL1 block get

    max_single_profile_geh_increase = max(sealed, sev_max_single_profile_geh_increase)
    max_high_geh_increase           = max(sealed, sev_max_high_geh_increase)

(R1_RUN_OPTIONS.json; values only ever relax, never tighten).  All other guards
(new GEH40 budget, severity20/30 budgets, protected profiles, shared objective) are
unchanged.

SEVRELAX2 (audit 2026-10-26): the early-exploration acceptance policy of TG and TD ends
at ``early_exploration_acceptance.through_outer_cycle`` (12).  From cycle 13 on core
silently falls back to the inherited V2.4.9.5 hysteresis contract (max single GEH
increase 2.0, at most 3 material new GEH20, TD 1.0) - the relaxed budgets above would
vanish and practically every step would be rejected (seen live in cycles 13-18 of an
earlier run: MATERIAL_NEW_GEH20_COUNT_EXCEEDED).  With ``sev_extend_early_horizon``
(default true) the per-call configuration extends the horizon to
``coupled_demand.max_outer_cycles`` so the same budgets apply in every cycle of the run.
``sev_protected_after_hard_geh`` (default 0 = unchanged 20) optionally relaxes the
protected-profile guard (profile with GEH < 5 must not end at GEH >= 20).
"""
from __future__ import annotations

import functools
from typing import Any, Dict, Mapping

RELEASE = "R1_15A2_V24917_SEVRELAX2_20261026"
_STATE: Dict[str, Any] = {"installed": False, "applied": 0}


def options() -> Dict[str, float]:
    import r1_15a2_demand_policy_v1 as dp
    o = dp.load_options()
    return {"single": float(o.get("sev_max_single_profile_geh_increase", 0.0) or 0.0),
            "high": float(o.get("sev_max_high_geh_increase", 0.0) or 0.0),
            "extend_horizon": bool(o.get("sev_extend_early_horizon", True)),
            "protected_hard": float(o.get("sev_protected_after_hard_geh", 0.0) or 0.0)}


def relax(cfg: Dict[str, Any], opts: Mapping[str, float]) -> Dict[str, Any]:
    """In place on a per-call copy; returns the record of what changed."""
    rec = {}
    for section in ("early_exploration_acceptance", "supply_route_choice_acceptance"):
        sec = cfg.get(section)
        if not isinstance(sec, dict) or not isinstance(sec.get("severity"), dict):
            continue
        sev = sec["severity"]
        for key, opt in (("max_single_profile_geh_increase", opts["single"]),
                         ("max_high_geh_increase", opts["high"]),
                         ("protected_after_hard_geh", float(opts.get("protected_hard", 0.0) or 0.0))):
            try:
                cur = float(sev.get(key))
            except (TypeError, ValueError):
                continue
            if opt > cur:
                sev[key] = float(opt)
                rec["%s.%s" % (section, key)] = [cur, float(opt)]
    early = cfg.get("early_exploration_acceptance")
    if opts.get("extend_horizon", False) and isinstance(early, dict) and early.get("enabled") is True:
        try:
            cur = int(early.get("through_outer_cycle", 0))
            horizon = int((cfg.get("coupled_demand", {}) or {}).get("max_outer_cycles", 0) or 0)
        except (TypeError, ValueError):
            cur, horizon = 0, 0
        if horizon <= 0:
            horizon = 100
        if cur > 0 and horizon > cur:
            early["through_outer_cycle"] = horizon
            rec["early_exploration_acceptance.through_outer_cycle"] = [cur, horizon]
    if rec:
        cfg.setdefault("aggressive_tuning", {})["v24917_severity_relax"] = {"release": RELEASE, "changes": rec}
    return rec


def _wrap(orig):
    @functools.wraps(orig)
    def builder(cfg, *args, **kwargs):
        c = orig(cfg, *args, **kwargs)
        if relax(c, options()):
            _STATE["applied"] += 1
        return c
    builder.__r1_sevrelax__ = True
    return builder


def install(print_fn=print) -> Dict[str, Any]:
    if _STATE["installed"]:
        return status()
    o = options()
    import r1_15a2_overnight_controller_coupled_v24915p2_force100 as ctrl
    for name in ("_generation_counts_cfg", "_td_acceptance_cfg_for_cycle"):
        fn = getattr(ctrl, name)
        if not getattr(fn, "__r1_sevrelax__", False):
            setattr(ctrl, name, _wrap(fn))
    _STATE["installed"] = True
    print_fn("V24917 SEVRELAX2: single-profile GEH jump <= %.0f, high-GEH (>60) jump <= %.0f "
             "(TG, TD, ADDVAL1; sealed values only relaxed); early-exploration horizon %s"
             % (o["single"], o["high"], "extended to all cycles" if o.get("extend_horizon") else "sealed (12)"))
    return status()


def status() -> Dict[str, Any]:
    return {"release": RELEASE, **_STATE, "options": options()}


__all__ = ["RELEASE", "install", "status", "relax", "options"]

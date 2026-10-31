# -*- coding: utf-8 -*-
"""SEVRELAX3: user-approved GEH tradeoff budgets for TG, TD and ADDVAL1.

User decision 2026-10-31: protected profiles may end below GEH40, individual
jumps up to +50, jumps ending above GEH60 up to +30. Independent scoped
severity20/30 and net GEH40 budgets are taken from validated run options.
Only per-call copies are relaxed, by max(sealed, requested). Historical config
files and GEH diagnostic buckets stay unchanged. A zero protected threshold
retains the historical limit. Shared objectives, IDP and technical guards are
unchanged. The earlier horizon extension to coupled_demand.max_outer_cycles
is retained, avoiding an unintended return to strict legacy gates at cycle 13.
"""
from __future__ import annotations

import functools
from typing import Any, Dict, Mapping

RELEASE = "R1_15A2_V24917_SEVRELAX3_GEH40_20261031"
_STATE: Dict[str, Any] = {"installed": False, "applied": 0}


def options() -> Dict[str, Any]:
    import r1_15a2_demand_policy_v1 as dp
    o = dp.load_options()
    return {"single": float(o.get("sev_max_single_profile_geh_increase", 0.0) or 0.0),
            "high": float(o.get("sev_max_high_geh_increase", 0.0) or 0.0),
            "extend_horizon": bool(o.get("sev_extend_early_horizon", True)),
            "protected_hard": float(o.get("sev_protected_after_hard_geh", 0.0) or 0.0),
            "scope_budgets": o["sev_scope_budgets"]}


def relax(cfg: Dict[str, Any], opts: Mapping[str, Any]) -> Dict[str, Any]:
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
    for scope, budget in (opts.get("scope_budgets") or {}).items():
        section = ("supply_route_choice_acceptance" if scope == "supply"
                   else "early_exploration_acceptance")
        sec = cfg.get(section)
        if not isinstance(sec, dict) or sec.get("enabled") is not True:
            continue
        scoped = sec.get(scope)
        if not isinstance(scoped, dict):
            continue  # An absent policy is not authority to create a new acceptance path.
        for key, value in budget.items():
            cur = scoped.get(key)
            if cur is None:
                raise ValueError("SEVRELAX3_SCOPED_BUDGET_MISSING:" + scope + "." + key)
            if value > cur:
                scoped[key] = value
                rec[section + "." + scope + "." + key] = [cur, value]
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
    print_fn("V24917 SEVRELAX3: protected after GEH < %.0f, single-profile jump <= %.0f, "
             "high-GEH (>60) jump <= %.0f (TG, TD, ADDVAL1); horizon %s; scoped budgets %s"
             % (o.get("protected_hard", 0.0), o["single"], o["high"],
                "extended to all demand cycles" if o.get("extend_horizon") else "sealed (12)",
                o.get("scope_budgets", {})))
    return status()


def status() -> Dict[str, Any]:
    return {"release": RELEASE, **_STATE, "options": options()}


__all__ = ["RELEASE", "install", "status", "relax", "options"]

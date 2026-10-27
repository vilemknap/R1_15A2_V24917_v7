# -*- coding: utf-8 -*-
"""BDPA1: the P/A balance of a Generation step includes the border-crossing (BNDGEN1) rows.

Live RUN 20261026 cycle 1 (from ACCEPTED_A_0001): every STEP1 scale 0.85 ... 0.064 failed
the pre-apply gate GENERATION_PA_GAP_WORK/SERVICE with a scale-invariant relative gap of
~1.0-1.15 (WORK: production +25 087, attraction +580 at scale 0.85).  Cause - a conflict
between the criteria of three stages:

* the V24917 zonal fit carries a (soft) trip-end balance of the WHOLE step per family
  (sum P_i u_i = sum A_j v_j) including the merged boundary variables X1-X31
  (coefficient b_P - b_A of the zone: the crossing scales its P and A together);
* the inherited projection rebalance (``mb._constrain_generation_projection``) and the
  apply gate (``generation_apply_gate``, 2 %) only see the domestic/ZAHR rows - the
  boundary rows are appended afterwards by the V24917 adapter.

When the fit lets the crossings carry part of the attraction growth, the domestic rows
alone look unbalanced; with opposite signs the rebalance cannot attenuate and the gate
rejects every scale (with equal signs the rebalance would silently cut the production
step to the tiny attraction side).

Fix: while a V24917 boundary design is active (``scope``), the boundary trip-end changes
of the same scale enter

1. the role rebalance: the inherited domestic-only balance is replaced by a balance of
   domestic + boundary trip ends that attenuates only the rows pushing the excess
   (monotone, so mixed-sign attraction patterns resolve; boundary steps stay as fitted), and
2. ``estimated_pa_delta_by_family`` of the design summary that the gate reads
   (internal and boundary parts are reported separately).

Without boundary rows / margins everything is unchanged.
"""
from __future__ import annotations

import contextlib
import functools
import math
from typing import Any, Dict, Iterable, Mapping, Optional

RELEASE = "R1_15A2_V24917_BDPA1_20261026"
_CTX: Dict[str, Any] = {"bd": None}
_STATE: Dict[str, Any] = {"installed": False, "designs": 0, "rebalances": 0}


# ------------------------------------------------------------------ data
def margins_from_problem(problem, zones: Iterable[int]) -> Dict[str, Dict[str, float]]:
    """Base trip-end margins of the boundary zones from the pre-merge fit problem."""
    zs = {int(z) for z in zones}
    out: Dict[str, Dict[str, float]] = {}
    for k, (fam, role, z) in enumerate(problem.var_keys):
        if int(z) in zs and role in ("PROD", "ATT"):
            out.setdefault("%s|%d" % (fam, int(z)), {})[role] = float(problem.base[k])
    return out


def pa_delta(bd: Optional[Mapping[str, Any]], scale: float) -> Dict[str, Dict[str, float]]:
    """Trip-end change of the boundary rows at ``scale`` per family: {fam: {prod, att}}."""
    out: Dict[str, Dict[str, float]] = {}
    if not bd or not bd.get("steps") or not bd.get("margins"):
        return out
    for key, step in bd["steps"].items():
        m = bd["margins"].get(key) or {}
        fam = key.split("|")[0]
        f = math.expm1(float(scale) * float(step))
        row = out.setdefault(fam, {"prod": 0.0, "att": 0.0})
        # BALANCE1: the crossing scales its symmetric (pre-sym) P and A inputs together, so its
        # trip-end change is the same on both sides; the incidence margins of the origin and
        # destination side differ only by path sampling -> use their mean for both.
        mean = 0.5 * (float(m.get("PROD", 0.0)) + float(m.get("ATT", 0.0)))
        row["prod"] += mean * f
        row["att"] += mean * f
    return out


@contextlib.contextmanager
def scope(bd: Optional[Mapping[str, Any]]):
    prev = _CTX["bd"]
    _CTX["bd"] = bd if (bd and bd.get("steps") and bd.get("margins")) else None
    try:
        yield
    finally:
        _CTX["bd"] = prev


# ------------------------------------------------------------------ wrappers
def _is_synth(row) -> bool:          # kept for API stability (no synthetic rows any more)
    return False


def _delta(row, alpha=1.0) -> float:
    base = max(0.0, float(row.get("base_margin_volume", 0.0) or 0.0))
    return base * math.expm1(float(row.get("requested_log_step", 0.0) or 0.0) * alpha)


def _scale_rows(rows, alpha) -> None:
    for r in rows:
        old = float(r.get("requested_log_step", 0.0) or 0.0)
        r.setdefault("pre_pa_rebalance_requested_log_step", old)
        r["v24917_bdpa_subset_factor"] = alpha
        r["requested_log_step"] = old * alpha
        r["guided_margin_delta"] = r["projected_margin_delta"] = _delta(r)


def _solve_alpha(rows, reduce_by: float):
    """alpha in [0,1] with sum delta(alpha) = sum delta(1) - reduce_by (rows share one sign)."""
    full = sum(_delta(r) for r in rows)
    target = full - reduce_by
    if not rows or abs(reduce_by) > abs(full) + 1e-9 or target * full < -1e-9:
        return None
    lo, hi = 0.0, 1.0
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        val = sum(_delta(r, mid) for r in rows)
        if (val - target) * (1.0 if full > 0 else -1.0) > 0:
            hi = mid
        else:
            lo = mid
    return 0.5 * (lo + hi)


def subset_rebalance(rows, delta, tol=1.0e-6) -> Dict[str, Any]:
    """Balance domestic+boundary per family by attenuating only rows that push the excess.

    Monotone in the attenuation factor (one sign), so it resolves the mixed-sign cases the
    inherited whole-side attenuation cannot (it attenuates the larger side as a whole).
    """
    report = {}
    for fam in sorted({r.get("family") for r in rows if not _is_synth(r)} | set(delta)):
        fam_rows = [r for r in rows if r.get("family") == fam and not _is_synth(r)]
        d = delta.get(fam) or {}
        p = sum(_delta(r) for r in fam_rows if r.get("role") == "PROD") + float(d.get("prod", 0.0))
        a = sum(_delta(r) for r in fam_rows if r.get("role") == "ATT") + float(d.get("att", 0.0))
        excess = p - a
        rec = {"prod_before": p, "att_before": a}
        if abs(excess) <= tol * max(1.0, abs(p), abs(a)):
            rec["status"] = "BALANCED"
            report[fam] = rec
            continue
        # excess > 0: shrink positive production steps, then negative attraction steps
        order = ((("PROD", 1.0), ("ATT", -1.0)) if excess > 0 else (("ATT", 1.0), ("PROD", -1.0)))
        remaining = abs(excess)
        steps = []
        for role, sign in order:
            group = [r for r in fam_rows if r.get("role") == role and _delta(r) * sign > 0]
            if not group or remaining <= tol:
                continue
            avail = abs(sum(_delta(r) for r in group))
            take = min(avail, remaining)
            alpha = _solve_alpha(group, take * sign)
            if alpha is None:
                continue
            # GENFIX2: attenuation of negative PROD can INCREASE mobility.
            # Preserve the certificate attached by MOBILITY2, including mixed signs.
            import r1_15a2_mobility_guard_v24917 as mobility
            saved = [dict(r) for r in group]
            full_delta = sum(_delta(r) for r in group)
            _scale_rows(group, alpha)
            if not mobility.certificate_passes(fam_rows):
                for r, old in zip(group, saved):
                    r.clear(); r.update(old)
                # Do not trade an envelope violation for a seemingly balanced P/A.
                # The unresolved P/A gap remains visible to the pre-write gate.
                steps.append({"role": role, "sign": sign, "rows": len(group),
                              "status": "BLOCKED_BY_MOBILITY", "reduced": 0.0})
                continue
            actual_take = abs(full_delta - sum(_delta(r) for r in group))
            steps.append({"role": role, "sign": sign, "rows": len(group), "alpha": alpha, "reduced": actual_take})
            remaining -= actual_take
        p1 = sum(_delta(r) for r in fam_rows if r.get("role") == "PROD") + float(d.get("prod", 0.0))
        a1 = sum(_delta(r) for r in fam_rows if r.get("role") == "ATT") + float(d.get("att", 0.0))
        rec.update(steps=steps, prod_after=p1, att_after=a1,
                   relative_gap_after=abs(p1 - a1) / max(1.0, abs(p1), abs(a1)),
                   status="SUBSET_ATTENUATION" if abs(p1-a1) <= tol*max(1.0, abs(p1), abs(a1)) else "UNRESOLVED")
        report[fam] = rec
    return report


def wrap_constrain(orig, holder):
    @functools.wraps(orig)
    def _constrain_generation_projection(normalized, zone_map, cfg, skipped, min_step, **kwargs):
        delta = holder.get("delta")
        if not delta:
            return orig(normalized, zone_map, cfg, skipped, min_step, **kwargs)
        # domain/zero constraints by the inherited stage; its domestic-only role balance is
        # switched off (it would balance a part of the step) and replaced by subset_rebalance
        cfg2 = dict(cfg)
        pol = dict(cfg.get("generation_bound_constrained_projection", {}) or {})
        pol["relative_balance_tolerance"] = float("inf")
        cfg2["generation_bound_constrained_projection"] = pol
        out, audit = orig(normalized, zone_map, cfg2, skipped, min_step, **kwargs)
        out = [dict(r) for r in out]
        sub = subset_rebalance(out, delta)
        kept = []
        for r in out:
            if abs(float(r.get("requested_log_step", 0.0) or 0.0)) < float(min_step):
                skipped.append(dict(r, reason="V24917_BDPA_SUBSET_REBALANCE_TO_NO_EFFECT"))
            else:
                kept.append(r)
        audit = dict(audit or {})
        audit["v24917_boundary_pa_in_rebalance"] = {
            "release": RELEASE, "boundary_delta": delta, "subset_rebalance": sub,
            "inherited_role_balance": "REPLACED_DOMESTIC_ONLY_BALANCE_WOULD_IGNORE_BOUNDARY"}
        audit["unresolved_families"] = sorted(f for f, r in sub.items() if r.get("status") == "UNRESOLVED")
        _STATE["rebalances"] += 1
        return kept, audit
    _constrain_generation_projection.__r1_bdpa1__ = True
    return _constrain_generation_projection


def wrap_design(orig, holder):
    @functools.wraps(orig)
    def design_generation_candidates(projection_rows, zone_rows, cfg, scale=1.0, reference_values=None):
        bd = _CTX["bd"]
        if bd is None:
            return orig(projection_rows, zone_rows, cfg, scale=scale, reference_values=reference_values)
        s = max(0.0, min(1.0, float(scale)))
        delta = pa_delta(bd, s)
        holder["delta"] = delta
        try:
            design = orig(projection_rows, zone_rows, cfg, scale=scale, reference_values=reference_values)
        finally:
            holder["delta"] = None
        summary = design.setdefault("summary", {})
        internal = {f: dict(v) for f, v in (summary.get("estimated_pa_delta_by_family") or {}).items()}
        total = {}
        for fam in sorted(set(internal) | set(delta)):
            row = dict(internal.get(fam) or {"estimated_prod_delta": 0.0, "estimated_att_delta": 0.0})
            d = delta.get(fam) or {}
            row["estimated_prod_delta"] = float(row.get("estimated_prod_delta", 0.0)) + float(d.get("prod", 0.0))
            row["estimated_att_delta"] = float(row.get("estimated_att_delta", 0.0)) + float(d.get("att", 0.0))
            row["estimated_abs_gap"] = abs(row["estimated_prod_delta"] - row["estimated_att_delta"])
            row.pop("estimated_relative_gap", None)
            total[fam] = row
        summary["v24917_internal_pa_delta_by_family"] = internal
        summary["v24917_boundary_pa_delta_by_family"] = delta
        summary["estimated_pa_delta_by_family"] = total
        summary["v24917_pa_balance_scope"] = "DOMESTIC_ZAHR_PLUS_BNDGEN1_BOUNDARY"
        _STATE["designs"] += 1
        return design
    design_generation_candidates.__r1_bdpa1__ = True
    return design_generation_candidates


def install(print_fn=print) -> Dict[str, Any]:
    if _STATE["installed"]:
        return status()
    import r1_15a2_multiblock as mb
    for name in ("design_generation_candidates", "_constrain_generation_projection"):
        if not hasattr(mb, name):
            raise RuntimeError("V24917_BDPA1_SYMBOL_MISSING:" + name)
    holder: Dict[str, Any] = {"delta": None}
    if not getattr(mb._constrain_generation_projection, "__r1_bdpa1__", False):
        mb._constrain_generation_projection = wrap_constrain(mb._constrain_generation_projection, holder)
    if not getattr(mb.design_generation_candidates, "__r1_bdpa1__", False):
        mb.design_generation_candidates = wrap_design(mb.design_generation_candidates, holder)
    _STATE["installed"] = True
    print_fn("V24917 BDPA1: Generation P/A rebalance and gate include the border-crossing rows")
    return status()


def status() -> Dict[str, Any]:
    return {"release": RELEASE, **_STATE}


__all__ = ["RELEASE", "install", "status", "scope", "pa_delta", "margins_from_problem",
           "subset_rebalance", "wrap_constrain", "wrap_design"]

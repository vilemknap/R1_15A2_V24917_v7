# -*- coding: utf-8 -*-
"""V24917 IZPEN1 - intrazonal impedance lever for the large aggregated zones.

Problem: b/c of the gravity model are common to all 681 zones.  The district zones
(611-618) and a few other large zones keep 72-99 % of their WORK+SERVICE trips
inside the zone (diagonal impedance 9-18 min, own attraction huge), so those trips
never reach the network and the counts around them stay low.  Flattening b/c for
everybody cannot fix a problem located in ~15 zones and quickly hits the survey.

Lever: the TD utility (impedance) matrix of the 16 native strata is a COPY of M9001
(default M9002, created once by R1_ADD_INTRAZONAL_IMPEDANCE_MATRIX.py).  M9001 itself is
never written (AMDY kappa bands, OSRM authority, protected-matrix guards).  For the
selected zones only the diagonal of the copy gets an additive penalty p_z [min]:

    U_zz = M9001_zz + p_z ,   0 <= p_z <= iz_max_penalty_min,   all off-diagonal cells = M9001

Zone selection (frozen at run start): WORK+SERVICE person trips 9101-9110,
intrazonal share > iz_min_share_select (0.70) AND production > iz_min_production_select
(5000); plus every zone that already carries a penalty (restart from a checkpoint).

Search (once per TD stage, after the FineCDF b/c inner search, b/c fixed at its best):
the same 65 % counts / 35 % survey objective as the TD blend,
    F(p) = w_cnt * Q(M(p)) / Q_ref + w_idp * J(p) / J_ref ,
with M(p) linearised through the FlowBundle path incidence (TD operation only, frozen
paths).  One probe TD run (+probe on all selected zones) gives the full Jacobian: the
change of row/column z is attributed to zone z (shared cells split, the balancing rest
spread by |dT_zz|), and the residual of every zone-attributed matrix is evaluated in
numpy.  Bounded ridge Gauss-Newton step (|dp| <= iz_max_step_min), backtracking line
search on real TD runs, and a floor on the intrazonal share
(iz_min_intrazonal_share, default 0.40) so the intrazonal trips never disappear.

Realization: the penalty is a TD parameter like b/c.  It is scaled with the same
realization scale (p = p_parent + s * (p_target - p_parent)), realised through the full
downstream recompute, accepted by the same outer 65/35 gate, restored on every
rollback (restore_td_parameters hook) and stored in every adapter snapshot under
``v24917_iz_penalty`` (state_hash unchanged), so rollback equality covers it.
Checkpoint .ver files contain M9002 and therefore the accepted penalties.
"""
from __future__ import annotations

import copy
import functools
import json
import math
import re
import time
import traceback
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

import numpy as np

RELEASE = "R1_15A2_V24917_INTRAZONAL_IMPEDANCE_V1_20261025"
SCHEMA = "R1_15A2_V24917_IZPEN1"
SNAPSHOT_KEY = "v24917_iz_penalty"
BASE_KEY = "v24917_ic_base_sha"
BASE_MATRIX_NO = 9001
WS_MATRICES = tuple(range(9101, 9111))
FOREIGN_MATRIX = 9116
_STOP_EXCEPTIONS = ("UserStopRequested", "TimeBudgetReached", "StopRequested")

STATE: Dict[str, Any] = {"active": False, "reason": "NOT_ACTIVATED"}
_STAGE: Dict[str, Any] = {}
_INSTALLED: Dict[str, Any] = {}


class IZError(RuntimeError):
    pass


# ------------------------------------------------------------------ options
def iz_options() -> Dict[str, Any]:
    try:
        import r1_15a2_demand_policy_v1 as dp
        o = dp.load_options()
    except Exception:
        import r1_15a2_demand_policy_v1 as dp
        o = dict(dp.DEFAULTS)
    return {k: o[k] for k in o if str(k).startswith(("iz_", "ic_"))}


def _arr(values) -> np.ndarray:
    a = np.asarray(values, dtype=np.float64)
    if a.ndim != 2 or a.shape[0] != a.shape[1] or not np.isfinite(a).all():
        raise IZError("V24917_IZ_MATRIX_INVALID")
    return a


def _get(visum, no) -> np.ndarray:
    return _arr(visum.Net.Matrices.ItemByKey(int(no)).GetValues())


def _zone_order(visum) -> List[int]:
    return [int(round(float(v))) for _k, v in visum.Net.Zones.GetMultiAttValues("NO")]


_MATRIX_REF = re.compile(r"(\d+)")


def matrix_ref_no(text) -> Optional[int]:
    """'Matrix([NO]=9002)' / 'Matrix([NO] = 9002)' / '9002' -> 9002."""
    s = str(text or "")
    m = re.search(r"\[NO\]\s*=\s*(\d+)", s, re.I)
    if m:
        return int(m.group(1))
    nums = _MATRIX_REF.findall(s)
    return int(nums[-1]) if len(nums) == 1 else None


UTIL_NAMES = ("UTILITYFUNCTION", "UtilityFunction", "UTILITYMATRIX", "UtilityMatrix",
              "UTILITYMATRIXREF", "IMPEDANCEMATRIX", "IMPEDANCEMATRIXREF", "SKIMMATRIXREF")


def _attr_ids(obj):
    try:
        return [str(a.ID) for a in obj.Attributes.GetAll]
    except Exception:
        return []


def utility_ref_of(dstrat, grav):
    """Utility (impedance) matrix reference of one TD stratum: DStrat object first, then gravity."""
    objs = [o for o in (dstrat, grav) if o is not None]
    for obj in objs:
        for name in UTIL_NAMES:
            try:
                return matrix_ref_no(obj.AttValue(name))
            except Exception:
                continue
    for obj in objs:
        for aid in _attr_ids(obj):
            if "UTIL" in aid.upper() or "IMPED" in aid.upper():
                try:
                    return matrix_ref_no(obj.AttValue(aid))
                except Exception:
                    continue
    return None


def td_utility_refs(visum) -> Dict[str, Optional[int]]:
    import r1_15a2_visum_parameters as vp
    state = vp.read_td_parameter_state(visum)
    return {str(comp): utility_ref_of(obj.get("dstrat"), obj.get("grav"))
            for comp, obj in (state.get("objects") or {}).items()}


# ------------------------------------------------------------------ activation
def select_zones(ws: np.ndarray, zone_order, o: Mapping[str, Any], existing: Mapping[int, float] = None):
    prod = ws.sum(axis=1)
    intra = np.diag(ws)
    share = np.divide(intra, prod, out=np.zeros_like(prod), where=prod > 0)
    explicit = [int(z) for z in (o.get("iz_zones") or [])]
    excluded = {int(z) for z in (o.get("iz_exclude_zones") or [])}
    if explicit:
        chosen = [z for z in explicit if z in set(zone_order)]
        basis = "EXPLICIT_IZ_ZONES"
    else:
        chosen = [int(z) for i, z in enumerate(zone_order)
                  if share[i] > float(o["iz_min_share_select"]) and prod[i] > float(o["iz_min_production_select"])]
        basis = "AUTO_SHARE_GT_%g_AND_PRODUCTION_GT_%g" % (o["iz_min_share_select"], o["iz_min_production_select"])
    for z, p in (existing or {}).items():
        if abs(float(p)) > 1e-9 and int(z) not in chosen:
            chosen.append(int(z))
    chosen = sorted(z for z in set(chosen) if z not in excluded or abs(float((existing or {}).get(z, 0.0))) > 1e-9)
    pos = {int(z): i for i, z in enumerate(zone_order)}
    rows = [{"zone_no": z, "ws_production": float(prod[pos[z]]), "ws_intrazonal_share": float(share[pos[z]]),
             "ws_intrazonal_trips": float(intra[pos[z]])} for z in chosen]
    return chosen, rows, basis


def activate(visum, options: Mapping[str, Any] = None, print_fn=print) -> Dict[str, Any]:
    """Validate the M9002 setup and freeze the zone selection; never raises (inactive on error)."""
    try:
        return _activate(visum, options, print_fn)
    except Exception as exc:
        STATE.clear()
        STATE.update(active=False, release=RELEASE, reason="ACTIVATION_ERROR:%r" % (exc,))
        return status()


def _activate(visum, options, print_fn):
    o = dict(options or iz_options())
    STATE.clear()
    STATE.update(active=False, release=RELEASE, options=o)
    if not o.get("iz_enabled", True) and not o.get("ic_enabled", False):
        STATE["reason"] = "DISABLED_BY_RUN_OPTION"
        return status()
    no = int(o["iz_matrix_no"])
    try:
        visum.Net.Matrices.ItemByKey(no)
    except Exception:
        STATE["reason"] = "MATRIX_M%d_MISSING_RUN_R1_ADD_INTRAZONAL_IMPEDANCE_MATRIX" % no
        return status()
    zone_order = _zone_order(visum)
    base = _get(visum, BASE_MATRIX_NO)
    cur = _get(visum, no)
    if base.shape != cur.shape or base.shape[0] != len(zone_order):
        STATE["reason"] = "MATRIX_SHAPE_MISMATCH"
        return status()
    off = ~np.eye(base.shape[0], dtype=bool)
    ic_on = bool(o.get("ic_enabled", False))
    B = base.copy()
    base_source = "M9001"
    if not np.allclose(cur[off], base[off], rtol=0.0, atol=1e-9):
        if not ic_on:
            STATE["reason"] = "M%d_OFFDIAGONAL_DIFFERS_FROM_M9001" % no
            return status()
        # restart from a checkpoint with congested impedance already applied
        B = cur.copy()
        np.fill_diagonal(B, np.diag(base))
        ratio = np.divide(B[off], base[off], out=np.ones(int(off.sum())), where=base[off] > 0)
        if float(B[off].min()) <= 0.0 or float(ratio.min()) < 0.2 or float(ratio.max()) > 20.0:
            STATE["reason"] = "M%d_OFFDIAGONAL_NOT_A_PLAUSIBLE_IMPEDANCE" % no
            return status()
        base_source = "M%d_OFFDIAGONAL_CONGESTED_RESTART" % no
    refs = td_utility_refs(visum)
    native = {k: v for k, v in refs.items()}
    if not native or any(v != no for v in native.values()):
        STATE["reason"] = ("TD_UTILITY_NOT_M%d:" % no) + ",".join(
            "%s=%s" % (k, v) for k, v in sorted(native.items()) if v != no)
        STATE["td_utility_refs"] = native
        return status()
    diag_pen = np.diag(cur) - np.diag(base)
    existing = {int(z): float(diag_pen[i]) for i, z in enumerate(zone_order) if abs(diag_pen[i]) > 1e-9}
    if any(v < -1e-9 for v in existing.values()):
        STATE["reason"] = "NEGATIVE_EXISTING_PENALTY"
        return status()
    ws = sum(_get(visum, m) for m in WS_MATRICES)
    if o.get("iz_enabled", True):
        zones, rows, basis = select_zones(ws, zone_order, o, existing)
    else:                                   # penalties frozen at their current values
        zones, rows, basis = select_zones(ws, zone_order, dict(o, iz_zones=sorted(existing) or [-1]), existing)
        zones = [z for z in zones if z in existing]
        rows = [r for r in rows if r["zone_no"] in existing]
        basis = "IZ_DISABLED_EXISTING_PENALTIES_FROZEN"
    if not zones and not ic_on:
        STATE["reason"] = "NO_ZONE_SELECTED"
        return status()
    pos = {int(z): i for i, z in enumerate(zone_order)}
    idx = np.array([pos[z] for z in zones], dtype=np.int64).reshape(-1)
    for r in rows:
        r["diag_m9001_min"] = float(base[pos[r["zone_no"]], pos[r["zone_no"]]])
        r["penalty_start_min"] = float(existing.get(r["zone_no"], 0.0))
    sha = base_sha(B)
    STATE.update(active=True, reason="ACTIVE", matrix_no=no, zone_order=zone_order, base=B,
                 osrm=base.copy(), base_diag=np.diag(base).copy(), bases={sha: B.copy()},
                 base_source=base_source, ic_started=base_source != "M9001", ic_updates=0,
                 zones=zones, idx=idx, selection=rows, selection_basis=basis, td_utility_refs=native)
    print_fn("R1 V24917 IZ lever ACTIVE: M%d, %d zones (%s): %s" % (
        no, len(zones), basis, ", ".join(str(z) for z in zones)))
    print_fn("R1 V24917 congested TD impedance: %s (%s)" % (
        "ON" if ic_on else "OFF", base_source if ic_on else "TD uses M9001 off-diagonal"))
    return status()


def base_sha(B) -> str:
    import hashlib
    a = np.ascontiguousarray(np.round(np.asarray(B, dtype=np.float64), 9))
    return hashlib.sha256(a.tobytes()).hexdigest()


def status() -> Dict[str, Any]:
    return {k: v for k, v in STATE.items() if k not in ("base", "base_diag", "idx", "zone_order", "osrm", "bases")}


def active() -> bool:
    return bool(STATE.get("active"))


# ------------------------------------------------------------------ read / write
def read_penalty(visum) -> np.ndarray:
    no = int(STATE["matrix_no"])
    cur = _get(visum, no)
    base = STATE["base"]
    d = np.diag(cur) - STATE["base_diag"]
    off = cur - base
    np.fill_diagonal(off, 0.0)
    if float(np.max(np.abs(off))) > 1e-9:
        raise IZError("V24917_IZ_M%d_OFFDIAGONAL_CHANGED" % no)
    mask = np.ones(len(d), dtype=bool)
    mask[STATE["idx"]] = False
    if float(np.max(np.abs(d[mask]), initial=0.0)) > 1e-9:
        raise IZError("V24917_IZ_PENALTY_OUTSIDE_SELECTED_ZONES")
    return d[STATE["idx"]].copy()


def write_penalty(visum, pen, adapter=None) -> np.ndarray:
    pen = np.asarray(pen, dtype=float)
    pmax = float(STATE["options"]["iz_max_penalty_min"])
    if pen.shape != (len(STATE["zones"]),) or not np.isfinite(pen).all():
        raise IZError("V24917_IZ_PENALTY_VECTOR_INVALID")
    if pen.size and (float(pen.min()) < -1e-9 or float(pen.max()) > pmax + 1e-9):
        raise IZError("V24917_IZ_PENALTY_OUT_OF_BOUNDS")
    pen = np.clip(pen, 0.0, pmax)
    m = STATE["base"].copy()
    idx = STATE["idx"]
    m[idx, idx] = STATE["base_diag"][idx] + pen
    if adapter is not None and hasattr(adapter, "invalidate_candidate_readback"):
        adapter.invalidate_candidate_readback("V24917_IZ_PENALTY_WRITE", mutation=True)
    visum.Net.Matrices.ItemByKey(int(STATE["matrix_no"])).SetValues(m.tolist())
    back = read_penalty(visum)
    if float(np.max(np.abs(back - pen), initial=0.0)) > 1e-6:
        raise IZError("V24917_IZ_PENALTY_READBACK_MISMATCH")
    return back


def penalty_dict(pen) -> Dict[str, float]:
    return {str(z): round(float(p), 9) for z, p in zip(STATE["zones"], np.asarray(pen, dtype=float))}


def penalty_from_snapshot(snapshot: Mapping[str, Any]) -> Optional[np.ndarray]:
    d = (snapshot or {}).get(SNAPSHOT_KEY)
    if not isinstance(d, Mapping):
        return None
    return np.array([float(d[str(z)]) for z in STATE["zones"]], dtype=float)


def extend_snapshot(snapshot: Mapping[str, Any], visum) -> Dict[str, Any]:
    if not active() or not isinstance(snapshot, Mapping):
        return snapshot
    out = dict(snapshot)
    out[SNAPSHOT_KEY] = penalty_dict(read_penalty(visum))
    out[BASE_KEY] = base_sha(STATE["base"])
    return out


def set_base(visum, B, adapter=None) -> str:
    """Write a new off-diagonal TD impedance base into M9002, keeping the current penalties."""
    B = np.array(B, dtype=np.float64, copy=True)
    osrm = STATE["osrm"]
    if B.shape != osrm.shape or not np.isfinite(B).all():
        raise IZError("V24917_IC_BASE_INVALID")
    np.fill_diagonal(B, STATE["base_diag"])
    off = ~np.eye(B.shape[0], dtype=bool)
    if float(B[off].min()) <= 0.0:
        raise IZError("V24917_IC_BASE_NONPOSITIVE")
    pen = read_penalty(visum)
    sha = base_sha(B)
    STATE["base"] = B
    bases = STATE.setdefault("bases", {})
    bases[sha] = B.copy()
    while len(bases) > 8:                       # keep the recent parents for rollbacks
        bases.pop(next(iter(bases)))
    try:
        write_penalty(visum, pen, adapter)
    except Exception:
        raise
    return sha


def restore_from_snapshot(visum, snapshot, adapter=None) -> None:
    """Restore the TD impedance base and the penalties recorded in an adapter snapshot."""
    if not active() or not isinstance(snapshot, Mapping):
        return
    sha = snapshot.get(BASE_KEY)
    if sha and sha != base_sha(STATE["base"]):
        if sha not in STATE.get("bases", {}):
            raise IZError("V24917_IC_PARENT_BASE_NOT_IN_REGISTRY")
        set_base(visum, STATE["bases"][sha], adapter)
    target = penalty_from_snapshot(snapshot)
    if target is not None:
        live = read_penalty(visum)
        if float(np.max(np.abs(live - target), initial=0.0)) > 1e-9:
            write_penalty(visum, target, adapter)


def ws_shares(mats: Mapping[int, np.ndarray]) -> np.ndarray:
    idx = STATE["idx"]
    ws = None
    for no in WS_MATRICES:
        if no in mats:
            ws = mats[no] if ws is None else ws + mats[no]
    if ws is None:
        return np.zeros(len(idx))
    rows = ws[idx, :].sum(axis=1)
    diag = ws[idx, idx]
    return np.divide(diag, rows, out=np.zeros_like(diag), where=rows > 0)


# ------------------------------------------------------------------ linear attribution
def attribute(dT: Mapping[int, np.ndarray], idx: np.ndarray, k: int) -> Dict[int, np.ndarray]:
    """Part of a simultaneous probe change dT attributed to selected zone idx[k]."""
    sel = np.zeros(next(iter(dT.values())).shape[0], dtype=bool)
    sel[idx] = True
    i = int(idx[k])
    weights = []
    for j in idx:
        weights.append(abs(sum(float(a[int(j), int(j)]) for a in dT.values())))
    wsum = sum(weights)
    w_k = weights[k] / wsum if wsum > 0 else 1.0 / len(idx)
    out = {}
    for no, a in dT.items():
        part = np.zeros_like(a)
        row = a[i, :].copy()
        col = a[:, i].copy()
        # shared cells between two selected zones (o != d) are split half/half
        row_share = np.where(sel, 0.5, 1.0); row_share[i] = 1.0
        part[i, :] = row * row_share
        col_vals = col * row_share
        col_vals[i] = 0.0                       # diagonal already in the row
        part[:, i] += col_vals
        rest = a.copy()
        rest[sel, :] = 0.0
        rest[:, sel] = 0.0
        part += w_k * rest
        out[no] = part
    return out


def bounded_ridge_step(r: np.ndarray, J: np.ndarray, lo: np.ndarray, hi: np.ndarray, ridge_rel: float) -> np.ndarray:
    n = J.shape[1]
    JTJ = J.T @ J
    lam = float(ridge_rel) * max(float(np.mean(np.diag(JTJ))), 1e-12)
    step = np.zeros(n)
    fixed = np.zeros(n, dtype=bool)
    for _ in range(n + 1):
        free = ~fixed
        if not free.any():
            break
        A = JTJ[np.ix_(free, free)] + lam * np.eye(int(free.sum()))
        g = J[:, free].T @ (r + J[:, fixed] @ step[fixed])
        x = np.linalg.solve(A, -g)
        trial = step.copy()
        trial[free] = x
        clipped = free & ((trial < lo - 1e-12) | (trial > hi + 1e-12))
        step = np.clip(trial, lo, hi)
        if not clipped.any():
            break
        fixed |= clipped
    return np.clip(step, lo, hi)


# ------------------------------------------------------------------ search
def _jsonable(x):
    if isinstance(x, dict):
        return {str(k): _jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_jsonable(v) for v in x]
    if isinstance(x, np.ndarray):
        return [_jsonable(v) for v in x.tolist()]
    if isinstance(x, (np.floating, float)):
        v = float(x)
        return v if math.isfinite(v) else str(v)
    if isinstance(x, (np.integer,)):
        return int(x)
    return x


def _write_json(path: Path, payload) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(_jsonable(payload), indent=2), encoding="utf-8")
    except Exception:
        pass


class _Evaluator:
    """TD-only evaluations of penalty vectors with the 65/35 objective."""

    def __init__(self, adapter, bridge, ref, metrics, pure_eval, blend, inner_blend):
        self.adapter, self.bridge, self.ref = adapter, bridge, ref
        self.metrics, self.pure_eval, self.blend, self.inner_blend = metrics, pure_eval, blend, inner_blend
        self.count = 0
        self.nos = sorted({int(no) for t in ref.TARGETS.values() for no in t["matrix_nos"]})

    def _M_ref(self, mats):
        ib = self.inner_blend
        if ib is None or not getattr(ib, "ref_set", False):
            return None
        m = ib.model
        total = np.zeros(len(m.profiles))
        for key in self.ref.TARGETS:
            total += m.delta_for(self.ref.TARGETS[key]["matrix_nos"], mats)
        return m.M_ref + total

    def residual(self, mats):
        out = self.pure_eval(self.metrics, mats)
        if not self.blend.ref_set:
            r, F, parts = self.blend.stacked(out, mats, M_ref=self._M_ref(mats))
        else:
            r, F, parts = self.blend.stacked(out, mats)
        return r, F, parts

    def run(self, pen):
        write_penalty(self.adapter.visum, pen, self.adapter)
        mats = self.bridge.execute()
        self.count += 1
        mats = {int(k): v for k, v in mats.items()}
        r, F, parts = self.residual(mats)
        return {"pen": np.asarray(pen, dtype=float).copy(), "mats": mats, "r": r, "F": F,
                "parts": parts, "shares": ws_shares(mats)}


def search(adapter, cfg, folder, control, package_root) -> Dict[str, Any]:
    import r1_15a2_finecdf_bridge_v24916 as bm
    import r1_15a2_td_count_blend_v24917 as tb
    o = STATE["options"]
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    zones, idx = STATE["zones"], STATE["idx"]
    pmax, step_max = float(o["iz_max_penalty_min"]), float(o["iz_max_step_min"])
    probe, floor = float(o["iz_probe_min"]), float(o["iz_min_intrazonal_share"])
    cycle_cap = float(o.get("iz_max_cycle_change_min", 0.0) or 0.0)
    if cycle_cap > 0.0:
        probe = min(probe, cycle_cap)
    p_parent = read_penalty(adapter.visum)
    report: Dict[str, Any] = {"schema": SCHEMA, "release": RELEASE, "zones": zones,
                              "penalty_parent": p_parent, "iterations": [], "status": "STARTED"}
    fine_cfg = (cfg.get("coupled_demand", {}) or {}).get("finecdf_td", {}) or {}
    ref, _path, _sha = bm.load_reference(package_root, fine_cfg)
    bridge = bm.NoDirectMatrixWriteTDAdapter(adapter.visum, ref, folder, control=control,
                                             telemetry=getattr(adapter, "telemetry", None),
                                             outer_adapter=adapter)
    if not bridge.dynamic_skim_enabled:
        report["status"] = "SKIPPED_NO_DYNAMIC_SKIMS"
        _write_json(folder / "V24917_IZ_SEARCH.json", report)
        return report
    pure_eval = tb.ORIGINAL_EVALUATE or bm.DynamicFamilyMetrics.evaluate
    inner_blend = tb._STATE.get("last_blend") or None
    try:
        bridge.isolate_td()
        metrics = bm.DynamicFamilyMetrics(bridge, ref)
        # TD operation only on the current path epoch, whatever td_inner_mode says: the
        # count term of this search is linear through the FlowBundle incidence anyway.
        manager = getattr(adapter, "v24916_dynamic_skims", None)
        current = getattr(manager, "current", None) if manager is not None else None
        if current is not None:
            bridge._v24917_frozen = True
            bridge.dynamic_skim_epoch = current
        ev = None
        cur = None
        # first execution fixes the frozen epoch; the Blend reads the frozen flag at init
        write_penalty(adapter.visum, p_parent, adapter)
        first = {int(k): v for k, v in bridge.execute().items()}
        blend = tb.Blend(bridge, ref, tb.options())
        blend.measured = False                     # counts always through the linear incidence
        ev = _Evaluator(adapter, bridge, ref, metrics, pure_eval, blend, inner_blend)
        ev.count = 1
        r0, F0, parts0 = ev.residual(first)
        cur = {"pen": p_parent.copy(), "mats": first, "r": r0, "F": F0, "parts": parts0,
               "shares": ws_shares(first)}
        report.update(F_start=F0, shares_start=cur["shares"], parts_start=parts0,
                      linear_counts=blend.model.linear is not None,
                      count_reference="INNER_BLEND_LINEAR" if inner_blend is not None else "LIVE_VOLUMES")
        if blend.model.linear is None:
            report["warning"] = "NO_FLOWBUNDLE_INCIDENCE_COUNT_TERM_CONSTANT"
        for it in range(int(o["iz_max_iterations"])):
            try:
                control.checkpoint("TD_IZ_PENALTY_SEARCH", iz_iteration=it + 1, iz_evaluations=ev.count)
            except Exception as exc:
                if exc.__class__.__name__ in _STOP_EXCEPTIONS:
                    report["stop"] = exc.__class__.__name__
                    break
                raise
            p = cur["pen"]
            delta = np.where(p + probe <= pmax + 1e-12, probe, -probe)
            e1 = ev.run(np.clip(p + delta, 0.0, pmax))
            dT = {no: e1["mats"][no] - cur["mats"][no] for no in ev.nos if no in cur["mats"]}
            n = len(zones)
            J = np.zeros((cur["r"].size, n))
            S = np.zeros(n)
            for k in range(n):
                part = attribute(dT, idx, k)
                mats_k = {no: cur["mats"][no] + part.get(no, 0.0) for no in cur["mats"]}
                rk, _Fk, _ = ev.residual(mats_k)
                J[:, k] = (rk - cur["r"]) / delta[k]
                S[k] = (ws_shares(mats_k)[k] - cur["shares"][k]) / delta[k]
            lo = np.maximum(-p, -step_max)
            hi = np.minimum(pmax - p, step_max)
            if cycle_cap > 0.0:
                # RBCONS1 audit: the realization moves the penalty at most cycle_cap per zone and
                # stage, so the search must not optimise a target that is never realised
                lo = np.maximum(lo, (p_parent - cycle_cap) - p)
                hi = np.minimum(hi, (p_parent + cycle_cap) - p)
            for k in range(n):
                if S[k] < -1e-12:
                    room = (cur["shares"][k] - floor) / (-S[k])
                    hi[k] = min(hi[k], max(0.0, room))
            hi = np.maximum(hi, lo)
            dp = bounded_ridge_step(cur["r"], J, lo, hi, float(o["iz_ridge_relative"]))
            pred = float(np.sum((cur["r"] + J @ dp) ** 2))
            rec = {"iteration": it + 1, "F_before": cur["F"], "probe": delta, "probe_F": e1["F"],
                   "dshare_dp": S, "step": dp, "predicted_F": pred, "line_search": []}
            accepted = False
            if float(np.max(np.abs(dp), initial=0.0)) >= 0.05:
                for t in (1.0, 0.5, 0.25):
                    cand = np.clip(p + t * dp, 0.0, pmax)
                    if cycle_cap > 0.0:
                        cand = np.clip(cand, p_parent - cycle_cap, p_parent + cycle_cap)
                    e = ev.run(cand)
                    ok_floor = bool(np.all(e["shares"] >= np.minimum(floor, cur["shares"]) - 1e-6))
                    ok = ok_floor and e["F"] < cur["F"] * (1.0 - 1e-4)
                    rec["line_search"].append({"t": t, "F": e["F"], "floor_ok": ok_floor, "accepted": ok})
                    if ok:
                        cur = e
                        accepted = True
                        break
            rec["accepted"] = accepted
            rec["F_after"] = cur["F"]
            rec["penalty_after"] = cur["pen"]
            report["iterations"].append(rec)
            if not accepted:
                break
        report.update(status="COMPLETED", penalty_target=cur["pen"], cycle_cap=cycle_cap, F_final=cur["F"],
                      shares_final=cur["shares"], parts_final=cur["parts"], evaluations=ev.count,
                      changed=bool(np.max(np.abs(cur["pen"] - p_parent), initial=0.0) > 1e-6),
                      seconds=round(time.monotonic() - started, 1))
        return report
    finally:
        try:
            bridge.restore_controls()
        finally:
            try:
                write_penalty(adapter.visum, p_parent, adapter)
            finally:
                if hasattr(adapter, "invalidate_candidate_readback"):
                    adapter.invalidate_candidate_readback("V24917_IZ_SEARCH_END", mutation=True)
                _write_json(folder / "V24917_IZ_SEARCH.json", report)


# ------------------------------------------------------------------ congested TD impedance (ICONG1)
def model_obs_ratio(diag) -> Optional[float]:
    rows = ((diag or {}).get("d12") or {}).get("rows") or []
    o = m = 0.0
    for r in rows:
        if str(r.get("role", "CALIBRATION")).upper() != "CALIBRATION":
            continue
        try:
            ob, mo = float(r.get("observed")), float(r.get("model"))
        except (TypeError, ValueError):
            continue
        if ob > 0 and math.isfinite(ob) and math.isfinite(mo):
            o += ob
            m += mo
    return m / o if o > 0 else None


def congestion_due(diag, outer_cycle=None) -> Dict[str, Any]:
    o = STATE.get("options", {})
    if not active() or not o.get("ic_enabled", False):
        return {"due": False, "reason": "OFF"}
    ratio = model_obs_ratio(diag)
    if not STATE.get("ic_started"):
        by_ratio = ratio is not None and ratio >= float(o["ic_start_model_obs_ratio"])
        by_cycle = int(o.get("ic_start_cycle", 0) or 0) > 0 and outer_cycle is not None and \
            int(outer_cycle) >= int(o["ic_start_cycle"])
        if not (by_ratio or by_cycle):
            return {"due": False, "reason": "WAITING_FOR_LATE_PHASE", "model_obs_ratio": ratio}
        STATE["ic_started"] = True
        STATE["ic_start"] = {"outer_cycle": outer_cycle, "model_obs_ratio": ratio,
                             "trigger": "MODEL_OBS_RATIO" if by_ratio else "OUTER_CYCLE"}
    return {"due": True, "reason": "LATE_PHASE", "model_obs_ratio": ratio}


def _skim_matrix_no(visum, code: str, dseg: str, retry_policy=None) -> int:
    from r1_15a2_skim_v24916 import matrix_inventory
    hits = [int(r["matrix_no_int"]) for r in matrix_inventory(visum, retry_policy)
            if r.get("matrix_code_norm") == code.upper() and r.get("dseg_code_norm") == dseg.upper()
            and r.get("matrix_no_int") is not None]
    if len(hits) != 1:
        raise IZError("V24917_IC_SKIM_%s_%s_FOUND_%d" % (code, dseg, len(hits)))
    return hits[0]


def congested_impedance(osrm: np.ndarray, ttc: np.ndarray, tt0: np.ndarray, mode: str,
                        ratio_max: float) -> Dict[str, Any]:
    """Target off-diagonal TD impedance [min] from the current assignment skims.

    RATIO    : U = OSRM * clip(tCur / t0, 1, ratio_max)  (OSRM geometry, Visum congestion delay)
    ABSOLUTE : U = clip(tCur [min], OSRM / ratio_max, OSRM * ratio_max)
    Cells without a valid skim (no path, t0 <= 0, non-finite) keep U = OSRM.
    """
    off = ~np.eye(osrm.shape[0], dtype=bool)
    good0 = off & np.isfinite(tt0) & np.isfinite(ttc) & (tt0 > 0) & (ttc > 0) & (tt0 < 1e7) & (ttc < 1e7)
    if not good0.any():
        raise IZError("V24917_IC_NO_VALID_SKIM_CELLS")
    unit = float(np.median(tt0[good0]) / max(np.median(osrm[good0]), 1e-9))
    if 20.0 <= unit <= 200.0:
        to_min, unit_name = 1.0 / 60.0, "s"
    elif 0.3 <= unit <= 3.0:
        to_min, unit_name = 1.0, "min"
    else:
        raise IZError("V24917_IC_SKIM_UNIT_UNKNOWN:median_t0/osrm=%g" % unit)
    U = osrm.copy()
    if mode == "ABSOLUTE":
        t = ttc * to_min
        U[good0] = np.clip(t[good0], osrm[good0] / ratio_max, osrm[good0] * ratio_max)
    else:
        r = np.clip(ttc[good0] / tt0[good0], 1.0, ratio_max)
        U[good0] = osrm[good0] * r
    cong = np.divide(ttc, tt0, out=np.ones_like(ttc), where=good0)
    return {"U": U, "unit": unit_name, "valid_cells": int(good0.sum()), "invalid_cells": int(off.sum() - good0.sum()),
            "tcur_t0_mean": float(cong[good0].mean()), "tcur_t0_p95": float(np.percentile(cong[good0], 95)),
            "tcur_t0_max": float(cong[good0].max())}


def _mean_ratio(a, b) -> float:
    ok = b > 1e-9
    return float((a[ok] / b[ok]).mean()) if ok.any() else 1.0


def congestion_feedback(ctrl, adapter, cfg, folder, control, state, diag) -> tuple:
    """Unconditional model-consistency step: TD impedance <- MSA blend with the congested skim.

    Not a calibration candidate (no accept/reject on fit): the network equilibrium requires the
    distribution to see the loaded network.  Realised through the full downstream recompute,
    then the TD stage that follows re-calibrates b/c (and the intrazonal penalties) on it.
    """
    o = STATE["options"]
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    rec: Dict[str, Any] = {"schema": SCHEMA + "_ICONG1", "applied": False}
    manager = getattr(adapter, "v24916_dynamic_skims", None)
    if manager is None:
        rec["status"] = "SKIPPED_NO_DYNAMIC_SKIM_MANAGER"
        return state, diag, rec
    epoch = manager.require_current()
    dseg = str(o["ic_skim_dseg"]).upper()
    retry = getattr(adapter, "com_retry_policy", None)
    dis_meta = (getattr(epoch, "matrix_meta_by_dseg", {}) or {}).get(dseg)
    if dis_meta:
        from r1_15a2_skim_v24916p2c import matrix_values_hash
        live_dis = _get(adapter.visum, int(dis_meta["matrix_no"]))
        if matrix_values_hash(live_dis) != dis_meta.get("values_sha256"):
            raise IZError("V24917_IC_SKIM_NOT_FROM_CURRENT_ASSIGNMENT_EPOCH")
    ttc_no = _skim_matrix_no(adapter.visum, "TTC", dseg, retry)
    tt0_no = _skim_matrix_no(adapter.visum, "TT0", dseg, retry)
    ttc, tt0 = _get(adapter.visum, ttc_no), _get(adapter.visum, tt0_no)
    osrm, B_prev = STATE["osrm"], STATE["base"]
    tgt = congested_impedance(osrm, ttc, tt0, str(o["ic_mode"]).upper(), float(o["ic_ratio_max"]))
    lam = float(o["ic_lambda"])
    B_new = (1.0 - lam) * B_prev + lam * tgt["U"]
    np.fill_diagonal(B_new, STATE["base_diag"])
    off = ~np.eye(osrm.shape[0], dtype=bool)
    rel = np.abs(B_new[off] - B_prev[off]) / np.maximum(B_prev[off], 1e-9)
    rec.update({k: v for k, v in tgt.items() if k != "U"})
    rec.update(skim_dseg=dseg, ttc_matrix=ttc_no, tt0_matrix=tt0_no, mode=str(o["ic_mode"]).upper(), lam=lam,
               dynamic_skim_epoch=int(getattr(epoch, "epoch", -1)),
               max_rel_change=float(rel.max()), mean_rel_change=float(rel.mean()),
               base_vs_osrm_mean_before=_mean_ratio(B_prev[off], osrm[off]),
               base_vs_osrm_mean_after=_mean_ratio(B_new[off], osrm[off]),
               model_obs_ratio=model_obs_ratio(diag))
    if float(rel.max()) < float(o["ic_min_rel_change"]):
        rec["status"] = "CONVERGED_NO_WRITE"
        _write_json(folder / "V24917_CONGESTED_IMPEDANCE.json", rec)
        return state, diag, rec
    parent_sha = base_sha(B_prev)
    try:
        if hasattr(adapter, "begin_candidate_readback_context"):
            adapter.begin_candidate_readback_context(
                state["state_hash"], "TD_FINECDF",
                ctrl.canonical_hash({"kind": "V24917_CONGESTED_IMPEDANCE", "base": base_sha(B_new),
                                     "parent": parent_sha}),
                parameter_evidence={"v24917_congested_impedance": True})
        set_base(adapter.visum, B_new, adapter)
        with ctrl.recovery_scope(control, "V24917_CONGESTED_IMPEDANCE_RECOMPUTE"):
            gap = ctrl._assign_candidate(adapter, folder / "FULL_DOWNSTREAM_RECOMPUTE", "TD_FINECDF")
        new_state = adapter.snapshot()
        ctrl._td_expected_freeze(state, new_state, [], cfg, folder / "TD_PARAMETER_FREEZE_AUDIT.json")
        if new_state.get(SNAPSHOT_KEY) != state.get(SNAPSHOT_KEY):
            raise IZError("V24917_IC_PENALTY_CHANGED_DURING_FEEDBACK")
        new_diag = adapter.diagnostics(folder / "DIAGNOSTICS", "AFTER_CONGESTED_IMPEDANCE")
        if adapter.snapshot() != new_state:
            raise IZError("V242_TD_DIAGNOSTICS_CHANGED_MODEL")
    except BaseException as exc:
        if exc.__class__.__name__ in _STOP_EXCEPTIONS:
            raise
        rec.update(status="FAILED_ROLLED_BACK", error=repr(exc)[:2000])
        _write_json(folder / "V24917_CONGESTED_IMPEDANCE.json", rec)
        rb_state, rb_diag = ctrl._rollback_td_all(adapter, state, diag, folder / "ROLLBACK", cfg)
        print("R1 V24917 IC WARNING: congested impedance step failed, parent restored: %r" % (exc,))
        return rb_state, rb_diag, rec
    if hasattr(adapter, "accepted_state_changed"):
        try:
            rec["path_epoch_transition"] = adapter.accepted_state_changed(
                new_state, new_diag, reason="V24917_CONGESTED_TD_IMPEDANCE_FEEDBACK", phase="DEMAND")
        except Exception as exc:
            rec["path_epoch_transition_error"] = repr(exc)[:500]
    STATE["ic_updates"] = int(STATE.get("ic_updates", 0)) + 1
    rec.update(status="APPLIED", applied=True, gap=gap, base_sha=base_sha(B_new), parent_base_sha=parent_sha,
               model_obs_ratio_after=model_obs_ratio(new_diag), update_index=STATE["ic_updates"])
    _write_json(folder / "V24917_CONGESTED_IMPEDANCE.json", rec)
    print("R1 V24917 IC: TD impedance <- congested skim (%s, lambda %.2f): tCur/t0 mean %.3f p95 %.3f, "
          "impedance/OSRM %.3f -> %.3f, max change %.1f %%" % (
              rec["mode"], lam, rec["tcur_t0_mean"], rec["tcur_t0_p95"], rec["base_vs_osrm_mean_before"],
              rec["base_vs_osrm_mean_after"], 100.0 * rec["max_rel_change"]))
    return new_state, new_diag, rec


# ------------------------------------------------------------------ controller integration
def _penalty_rows_summary(parent, target, scale=None):
    rows = []
    for z, a, b in zip(STATE["zones"], parent, target):
        rows.append({"zone_no": int(z), "penalty_parent_min": float(a), "penalty_target_min": float(b),
                     "penalty_realized_min": float(a + (scale if scale is not None else 1.0) * (b - a))})
    return rows


def _realize_with_penalty(ctrl, adapter, cfg, folder, control, before, baseline_diag, target_rows, stage):
    """V24915P2 _realize_finecdf_td with the intrazonal penalty as an extra TD parameter."""
    folder = Path(folder); folder.mkdir(parents=True, exist_ok=True)
    p_parent = np.asarray(stage["parent"], dtype=float)
    p_target = np.asarray(stage["target"], dtype=float)
    scales = ctrl._td_realization_scales(cfg)
    attempts = []
    last_error = None
    last_status = None
    soft_enabled = (cfg.get("td_soft_reference_policy", {}) or {}).get("enabled") is True
    seen = set()
    # V24917 TDSPLIT1: the penalty moves at most iz_max_cycle_change_min per zone and TD stage
    cap = float(STATE["options"].get("iz_max_cycle_change_min", 0.0) or 0.0)
    if cap > 0.0:
        p_target = p_parent + np.clip(p_target - p_parent, -cap, cap)
    pen_moves = bool(np.max(np.abs(p_target - p_parent), initial=0.0) > 1e-9)
    # combined b/c + penalty first, then b/c alone (parent penalties), then penalties alone
    plan = [("BC_AND_PENALTY", float(sc), True, True) for sc in scales]
    if STATE["options"].get("iz_split_realization", True) and target_rows and pen_moves:
        plan += [("BC_ONLY", float(sc), True, False) for sc in (1.0, 0.5)]
        plan += [("PENALTY_ONLY", float(sc), False, True) for sc in (1.0, 0.5)]
    for ordinal, (kind, scale, use_bc, use_pen) in enumerate(plan, start=1):
        attempt_folder = folder / ("TRY_%02d_%s_%s" % (ordinal, {"BC_AND_PENALTY": "S", "BC_ONLY": "BC",
                                                                  "PENALTY_ONLY": "IZ"}[kind],
                                                        str(scale).replace(".", "p")))
        attempt_folder.mkdir(parents=True, exist_ok=True)
        rows = ctrl._td_rows_at_scale(before, target_rows, scale) if (target_rows and use_bc) else []
        pen = (p_parent + float(scale) * (p_target - p_parent)) if use_pen else p_parent.copy()
        signature = ctrl.canonical_hash({
            "bc": [(r.get("component"), r.get("candidate_b"), r.get("candidate_c")) for r in rows],
            "iz": [round(float(x), 9) for x in pen]})
        if signature in seen:
            attempts.append({"trial": ordinal, "kind": kind, "scale": scale,
                             "status": "DUPLICATE_EFFECTIVE_CANDIDATE_SKIPPED"})
            continue
        seen.add(signature)
        if hasattr(adapter, "begin_candidate_readback_context"):
            adapter.begin_candidate_readback_context(
                before["state_hash"], "TD_FINECDF", signature,
                parameter_evidence={"scale": scale, "rows": rows, "iz_penalty": penalty_dict(pen)})
        try:
            ctrl.restore_td_parameters(adapter, before, ctrl._all_td_restore_rows(before),
                                       attempt_folder / "RESTORE_PARENT_BC")
            if rows:
                adapter.apply_td(rows)
            write_penalty(adapter.visum, pen, adapter)
            with ctrl.recovery_scope(control, "REALIZE_FINECDF_TD_IZ_SCALE_%s" % scale):
                gap = ctrl._assign_candidate(adapter, attempt_folder / "FULL_DOWNSTREAM_RECOMPUTE", "TD_FINECDF")
            if rows:
                adapter.parameter_persistence("TD_FINECDF", rows)
            with ctrl.recovery_scope(control, "VERIFY_REALIZED_FINECDF_TD_IZ_SCALE_%s" % scale):
                after = adapter.snapshot()
                ctrl._td_expected_freeze(before, after, rows, cfg,
                                         attempt_folder / "TD_PARAMETER_FREEZE_AUDIT.json")
                bmat = {r["matrix_no"]: r for r in before.get("matrices", [])}
                amat = {r["matrix_no"]: r for r in after.get("matrices", [])}
                if set(bmat) != set(amat):
                    raise IZError("V245_TD_MATRIX_SET_CHANGED")
                protected = {FOREIGN_MATRIX}
                protected.update(int(no) for code, no in before.get("dseg_map", {}).items()
                                 if code.startswith("EXOG_EE_") or code in ("LNV", "NV"))
                for no in protected & set(bmat):
                    if bmat[no] != amat[no]:
                        raise IZError("V245_TD_MUTATED_FIXED_MATRIX:%s" % no)
                live = penalty_from_snapshot(after)
                if live is None or float(np.max(np.abs(live - pen), initial=0.0)) > 1e-6:
                    raise IZError("V24917_IZ_REALIZED_PENALTY_MISMATCH")
                after_diag = adapter.diagnostics(attempt_folder / "DIAGNOSTICS", "AFTER_FINECDF_TD")
                if adapter.snapshot() != after:
                    raise IZError("V242_TD_DIAGNOSTICS_CHANGED_MODEL")
            decision = {"accepted": True, "reasons": [], "policy": "LEGACY_INNER_AUTHORITY"}
            if soft_enabled:
                gate_rows = rows or [{"component": r["component"]} for r in before.get("td_values", [])
                                     if str(r.get("component", "")).upper().startswith(("WORK_", "SERV_"))]
                decision = adapter.block_gate("TD_FINECDF_SOFT_REFERENCE", baseline_diag, after_diag, gate_rows)
                ctrl.atomic_json(attempt_folder / "TD_SOFT_REFERENCE_ACCEPTANCE.json", decision)
                if not decision.get("accepted", False):
                    last_status = "REJECTED_SOFT_REFERENCE_GUARD"
                    attempts.append({"trial": ordinal, "kind": kind, "scale": scale, "status": last_status,
                                     "gap": gap, "rows": rows, "iz_penalty": penalty_dict(pen),
                                     "decision": decision})
                    ctrl.atomic_json(folder / "TD_REALIZATION_ATTEMPTS.json",
                                     {"status": "BACKTRACKING_SOFT_REFERENCE", "attempts": attempts})
                    continue
            out_rows = list(rows)
            if not out_rows:
                # b/c unchanged: report a value-identical row so the controller treats the
                # realised penalty as an accepted TD change (cache transition, stationarity).
                parent = sorted(before.get("td_values", []), key=lambda r: str(r["component"]))[0]
                out_rows = [{"component": parent["component"],
                             "candidate_b": ctrl.number(parent["current_b"]),
                             "candidate_c": ctrl.number(parent["current_c"]),
                             "realization_scale": scale, "coordinate_system": "B_LINEAR_LOG_NEG_C",
                             "v24917_noop_bc_row_for_iz_penalty": True}]
            attempts.append({"trial": ordinal, "kind": kind, "scale": scale, "status": "REALIZED", "gap": gap,
                             "rows": rows, "iz_penalty": penalty_dict(pen), "decision": decision})
            evidence = {"status": "REALIZED", "selected_scale": scale, "selected_kind": kind,
                        "coordinate_system": "B_LINEAR_LOG_NEG_C+IZ_PENALTY_LINEAR",
                        "iz_penalty_rows": _penalty_rows_summary(p_parent, p_target, scale if use_pen else 0.0),
                        "attempts": attempts}
            ctrl.atomic_json(folder / "TD_REALIZATION_ATTEMPTS.json", evidence)
            _INSTALLED["last_realized"] = {"scale": scale, "penalty": penalty_dict(pen)}
            print("R1 V24917 IZ: realized penalty scale %s: %s" % (
                scale, ", ".join("%d:%+.2f" % (z, v) for z, v in zip(STATE["zones"], pen) if abs(v) > 1e-6)))
            return out_rows, after, after_diag, gap, evidence
        except BaseException as exc:
            last_error = exc
            retryable = ctrl._is_retryable_td_realization_error(exc)
            last_status = "RETRYABLE_NATIVE_IPF_NONCONVERGENCE" if retryable else "FAILED_HARD"
            attempts.append({"trial": ordinal, "kind": kind, "scale": scale, "status": last_status,
                             "error": str(exc)})
            ctrl.atomic_json(folder / "TD_REALIZATION_ATTEMPTS.json", {"status": "FAILED", "attempts": attempts})
            if not retryable:
                raise
    if last_status == "REJECTED_SOFT_REFERENCE_GUARD":
        rb_state, rb_diag = ctrl._rollback_td_all(
            adapter, before, baseline_diag, folder / "SOFT_REFERENCE_PLATEAU_ROLLBACK", cfg)
        evidence = {"status": "SOFT_REFERENCE_PLATEAU", "selected_scale": None,
                    "plateau_reason": "NO_SAFE_MATERIAL_FULL_DOWNSTREAM_TD_IMPROVEMENT",
                    "iz_penalty_rows": _penalty_rows_summary(p_parent, p_target, 0.0),
                    "attempts": attempts}
        ctrl.atomic_json(folder / "TD_REALIZATION_ATTEMPTS.json", evidence)
        return [], rb_state, rb_diag, None, evidence
    raise IZError("V2490_TD_REALIZATION_BACKTRACK_EXHAUSTED:%s" % str(last_error)) from last_error


def _inner_with_penalty(orig_inner, adapter, cfg, folder, control, package_root, *args, **kwargs):
    import r1_15a2_td_count_blend_v24917 as tb
    _STAGE.clear()
    tb._STATE.pop("last_blend", None)
    inner = orig_inner(adapter, cfg, folder, control, package_root, *args, **kwargs)
    if not active() or not STATE.get("zones") or not STATE["options"].get("iz_enabled", True):
        return inner
    iz_folder = Path(folder).parent / "V24917_IZ_PENALTY"
    try:
        rep = search(adapter, cfg, iz_folder, control, package_root)
    except BaseException as exc:
        if exc.__class__.__name__ in _STOP_EXCEPTIONS:
            raise
        rep = {"status": "ERROR_PENALTY_UNCHANGED", "error": repr(exc)[:2000],
               "traceback": traceback.format_exc()[-4000:]}
        _write_json(iz_folder / "V24917_IZ_SEARCH_ERROR.json", rep)
        print("R1 V24917 IZ WARNING: penalty search failed, penalties unchanged: %r" % (exc,))
    summary = {k: _jsonable(rep.get(k)) for k in ("status", "F_start", "F_final", "evaluations", "changed",
                                                   "penalty_parent", "penalty_target", "shares_start",
                                                   "shares_final", "error", "seconds")}
    summary["zones"] = list(STATE["zones"])
    if rep.get("changed"):
        _STAGE.update(parent=np.asarray(rep["penalty_parent"], dtype=float),
                      target=np.asarray(rep["penalty_target"], dtype=float))
        print("R1 V24917 IZ: TD-only F %.4f -> %.4f in %d TD runs; target: %s" % (
            rep["F_start"], rep["F_final"], rep["evaluations"],
            ", ".join("%d:%.2f" % (z, v) for z, v in zip(STATE["zones"], rep["penalty_target"]))))
    else:
        print("R1 V24917 IZ: no penalty change (%s)" % rep.get("status"))
    inner = dict(inner)
    inner["v24917_intrazonal_penalty"] = summary
    return inner


def install(print_fn=print) -> Dict[str, Any]:
    if _INSTALLED.get("installed"):
        return dict(_INSTALLED["installed"])
    import r1_15a2_overnight_controller_coupled_v24915p2_force100 as ctrl
    import r1_15a2_inplace_transaction_v24915p2 as tx
    import r1_15a2_td_count_blend_v24917 as tb

    orig_restore = tx.restore_td_parameters

    @functools.wraps(orig_restore)
    def restore_td_parameters(adapter, before_snapshot, candidate_rows, folder=None):
        audit = orig_restore(adapter, before_snapshot, candidate_rows, folder)
        restore_from_snapshot(adapter.visum, before_snapshot, adapter)
        return audit
    restore_td_parameters._v24917_iz = True
    if not getattr(tx.restore_td_parameters, "_v24917_iz", False):
        tx.restore_td_parameters = restore_td_parameters
    if not getattr(ctrl.restore_td_parameters, "_v24917_iz", False):
        ctrl.restore_td_parameters = restore_td_parameters

    orig_inner = ctrl.run_finecdf_inner

    @functools.wraps(orig_inner)
    def run_finecdf_inner(adapter, cfg, folder, control, package_root, *args, **kwargs):
        return _inner_with_penalty(orig_inner, adapter, cfg, folder, control, package_root, *args, **kwargs)
    run_finecdf_inner._v24917_iz = True
    if not getattr(ctrl.run_finecdf_inner, "_v24917_iz", False):
        ctrl.run_finecdf_inner = run_finecdf_inner
    # The V24916 controller patch calls its own module-level import of the inner search
    # (r1_15a2_active_controller_patch_v24916p2c.targeted_run_finecdf_inner), not ctrl.run_finecdf_inner.
    patched_dispatch = []
    try:
        import r1_15a2_active_controller_patch_v24916p2c as acp
        cur = getattr(acp, "targeted_run_finecdf_inner", None)
        if cur is not None and not getattr(cur, "_v24917_iz", False):
            acp_orig = cur

            @functools.wraps(acp_orig)
            def targeted_inner(adapter, cfg, folder, control, package_root, *args, **kwargs):
                return _inner_with_penalty(acp_orig, adapter, cfg, folder, control, package_root, *args, **kwargs)
            targeted_inner._v24917_iz = True
            acp.targeted_run_finecdf_inner = targeted_inner
            patched_dispatch.append("r1_15a2_active_controller_patch_v24916p2c.targeted_run_finecdf_inner")
    except ImportError:
        pass

    orig_realize = ctrl._realize_finecdf_td

    @functools.wraps(orig_realize)
    def realize_finecdf_td(adapter, cfg, folder, control, before, baseline_diag, target_rows):
        stage = dict(_STAGE)
        _STAGE.clear()
        if not active() or not stage:
            return orig_realize(adapter, cfg, folder, control, before, baseline_diag, target_rows)
        return _realize_with_penalty(ctrl, adapter, cfg, folder, control, before, baseline_diag,
                                     target_rows, stage)
    realize_finecdf_td._v24917_iz = True
    if not getattr(ctrl._realize_finecdf_td, "_v24917_iz", False):
        ctrl._realize_finecdf_td = realize_finecdf_td

    orig_td_once = ctrl._finecdf_td_once

    @functools.wraps(orig_td_once)
    def finecdf_td_once(adapter, cfg, folder, control, state, diag, package_root, *args, **kwargs):
        fb = None
        due = congestion_due(diag, kwargs.get("outer_cycle"))
        if due.get("due"):
            state, diag, fb = congestion_feedback(ctrl, adapter, cfg, Path(folder) / "V24917_CONGESTED_IMPEDANCE",
                                                  control, state, diag)
            fb["trigger"] = due
        elif active() and STATE["options"].get("ic_enabled"):
            print("R1 V24917 IC: TD impedance still M9001 (%s, model/counts %s)" % (
                due.get("reason"), "%.3f" % due["model_obs_ratio"] if due.get("model_obs_ratio") is not None else "?"))
        changed, new_state, new_diag, rec = orig_td_once(adapter, cfg, folder, control, state, diag,
                                                         package_root, *args, **kwargs)
        if fb is not None:
            rec = dict(rec)
            rec["v24917_congested_impedance"] = _jsonable(fb)
            changed = bool(changed or fb.get("applied"))
        return changed, new_state, new_diag, rec
    finecdf_td_once._v24917_ic = True
    if not getattr(ctrl._finecdf_td_once, "_v24917_ic", False):
        ctrl._finecdf_td_once = finecdf_td_once

    _INSTALLED["installed"] = {"installed": True, "release": RELEASE, "active": active(),
                               "inner_dispatch_patched": ["ctrl.run_finecdf_inner"] + patched_dispatch,
                               "reason": STATE.get("reason"), "zones": list(STATE.get("zones") or [])}
    return dict(_INSTALLED["installed"])


__all__ = ["RELEASE", "STATE", "activate", "install", "read_penalty", "write_penalty", "extend_snapshot",
           "search", "select_zones", "attribute", "bounded_ridge_step", "matrix_ref_no", "td_utility_refs"]

# -*- coding: utf-8 -*-
"""OPMAP1: resolve the R1 procedure-sequence ROLES of the live model.

The calibrator was written against the 43-operation 09C procedure sequence in
which the roles sit at fixed 1-based positions (``Operations.ItemByKey``):

    1  reset PrT assignment before TG          (Initialize assignment, type 9)
    15 reset PrT assignment after new demand   (type 9)
    17 PrT assignment LNV + NV                 (type 101, DSEGSET exact)
    18 PrT assignment NATIVE_CF + NATIVE_CL    (type 101)
    19 PrT assignment NATIVE_CS/CW (+ _noT)    (type 101)
    20 joint 14-DSeg PrT assignment (GAP/COUNT authority)
    21 post-assignment GEH / count-location script (type 65)

The 2022 model since 2026-11 nests the demand steps in more groups (country
add-on preset, OSRM time update, demand/foreign groups, R1 20D vignette split),
so the same roles sit at other positions (e.g. 23 / 25-28 / 29).  Every legacy
position literal in the runtime and in the sealed configuration is therefore
TRANSLATED through this module instead of being used directly:

    live = roles.live_position(rows_or_visum, 20)

* A model whose roles are exactly at the legacy positions maps to the identity
  (no DSEGSET read is needed and nothing changes).
* Otherwise every role is identified by its signature (operation type, ACTIVE,
  exact DSEGSET of the assignments, order: TG < TD < reset < assignments <
  joint assignment < GEH script).  Any missing or ambiguous role fails closed
  with ``OPMAP1_*``; nothing is guessed.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Mapping, Optional

import r1_15a2_com_compat as com

RELEASE = "R1_15A2_V24917_OPMAP1_20261111"
RESET_TYPE = 9

LEGACY = {
    "RESET_PRE": 1,
    "RESET_POST": 15,
    "ASG_FREIGHT": 17,
    "ASG_CF_CL": 18,
    "ASG_CS_CW": 19,
    "ASG_FINAL": 20,
    "POST_GEH": 21,
}
ROLE_OF_LEGACY = {v: k for k, v in LEGACY.items()}
ASSIGNMENT_DSEGS = {
    "ASG_FREIGHT": frozenset(("LNV", "NV")),
    "ASG_CF_CL": frozenset(("NATIVE_CF", "NATIVE_CL")),
    "ASG_CS_CW": frozenset(("NATIVE_CS", "NATIVE_CS_NOT", "NATIVE_CW", "NATIVE_CW_NOT")),
    "ASG_FINAL": frozenset((
        "EXOG_EE_CF", "EXOG_EE_CL", "EXOG_EE_CS", "EXOG_EE_CS_NOT",
        "EXOG_EE_CW", "EXOG_EE_CW_NOT", "LNV", "NATIVE_CF", "NATIVE_CL",
        "NATIVE_CS", "NATIVE_CS_NOT", "NATIVE_CW", "NATIVE_CW_NOT", "NV",
    )),
}
POST_GEH_TOKENS = ("12C", "COUNTLOCATION", "GEH", "COLOR")


class OpmapError(RuntimeError):
    """The live procedure sequence does not contain an unambiguous role."""


def _rows(source) -> List[Mapping[str, Any]]:
    if isinstance(source, (list, tuple)):
        return list(source)
    return com.operation_rows(source)


def _type(row) -> int:
    return int(row["type"])


def _pos(row) -> int:
    return int(row.get("position", row["no"]))


def _norm(code: str) -> str:
    return re.sub(r"[^A-Z0-9_]", "", str(code).upper())


def dsegset(row) -> frozenset:
    obj = row.get("object")
    if obj is None:
        raise OpmapError("OPMAP1_ASSIGNMENT_OBJECT_UNAVAILABLE:%s" % _pos(row))
    raw = com.object_property(obj, "PrTAssignmentParameters").AttValue("DSEGSET")
    tokens = [x.strip("\"' ") for x in re.split(r"[,;{}\s]+", str(raw)) if x.strip("\"' ")]
    return frozenset(_norm(x) for x in tokens)


def _is_legacy_layout(rows) -> bool:
    by = {_pos(r): r for r in rows}
    # the four assignment roles at 17-20 identify the legacy 09C layout (reduced
    # harnesses do not model the resets at 1 / 15)
    want = {17: com.ASSIGNMENT_PRT, 18: com.ASSIGNMENT_PRT, 19: com.ASSIGNMENT_PRT,
            20: com.ASSIGNMENT_PRT}
    return all(p in by and _type(by[p]) == t for p, t in want.items())


def resolve(source) -> Dict[str, Any]:
    """Role -> live position plus the legacy -> live map (cached per row list)."""
    rows = _rows(source)
    if not rows:
        raise OpmapError("OPMAP1_EMPTY_PROCEDURE_SEQUENCE")
    if _is_legacy_layout(rows):
        roles = dict(LEGACY)
        return {"schema": "R1_15A2_OPMAP1_ROLES_V1", "release": RELEASE, "mode": "LEGACY_IDENTITY",
                "roles": roles, "legacy_to_live": {v: v for v in LEGACY.values()},
                "operation_count": len(rows)}
    active = [r for r in rows if int(r["active"])]
    tg = [_pos(r) for r in active if _type(r) == com.TG]
    td = [_pos(r) for r in active if _type(r) == com.TD]
    if len(td) != 1:
        raise OpmapError("OPMAP1_EXPECTED_ONE_ACTIVE_TD_FOUND_%d" % len(td))
    td_pos = td[0]
    roles: Dict[str, int] = {}
    for role, want in ASSIGNMENT_DSEGS.items():
        hits = [_pos(r) for r in active if _type(r) == com.ASSIGNMENT_PRT and dsegset(r) == want]
        if len(hits) != 1:
            raise OpmapError("OPMAP1_ROLE_%s_FOUND_%d" % (role, len(hits)))
        roles[role] = hits[0]
    order = [roles[k] for k in ("ASG_FREIGHT", "ASG_CF_CL", "ASG_CS_CW", "ASG_FINAL")]
    if order != sorted(order) or order[0] <= td_pos:
        raise OpmapError("OPMAP1_ASSIGNMENT_ORDER:%s;td=%d" % (order, td_pos))
    pre = [_pos(r) for r in active if _type(r) == RESET_TYPE and tg and _pos(r) < min(tg)]
    post = [_pos(r) for r in active if _type(r) == RESET_TYPE and td_pos < _pos(r) < order[0]]
    if len(pre) != 1:
        raise OpmapError("OPMAP1_ROLE_RESET_PRE_FOUND_%d" % len(pre))
    if len(post) != 1:
        raise OpmapError("OPMAP1_ROLE_RESET_POST_FOUND_%d" % len(post))
    roles["RESET_PRE"], roles["RESET_POST"] = pre[0], post[0]
    final = roles["ASG_FINAL"]
    nxt = [r for r in rows if _pos(r) > final and _type(r) != com.GROUP]
    if nxt and _type(nxt[0]) == com.EXECUTE_SCRIPT:
        text = (str(nxt[0].get("comment", "")) + " " + str(nxt[0].get("name", ""))).upper()
        if any(t in text for t in POST_GEH_TOKENS):
            roles["POST_GEH"] = _pos(nxt[0])
    if "POST_GEH" not in roles:
        roles["POST_GEH"] = None        # optional: no safe post-assignment skip
    legacy_to_live = {LEGACY[k]: v for k, v in roles.items() if v is not None}
    return {"schema": "R1_15A2_OPMAP1_ROLES_V1", "release": RELEASE, "mode": "RESOLVED_BY_SIGNATURE",
            "roles": roles, "legacy_to_live": legacy_to_live, "operation_count": len(rows),
            "td_position": td_pos, "tg_positions": tg}


def live_position(source, legacy_no: int) -> int:
    legacy_no = int(legacy_no)
    if legacy_no not in ROLE_OF_LEGACY:
        return legacy_no                  # not a role position: positions are used as given
    mapping = resolve(source)["legacy_to_live"]
    if legacy_no not in mapping:
        raise OpmapError("OPMAP1_ROLE_NOT_PRESENT:%s" % ROLE_OF_LEGACY[legacy_no])
    return int(mapping[legacy_no])


def live_positions(source, legacy: Iterable[int]) -> List[int]:
    m = resolve(source)["legacy_to_live"]
    out = []
    for n in legacy:
        n = int(n)
        if n in ROLE_OF_LEGACY and n not in m:
            raise OpmapError("OPMAP1_ROLE_NOT_PRESENT:%s" % ROLE_OF_LEGACY[n])
        out.append(int(m.get(n, n)))
    return out


def expected_dsegs_by_live(source) -> Dict[int, frozenset]:
    roles = resolve(source)["roles"]
    return {int(roles[r]): d for r, d in ASSIGNMENT_DSEGS.items()}


ROLE_TYPES = {"RESET_PRE": RESET_TYPE, "RESET_POST": RESET_TYPE, "ASG_FREIGHT": com.ASSIGNMENT_PRT,
              "ASG_CF_CL": com.ASSIGNMENT_PRT, "ASG_CS_CW": com.ASSIGNMENT_PRT,
              "ASG_FINAL": com.ASSIGNMENT_PRT, "POST_GEH": com.EXECUTE_SCRIPT}


def translator(source):
    """legacy position -> live position for one inventory.

    Full signature resolution when possible.  Reduced inventories (single-assignment
    harnesses, supply-only views) that cannot be resolved keep a legacy number ONLY
    when the operation at that legacy position still has the role's type; anything
    else fails closed.
    """
    rows = _rows(source)
    try:
        mapping = resolve(rows)["legacy_to_live"]
        err = None
    except OpmapError as exc:
        mapping, err = None, exc
    by = {_pos(r): r for r in rows}

    def tr(legacy_no: int) -> int:
        legacy_no = int(legacy_no)
        role = ROLE_OF_LEGACY.get(legacy_no)
        if role is None:
            return legacy_no
        if mapping is not None:
            if legacy_no not in mapping:
                raise OpmapError("OPMAP1_ROLE_NOT_PRESENT:%s" % role)
            return int(mapping[legacy_no])
        row = by.get(legacy_no)
        if row is not None and _type(row) == ROLE_TYPES[role]:
            return legacy_no
        raise err
    return tr


# ------------------------------------------------------------------ overlay (sealed parents)
# The sealed parent modules (acceleration V24915P1, supply_visum, assignment authority
# V239, trial adapter V240, FineCDF bridge V24916) read the legacy positions from the
# configuration or from literals.  They are not edited; their entry points receive a
# configuration whose position fields are translated to the live sequence.
import copy as _copy
import functools as _functools

_STATE: Dict[str, Any] = {"installed": False, "events": []}


def live_cfg(visum, cfg):
    """Shallow copy of ``cfg`` with the role positions translated (identity on legacy)."""
    if not isinstance(cfg, Mapping):
        return cfg
    rows = _rows(visum)
    if _is_legacy_layout(rows):
        return cfg
    tr = translator(rows)
    out = dict(cfg)
    supply = dict(out.get("supply") or {})
    if supply.get("assignment_operations"):
        supply["assignment_operations"] = [dict(r, no=tr(int(r["no"])), opmap1_legacy_no=int(r["no"]))
                                           for r in supply["assignment_operations"]]
    if isinstance(supply.get("gap_readback"), Mapping) and supply["gap_readback"].get("operation_no"):
        g = dict(supply["gap_readback"])
        g["operation_no"] = tr(int(g["operation_no"]))
        supply["gap_readback"] = g
    out["supply"] = supply
    perf = out.get("performance")
    if isinstance(perf, Mapping) and isinstance(perf.get("v24915_perf1"), Mapping):
        p1 = dict(perf["v24915_perf1"])
        ph = p1.get("phase_specific_procseq")
        if isinstance(ph, Mapping) and ph.get("safe_post_assignment_operations"):
            ph = dict(ph)
            rules = []
            for r in ph["safe_post_assignment_operations"]:
                try:
                    rules.append(dict(r, position=tr(int(r["position"]))))
                except OpmapError:
                    pass                    # no reviewed GEH script: post skip simply not proven
            ph["safe_post_assignment_operations"] = rules
            p1["phase_specific_procseq"] = ph
        perf = dict(perf); perf["v24915_perf1"] = p1
        out["performance"] = perf
    out["opmap1_roles"] = resolve(rows)
    return out


def live_spec(visum, spec):
    if not isinstance(spec, Mapping) or not spec.get("operation_no"):
        return spec
    rows = _rows(visum)
    if _is_legacy_layout(rows):
        return spec
    return dict(spec, operation_no=translator(rows)(int(spec["operation_no"])))


def role_assignment_scope(visum, expected):
    """V239 assignment-scope authority on a non-legacy layout, reported in LEGACY role
    numbering (``no`` 17..20, selected [20]) with the live positions alongside."""
    rows = _rows(visum)
    try:
        info = resolve(rows)
    except OpmapError as exc:
        return {"schema": "R1_15A2_ASSIGNMENT_SCOPE_AUTHORITY_V239", "passes": False,
                "failures": [str(exc)], "verified_operations": [],
                "selected_trial_assignment_operations": [], "gap_operation_no": 20,
                "required_full_scope": sorted(expected[20]), "opmap1": {"error": str(exc)}}
    live = info["legacy_to_live"]
    by = {_pos(r): r for r in rows}
    details, failures = [], []
    for legacy_no in (17, 18, 19, 20):
        row = by[int(live[legacy_no])]
        out = {"no": legacy_no, "live_no": int(live[legacy_no]), "expected_type": com.ASSIGNMENT_PRT,
               "expected_dsegs": sorted(expected[legacy_no]), "type": _type(row),
               "active": int(row["active"]), "comment": row.get("comment", ""), "name": row.get("name", "")}
        got = dsegset(row)
        out["live_dsegs"] = sorted(got)
        if got != frozenset(expected[legacy_no]):
            out["status"] = "DSEGSET_MISMATCH"
            failures.append("OP_%d_DSEGSET" % legacy_no)
        else:
            out["status"] = "PASS"
        details.append(out)
    return {"schema": "R1_15A2_ASSIGNMENT_SCOPE_AUTHORITY_V239", "passes": not failures,
            "failures": failures, "verified_operations": details,
            "selected_trial_assignment_operations": [20] if not failures else [],
            "selection_reason": "OPMAP1_ROLE_20_IS_THE_FINAL_JOINT_14_DSEG_PRT_ASSIGNMENT_AT_LIVE_%d" % live[20],
            "gap_operation_no": 20, "gap_operation_live_no": int(live[20]),
            "required_full_scope": sorted(expected[20]),
            "numbering": "LEGACY_ROLE_NUMBERS_WITH_LIVE_POSITIONS",
            "opmap1": {k: v for k, v in info.items() if k != "tg_positions"}}


def _wrap_scope(orig):
    @_functools.wraps(orig)
    def audit(visum):
        if _is_legacy_layout(_rows(visum)):
            return orig(visum)
        from r1_15a2_assignment_authority_v239 import EXPECTED
        return role_assignment_scope(visum, EXPECTED)
    audit.__r1_opmap1__ = True
    return audit


def _wrap_cfg_first(orig):
    @_functools.wraps(orig)
    def call(visum, cfg, *args, **kwargs):
        return orig(visum, live_cfg(visum, cfg), *args, **kwargs)
    call.__r1_opmap1__ = True
    return call


def _wrap_gap(orig):
    @_functools.wraps(orig)
    def call(visum, spec):
        return orig(visum, live_spec(visum, spec))
    call.__r1_opmap1__ = True
    return call


def _wrap_dynamic_plan(orig):
    @_functools.wraps(orig)
    def plan(self):
        outer = getattr(self, "outer_adapter", None)
        if outer is None or not hasattr(outer, "cfg"):
            return orig(self)
        saved = outer.cfg
        try:
            outer.cfg = live_cfg(self.v, saved)
            return orig(self)
        finally:
            outer.cfg = saved
    plan.__r1_opmap1__ = True
    return plan


def install(print_fn=print) -> Dict[str, Any]:
    if _STATE["installed"]:
        return dict(_STATE)
    import r1_15a2_assignment_authority_v239 as a239
    import r1_15a2_trial_adapter_v240 as a240
    import r1_15a2_acceleration_v24915p1 as perf1
    import r1_15a2_supply_visum as sv
    import r1_15a2_finecdf_bridge_v24916 as bridge
    patched = []
    for mod in (a239, a240):
        if not getattr(mod.audit_assignment_scope, "__r1_opmap1__", False):
            mod.audit_assignment_scope = _wrap_scope(mod.audit_assignment_scope)
            patched.append(mod.__name__ + ".audit_assignment_scope")
    for mod, name in ((perf1, "phase_recompute_plan"), (sv, "assignment_plan")):
        if not getattr(getattr(mod, name), "__r1_opmap1__", False):
            setattr(mod, name, _wrap_cfg_first(getattr(mod, name)))
            patched.append(mod.__name__ + "." + name)
    if not getattr(sv.assignment_gap_evidence, "__r1_opmap1__", False):
        sv.assignment_gap_evidence = _wrap_gap(sv.assignment_gap_evidence)
        patched.append(sv.__name__ + ".assignment_gap_evidence")
    cls = bridge.NoDirectMatrixWriteTDAdapter
    if not getattr(cls._dynamic_realization_plan, "__r1_opmap1__", False):
        cls._dynamic_realization_plan = _wrap_dynamic_plan(cls._dynamic_realization_plan)
        patched.append("NoDirectMatrixWriteTDAdapter._dynamic_realization_plan")
    _STATE.update(installed=True, release=RELEASE, patched=patched,
                  policy="LEGACY_LAYOUT_IDENTITY;OTHER_LAYOUTS_RESOLVED_BY_ROLE_SIGNATURE_FAIL_CLOSED")
    print_fn("V24917 OPMAP1: procedure-sequence roles resolved live (%d entry points)" % len(patched))
    return dict(_STATE)

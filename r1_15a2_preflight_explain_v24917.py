# -*- coding: utf-8 -*-
"""PREFLIGHT2 (V24917): explainable live preflight + no stale-assignment requirement.

Live run RUN_20261025_205621 (after network edits): ``V240_LIVE_RECOMPUTE_PREFLIGHT_FAILED``
without any reason.  The inherited preflight requires readable assignment-quality
results of operation 20 in the OPENED .ver (gap list), but Visum discards PrT
assignment results when the network is edited, so a freshly edited and saved
model can never pass - although the controller performs a full baseline recompute
(and checks the gap after every assignment) right after the preflight.

1. assignment_plan: a reason ``ASSIGNMENT_GAP_READBACK_UNAVAILABLE`` alone (no
   results in the opened model) no longer blocks; it is recorded as
   ``DEFERRED_TO_BASELINE_FULL_RECOMPUTE``.  The gap gate itself (maximum gap on
   op 20 after each assignment) is unchanged.
2. Links with t0_C + 10*ADDVAL1 below the minimum cost (zero car travel time, typically
   a freshly split / zero-length link after a network edit) are excluded from the
   ADDVAL1 supply lever instead of blocking the whole run; they are listed on the console
   and in PREFLIGHT/00_ZERO_COST_LINKS_EXCLUDED.json.  (Assignment still uses them - fix
   length / v0 in the network.)
3. A failing V240 preflight raises with the actual reasons (TG contract, procedure
   sequence, assignment plan, links outside the positive cost domain) and writes
   PREFLIGHT/00_PREFLIGHT_FAILURE_EXPLAINED.json.
"""
from __future__ import annotations

import functools
import json
from pathlib import Path
from typing import Any, Dict

RELEASE = "R1_15A2_V24917_PREFLIGHT2_20261025"
DEFERRABLE = ("ASSIGNMENT_GAP_READBACK_UNAVAILABLE",)
_STATE: Dict[str, Any] = {"installed": False, "deferred": [], "zero_cost_links": []}


def _wrap_inactive_partial_scope_audit(orig):
    """V24917: exact read-only 09C audit with optional-inactive OP17..19.

    The immutable V239 auditor checks the DSEGSET on active operations only,
    and reports OP17/18/19_INACTIVE before reading their scope. The live R1
    09C version legitimately activates final OP20 alone. Recover only these
    specific premature failures and re-read *every* inactive partial DSEGSET.
    All other failures (notably an inactive or wrong OP20) remain hard.
    """
    @functools.wraps(orig)
    def audit(visum):
        report = orig(visum)
        idle_reasons = {"OP_%d_INACTIVE" % no for no in (17, 18, 19)}
        errors = list(report.get("failures") or [])
        if not any(reason in idle_reasons for reason in errors):
            return report
        from r1_15a2_assignment_authority_v239 import EXPECTED, _tokens
        from r1_15a2_com_compat import operation_rows, object_property
        details = [dict(row) for row in report["verified_operations"]]
        by_no = {int(row["no"]): row for row in operation_rows(visum)}
        errors = [reason for reason in errors if reason not in idle_reasons]
        verified_inactive = []
        for detail in details:
            no = int(detail["no"])
            if no not in (17, 18, 19) or detail.get("status") != "INACTIVE":
                continue
            row = by_no.get(no)
            if row is None or int(row["type"]) != 101 or row["active"]:
                detail["status"] = "ACTIVITY_OR_TYPE_DRIFT"
                errors.append("OP_%d_ACTIVITY_OR_TYPE_DRIFT" % no)
                continue
            try:
                params = object_property(row["object"], "PrTAssignmentParameters")
                raw = params.AttValue("DSEGSET")
                actual = _tokens(raw)
                detail["live_dsegset_raw"] = raw
                detail["live_dsegs"] = sorted(actual)
                if actual != EXPECTED[no]:
                    detail["status"] = "DSEGSET_MISMATCH"
                    detail["missing"] = sorted(EXPECTED[no] - actual)
                    detail["extra"] = sorted(actual - EXPECTED[no])
                    errors.append("OP_%d_DSEGSET" % no)
                else:
                    detail["status"] = "PASS_INACTIVE_PARTIAL"
                    verified_inactive.append(no)
            except Exception as exc:
                detail["status"] = "UNREADABLE"
                detail["error"] = str(exc)
                errors.append("OP_%d_UNREADABLE" % no)
        out = dict(report)
        out["verified_operations"] = details
        out["failures"] = errors
        out["passes"] = not errors
        out["selected_trial_assignment_operations"] = [20] if not errors else []
        out["validated_inactive_partial_operations"] = sorted(verified_inactive)
        out["activity_policy"] = (
            "OP20_ACTIVE_EXACT_14_DSEG_FINAL;_OP17_19_MAY_BE_INACTIVE_"
            "BUT_TYPE_AND_DSEGSET_MUST_MATCH")
        return out
    audit.__r1_preflight2_inactive_partial_scope__ = True
    return audit


def _wrap_plan(orig):
    @functools.wraps(orig)
    def assignment_plan(visum, cfg):
        plan = orig(visum, cfg)
        reasons = list(plan.get("reasons") or [])
        if reasons and all(str(r).startswith(DEFERRABLE) for r in reasons):
            plan = dict(plan)
            plan["passes"] = True
            plan["deferred_reasons"] = reasons
            plan["reasons"] = []
            plan["gap_readback_status"] = "DEFERRED_TO_BASELINE_FULL_RECOMPUTE"
            _STATE["deferred"].append(reasons)
        return plan
    assignment_plan.__r1_preflight2__ = True
    return assignment_plan


def _wrap_read_links(orig, print_fn):
    @functools.wraps(orig)
    def read_links(self):
        rows = orig(self)
        try:
            minimum = float(getattr(getattr(self, "policy", None), "minimum_cost_seconds", 0.001) or 0.001)
        except Exception:
            minimum = 0.001
        bad = []
        for key, row in rows.items():
            try:
                cost = float(row["t0_c_seconds"]) + 10.0 * float(row["addval1"])
            except Exception:
                continue
            if row.get("eligible") and cost < minimum:
                row["eligible"] = False          # "eligible" is not part of the fixed-link hash
                bad.append({"link": list(key), "t0_c_seconds": row["t0_c_seconds"],
                            "addval1": row["addval1"], "length": row.get("length")})
        if bad:
            new = [b for b in bad if b["link"] not in [x["link"] for x in _STATE["zero_cost_links"]]]
            _STATE["zero_cost_links"].extend(new)
            if new:
                try:
                    print_fn("R1 V24917 WARNING: %d link(s) with zero car travel time excluded from the ADDVAL1 "
                             "lever (fix length/v0 in the network): %s" % (len(new), [b["link"] for b in new]))
                except Exception:
                    pass
        return rows
    read_links.__r1_preflight2__ = True
    return read_links


def explain(folder) -> Dict[str, Any]:
    folder = Path(folder)
    out: Dict[str, Any] = {"release": RELEASE}
    try:
        pre = json.loads((folder / "00_PREFLIGHT.json").read_text(encoding="utf-8"))
    except Exception as exc:
        return {"release": RELEASE, "error": "00_PREFLIGHT.json unreadable: %r" % (exc,)}
    tg = pre.get("tg") or {}
    seq = pre.get("procseq") or {}
    plan = pre.get("supply_assignment") or {}
    out["tg_passes"] = bool(tg.get("passes"))
    out["tg_reasons"] = tg.get("reasons") or tg.get("failures") or tg.get("errors")
    out["procseq_passes"] = bool(seq.get("passes"))
    out["procseq_reasons"] = seq.get("reasons") or seq.get("failures") or seq.get("errors")
    out["assignment_plan_passes"] = bool(plan.get("passes"))
    out["assignment_plan_reasons"] = plan.get("reasons")
    unsafe = pre.get("unsafe_minimum_cost_keys") or []
    out["links_outside_positive_cost_domain"] = unsafe[:50]
    out["links_outside_positive_cost_domain_count"] = len(unsafe)
    return out


def _short(info: Dict[str, Any]) -> str:
    parts = []
    if not info.get("tg_passes", True):
        parts.append("TG_CONTRACT:%s" % json.dumps(info.get("tg_reasons"), default=str)[:300])
    if not info.get("procseq_passes", True):
        parts.append("PROCSEQ:%s" % json.dumps(info.get("procseq_reasons"), default=str)[:300])
    if not info.get("assignment_plan_passes", True):
        parts.append("ASSIGNMENT_PLAN:%s" % json.dumps(info.get("assignment_plan_reasons"), default=str)[:300])
    if info.get("links_outside_positive_cost_domain_count"):
        parts.append("LINKS_T0_PLUS_ADDVAL_NOT_POSITIVE(%d):%s" % (
            info["links_outside_positive_cost_domain_count"],
            json.dumps(info["links_outside_positive_cost_domain"][:10])))
    if info.get("error"):
        parts.append(info["error"])
    return " | ".join(parts) or "see 00_PREFLIGHT.json"


def _wrap_preflight(orig, SupplyContractError):
    @functools.wraps(orig)
    def preflight(self, folder):
        try:
            out = orig(self, folder)
            if _STATE["zero_cost_links"]:
                try:
                    (Path(folder) / "00_ZERO_COST_LINKS_EXCLUDED.json").write_text(json.dumps(
                        {"release": RELEASE, "links": _STATE["zero_cost_links"],
                         "note": "excluded from ADDVAL1 supply calibration; assignment still uses them"},
                        indent=2, default=str), encoding="utf-8")
                except Exception:
                    pass
            return out
        except SupplyContractError as exc:
            if str(exc) != "V240_LIVE_RECOMPUTE_PREFLIGHT_FAILED":
                raise
            info = explain(folder)
            try:
                (Path(folder) / "00_PREFLIGHT_FAILURE_EXPLAINED.json").write_text(
                    json.dumps(info, indent=2, default=str), encoding="utf-8")
            except Exception:
                pass
            raise SupplyContractError("V240_LIVE_RECOMPUTE_PREFLIGHT_FAILED: " + _short(info)) from exc
    preflight.__r1_preflight2__ = True
    return preflight


def install(print_fn=print) -> Dict[str, Any]:
    if _STATE["installed"]:
        return status()
    import r1_15a2_supply_visum as sv
    import r1_15a2_trial_adapter_v240 as a240
    from r1_15a2_supply import SupplyContractError
    if not getattr(a240.audit_assignment_scope, "__r1_preflight2_inactive_partial_scope__", False):
        a240.audit_assignment_scope = _wrap_inactive_partial_scope_audit(a240.audit_assignment_scope)
    if not getattr(sv.assignment_plan, "__r1_preflight2__", False):
        sv.assignment_plan = _wrap_plan(sv.assignment_plan)
    if not getattr(sv.VisumAdapter.read_links, "__r1_preflight2__", False):
        sv.VisumAdapter.read_links = _wrap_read_links(sv.VisumAdapter.read_links, print_fn)
    if not getattr(a240.VisumAdapter.preflight, "__r1_preflight2__", False):
        a240.VisumAdapter.preflight = _wrap_preflight(a240.VisumAdapter.preflight, SupplyContractError)
    _STATE["installed"] = True
    return status()


def status() -> Dict[str, Any]:
    return {"release": RELEASE, "installed": _STATE["installed"], "deferred": list(_STATE["deferred"]),
            "zero_cost_links": list(_STATE["zero_cost_links"])}


__all__ = ["RELEASE", "install", "status", "explain"]

# -*- coding: utf-8 -*-
"""Visum parameter read/write adapter for R1 STEP 15A2 V2.1.

All writes are explicit and followed by live readback.  This module does not run
Procedure Sequence and does not save a version; the master owns those actions.
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
import re
import inspect
import r1_15a2_com_compat as com

import r1_15a2_multiblock as mb
import r1_15a2_runtime_v1 as rt

TD_B_ATTRS = ("PARA_B", "Para_B", "ParaB", "PARAM_B", "ParamB", "ParameterB", "B")
TD_C_ATTRS = ("PARA_C", "Para_C", "ParaC", "PARAM_C", "ParamC", "ParameterC", "C")


def _is_active(value: Any) -> bool:
    return com.active_bool(value)


def _operation_type(value: Any) -> int:
    return com.exact_int(value, "OPERATIONTYPE")


def _operation_is(value: Any, number: int, words: Sequence[str]) -> bool:
    return _operation_type(value) == number


def _iter_operations(visum):
    try:
        return rt.get_all(visum.Procedures.Operations)
    except Exception:
        return []


def _find_operation(visum, number: int, words: Sequence[str], parameter_props: Sequence[str], required_codes: Sequence[str] = ()):
    best = None
    audit = []
    for idx, op in enumerate(_iter_operations(visum), start=1):
        otype = rt.att(op, "OPERATIONTYPE", "")
        active = _is_active(rt.att(op, "ACTIVE", ""))
        row = {
            "index": idx, "operation_type": mb.sval(otype), "active": int(active),
            "comment": mb.sval(rt.att(op, "COMMENT", "")), "selected": 0,
        }
        if not _operation_is(otype, number, words):
            audit.append(row); continue
        params = None; source = ""
        for prop in parameter_props:
            try:
                params = getattr(op, prop)
                if params is not None:
                    source = prop; break
            except Exception:
                pass
        row["parameter_source"] = source
        row["parameter_status"] = "OK" if params is not None else "UNREADABLE"
        score = (100 if active else 0)
        dset = ""
        if params is not None:
            for attr in ("DSTRATSET", "DStratSet", "DEMANDSTRATUMSET"):
                dset = mb.sval(rt.att(params, attr, ""))
                if dset:
                    break
            tokens = com.code_set(dset, "DSTRATSET") if dset else set()
            score += sum(1 for code in required_codes if code.upper() in tokens)
        row["dstratset"] = dset
        if params is not None and (best is None or score > best[0]):
            best = (score, op, params, row)
        audit.append(row)
    if best is None:
        return None, None, audit
    complete_active = [r for r in audit if r.get("active") and r.get("parameter_status") == "OK"
                       and set(c.upper() for c in required_codes) <= (com.code_set(r["dstratset"]) if r.get("dstratset") else set())]
    if len(complete_active) > 1:
        for r in complete_active:
            r["resolution_error"] = "AMBIGUOUS_ACTIVE_OPERATION_SCOPE"
        return None, None, audit
    best[3]["selected"] = 1
    return best[1], best[2], audit


def _dstrat_object(params, code: str, prefixes: Sequence[str]):
    names = []
    for prefix in prefixes:
        names.extend((prefix + "DStratParameters", prefix + "DStratParas"))
    names.extend(("DStratParameters", "DStratParas"))
    for name in names:
        try:
            obj = getattr(params, name)
        except Exception:
            continue
        if getattr(obj, "_oleobj_", None) is None and (inspect.ismethod(obj) or inspect.isfunction(obj) or inspect.isbuiltin(obj)):
            try:
                value = obj(code)
                if value is not None:
                    return value, name + "(code)"
            except Exception:
                pass
        for meth in ("ItemByKey", "Item"):
            try:
                value = getattr(obj, meth)(code)
                if value is not None:
                    return value, name + "." + meth
            except Exception:
                pass
        try:
            for value in rt.get_all(obj):
                live = mb.sval(rt.att(value, "DEMANDSTRATUMCODE", "") or rt.att(value, "CODE", ""))
                if live == code:
                    return value, name + " iteration"
        except Exception:
            pass
    return None, "NOT_FOUND"


def _read_any(obj, attrs: Sequence[str]):
    for name in attrs:
        try:
            value = obj.AttValue(name)
            if value not in (None, ""):
                return name, value, "AttValue"
        except Exception:
            pass
    for name in attrs:
        try:
            value = getattr(obj, name)
            if value not in (None, ""):
                return name, value, "property"
        except Exception:
            pass
    return "", None, "NOT_READ"


def _set_any(obj, attr: str, value: Any, mode: str):
    if not attr:
        raise RuntimeError("Cannot set unresolved Visum parameter")
    if mode == "property":
        try:
            setattr(obj, attr, value)
            return
        except Exception:
            pass
    obj.SetAttValue(attr, value)


def _formula_has_token(formula: str, token: str) -> bool:
    # Visum zone attributes in TG formulas are referenced in square brackets.
    # Requiring that form avoids false positives such as MY_ADD_PROD_W_BACKUP.
    return re.search(r"\[\s*" + re.escape(mb.sval(token)) + r"\s*\]", mb.sval(formula), flags=re.IGNORECASE) is not None


def audit_trip_generation_contract(visum, cfg: Mapping[str, Any]) -> Dict[str, Any]:
    contract = cfg.get("tg_dependency_contract", {}) or {}
    required_dstrats = list(contract.get("required_dstrata", []))
    op, params, operation_rows = _find_operation(
        visum, 45, ("trip", "generation"),
        ("TripGenerationParameters", "TripGenerationParameter"), required_dstrats,
    )
    failures: List[str] = []
    rows: List[Dict[str, Any]] = []
    if params is None:
        failures.append("TRIP_GENERATION_OPERATION_NOT_FOUND")
    selected_ops = [r for r in operation_rows if int(r.get("selected", 0) or 0) == 1]
    if selected_ops and int(selected_ops[0].get("active", 0) or 0) != 1:
        failures.append("SELECTED_TRIP_GENERATION_OPERATION_INACTIVE")
    if selected_ops:
        dset = mb.sval(selected_ops[0].get("dstratset"))
        tokens = com.code_set(dset) if dset else set()
        missing_set = [code for code in required_dstrats if code.upper() not in tokens]
        if missing_set:
            failures.append("TRIP_GENERATION_DSTRATSET_MISSING:%s" % ",".join(missing_set))
    expected = contract.get("dstrata", {}) or {}
    for code, spec in sorted(expected.items()):
        d_obj, source = _dstrat_object(params, code, ("TripGeneration",)) if params is not None else (None, "NO_PARAMS")
        row = {"dstrat_code": code, "source": source, "status": "OK"}
        if d_obj is None:
            row["status"] = "DSTRAT_NOT_FOUND"; failures.append("TG_DSTRAT_MISSING:%s" % code); rows.append(row); continue
        _, prod, _ = _read_any(d_obj, ("PRODUCTIONFUNCTION", "ProductionFunction", "PRODFUNCTION", "ProdFunction"))
        _, att, _ = _read_any(d_obj, ("ATTRACTIONFUNCTION", "AttractionFunction", "ATTFUNCTION", "AttFunction"))
        prod_text = mb.sval(prod); att_text = mb.sval(att)
        row["production_function"] = prod_text
        row["attraction_function"] = att_text
        # Visum TG parameters normally contain [FP_*] / [FA_*] references;
        # population and ZAHR are in those zone-attribute formulas, not directly
        # in PRODUCTIONFUNCTION. The old one-layer check falsely rejected them.
        # Older contracts without outer_attribute continue to use inline tokens.
        def validate_binding(value, prefix):
            outer = mb.sval(spec.get(prefix + "_outer_attribute", ""))
            additive = mb.sval(spec.get(prefix + "_additive_attribute", ""))
            if additive:
                # This model's active TG formula contains an independent 09F4
                # pre-input per stratum.  Demand must not silently drop, swap,
                # duplicate or scale it: require the exact approved two terms.
                expression = (r"\s*\[\s*" + re.escape(outer) + r"\s*\]"
                              + r"\s*\+\s*\[\s*" + re.escape(additive)
                              + r"\s*\]\s*")
                if outer and re.fullmatch(expression, mb.sval(value), flags=re.IGNORECASE):
                    return [], "VERIFIED_OUTER_PLUS_09F4_PREFEED"
                return ["EXPECTED_EXACT_OUTER_PLUS_09F4:[%s]+[%s]" % (outer, additive)], "INVALID"
            inline_missing = [token for token in spec.get(prefix + "_tokens", [])
                              if not _formula_has_token(value, token)]
            if not outer:
                return inline_missing, "INLINE_LEGACY" if not inline_missing else "INVALID"
            if re.fullmatch(r"\[\s*" + re.escape(outer) + r"\s*\]", value.strip(), flags=re.I):
                return [], "VERIFIED_OUTER_ZONE_ATTRIBUTE_REFERENCE"
            if not inline_missing:
                if (spec.get(prefix + "_inline_population_required", False)
                        and not _formula_has_token(value, cfg.get("zahr", {}).get("population_attr", "POP_ZP"))):
                    inline_missing.append(cfg.get("zahr", {}).get("population_attr", "POP_ZP"))
                if not inline_missing:
                    return [], "VERIFIED_INLINE_TG_FORMULA"
            return inline_missing or ["EXPECTED_EXACT_OUTER_REFERENCE:[%s]" % outer], "INVALID"
        missing_prod, prod_mode = validate_binding(prod_text, "production")
        missing_att, att_mode = validate_binding(att_text, "attraction")
        row["production_binding_mode"] = prod_mode
        row["attraction_binding_mode"] = att_mode
        row["missing_production_tokens"] = ",".join(missing_prod)
        row["missing_attraction_tokens"] = ",".join(missing_att)
        if missing_prod or missing_att:
            row["status"] = "FORMULA_CONTRACT_MISMATCH"
            failures.append("TG_FORMULA_MISMATCH:%s" % code)
        rows.append(row)

    zone_attribute_rows = []
    # The actual Visum 2026 Zones.Attributes catalog reports these prefeed
    # UDAs as ValueType=2 (Real).  Do not accept a text alias silently.
    expected_types = contract.get("expected_zone_attribute_types", {}) or {}
    if expected_types:
        try:
            catalog = rt.get_all(visum.Net.Zones.Attributes)
            actual_types = {}
            for definition in catalog:
                attr_id = mb.sval(getattr(definition, "ID", "")).strip().upper()
                if attr_id in actual_types:
                    raise RuntimeError("DUPLICATE_ZONE_ATTRIBUTE_DEFINITION:" + attr_id)
                if attr_id:
                    actual_types[attr_id] = com.exact_int(getattr(definition, "ValueType"), "ValueType:"+attr_id)
            for name, intended in sorted(expected_types.items()):
                actual = actual_types.get(name.upper())
                zone_attribute_rows.append({"attr": name, "status": "TYPE_OK" if actual == int(intended) else "TYPE_MISMATCH",
                                            "expected_value_type": int(intended), "actual_value_type": actual})
                if actual != int(intended):
                    failures.append("TG_ZONE_ATTRIBUTE_TYPE_MISMATCH:%s" % name)
        except Exception as exc:
            failures.append("TG_ZONE_ATTRIBUTE_SCHEMA_UNREADABLE")
            zone_attribute_rows.append({"status": "SCHEMA_UNREADABLE", "error": rt.compact_error(exc)})
    zones = rt.zone_numbers(visum)
    for attr in contract.get("required_zone_attributes", []):
        try:
            vals = rt.read_zone_attr_strict(visum, attr, zones)
            zone_attribute_rows.append({"attr": attr, "status": "OK", "rows": len(vals), "nonfinite": 0})
        except Exception as exc:
            failures.append("TG_ZONE_ATTRIBUTE_UNREADABLE:%s" % attr)
            zone_attribute_rows.append({"attr": attr, "status": "UNREADABLE", "error": rt.compact_error(exc)})
    return {
        "passes": not failures,
        "failures": failures,
        "rows": rows,
        "operation_rows": operation_rows,
        "zone_attribute_rows": zone_attribute_rows,
        "contract_id": contract.get("contract_id", ""),
    }


def read_td_parameter_state(visum) -> Dict[str, Any]:
    required_codes = [x["dstrat_code"] for x in mb.COMPONENT_REGISTRY.values()]
    op, params, operation_rows = _find_operation(
        visum, 46, ("trip", "distribution"),
        ("TripDistributionParameters", "TripDistributionParameter"), required_codes,
    )
    if params is None:
        raise RuntimeError("Could not locate readable Trip Distribution operation")
    selected_ops = [r for r in operation_rows if int(r.get("selected", 0) or 0) == 1]
    if not selected_ops or int(selected_ops[0].get("active", 0) or 0) != 1:
        raise RuntimeError("Selected Trip Distribution operation is inactive or unresolved")
    if selected_ops:
        dset = mb.sval(selected_ops[0].get("dstratset"))
        tokens = com.code_set(dset) if dset else set()
        missing_set = [code for code in required_codes if code.upper() not in tokens]
        if missing_set:
            raise RuntimeError("Trip Distribution DStratSet misses: %s" % ",".join(missing_set))
    rows = []
    objects = {}
    for component, reg in mb.COMPONENT_REGISTRY.items():
        d_obj, source = _dstrat_object(params, reg["dstrat_code"], ("TripDistribution",))
        if d_obj is None:
            rows.append({"component": component, "dstrat_code": reg["dstrat_code"], "matrix_no": reg["matrix_no"], "status": "DSTRAT_NOT_FOUND", "source": source})
            continue
        grav = d_obj; grav_source = "DStratPara"
        for prop in ("GravitationParameters", "GravityParameters", "DistributionParameters"):
            try:
                candidate = getattr(d_obj, prop)
                if candidate is not None:
                    grav = candidate; grav_source = prop; break
            except Exception:
                pass
        b_attr, b_raw, b_mode = _read_any(grav, TD_B_ATTRS)
        c_attr, c_raw, c_mode = _read_any(grav, TD_C_ATTRS)
        b = mb.fval(b_raw, None); c = mb.fval(c_raw, None)
        status = "OK" if b is not None and c is not None else "PARAM_READ_INCOMPLETE"
        row = {
            "component": component, "family": reg["family"], "dstrat_code": reg["dstrat_code"],
            "matrix_no": reg["matrix_no"], "status": status, "source": source,
            "gravitation_source": grav_source, "b_attr": b_attr, "current_b": b,
            "b_mode": b_mode, "c_attr": c_attr, "current_c": c, "c_mode": c_mode,
        }
        rows.append(row)
        objects[component] = {"dstrat": d_obj, "grav": grav, **row}
    return {"rows": rows, "objects": objects, "operation_rows": operation_rows}


def td_parameter_map(state: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {mb.sval(r.get("component")): dict(r) for r in state.get("rows", []) if r.get("status") == "OK"}


def apply_td_candidates(visum, candidates: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    state = read_td_parameter_state(visum)
    objects = state["objects"]
    audit = []
    for row0 in candidates:
        row = dict(row0); comp = mb.sval(row.get("component"))
        info = objects.get(comp)
        if not info:
            audit.append(dict(row, status="OBJECT_NOT_FOUND")); continue
        target_b = float(row["candidate_b"]); target_c = float(row["candidate_c"])
        try:
            _set_any(info["grav"], info["b_attr"], target_b, info["b_mode"])
            _set_any(info["grav"], info["c_attr"], target_c, info["c_mode"])
            _, rb_raw, _ = _read_any(info["grav"], TD_B_ATTRS)
            _, rc_raw, _ = _read_any(info["grav"], TD_C_ATTRS)
            rb = mb.fval(rb_raw, None); rc = mb.fval(rc_raw, None)
            ok = rb is not None and rc is not None and abs(rb - target_b) <= 1.0e-8 and abs(rc - target_c) <= 1.0e-8
            audit.append(dict(row, readback_b=rb, readback_c=rc, status="OK" if ok else "READBACK_MISMATCH"))
        except Exception as exc:
            audit.append(dict(row, status="ERROR", error=rt.compact_error(exc)))
    return audit


def verify_td_persistence(visum, candidates: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    state = read_td_parameter_state(visum)
    pmap = td_parameter_map(state)
    out = []
    for row in candidates:
        comp = mb.sval(row.get("component")); live = pmap.get(comp, {})
        b = mb.fval(live.get("current_b"), None); c = mb.fval(live.get("current_c"), None)
        tb = float(row["candidate_b"]); tc = float(row["candidate_c"])
        ok = b is not None and c is not None and abs(b - tb) <= 1.0e-8 and abs(c - tc) <= 1.0e-8
        out.append({"component": comp, "target_b": tb, "target_c": tc, "live_b": b, "live_c": c, "status": "OK" if ok else "OVERWRITTEN_OR_CHANGED"})
    return out


__all__ = [
    "audit_trip_generation_contract", "read_td_parameter_state", "td_parameter_map",
    "apply_td_candidates", "verify_td_persistence",
]

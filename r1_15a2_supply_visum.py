"""Visum adapter for the V2.2 shared controller.

Uses the existing official PrT list exporter and existing TG/TD implementation.
No alternative routing, guessed operation IDs, or direct OD writes.
"""
from __future__ import annotations
from contextlib import contextmanager
from pathlib import Path
import copy
import hashlib
import importlib.util
import json
import math
import re
import numpy as np

import r1_15a2_com_compat as com
import r1_15a2_core as core
import r1_15a2_multiblock as mb
import r1_15a2_runtime_v1 as rt
import r1_15a2_visum_parameters as vp
from r1_15a2_perf_v246 import optional_span
from r1_15a2_supply import (SupplyContractError, SupplyPolicy, ActualRouteCollector,
    propose_supply, canonical_hash, key_text, number, integer, check_addval_change,
    validate_impedance_csv, observation_identity)

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("r1_15a2_v21_base_for_v22", HERE / "R1_15A2_ACTUAL_PATH_MULTIBLOCK_CALIBRATION_MASTER_V2_1.py")
base = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(base)


def strict_collection(collection):
    try:
        return com.collection_items(collection)
    except RuntimeError as exc:
        raise SupplyContractError(str(exc)) from exc


def _multi_att_values(collection, attribute):
    """Read one attribute for all objects, explicitly including inactive rows.

    Visum returns pairs (collection index, value).  The collection index is an
    ordering key, not a network object key, so callers must join attributes on
    that first column and independently verify object identity.
    """
    method = getattr(collection, "GetMultiAttValues", None)
    if method is None:
        raise SupplyContractError("GET_MULTI_ATT_VALUES_UNAVAILABLE")
    try:
        rows = list(method(attribute, False))
    except TypeError:
        rows = list(method(attribute))
    except Exception as exc:
        raise SupplyContractError("GET_MULTI_ATT_VALUES_FAILED:%s" % attribute) from exc
    result = {}
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) != 2:
            raise SupplyContractError("GET_MULTI_ATT_VALUES_SCHEMA:%s" % attribute)
        index = integer(row[0], "collection_index")
        if index in result:
            raise SupplyContractError("GET_MULTI_ATT_VALUES_DUPLICATE_INDEX:%s" % attribute)
        result[index] = row[1]
    if not result:
        raise SupplyContractError("GET_MULTI_ATT_VALUES_EMPTY:%s" % attribute)
    return result


def _bulk_link_rows(collection, attrs, *, verify_object_no=True):
    objects = list(strict_collection(collection))
    if not objects:
        raise SupplyContractError("EMPTY_LINK_NETWORK")
    columns = {name: _multi_att_values(collection, attribute)
               for name, attribute in attrs.items()}
    index_sets = {tuple(sorted(values)) for values in columns.values()}
    if len(index_sets) != 1:
        raise SupplyContractError("GET_MULTI_ATT_VALUES_INDEX_SET_MISMATCH")
    indices = next(iter(index_sets))
    if len(indices) != len(objects):
        raise SupplyContractError("GET_MULTI_ATT_VALUES_OBJECT_COUNT_MISMATCH")
    rows = []
    for obj, index in zip(objects, indices):
        raw = {name: columns[name][index] for name in attrs}
        if verify_object_no:
            object_no = integer(obj.AttValue(attrs["link_no"]), "object_link_no")
            if object_no != integer(raw["link_no"], "bulk_link_no"):
                raise SupplyContractError("GET_MULTI_ATT_VALUES_OBJECT_ORDER_MISMATCH")
        raw["object"] = obj
        rows.append(raw)
    return rows


def _scalar_link_rows(collection, attrs):
    return [dict({name: obj.AttValue(attribute) for name, attribute in attrs.items()},
                 object=obj)
            for obj in strict_collection(collection)]


def read_path_attribute(visum, spec):
    obj = visum
    for name in spec.get("object_path", []):
        if not isinstance(name, str) or not name.isidentifier() or name.startswith("_"):
            raise SupplyContractError("INVALID_COM_OBJECT_PATH")
        obj = getattr(obj, name)
    name = spec.get("attribute")
    if not isinstance(name, str) or not name:
        raise SupplyContractError("LIVE_ATTRIBUTE_NOT_CONFIGURED")
    return obj.AttValue(name)


def assignment_gap_evidence(visum, spec):
    """Read exact operation-scoped PrT quality list, never an invented Net.GAP.

    Live compatibility evidence: R1 09Q, Visum 2026, ten quality rows,
    operation 20, 14 DSegs, unique maximum iteration 2.
    Historical rows are diagnostic only; they do NOT prove run freshness.
    """
    source = str(spec.get("source", "LEGACY_NET_ATTRIBUTE")).strip().upper()
    if source == "LEGACY_NET_ATTRIBUTE":
        gap = number(read_path_attribute(visum, spec), "assignment gap")
        if gap < 0:
            raise SupplyContractError("NEGATIVE_ASSIGNMENT_GAP")
        return {"source": source, "gap": gap, "freshness": "UNVERIFIED"}
    if source != "PRT_ASS_QUALITY_LIST":
        raise SupplyContractError("UNSUPPORTED_GAP_READBACK_SOURCE:" + source)
    position = integer(spec.get("operation_no", 0))
    rows = com.operation_rows(visum)
    if position <= 0 or position > len(rows):
        raise SupplyContractError("QUALITY_OPERATION_POSITION_UNAVAILABLE")
    op = rows[position - 1]
    if op["position"] != position or op["type"] != com.ASSIGNMENT_PRT or not op["active"]:
        raise SupplyContractError("QUALITY_OPERATION_NOT_ACTIVE_PRT")
    params = com.object_property(op["object"], "PrTAssignmentParameters")
    scope_text = params.AttValue("DSEGSET")
    if not isinstance(scope_text, str) or not scope_text.strip():
        raise SupplyContractError("QUALITY_DSEG_SCOPE_MISSING")
    parts = [x.strip("\"' ").upper() for x in re.split(r"[,;{}\s]+", scope_text) if x.strip("\"' ")]
    if not parts or len(parts) != len(set(parts)):
        raise SupplyContractError("QUALITY_DSEG_SCOPE_AMBIGUOUS")
    required = frozenset(parts)
    quality = com.object_property(com.object_property(com.object_property(visum, "Workbench"), "Lists"), "CreatePrTAssQualityList")
    for column in ("DSEGCODE", "ITERATION", "GAP"):
        quality.AddColumn(column)
    count = com.exact_int(com.member_value(getattr(quality, "NumActiveElements")), "QUALITY_ROWS")
    if count <= 0 or count > 50000:
        raise SupplyContractError("QUALITY_LIST_INVALID_ROW_COUNT")
    exact = []
    scopes = {}
    for first in range(1, count + 1, 400):
        last = min(count, first + 399)
        page = list(quality.SaveToArray(first, last))
        if len(page) != last - first + 1:
            raise SupplyContractError("QUALITY_LIST_INCOMPLETE_PAGE")
        for ix, rec in enumerate(page, first):
            if len(rec) != 3:
                raise SupplyContractError("QUALITY_LIST_INVALID_WIDTH:%d" % ix)
            raw_code, raw_iter, raw_gap = rec
            if not isinstance(raw_code, str) or not raw_code.strip():
                raise SupplyContractError("QUALITY_LIST_EMPTY_DSEG_CODE")
            tokens = [x.strip("\"' ").upper() for x in re.split(r"[,;{}\s]+", raw_code) if x.strip("\"' ")]
            if not tokens or len(tokens) != len(set(tokens)):
                raise SupplyContractError("QUALITY_LIST_AMBIGUOUS_DSEG_CODE")
            dsegs = frozenset(tokens)
            iteration = com.exact_int(raw_iter, "QUALITY_ITERATION")
            gap = com.finite_float(raw_gap, "QUALITY_GAP")
            if iteration < 1 or gap < 0:
                raise SupplyContractError("QUALITY_LIST_INVALID_VALUE")
            obj = {"row": ix, "iteration": iteration, "gap": gap}
            key = ",".join(sorted(dsegs))
            scopes.setdefault(key, []).append(obj)
            if dsegs == required:
                exact.append(obj)
    if not exact:
        raise SupplyContractError("QUALITY_LIST_NO_EXACT_OPERATION_SCOPE")
    max_iter = max(r["iteration"] for r in exact)
    winners = [r for r in exact if r["iteration"] == max_iter]
    if len(winners) != 1:
        raise SupplyContractError("QUALITY_LIST_LAST_ITERATION_NOT_UNIQUE")
    selected = winners[0]
    latest_scopes = {}
    for key, candidates in scopes.items():
        m = max(r["iteration"] for r in candidates)
        ties = [r for r in candidates if r["iteration"] == m]
        if len(ties) != 1:
            raise SupplyContractError("QUALITY_LIST_AMBIGUOUS_SCOPE_ITERATION:" + key)
        latest_scopes[key] = {"iteration": m, "gap": ties[0]["gap"]}
    return {"source": source, "operation_no": position,
            "operation_dsegs": sorted(required), "quality_rows": count,
            "exact_scope_rows": len(exact), "iteration": max_iter,
            "quality_row": selected["row"], "gap": selected["gap"],
            "latest_gap_by_scope": latest_scopes,
            "freshness": "UNVERIFIED_HISTORICAL_UNLESS_READ_AFTER_SUCCESSFUL_EXPLICIT_ASSIGNMENT"}


def operation_inventory(visum, cfg):
    try:
        return com.operation_rows(visum)
    except RuntimeError as exc:
        raise SupplyContractError(str(exc)) from exc


def assignment_plan(visum, cfg):
    inventory = operation_inventory(visum, cfg)
    approved = cfg.get("supply", {}).get("assignment_operations", [])
    reasons = []
    if not approved:
        reasons.append("ASSIGNMENT_OPERATION_NUMBERS_AND_TYPES_REQUIRE_APPROVAL")
    byno = {r["no"]: r for r in inventory}
    wanted = set()
    for rule in approved:
        no = integer(rule["no"]); typ = integer(rule["operation_type"])
        if no in wanted:
            raise SupplyContractError("DUPLICATE_APPROVED_OPERATION")
        wanted.add(no)
        row = byno.get(no)
        if row is None or row["type"] != typ or not row["active"] or typ != com.ASSIGNMENT_PRT:
            reasons.append("APPROVED_ASSIGNMENT_OPERATION_MISMATCH:%s" % no)
        if row and "15A2" in (row["comment"] + row["name"]).upper():
            reasons.append("RECURSIVE_MASTER_OPERATION")
    gap = cfg.get("supply", {}).get("gap_readback", {})
    quality_evidence = None
    if gap.get("source", "LEGACY_NET_ATTRIBUTE").upper() == "LEGACY_NET_ATTRIBUTE" and not gap.get("attribute"):
        reasons.append("ASSIGNMENT_GAP_READBACK_NOT_CONFIGURED")
    else:
        try:
            quality_evidence = assignment_gap_evidence(visum, gap)
            if number(gap.get("maximum_gap", 1e-6)) <= 0:
                raise SupplyContractError("INVALID_GAP_POLICY_MAXIMUM")
        except Exception as exc:
            reasons.append("ASSIGNMENT_GAP_READBACK_UNAVAILABLE:" + str(exc))
    covered = set()
    for rule in approved:
        row = byno.get(integer(rule["no"]))
        if row is None:
            continue
        try:
            obj = row["object"]
            for name in rule.get("dseg_object_path", ["PrTAssignmentParameters"]):
                if not isinstance(name, str) or not name.isidentifier() or name.startswith("_"):
                    raise SupplyContractError("INVALID_DSEG_OBJECT_PATH")
                obj = com.object_property(obj, name)
            value = obj.AttValue(rule.get("dseg_attribute", "DSEGSET"))
            if not isinstance(value, str):
                raise SupplyContractError("NONSTRING_DSEGSET_REQUIRES_EXPLICIT_ADAPTER")
            covered.update(core.norm_code(x) for x in re.split(r"[,;{}\s]+", value) if x)
        except Exception as exc:
            reasons.append("ASSIGNMENT_DSEG_SCOPE_UNREADABLE:%s:%s" % (rule["no"], exc))
    required = {core.norm_code(x) for x in cfg.get("supply", {}).get("passenger_dsegs", [])}
    required.update(core.norm_code(x) for x in cfg.get("supply", {}).get("freight_dsegs", []))
    if approved and not required <= covered:
        reasons.append("ASSIGNMENT_OMITS_REQUIRED_PASSENGER_OR_FREIGHT:" + ",".join(sorted(required-covered)))
    extra = {core.norm_code(x) for x in cfg.get("supply", {}).get("allowed_extra_assignment_dsegs", [])}
    if approved and covered - required - extra:
        reasons.append("UNAPPROVED_EXTRA_ASSIGNMENT_DSEGS:" + ",".join(sorted(covered-required-extra)))
    return {"passes": not reasons, "reasons": reasons, "approved_numbers": sorted(wanted),
            "gap_readback_evidence": quality_evidence,
            "covered_dsegs": sorted(covered),
            "preserved_group_numbers": [r["no"] for r in inventory if r["type"] == com.GROUP and r["active"]],
            "inventory": [{k: v for k, v in r.items() if k != "object"} for r in inventory]}


@contextmanager
def assignment_only_operations(visum, cfg):
    """Run approved PrT assignments with originally-active groups; restore all flags.

    Groups are structural containers, not computations. Deactivating the parent
    can suppress selected child assignment operations in the live sequence.
    """
    plan = assignment_plan(visum, cfg)
    if not plan["passes"]:
        raise SupplyContractError("ASSIGNMENT_ONLY_PLAN_BLOCKED:" + ";".join(plan["reasons"]))
    old = operation_inventory(visum, cfg)
    selected = set(plan["approved_numbers"]) | set(plan["preserved_group_numbers"])
    try:
        for row in old:
            expected = int(row["no"] in selected)
            row["object"].SetAttValue("ACTIVE", expected)
            if int(com.active_bool(row["object"].AttValue("ACTIVE"))) != expected:
                raise SupplyContractError("OPERATION_FLAG_WRITE_MISMATCH")
        current = operation_inventory(visum, cfg)
        if {r["no"] for r in current if r["active"]} != selected:
            raise SupplyContractError("ASSIGNMENT_ONLY_SELECTION_MISMATCH")
        yield plan
    finally:
        errors = []
        for row in old:
            try:
                row["object"].SetAttValue("ACTIVE", row["active"])
                if int(com.active_bool(row["object"].AttValue("ACTIVE"))) != row["active"]:
                    raise SupplyContractError("ACTIVE_READBACK")
            except Exception as exc:
                errors.append(str(exc))
        if errors:
            raise SupplyContractError("OPERATION_FLAGS_RESTORE_FAILED:" + ";".join(errors))
        restored = operation_inventory(visum, cfg)
        if [(r["no"], r["type"], r["active"]) for r in old] != [(r["no"], r["type"], r["active"]) for r in restored]:
            raise SupplyContractError("OPERATION_SET_CHANGED")


class VisumAdapter:
    runtime_backend = "VISUM_COM"
    def __init__(self, visum, cfg):
        self.visum = visum
        self.cfg = cfg
        self.policy = SupplyPolicy.from_config(cfg)
        self.com_retry_policy = dict(cfg.get("com_resilience", {}) or {})
        expected_zone_nos = list(range(1, rt.EXPECTED_ZONES + 1))
        self.zones, self.zone_write_index_by_no = com.zone_identity(
            visum, expected_zone_nos, self.com_retry_policy)
        if self.zones != expected_zone_nos:
            raise SupplyContractError("ZONE_MATRIX_AXIS_ORDER_MISMATCH")
        self.zone_readback_tolerance = number(
            self.com_retry_policy.get("zone_readback_tolerance", 1.0e-7),
            "zone readback tolerance")
        self.actuatable_zones = None
        self.baseline_addval = None
        self.supply_path_proof = None
        self.generation_reference_values = None
        self.generation_reference_hash = None
        rt.Visum = visum
        base.Visum = visum

    def preflight(self, folder):
        folder = Path(folder)
        if len(self.zones) != integer(self.cfg.get("expected_zones", 681)):
            raise SupplyContractError("ZONE_AUTHORITY_COUNT")
        supply = self.cfg["supply"]
        rt.write_json(folder / "00_DSEG_INVENTORY.json", [
            {k: v for k, v in row.items() if k != "object"} for row in rt.list_dsegs(self.visum)])
        formula = validate_impedance_csv(HERE / supply["impedance_authority_csv"])
        expected_hash = supply["impedance_file_sha256"]
        if rt.sha256_file(HERE / supply["impedance_authority_csv"]) != expected_hash:
            raise SupplyContractError("IMPEDANCE_AUTHORITY_FILE_CHANGED")
        for name, digest in supply.get("fixed_input_hashes", {}).items():
            if rt.sha256_file(HERE / name) != digest:
                raise SupplyContractError("FROZEN_VDF_AUTHORITY_CHANGED")
        self.actuatable_zones, zinfo = base.generation_actuator_zone_scope(
            self.visum, self.zones, self.cfg, folder,
            zone_indices=self.zone_write_index_by_no, retry_policy=self.com_retry_policy)
        tg = vp.audit_trip_generation_contract(self.visum, self.cfg)
        seq = rt.audit_procseq(self.visum, folder, self.cfg)
        plan = assignment_plan(self.visum, self.cfg)
        rt.write_json(folder / "00_SUPPLY_ASSIGNMENT_PLAN.json", plan)
        links = self.read_links()
        self.baseline_addval = {key: row["addval1"] for key, row in links.items()}
        eligible = [key for key, row in links.items() if row["eligible"]]
        unsafe = [list(k) for k in eligible if links[k]["t0_c_seconds"]+10*links[k]["addval1"] < self.policy.minimum_cost_seconds]
        if unsafe:
            plan["reasons"].append("BASELINE_OUTSIDE_POSITIVE_COST_DOMAIN")
            plan["passes"] = False
        snapshot = self.snapshot()
        if self.cfg.get("generation_signed_refinement", {}).get("enabled") is True:
            self.generation_reference_values = copy.deepcopy(snapshot.get("generation_values", {}))
            self.generation_reference_hash = canonical_hash(self.generation_reference_values)
            rt.write_json(folder / "00_GENERATION_COEFFICIENT_REFERENCE.json", {
                "schema": "R1_15A2_GENERATION_COEFFICIENT_REFERENCE_V2492",
                "policy": "RUN_START_REFERENCE_FIXED_FOR_SIGNED_REFINEMENT",
                "state_hash": snapshot.get("state_hash"),
                "generation_reference_hash": self.generation_reference_hash,
                "values": self.generation_reference_values,
            })
        if self.cfg.get("apply") and (not tg.get("passes") or not seq.get("passes") or not plan["passes"]):
            rt.write_json(folder / "00_PREFLIGHT_BLOCKED.json", {"tg": tg, "procseq": seq, "supply": plan, "unsafe_keys": unsafe})
            raise SupplyContractError("LIVE_APPLY_PREFLIGHT_BLOCKED")
        result = {"tg": tg, "procseq": seq, "supply_assignment": plan, "zones": zinfo,
                  "impedance": formula, "impedance_basis": "USER_SUPPLIED_EXPORTED_FORMULA_AUTHORITY",
                  "eligible_links": len(eligible), "unsafe_minimum_cost_keys": unsafe,
                  "apply_preflight_passes": bool(tg.get("passes") and seq.get("passes") and plan["passes"])}
        rt.write_json(folder / "00_PREFLIGHT.json", result)
        return result

    def read_links(self):
        maps = self.cfg["supply"].get("link_attributes", {})
        attrs = {"link_no": "NO", "from_node_no": "FROMNODENO", "to_node_no": "TONODENO",
                 "addval1": "ADDVAL1", "t0_c_seconds": "T0_PRTSYS(C)", "capacity": "CAPPRT",
                 "length": "LENGTH", "type_no": "TYPENO", "tsys": "TSYSSET"}
        attrs.update(maps)
        excluded = {tuple(integer(x) for x in key) for key in self.cfg["supply"].get("excluded_link_keys", [])}
        allowed_types = self.cfg["supply"].get("editable_link_types")
        performance = self.cfg.get("performance", {}).get("bulk_link_read", {})
        use_bulk = performance.get("enabled", False) is True
        fallback = performance.get("fallback_to_scalar", True) is True
        verify_no = performance.get("verify_object_no", True) is True
        mode = "SCALAR"
        with optional_span(self, "COM_READ_LINKS", requested_mode="BULK" if use_bulk else "SCALAR"):
            if use_bulk:
                try:
                    raw_rows = _bulk_link_rows(self.visum.Net.Links, attrs,
                                               verify_object_no=verify_no)
                    mode = "BULK_GET_MULTI_ATT_VALUES"
                except Exception:
                    if not fallback:
                        raise
                    raw_rows = _scalar_link_rows(self.visum.Net.Links, attrs)
                    mode = "SCALAR_FALLBACK"
            else:
                raw_rows = _scalar_link_rows(self.visum.Net.Links, attrs)
        rows = {}
        for raw in raw_rows:
            key = tuple(integer(raw[name]) for name in ("link_no", "from_node_no", "to_node_no"))
            if key in rows:
                raise SupplyContractError("DUPLICATE_DIRECTED_LINK_KEY")
            for name in ("addval1", "t0_c_seconds", "capacity", "length", "type_no"):
                raw[name] = number(raw[name], name)
            if min(raw["t0_c_seconds"], raw["capacity"], raw["length"]) < 0:
                raise SupplyContractError("INVALID_PHYSICAL_LINK_ATTRIBUTE")
            tsys = {core.norm_code(x) for x in re.split(r"[,;{}\s]+", str(raw["tsys"])) if x}
            raw["tsys"] = sorted(tsys)
            raw["eligible"] = bool({"C", "C_NOT"} & tsys) and key not in excluded
            if allowed_types is not None:
                raw["eligible"] = raw["eligible"] and integer(raw["type_no"]) in allowed_types
            rows[key] = raw
        if not rows:
            raise SupplyContractError("EMPTY_LINK_NETWORK")
        self.last_link_read_mode = mode
        telemetry = getattr(self, "telemetry", None)
        if telemetry is not None:
            telemetry.event("COM_READ_LINKS_RESULT", mode=mode, link_count=len(rows), attribute_count=len(attrs))
        return rows

    def snapshot(self):
        links = self.read_links()
        fixed = []
        values = {}
        for key, row in sorted(links.items()):
            values[key_text(key)] = row["addval1"]
            fixed.append({k: v for k, v in row.items() if k not in ("addval1", "object", "eligible")})
        dsrows = rt.list_dsegs(self.visum)
        if len({r["norm_code"] for r in dsrows}) != len(dsrows):
            raise SupplyContractError("DUPLICATE_DSEG_IDENTITY")
        dsmap = {r["norm_code"]: r.get("matrix_no") for r in dsrows}
        required = {core.norm_code(x) for x in self.cfg["supply"]["passenger_dsegs"] + self.cfg["supply"].get("freight_dsegs", [])}
        if not required <= set(dsmap):
            raise SupplyContractError("REQUIRED_DEMAND_SEGMENT_MISSING:" + ",".join(sorted(required-set(dsmap))))
        unbound = sorted(code for code in required if dsmap[code] in (None, ""))
        if unbound:
            raise SupplyContractError("REQUIRED_DSEG_ODMATRIX_UNREADABLE:" + ",".join(unbound))
        numbers = set(integer(r["matrix_no"]) for r in dsrows if r.get("matrix_no") not in (None, ""))
        numbers.update(integer(x) for x in self.cfg["supply"].get("component_matrix_nos", []))
        mats = []
        for no in sorted(numbers):
            mat = self.visum.Net.Matrices.ItemByKey(no)
            row = rt._fingerprint_matrix_object(mat, "MATRIX:%d" % no, "ALL_DEMAND")
            expected_zones = self.cfg.get("expected_zones")
            if expected_zones is not None and (row["rows"], row["cols"]) != (int(expected_zones), int(expected_zones)):
                raise SupplyContractError("DEMAND_MATRIX_AXIS_SHAPE_MISMATCH:%s" % no)
            if not math.isfinite(row["sum"]) or row["sum"] < 0:
                raise SupplyContractError("NONFINITE_OR_NEGATIVE_DEMAND")
            mats.append({k: row[k] for k in ("matrix_no", "rows", "cols", "sha256_float64_le")})
        if not mats:
            raise SupplyContractError("EMPTY_DEMAND_FINGERPRINT")
        zone = {attr: {str(z): number(v) for z, v in zip(
                    self.zones, rt.read_zone_attr_strict(
                        self.visum, attr, self.zones,
                        zone_indices=self.zone_write_index_by_no,
                        retry_policy=self.com_retry_policy))}
                for attr in mb.GENERATION_ATTRS}
        td = base.td_snapshot(self.visum)
        if len(td) != len(mb.COMPONENT_REGISTRY) or any(r.get("status") != "OK" for r in td):
            raise SupplyContractError("COMPONENT_PARAMETER_SNAPSHOT_FAILED")
        ops = [{k: v for k, v in r.items() if k != "object"} for r in operation_inventory(self.visum, self.cfg)]
        result = {"addval1": values, "addval_hash": canonical_hash(values),
                  "fixed_link_hash": canonical_hash(fixed), "matrix_hash": canonical_hash(mats),
                  "matrices": mats, "dseg_map": dsmap,
                  "dseg_hash": canonical_hash(dsmap), "generation_hash": canonical_hash(zone),
                  "generation_values": zone, "td_values": sorted(td, key=lambda r: r["component"]),
                  "td_hash": canonical_hash(sorted(td, key=lambda r: r["component"])),
                  "operations_hash": canonical_hash(ops)}
        result["state_hash"] = canonical_hash(result)
        return result

    def save(self, path):
        with optional_span(self, "VISUM_SAVE_VERSION", path=str(path)):
            return rt.save_version(self.visum, path)

    def restore(self, checkpoint, snapshot):
        if rt.sha256_file(checkpoint["path"]) != checkpoint["sha256"]:
            raise SupplyContractError("CHECKPOINT_BYTES_CHANGED")
        rt.load_version(self.visum, checkpoint["path"])
        expected_zone_nos = list(range(1, rt.EXPECTED_ZONES + 1))
        self.zones, self.zone_write_index_by_no = com.zone_identity(
            self.visum, expected_zone_nos, self.com_retry_policy)
        if self.zones != expected_zone_nos:
            raise SupplyContractError("ZONE_MATRIX_AXIS_ORDER_MISMATCH_AFTER_LOADVERSION")
        current = self.snapshot()
        if current != snapshot:
            raise SupplyContractError("ROLLBACK_STATE_NOT_IDENTICAL")
        return current

    def gap(self):
        spec = self.cfg["supply"].get("gap_readback", {})
        evidence = assignment_gap_evidence(self.visum, spec)
        self.last_gap_evidence = evidence
        gap = evidence["gap"]
        if gap < 0 or gap > number(spec.get("maximum_gap", 1e-6)):
            raise SupplyContractError("ASSIGNMENT_NOT_TIGHT: gap=%0.9g maximum=%0.9g source=%s" %
                (gap, number(spec.get("maximum_gap", 1e-6)), evidence["source"]))
        return gap

    def assign(self, folder, *, supply_only):
        self.last_gap_evidence = None
        try:
            with optional_span(self, "VISUM_PROCEDURES_EXECUTE",
                               purpose="SUPPLY_ONLY_ASSIGNMENT" if supply_only else "FULL_DOWNSTREAM_RECOMPUTE"):
                if supply_only:
                    with assignment_only_operations(self.visum, self.cfg):
                        rt.execute_procseq(self.visum, folder)
                        gap = self.gap()
                else:
                    rt.execute_procseq(self.visum, folder)
                    gap = self.gap()
        finally:
            # Persist the actual quality evidence even when the configured
            # threshold rejects it; do not quietly hide the diagnostic.
            if self.last_gap_evidence is not None:
                rt.write_json(Path(folder) / "ASSIGNMENT_QUALITY_SCOPE_EVIDENCE.json", self.last_gap_evidence)
        rt.write_json(Path(folder) / "ASSIGNMENT_QUALITY.json", {"gap": gap, "supply_only": supply_only, "passes": True})
        return gap

    def diagnostics(self, folder, label="CURRENT"):
        with optional_span(self, "LIVE_DIAGNOSTICS_12D_11D", label=label):
            d12, d11 = rt.run_diagnostics(self.visum, folder, label, self.cfg)
        observation_identity(d12["rows"], include_model=True)
        signals, _ = base.build_td_signals_from_11d(d11, self.cfg)
        return {"d12": d12, "d11": d11, "signals": signals}

    def supply_design(self, diag, folder, snapshot):
        links = self.read_links()
        collector = ActualRouteCollector(diag["d12"]["rows"], self.policy, snapshot["state_hash"],
                                         [k for k, r in links.items() if r["eligible"]])
        cfg = dict(self.cfg, path_export_dsegs=list(self.cfg["supply"]["passenger_dsegs"]),
                   mutable_dsegs=[], include_exog_ee_paths=True, require_all_path_export_dsegs=True)
        _, export = rt.export_actual_paths_and_build_incidence(self.visum, folder, cfg, diag["d12"]["rows"], [],
                                 route_batch_callback=collector.consume, build_incidence=False)
        design = propose_supply(collector, links, self.baseline_addval, self.policy)
        design["path_export_summary"] = export
        self.supply_path_proof = {"parent_hash": snapshot["state_hash"],
                                  "assignment_path_hash": design["authority"]["assignment_path_hash"]}
        rt.write_json(Path(folder) / "SUPPLY_PATH_DESIGN.json", design)
        return design

    def apply_supply(self, candidate, snapshot, folder):
        if candidate["parent_hash"] != snapshot["state_hash"] or self.snapshot() != snapshot:
            raise SupplyContractError("STALE_SUPPLY_PARENT")
        proof = self.supply_path_proof or {}
        if proof.get("parent_hash") != snapshot["state_hash"] or not proof.get("assignment_path_hash") or candidate.get("assignment_path_hash") != proof["assignment_path_hash"]:
            raise SupplyContractError("UNVERIFIED_OR_STALE_ACTUAL_PATH_PROOF")
        links = self.read_links()
        keys = [tuple(x["key"]) for x in candidate["changes"]]
        if len(set(keys)) != len(keys) or not keys:
            raise SupplyContractError("DUPLICATE_OR_EMPTY_SUPPLY_WRITE")
        # Complete validation BEFORE the first COM write.
        for change in candidate["changes"]:
            key = tuple(change["key"])
            if links[key]["addval1"] != number(change["expected_old"]):
                raise SupplyContractError("STALE_EXPECTED_OLD_ADDVAL1")
            check_addval_change(key, change["expected_old"], change["new"],
                                self.baseline_addval[key], links[key], self.policy)
        audit = []
        for change in candidate["changes"]:
            key = tuple(change["key"]); obj = links[key]["object"]
            attr = self.cfg["supply"].get("link_attributes", {}).get("addval1", "ADDVAL1")
            obj.SetAttValue(attr, change["new"])
            observed = number(obj.AttValue(attr), "ADDVAL1 readback")
            audit.append({**change, "readback": observed})
            if abs(observed-change["new"]) > 1e-10:
                raise SupplyContractError("ADDVAL1_READBACK_FAILED")
        rt.write_json(Path(folder) / "SUPPLY_WRITE_READBACK.json", audit)

    def generation_design(self, diag, folder):
        return base.path_guidance_design(self.visum, folder, self.cfg, diag["d12"], self.zones, self.actuatable_zones)

    def generation_preview(self, context, scale):
        return base.generation_candidate(
            self.visum, self.zones, context["projection"], self.cfg, scale,
            reference_values=self.generation_reference_values)

    def apply_generation(self, context, scale, folder):
        if self.cfg.get("require_solver_convergence_for_apply", True) and not context["result"].converged:
            raise SupplyContractError("GENERATION_SOLVER_NOT_CONVERGED")
        fams = context["projection"].family_summaries
        if self.cfg.get("require_projection_convergence_for_apply", True) and (not fams or not all(x.get("converged") for x in fams)):
            raise SupplyContractError("GENERATION_PROJECTION_NOT_CONVERGED")
        design = base.generation_candidate(
            self.visum, self.zones, context["projection"], self.cfg, scale,
            reference_values=self.generation_reference_values,
            zone_indices=self.zone_write_index_by_no, retry_policy=self.com_retry_policy)
        gate = base.generation_apply_gate(design, self.cfg)
        rt.write_json(Path(folder) / "GENERATION_DESIGN.json", design)
        rt.write_json(Path(folder) / "GENERATION_SIGNED_REFINEMENT_AUDIT.json", {
            "reference_hash": self.generation_reference_hash,
            "guidance_mode": self.cfg.get("guidance_mode"),
            "signed_generation_refinement": design.get("summary", {}).get("signed_generation_refinement"),
            "generation_coefficient_authority": design.get("summary", {}).get("generation_coefficient_authority"),
            "gate": gate,
        })
        if not gate["passes"]:
            raise SupplyContractError("GENERATION_GATE:" + ";".join(gate["reasons"]))
        rows = design["candidate_rows"]
        audit = rt.apply_add_candidate(
            self.visum, rows, self.zones,
            zone_indices=self.zone_write_index_by_no,
            retry_policy=self.com_retry_policy,
            readback_tolerance=self.zone_readback_tolerance)
        if not audit or any(x.get("status") != "OK" for x in audit):
            raise SupplyContractError("GENERATION_READBACK_FAILED")
        return rows

    def td_design(self, diag, block, scale, folder):
        design, signals, state = base.design_td_block(self.visum, diag["d11"], base.block_family(block), self.cfg, scale, folder)
        return design

    def apply_td(self, rows):
        audit = vp.apply_td_candidates(self.visum, rows)
        if not audit or any(x.get("status") != "OK" for x in audit):
            raise SupplyContractError("TD_READBACK_FAILED")

    def parameter_persistence(self, block, rows):
        if block == "GENERATION":
            result = rt.verify_add_candidate_persistence(
                self.visum, rows, self.zones,
                zone_indices=self.zone_write_index_by_no,
                retry_policy=self.com_retry_policy,
                readback_tolerance=self.zone_readback_tolerance)
        else:
            result = vp.verify_td_persistence(self.visum, rows)
        if not result or any(x.get("status") != "OK" for x in result):
            raise SupplyContractError("CANDIDATE_PARAMETERS_OVERWRITTEN")

    def block_gate(self, block, before, after, rows):
        if block in ("SUPPLY_ADDVAL1", "GENERATION"):
            return core.acceptance_decision(
                before["d12"]["rows"], after["d12"]["rows"],
                before["d11"]["summary"], after["d11"]["summary"], self.cfg,
                policy_scope=block)
        return base.td_acceptance_decision(before["d12"]["rows"], after["d12"]["rows"],
                 before["d11"]["summary"], after["d11"]["summary"], before["signals"], after["signals"],
                 [r["component"] for r in rows], self.cfg)

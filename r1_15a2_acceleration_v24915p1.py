# -*- coding: utf-8 -*-
"""Exact-safe runtime acceleration for the V24915 calibration lineage.

This module deliberately changes orchestration only.  It does not change any
candidate mathematics, IPF tolerance, assignment quality threshold, objective,
acceptance gate, matrix values, or supply policy.

Implemented accelerations:

* phase-specific Procedure Sequence slicing with fail-closed full-sequence
  fallback;
* delta-only ACTIVE flag writes and exact restoration/readback;
* read-only 498-profile passenger-flow signature used to prove rollback
  diagnostic equivalence before reusing an already computed baseline 12D/11D
  diagnostic payload.

The full legacy execution and full diagnostics remain the mandatory fallback
whenever the optimization cannot prove that its preconditions hold.
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Sequence, Tuple
import copy
import json
import math
import os

import r1_15a2_com_compat as com
from r1_15a2_supply import SupplyContractError, canonical_hash

SCHEMA = "R1_15A2_V24915_PERF1_EXACT_SAFE_ACCELERATION_V1"


def _atomic_json(path: Path, value: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=True, indent=2, allow_nan=False)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def _cfg(cfg: Mapping[str, Any]) -> Mapping[str, Any]:
    value = cfg.get("performance", {}).get("v24915_perf1", {}) or {}
    if not isinstance(value, Mapping):
        raise SupplyContractError("V24915P1_PERFORMANCE_CONFIG_NOT_MAPPING")
    return value


def enabled(cfg: Mapping[str, Any], feature: str) -> bool:
    section = _cfg(cfg).get(feature, {}) or {}
    return isinstance(section, Mapping) and section.get("enabled") is True


def _full_plan(inventory: Sequence[Mapping[str, Any]], block: str,
               reason: str, *, requested_mode: str) -> Dict[str, Any]:
    selected = [int(row["no"]) for row in inventory if int(row["active"])]
    return {
        "schema": SCHEMA,
        "block": str(block),
        "requested_mode": requested_mode,
        "mode": "FULL_SEQUENCE_FALLBACK",
        "optimized": False,
        "fallback_reason": str(reason),
        "selected_operation_positions": selected,
        "original_active_operation_positions": selected,
        "changed_operation_positions": [],
        "inventory": [{k: v for k, v in row.items() if k != "object"}
                      for row in inventory],
    }


def _approved_assignments(inventory: Sequence[Mapping[str, Any]],
                          cfg: Mapping[str, Any]) -> List[int]:
    approved = list(cfg.get("supply", {}).get("assignment_operations", []) or [])
    if not approved:
        raise SupplyContractError("V24915P1_ASSIGNMENT_OPERATION_AUTHORITY_EMPTY")
    by_position = {int(row["no"]): row for row in inventory}
    result: List[int] = []
    for rule in approved:
        position = int(rule["no"])
        expected_type = int(rule["operation_type"])
        row = by_position.get(position)
        if (row is None or int(row["type"]) != expected_type or
                expected_type != com.ASSIGNMENT_PRT or not int(row["active"])):
            raise SupplyContractError(
                "V24915P1_ASSIGNMENT_OPERATION_AUTHORITY_MISMATCH:%s" % position)
        if "15A2" in (str(row.get("comment", "")) + str(row.get("name", ""))).upper():
            raise SupplyContractError("V24915P1_RECURSIVE_MASTER_OPERATION:%s" % position)
        result.append(position)
    if len(result) != len(set(result)):
        raise SupplyContractError("V24915P1_DUPLICATE_ASSIGNMENT_OPERATION_AUTHORITY")
    return sorted(result)


def phase_recompute_plan(visum: Any, cfg: Mapping[str, Any], block: str) -> Dict[str, Any]:
    """Return an audited active-operation plan for one candidate block.

    The plan is optimized only when every skipped active operation is covered by
    an explicit safe rule.  Otherwise it returns the original full active set.
    """
    try:
        inventory = com.operation_rows(visum)
    except Exception as exc:
        raise SupplyContractError("V24915P1_OPERATION_INVENTORY_FAILED:%s" % exc) from exc

    original_active = {int(r["no"]) for r in inventory if int(r["active"])}
    p1 = _cfg(cfg)
    phase_cfg = p1.get("phase_specific_procseq", {}) or {}
    if phase_cfg.get("enabled") is not True:
        return _full_plan(inventory, block, "FEATURE_DISABLED", requested_mode="FULL")

    fallback = phase_cfg.get("fallback_to_full", True) is True
    safe_post = {int(v) for v in phase_cfg.get("safe_post_assignment_skip_positions", [])}
    safe_post_rules = list(phase_cfg.get("safe_post_assignment_operations", []) or [])
    by_position = {int(row["no"]): row for row in inventory}
    safe_post_rule_error: Exception | None = None
    try:
        for rule in safe_post_rules:
            position = int(rule["position"])
            row = by_position.get(position)
            if row is None:
                raise SupplyContractError("V24915P1_SAFE_POST_OPERATION_MISSING:%s" % position)
            expected_type = int(rule.get("operation_type", row["type"]))
            if int(row["type"]) != expected_type:
                raise SupplyContractError("V24915P1_SAFE_POST_OPERATION_TYPE_MISMATCH:%s" % position)
            tokens = [str(x).upper() for x in rule.get("text_contains_any", []) if str(x).strip()]
            text = (str(row.get("name", "")) + " " + str(row.get("comment", ""))).upper()
            if tokens and not any(token in text for token in tokens):
                raise SupplyContractError("V24915P1_SAFE_POST_OPERATION_TEXT_MISMATCH:%s" % position)
            safe_post.add(position)
    except Exception as exc:
        # A reviewed post-assignment operation is part of the optimization
        # authority.  If the live Procedure Sequence does not match it, the
        # exact-safe behavior is the same as for every other unproven
        # optimization precondition: run the original full sequence.
        safe_post_rule_error = exc
    safe_pre_td_types = {int(v) for v in phase_cfg.get(
        "safe_pre_td_skip_operation_types", [com.TG, com.GROUP])}
    preserve_groups = phase_cfg.get("preserve_active_groups", True) is True
    block_text = str(block).upper()
    requested_mode = ("SUPPLY_ASSIGNMENT_ONLY" if block_text == "SUPPLY_ADDVAL1" else
                      "GENERATION_PREFIX" if block_text == "GENERATION" else
                      "TD_TO_ASSIGNMENT" if block_text.startswith("TD_") else "FULL")
    try:
        if safe_post_rule_error is not None:
            raise safe_post_rule_error
        assignments = _approved_assignments(inventory, cfg)
        first_assignment = min(assignments)
        last_assignment = max(assignments)
        groups = {int(r["no"]) for r in inventory
                  if int(r["active"]) and int(r["type"]) == com.GROUP}

        if block_text == "SUPPLY_ADDVAL1":
            selected = set(assignments)
            if preserve_groups:
                selected |= groups
        elif block_text == "GENERATION":
            # All originally active operations up to and including the approved
            # assignment stay active.  Only explicitly reviewed post-assignment
            # display/export operations may be skipped.
            unapproved_post = [int(r["no"]) for r in inventory
                               if int(r["active"]) and int(r["no"]) > last_assignment
                               and int(r["type"]) != com.GROUP
                               and int(r["no"]) not in safe_post]
            if unapproved_post:
                raise SupplyContractError(
                    "V24915P1_UNAPPROVED_POST_ASSIGNMENT_OPERATION:" +
                    ",".join(map(str, unapproved_post)))
            selected = {int(r["no"]) for r in inventory
                        if int(r["active"]) and int(r["no"]) <= last_assignment}
            if preserve_groups:
                selected |= groups
        elif block_text.startswith("TD_"):
            td_positions = [int(r["no"]) for r in inventory
                            if int(r["active"]) and int(r["type"]) == com.TD
                            and int(r["no"]) <= last_assignment]
            if not td_positions:
                raise SupplyContractError("V24915P1_NO_ACTIVE_TD_OPERATION_BEFORE_ASSIGNMENT")
            first_td = min(td_positions)
            unsafe_pre = [int(r["no"]) for r in inventory
                          if int(r["active"]) and int(r["no"]) < first_td
                          and int(r["type"]) not in safe_pre_td_types]
            if unsafe_pre:
                raise SupplyContractError(
                    "V24915P1_UNAPPROVED_PRE_TD_OPERATION:" +
                    ",".join(map(str, unsafe_pre)))
            unapproved_post = [int(r["no"]) for r in inventory
                               if int(r["active"]) and int(r["no"]) > last_assignment
                               and int(r["type"]) != com.GROUP
                               and int(r["no"]) not in safe_post]
            if unapproved_post:
                raise SupplyContractError(
                    "V24915P1_UNAPPROVED_POST_ASSIGNMENT_OPERATION:" +
                    ",".join(map(str, unapproved_post)))
            selected = {int(r["no"]) for r in inventory
                        if int(r["active"]) and first_td <= int(r["no"]) <= last_assignment}
            if preserve_groups:
                selected |= groups
        else:
            return _full_plan(inventory, block, "BLOCK_NOT_OPTIMIZED", requested_mode="FULL")

        if not set(assignments) <= selected:
            raise SupplyContractError("V24915P1_PLAN_OMITS_APPROVED_ASSIGNMENT")
        if not selected <= {int(r["no"]) for r in inventory}:
            raise SupplyContractError("V24915P1_PLAN_REFERENCES_UNKNOWN_OPERATION")
        changed = sorted(int(r["no"]) for r in inventory
                         if int(r["active"]) != int(int(r["no"]) in selected))
        skipped = sorted(original_active - selected)
        return {
            "schema": SCHEMA,
            "block": str(block),
            "requested_mode": requested_mode,
            "mode": "PHASE_SPECIFIC",
            "optimized": True,
            "fallback_reason": None,
            "selected_operation_positions": sorted(selected),
            "original_active_operation_positions": sorted(original_active),
            "skipped_originally_active_positions": skipped,
            "changed_operation_positions": changed,
            "approved_assignment_positions": assignments,
            "preserved_group_positions": sorted(groups if preserve_groups else set()),
            "safe_post_assignment_skip_positions": sorted(safe_post),
            "inventory": [{k: v for k, v in row.items() if k != "object"}
                          for row in inventory],
        }
    except Exception as exc:
        if not fallback:
            if isinstance(exc, SupplyContractError):
                raise
            raise SupplyContractError("V24915P1_PHASE_PLAN_FAILED:%s" % exc) from exc
        return _full_plan(inventory, block, str(exc), requested_mode=requested_mode)


@contextmanager
def activate_operation_plan(visum: Any, plan: Mapping[str, Any]):
    """Apply only changed ACTIVE flags and restore them exactly on exit."""
    original = com.operation_rows(visum)
    selected = {int(v) for v in plan.get("selected_operation_positions", [])}
    original_state = [(int(r["no"]), int(r["type"]), int(r["active"])) for r in original]
    changed: List[Mapping[str, Any]] = []
    try:
        for row in original:
            position = int(row["no"])
            expected = int(position in selected)
            if int(row["active"]) == expected:
                continue
            # Register the row before the COM write.  A write may succeed and
            # its immediate readback may still fail; in that case the finally
            # block must know that this row needs restoration.
            changed.append(row)
            row["object"].SetAttValue("ACTIVE", expected)
            got = int(com.active_bool(row["object"].AttValue("ACTIVE")))
            if got != expected:
                raise SupplyContractError(
                    "V24915P1_OPERATION_FLAG_WRITE_MISMATCH:%s" % position)
        current = com.operation_rows(visum)
        current_active = {int(r["no"]) for r in current if int(r["active"])}
        if current_active != selected:
            raise SupplyContractError("V24915P1_OPERATION_SELECTION_READBACK_MISMATCH")
        yield dict(plan, actual_changed_operation_positions=[int(r["no"]) for r in changed])
    finally:
        errors: List[str] = []
        for row in reversed(changed):
            try:
                expected = int(row["active"])
                row["object"].SetAttValue("ACTIVE", expected)
                got = int(com.active_bool(row["object"].AttValue("ACTIVE")))
                if got != expected:
                    raise RuntimeError("ACTIVE_READBACK")
            except Exception as exc:
                errors.append("%s:%s" % (row.get("no"), exc))
        if errors:
            raise SupplyContractError(
                "V24915P1_OPERATION_FLAGS_RESTORE_FAILED:" + ";".join(errors))
        restored = com.operation_rows(visum)
        restored_state = [(int(r["no"]), int(r["type"]), int(r["active"])) for r in restored]
        if restored_state != original_state:
            raise SupplyContractError("V24915P1_OPERATION_SET_CHANGED_AFTER_RESTORE")


def _column(container: Any, attribute: str, retry_policy: Mapping[str, Any] | None) -> Dict[int, Any]:
    rows = com.get_multi_att_values(container, attribute, retry_policy)
    result: Dict[int, Any] = {}
    for raw_index, value in rows:
        index = com.exact_int(raw_index, "link collection index")
        if index in result:
            raise SupplyContractError(
                "V24915P1_DUPLICATE_LINK_COLLECTION_INDEX:%s" % attribute)
        result[index] = value
    if not result:
        raise SupplyContractError("V24915P1_EMPTY_LINK_COLUMN:%s" % attribute)
    return result


def _link_volume_table(visum: Any, dsegs: Sequence[str],
                       retry_policy: Mapping[str, Any] | None) -> Dict[Tuple[int, int, int], Dict[str, float]]:
    links = visum.Net.Links
    attrs = {
        "link_no": "NO",
        "from_node_no": "FROMNODENO",
        "to_node_no": "TONODENO",
    }
    attrs.update({str(code): "VOLVEH_DSEG(%s,AP)" % code for code in dsegs})
    columns = {name: _column(links, attr, retry_policy) for name, attr in attrs.items()}
    sets = {tuple(sorted(col)) for col in columns.values()}
    if len(sets) != 1:
        raise SupplyContractError("V24915P1_LINK_COLUMN_INDEX_SET_MISMATCH")
    indices = next(iter(sets))
    table: Dict[Tuple[int, int, int], Dict[str, float]] = {}
    for index in indices:
        key = (
            com.exact_int(columns["link_no"][index], "Link.NO"),
            com.exact_int(columns["from_node_no"][index], "Link.FROMNODENO"),
            com.exact_int(columns["to_node_no"][index], "Link.TONODENO"),
        )
        if key in table:
            raise SupplyContractError("V24915P1_DUPLICATE_DIRECTED_LINK_KEY")
        values: Dict[str, float] = {}
        for code in dsegs:
            value = com.finite_float(columns[str(code)][index], "VOLVEH_DSEG(%s,AP)" % code)
            if value < 0:
                raise SupplyContractError("V24915P1_NEGATIVE_PASSENGER_LINK_VOLUME")
            values[str(code)] = value
        table[key] = values
    return table


def _profile_identity(row: Mapping[str, Any]) -> Tuple[Any, ...]:
    return (
        str(row.get("profile_id", row.get("countlocation_no", row.get("countlocation_code", "")))),
        int(row.get("link_no")), int(row.get("from_node_no")), int(row.get("to_node_no")),
        str(row.get("observation_direction", row.get("direction", "DIRECTED"))).upper(),
    )


def count_profile_signature(visum: Any, cfg: Mapping[str, Any],
                            baseline_rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Read a compact exact passenger-flow signature for the authoritative 12D roster.

    This is a read-only proof.  It never changes CountLocations, links, matrices,
    or procedure settings.
    """
    feature = _cfg(cfg).get("rollback_diagnostic_reuse", {}) or {}
    if feature.get("enabled") is not True:
        return {"schema": SCHEMA, "passes": False, "reason": "FEATURE_DISABLED"}
    expected = int(feature.get("expected_profiles", cfg.get("expected_12d_rows", 498)))
    if len(baseline_rows) != expected:
        return {
            "schema": SCHEMA, "passes": False,
            "reason": "BASELINE_PROFILE_COUNT_MISMATCH",
            "expected_profiles": expected, "actual_profiles": len(baseline_rows),
        }
    dsegs = [str(x) for x in cfg.get("supply", {}).get("passenger_dsegs", [])]
    if not dsegs or len(dsegs) != len(set(dsegs)):
        raise SupplyContractError("V24915P1_PASSENGER_DSEG_AUTHORITY_INVALID")
    table = _link_volume_table(visum, dsegs, cfg.get("com_resilience", {}) or {})
    atol = float(feature.get("absolute_tolerance", 1.0e-7))
    rtol = float(feature.get("relative_tolerance", 1.0e-10))
    max_mismatches = int(feature.get("max_reported_mismatches", 30))
    if min(atol, rtol) < 0 or not all(math.isfinite(v) for v in (atol, rtol)):
        raise SupplyContractError("V24915P1_ROLLBACK_SIGNATURE_TOLERANCE_INVALID")

    rows_out: List[Dict[str, Any]] = []
    mismatches: List[Dict[str, Any]] = []
    mismatch_count_total = 0
    max_abs_error = 0.0
    max_rel_error = 0.0
    seen = set()
    for source in baseline_rows:
        ident = _profile_identity(source)
        if ident in seen:
            raise SupplyContractError("V24915P1_DUPLICATE_BASELINE_PROFILE_IDENTITY")
        seen.add(ident)
        key = (int(source["link_no"]), int(source["from_node_no"]), int(source["to_node_no"]))
        if key not in table:
            raise SupplyContractError("V24915P1_PROFILE_LINK_MISSING:%s" % (key,))
        direction = str(source.get("observation_direction", source.get("direction", "DIRECTED"))).upper()
        keys = [key]
        if direction == "BOTH":
            reverse = (
                int(source.get("reverse_link_no", source["link_no"])),
                int(source.get("reverse_from_node_no", source["to_node_no"])),
                int(source.get("reverse_to_node_no", source["from_node_no"])),
            )
            if reverse == key:
                raise SupplyContractError("V24915P1_BOTH_PROFILE_REVERSE_EQUALS_FORWARD")
            if reverse not in table:
                raise SupplyContractError("V24915P1_BOTH_PROFILE_REVERSE_LINK_MISSING:%s" % (reverse,))
            keys.append(reverse)
        elif direction not in ("DIRECTED", "ONE_WAY"):
            raise SupplyContractError("V24915P1_UNSUPPORTED_PROFILE_DIRECTION:%s" % direction)

        model_values: Dict[str, float] = {}
        total = 0.0
        row_mismatch = False
        for code in dsegs:
            actual = sum(table[k][code] for k in keys)
            model_values[code] = actual
            total += actual
            field = "model_%s" % code
            if field not in source:
                raise SupplyContractError("V24915P1_BASELINE_PROFILE_FIELD_MISSING:%s" % field)
            expected_value = com.finite_float(source[field], field)
            abs_error = abs(actual - expected_value)
            rel_error = abs_error / max(1.0, abs(actual), abs(expected_value))
            tolerance = max(atol, rtol * max(1.0, abs(actual), abs(expected_value)))
            max_abs_error = max(max_abs_error, abs_error)
            max_rel_error = max(max_rel_error, rel_error)
            if abs_error > tolerance:
                row_mismatch = True
                mismatch_count_total += 1
                if len(mismatches) < max_mismatches:
                    mismatches.append({
                        "profile_identity": list(ident), "field": field,
                        "expected": expected_value, "actual": actual,
                        "absolute_error": abs_error, "relative_error": rel_error,
                        "tolerance": tolerance,
                    })
        if "model" in source:
            expected_total = com.finite_float(source["model"], "model")
            abs_error = abs(total - expected_total)
            rel_error = abs_error / max(1.0, abs(total), abs(expected_total))
            tolerance = max(atol, rtol * max(1.0, abs(total), abs(expected_total)))
            max_abs_error = max(max_abs_error, abs_error)
            max_rel_error = max(max_rel_error, rel_error)
            if abs_error > tolerance:
                row_mismatch = True
                mismatch_count_total += 1
                if len(mismatches) < max_mismatches:
                    mismatches.append({
                        "profile_identity": list(ident), "field": "model",
                        "expected": expected_total, "actual": total,
                        "absolute_error": abs_error, "relative_error": rel_error,
                        "tolerance": tolerance,
                    })
        rows_out.append({
            "profile_identity": list(ident),
            "directed_link_keys": [list(k) for k in keys],
            "model_by_dseg": model_values,
            "model_total": total,
            "passes": not row_mismatch,
        })

    rows_out.sort(key=lambda row: tuple(str(x) for x in row["profile_identity"]))
    signature_payload = [{
        "profile_identity": row["profile_identity"],
        "model_by_dseg": row["model_by_dseg"],
        "model_total": row["model_total"],
    } for row in rows_out]
    return {
        "schema": SCHEMA,
        "passes": mismatch_count_total == 0,
        "reason": None if mismatch_count_total == 0 else "PROFILE_VOLUME_SIGNATURE_MISMATCH",
        "profiles": len(rows_out),
        "passenger_dsegs": dsegs,
        "directed_links_read": len(table),
        "signature_hash": canonical_hash(signature_payload),
        "absolute_tolerance": atol,
        "relative_tolerance": rtol,
        "max_abs_error": max_abs_error,
        "max_rel_error": max_rel_error,
        "mismatch_count_total": mismatch_count_total,
        "mismatch_count_reported": len(mismatches),
        "mismatches": mismatches,
    }


def rollback_diagnostic_equivalence(adapter: Any, baseline_diag: Mapping[str, Any],
                                    before_snapshot: Mapping[str, Any],
                                    folder: Path) -> Dict[str, Any]:
    """Prove that full rollback diagnostics can be reused, or return FAIL.

    Preconditions are intentionally redundant:
      1. exact semantic snapshot equals the accepted parent before the read;
      2. all authoritative 12D passenger model values match by directed link;
      3. exact semantic snapshot still equals the parent after the read.

    The unchanged demand matrix hashes and unchanged generation/TD parameters in
    the semantic snapshot are the authority that the 11D payload is unchanged.
    """
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    feature = _cfg(adapter.cfg).get("rollback_diagnostic_reuse", {}) or {}
    if feature.get("enabled") is not True:
        result = {"schema": SCHEMA, "passes": False, "reason": "FEATURE_DISABLED"}
        _atomic_json(folder / "ROLLBACK_DIAGNOSTIC_REUSE_PROOF.json", result)
        return result
    if adapter.snapshot() != before_snapshot:
        result = {"schema": SCHEMA, "passes": False,
                  "reason": "PRE_SIGNATURE_SNAPSHOT_MISMATCH"}
        _atomic_json(folder / "ROLLBACK_DIAGNOSTIC_REUSE_PROOF.json", result)
        return result
    rows = list((baseline_diag.get("d12", {}) or {}).get("rows", []) or [])
    try:
        signature = count_profile_signature(adapter.visum, adapter.cfg, rows)
    except Exception as exc:
        signature = {"schema": SCHEMA, "passes": False,
                     "reason": "SIGNATURE_READ_FAILED", "error": str(exc)}
    post_equal = adapter.snapshot() == before_snapshot
    passes = bool(signature.get("passes") and post_equal)
    result = {
        "schema": SCHEMA,
        "passes": passes,
        "reason": None if passes else (
            "POST_SIGNATURE_SNAPSHOT_MISMATCH" if not post_equal
            else signature.get("reason", "SIGNATURE_NOT_PROVED")),
        "snapshot_equal_before_signature": True,
        "snapshot_equal_after_signature": bool(post_equal),
        "matrix_hash_equal_authority": True,
        "generation_hash_equal_authority": True,
        "td_hash_equal_authority": True,
        "d11_reuse_basis": "EXACT_SEMANTIC_SNAPSHOT_INCLUDING_ALL_DEMAND_MATRIX_HASHES",
        "d12_reuse_basis": "498_PROFILE_12_DSEG_BULK_LINK_VOLUME_SIGNATURE",
        "full_diagnostics_fallback_required": not passes,
        "signature": signature,
    }
    _atomic_json(folder / "ROLLBACK_DIAGNOSTIC_REUSE_PROOF.json", result)
    return result


__all__ = [
    "SCHEMA", "enabled", "phase_recompute_plan", "activate_operation_plan",
    "count_profile_signature", "rollback_diagnostic_equivalence",
]

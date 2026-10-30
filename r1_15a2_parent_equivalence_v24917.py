"""GENFIX2: fail-closed numerical equivalence of an accepted parent.

Snapshots keep their original public schema.  Matrix tolerances need byte-bound
parent arrays captured BEFORE mutation, not just aggregate profile agreement.
Proofs are temporary .npy files (one matrix in RAM); they never write to Visum.
"""
from __future__ import annotations

import contextlib
import copy
import hashlib
import json
import math
import numbers
import shutil
import tempfile
from pathlib import Path
from typing import Any, Mapping

import numpy as np

import r1_15a2_long_composite_diagnostic_v24917 as long_composite

from r1_15a2_com_compat import com_call_with_retry, zone_identity
from r1_15a2_supply import SupplyContractError, canonical_hash

RELEASE = "R1_15A2_V24917_PARENT_EQUIVALENCE_TDROLLBACKFIX1_20261027"
MATRIX_ATOL = 1.0e-7
MATRIX_RTOL = 1.0e-10
MARGIN_ATOL = 1.0e-6
SIGNAL_ATOL = 1.0e-9
SIGNAL_RTOL = 1.0e-8
# Only provenance/transport metadata is ignored; statuses and metrics are not.
_METADATA = frozenset(("timestamp", "created_at", "generated_at", "elapsed_s", "elapsed_seconds",
                       "runtime_seconds", "summary_path", "output_dir", "output_folder", "folder",
                       "evidence_zip", "source_file", "source_path", "path", "script_path", "authority_dir"))


def _public_write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str, allow_nan=False), encoding="utf-8")


def _matrix_index(state):
    out = {}
    for row in state.get("matrices", []) or []:
        no = int(row["matrix_no"])
        if no in out:
            raise SupplyContractError("GENFIX2_DUPLICATE_MATRIX_ID:%s" % no)
        out[no] = row
    return out


def _array_hash(array):
    return hashlib.sha256(np.ascontiguousarray(array, dtype="<f8").tobytes(order="C")).hexdigest()


def _array(adapter, no):
    policy = getattr(adapter, "com_retry_policy", None)
    return np.asarray(com_call_with_retry(
        lambda: adapter.visum.Net.Matrices.ItemByKey(int(no)).GetValues(),
        label="GENFIX2_MATRIX:%s" % no, retry_policy=policy), dtype="<f8")


def _valid_array(a):
    return a.ndim == 2 and bool(np.isfinite(a).all()) and not bool((a < 0).any())


def _axes(adapter):
    order, _ = zone_identity(adapter.visum, getattr(adapter, "zones", None),
                             getattr(adapter, "com_retry_policy", None))
    expected = getattr(adapter, "zones", None)
    if expected is not None and list(order) != list(expected):
        raise SupplyContractError("GENFIX2_MATRIX_AXIS_ORDER_MISMATCH")
    return order


def capture(adapter, state):
    """Bind a disk proof to the entire parent snapshot, including IZ penalties."""
    rows = _matrix_index(state)
    proof = {"snapshot": copy.deepcopy(state), "identity": canonical_hash(state),
             "matrices": {}, "directory": None, "status": "EXACT_ONLY_NO_MATRIX_READER",
             "path_epoch_accepts_before": getattr(adapter, "path_epoch_accepts", None)}
    if not rows:
        proof["status"] = "EXACT_ONLY_NO_MATRICES"
        return proof
    if not hasattr(adapter, "visum") or not hasattr(getattr(adapter.visum, "Net", None), "Matrices"):
        return proof  # exact hash equality remains possible; drift is never waived
    directory = Path(tempfile.mkdtemp(prefix="R1EQ_"))
    proof["directory"] = str(directory)
    try:
        proof["axes"] = _axes(adapter)
        for no, row in sorted(rows.items()):
            a = _array(adapter, no)
            if (not _valid_array(a) or list(a.shape) != [row.get("rows"), row.get("cols")]
                    or list(a.shape) != [len(proof["axes"]), len(proof["axes"])]):
                raise SupplyContractError("GENFIX2_PARENT_MATRIX_INVALID:%s" % no)
            if _array_hash(a) != row.get("sha256_float64_le"):
                raise SupplyContractError("GENFIX2_PARENT_MATRIX_SNAPSHOT_MISMATCH:%s" % no)
            p = directory / ("M%s.npy" % no)
            np.save(p, a, allow_pickle=False)
            proof["matrices"][no] = {"path": str(p), "sha256": _array_hash(a), "shape": list(a.shape)}
        proof["status"] = "CAPTURED_BEFORE_MUTATION"
        _public_write(directory / "PARENT_PROOF.json", proof)
        return proof
    except BaseException:
        shutil.rmtree(directory, ignore_errors=True)
        raise


@contextlib.contextmanager
def parent_scope(adapter, state, folder):
    """Nestable transaction boundary. Retain failed-run proof, remove successful temporary data."""
    old = getattr(adapter, "_genfix2_parent_proof", None)
    if old and old.get("identity") == canonical_hash(state):
        yield old
        return
    proof = capture(adapter, state)
    adapter._genfix2_parent_proof = proof
    failed = False
    try:
        yield proof
    except BaseException:
        failed = True
        try:
            _public_write(Path(folder) / "GENFIX2_PARENT_PROOF_RETAINED.json", proof)
        except Exception:
            pass
        raise
    finally:
        adapter._genfix2_parent_proof = old
        if not failed and proof.get("directory"):
            shutil.rmtree(proof["directory"], ignore_errors=True)


def compare_matrices(adapter, before, after):
    rec = {"passes": False, "matrices": [], "atol": MATRIX_ATOL, "rtol": MATRIX_RTOL,
           "margin_atol": MARGIN_ATOL}
    try:
        b, a = _matrix_index(before), _matrix_index(after)
        if set(a) != set(b):
            rec["reason"] = "MATRIX_IDENTITY_MISMATCH"
            return rec
        for no in b:
            if any(b[no].get(k) != a[no].get(k) for k in ("rows", "cols")):
                rec["reason"] = "MATRIX_SHAPE_MISMATCH:%s" % no
                return rec
        proof = getattr(adapter, "_genfix2_parent_proof", None)
        if proof and proof.get("axes") is not None and _axes(adapter) != proof["axes"]:
            rec["reason"] = "MATRIX_AXIS_ORDER_CHANGED"
            return rec
        changed = [no for no in b if a[no] != b[no]]
        if not changed and before.get("matrix_hash") == after.get("matrix_hash"):
            rec.update(passes=True, mode="EXACT_MATRIX_FINGERPRINTS")
            return rec
        proof = getattr(adapter, "_genfix2_parent_proof", None)
        if not proof or proof.get("identity") != canonical_hash(before) or proof.get("status") != "CAPTURED_BEFORE_MUTATION":
            rec["reason"] = "NO_BYTE_BOUND_PRE_MUTATION_MATRIX_PROOF"
            return rec
        if _axes(adapter) != proof.get("axes"):
            rec["reason"] = "MATRIX_AXIS_ORDER_CHANGED"
            return rec
        # An aggregate hash change not explained by its rows is inconsistent too.
        if not changed:
            rec["reason"] = "INCONSISTENT_MATRIX_AGGREGATE_HASH"
            return rec
        for no in changed:
            item = proof["matrices"].get(no)
            if not item:
                raise SupplyContractError("GENFIX2_PARENT_MATRIX_PROOF_MISSING:%s" % no)
            x = np.load(item["path"], mmap_mode="r", allow_pickle=False)
            y = _array(adapter, no)
            if not _valid_array(x) or not _valid_array(y) or x.shape != y.shape:
                raise SupplyContractError("GENFIX2_MATRIX_INVALID:%s" % no)
            if _array_hash(x) != b[no].get("sha256_float64_le") or _array_hash(y) != a[no].get("sha256_float64_le"):
                raise SupplyContractError("GENFIX2_MATRIX_PROOF_HASH_MISMATCH:%s" % no)
            diff = np.abs(y - x)
            cells_ok = bool(np.all(diff <= MATRIX_ATOL + MATRIX_RTOL * np.abs(x)))
            l1 = float(diff.sum())
            l1_ok = l1 <= MATRIX_ATOL * x.size + MATRIX_RTOL * float(np.abs(x).sum())
            margins_ok = True
            for axis in (0, 1):
                xb, ya = x.sum(axis=axis), y.sum(axis=axis)
                margins_ok = margins_ok and bool(np.all(np.abs(ya - xb) <= MARGIN_ATOL + MATRIX_RTOL * np.abs(xb)))
            total_ok = abs(float(y.sum()) - float(x.sum())) <= MARGIN_ATOL + MATRIX_RTOL * abs(float(x.sum()))
            ok = cells_ok and l1_ok and margins_ok and total_ok
            rec["matrices"].append({"matrix_no": no, "passes": ok, "max_abs": float(diff.max(initial=0)),
                                    "l1": l1, "sum_before": float(x.sum()), "sum_after": float(y.sum())})
            del x, y, diff
            if not ok:
                rec["reason"] = "MATERIAL_MATRIX_DRIFT:%s" % no
                return rec
        rec.update(passes=True, mode="BYTE_BOUND_NUMERIC_MATRIX_PROOF")
    except Exception as exc:
        rec["reason"] = "MATRIX_PROOF_ERROR:%s:%s" % (type(exc).__name__, str(exc)[:1000])
    return rec


def semantic_differences(before, after, path="", result=None):
    """Compare every diagnostic signal; only explicitly named file/timing metadata is ignored."""
    if result is None:
        result = []
    if len(result) >= 30:
        return result
    if isinstance(before, Mapping) and isinstance(after, Mapping):
        kb, ka = set(before) - _METADATA, set(after) - _METADATA
        if kb != ka:
            result.append(path + ":KEYS")
        for k in sorted(kb & ka, key=str):
            if k == "outputs" and isinstance(before[k], Mapping) and isinstance(after[k], Mapping):
                # 11D outputs maps artifact names to workspace-dependent paths.
                # Validate its schema and inventory, not temporary path spelling.
                if set(before[k]) != set(after[k]) or not all(
                        isinstance(v, str) for v in list(before[k].values()) + list(after[k].values())):
                    result.append(path + ".outputs:INVENTORY_OR_TYPE")
                continue
            semantic_differences(before[k], after[k], path + "." + str(k), result)
    elif isinstance(before, (list, tuple)) and isinstance(after, (list, tuple)):
        if len(before) != len(after):
            result.append(path + ":LENGTH")
        else:
            for i, (b, a) in enumerate(zip(before, after)):
                semantic_differences(b, a, "%s[%d]" % (path, i), result)
    elif isinstance(before, (bool, np.bool_)) or isinstance(after, (bool, np.bool_)):
        if (not isinstance(before, (bool, np.bool_))
                or not isinstance(after, (bool, np.bool_)) or bool(before) != bool(after)):
            result.append(path + ":BOOLEAN")
    elif isinstance(before, numbers.Real) and isinstance(after, numbers.Real):
        b, a = float(before), float(after)
        if not math.isfinite(a) or not math.isfinite(b) or abs(a - b) > SIGNAL_ATOL + SIGNAL_RTOL * abs(b):
            result.append(path + ":NUMERIC")
    elif before != after:
        result.append(path + ":VALUE")
    return result


def _diagnostic_signals(signals):
    """Normalize ONLY the producer's documented inactive atomic LONG sentinel.

    build_td_signals uses +inf objective for the five atomic LONG components
    when only LONG_COMPOSITE has a survey authority. That sentinel is not a
    failed numerical measurement. NaN, -inf, active objectives and all other
    nonfinite quantities remain invalid. All authority/status fields are kept.
    """
    out = copy.deepcopy(signals)
    from r1_15a2_multiblock import COMPONENT_REGISTRY
    for component, signal in out.items():
        if not isinstance(signal, Mapping):
            continue
        value = signal.get("objective")
        if (COMPONENT_REGISTRY.get(component, {}).get("family") == "LONG"
                and signal.get("component") == component
                and signal.get("family") == "LONG"
                and signal.get("calibratable") is False
                and signal.get("authority_status") == "NO_COMPONENT_LONG_AUTHORITY"
                and signal.get("policy_reason") == "AGGREGATE_CL_TARGET_IS_GUARD_ONLY"
                and isinstance(value, numbers.Real) and not isinstance(value, bool)
                and math.isinf(float(value)) and float(value) > 0):
            signal["objective"] = {"sentinel": "NOT_APPLICABLE_ATOMIC_LONG_WITHOUT_AUTHORITY"}
    return out


def _sha256_text(value):
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _dynamic_summary(diag, errors, side):
    """Validate each dynamic epoch, then compare its content, not execution IDs.

    Only documented producer locations are normalized. Content hashes,
    matrix identity/shape/units, zone order, statuses and metrics stay exact or
    subject to the existing metric roundoff check. Unknown metadata is NOT
    removed globally. This does not reuse an old epoch or skip its freshness
    check: verify_parent also binds the returned diagnostics to the live manager.
    """
    summary = copy.deepcopy((diag.get("d11") or {}).get("summary", {}))
    if not isinstance(summary, Mapping):
        errors.append(side + ":INVALID_11D_SUMMARY")
        return summary
    authority = summary.get("dynamic_distance_authority")
    classification = summary.get("dist_classification_matrix") or {}
    rows = summary.get("component_dist_summary_rows") or []
    dynamic = (authority is not None or "dynamic_skim_epoch" in diag
               or classification.get("code") == "VISUM_DYNAMIC_ASSIGNMENT_DIS_KM"
               or any(isinstance(r, Mapping) and "dynamic_skim_epoch" in r for r in rows))
    if not dynamic:
        return summary
    from r1_15a2_dynamic_skim_v24916p2c import SCHEMA, REQUIRED_NATIVE_DSEGS, _hash
    def require(ok, message):
        if not ok:
            raise ValueError(message)
    def same_reference(value, expected):
        # These are structural references, not tolerant numerical metrics.
        # Python equality alone treats True as epoch 1. Bind their JSON types
        # using the existing epoch hash before execution IDs are normalized.
        return value == expected and _hash(value) == _hash(expected)
    try:
        require(isinstance(authority, Mapping), "MISSING_DYNAMIC_AUTHORITY")
        require(authority.get("schema") == SCHEMA, "UNKNOWN_DYNAMIC_AUTHORITY_SCHEMA")
        require(authority.get("role") == "ACTIVE_TD_CALIBRATION_DISTANCE_AUTHORITY"
                and authority.get("source") == "VISUM_FRESH_ASSIGNMENT_PATHS_PRT_DIS",
                "DYNAMIC_AUTHORITY_ROLE_OR_SOURCE")
        for key in ("epoch", "assignment_epoch"):
            require(isinstance(authority.get(key), int) and not isinstance(authority[key], bool)
                    and authority[key] > 0, "INVALID_" + key)
        require(isinstance(authority.get("assignment_token"), str) and bool(authority["assignment_token"]),
                "INVALID_ASSIGNMENT_TOKEN")
        require(_sha256_text(authority.get("zone_order_sha256")), "INVALID_ZONE_HASH")
        positions = authority.get("operation_positions")
        require(isinstance(positions, (list, tuple)) and len(positions) == len(REQUIRED_NATIVE_DSEGS)
                and all(isinstance(n, int) and not isinstance(n, bool) and n > 0 for n in positions)
                and len(set(positions)) == len(positions), "INVALID_SKIM_OPERATIONS")
        meta = authority.get("matrix_meta_by_dseg")
        require(isinstance(meta, Mapping) and set(meta) == set(REQUIRED_NATIVE_DSEGS), "DSEG_INVENTORY")
        matrix_nos, shapes = [], []
        for dseg in REQUIRED_NATIVE_DSEGS:
            m = meta[dseg]
            require(isinstance(m, Mapping), "INVALID_MATRIX_METADATA:" + dseg)
            require(m.get("canonical_dseg") == dseg and m.get("unit") == "km"
                    and str(m.get("matrix_code", "")).upper() == "DIS", "MATRIX_SEMANTICS:" + dseg)
            require(_sha256_text(m.get("values_sha256")), "INVALID_MATRIX_HASH:" + dseg)
            no = m.get("matrix_no")
            require(isinstance(no, int) and not isinstance(no, bool) and no > 0, "INVALID_MATRIX_ID:" + dseg)
            shape = m.get("shape")
            require(isinstance(shape, (list, tuple)) and len(shape) == 2
                    and all(isinstance(n, int) and not isinstance(n, bool) and n > 0 for n in shape)
                    and shape[0] == shape[1], "INVALID_MATRIX_SHAPE:" + dseg)
            matrix_nos.append(no)
            shapes.append(tuple(shape))
        require(len(set(matrix_nos)) == len(matrix_nos) and len(set(shapes)) == 1,
                "DUPLICATE_MATRIX_OR_MISMATCHED_AXES")
        family = authority.get("family_hashes")
        require(isinstance(family, Mapping) and set(family) == {"WORK", "SERVICE", "LONG", "FOREIGN"}
                and all(_sha256_text(v) for v in family.values()), "INVALID_FAMILY_HASHES")
        payload = {key: authority[key] for key in ("schema", "epoch", "assignment_epoch",
                   "assignment_token", "zone_order_sha256", "operation_positions", "family_hashes")}
        payload["matrix_hashes"] = {k: meta[k]["values_sha256"] for k in REQUIRED_NATIVE_DSEGS}
        require(_hash(payload) == authority.get("epoch_hash"), "EPOCH_HASH_SELF_INCONSISTENT")
        require(same_reference(diag.get("dynamic_skim_epoch"), authority), "TOP_LEVEL_EPOCH_MISMATCH")
        require(classification.get("code") == "VISUM_DYNAMIC_ASSIGNMENT_DIS_KM"
                and classification.get("classification") == "DYNAMIC_ASSIGNMENT_PATH_VOLUME_WEIGHTED_DIS",
                "CLASSIFICATION_AUTHORITY_MISMATCH")
        for key, auth_key in (("assignment_epoch", "assignment_epoch"), ("skim_epoch", "epoch"),
                              ("skim_epoch_hash", "epoch_hash"), ("zone_order_sha256", "zone_order_sha256"),
                              ("family_hashes", "family_hashes")):
            require(same_reference(classification.get(key), authority[auth_key]), "CLASSIFICATION_REFERENCE:" + key)
        for row in rows:
            if row.get("distance_authority") == "DYNAMIC_ASSIGNMENT_DIS_KM" or "dynamic_skim_epoch" in row:
                require(row.get("distance_authority") == "DYNAMIC_ASSIGNMENT_DIS_KM"
                        and same_reference(row.get("dynamic_skim_epoch"), authority["epoch"])
                        and row.get("dynamic_skim_epoch_hash") == authority["epoch_hash"],
                        "COMPONENT_EPOCH_REFERENCE:" + str(row.get("component")))
        gate = (diag.get("d11") or {}).get("idp_gate")
        if gate is not None:
            require(gate.get("passes") is True, "IDP_GATE_FAILED")
            for key, auth_key in (("dynamic_assignment_epoch", "assignment_epoch"),
                                  ("dynamic_skim_epoch", "epoch"), ("dynamic_skim_epoch_hash", "epoch_hash")):
                require(same_reference(gate.get(key), authority[auth_key]), "IDP_GATE_REFERENCE:" + key)
        composite = summary.get(long_composite.KEY)
        if composite is not None:
            if composite.get('status') == 'VERIFIED':
                long_composite.validate(composite, authority, reference_sha=diag.get('dynamic_11d_reference_sha256'))
            else:
                require(composite.get('schema') == long_composite.SCHEMA and composite.get('status') == 'UNVERIFIED'
                        and isinstance(composite.get('reason'), str) and bool(composite['reason']),
                        'LONG_COMPOSITE_DIAGNOSTIC_INVALID')
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        errors.append(side + ":DYNAMIC_AUTHORITY_INVALID:" + str(exc))
        return summary
    # Execution identity is intentionally different after a new assignment.
    # No other fields are discarded, including every matrix/family content hash.
    for key in ("epoch", "assignment_epoch", "assignment_token", "epoch_hash"):
        summary["dynamic_distance_authority"].pop(key)
    for key in ("assignment_epoch", "skim_epoch", "skim_epoch_hash"):
        summary["dist_classification_matrix"].pop(key)
    for row in summary.get("component_dist_summary_rows", []):
        if row.get("distance_authority") == "DYNAMIC_ASSIGNMENT_DIS_KM":
            row.pop("dynamic_skim_epoch", None)
            row.pop("dynamic_skim_epoch_hash", None)
    composite = summary.get(long_composite.KEY)
    if composite is not None and composite.get('status') == 'VERIFIED':
        for key in long_composite.EXECUTION_KEYS:
            composite.pop(key)
    return summary


def compare_diagnostics(before, after):
    import r1_15a2_td_rollback_tolerant_v24917 as tr
    b = (before.get("d12") or {}).get("rows", [])
    a = (after.get("d12") or {}).get("rows", [])
    drift = tr.profile_drift(b, a)
    gb, ga = tr._weighted_geh(b), tr._weighted_geh(a)
    geh_ok = gb is not None and ga is not None and math.isfinite(gb) and math.isfinite(ga) and abs(ga - gb) <= tr.GEH_TOL
    errors = []
    for domain in ("d11", "signals"):
        if (domain in before) != (domain in after):
            errors.append(domain + ":MISSING")
            continue
        if domain == "d11":
            x, y = _dynamic_summary(before, errors, "before"), _dynamic_summary(after, errors, "after")
        else:
            x, y = _diagnostic_signals(before.get(domain, {})), _diagnostic_signals(after.get(domain, {}))
        semantic_differences(x, y, domain, errors)
    return {"passes": bool(not drift["violations"] and not drift["missing"] and geh_ok and not errors),
            "profile_drift": drift, "weighted_geh_before": gb, "weighted_geh_after": ga,
            "geh_tol": tr.GEH_TOL, "component_differences": errors,
            "signal_atol": SIGNAL_ATOL, "signal_rtol": SIGNAL_RTOL,
            "comparison_contract": "TDROLLBACKFIX1_CONTENT_NOT_EXECUTION_IDENTITY",
            "dynamic_skim_hash_policy": "MATRIX_AND_FAMILY_CONTENT_HASHES_EXACT; EPOCH_REFERENCE_SELF_CHECKED",
            "inactive_long_objective_policy": "ONLY_DOCUMENTED_POSITIVE_INFINITY_SENTINEL"}


def verify_parent(adapter, before, after, baseline_diag, diag, allow_td=False, ctrl=None, cfg=None, folder=None):
    import r1_15a2_td_rollback_tolerant_v24917 as tr
    if allow_td:
        params = tr.parameter_differences(before, after)
        try:
            ctrl._td_expected_freeze(before, after, [], cfg or {},
                                     Path(folder) / "GENFIX2_TD_FREEZE.json")
        except Exception as exc:
            params.append("TD_FREEZE:" + str(exc))
    else:
        params = sorted(k for k in set(before) | set(after) if k not in ("state_hash", "matrices", "matrix_hash")
                        and before.get(k) != after.get(k))
    # An unexplained hash change is not a numerical reconstruction.
    if before.get("state_hash") != after.get("state_hash") and all(
            before.get(k) == after.get(k) for k in (set(before) | set(after)) - {"state_hash"}):
        params.append("UNEXPLAINED_STATE_HASH_CHANGE")
    matrices = compare_matrices(adapter, before, after)
    diagnostic = compare_diagnostics(baseline_diag, diag)
    # The new diagnostics must refer to the currently valid assignment epoch.
    # Do not restore/reuse the old dynamic-skim object merely to match its IDs.
    manager = getattr(adapter, "v24916_dynamic_skims", None)
    if manager is not None:
        try:
            current = manager.require_current().summary()
            if current != (diag.get("d11") or {}).get("summary", {}).get("dynamic_distance_authority"):
                params.append("LIVE_DYNAMIC_SKIM_EPOCH_DIAGNOSTICS_MISMATCH")
        except Exception as exc:
            params.append("LIVE_DYNAMIC_SKIM_FRESHNESS:" + type(exc).__name__ + ":" + str(exc))
    return {"passes": not params and matrices["passes"] and diagnostic["passes"],
            "release": RELEASE,
            "parameter_differences": params, "matrix_proof": matrices, "diagnostics": diagnostic}


def rebind_verified_parent(adapter, state, diag):
    """Rebind an already-proved parent without incrementing accepted-change counters.

    Preserve the epoch geometry when its immutable context still matches. A fake
    or custom adapter without epoch state needs no callback. Never call the
    candidate-acceptance callback to represent a rollback.
    """
    proof = getattr(adapter, "_genfix2_parent_proof", None) or {}
    if proof.get("path_epoch_accepts_before") is not None:
        adapter.path_epoch_accepts = proof["path_epoch_accepts_before"]
    if getattr(adapter, "cache", None) is None:
        return {"retained": False, "reason": "NO_LIVE_PATH_EPOCH", "accepted_change": False}
    origin = getattr(adapter, "cache_snapshot", None) or {}
    if any(origin.get(k) != state.get(k) for k in ("fixed_link_hash", "dseg_hash", "operations_hash")):
        raise SupplyContractError("GENFIX2_PARENT_CACHE_IMMUTABLE_CONTEXT_MISMATCH")
    current = state.get("addval1", {})
    records = getattr(adapter, "cache_links", None)
    updates = []
    if records is not None:
        for key, row in records.items():
            text = "|".join(str(int(x)) for x in key)
            if text not in current:
                raise SupplyContractError("GENFIX2_PARENT_CACHE_LINK_COVERAGE")
            updates.append((row, float(current[text])))
    adapter.cache_live_snapshot = copy.deepcopy(state)
    adapter.path_epoch_plateau_verified = None
    adapter.supply_path_proof = None
    for row, value in updates:
        row["addval1"] = value
    persistent = getattr(adapter, "persistent_path_cache", None)
    manifest = getattr(adapter, "persistent_cache_manifest", None)
    if persistent is not None and persistent.enabled and manifest is not None:
        persistent.bind_state(state, manifest, reason="GENFIX2_VERIFIED_PARENT_REBASE", phase="RECOVERY")
    return {"retained": True, "reason": "GENFIX2_VERIFIED_PARENT_REBASE", "accepted_change": False}

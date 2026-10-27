# -*- coding: utf-8 -*-
"""GENFIX2: parameter-exact TD rollback with explicit full-parent evidence.

Existing TD parameter and profile roundoff tolerances remain unchanged. Changed
matrix hashes require pre-mutation, hash-bound arrays and bounded cell/margin/
total differences. Live 11D, component signals and profile authority are checked
even when the legacy diagnostic hash compares equal. Verified reconstruction
rebinds the existing parent cache; it is not a new accepted optimisation step.
"""
from __future__ import annotations

import functools
import math
import json
from pathlib import Path
from typing import Any, Dict, List, Mapping

RELEASE = "R1_15A2_V24917_TDROLLBACKFIX1_20261027"
PARAM_EXCLUDE = {"td_values", "td_hash", "state_hash", "matrices", "matrix_hash"}
ABS_TOL = 0.5          # vehicles per profile
REL_TOL = 1.0e-4       # of the profile volume
GEH_TOL = 0.01         # weighted mean CAL GEH
_STATE: Dict[str, Any] = {"installed": False, "tolerant_accepts": 0, "refused": 0, "events": []}


def _pid(r):
    for k in ("countlocation_no", "obs_id", "code"):
        if r.get(k) not in (None, ""):
            return str(r.get(k))
    return ""


def _f(v):
    try:
        x = float(v)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def profile_drift(before_rows, after_rows) -> Dict[str, Any]:
    from r1_15a2_supply import observation_identity
    from r1_15a2_td_count_blend_v24917 import cl_key
    errors = []
    def index(rows):
        out = {}
        for r in rows or []:
            key = cl_key(_pid(r))
            if not key or key in out:
                errors.append("EMPTY_OR_DUPLICATE_PROFILE:" + key)
            value = _f(r.get("model"))
            if value is None or value < 0:
                errors.append("INVALID_PROFILE_MODEL:" + key)
            out[key] = r
        if not out:
            errors.append("EMPTY_PROFILES")
        return out
    b, a = index(before_rows), index(after_rows)
    try:
        if observation_identity(before_rows) != observation_identity(after_rows):
            errors.append("OBSERVATION_AUTHORITY_CHANGED")
    except Exception as exc:
        errors.append("INVALID_OBSERVATION_AUTHORITY:" + str(exc))
    worst, worst_id, worst_rel, n_bad = 0.0, None, 0.0, len(errors)
    missing = sorted(set(b) ^ set(a))
    for k in set(b) & set(a):
        fields = {"model"} | {name for name in set(b[k]) | set(a[k]) if name.startswith("model_")}
        for field in fields:
            mb, ma = _f(b[k].get(field)), _f(a[k].get(field))
            if mb is None or ma is None or mb < 0 or ma < 0:
                n_bad += 1
                continue
            diff = abs(ma - mb)
            if diff > max(ABS_TOL, REL_TOL * abs(mb)):
                n_bad += 1
            if diff > worst:
                worst, worst_id, worst_rel = diff, k, diff / max(abs(mb), 1e-9)
    return {"profiles": len(set(b) & set(a)), "missing": missing[:20], "violations": n_bad,
            "max_abs_diff": worst, "max_rel_diff": worst_rel, "worst_profile": worst_id,
            "abs_tol": ABS_TOL, "rel_tol": REL_TOL, "identity_errors": errors[:20]}


PENALTY_KEY = "v24917_iz_penalty"
PENALTY_TOL = 1.0e-6     # minutes; the intrazonal penalty write itself is verified to 1e-6


def _penalty_equal(a, b) -> bool:
    if a == b:
        return True
    if not isinstance(a, Mapping) or not isinstance(b, Mapping) or set(a) != set(b):
        return False
    try:
        return all(abs(float(a[k]) - float(b[k])) <= PENALTY_TOL for k in a)
    except (TypeError, ValueError):
        return False


def parameter_differences(before: Mapping[str, Any], after: Mapping[str, Any]) -> List[str]:
    out = []
    for k in set(before) | set(after):
        if k in PARAM_EXCLUDE or before.get(k) == after.get(k):
            continue
        if k == PENALTY_KEY and _penalty_equal(before.get(k), after.get(k)):
            continue
        out.append(k)
    return sorted(out)


def matrix_differences(before, after) -> List[int]:
    bm = {r.get("matrix_no"): r.get("sha256_float64_le") for r in before.get("matrices", []) or []}
    am = {r.get("matrix_no"): r.get("sha256_float64_le") for r in after.get("matrices", []) or []}
    return sorted(int(k) for k in set(bm) | set(am) if bm.get(k) != am.get(k))


def _weighted_geh(rows):
    try:
        import r1_15a2_core as core
        m = core.csd_metrics(rows, "CALIBRATION", True)
        return float(m["objective_geh_mean_weighted"])
    except Exception:
        return None


def tolerant_check(ctrl, adapter, before, baseline_diag, folder, cfg) -> Dict[str, Any]:
    """Return a decision dict; on success it carries the recomputed (state, diag)."""
    from r1_15a2_supply import SupplyContractError
    folder = Path(folder)
    state = _live_snapshot(adapter)
    params = parameter_differences(before, state)
    mats = matrix_differences(before, state)
    rec: Dict[str, Any] = {"release": RELEASE, "parameter_differences": params,
                           "changed_matrices": mats[:50], "changed_matrix_count": len(mats), "_state": state}
    td_ok = True
    try:
        ctrl._td_expected_freeze(before, state, [], cfg or {}, folder / "TDROLLBACK1_TD_FREEZE_AUDIT.json")
    except SupplyContractError as exc:
        td_ok = False
        rec["td_freeze_error"] = str(exc)
    rec["td_parameters_restored"] = td_ok
    if params or not td_ok:
        rec["status"] = "REFUSED_PARAMETERS_NOT_RESTORED"
        return rec
    diag = adapter.diagnostics(folder / "TDROLLBACK1_DIAGNOSTICS", "ROLLBACK_TOLERANT")
    if _live_snapshot(adapter) != state:
        rec["status"] = "REFUSED_DIAGNOSTICS_CHANGED_MODEL"
        return rec
    import r1_15a2_parent_equivalence_v24917 as eq
    proof = eq.verify_parent(adapter, before, state, baseline_diag, diag,
                             allow_td=True, ctrl=ctrl, cfg=cfg, folder=folder)
    rec["parent_equivalence"] = proof
    rec.update(proof["diagnostics"])
    if not proof["passes"]:
        rec["status"] = "REFUSED_NOT_NUMERICALLY_EQUIVALENT"
        return rec
    rec["status"] = "PARAMETER_EXACT_NUMERICALLY_EQUIVALENT_RECOMPUTE"
    rec["state_hash_before"] = before.get("state_hash")
    rec["state_hash_after"] = state.get("state_hash")
    rec["_state"], rec["_diag"] = state, diag
    return rec


def _live_snapshot(adapter):
    # The GENFIX1 reader includes fresh IZ penalties and bypasses candidate caches.
    reader = getattr(adapter, "generation_guard_snapshot", None)
    return reader() if callable(reader) else adapter.snapshot()


def _write_final_proof(ctrl, folder, before, state, proof, mode):
    """The final verifier owns the result; a legacy PASS alone is provisional."""
    folder = Path(folder)
    evidence_path = folder / "TDROLLBACKFIX1_PARENT_PROOF.json"
    result_path = folder / "ROLLBACK_ALL_TD_RESULT.json"
    legacy = None
    try:
        from r1_15a2_runtime_io_hotfix_profile488 import _native_path
        with open(_native_path(result_path), encoding="utf-8-sig") as f:
            legacy = json.load(f)
    except (OSError, ValueError):
        pass
    public = {"release": RELEASE, "verification_mode": mode,
              "before_state_hash": before.get("state_hash"),
              "after_state_hash": state.get("state_hash"),
              "next_generation_permitted": bool(proof["passes"]),
              "accepted_optimization_step": False,
              "parent_equivalence": proof}
    ctrl.atomic_json(evidence_path, public)
    summary = dict(legacy or {})
    summary.update({"passes": bool(proof["passes"]),
                    "status": "VERIFIED_PARENT" if proof["passes"] else "PARENT_PROOF_FAILED",
                    "verification_layer": RELEASE, "legacy_result": legacy,
                    "parent_equivalence": proof, "proof_path": str(evidence_path),
                    "next_generation_permitted": bool(proof["passes"]),
                    "direct_od_matrix_writes": False, "load_version_called": False})
    ctrl.atomic_json(result_path, summary)
    return evidence_path


def _proof_failure(proof, evidence_path, prefix="GENFIX2_TD_ROLLBACK_FULL_PARENT_PROOF_FAILED"):
    from r1_15a2_supply import SupplyContractError
    reasons = list(proof.get("parameter_differences", []))
    matrices = proof.get("matrix_proof", {})
    if not matrices.get("passes"):
        reasons.append(matrices.get("reason", "MATRIX_PROOF_FAILED"))
    diagnostic = proof.get("diagnostics", {})
    reasons.extend(diagnostic.get("component_differences", []))
    drift = diagnostic.get("profile_drift", {})
    if drift.get("violations") or drift.get("missing"):
        reasons.append("PROFILE_DRIFT_OR_IDENTITY")
    if not diagnostic.get("passes") and not reasons:
        reasons.append("DIAGNOSTIC_OR_GEH_EQUIVALENCE")
    message = prefix + ":" + ";".join(str(x) for x in reasons[:6])[:1200]
    exc = SupplyContractError(message + ";proof=" + str(evidence_path))
    exc.parent_equivalence = proof
    exc.evidence_path = str(evidence_path)
    return exc


def wrap_rollback_td_all(orig, ctrl):
    @functools.wraps(orig)
    def _rollback_td_all(adapter, before, baseline_diag, folder, cfg=None):
        import r1_15a2_parent_equivalence_v24917 as eq
        try:
            state, diag = orig(adapter, before, baseline_diag, folder, cfg)
        except Exception as exc:
            if "V242_TD_ROLLBACK_NOT_IDENTICAL" not in str(exc):
                raise
            folder = Path(folder)
            try:
                rec = tolerant_check(ctrl, adapter, before, baseline_diag, folder, cfg)
            except Exception as exc2:
                rec = {"release": RELEASE, "status": "REFUSED_CHECK_ERROR", "error": repr(exc2)[:2000]}
            public = {k: v for k, v in rec.items() if not k.startswith("_")}
            ctrl.atomic_json(folder / "TDROLLBACK1_TOLERANT_RESULT.json", public)
            _STATE["events"].append({k: public.get(k) for k in ("status", "changed_matrix_count")})
            del _STATE["events"][:-50]
            if rec.get("status") != "PARAMETER_EXACT_NUMERICALLY_EQUIVALENT_RECOMPUTE":
                _STATE["refused"] += 1
                if "parent_equivalence" in rec:
                    evidence = _write_final_proof(ctrl, folder, before, rec.get("_state", before),
                                                  rec["parent_equivalence"], "NUMERIC_RECOMPUTE_REFUSED")
                    raise _proof_failure(rec["parent_equivalence"], evidence,
                                         prefix="V242_TD_ROLLBACK_NOT_IDENTICAL") from exc
                raise
            state, diag = rec["_state"], rec["_diag"]
            proof = rec["parent_equivalence"]
            mode = "BYTE_BOUND_NUMERIC_RECOMPUTE"
        else:
            if adapter is None or baseline_diag is None:
                return state, diag  # compatibility for pure dispatcher tests
            if diag is baseline_diag:
                diag = adapter.diagnostics(Path(folder) / "TDROLLBACKFIX1_LIVE_DIAGNOSTICS", "ROLLBACK")
            try:
                proof = eq.verify_parent(adapter, before, state, baseline_diag, diag,
                                         allow_td=True, ctrl=ctrl, cfg=cfg, folder=folder)
            except Exception as exc:
                proof = {"passes": False,
                         "parameter_differences": ["PARENT_PROOF_EVALUATION_ERROR:" + type(exc).__name__ + ":" + str(exc)],
                         "matrix_proof": {"passes": False, "reason": "PROOF_EVALUATION_INCOMPLETE"},
                         "diagnostics": {"passes": False, "component_differences": []}}
            mode = "LEGACY_EQUALITY_PLUS_FULL_PARENT_PROOF"
        # Always read through the live reader when available, not a cached bundle.
        try:
            stable = _live_snapshot(adapter) == state
        except Exception as exc:
            stable = False
            proof["parameter_differences"].append("FINAL_LIVE_READ:" + type(exc).__name__ + ":" + str(exc))
        proof["live_snapshot_stable"] = stable
        if not stable:
            proof["passes"] = False
            proof["parameter_differences"].append("LIVE_SNAPSHOT_NOT_EQUAL_RETURNED_STATE")
        if proof["passes"]:
            try:
                proof["parent_cache_rebind"] = eq.rebind_verified_parent(adapter, state, diag)
            except Exception as exc:
                proof["passes"] = False
                proof["parameter_differences"].append("PARENT_CACHE_REBIND:" + type(exc).__name__ + ":" + str(exc))
        evidence_path = _write_final_proof(ctrl, folder, before, state, proof, mode)
        if not proof["passes"]:
            _STATE["refused"] += 1
            raise _proof_failure(proof, evidence_path)
        if mode == "BYTE_BOUND_NUMERIC_RECOMPUTE":
            _STATE["tolerant_accepts"] += 1
        # Expose proof in ordinary adapter telemetry; never count a rollback as acceptance.
        if isinstance(getattr(adapter, "v24917_status", None), dict):
            adapter.v24917_status["last_td_rollback_proof"] = {
                "passes": True, "mode": mode, "path": str(evidence_path), "accepted_change": False}
        return state, diag
    _rollback_td_all.__r1_tdrollback1__ = True
    return _rollback_td_all


def install(print_fn=print) -> Dict[str, Any]:
    if _STATE["installed"]:
        return status()
    import r1_15a2_overnight_controller_coupled_v24915p2_force100 as ctrl
    for name in ("_rollback_td_all", "_td_expected_freeze", "atomic_json"):
        if not hasattr(ctrl, name):
            raise RuntimeError("V24917_TDROLLBACK1_SYMBOL_MISSING:" + name)
    if not getattr(ctrl._rollback_td_all, "__r1_tdrollback1__", False):
        ctrl._rollback_td_all = wrap_rollback_td_all(ctrl._rollback_td_all, ctrl)
    if not getattr(ctrl._finecdf_td_once_impl, "__r1_genfix2_matrix_proof__", False):
        original_stage = ctrl._finecdf_td_once_impl
        @functools.wraps(original_stage)
        def guarded_stage(adapter, cfg, folder, control, state, diag, package_root):
            import r1_15a2_parent_equivalence_v24917 as eq
            with eq.parent_scope(adapter, state, folder):
                return original_stage(adapter, cfg, folder, control, state, diag, package_root)
        guarded_stage.__r1_genfix2_matrix_proof__ = True
        ctrl._finecdf_td_once_impl = guarded_stage
    _STATE["installed"] = True
    print_fn("V24917 TDROLLBACKFIX1: epoch identity separated from content; full proof recorded; tolerances "
             "%.2g veh / %.0e rel per profile and %.2g weighted GEH" % (ABS_TOL, REL_TOL, GEH_TOL))
    return status()


def status() -> Dict[str, Any]:
    return {"release": RELEASE, "installed": _STATE["installed"],
            "tolerant_accepts": _STATE["tolerant_accepts"], "refused": _STATE["refused"],
            "events": list(_STATE["events"][-20:])}


__all__ = ["RELEASE", "install", "status", "profile_drift", "parameter_differences",
           "matrix_differences", "tolerant_check", "wrap_rollback_td_all"]

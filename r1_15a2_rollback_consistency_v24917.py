# -*- coding: utf-8 -*-
"""GENFIX2: verified rollback with live 12D/11D and byte-bound matrices.

Legacy profile tolerances remain unchanged. Numerical matrix equivalence needs
pre-mutation array evidence. A hash-only reread or reused diagnostic object is
not sufficient. Returned diagnostics always describe the measured live model.
"""
from __future__ import annotations

import copy
import functools
import inspect
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence

RELEASE = "R1_15A2_V24917_RBCONS_GENFIX2_20261027"
_STATE: Dict[str, Any] = {"installed": False, "proof_count_rebased": 0, "proof_errors": 0,
                          "tolerant_accepts": 0, "tolerant_refused": 0, "events": []}


def options() -> Dict[str, bool]:
    try:
        import r1_15a2_demand_policy_v1 as dp
        o = dp.load_options()
    except Exception:
        o = {}
    return {"tolerant": bool(o.get("rb_tolerant_diagnostics", True)),
            "roster_proof": bool(o.get("rb_roster_reuse_proof", True))}


def _event(kind: str, **kw) -> None:
    _STATE["events"].append(dict(kind=kind, **kw))
    del _STATE["events"][:-50]


# ------------------------------------------------------------- 1. reuse proof
def roster_cfg(cfg: Mapping[str, Any], n_rows: int):
    """Return (cfg_for_call, rebased) - a copy whose expected profile count is the roster's."""
    perf = (cfg.get("performance", {}) or {}).get("v24915_perf1", {}) or {}
    feature = perf.get("rollback_diagnostic_reuse", {}) or {}
    try:
        sealed = int(feature.get("expected_profiles", cfg.get("expected_12d_rows", 498)))
        roster = int(cfg.get("expected_12d_rows", -1))
    except (TypeError, ValueError):
        return cfg, False
    if sealed == n_rows or roster != n_rows or roster <= 0:
        return cfg, False
    out = dict(cfg)
    out["performance"] = dict(cfg.get("performance", {}) or {})
    p1 = dict(perf)
    f = dict(feature)
    f["expected_profiles"] = roster
    p1["rollback_diagnostic_reuse"] = f
    out["performance"]["v24915_perf1"] = p1
    return out, True


def wrap_signature(orig):
    @functools.wraps(orig)
    def count_profile_signature(visum, cfg, baseline_rows):
        rows = list(baseline_rows or [])
        call_cfg, rebased = (roster_cfg(cfg, len(rows)) if options()["roster_proof"] else (cfg, False))
        try:
            out = orig(visum, call_cfg, rows)
        except Exception as exc:
            _STATE["proof_errors"] += 1
            return {"schema": "R1_15A2_V24917_RBCONS1_SIGNATURE", "passes": False,
                    "reason": "SIGNATURE_READ_FAILED", "error": "%s:%s" % (type(exc).__name__, str(exc)[:500])}
        if rebased:
            _STATE["proof_count_rebased"] += 1
            out = dict(out)
            out["v24917_expected_profiles_source"] = "ACTIVE_ROSTER_EXPECTED_12D_ROWS"
            out["v24917_expected_profiles"] = len(rows)
        return out
    count_profile_signature.__r1_rbcons1__ = True
    return count_profile_signature


# ------------------------------------------------- 2. tolerant diagnostics
def tolerant_compare(baseline_diag: Mapping[str, Any], diag: Mapping[str, Any]) -> Dict[str, Any]:
    import r1_15a2_parent_equivalence_v24917 as eq
    return eq.compare_diagnostics(baseline_diag, diag)


def wrap_rollback_and_verify(orig, atomic_json):
    @functools.wraps(orig)
    def rollback_and_verify(adapter, block, before_snapshot, baseline_diag_hash,
                            diagnostic_hash_fn, folder, candidate_rows=None, candidate=None,
                            baseline_diag=None):
        kwargs = {"candidate_rows": candidate_rows, "candidate": candidate}
        try:
            if "baseline_diag" in inspect.signature(orig).parameters:
                kwargs["baseline_diag"] = baseline_diag
        except (TypeError, ValueError):
            pass
        try:
            result, diag = orig(adapter, block, before_snapshot, baseline_diag_hash, diagnostic_hash_fn,
                                folder, **kwargs)
            if adapter is not None and baseline_diag is not None:
                import r1_15a2_parent_equivalence_v24917 as eq
                from r1_15a2_supply import SupplyContractError
                live = adapter.snapshot()
                if diag is baseline_diag:
                    diag = adapter.diagnostics(Path(folder) / "GENFIX2_LIVE_PROOF", "ROLLBACK")
                proof = eq.verify_parent(adapter, before_snapshot, live, baseline_diag, diag)
                if adapter.snapshot() != live or not proof["passes"]:
                    raise SupplyContractError("GENFIX2_ROLLBACK_FULL_PARENT_PROOF_FAILED")
                result = dict(result, genfix2_parent_proof=proof, diagnostic_hash=diagnostic_hash_fn(diag),
                              diagnostic_equal=diagnostic_hash_fn(diag) == baseline_diag_hash,
                              diagnostic_equivalent=True)
            return result, diag
        except Exception as exc:
            eligible = any(text in str(exc) for text in
                           ("INPLACE_ROLLBACK_DIAGNOSTICS_DIFFER", "INPLACE_ROLLBACK_SNAPSHOT_DIFFER"))
            if not eligible or baseline_diag is None or not options()["tolerant"]:
                raise
            folder = Path(folder)
            rec: Dict[str, Any] = {"release": RELEASE, "block": str(block), "original_error": str(exc)}
            try:
                import r1_15a2_parent_equivalence_v24917 as eq
                state = adapter.snapshot()
                diag = adapter.diagnostics(folder / "RBCONS1_DIAGNOSTICS", "ROLLBACK_TOLERANT")
                if adapter.snapshot() != state:
                    rec["status"] = "REFUSED_DIAGNOSTICS_CHANGED_MODEL"
                else:
                    proof = eq.verify_parent(adapter, before_snapshot, state, baseline_diag, diag)
                    rec["parent_equivalence"] = proof
                    rec.update(proof["diagnostics"])
                    rec["passes"] = proof["passes"]
                    rec["status"] = ("SNAPSHOT_EXACT_LOADS_NUMERICALLY_EQUIVALENT" if proof["passes"]
                                     else "REFUSED_NOT_NUMERICALLY_EQUIVALENT")
            except Exception as exc2:
                rec["status"] = "REFUSED_CHECK_ERROR"
                rec["error"] = repr(exc2)[:2000]
            try:
                atomic_json(folder / "RBCONS1_TOLERANT_ROLLBACK.json", rec)
            except Exception:
                pass
            _event(rec["status"], block=str(block))
            if rec["status"] not in ("SNAPSHOT_EXACT_LOADS_NUMERICALLY_EQUIVALENT", "EXACT_ON_REREAD"):
                _STATE["tolerant_refused"] += 1
                raise
            _STATE["tolerant_accepts"] += 1
            drift = (rec.get("profile_drift") or {}).get("max_abs_diff", 0.0)
            print("R1 V24917 RBCONS1: %s rollback snapshot exact, loads within noise (max %.3g veh) - "
                  "live diagnostics returned" % (block, drift or 0.0))
            result = {"block": block, "snapshot_equal": state == before_snapshot, "state_after": state, "diagnostic_equal": diagnostic_hash_fn(diag) == baseline_diag_hash,
                      "diagnostic_hash": diagnostic_hash_fn(diag),
                      "baseline_diagnostic_hash": baseline_diag_hash,
                      "diagnostic_equivalent": True,
                      "diagnostic_verification_mode": "V24917_RBCONS1_" + rec["status"],
                      "rbcons1": rec, "passes": True, "load_version_called": False,
                      "save_version_called": False, "direct_od_matrix_writes": False}
            return result, diag
    rollback_and_verify.__r1_rbcons1__ = True
    return rollback_and_verify


# ------------------------------------------------------------------ install
def install(print_fn=print) -> Dict[str, Any]:
    if _STATE["installed"]:
        return status()
    import r1_15a2_acceleration_v24915p1 as perf1
    import r1_15a2_overnight_controller_v24915p2 as base
    for mod, name in ((perf1, "count_profile_signature"), (base, "rollback_and_verify"),
                      (base, "atomic_json")):
        if not hasattr(mod, name):
            raise RuntimeError("V24917_RBCONS1_SYMBOL_MISSING:" + name)
    if not getattr(perf1.count_profile_signature, "__r1_rbcons1__", False):
        perf1.count_profile_signature = wrap_signature(perf1.count_profile_signature)
    if not getattr(base.rollback_and_verify, "__r1_rbcons1__", False):
        base.rollback_and_verify = wrap_rollback_and_verify(base.rollback_and_verify, base.atomic_json)
    _STATE["installed"] = True
    o = options()
    print_fn("V24917 RBCONS1: rollback reuse proof on the active roster %s; noise-tolerant rollback "
             "diagnostics %s" % ("ON" if o["roster_proof"] else "OFF", "ON" if o["tolerant"] else "OFF"))
    return status()


def status() -> Dict[str, Any]:
    return {"release": RELEASE, **{k: (list(v) if isinstance(v, list) else v) for k, v in _STATE.items()},
            "options": options()}


__all__ = ["RELEASE", "install", "status", "roster_cfg", "wrap_signature", "tolerant_compare",
           "wrap_rollback_and_verify", "options"]

# -*- coding: utf-8 -*-
"""V24917 runtime installation on top of an already loaded V24916 launcher.

Installed in memory, after the V24916 runtime install and before parent.main:
  1. r1_15a2_multiblock patch: W/S domestic P upper 3.0, A upper 5.0; TARGETED_ZONE_DIRECT;
  2. TG pre-apply gate non-fatal (GENERATION_GATE rejects the candidate);
  3. demand policy: TD scheduling from R1_RUN_OPTIONS (universal fresh ALWAYS), early stop
     (options in R1_RUN_OPTIONS.json / environment);
  4. DIAGFAST V2 FAST_EXACT 12D/11D with the DIRECT guard (inline LEGACY vs
     FAST parity on the first call of each helper, automatic LEGACY fallback).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict

RELEASE = "R1_15A2_V24917_MOBILITYALLOC1_TDLONG1_RUNTIME_20261027"
_STATE: Dict[str, Any] = {}


def install_tg_gate(controller) -> Dict[str, Any]:
    import r1_15a2_generation_gate_nonfatal_v1 as gate
    if getattr(controller._evaluate_candidate, "__r1_generation_gate_nonfatal__", False):
        return {"installed": True, "already": True}
    events: list = []
    controller._evaluate_candidate = gate.wrap_evaluate(controller._evaluate_candidate, events)
    if gate.gap_override() is not None:
        raise RuntimeError("V24917_R1_MAX_GENERATION_PA_GAP_NOT_SUPPORTED_UNSET_IT")
    return {"installed": True, "release": gate.RELEASE, "events": events}


def install_demand_policy(controller, print_fn=print) -> Dict[str, Any]:
    import r1_15a2_demand_policy_v1 as dp
    options = dp.load_options()
    if abs(float(options["generation_envelope_scale"]) - 1.0) > 1.0e-12:
        raise RuntimeError("V24917_GENERATION_ENVELOPE_SCALE_MUST_BE_1_V24917_HAS_OWN_ENVELOPE")
    state = dp.activate(SimpleNamespace(coupled_runtime=controller), options=options, print_fn=print_fn)
    return {"installed": True, "release": dp.RELEASE, "note": state["note"]}


LAZY_RUNTIME_MODULES = ("r1_15a2_diagfast_parity_v1", "r1_15a2_diagfast_v2", "r1_15a2_diagfast_numpy_v2")


PARENT_EQ_MODULE = "r1_15a2_parent_equivalence_v24917"

def preload_parent_equivalence(root: Path = None) -> Dict[str, Any]:
    """Prebind the GENFIX2 rollback proof to its manifest-verified source.

    This module is imported lazily by generation/TD/supply transaction paths.
    The long-lived Visum host may restore sys.path or retain a stale finder
    cache between initialization and the first generation trial.  Successful
    source-manifest verification alone does not make that late import resolve.
    Loading the module by its absolute path *before* the first trial fixes the
    failure while preserving all rollback and diagnostic checks.
    """
    import hashlib
    import importlib.util
    import json
    root = (Path(root) if root is not None else Path(__file__).resolve().parent).resolve()
    source = root / (PARENT_EQ_MODULE + ".py")
    manifest_path = root / "V24917_RUNTIME_MANIFEST.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        expected = manifest["required_files"][source.name]
        actual = hashlib.sha256(source.read_bytes()).hexdigest()
    except (OSError, KeyError, ValueError) as exc:
        raise RuntimeError("V24917_PARENT_EQ_PREFLIGHT_INCOMPLETE:%s" % exc) from exc
    if expected != actual:
        raise RuntimeError("V24917_PARENT_EQ_SOURCE_HASH_MISMATCH")
    existing = sys.modules.get(PARENT_EQ_MODULE)
    if existing is not None:
        origin = getattr(existing, "__file__", None)
        if not origin or os.path.normcase(str(Path(origin).resolve())) != os.path.normcase(str(source)):
            raise RuntimeError("V24917_PARENT_EQ_WRONG_MODULE_ORIGIN:%s" % origin)
        return {"status": "ALREADY_BOUND", "source": str(source), "sha256": actual}
    spec = importlib.util.spec_from_file_location(PARENT_EQ_MODULE, str(source))
    if spec is None or spec.loader is None:
        raise RuntimeError("V24917_PARENT_EQ_SPEC_UNAVAILABLE:%s" % source)
    module = importlib.util.module_from_spec(spec)
    sys.modules[PARENT_EQ_MODULE] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(PARENT_EQ_MODULE, None)
        raise
    return {"status": "BOUND_BY_MANIFEST_VERIFIED_ABSOLUTE_PATH",
            "source": str(source), "sha256": actual}


def preload_modules(names=LAZY_RUNTIME_MODULES, root: Path = None) -> Dict[str, Any]:
    """Load modules that the runtime imports lazily (inside functions) up front.

    Live run 20261025_162648: ``import r1_15a2_diagfast_parity_v1`` inside the DIAGFAST
    inline audit raised ModuleNotFoundError although the file is in the sealed package
    (manifest PASS) -> the whole run fell back to slow LEGACY diagnostics.  A stale
    importlib directory cache in the long-lived Visum Python host (package folder
    replaced while Visum stayed open) or a sys.path change after start both produce
    exactly this.  Preloading into sys.modules by absolute file path removes the
    dependency on sys.path / finder caches for the rest of the run.
    """
    import importlib
    import importlib.util
    root = (Path(root) if root is not None else Path(__file__).resolve().parent).resolve()
    importlib.invalidate_caches()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    report = {"package_root": str(root), "modules": {}}
    for name in names:
        path = root / (name + ".py")
        if not path.is_file():
            raise RuntimeError("V24917_PRELOAD_MODULE_FILE_MISSING:%s" % path)
        if name in sys.modules:
            origin = getattr(sys.modules[name], "__file__", None)
            if not origin or os.path.normcase(str(Path(origin).resolve())) != os.path.normcase(str(path)):
                raise RuntimeError("V24917_PRELOAD_WRONG_MODULE_ORIGIN:%s:%s" % (name, origin))
            report["modules"][name] = "ALREADY_LOADED"
            continue
        spec = importlib.util.spec_from_file_location(name, str(path))
        if spec is None or spec.loader is None:
            raise RuntimeError("V24917_PRELOAD_SPEC_UNAVAILABLE:%s" % path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        try:
            spec.loader.exec_module(module)
        except BaseException:
            sys.modules.pop(name, None)
            raise
        report["modules"][name] = "LOADED_BY_ABSOLUTE_PATH"
    return report


def install_diagfast(rt, print_fn=print) -> Dict[str, Any]:
    preload = preload_modules()
    import r1_15a2_diagfast_runtime_v1 as fast
    import r1_15a2_diagfast_direct_v2 as direct
    from r1_15a2_supply import canonical_hash
    shim = SimpleNamespace(
        rt=rt, canonical_hash=canonical_hash,
        prepare_runtime_config=lambda *a, **k: ({"implementation_files": {}, "aggressive_tuning": {}}, None))
    activation = fast.activate(shim, "FAST_EXACT")
    guard = direct.install(shim, print_fn=print_fn)
    return {"installed": True, "activation": {k: v for k, v in activation.items() if k != "integrity"},
            "integrity": activation.get("integrity"), "guard_mode": guard.mode,
            "inline_parity": guard.inline_parity, "guard_log": str(guard.log_path),
            "preload": preload, "guard": guard}


def install_all(controller, rt, print_fn=print) -> Dict[str, Any]:
    if _STATE:
        return _STATE
    # Import before generation/TD/supply patches begin any model transaction.
    # Do not depend on sys.path at the eventual lazy-import callsite.
    parent_eq_status = preload_parent_equivalence()
    import r1_15a2_path_store_build_v24917 as path_store_build
    import r1_15a2_targeted_generation_v24917 as tg
    status = {"release": RELEASE, "parent_equivalence_preload": parent_eq_status}
    status["path_store_build"] = path_store_build.install()
    import r1_15a2_snapshot_reads_v24917 as snapshot_reads
    status["snapshot_reads"] = {
        "enabled": True, "release": snapshot_reads.RELEASE,
        "public_snapshot_schema_changed": False,
        "transient_errors_use_default_values": False,
        "generation_parent_check": "UNCACHED_LIVE_EXACT_EQUALITY",
    }
    status["multiblock"] = tg.patch_multiblock()
    import r1_15a2_finecdf_gapfix_v24917 as gapfix
    status["finecdf_gapfix"] = gapfix.install()
    import r1_15a2_td_count_blend_v24917 as td_blend
    status["td_count_blend"] = td_blend.install(print_fn=print_fn)
    import r1_15a2_long_post_td_mask_v24917 as long_post_mask
    status["long_post_td_mask"] = long_post_mask.install(rt)
    import r1_15a2_intrazonal_penalty_v24917 as izpen
    status["intrazonal_penalty"] = izpen.install(print_fn=print_fn)
    import r1_15a2_profile_roster_v24917 as roster
    status["profile_roster_gate"] = roster.install_gate()
    status["tg_gate"] = install_tg_gate(controller)
    status["demand_policy"] = install_demand_policy(controller, print_fn=print_fn)
    import r1_15a2_fast_trial_assignment_v24917 as fastassign
    status["fast_trial_assignment"] = fastassign.install(print_fn=print_fn)
    import r1_15a2_step_search_v24917 as step1
    status["step_search"] = step1.install(print_fn=print_fn)
    import r1_15a2_demand_policy_v1 as _dp
    if _dp.load_options().get("perf3_enabled", True):
        import r1_15a2_perf_v24917 as perf3
        status["perf3"] = perf3.install(print_fn=print_fn)
    else:
        status["perf3"] = {"installed": False, "reason": "perf3_enabled=false"}
    import r1_15a2_preflight_explain_v24917 as preflight2
    status["preflight2"] = preflight2.install(print_fn=print_fn)
    import r1_15a2_combusy2_v24917 as combusy2
    status["combusy2"] = combusy2.install(print_fn=print_fn)
    import r1_15a2_severity_relax_v24917 as sevrelax
    status["severity_relax"] = sevrelax.install(print_fn=print_fn)
    import r1_15a2_td_rollback_tolerant_v24917 as tdrb
    status["td_rollback_tolerant"] = tdrb.install(print_fn=print_fn)
    import r1_15a2_boundary_pa_v24917 as bdpa
    status["boundary_pa"] = bdpa.install(print_fn=print_fn)
    import r1_15a2_rollback_consistency_v24917 as rbcons
    status["rollback_consistency"] = rbcons.install(print_fn=print_fn)
    import r1_15a2_supply_mix_v24917 as supplymix
    status["supplymix"] = supplymix.install(print_fn=print_fn)
    if os.environ.get("R1_DIAGFAST_DISABLE", "").strip() in ("1", "true", "TRUE", "yes"):
        status["diagfast"] = {"installed": False, "reason": "R1_DIAGFAST_DISABLE"}
    else:
        status["diagfast"] = install_diagfast(rt, print_fn=print_fn)
    import r1_15a2_mobility_guard_v24917 as _mguard
    o = _dp.load_options()
    status["genfix2_policy_semantics"] = {
        "release": RELEASE,
        "td_survey_limit_scope": "LOCAL_STEP_ERROR_RATIO_NOT_GLOBAL_SURVEY_PERCENT",
        "td_local_max_error_ratio": o.get("td_max_survey_degradation"),
        "global_survey_error_limit_added": False,
        "mobility_band": [o.get("mg_min_ratio"), o.get("mg_max_ratio")],
        "mobility_reference": "EXISTING_FP_DIV_ADD_REFERENCE_NOT_INDEPENDENT_SURVEY_VALIDATION",
        "ws_attraction_coefficient_band": list(_mguard.ATTRACTION_BAND),
        "ws_attraction_gate": "FINAL_GENERATION_CANDIDATE_AND_LIVE_ZONE_READBACK_ONLY",
        "attraction_changes_mobility_ratio": False,
        "early_exploration_extended": o.get("sev_extend_early_horizon"),
        "fast_assignment_step1": "NOT_ACTIVE_FULL_ASSIGNMENT_REQUIRED",
        "stationarity": "BOUNDED_STEP1_EXHAUSTION_NOT_CERTIFIED",
        "release_live_visum_validation_supplied": False,
    }
    import r1_15a2_td_joint_runtime_v24917 as tdjoint
    status["tdjoint1"] = tdjoint.install(controller, print_fn=print_fn)
    import r1_15a2_td_numpy_v24917 as td_numpy
    import r1_15a2_td_restore_v24917 as td_restore
    status["td_numpy"] = td_numpy.install()
    status["td_restore"] = td_restore.install()
    _STATE.update(status)
    return _STATE


def public_status(status: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(status)
    if isinstance(out.get("diagfast"), dict):
        out["diagfast"] = {k: v for k, v in out["diagfast"].items() if k != "guard"}
    if isinstance(out.get("tg_gate"), dict):
        out["tg_gate"] = {k: v for k, v in out["tg_gate"].items() if k != "events"}
    return out


__all__ = ["RELEASE", "install_all", "install_tg_gate", "install_demand_policy",
           "install_diagfast", "public_status"]

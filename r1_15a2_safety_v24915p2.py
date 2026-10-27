# -*- coding: utf-8 -*-
"""Fail-closed safety contract for V24915 PERF2 CandidateReadbackBundle."""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from typing import Any, Mapping

import r1_15a2_runtime_v1 as rt
import r1_15a2_safety_v24915p1 as parent_safety
from r1_15a2_supply import SupplyContractError

RELEASE = "R1_15A2_V2_4_9_15_PERF2_CANDIDATE_READBACK_BUNDLE_20261019"
PARENT_RELEASE = parent_safety.RELEASE
PARENT_CONFIG_FILE = "R1_15A2_CONFIG_V2_4_9_15_PERF1.json"
PARENT_CONFIG_SHA256 = "360b80d1cd259250d551eed1b8891431f854bd87486a9ea48d7cbfbfdd9243e6"
CONTRACT_FILE = "V24915_PERF2_CANDIDATE_READBACK_BUNDLE_CONTRACT.json"
CONTRACT_SHA256 = "d6441bc5bff362f2fb08ba9ba0d14bced1f4a39713067cac52611d024563110c"
RUNTIME_MANIFEST_FILE = "V24915_PERF2_RUNTIME_BUNDLE_MANIFEST.json"
RUNTIME_MANIFEST_SHA256 = "d32d02b878b12cbe6ecf1c662824689736dd0b2a5991d7b84353256914b450bc"
PACKAGE_REVISION = "V24915_PERF2_R5_OVERNIGHT50_B0016_CONTINUATION"
R4_BASELINE_CONFIG_FILE = "R1_15A2_CONFIG_V2_4_9_15_PERF2_R4_BASELINE.json"
R4_BASELINE_CONFIG_SHA256 = "a720d1c61d323781302dfefe4b1fc82d95d50491ca77d16d9f83160817984c0e"
OVERNIGHT50_CONTRACT_FILE = "V24915_PERF2_R5_OVERNIGHT50_EXTENSION_CONTRACT.json"
OVERNIGHT50_CONTRACT_SHA256 = "f855f750e0c4b79a27c59b3c6adabde6f76c8879654543d5ba1348cc29656169"
OVERNIGHT50_MAX_OUTER_CYCLES = 50
OVERNIGHT50_RUNTIME_SECONDS = 64800.0


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise SupplyContractError(code)


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _parent(root: Path) -> Mapping[str, Any]:
    path = root / PARENT_CONFIG_FILE
    _require(path.is_file(), "V24915P2_PARENT_CONFIG_MISSING")
    _require(rt.sha256_file(path) == PARENT_CONFIG_SHA256,
             "V24915P2_PARENT_CONFIG_HASH_MISMATCH")
    cfg = rt.read_json(path)
    _require(cfg.get("release") == PARENT_RELEASE,
             "V24915P2_PARENT_RELEASE_MISMATCH")
    return cfg


def _expected_feature() -> Mapping[str, Any]:
    return {
        "schema": "R1_15A2_V24915_PERF2_CONFIG_V1",
        "enabled": True,
        "shadow_parity_mode": True,
        "fallback_to_legacy": True,
        "require_exact_snapshot_parity": True,
        "candidate_math_changed": False,
        "acceptance_changed": False,
        "assignment_method_changed": False,
        "matrix_fingerprint_semantics_changed": False,
        "diagnostic_method_changed": False,
        "candidate_parallelism": False,
        "cross_run_cache": False,
        "invalidate_before_side_effect": True,
        "required_identity_fields": [
            "visum_session_token", "run_token", "accepted_parent_state_hash",
            "block", "candidate_write_signature", "mutation_epoch",
            "assignment_epoch", "payload_hash",
        ],
    }


def _r4_baseline(root: Path) -> Mapping[str, Any]:
    path = root / R4_BASELINE_CONFIG_FILE
    _require(path.is_file(), "V24915P2_R5_R4_BASELINE_CONFIG_MISSING")
    _require(rt.sha256_file(path) == R4_BASELINE_CONFIG_SHA256,
             "V24915P2_R5_R4_BASELINE_CONFIG_HASH_MISMATCH")
    return rt.read_json(path)


def _validate_reviewed_delta(cfg: Mapping[str, Any], root: Path) -> None:
    """Allow only the reviewed R5 overnight budget extension over exact R4.

    No acceptance threshold or calibration math is changed.  Only outer-loop
    coverage and the global wall-clock lease are extended; the mature final
    Generation/FineCDF stages keep the exact same step sizes and inner budgets.
    """
    baseline = copy.deepcopy(dict(_r4_baseline(root)))
    child_all = copy.deepcopy(dict(cfg))
    child = {key: copy.deepcopy(child_all.get(key)) for key in baseline}
    # load_config() injects these runtime-only fields before safety validation.
    # Normalize them back to the on-disk R4 baseline so they do not masquerade
    # as calibration-policy drift.
    for runtime_key in ("implementation_files", "implementation_hash", "config_path", "config_sha256"):
        if runtime_key in baseline:
            child[runtime_key] = copy.deepcopy(baseline.get(runtime_key))

    _require(child.get("package_revision") == PACKAGE_REVISION,
             "V24915P2_R5_PACKAGE_REVISION_DRIFT")
    child["package_revision"] = baseline.get("package_revision")

    manifest_sha = child.get("runtime_bundle_manifest_sha256")
    _require(isinstance(manifest_sha, str) and len(manifest_sha) == 64,
             "V24915P2_R5_RUNTIME_MANIFEST_SHA_MISSING")
    child["runtime_bundle_manifest_sha256"] = baseline.get("runtime_bundle_manifest_sha256")

    phases = child.get("calibration_phases") or []
    base_phases = baseline.get("calibration_phases") or []
    _require(len(phases) == len(base_phases) and len(phases) >= 1,
             "V24915P2_R5_PHASE_STRUCTURE_DRIFT")
    _require(int(phases[0].get("max_cycles", -1)) == OVERNIGHT50_MAX_OUTER_CYCLES,
             "V24915P2_R5_DEMAND_PHASE_CAP_NOT_50")
    phases[0]["max_cycles"] = base_phases[0]["max_cycles"]

    dc = child.get("coupled_demand") or {}
    base_dc = baseline.get("coupled_demand") or {}
    _require(int(dc.get("max_outer_cycles", -1)) == OVERNIGHT50_MAX_OUTER_CYCLES,
             "V24915P2_R5_OUTER_CAP_NOT_50")
    dc["max_outer_cycles"] = base_dc["max_outer_cycles"]
    stages = dc.get("finecdf_td", {}).get("progressive_schedule", [])
    base_stages = base_dc.get("finecdf_td", {}).get("progressive_schedule", [])
    _require(len(stages) == len(base_stages) and stages,
             "V24915P2_R5_FINECDF_STAGE_STRUCTURE_DRIFT")
    _require(int(stages[-1].get("through_outer_cycle", -1)) == OVERNIGHT50_MAX_OUTER_CYCLES,
             "V24915P2_R5_FINECDF_FINAL_STAGE_NOT_50")
    stages[-1]["through_outer_cycle"] = base_stages[-1]["through_outer_cycle"]

    perf = child.get("performance") or {}
    base_perf = baseline.get("performance") or {}
    gen_stages = perf.get("generation_step_schedule", [])
    base_gen_stages = base_perf.get("generation_step_schedule", [])
    _require(len(gen_stages) == len(base_gen_stages) and gen_stages,
             "V24915P2_R5_GENERATION_STAGE_STRUCTURE_DRIFT")
    _require(int(gen_stages[-1].get("through_outer_cycle", -1)) == OVERNIGHT50_MAX_OUTER_CYCLES,
             "V24915P2_R5_GENERATION_FINAL_STAGE_NOT_50")
    gen_stages[-1]["through_outer_cycle"] = base_gen_stages[-1]["through_outer_cycle"]

    trial = child.get("trial_calibration") or {}
    base_trial = baseline.get("trial_calibration") or {}
    _require(float(trial.get("max_runtime_seconds", -1.0)) == OVERNIGHT50_RUNTIME_SECONDS,
             "V24915P2_R5_GLOBAL_RUNTIME_NOT_18H")
    trial["max_runtime_seconds"] = base_trial["max_runtime_seconds"]

    _require(int(child_all.get("early_exploration_acceptance", {}).get("through_outer_cycle", -1)) == 12,
             "V24915P2_R5_ACCEPTANCE_HORIZON_MUST_REMAIN_12")
    _require(int(child_all.get("coupled_demand", {}).get("min_stationary_cycles", -1)) == 2,
             "V24915P2_R5_STATIONARITY_RULE_DRIFT")
    _require(int(child_all.get("coupled_demand", {}).get("supply_max_cycles", -1)) == 100,
             "V24915P2_R5_SUPPLY_CAP_DRIFT")
    _require(float(child_all.get("coupled_demand", {}).get("finecdf_td", {}).get("max_runtime_seconds", -1)) ==
             float(baseline.get("coupled_demand", {}).get("finecdf_td", {}).get("max_runtime_seconds", -2)),
             "V24915P2_R5_FINECDF_INNER_RUNTIME_DRIFT")

    _require(_canonical(child) == _canonical(baseline),
             "V24915P2_R5_UNREVIEWED_CONFIG_DRIFT")

    feature = cfg.get("performance", {}).get(
        "v24915_perf2_candidate_readback_bundle", {})
    _require(_canonical(feature) == _canonical(_expected_feature()),
             "V24915P2_FEATURE_CONTRACT_DRIFT")

    extension = root / OVERNIGHT50_CONTRACT_FILE
    _require(extension.is_file() and rt.sha256_file(extension) == OVERNIGHT50_CONTRACT_SHA256,
             "V24915P2_R5_OVERNIGHT50_CONTRACT_HASH_MISMATCH")

def preflight_v24915p2_deployment_files(package_root=None) -> Mapping[str, Any]:
    root = Path(package_root).resolve() if package_root is not None else Path(__file__).resolve().parent
    path = root / RUNTIME_MANIFEST_FILE
    _require(path.is_file(), "V24915P2_RUNTIME_MANIFEST_MISSING")
    _require(rt.sha256_file(path) == RUNTIME_MANIFEST_SHA256,
             "V24915P2_RUNTIME_MANIFEST_HASH_MISMATCH")
    manifest = rt.read_json(path)
    _require(manifest.get("schema") ==
             "R1_15A2_V24915_PERF2_RUNTIME_BUNDLE_MANIFEST_V1",
             "V24915P2_RUNTIME_MANIFEST_SCHEMA_MISMATCH")
    _require(manifest.get("release") == RELEASE,
             "V24915P2_RUNTIME_MANIFEST_RELEASE_MISMATCH")
    failures = []
    checked = 0
    for row in manifest.get("files", []):
        rel = str(row.get("path", ""))
        file = root / rel
        if not rel or not file.is_file():
            failures.append({"path": rel, "reason": "MISSING"})
            continue
        checked += 1
        if int(file.stat().st_size) != int(row.get("size", -1)):
            failures.append({"path": rel, "reason": "SIZE_MISMATCH"})
        elif rt.sha256_file(file) != row.get("sha256"):
            failures.append({"path": rel, "reason": "SHA256_MISMATCH"})
    _require(not failures, "V24915P2_RUNTIME_BUNDLE_INVALID:" +
             json.dumps(failures, sort_keys=True))
    return {
        "passes": True, "release": RELEASE,
        "package_revision": PACKAGE_REVISION,
        "manifest_path": str(path),
        "manifest_sha256": RUNTIME_MANIFEST_SHA256,
        "files_checked": checked, "failures": [],
    }


def validate_v24915p2_config(cfg: Mapping[str, Any], package_root=None) -> Mapping[str, Any]:
    root = Path(package_root).resolve() if package_root is not None else Path(__file__).resolve().parent
    _validate_reviewed_delta(cfg, root)
    _require(cfg.get("release") == RELEASE and cfg.get("safety_gate_release") == RELEASE,
             "V24915P2_RELEASE_IDENTITY_MISSING")
    _require(cfg.get("version") == "2.4.9.15-perf2-candidate-readback-bundle",
             "V24915P2_VERSION_IDENTITY_MISSING")
    _require(cfg.get("package_revision") == PACKAGE_REVISION,
             "V24915P2_PACKAGE_REVISION_MISSING")
    _require(cfg.get("runtime_bundle_manifest") == RUNTIME_MANIFEST_FILE and
             cfg.get("runtime_bundle_manifest_sha256") == RUNTIME_MANIFEST_SHA256,
             "V24915P2_RUNTIME_MANIFEST_NOT_PINNED")
    contract = root / CONTRACT_FILE
    _require(contract.is_file() and rt.sha256_file(contract) == CONTRACT_SHA256,
             "V24915P2_CONTRACT_HASH_MISMATCH")
    _require(cfg.get("guard_contract_file") == CONTRACT_FILE and
             cfg.get("guard_contract_sha256") == CONTRACT_SHA256,
             "V24915P2_CONTRACT_NOT_PINNED")

    parent_preflight = parent_safety.preflight_v24915p1_deployment_files(root)
    _require(parent_preflight.get("passes") is True,
             "V24915P2_PARENT_DEPLOYMENT_NOT_INTACT")

    parent = _parent(root)
    for key in (
        "demand_continuation", "supply", "supply_route_choice_acceptance",
        "supply_route_choice_readiness", "early_exploration_acceptance",
        "geh20_transition_policy", "restart_authority",
        "shared_objective", "td", "generation", "acceptance",
    ):
        _require(_canonical(cfg.get(key)) == _canonical(parent.get(key)),
                 "V24915P2_CALIBRATION_POLICY_DRIFT:" + key)

    feature = cfg.get("performance", {}).get(
        "v24915_perf2_candidate_readback_bundle", {})
    _require(_canonical(feature) == _canonical(_expected_feature()),
             "V24915P2_FEATURE_CONTRACT_DRIFT")
    compat = cfg.get("performance", {}).get("persistent_path_cache", {}).get(
        "explicit_predecessor_read_compatibility", {})
    _require(compat.get("target_release") == RELEASE,
             "V24915P2_CACHE_TARGET_RELEASE_MISMATCH")

    impl = cfg.get("implementation_files", {}) or {}
    required = (
        "R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_9_15_PERF2.py",
        "r1_15a2_safety_v24915p2.py",
        "r1_15a2_candidate_readback_bundle_v24915p2.py",
        "r1_15a2_trial_adapter_v24915p2.py",
        "r1_15a2_inplace_transaction_v24915p2.py",
        "r1_15a2_overnight_controller_v24915p2.py",
        "r1_15a2_overnight_controller_coupled_v24915p2.py",
        "r1_15a2_supply_handoff_v24915p2.py",
        "r1_15a2_demand_continuation_v24915r4.py",
        "r1_15a2_demand_continuation_v24915r5.py",
    )
    for name in required:
        digest = impl.get(name)
        _require(isinstance(digest, str) and len(digest) == 64,
                 "V24915P2_IMPLEMENTATION_HASH_MISSING:" + name)
        _require((root / name).is_file() and rt.sha256_file(root / name) == digest,
                 "V24915P2_IMPLEMENTATION_HASH_MISMATCH:" + name)
    r4_authority = root / "V24915_B0016_CONTINUATION_AUTHORITY.json"
    _require(r4_authority.is_file() and
             rt.sha256_file(r4_authority) == "602d0cdf7b40ad6cb8ab49d36030e6bc16c06eba757d56ffdf7d4ad28e3185a9",
             "V24915P2_R4_B0016_AUTHORITY_HASH_MISMATCH")
    r4_reference = root / "continuation_b0016" / "GENERATION_COUNTS_REFERENCE.json"
    _require(r4_reference.is_file() and
             rt.sha256_file(r4_reference) == "57016672bc247a820075998e98453e7dd4155d6e5b3fd2dcdf752731f6c29e2c",
             "V24915P2_R4_GENERATION_REFERENCE_HASH_MISMATCH")
    r5_contract = root / OVERNIGHT50_CONTRACT_FILE
    _require(r5_contract.is_file() and rt.sha256_file(r5_contract) == OVERNIGHT50_CONTRACT_SHA256,
             "V24915P2_R5_OVERNIGHT50_CONTRACT_HASH_MISMATCH")
    sealed_idp = root / "helpers" / "R1_IDP_DISTRIBUTION_AUTHORITY_V1" / "R1_IDP_DIST_KM_TARGET_CURVES_V1.csv"
    _require(sealed_idp.is_file() and
             rt.sha256_file(sealed_idp) == "f68087c249d6f1da2582e2ea1d723a8b3d1a8d99af82ffe5283f63d0de6a0737",
             "V24915P2_R4_SEALED_IDP_AUTHORITY_HASH_MISMATCH")
    return {
        "passes": True,
        "release": RELEASE,
        "parent_release": PARENT_RELEASE,
        "parent_config_sha256": PARENT_CONFIG_SHA256,
        "calibration_math_changed": False,
        "assignment_method_changed": False,
        "acceptance_changed": False,
        "candidate_readback_bundle": True,
        "legacy_fallback": True,
        "live_12d_11d_unchanged": True,
        "overnight50_budget_extension": True,
        "max_outer_cycles": OVERNIGHT50_MAX_OUTER_CYCLES,
        "max_runtime_seconds": OVERNIGHT50_RUNTIME_SECONDS,
        "real_visum_tested": False,
        "production_ready": False,
    }


def validate_v24915p2_runtime_bundle(cfg: Mapping[str, Any], package_root=None) -> Mapping[str, Any]:
    root = Path(package_root).resolve() if package_root is not None else Path(__file__).resolve().parent
    deployment = preflight_v24915p2_deployment_files(root)
    config = validate_v24915p2_config(cfg, root)
    mixed = []
    for name, module in list(sys.modules.items()):
        if not name.startswith("r1_15a2_") or module is None:
            continue
        filename = getattr(module, "__file__", None)
        if filename and Path(filename).resolve().parent != root:
            mixed.append({"module": name, "file": str(Path(filename).resolve())})
    _require(not mixed, "V24915P2_MIXED_RELEASE_MODULES:" + json.dumps(mixed, sort_keys=True))
    return {
        "passes": True,
        "release": RELEASE,
        "package_revision": PACKAGE_REVISION,
        "files_checked": deployment["files_checked"],
        "mixed_release_modules": [],
        "parent_deployment_intact": True,
        "config_validation": config,
        "real_visum_tested": False,
        "production_ready": False,
    }


__all__ = [
    "RELEASE", "PARENT_RELEASE", "PARENT_CONFIG_SHA256", "CONTRACT_FILE",
    "CONTRACT_SHA256", "RUNTIME_MANIFEST_FILE", "RUNTIME_MANIFEST_SHA256",
    "PACKAGE_REVISION", "preflight_v24915p2_deployment_files",
    "validate_v24915p2_config", "validate_v24915p2_runtime_bundle",
]

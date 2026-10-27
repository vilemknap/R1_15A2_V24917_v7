# -*- coding: utf-8 -*-
"""V2.4.9.3 methodology and COM-resilience safety contract.

This release preserves the signed Generation and TD soft-reference contract of
V2.4.9.2.  It changes only four reviewed semantics: the aggregate CSD objective
uses weighted mean GEH, profile sums are diagnostic passage checksums, LONG is
accepted as one global composite mix, and zonal COM transactions use a verified
identity cache plus bounded transient-only retries.
"""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
from typing import Any, Mapping

from r1_15a2_safety_v2492 import (
    RELEASE as V2492_RELEASE,
    validate_v2492_config,
)
from r1_15a2_supply import SupplyContractError
import r1_15a2_runtime_v1 as rt

RELEASE = "R1_15A2_V2_4_9_3_METHOD_AND_COM_CORRECTIONS_20261018"
V2492_CONFIG_SHA256 = "356cde547e168d277763cf52a3fb82cc4f766863fd0340a695ab87785960ed22"
V2492_PATH_IMPLEMENTATION_FILES = {
    "r1_15a2_two_mode_v238.py": "a58980069e942b6782f6d906443e81922f81e6596eb5de5be456719f96ce15ad",
    "r1_15a2_trial_adapter_v240.py": "f55e7e4936bb93770fb7ff99d6a485a0695575f1e6c59ba44552e2163c857109",
    "r1_15a2_persistent_path_cache_v248.py": "78522a1a9d7bd4bcabfb360604fd9c0a6d3415e0d845d935e7c3084aeedb276c",
    "r1_15a2_sequence_v23.py": "91a3c65e7c38a56dbb560d5debe91235ae10637176de16f08b29ccd09ff5a983",
    "r1_15a2_supply.py": "c35e6440b63bbc9ba2ec060ef77543d420e0411b5b463dee8479171e0a46198e",
    "r1_15a2_core.py": "f8c46886dc5fead310812f053037e005bee3c4bb641aa9439f11f222fb9976d7",
    "r1_15a2_runtime_v1.py": "eed25b8dc78ca2c256b6d67a4893cdbb8acae4fb80f529ff10254054bb7c14f9"
}


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise SupplyContractError(code)


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _load_and_validate_bundled_v2492(package_root: Path) -> Mapping[str, Any]:
    launcher = package_root / "R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_9_2.py"
    _require(launcher.is_file(), "V2493_BUNDLED_V2492_LAUNCHER_MISSING")
    spec = importlib.util.spec_from_file_location("_r1_v2492_lineage_launcher", launcher)
    _require(spec is not None and spec.loader is not None,
             "V2493_BUNDLED_V2492_IMPORT_SPEC_FAILED")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    baseline = module.load_config()
    return validate_v2492_config(baseline, package_root)


def _validate_reviewed_delta(cfg: Mapping[str, Any], package_root: Path) -> None:
    baseline = rt.read_json(package_root / "R1_15A2_CONFIG_V2_4_9_2.json")
    allowed_top = {
        "version", "release", "safety_gate_release", "methodology",
        "implementation_files", "csd_calibration_objective", "com_resilience",
    }
    for key, old_value in baseline.items():
        if key in allowed_top:
            continue
        _require(key in cfg, "V2493_CONFIG_KEY_MISSING:" + key)
        new_value = cfg[key]
        if key == "td":
            old_value = copy.deepcopy(old_value); new_value = copy.deepcopy(new_value)
            for name in ("long_acceptance_mode", "long_composite_authority",
                         "max_cal_geh_relative_degradation"):
                old_value.pop(name, None); new_value.pop(name, None)
        elif key == "coupled_demand":
            old_value = copy.deepcopy(old_value); new_value = copy.deepcopy(new_value)
            old_value.pop("generation_objective", None)
            new_value.pop("generation_objective", None)
        elif key == "performance":
            old_value = copy.deepcopy(old_value); new_value = copy.deepcopy(new_value)
            old_value.pop("release", None); new_value.pop("release", None)
            old_compat = old_value["persistent_path_cache"]["explicit_predecessor_read_compatibility"]
            new_compat = new_value["persistent_path_cache"]["explicit_predecessor_read_compatibility"]
            old_compat.pop("target_release", None); new_compat.pop("target_release", None)
            new_compat["predecessors"] = [
                row for row in new_compat.get("predecessors", [])
                if row.get("source_release") != V2492_RELEASE
            ]
        _require(_canonical(new_value) == _canonical(old_value),
                 "V2493_UNREVIEWED_CONFIG_DRIFT:" + key)


def validate_v2493_config(cfg: Mapping[str, Any], package_root=None) -> Mapping[str, Any]:
    root = Path(package_root).resolve() if package_root is not None else Path(__file__).resolve().parent
    predecessor = _load_and_validate_bundled_v2492(root)
    _validate_reviewed_delta(cfg, root)

    _require(cfg.get("release") == RELEASE and cfg.get("safety_gate_release") == RELEASE,
             "V2493_RELEASE_IDENTITY_MISSING")
    _require(cfg.get("version") == "2.4.9.3-method-and-com-corrections-tg-td-supply", "V2493_VERSION_IDENTITY_MISSING")
    _require(str(cfg.get("guidance_mode", "")).upper() == "SIGNED" and
             cfg.get("allow_signed_apply") is True,
             "V2493_SIGNED_GENERATION_CONTRACT_LOST")

    csd = cfg.get("csd_calibration_objective", {}) or {}
    expected_csd = {
        "metric": "WEIGHTED_MEAN_GEH",
        "profile_sum_role": "DIAGNOSTIC_ONLY_PROFILE_PASSAGE_CHECKSUM",
        "unique_trip_interpretation_allowed": False,
        "individual_severity_metric": "GEH",
    }
    _require(_canonical(csd) == _canonical(expected_csd),
             "V2493_CSD_OBJECTIVE_CONTRACT_CHANGED")

    td = cfg.get("td", {}) or {}
    _require(td.get("long_acceptance_mode") == "GLOBAL_LONG_COMPOSITE" and
             td.get("long_composite_authority") == "AGGREGATE_CL_GUARD_GLOBAL_MIX",
             "V2493_LONG_COMPOSITE_CONTRACT_CHANGED")
    _require(float(td.get("max_cal_geh_relative_degradation", -1.0)) == 0.005,
             "V2493_CAL_GEH_GUARD_CHANGED")
    _require(float(td.get("max_cal_geh2_relative_degradation", -1.0)) == 0.005,
             "V2493_LEGACY_GEH2_DIAGNOSTIC_CHANGED")
    _require(cfg.get("max_new_geh20") == 0 and cfg.get("max_new_geh30") == 0,
             "V2493_INDIVIDUAL_GEH_GUARD_CHANGED")

    com = cfg.get("com_resilience", {}) or {}
    expected_com = {
        "enabled": True,
        "max_attempts": 5,
        "initial_delay_seconds": 0.05,
        "backoff_factor": 2.0,
        "max_delay_seconds": 0.8,
        "helper_retry_enabled": True,
        "zone_identity_cache": True,
        "zone_readback_tolerance": 1.0e-7,
        "retryable_hresult": [-2147418111, -2147417846],
        "retry_scope": "TRANSIENT_RPC_CALL_REJECTED_OR_RETRY_LATER_ONLY",
    }
    _require(_canonical(com) == _canonical(expected_com),
             "V2493_COM_RESILIENCE_CONTRACT_CHANGED")

    _require(cfg.get("coupled_demand", {}).get("generation_objective") ==
             "CAL_WEIGHTED_MEAN_GEH_COUNTS_ONLY; IDP_DEFERRED_TO_IMMEDIATE_TD_SUBSTEP",
             "V2493_GENERATION_OBJECTIVE_LABEL_CHANGED")

    compat = cfg.get("performance", {}).get("persistent_path_cache", {}).get(
        "explicit_predecessor_read_compatibility", {})
    _require(compat.get("target_release") == RELEASE,
             "V2493_CACHE_COMPAT_TARGET_CHANGED")
    rows = [r for r in compat.get("predecessors", [])
            if r.get("source_release") == V2492_RELEASE]
    _require(len(rows) == 1 and rows[0].get("source_config_sha256s") == [V2492_CONFIG_SHA256],
             "V2493_V2492_CONFIG_PROVENANCE_NOT_PINNED")
    _require(rows[0].get("source_path_implementation_files") == V2492_PATH_IMPLEMENTATION_FILES,
             "V2493_V2492_PATH_IMPLEMENTATION_NOT_PINNED")

    impl = cfg.get("implementation_files", {}) or {}
    required = (
        "R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_9_3.py",
        "r1_15a2_safety_v2493.py", "r1_15a2_core.py", "r1_15a2_multiblock.py",
        "r1_15a2_com_compat.py", "r1_15a2_runtime_v1.py",
        "r1_15a2_inplace_transaction_v239.py", "r1_15a2_supply_visum.py",
        "R1_15A2_ACTUAL_PATH_MULTIBLOCK_CALIBRATION_MASTER_V2_1.py",
    )
    for name in required:
        digest = impl.get(name)
        _require(isinstance(digest, str) and len(digest) == 64,
                 "V2493_IMPLEMENTATION_HASH_MISSING:" + name)
        _require((root / name).is_file() and rt.sha256_file(root / name) == digest,
                 "V2493_IMPLEMENTATION_HASH_MISMATCH:" + name)

    return {
        "passes": True,
        "predecessor_contract": predecessor,
        "csd_calibration_objective": "WEIGHTED_MEAN_GEH",
        "profile_sum_role": "DIAGNOSTIC_ONLY_PROFILE_PASSAGE_CHECKSUM",
        "long_acceptance_mode": "GLOBAL_LONG_COMPOSITE",
        "com_retry_scope": "TRANSIENT_ONLY",
        "zone_identity_cache": True,
        "fresh_visum_acceptance_retained": True,
        "real_visum_tested": False,
        "production_ready": False,
    }


__all__ = [
    "RELEASE", "V2492_RELEASE", "V2492_CONFIG_SHA256",
    "V2492_PATH_IMPLEMENTATION_FILES", "validate_v2493_config",
]

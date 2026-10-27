#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def require(cond, code):
    if not cond:
        raise RuntimeError(code)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    from r1_15a2_safety_v24912 import preflight_v24912_deployment_files
    deployment_preflight = preflight_v24912_deployment_files(ROOT)
    cfg_path = ROOT / "R1_15A2_CONFIG_V2_4_9_12.json"
    parent_cfg = ROOT / "R1_15A2_CONFIG_V2_4_9_6.json"
    contract_path = ROOT / "V24912_GUARD_POLICY_CONTRACT.json"
    audit_path = ROOT / "V24912_GUARD_AUDIT_AND_COUNTERFACTUAL_REPLAY.json"
    for p in (cfg_path, parent_cfg, contract_path, audit_path,
              ROOT / "r1_15a2_guard_policy_v24912.py",
              ROOT / "r1_15a2_safety_v24912.py",
              ROOT / "r1_15a2_core.py",
              ROOT / "R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_9_12.py"):
        require(p.is_file(), "V24912_REQUIRED_FILE_MISSING:" + p.name)

    require(sha(parent_cfg) == "8f72699a375fe10458f12c508492e70bf5b3fc85f6cb5b88bfb494ce9d14dc23",
            "V24912_PARENT_CONFIG_BYTES_CHANGED")

    launcher_path = ROOT / "R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_9_12.py"
    spec = importlib.util.spec_from_file_location("verify_v24912_launcher", launcher_path)
    launcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launcher)
    cfg = launcher.load_config()

    from r1_15a2_safety_v24912 import validate_v24912_config, validate_v24912_runtime_bundle
    safety = validate_v24912_config(cfg, ROOT)
    runtime_bundle = validate_v24912_runtime_bundle(cfg, ROOT)
    require(safety.get("passes") is True, "V24912_SAFETY_VALIDATOR_FAILED")
    require(runtime_bundle.get("passes") is True, "V24912_RUNTIME_BUNDLE_PREFLIGHT_FAILED")
    require(runtime_bundle.get("late_policy_import_required") is False,
            "V24912_LATE_POLICY_IMPORT_STILL_REQUIRED")
    require(safety.get("real_visum_tested") is False and safety.get("production_ready") is False,
            "V24912_STATUS_OVERCLAIM")

    require(cfg.get("guard_contract_sha256") == sha(contract_path), "V24912_CONTRACT_CONFIG_HASH_MISMATCH")
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    require(contract.get("policy_level") == "BASELINE_RELATIVE_BUDGET_V24912", "V24912_CONTRACT_POLICY_LEVEL_BAD")
    require(contract.get("real_visum_tested") is False and contract.get("production_ready") is False,
            "V24912_CONTRACT_STATUS_OVERCLAIM")

    core_text = (ROOT / "r1_15a2_core.py").read_text(encoding="utf-8")
    require("return rebase_severity_guard_v24912(result, sev, early[\"scoped\"])" in core_text,
            "V24912_POLICY_NOT_INTEGRATED_IN_CORE")
    launch_text = launcher_path.read_text(encoding="utf-8")
    require("R1_15A2_CONFIG_V2_4_9_12.json" in launch_text and "validate_v24912_config" in launch_text,
            "V24912_LAUNCHER_NOT_WIRED")
    require("R1_15A2_V24912_RUNS" in launch_text, "V24912_RUN_ROOT_NOT_WIRED")

    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    assertions = audit.get("assertions", {})
    expected_true = [
        "generation_1_0_accept", "generation_0_5_reject", "generation_0_25_accept",
        "td_0_5_reject", "td_0_25_accept", "td_0_125_accept", "td_0_0625_accept",
    ]
    for key in expected_true:
        require(assertions.get(key) is True, "V24912_REPLAY_ASSERTION_FAILED:" + key)
    require(audit.get("real_visum_tested") is False and audit.get("production_ready") is False,
            "V24912_AUDIT_STATUS_OVERCLAIM")

    print(json.dumps({
        "status": "PASS",
        "release": cfg["release"],
        "config_sha256": sha(cfg_path),
        "contract_sha256": sha(contract_path),
        "parent_config_sha256": sha(parent_cfg),
        "package_revision": cfg.get("package_revision"),
        "deployment_files_checked": deployment_preflight.get("files_checked"),
        "runtime_bundle_files_checked": runtime_bundle.get("files_checked"),
        "late_policy_import_required": runtime_bundle.get("late_policy_import_required"),
        "implementation_file_count": len(cfg.get("implementation_files", {})),
        "counterfactual_replay_assertions": {k: assertions[k] for k in expected_true},
        "real_visum_tested": False,
        "production_ready": False,
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

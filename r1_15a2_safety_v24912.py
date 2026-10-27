# -*- coding: utf-8 -*-
"""Fail-closed V2.4.9.12 guard-policy rebase safety contract."""
from __future__ import annotations
import copy, json, sys
from pathlib import Path
from typing import Any, Mapping
from r1_15a2_supply import SupplyContractError
import r1_15a2_runtime_v1 as rt
import r1_15a2_core as core
from r1_15a2_restart_v2494 import SCHEMA as RESTART_SCHEMA, SEMANTIC_FIELDS, RAW_VER_SHA_ROLE

RELEASE = "R1_15A2_V2_4_9_12_GUARD_POLICY_REBASE_20261018"
PARENT_RELEASE = "R1_15A2_V2_4_9_6_EARLY_EXPLORATION_PARETO_ACCEPTANCE_20261018"
PARENT_CONFIG_SHA256 = "8f72699a375fe10458f12c508492e70bf5b3fc85f6cb5b88bfb494ce9d14dc23"
CONTRACT_FILE = "V24912_GUARD_POLICY_CONTRACT.json"
CONTRACT_SHA256 = "bd5c3353d35aeed634eb93123d3aa75d3f1072092b3eb253b639953a87c3032d"
RUNTIME_MANIFEST_FILE = "V24912_RUNTIME_BUNDLE_MANIFEST.json"
RUNTIME_MANIFEST_SHA256 = "40750767d99fa29a776a122c1c3c0fb4875f758962384e03ef1af6594f299556"
PACKAGE_REVISION = "V24912_COMPLETE_R2"

def _require(condition: bool, code: str) -> None:
    if not condition:
        raise SupplyContractError(code)

def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

def _parent(root: Path) -> Mapping[str, Any]:
    p=root / "R1_15A2_CONFIG_V2_4_9_6.json"
    _require(p.is_file(), "V24912_BUNDLED_V2496_CONFIG_MISSING")
    _require(rt.sha256_file(p)==PARENT_CONFIG_SHA256, "V24912_BUNDLED_V2496_CONFIG_HASH_MISMATCH")
    obj=rt.read_json(p)
    _require(obj.get("release")==PARENT_RELEASE, "V24912_PARENT_RELEASE_MISMATCH")
    return obj

def _validate_reviewed_delta(cfg: Mapping[str, Any], root: Path) -> None:
    baseline=copy.deepcopy(dict(_parent(root)))
    candidate=copy.deepcopy(dict(cfg))
    allowed={"version","release","safety_gate_release","methodology","implementation_files","early_exploration_acceptance","package_revision","runtime_bundle_manifest","runtime_bundle_manifest_sha256"}
    for key, old in baseline.items():
        if key in allowed:
            continue
        _require(key in candidate, "V24912_CONFIG_KEY_MISSING:"+key)
        new=candidate[key]
        if key=="performance":
            old=copy.deepcopy(old); new=copy.deepcopy(new)
            old.pop("release",None); new.pop("release",None)
            oc=old["persistent_path_cache"]["explicit_predecessor_read_compatibility"]
            nc=new["persistent_path_cache"]["explicit_predecessor_read_compatibility"]
            oc.pop("target_release",None); nc.pop("target_release",None)
            nc["predecessors"]=[r for r in nc.get("predecessors",[]) if r.get("source_release")!=PARENT_RELEASE]
        elif key=="trial_calibration":
            old=copy.deepcopy(old); new=copy.deepcopy(new); new.pop("v24912_guard_policy_rebase",None)
        _require(_canonical(new)==_canonical(old), "V24912_UNREVIEWED_CONFIG_DRIFT:"+key)


def preflight_v24912_deployment_files(package_root=None) -> Mapping[str, Any]:
    """Aggregate all manifest deployment defects before config/model work."""
    root = Path(package_root).resolve() if package_root is not None else Path(__file__).resolve().parent
    manifest_path = root / RUNTIME_MANIFEST_FILE
    _require(manifest_path.is_file(), "V24912_RUNTIME_MANIFEST_MISSING")
    _require(rt.sha256_file(manifest_path) == RUNTIME_MANIFEST_SHA256,
             "V24912_RUNTIME_MANIFEST_HASH_MISMATCH")
    manifest = rt.read_json(manifest_path)
    _require(manifest.get("schema") == "R1_15A2_V24912_RUNTIME_BUNDLE_MANIFEST_V1",
             "V24912_RUNTIME_MANIFEST_SCHEMA_MISMATCH")
    _require(manifest.get("release") == RELEASE, "V24912_RUNTIME_MANIFEST_RELEASE_MISMATCH")
    failures = []
    checked = 0
    for row in manifest.get("files", []):
        rel = str(row.get("path", ""))
        path = root / rel
        if not rel or not path.is_file():
            failures.append({"path": rel, "reason": "MISSING"})
            continue
        checked += 1
        size = int(path.stat().st_size)
        if size != int(row.get("size", -1)):
            failures.append({"path": rel, "reason": "SIZE_MISMATCH",
                             "expected": row.get("size"), "actual": size})
            continue
        digest = rt.sha256_file(path)
        if digest != row.get("sha256"):
            failures.append({"path": rel, "reason": "SHA256_MISMATCH",
                             "expected": row.get("sha256"), "actual": digest})
    _require(not failures, "V24912_RUNTIME_BUNDLE_INVALID:" + json.dumps(failures, sort_keys=True))
    return {
        "passes": True,
        "release": RELEASE,
        "package_revision": PACKAGE_REVISION,
        "manifest_path": str(manifest_path),
        "manifest_sha256": RUNTIME_MANIFEST_SHA256,
        "files_checked": checked,
        "failures": [],
    }


def validate_v24912_runtime_bundle(cfg: Mapping[str, Any], package_root=None) -> Mapping[str, Any]:
    """Verify the complete deployable runtime before any Visum model write.

    This is intentionally broader than the config contract.  It detects an
    incomplete extraction, stale mixed-release imports, missing helper/authority
    files and the exact late-import failure observed in the first live V24912
    run.
    """
    root = Path(package_root).resolve() if package_root is not None else Path(__file__).resolve().parent
    deployment = preflight_v24912_deployment_files(root)
    manifest_path = root / RUNTIME_MANIFEST_FILE
    checked = int(deployment["files_checked"])

    mixed = []
    for name, module in list(sys.modules.items()):
        if not name.startswith("r1_15a2_") or module is None:
            continue
        filename = getattr(module, "__file__", None)
        if filename and Path(filename).resolve().parent != root:
            mixed.append({"module": name, "file": str(Path(filename).resolve())})
    _require(not mixed, "V24912_MIXED_RELEASE_MODULES:" + json.dumps(mixed, sort_keys=True))

    _require(core.rebase_severity_guard_v24912.__module__ == "r1_15a2_core",
             "V24912_POLICY_NOT_EMBEDDED_IN_CORE")
    core_text = (root / "r1_15a2_core.py").read_text(encoding="utf-8")
    _require("from r1_15a2_guard_policy_v24912 import" not in core_text,
             "V24912_LATE_POLICY_IMPORT_STILL_ACTIVE")

    # Reproduce the live failure boundary: once core is loaded, remove the
    # release directory from sys.path and the compatibility facade from the
    # module cache.  The acceptance call must still succeed because policy
    # execution is embedded in core.
    saved_path = list(sys.path)
    saved_facade = sys.modules.pop("r1_15a2_guard_policy_v24912", None)
    try:
        sys.path[:] = [x for x in sys.path if Path(x or ".").resolve() != root]
        smoke_cfg = copy.deepcopy(dict(cfg))
        smoke_cfg["runtime_acceptance_outer_cycle"] = 1
        smoke_cfg["runtime_acceptance_scope"] = "GENERATION"
        rows = [{
            "countlocation_no": "V24912_PREFLIGHT",
            "role": "CALIBRATION",
            "observed": 100.0,
            "model": 100.0,
            "profile_weight": 1.0,
        }]
        smoke = core.severity_transition_guard(rows, rows, smoke_cfg, "GENERATION")
    finally:
        sys.path[:] = saved_path
        if saved_facade is not None:
            sys.modules["r1_15a2_guard_policy_v24912"] = saved_facade
    _require(smoke.get("passes") is True, "V24912_EMBEDDED_POLICY_SMOKE_REJECTED")
    _require(smoke.get("mode") == "EARLY_EXPLORATION_BASELINE_RELATIVE_SEVERITY_V24912",
             "V24912_EMBEDDED_POLICY_SMOKE_WRONG_MODE")
    _require(smoke.get("v24912_policy", {}).get("runtime_external_policy_import_required") is False,
             "V24912_POLICY_STILL_REQUIRES_RUNTIME_EXTERNAL_IMPORT")

    return {
        "passes": True,
        "release": RELEASE,
        "package_revision": PACKAGE_REVISION,
        "manifest_path": str(manifest_path),
        "manifest_sha256": RUNTIME_MANIFEST_SHA256,
        "files_checked": checked,
        "mixed_release_modules": [],
        "policy_implementation_owner": "r1_15a2_core.py",
        "late_policy_import_required": False,
        "live_failure_signature_reproduced_and_closed":
            "NO_MODULE_NAMED_R1_15A2_GUARD_POLICY_V24912",
    }

def validate_v24912_config(cfg: Mapping[str, Any], package_root=None) -> Mapping[str, Any]:
    root=Path(package_root).resolve() if package_root is not None else Path(__file__).resolve().parent
    _validate_reviewed_delta(cfg,root)
    _require(cfg.get("release")==RELEASE and cfg.get("safety_gate_release")==RELEASE, "V24912_RELEASE_IDENTITY_MISSING")
    _require(cfg.get("version")=="2.4.9.12-guard-policy-rebase-baseline-relative", "V24912_VERSION_IDENTITY_MISSING")
    _require(cfg.get("package_revision")==PACKAGE_REVISION, "V24912_PACKAGE_REVISION_MISSING")
    _require(cfg.get("runtime_bundle_manifest")==RUNTIME_MANIFEST_FILE and
             cfg.get("runtime_bundle_manifest_sha256")==RUNTIME_MANIFEST_SHA256,
             "V24912_RUNTIME_MANIFEST_NOT_PINNED")
    e=cfg.get("early_exploration_acceptance",{}) or {}; g=e.get("generation",{}) or {}; t=e.get("td",{}) or {}; s=e.get("severity",{}) or {}
    _require(e.get("enabled") is True and int(e.get("through_outer_cycle",0))==12, "V24912_EXPLORATION_HORIZON_CHANGED")
    _require(str(s.get("policy_level","")).upper()=="BASELINE_RELATIVE_BUDGET_V24912", "V24912_POLICY_LEVEL_CHANGED")
    _require(float(g.get("max_severity20_relative_degradation",-1))==0.08 and float(g.get("max_severity30_relative_degradation",-1))==0.10 and int(g.get("max_geh40_net_count_increase",-1))==5, "V24912_GENERATION_SEVERITY_BUDGET_CHANGED")
    _require(float(t.get("max_severity20_relative_degradation",-1))==0.25 and float(t.get("max_severity30_relative_degradation",-1))==0.30 and int(t.get("max_geh40_net_count_increase",-1))==15, "V24912_TD_SEVERITY_BUDGET_CHANGED")
    _require(float(t.get("min_selected_relative_improvement",-1))==0.0025 and float(t.get("max_cal_relative_degradation",-1))==0.05 and float(t.get("min_benefit_cost_ratio",-1))==1.5, "V24912_TD_PARETO_CHANGED")
    _require(float(t.get("max_selected_component_relative_degradation",-1))==0.20 and float(t.get("max_nonselected_component_relative_degradation",-1))==0.20, "V24912_TD_COMPONENT_BUDGET_CHANGED")
    _require(float(s.get("max_single_profile_geh_increase",-1))==15.0 and float(s.get("high_geh_threshold",-1))==60.0 and float(s.get("max_high_geh_increase",-1))==10.0, "V24912_CATASTROPHIC_DELTA_GUARD_CHANGED")
    _require(float(s.get("protected_before_geh",-1))==5.0 and float(s.get("protected_after_hard_geh",-1))==20.0 and int(s.get("max_protected_catastrophic",-1))==0, "V24912_PROTECTED_PROFILE_GUARD_CHANGED")
    _require(e.get("fallback_after_early_cycles")=="V2495_FALLBACK_ONLY_OUTSIDE_COUPLED_DEMAND_HORIZON_AFTER_CYCLE_12", "V24912_LATE_POLICY_CHANGED")
    # Existing technical/method authorities remain exact.
    _require(cfg.get("coupled_demand",{}).get("max_outer_cycles")==12, "V24912_COUPLED_DEMAND_HORIZON_CHANGED")
    _require(cfg.get("csd_calibration_objective",{}).get("metric")=="WEIGHTED_MEAN_GEH", "V24912_CSD_OBJECTIVE_CHANGED")
    _require(str(cfg.get("guidance_mode","")).upper()=="SIGNED" and cfg.get("allow_signed_apply") is True, "V24912_SIGNED_GENERATION_CONTRACT_LOST")
    _require(cfg.get("coupled_demand",{}).get("finecdf_td",{}).get("ipf_tolerance_policy")=="UNCHANGED_NEVER_RELAXED_BY_CALIBRATOR", "V24912_IPF_TOLERANCE_CONTRACT_LOST")
    restart=cfg.get("restart_authority",{}) or {}
    _require(restart.get("mode")=="SEMANTIC_MODEL_STATE" and restart.get("schema")==RESTART_SCHEMA and restart.get("semantic_fields")==list(SEMANTIC_FIELDS) and restart.get("raw_ver_sha_role")==RAW_VER_SHA_ROLE and restart.get("raw_ver_sha_used_for_restart_acceptance") is False, "V24912_SEMANTIC_RESTART_CONTRACT_LOST")
    contract=root/CONTRACT_FILE
    _require(contract.is_file() and rt.sha256_file(contract)==CONTRACT_SHA256, "V24912_GUARD_CONTRACT_HASH_MISMATCH")
    _require(cfg.get("guard_contract_file")==CONTRACT_FILE and cfg.get("guard_contract_sha256")==CONTRACT_SHA256, "V24912_GUARD_CONTRACT_NOT_PINNED")
    compat=cfg.get("performance",{}).get("persistent_path_cache",{}).get("explicit_predecessor_read_compatibility",{})
    _require(compat.get("target_release")==RELEASE, "V24912_CACHE_COMPAT_TARGET_CHANGED")
    rows=[r for r in compat.get("predecessors",[]) if r.get("source_release")==PARENT_RELEASE]
    _require(len(rows)==1 and rows[0].get("source_config_sha256s")==[PARENT_CONFIG_SHA256], "V24912_V2496_PROVENANCE_NOT_PINNED")
    impl=cfg.get("implementation_files",{}) or {}
    required=("R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_9_12.py","r1_15a2_safety_v24912.py","r1_15a2_guard_policy_v24912.py","r1_15a2_core.py","R1_15A2_ACTUAL_PATH_MULTIBLOCK_CALIBRATION_MASTER_V2_1.py","r1_15a2_overnight_controller_v242.py","r1_15a2_supply_visum.py","r1_15a2_runtime_v1.py")
    for name in required:
        digest=impl.get(name)
        _require(isinstance(digest,str) and len(digest)==64, "V24912_IMPLEMENTATION_HASH_MISSING:"+name)
        _require((root/name).is_file() and rt.sha256_file(root/name)==digest, "V24912_IMPLEMENTATION_HASH_MISMATCH:"+name)
    return {"passes":True,"parent_release":PARENT_RELEASE,"policy_level":"BASELINE_RELATIVE_BUDGET_V24912","early_exploration_through_outer_cycle":12,"generation_severity20_budget":0.08,"generation_severity30_budget":0.10,"generation_geh40_net_budget":5,"td_severity20_budget":0.25,"td_severity30_budget":0.30,"td_geh40_net_budget":15,"high_geh_delta_guard":10.0,"real_visum_tested":False,"production_ready":False}

__all__=["RELEASE","PARENT_RELEASE","PARENT_CONFIG_SHA256","CONTRACT_FILE","CONTRACT_SHA256","RUNTIME_MANIFEST_FILE","RUNTIME_MANIFEST_SHA256","PACKAGE_REVISION","preflight_v24912_deployment_files","validate_v24912_config","validate_v24912_runtime_bundle"]

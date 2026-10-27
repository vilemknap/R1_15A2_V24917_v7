# -*- coding: utf-8 -*-
"""ONE-CLICK fresh-cycle-1 V24916 calibration isolated from a parallel V24915 run.

Operational contract:
- current opened .ver is the new baseline (accepted_count=0, outer_cycle=1),
- PROFILE488 authority is used,
- V24916 Generation FlowBundle targeting + TD component mask are active,
- persistent path cache is hard-disabled: no restore, import, publication, or read,
- fresh path geometry is enumerated from live Visum and kept only as the current
  run's path basis; no V248 persistent store is consumed or published,
- project lock and run tree use short V24916-specific names so a separate
  Visum process running V24915 does not collide with this release;
- IOFIX3/PATHFIX3 uses short opaque temp names and extended-length Windows I/O;
- transient COM-busy snapshot reads use bounded retry;
- the active native TD operation may contain approved 16 or historical 17 strata.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import sys
import traceback
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
_INJECTED_VISUM = globals().get("Visum")
_INJECTED_COM = globals().get("COM")
_ORIGINAL_SYS_PATH = list(sys.path)

if _INJECTED_VISUM is not None and getattr(sys, "_r1_15a2_calibration_busy", False):
    raise RuntimeError("ANOTHER_15A2_RUN_IS_ACTIVE_IN_THIS_VISUM_PROCESS")
for _name in list(sys.modules):
    # A fresh launcher must not mix API contracts from a previous R1_15A2 run
    # in the same Visum Python host.  Purge both lower-case helper modules and
    # upper-case entrypoint/runtime modules before importing this package.
    if _name.startswith("r1_15a2_") or _name.startswith("R1_15A2_"):
        sys.modules.pop(_name, None)
sys.path[:] = [str(HERE)] + [p for p in sys.path if p != str(HERE)]

import r1_15a2_com_compat as com
parent = importlib.import_module("r1_15a2_fresh0_shortroot_parent_v24916")
# Freeze the unpatched parent layout resolver.  _install_runtime() later replaces
# parent._stable_project_layout with the isolated V24916 resolver; calling the
# mutable module attribute from _base_layout would recurse indefinitely.
_ORIGINAL_PARENT_STABLE_PROJECT_LAYOUT = parent._stable_project_layout
import r1_15a2_overnight_controller_coupled_v24915p2_force100 as force100
import r1_15a2_perf_telemetry_failopen_hotfix_profile488 as telemetry_failopen
import r1_15a2_runtime_io_hotfix_profile488 as runtime_io_hotfix
import r1_15a2_com_busy_snapshot_hotfix_v24916 as combusy_hotfix
import r1_15a2_td09c_16or17_hotfix_v24916 as td09c_hotfix
from r1_15a2_active_controller_patch_v24916p2c import install as install_controller_patch
from r1_15a2_fresh_baseline_live_preflight_v24916p2c import build_live_authority
from r1_15a2_runtime_manifest_v24916p2c import verify_runtime_manifest
from r1_15a2_trial_adapter_v24916p2c_active import VisumAdapter as ActiveVisumAdapter
from r1_15a2_profile488_gatefix_v24916p2c import (
    AUTHORITY_FILE,
    SOURCE_SEMANTIC_POLICY,
    PRIVATE_CACHE_DIRNAME,
    RELEASE,
    WORKSPACE_NAME, RUNS_ROOT_NAME, LOCK_NAME,
    apply_active_runtime_delta,
    validate_active_runtime_delta,
    activate_runtime_gate_overlay,
)

BOOTSTRAP_SCHEMA = "R1_15A2_V24916_FRESH0_ISOLATED_BOOTSTRAP_V2"
BOOTSTRAPFIX_REVISION = "BOOTSTRAPFIX2_FASTCAL1_PROFILE488FIX1_COMBUSY_TD09C16_20261023"
BOOTSTRAP_FILE = "LATEST_BOOTSTRAP.json"
BOOTSTRAP_FAILURE_FILE = "BOOTSTRAP_FAILED.json"
PACKAGE_LOCATOR_FILE = "V24916_LAST_RUNS_LOCATION.txt"
PACKAGE_FAILURE_FILE = "V24916_LAST_BOOTSTRAP_FAILURE.json"
_ACTIVE_HOTFIX_STATUS = {}




def _best_effort_package_text(name: str, text_value: str) -> None:
    """Write a discoverable package-local breadcrumb without masking startup."""
    try:
        (HERE / name).write_text(str(text_value), encoding="utf-8")
    except BaseException:
        pass


def _best_effort_package_json(name: str, payload) -> None:
    try:
        (HERE / name).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False, default=str),
            encoding="utf-8")
    except BaseException:
        pass


def _write_runs_locator(source_ver: Path, workspace: Path, stage: str) -> None:
    _best_effort_package_text(
        PACKAGE_LOCATOR_FILE,
        "\n".join([
            "R1 15A2 V24916 FRESH0 runtime location",
            "stage=" + str(stage),
            "source_ver=" + str(source_ver),
            "runs_root=" + str(workspace),
            "note=R1_15A2_V16_RUNS is created next to the opened .ver/project base, not necessarily inside this package folder.",
            "",
        ]))

def _install_com_retry_budget_compat():
    """Normalize historical 4-item COM retry budgets to the current 5-item API.

    This is an additive launcher overlay only.  The sealed parent helper stays
    byte-identical, so PERF1/PERF2 runtime-manifest authority is preserved.
    """
    provider = getattr(com, "_retry_budget", None)
    if provider is None:
        raise RuntimeError("COM_RETRY_BUDGET_PROVIDER_MISSING")
    if getattr(provider, "_v24916_4to5_compat", False):
        probe = tuple(provider({"enabled": False}))
        if len(probe) != 5:
            raise RuntimeError("COM_RETRY_BUDGET_COMPAT_PROBE_FAILED")
        return {"status": "ALREADY_ACTIVE", "probe_length": len(probe)}

    def compatible(policy):
        raw = tuple(provider(policy))
        if len(raw) == 5:
            return raw
        if len(raw) == 4:
            return raw + (None,)
        raise RuntimeError(
            "COM_RETRY_BUDGET_CONTRACT_MISMATCH:expected=4_or_5 got=%d" % len(raw))

    compatible._v24916_4to5_compat = True
    compatible._v24916_original_provider = provider
    com._retry_budget = compatible
    probe = tuple(com._retry_budget({"enabled": False}))
    if len(probe) != 5:
        raise RuntimeError("COM_RETRY_BUDGET_COMPAT_PROBE_FAILED")
    return {
        "status": "ACTIVE",
        "legacy_four_item_supported": True,
        "current_five_item_supported": True,
        "probe_length": len(probe),
        "sealed_parent_file_modified_on_disk": False,
    }


def _hash(value):
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False, default=str).encode("utf-8")).hexdigest()


def _atomic_json(path: Path, payload):
    return runtime_io_hotfix.critical_atomic_json(path, payload)


def _base_layout(source_ver: Path):
    """Resolve the parent project layout through the frozen pre-patch resolver.

    Do not dereference parent._stable_project_layout here: _install_runtime()
    intentionally replaces that module attribute with _isolated_project_layout.
    Using the mutable attribute creates an infinite wrapper cycle.
    """
    return _ORIGINAL_PARENT_STABLE_PROJECT_LAYOUT(source_ver)


def _isolated_workspace(source_ver: Path) -> tuple[dict, Path]:
    original = _base_layout(source_ver)
    base = Path(original["project_base"]).resolve()
    runs_root = (base / RUNS_ROOT_NAME).resolve()
    runtime_io_hotfix._ensure_parent(runs_root / "LATEST_BOOTSTRAP.json")
    return original, runs_root


def _isolated_project_layout(source_ver):
    source_ver = Path(source_ver).resolve()
    original, runs_root = _isolated_workspace(source_ver)
    return {
        "source_version": source_ver,
        "project_base": Path(original["project_base"]).resolve(),
        "mode": "V24916_FRESH0_SHORTROOT_PARALLEL_ISOLATION_PATHFIX3",
        "detected_run_roots_nearest_first": list(original.get("detected_run_roots_nearest_first", [])),
        "outermost_run_root": original.get("outermost_run_root"),
        "original_project_base": str(original["project_base"]),
        "original_project_base_mode": original["mode"],
        "parallel_isolation_workspace": str(runs_root),
        "runs_root_name": RUNS_ROOT_NAME,
        "lock_name": LOCK_NAME,
    }


def _isolated_fresh_run_cache_root(run_folder, project_base):
    """Return a run-local sentinel path while persistent caching is disabled.

    The parent launcher records a cache-root field unconditionally.  Keeping that
    field inside the isolated RUN_* proves it cannot point at V24915/LOCALAPPDATA.
    PersistentPathCacheManager remains disabled, so this directory is never
    created, read, restored, imported, or published.
    """
    run_folder = Path(run_folder).resolve()
    project_base = Path(project_base).resolve()
    if run_folder.parent.name != RUNS_ROOT_NAME or run_folder.parent.parent != project_base:
        raise RuntimeError(
            "V24916_ISOLATED_PROJECT_BASE_MISMATCH:"
            + str(project_base) + "__RUN:" + str(run_folder)
        )
    root = run_folder / PRIVATE_CACHE_DIRNAME
    if root.exists():
        raise RuntimeError("V24916_DISABLED_CACHE_SENTINEL_MUST_START_ABSENT:" + str(root))
    return root


def _write_bootstrap(path: Path, **payload):
    row = {
        "schema": BOOTSTRAP_SCHEMA,
        "release": RELEASE,
        "bootstrapfix_revision": BOOTSTRAPFIX_REVISION,
        "updated_at": datetime.now().astimezone().isoformat(),
    }
    row.update(payload)
    _atomic_json(path, row)
    return row


def _run_live_preflight(visum, workspace: Path, combusy_status=None, td09c_status=None):
    combusy_status = combusy_status or _ACTIVE_HOTFIX_STATUS.get("combusy")
    td09c_status = td09c_status or _ACTIVE_HOTFIX_STATUS.get("td09c")
    deployment = dict(parent.preflight_v24915p2_deployment_files(HERE))
    deployment["perf2c_overlay"] = dict(parent.preflight_v24915p2c_overlay(HERE))
    deployment["fresh100_profile488_savefix1_parent"] = True

    base_cfg = parent.load_config("FULL")
    parent_runtime = parent._fresh100_runtime_preflight(base_cfg, HERE)
    parent._bind_current_profile_authority(base_cfg)
    active_cfg = apply_active_runtime_delta(base_cfg)
    delta = validate_active_runtime_delta(active_cfg, base_cfg)

    manifest = verify_runtime_manifest(HERE)
    if not manifest.get("passes"):
        raise RuntimeError("V24916_FRESH0_ISOLATED_RUNTIME_MANIFEST_FAIL")

    td09c_source_preflight = td09c_hotfix.read_only_source_preflight(visum)

    # build_live_authority internally disables persistent path cache for this
    # read-only preflight, so no cache root is needed or touched here.
    report = build_live_authority(visum, base_cfg, HERE)
    got_semantic = report.get("source_semantic_state_hash")
    if not isinstance(got_semantic, str) or len(got_semantic) != 64:
        raise RuntimeError("V24916_FRESH0_SOURCE_SEMANTIC_CAPTURE_FAILED:" + str(got_semantic))
    # Universal fresh-start policy: the currently opened .ver becomes the new
    # baseline.  Its semantic hash is captured as provenance and is then used
    # only to prove that the model does not change between preflight and the
    # calibration handoff.  It is NOT compared with a package-baked hash.
    report["source_baseline_policy"] = {
        "policy": SOURCE_SEMANTIC_POLICY,
        "fixed_semantic_hash_required": False,
        "captured_semantic_state_hash": got_semantic,
        "current_open_ver_is_baseline": True,
        "structural_preflight_required": True,
    }
    report["release"] = RELEASE
    report["integrated_hotfixes"] = {
        "com_busy_snapshot_retry": combusy_status or combusy_hotfix.policy_payload(),
        "td09c_runtime_patch": td09c_status or td09c_hotfix.policy_payload(),
        "td09c_source_preflight": td09c_source_preflight,
        "iofix4_import_decision": "CURRENT_V24916_IOFIX3_PATHFIX3_IS_STRICT_SUPERSET_NO_DOWNGRADE",
    }
    report["activation_stage"] = "FRESH0_ISOLATED_ACTIVE_GENERATION_AND_TD_TARGETING"
    report["parallel_isolation"] = {
        "workspace": str(workspace),
        "shared_v24915_lock": False,
        "shared_v24915_runs_root": False,
        "external_cache_read_allowed": False,
        "cross_run_cache_restore_allowed": False,
        "legacy_cache_roots": [],
        "persistent_path_cache_enabled": False,
        "persistent_path_cache_reads_allowed": False,
        "persistent_path_cache_writes_allowed": False,
        "private_cache_location": "DISABLED",
        "within_run_path_basis_reuse_allowed": True,
    }
    report["package_gates"] = {
        "parent_deployment_passes": bool(deployment.get("passes", True)),
        "parent_fresh100_runtime_passes": bool(parent_runtime.get("passes", True)),
        "v24916_runtime_manifest_passes": True,
        "active_config_delta": delta,
        "com_busy_snapshot_retry_active": bool((combusy_status or {}).get("active", True)),
        "td09c_16_or_17_compat_active": bool((td09c_status or {}).get("active", True)),
        "td09c_source_preflight_passes": td09c_source_preflight.get("status") == "PASS",
    }
    report.pop("authority_hash", None)
    report["authority_hash"] = _hash(report)
    _atomic_json(workspace / AUTHORITY_FILE, report)
    return report, manifest


def _install_runtime(visum, authority, manifest, workspace):
    base_load_config = parent.load_config
    base_runtime_preflight = parent._fresh100_runtime_preflight
    base_project_layout = parent._stable_project_layout
    base_cache_root = parent._fresh_run_cache_root

    base_cfg = base_load_config("FULL")
    parent._bind_current_profile_authority(base_cfg)
    cfg = apply_active_runtime_delta(base_cfg)
    cfg["runtime_v24916_live_authority_path"] = str(Path(workspace) / AUTHORITY_FILE)
    validate_active_runtime_delta({k: v for k, v in cfg.items() if k != "runtime_v24916_live_authority_path"}, base_cfg)

    def active_load_config(execution_mode="FULL"):
        p = base_load_config(execution_mode)
        child = apply_active_runtime_delta(p)
        child["runtime_v24916_live_authority_path"] = str(Path(workspace) / AUTHORITY_FILE)
        validate_active_runtime_delta({k: v for k, v in child.items() if k != "runtime_v24916_live_authority_path"}, p)
        return child

    def active_parent_runtime_preflight(runtime_cfg, package_root=None):
        p = base_load_config("FULL")
        result = dict(base_runtime_preflight(p, package_root or HERE))
        cfg_for_validation = {k: v for k, v in runtime_cfg.items() if k != "runtime_v24916_live_authority_path"}
        result["v24916_active_targeting_config_delta"] = validate_active_runtime_delta(cfg_for_validation, p)
        result["v24916_runtime_manifest"] = manifest
        result["v24916_live_authority_hash"] = authority.get("authority_hash")
        result["v24916_live_authority_path"] = str(Path(workspace) / AUTHORITY_FILE)
        result["pathfix3_enabled"] = True
        result["runs_root_name"] = RUNS_ROOT_NAME
        result["lock_name"] = LOCK_NAME
        result["generation_flowbundle_targeting_enabled"] = True
        result["td_component_mask_enabled"] = True
        result["fresh_lineage_accepted_count_start"] = 0
        result["fresh_lineage_outer_cycle_start"] = 1
        result["parallel_isolation_enabled"] = True
        result["external_cache_read_allowed"] = False
        result["cross_run_cache_restore_allowed"] = False
        result["legacy_cache_import_allowed"] = False
        result["persistent_path_cache_enabled"] = False
        result["persistent_path_cache_reads_allowed"] = False
        result["persistent_path_cache_writes_allowed"] = False
        result["within_run_path_basis_reuse_allowed"] = True
        result["acceptance_authority_changed"] = False
        result["acceptance_thresholds_changed"] = True
        result["tg_search_envelope_changed"] = True
        result["td_realization_backtracking_changed"] = True
        return result

    patch = install_controller_patch(force100)
    telemetry_status = telemetry_failopen.activate()
    io_status = runtime_io_hotfix.activate()
    profile488_gate_status = activate_runtime_gate_overlay()
    combusy_status = combusy_hotfix.activate()
    td09c_status = td09c_hotfix.activate()

    parent.VisumAdapter = ActiveVisumAdapter
    parent.load_config = active_load_config
    parent._fresh100_runtime_preflight = active_parent_runtime_preflight
    parent._stable_project_layout = _isolated_project_layout
    parent._fresh_run_cache_root = _isolated_fresh_run_cache_root
    parent.RELEASE = RELEASE
    parent.Visum = visum
    if _INJECTED_COM is not None:
        parent.COM = _INJECTED_COM

    return {
        "controller_patch": patch,
        "telemetry_hotfix": telemetry_status,
        "critical_io_hotfix": io_status,
        "profile488_gatefix1": profile488_gate_status,
        "com_busy_snapshot_retry": combusy_status,
        "td09c_16_or_17_compat": td09c_status,
        "parent_project_layout_replaced": base_project_layout is not parent._stable_project_layout,
        "parent_cache_root_resolver_replaced": base_cache_root is not parent._fresh_run_cache_root,
    }


def main():
    bootstrap_path = None
    workspace = None
    source_ver = None
    stage = "BIND_INJECTED_VISUM"
    try:
        print("=== R1 15A2 V24916 FRESH0 ISOLATED ACTIVE TARGETING ===")
        print("Using currently opened version as new baseline.")
        visum, _ = com.bind_injected(globals())
        source_ver = Path(str(visum.IO.CurrentVersionFile)).resolve()
        if not source_ver.is_file():
            raise RuntimeError("CURRENT_VERSION_FILE_NOT_FOUND")

        # Allocate the isolated RUNS root before any runtime activation that may
        # import/patch a mixed live Visum module graph.  This guarantees that a
        # bootstrap failure always leaves a discoverable forensic record.
        stage = "ALLOCATE_ISOLATED_RUNS_ROOT"
        _, workspace = _isolated_workspace(source_ver)
        bootstrap_path = workspace / BOOTSTRAP_FILE
        _write_runs_locator(source_ver, workspace, stage)
        print("RUNS root: " + str(workspace))
        _write_bootstrap(
            bootstrap_path,
            status="BOOTSTRAP_STARTED",
            stage=stage,
            source_version=str(source_ver),
            isolated_workspace=str(workspace),
            accepted_count_start=0,
            outer_cycle_start=1,
            external_cache_read_allowed=False,
            cross_run_cache_restore_allowed=False,
            legacy_cache_roots=[],
            persistent_path_cache_enabled=False,
            persistent_path_cache_reads_allowed=False,
            persistent_path_cache_writes_allowed=False,
            path_basis_policy="FRESH_ENUMERATION_ONLY_NO_PERSISTENT_CACHE",
            source_baseline_policy=SOURCE_SEMANTIC_POLICY,
            fixed_semantic_hash_required=False,
            parallel_v24915_note="SAFE_ONLY_WHEN_V24915_RUNS_IN_A_SEPARATE_VISUM_PROCESS",
            runs_root_name=RUNS_ROOT_NAME,
            lock_name=LOCK_NAME,
        )

        stage = "INSTALL_COM_RETRY_4TO5_COMPAT"
        com_retry_compat = _install_com_retry_budget_compat()

        stage = "ACTIVATE_IOFIX3"
        early_io_status = runtime_io_hotfix.activate()

        stage = "ACTIVATE_TELEMETRY_FAILOPEN"
        early_telemetry_status = telemetry_failopen.activate()

        stage = "ACTIVATE_COMBUSY_SNAPSHOT_RETRY"
        combusy_status = combusy_hotfix.activate()

        stage = "ACTIVATE_TD09C_16OR17_COMPAT"
        td09c_status = td09c_hotfix.activate()
        _ACTIVE_HOTFIX_STATUS.clear()
        _ACTIVE_HOTFIX_STATUS.update({"combusy": combusy_status, "td09c": td09c_status})

        stage = "LIVE_READ_ONLY_PREFLIGHT"
        authority, manifest = _run_live_preflight(visum, workspace)
        _write_bootstrap(
            bootstrap_path,
            status="PREFLIGHT_PASS_STARTING_FRESH0_CALIBRATION",
            stage=stage,
            source_version=str(source_ver),
            isolated_workspace=str(workspace),
            semantic_state_hash=authority.get("source_semantic_state_hash"),
            source_baseline_policy=SOURCE_SEMANTIC_POLICY,
            fixed_semantic_hash_required=False,
            authority_hash=authority.get("authority_hash"),
            accepted_count_start=0,
            outer_cycle_start=1,
            active_actuators=[
                "GENERATION_FLOWBUNDLE_TARGETING",
                "TD_COMPONENT_MASK",
                "COMBUSY_SNAPSHOT_READ_RETRY",
                "TD09C_16_OR_17_NATIVE_SCOPE_COMPAT",
            ],
            external_cache_read_allowed=False,
            persistent_path_cache_enabled=False,
            persistent_path_cache_reads_allowed=False,
            persistent_path_cache_writes_allowed=False,
            com_retry_4to5_compat=com_retry_compat,
            pathfix3=early_io_status,
            telemetry_pathfix3=early_telemetry_status,
            com_busy_snapshot_retry=combusy_status,
            td09c_16_or_17_compat=td09c_status,
        )

        stage = "INSTALL_ACTIVE_RUNTIME"
        runtime_status = _install_runtime(visum, authority, manifest, workspace)
        _write_bootstrap(
            bootstrap_path,
            status="CALIBRATION_HANDOFF",
            stage=stage,
            source_version=str(source_ver),
            isolated_workspace=str(workspace),
            authority_hash=authority.get("authority_hash"),
            runtime_status=runtime_status,
            accepted_count_start=0,
            outer_cycle_start=1,
        )

        stage = "PARENT_MAIN_FULL"
        result = parent.main("FULL")
        _write_bootstrap(
            bootstrap_path,
            status="CALIBRATION_RETURNED",
            stage=stage,
            source_version=str(source_ver),
            isolated_workspace=str(workspace),
            result=result,
        )
        _write_runs_locator(source_ver, workspace, "CALIBRATION_RETURNED")
        return result
    except Exception as exc:
        tb = traceback.format_exc()
        failure = {
            "schema": BOOTSTRAP_SCHEMA,
            "release": RELEASE,
            "bootstrapfix_revision": BOOTSTRAPFIX_REVISION,
            "status": "FAILED",
            "stage": stage,
            "source_version": str(source_ver) if source_ver is not None else None,
            "isolated_workspace": str(workspace) if workspace is not None else None,
            "expected_runs_root_name": RUNS_ROOT_NAME,
            "package_root": str(HERE),
            "exception_type": type(exc).__name__,
            "exception": str(exc),
            "traceback": tb,
            "updated_at": datetime.now().astimezone().isoformat(),
        }
        if bootstrap_path is not None:
            try:
                _write_bootstrap(bootstrap_path, **failure)
                _atomic_json(Path(workspace) / BOOTSTRAP_FAILURE_FILE, failure)
            except Exception:
                pass
        _best_effort_package_json(PACKAGE_FAILURE_FILE, failure)
        if source_ver is not None and workspace is not None:
            _write_runs_locator(source_ver, workspace, "FAILED:" + stage)
        print("BOOTSTRAP ERROR [%s]: %s: %s" % (stage, type(exc).__name__, str(exc)))
        print(tb)
        raise
    finally:
        sys.path[:] = _ORIGINAL_SYS_PATH


if __name__ == "__main__" or _INJECTED_VISUM is not None or _INJECTED_COM is not None:
    main()

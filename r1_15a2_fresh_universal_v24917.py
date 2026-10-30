"""Independent fresh-cycle-1 launcher guard for the V24917 TD PERF release.

The opened, structurally compatible .ver is the NEW baseline: accepted_count=0.
No B0002/A0001 fixed checkpoint, no prior lineage, no old SQLite. The reviewed
native path exporter remains the only route authority. Output/lock/debug live in
a separate project sandbox so a running V16 calibration is not disturbed.
"""
from __future__ import annotations

import copy
import json
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
import traceback

RELEASE = "R1_V24917_FRESH_UNIVERSAL_TDPERF_ISOLATED_V1_20261030"
SANDBOX_NAME = "R1FRESH17"
RUNS_NAME = "R1_15A2_V16_RUNS"
SCHEMA = "R1_V24917_FRESH_UNIVERSAL_EPOCH_AUTHORITY_V1"


def require(ok, message):
    if not ok:
        raise RuntimeError("FRESH_UNIVERSAL_" + message)


def true_project_base(source):
    """Replicate the sealed outermost-runs normalization, without COM or import."""
    source = Path(source).resolve()
    require(source.suffix.lower() == ".ver" and source.is_file(),
            "OPEN_EXISTING_VER_FIRST")
    ancestors = []
    for folder in source.parents:
        if not (folder.name.upper().startswith("R1_15A2_")
                and folder.name.upper().endswith("_RUNS")):
            continue
        relative = source.relative_to(folder)
        if len(relative.parts) >= 2 and relative.parts[0].upper().startswith("RUN_"):
            ancestors.append(folder)
    return (ancestors[-1].parent if ancestors else source.parent).resolve()


def sandbox_for(source):
    source = Path(source).resolve()
    base = true_project_base(source)
    sandbox = base / SANDBOX_NAME
    require(sandbox not in source.parents and source != sandbox,
            "SOURCE_INSIDE_OUTPUT_SANDBOX")
    require(not sandbox.is_symlink(), "SYMLINKED_SANDBOX_FORBIDDEN")
    return sandbox


def path_is_under(path, parent):
    try:
        Path(path).resolve().relative_to(Path(parent).resolve())
        return True
    except ValueError:
        return False


def validate_fresh_config(cfg, options):
    """Check all fresh-run switches without changing a scientific parameter."""
    fresh = cfg.get("fresh100_overlay", {})
    require(fresh.get("source_ver_is_new_baseline") is True,
            "MISSING_FRESH_SOURCE_CONTRACT")
    require(fresh.get("start_outer_cycle") == 1
            and fresh.get("accepted_count_start") == 0
            and fresh.get("continuation_from_prior_run") is False,
            "INHERITED_LINEAGE_NOT_ALLOWED")
    require(fresh.get("fresh_path_enumeration_required") is True
            and fresh.get("cross_run_path_cache_restore") is False
            and fresh.get("legacy_path_cache_import") is False,
            "CROSS_RUN_CACHE_ENABLED")
    require(options.get("td_joint_enabled") is True, "TDJOINT_DISABLED")
    require(options.get("td_inner_mode") == "DYNAMIC", "DYNAMIC_TD_DISABLED")
    require(options.get("td_first_cycle") is True, "FIRST_CYCLE_TD_DISABLED")
    require(options.get("school_td_enabled") is True
            and options.get("long_composite_td_enabled") is True,
            "SCHOOL_OR_LONG_TD_DISABLED")
    return {"fresh_lineage": True, "accepted_count_start": 0,
            "outer_cycle_start": 1, "fresh_native_paths": True,
            "td_optimizations_required": True}


def verify_runtime_status(status):
    optimized = status.get("v24917", {})
    require(isinstance(optimized, dict), "OPTIMIZED_RUNTIME_MISSING")
    for name in ("tdjoint1", "td_numpy", "td_restore", "path_store_build"):
        item = optimized.get(name, {})
        require(isinstance(item, dict) and item.get("installed") is True,
                "OPTIMIZATION_NOT_INSTALLED:" + name)
    require("REVIEW1" in str(optimized["td_restore"].get("release", "")),
            "TD_RESTORE_SAFETY_REVIEW_MISSING")
    return {name: copy.deepcopy(optimized[name])
            for name in ("tdjoint1", "td_numpy", "td_restore", "path_store_build")}


def install_native_epoch_guard(adapter_type, sandbox):
    """Protect first and later fresh native enumeration; do not fake incidence."""
    sandbox = Path(sandbox).resolve()
    runs = sandbox / RUNS_NAME
    original = adapter_type._build_cache
    require(callable(original), "NATIVE_EPOCH_BUILDER_MISSING")
    require(not getattr(original, "_fresh_universal_wrapped", False),
            "EPOCH_WRAPPER_ALREADY_INSTALLED")

    def native_only(self, diag, folder, snapshot, *,
                    build_sequence_evidence=False, allow_persistent_restore=True):
        from r1_15a2_supply import SupplyContractError
        from r1_15a2_two_mode_v238 import atomic_json
        target = Path(folder).resolve()
        try:
            relative = target.relative_to(runs)
        except ValueError as exc:
            raise SupplyContractError(
                "FRESH_UNIVERSAL_EPOCH_OUTSIDE_OWN_RUN:" + str(target)) from exc
        if (len(relative.parts) < 4 or not relative.parts[0].startswith("RUN_")
                or relative.parts[1] != "CALIBRATION"):
            raise SupplyContractError("FRESH_UNIVERSAL_INVALID_EPOCH_FOLDER")
        persistent = getattr(self, "persistent_path_cache", None)
        if persistent is None or persistent.enabled is not False:
            raise SupplyContractError("FRESH_UNIVERSAL_PERSISTENT_CACHE_MUST_BE_DISABLED")
        if self.cfg.get("runtime_legacy_path_cache_roots", None) != []:
            raise SupplyContractError("FRESH_UNIVERSAL_LEGACY_CACHE_ROOTS_NONEMPTY")
        before = int(getattr(self, "path_epoch_index", -1))
        previous = getattr(self, "cache", None)
        if before == 0 and (previous is not None
                            or getattr(self, "path_epoch_history", None) != []):
            raise SupplyContractError("FRESH_UNIVERSAL_INITIAL_CACHE_NOT_EMPTY")
        if before < 0 or not isinstance(snapshot, dict) or not snapshot.get("state_hash"):
            raise SupplyContractError("FRESH_UNIVERSAL_MISSING_EPOCH_STATE")
        if previous is not None:
            db = getattr(previous, "route_db_path", None)
            if db is None or not path_is_under(db, runs):
                raise SupplyContractError("FRESH_UNIVERSAL_FOREIGN_PREVIOUS_SQLITE")
        marker = target / "FRESH_UNIVERSAL_NATIVE_EPOCH.json"
        event = {"schema": SCHEMA, "status": "STARTED",
                 "epoch_before": before, "source_state_hash": snapshot["state_hash"],
                 "destination": str(target), "cross_run_restore_allowed": False,
                 "legacy_cache_import_allowed": False,
                 "allow_persistent_restore_passed_to_native": False,
                 "original_builder": getattr(original, "__qualname__", str(original))}
        target.mkdir(parents=True, exist_ok=True)
        atomic_json(marker, event)
        try:
            collector, links, exported = original(
                self, diag, target, snapshot,
                build_sequence_evidence=build_sequence_evidence,
                allow_persistent_restore=False)
            db = getattr(collector, "route_db_path", None)
            if (db is None or not path_is_under(db, target) or not Path(db).is_file()
                    or getattr(collector, "read_only", False) is True
                    or int(getattr(self, "path_epoch_index", -1)) != before + 1
                    or getattr(self, "cache", None) is not collector
                    or not getattr(collector, "incidence_ready", False)
                    or getattr(self, "persistent_cache_manifest", None) is not None):
                raise SupplyContractError("FRESH_UNIVERSAL_NATIVE_EPOCH_PROOF_FAILED")
            event.update(status="FRESH_NATIVE_ENUMERATION_VERIFIED",
                         epoch_after=int(self.path_epoch_index),
                         sqlite=str(Path(db).resolve()),
                         route_basis_hash=collector.path_basis_hash(),
                         same_run_persistent_restore_used=False)
            atomic_json(marker, event)
            return collector, links, exported
        except BaseException as exc:
            event.update(status="FAILED", error_type=type(exc).__name__,
                         error=str(exc)[:1000])
            try:
                atomic_json(marker, event)
            except Exception:
                pass
            raise

    native_only._fresh_universal_wrapped = True
    adapter_type._build_cache = native_only
    return {"installed": True, "native_export_only": True,
            "output_root": str(runs), "source_sqlite_import_allowed": False}


def install(v16, source, sandbox, *, options):
    source = Path(source).resolve()
    sandbox = Path(sandbox).resolve()
    require(sandbox == sandbox_for(source), "SANDBOX_OR_SOURCE_MISMATCH")
    original_base = true_project_base(source)
    require(Path(v16._base_layout(source)["project_base"]).resolve() == original_base,
            "PARENT_PROJECT_BASE_MISMATCH")
    original_install = v16._install_runtime
    require(callable(original_install), "RUNTIME_INSTALLER_MISSING")
    require(v16.RUNS_ROOT_NAME == RUNS_NAME, "UNEXPECTED_RUNS_ROOT")
    require(not getattr(v16, "_fresh_universal_guard_installed", False),
            "ALREADY_INSTALLED")

    # The parent main uses the stable project_base to choose BOTH its hardcoded
    # RUNS root and its .R1_15A2_V16.lock. Redirect it to the new sandbox,
    # not by replacing OS calls, and never nest under an old RUN_*.
    def isolated_workspace(opened_source):
        require(Path(opened_source).resolve() == source, "SOURCE_CHANGED")
        baseline_layout = dict(v16._base_layout(source))
        require(Path(baseline_layout["project_base"]).resolve() == original_base,
                "SOURCE_LAYOUT_CHANGED")
        baseline_layout.update(project_base=sandbox,
                               mode="FRESH_UNIVERSAL_DETACHED_PROJECT_SANDBOX")
        sandbox.mkdir(parents=True, exist_ok=True)
        runs = sandbox / RUNS_NAME
        runs.mkdir(parents=True, exist_ok=True)
        return baseline_layout, runs

    def isolated_project_layout(opened_source):
        layout, runs = isolated_workspace(opened_source)
        return {"source_version": source, "project_base": sandbox,
                "mode": "FRESH_UNIVERSAL_DETACHED_PROJECT_SANDBOX",
                "detected_run_roots_nearest_first":
                    list(layout.get("detected_run_roots_nearest_first", [])),
                "outermost_run_root": layout.get("outermost_run_root"),
                "original_project_base": str(original_base),
                "original_project_base_mode": v16._base_layout(source)["mode"],
                "parallel_isolation_workspace": str(runs),
                "runs_root_name": RUNS_NAME, "lock_name": v16.LOCK_NAME}

    v16._isolated_workspace = isolated_workspace
    v16._isolated_project_layout = isolated_project_layout

    def verified_install(visum, authority, manifest, workspace):
        require(Path(workspace).resolve() == sandbox / RUNS_NAME,
                "INSTALL_IN_WRONG_WORKSPACE")
        status = dict(original_install(visum, authority, manifest, workspace))
        verified = verify_runtime_status(status)
        config = v16.parent.load_config("FULL")
        contract = validate_fresh_config(config, options)
        epoch = install_native_epoch_guard(v16.ActiveVisumAdapter, sandbox)
        status["fresh_universal"] = {"release": RELEASE, "sandbox": str(sandbox),
                                      "source_version": str(source),
                                      "optimizations": verified,
                                      "fresh_contract": contract, "path_epoch": epoch}
        from r1_15a2_two_mode_v238 import atomic_json
        atomic_json(Path(workspace) / "FRESH_UNIVERSAL_BOOTSTRAP_AUTHORITY.json",
                    status["fresh_universal"])
        return status

    v16._install_runtime = verified_install
    v16._fresh_universal_guard_installed = True
    return {"installed": True, "release": RELEASE,
            "source": str(source), "sandbox": str(sandbox),
            "new_accepted_count": 0, "next_outer_cycle": 1}


def run_silent_detached(host, package_root, main, sandbox, silent):
    """Use the existing bounded forensic ZIP builder, but under the NEW root.

    The standard run_silent requires the debug directory to be an ancestor of
    the source .ver. Here output is intentionally a sibling, so we redirect the
    same diagnostic primitives without weakening that original ancestor guard.
    """
    import time
    sandbox = Path(sandbox).resolve()
    require(sandbox == sandbox_for(host.IO.CurrentVersionFile),
            "SILENT_ROOT_NOT_ISOLATED")
    output = sandbox / silent.DEBUG_NAME
    output.mkdir(parents=True, exist_ok=True)
    runs = sandbox / RUNS_NAME
    old = ({p.name for p in runs.iterdir() if p.is_dir() and p.name.startswith("RUN_")}
           if runs.is_dir() else set())
    tag = silent._timestamp()
    log = output / ("SILENT_%s.log" % tag)
    returned, exception = None, None
    with log.open("w", encoding="utf-8", buffering=1) as handle:
        writer = silent._Autoflush(handle)
        with redirect_stdout(writer), redirect_stderr(writer):
            print("UNIVERSAL_FRESH_START", RELEASE, str(host.IO.CurrentVersionFile))
            try:
                returned = main()
            except BaseException as exc:
                exception = type(exc).__name__ + ":" + str(exc)
                print("UNIVERSAL_FRESH_EXCEPTION", exception)
                print(traceback.format_exc())
            print("UNIVERSAL_FRESH_END", tag)
    new_run = silent._find_new_run(runs, old) if runs.is_dir() else None
    if exception:
        state, origin = "FAILED_SILENT", "PYTHON_EXCEPTION"
    else:
        state, origin = silent._terminal_status(new_run, returned)
    report = {"schema": silent.SCHEMA, "status": state,
              "status_source": origin, "error": exception,
              "release": RELEASE, "source_version": str(host.IO.CurrentVersionFile),
              "sandbox": str(sandbox), "run_directory": str(new_run) if new_run else None,
              "python_log": str(log), "started_tag": tag,
              "model_changed_by_wrapper": False,
              "fresh_lineage": True, "separate_project_lock": True}
    silent._atomic_json(output / ("SILENT_%s_STATUS.json" % tag), report)
    archive = output / ("SILENT_%s_DEBUG.zip" % tag)
    try:
        report["debug_bundle"] = silent._bundle(archive, report, new_run, log)
    except Exception as exc:
        report["debug_bundle_error"] = type(exc).__name__ + ":" + str(exc)
    silent._atomic_json(output / "SILENT_LATEST_STATUS.json", report)
    return report


__all__ = ["RELEASE", "SANDBOX_NAME", "RUNS_NAME", "true_project_base",
           "sandbox_for", "validate_fresh_config", "verify_runtime_status",
           "install_native_epoch_guard", "install", "run_silent_detached"]

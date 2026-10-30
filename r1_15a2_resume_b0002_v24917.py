# -*- coding: utf-8 -*-
"""Verified B0002 -> outer cycle 2 continuation with a NEW native path epoch.

Starts at the next full Generation step (cycle 2), never repeats accepted
cycle-1 Generation/TD. No stale A0001 path store is imported. The B0002 .ver
and its accepted-state sidecar stay outside the new run and are immutable.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import r1_15a2_resume_a0001_v24917 as a0001

RELEASE = "R1_V24917_B0002_CYCLE2_FRESH_NATIVE_PATH_EPOCH_20261030"
MODE = "V24917_VERIFIED_B0002_CYCLE2_GENERATION_FRESH_EPOCH"
AUTHORITY_FILE = "B0002_CYCLE2_RESUME_AUTHORITY.json"


def require(ok, error):
    if not ok:
        raise RuntimeError("B0002_RESUME_" + error)


def authority(root=None):
    return a0001.read_json((Path(root) if root else Path(__file__).resolve().parent)
                           / AUTHORITY_FILE)


def source_layout(checkpoint, recipe):
    cp = Path(checkpoint).resolve()
    require(cp.is_file(), "SOURCE_CHECKPOINT_MISSING")
    require(cp.name == recipe["checkpoint_filename"], "SOURCE_CHECKPOINT_NAME_MISMATCH")
    require(cp.parent.name.upper() == "CHECKPOINTS" and
            cp.parent.parent.name.upper() == "CALIBRATION" and
            cp.parent.parent.parent.name == recipe["source_run_name"] and
            cp.parent.parent.parent.parent.name.upper() == "R1_15A2_V16_RUNS",
            "SOURCE_CHECKPOINT_LAYOUT_MISMATCH")
    root = cp.parent.parent
    return {"checkpoint": cp, "sidecar": Path(str(cp) + ".semantic.json"),
            "run_status": root / "RUN_STATUS.json",
            "reference": root / "GENERATION_COUNTS_REFERENCE.json",
            "source_run": root.parent, "calibration": root}


def validate_source_records(run, sidecar, recipe, reference):
    """Separate evidence from run status, B checkpoint, and best-state authority."""
    from r1_15a2_restart_v2494 import semantic_state_hash, SEMANTIC_FIELDS
    from r1_15a2_supply import canonical_hash

    require(run.get("schema") == "R1_15A2_V24914_CONTINUABLE_COUPLED_DEMAND_STATE_MACHINE",
            "RUN_STATUS_SCHEMA_MISMATCH")
    require(run.get("status") == "FAILED" and
            run.get("error", "").startswith("A0001_RESUME_NO_PATH_ENUMERATION_ALLOWED"),
            "RUN_STATUS_UNEXPECTED_TERMINATION")
    require(run.get("accepted_count") == 2 and run.get("demand_converged") is False
            and run.get("supply_started") is False,
            "RUN_ACCEPTED_LINEAGE_MISMATCH")
    cycles = run.get("demand_cycles") or []
    require(len(cycles) == 2, "RUN_CYCLE_COUNT_MISMATCH")
    first, second = cycles
    require(first.get("cycle") == 1 and
            first.get("status") == "PROGRESS_CONTINUE_DEMAND" and
            first.get("generation_completed") is True and
            first.get("td_completed") is True and
            first.get("generation_changed") is True and
            first.get("td_changed") is True and
            first.get("joint_stationary") is False and
            first.get("progress_continue") is True and
            (first.get("td") or {}).get("td_realization_complete") is True and
            (first.get("td", {}).get("inner") or {}).get("stop_reason") == "TD_EVALUATION_BUDGET",
            "CYCLE1_NOT_PROVEN_ACCEPTED_BOTH_STEPS")
    require(second.get("cycle") == 2 and second.get("status") == "FAILED" and
            second.get("generation_completed") is False and
            second.get("td_completed") is False and
            second.get("state_hash_start") == first.get("state_hash_end") and
            second.get("generation") is None and second.get("td") is None,
            "CYCLE2_MUST_BE_UNSTARTED")
    require(first.get("state_hash_end") == recipe["checkpoint_snapshot_state_hash_diagnostic"],
            "ACCEPTED_B0002_STATE_HASH_MISMATCH")
    cp = run.get("latest_accepted_checkpoint") or {}
    require(cp.get("path", "").replace("\\", "/").split("/")[-1] ==
            recipe["checkpoint_filename"] and
            cp.get("sha256") == recipe["expected_checkpoint_raw_sha256"] and
            cp.get("size") == recipe["expected_checkpoint_size_bytes"],
            "LATEST_CHECKPOINT_MISMATCH")
    require(run.get("current_exploratory_checkpoint") == cp,
            "CURRENT_ACCEPTED_CHECKPOINT_MISMATCH")
    best = run.get("best_so_far_checkpoint") or {}
    best_authority = best.get("semantic_restart_authority") or {}
    require(best.get("accepted_count") == 2 and
            best.get("state_hash") == recipe["checkpoint_snapshot_state_hash_diagnostic"] and
            best.get("source_accepted_checkpoint") == cp and
            best_authority.get("semantic_state_hash") == recipe["checkpoint_semantic_state_hash"] and
            best_authority.get("semantic_hashes") == recipe["checkpoint_semantic_hashes"],
            "BEST_SO_FAR_INDEPENDENT_SEMANTIC_WITNESS_MISMATCH")
    require(run.get("generation_reference_sha256") == recipe["generation_reference_hash"],
            "RUN_REFERENCE_SHA_MISMATCH")
    require(reference.get("schema") == "R1_15A2_SHARED_OBJECTIVE_V22" and
            canonical_hash(reference) == recipe["generation_reference_hash"],
            "FIXED_GENERATION_REFERENCE_CHANGED")
    require(sidecar.get("schema") == "R1_15A2_SEMANTIC_RESTART_AUTHORITY_V2494" and
            sidecar.get("semantic_state_hash") == recipe["checkpoint_semantic_state_hash"] and
            sidecar.get("semantic_hashes") == recipe["checkpoint_semantic_hashes"] and
            set(sidecar["semantic_hashes"]) == set(SEMANTIC_FIELDS) and
            semantic_state_hash(sidecar["semantic_hashes"]) ==
            recipe["checkpoint_semantic_state_hash"],
            "CHECKPOINT_SIDECAR_SEVEN_FIELD_MISMATCH")
    return {"accepted_count": 2, "first_cycle_status": first["status"],
            "failed_next_cycle": second["cycle"], "first_cycle_end_hash": first["state_hash_end"],
            "best_so_far_confirmed": True}


def check_source(checkpoint, recipe):
    """Fail closed BEFORE any new-run output or Visum mutation."""
    from r1_15a2_restart_v2494 import load_optional_sidecar
    require(recipe.get("schema") == "R1_V24917_B0002_CYCLE2_RESUME_AUTHORITY_V1",
            "AUTHORITY_SCHEMA_MISMATCH")
    paths = source_layout(checkpoint, recipe)
    require(paths["checkpoint"].stat().st_size == recipe["expected_checkpoint_size_bytes"],
            "CHECKPOINT_SIZE_MISMATCH")
    require(a0001.sha256_file(paths["checkpoint"]) == recipe["expected_checkpoint_raw_sha256"],
            "CHECKPOINT_RAW_SHA_MISMATCH")
    require(paths["sidecar"].is_file(), "CHECKPOINT_SEMANTIC_SIDECAR_MISSING")
    sidecar = load_optional_sidecar(paths["checkpoint"])
    require(sidecar is not None, "CHECKPOINT_SEMANTIC_SIDECAR_MISSING")
    run = a0001.read_json(paths["run_status"])
    reference = a0001.read_json(paths["reference"])
    audit = validate_source_records(run, sidecar, recipe, reference)
    paths.update(sidecar_authority=sidecar, source_audit=audit,
                 generation_reference=reference)
    return paths


def check_live_hashes(snapshot, recipe, *, allow_matrix_deferral=False):
    """The six nonmatrix fields are never deferred; matrix only BEFORE baseline."""
    from r1_15a2_restart_v2494 import SEMANTIC_FIELDS, semantic_state_hash
    require(isinstance(snapshot, dict), "LIVE_SNAPSHOT_UNAVAILABLE")
    expected = recipe["checkpoint_semantic_hashes"]
    diffs = [name for name in SEMANTIC_FIELDS
             if snapshot.get(name) != expected[name]]
    require(not diffs or (allow_matrix_deferral and diffs == ["matrix_hash"]),
            "LIVE_SEMANTIC_DIFFERENCE:" + ",".join(diffs))
    if not diffs:
        require(semantic_state_hash(snapshot) == recipe["checkpoint_semantic_state_hash"],
                "LIVE_SEMANTIC_STATE_HASH_MISMATCH")
    return {"status": ("EXACT_ALL_SEVEN_FIELDS" if not diffs else
                       "MATRIX_ONLY_DEFERRED_UNTIL_NATIVE_BASELINE"),
            "differences": diffs, "semantic_state_hash": semantic_state_hash(snapshot)}


def continuation(paths, recipe):
    """Never replay accepted cycle 1; perform cycle 2 Generation normally."""
    return {
        "enabled": True, "mode": MODE, "accepted_count": 2,
        "next_outer_cycle": 2, "inherited_outer_cycles": 1,
        "max_lineage_outer_cycle": 100, "inherited_stationary_cycle_streak": 0,
        "inherited_completed_demand_cycles": 0,
        "resume_substep": "GENERATION",
        "generation_reference": copy.deepcopy(paths["generation_reference"]),
        "generation_reference_sha256": recipe["generation_reference_hash"],
        "semantic_state_hash": recipe["checkpoint_semantic_state_hash"],
        "source_role": "B0002_POST_ACCEPTED_CYCLE1_GENERATION_AND_TD",
        "source_version": str(paths["checkpoint"]),
        "source_run_status": str(paths["run_status"]),
        "bounded_inner_budget_stop_reasons": [
            "MAX_ITERATIONS", "TD_EVALUATION_BUDGET", "TD_INNER_TIME_BUDGET"],
        "continue_bounded_budget_without_accepted_change": True,
        "bounded_budget_counts_as_stationarity": False,
        "supply_unlock_criterion": "EXISTING_JOINT_DEMAND_STATIONARITY_ONLY",
        "fresh_native_path_epoch_required": True,
        "legacy_cache_import_allowed": False,
        "prior_generation_and_td_replayed": False,
    }


def validate_continuation(cfg, recipe):
    from r1_15a2_supply import canonical_hash
    row = cfg.get("runtime_demand_continuation") or {}
    require(row.get("enabled") is True and row.get("mode") == MODE,
            "CONTINUATION_MODE_INVALID")
    for key, expected in (("accepted_count", 2), ("next_outer_cycle", 2),
                          ("inherited_outer_cycles", 1), ("inherited_stationary_cycle_streak", 0),
                          ("inherited_completed_demand_cycles", 0),
                          ("max_lineage_outer_cycle", 100),
                          ("resume_substep", "GENERATION"),
                          ("semantic_state_hash", recipe["checkpoint_semantic_state_hash"]),
                          ("fresh_native_path_epoch_required", True),
                          ("legacy_cache_import_allowed", False),
                          ("prior_generation_and_td_replayed", False)):
        require(row.get(key) == expected, "CONTINUATION_INVALID:" + key)
    require(canonical_hash(row.get("generation_reference")) == recipe["generation_reference_hash"]
            and row.get("generation_reference_sha256") == recipe["generation_reference_hash"],
            "CONTINUATION_FIXED_REFERENCE_CHANGED")
    return copy.deepcopy(row)


def install_fresh_epoch_gate(adapter, folder, baseline_verified):
    """Allow only real native exports in this NEW run, never predecessor SQLite."""
    from r1_15a2_supply import SupplyContractError
    from r1_15a2_two_mode_v238 import atomic_json
    folder = Path(folder).resolve()
    builder = getattr(adapter, "_build_cache", None)
    retire = getattr(adapter, "_retire_obsolete_epoch_store", None)
    require(callable(builder) and callable(retire), "NATIVE_EPOCH_METHODS_UNAVAILABLE")
    require(adapter.cache is None and adapter.path_epoch_index == 0,
            "PREEXISTING_CACHE_NOT_ALLOWED")
    require(adapter.cfg.get("performance", {}).get("path_epochs", {}).get("enabled") is True,
            "PATH_EPOCHS_MUST_BE_ENABLED")
    require(adapter.persistent_path_cache.enabled is False,
            "PERSISTENT_CROSS_RUN_CACHE_MUST_BE_DISABLED")
    events = []

    def only_local_retire(store, audit_folder):
        if store is None:
            return retire(store, audit_folder)
        path = Path(store).resolve()
        try:
            path.relative_to(folder)
        except ValueError as exc:
            raise SupplyContractError("B0002_REFUSE_RETIRE_SOURCE_CACHE:" + str(path)) from exc
        return retire(store, audit_folder)

    def guarded_build(diag, destination, snapshot, *, build_sequence_evidence=False,
                      allow_persistent_restore=True):
        require(baseline_verified(), "PATH_ENUMERATION_BEFORE_STRICT_BASELINE_PROOF")
        target = Path(destination).resolve()
        try:
            target.relative_to(folder)
        except ValueError as exc:
            raise SupplyContractError("B0002_NEW_EPOCH_OUTSIDE_NEW_CALIBRATION:" + str(target)) from exc
        require(target != folder and not target.exists(),
                "NEW_EPOCH_TARGET_MUST_BE_EMPTY:" + str(target))
        require((isinstance(snapshot, dict) and snapshot.get("state_hash")),
                "NEW_EPOCH_SNAPSHOT_INVALID")
        event = {"schema": "R1_B0002_VERIFIED_FRESH_NATIVE_EPOCH_V1",
                 "status": "NATIVE_ENUMERATION_STARTED",
                 "source_accepted_count": 2,
                 "previous_epoch": int(adapter.path_epoch_index),
                 "current_snapshot_state_hash": snapshot["state_hash"],
                 "target": str(target),
                 "old_source_sqlite_never_opened": True,
                 "persistent_restore_disabled": True,
                 "native_route_export_required": True}
        target.mkdir(parents=True)
        atomic_json(target / "B0002_NATIVE_EPOCH_AUTHORITY.json", event)
        # Original native collector/exporter, no simulated paths or cache fallback.
        result = builder(diag, target, snapshot,
                         build_sequence_evidence=build_sequence_evidence,
                         allow_persistent_restore=False)
        collector = result[0]
        require(getattr(collector, "route_db_path", None) is not None,
                "NATIVE_EPOCH_COLLECTOR_HAS_NO_STORE")
        db = Path(collector.route_db_path).resolve()
        try:
            db.relative_to(folder)
        except ValueError as exc:
            raise SupplyContractError("B0002_EPOCH_STORE_OUTSIDE_NEW_RUN:" + str(db)) from exc
        require(db.is_file() and int(adapter.path_epoch_index) > event["previous_epoch"],
                "NATIVE_EPOCH_NOT_PUBLISHED")
        event.update(status="NEW_NATIVE_EPOCH_VERIFIED", new_epoch=int(adapter.path_epoch_index),
                     store=str(db))
        atomic_json(target / "B0002_NATIVE_EPOCH_AUTHORITY.json", event)
        events.append(event)
        return result

    adapter._retire_obsolete_epoch_store = only_local_retire
    adapter._build_cache = guarded_build
    return events


def prove_native_support(adapter, diag, folder, snapshot):
    """Early smoke: fresh native paths must cover live positive OD support."""
    from r1_15a2_two_mode_v238 import atomic_json
    folder = Path(folder)
    require(adapter.cache is None and adapter.path_epoch_index == 0,
            "NATIVE_SMOKE_MUST_START_WITHOUT_CACHE")
    collector, _, export = adapter._build_cache(
        diag, folder / "B0002_INITIAL_EPOCH", snapshot,
        build_sequence_evidence=False, allow_persistent_restore=False)
    # Same material support check as VisumAdapter.generation_design(), before
    # the first generation trial. Fails with its true PATH_EPOCH_* reason.
    try:
        actual = adapter._live_generation_matrices()
        support = collector.incidence(adapter.cfg, adapter.actuatable_zones,
                                      live_od_matrices=actual)
        require(support is not None, "NATIVE_PATH_SUPPORT_NOT_AVAILABLE")
    except Exception as exc:
        atomic_json(folder / "B0002_INITIAL_PATH_SUPPORT_SMOKE.json", {
            "schema": "R1_B0002_INITIAL_NATIVE_PATH_SUPPORT_SMOKE_V1",
            "status": "FAIL_CLOSED_AFTER_FRESH_NATIVE_ENUMERATION",
            "error": str(exc),
            "new_epoch": adapter.path_epoch_index,
            "source_checkpoint_unchanged": True,
            "no_generation_trial_executed": True,
            "manual_reopen_checkpoint_for_retry": True,
        })
        raise
    audit = {"schema": "R1_B0002_INITIAL_NATIVE_PATH_SUPPORT_SMOKE_V1",
             "status": "PASS_NEW_NATIVE_PATH_SUPPORT",
             "native_export_completed": True,
             "new_epoch": adapter.path_epoch_index,
             "positive_od_support_verified": True,
             "source_sqlite_imported": False,
             "matrix_scope": sorted(actual),
             "new_store": str(collector.route_db_path)}
    atomic_json(folder / "B0002_INITIAL_PATH_SUPPORT_SMOKE.json", audit)
    return audit


def install_resume(v16, checkpoint, recipe, paths, print_fn=print, *, smoke_only=False):
    """Hook installed V24917/V24916 parent without changing source `.ver`."""
    from r1_15a2_supply import canonical_hash
    a0001.install_sibling_run_layout_guard(v16, checkpoint, print_fn=print_fn)
    base_install, base_preflight = v16._install_runtime, v16._run_live_preflight
    proof = {}

    def checked_preflight(*args, **kwargs):
        report, manifest = base_preflight(*args, **kwargs)
        require(report.get("passes") is True and
                (report.get("semantic_before_after") or {}).get("passes") is True,
                "SOURCE_PREFLIGHT_NOT_STABLE")
        require(Path(report.get("current_version_file", "")).resolve() == paths["checkpoint"],
                "PREFLIGHT_SOURCE_VERSION_CHANGED")
        require(report.get("source_raw_ver_sha256_provenance_only") ==
                recipe["expected_checkpoint_raw_sha256"],
                "PREFLIGHT_SOURCE_RAW_SHA_CHANGED")
        observed = report.get("source_semantic_hashes")
        require(isinstance(observed, dict), "PREFLIGHT_SEMANTIC_HASHES_MISSING")
        check = check_live_hashes(observed, recipe, allow_matrix_deferral=True)
        require(report.get("source_semantic_state_hash") == check["semantic_state_hash"],
                "PREFLIGHT_SEMANTIC_HASH_SELF_INCONSISTENT")
        proof.update(check, source_checkpoint=str(paths["checkpoint"]),
                     raw_sha_verified=True)
        return report, manifest

    def installer(*args, **kwargs):
        installed = base_install(*args, **kwargs)
        import r1_15a2_overnight_controller_coupled_v24915p2_force100 as coupled
        parent = v16.parent
        original_run = parent.run_overnight_calibration_coupled
        original_parser = coupled._runtime_demand_continuation
        descriptor = continuation(paths, recipe)

        def parser(cfg):
            if (cfg.get("runtime_demand_continuation") or {}).get("mode") == MODE:
                return validate_continuation(cfg, recipe)
            return original_parser(cfg)

        def resumed_run(adapter, cfg, folder, control, package_root):
            require(proof.get("raw_sha_verified") is True,
                    "LIVE_PREFLIGHT_NOT_PROVEN")
            require(cfg.get("coupled_demand", {}).get("max_outer_cycles") == 100,
                    "COUPLED_DEMAND_CYCLE_LIMIT_CHANGED")
            require(adapter.cache is None, "CACHE_NOT_EMPTY_BEFORE_RESTART")
            pre = adapter.generation_guard_snapshot()
            check_live_hashes(pre, recipe, allow_matrix_deferral=True)
            require(canonical_hash(descriptor["generation_reference"]) ==
                    recipe["generation_reference_hash"], "FIXED_REFERENCE_CHANGED")
            cfg["runtime_demand_continuation"] = copy.deepcopy(descriptor)
            adapter.cfg["runtime_demand_continuation"] = copy.deepcopy(descriptor)
            orig_diagnostics = adapter.diagnostics
            baseline = {"verified": False, "calls": 0}

            def strict_baseline(diagnostic_folder, label="CURRENT"):
                diag = orig_diagnostics(diagnostic_folder, label=label)
                if label == "BASELINE":
                    require(baseline["calls"] == 0, "DUPLICATE_BASELINE")
                    baseline["calls"] += 1
                    snapshot = adapter.generation_guard_snapshot()
                    semantic = check_live_hashes(snapshot, recipe)
                    require(semantic["status"] == "EXACT_ALL_SEVEN_FIELDS",
                            "POST_BASELINE_SEVEN_FIELDS_MISMATCH")
                    accepted = adapter.snapshot()
                    check_live_hashes(accepted, recipe)
                    from r1_15a2_two_mode_v238 import atomic_json
                    evidence = {"schema": "R1_B0002_POST_NATIVE_BASELINE_PROOF_V1",
                                "status": "EXACT_ACCEPTED_B0002_SEVEN_FIELD_PROOF",
                                "source_checkpoint": str(paths["checkpoint"]),
                                "source_semantic_state_hash": semantic["semantic_state_hash"],
                                "original_cycle_1_state_hash_diagnostic":
                                    recipe["checkpoint_snapshot_state_hash_diagnostic"],
                                "current_state_hash_diagnostic": accepted.get("state_hash"),
                                "prior_generation_and_td_replayed": False}
                    atomic_json(Path(folder) / "RESUME_EVIDENCE" /
                                "B0002_POST_BASELINE_AUTHORITY.json", evidence)
                    baseline["verified"] = True
                    install_fresh_epoch_gate(
                        adapter, folder, baseline_verified=lambda: baseline["verified"])
                    # Only one bounded initial COM path enumeration; subsequent
                    # generations reuse that basis until true support/plateau change.
                    prove_native_support(adapter, diag, Path(folder) / "RESUME_EVIDENCE",
                                         accepted)
                return diag

            adapter.diagnostics = strict_baseline
            print_fn("B0002: accepted cycle 1 retained; rebuilding native path epoch in new run")
            if smoke_only:
                # A bounded, read-only-to-source Windows/Visum verification run.
                # The verified baseline callback performs the single fresh
                # native path enumeration and live positive OD support check.
                control.checkpoint("B0002_NATIVE_PATH_SMOKE_BEGIN", force=True)
                adapter.preflight(Path(folder) / "PREFLIGHT")
                pre_smoke = adapter.snapshot()
                adapter.assign(Path(folder) / "BASELINE_FULL_RECOMPUTE", supply_only=False)
                native_state = adapter.snapshot()
                for name in ("fixed_link_hash", "dseg_hash", "operations_hash",
                             "addval_hash", "generation_hash", "td_hash"):
                    require(pre_smoke[name] == native_state[name],
                            "SMOKE_BASELINE_RECOMPUTE_CHANGED_PARAMETER:" + name)
                adapter.diagnostics(Path(folder) / "BASELINE_DIAGNOSTICS", "BASELINE")
                require(baseline["verified"] and adapter.snapshot() == native_state,
                        "SMOKE_DID_NOT_PRESERVE_NATIVE_BASELINE")
                from r1_15a2_two_mode_v238 import atomic_json
                event = {
                    "schema": "R1_V24917_B0002_NATIVE_PATH_EPOCH_SMOKE_V1",
                    "status": "B0002_NATIVE_PATH_EPOCH_SMOKE_PASSED",
                    "source_checkpoint": str(paths["checkpoint"]),
                    "source_accepted_count": 2,
                    "next_outer_cycle": 2,
                    "source_semantic_hash": recipe["checkpoint_semantic_state_hash"],
                    "new_native_path_epoch": adapter.path_epoch_index,
                    "current_state_hash_diagnostic": native_state["state_hash"],
                    "generation_candidates_evaluated": 0,
                    "finecdf_td_candidates_evaluated": 0,
                    "new_accepted_changes": 0,
                    "source_sqlite_imported": False,
                    "source_checkpoint_written": False,
                    "demand_converged": False,
                    "calibration_complete": False,
                    "next_step": "REOPEN_ORIGINAL_B0002_THEN_FULL_CYCLE2_LAUNCHER",
                }
                atomic_json(Path(folder) / "RUN_STATUS.json", event)
                atomic_json(Path(folder) / "B0002_PATH_EPOCH_SMOKE_RESULT.json", event)
                return event
            return original_run(adapter, cfg, folder, control, package_root)

        coupled._runtime_demand_continuation = parser
        parent.run_overnight_calibration_coupled = resumed_run
        return installed

    v16._run_live_preflight = checked_preflight
    v16._install_runtime = installer
    return {"release": RELEASE, "mode": MODE, "checkpoint": str(paths["checkpoint"]),
            "first_new_cycle": 2, "prior_cycle1_skipped": True,
            "smoke_only": bool(smoke_only),
            "fresh_native_route_enumeration": True}

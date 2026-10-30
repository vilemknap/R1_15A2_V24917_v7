# -*- coding: utf-8 -*-
"""A0001 Generation-coefficient recovery with native matrices and NEW route epoch.

The old A0001 .ver is a coefficient/provenance SOURCE, not accepted OD-matrix
authority: a failed TD rollback produced a live matrix hash differing from the
A0001 acceptance sidecar. Recompute all native demand operations, then enumerate
paths afresh before TD cycle 1. Never borrow the old sqlite or silently rewrite
the source acceptance sidecar.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import r1_15a2_resume_a0001_v24917 as original

RELEASE = "R1_V24917_A0001_GENERATION_NATIVE_REBUILD_FRESH_ENUM_20261030"
MODE = "V24917_A0001_REBUILT_NATIVE_MATRICES_NEW_PATH_EPOCH"
REBUILD_NAME = "A0001_REBUILT_GENERATION_AND_FRESH_PATH_AUTHORITY.json"
SIX_IMMUTABLE = ("fixed_link_hash", "dseg_hash", "operations_hash",
                 "addval_hash", "generation_hash", "td_hash")
REQUIRED_NATIVE_PHASES = {
    "THROUGH_TD": {1, 5, 6},
    "REALIZATION": {8, 10, 11, 12, 14},
    "ASSIGNMENT_SKIMS": {17, 18, 19, 20},
}
SOURCE_MATRIX_HASH = "d3d41a7b64f06e94d3c0001e120176ce1c2141c0de71753cba8e2559992d8d5c"


def require(test, code):
    if not test:
        raise RuntimeError("A0001_REBUILD_" + code)


def source_paths(checkpoint, recipe):
    """Verify A0001 provenance, but never require or open the OLD path sqlite."""
    paths = original.original_layout(checkpoint, recipe)
    require(paths["checkpoint"].name == recipe["checkpoint_filename"],
            "CHECKPOINT_NAME_MISMATCH")
    require(original.sha256_file(paths["checkpoint"]) ==
            recipe["expected_checkpoint_raw_sha256"],
            "CHECKPOINT_BYTES_CHANGED")
    sidecar = original.read_json(paths["sidecar"])
    require(sidecar.get("semantic_state_hash") ==
            recipe["checkpoint_semantic_state_hash"],
            "ACCEPTED_SIDECAR_HASH_MISMATCH")
    original.check_fields(sidecar.get("semantic_hashes"), recipe,
                          "ACCEPTED_SIDECAR")
    for k in ("reference", "run_status"):
        require(paths[k].is_file(), "MISSING_SOURCE_" + k.upper())
    return paths


def six_fields_match(snapshot, recipe, label):
    expected = recipe["checkpoint_semantic_hashes"]
    require(isinstance(snapshot, dict), label + "_NOT_OBJECT")
    for name in SIX_IMMUTABLE:
        require(snapshot.get(name) == expected[name],
                label + "_FIELD_MISMATCH:" + name)


def validate_fresh_path_root(cfg, paths):
    """Fresh namespace only; never use the old disabled V24916 cache."""
    require(cfg.get("runtime_legacy_path_cache_roots", []) == [],
            "LEGACY_CACHE_ROOTS_NONEMPTY")
    newroot = cfg.get("runtime_persistent_path_cache_root")
    require(bool(newroot), "NEW_CACHE_ROOT_MISSING")
    fresh = Path(newroot).resolve()
    oldrun = paths["calibration_root"].parent.resolve()
    require(fresh != oldrun and oldrun not in fresh.parents,
            "NEW_CACHE_ROOT_NESTED_IN_OLD_RUN")
    oldstore = paths["sqlite"].resolve()
    require(fresh != oldstore and fresh not in oldstore.parents,
            "NEW_CACHE_ROOT_OVERLAPS_SOURCE_STORE")
    return fresh


def validate_native_execution_plan(path):
    """The audited Visum sequence must have regenerated TG + TD + realization."""
    require(Path(path).is_file(), "NATIVE_EXECUTION_PLAN_MISSING")
    plan = original.read_json(path)
    phases = plan.get("phases") or []
    by_name = {str(name): {int(x) for x in positions}
               for name, positions in phases}
    require(len(by_name) == len(phases), "DUPLICATE_NATIVE_PHASE")
    for name, needed in REQUIRED_NATIVE_PHASES.items():
        require(needed <= by_name.get(name, set()),
                "NATIVE_OPERATION_PHASE_MISSING:" + name)
    require(plan.get("td_operation_position") == 6,
            "NATIVE_TD_OPERATION_CHANGED")
    require(plan.get("original_active_flags_restored_after_each_phase") is True,
            "NATIVE_OPERATION_FLAGS_UNRESTORED")
    return {name: sorted(by_name[name]) for name in REQUIRED_NATIVE_PHASES}


def matrix_rows_valid(snapshot, expected_zones):
    rows = snapshot.get("matrices")
    require(isinstance(rows, list) and len(rows) == 37,
            "GENERATION_MATRIX_ROSTER_NOT_37")
    numbers = []
    for row in rows:
        no = int(row["matrix_no"])
        numbers.append(no)
        require(int(row["rows"]) == expected_zones and
                int(row["cols"]) == expected_zones and
                len(str(row["sha256_float64_le"])) == 64,
                "GENERATION_MATRIX_FINGERPRINT_INVALID:" + str(no))
    require(len(numbers) == len(set(numbers)), "DUPLICATE_MATRIX_NO")
    return copy.deepcopy(rows)


def write_rebuilt_authority(folder, snapshot, diag, recipe, paths,
                            fresh_root, collector, native_phases):
    """Document a NEW scientific state; never claim it equals the old A0001 OD."""
    from r1_15a2_restart_v2494 import semantic_state_hash
    from r1_15a2_runtime_v1 import write_json
    from r1_15a2_supply import canonical_hash

    six_fields_match(snapshot, recipe, "AFTER_NATIVE")
    rows = matrix_rows_valid(snapshot, 681)
    matrix_hash = canonical_hash(rows)
    require(matrix_hash == snapshot.get("matrix_hash"),
            "FRESH_MATRIX_ROWS_HASH_MISMATCH")
    profile_rows = (diag.get("d12") or {}).get("rows")
    require(isinstance(profile_rows, list) and len(profile_rows) == 248,
            "FRESH_12D_PROFILE_ROSTER_MISMATCH")
    require(collector is not None, "NEW_PATH_COLLECTOR_NOT_AVAILABLE")
    require(bool(getattr(collector, "ready", False)),
            "NEW_PATH_COLLECTOR_NOT_READY")
    store_value = getattr(collector, "route_db_path", None)
    require(store_value is not None, "NEW_ROUTE_DB_PATH_MISSING")
    store = Path(store_value).resolve()
    require(store.is_file() and store != paths["sqlite"].resolve(),
            "NEW_PATH_STORE_MISSING_OR_REUSED_OLD")
    require(paths["calibration_root"].parent.resolve() not in store.parents,
            "NEW_PATH_STORE_INSIDE_OLD_RUN")
    current_sem = semantic_state_hash(snapshot)
    source_sem = recipe["checkpoint_semantic_state_hash"]
    result = {
        "schema": "R1_A0001_NATIVE_GENERATION_REBUILD_V1",
        "status": "FRESH_NATIVE_MATRICES_AND_FRESH_PATH_EPOCH_VERIFIED",
        "policy": "ACCEPTED_GENERATION_COEFFICIENTS__NEW_NATIVE_DEMAND_AUTHORITY__NO_OLD_MATRIX_IDENTITY_CLAIM",
        "source_original_a0001_ver": str(paths["checkpoint"]),
        "source_a0001_raw_sha256": recipe["expected_checkpoint_raw_sha256"],
        "source_a0001_accepted_semantic_state_hash": source_sem,
        "source_a0001_accepted_matrix_hash": recipe["checkpoint_semantic_hashes"]["matrix_hash"],
        "new_semantic_state_hash": current_sem,
        "new_matrix_hash": matrix_hash,
        "old_matrix_hash_equal": matrix_hash == recipe["checkpoint_semantic_hashes"]["matrix_hash"],
        "accepted_generation_hash_equal": True,
        "td_coefficients_frozen_equal": True,
        "source_generation_optimization_replayed": False,
        "old_acceptance_coefficients_retained": True,
        "reconstructed_matrices_not_assumed_equal_to_old_a0001": True,
        "native_tg_td_realization_recomputed": True,
        "native_operations": native_phases,
        "native_matrix_count": len(rows),
        "native_matrix_rows": rows,
        "fresh_route_enumeration_called": True,
        "source_path_epoch_reused": False,
        "old_sqlite_opened": False,
        "fresh_cache_root": str(fresh_root),
        "fresh_path_epoch_origin_state_hash": snapshot["state_hash"],
        "fresh_path_basis_hash": collector.path_basis_hash(),
        "fresh_path_comparison_basis_hash": collector.path_basis_comparison_hash(),
        "fresh_route_store": str(store),
        "profile_count": len(profile_rows),
        "origin_generation_acceptance_role": "ACCEPTED_COEFFICIENT_STEP_NOT_OLD_SERIALIZED_OD",
        "continuation": "CYCLE_1_TD_FINECDF_V17",
    }
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    write_json(folder / REBUILD_NAME, result)
    return result


def install_rebuild(v16, paths, recipe, continuation, disk_receipt, print_fn=print):
    """Patch ONLY the A0001 launcher; core TG/TD and cache builder stay native."""
    original.install_sibling_run_layout_guard(
        v16, paths["checkpoint"], print_fn=print_fn)
    saved_install = v16._install_runtime
    saved_preflight = v16._run_live_preflight
    preflight_proof = {}

    def guarded_preflight(*args, **kwargs):
        report, manifest = saved_preflight(*args, **kwargs)
        require(disk_receipt.get("load_version_called") is True
                and disk_receipt.get("source_raw_sha256") ==
                   recipe["expected_checkpoint_raw_sha256"],
                "SOURCE_NOT_RELOADED_FROM_DISK")
        require(report.get("passes") is True
                and (report.get("semantic_before_after") or {}).get("passes") is True,
                "LIVE_PREFLIGHT_FAILED_OR_MUTATED")
        require(Path(report.get("current_version_file", "")).resolve() ==
                paths["checkpoint"], "WRONG_LOADED_VERSION")
        require(report.get("source_raw_ver_sha256_provenance_only") ==
                recipe["expected_checkpoint_raw_sha256"],
                "SOURCE_BYTES_CHANGED")
        hashes = report.get("source_semantic_hashes")
        six_fields_match(hashes, recipe, "SOURCE_PREFLIGHT")
        from r1_15a2_restart_v2494 import semantic_state_hash
        require(report.get("source_semantic_state_hash") ==
                semantic_state_hash(hashes),
                "SOURCE_PREFLIGHT_SEMANTIC_HASH_INCONSISTENT")
        preflight_proof.update(
            source_semantic_state_hash=report["source_semantic_state_hash"],
            source_matrix_hash=hashes.get("matrix_hash"),
            accepted_generation_hash=hashes["generation_hash"],
            source_matrix_rebuild_required=True,
            source_disk_load=True)
        return report, manifest

    def installer(*args, **kwargs):
        installed = saved_install(*args, **kwargs)
        import r1_15a2_overnight_controller_coupled_v24915p2_force100 as coupled
        old_parser = coupled._runtime_demand_continuation
        old_controller = v16.parent.run_overnight_calibration_coupled

        def parser(cfg):
            row = cfg.get("runtime_demand_continuation") or {}
            if row.get("mode") != MODE:
                return old_parser(cfg)
            require(row.get("accepted_count") == 1 and
                    row.get("next_outer_cycle") == 1 and
                    row.get("resume_substep") == "TD_FINECDF_V17" and
                    row.get("fresh_path_enumeration_required") is True and
                    row.get("no_path_enumeration") is False,
                    "REBUILT_CONTINUATION_INVALID")
            require(row.get("generation_reference_sha256") ==
                    recipe["generation_reference_hash"],
                    "REBUILT_REFERENCE_MISMATCH")
            return copy.deepcopy(row)

        def controller(adapter, cfg, folder, control, root):
            require(preflight_proof.get("source_disk_load") is True,
                    "SOURCE_PREFLIGHT_PROOF_MISSING")
            require(adapter.cache is None, "OLD_CACHE_PRESENT_BEFORE_FRESH_ENUM")
            require(int(cfg.get("coupled_demand", {}).get("max_outer_cycles", -1)) == 100,
                    "COUPLED_CYCLE_BUDGET_CHANGED")
            fresh_root = validate_fresh_path_root(cfg, paths)
            pre_native = adapter.generation_guard_snapshot()
            six_fields_match(pre_native, recipe, "SOURCE_BEFORE_NATIVE")
            initial = copy.deepcopy(continuation)
            initial["mode"] = MODE
            initial["no_path_enumeration"] = False
            initial["fresh_path_enumeration_required"] = True
            initial["old_sqlite_reuse_allowed"] = False
            initial["source_role"] = "ACCEPTED_A0001_GENERATION_COEFFICIENTS__NATIVE_REBUILD_FRESH_PATHS"
            initial["semantic_state_hash"] = recipe["checkpoint_semantic_state_hash"]
            cfg["runtime_demand_continuation"] = copy.deepcopy(initial)
            adapter.cfg["runtime_demand_continuation"] = copy.deepcopy(initial)
            original_diag = adapter.diagnostics
            state = {"baseline_called": False, "rebuild": None}

            def after_baseline(diag_folder, label="CURRENT"):
                diag = original_diag(diag_folder, label=label)
                if label != "BASELINE":
                    return diag
                require(not state["baseline_called"], "BASELINE_CALLED_TWICE")
                # Original controller's FULL downstream native recompute has
                # finished (ops 1, 5, 6, 8, 10, 11, 12, 14, 17-20).
                strict_native = adapter.generation_guard_snapshot()
                before_enum = adapter.snapshot()
                six_fields_match(strict_native, recipe, "AFTER_NATIVE_STRICT")
                six_fields_match(before_enum, recipe, "AFTER_NATIVE_CONTROLLER")
                # The original _build_cache requires exact object equality
                # to adapter.snapshot() after the export. Use THAT native
                # controller snapshot as its origin, never a differently
                # shaped optimized/strict readback object.
                for name in SIX_IMMUTABLE + ("matrix_hash", "state_hash"):
                    require(strict_native.get(name) == before_enum.get(name),
                            "STRICT_VS_CONTROLLER_SNAPSHOT_MISMATCH:" + name)
                plan = validate_native_execution_plan(
                    Path(folder) / "BASELINE_FULL_RECOMPUTE" /
                    "LONG_MASK_EXECUTION_PLAN.json")
                # Fresh, run-isolated epoch, never the old A0001 sqlite and
                # never a cross-run restore. This CALL enumerates all paths.
                require(adapter.cache is None, "OLD_CACHE_REAPPEARED")
                collector, _links, _export = adapter._build_cache(
                    diag, Path(folder) / "REBUILT_GENERATION_FRESH_PATH_EPOCH",
                    before_enum, build_sequence_evidence=False,
                    allow_persistent_restore=False)
                require(adapter.cache is collector,
                        "NEW_PATH_EPOCH_NOT_BOUND")
                after_enum = adapter.snapshot()
                require(after_enum == before_enum,
                        "NEW_PATH_ENUMERATION_MUTATED_LIVE_MODEL")
                report = write_rebuilt_authority(
                    folder, after_enum, diag, recipe, paths, fresh_root,
                    collector, plan)
                state["rebuild"] = report
                state["baseline_called"] = True
                print_fn("A0001 Generation matrices REBUILT: matrix=" +
                         report["new_matrix_hash"] +
                         " original=" + report["source_a0001_accepted_matrix_hash"] +
                         " full fresh path basis=" + report["fresh_path_basis_hash"])
                return diag

            adapter.diagnostics = after_baseline
            try:
                return old_controller(adapter, cfg, folder, control, root)
            finally:
                # The controller is responsible for fail-closed rollback and
                # status emission. Never mutate the original source .ver.
                if state["rebuild"] is None:
                    print_fn("A0001 REBUILD did not complete: TD not authorized")

        coupled._runtime_demand_continuation = parser
        v16.parent.run_overnight_calibration_coupled = controller
        print_fn("A0001 Generation coefficient recovery installed; native full " +
                 "TG/TD + entirely NEW path enumeration before cycle-1 TD")
        return installed

    v16._run_live_preflight = guarded_preflight
    v16._install_runtime = installer
    return {"release": RELEASE, "source": str(paths["checkpoint"]),
            "source_accepted_generation_hash":
                recipe["checkpoint_semantic_hashes"]["generation_hash"],
            "old_matrix_hash_is_not_accepted_as_rebuilt_authority": True,
            "original_sqlite_reuse": False, "fresh_path_enumeration": True}

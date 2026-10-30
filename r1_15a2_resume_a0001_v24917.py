"""Explicit A0001 cycle-1 TD continuation using a verified, read-only old path epoch.

Never calls LoadVersion or enumerates routes. Reuses the existing native TD
controller. A missing/changed original SQLite path store is a hard stop.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

RELEASE = "R1_V24917_A0001_TD_RESUME_NO_ENUM_20261030"
MODE = "V24917_A0001_ACCEPTED_GENERATION_TD_RESUME_NO_ENUM"
AUTHORITY_FILE = "A0001_TD_RESUME_AUTHORITY.json"


def require(ok, error):
    if not ok:
        raise RuntimeError("A0001_RESUME_" + error)


def read_json(path):
    path = Path(path)
    require(path.is_file(), "SOURCE_ARTIFACT_MISSING:" + str(path))
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (ValueError, OSError) as exc:
        raise RuntimeError("A0001_RESUME_SOURCE_ARTIFACT_UNREADABLE:" + str(path)) from exc


def authority(root=None):
    return read_json((Path(root) if root else Path(__file__).resolve().parent) / AUTHORITY_FILE)


def original_layout(checkpoint, recipe):
    cp = Path(checkpoint).resolve()
    require(cp.is_file(), "CHECKPOINT_FILE_MISSING")
    require(cp.name == recipe["checkpoint_filename"], "CHECKPOINT_NAME_MISMATCH")
    require(cp.parent.name.upper() == "CHECKPOINTS" and
            cp.parent.parent.name.upper() == "CALIBRATION", "CHECKPOINT_LAYOUT_MISMATCH")
    base = cp.parent.parent
    return {
        "checkpoint": cp,
        "calibration_root": base,
        "sqlite": base / recipe["path_store_relative_to_calibration"],
        "reference": base / recipe["source_reference_relative_to_calibration"],
        "run_status": base / recipe["source_run_status_relative_to_calibration"],
        "sidecar": Path(str(cp) + ".semantic.json"),
    }


def sha256_file(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for part in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(part)
    return h.hexdigest()


def check_fields(fields, recipe, prefix):
    expected = recipe["checkpoint_semantic_hashes"]
    require(isinstance(fields, dict), prefix + "_NOT_OBJECT")
    for key in recipe["checkpoint_semantic_fields"]:
        require(fields.get(key) == expected.get(key), prefix + "_FIELD_MISMATCH:" + key)


def check_source(checkpoint, recipe):
    """Check exact path/layout and sidecar before creating any working copy."""
    require(recipe.get("schema") == "R1_V24917_A0001_TD_RESUME_AUTHORITY_V1",
            "RECIPE_SCHEMA_MISMATCH")
    paths = original_layout(checkpoint, recipe)
    require(sha256_file(paths["checkpoint"]) == recipe["expected_checkpoint_raw_sha256"],
            "CHECKPOINT_BYTES_CHANGED")
    sidecar = read_json(paths["sidecar"])
    require(sidecar.get("semantic_state_hash") == recipe["checkpoint_semantic_state_hash"],
            "CHECKPOINT_SIDECAR_IDENTITY_MISMATCH")
    check_fields(sidecar.get("semantic_hashes"), recipe, "CHECKPOINT_SIDECAR")
    require(paths["sqlite"].is_file(), "PATH_STORE_MISSING:" + str(paths["sqlite"]))
    require(paths["reference"].is_file(), "GENERATION_REFERENCE_MISSING")
    require(paths["run_status"].is_file(), "RUN_STATUS_MISSING")
    return paths


def check_live_semantic(live, recipe, *, permit_v24916_matrix_deferral=False):
    """Separate cross-release V24916 preflight from V24917 checkpoint proof.

    A matching source .ver SHA alone is never a semantic proof. The six
    non-matrix fields must match exactly. A V24916-only matrix difference may
    be deferred, but is NOT ACCEPTED: the V24917 exact live snapshot must
    independently match all seven fields before TD and path-store use.
    """
    from r1_15a2_restart_v2494 import semantic_state_hash

    observed = live.get("semantic_hashes")
    require(isinstance(observed, dict), "LIVE_SEMANTIC_FIELDS_MISSING")
    expected = recipe["checkpoint_semantic_hashes"]
    names = recipe["checkpoint_semantic_fields"]
    differences = [name for name in names if observed.get(name) != expected[name]]
    computed = semantic_state_hash(observed)
    require(live.get("semantic_state_hash") == computed,
            "LIVE_PREFLIGHT_SEMANTIC_HASH_SELF_INCONSISTENT")
    if not differences:
        require(computed == recipe["checkpoint_semantic_state_hash"],
                "LIVE_SEMANTIC_STATE_MISMATCH")
        return {"status": "EXACT_ALL_SEVEN_FIELDS", "matrix_match": True,
                "semantic_state_hash": computed}
    require(differences == ["matrix_hash"] and permit_v24916_matrix_deferral,
            "LIVE_SEMANTIC_DIFFERENCE:" + ",".join(differences))
    return {
        "status": "V24916_MATRIX_ONLY_UNPROVEN_REQUIRES_V24917_EXACT_SNAPSHOT",
        "matrix_match": False,
        "expected_checkpoint_matrix_hash": expected["matrix_hash"],
        "v24916_live_matrix_hash": observed["matrix_hash"],
        "v24916_semantic_state_hash": computed,
        "no_checkpoint_acceptance_granted": True,
        "model_mutations_allowed_by_this_gate": False,
    }


def publish_matrix_reopen_audit(folder, snapshot, recipe, preflight_proof):
    """Persist exact live matrix identities BEFORE any resume TD evaluation."""
    from r1_15a2_restart_v2494 import semantic_state_hash
    expected = recipe["checkpoint_semantic_hashes"]
    names = recipe["checkpoint_semantic_fields"]
    observed = {name: snapshot.get(name) for name in names}
    diffs = [name for name in names if observed[name] != expected[name]]
    exact = not diffs and semantic_state_hash(snapshot) == recipe["checkpoint_semantic_state_hash"]
    matrix_rows = snapshot.get("matrices")
    require(isinstance(matrix_rows, list), "LIVE_MATRIX_ROWS_MISSING")
    row = {
        "schema": "R1_A0001_REOPEN_MATRIX_FORENSICS_V1",
        "status": "EXACT_V24917_CHECKPOINT" if exact else "MISMATCH_V24917_CHECKPOINT",
        "source_checkpoint": preflight_proof.get("source_checkpoint"),
        "checkpoint_raw_sha256_verified": preflight_proof.get("checkpoint_raw_sha256_verified"),
        "checkpoint_expected_semantic_state_hash": recipe["checkpoint_semantic_state_hash"],
        "checkpoint_expected_matrix_hash": expected["matrix_hash"],
        "v24916_preflight": dict(preflight_proof),
        "v24917_strict": {
            "semantic_state_hash": semantic_state_hash(snapshot),
            "matrix_hash": snapshot.get("matrix_hash"),
            "snapshot_state_hash_diagnostic": snapshot.get("state_hash"),
            "matrix_count": len(matrix_rows),
            "matrix_rows": copy.deepcopy(matrix_rows),
        },
        "changed_semantic_fields": diffs,
        "source_original_accepted_snapshot": "CHECKPOINT_SIDECAR_SEVEN_HASHES",
        "original_per_matrix_sha_available": False,
        "com_path_export_calls": 0,
        "path_enumeration_calls": 0,
        "td_evaluations_executed_by_this_proof": 0,
        "authority_decision": "CONTINUE_ONLY_IF_EXACT" if exact else "FAIL_CLOSED_NO_TD",
    }
    target = Path(folder) / "A0001_MATRIX_REOPEN_FORENSICS.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    try:
        tmp.write_text(json.dumps(row, ensure_ascii=False, indent=2, allow_nan=False)
                       + "\n", encoding="utf-8")
        tmp.replace(target)
    finally:
        tmp.unlink(missing_ok=True)
    return row


def check_snapshot(snapshot, recipe):
    """Same-release semantic fields; do not use cross-release state-hash equality."""
    check_fields(snapshot, recipe, "LIVE_SNAPSHOT")


def load_continuation(paths, recipe, hash_reference):
    """Use the original calibration reference and honest accepted STEP1 record."""
    run = read_json(paths["run_status"])
    require(run.get("status") in recipe["source_run_status_allowed"], "SOURCE_RUN_STATUS_UNEXPECTED")
    require(run.get("accepted_count") == 1, "SOURCE_ACCEPTED_COUNT_MISMATCH")
    require(len(run.get("demand_cycles") or ()) == 1, "SOURCE_CYCLE_COUNT_MISMATCH")
    cycle = run["demand_cycles"][0]
    require(cycle.get("cycle") == 1 and cycle.get("generation_completed") is True and
            cycle.get("generation_changed") is True and cycle.get("td_completed") is False,
            "SOURCE_INCOMPLETE_CYCLE_MISMATCH")
    require(cycle.get("state_hash_start") == recipe["epoch_origin_snapshot_state_hash"],
            "SOURCE_ORIGIN_STATE_MISMATCH")
    generation = cycle.get("generation") or {}
    expected = recipe["expected_generation_record"]
    for key in ("status", "adopted_in_place", "search_complete", "early_stop_policy"):
        require(generation.get(key) == expected[key], "GENERATION_RECORD_MISMATCH:" + key)
    require((generation.get("candidate") or {}).get("scale") == expected["candidate_scale"],
            "GENERATION_ACCEPTED_STEP_MISMATCH")
    basis = (generation.get("path_epoch_transition") or {}).get("basis_hash")
    require(basis == recipe["path_epoch"]["basis_hash"], "GENERATION_PATH_BASIS_MISMATCH")
    latest = run.get("latest_accepted_checkpoint") or {}
    # Real 2026-10-30 RUN_STATUS has a flat {path, sha256, size} record.
    # Do not confuse it with the separately uploaded SLOT_A wrapper.
    require(latest.get("path", "").replace("\\", "/").split("/")[-1] ==
            recipe["checkpoint_filename"], "RUN_LATEST_CHECKPOINT_MISMATCH")
    require(latest.get("sha256") == recipe["expected_checkpoint_raw_sha256"],
            "RUN_LATEST_CHECKPOINT_SHA_MISMATCH")
    reference = read_json(paths["reference"])
    require(isinstance(reference, dict) and
            reference.get("schema") == "R1_15A2_SHARED_OBJECTIVE_V22", "REFERENCE_SCHEMA_MISMATCH")
    digest = hash_reference(reference)
    require(digest == recipe["generation_reference_hash"], "REFERENCE_FIXED_OBJECTIVE_HASH_MISMATCH")
    require((generation.get("objective_after") or {}).get("reference_hash") == digest,
            "GENERATION_OBJECTIVE_REFERENCE_MISMATCH")
    continuation = {
        "enabled": True, "mode": MODE, "accepted_count": 1,
        "next_outer_cycle": 1, "inherited_outer_cycles": 0,
        "max_lineage_outer_cycle": 100, "inherited_stationary_cycle_streak": 0,
        "inherited_completed_demand_cycles": 0,
        "resume_substep": "TD_FINECDF_V17", "resume_outer_cycle": 1,
        "resume_generation_completed": True, "resume_td_completed": False,
        "resume_generation_changed": True,
        "resume_generation_record": copy.deepcopy(generation),
        "generation_reference": copy.deepcopy(reference),
        "generation_reference_sha256": digest,
        "semantic_state_hash": recipe["checkpoint_semantic_state_hash"],
        "source_role": "VERIFIED_ACCEPTED_A0001_POST_GENERATION_PRE_TD",
        "source_version": str(paths["checkpoint"]),
        "bounded_inner_budget_stop_reasons": [
            "MAX_ITERATIONS", "TD_EVALUATION_BUDGET", "TD_INNER_TIME_BUDGET"],
        "continue_bounded_budget_without_accepted_change": True,
        "bounded_budget_counts_as_stationarity": False,
        "supply_unlock_criterion": "EXISTING_JOINT_DEMAND_STATIONARITY_ONLY",
        "no_path_enumeration": True,
    }
    return continuation


def validate_continuation(cfg, recipe):
    row = cfg.get("runtime_demand_continuation") or {}
    require(row.get("mode") == MODE and row.get("enabled") is True,
            "CONTINUATION_MODE_MISMATCH")
    for key, expected in (("accepted_count", 1), ("next_outer_cycle", 1),
                          ("inherited_outer_cycles", 0), ("resume_outer_cycle", 1),
                          ("resume_substep", "TD_FINECDF_V17"),
                          ("resume_generation_completed", True),
                          ("resume_generation_changed", True),
                          ("resume_td_completed", False),
                          ("max_lineage_outer_cycle", 100),
                          ("semantic_state_hash", recipe["checkpoint_semantic_state_hash"])):
        require(row.get(key) == expected, "CONTINUATION_INVALID:" + key)
    gen = row.get("resume_generation_record") or {}
    require(gen.get("status") == "ACCEPTED" and gen.get("adopted_in_place") is True and
            gen.get("search_complete") is False and
            gen.get("early_stop_policy") == "STEP1_FIRST_ELIGIBLE_KEPT",
            "CONTINUATION_GEN_ACCEPTANCE_NOT_PROVEN")
    require(row.get("generation_reference_sha256") == recipe["generation_reference_hash"],
            "CONTINUATION_FIXED_REFERENCE_MISMATCH")
    return copy.deepcopy(row)


def verify_legacy_profile_hits(collector):
    """Prove profile-index attribution for a non-persistent V24916 path store.

    That store has no observation_authority_hash/profile_order_hash metadata:
    these fields are added by PersistentPathCacheManager.publish(), which was
    disabled in the failed source run. Instead, reconstruct each stored
    profile_hit from its immutable geometry edge IDs and the live ordered
    12D profile edge keys. The entire comparison is a read-only SQL scan;
    no COM path list, path export or native assignment is invoked.
    """
    from collections import Counter
    from r1_15a2_two_mode_v238 import _unpacked
    from r1_15a2_supply import SupplyContractError

    conn = collector.db
    rows = conn.execute("SELECT gid,edge_ids,edge_count FROM geometry ORDER BY gid")
    hits = iter(conn.execute(
        "SELECT gid,profile_index,multiplicity FROM profile_hits ORDER BY gid,profile_index"))
    current_hit = next(hits, None)
    routes = rows_checked = links_checked = 0
    for gid, blob, edge_count in rows:
        gid = int(gid)
        sequence = _unpacked(blob)
        if len(sequence) != int(edge_count):
            raise SupplyContractError("A0001_RESUME_GEOMETRY_EDGE_COUNT_MISMATCH")
        expected = Counter()
        for eid in sequence:
            eid = int(eid)
            if not 0 < eid < len(collector.edge_keys):
                raise SupplyContractError("A0001_RESUME_GEOMETRY_EDGE_ID_INVALID")
            key = collector.edge_keys[eid]
            for profile_index in collector.profile_index_by_key.get(key, ()):
                expected[int(profile_index)] += 1
        while current_hit is not None and int(current_hit[0]) == gid:
            index = int(current_hit[1])
            multiplicity = int(current_hit[2])
            if expected.pop(index, None) != multiplicity or multiplicity <= 0:
                raise SupplyContractError(
                    "A0001_RESUME_PROFILE_HITS_STATIC_AUTHORITY_MISMATCH")
            rows_checked += 1
            current_hit = next(hits, None)
        if expected or (current_hit is not None and int(current_hit[0]) < gid):
            raise SupplyContractError("A0001_RESUME_PROFILE_HITS_STATIC_AUTHORITY_MISMATCH")
        routes += 1
        links_checked += len(sequence)
    if current_hit is not None or routes <= 0:
        raise SupplyContractError("A0001_RESUME_PROFILE_HITS_STATIC_AUTHORITY_MISMATCH")
    return {"method": "RECONSTRUCT_PROFILE_HITS_FROM_READ_ONLY_GEOMETRY",
            "passes": True, "routes_checked": routes,
            "links_checked": links_checked, "hit_rows_checked": rows_checked,
            "com_path_export_calls": 0}


def restore_readonly_path_epoch(adapter, diag, snapshot, paths, recipe, output_folder,
                                collector_type=None):
    """Reopen original SQLite in read-only mode; validate original B basis."""
    from r1_15a2_two_mode_v238 import DEFAULT_SETTINGS, TwoModeRouteCollector
    require(adapter.cache is None and adapter.path_epoch_index == 0,
            "PATH_CACHE_ALREADY_ACTIVE")
    check_snapshot(snapshot, recipe)
    require(adapter.cfg.get("performance", {}).get("path_epochs", {}).get("enabled") is True,
            "PATH_EPOCH_POLICY_DISABLED")
    require(adapter.persistent_path_cache.enabled is False,
            "PERSISTENT_POLICY_CHANGED")
    require(paths["sqlite"].is_file(), "PATH_STORE_MISSING")
    links_live = adapter.read_links()
    links = {k: {field: value for field, value in row.items() if field != "object"}
             for k, row in links_live.items()}
    settings = dict(DEFAULT_SETTINGS, **adapter.cfg["two_mode"])
    settings["dseg_path_volume_relative_tolerance"] = adapter.cfg["dseg_path_volume_relative_tolerance"]
    settings["com_retry_policy"] = dict(adapter.cfg.get("com_resilience", {}) or {})
    seq = adapter.cfg["supply"].get("sequence", {})
    cls = collector_type or TwoModeRouteCollector
    collector = None
    try:
        collector = cls.open_existing(
            diag["d12"]["rows"], adapter.policy, links, paths["sqlite"], settings,
            adapter.control, duplicate_scope_policy=seq.get(
                "design_only_duplicate_scope_policy", "DIAGNOSTIC_EXCLUDE_CONFLICTED_DRIVERS"),
            max_unique_sequences=seq.get("max_unique_sequences", 100000),
            max_pairs_per_market=seq.get("max_pairs_per_market", 64),
            read_only=True, require_profile_metadata=False)
        profile_proof = verify_legacy_profile_hits(collector)
        require(collector.parent_hash == recipe["epoch_origin_snapshot_state_hash"],
                "PATH_STORE_ORIGIN_MISMATCH")
        require(collector.path_basis_hash() == recipe["path_epoch"]["basis_hash"],
                "PATH_STORE_BASIS_MISMATCH")
        require(collector.path_basis_comparison_hash() == recipe["path_epoch"]["comparison_basis_hash"],
                "PATH_STORE_COMPARISON_MISMATCH")
        require(collector.incidence_ready, "PATH_STORE_INCIDENCE_INCOMPLETE")
        audit = collector.rebind_profiles(diag["d12"]["rows"], refresh_drivers=False)
        current = snapshot.get("addval1") or {}
        for key, row in links.items():
            link_id = "|".join(str(int(x)) for x in key)
            require(link_id in current, "PATH_STORE_ADDVAL_KEY_MISSING")
            row["addval1"] = float(current[link_id])
        origin = {name: recipe["epoch_origin_semantic_hashes"][name] for name in (
            "fixed_link_hash", "dseg_hash", "operations_hash", "addval_hash",
            "matrix_hash", "generation_hash", "td_hash")}
        origin["state_hash"] = recipe["epoch_origin_snapshot_state_hash"]
        adapter.cache_snapshot = origin
        adapter.cache_live_snapshot = snapshot
        adapter.cache_links = links
        adapter.cache = collector
        adapter.path_epoch_index = 1
        adapter.path_epoch_accepts = 1
        adapter.path_epoch_history.append({
            "epoch": 1, "origin_state_hash": collector.parent_hash,
            "live_state_hash": snapshot["state_hash"],
            "basis_hash": recipe["path_epoch"]["basis_hash"],
            "comparison_basis_hash": recipe["path_epoch"]["comparison_basis_hash"],
            "restored_cross_run": True, "policy": "A0001_READ_ONLY_ORIGINAL_SQLITE_NO_COM_PATH_EXPORT",
        })
        record = {
            "release": RELEASE, "status": "VERIFIED_ORIGINAL_PATH_EPOCH_RESTORED",
            "store": str(paths["sqlite"]), "read_only": True,
            "path_enumeration_calls": 0, "path_export_calls": 0,
            "origin_state_hash": collector.parent_hash,
            "basis_hash": collector.path_basis_hash(),
            "comparison_basis_hash": collector.path_basis_comparison_hash(),
            "profile_rebind": audit, "legacy_profile_hits_proof": profile_proof,
        }
        from r1_15a2_two_mode_v238 import atomic_json
        atomic_json(Path(output_folder) / "A0001_PATH_EPOCH_RESTORE.json", record)
        return record
    except BaseException:
        if collector is not None:
            collector.close()
        raise


def refuse_enumeration(*args, **kwargs):
    from r1_15a2_supply import SupplyContractError
    raise SupplyContractError("A0001_RESUME_NO_PATH_ENUMERATION_ALLOWED:"
                              "fresh path export required for support/plateau; "
                              "the existing accepted checkpoint remains authoritative")



def install_sibling_run_layout_guard(v16, checkpoint, print_fn=print):
    """Allow a NEW direct RUN_* sibling under V16_RUNS; refuse actual nesting.

    The historical parent postcondition rejects ANY descendant of a detected
    _RUNS root, including valid direct siblings. This resume-only hook fixes
    the postcondition, without changing the frozen V24916 project resolver.
    """
    cp = Path(checkpoint).resolve()
    source_run = cp.parent.parent.parent  # RUN_OLD/CALIBRATION/CHECKPOINTS/file.ver
    source_runs_root = source_run.parent
    require(source_run.name.upper().startswith("RUN_"),
            "SOURCE_RUN_DIRECTORY_NOT_RECOGNIZED")
    require(source_runs_root.name.upper() == "R1_15A2_V16_RUNS",
            "SOURCE_RUNS_ROOT_NOT_RECOGNIZED")
    resolver = getattr(v16, "_base_layout", None)
    require(callable(resolver), "SOURCE_LAYOUT_RESOLVER_UNAVAILABLE")
    layout = resolver(cp)  # frozen ORIGINAL resolver, not the wrapped one
    require(isinstance(layout, dict) and layout.get("project_base") is not None,
            "SOURCE_LAYOUT_INVALID")
    project_base = source_runs_root.parent.resolve()
    require(Path(layout["project_base"]).resolve() == project_base,
            "SOURCE_LAYOUT_PROJECT_BASE_MISMATCH")
    detected_roots = tuple(
        Path(p).resolve() for p in layout.get("detected_run_roots_nearest_first", ())
    )
    require(detected_roots and detected_roots[-1] == source_runs_root,
            "SOURCE_LAYOUT_RUNS_ROOT_MISMATCH")
    runs_name = str(getattr(v16, "RUNS_ROOT_NAME", "") or "")
    require(runs_name == "R1_15A2_V16_RUNS", "OUTPUT_RUNS_ROOT_NAME_CHANGED")
    output_root = (project_base / runs_name).resolve()
    require(output_root == source_runs_root, "OUTPUT_RUNS_ROOT_NOT_SIBLING_ROOT")
    original_guard = getattr(v16.parent, "_assert_new_run_is_not_nested", None)
    require(callable(original_guard), "PARENT_NESTED_RUN_GUARD_MISSING")

    def assert_new_run_is_direct_sibling(new_run_directory, prior_run_roots):
        new_run = Path(new_run_directory).resolve()
        require(new_run.parent == output_root,
                "NEW_RUN_NOT_DIRECT_SIBLING:" + str(new_run))
        require(new_run.name.upper().startswith("RUN_") and new_run != source_run,
                "NEW_RUN_NAME_OR_SOURCE_COLLISION")
        roots = tuple(Path(p).resolve() for p in prior_run_roots)
        require(roots == detected_roots, "PRIOR_RUN_ROOTS_CHANGED")
        # Other ancestor RUNS trees remain prohibited (doubly nested history).
        for root in roots:
            if root == output_root:
                continue  # ONLY this direct-sibling relation is permitted.
            try:
                new_run.relative_to(root)
            except ValueError:
                continue
            raise RuntimeError(
                "A0001_RESUME_NEW_RUN_NESTED_UNDER_OTHER_RUN_TREE:" + str(root))
        return None

    v16.parent._assert_new_run_is_not_nested = assert_new_run_is_direct_sibling
    print_fn("A0001 output is a sibling RUN_* under: " + str(output_root))
    return {
        "policy": "EXACT_SOURCE_RUN_TREE__NEW_RUN_DIRECT_SIBLING_ONLY",
        "source_run": str(source_run),
        "runs_root": str(output_root),
        "project_base": str(project_base),
        "source_checkpoint": str(cp),
        "source_is_in_existing_run": True,
        "new_run_must_be_sibling": True,
        "original_parent_guard_is_incorrect_for_same_RUNS_root": True,
    }


def install_resume(v16, checkpoint, recipe, paths, continuation, print_fn=print):
    """Bind hooks to actual V24916 parent after the normal V24917 installer."""
    output_layout = install_sibling_run_layout_guard(v16, checkpoint, print_fn=print_fn)
    base_install = v16._install_runtime
    base_preflight = v16._run_live_preflight
    preflight_proof = {}

    def checked_preflight(*args, **kwargs):
        report, manifest = base_preflight(*args, **kwargs)
        # Provenance checks and six exact fields happen before any working-copy writes.
        require(report.get("passes") is True and
                (report.get("semantic_before_after") or {}).get("passes") is True,
                "LIVE_V24916_PREFLIGHT_NOT_STABLE")
        require(Path(report.get("current_version_file", "")).resolve() ==
                paths["checkpoint"], "LIVE_SOURCE_VERSION_CHANGED")
        require(report.get("source_raw_ver_sha256_provenance_only") ==
                recipe["expected_checkpoint_raw_sha256"], "LIVE_CHECKPOINT_BYTES_CHANGED")
        proof = check_live_semantic({
            "semantic_state_hash": report.get("source_semantic_state_hash"),
            "semantic_hashes": report.get("source_semantic_hashes")},
            recipe, permit_v24916_matrix_deferral=True)
        preflight_proof.clear()
        preflight_proof.update(proof)
        preflight_proof["source_checkpoint"] = str(paths["checkpoint"])
        preflight_proof["checkpoint_raw_sha256_verified"] = True
        return report, manifest

    def installer(*args, **kwargs):
        result = base_install(*args, **kwargs)
        import r1_15a2_overnight_controller_coupled_v24915p2_force100 as coupled
        from r1_15a2_supply import canonical_hash
        parent = v16.parent
        old_parser = coupled._runtime_demand_continuation
        old_run = parent.run_overnight_calibration_coupled

        def parser(cfg):
            if (cfg.get("runtime_demand_continuation") or {}).get("mode") == MODE:
                return validate_continuation(cfg, recipe)
            return old_parser(cfg)

        def resumed_run(adapter, cfg, folder, control, package_root):
            require(cfg.get("coupled_demand", {}).get("max_outer_cycles") == 100,
                    "CONFIG_CYCLE_BUDGET_CHANGED")
            require(adapter.cache is None, "CACHE_ALREADY_INITIALIZED")
            require(preflight_proof.get("checkpoint_raw_sha256_verified") is True,
                    "V24916_PREFLIGHT_PROOF_NOT_AVAILABLE")
            # This V24917 reader bypasses candidate readback cache and tests
            # the real live matrix values, not a legacy V24916 hash or a label.
            snapshot = adapter.generation_guard_snapshot()
            require(snapshot.get("state_hash") is not None,
                    "LIVE_SNAPSHOT_UNAVAILABLE")
            audit = publish_matrix_reopen_audit(
                folder, snapshot, recipe, preflight_proof)
            print_fn("A0001 MATRIX REOPEN: " + audit["status"] +
                     " changed=" + ",".join(audit["changed_semantic_fields"]) +
                     " expected=" + recipe["checkpoint_semantic_hashes"]["matrix_hash"] +
                     " actual=" + str(snapshot.get("matrix_hash")))
            require(audit["status"] == "EXACT_V24917_CHECKPOINT",
                    "V24917_REOPENED_MATRIX_AUTHORITY_MISMATCH")
            check_snapshot(snapshot, recipe)
            require(canonical_hash(continuation["generation_reference"]) ==
                    recipe["generation_reference_hash"], "REFERENCE_CHANGED")
            cfg["runtime_demand_continuation"] = copy.deepcopy(continuation)
            adapter.cfg["runtime_demand_continuation"] = copy.deepcopy(continuation)
            orig_diagnostics = adapter.diagnostics
            used = {"baseline": False}

            def guarded_diagnostics(diag_folder, label="CURRENT"):
                diag = orig_diagnostics(diag_folder, label=label)
                if label == "BASELINE":
                    require(not used["baseline"], "DUPLICATE_BASELINE")
                    state = adapter.snapshot()
                    check_snapshot(state, recipe)
                    restore_readonly_path_epoch(
                        adapter, diag, state, paths, recipe, Path(folder) / "RESUME_EVIDENCE")
                    used["baseline"] = True
                return diag

            adapter.diagnostics = guarded_diagnostics
            # All unexpected attempts to build/refresh any path epoch fail closed.
            adapter._build_cache = refuse_enumeration
            return old_run(adapter, cfg, folder, control, package_root)

        coupled._runtime_demand_continuation = parser
        parent.run_overnight_calibration_coupled = resumed_run
        print_fn("A0001 resume installed: cycle 1 TD, read-only SQLite, zero COM path exports")
        return result

    v16._run_live_preflight = checked_preflight
    v16._install_runtime = installer
    return {"release": RELEASE, "checkpoint": str(checkpoint),
            "source_path_store": str(paths["sqlite"]), "mode": MODE,
            "output_layout": output_layout}

"""Offline contract test for standalone fresh V24917 optimized calibration."""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
import r1_15a2_fresh_universal_v24917 as fresh
import r1_15a2_targeted_generation_v24917 as tg


def source(tmp_path, relative="BASE/original.ver"):
    p = tmp_path / relative
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"test-only-Visum-version")
    return p


def valid_options():
    return {"td_joint_enabled": True, "td_inner_mode": "DYNAMIC",
            "td_first_cycle": True, "school_td_enabled": True,
            "long_composite_td_enabled": True,
            "td_policy": "ALWAYS", "td_every_n_cycles": 1,
            "td_during_catchup": True,
            "mg_enabled": True, "mg_min_ratio": 0.75,
            "mg_max_ratio": 2.5}


def valid_cfg():
    return {"v24917_targeted_generation": copy.deepcopy(tg.DEFAULT_POLICY),
            "fresh100_overlay": {
        "source_ver_is_new_baseline": True, "start_outer_cycle": 1,
        "accepted_count_start": 0, "continuation_from_prior_run": False,
        "fresh_path_enumeration_required": True,
        "cross_run_path_cache_restore": False,
        "legacy_path_cache_import": False}}


def runtime_status():
    return {"v24917": {
        "demand_policy": {"installed": True, "note": {
            "options": {"td_policy": "ALWAYS", "td_every_n_cycles": 1,
                        "td_during_catchup": True, "td_first_cycle": True,
                        "mg_enabled": True, "mg_min_ratio": 0.75,
                        "mg_max_ratio": 2.5}}},
        "tdjoint1": {"installed": True, "release": "TDJOINT",
                     "options": {"enabled": True, "long_enabled": True,
                                 "school_enabled": True, "inner_mode": "DYNAMIC"}},
        "td_numpy": {"installed": True, "release": "TDNUMPY"},
        "td_restore": {"installed": True, "release": "REVIEW1_NATIVE_PROOF"},
        "path_store_build": {"installed": True, "release": "PATH_BUILD"}}}


def test_any_compatible_source_is_fresh_baseline_without_specific_checkpoint(tmp_path):
    original = source(tmp_path)
    assert fresh.true_project_base(original) == original.parent
    assert fresh.sandbox_for(original) == original.parent / fresh.SANDBOX_NAME
    nested = source(tmp_path, "BASE/R1_15A2_V16_RUNS/RUN_OLD/CALIBRATION/CHECKPOINTS/ACCEPTED_B_0099.ver")
    assert fresh.true_project_base(nested) == tmp_path / "BASE"
    assert fresh.sandbox_for(nested) == tmp_path / "BASE" / fresh.SANDBOX_NAME
    assert not fresh.path_is_under(fresh.sandbox_for(nested), nested.parent.parent.parent)


def test_bad_or_recursive_source_fails_before_any_runtime_install(tmp_path):
    with pytest.raises(RuntimeError, match="OPEN_EXISTING_VER_FIRST"):
        fresh.sandbox_for(tmp_path / "UNKNOWN.ver")
    nested = source(tmp_path, "BASE/R1FRESH17/a.ver")
    with pytest.raises(RuntimeError, match="SOURCE_INSIDE_OUTPUT_SANDBOX"):
        fresh.sandbox_for(nested)
    base = tmp_path / "OTHER_BASE"
    ext = tmp_path / "OTHER"
    ext.mkdir()
    base.mkdir(exist_ok=True)
    (base/"R1FRESH17").symlink_to(ext, target_is_directory=True)
    with pytest.raises(RuntimeError, match="SYMLINKED_SANDBOX_FORBIDDEN"):
        fresh.sandbox_for(source(tmp_path, "OTHER_BASE/other.ver"))


@pytest.mark.parametrize("change", [
    ("fresh100_overlay","start_outer_cycle", 2),
    ("fresh100_overlay","accepted_count_start", 8),
    ("fresh100_overlay","cross_run_path_cache_restore", True),
    ("fresh100_overlay","fresh_path_enumeration_required", False),
])
def test_start_is_not_resume(change):
    cfg = valid_cfg()
    section, key, value = change
    cfg[section][key] = value
    with pytest.raises(RuntimeError):
        fresh.validate_fresh_config(cfg, valid_options())


@pytest.mark.parametrize("name", [
    "td_joint_enabled", "td_first_cycle", "school_td_enabled",
    "long_composite_td_enabled"])
def test_requested_optimized_td_is_enabled(name):
    opts = valid_options(); opts[name] = False
    with pytest.raises(RuntimeError):
        fresh.validate_fresh_config(valid_cfg(), opts)


def test_runtime_must_install_reviewed_restore_not_old_wrapper():
    item = runtime_status()
    assert set(fresh.verify_runtime_status(item)) == {
        "demand_policy", "tdjoint1", "td_numpy", "td_restore", "path_store_build"}
    item["v24917"]["td_restore"]["release"] = "OLD_SKIP_UNVERIFIED"
    with pytest.raises(RuntimeError, match="TD_RESTORE_SAFETY_REVIEW_MISSING"):
        fresh.verify_runtime_status(item)

    item = runtime_status()
    item["v24917"]["tdjoint1"]["options"]["school_enabled"] = False
    with pytest.raises(RuntimeError, match="EFFECTIVE_TD_OPTIMIZATION_DISABLED"):
        fresh.verify_runtime_status(item)



@pytest.mark.parametrize("field,value", [
    ("td_policy", "EVERY_N"), ("td_policy", "OFF"),
    ("td_every_n_cycles", 3), ("td_during_catchup", False),
])
def test_fresh_start_rejects_any_td_skip_setting(field, value):
    opts = valid_options()
    opts[field] = value
    with pytest.raises(RuntimeError, match="TD_EVERY_CYCLE_POLICY_REQUIRED"):
        fresh.validate_fresh_config(valid_cfg(), opts)


@pytest.mark.parametrize("field,value", [
    ("td_policy", "EVERY_N"), ("td_policy", "OFF"),
    ("td_every_n_cycles", 3), ("td_during_catchup", False),
    ("td_first_cycle", False),
])
def test_runtime_rejects_effective_td_skip_overrides(field, value):
    status = runtime_status()
    status["v24917"]["demand_policy"]["note"]["options"][field] = value
    with pytest.raises(RuntimeError, match="EFFECTIVE_TD_EVERY_CYCLE_POLICY_MISMATCH"):
        fresh.verify_runtime_status(status)


def test_options_file_explicitly_schedules_native_td_every_cycle():
    from r1_15a2_demand_policy_v1 import load_options
    options = load_options(root=Path(__file__).resolve().parents[1], environ={})
    assert options["td_policy"] == "ALWAYS"
    assert options["td_every_n_cycles"] == 1
    assert options["td_during_catchup"] is True
    assert options["td_first_cycle"] is True
    assert options["td_inner_mode"] == "DYNAMIC"
    assert options["td_count_weight"] == 0.6
    assert options["td_inner_max_evaluations"] == 60
    assert options["mg_max_ratio"] == 2.5


def test_actual_demand_policy_runs_td_for_every_one_of_100_cycles_even_in_catchup(monkeypatch):
    import r1_15a2_demand_policy_v1 as dp
    options = dp.load_options(root=Path(__file__).resolve().parents[1], environ={})
    policy = dp.DemandPolicy(options)
    monkeypatch.setattr(dp, "catchup_phase", lambda cfg, diag: ("CATCH_UP", 0.60))
    actual_calls = []

    def genuine_td(adapter, cfg, folder, control, state, diag, root, outer_cycle=None):
        actual_calls.append(outer_cycle)
        return False, state, diag, {
            "inner": {"search_complete": True, "progress_continue": False},
            "td_realization_complete": True,
        }

    wrapped = dp.wrap_td(genuine_td, policy, NS())
    adapter = NS(v24917_status={})
    state, diag = {"state_hash": "accepted"}, {"d12": {"rows": []}}
    for outer in range(1, 101):
        # Exercise both accepted and unaccepted TG transitions.
        policy.note_generation(outer % 2 == 0,
                               {"search_complete": True, "stationarity_confirmed": True})
        changed, returned_state, returned_diag, rec = wrapped(
            adapter, {}, Path("unused"), NS(), state, diag, Path("unused"),
            outer_cycle=outer)
        assert changed is False
        assert returned_state is state and returned_diag is diag
        assert rec["td_run_policy_reason"] == "ALWAYS"
    assert actual_calls == list(range(1, 101))
    assert policy.td_calls == 100
    assert all(rec["td_ran"] for rec in policy.records)


def test_environment_overrides_cannot_silently_make_this_fresh_run_sparse():
    from r1_15a2_demand_policy_v1 import load_options
    folder = Path(__file__).resolve().parents[1]
    effective = load_options(root=folder, environ={
        "R1_TD_POLICY": "EVERY_N", "R1_TD_EVERY_N": "3",
        "R1_TD_DURING_CATCHUP": "false",
    })
    status = runtime_status()
    status["v24917"]["demand_policy"]["note"]["options"] = effective
    with pytest.raises(RuntimeError, match="EFFECTIVE_TD_EVERY_CYCLE_POLICY_MISMATCH"):
        fresh.verify_runtime_status(status)



@pytest.mark.parametrize("field,value", [
    ("mg_max_ratio", 2.0), ("mg_min_ratio", 0.6),
    ("mg_enabled", False),
])
def test_fresh_start_rejects_inconsistent_ws_production_mobility_band(field, value):
    opts = valid_options()
    opts[field] = value
    with pytest.raises(RuntimeError, match="WORK_SERVICE_MOBILITY2_BAND_MISMATCH"):
        fresh.validate_fresh_config(valid_cfg(), opts)


@pytest.mark.parametrize("role,upper", [("PROD", 2.0), ("ATT", 2.0)])
def test_fresh_start_rejects_old_generation_upper_bounds(role, upper):
    cfg = valid_cfg()
    cfg["v24917_targeted_generation"]["envelope"]["domestic_hard_by_role"][role][1] = upper
    with pytest.raises(RuntimeError, match="WORK_SERVICE_PA_BOUNDS_NOT_INSTALLED"):
        fresh.validate_fresh_config(cfg, valid_options())


def test_runtime_rejects_environment_override_of_ws_mobility_band():
    status = runtime_status()
    status["v24917"]["demand_policy"]["note"]["options"]["mg_max_ratio"] = 2.0
    with pytest.raises(RuntimeError, match="EFFECTIVE_MOBILITY2_WS_PRODUCTION_BAND_MISMATCH"):
        fresh.verify_runtime_status(status)


def native_adapter(runs, *, native_fails=False):
    calls = []
    class Native:
        def __init__(self):
            self.path_epoch_index = 0
            self.path_epoch_history = []
            self.cache = None
            self.persistent_cache_manifest = None
            self.persistent_path_cache = NS(enabled=False)
            self.cfg = {"runtime_legacy_path_cache_roots": []}
        def _build_cache(self, diag, folder, snapshot, *,
                         build_sequence_evidence=False,
                         allow_persistent_restore=True):
            calls.append((Path(folder), allow_persistent_restore))
            if native_fails:
                raise RuntimeError("TEST_EXPORTER_FAILURE")
            db = Path(folder) / "TWO_MODE_PATH_STORE.sqlite"
            db.parent.mkdir(parents=True, exist_ok=True)
            db.write_bytes(b"test native path store")
            collector = NS(route_db_path=str(db), incidence_ready=True,
                           read_only=False, path_basis_hash=lambda: "basis")
            self.path_epoch_index += 1
            self.cache = collector
            self.path_epoch_history.append({"epoch": self.path_epoch_index})
            return collector, {}, {"real_native_export": True}
    return Native, calls


def test_new_epoch_is_genuine_local_sqlite_not_cross_run_restore(tmp_path):
    sandbox = tmp_path / "R1FRESH17"
    runs = sandbox / fresh.RUNS_NAME
    native, calls = native_adapter(runs)
    fresh.install_native_epoch_guard(native, sandbox)
    adapter = native()
    first = runs / "RUN_NEW" / "CALIBRATION" / "DEMAND_CYCLE_01_GENERATION" / "GENERATION_CACHE"
    result = adapter._build_cache({}, first, {"state_hash": "live0"})
    assert result[2]["real_native_export"]
    assert calls == [(first, False)]
    assert adapter.path_epoch_index == 1
    rec = json.loads((first / "FRESH_UNIVERSAL_NATIVE_EPOCH.json").read_text())
    assert rec["status"] == "FRESH_NATIVE_ENUMERATION_VERIFIED"
    assert rec["allow_persistent_restore_passed_to_native"] is False
    assert Path(rec["sqlite"]).is_file()
    second = runs / "RUN_NEW" / "CALIBRATION" / "PATH_EPOCHS" / "NEXT"
    adapter._build_cache({}, second, {"state_hash": "live1"})
    assert adapter.path_epoch_index == 2
    assert calls[-1] == (second, False)


def test_first_epoch_cannot_inherit_cache_or_read_other_run(tmp_path):
    sandbox = tmp_path / "R1FRESH17"
    native, calls = native_adapter(sandbox / fresh.RUNS_NAME)
    fresh.install_native_epoch_guard(native, sandbox)
    adapter = native()
    safe = sandbox / fresh.RUNS_NAME / "RUN_NEW" / "CALIBRATION" / "DEMAND_CYCLE_01_GENERATION" / "GENERATION_CACHE"
    adapter.persistent_path_cache.enabled = True
    with pytest.raises(RuntimeError, match="PERSISTENT_CACHE_MUST_BE_DISABLED"):
        adapter._build_cache({}, safe, {"state_hash": "live"})
    adapter.persistent_path_cache.enabled = False
    adapter.cache = NS(route_db_path=str(tmp_path/"old.sqlite"))
    with pytest.raises(RuntimeError, match="INITIAL_CACHE_NOT_EMPTY"):
        adapter._build_cache({}, safe, {"state_hash": "live"})
    adapter.cache = None
    with pytest.raises(RuntimeError, match="OUTSIDE_OWN_RUN"):
        adapter._build_cache({}, tmp_path/"OLD"/"CALIBRATION"/"GENERATION_CACHE",
                             {"state_hash": "live"})
    assert calls == []


def test_exporter_failure_is_not_misreported_as_success(tmp_path):
    sandbox = tmp_path / "R1FRESH17"
    native, _ = native_adapter(sandbox / fresh.RUNS_NAME, native_fails=True)
    fresh.install_native_epoch_guard(native, sandbox)
    target = sandbox / fresh.RUNS_NAME / "RUN_NEW" / "CALIBRATION" / "DEMAND_CYCLE_01_GENERATION" / "GENERATION_CACHE"
    with pytest.raises(RuntimeError, match="TEST_EXPORTER_FAILURE"):
        native()._build_cache({}, target, {"state_hash": "before"})
    rec = json.loads((target / "FRESH_UNIVERSAL_NATIVE_EPOCH.json").read_text())
    assert rec["status"] == "FAILED"


def test_relocate_parent_lock_workspace_without_touching_source(tmp_path):
    original = source(tmp_path)
    sandbox = fresh.sandbox_for(original)
    native, _ = native_adapter(sandbox/fresh.RUNS_NAME)
    class Parent:
        @staticmethod
        def load_config(mode):
            assert mode == "FULL"
            return valid_cfg()
    v16 = NS(
        RUNS_ROOT_NAME=fresh.RUNS_NAME, LOCK_NAME=".R1_15A2_V16.lock",
        _base_layout=lambda path: {"source_version": original,
            "project_base": original.parent, "mode": "SOURCE_PARENT",
            "detected_run_roots_nearest_first": [], "outermost_run_root": None},
        _install_runtime=lambda *args: runtime_status(),
        ActiveVisumAdapter=native, parent=Parent(),
        runtime_io_hotfix=NS(_ensure_parent=lambda p: Path(p).parent.mkdir(
            parents=True, exist_ok=True)))
    fresh.install(v16, original, sandbox, options=valid_options())
    original_layout, workspace = v16._isolated_workspace(original)
    assert workspace == sandbox/fresh.RUNS_NAME
    assert original_layout["project_base"] == sandbox
    assert v16._isolated_project_layout(original)["project_base"] == sandbox
    installed = v16._install_runtime(object(), {}, {}, workspace)
    assert installed["fresh_universal"]["fresh_contract"]["accepted_count_start"] == 0
    assert installed["fresh_universal"]["fresh_contract"]["td_skipping_allowed"] is False
    assert installed["fresh_universal"]["fresh_contract"]["td_policy"] == "ALWAYS"
    assert installed["fresh_universal"]["fresh_contract"]["generation_work_service_prod_bounds"] == [0.75, 2.5]
    assert installed["fresh_universal"]["fresh_contract"]["generation_work_service_att_bounds"] == [0.75, 4.0]
    assert installed["fresh_universal"]["path_epoch"]["native_export_only"]
    assert (workspace / "FRESH_UNIVERSAL_BOOTSTRAP_AUTHORITY.json").exists()
    assert not (original.parent/".R1_15A2_V16.lock").exists()


def test_detached_silent_only_writes_in_own_sandbox(tmp_path):
    import v24917_silent_debug as silent
    source_ver = source(tmp_path)
    sandbox = fresh.sandbox_for(source_ver)
    host = NS(IO=NS(CurrentVersionFile=str(source_ver)))
    def exercise():
        run = sandbox / fresh.RUNS_NAME / "RUN_FRESH"
        run.mkdir(parents=True)
        (run / "RUN_STATUS.json").write_text('{"status":"PROGRESS_CONTINUE_DEMAND"}')
        return {"status":"PROGRESS_CONTINUE_DEMAND"}
    result = fresh.run_silent_detached(host, tmp_path, exercise, sandbox, silent)
    assert result["status"] == "PROGRESS_CONTINUE_DEMAND"
    assert (sandbox / silent.DEBUG_NAME / "SILENT_LATEST_STATUS.json").is_file()
    assert list((sandbox / silent.DEBUG_NAME).glob("SILENT_*_DEBUG.zip"))
    assert not (source_ver.parent / silent.DEBUG_NAME).exists()

"""V2.4.7 frozen-path epoch calibration regressions.

These are offline/COM-shaped tests.  They verify controller and cache semantics,
not a real PTV Visum enumeration or assignment.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import MethodType

import numpy as np
import pytest

import r1_15a2_overnight_controller_v242 as coupled
from r1_15a2_safety_v247 import validate_v247_config
from r1_15a2_supply import SupplyContractError
from r1_15a2_trial_adapter_v240 import VisumAdapter as PathEpochAdapter
from test_supply_v22 import P, profile
from test_two_mode_v238 import authority, hierarchy, store
from test_v245_workflow import setup_workflow

ROOT = Path(__file__).resolve().parents[1]
PLATEAU = "LOCAL_PLATEAU_NOT_PROOF_OF_GLOBAL_OPTIMUM"


def test_v247_config_locks_path_epoch_method():
    cfg = json.loads((ROOT / "R1_15A2_CONFIG_V2_4_7.json").read_text(encoding="utf-8"))
    result = validate_v247_config(cfg, ROOT)
    assert result["passes"]
    pe = cfg["performance"]["path_epochs"]
    assert pe["enabled"] is True
    assert pe["initial_enumeration_required"] is True
    assert pe["refresh_trigger"] == "COMPLETE_LOCAL_PLATEAU_ON_CURRENT_PATH_BASIS"
    assert pe["fresh_assignment_acceptance_authority"] is True
    assert pe["new_positive_od_without_epoch_support_forces_reenumeration"] is True


def test_frozen_path_epoch_reweights_live_od_without_geometry_reexport(tmp_path):
    c = store(tmp_path, profiles=[profile(model=600)])
    try:
        c.add_parents("NATIVE_CW", "C", [[1, 2, 1, 600], [1, 2, 2, 400]],
                      authority([600, 400]))
        c.add_geometry("C", hierarchy())
        c.prepare_incidence_evidence()
        before_structure = c.path_structure_hash()
        before_geometry_rows = c.db.execute("SELECT COUNT(*) FROM geometry").fetchone()[0]
        live = np.zeros((2, 2), dtype=float)
        live[0, 1] = 2000.0
        result, summary = c.incidence({
            "expected_zones": 2,
            "path_export_dsegs": ["NATIVE_CW"],
            "mutable_dsegs": ["NATIVE_CW"],
            "mutable_relation_policy": "ALL_MUTABLE_RELATIONS",
        }, None, live_od_matrices={"NATIVE_CW": live})
        # Route 1 crosses the observed link and owns 60% of the frozen OD split.
        assert result["q_current"].tolist() == [2000.0]
        assert result["full_profile_model_from_paths"].tolist() == pytest.approx([1200.0])
        assert result["incidence_share"].tolist() == pytest.approx([0.6])
        assert summary["source"] == "FROZEN_PATH_EPOCH_LIVE_OD_REWEIGHT_NO_COM_REEXPORT"
        assert c.path_structure_hash() == before_structure
        assert c.db.execute("SELECT COUNT(*) FROM geometry").fetchone()[0] == before_geometry_rows
    finally:
        c.close()


def test_new_positive_od_without_frozen_support_forces_reenumeration(tmp_path):
    c = store(tmp_path, profiles=[profile(model=0)])
    try:
        c.add_parents("NATIVE_CW", "C", [[1, 2, 1, 0], [1, 2, 2, 0]],
                      authority([0, 0]))
        c.add_geometry("C", hierarchy())
        c.prepare_incidence_evidence()
        live = np.zeros((2, 2), dtype=float)
        live[0, 1] = 10.0
        with pytest.raises(SupplyContractError, match="PATH_EPOCH_NEW_POSITIVE_OD_REQUIRES_REENUMERATION"):
            c.incidence({
                "expected_zones": 2,
                "path_export_dsegs": ["NATIVE_CW"],
                "mutable_dsegs": ["NATIVE_CW"],
                "mutable_relation_policy": "ALL_MUTABLE_RELATIONS",
            }, None, live_od_matrices={"NATIVE_CW": live})
    finally:
        c.close()


def test_live_profile_rebind_changes_only_model_and_can_refresh_drivers(tmp_path):
    original = profile(model=600, obs=1000, ident="obs-a")
    c = store(tmp_path, profiles=[original])
    try:
        c.add_parents("NATIVE_CW", "C", [[1, 2, 1, 600], [1, 2, 2, 400]],
                      authority([600, 400]))
        c.add_geometry("C", hierarchy())
        c.prepare_incidence_evidence()
        rebound = profile(model=800, obs=1000, ident="obs-a")
        audit = c.rebind_profiles([rebound], refresh_drivers=True)
        assert audit["profile_count"] == 1
        assert audit["drivers_refreshed"] is True
        assert c.profiles[0]["model"] == 800
        changed_observation = profile(model=800, obs=999, ident="obs-a")
        with pytest.raises(SupplyContractError, match="OBSERVATION_AUTHORITY_CHANGED|STATIC_CONTRACT_CHANGED"):
            c.rebind_profiles([changed_observation], refresh_drivers=True)
    finally:
        c.close()


class FakeEpochCache:
    incidence_ready = True

    def __init__(self, basis, structure="structure"):
        self.basis = basis
        self.structure = structure
        self.closed = False

    def path_basis_hash(self):
        return self.basis

    def path_structure_hash(self):
        return self.structure

    def path_basis_comparison_hash(self):
        return self.basis

    def close(self):
        self.closed = True


def bare_epoch_adapter(basis="basis-0", structure="structure-0"):
    a = object.__new__(PathEpochAdapter)
    a.cfg = {"performance": {"path_epochs": {
        "enabled": True,
        "max_demand_reenumerations": 3,
        "max_supply_reenumerations": 3,
    }}}
    a.cache = FakeEpochCache(basis, structure)
    a.cache_links = {}
    a.cache_snapshot = {
        "state_hash": "state-0", "fixed_link_hash": "fixed",
        "dseg_hash": "dseg", "operations_hash": "ops", "addval1": {},
    }
    a.cache_live_snapshot = dict(a.cache_snapshot)
    a.initial_snapshot = None
    a.path_epoch_index = 1
    a.path_epoch_accepts = 0
    a.path_epoch_refresh_counts = {"DEMAND": 0, "SUPPLY": 0}
    a.path_epoch_plateau_verified = None
    a.path_epoch_history = []
    a.supply_path_proof = None
    a.telemetry = None
    return a


def test_accepted_state_change_retains_epoch_but_context_drift_fails_closed():
    a = bare_epoch_adapter()
    state = dict(a.cache_snapshot, state_hash="state-1")
    record = a.accepted_state_changed(state, reason="TG_ACCEPTED", phase="DEMAND")
    assert record["retained"] is True
    assert a.cache.path_basis_hash() == "basis-0"
    assert a.cache_live_snapshot["state_hash"] == "state-1"
    assert a.path_epoch_accepts == 1
    drift = dict(state, state_hash="state-2", fixed_link_hash="changed")
    with pytest.raises(SupplyContractError, match="PATH_EPOCH_IMMUTABLE_CONTEXT_CHANGED"):
        a.accepted_state_changed(drift, reason="BAD", phase="DEMAND")


def test_plateau_reenumerates_once_then_reuses_verified_fresh_epoch(tmp_path):
    a = bare_epoch_adapter()
    state = dict(a.cache_snapshot)
    bases = iter([("basis-1", "structure-1"), ("basis-1", "structure-1")])

    def fake_build(self, diag, folder, snapshot, *, build_sequence_evidence=False):
        basis, structure = next(bases)
        self.path_epoch_index += 1
        self.cache = FakeEpochCache(basis, structure)
        self.cache_snapshot = dict(snapshot)
        self.cache_live_snapshot = dict(snapshot)
        return self.cache, {}, {"sequence_evidence_ready": build_sequence_evidence}

    a._build_cache = MethodType(fake_build, a)
    first = a.path_epoch_plateau_gate({}, tmp_path / "first", state, phase="DEMAND")
    assert first["action"] == "NEW_PATH_BASIS_CONTINUE_CALIBRATION"
    assert first["stationarity_confirmed"] is False
    second = a.path_epoch_plateau_gate({}, tmp_path / "second", state, phase="DEMAND")
    assert second["action"] == "FRESH_ENUMERATION_CONFIRMED_LOCAL_PLATEAU"
    assert second["stationarity_confirmed"] is True
    third = a.path_epoch_plateau_gate({}, tmp_path / "third", state, phase="DEMAND")
    assert third["action"] == "ALREADY_VERIFIED"
    assert third["stationarity_confirmed"] is True
    assert a.path_epoch_refresh_counts["DEMAND"] == 2


def test_path_epoch_refresh_budget_is_hard_gate(tmp_path):
    a = bare_epoch_adapter()
    a.cfg["performance"]["path_epochs"]["max_supply_reenumerations"] = 0
    with pytest.raises(SupplyContractError, match="PATH_EPOCH_REENUMERATION_BUDGET_EXHAUSTED:SUPPLY"):
        a.path_epoch_plateau_gate({}, tmp_path, dict(a.cache_snapshot), phase="SUPPLY")


def test_coupled_controller_continues_after_changed_path_epoch_before_stationarity(tmp_path, monkeypatch):
    cfg, ctl, adapter = setup_workflow(tmp_path, monkeypatch)
    cfg["coupled_demand"]["max_outer_cycles"] = 6
    adapter.no_generation = True
    adapter.td_change = False
    adapter.no_supply = True
    calls = {"DEMAND": 0, "SUPPLY": 0}

    def gate(self, diag, folder, snapshot, *, phase):
        calls[phase] += 1
        if phase == "DEMAND" and calls[phase] == 1:
            return {"stationarity_confirmed": False, "basis_changed": True,
                    "action": "NEW_PATH_BASIS_CONTINUE_CALIBRATION"}
        return {"stationarity_confirmed": True, "basis_changed": False,
                "action": "FRESH_ENUMERATION_CONFIRMED_LOCAL_PLATEAU"}

    adapter.path_epoch_plateau_gate = MethodType(gate, adapter)
    result = coupled.run_overnight_calibration_coupled(
        adapter, cfg, tmp_path / "workflow", ctl, ROOT)
    assert result["status"] == "COMPLETED_CONFIGURED_DEMAND_AND_SUPPLY_SEARCH"
    assert result["demand_cycles"][0]["status"] == "PATH_EPOCH_REFRESHED_CONTINUE_DEMAND"
    assert result["demand_converged_cycle"] == 3
    assert calls["DEMAND"] == 3
    assert calls["SUPPLY"] >= 1


def test_supply_controller_reenumerates_only_after_no_accepted_candidate(tmp_path, monkeypatch):
    cfg, ctl, adapter = setup_workflow(tmp_path, monkeypatch)
    adapter.no_generation = True
    adapter.td_change = False
    adapter.no_supply = True
    calls = {"DEMAND": 0, "SUPPLY": 0}

    def gate(self, diag, folder, snapshot, *, phase):
        calls[phase] += 1
        if phase == "SUPPLY" and calls[phase] == 1:
            return {"stationarity_confirmed": False, "basis_changed": True,
                    "action": "NEW_PATH_BASIS_CONTINUE_CALIBRATION"}
        return {"stationarity_confirmed": True, "basis_changed": False,
                "action": "FRESH_ENUMERATION_CONFIRMED_LOCAL_PLATEAU"}

    adapter.path_epoch_plateau_gate = MethodType(gate, adapter)
    result = coupled.run_overnight_calibration_coupled(
        adapter, cfg, tmp_path / "workflow", ctl, ROOT)
    assert result["status"] == "COMPLETED_CONFIGURED_DEMAND_AND_SUPPLY_SEARCH"
    supply = result["supply_result"]
    assert supply["cycles"][0]["status"] == "PATH_EPOCH_REFRESHED_CONTINUE_SUPPLY"
    assert supply["cycles"][1]["path_epoch_plateau_gate"]["stationarity_confirmed"] is True
    assert calls["SUPPLY"] == 2


def test_new_positive_od_absent_from_epoch_catalog_forces_refresh(tmp_path):
    c = store(tmp_path, profiles=[profile(model=600)])
    try:
        c.add_parents("NATIVE_CW", "C", [[1, 2, 1, 600], [1, 2, 2, 400]],
                      authority([600, 400]))
        c.add_geometry("C", hierarchy())
        c.prepare_incidence_evidence()
        live = np.zeros((2, 2), dtype=float)
        live[0, 1] = 1000.0
        live[1, 0] = 5.0  # no (2,1) parent exists in the frozen epoch
        with pytest.raises(SupplyContractError, match="NATIVE_CW:2:1"):
            c.incidence({
                "expected_zones": 2,
                "path_export_dsegs": ["NATIVE_CW"],
                "mutable_dsegs": ["NATIVE_CW"],
                "mutable_relation_policy": "ALL_MUTABLE_RELATIONS",
            }, None, live_od_matrices={"NATIVE_CW": live})
    finally:
        c.close()


def test_path_basis_comparison_ignores_sub_micro_volume_noise_but_exact_audit_does_not(tmp_path):
    a = store(tmp_path, profiles=[profile(model=600)], name="a.sqlite")
    b = store(tmp_path, profiles=[profile(model=600)], name="b.sqlite")
    try:
        vols_a = [600.0, 400.0]
        vols_b = [600.0 + 1e-8, 400.0 - 1e-8]
        a.add_parents("NATIVE_CW", "C", [[1, 2, 1, vols_a[0]], [1, 2, 2, vols_a[1]]],
                      authority(vols_a))
        b.add_parents("NATIVE_CW", "C", [[1, 2, 1, vols_b[0]], [1, 2, 2, vols_b[1]]],
                      authority(vols_b))
        a.add_geometry("C", hierarchy()); b.add_geometry("C", hierarchy())
        a.prepare_incidence_evidence(); b.prepare_incidence_evidence()
        assert a.path_basis_hash() != b.path_basis_hash()
        assert a.path_basis_comparison_hash() == b.path_basis_comparison_hash()
    finally:
        a.close(); b.close()


def _launcher_v247_module():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "v247_user_entrypoint", ROOT / "R1_15A2_FULL_OVERNIGHT_PATH_EPOCH_V2_4_7.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_v247_launcher_loads_hash_locked_path_epoch_config():
    module = _launcher_v247_module()
    cfg = module.load_config()
    assert cfg["release"] == module.RELEASE
    assert cfg["performance"]["release"] == "V2.4.7"
    assert cfg["performance"]["path_epochs"]["enabled"] is True
    assert cfg["trial_calibration"]["path_epoch_calibration"] is True
    assert len(cfg["implementation_hash"]) == 64
    assert "r1_15a2_safety_v247.py" in cfg["implementation_files"]
    assert "R1_15A2_FULL_OVERNIGHT_PATH_EPOCH_V2_4_7.py" in cfg["implementation_files"]


def test_v247_user_entrypoint_completes_in_v247_run_root(tmp_path, monkeypatch):
    from types import SimpleNamespace
    cfg, _, adapter = setup_workflow(tmp_path, monkeypatch)
    cfg["performance"] = {
        "release": "V2.4.7",
        "telemetry": {"enabled": True},
        "first_sufficient": {"enabled": True,
            "generation_min_relative_improvement": 0.0,
            "supply_min_relative_improvement": 0.0},
        "path_epochs": {"enabled": False},
    }
    project = tmp_path / "user project with spaces"
    project.mkdir()
    source = project / "SOURCE.ver"
    source.write_bytes(b"ORIGINAL_USER_MODEL")
    adapter.visum.IO = SimpleNamespace(CurrentVersionFile=str(source))
    adapter.visum.Procedures = SimpleNamespace()
    module = _launcher_v247_module()
    monkeypatch.setattr(module, "Visum", adapter.visum, raising=False)
    monkeypatch.setattr(module, "load_config", lambda: cfg)
    monkeypatch.setattr(module.api_audit, "project_output_root",
                        lambda visum: (project / "diagnostics", None))
    monkeypatch.setattr(module.api_audit, "collect_live_api",
                        lambda *args, **kwargs: {"required_failures": []})

    def construct(visum, config, control):
        adapter.control = control
        adapter.telemetry = control.telemetry
        return adapter

    monkeypatch.setattr(module, "VisumAdapter", construct)

    def native_save(visum, path):
        cp = adapter.save(path)
        visum.IO.CurrentVersionFile = str(path)
        return cp

    monkeypatch.setattr(module.rt, "save_version", native_save)
    result = module.main()
    assert result["calibration_complete"] and result["final_state_verified"], result
    assert result["release"] == module.RELEASE
    assert result["source_file_unchanged"] and source.read_bytes() == b"ORIGINAL_USER_MODEL"
    assert "R1_15A2_V247_RUNS" in result["run_directory"]
    assert Path(result["final_accepted_version"]["path"]).name == "FINAL_CALIBRATED_WORKING_COPY.ver"
    assert adapter.closed


def test_path_basis_comparison_is_invariant_to_path_index_renumbering(tmp_path):
    from test_two_mode_v238 import SEQS
    a = store(tmp_path, profiles=[profile(model=600)], name="idx_a.sqlite")
    b = store(tmp_path, profiles=[profile(model=600)], name="idx_b.sqlite")
    try:
        a.add_parents("NATIVE_CW", "C", [[1, 2, 1, 600], [1, 2, 2, 400]],
                      authority([600, 400]))
        a.add_geometry("C", hierarchy(SEQS))
        # Same two physical route/volume pairs, but Visum assigned the opposite
        # path indices in the fresh enumeration.
        b.add_parents("NATIVE_CW", "C", [[1, 2, 1, 400], [1, 2, 2, 600]],
                      authority([400, 600]))
        b.add_geometry("C", hierarchy(SEQS[::-1]))
        a.prepare_incidence_evidence(); b.prepare_incidence_evidence()
        assert a.path_basis_hash() != b.path_basis_hash()
        assert a.path_structure_hash() != b.path_structure_hash()
        assert a.path_basis_comparison_hash() == b.path_basis_comparison_hash()
    finally:
        a.close(); b.close()


def test_obsolete_path_epoch_sqlite_is_removed_only_by_locked_policy(tmp_path):
    a = bare_epoch_adapter()
    a.cfg["performance"]["path_epochs"].update({
        "cleanup_obsolete_sqlite_after_verified_refresh": True,
        "retain_sqlite_stores": 1,
    })
    old_dir = tmp_path / "epoch-old"
    old_dir.mkdir()
    store_path = old_dir / "TWO_MODE_PATH_STORE.sqlite"
    store_path.write_bytes(b"old-store")
    Path(str(store_path) + "-journal").write_bytes(b"journal")
    record = a._retire_obsolete_epoch_store(store_path, tmp_path / "audit")
    assert record["retired"] is True
    assert not store_path.exists()
    assert not Path(str(store_path) + "-journal").exists()
    assert (tmp_path / "audit" / "PATH_EPOCH_STORE_RETENTION.json").is_file()
    unexpected = tmp_path / "do-not-delete.sqlite"
    unexpected.write_bytes(b"x")
    with pytest.raises(SupplyContractError, match="REFUSE_UNEXPECTED_STORE_DELETE"):
        a._retire_obsolete_epoch_store(unexpected, tmp_path / "audit2")
    assert unexpected.is_file()

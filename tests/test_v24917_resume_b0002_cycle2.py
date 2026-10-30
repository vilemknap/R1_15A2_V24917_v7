"""Regression: B0002 keeps accepted cycle1, creates new native route epoch.

No mock is permitted to make a fake OD path share valid. Only the original
collector exporter may provide support in production.
"""
from __future__ import annotations

import copy
import hashlib
import importlib
import json
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

import r1_15a2_resume_b0002_v24917 as b
import r1_15a2_supply as supply


@pytest.fixture
def recorded(tmp_path):
    recipe = b.authority()
    parent = tmp_path / "R1_15A2_V16_RUNS" / recipe["source_run_name"]
    calibration = parent / "CALIBRATION"
    cp = calibration / "CHECKPOINTS" / recipe["checkpoint_filename"]
    cp.parent.mkdir(parents=True)
    cp.write_bytes(b"short-test-checkpoint")
    recipe["expected_checkpoint_size_bytes"] = cp.stat().st_size
    recipe["expected_checkpoint_raw_sha256"] = hashlib.sha256(cp.read_bytes()).hexdigest()
    sidecar = {"schema": "R1_15A2_SEMANTIC_RESTART_AUTHORITY_V2494",
               "semantic_state_hash": recipe["checkpoint_semantic_state_hash"],
               "semantic_hashes": recipe["checkpoint_semantic_hashes"]}
    Path(str(cp) + ".semantic.json").write_text(json.dumps(sidecar))
    reference = {"schema": "R1_15A2_SHARED_OBJECTIVE_V22", "test": "fixed"}
    recipe["generation_reference_hash"] = supply.canonical_hash(reference)
    (calibration / "GENERATION_COUNTS_REFERENCE.json").write_text(json.dumps(reference))
    checkpoint_ref = {"path": str(cp), "sha256": recipe["expected_checkpoint_raw_sha256"],
                      "size": recipe["expected_checkpoint_size_bytes"]}
    run = {
        "schema": "R1_15A2_V24914_CONTINUABLE_COUPLED_DEMAND_STATE_MACHINE",
        "status": "FAILED", "accepted_count": 2, "demand_converged": False,
        "supply_started": False,
        "error": "A0001_RESUME_NO_PATH_ENUMERATION_ALLOWED:old path basis",
        "demand_cycles": [{
            "cycle": 1, "status": "PROGRESS_CONTINUE_DEMAND", "generation_completed": True,
            "td_completed": True, "generation_changed": True, "td_changed": True,
            "joint_stationary": False, "progress_continue": True,
            "td": {"td_realization_complete": True, "inner": {"stop_reason": "TD_EVALUATION_BUDGET"}},
            "state_hash_end": recipe["checkpoint_snapshot_state_hash_diagnostic"]
        }, {
            "cycle": 2, "status": "FAILED", "generation_completed": False,
            "td_completed": False,
            "state_hash_start": recipe["checkpoint_snapshot_state_hash_diagnostic"]
        }],
        "latest_accepted_checkpoint": checkpoint_ref,
        "current_exploratory_checkpoint": checkpoint_ref,
        "generation_reference_sha256": recipe["generation_reference_hash"],
        "best_so_far_checkpoint": {
            "accepted_count": 2, "state_hash": recipe["checkpoint_snapshot_state_hash_diagnostic"],
            "source_accepted_checkpoint": checkpoint_ref,
            "semantic_restart_authority": {
                "semantic_state_hash": recipe["checkpoint_semantic_state_hash"],
                "semantic_hashes": recipe["checkpoint_semantic_hashes"]
            }
        }
    }
    (calibration / "RUN_STATUS.json").write_text(json.dumps(run))
    return cp, recipe, sidecar, run, reference


def test_source_witness_proves_exact_b0002_and_skips_accepted_cycle1(recorded):
    cp, recipe, sidecar, run, ref = recorded
    paths = b.check_source(cp, recipe)
    assert paths["source_audit"]["best_so_far_confirmed"]
    descriptor = b.continuation(paths, recipe)
    assert descriptor["next_outer_cycle"] == 2
    assert descriptor["accepted_count"] == 2
    assert descriptor["resume_substep"] == "GENERATION"
    assert descriptor["prior_generation_and_td_replayed"] is False
    assert descriptor["fresh_native_path_epoch_required"]
    validated = b.validate_continuation({"runtime_demand_continuation": descriptor}, recipe)
    assert validated == descriptor
    assert cp.read_bytes() == b"short-test-checkpoint"


@pytest.mark.parametrize("damage", (
    "raw_bytes", "missing_sidecar", "alter_semantic", "alter_status",
    "alter_best", "alter_hash", "cycle2_partial", "wrong_cycle1", "wrong_checkpoint",
))
def test_corruption_or_invalid_resume_boundary_never_continues(recorded, damage):
    cp, recipe, sidecar, run, ref = recorded
    if damage == "raw_bytes": cp.write_bytes(b"tampered-ver-contents")
    elif damage == "missing_sidecar": Path(str(cp) + ".semantic.json").unlink()
    elif damage == "alter_semantic":
        sidecar["semantic_hashes"]["matrix_hash"] = "a" * 64
        Path(str(cp) + ".semantic.json").write_text(json.dumps(sidecar))
    elif damage == "alter_status": run["status"] = "SUCCESS"
    elif damage == "alter_best": run["best_so_far_checkpoint"]["accepted_count"] = 1
    elif damage == "alter_hash": run["latest_accepted_checkpoint"]["sha256"] = "b"*64
    elif damage == "cycle2_partial": run["demand_cycles"][1]["generation_completed"] = True
    elif damage == "wrong_cycle1": run["demand_cycles"][0]["td_completed"] = False
    elif damage == "wrong_checkpoint": run["latest_accepted_checkpoint"]["path"] = "other.ver"
    (cp.parent.parent / "RUN_STATUS.json").write_text(json.dumps(run))
    with pytest.raises((RuntimeError, supply.SupplyContractError)):
        b.check_source(cp, recipe)


def test_baseline_matrix_deferral_is_temporary(recorded):
    _, recipe, *_ = recorded
    original = dict(recipe["checkpoint_semantic_hashes"])
    assert b.check_live_hashes(original, recipe)["status"] == "EXACT_ALL_SEVEN_FIELDS"
    drift = dict(original, matrix_hash="a"*64)
    assert b.check_live_hashes(drift, recipe, allow_matrix_deferral=True)["differences"] == ["matrix_hash"]
    with pytest.raises(RuntimeError, match="LIVE_SEMANTIC_DIFFERENCE"):
        b.check_live_hashes(drift, recipe, allow_matrix_deferral=False)
    drift["td_hash"] = "b"*64
    with pytest.raises(RuntimeError, match="LIVE_SEMANTIC_DIFFERENCE"):
        b.check_live_hashes(drift, recipe, allow_matrix_deferral=True)


class NativeCollector:
    def __init__(self, path):
        self.route_db_path = str(path)
        self.support_calls = 0
    def incidence(self, cfg, zones, *, live_od_matrices):
        self.support_calls += 1
        assert "NATIVE_CS_NOT" in live_od_matrices
        return {"real_route_shares": [1.0]}


def test_fresh_epoch_export_and_support_are_inside_new_run(monkeypatch, tmp_path):
    from r1_15a2_supply import SupplyContractError
    folder = tmp_path / "NEW" / "CALIBRATION"
    folder.mkdir(parents=True)
    original = tmp_path / "OLD" / "TWO_MODE_PATH_STORE.sqlite"
    original.parent.mkdir()
    original.write_bytes(b"source-do-not-touch")
    verified = {"yes": False}
    events = []
    collector = None
    adapter = NS(cache=None, path_epoch_index=0, path_epoch_accepts=0,
                 persistent_path_cache=NS(enabled=False),
                 cfg={"performance": {"path_epochs": {"enabled": True}}},
                 actuatable_zones=[616, 676])
    def native_build(diag, target, snap, **kwargs):
        nonlocal collector
        events.append(("fresh-native-export", Path(target), kwargs))
        db = Path(target) / "TWO_MODE_PATH_STORE.sqlite"
        db.write_bytes(b"genuine-native-test-store")
        collector = NativeCollector(db)
        adapter.cache = collector
        adapter.path_epoch_index += 1
        return (collector, {}, {"native_export": True})
    def retire(src, audit):
        events.append(("retire", src))
        Path(src).unlink()
    adapter._build_cache = native_build
    adapter._retire_obsolete_epoch_store = retire
    adapter._live_generation_matrices = lambda: {"NATIVE_CS_NOT": [[1.0]]}
    b.install_fresh_epoch_gate(adapter, folder, lambda: verified["yes"])
    with pytest.raises(RuntimeError, match="BEFORE_STRICT_BASELINE_PROOF"):
        adapter._build_cache({}, folder / "EPOCH", {"state_hash": "good"})
    verified["yes"] = True
    with pytest.raises(SupplyContractError, match="OUTSIDE_NEW_CALIBRATION"):
        adapter._build_cache({}, original.parent / "UNSAFE", {"state_hash": "good"})
    with pytest.raises(SupplyContractError, match="REFUSE_RETIRE_SOURCE_CACHE"):
        adapter._retire_obsolete_epoch_store(str(original), folder)
    assert original.read_bytes() == b"source-do-not-touch"
    proof = b.prove_native_support(adapter, {}, folder / "RESUME_EVIDENCE", {"state_hash": "good"})
    assert proof["new_epoch"] == 1
    assert proof["source_sqlite_imported"] is False
    assert proof["positive_od_support_verified"]
    assert collector.support_calls == 1
    assert events[0][2]["allow_persistent_restore"] is False
    assert original.read_bytes() == b"source-do-not-touch"
    assert (folder / "RESUME_EVIDENCE" / "B0002_INITIAL_EPOCH" /
            "B0002_NATIVE_EPOCH_AUTHORITY.json").exists()


def test_native_epoch_fails_if_no_od_route_support(tmp_path):
    from r1_15a2_supply import SupplyContractError
    folder = tmp_path / "CALIBRATION"
    folder.mkdir()
    adapter = NS(cache=None, path_epoch_index=0, path_epoch_accepts=0,
                 persistent_path_cache=NS(enabled=False),
                 cfg={"performance":{"path_epochs":{"enabled":True}}},
                 actuatable_zones=[616, 676])
    class Insufficient(NativeCollector):
        def incidence(self, cfg, zones, *, live_od_matrices):
            raise SupplyContractError("PATH_EPOCH_NEW_POSITIVE_OD_REQUIRES_REENUMERATION:NATIVE_CS_NOT:616:676")
    def build(diag, target, snapshot, **kwargs):
        db=Path(target)/"TWO_MODE_PATH_STORE.sqlite"
        db.write_bytes(b"real-bytes")
        adapter.path_epoch_index += 1
        adapter.cache = Insufficient(db)
        return (adapter.cache, {}, {})
    adapter._build_cache = build
    adapter._retire_obsolete_epoch_store = lambda *a: None
    adapter._live_generation_matrices = lambda: {"NATIVE_CS_NOT": [[1.0]]}
    b.install_fresh_epoch_gate(adapter, folder, lambda: True)
    with pytest.raises(SupplyContractError, match="616:676"):
        b.prove_native_support(adapter, {}, folder / "SMOKE", {"state_hash":"s"})


def test_corrupted_continuation_descriptor_rejected(recorded):
    cp, recipe, _, _, _ = recorded
    descriptor = b.continuation(b.check_source(cp, recipe), recipe)
    for key, bad in (("next_outer_cycle", 1), ("accepted_count", 3),
                     ("resume_substep", "TD_FINECDF_V17"),
                     ("generation_reference_sha256", "wrong"),
                     ("prior_generation_and_td_replayed", True)):
        variant = dict(descriptor, **{key: bad})
        with pytest.raises(RuntimeError):
            b.validate_continuation({"runtime_demand_continuation": variant}, recipe)


def test_runtime_binds_cycle2_and_performs_first_native_path_smoke(
        monkeypatch, recorded, tmp_path):
    cp, recipe, sidecar, run, reference = recorded
    paths = b.check_source(cp, recipe)
    monkeypatch.setattr(b.a0001, "install_sibling_run_layout_guard", lambda *a, **k: {"passes": True})
    active = dict(recipe["checkpoint_semantic_hashes"], state_hash="s1")
    report = {
        "passes": True, "semantic_before_after": {"passes": True},
        "current_version_file": str(cp),
        "source_raw_ver_sha256_provenance_only": recipe["expected_checkpoint_raw_sha256"],
        "source_semantic_hashes": dict(recipe["checkpoint_semantic_hashes"]),
        "source_semantic_state_hash": recipe["checkpoint_semantic_state_hash"],
    }
    called = []
    def native_build(diag, target, state, **kwargs):
        called.append(("native-enum", Path(target), dict(kwargs)))
        db = Path(target) / "TWO_MODE_PATH_STORE.sqlite"
        db.write_bytes(b"native-test")
        adapter.cache = NativeCollector(db)
        adapter.path_epoch_index += 1
        return (adapter.cache, {}, {"native": True})
    adapter = NS(
        cache=None, path_epoch_index=0, path_epoch_accepts=0,
        persistent_path_cache=NS(enabled=False),
        cfg={"performance": {"path_epochs": {"enabled":True}}},
        actuatable_zones=[616, 676],
        _build_cache=native_build, _retire_obsolete_epoch_store=lambda *args: None,
        generation_guard_snapshot=lambda: dict(active),
        snapshot=lambda: dict(active),
        _live_generation_matrices=lambda: {"NATIVE_CS_NOT": [[1.0]]},
        diagnostics=lambda path,label="CURRENT": {"d12":{"rows":[]}},
    )
    cfg = {"coupled_demand": {"max_outer_cycles": 100}}
    folder = tmp_path / "NEW_RUN" / "CALIBRATION"
    folder.mkdir(parents=True)
    def old_run(adapter_, cfg_, folder_, control, package_root):
        assert cfg_ is cfg
        assert adapter_ is adapter
        assert cfg_["runtime_demand_continuation"]["next_outer_cycle"] == 2
        assert cfg_["runtime_demand_continuation"]["accepted_count"] == 2
        assert cfg_["runtime_demand_continuation"]["resume_substep"] == "GENERATION"
        assert cfg_["runtime_demand_continuation"]["generation_reference"] == reference
        # This invokes the actual installed baseline hook, which must enumerate.
        adapter_.diagnostics(folder / "BASELINE_DIAGNOSTICS", "BASELINE")
        called.append(("controller-next-cycle", 2))
        return {"status":"CONTROLLER_BOUND", "next_outer_cycle":2}
    coupled = importlib.import_module("r1_15a2_overnight_controller_coupled_v24915p2_force100")
    old_parser = coupled._runtime_demand_continuation
    monkeypatch.setattr(coupled, "_runtime_demand_continuation", old_parser)
    parent = NS(run_overnight_calibration_coupled=old_run)
    v16 = NS(parent=parent,
              _install_runtime=lambda *a,**k: {"installed": True},
              _run_live_preflight=lambda *a,**k: (report, {}))
    b.install_resume(v16, cp, recipe, paths, print_fn=lambda *args:None)
    v16._run_live_preflight()
    v16._install_runtime()
    try:
        output = parent.run_overnight_calibration_coupled(
            adapter, cfg, folder, object(), Path.cwd())
        assert output == {"status":"CONTROLLER_BOUND", "next_outer_cycle":2}
        assert called[0][0] == "native-enum"
        assert called[0][2]["allow_persistent_restore"] is False
        assert called[-1] == ("controller-next-cycle", 2)
        assert adapter.path_epoch_index == 1
        assert (folder / "RESUME_EVIDENCE" / "B0002_POST_BASELINE_AUTHORITY.json").exists()
        assert (folder / "RESUME_EVIDENCE" / "B0002_INITIAL_PATH_SUPPORT_SMOKE.json").exists()
        assert cp.read_bytes() == b"short-test-checkpoint"
    finally:
        coupled._runtime_demand_continuation = old_parser


def test_one_shot_native_path_support_smoke_exits_before_generation(monkeypatch, recorded, tmp_path):
    cp, recipe, _sidecar, _run, _ref = recorded
    paths = b.check_source(cp, recipe)
    monkeypatch.setattr(b.a0001, "install_sibling_run_layout_guard", lambda *a, **k: {"passes":True})
    live=dict(recipe["checkpoint_semantic_hashes"],state_hash="b0002-live")
    report={"passes":True,"semantic_before_after":{"passes":True},
            "current_version_file":str(cp),
            "source_raw_ver_sha256_provenance_only":recipe["expected_checkpoint_raw_sha256"],
            "source_semantic_hashes":dict(recipe["checkpoint_semantic_hashes"]),
            "source_semantic_state_hash":recipe["checkpoint_semantic_state_hash"]}
    trace=[]
    adapter=NS(cache=None,path_epoch_index=0,path_epoch_accepts=0,
               persistent_path_cache=NS(enabled=False),
               cfg={"performance":{"path_epochs":{"enabled":True}}},
               actuatable_zones=[616,676],
               snapshot=lambda:dict(live),
               generation_guard_snapshot=lambda:dict(live),
               preflight=lambda *a:trace.append("native-preflight") or {},
               assign=lambda *a,**k:trace.append("native-assignment") or None,
               diagnostics=lambda *a,**k:trace.append("native-diagnostics") or {"d12":{"rows":[]}},
               _retire_obsolete_epoch_store=lambda *a:None,
               _live_generation_matrices=lambda:{"NATIVE_CS_NOT":[[1.0]]})
    def native(diag, target, snapshot, **kw):
        trace.append("native-route-enumeration")
        path=Path(target)/"TWO_MODE_PATH_STORE.sqlite"
        path.write_bytes(b"new-native-test-data")
        adapter.path_epoch_index+=1
        adapter.cache=NativeCollector(path)
        return (adapter.cache,{}, {"native_export":True})
    adapter._build_cache=native
    parent=NS(run_overnight_calibration_coupled=lambda *a: (_ for _ in ()).throw(
        AssertionError("Full 100-cycle controller must NOT run in smoke mode")))
    v16=NS(parent=parent,
            _install_runtime=lambda *a,**kw:{"installed":True},
            _run_live_preflight=lambda *a,**kw:(report,{}))
    coupled=importlib.import_module("r1_15a2_overnight_controller_coupled_v24915p2_force100")
    old_parser=coupled._runtime_demand_continuation
    b.install_resume(v16,cp,recipe,paths,print_fn=lambda *a:None,smoke_only=True)
    v16._run_live_preflight()
    v16._install_runtime()
    output=tmp_path/"RUN_NEW"/"CALIBRATION"
    output.mkdir(parents=True)
    try:
        result=parent.run_overnight_calibration_coupled(
            adapter,{"coupled_demand":{"max_outer_cycles":100}},output,
            NS(checkpoint=lambda *a,**kw:None),Path.cwd())
        assert result["status"]=="B0002_NATIVE_PATH_EPOCH_SMOKE_PASSED"
        assert result["source_accepted_count"]==2 and result["new_native_path_epoch"]==1
        assert result["generation_candidates_evaluated"]==0
        assert result["finecdf_td_candidates_evaluated"]==0
        assert result["calibration_complete"] is False
        assert trace==["native-preflight","native-assignment","native-diagnostics","native-route-enumeration"]
        assert (output/"B0002_PATH_EPOCH_SMOKE_RESULT.json").is_file()
        assert cp.read_bytes()==b"short-test-checkpoint"
    finally:
        coupled._runtime_demand_continuation=old_parser

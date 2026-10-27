"""V2.4.6 performance implementation regressions and user-level contracts.

All tests are offline/COM-shaped fixtures. They do not claim a real PTV Visum run.
"""
from __future__ import annotations

import hashlib
import copy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import r1_15a2_finecdf_bridge_v242 as bridge
import r1_15a2_overnight_controller_v240 as trial
import r1_15a2_overnight_controller_v242 as coupled
import r1_15a2_sequence_v23 as sequence
import r1_15a2_supply_visum as supply_visum
from r1_15a2_perf_v246 import PerformanceTelemetry
from r1_15a2_safety_v246 import validate_v246_config
from r1_15a2_supply import SupplyContractError, SupplyPolicy, canonical_hash
from r1_15a2_two_mode_v238 import bounded_rows, DEFAULT_SETTINGS, GEOMETRY_COLUMNS, QuietControl
from test_sequence_v23 import fixture as sequence_fixture, links as sequence_links
from test_two_mode_v238 import store, authority, hierarchy
from test_v237_15p_bounded_offdiag_stream import BoundedHierarchical
from test_v245_workflow import setup_workflow

ROOT = Path(__file__).resolve().parents[1]


class Link:
    def __init__(self, **attrs):
        self.attrs = dict(attrs)
        self.calls = 0
    def AttValue(self, name):
        self.calls += 1
        return self.attrs[name]


class BulkLinks:
    def __init__(self, rows, fail_bulk=False):
        self.items = [Link(**row) for row in rows]
        self.fail_bulk = fail_bulk
        self.multi_calls = []
        self.Count = len(self.items)
    @property
    def GetAll(self):
        return tuple(self.items)
    def GetMultiAttValues(self, attr, only_active=False):
        self.multi_calls.append((attr, only_active))
        if self.fail_bulk:
            raise RuntimeError("INJECTED_BULK_FAILURE")
        return [(i, row.attrs[attr]) for i, row in enumerate(self.items, 1)]


def link_rows():
    return [
        {"NO": 10, "FROMNODENO": 1, "TONODENO": 2, "ADDVAL1": 0.0,
         "T0_PRTSYS(C)": 12.5, "CAPPRT": 900.0, "LENGTH": 1.2,
         "TYPENO": 3, "TSYSSET": "C,C_not"},
        {"NO": 11, "FROMNODENO": 2, "TONODENO": 3, "ADDVAL1": -1.0,
         "T0_PRTSYS(C)": 8.0, "CAPPRT": 700.0, "LENGTH": 0.8,
         "TYPENO": 4, "TSYSSET": "C"},
    ]


def adapter_for_links(collection, bulk_enabled=True, fallback=True):
    obj = object.__new__(supply_visum.VisumAdapter)
    obj.cfg = {"supply": {"link_attributes": {}, "excluded_link_keys": [],
                           "editable_link_types": None},
               "performance": {"bulk_link_read": {
                   "enabled": bulk_enabled, "fallback_to_scalar": fallback,
                   "verify_object_no": True}}}
    obj.visum = SimpleNamespace(Net=SimpleNamespace(Links=collection))
    obj.telemetry = None
    return obj


def normalized_links(rows):
    return {key: {k: v for k, v in row.items() if k != "object"}
            for key, row in rows.items()}


def test_v246_config_and_v18_reference_are_hash_locked():
    cfg = json.loads((ROOT / "R1_15A2_CONFIG_V2_4_6.json").read_text(encoding="utf-8"))
    result = validate_v246_config(cfg, ROOT)
    assert result["passes"] and result["adaptive_page_size"] == 2048
    fine = cfg["coupled_demand"]["finecdf_td"]
    ref, path, sha = bridge.load_reference(ROOT, fine)
    assert path.name.endswith("v1_8.py")
    assert sha == fine["reference_sha256"]
    assert ref.SCRIPT_ID == fine["reference_script_id"]
    assert len(ref.FINE_AUTHORITY["targets"]) == 12


def test_bulk_link_read_equals_scalar_and_explicitly_includes_inactive():
    bulk_collection = BulkLinks(link_rows())
    scalar_collection = BulkLinks(link_rows())
    bulk = adapter_for_links(bulk_collection, True).read_links()
    scalar = adapter_for_links(scalar_collection, False).read_links()
    assert normalized_links(bulk) == normalized_links(scalar)
    assert adapter_for_links(BulkLinks(link_rows()), True).cfg["performance"]["bulk_link_read"]["enabled"]
    assert len(bulk_collection.multi_calls) == 9
    assert all(flag is False for _, flag in bulk_collection.multi_calls)
    # Bulk verifies only object NO, instead of reading all nine attributes per object.
    assert sum(x.calls for x in bulk_collection.items) == len(bulk_collection.items)
    assert sum(x.calls for x in scalar_collection.items) == 9 * len(scalar_collection.items)


def test_bulk_link_failure_uses_verified_scalar_fallback():
    collection = BulkLinks(link_rows(), fail_bulk=True)
    adapter = adapter_for_links(collection, True, fallback=True)
    rows = adapter.read_links()
    assert len(rows) == 2 and adapter.last_link_read_mode == "SCALAR_FALLBACK"
    strict = adapter_for_links(BulkLinks(link_rows(), fail_bulk=True), True, fallback=False)
    with pytest.raises(SupplyContractError, match="GET_MULTI_ATT_VALUES_FAILED"):
        strict.read_links()


class FailingOLE:
    def __init__(self, owner, fail_above):
        # Reuse the verified COM signature implementation from the existing fixture.
        self.base = BoundedHierarchical([])._oleobj_
        self.owner = owner
        self.fail_above = fail_above
        self.calls = []
    def GetTypeInfo(self):
        return self.base.GetTypeInfo()
    def Invoke(self, memid, lcid, kind, as_method, first, last):
        self.calls.append((first, last))
        if last - first + 1 > self.fail_above:
            raise RuntimeError("PAGE_TOO_LARGE")
        return self.owner.raw[first-1:last]


class AdaptiveBounded(BoundedHierarchical):
    def __init__(self, raw, fail_above):
        super().__init__(raw)
        self._oleobj_ = FailingOLE(self, fail_above)


def test_adaptive_bounded_paging_falls_back_without_duplicates_or_loss():
    raw = [[1, 2, 1, "", "", "", ""]] + [
        ["", "", "", i, 100+i, i, i+1] for i in range(1, 11)]
    obj = AdaptiveBounded(raw, fail_above=4)
    settings = dict(DEFAULT_SETTINGS, page_size=8, page_size_fallbacks=[4, 2, 1])
    got = list(bounded_rows(obj, GEOMETRY_COLUMNS, settings, QuietControl(), "TEST"))
    direct = list(bounded_rows(BoundedHierarchical(raw), GEOMETRY_COLUMNS,
                               dict(DEFAULT_SETTINGS, page_size=2), QuietControl(), "TEST"))
    assert got == direct == raw
    assert obj._oleobj_.calls[0] == (1, 8)
    assert obj._oleobj_.calls[1] == (1, 4)
    assert obj.unbounded_calls == 0
    assert canonical_hash(got) == canonical_hash(raw)


def test_generation_incidence_is_ready_before_deferred_supply_pairs(tmp_path):
    collector = store(tmp_path)
    try:
        collector.add_parents("NATIVE_CW", "C", [[1, 2, 1, 600], [1, 2, 2, 400]],
                              authority([600, 400]))
        collector.add_geometry("C", hierarchy())
        pre = collector.prepare_incidence_evidence()
        assert pre["incidence_ready"] and not pre["sequence_evidence_ready"]
        assert collector.incidence_ready and not collector.sequence_ready
        assert sum(len(x) for x in collector.evidence.values()) == 0
        incidence, _ = collector.incidence(
            {"path_export_dsegs": ["NATIVE_CW"], "mutable_dsegs": ["NATIVE_CW"]},
            [1, 2])
        before = collector.db.execute("SELECT COUNT(*) FROM geometry").fetchone()[0]
        post = collector.prepare_sequence_evidence()
        assert post["sequence_evidence_ready"] and collector.sequence_ready
        assert collector.db.execute("SELECT COUNT(*) FROM geometry").fetchone()[0] == before
        assert collector.finish()["path_store_route_count"] == incidence["path_count"]
    finally:
        collector.close()


def test_addval_amplitude_schedule_is_explicit_and_budget_guarded():
    policy = SupplyPolicy(min_geh=1., min_residual=1., max_candidates=50,
                          max_step=4., max_cumulative=4., max_edges=12,
                          max_bundle_equivalent_seconds=120.)
    c = sequence_fixture(policy=policy)
    try:
        design = sequence.propose_sequence_supply(
            c, sequence_links(), {k: 0. for k in sequence_links()}, policy,
            sequence_caps=(4, 2, 1), step_units=(4, 2, 1))
        assert design["step_units_schedule"] == [4, 2, 1]
        assert design["candidates"]
        assert any(x["step_units"] == 4 for x in design["candidates"])
        assert all(max(abs(ch["delta"]) for ch in x["changes"]) in (1, 2, 4)
                   for x in design["candidates"])
        assert all(x["equivalent_impedance_budget_seconds"] <= 120.0 + 1e-12
                   for x in design["candidates"])
        with pytest.raises(SupplyContractError, match="EXCEED_MAX_STEP"):
            sequence.propose_sequence_supply(
                c, sequence_links(), {k: 0. for k in sequence_links()},
                SupplyPolicy(min_geh=1., min_residual=1., max_step=1.),
                step_units=(4, 2, 1))
    finally:
        c.close()


def test_first_sufficient_policy_never_bypasses_acceptance():
    cfg = {"performance": {"first_sufficient": {
        "enabled": True, "generation_min_relative_improvement": .01,
        "supply_min_relative_improvement": .02}}}
    baseline = {"total": 100.0}
    rejected = {"eligible": False, "after_value": {"total": 1.0}}
    accepted_small = {"eligible": True, "after_value": {"total": 99.5}}
    accepted_large = {"eligible": True, "after_value": {"total": 98.0}}
    assert not trial._first_sufficient_candidate(cfg, "GENERATION", baseline, rejected)
    assert not trial._first_sufficient_candidate(cfg, "GENERATION", baseline, accepted_small)
    assert trial._first_sufficient_candidate(cfg, "GENERATION", baseline, accepted_large)
    assert accepted_large["first_sufficient_relative_improvement"] == pytest.approx(.02)


def test_generation_stops_after_first_material_live_improvement(tmp_path, monkeypatch):
    cfg, control, adapter = setup_workflow(tmp_path, monkeypatch)
    cfg["performance"] = {"first_sufficient": {
        "enabled": True, "generation_min_relative_improvement": 0.0,
        "supply_min_relative_improvement": 0.0}}
    result = coupled.run_overnight_calibration_coupled(
        adapter, cfg, tmp_path / "workflow", control, ROOT)
    first = result["demand_cycles"][0]["generation"]
    assert first["early_stop_policy"] == "FIRST_SUFFICIENT_GATE_ACCEPTED"
    assert len(first["attempts"]) == 1
    assert result["calibration_complete"]


def test_progressive_td_budget_continues_then_requires_two_full_stationary_cycles(tmp_path, monkeypatch):
    cfg, control, adapter = setup_workflow(tmp_path, monkeypatch)
    cfg["coupled_demand"].update(max_outer_cycles=5, min_stationary_cycles=2)
    cfg["coupled_demand"]["finecdf_td"] = {
        "progressive_schedule": [
            {"name": "EXPLORE", "through_outer_cycle": 2, "max_iterations": 2,
             "max_td_evaluations": 12, "allow_progress_continue": True},
            {"name": "FULL_VERIFY", "through_outer_cycle": 5, "max_iterations": 35,
             "max_td_evaluations": 180, "allow_progress_continue": False},
        ]
    }
    calls = []
    def inner(a, cfg, folder, ctl, package_root, phase_budget=None):
        calls.append(dict(phase_budget or {}))
        rows = []
        if len(calls) == 1:
            a.state["b"] = .08
            rows = [{"component": "WORK_E_C", "after_b": .08, "after_c": -.1}]
        early = bool(phase_budget and phase_budget.get("allow_progress_continue"))
        return {"changed_rows": rows,
                "stop_reason": "MAX_ITERATIONS" if early else "LOCAL_PLATEAU_NOT_PROOF_OF_GLOBAL_OPTIMUM",
                "search_complete": not early,
                "stationarity_confirmed": not early,
                "progress_continue": early,
                "backend": "SYNTHETIC_NATIVE_EVALUATOR_NOT_VISUM"}
    monkeypatch.setattr(coupled, "run_finecdf_inner", inner)
    result = coupled.run_overnight_calibration_coupled(
        adapter, cfg, tmp_path / "progressive", control, ROOT)
    assert [c["status"] for c in result["demand_cycles"][:2]] == [
        "PROGRESS_CONTINUE_DEMAND", "PROGRESS_CONTINUE_DEMAND"]
    assert result["demand_cycles"][2]["joint_stationary"]
    assert result["demand_cycles"][3]["joint_stationary"]
    assert result["demand_converged_cycle"] == 4
    assert result["supply_started"] and result["calibration_complete"]
    assert [c["name"] for c in calls] == ["EXPLORE", "EXPLORE", "FULL_VERIFY", "FULL_VERIFY"]


def test_performance_telemetry_is_atomic_and_records_errors(tmp_path):
    now = [0.0]
    def clock():
        now[0] += 0.1
        return now[0]
    t = PerformanceTelemetry(tmp_path / "perf", clock=clock)
    with t.span("OK_SPAN", rows=3):
        pass
    with pytest.raises(RuntimeError, match="boom"):
        with t.span("BAD_SPAN"):
            raise RuntimeError("boom")
    summary = t.finish()
    assert summary["event_count"] == 2 and summary["error_count"] == 1
    events = sorted((tmp_path / "perf").glob("EVENT_*.json"))
    assert len(events) == 2
    assert json.loads(events[1].read_text())["status"] == "ERROR"
    assert not list((tmp_path / "perf").glob("*.tmp"))


def _launcher_v246_module():
    spec = importlib.util.spec_from_file_location(
        "v246_user_entrypoint", ROOT / "R1_15A2_FULL_OVERNIGHT_ADAPTIVE_V2_4_6.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_v246_launcher_loads_its_complete_hash_locked_config():
    module = _launcher_v246_module()
    cfg = module.load_config()
    assert cfg["release"] == module.RELEASE
    assert cfg["performance"]["release"] == "V2.4.6"
    assert cfg["coupled_demand"]["finecdf_td"]["reference_script"].startswith("reference_v18/")
    assert len(cfg["implementation_hash"]) == 64
    assert "r1_15a2_perf_v246.py" in cfg["implementation_files"]
    assert "r1_15a2_safety_v246.py" in cfg["implementation_files"]


def test_v246_user_entrypoint_completes_and_writes_telemetry(tmp_path, monkeypatch):
    cfg, _, adapter = setup_workflow(tmp_path, monkeypatch)
    cfg["performance"] = {
        "release": "V2.4.6",
        "telemetry": {"enabled": True},
        "first_sufficient": {"enabled": True,
            "generation_min_relative_improvement": 0.0,
            "supply_min_relative_improvement": 0.0},
    }
    project = tmp_path / "user project with spaces"
    project.mkdir()
    source = project / "SOURCE.ver"
    source.write_bytes(b"ORIGINAL_USER_MODEL")
    adapter.visum.IO = SimpleNamespace(CurrentVersionFile=str(source))
    adapter.visum.Procedures = SimpleNamespace()
    module = _launcher_v246_module()
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
    assert "R1_15A2_V246_RUNS" in result["run_directory"]
    perf = Path(result["run_directory"]) / "PERFORMANCE" / "SUMMARY.json"
    assert perf.is_file()
    summary = json.loads(perf.read_text())
    assert summary["schema"] == "R1_15A2_V246_PERFORMANCE_TELEMETRY_V1"
    assert summary["error_count"] == 0
    assert Path(result["final_accepted_version"]["path"]).name == "FINAL_CALIBRATED_WORKING_COPY.ver"
    assert adapter.closed


def test_v18_actual_runner_on_com_shaped_backend(tmp_path, monkeypatch):
    from test_v245_native_bridge import fixture
    ref17, _, _, visum, cfg, control, _, matrices, calls = fixture(tmp_path)
    fine = json.loads((ROOT / "R1_15A2_CONFIG_V2_4_6.json").read_text())["coupled_demand"]["finecdf_td"]
    ref18, path18, sha18 = bridge.load_reference(ROOT, fine)
    ref18.CONFIG["expected_zone_count"] = 4
    ref18.CONFIG["require_2022_patch_preflight"] = False
    cfg["release"] = "R1_15A2_V2_4_6_ADAPTIVE_PERFORMANCE_20261016"
    cfg["coupled_demand"]["finecdf_td"] = dict(fine, max_iterations=2,
                                                max_td_evaluations=16,
                                                max_stagnant_iterations=2,
                                                progressive_schedule=[])
    monkeypatch.setattr(bridge, "load_reference",
                        lambda root, configured=None: (ref18, path18, sha18))
    result = bridge.run_finecdf_inner(
        SimpleNamespace(visum=visum, telemetry=None), cfg, tmp_path / "v18", control, ROOT)
    assert calls and result["reference_sha256"] == sha18
    assert result["objective_final"] <= result["objective_start"] + 1e-12
    history = tmp_path / "v18" / "ITERATION_HISTORY.csv"
    assert history.is_file()
    text = history.read_text(encoding="utf-8-sig")
    assert "predicted_objective" in text and "predicted_active" in text
    assert matrices[9116].values.sum() > 0


def test_supply_first_sufficient_reduces_live_trials(tmp_path):
    from test_v245_repair import synthetic_trial
    cfg, control, adapter = synthetic_trial(tmp_path)
    cfg["performance"] = {
        "telemetry": {"enabled": True},
        "first_sufficient": {"enabled": True,
            "generation_min_relative_improvement": 0.0,
            "supply_min_relative_improvement": 0.0},
    }
    result = trial.run_overnight_calibration(adapter, cfg, tmp_path / "supply", control)
    accepted_blocks = [b for b in result["blocks"] if b.get("status") == "ACCEPTED"]
    assert accepted_blocks
    assert accepted_blocks[0]["early_stop_policy"] == "FIRST_SUFFICIENT_GATE_ACCEPTED"
    assert len(accepted_blocks[0]["attempts"]) == 1
    assert result["final_state_verified"]


class MisorderedBulkLinks(BulkLinks):
    def GetMultiAttValues(self, attr, only_active=False):
        rows = super().GetMultiAttValues(attr, only_active)
        if attr == "NO":
            values = [value for _, value in rows][::-1]
            return [(i, value) for i, value in enumerate(values, 1)]
        return rows


def test_bulk_object_order_mismatch_falls_back_or_fails_closed():
    collection = MisorderedBulkLinks(link_rows())
    adapter = adapter_for_links(collection, True, fallback=True)
    rows = adapter.read_links()
    assert len(rows) == 2 and adapter.last_link_read_mode == "SCALAR_FALLBACK"
    strict = adapter_for_links(MisorderedBulkLinks(link_rows()), True, fallback=False)
    with pytest.raises(SupplyContractError, match="OBJECT_ORDER_MISMATCH"):
        strict.read_links()


def test_generation_step_schedule_is_large_only_early_and_source_is_immutable():
    cfg = json.loads((ROOT / "R1_15A2_CONFIG_V2_4_6.json").read_text(encoding="utf-8"))
    original = copy.deepcopy(cfg)
    early = coupled._generation_counts_cfg(cfg, outer_cycle=1)
    full = coupled._generation_counts_cfg(cfg, outer_cycle=5)
    assert early["max_od_relative_up"] == pytest.approx(.12)
    assert early["max_add_log_up"] == pytest.approx(.08)
    assert early["salary"]["max_abs_delta_per_block"] == pytest.approx(.08)
    assert early["performance"]["active_generation_step_stage"]["name"] == "EXPLORE"
    assert full["max_od_relative_up"] == cfg["max_od_relative_up"]
    assert full["max_add_log_up"] == cfg["max_add_log_up"]
    assert full["salary"]["max_abs_delta_per_block"] == cfg["salary"]["max_abs_delta_per_block"]
    assert full["performance"]["active_generation_step_stage"]["name"] == "FULL_VERIFY"
    assert cfg == original


def test_v246_tampered_reference_and_bad_schedules_fail_before_model_mutation(tmp_path):
    cfg = json.loads((ROOT / "R1_15A2_CONFIG_V2_4_6.json").read_text(encoding="utf-8"))
    tampered = copy.deepcopy(cfg)
    tampered["coupled_demand"]["finecdf_td"]["reference_sha256"] = "0" * 64
    with pytest.raises(SupplyContractError, match="FILE_HASH_MISMATCH"):
        validate_v246_config(tampered, ROOT)

    escaped = copy.deepcopy(cfg)
    escaped["coupled_demand"]["finecdf_td"]["reference_script"] = "../outside.py"
    with pytest.raises(SupplyContractError, match="AUTHORITY_NOT_LOCKED"):
        validate_v246_config(escaped, ROOT)
    with pytest.raises(SupplyContractError, match="PATH_NOT_PACKAGE_RELATIVE"):
        bridge.load_reference(ROOT, escaped["coupled_demand"]["finecdf_td"])

    bad_generation = copy.deepcopy(cfg)
    bad_generation["performance"]["generation_step_schedule"][-1]["max_add_log_up"] = .02
    with pytest.raises(SupplyContractError, match="FINAL_GENERATION_STAGE_NOT_FULL"):
        validate_v246_config(bad_generation, ROOT)

    bad_td = copy.deepcopy(cfg)
    bad_td["coupled_demand"]["finecdf_td"]["progressive_schedule"][-1]["allow_progress_continue"] = True
    with pytest.raises(SupplyContractError, match="FINAL_TD_STAGE_MUST_BE_FULL"):
        validate_v246_config(bad_td, ROOT)


def test_global_user_stop_is_never_converted_to_progress_continue(tmp_path, monkeypatch):
    cfg, control, adapter = setup_workflow(tmp_path, monkeypatch)
    cfg["coupled_demand"].update(max_outer_cycles=5, min_stationary_cycles=2)
    cfg["coupled_demand"]["finecdf_td"] = {
        "progressive_schedule": [
            {"name": "EXPLORE", "through_outer_cycle": 2, "max_iterations": 2,
             "max_td_evaluations": 12, "allow_progress_continue": True},
            {"name": "FULL_VERIFY", "through_outer_cycle": 5, "max_iterations": 35,
             "max_td_evaluations": 180, "allow_progress_continue": False},
        ]
    }
    def inner(a, cfg, folder, ctl, package_root, phase_budget=None):
        return {"changed_rows": [], "stop_reason": "GLOBAL_USERSTOPREQUESTED",
                "search_complete": False, "stationarity_confirmed": False,
                "progress_continue": False,
                "backend": "SYNTHETIC_NATIVE_EVALUATOR_NOT_VISUM"}
    monkeypatch.setattr(coupled, "run_finecdf_inner", inner)
    result = coupled.run_overnight_calibration_coupled(
        adapter, cfg, tmp_path / "stopped", control, ROOT)
    assert result["status"] == "DEMAND_SEARCH_INCOMPLETE_SUPPLY_LOCKED:GLOBAL_USERSTOPREQUESTED"
    assert result["demand_cycles"][0]["status"] == "SEARCH_INCOMPLETE"
    assert result["completed_demand_cycles"] == 0
    assert not result["demand_converged"] and not result["supply_started"]


def test_v246_performance_benchmark_keeps_truth_boundary():
    from benchmarks.run_v246_performance_benchmark import run
    report = run()
    measured = report["measured_offline_synthetic"]
    assert report["status"] == "PASS_OFFLINE_EVIDENCE_ONLY"
    assert report["scientific_boundary"]["real_ptv_visum_tested"] is False
    assert report["scientific_boundary"]["real_wall_time_speedup_claim"] is None
    assert measured["v245"]["calibration_complete"]
    assert measured["v246"]["calibration_complete"]
    assert measured["v246"]["assignment_or_recompute_calls"] < measured["v245"]["assignment_or_recompute_calls"]
    assert measured["same_final_state"] is False
    assert report["measured_offline_lazy_evidence"]["incidence_ready_before_sequence"]

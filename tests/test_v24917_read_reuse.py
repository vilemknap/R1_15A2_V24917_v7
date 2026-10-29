"""Offline contracts for call-scoped reuse; never opens a Visum model."""
from collections import Counter, defaultdict
from pathlib import Path
from types import SimpleNamespace as NS

import numpy as np
import pytest

@pytest.fixture(autouse=True)
def current_modules():
    # Bootstrap tests can replace modules in sys.modules. Bind after bootstrap,
    # rather than retaining a second module/class identity from collection.
    global d11, evidence, adapter_mod, CountModel
    import r1_15a2_dynamic_11d_files_v24917 as d11
    import r1_15a2_active_demand_evidence_v24917 as evidence
    import r1_15a2_trial_adapter_v24917 as adapter_mod
    from r1_15a2_td_count_blend_v24917 import CountModel


def epoch(number=1):
    return NS(assignment_epoch=number, epoch=number, epoch_hash=str(number),
              zone_order_sha256="zones", summary=lambda: {"epoch_hash": str(number)})


def test_td_unique_directed_links_and_new_live_call(monkeypatch):
    model = CountModel.__new__(CountModel)
    model.profiles = [dict(**{"from": 1, "to": 2}, both=False),
                      dict(**{"from": 1, "to": 2}, both=True),
                      dict(**{"from": 2, "to": 1}, both=True)]
    calls = Counter()
    values = {(1, 2): 3., (2, 1): 7.}
    model._link = lambda fr, to: (fr, to)
    def volume(key):
        calls[key] += 1
        return values[key]
    model._vol = volume
    np.testing.assert_array_equal(model.read_live(), [3, 10, 10])
    assert calls == {(1, 2): 1, (2, 1): 1}
    values[1, 2] = 5.
    np.testing.assert_array_equal(model.read_live(), [5, 12, 12])
    assert calls == {(1, 2): 2, (2, 1): 2}


def test_td_failed_read_does_not_survive_next_call():
    model = CountModel.__new__(CountModel)
    model.profiles = [dict(**{"from": 1, "to": 2}, both=False)]
    model._link = lambda *key: key
    model._vol = lambda key: (_ for _ in ()).throw(RuntimeError("COM"))
    with pytest.raises(RuntimeError, match="COM"):
        model.read_live()
    model._vol = lambda key: 42.
    np.testing.assert_array_equal(model.read_live(), [42.])


def generation_adapter(monkeypatch):
    a = adapter_mod.VisumAdapter.__new__(adapter_mod.VisumAdapter)
    a.cfg = {"path_export_dsegs": ["NATIVE_CW"], "expected_zones": 2}
    a.zones = [1, 2]
    a.path_epoch_index = 1
    a.readback_manager = NS(mutation_epoch=0, assignment_epoch=0)
    a.v24916_dynamic_skims = NS(require_current=lambda: epoch())
    calls = []
    def read(_self):
        calls.append(1)
        return {"NATIVE_CW": np.full((2, 2), len(calls), dtype=float)}
    monkeypatch.setattr(adapter_mod._V24916ActiveAdapter, "_live_generation_matrices", read)
    return a, calls


def test_generation_reuses_only_inside_design_and_restores_on_exception(monkeypatch, tmp_path):
    a, calls = generation_adapter(monkeypatch)
    def design(*args):
        first = a._live_generation_matrices()
        second = a._live_generation_matrices()
        assert first is not second
        assert first["NATIVE_CW"] is second["NATIVE_CW"]
        assert not first["NATIVE_CW"].flags.writeable
        raise RuntimeError("design")
    a._generation_design_live = design
    for i in range(2):
        with pytest.raises(RuntimeError, match="design"):
            a.generation_design({}, tmp_path)
        assert not hasattr(a, "_v24917_generation_reads")
        assert len(calls) == i + 1
    a._live_generation_matrices()
    a._live_generation_matrices()
    assert len(calls) == 4


@pytest.mark.parametrize("change", ["mutation", "assignment", "skim", "path", "zones", "codes"])
def test_generation_invalidates_for_each_authority(monkeypatch, change):
    a, calls = generation_adapter(monkeypatch)
    a._v24917_generation_reads = {}
    first = a._live_generation_matrices()
    if change == "mutation": a.readback_manager.mutation_epoch += 1
    elif change == "assignment": a.readback_manager.assignment_epoch += 1
    elif change == "skim": a.v24916_dynamic_skims.require_current = lambda: epoch(2)
    elif change == "path": a.path_epoch_index += 1
    elif change == "zones": a.zones.reverse()
    else: a.cfg["path_export_dsegs"] = ["NATIVE_CS"]
    second = a._live_generation_matrices()
    assert len(calls) == 2
    assert first["NATIVE_CW"] is not second["NATIVE_CW"]


def test_generation_epoch_change_during_read_not_cached(monkeypatch):
    a, calls = generation_adapter(monkeypatch)
    a._v24917_generation_reads = {}
    def read(_self):
        a.readback_manager.mutation_epoch += 1
        return {"NATIVE_CW": np.ones((2, 2))}
    monkeypatch.setattr(adapter_mod._V24916ActiveAdapter, "_live_generation_matrices", read)
    with pytest.raises(RuntimeError, match="READ_EPOCH_CHANGED"):
        a._live_generation_matrices()
    assert a._v24917_generation_reads == {}


def test_generation_cache_owns_immutable_copies_without_freezing_producer(monkeypatch):
    a, calls = generation_adapter(monkeypatch)
    producer = np.array([[1., 2.], [3., 4.]])
    monkeypatch.setattr(adapter_mod._V24916ActiveAdapter, '_live_generation_matrices',
                        lambda self: {'NATIVE_CW':producer})
    a._v24917_generation_reads = {}
    cached = a._live_generation_matrices()['NATIVE_CW']
    assert producer.flags.writeable
    assert not cached.flags.writeable and not np.shares_memory(producer, cached)
    producer[:] = 99.
    np.testing.assert_array_equal(a._live_generation_matrices()['NATIVE_CW'], [[1,2],[3,4]])


def test_generation_nested_failure_restores_outer_read_scope(monkeypatch, tmp_path):
    a, calls = generation_adapter(monkeypatch)
    previous = a._v24917_generation_reads = {'outer':'scope'}
    def fail(*args):
        assert a._v24917_generation_reads is not previous
        a._live_generation_matrices()
        raise RuntimeError('nested design')
    a._generation_design_live = fail
    with pytest.raises(RuntimeError, match='nested design'):
        a.generation_design({}, tmp_path)
    assert a._v24917_generation_reads is previous
    assert previous == {'outer':'scope'}


def flow_reads(monkeypatch, shared=()):
    b = NS(_distance_epoch=lambda: epoch(), telemetry=defaultdict(int), adapter=NS(zones=[10,20]))
    reads = evidence._FlowBundleReads(b, epoch())
    reads.shared = set(shared)
    calls = []
    source = np.array([[1., 2.], [3., 4.]])
    def read(*args):
        calls.append(args[-1])
        return source
    monkeypatch.setattr(evidence.base, "_read_flowbundle_matrix", read)
    def link(no=1, fr=10, to=20):
        return NS(AttValue=lambda attr: {"NO": no, "FROMNODENO": fr, "TONODENO": to}[attr])
    return reads, calls, source, link


def test_flowbundle_owned_buffers_direction_dseg_and_no_single_use_retention(monkeypatch):
    reads, calls, source, link = flow_reads(monkeypatch, [(1, 10, 20, "CW")])
    first = reads.read(None, link(), None, "CW")
    source[:] = 99
    second = reads.read(None, link(), None, "CW")
    np.testing.assert_array_equal(second, [[1, 2], [3, 4]])
    assert first is second and not first.flags.writeable
    reads.read(None, link(fr=20, to=10), None, "CW")
    reads.read(None, link(), None, "CS")
    reads.read(None, link(no=2), None, "CW")
    assert len(calls) == 4 and len(reads.cache) == 1


def test_flowbundle_four_entry_lru_and_epoch_failure(monkeypatch):
    shared = [(i, 10, 20, "CW") for i in range(6)]
    reads, calls, _, link = flow_reads(monkeypatch, shared)
    for i in range(5): reads.read(None, link(i), None, "CW")
    assert len(reads.cache) == reads.peak == 4
    assert reads.evictions == 1
    reads.read(None, link(1), None, "CW")
    reads.read(None, link(5), None, "CW")
    assert (1, 10, 20, "CW") in reads.cache  # touch preserved it
    assert (2, 10, 20, "CW") not in reads.cache
    reads.builder._distance_epoch = lambda: epoch(2)
    with pytest.raises(RuntimeError, match="READ_EPOCH_CHANGED"):
        reads.read(None, link(1), None, "CW")
    assert not reads.cache


def test_flowbundle_failed_read_is_not_cached(monkeypatch):
    reads, calls, _, link = flow_reads(monkeypatch, [(1, 10, 20, "CW")])
    def fail(*args): raise RuntimeError("COM")
    monkeypatch.setattr(evidence.base, "_read_flowbundle_matrix", fail)
    with pytest.raises(RuntimeError, match="COM"):
        reads.read(None, link(), None, "CW")
    assert not reads.cache


@pytest.mark.parametrize("changed", ["mutation", "assignment", "path"])
def test_flowbundle_model_change_rejects_even_with_same_skim(monkeypatch, changed):
    reads, calls, _, link = flow_reads(monkeypatch, [(1, 10, 20, "CW")])
    reads.builder.adapter = NS(readback_manager=NS(mutation_epoch=1, assignment_epoch=1),
                               path_epoch_index=1, zones=[10, 20])
    reads.authority = reads._authority_key()
    reads.read(None, link(), None, "CW")
    if changed == "mutation": reads.builder.adapter.readback_manager.mutation_epoch += 1
    elif changed == "assignment": reads.builder.adapter.readback_manager.assignment_epoch += 1
    else: reads.builder.adapter.path_epoch_index += 1
    with pytest.raises(RuntimeError, match="READ_EPOCH_CHANGED"):
        reads.read(None, link(), None, "CW")
    assert not reads.cache and len(calls) == 1


def test_metric_hook_is_active_in_installed_runtime(monkeypatch):
    from test_v24917_targeted_catchup import _install_blend_with_fake_eval
    expected = {"WORK_X": {"objective": 1.}}
    _, bridge = _install_blend_with_fake_eval(monkeypatch, lambda self, matrices: expected)
    evaluator = bridge.DynamicFamilyMetrics(NS(dynamic_skim_epoch=epoch()), NS(__file__=__file__))
    with d11.capture_metrics() as captured:
        assert evaluator.evaluate({}) is expected
    assert captured["metrics"] is expected
    assert captured["epoch"] == d11.epoch_key(epoch())


def test_flowbundle_only_exact_shared_link_dseg_is_retained(monkeypatch):
    audits = [dict(selected=True, _source_row={"keys": [(1, 10, 20)]}, _v24916_family=f)
              for f in ["WORK", "WORK", "SERVICE"]]
    monkeypatch.setattr(evidence.base, "driver_profile_audit", lambda *a: audits)
    monkeypatch.setattr(evidence.base, "profile_directed_keys", lambda p: p["keys"])
    b = NS(cfg={}, _profile_rows=lambda: [], _distance_epoch=lambda: epoch(),
           _native_dsegs=lambda: [dict(code="CW", family="WORK"), dict(code="CS", family="SERVICE")])
    assert evidence._FlowBundleReads(b, epoch())._shared_links() == {(1, 10, 20, "CW")}


def test_flowbundle_unsupported_profile_does_not_make_a_link_shared(monkeypatch):
    audits = [dict(selected=True, _source_row={'keys':keys}, _v24916_family='WORK')
              for keys in [[(1,10,20)], [(1,10,20), (2,20,30), (3,30,40)]]]
    monkeypatch.setattr(evidence.base, 'driver_profile_audit', lambda *a: audits)
    monkeypatch.setattr(evidence.base, 'profile_directed_keys', lambda row: row['keys'])
    b = NS(cfg={}, _profile_rows=lambda:[], _distance_epoch=lambda:epoch(),
           _native_dsegs=lambda:[dict(code='CW', family='WORK')])
    assert evidence._FlowBundleReads(b, epoch())._shared_links() == set()


@pytest.mark.parametrize('bad', [np.full((2,2), np.nan), np.full((2,2), np.inf),
    np.array([[0.,-2.],[3.,0.]]), np.ones((1,1)), np.zeros((2,2)), [[1.],[2.,3.]]])
def test_flowbundle_invalid_read_does_not_poison_later_profile(monkeypatch, bad):
    reads, calls, _, link = flow_reads(monkeypatch, [(1,10,20,'CW')])
    good = np.array([[0.,2.],[3.,0.]])
    returned = iter([bad,good])
    monkeypatch.setattr(evidence.base, '_read_flowbundle_matrix', lambda *args:next(returned))
    reads.read(None, link(), None, 'CW')
    assert not reads.cache
    result = reads.read(None, link(), None, 'CW')
    np.testing.assert_array_equal(result,good)
    assert len(reads.cache) == 1


@pytest.mark.parametrize("both", [False, True])
def test_flowbundle_numpy_and_tuple_reduction_are_exactly_equal(both):
    from r1_15a2_flowbundle_v24916p2c import FlowBundleMatrixReducer
    a = np.array([[0., 3.], [3., 0.]])  # tied cells exercise deterministic top-k order
    b = np.array([[1., 0.], [2., 4.]])
    reducer = FlowBundleMatrixReducer([10, 20], top_k=2)
    kwargs = {"source_directions": ("FORWARD", "REVERSE") if both else ("DIRECTED",)}
    original = reducer.reduce(tuple(map(tuple, a)), tuple(map(tuple, b)) if both else None, **kwargs)
    optimized = reducer.reduce(a, b if both else None, **kwargs)
    assert optimized == original


def test_flowbundle_restores_builder_and_never_patches_parent_globals(monkeypatch, tmp_path):
    b = evidence.ActiveDemandEvidenceBuilder.__new__(evidence.ActiveDemandEvidenceBuilder)
    original_manager = b.manager = object()
    b._distance_epoch = lambda: epoch()
    globals_before = dict(evidence.base.__dict__)
    def fail(self, *args):
        assert dist.epoch_hash == "1"
        assert _read_flowbundle_matrix.__self__.builder is self
        raise RuntimeError("build")
    monkeypatch.setattr(evidence.base.ActiveDemandEvidenceBuilder, "build", fail)
    with pytest.raises(RuntimeError, match="build"):
        b.build({}, {}, tmp_path, {})
    assert b.manager is original_manager and not hasattr(b, "_v24917_epoch")
    assert evidence.base.__dict__.get("dist") == globals_before.get("dist")
    assert evidence.base._read_flowbundle_matrix is globals_before["_read_flowbundle_matrix"]


def publishing(monkeypatch, tmp_path):
    import r1_15a2_finecdf_bridge_v24916 as bridge
    import r1_15a2_supply_visum as supply
    ref = NS(__file__=str(tmp_path / "ref.py"), TARGETS={"WORK_X": {
        "matrix_nos": [9101], "edges": [0., 10., 20.]}})
    metric = {"WORK_X": dict(bin_volumes=[2., 3.], shares=[.4, .6], total_volume_diagnostic=5.)}
    monkeypatch.setattr(bridge, "load_reference", lambda *a: (ref, Path(ref.__file__), "sha"))
    monkeypatch.setattr(bridge.DynamicFamilyMetrics, "evaluate", lambda *a: metric)
    monkeypatch.setattr(supply.base, "build_td_signals_from_11d", lambda *a: ({"ok": True}, "csv"))
    static = [dict(component="WORK_X", bin_low=0, bin_high=10),
              dict(component="WORK_X", bin_low=10, bin_high=20)]
    calls = []
    def matrix(no):
        calls.append(no)
        return NS(GetValues=lambda: [[5.]])
    a = NS(v24916_dynamic_skims=NS(require_current=lambda: epoch()),
           _v24916_package_root=tmp_path, visum=NS(Net=NS(Matrices=NS(ItemByKey=matrix))))
    diag = {"d11": {"summary": {"component_dist_summary_rows": [{"component": "WORK_X"}]}},
            "dynamic_11d_reference_sha256": "sha"}
    d11.rt.write_csv(tmp_path / (d11.rt.D11_PREFIX + d11.SUFFIXES["baseline"]), static)
    captured = dict(epoch=d11.epoch_key(epoch()), reference_path=ref.__file__, metrics=metric)
    return a, diag, captured, calls, ref


def test_dynamic_11d_reuses_verified_metrics_with_identical_csv(monkeypatch, tmp_path):
    a, diag, captured, calls, ref = publishing(monkeypatch, tmp_path)
    path = tmp_path / (d11.rt.D11_PREFIX + d11.SUFFIXES["baseline"])
    assert not d11.publish_dynamic_files(a, diag, tmp_path, {})["verified_metrics_reused"]
    expected = path.read_bytes()
    assert calls == [9101]
    assert d11.publish_dynamic_files(a, diag, tmp_path, {}, captured=captured)["verified_metrics_reused"]
    assert path.read_bytes() == expected and calls == [9101]


@pytest.mark.parametrize("changed", ["epoch", "reference_path", "sha"])
def test_dynamic_11d_rejects_stale_capture(monkeypatch, tmp_path, changed):
    a, diag, captured, calls, ref = publishing(monkeypatch, tmp_path)
    if changed == "epoch": captured[changed] = d11.epoch_key(epoch(2))
    elif changed == "sha": diag["dynamic_11d_reference_sha256"] = "other"
    else: captured[changed] += "wrong"
    assert not d11.publish_dynamic_files(a, diag, tmp_path, {}, captured=captured)["verified_metrics_reused"]
    assert calls == [9101]


def test_dynamic_capture_nesting_and_exception_cleanup():
    evaluator = NS(bridge=NS(dynamic_skim_epoch=epoch()), ref=NS(__file__=__file__))
    with d11.capture_metrics() as outer:
        d11.record_metrics(evaluator, {"value": 1})
        with pytest.raises(RuntimeError):
            with d11.capture_metrics() as inner:
                d11.record_metrics(evaluator, {"value": 2})
                raise RuntimeError()
        assert outer["metrics"] == {"value": 1}
    assert d11._METRIC_CAPTURE.get() is None


@pytest.mark.parametrize('bad_first', [None, 'nan', 'zero'])
def test_real_inherited_flowbundle_build_reuses_and_publishes_safely(monkeypatch, tmp_path, bad_first):
    base = evidence.base
    audits = [dict(selected=True, profile_id=p, observed=10., model=1., geh=15.,
                   _v24916_family="WORK", _v24916_residual=9.,
                   _source_row={"key": (1, 10, 20)}) for p in ["P1", "P2"]]
    adapter = NS(cfg={}, zones=[10, 20], _live_generation_matrices=lambda: {})
    b = evidence.ActiveDemandEvidenceBuilder(adapter, tmp_path, {})
    b._distance_epoch = lambda: epoch()
    b._identity = lambda *args: "identity"
    b._profile_rows = lambda: []
    b._native_dsegs = lambda: [dict(code="NATIVE_CW", canonical_code="NATIVE_CW", family="WORK", object=object())]
    b._path_profile_od_rows = lambda matrices: []
    b.distance_value = lambda *args: 5.
    published = []
    def publish(**kwargs):
        published.append(kwargs)
        return NS(as_dict=lambda: {"published": True})
    b.manager = NS(get=lambda identity: None, publish=publish)
    monkeypatch.setattr(base, "driver_profile_audit", lambda *args: audits)
    monkeypatch.setattr(base, "profile_directed_keys", lambda row: [row["key"]])
    monkeypatch.setattr(base, "_exact_link", lambda *args: NS(AttValue=lambda a: {
        "NO": 1, "FROMNODENO": 10, "TONODENO": 20}[a]))
    reads = []
    def read(*args):
        reads.append(1)
        if bad_first and len(reads)==1:
            return [[0.,0.],[0.,0.]] if bad_first=='zero' else [[float('nan'),2.],[3.,0.]]
        return [[0.,2.],[3.,0.]]
    monkeypatch.setattr(base, "_read_flowbundle_matrix", read)
    monkeypatch.setattr(base, "path_parity", lambda *args: {
        "passing_profile_dseg_keys": ["P1|NATIVE_CW", "P2|NATIVE_CW"]})
    monkeypatch.setattr(base, "build_generation_targets", lambda *args: {"status": "ACTIVE"})
    monkeypatch.setattr(base, "build_td_targeting", lambda *args: {})
    for index in range(2):
        b.build({}, {"incidence": {}}, tmp_path / str(index), {})
        expected_reads = index + 1 + int(bool(bad_first))
        assert len(reads) == expected_reads  # never retained across build calls
        assert b.telemetry["FLOWBUNDLE_MATRIX_GETVALUES_COUNT"] == expected_reads
        assert len(published[-1]["flowbundles"]) == (1 if bad_first and index==0 else 2)
        assert published[-1]["skim_identity"].as_dict()["epoch_hash"] == "1"
    assert not hasattr(base, "dist")


def test_real_dynamic_overlay_reads_od_matrices_only_once(monkeypatch, tmp_path):
    from test_v24917_targeted_catchup import _install_blend_with_fake_eval
    import r1_15a2_supply_visum as supply
    metrics = {"WORK_X": dict(bin_volumes=[2., 3.], shares=[.4, .6],
        total_volume_diagnostic=5., conditioned_volume_diagnostic=5.,
        mean_model_km=10., mean_target_km=10., l1_half=0., rmse_share=0.,
        fine_cdf_rmse=0., dynamic_distance_family="WORK")}
    _, bridge = _install_blend_with_fake_eval(monkeypatch, lambda self, matrices: metrics)
    ref = NS(__file__=str(tmp_path / "ref.py"), TARGETS={"WORK_X": {
        "matrix_nos": [9101], "edges": [0., 10., 20.]}})
    monkeypatch.setattr(bridge, "load_reference", lambda *a: (ref, Path(ref.__file__), "sha"))
    monkeypatch.setattr(d11.rt, "assess_11d_idp_gate", lambda *a: {"passes": True})
    monkeypatch.setattr(supply.base, "build_td_signals_from_11d", lambda *a: ({}, "csv"))
    short = tmp_path / "short"
    monkeypatch.setattr(d11, "new_short_folder", lambda: short)
    static = tmp_path / "static"
    static.mkdir()
    for suffix in d11.SUFFIXES.values():
        rows = [dict(component="WORK_X", bin_low=0, bin_high=10),
                dict(component="WORK_X", bin_low=10, bin_high=20)]
        d11.rt.write_csv(static / (d11.rt.D11_PREFIX + suffix), rows)
    a = adapter_mod.VisumAdapter.__new__(adapter_mod.VisumAdapter)
    a.cfg = {}; a.zones = [1]; a._v24916_package_root = tmp_path
    current = epoch(); current.family_hashes = {"WORK": "hash"}
    a.v24916_dynamic_skims = NS(require_current=lambda: current)
    reads = []
    a.visum = NS(Net=NS(Matrices=NS(ItemByKey=lambda no: reads.append(no) or NS(GetValues=lambda: [[5.]]))))
    result = a._dynamic_11d_overlay({"d11": {"summary_path": str(static / "summary.json"),
        "summary": {"component_dist_summary_rows": [{"component": "WORK_X"}]}}, "d12": {}},
        tmp_path / "run", "BASELINE")
    assert reads == [9101]
    assert result["v24917_dynamic_11d_files"]["verified_metrics_reused"]
    assert d11._METRIC_CAPTURE.get() is None

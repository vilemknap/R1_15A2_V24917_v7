"""Production setup, per-family corrections, native TD guards and exact rollback."""
import contextlib
import copy
import importlib
from types import SimpleNamespace as NS

import numpy as np
import pytest

import R1_CREATE_COMPONENT_TD_UTILITIES as setup
import r1_15a2_component_td_utilities_v24917 as u
import r1_15a2_intrazonal_penalty_v24917 as iz
import r1_15a2_demand_policy_v1 as policy
from r1_15a2_supply import SupplyContractError


class Matrix:
    def __init__(self, no, a, code=''):
        self.values = np.array(a, dtype=float)
        self.attrs = dict(NO=no, CODE=code, NAME=code, MATRIXTYPE=4, OBJECTTYPEREF=2, DATASOURCETYPE=1)
        self.writes = 0
        self.fail_once = False
        self.fail_restore = False

    def AttValue(self, name):
        return self.attrs[name]

    def SetAttValue(self, name, value):
        self.attrs[name] = value

    def GetValues(self):
        return self.values.copy()

    def SetValues(self, a):
        self.values = np.array(a, dtype=float)
        self.writes += 1
        if self.fail_once:
            self.fail_once = False
            raise RuntimeError('PARTIAL_MATRIX_WRITE')
        if self.fail_restore:
            raise RuntimeError('PERSISTENT_MATRIX_WRITE_FAILURE')


class Parameter:
    def __init__(self):
        self.raw = 'Matrix([NO]=9002)'
        self.writes = 0
        self.fail_once = False

    def AttValue(self, name):
        if name != 'UTILITYFUNCTION':
            raise AttributeError(name)
        return self.raw

    def SetAttValue(self, name, value):
        assert name == 'UTILITYFUNCTION'
        self.raw = value
        self.writes += 1
        if self.fail_once:
            self.fail_once = False
            raise RuntimeError('PARTIAL_BINDING_WRITE')


@pytest.fixture
def model(monkeypatch):
    # Launcher tests replace r1 modules in sys.modules. Resolve the same current
    # module graph as the real launcher, rather than collection-time aliases.
    global u, iz, setup, policy, SupplyContractError
    u = importlib.import_module('r1_15a2_component_td_utilities_v24917')
    iz = importlib.import_module('r1_15a2_intrazonal_penalty_v24917')
    setup = importlib.import_module('R1_CREATE_COMPONENT_TD_UTILITIES')
    policy = importlib.import_module('r1_15a2_demand_policy_v1')
    SupplyContractError = importlib.import_module('r1_15a2_supply').SupplyContractError
    monkeypatch.setattr(setup, 'utilities', u)
    monkeypatch.setattr(setup, 'SupplyContractError', SupplyContractError)
    monkeypatch.setattr(u, 'vp', importlib.import_module('r1_15a2_visum_parameters'))
    monkeypatch.setattr(u, 'snapshot_reads', importlib.import_module('r1_15a2_snapshot_reads_v24917'))
    base = np.array([[2., 10., 20.], [12., 3., 15.], [18., 11., 4.]])
    z = (101, 305, 420)
    mats = {no: Matrix(no, base, 'M' + str(no)) for no in (9001, 9002, 9697, *range(9101, 9118))}
    for d, no in u.FLOW_NOS.items():
        mats[no] = Matrix(no, np.full((3, 3), 3. if d in ('NATIVE_CW', 'NATIVE_CS_NOT') else 1.))
    collection = NS(ItemByKey=lambda no: mats[no],
        GetMultiAttValues=lambda attr: [(i, m.AttValue(attr)) for i, m in enumerate(mats.values(), 1)])
    parameters = {r['component']: Parameter() for r in u.MAPPING}
    def parameter_state(v):
        return {'objects': {c: dict(dstrat=p, grav=p, status='OK') for c, p in parameters.items()}}
    monkeypatch.setattr(u.vp, 'read_td_parameter_state', parameter_state)
    def add(no, object_type, matrix_type):
        assert no not in mats and object_type == 2 and matrix_type == 4
        mats[no] = Matrix(no, np.zeros_like(base))
        return mats[no]
    v = NS(Net=NS(Matrices=collection, Zones=NS(GetMultiAttValues=lambda attr: list(enumerate(z, 1))),
        AddMatrix=add, RemoveMatrix=lambda matrix: mats.pop(matrix.AttValue('NO'))))
    monkeypatch.setattr(u.snapshot_reads, '_dseg_bindings', lambda visum: [
        dict(norm_code=d, matrix_no=no, object=NS(ODMatrix=mats[no])) for d, no in u.FLOW_NOS.items()])
    u.STATE.clear()
    iz.STATE.clear()
    env = NS(v=v, mats=mats, parameters=parameters, base=base, zones=z, add=add)
    yield env
    u.STATE.clear()
    iz.STATE.clear()


def prepare(m, tmp_path):
    result = setup.run(m.v, tmp_path)
    u.activate(m.v, m.zones, 9002)
    return result


def activate_iz(m):
    opts = dict(policy.DEFAULTS, iz_zones=[101])
    status = iz.activate(m.v, opts, print_fn=lambda *a: None)
    assert status['active'], status
    return opts


def test_setup_creates_16_distinct_inputs_with_unchanged_initial_result(model, tmp_path):
    before = {no: matrix.GetValues() for no, matrix in model.mats.items()}
    rec = prepare(model, tmp_path)
    assert rec['status'] == 'CREATED_AND_BOUND' and len(rec['created']) == 16
    assert not rec['assignment_executed'] and not rec['td_executed'] and not rec['version_saved']
    assert len(set(u.UTILITY_NOS)) == 16 and u.UTILITY_NOS == tuple(range(9700, 9716))
    for r in u.MAPPING:
        matrix = model.mats[r['utility_no']]
        assert matrix.AttValue('CODE') == r['utility_code']
        assert np.array_equal(matrix.values, model.base)
        assert u.ref_no(model.parameters[r['component']].raw) == r['utility_no']
    for no, a in before.items():
        assert np.array_equal(model.mats[no].values, a) and model.mats[no].writes == 0


def test_setup_idempotence_preserves_existing_corrections(model, tmp_path):
    prepare(model, tmp_path)
    arrays, _ = u.read_live(model.v)
    arrays[9700][0, 1] *= 1.5
    u.write_arrays(model.v, arrays)
    before = {no: matrix.GetValues() for no, matrix in model.mats.items()}
    rec = setup.run(model.v, tmp_path)
    assert rec['created'] == [] and rec['changed_bindings'] == 0
    for no, a in before.items():
        assert np.array_equal(model.mats[no].values, a)


def test_setup_dry_run_creates_nothing_and_changes_no_binding(model, tmp_path):
    rec = setup.run(model.v, tmp_path, dry_run=True)
    assert rec['status'] == 'PREFLIGHT_OK' and rec['dry_run']
    assert all(no not in model.mats for no in u.UTILITY_NOS)
    assert all(p.writes == 0 for p in model.parameters.values())


@pytest.mark.parametrize('failure', ['number_collision', 'code_collision', 'unexpected_reference', 'dangling_reference'])
def test_setup_finishes_preflight_before_any_mutation(model, tmp_path, failure):
    if failure == 'number_collision':
        model.mats[9708] = Matrix(9708, model.base, 'UNRELATED_MATRIX')
    elif failure == 'code_collision':
        model.mats[8000] = Matrix(8000, model.base, u.MAPPING[2]['utility_code'])
    elif failure == 'unexpected_reference':
        model.parameters['SCHOOL'].raw = 'Matrix([NO]=8000)'
    else:
        model.parameters['SCHOOL'].raw = 'Matrix([NO]=9715)'
    before = set(model.mats)
    with pytest.raises(SupplyContractError):
        setup.run(model.v, tmp_path)
    assert set(model.mats) == before
    assert all(p.writes == 0 for p in model.parameters.values())
    assert all(m.writes == 0 for m in model.mats.values())


def test_partial_parameter_setter_restores_bindings_and_removes_only_created_matrices(model, tmp_path):
    before = set(model.mats)
    model.parameters['LONG_E_C'].fail_once = True
    with pytest.raises(RuntimeError, match='PARTIAL_BINDING_WRITE'):
        setup.run(model.v, tmp_path)
    assert set(model.mats) == before
    assert all(p.raw == 'Matrix([NO]=9002)' for p in model.parameters.values())


def test_partial_matrix_creation_is_owned_before_com_returns(model, tmp_path):
    before = set(model.mats)
    def partial_add(*args):
        matrix = model.add(*args)
        if args[0] == 9704:
            raise RuntimeError('PARTIAL_ADD_MATRIX')
        return matrix
    model.v.Net.AddMatrix = partial_add
    with pytest.raises(RuntimeError, match='PARTIAL_ADD_MATRIX'):
        setup.run(model.v, tmp_path)
    assert set(model.mats) == before
    assert all(p.writes == 0 for p in model.parameters.values())


def time_inputs():
    route_ratios = dict(NATIVE_CW=1.2, NATIVE_CW_NOT=2., NATIVE_CS=1.5, NATIVE_CS_NOT=3., NATIVE_CL=1.8)
    times = {d: (np.full((3, 3), 300. * r), np.full((3, 3), 300.)) for d, r in route_ratios.items()}
    flows = {d: np.full((3, 3), 3. if d in ('NATIVE_CW', 'NATIVE_CS_NOT') else 1.) for d in u.FLOW_NOS}
    return times, flows


def test_family_ratios_use_actual_route_shares_and_preserve_component_identity(model, tmp_path):
    prepare(model, tmp_path)
    times, flows = time_inputs()
    ratios = u.ratios(times, flows, 3, 4.)
    assert ratios['WORK'][0, 1] == pytest.approx(1.4)
    assert ratios['SERVICE'][0, 1] == pytest.approx(2.625)
    assert ratios['LONG'][0, 1] == pytest.approx(1.8)
    assert np.array_equal(ratios['SCHOOL'], ratios['WORK'])
    old, base = u.read_live(model.v)
    result = u.targets(base, old, ratios, .5)
    assert result[9700][0, 1] == pytest.approx(12.)
    assert result[9705][0, 1] == pytest.approx(18.125)
    assert result[9710][0, 1] == pytest.approx(14.)
    assert np.array_equal(result[9700], result[9701])
    assert result[9700] is not result[9701]
    for a in result.values():
        assert np.array_equal(np.diag(a), np.diag(base))


def test_ratio_clipping_invalid_paths_and_zero_demand_have_deterministic_fallback():
    times, flows = time_inputs()
    times['NATIVE_CW'][0][0, 1] = 0.
    times['NATIVE_CW_NOT'][0][0, 1] = 900.
    times['NATIVE_CL'][0][0, 1] = -1.
    times['NATIVE_CS'][0][1, 2] = 30000.
    for f in flows.values():
        f[2, 1] = 0.
    r = u.ratios(times, flows, 3, 4.)
    assert r['WORK'][0, 1] == 3.  # valid noT only, no dilution by an invalid path
    assert r['LONG'][0, 1] == 1.  # retain the common base where no valid time exists
    assert r['SERVICE'][1, 2] == pytest.approx(3.25)
    assert r['WORK'][2, 1] == 1.2  # minimum available ratio with zero current demand


@pytest.mark.parametrize('failure', ['negative_weight', 'nan_time', 'shape', 'ratio_limit'])
def test_pure_computation_rejects_invalid_authoritative_inputs(failure):
    times, flows = time_inputs()
    limit = 4.
    if failure == 'negative_weight':
        flows['NATIVE_CW'][0, 1] = -1.
    elif failure == 'nan_time':
        times['NATIVE_CL'][0][0, 1] = np.nan
    elif failure == 'shape':
        flows['NATIVE_CS'] = np.zeros((2, 3))
    else:
        limit = .5
    with pytest.raises(SupplyContractError):
        u.ratios(times, flows, 3, limit)


def test_partial_component_write_restores_all_owned_inputs_and_keeps_state(model, tmp_path):
    prepare(model, tmp_path)
    before = copy.deepcopy(u.STATE['current'])
    arrays, _ = u.read_live(model.v)
    for a in arrays.values():
        a[0, 1] *= 1.25
    model.mats[9703].fail_once = True
    with pytest.raises(RuntimeError, match='PARTIAL_MATRIX_WRITE'):
        u.write_arrays(model.v, arrays)
    assert u.verify(model.v) == before
    assert all(np.array_equal(model.mats[no].values, model.base) for no in u.UTILITY_NOS)


def test_persistent_write_failure_reports_unverified_restore(model, tmp_path):
    prepare(model, tmp_path)
    arrays, _ = u.read_live(model.v)
    arrays[9701][0, 1] *= 1.25
    model.mats[9701].fail_restore = True
    with pytest.raises(SupplyContractError, match='TD_UTILITY_RESTORE_UNVERIFIED'):
        u.write_arrays(model.v, arrays)


@pytest.mark.parametrize('failure', ['values', 'binding', 'formula_source', 'base', 'zone_order'])
def test_live_guards_detect_unowned_or_stale_inputs(model, tmp_path, failure):
    prepare(model, tmp_path)
    if failure == 'values':
        model.mats[9702].values[0, 1] += 1.
    elif failure == 'binding':
        model.parameters['WORK_E_C'].raw = 'Matrix([NO]=9002)'
    elif failure == 'formula_source':
        model.mats[9702].attrs['DATASOURCETYPE'] = 'FORMULA'
    elif failure == 'base':
        model.mats[9002].values[0, 1] += 1.
    else:
        model.v.Net.Zones.GetMultiAttValues = lambda attr: list(enumerate(reversed(model.zones), 1))
    with pytest.raises(SupplyContractError):
        u.verify(model.v)


def test_snapshot_hash_includes_inputs_and_rollback_restores_corrections_and_common_penalty(model, tmp_path):
    prepare(model, tmp_path)
    activate_iz(model)
    raw = dict(state_hash='b' * 64, generation_hash='g' * 64)
    parent = iz.extend_snapshot(u.extend_snapshot(raw, model.v), model.v)
    arrays, _ = u.read_live(model.v)
    arrays[9700][0, 1] *= 1.5
    u.write_arrays(model.v, arrays)
    iz.write_penalty(model.v, [2.5])
    child = iz.extend_snapshot(u.extend_snapshot(raw, model.v), model.v)
    assert child['state_hash'] != parent['state_hash']
    assert child[u.SNAPSHOT_KEY] != parent[u.SNAPSHOT_KEY]
    assert all(model.mats[no].values[0, 0] == 4.5 for no in u.UTILITY_NOS)
    iz.restore_from_snapshot(model.v, parent)
    assert iz.extend_snapshot(u.extend_snapshot(raw, model.v), model.v) == parent
    assert model.mats[9002].values[0, 1] == model.base[0, 1]


def test_failed_diagonal_propagation_restores_common_and_components_together(model, tmp_path):
    prepare(model, tmp_path)
    activate_iz(model)
    before = copy.deepcopy(u.STATE['current'])
    model.mats[9707].fail_once = True
    with pytest.raises(RuntimeError, match='PARTIAL_MATRIX_WRITE'):
        iz.write_penalty(model.v, [2.])
    assert u.verify(model.v) == before
    assert np.array_equal(model.mats[9002].values, model.base)
    assert np.array_equal(iz.read_penalty(model.v), [0.])


def test_component_mode_cannot_update_common_congestion_again(model, tmp_path):
    prepare(model, tmp_path)
    activate_iz(model)
    with pytest.raises(iz.IZError, match='COMMON_BASE_IS_FIXED'):
        iz.set_base(model.v, model.base * 1.5)
    assert model.mats[9002].writes == 0


def test_default_component_policy_requires_setup_instead_of_common_fallback(model):
    status = iz.activate(model.v, dict(policy.DEFAULTS), print_fn=lambda *a: None)
    assert not status['active']
    assert setup.__name__ + '.py' in status['reason']
    with pytest.raises(iz.IZError, match='IC_REQUIRED_BUT_INACTIVE'):
        iz.congestion_due({}, 2)


def test_default_options_select_component_mode():
    assert policy.load_options()['ic_utility_mode'] == 'COMPONENT'


def test_native_guard_and_restore_optimization_include_all_utility_inputs(model, tmp_path):
    from r1_15a2_finecdf_bridge_v24916 import NoDirectMatrixWriteTDAdapter
    import r1_15a2_td_restore_v24917 as restore
    prepare(model, tmp_path)
    assert u.install()['native_source_unchanged']
    bridge = NoDirectMatrixWriteTDAdapter.__new__(NoDirectMatrixWriteTDAdapter)
    bridge.v = model.v
    bridge.ref = NS(sha_array=u.matrix_values_hash)
    bridge._guard_generation_addval = lambda: None
    bridge.read_matrix = lambda no: model.mats[no].GetValues()
    bridge.protected_hashes = {no: u.matrix_values_hash(model.mats[no].values) for no in (9001, 9697, 9116)}
    bridge.guard_protected(full=True)
    assert set(u.UTILITY_NOS) <= set(restore.protected_matrix_nos(bridge))
    model.mats[9712].values[1, 0] += 1.
    with pytest.raises(SupplyContractError, match='UNOWNED_MATRIX_CHANGE'):
        bridge.guard_protected(full=True)


@pytest.mark.parametrize('fail_native', [False, True])
def test_actual_feedback_runs_native_recompute_or_verified_parent_rollback(model, tmp_path, monkeypatch, fail_native):
    import r1_15a2_td_impedance_refresh_v24917 as fresh
    prepare(model, tmp_path)
    opts = activate_iz(model)
    calls = []
    times, _ = time_inputs()
    def refresh_many(adapter, dsegs, folder):
        assert tuple(dsegs) == u.REQUIRED_DSEGS
        calls.append('FRESH_5_NATIVE_TIME_SKIMS')
        return times, {'status': 'FRESH_NATIVE_TIME_SKIMS'}
    monkeypatch.setattr(fresh, 'refresh_many', refresh_many)
    adapter = NS(visum=model.v, invalidate_candidate_readback=lambda *a, **kw: calls.append('INVALIDATE'))
    epoch = object()
    adapter.v24916_dynamic_skims = NS(require_current=lambda: epoch)
    raw = dict(state_hash='b' * 64, td_values=[], generation_hash='g' * 64)
    adapter.snapshot = lambda: iz.extend_snapshot(u.extend_snapshot(raw, model.v), model.v)
    adapter.diagnostics = lambda *a: {'fresh': True}
    parent = adapter.snapshot()
    diag = {'fresh': False}
    def assign(*args):
        calls.append('FULL_DOWNSTREAM_NATIVE_RECOMPUTE')
        assert np.array_equal(model.mats[9002].values, model.base)
        assert model.mats[9700].values[0, 1] == pytest.approx(12.)
        if fail_native:
            raise RuntimeError('NATIVE_REALIZATION_FAILURE')
        return .001
    def rollback(adapter, state, baseline, *args):
        calls.append('VERIFIED_PARENT_ROLLBACK')
        iz.restore_from_snapshot(model.v, state, adapter)
        assert adapter.snapshot() == state
        return state, baseline
    ctrl = NS(recovery_scope=lambda *a: contextlib.nullcontext(), _assign_candidate=assign,
              _td_expected_freeze=lambda *a: None, _rollback_td_all=rollback)
    transitions = []
    adapter.accepted_state_changed = lambda state, diag, **kw: transitions.append(kw) or {'rebound': True}
    after, result_diag, rec = iz.congestion_feedback(ctrl, adapter, {}, tmp_path / 'feedback', None, parent, diag)
    assert rec['fresh_time_skim_proof']['status'] == 'FRESH_NATIVE_TIME_SKIMS'
    assert np.array_equal(model.mats[9002].values, model.base)
    assert model.mats[9002].writes == 0 and model.mats[9001].writes == 0
    if fail_native:
        assert rec['status'] == 'FAILED_ROLLED_BACK' and not rec['applied']
        assert after == parent and result_diag == diag
        assert 'VERIFIED_PARENT_ROLLBACK' in calls
        assert not transitions
    else:
        assert rec['status'] == 'APPLIED' and rec['applied']
        assert after[u.SNAPSHOT_KEY] != parent[u.SNAPSHOT_KEY] and result_diag['fresh']
        assert model.mats[9705].values[0, 1] == pytest.approx(18.125)
        assert transitions == [{'reason': 'COMPONENT_TD_UTILITY_REFRESH', 'phase': 'DEMAND'}]


def test_reference_parser_never_accepts_a_compound_utility_formula():
    assert u.ref_no('Matrix([NO] = 9701)') == 9701
    assert u.ref_no('Matrix([NO]=9701)+2') is None


def test_weight_reads_refuse_another_live_dseg_matrix_with_identical_values(model, monkeypatch):
    rows = u.snapshot_reads._dseg_bindings(model.v)
    rows[0]['matrix_no'] = 8000
    monkeypatch.setattr(u.snapshot_reads, '_dseg_bindings', lambda visum: rows)
    with pytest.raises(SupplyContractError, match='WEIGHT_BINDING_CHANGED'):
        u.read_weights(NS(visum=model.v))


def test_production_adapter_snapshot_includes_live_component_state(model, tmp_path, monkeypatch):
    from r1_15a2_trial_adapter_v24917 import VisumAdapter
    prepare(model, tmp_path)
    adapter = VisumAdapter.__new__(VisumAdapter)
    adapter.visum = model.v
    adapter._sync_readback_telemetry = lambda: None
    adapter._record_snapshot_event = lambda *a, **kw: None
    current_reads = importlib.import_module('r1_15a2_trial_adapter_v24917').snapshot_reads
    monkeypatch.setattr(current_reads, 'strict_snapshot', lambda ad: {'state_hash': 'b' * 64})
    snapshot = adapter.legacy_snapshot_from_live_visum()
    assert snapshot[u.SNAPSHOT_KEY] == u.verify(model.v)
    assert snapshot['state_hash'] != 'b' * 64
    model.mats[9701].values[0, 1] += 1.
    with pytest.raises(SupplyContractError, match='UNOWNED_MATRIX_CHANGE'):
        adapter.legacy_snapshot_from_live_visum()


@pytest.mark.parametrize('invalid', [{'ic_utility_mode': 'OTHER'}, {'ic_mode': 'ABSOLUTE'},
                                   {'ic_refresh_policy': 'LATE_PHASE'}, {'iz_matrix_no': 9010}])
def test_component_policy_rejects_incompatible_methods(invalid):
    with pytest.raises(RuntimeError, match='R1_RUN_OPTION_INVALID'):
        policy.validate(invalid)


def test_failed_setup_binding_restore_retains_created_matrices_instead_of_dangling_refs(model, tmp_path):
    parameter = model.parameters['LONG_E_C']
    original = parameter.SetAttValue
    def fail_restore(name, value):
        if value == 'Matrix([NO]=9002)':
            raise RuntimeError('RESTORE_BINDING_REFUSED')
        original(name, value)
    parameter.SetAttValue = fail_restore
    parameter.fail_once = True
    with pytest.raises(SupplyContractError, match='SETUP_RESTORE_UNVERIFIED'):
        setup.run(model.v, tmp_path)
    assert set(u.UTILITY_NOS) <= set(model.mats)
    assert u.ref_no(parameter.raw) == 9710 and 9710 in model.mats


def test_converged_fresh_corrections_skip_native_realization_and_all_writes(model, tmp_path, monkeypatch):
    import r1_15a2_td_impedance_refresh_v24917 as fresh
    prepare(model, tmp_path)
    opts = activate_iz(model)
    times = {d: (np.ones((3, 3)), np.ones((3, 3))) for d in u.REQUIRED_DSEGS}
    calls = []
    def refresh(*args):
        calls.append('FRESH')
        return times, {'status': 'FRESH_NATIVE_TIME_SKIMS'}
    monkeypatch.setattr(fresh, 'refresh_many', refresh)
    epoch = object()
    adapter = NS(visum=model.v, v24916_dynamic_skims=NS(require_current=lambda: epoch))
    writes_before = sum(m.writes for m in model.mats.values())
    parent, diag = {'state_hash': 'b' * 64}, {'fresh': False}
    state, result, rec = u.feedback(NS(), adapter, {}, tmp_path, None, parent, diag, opts)
    assert calls == ['FRESH'] and rec['status'] == 'CONVERGED_NO_WRITE'
    assert state is parent and result is diag
    assert sum(m.writes for m in model.mats.values()) == writes_before


def test_new_epoch_during_preparation_cannot_write_utilities(model, tmp_path, monkeypatch):
    import r1_15a2_td_impedance_refresh_v24917 as fresh
    prepare(model, tmp_path)
    opts = activate_iz(model)
    epochs = iter([object(), object()])
    adapter = NS(visum=model.v, v24916_dynamic_skims=NS(require_current=lambda: next(epochs)))
    times, _ = time_inputs()
    monkeypatch.setattr(fresh, 'refresh_many', lambda *a: (times, {'status': 'FRESH_NATIVE_TIME_SKIMS'}))
    writes_before = sum(m.writes for m in model.mats.values())
    with pytest.raises(SupplyContractError, match='ASSIGNMENT_CHANGED_DURING_PREPARATION'):
        u.feedback(NS(), adapter, {}, tmp_path, None, {}, {}, opts)
    assert sum(m.writes for m in model.mats.values()) == writes_before


def test_returned_snapshot_cannot_mutate_runtime_rollback_authority(model, tmp_path):
    prepare(model, tmp_path)
    expected = copy.deepcopy(u.STATE['current'])
    snapshot = u.extend_snapshot({'state_hash': 'b' * 64}, model.v)
    snapshot[u.SNAPSHOT_KEY]['matrices']['9700'] = 'CALLER_CHANGED_ITS_OWN_SNAPSHOT'
    assert u.verify(model.v) == expected

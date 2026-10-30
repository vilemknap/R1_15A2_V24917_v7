"""Shared-cache LONG port: production SQL, solver, preview/apply and freshness."""
import copy
import math
import sqlite3
from types import SimpleNamespace as NS

import numpy as np
import pytest

import r1_15a2_core as core
import r1_15a2_long_cache_generation_v24917 as lc
import r1_15a2_long_school_generation_v24917 as ls
import r1_15a2_mobility_zone_v24917 as mz
import r1_15a2_zonal_count_fit_v24917 as zf
from test_v24917_long_incidence_read import harness as read_harness
from test_v24917_mobilityzone1 import authority, zones as mobility_rows


@pytest.fixture
def live():
    adapter, state, profiles = read_harness()
    db = sqlite3.connect(':memory:')
    db.executescript('''
        CREATE TABLE geometry(gid INTEGER, orig INTEGER, dest INTEGER, edge_count INTEGER);
        CREATE TABLE volumes(gid INTEGER, dseg TEXT, volume REAL);
        CREATE TABLE profile_hits(gid INTEGER, profile_index INTEGER, multiplicity INTEGER);
        INSERT INTO geometry VALUES(1,1,2,4),(2,1,2,1),(3,2,1,1);
        INSERT INTO volumes VALUES(1,'NATIVE_CL',80),(2,'NATIVE_CL',20),(3,'NATIVE_CL',50);
        INSERT INTO profile_hits VALUES(1,0,2),(1,1,1),(2,1,1),(3,1,1);
    ''')
    adapter.cache = NS(db=db, incidence_ready=True, parents={'NATIVE_CL': {'passes': True, 'matrix_no': 9305}},
                       profiles=profiles, parent_hash='original-cache-parent')
    adapter.path_epoch_index = 1
    adapter._cache_context_compatible = lambda snap: True
    adapter.policy = NS(parity_absolute_tolerance=1.e-6, parity_relative_tolerance=1.e-8)
    state.coeff = {'ADD_PROD_L': [.3, .3], 'ADD_ATT_L': [1., 1.],
                   'ADD_PROD_SCH': [1., 1.], 'ADD_ATT_SCH': [1., 1.]}
    state.writes = []
    class Zones:
        def GetMultiAttValues(self, attr, active=False):
            return list(enumerate(state.zone_order if attr == 'NO' else state.coeff[attr], 1))
        def SetMultiAttValues(self, attr, rows, active=False):
            state.writes.append(attr)
            for index, value in rows: state.coeff[attr][index-1] = value
    adapter.visum.Net.Zones = Zones()
    # Deliberately no available export API: reuse of the existing store is required.
    adapter.visum.Workbench = None
    try: yield adapter, state, profiles
    finally: db.close()


def problem(profiles):
    rows = [{'profile_index': i, 'countlocation_no': p['countlocation_no'],
             'model': model, 'observed': obs}
            for i, (p, model, obs) in enumerate(zip(profiles, [220., 210.], [260., 200.]))]
    return zf.FitProblem([1, 2], rows, np.zeros((2, 0)), np.array([40., -10.]),
                         np.ones(2), [], np.array([]), np.array([]), np.array([]), {})


def payload(live, monkeypatch):
    adapter, state, profiles = live
    observed = lc.capture(adapter)
    ws = problem(profiles)
    a = authority(mobility_rows())
    monkeypatch.setattr(ls, 'ls_options', lambda: dict(ls.LS_DEFAULTS))
    refs = {'ADD_ATT_L': {'1': 1., '2': 1.}}
    opts = {'longguard1_allow_long': True, 'long_cache_incidence': observed,
            'long_mobility_authority': a, 'max_iter': 2000}
    inc = {'variables': [], 'incidence': core.SparseOperator(
        np.array([], dtype=int), np.array([], dtype=int), np.array([]), 2, 0)}
    state.arrays[9225] = np.zeros((2, 2))
    state.arrays[9226] = np.ones((2, 2))
    result = ls.design(adapter.visum, {'max_add_log_up': .5, 'max_add_log_down': .5},
                        [1, 2], inc, ws, {'predicted_change': np.zeros(2)}, refs, opts)
    return result, observed, ws, a


def test_shared_store_exact_profile_multiplicity_components_and_no_export(live):
    adapter, state, _ = live
    out = lc.capture(adapter)
    assert out['status'] == lc.STATUS and not out['tg_sensitivity_verified']
    assert out['profile_long_vehicle_flow'] == pytest.approx([160., 150.])
    assert out['component_profile_vehicle_flow']['9291'] == pytest.approx([96., 70.])
    assert out['component_profile_vehicle_flow']['9292'] == pytest.approx([64., 80.])
    assert out['profile_parity_max_abs'] == 0.
    assert state.exports == 0 and state.writes == []


def test_frozen_shares_reweighted_with_current_od_without_reexport(live):
    adapter, state, _ = live
    for no in lc.longinc.COMPONENT_MATRICES + (9305,): state.arrays[no] *= 2.
    state.profile_flow = {k: v*2 for k, v in state.profile_flow.items()}
    out = lc.capture(adapter)
    assert out['profile_long_vehicle_flow'] == pytest.approx([320., 300.])
    assert out['variables'][0]['q_current'] == 200.
    assert state.exports == 0


@pytest.mark.parametrize('fault,reason', [('share', 'REFRESH_REQUIRED'),
    ('profile', 'REFRESH_REQUIRED'), ('component', 'COMPONENT_TO_FINAL'),
    ('support', 'OSRM_SUPPORT'), ('geometry', 'WITHOUT_GEOMETRY'),
    ('missing_cl', 'NATIVE_CL_MISSING'), ('epoch', 'BINDING_STALE')])
def test_invalid_cache_or_parent_never_creates_proposal(live, fault, reason):
    adapter, state, _ = live
    if fault == 'share': adapter.cache.db.execute("UPDATE volumes SET volume=0 WHERE gid=3")
    elif fault == 'profile': state.profile_flow[(1, 2)] += 10.
    elif fault == 'component': state.arrays[9291][0, 1] += 1.
    elif fault == 'support': state.arrays[9697][0, 1] = 79.99
    elif fault == 'geometry': adapter.cache.db.execute('UPDATE geometry SET edge_count=0 WHERE gid=1')
    elif fault == 'missing_cl': adapter.cache.parents = {}
    else: adapter.readback_manager.mutation_epoch += 1
    with pytest.raises(ValueError, match=reason): lc.capture(adapter)
    assert not state.writes


def test_long_fit_is_zonal_bounded_and_preserves_nonlinear_pa(live, monkeypatch):
    result, observed, ws, a = payload(live, monkeypatch)
    assert result['summary']['long_generation_permitted'], result['summary']
    assert result['summary']['long_objective_final'] < result['summary']['long_objective_initial']
    assert result['summary']['long_balance_mode'] == 'HARD'
    assert result['steps']['ADD_PROD_L'][1] != result['steps']['ADD_PROD_L'][2]
    rows = ls.rows_at_scale(result, 1.)
    assert rows and {r['family'] for r in rows} == {'LONG'}
    for row in rows:
        assert .9-1.e-12 <= row['proposed']/row['current'] <= 1.1+1.e-12
        if row['role'] == 'PROD': assert .15 <= row['proposed'] <= .45
    p = sum(observed['vehicle_production'][z-1]*math.expm1(s)
            for z, s in result['steps'].get('ADD_PROD_L', {}).items())
    att = sum(observed['vehicle_attraction'][z-1]*math.expm1(s)
              for z, s in result['steps'].get('ADD_ATT_L', {}).items())
    assert p == pytest.approx(att, abs=2.e-8)
    guarded = mz.guard_ls(result, a)
    assert guarded['summary']['long_generation_permitted']
    assert guarded['predicted_change'] == pytest.approx(result['predicted_change'])
    assert mz.check_candidate(rows, a)['passes']


def test_long_zonal_fit_does_not_subtract_unrealized_school_effect(live, monkeypatch):
    adapter, _, profiles = live
    observed = lc.capture(adapter)
    ws = problem(profiles)
    # SCHOOL's speculative 0.1 log-step predicts [1, 1.2] profile vehicles,
    # but the AMDY SCHOOL production formula does not depend on ADD_PROD_SCH.
    # The candidate SCHOOL step will be frozen by the same MOBILITYZONE1 gate;
    # it must be excluded BEFORE solving the LONG residual, not only after.
    school = {
        'steps': {'ADD_PROD_SCH': {1: .1}},
        'current': {'ADD_PROD_SCH': {1: 1.}},
        'predicted_change': [1., 1.2],
        'effect_operator': {'keys': [['SCHOOL', 'PROD', 1]],
                            'G': [[10.], [12.]]},
        'summary': {'status': 'OK'},
    }
    monkeypatch.setattr(ls, 'ls_options', lambda: dict(ls.LS_DEFAULTS))
    actual_authority = authority(mobility_rows())
    # The imported synthetic fixture certifies a proportional SCHOOL formula.
    # Reproduce the REAL 2026-10-30 AMDY source, where this extra coefficient
    # is not wired into FP_5_SCHOOL and must not affect LONG's residual.
    actual_authority['school_fp_link_verified'] = False
    fit_cfg = {
        'long_mobility_authority': actual_authority,
        'max_iter': 2000,
    }
    out = lc.attach_fit(school, observed, adapter.visum,
                        {'max_add_log_up': .5, 'max_add_log_down': .5}, [1, 2],
                        ws, {'predicted_change': np.zeros(2)},
                        {'ADD_ATT_L': {'1': 1., '2': 1.}}, fit_cfg)
    assert out['steps']['ADD_PROD_SCH'] == {}
    assert out['steps']['ADD_ATT_SCH'] == {}
    assert out['summary']['school_generation_status'] == (
        'FIXED_AMDY_NO_SCHOOL_ADD_COEFFICIENT')
    assert out['summary']['long_generation_permitted']
    assert out['summary']['long_zone_steps'] > 0


def test_missing_attraction_reference_defers_long_and_retains_school(live, monkeypatch):
    adapter, _, profiles = live
    obs = lc.capture(adapter)
    school = {'steps': {'ADD_PROD_SCH': {1: .01}}, 'predicted_change': [1., 2.],
              'summary': {'status': 'OK'}}
    monkeypatch.setattr(ls, '_school_design', lambda *a, **k: copy.deepcopy(school))
    out = ls.design(adapter.visum, {}, [1, 2], {}, problem(profiles),
        {'predicted_change': np.zeros(2)}, {}, {'long_cache_incidence': obs,
        'longguard1_allow_long': True, 'long_mobility_authority': authority(mobility_rows())})
    assert out['steps'] == school['steps'] and out['predicted_change'] == [1., 2.]
    assert not out['summary']['long_generation_permitted']
    assert 'REFERENCE_MISSING' in out['summary']['long_deferred_reason']


def test_ordinary_live_mobility_and_finecdf_gates_still_reject(live, monkeypatch):
    import r1_15a2_long_distance_guard_v24917 as guard
    from test_v24917_longguard1 import evidence
    result, _, _, a = payload(live, monkeypatch)
    rows = ls.rows_at_scale(result, 1.)
    assert guard.changed_long(rows)
    rejected = guard.decide(evidence(fine=.1), evidence(fine=.12), changed_long=True)
    assert not rejected['passes'] and 'LONGGUARD1_512_CDF_DEGRADED' in rejected['reasons']
    invalid = [{'zone_no': 1, 'family': 'LONG', 'role': 'PROD', 'attr': 'ADD_PROD_L',
                'current': .3, 'proposed': .46, 'log_step': math.log(.46/.3)}]
    assert not mz.check_candidate(invalid, a)['passes']


def test_receipt_invalidates_after_assignment_mutation_or_cache_refresh(live):
    adapter, _, _ = live
    receipt = lc.capture(adapter)
    lc.require_current(adapter, receipt)
    adapter.path_epoch_index += 1
    with pytest.raises(ValueError, match='PROPOSAL_STALE'): lc.require_current(adapter, receipt)
    adapter.path_epoch_index -= 1
    adapter.readback_manager.mutation_epoch += 1
    with pytest.raises(ValueError, match='PROPOSAL_STALE'): lc.require_current(adapter, receipt)


def test_real_adapter_preview_and_apply_include_long_with_unchanged_parent_owner(live, monkeypatch, tmp_path):
    import contextlib
    import r1_15a2_trial_adapter_v24917 as mod
    fixture, state, profiles = live
    result, observed, ws, a = payload(live, monkeypatch)
    adapter = object.__new__(mod.VisumAdapter)
    adapter.__dict__.update(vars(fixture))
    adapter.generation_reference_values = {'ADD_ATT_L': {'1': 1., '2': 1.}}
    adapter._v24917_overlay = lambda phase: contextlib.nullcontext(adapter.cfg)
    adapter._phase_of = lambda context: None
    adapter.zone_write_index_by_no = {1: 1, 2: 2}
    adapter.zone_readback_tolerance = 1.e-9
    def invalidate(reason, mutation=True):
        if mutation: adapter.readback_manager.mutation_epoch += 1
    adapter.invalidate_candidate_readback = invalidate
    adapter.cfg.update(require_solver_convergence_for_apply=False,
                       require_projection_convergence_for_apply=False)
    adapter.generation_reference_hash = 'parent-reference'
    adapter._validate_mobility_plan = lambda context, design: design.setdefault(
        'genfix2_mobility', {'passes': True})
    adapter._final_step_prediction = lambda *args: {'available': True}
    monkeypatch.setattr(mod._V24916ActiveAdapter, 'generation_preview',
                        lambda *a, **k: {'candidate_rows': []})
    monkeypatch.setattr(mod.supply_visum.base, 'generation_candidate',
                        lambda *a, **k: {'candidate_rows': [], 'summary': {}})
    monkeypatch.setattr(mod._V24916ActiveAdapter, 'apply_generation',
                        mod.supply_visum.VisumAdapter.apply_generation)
    context = {'v24917_ls': result, '_long_cache_receipt': {k: observed[k] for k in (
        'status', 'binding', 'cache_parent_hash', 'path_epoch')},
        'projection': core.ProjectionResult([], [], 0.)}
    preview = adapter.generation_preview(context, 1.)
    assert preview['candidate_rows'] and all(r['family'] == 'LONG' for r in preview['candidate_rows'])
    parent = copy.deepcopy(state.coeff)
    written = adapter.apply_generation(context, 1., tmp_path)
    assert written == preview['candidate_rows']
    assert set(state.writes) <= {'ADD_PROD_L', 'ADD_ATT_L'}
    assert state.coeff['ADD_PROD_L'] != parent['ADD_PROD_L']
    # Existing runtime setter restores the same snapshot-owned attributes;
    # native parent recomputation/diagnostic equivalence is still controller-owned.
    from r1_15a2_inplace_transaction_v24915p2 import restore_generation_parameters
    snapshot = {'generation_values': {attr: {str(z+1): v for z, v in enumerate(values)}
                                      for attr, values in parent.items()}}
    restore_generation_parameters(adapter, snapshot, written, tmp_path/'rollback')
    assert state.coeff == parent
    adapter.readback_manager.mutation_epoch += 1
    with pytest.raises(ValueError, match='PROPOSAL_STALE'): adapter.generation_preview(context, 1.)


def test_unapproved_caller_long_rows_stay_filtered():
    from r1_15a2_trial_adapter_v24917 import VisumAdapter
    assert VisumAdapter._without_unverified_long_rows([{'family': 'LONG'}, {'family': 'WORK'}]) == [{'family': 'WORK'}]


@pytest.mark.parametrize('refresh', [False, True])
@pytest.mark.parametrize('ws_empty', [False, True])
def test_automatic_generation_design_uses_shared_cache_and_keeps_live_trial_contract(live, monkeypatch, tmp_path, refresh, ws_empty):
    import contextlib
    import r1_15a2_trial_adapter_v24917 as mod
    fixture, state, profiles = live
    adapter = object.__new__(mod.VisumAdapter)
    adapter.__dict__.update(vars(fixture))
    adapter.v24917_ls = {'active': True}
    adapter.v24917_status = {'fit_fallbacks': 0, 'designs': 0}
    adapter.generation_reference_values = {'ADD_ATT_L': {'1': 1., '2': 1.}}
    adapter.snapshot = adapter.generation_guard_snapshot
    adapter._v24917_overlay = lambda phase: contextlib.nullcontext(adapter.cfg)
    adapter.zone_write_index_by_no = {1: 1, 2: 2}
    state.arrays[9225] = np.zeros((2, 2)); state.arrays[9226] = np.ones((2, 2))
    inc = {'profiles': profiles, 'variables': [], 'incidence': core.SparseOperator(
        np.array([], dtype=int), np.array([], dtype=int), np.array([]), 2, 0)}
    ws = problem(profiles)
    sol = {'predicted_change': np.zeros(2), 'converged': True, 'iterations': 1,
           'objective_initial': 100., 'objective_final': 90., 'x': np.array([])}
    projection = [] if ws_empty else [{'zone_no': 1, 'family': 'WORK', 'role': 'PROD', 'log_step': .001}]
    calls = []
    def parent(*args):
        calls.append('parent')
        return {'incidence': inc, 'projection': core.ProjectionResult(projection, [], 0.)}
    monkeypatch.setattr(mod._V24916ActiveAdapter, 'generation_design', parent)
    monkeypatch.setattr(mod.longguard, 'capture', lambda *args: {
        'long_generation_permitted': True, 'fine_cdf_verified': True, 'fine_100_200_rmse': .1})
    monkeypatch.setattr(mod.longmask, 'capture_current', lambda *args: {'status': 'MASK_READY'})
    monkeypatch.setattr(mod.tg, 'policy_of', lambda cfg: {'fit': {'max_iter': 2000}})
    monkeypatch.setattr(mod.tg, 'phase_for', lambda *args: ('REFINE', 1.))
    monkeypatch.setattr(mod.tg, 'zone_bounds', lambda *args: {})
    monkeypatch.setattr(ls, 'ls_options', lambda: dict(ls.LS_DEFAULTS))
    zone_rows = mobility_rows()
    monkeypatch.setattr(mod.supply_visum.base, 'zone_state_rows', lambda *args, **kwargs: (zone_rows, []))
    monkeypatch.setattr(mod.mguard, 'options', lambda: {'enabled': True, 'lo': .75, 'hi': 2.})
    monkeypatch.setattr(mod.zguard, 'enrich', lambda *args: (zone_rows, list(mz.SPECS), {}))
    monkeypatch.setattr(mod.zguard, 'guard_projection', lambda rows, a: (rows, {'status': 'OK'}))
    monkeypatch.setattr(mod.mguard, 'guard', lambda rows, *args: (rows, {'passes': True}))
    adapter._fit_with_boundary = lambda *args: (projection, {}, ws, sol, None)
    adapter._apply_flowbundle_mask = lambda rows, *args: {'rows': rows, 'audit': {'status': 'OK'}}
    if refresh:
        # Launcher tests reload runtime modules; patch the adapter's actual owner.
        cache_module = mod.long_cache
        capture = cache_module.capture
        count = [0]
        def first_stale(ad):
            count[0] += 1
            if count[0] == 1: raise ValueError('LONG_CACHE_REFRESH_REQUIRED:NEW_POSITIVE_OD')
            return capture(ad)
        monkeypatch.setattr(cache_module, 'capture', first_stale)
        def rebuild(*args, **kwargs):
            assert kwargs['allow_persistent_restore'] is False
            calls.append('refresh'); adapter.path_epoch_index += 1
        adapter._build_cache = rebuild
    context = adapter.generation_design({'d12': {'rows': profiles}}, tmp_path)
    assert context['v24917_ls']['summary']['long_generation_permitted'], context['v24917']
    assert ls.rows_at_scale(context['v24917_ls'], 1.)
    # LONG has source-verified shared-cache evidence, but the 2026-10-30
    # live SCHOOL FP dependency does not: do NOT report LONG+SCHOOL complete.
    assert context['v24917']['long_school_search_incomplete']
    assert not context['v24917']['school_fp_link_deferred']
    assert context['v24917_ls']['summary']['school_generation_search_complete'] is True
    assert context['v24917_step_model']['available']
    assert context['v24917']['tdlong1']['native_filter_status'] == 'NOT_REQUIRED_POST_TD_MASK'
    assert calls == (['parent', 'refresh', 'parent'] if refresh else ['parent'])
    assert state.exports == 0 and state.writes == []


def test_existing_controller_freeze_proof_owns_long_parameters_and_rejects_unrequested_changes(live, monkeypatch):
    import r1_15a2_multiblock as mb
    from r1_15a2_controller_v22 import assert_freeze
    adapter, state, _ = live
    monkeypatch.setattr(mb, 'GENERATION_ATTRS', list(mb.GENERATION_ATTRS))
    monkeypatch.setattr(mb, 'GENERATION_ATTR_MAP', dict(mb.GENERATION_ATTR_MAP))
    assert ls.activate(adapter.visum)['active']
    assert {'ADD_PROD_L', 'ADD_ATT_L'} <= set(mb.GENERATION_ATTRS)
    base = {'fixed_link_hash': 'L', 'dseg_hash': 'D', 'operations_hash': 'O',
            'addval1': {}, 'td_hash': 'TD', 'matrices': [{'matrix_no': 9111, 'sha256_float64_le': 'before'}],
            'generation_values': {'ADD_PROD_L': {'1': .3, '2': .3},
            'ADD_ATT_L': {'1': 1., '2': 1.}, 'ADD_PROD_W': {'1': 1.}}}
    after = copy.deepcopy(base); after['generation_values']['ADD_PROD_L']['1'] = .33
    after['matrices'][0]['sha256_float64_le'] = 'after-native-recompute'
    cfg = {'matrix_scope_by_block': {'GENERATION': {'matrix_nos': [9111]}}}
    rows = [{'attr': 'ADD_PROD_L', 'zone_no': 1, 'current': .3, 'proposed': .33}]
    assert_freeze(base, after, 'GENERATION', rows=rows, cfg=cfg)
    after['generation_values']['ADD_PROD_W']['1'] = 1.1
    with pytest.raises(Exception, match='UNREQUESTED_GENERATION_PARAMETER_CHANGE'):
        assert_freeze(base, after, 'GENERATION', rows=rows, cfg=cfg)


def test_only_owned_retry_with_restored_parameters_can_reuse_frozen_proposal(live):
    adapter, state, _ = live
    def snapshot():
        return dict(state.parent, generation_values=copy.deepcopy(state.coeff), td_values=[],
                    addval1={}, fixed_link_hash='L', dseg_hash='D', operations_hash='O')
    adapter.generation_guard_snapshot = snapshot
    receipt = lc.capture(adapter)
    state.coeff['ADD_ATT_L'][0] = 1.1
    with pytest.raises(ValueError, match='PARENT_PARAMETERS_CHANGED'): lc.begin_apply(adapter, receipt)
    state.coeff['ADD_ATT_L'][0] = 1.
    lc.begin_apply(adapter, receipt)
    adapter.readback_manager.mutation_epoch += 1
    state.coeff['ADD_PROD_L'][0] = .33
    with pytest.raises(ValueError, match='PROPOSAL_STALE'): lc.require_current(adapter, receipt)
    state.coeff['ADD_PROD_L'][0] = .3
    lc.require_current(adapter, receipt)  # parameter-only backtracking restore
    copied = copy.deepcopy(receipt)
    with pytest.raises(ValueError, match='PROPOSAL_STALE'): lc.require_current(adapter, copied)
    adapter.path_epoch_index += 1
    with pytest.raises(ValueError, match='PROPOSAL_STALE'): lc.require_current(adapter, receipt)


def test_long_only_scope_is_explicit_and_foreign_scope_tampering_is_rejected():
    import r1_15a2_fresh0_shortroot_parent_v24916 as parent
    import r1_15a2_runtime_delta_v24917 as delta
    cfg0 = parent.load_config('FULL')
    cfg = delta.apply_active_runtime_delta(cfg0)
    assert delta.validate_active_runtime_delta(cfg, cfg0)['v24917']['passes']
    scope = cfg['matrix_scope_by_block']['GENERATION']
    assert 'NATIVE_CL' in scope['dseg_codes'] and set(range(9111, 9116)) <= set(scope['matrix_nos'])
    assert 9116 not in scope['matrix_nos']
    changed = copy.deepcopy(cfg)
    changed['matrix_scope_by_block']['GENERATION']['matrix_nos'].append(9116)
    with pytest.raises(RuntimeError, match='SCOPE_MISMATCH'): delta.validate_active_runtime_delta(changed, cfg0)


def test_long_fit_is_prebound_before_visum_restores_import_path(live, monkeypatch):
    import builtins
    original = builtins.__import__
    def guarded(name, *args, **kwargs):
        if name == 'r1_15a2_long_zonal_fit_v24917':
            raise AssertionError('LONG_FIT_LATE_IMPORT_DEPENDS_ON_HOST_SYS_PATH')
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', guarded)
    result, *_ = payload(live, monkeypatch)
    assert result['summary']['long_generation_permitted']

"""Real shared LONG coordinates and atomic realization, offline only."""
import copy
import hashlib
import math
from pathlib import Path
from types import SimpleNamespace as NS

import numpy as np
import pytest

import r1_15a2_long_composite_td_v24917 as long_td

ROOT = Path(__file__).resolve().parents[1]
FINE = {'reference_script': 'reference_v19/R1_BC_AUTO_DIST_ONLY_FINECDF_SOFT_v1_9.py',
        'reference_sha256': 'fcdfa535940296e6cc793b6416c7c0a56c18aae8d5d20beddb064a170c673ff5',
        'reference_script_id': 'R1_BC_AUTO_DIST_ONLY_FINECDF_SOFT_V1_9_20261017'}


@pytest.fixture
def reference():
    import r1_15a2_finecdf_bridge_v24916 as bridge
    return bridge.load_reference(ROOT, FINE)[0]


def proposal(ref):
    abc = {n: {'a': 1., 'b': 1. + (n % 5) / 10, 'c': -.1 - (n % 5) / 100}
           for n in ref.BY_NO}
    space = ref.ParameterSpace(abc)
    x = {key: value.copy() for key, value in space.x.items()}
    x['LONG_COMPOSITE'] = np.array([.08, math.log(1.06)])
    after = space.abc(x)
    parent = [dict(component=ref.BY_NO[n]['component'], current_b=v['b'], current_c=v['c'])
              for n, v in abc.items()]
    rows = [dict(component=ref.BY_NO[n]['component'], candidate_b=after[n]['b'], candidate_c=after[n]['c'])
            for n in long_td.MATRIX_NOS]
    registry = {ref.BY_NO[n]['component']: n for n in abc}
    return abc, after, parent, rows, registry


def test_real_sealed_space_moves_five_components_together(reference):
    before, after, parent, rows, registry = proposal(reference)
    for no in before:
        if no in long_td.MATRIX_NOS:
            assert after[no]['b'] - before[no]['b'] == pytest.approx(.08)
            assert after[no]['c'] / before[no]['c'] == pytest.approx(1.06)
            assert after[no]['a'] == before[no]['a']
        else:
            assert after[no] == pytest.approx(before[no], rel=0., abs=1e-14)
    groups = long_td.realization_groups(rows, parent, registry)
    assert len(groups) == 1 and groups[0][0] == 'LONG_COMPOSITE'
    assert len(groups[0][1]) == 5


def test_shared_group_remains_atomic_beside_work(reference):
    _, after, parent, rows, registry = proposal(reference)
    row = dict(component=reference.BY_NO[9101]['component'], candidate_b=1.3, candidate_c=-.12)
    groups = long_td.realization_groups(rows + [row], parent, registry)
    assert [(name, len(members)) for name, members in groups] == [('LONG_COMPOSITE', 5), (row['component'], 1)]


@pytest.mark.parametrize('scale', [1., .5, .25])
def test_native_controller_backtracking_preserves_shared_coordinates(reference, scale):
    import r1_15a2_overnight_controller_coupled_v24915p2_force100 as ctrl
    _, _, parent, rows, registry = proposal(reference)
    scaled = ctrl._td_rows_at_scale({'td_values': parent}, rows, scale)
    groups = long_td.realization_groups(scaled, parent, registry)
    assert len(groups[0][1]) == 5
    for old, row in zip([r for r in parent if r['component'] in {x['component'] for x in rows}], scaled):
        assert row['candidate_b'] - old['current_b'] == pytest.approx(.08 * scale)
        assert row['candidate_c'] / old['current_c'] == pytest.approx(1.06 ** scale)


@pytest.mark.parametrize('fault', ['partial', 'duplicate', 'independent_b', 'independent_c', 'nan', 'positive_c'])
def test_invalid_shared_group_rejected(reference, fault):
    _, _, parent, rows, registry = proposal(reference)
    if fault == 'partial': rows.pop()
    elif fault == 'duplicate': rows.append(dict(rows[0]))
    elif fault == 'independent_b': rows[0]['candidate_b'] += .01
    elif fault == 'independent_c': rows[0]['candidate_c'] *= 1.01
    elif fault == 'nan': rows[0]['candidate_b'] = float('nan')
    else: rows[0]['candidate_c'] = .1
    with pytest.raises(ValueError, match='TDLONG_COMPOSITE'):
        long_td.realization_groups(rows, parent, registry)


def test_target_is_one_existing_512_point_aggregate(reference):
    saved = copy.deepcopy(reference.FINE_AUTHORITY)
    contract = long_td.reference_contract(reference)
    assert contract['aggregate_target_points'] == 512
    assert contract['target_copies'] == 1 and not contract['component_targets_created']
    assert contract['above_200_km_permitted']
    assert reference.FINE_AUTHORITY == saved


@pytest.mark.parametrize('fault', ['matrix_scope', 'grid', 'cdf'])
def test_wrong_target_authority_rejected(reference, fault):
    if fault == 'matrix_scope': reference.TARGETS['LONG_COMPOSITE']['matrix_nos'] = [9111]
    elif fault == 'grid': reference.FINE_AUTHORITY['common_grid_long_km'][0] = 0.
    else: reference.FINE_AUTHORITY['targets']['LONG_COMPOSITE']['cdf'][10] = float('nan')
    with pytest.raises(ValueError, match='TDLONG_COMPOSITE'):
        long_td.reference_contract(reference)


def test_no_caller_verified_flag_can_enable_live_long(reference, monkeypatch, tmp_path):
    import r1_15a2_td_joint_runtime_v24917 as wire
    _, after, parent, rows, _ = proposal(reference)
    monkeypatch.setattr(wire.joint, 'options', lambda: {'enabled': True, 'outer_isolates': True, 'max_isolates': 2})
    import r1_15a2_td_count_blend_v24917 as blend
    monkeypatch.setattr(blend, 'options', lambda: {'w_cnt': .6, 'w_idp': .4})
    adapter = NS(_tdjoint_stage={'w_cnt': .6, 'w_idp': .4,
                                'final_abc': {str(n): v for n, v in after.items()},
                                'native_filter_verified': True})
    calls = []
    run = wire.wrap_realization(lambda *args: calls.append(args), NS())
    with pytest.raises(RuntimeError, match='LONG_COUNT_RESPONSE_UNVERIFIED'):
        run(adapter, {}, tmp_path, None, {'td_values': parent}, {}, rows)
    assert not calls
    assert not long_td.activation_plan()['live_enabled']


def test_reference_source_hash_unchanged(reference):
    data = (ROOT / 'reference_v19/R1_BC_AUTO_DIST_ONLY_FINECDF_SOFT_v1_9.py').read_bytes()
    assert hashlib.sha256(data).hexdigest() == 'fcdfa535940296e6cc793b6416c7c0a56c18aae8d5d20beddb064a170c673ff5'


@pytest.mark.parametrize('groups,x', [(['LONG_COMPOSITE'], {}),
                                    (['WORK_E_C'], {'LONG_COMPOSITE': [.01, 0.]}),
                                    (['WORK_E_C'], {'LONG_COMPOSITE': [0., float('nan')]})])
def test_attempt_to_enable_pending_long_stops_before_native_parameter_write(groups, x):
    import r1_15a2_td_joint_v24917 as joint
    calls = []
    class Parent:
        def evaluate(self, *args, **kwargs):
            calls.append('native parameter write')
    runner = joint.make_runner(Parent, NS(GROUPS=groups))()
    with pytest.raises(RuntimeError, match='LONG_COUNT_RESPONSE_UNVERIFIED'):
        runner.evaluate(x, 'BASELINE')
    assert not calls


def test_installed_loader_keeps_global_fallback_long_frozen(monkeypatch):
    import r1_15a2_td_joint_runtime_v24917 as wire
    import r1_15a2_finecdf_bridge_v24916 as bridge
    import r1_15a2_active_controller_patch_v24916p2c as active
    monkeypatch.setattr(wire.joint, 'options', lambda: {'enabled': True, 'outer_isolates': True})
    for module, name in [(bridge, 'load_reference'), (bridge, 'run_finecdf_inner'),
                         (active, 'targeted_run_finecdf_inner')]:
        monkeypatch.setattr(module, name, getattr(module, name))
    controller = NS(run_finecdf_inner=lambda *args: None, _realize_finecdf_td=lambda *args: None)
    wire.install(controller, print_fn=lambda *args: None)
    ref, _, _ = bridge.load_reference(ROOT, FINE)
    assert 'LONG_COMPOSITE' not in ref.GROUPS
    assert 'LONG_COMPOSITE' in ref.TARGETS  # still evaluated as an aggregate guard
    assert ref.long_composite_td_contract['aggregate_target_verified']
    assert not ref.long_composite_td_contract['live_enabled']

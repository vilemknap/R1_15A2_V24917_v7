"""SCHOOL native counts, fixed zonal P/A and unified-TD LONG support seams."""
import copy
from types import SimpleNamespace as NS

import numpy as np
import pytest

import r1_15a2_demand_policy_v1 as dp
import r1_15a2_td_joint_runtime_v24917 as wire
import r1_15a2_td_joint_v24917 as joint
import r1_15a2_school_td_v24917 as school
import r1_15a2_td_count_blend_v24917 as tb
from test_v24917_tdjoint1 import make_blend, metric


def test_school_frozen_option_is_rejected_before_a_native_write():
    with pytest.raises(RuntimeError, match='SCHOOL_TD_REQUIRES_DYNAMIC'):
        dp.validate(dict(school_td_enabled=True, td_joint_enabled=True,
                         long_composite_td_enabled=False, td_inner_mode='FROZEN_PATHS'))


def test_school_target_scope_cannot_bypass_dynamic_option_guard(monkeypatch):
    monkeypatch.setattr(wire.joint, 'options', lambda: {
        'enabled': True, 'school_enabled': True, 'inner_mode': 'FROZEN_PATHS'})
    with pytest.raises(RuntimeError, match='TDSCHOOL_TARGET_REQUIRES_DYNAMIC'):
        wire._scope_long_target({'coupled_demand': {'finecdf_td': {'active_components': ['SCHOOL']}}})
    assert wire._LONG_TARGET_CONTEXT.get() is None


def test_dynamic_school_scores_fresh_counts_without_work_incidence_or_auxiliary_matrices(tmp_path, monkeypatch):
    blend, mats, _ = make_blend(tmp_path, missing=True, dynamic=True)
    blend.ref.GROUPS = ['SCHOOL']
    blend.ref.TARGETS = {'SCHOOL': {'matrix_nos': [9117]}}
    def forbidden(*args, **kwargs):
        pytest.fail('measured TD attempted unused frozen-path attribution')
    monkeypatch.setattr(blend.bridge, 'read_matrix', forbidden)
    monkeypatch.setattr(blend.model, 'delta_for', forbidden)
    reads = []
    monkeypatch.setattr(blend.model, 'read_live', lambda: reads.append(1) or np.array([100.]))
    # The fixture has one CAL profile; give it a residual so Q_ref is nonzero.
    out = {'SCHOOL': metric()['WORK_E_C']}
    blend.apply(out, {9117: np.array([[0., 20.], [10., 0.]])})
    assert len(reads) == 1
    assert blend.model.linear is None and blend.model.T_ref == {}
    assert blend.last_joint['component_attribution'] == 'MEASURED_NATIVE_ASSIGNMENT'
    assert blend.last_joint['objective'] == pytest.approx(1.)
    monkeypatch.setattr(blend.model, 'read_live', lambda: reads.append(1) or np.array([120.]))
    blend.apply(out, {9117: np.array([[0., 25.], [15., 0.]])})
    expected = blend.opts['w_cnt'] * blend.model.Q([120.]) / blend.model.Q_ref + blend.opts['w_idp']
    assert blend.last_joint['objective'] == pytest.approx(expected)
    assert len(reads) == 2 and blend.last_joint['count_residual_copies'] == 1


@pytest.mark.parametrize('weight', [0., .6, 1.])
def test_measured_score_matches_original_formula_for_ws_and_school(tmp_path, weight):
    blend, mats, _ = make_blend(tmp_path, wc=weight, dynamic=True)
    out = metric()
    # Capture the original scalar formula independently, with explicit live changes.
    live = np.array([150.])
    blend.model.read_live = lambda: live.copy()
    blend.apply(copy.deepcopy(out), mats)
    live[:] = 170.
    changed = metric(.05, .07)
    blend.apply(changed, mats)
    expected = weight * blend.model.Q(live) / max(tb.EPS, blend.model.Q_ref) + (1.-weight) * .12/.1
    assert blend.last_joint['objective'] == pytest.approx(expected)


def test_frozen_school_cannot_borrow_work_count_response(tmp_path):
    blend, mats, _ = make_blend(tmp_path)
    blend.ref.GROUPS = ['SCHOOL']
    with pytest.raises(RuntimeError, match='TDSCHOOL_FROZEN_PATH_COUNT_RESPONSE_FORBIDDEN'):
        blend.apply(metric(), mats)


class Zones:
    def __init__(self):
        # COM indices deliberately differ from NO and each read uses a different order.
        self.indices = {9: 1, 3: 2}
        self.values = {'FP_5_SCHOOL': {1: 10., 2: 0.}, 'FA_5_SCHOOL': {1: 3., 2: 7.}}
    def GetMultiAttValues(self, attr, *args):
        return [(key, no if attr == 'NO' else self.values[attr][no])
                for key, no in reversed(list(self.indices.items()))]


def bridge():
    outer = NS(_long_post_td_mask_enabled=True)
    return NS(outer_adapter=outer, ref=NS(GROUPS=['SCHOOL']),
              v=NS(Net=NS(Zones=Zones())), zone_order=[1, 2],
              dynamic_skim_enabled=True, _v24917_frozen=False)


def test_school_only_native_probe_is_inside_long_mask_scope_and_checks_fixed_pa(monkeypatch):
    import r1_15a2_long_post_td_mask_v24917 as mask
    monkeypatch.setattr(wire.joint, 'options', lambda: {'long_enabled': False})
    host = bridge()
    seen = []
    def native(obj):
        seen.append(mask._SCOPE.get() is host.outer_adapter)
        return 'fresh-native-result'
    assert wire.wrap_dynamic_realization(native)(host) == 'fresh-native-result'
    assert seen == [True] and mask._SCOPE.get() is None
    proof = host._school_generation_freeze_proof
    assert proof['status'] == 'VERIFIED_FIXED_SCHOOL_PA'
    assert proof['source_values_hash'] == proof['readback_values_hash']


@pytest.mark.parametrize('attr', ['FP_5_SCHOOL', 'FA_5_SCHOOL'])
def test_native_school_probe_cannot_change_generation(monkeypatch, attr):
    import r1_15a2_long_post_td_mask_v24917 as mask
    host = bridge()
    def native(obj):
        obj.v.Net.Zones.values[attr][1] += .001
    with pytest.raises(RuntimeError, match='TDSCHOOL_FIXED_GENERATION_CHANGED'):
        wire.wrap_dynamic_realization(native)(host)
    assert mask._SCOPE.get() is None
    assert not hasattr(host, '_school_generation_freeze_proof')


def test_school_pa_reference_is_not_reset_between_native_probes():
    host = bridge()
    run = wire.wrap_dynamic_realization(lambda obj: None)
    run(host)
    host.v.Net.Zones.values['FP_5_SCHOOL'][1] += 1.
    with pytest.raises(RuntimeError, match='FIXED_GENERATION_CHANGED'):
        run(host)


@pytest.mark.parametrize('kind', ['duplicate_index', 'missing_row', 'nan', 'negative'])
def test_invalid_school_generation_cannot_reach_native_execution(kind):
    host = bridge()
    z = host.v.Net.Zones
    if kind == 'nan':
        z.values['FP_5_SCHOOL'][1] = float('nan')
    elif kind == 'negative':
        z.values['FP_5_SCHOOL'][1] = -1.
    else:
        original = z.GetMultiAttValues
        def read(attr, *args):
            rows = original(attr, *args)
            if attr == 'FP_5_SCHOOL':
                return [rows[0], rows[0]] if kind == 'duplicate_index' else rows[:1]
            return rows
        z.GetMultiAttValues = read
    called = []
    with pytest.raises((RuntimeError, ValueError)):
        wire.wrap_dynamic_realization(lambda obj: called.append(1))(host)
    assert called == []


def test_native_probe_error_unwinds_mask_and_is_not_swallowed():
    import r1_15a2_long_post_td_mask_v24917 as mask
    host = bridge()
    def fail(obj):
        raise ValueError('original native failure')
    with pytest.raises(ValueError, match='original native failure'):
        wire.wrap_dynamic_realization(fail)(host)
    assert mask._SCOPE.get() is None


def test_legacy_ws_without_owned_long_mask_retains_existing_native_route():
    host = NS(outer_adapter=NS(), ref=NS(GROUPS=['WORK_E_C']))
    assert wire.wrap_dynamic_realization(lambda obj: 'legacy')(host) == 'legacy'


def test_school_stage_without_fixed_generation_proof_cannot_be_published(tmp_path, monkeypatch):
    monkeypatch.setattr(wire.joint, 'options', lambda: {'enabled': True})
    host = NS()
    def inner(adapter, *args, **kwargs):
        adapter._tdjoint_stage = {'inner_root': str(tmp_path.resolve()), 'component_pool': ['SCHOOL']}
        return {}
    with pytest.raises(RuntimeError, match='TDSCHOOL_FIXED_GENERATION_PROOF_MISSING'):
        wire.wrap_inner(inner)(host, {}, tmp_path, None, tmp_path)

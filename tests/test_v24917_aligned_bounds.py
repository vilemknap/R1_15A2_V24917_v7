"""Approved coefficient bands must agree across proposal and mobility guards."""
import copy
import math

import pytest

import r1_15a2_demand_policy_v1 as dp
import r1_15a2_targeted_generation_v24917 as tg
import r1_15a2_mobility_zone_v24917 as mz
import r1_15a2_mobility_guard_v24917 as mg


@pytest.mark.parametrize('phase', ['CATCH_UP', 'REFINE'])
def test_absolute_and_relative_bands_agree_with_fixed_mobility(phase):
    import r1_15a2_multiblock as mb
    cfg = tg.overlay_cfg({tg.POLICY_KEY: copy.deepcopy(tg.DEFAULT_POLICY),
                          'guidance_mode': 'SIGNED', 'generation_signed_refinement': {'enabled': True}}, phase)
    hard, soft = tg._bounds_patch(mb._multiplicative_coefficient_bounds,
                                  mb._soft_multiplier_bounds, mb)
    opts = dp.load_options(environ={})
    assert opts['ls_school_envelope'] == [.75, 2.]
    assert [opts['mg_min_ratio'], opts['mg_max_ratio']] == [.75, 2.5]
    assert mz.SCHOOL_HARD_MAX == 2.
    assert hard('DOMESTIC', cfg, 1.)[:2] == (.75, 2.)
    assert soft('DOMESTIC', cfg, 1.) == (.75, 2.)
    for role, upper in [('PROD', 2.5), ('ATT', 4.)]:
        assert hard('DOMESTIC', cfg, 1., role=role)[:2] == (.75, upper)
        assert soft('DOMESTIC', cfg, 1., role=role) == (.75, upper)
    # Reference 1 is the normalized starting state; raw ZAHR units may differ.
    for ref in [1., 8.]:
        assert hard('ZAHR', cfg, ref, ref)[:2] == (.5*ref, 10.*ref)
        assert soft('ZAHR', cfg, ref, ref) == (.5*ref, 10.*ref)
    rows = [{'zone_no': 1, 'NOT_ZAHR': 1., 'ADD_PROD_W': 1.,
             **{name: 10. for name in mz.SPECS['WORK'][2]}}]
    authority = mz.capture(rows, {'lo': opts['mg_min_ratio'], 'hi': opts['mg_max_ratio']}, ['WORK'])
    bounded = mz.bounded_step(authority['entries']['WORK|1'], math.log(3), authority)
    assert math.exp(bounded) == pytest.approx(2.5)
    for value, allowed in [(.749, False), (.75, True),
                           (2., True), (2.5, True), (2.501, False)]:
        row = {'zone_no': 1, 'attr': 'ADD_PROD_W', 'family': 'WORK',
               'role': 'PROD', 'current': 1., 'proposed': value}
        assert mz.check_candidate([row], authority)['passes'] is allowed
    # Existing out-of-band parents retain hold/inward-only behavior.
    assert hard('DOMESTIC', cfg, 3.)[:2] == (.75, 3.)


def test_new_ws_mobility_prod_2_5_does_not_widen_school_or_long():
    opts = {'enabled': True, 'lo': 0.75, 'hi': 2.5}
    row = {'zone_no': 1, 'NOT_ZAHR': 1.0,
           'ADD_PROD_W': 1.0, 'ADD_PROD_S': 1.0,
           'ADD_PROD_SCH': 1.0, 'FP_5_SCHOOL': 100.0}
    for fam in ('WORK', 'SERVICE'):
        for attr in mz.SPECS[fam][2]:
            row[attr] = 10.0
    authority = mz.capture([row], opts, families=('WORK', 'SERVICE', 'SCHOOL'))
    assert authority['band'] == [0.75, 2.5]
    assert authority['school_band'] == [0.75, 2.0]
    assert authority['long_band'] == [0.5, 1.5]
    assert mz.check_candidate([
        {'zone_no': 1, 'attr': 'ADD_PROD_W', 'current': 1., 'proposed': 2.5},
        {'zone_no': 1, 'attr': 'ADD_PROD_S', 'current': 1., 'proposed': 2.5},
    ], authority)['passes']
    assert not mz.check_candidate([
        {'zone_no': 1, 'attr': 'ADD_PROD_SCH', 'current': 1., 'proposed': 2.5}
    ], authority)['passes']
    assert mz.check_candidate([
        {'zone_no': 1, 'attr': 'ADD_PROD_SCH', 'current': 1., 'proposed': 2.0}
    ], authority)['passes']
    candidate = [{'zone_no': 1, 'attr': 'ADD_PROD_W',
                  'current': 1., 'proposed': 2.5},
                 {'zone_no': 1, 'attr': 'ADD_PROD_S',
                  'current': 1., 'proposed': 2.5}]
    assert mg.check_candidate(candidate, [row], opts)['passes']
    candidate[0]['proposed'] = 2.501
    assert not mg.check_candidate(candidate, [row], opts)['passes']


def test_defaults_without_options_file_match_installed_policy(tmp_path):
    opts = dp.load_options(root=tmp_path, environ={})
    assert opts['mg_max_ratio'] == 2.
    assert opts['ls_school_envelope'] == [.75, 2.]
    assert opts['td_count_weight'] == .60
    assert mz.SPECS['LONG'][1] == .3
    assert mz.LONG_BAND == (.5, 1.5)


def test_td_default_blend_and_acceptance_margin(monkeypatch):
    import r1_15a2_td_count_blend_v24917 as td
    import r1_15a2_core as core
    import r1_15a2_multiblock as mb
    monkeypatch.setattr(core, 'csd_metrics', lambda rows, *a: {'objective_geh_mean_weighted': rows})
    monkeypatch.setattr(mb, 'td_component_metrics', lambda signals, *a: {'weighted_objective': signals['X']})
    before = {'d12': {'rows': 10.}, 'signals': {'X': 1.}}
    def decide(count, idp):
        return td.outer_decision({'accepted': True, 'reasons': []}, before,
                                 {'d12': {'rows': count}, 'signals': {'X': idp}}, {})
    unchanged = decide(10., 1.)
    assert not unchanged['accepted']
    assert unchanged['v24917_td_blend']['F'] == pytest.approx(1.)
    assert decide(9.9, 1.)['accepted']  # F = .994
    assert not decide(9.99, 1.)['accepted']  # F = .9994, insufficient gain
    assert not decide(1., 1.251)['accepted']  # survey cap survives strong count gain

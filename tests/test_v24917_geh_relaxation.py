"""Approved GEH relaxation must reach real guards in every active block/cycle."""
import copy
import json
import math
from pathlib import Path
from types import SimpleNamespace

import pytest

import r1_15a2_core as core
import r1_15a2_demand_policy_v1 as dp
import r1_15a2_severity_relax_v24917 as sr
import r1_15a2_step_search_v24917 as step

ROOT = Path(__file__).resolve().parents[1]
CFG = json.loads((ROOT/'tests/data/EFFECTIVE_CONFIG_RUN_20261025_175302.json').read_text())
EXPECTED = {'generation': (.20, .25, 10), 'td': (.40, .50, 25), 'supply': (.35, .45, 30)}


def approved():
    return sr.options()


def config(scope='GENERATION', cycle=2):
    cfg = copy.deepcopy(CFG)
    cfg['runtime_acceptance_outer_cycle'] = cycle
    cfg['runtime_acceptance_supply_cycle'] = cycle
    sr.relax(cfg, approved())
    return cfg


def row(key, g):
    # Positive root of the definition of GEH, preserving the target GEH exactly.
    obs = 1000.
    d = (g*g + math.sqrt(g**4 + 16*g*g*obs))/4
    return {'countlocation_no': key, 'role': 'CALIBRATION', 'observed': obs,
            'model': obs+d, 'profile_weight': 1.}


def background(n=200, g=59.):
    return [row('B%d'%i, g) for i in range(n)]


def test_defaults_file_and_validated_options_agree():
    actual = dp.load_options(root=ROOT, environ={})
    assert actual['sev_max_single_profile_geh_increase'] == dp.DEFAULTS['sev_max_single_profile_geh_increase'] == 50.
    assert actual['sev_max_high_geh_increase'] == dp.DEFAULTS['sev_max_high_geh_increase'] == 30.
    assert actual['sev_protected_after_hard_geh'] == dp.DEFAULTS['sev_protected_after_hard_geh'] == 40.
    assert actual['sev_scope_budgets'] == dp.DEFAULTS['sev_scope_budgets']


@pytest.mark.parametrize('scope', ['GENERATION', 'TD', 'SUPPLY_ADDVAL1'])
@pytest.mark.parametrize('cycle', [1, 13, 100])
def test_real_builders_apply_all_budgets_without_mutating_parent(monkeypatch, scope, cycle):
    import r1_15a2_overnight_controller_coupled_v24915p2_force100 as ctrl
    original = copy.deepcopy(CFG)
    builder = ctrl._td_acceptance_cfg_for_cycle if scope == 'TD' else ctrl._generation_counts_cfg
    cfg = sr._wrap(builder)(CFG, outer_cycle=cycle)
    cfg['runtime_acceptance_supply_cycle'] = cycle
    policy = core.early_exploration_policy(cfg, scope)
    assert policy is not None
    key = 'supply' if scope.startswith('SUPPLY') else scope.lower()
    expected = EXPECTED[key]
    assert tuple(policy['scoped'][k] for k in ('max_severity20_relative_degradation',
        'max_severity30_relative_degradation','max_geh40_net_count_increase')) == expected
    assert policy['severity']['max_single_profile_geh_increase'] == 50.
    assert policy['severity']['max_high_geh_increase'] == 30.
    assert policy['severity']['protected_after_hard_geh'] == 40.
    assert CFG == original


@pytest.mark.parametrize('scope', ['GENERATION', 'TD', 'SUPPLY_ADDVAL1'])
def test_old_protected_failure_37_39_is_allowed_but_40_remains_hard(scope):
    before = background(g=50.) + [row('920023', 1.522286391501216)]
    after = background(g=48.) + [row('920023', 37.393888093353084)]
    cfg = config(scope)
    historical = copy.deepcopy(CFG)
    historical['runtime_acceptance_outer_cycle'] = historical['runtime_acceptance_supply_cycle'] = 2
    assert not core.protected_profile_guard(before, after, historical, scope)['passes']
    assert core.protected_profile_guard(before, after, cfg, scope)['passes']
    assert core.severity_transition_guard(before, after, cfg, scope)['passes']
    after[-1] = row('920023', 40.000001)
    assert not core.protected_profile_guard(before, after, cfg, scope)['passes']


@pytest.mark.parametrize('scope', ['GENERATION', 'TD', 'SUPPLY_ADDVAL1'])
def test_individual_increase_50_has_a_real_upper_boundary(scope):
    before = background() + [row('X', 5.1)]
    cfg = config(scope)
    accepted = core.severity_transition_guard(before, background()+[row('X', 55.1)], cfg, scope)
    rejected = core.severity_transition_guard(before, background()+[row('X', 55.10001)], cfg, scope)
    assert accepted['passes']
    assert 'SINGLE_PROFILE_GEH_INCREASE_EXCEEDED' in rejected['violation_codes']


@pytest.mark.parametrize('scope', ['GENERATION', 'TD', 'SUPPLY_ADDVAL1'])
def test_already_high_profiles_keep_the_separate_30_limit(scope):
    cfg = config(scope)
    before = background(g=120.) + [row('X', 70.)]
    accepted = core.severity_transition_guard(before, background(g=120.)+[row('X', 100.)], cfg, scope)
    rejected = core.severity_transition_guard(before, background(g=120.)+[row('X', 100.00001)], cfg, scope)
    assert accepted['passes']  # GEH60 is diagnostic, not a new absolute cap.
    assert 'V24912_HIGH_GEH_DELTA_BUDGET_EXCEEDED' in rejected['violation_codes']


@pytest.mark.parametrize('scope,limit', [('GENERATION', 10), ('TD', 25), ('SUPPLY_ADDVAL1', 30)])
def test_net_geh40_budget_is_scoped_and_finite(scope, limit):
    cfg = config(scope)
    for n in (limit, limit+1):
        before = background(g=50.) + [row('N%d'%i,39.9) for i in range(n)]
        after = background(g=50.) + [row('N%d'%i,40.1) for i in range(n)]
        actual = core.severity_transition_guard(before, after, cfg, scope)
        assert actual['geh40_net_count_increase'] == n
        assert actual['passes'] is (n == limit)
        assert actual['v24912_policy']['geh40_net_count_budget'] == limit


@pytest.mark.parametrize('scope', ['GENERATION', 'TD', 'SUPPLY_ADDVAL1'])
@pytest.mark.parametrize('metric', ['severity20', 'severity30'])
def test_each_relative_severity_budget_has_a_real_boundary(scope, metric):
    cfg = config(scope)
    policy = core.early_exploration_policy(cfg, scope)
    limit = policy['scoped']['max_'+metric+'_relative_degradation']
    # Feed the production rebasing function its raw pre-rebase metrics. This
    # isolates each budget from the other severity metric's separate limit.
    for extra in (0., 1e-6):
        raw = {'before_severity': {'severity20':100.,'severity30':100.,'geh_ge40':10},
               'after_severity': {'severity20':100.,'severity30':100.,'geh_ge40':10},
               'violation_codes': [], 'single_profile_geh_increase_violations': [],
               'absolute_geh_ceiling_violations': []}
        raw['after_severity'][metric] = 100.*(1.+limit+extra)
        result = core.rebase_severity_guard_v24912(raw, policy['severity'], policy['scoped'])
        assert result['passes'] is (extra == 0.)


def test_step_planning_and_final_core_gate_use_the_same_relaxed_profile_policy():
    from r1_15a2_safety_v245 import adapter_config_scope
    before = background(g=50.) + [row('920023', 1.522286391501216)]
    after = background(g=48.) + [row('920023', 37.393888093353084)]
    adapter = SimpleNamespace(cfg=copy.deepcopy(CFG))
    old = adapter.cfg
    with adapter_config_scope(adapter, config()):
        gate, holder = step._gate_fn(adapter)
        holder['before'] = {}
        planned = gate(before, after)
        final = core.acceptance_decision(before, after, {}, {}, adapter.cfg, 'GENERATION')
        assert planned == final
        assert final['accepted']
    assert adapter.cfg is old


def test_global_objective_and_observation_authority_remain_required():
    cfg = config('SUPPLY_ADDVAL1')
    before = background(40,g=50.)
    worse = background(40,g=51.)
    decision = core.acceptance_decision(before,worse,{},{},cfg,'SUPPLY_ADDVAL1')
    assert not decision['accepted']
    assert 'CAL_GEH_OBJECTIVE_NOT_IMPROVED' in decision['reasons']
    improved = background(40,g=48.)
    improved[0]['observed'] += 1
    decision = core.acceptance_decision(before,improved,{},{},cfg,'SUPPLY_ADDVAL1')
    assert 'OBSERVATION_AUTHORITY_CHANGED' in decision['reasons']


def test_relaxation_never_tightens_explicitly_more_permissive_parent():
    cfg = config()
    cfg['early_exploration_acceptance']['severity']['max_single_profile_geh_increase'] = 80.
    cfg['early_exploration_acceptance']['generation']['max_severity20_relative_degradation'] = .70
    sr.relax(cfg, approved())
    assert cfg['early_exploration_acceptance']['severity']['max_single_profile_geh_increase'] == 80.
    assert cfg['early_exploration_acceptance']['generation']['max_severity20_relative_degradation'] == .70


def test_partial_scope_override_and_environment_do_not_mutate_defaults(tmp_path):
    original = copy.deepcopy(dp.DEFAULTS)
    override = {'generation': {'max_severity20_relative_degradation':.3}}
    o = dp.load_options(root=tmp_path,environ={'R1_SEV_SCOPE_BUDGETS':json.dumps(override)})
    assert o['sev_scope_budgets']['generation']['max_severity20_relative_degradation'] == .3
    assert o['sev_scope_budgets']['td'] == dp.DEFAULTS['sev_scope_budgets']['td']
    o['sev_scope_budgets']['td']['max_geh40_net_count_increase'] = 999
    assert dp.DEFAULTS == original
    assert override == {'generation': {'max_severity20_relative_degradation':.3}}


@pytest.mark.parametrize('raw', [None, [], {'invalid':{}}, {'td':[]}, {'td':{'wrong':1}},
    {'td':{'max_severity20_relative_degradation':float('nan')}},
    {'td':{'max_severity30_relative_degradation':float('inf')}},
    {'td':{'max_severity20_relative_degradation':-.1}},
    {'td':{'max_severity30_relative_degradation':3.1}},
    {'td':{'max_geh40_net_count_increase':-1}},
    {'td':{'max_geh40_net_count_increase':2.5}},
    {'td':{'max_geh40_net_count_increase':True}}, '{broken'])
def test_invalid_scope_budgets_fail_closed(raw):
    with pytest.raises(RuntimeError,match='R1_RUN_OPTION_INVALID:sev_scope_budgets'):
        dp.validate({'sev_scope_budgets':raw})

"""Runtime policy errors must reach callers without installing a default policy."""
import copy
import importlib
import json

import pytest

MODULES = ('boundary_generation', 'combusy2', 'fast_trial_assignment',
           'rollback_consistency', 'severity_relax', 'step_search')


def module(name):
    return importlib.import_module('r1_15a2_' + name + '_v24917')


@pytest.mark.parametrize('name', MODULES)
@pytest.mark.parametrize('failure', [OSError('CONFIG_IO'),
    json.JSONDecodeError('CONFIG_JSON', '{', 1), RuntimeError('CONFIG_INVALID_POLICY')])
def test_runtime_options_propagate_original_configuration_failure(monkeypatch, name, failure):
    import r1_15a2_demand_policy_v1 as dp
    def fail(): raise failure
    monkeypatch.setattr(dp, 'load_options', fail)
    with pytest.raises(type(failure)) as error:
        module(name).options()
    assert error.value is failure


@pytest.mark.parametrize('name', MODULES)
def test_real_invalid_run_options_file_is_not_replaced(tmp_path, monkeypatch, name):
    import r1_15a2_demand_policy_v1 as dp
    (tmp_path/'R1_RUN_OPTIONS.json').write_text('{"ts_grid_points":0}')
    original = dp.load_options
    monkeypatch.setattr(dp, 'load_options', lambda: original(root=tmp_path, environ={}))
    with pytest.raises(RuntimeError, match='ts_grid_points'):
        module(name).options()


def test_boundary_configuration_failure_propagates_before_state_or_com(monkeypatch):
    import r1_15a2_demand_policy_v1 as dp
    boundary = module('boundary_generation')
    before = copy.deepcopy(boundary.STATE)
    failure = RuntimeError('BOUNDARY_OPTIONS_INVALID')
    def fail(): raise failure
    monkeypatch.setattr(dp, 'load_options', fail)
    monkeypatch.setattr(boundary, '_zone_values', lambda *args: pytest.fail('No COM before policy validation'))
    with pytest.raises(RuntimeError, match='BOUNDARY_OPTIONS_INVALID'):
        boundary.activate(object())
    assert boundary.STATE == before


@pytest.mark.parametrize('name', MODULES[1:])
def test_failed_install_validation_does_not_patch_functions_or_state(monkeypatch, name):
    import r1_15a2_demand_policy_v1 as dp
    import r1_15a2_acceleration_v24915p1 as perf
    import r1_15a2_overnight_controller_v24915p2 as base
    import r1_15a2_overnight_controller_coupled_v24915p2_force100 as ctrl
    target = module(name)
    state = copy.deepcopy(target._STATE)
    state['installed'] = False
    monkeypatch.setattr(target, '_STATE', state)
    before = copy.deepcopy(state)
    functions = [(perf,'phase_recompute_plan'), (perf,'count_profile_signature'),
                 (base,'rollback_and_verify'), (base,'_rollback_candidate'),
                 (base,'_assign_candidate'), (ctrl,'_generation_update_once_impl'),
                 (ctrl,'_finecdf_td_once'), (ctrl,'_generation_counts_cfg'),
                 (ctrl,'_td_acceptance_cfg_for_cycle'), (ctrl,'_evaluate_candidate'),
                 (ctrl,'_adopt_candidate')]
    originals = [(obj, attr, getattr(obj, attr)) for obj, attr in functions]
    for obj, attr, value in originals:
        monkeypatch.setattr(obj, attr, value)  # restore even if a broken install overwrites it
    failure = RuntimeError('CONFIGURATION_BLOCKS_INSTALL')
    def fail(): raise failure
    monkeypatch.setattr(dp, 'load_options', fail)
    with pytest.raises(RuntimeError, match='CONFIGURATION_BLOCKS_INSTALL'):
        target.install(print_fn=lambda *a: None)
    assert target._STATE == before
    assert all(getattr(obj, attr) is value for obj, attr, value in originals)


def test_valid_nondefault_runtime_options_are_preserved(monkeypatch):
    import r1_15a2_demand_policy_v1 as dp
    raw = {'bd_enabled':False, 'bd_zones':[2,3], 'ts_enabled':False,
           'fa_enabled':False, 'rb_tolerant_diagnostics':False,
           'rb_roster_reuse_proof':False, 'cb_block_retries':1}
    values = dp.validate(raw)
    monkeypatch.setattr(dp, 'load_options', lambda: values)
    assert module('boundary_generation').options() == {'bd_enabled':False, 'bd_zones':[2,3]}
    assert module('step_search').options()['enabled'] is False
    assert module('fast_trial_assignment').options()['enabled'] is False
    assert module('rollback_consistency').options() == {'tolerant':False, 'roster_proof':False}
    assert module('combusy2').options()['block_retries'] == 1
    assert module('severity_relax').options()['single'] == values['sev_max_single_profile_geh_increase']

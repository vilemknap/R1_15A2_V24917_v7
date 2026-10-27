import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _phase_cfg(base):
    base = dict(base)
    base['apply'] = False
    base['production_apply'] = False
    base['block_schedule'] = [
        'GENERATION',
        'TD_COMPONENT_WORK', 'TD_COMPONENT_SERVICE', 'TD_COMPONENT_SCHOOL', 'TD_COMPONENT_LONG',
        'SUPPLY_ADDVAL1',
    ]
    base['calibration_phases'] = [
        {'name': 'TRIP_GENERATION', 'blocks': ['GENERATION'], 'max_cycles': 1,
         'must_converge_before_next_phase': True,
         'convergence_rule': 'FULL_PHASE_CYCLE_WITH_ZERO_ACCEPTED_AND_NO_BLOCKING_ERRORS'},
        {'name': 'TRIP_DISTRIBUTION',
         'blocks': ['TD_COMPONENT_WORK', 'TD_COMPONENT_SERVICE', 'TD_COMPONENT_SCHOOL', 'TD_COMPONENT_LONG'],
         'max_cycles': 1, 'must_converge_before_next_phase': True,
         'convergence_rule': 'FULL_PHASE_CYCLE_WITH_ZERO_ACCEPTED_AND_NO_BLOCKING_ERRORS'},
        {'name': 'SUPPLY_ROUTE_CHOICE', 'blocks': ['SUPPLY_ADDVAL1'], 'max_cycles': 1,
         'must_converge_before_next_phase': True,
         'convergence_rule': 'FULL_PHASE_CYCLE_WITH_ZERO_ACCEPTED_AND_NO_BLOCKING_ERRORS'},
    ]
    base['trial_calibration'] = {
        'enabled': True,
        'max_runtime_seconds': 1000.0,
        'progress_interval_seconds': 0.0,
        'max_accepted_states': 20,
        'max_trials_per_block': {
            'GENERATION': 3,
            'TD_COMPONENT_WORK': 3,
            'TD_COMPONENT_SERVICE': 3,
            'TD_COMPONENT_SCHOOL': 3,
            'TD_COMPONENT_LONG': 3,
            'SUPPLY_ADDVAL1': 2,
        },
        'require_reproducible_reapply': True,
        'supply_start_requires_converged_phases': ['TRIP_GENERATION', 'TRIP_DISTRIBUTION'],
    }
    return base


def test_v241_config_hard_orders_generation_then_distribution_then_supply():
    cfg = json.loads((ROOT / 'R1_15A2_CONFIG_V2_4_1.json').read_text(encoding='utf-8'))
    assert cfg['block_schedule'] == [
        'GENERATION',
        'TD_COMPONENT_WORK', 'TD_COMPONENT_SERVICE', 'TD_COMPONENT_SCHOOL', 'TD_COMPONENT_LONG',
        'SUPPLY_ADDVAL1',
    ]
    phases = cfg['calibration_phases']
    assert [p['name'] for p in phases] == ['TRIP_GENERATION', 'TRIP_DISTRIBUTION', 'SUPPLY_ROUTE_CHOICE']
    assert phases[0]['blocks'] == ['GENERATION']
    assert phases[1]['blocks'] == ['TD_COMPONENT_WORK', 'TD_COMPONENT_SERVICE', 'TD_COMPONENT_SCHOOL', 'TD_COMPONENT_LONG']
    assert phases[2]['blocks'] == ['SUPPLY_ADDVAL1']
    assert cfg['trial_calibration']['supply_start_requires_converged_phases'] == ['TRIP_GENERATION', 'TRIP_DISTRIBUTION']
    assert cfg['trial_calibration']['demand_parameters_frozen_during_supply'] is True


def test_v241_phase_validator_rejects_supply_before_demand():
    from r1_15a2_overnight_controller_v241 import _validated_phase_plan
    cfg = json.loads((ROOT / 'R1_15A2_CONFIG_V2_4_1.json').read_text(encoding='utf-8'))
    cfg['calibration_phases'][0]['blocks'] = ['SUPPLY_ADDVAL1']
    with pytest.raises(Exception):
        _validated_phase_plan(cfg)


def test_v241_no_candidate_flow_reaches_supply_only_after_both_demand_phases(tmp_path):
    from tests.synthetic_v22_adapter import SyntheticAdapter, synthetic_config
    import r1_15a2_overnight_controller_v241 as ctl

    class NoCandidateAdapter(SyntheticAdapter):
        def __init__(self, cfg):
            super().__init__(cfg)
            self.phase_calls = []
        def generation_design(self, diag, folder):
            self.phase_calls.append('GENERATION')
            return {}
        def generation_preview(self, context, scale):
            return {'candidate_rows': []}
        def td_design(self, diag, block, scale, folder):
            self.phase_calls.append(block)
            return {'candidate_rows': []}
        def supply_design(self, diag, folder, snapshot):
            self.phase_calls.append('SUPPLY_ADDVAL1')
            return {'candidates': []}

    cfg = _phase_cfg(synthetic_config())
    adapter = NoCandidateAdapter(cfg)
    control = ctl.OvernightControl(tmp_path / 'run', cfg)
    result = ctl.run_overnight_calibration_hierarchical(adapter, cfg, tmp_path / 'cal', control)
    assert result['status'] == 'CONVERGED_TG_THEN_TD_THEN_SUPPLY'
    assert result['completed_phases'] == ['TRIP_GENERATION', 'TRIP_DISTRIBUTION', 'SUPPLY_ROUTE_CHOICE']
    assert result['supply_started'] is True
    assert adapter.phase_calls.index('GENERATION') < adapter.phase_calls.index('TD_COMPONENT_WORK')
    assert adapter.phase_calls.index('TD_COMPONENT_LONG') < adapter.phase_calls.index('SUPPLY_ADDVAL1')


def test_v241_supply_does_not_start_if_generation_has_not_converged(tmp_path, monkeypatch):
    from tests.synthetic_v22_adapter import SyntheticAdapter, synthetic_config
    import r1_15a2_overnight_controller_v241 as ctl

    class LoggedAdapter(SyntheticAdapter):
        def __init__(self, cfg):
            super().__init__(cfg)
            self.supply_called = False
        def supply_design(self, diag, folder, snapshot):
            self.supply_called = True
            return super().supply_design(diag, folder, snapshot)
        def invalidate_cache(self, *args, **kwargs):
            pass

    cfg = _phase_cfg(synthetic_config())
    cfg['calibration_phases'][0]['max_cycles'] = 1

    def rb(adapter, block, before, baseline_diag_hash, diagnostic_hash_fn, folder, candidate_rows=None, candidate=None):
        adapter.state['a'] = dict(before['addval1'])
        adapter.state['generation'] = before['generation_values']['ADD_PROD_W']['1']
        adapter.state['q'] = 1000.0 * adapter.state['generation']
        adapter.state['b'] = before['td_values'][0]['current_b']
        adapter.assign(folder, supply_only=(block == 'SUPPLY_ADDVAL1'))
        assert adapter.snapshot() == before
        diag = adapter.diagnostics(folder, 'ROLLBACK')
        assert diagnostic_hash_fn(diag) == baseline_diag_hash
        return {'passes': True, 'snapshot_equal': True, 'diagnostic_equal': True}, diag

    import r1_15a2_overnight_controller_v240 as ctl240
    monkeypatch.setattr(ctl240, 'rollback_and_verify', rb)
    # _evaluate_candidate imported from v240 closes over v240.rollback_and_verify.
    adapter = LoggedAdapter(cfg)
    control = ctl.OvernightControl(tmp_path / 'run2', cfg)
    result = ctl.run_overnight_calibration_hierarchical(adapter, cfg, tmp_path / 'cal2', control)
    assert result['status'].startswith('TRIP_GENERATION_MAX_CYCLES_REACHED')
    assert result['completed_phases'] == []
    assert result['supply_started'] is False
    assert adapter.supply_called is False


def test_v241_entrypoint_uses_hierarchical_controller_and_new_config():
    src = (ROOT / 'R1_15A2_FULL_OVERNIGHT_HIERARCHICAL_V2_4_1.py').read_text(encoding='utf-8')
    assert 'R1_15A2_CONFIG_V2_4_1.json' in src
    assert 'run_overnight_calibration_hierarchical' in src
    assert 'TRIP_GENERATION' in src and 'TRIP_DISTRIBUTION' in src and 'SUPPLY_ROUTE_CHOICE' in src


def test_v241_controller_never_loads_version_and_supply_stays_final():
    src = (ROOT / 'r1_15a2_overnight_controller_v241.py').read_text(encoding='utf-8')
    assert '.LoadVersion(' not in src
    assert 'load_version(' not in src
    assert 'SUPPLY_ROUTE_CHOICE' in src
    assert 'V241_SUPPLY_STARTED_BEFORE_DEMAND_PHASES_CONVERGED' in src
    assert 'SUPPLY_ADDVAL1' in src


def test_v241_compile_sources():
    for name in ('R1_15A2_FULL_OVERNIGHT_HIERARCHICAL_V2_4_1.py',
                 'r1_15a2_overnight_controller_v241.py'):
        compile((ROOT / name).read_text(encoding='utf-8'), name, 'exec')

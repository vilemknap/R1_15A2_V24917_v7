import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_v240_config_is_trial_working_copy_not_production_apply():
    cfg = json.loads((ROOT / 'R1_15A2_CONFIG_V2_4_0.json').read_text(encoding='utf-8'))
    assert cfg['apply'] is False
    assert cfg['production_apply'] is False
    assert cfg['trial_calibration']['enabled'] is True
    assert cfg['trial_calibration']['max_runtime_seconds'] == 36000.0
    assert cfg['trial_calibration']['global_link_count_cap'] is None
    assert cfg['trial_calibration']['full_network_link_eligibility'] is True


def test_v240_supply_scope_is_op20_only_and_local_edge_limit_not_global():
    cfg = json.loads((ROOT / 'R1_15A2_CONFIG_V2_4_0.json').read_text(encoding='utf-8'))
    ops = cfg['supply']['assignment_operations']
    assert [x['no'] for x in ops] == [20]
    assert ops[0]['operation_type'] == 101
    assert cfg['supply']['max_edges'] == 12
    assert cfg['supply']['max_bundle_equivalent_seconds'] == 120.0
    assert cfg['supply']['editable_link_types'] is None
    assert cfg['supply']['excluded_link_keys'] == []


def test_v240_controller_never_calls_loadversion_or_adapter_restore():
    src = (ROOT / 'r1_15a2_overnight_controller_v240.py').read_text(encoding='utf-8')
    assert '.LoadVersion(' not in src
    assert 'load_version(' not in src
    assert 'adapter.restore(' not in src
    assert 'rollback_and_verify(' in src
    assert 'adapter.assign(' in src


def test_v240_entrypoint_creates_isolated_working_and_final_versions():
    src = (ROOT / 'R1_15A2_FULL_OVERNIGHT_CALIBRATION_V2_4_0.py').read_text(encoding='utf-8')
    assert 'WORKING_START.ver' in src
    assert 'FINAL_CALIBRATED_WORKING_COPY.ver' in src
    assert 'source_file_unchanged' in src
    assert 'load_version_called=False' in src


def test_v240_adapter_prohibits_loadversion_restore_boundary():
    src = (ROOT / 'r1_15a2_trial_adapter_v240.py').read_text(encoding='utf-8')
    assert 'V240_LOADVERSION_ROLLBACK_FORBIDDEN' in src
    assert 'geometry_used_for="CANDIDATE_PROPOSAL_ONLY"' in src
    assert 'acceptance_authority="FRESH_VISUM_ASSIGNMENT_PLUS_LIVE_12D_11D"' in src


def test_v240_control_time_and_stop_are_cooperative(tmp_path):
    from r1_15a2_overnight_controller_v240 import OvernightControl, UserStopRequested, TimeBudgetReached
    class Clock:
        def __init__(self): self.v = 0.0
        def __call__(self): return self.v
    c = Clock()
    cfg = {'trial_calibration': {'max_runtime_seconds': 10.0, 'progress_interval_seconds': 0.0}}
    ctl = OvernightControl(tmp_path, cfg, clock=c)
    c.v = 5.0
    ctl.checkpoint('MID')
    (tmp_path / 'STOP_REQUESTED').write_text('')
    with pytest.raises(UserStopRequested):
        ctl.checkpoint('STOP')
    (tmp_path / 'STOP_REQUESTED').unlink()
    c.v = 11.0
    with pytest.raises(TimeBudgetReached):
        ctl.checkpoint('TIME')


def test_v240_compile_sources():
    for name in ('R1_15A2_FULL_OVERNIGHT_CALIBRATION_V2_4_0.py',
                 'r1_15a2_trial_adapter_v240.py',
                 'r1_15a2_overnight_controller_v240.py'):
        compile((ROOT / name).read_text(encoding='utf-8'), name, 'exec')


def test_v240_controller_real_trial_accepts_and_reapplies_without_loadversion(tmp_path, monkeypatch):
    import copy
    import r1_15a2_overnight_controller_v240 as ctlmod
    from tests.synthetic_v22_adapter import SyntheticAdapter, synthetic_config

    cfg = synthetic_config()
    cfg['apply'] = False
    cfg['production_apply'] = False
    cfg['block_schedule'] = ['SUPPLY_ADDVAL1']
    cfg['trial_calibration'] = {
        'enabled': True, 'max_runtime_seconds': 1000.0, 'progress_interval_seconds': 0.0,
        'max_cycles': 1, 'max_accepted_states': 5,
        'max_trials_per_block': {'SUPPLY_ADDVAL1': 2},
        'require_reproducible_reapply': True,
    }
    # exact rollback stub for the deterministic synthetic state machine
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
    monkeypatch.setattr(ctlmod, 'rollback_and_verify', rb)
    adapter = SyntheticAdapter(cfg)
    control = ctlmod.OvernightControl(tmp_path / 'run', cfg)
    result = ctlmod.run_overnight_calibration(adapter, cfg, tmp_path / 'cal', control)
    assert result['accepted_count'] == 1
    assert result['status'] == 'MAX_CYCLES_REACHED'
    # candidate evaluation is rolled back, then the selected candidate is really reapplied
    assert adapter.state['a']['1|1|2'] == -1.0 or adapter.state['a']['2|2|3'] == -1.0
    assert adapter.restores == 0

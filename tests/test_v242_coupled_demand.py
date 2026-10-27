import copy
import json
from pathlib import Path

import r1_15a2_overnight_controller_v242 as v242
from r1_15a2_supply import canonical_hash

ROOT = Path(__file__).resolve().parents[1]


def test_v242_config_is_one_coupled_demand_phase_then_supply():
    cfg = json.loads((ROOT / 'R1_15A2_CONFIG_V2_4_2.json').read_text(encoding='utf-8'))
    assert cfg['block_schedule'] == ['GENERATION', 'TD_FINECDF_V17', 'SUPPLY_ADDVAL1']
    assert [p['name'] for p in cfg['calibration_phases']] == ['COUPLED_DEMAND', 'SUPPLY_ROUTE_CHOICE']
    assert cfg['calibration_phases'][0]['blocks'] == ['GENERATION', 'TD_FINECDF_V17']
    assert cfg['trial_calibration']['supply_start_requires_converged_phases'] == ['COUPLED_DEMAND']
    assert cfg['coupled_demand']['convergence_rule'] == 'NO_ACCEPTED_GENERATION_AND_NO_ACCEPTED_FINECDF_TD_IN_SAME_OUTER_CYCLE'


def test_generation_substep_uses_counts_objective_and_defers_idp_to_td():
    cfg = {'shared_objective': {'cal_weight': 1.0, 'idp_weight': 1.0},
           'idp_max_mean_degradation': 0.005, 'idp_max_component_degradation': 0.02}
    got = v242._generation_counts_cfg(cfg)
    assert got['shared_objective']['idp_weight'] == 0.0
    assert got['idp_max_mean_degradation'] > 1e20
    assert got['idp_max_component_degradation'] > 1e20
    assert cfg['shared_objective']['idp_weight'] == 1.0  # no mutation of authority config


def _snapshot():
    td = [
        {'component': 'WORK_E_C', 'current_b': 1.0, 'current_c': -0.1},
        {'component': 'SCHOOL', 'current_b': 2.0, 'current_c': -0.2},
    ]
    return {
        'fixed_link_hash': 'F', 'dseg_hash': 'D', 'operations_hash': 'O',
        'addval_hash': 'A', 'generation_hash': 'G',
        'td_values': td, 'td_hash': canonical_hash(sorted(td, key=lambda r: r['component'])),
    }


def test_td_freeze_allows_only_declared_bc_changes():
    before = _snapshot()
    after = copy.deepcopy(before)
    rows = [{'component': 'WORK_E_C', 'candidate_b': 1.2, 'candidate_c': -0.12}]
    for r in after['td_values']:
        if r['component'] == 'WORK_E_C':
            r['current_b'] = 1.2; r['current_c'] = -0.12
    after['td_hash'] = canonical_hash(sorted(after['td_values'], key=lambda r: r['component']))
    v242._td_expected_freeze(before, after, rows)


def test_td_freeze_rejects_generation_change():
    before = _snapshot(); after = copy.deepcopy(before)
    after['generation_hash'] = 'OTHER'
    try:
        v242._td_expected_freeze(before, after, [])
    except Exception as exc:
        assert 'V242_TD_CHANGED_FROZEN_CONTEXT:generation_hash' in str(exc)
    else:
        raise AssertionError('generation mutation was not rejected')


def test_new_controller_hard_codes_supply_after_joint_demand_convergence():
    text = (ROOT / 'r1_15a2_overnight_controller_v242.py').read_text(encoding='utf-8')
    assert 'if not result["demand_converged"]' in text
    assert 'result["supply_started"] = True' in text
    assert text.index('if not result["demand_converged"]') < text.index('result["supply_started"] = True')

def test_controller_repeats_generation_then_td_and_only_then_supply(monkeypatch, tmp_path):
    cfg = json.loads((ROOT / 'R1_15A2_CONFIG_V2_4_2.json').read_text(encoding='utf-8'))
    cfg['coupled_demand']['max_outer_cycles'] = 3
    calls = []

    def state(tag):
        return {
            'fixed_link_hash':'F','dseg_hash':'D','operations_hash':'O',
            'addval_hash':'A','generation_hash':'G','td_hash':'T',
            'addval1':{}, 'state_hash':tag,
        }

    class Adapter:
        def __init__(self): self.s = state('S0')
        def preflight(self, folder): return {'passes':True}
        def snapshot(self): return copy.deepcopy(self.s)
        def assign(self, folder, *, supply_only): calls.append('baseline_assign' if not calls else 'assign'); return 0.001
        def diagnostics(self, folder, label='CURRENT'): return {'d12':{'rows':[]},'d11':{},'signals':{}}
        def save(self, path): return {'path':str(path),'sha256':'X'}

    adapter = Adapter()

    class Control:
        def checkpoint(self, *a, **k): pass
        def elapsed(self): return 1.0

    control = Control()
    monkeypatch.setattr(v242, 'build_reference', lambda diag, cfg: {'ref':'R'})
    monkeypatch.setattr(v242, 'diagnostic_hash', lambda diag: 'DH')
    monkeypatch.setattr(v242, '_save_rotating_checkpoint', lambda adapter, root, n: {'path':str(tmp_path/f'cp{n}.ver'),'sha256':'X'})

    gen_calls = {'n':0}
    def fake_gen(adapter, cfg, folder, control, st, diag, anchors, reference, policy):
        gen_calls['n'] += 1; calls.append('generation')
        changed = gen_calls['n'] == 1
        if changed:
            adapter.s = state('S1')
        return changed, adapter.snapshot(), diag, {'total':1.0}, {'status':'ACCEPTED' if changed else 'PLATEAU', 'search_complete':True, 'stationarity_confirmed':not changed}
    monkeypatch.setattr(v242, '_generation_update_once', fake_gen)

    td_calls = {'n':0}
    def fake_td(adapter, cfg, folder, control, st, diag, package_root):
        td_calls['n'] += 1; calls.append('finecdf_td')
        changed = td_calls['n'] == 1
        if changed:
            adapter.s = state('S2')
        return changed, adapter.snapshot(), diag, {'inner':{'stop_reason':'LOCAL_PLATEAU_NOT_PROOF_OF_GLOBAL_OPTIMUM', 'search_complete':True, 'stationarity_confirmed':True},'status':'X'}
    monkeypatch.setattr(v242, '_finecdf_td_once', fake_td)

    def fake_supply(adapter, cfg, folder, control):
        calls.append('supply')
        return {'status':'CONVERGED_NO_ACCEPTED_IMPROVEMENT','accepted_count':0, 'final_state_verified':True, 'stationarity_confirmed':True, 'final_diagnostic_hash':'DH', 'final_state_hash':adapter.snapshot()['state_hash']}
    monkeypatch.setattr(v242, 'run_overnight_calibration', fake_supply)

    result = v242.run_overnight_calibration_coupled(adapter, cfg, tmp_path/'run', control, ROOT)
    assert result['demand_converged'] is True
    assert result['supply_started'] is True
    # Ignore the initial baseline assignment marker; scientific substep order is exact.
    scientific = [x for x in calls if x in ('generation','finecdf_td','supply')]
    assert scientific == ['generation','finecdf_td','generation','finecdf_td','generation','finecdf_td','supply']

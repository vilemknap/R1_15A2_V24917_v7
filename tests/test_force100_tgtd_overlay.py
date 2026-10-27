from pathlib import Path
import r1_15a2_inplace_transaction_v239 as tx
import r1_15a2_overnight_controller_coupled_v24915p2_force100 as forced
from test_v245_workflow import setup_workflow, PLATEAU

ROOT = Path(__file__).resolve().parents[1]

def _setup(tmp_path, monkeypatch, max_outer=5):
    cfg, ctl, a = setup_workflow(tmp_path, monkeypatch)
    cfg['coupled_demand'].update(max_outer_cycles=max_outer, min_stationary_cycles=2, supply_max_cycles=5)
    cfg['runtime_demand_continuation'] = {
        'enabled': True,
        'mode': 'FRESH_CYCLE1_TEST_FORCE_EXACT_TGTD',
        'accepted_count': 0,
        'next_outer_cycle': 1,
        'inherited_outer_cycles': 0,
        'inherited_stationary_cycle_streak': 0,
        'inherited_completed_demand_cycles': 0,
        'max_lineage_outer_cycle': max_outer,
        'resume_substep': 'GENERATION',
        'bounded_inner_budget_stop_reasons': list(forced.V24914_BOUNDED_INNER_BUDGET_STOP_REASONS),
        'continue_bounded_budget_without_accepted_change': True,
    }
    def native_inner(adapter,cfg,folder,control,package_root,phase_budget=None):
        adapter.td_calls += 1
        return {'changed_rows': [], 'stop_reason': PLATEAU,
                'search_complete': True, 'stationarity_confirmed': True,
                'backend': 'SYNTHETIC'}
    monkeypatch.setattr(forced, 'run_finecdf_inner', native_inner)
    def write_bc(visum, rows):
        a.apply_td(rows)
        return [{'status':'OK'} for _ in rows]
    monkeypatch.setattr(tx.vp, 'apply_td_candidates', write_bc)
    a.no_generation = True
    a.td_change = False
    a.no_supply = True
    return cfg, ctl, a

def test_stationarity_does_not_end_tgtd_before_cap(tmp_path, monkeypatch):
    cfg, ctl, a = _setup(tmp_path, monkeypatch, max_outer=5)
    r = forced.run_overnight_calibration_coupled(a, cfg, tmp_path/'forced', ctl, ROOT)
    assert [c['cycle'] for c in r['demand_cycles']] == [1,2,3,4,5]
    assert a.td_calls == 5
    assert a.generation_design_calls == 5
    assert r['demand_converged'] is True
    assert r['demand_converged_cycle'] == 5
    assert r['supply_started'] is False
    assert r['supply_disabled_by_tgtd100_only_contract'] is True
    assert r['status'] == 'COMPLETED_EXACT_100_TGTD_SUPPLY_DISABLED'
    assert r['demand_cycles'][1]['stationarity_threshold_reached'] is True
    assert r['demand_cycles'][1]['forced_tgtd_cycles_remaining'] == 3

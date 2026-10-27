"""Demand policy (sparse TD, early stop) ported to V24917."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import r1_15a2_demand_policy_v1 as dp
import r1_15a2_overnight_controller_coupled_v24915p2_force100 as ctrl



# ------------------------------------------------------------------ options
def test_defaults_and_file_and_env(tmp_path):
    opts = dp.load_options(tmp_path, environ={})
    assert opts['td_policy'] == 'EVERY_N' and opts['td_every_n_cycles'] == 5
    assert opts['stop_when_stationary_cycles'] == 2 and opts['generation_envelope_scale'] == 1.0
    (tmp_path / dp.OPTIONS_FILE).write_text(json.dumps(
        {'td_policy': 'off', 'generation_envelope_scale': 3.2}), encoding='utf-8')
    opts = dp.load_options(tmp_path, environ={'R1_TD_EVERY_N': '3', 'R1_TD_ON_TG_PLATEAU': 'ne'})
    assert opts['td_policy'] == 'OFF' and opts['generation_envelope_scale'] == 3.2
    assert opts['td_every_n_cycles'] == 3 and opts['td_when_generation_plateau'] is False
    assert opts['_sources']['td_every_n_cycles'] == 'ENV:R1_TD_EVERY_N'


@pytest.mark.parametrize('raw', [{'td_policy': 'SOMETIMES'}, {'td_every_n_cycles': 0},
                                 {'generation_envelope_scale': 50},
                                 {'stop_when_stationary_cycles': -1},
                                 {'td_when_generation_plateau': 'maybe'}])
def test_invalid_options(raw):
    with pytest.raises(RuntimeError):
        dp.validate(raw)


def test_td_due():
    p = dp.DemandPolicy(dp.validate({}))
    assert p.td_due(3, True) == (True, 'FIRST_CYCLE_OF_RUN')   # td_first_cycle (default true)
    p = dp.DemandPolicy(dp.validate({'td_first_cycle': False}))
    assert p.td_due(3, True) == (False, 'NOT_DUE')
    assert p.td_due(5, True) == (True, 'EVERY_5')
    assert p.td_due(3, False) == (True, 'GENERATION_PLATEAU')
    assert p.td_due(3, None)[0] is True
    p = dp.DemandPolicy(dp.validate({'td_policy': 'OFF'}))
    assert p.td_due(5, False) == (False, 'OFF')
    p = dp.DemandPolicy(dp.validate({'td_policy': 'ALWAYS'}))
    assert p.td_due(3, True)[0] is True


# --------------------------------------------------- full coupled loop (fake)
def run_loop(monkeypatch, tmp_path, options, tg_changes_until=6, max_outer=12):
    holder = {'state': {'state_hash': 'S0', 'fixed_link_hash': 'a', 'dseg_hash': 'b',
                        'operations_hash': 'c', 'addval_hash': 'd', 'generation_hash': 'e',
                        'td_hash': 'f', 'addval1': {}}}
    td_calls, tg_calls = [], []

    def gen(adapter, cfg, folder, control, state, diag, anchors, reference, policy, outer_cycle=None):
        tg_calls.append(outer_cycle)
        changed = outer_cycle <= tg_changes_until
        if changed:
            state = dict(state, state_hash='S%d' % outer_cycle)
            holder['state'] = state
        rec = {'search_complete': True, 'stationarity_confirmed': not changed,
               'status': 'ACCEPTED' if changed else 'CONFIGURED_GENERATION_SEARCH_EXHAUSTED'}
        return changed, state, diag, {'total': 1.0}, rec

    def td(adapter, cfg, folder, control, state, diag, package_root, outer_cycle=None):
        td_calls.append(outer_cycle)
        return False, state, diag, {'status': 'FINECDF_TD_PLATEAU', 'td_realization_complete': True,
                                    'inner': {'search_complete': True, 'stop_reason': 'CONVERGED',
                                              'progress_continue': False}}

    monkeypatch.setattr(ctrl, '_generation_update_once', gen)
    monkeypatch.setattr(ctrl, '_finecdf_td_once', td)
    launcher = SimpleNamespace(coupled_runtime=ctrl)
    monkeypatch.setattr(dp, '_ACTIVE', {})
    state = dp.activate(launcher, options=dp.validate(options), print_fn=lambda *a: None)
    monkeypatch.setattr(ctrl, 'build_reference', lambda diag, cfg: {'ref': 1})
    monkeypatch.setattr(ctrl, 'ledger', lambda *a, **k: {'total': 1.0})
    monkeypatch.setattr(ctrl, 'diagnostic_hash', lambda d: 'H')
    monkeypatch.setattr(ctrl, 'stationary_td_result', lambda inner: True)
    monkeypatch.setattr(ctrl, '_save_rotating_checkpoint', lambda adapter, folder, n: {'path': 'cp%d' % n})
    monkeypatch.setattr(ctrl, '_final_snapshot_with_retry', lambda adapter, cfg, label, audit: holder['state'])
    adapter = SimpleNamespace(preflight=lambda folder: {}, snapshot=lambda: holder['state'],
                              assign=lambda folder, supply_only: 0.0,
                              diagnostics=lambda folder, label: {'d': 1})
    control = SimpleNamespace(checkpoint=lambda *a, **k: None, elapsed=lambda: 0.0)
    cfg = {'coupled_demand': {'max_outer_cycles': max_outer, 'min_stationary_cycles': 2}}
    result = ctrl.run_overnight_calibration_coupled(adapter, cfg, tmp_path, control, tmp_path)
    return result, td_calls, tg_calls, state


def test_sparse_td_and_early_stop(monkeypatch, tmp_path):
    result, td_calls, tg_calls, state = run_loop(monkeypatch, tmp_path, {})
    assert td_calls == [1, 5, 7, 8]                 # first cycle of the run + every 5th + TG plateau
    assert tg_calls == [1, 2, 3, 4, 5, 6, 7, 8]     # cycle 9 stopped before TG
    assert result['status'].startswith('STOPPED_AT_LAST_VERIFIED_STATE:R1_DEMAND_STATIONARY_EARLY_STOP')
    assert result['final_state_verified'] is True
    statuses = {c['cycle']: c['status'] for c in result['demand_cycles']}
    assert statuses[1] == 'COMPLETED' and statuses[2] == 'PROGRESS_CONTINUE_DEMAND'
    assert statuses[5] == 'COMPLETED'
    assert statuses[9] == 'INTERRUPTED'
    assert result['accepted_count'] == 6
    skipped = json.loads((tmp_path / 'DEMAND_CYCLE_02_TD_FINECDF' / 'TD_FINECDF_BLOCK_RESULT.json').read_text())
    assert skipped['status'] == dp.SKIP_REASON and skipped['skip_policy_reason'] == 'NOT_DUE'
    assert [r['streak'] for r in state['policy'].records][-2:] == [1, 2]


def test_td_off_and_no_early_stop_runs_all_cycles(monkeypatch, tmp_path):
    result, td_calls, tg_calls, _ = run_loop(
        monkeypatch, tmp_path, {'td_policy': 'OFF', 'stop_when_stationary_cycles': 0}, max_outer=8)
    assert td_calls == [] and tg_calls == list(range(1, 9))
    assert result['status'] == 'COMPLETED_EXACT_100_TGTD_SUPPLY_DISABLED'
    assert all(c['status'] == 'PROGRESS_CONTINUE_DEMAND' for c in result['demand_cycles'])


def test_always_matches_previous_behaviour(monkeypatch, tmp_path):
    result, td_calls, _, _ = run_loop(
        monkeypatch, tmp_path, {'td_policy': 'ALWAYS', 'stop_when_stationary_cycles': 0}, max_outer=5)
    assert td_calls == [1, 2, 3, 4, 5]


# ----------------------------------------------------------------- envelope
def test_envelope_scale(monkeypatch):
    import r1_15a2_multiblock as mb
    monkeypatch.setattr(mb, '_multiplicative_coefficient_bounds', mb._multiplicative_coefficient_bounds)
    monkeypatch.setattr(mb, '_soft_multiplier_bounds', mb._soft_multiplier_bounds)
    cfg = {'guidance_mode': 'SIGNED', 'generation_signed_refinement': {
        'enabled': True, 'domestic_hard_min': 0.5, 'domestic_hard_max': 2.0,
        'domestic_soft_min': 0.8, 'domestic_soft_max': 1.25,
        'zahr_reference_multiplier_min': 0.5, 'zahr_reference_multiplier_max': 2.0,
        'zahr_reference_soft_min': 0.7, 'zahr_reference_soft_max': 1.3}}
    zahr_before = mb._multiplicative_coefficient_bounds('ZAHR', cfg, 5.0, 4.0)
    assert dp.patch_envelope(mb, 3.0) is True
    low, high, name = mb._multiplicative_coefficient_bounds('DOMESTIC', cfg, 3.3)
    assert (low, high, name) == (1.5, 6.0, 'AMDY_LIKE_DOMESTIC_ABSOLUTE_ENVELOPE')
    assert mb._multiplicative_coefficient_bounds('DOMESTIC', cfg, 7.0)[1] == 7.0   # inward only
    assert mb._soft_multiplier_bounds('DOMESTIC', cfg, 3.0) == pytest.approx((2.4, 3.75))
    assert mb._multiplicative_coefficient_bounds('ZAHR', cfg, 5.0, 4.0) == zahr_before
    assert mb._soft_multiplier_bounds('ZAHR', cfg, 5.0, 4.0) == pytest.approx((2.8, 5.2))
    assert dp.patch_envelope(mb, 3.0) is True                    # idempotent
    with pytest.raises(RuntimeError):
        dp.patch_envelope(mb, 2.0)


def test_envelope_scale_one_is_noop():
    import r1_15a2_multiblock as mb
    before = mb._multiplicative_coefficient_bounds
    assert dp.patch_envelope(mb, 1.0) is False
    assert mb._multiplicative_coefficient_bounds is before



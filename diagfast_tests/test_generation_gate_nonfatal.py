"""TG pre-apply gate hotfix: GENERATION_GATE rejects the candidate, never fails the run."""
from pathlib import Path
from types import SimpleNamespace

import pytest

import r1_15a2_generation_gate_nonfatal_v1 as hot
import r1_15a2_overnight_controller_coupled_v24915p2_force100 as ctrl
from r1_15a2_supply import SupplyContractError


def fake_original(outcomes):
    calls = []

    def evaluate(adapter, cfg, policy, block, candidate, rows, context, before,
                 baseline_diag, baseline_value, anchors, reference, folder, control):
        calls.append(candidate['scale'])
        kind = outcomes[len(calls) - 1]
        if kind == 'gate':
            return None, baseline_diag, 'GENERATION_GATE:GENERATION_PA_GAP_WORK'
        if kind == 'other':
            return None, baseline_diag, 'GENERATION_READBACK_FAILED'
        return ({'eligible': False, 'decision': {'accepted': False, 'reasons': ['X']},
                 'after_value': {'total': 2.0}, 'candidate': candidate, 'rows': rows},
                baseline_diag, None)
    return evaluate, calls


def run_block(monkeypatch, tmp_path, outcomes, patched=True):
    evaluate, calls = fake_original(outcomes)
    monkeypatch.setattr(ctrl, '_evaluate_candidate', evaluate)
    if patched:
        monkeypatch.setattr(ctrl, '_evaluate_candidate', hot.wrap_evaluate(evaluate, []))
    monkeypatch.setattr(ctrl, 'ledger', lambda *a, **k: {'total': 1.0})
    monkeypatch.setattr(ctrl, '_planned_generation_rows', lambda adapter, context, scale: ({'scale': scale}, [{'zone': 1}]))
    monkeypatch.setattr(ctrl, 'diagnostic_hash', lambda d: 'H')
    adapter = SimpleNamespace(generation_design=lambda diag, folder: {}, snapshot=lambda: 'STATE')
    control = SimpleNamespace(checkpoint=lambda *a, **k: None)
    cfg = {'backtracking_scales': [1.0, 0.75, 0.5, 0.25, 0.125, 0.0625],
           'trial_calibration': {'max_trials_per_block': {'GENERATION': 6}}}
    result = ctrl._generation_update_once_impl(adapter, cfg, tmp_path, control, 'STATE', {'d': 1},
                                               {}, {}, None)
    return result, calls


def test_gate_rejection_continues_and_ends_as_plateau(monkeypatch, tmp_path):
    (changed, state, diag, value, rec), calls = run_block(
        monkeypatch, tmp_path, ['rej', 'rej', 'rej', 'rej', 'gate', 'rej'])
    assert changed is False and state == 'STATE'
    assert calls == [1.0, 0.75, 0.5, 0.25, 0.125, 0.0625]
    assert rec['status'] == 'CONFIGURED_GENERATION_SEARCH_EXHAUSTED'
    assert rec['attempts'][4]['status'] == 'REJECTED'
    assert rec['attempts'][4]['decision']['reasons'] == ['PRE_APPLY_GATE:GENERATION_PA_GAP_WORK']


def test_without_hotfix_the_same_case_fails(monkeypatch, tmp_path):
    with pytest.raises(SupplyContractError, match='GENERATION_GATE:GENERATION_PA_GAP_WORK'):
        run_block(monkeypatch, tmp_path, ['rej', 'rej', 'rej', 'rej', 'gate', 'rej'], patched=False)


def test_other_errors_stay_fatal(monkeypatch, tmp_path):
    with pytest.raises(SupplyContractError, match='GENERATION_READBACK_FAILED'):
        run_block(monkeypatch, tmp_path, ['rej', 'other', 'rej', 'rej', 'rej', 'rej'])


def test_supply_block_untouched():
    evaluate, calls = fake_original(['gate'])
    wrapped = hot.wrap_evaluate(evaluate, [])
    ev, diag, error = wrapped(None, {}, None, 'SUPPLY_ADDVAL1', {'scale': 1.0}, [], None, 'S',
                              {'d': 1}, {'total': 1.0}, {}, {}, Path('.'), None)
    assert ev is None and error.startswith('GENERATION_GATE:')


def test_gap_override_validation(monkeypatch):
    monkeypatch.setenv(hot.GAP_ENV, '0,05')
    assert hot.gap_override() == 0.05
    monkeypatch.setenv(hot.GAP_ENV, '2')
    with pytest.raises(RuntimeError):
        hot.gap_override()
    monkeypatch.delenv(hot.GAP_ENV)
    assert hot.gap_override() is None


def test_activate_records_config_and_override(monkeypatch):
    monkeypatch.setenv(hot.GAP_ENV, '0.04')
    controller = SimpleNamespace(__name__='fake_ctrl', _evaluate_candidate=fake_original(['rej'])[0])
    launcher = SimpleNamespace(coupled_runtime=controller,
                               prepare_runtime_config=lambda *a, **k: ({'max_generation_pa_relative_gap': 0.02}, None))
    state = hot.activate(launcher)
    cfg = launcher.prepare_runtime_config()[0]
    assert cfg['max_generation_pa_relative_gap'] == 0.04
    assert cfg['aggressive_tuning']['generation_gate_nonfatal']['pre_apply_generation_gate'] == 'REJECT_CANDIDATE_NOT_FAIL_RUN'
    assert getattr(controller._evaluate_candidate, '__r1_generation_gate_nonfatal__')
    assert hot.activate(launcher) is state      # idempotent

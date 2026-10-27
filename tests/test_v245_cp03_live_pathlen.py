from pathlib import Path
import csv
import json
import os

import pytest

import r1_15a2_runtime_v1 as rt
import r1_15a2_inplace_transaction_v239 as tx


def _fake_12d_helper(captured):
    def fake(script, visum, stage, workspace, stage_log):
        ws = Path(workspace)
        captured['workspace'] = ws
        captured['stage_log'] = Path(stage_log)
        nested = ws / 'R1_12D_CSD2022_GEH_FORENSIC' / 'R1_12D_20990101_000000'
        nested.mkdir(parents=True, exist_ok=True)
        with (nested / rt.D12_DETAIL).open('w', newline='', encoding='utf-8-sig') as h:
            w = csv.DictWriter(h, fieldnames=['role', 'model', 'observed'])
            w.writeheader(); w.writerow({'role': 'CALIBRATION', 'model': 100, 'observed': 100})
        (nested / rt.D12_SUMMARY).write_text(json.dumps({'status':'PASS'}), encoding='utf-8')
        (nested / '19_CSD408_CITY90_AUTHORITY_CHECK.json').write_text(json.dumps({'status':'PASS'}), encoding='utf-8')
        (nested / '12d_PASS.txt').write_text('PASS\n', encoding='utf-8')
    return fake


def test_cp03_12d_executes_outside_deep_controller_tree_and_publishes_compact_mirror(tmp_path, monkeypatch):
    captured = {}
    monkeypatch.setattr(rt, 'run_helper', _fake_12d_helper(captured))
    deep = tmp_path / ('RUN_' + 'x'*40) / 'CALIBRATION' / 'DEMAND_CYCLE_01_GENERATION' / 'TRY_01' / 'ROLLBACK'
    cfg = {'expected_12d_rows':1, 'expected_calibration_rows':1, 'expected_validation_rows':0}
    result = rt.run_12d(None, deep, 'ROLLBACK', cfg)
    scratch = captured['workspace']
    assert not str(scratch).startswith(str(deep))
    assert len(str(scratch)) <= 120
    assert not scratch.exists()  # scratch is cleaned after durable evidence publication
    mirror = deep / '12D_ROLLBACK'
    assert Path(result['detail_path']).is_file()
    assert Path(result['summary_path']).is_file()
    assert (mirror / '19_CSD408_CITY90_AUTHORITY_CHECK.json').is_file()
    assert (deep / '12D_ROLLBACK.zip').is_file()
    policy = json.loads((mirror / 'HELPER_WORKSPACE_POLICY.json').read_text(encoding='utf-8'))
    assert policy['execution_workspace_policy'] == 'SHORT_OS_TEMP'


def test_cp03_known_live_failure_path_is_over_legacy_max_path_but_short_run_root_has_headroom():
    old = (
        "C:\\Users\\vilem_knap\\Documents\\VISUM\\v45\\2022\\"
        "R1_15A2_V2_4_5_FULL_CALIBRATION_REPAIR_RUNS\\RUN_20261016_130246_304692\\"
        "CALIBRATION\\DEMAND_CYCLE_01_GENERATION\\TRY_01\\ROLLBACK\\12D_ROLLBACK\\"
        "R1_12D_CSD2022_GEH_FORENSIC\\R1_12D_20261016_132622\\01_DETAIL_498_FORENSIC.csv"
    )
    new = old.replace('R1_15A2_V2_4_5_FULL_CALIBRATION_REPAIR_RUNS', 'R1_15A2_V245_RUNS')
    assert len(old) == 261
    assert len(new) == 235
    assert len(new) < 240


class _DiagFailAdapter:
    def __init__(self, before):
        self.before = before
    def snapshot(self):
        return self.before
    def diagnostics(self, folder, label):
        raise OSError('diagnostic I/O failed after state restore')


def test_cp03_rollback_persists_state_restore_proof_before_diagnostic_io_failure(tmp_path, monkeypatch):
    before = {'state_hash':'BASE', 'generation_values':{}, 'td_values':[], 'addval1':{}}
    adapter = _DiagFailAdapter(before)
    monkeypatch.setattr(tx, 'restore_parameters', lambda *a, **k: [])
    monkeypatch.setattr(tx, 'recompute_after_restore', lambda *a, **k: 0.001)
    with pytest.raises(OSError, match='diagnostic I/O failed'):
        tx.rollback_and_verify(adapter, 'GENERATION', before, 'DH', lambda d:'DH', tmp_path)
    proof = json.loads((tmp_path / 'ROLLBACK_STATE_RESTORED.json').read_text(encoding='utf-8'))
    assert proof['snapshot_equal'] is True
    assert proof['status'] == 'STATE_RESTORED_PENDING_DIAGNOSTIC_VERIFICATION'

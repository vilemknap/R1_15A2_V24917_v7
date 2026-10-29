"""Live startup failure: save-boundary operation evidence precedes the exact gate."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from test_v24917_snapshot_reads_genfix1 import _adapter, _original
import r1_15a2_snapshot_reads_v24917 as strict
import r1_15a2_restart_v2494 as restart


def startup(tmp_path):
    adapter = _adapter()
    adapter.control = SimpleNamespace(root=tmp_path, progress={'phase': 'SOURCE_SEMANTIC_RESTART_AUTHORITY'})
    return adapter


def working(adapter):
    adapter.control.progress['phase'] = 'WORKING_COPY_SEMANTIC_IDENTITY'
    return strict.strict_snapshot(adapter)


@pytest.mark.parametrize('attribute,value,field', [
    ('ACTIVE', 0, 'active'), ('OPERATIONTYPE', 99, 'type'),
    ('COMMENT', 'changed by synthetic save', 'comment'),
    ('NAME', 'display name after synthetic save', 'name'),
])
def test_exact_changed_operation_attribute_is_published_before_guard_failure(tmp_path, attribute, value, field):
    adapter = startup(tmp_path)
    before = strict.strict_snapshot(adapter)
    adapter.visum.Procedures.Operations.items[0].SetAttValue(attribute, value)
    after = working(adapter)
    report_path = tmp_path / 'WORKING_COPY_OPERATIONS_DIFF.json'
    assert report_path.is_file()  # This exists before the parent raises or publishes its working authority.
    report = json.loads(report_path.read_text())
    assert report['semantic_fields_changed'] == ['operations_hash']
    assert report['changed_operation_count'] == 1
    difference = report['operation_changes'][0]
    assert difference['position'] == 1 and list(difference['fields']) == [field]
    assert difference['fields'][field]['after'] == value
    assert report['source']['operation_inventory_hash_verified']
    assert report['working_copy']['operation_inventory_hash_verified']
    with pytest.raises(restart.SupplyContractError, match='WORKING_COPY_SEMANTIC_IDENTITY_MISMATCH:operations_hash'):
        restart.require_authority_match(restart.build_authority(before), restart.build_authority(after),
                                        label='WORKING_COPY_SEMANTIC_IDENTITY')
    assert after == _original(adapter)  # exact snapshot schema, bytes and semantics retained


def test_successful_save_preserves_identical_schema_and_hashes(tmp_path):
    adapter = startup(tmp_path)
    before = strict.strict_snapshot(adapter)
    after = working(adapter)
    assert after == before == _original(adapter)
    report = json.loads((tmp_path / 'WORKING_COPY_OPERATIONS_DIFF.json').read_text())
    assert report['semantic_fields_changed'] == [] and report['operation_changes'] == []
    assert restart.require_authority_match(restart.build_authority(before), restart.build_authority(after))['passes']
    assert set(p.name for p in tmp_path.iterdir()) == {
        'SOURCE_OPERATIONS_READBACK.json', 'WORKING_COPY_OPERATIONS_READBACK.json',
        'WORKING_COPY_OPERATIONS_DIFF.json'}


def test_other_semantic_changes_are_reported_and_still_rejected(tmp_path):
    adapter = startup(tmp_path)
    before = strict.strict_snapshot(adapter)
    adapter.visum.Net.Matrices.ItemByKey(9101).values[0, 1] += .01
    after = working(adapter)
    report = json.loads((tmp_path / 'WORKING_COPY_OPERATIONS_DIFF.json').read_text())
    assert report['operation_changes'] == [] and report['semantic_fields_changed'] == ['matrix_hash']
    with pytest.raises(restart.SupplyContractError, match='MISMATCH:matrix_hash'):
        restart.require_authority_match(restart.build_authority(before), restart.build_authority(after))


def test_diagnostics_never_modify_live_operation_attributes(tmp_path):
    adapter = startup(tmp_path)
    for obj in adapter.visum.Procedures.Operations.items:
        obj.SetAttValue = lambda *a: pytest.fail('diagnostic attempted a model write')
    strict.strict_snapshot(adapter)
    working(adapter)


def test_evidence_disk_failure_never_overrides_snapshot_or_approves_a_mismatch(tmp_path, monkeypatch):
    adapter = startup(tmp_path)
    def failing_write(*a, **k):
        raise PermissionError('synthetic file lock')
    monkeypatch.setattr(strict.rt, 'write_json', failing_write)
    before = strict.strict_snapshot(adapter)
    assert before == _original(adapter)
    adapter.visum.Procedures.Operations.items[0].SetAttValue('COMMENT', 'real change')
    after = working(adapter)
    with pytest.raises(restart.SupplyContractError, match='MISMATCH:operations_hash'):
        restart.require_authority_match(restart.build_authority(before), restart.build_authority(after))


def test_routine_snapshot_does_not_write_or_keep_startup_evidence(tmp_path):
    adapter = startup(tmp_path)
    adapter.control.progress['phase'] = 'DEMAND_CYCLE_001_GENERATION'
    strict.strict_snapshot(adapter)
    assert list(tmp_path.iterdir()) == []
    assert not hasattr(adapter, '_v24917_source_operation_readback')


def test_working_snapshot_without_source_keeps_actual_readback_without_fabricated_comparison(tmp_path):
    adapter = startup(tmp_path)
    working(adapter)
    assert (tmp_path / 'WORKING_COPY_OPERATIONS_READBACK.json').is_file()
    assert not (tmp_path / 'WORKING_COPY_OPERATIONS_DIFF.json').exists()


@pytest.mark.parametrize('before,after,position', [
    ([{'no': 1}], [{'no': 1}, {'no': 2}], 2),
    ([{'no': 1}, {'no': 2}], [{'no': 1}], 2),
    ([{'no': 1}, {'no': 2}], [{'no': 2}, {'no': 1}], 1),
])
def test_operation_inventory_diff_detects_added_removed_and_reordered_operations(before, after, position):
    delta = strict._operation_changes(before, after)
    assert delta[0]['position'] == position
    assert delta[0]['before'] != delta[0]['after']

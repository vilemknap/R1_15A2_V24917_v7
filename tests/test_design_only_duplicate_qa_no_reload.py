"""Design-only narrow hotfix tests; no real COM, no assignment, no Visum writes."""
from pathlib import Path
import csv
import json
import pytest

from synthetic_v22_adapter import SyntheticAdapter, synthetic_config
from r1_15a2_controller_v22 import run_calibration
from r1_15a2_supply import ActualRouteCollector, SupplyContractError, SupplyPolicy
from r1_15a2_sequence_v23 import ActualSequenceRouteCollector

HERE = Path(__file__).resolve().parents[1]


def row(obs_id, key, observed, model, source='CSD2022', role='CALIBRATION'):
    return dict(countlocation_no=obs_id, link_no=key[0], from_node_no=key[1],
                to_node_no=key[2], observed=float(observed), model=float(model),
                role=role, source_group=source, profile_weight=1.0,
                observation_direction='DIRECTED')


def scope_fixture():
    a = (2003608, 1000670, 1000663)
    b = (2003608, 1000663, 1000670)
    c = (123, 4, 5)
    return [row('920259', a, 2103, 3000), row('920421', a, 1373, 3000),
            row('920260', b, 2103, 3000), row('920420', b, 1373, 3000),
            row('other', c, 500, 2500)], [a, b, c]


def test_strict_default_still_fails_on_conflicted_same_source_scope():
    rr, keys = scope_fixture()
    with pytest.raises(SupplyContractError, match='CONFLICTING_DUPLICATE_COUNT'):
        ActualRouteCollector(rr, SupplyPolicy(min_geh=1., min_residual=1.), 'parent', keys)
    with pytest.raises(SupplyContractError, match='CONFLICTING_DUPLICATE_COUNT'):
        ActualSequenceRouteCollector(rr, SupplyPolicy(min_geh=1., min_residual=1.), 'parent', keys)


def test_diagnostic_excludes_only_conflict_drivers_and_never_changes_observations():
    rr, keys = scope_fixture()
    before = json.loads(json.dumps(rr))
    c = ActualRouteCollector(rr, SupplyPolicy(min_geh=1., min_residual=1.), 'parent', keys,
                             duplicate_scope_policy='DIAGNOSTIC_EXCLUDE_CONFLICTED_DRIVERS')
    assert c.drivers == [4]
    assert c.duplicate_scope_audit['conflicting_same_source_groups'] == 2
    assert c.duplicate_scope_audit['excluded_conflicting_driver_indices'] == [0,1,2,3]
    assert len(c.profiles) == 5
    assert rr == before
    assert c.duplicate_scope_audit['all_observations_retained'] is True
    assert c.profile_index_by_key[keys[0]] == [0,1]
    assert c.profile_index_by_key[keys[1]] == [2,3]


def test_city_overlap_is_reported_without_fake_same_source_duplicate():
    a = (12, 1, 2)
    rr = [row('CSD', a, 1000, 2500, 'CSD2022'),
          row('CITY', a, 2000, 2500, 'CITY_RPDI_LEGACY')]
    c=ActualRouteCollector(rr, SupplyPolicy(min_geh=1., min_residual=1.), 'p', [a],
                           duplicate_scope_policy='DIAGNOSTIC_EXCLUDE_CONFLICTED_DRIVERS')
    assert c.duplicate_scope_audit['conflicting_same_source_groups'] == 0
    assert c.duplicate_scope_audit['overlapping_directed_link_group_count'] == 1
    assert c.drivers == [0, 1]


def test_real_locked_csd_authority_has_exact_conflict_pairs_and_all_498_preserved():
    f=HERE/'authorities/R1_CSD2022_COUNTLOCATION_AUTHORITY_408.csv'
    rr=list(csv.DictReader(f.open(encoding='utf-8-sig',newline='')))
    assert len(rr) == 408
    index={str(r['countlocation_no']):r for r in rr}
    for a,b,frm,to in [('920259','920421',1000670,1000663),
                       ('920260','920420',1000663,1000670)]:
        x,y=index[a],index[b]
        assert [x[k] for k in ('current_link_no','current_from_node_no','current_to_node_no')] == [
                 y[k] for k in ('current_link_no','current_from_node_no','current_to_node_no')]
        assert (int(x['current_link_no']),int(x['current_from_node_no']),int(x['current_to_node_no'])) == (2003608, frm,to)
        assert {float(x['observed_passenger_cars_O']),float(y['observed_passenger_cars_O'])} == {2103.,1373.}
        assert x['role'] == y['role'] == 'CALIBRATION'
    city=list(csv.DictReader((HERE/'authorities/R1_CITY_RPDI_COUNTLOCATION_AUTHORITY_90.csv').open(encoding='utf-8-sig',newline='')))
    assert len(city)==90
    assert len(rr)+len(city)==498


def test_design_only_failed_block_does_not_call_restore_and_continues(tmp_path):
    class Reject(SyntheticAdapter):
        def supply_design(self,diag,folder,snapshot):
            raise SupplyContractError('INJECTED_DESIGN_ERROR_WITH_LIVE_COM_REFS')
    cfg=synthetic_config();cfg['apply']=False
    a=Reject(cfg,broken_restore=True)
    original=a.snapshot()
    r=run_calibration(a,cfg,tmp_path)
    assert r['status']=='DESIGN_ONLY_BLOCKERS'
    assert r['accepted_count']==0
    assert len(r['blocks'])==3
    assert r['blocks'][0]['error']=='INJECTED_DESIGN_ERROR_WITH_LIVE_COM_REFS'
    assert r['blocks'][0]['model_unchanged'] is True
    assert all(b['rollback_action']=='NOT_REQUIRED_READ_ONLY' for b in r['blocks'])
    assert a.restores==0 and a.assignments==[] and a.snapshot()==original
    assert (tmp_path/'BASELINE'/'READ_ONLY_GUARD.ver').is_file()


def test_design_only_state_drift_never_auto_restores_and_forces_manual_reopen(tmp_path):
    class MaliciousMutation(SyntheticAdapter):
        def supply_design(self,diag,folder,snapshot):
            self.state['a']['1|1|2'] += 17.
            raise RuntimeError('INJECTED_ACCIDENTAL_MUTATION')
    cfg=synthetic_config();cfg['apply']=False
    a=MaliciousMutation(cfg)
    result=run_calibration(a,cfg,tmp_path)
    assert result['status']=='DESIGN_ONLY_MODEL_STATE_UNVERIFIED_MANUAL_REOPEN_REQUIRED'
    assert 'DESIGN_ONLY_STATE_DRIFT_MANUAL_REOPEN_REQUIRED' in result['error']
    assert a.restores==0 and not a.assignments
    assert result['blocks'][0]['status']=='STATE_DRIFT_STOP'
    assert len(result['blocks'])==1


def test_design_only_unreadable_snapshot_does_not_call_loadversion(tmp_path):
    class NonReadable(SyntheticAdapter):
        def supply_design(self,diag,folder,snapshot):
            self.snapshot_bad=True
            raise RuntimeError('SIMULATED_REF_ERROR')
        def snapshot(self):
            if getattr(self,'snapshot_bad',False):
                raise RuntimeError('INJECTED_SNAPSHOT_COM_READ_ERROR')
            return super().snapshot()
    cfg=synthetic_config();cfg['apply']=False
    a=NonReadable(cfg)
    result=run_calibration(a,cfg,tmp_path)
    assert result['status']=='DESIGN_ONLY_MODEL_STATE_UNVERIFIED_MANUAL_REOPEN_REQUIRED'
    assert 'DESIGN_ONLY_POST_BLOCK_SNAPSHOT_UNREADABLE' in result['error']
    assert a.restores==0


def test_dry_run_prohibits_explicit_resume_or_hidden_loadversion(tmp_path):
    cfg=synthetic_config();cfg['apply']=False
    a=SyntheticAdapter(cfg)
    result=run_calibration(a,cfg,tmp_path,resume_from=tmp_path/'old')
    assert 'DESIGN_ONLY_RESUME_COM_LOADVERSION_FORBIDDEN' in result['error']
    assert a.restores==0 and a.assignments==[]


def test_read_only_qa_status_not_misrepresented_as_live_apply_ready(tmp_path):
    class WithConflictAudit(SyntheticAdapter):
        def supply_design(self,diag,folder,snapshot):
            d=super().supply_design(diag,folder,snapshot)
            d['duplicate_scope_audit']={
                'conflicting_same_source_groups':2,
                'overlapping_directed_link_group_count':20}
            return d
    cfg=synthetic_config();cfg['apply']=False
    a=WithConflictAudit(cfg)
    r=run_calibration(a,cfg,tmp_path)
    assert r['status']=='DESIGN_ONLY_NEEDS_DUPLICATE_SCOPE_QA'
    assert r['blocks'][0]['duplicate_scope_review_required'] is True
    assert r['blocks'][0]['conflicting_same_source_groups']==2
    assert a.restores==0


def test_design_only_policy_is_explicit_and_never_for_apply():
    cfg=json.loads((HERE/'R1_15A2_CONFIG_V2_3_7.json').read_text())
    assert cfg['apply'] is False
    assert cfg['supply']['assignment_operations']==[]
    assert cfg['supply']['sequence']['design_only_duplicate_scope_policy']=='DIAGNOSTIC_EXCLUDE_CONFLICTED_DRIVERS'
    assert cfg['supply']['gap_readback']['maximum_gap']==0.005


def test_sequence_collector_diagnostic_has_no_conflict_drivers_but_retains_all_rows(tmp_path):
    rr,keys = scope_fixture()
    col=ActualSequenceRouteCollector(rr, SupplyPolicy(min_geh=1.,min_residual=1.),
                                    'parent',keys,db_path=tmp_path/'proof.sqlite',
                                    duplicate_scope_policy='DIAGNOSTIC_EXCLUDE_CONFLICTED_DRIVERS')
    try:
        assert col.drivers==[4]
        assert col.cal_indices==set(range(5))
        assert col.duplicate_scope_audit['conflicting_same_source_groups']==2
        assert col.db.execute('SELECT COUNT(*) FROM routes').fetchone()[0]==0
    finally:
        col.close()

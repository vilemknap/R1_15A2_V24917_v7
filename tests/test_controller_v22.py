import copy,json
from pathlib import Path
import pytest
from synthetic_v22_adapter import SyntheticAdapter,synthetic_config
from r1_15a2_controller_v22 import run_calibration,assert_freeze,build_reference,ledger
from r1_15a2_supply import SupplyContractError,SupplyPolicy


def test_full_controller_all_blocks_best_supply_and_one_pointer(tmp_path):
    cfg=synthetic_config();a=SyntheticAdapter(cfg)
    result=run_calibration(a,cfg,tmp_path)
    assert result['status']=='BOUNDED_CYCLE_LIMIT',result
    assert result['accepted_count']==3
    assert result['blocks'][0]['selected_trial']==2
    assert a.state['a']=={'1|1|2':0.,'2|2|3':-1.}
    assert a.state['q']>1000 and a.state['b']>0
    record=json.loads((tmp_path/'ACCEPTED_STATE.json').read_text())
    assert record['block']=='TD_COMPONENT_WORK'
    assert set(record['original_addval_anchors'].values())=={0.}
    totals=[r['ledger']['total'] for r in result['blocks'] if r['status']=='ACCEPTED']
    assert all(b<a for a,b in zip(totals,totals[1:]))
    assert all(t.get('rollback_verified') for r in result['blocks'] for t in r['attempts'])


def test_supply_failure_does_not_abort_demand_cycle(tmp_path):
    cfg=synthetic_config();a=SyntheticAdapter(cfg,mutate_supply_demand=True)
    result=run_calibration(a,cfg,tmp_path)
    assert result['accepted_count']==2,result
    assert result['blocks'][0]['status']=='NO_ACCEPTED_CANDIDATE'
    assert all(t['status']=='FAILED_ROLLED_BACK' for t in result['blocks'][0]['attempts'])
    assert a.state['a']=={'1|1|2':0.,'2|2|3':0.}
    assert result['cycles'][0]['examined']==cfg['block_schedule']


def test_no_progress_only_after_complete_cycle(tmp_path):
    cfg=synthetic_config();a=SyntheticAdapter(cfg,flat=True)
    result=run_calibration(a,cfg,tmp_path)
    assert result['status']=='COMPLETE_CYCLE_NO_ACCEPTED_IMPROVEMENT',result
    assert result['accepted_count']==0
    assert result['cycles'][0]['examined']==cfg['block_schedule']
    assert result['cycles'][0]['scientific_optimum_claimed'] is False
    assert a.state['q']==1000 and a.state['b']==0


def test_apply_bound_not_misreported_as_convergence(tmp_path):
    cfg=synthetic_config();cfg['max_accepted_blocks']=1;a=SyntheticAdapter(cfg)
    result=run_calibration(a,cfg,tmp_path)
    assert result['status']=='BOUNDED_ACCEPTED_LIMIT' and result['accepted_count']==1
    assert result['cycles']==[]


def test_save_failure_never_publishes_candidate(tmp_path):
    cfg=synthetic_config();cfg['block_schedule']=['SUPPLY_ADDVAL1'];a=SyntheticAdapter(cfg,fail_save=True)
    result=run_calibration(a,cfg,tmp_path)
    assert result['accepted_count']==0
    assert json.loads((tmp_path/'ACCEPTED_STATE.json').read_text())['block']=='BASELINE'
    assert all(v==0 for v in a.state['a'].values())


def test_rollback_failure_is_fatal(tmp_path):
    cfg=synthetic_config();a=SyntheticAdapter(cfg,broken_restore=True)
    result=run_calibration(a,cfg,tmp_path)
    assert result['status']=='ROLLBACK_FAILED_STOP_MANUAL_RECOVERY_REQUIRED',result
    assert result['accepted_count']==0


def test_dry_run_has_no_assignments_or_accepted_state(tmp_path):
    cfg=synthetic_config();cfg['apply']=False;a=SyntheticAdapter(cfg)
    original=a.snapshot();result=run_calibration(a,cfg,tmp_path)
    assert result['status']=='DESIGN_ONLY_READY_FOR_LIVE_APPLY_GATE',result
    assert a.snapshot()==original and not a.assignments
    assert not (tmp_path/'ACCEPTED_STATE.json').exists()


def test_resume_preserves_original_anchor_and_objective_reference(tmp_path):
    cfg=synthetic_config();cfg['max_accepted_blocks']=1
    a=SyntheticAdapter(cfg);first=tmp_path/'first';r=run_calibration(a,cfg,first)
    assert r['accepted_count']==1
    old=json.loads((first/'ACCEPTED_STATE.json').read_text())
    b=SyntheticAdapter(cfg);second=tmp_path/'second';r=run_calibration(b,cfg,second,resume_from=first)
    assert r.get('recovery_semantics')=='RESTART_CYCLE_FROM_ACCEPTED_WITH_PRESERVED_ANCHORS',r
    assert json.loads((second/'ORIGINAL_ADDVAL1_ANCHORS.json').read_text())==old['original_addval_anchors']
    assert json.loads((second/'OBJECTIVE_REFERENCE.json').read_text())==old['reference']


@pytest.mark.parametrize('field',['fixed_link_hash','matrix_hash','generation_hash','td_hash','operations_hash','dseg_hash'])
def test_supply_freeze_rejects_cross_block_mutations(field):
    a=SyntheticAdapter(synthetic_config());b=a.snapshot();after=copy.deepcopy(b);after[field]='tampered'
    with pytest.raises(SupplyContractError):assert_freeze(b,after,'SUPPLY_ADDVAL1')


def test_demand_rejects_addval_mutation():
    a=SyntheticAdapter(synthetic_config());b=a.snapshot();after=copy.deepcopy(b);after['addval1']['1|1|2']=1.
    with pytest.raises(SupplyContractError,match='DEMAND_MUTATED'):assert_freeze(b,after,'GENERATION')


def test_shared_ledger_does_not_use_validation_targets():
    cfg=synthetic_config();a=SyntheticAdapter(cfg);d=a.diagnostics(None);st=a.snapshot();ref=build_reference(d,cfg)
    l1=ledger(d,st,st['addval1'],SupplyPolicy(),ref,cfg)
    changed=copy.deepcopy(d);changed['d12']['rows'][1]['observed']=999999.
    changed['d12']['rows'][1]['model']=3.
    ref2=build_reference(changed,cfg)
    l2=ledger(changed,st,st['addval1'],SupplyPolicy(),ref2,cfg)
    assert l1['total']==l2['total'] and l1['terms']==l2['terms']


def test_target_change_cannot_improve_objective_by_redefinition():
    cfg=synthetic_config();a=SyntheticAdapter(cfg);d=a.diagnostics(None);ref=build_reference(d,cfg);st=a.snapshot()
    d['signals']['WORK_E_C']['model_bins'][0]['target_share']=.9
    with pytest.raises(SupplyContractError,match='TARGET_CHANGED'):ledger(d,st,st['addval1'],SupplyPolicy(),ref,cfg)


def test_stop_request_checked_at_safe_boundary(tmp_path):
    cfg=synthetic_config();a=SyntheticAdapter(cfg);(tmp_path/'STOP_REQUESTED').touch()
    r=run_calibration(a,cfg,tmp_path)
    assert r['status']=='SAFE_STOP_AT_BLOCK_BOUNDARY' and r['accepted_count']==0
    assert (tmp_path/'ACCEPTED_STATE.json').exists()


def test_unknown_block_is_not_silently_skipped(tmp_path):
    cfg=synthetic_config();cfg['block_schedule']=['UNKNOWN'];a=SyntheticAdapter(cfg)
    r=run_calibration(a,cfg,tmp_path)
    assert r['status']=='BLOCKED_OR_FAILED' and 'INVALID_BLOCK_SCHEDULE' in r['error']


def test_component_objective_weights_stay_at_initial_reference():
    cfg=synthetic_config();a=SyntheticAdapter(cfg);d=a.diagnostics(None);ref=build_reference(d,cfg);state=a.snapshot()
    first=ledger(d,state,state['addval1'],SupplyPolicy(),ref,cfg)
    d['signals']['WORK_E_C']['conditioned_volume']=9999999
    second=ledger(d,state,state['addval1'],SupplyPolicy(),ref,cfg)
    assert first['total']==second['total']


def test_tampered_accepted_pointer_blocks_resume(tmp_path):
    cfg=synthetic_config();cfg['max_accepted_blocks']=1;a=SyntheticAdapter(cfg)
    first=tmp_path/'first';run_calibration(a,cfg,first)
    path=first/'ACCEPTED_STATE.json';record=json.loads(path.read_text());record['original_addval_anchors']['1|1|2']=99
    path.write_text(json.dumps(record))
    b=SyntheticAdapter(cfg);r=run_calibration(b,cfg,tmp_path/'second',resume_from=first)
    assert r['status']=='BLOCKED_OR_FAILED' and 'RECOVERY_AUTHORITY_MISMATCH' in r['error']
    assert not b.assignments


def test_empty_validation_objective_does_not_veto_calibration(tmp_path):
    class EmptyValidation(SyntheticAdapter):
        def diagnostics(self,folder,label='CURRENT'):
            d=super().diagnostics(folder,label)
            d['d12']['rows'][1]['observed']=0.
            return d
    cfg=synthetic_config();cfg['max_accepted_blocks']=1
    a=EmptyValidation(cfg);result=run_calibration(a,cfg,tmp_path)
    assert result['accepted_count']==1,result
    data=json.loads((tmp_path/'RUN_STATUS.json').read_text())
    report=data['blocks'][0]['attempts'][0]['decision']['validation_before_report_only']
    assert report['n']==0 and report['objective_geh2_mean'] is None


def test_v22_entrypoint_config_is_dry_run_and_binds_source_identity():
    import R1_15A2_SUPPLY_DEMAND_MASTER_V2_2 as entry
    cfg=entry.load_config()
    assert cfg['apply'] is False
    assert len(cfg['implementation_hash'])==64
    assert cfg['supply']['equivalent_seconds_per_addval1']==10
    assert cfg['supply']['assignment_operations']==[]

"""GENFIX2 safety regressions: real byte-bound proofs and final mutation path."""
import copy
import json
import math
import zipfile
from pathlib import Path
from types import SimpleNamespace as NS

import numpy as np
import pytest

import r1_15a2_parent_equivalence_v24917 as eq
import r1_15a2_mobility_guard_v24917 as mg
import r1_15a2_step_search_v24917 as step
import r1_15a2_rollback_consistency_v24917 as rb
import r1_15a2_td_rollback_tolerant_v24917 as tr
import r1_15a2_supply_mix_v24917 as sm
from r1_15a2_supply import canonical_hash, SupplyContractError
from test_v24917_supply_mix import harness as supply_harness, _no_g1b, OPTS as SUPPLY_OPTS
from test_v24917_step_search import harness as generation_harness, OPTS as STEP_OPTS

MGO = {"enabled": True, "lo": .75, "hi": 1.25}


def diagnostics(model=1000.):
    return {"d12": {"rows": [{"countlocation_no": "1", "role": "CALIBRATION", "observed": 1200.,
                              "model": model, "profile_weight": 1.}]},
            "d11": {"summary": {"component_dist_summary_rows": [{"component": "WORK", "mean": 10.}],
                                  "created_at": "T1", "outputs": {"summary": "C:/old/summary.json"}}},
            "signals": {"WORK": {"cdf_rmse": .12}}}


class ArrayAdapter:
    def __init__(self):
        self.a = np.array([[50., 1.], [2., 47.]], dtype='<f8')
        self.zones = [1, 2]
        self.order = [1, 2]
        self.com_retry_policy = {"enabled": True, "max_attempts": 2, "initial_delay_seconds": 0.}
        mat = NS(GetValues=lambda: self.a.copy())
        zone = NS(GetMultiAttValues=lambda *args: list(enumerate(self.order, 1)))
        self.visum = NS(Net=NS(Matrices=NS(ItemByKey=lambda n: mat), Zones=zone))
        self.diag = diagnostics()

    def snapshot(self):
        row = {"matrix_no": 9101, "rows": 2, "cols": 2, "sha256_float64_le": eq._array_hash(self.a)}
        out = {"matrices": [row], "matrix_hash": canonical_hash([row]), "addval1": {},
               "generation_values": {"ADD_PROD_W": {"1": 1., "2": 1.}},
               "td_values": [{"component": "WORK", "current_b": .1, "current_c": -.1}],
               "fixed_link_hash": "L", "dseg_hash": "D", "operations_hash": "O"}
        return dict(out, state_hash=canonical_hash(out))

    def diagnostics(self, *args):
        return copy.deepcopy(self.diag)


def test_disk_proof_accepts_bounded_roundoff_and_removes_successful_temp(tmp_path):
    ad = ArrayAdapter(); before = ad.snapshot()
    with eq.parent_scope(ad, before, tmp_path) as proof:
        directory = Path(proof['directory'])
        assert directory.is_dir() and proof['status'] == 'CAPTURED_BEFORE_MUTATION'
        ad.a += 1e-10
        check = eq.verify_parent(ad, before, ad.snapshot(), diagnostics(), diagnostics())
        assert check['passes'] and check['matrix_proof']['mode'] == 'BYTE_BOUND_NUMERIC_MATRIX_PROOF'
    assert not directory.exists() and ad._genfix2_parent_proof is None


@pytest.mark.parametrize('change', ['swap', 'nan', 'negative', 'axis', 'corrupt_proof'])
def test_disk_proof_refuses_material_invalid_or_unbound_matrix(change, tmp_path):
    ad = ArrayAdapter(); before = ad.snapshot()
    with eq.parent_scope(ad, before, tmp_path) as proof:
        if change == 'swap': ad.a = ad.a[:, ::-1].copy()
        elif change == 'nan': ad.a[0, 0] = np.nan
        elif change == 'negative': ad.a[0, 0] = -1.
        elif change == 'axis': ad.order = [2, 1]
        elif change == 'corrupt_proof':
            Path(proof['matrices'][9101]['path']).write_bytes(b'NOT_NPY'); ad.a += 1e-10
        after = ad.snapshot()
        assert not eq.compare_matrices(ad, before, after)['passes']


def test_changed_bytes_without_capture_never_pass(tmp_path):
    ad=ArrayAdapter(); before=ad.snapshot(); ad.a+=1e-10
    assert not eq.compare_matrices(ad, before, ad.snapshot())['passes']


def test_parent_proof_capture_is_checked_before_first_mutation(tmp_path):
    ad=ArrayAdapter(); before=ad.snapshot(); ad.a[0, 0]+=1
    with pytest.raises(Exception, match='PARENT_MATRIX_SNAPSHOT_MISMATCH'):
        with eq.parent_scope(ad, before, tmp_path):
            pytest.fail('mutation scope opened for stale parent')


def test_failed_scope_retains_original_matrix_evidence(tmp_path):
    ad=ArrayAdapter(); before=ad.snapshot()
    with pytest.raises(KeyboardInterrupt):
        with eq.parent_scope(ad, before, tmp_path) as proof:
            directory=Path(proof['directory'])
            raise KeyboardInterrupt()
    assert directory.exists()
    assert json.loads((tmp_path/'GENFIX2_PARENT_PROOF_RETAINED.json').read_text())['identity']==canonical_hash(before)
    import shutil; shutil.rmtree(directory)


@pytest.mark.parametrize('change', ['signal', '11d', 'duplicate', 'observed', 'weight', 'role', 'missing', 'nonfinite', 'outputs'])
def test_full_diagnostic_proof_rejects_changed_authority_or_metrics(change):
    b=diagnostics(); a=copy.deepcopy(b)
    if change=='signal': a['signals']['WORK']['cdf_rmse']=2.
    elif change=='11d': a['d11']['summary']['component_dist_summary_rows'][0]['mean']=20.
    elif change=='duplicate':
        a['d12']['rows']*=2; b['d12']['rows']*=2
    elif change=='observed': a['d12']['rows'][0]['observed']=1300.
    elif change=='weight': a['d12']['rows'][0]['profile_weight']=2.
    elif change=='role': a['d12']['rows'][0]['role']='VALIDATION'
    elif change=='missing': del a['d11']
    elif change=='nonfinite': a['signals']['WORK']['cdf_rmse']=float('nan')
    elif change=='outputs': a['d11']['summary']['outputs']['extra']='C:/extra.csv'
    assert not eq.compare_diagnostics(b,a)['passes']


def test_11d_transport_paths_differ_but_metrics_are_proven_equal():
    b=diagnostics(); a=copy.deepcopy(b)
    a['d11']['summary']['created_at']='T2'
    a['d11']['summary']['outputs']['summary']='C:/new/summary.json'
    assert eq.compare_diagnostics(b,a)['passes']


def test_exact_legacy_hash_does_not_waive_11d_check(tmp_path):
    ad=ArrayAdapter(); before=ad.snapshot(); baseline=diagnostics()
    ad.diag['d11']['summary']['component_dist_summary_rows'][0]['mean']=20.
    original=lambda *args, **kwargs: ({'passes':True}, copy.deepcopy(ad.diag))
    wrapped=rb.wrap_rollback_and_verify(original,lambda *args:None)
    with pytest.raises(Exception,match='FULL_PARENT_PROOF_FAILED'):
        wrapped(ad,'GENERATION',before,'IGNORES_11D',lambda d:'IGNORES_11D',tmp_path,baseline_diag=baseline)


def test_exact_td_return_does_not_waive_component_check(tmp_path):
    ad=ArrayAdapter(); state=ad.snapshot(); baseline=diagnostics()
    ad.diag['signals']['WORK']['cdf_rmse']=2.
    ctrl=NS(_td_expected_freeze=lambda *args:None, atomic_json=lambda *args:None)
    wrapped=tr.wrap_rollback_td_all(lambda *args:(ad.snapshot(),copy.deepcopy(ad.diag)),ctrl)
    with pytest.raises(Exception,match='FULL_PARENT_PROOF_FAILED'):
        wrapped(ad,state,baseline,tmp_path,{})


def zones(c=1.):
    result=[]
    for z in (1,2):
        row={'zone_no':z,'NOT_ZAHR':1.,'ADD_PROD_W':c,'ADD_PROD_S':1.}
        for fam,attr in mg.MULT_ATTR.items():
            for fp in mg.FP_ATTRS[fam]: row[fp]=float(z*10)*row[attr]
        result.append(row)
    return result


@pytest.mark.parametrize('seed',range(8))
def test_mixed_sign_guard_envelope_over_dense_scale_grid(seed):
    rng=np.random.default_rng(seed); zr=zones(.75+seed*.5/7)
    rows=[{'zone_no':z,'family':'WORK','role':'PROD','log_step':rng.uniform(-.22,.405),'base_margin_volume':100.} for z in (1,2)]
    out,rep=mg.guard(rows,zr,MGO)
    prod=mg.zone_productions(zr,'WORK'); steps={r['zone_no']:r['log_step'] for r in out}
    vals=[mg.ratio(prod,{z:t*s for z,s in steps.items()}) for t in np.linspace(0,1,201)]
    assert rep['passes'] and min(vals)>=.75-1e-11 and max(vals)<=1.25+1e-11


@pytest.mark.parametrize('change',['missing','negative','nan','duplicate'])
def test_required_mobility_data_fail_closed(change):
    zr=zones()
    if change=='missing': del zr[0][mg.FP_ATTRS['WORK'][0]]
    elif change=='negative': zr[0][mg.FP_ATTRS['WORK'][0]]=-1.
    elif change=='nan': zr[0][mg.FP_ATTRS['WORK'][0]]=float('nan')
    elif change=='duplicate': zr.append(copy.deepcopy(zr[0]))
    with pytest.raises((ValueError,KeyError)):
        mg.guard([],zr,MGO)


def test_final_candidate_after_rebalance_rejected():
    zr=zones(1.25)
    rows=[{'zone_no':1,'attr':'ADD_PROD_W','current':1.25,'proposed':1.3}]
    assert not mg.check_candidate(rows,zr,MGO)['passes']


def test_live_fp_recompute_checked_against_fixed_reference():
    old=zones(1.2); new=zones(1.3)
    assert not mg.check_live(old,new,MGO)['passes']
    ok=zones(1.21)
    assert mg.check_live(old,ok,MGO)['passes']
    ok[0][mg.FP_ATTRS['WORK'][0]]+=1.
    with pytest.raises(ValueError,match='REFERENCE'):
        mg.check_live(old,ok,MGO)


def test_final_prediction_uses_implemented_effects_instead_of_raw_fit():
    import r1_15a2_trial_adapter_v24917 as a17
    ad=a17.VisumAdapter.__new__(a17.VisumAdapter)
    problem=NS(G=np.array([[100.,200.]]),var_keys=[('WORK','PROD',1),('WORK','ATT',1)],
               profile_rows=[{'countlocation_no':'1'}])
    ctx={'_genfix2_effect_model':{'problem':problem}}
    design={'effect_rows':[{'family':'WORK','role':'PROD','zone_no':1,'implemented_total_log_effect':.01},
                           {'family':'WORK','role':'ATT','zone_no':1,'implemented_total_log_effect':-.002}]}
    rec=ad._final_step_prediction(ctx,design,.5)
    assert rec['available'] and rec['delta']==pytest.approx([.6])
    design['effect_rows']=[]
    assert ad._final_step_prediction(ctx,design,.5)['delta']==[0.]


def test_actual_apply_checks_fresh_plan_before_any_mutation(monkeypatch,tmp_path):
    import r1_15a2_trial_adapter_v24917 as a17
    import r1_15a2_supply_visum as sv
    import r1_15a2_core as core
    ad=a17.VisumAdapter.__new__(a17.VisumAdapter)
    ad.cfg={};ad.visum=None;ad.zones=[1,2];ad.zone_write_index_by_no={}
    ad.com_retry_policy={};ad.generation_reference_values=None
    old=zones(); fresh=copy.deepcopy(old); writes=[]
    def design(projection,zr,cfg,scale,**kw):
        c=zr[0]['ADD_PROD_W']
        return {'candidate_rows':[{'zone_no':1,'attr':'ADD_PROD_W','current':c,'proposed':c*math.exp(.02*scale)}],
                'effect_rows':[],'summary':{}}
    monkeypatch.setattr(a17.mb,'design_generation_candidates',design)
    monkeypatch.setattr(sv.base,'zone_state_rows',lambda *args,**kw:(fresh,[]))
    def original_apply(self,context,scale,folder):
        planned=sv.base.generation_candidate(self.visum,self.zones,context['projection'],self.cfg,scale)
        writes.extend(planned['candidate_rows'])
        return planned['candidate_rows']
    monkeypatch.setattr(a17._V24916ActiveAdapter,'apply_generation',original_apply)
    context={'projection':core.ProjectionResult(rows=[],family_summaries=[],weighted_rmse=0.),
             '_genfix2_mobility':{'zone_rows':old,'options':MGO,'zone_attributes':[]}}
    before_hook=sv.base.generation_candidate
    assert ad.apply_generation(context,.5,tmp_path) and len(writes)==1
    writes.clear(); fresh[0]['ADD_PROD_W']=1.01
    with pytest.raises(Exception,match='STALE|PLAN_CHANGED'):
        ad.apply_generation(context,.5,tmp_path)
    assert not writes and sv.base.generation_candidate is before_hook


def test_supply_bad_full_recovery_is_explicit_failure_without_acceptance(supply_harness,monkeypatch):
    h=supply_harness(shift=60.); _no_g1b(h,monkeypatch)
    monkeypatch.setattr(h.ad,'block_gate',lambda *args:{'accepted':False,'reasons':['TEST_REJECT']})
    def bad_rollback(*args,**kwargs): raise RuntimeError('INPLACE_ROLLBACK_DIAGNOSTICS_DIFFER')
    monkeypatch.setattr(h.base,'_rollback_candidate',bad_rollback)
    original=h.ad.assign_for_block
    def recompute(folder,block):
        if 'RECOVERY_FULL_RECOMPUTE' in str(folder):
            h.ad.rows0=[dict(r,model=r['model']*10) for r in h.ad.rows0]
        return original(folder,block)
    monkeypatch.setattr(h.ad,'assign_for_block',recompute)
    with pytest.raises(Exception,match='RECOVERY_NOT_EQUIVALENT_MANUAL_REOPEN'):
        h.run(opts=dict(SUPPLY_OPTS,max_trials=1))
    assert not h.ad.kept


def test_supply_keyboard_interrupt_restores_real_assignment(supply_harness,monkeypatch):
    h=supply_harness(shift=60.); _no_g1b(h,monkeypatch)
    original=h.ad.assign_for_block; called=[]
    def interrupt(folder,block):
        called.append(1); val=original(folder,block)
        if len(called)==1: raise KeyboardInterrupt()
        return val
    monkeypatch.setattr(h.ad,'assign_for_block',interrupt)
    with pytest.raises(KeyboardInterrupt): h.run()
    assert h.ad.snapshot()==h.state and h.ad.vol==h.ad.addval and len(called)>=2
    assert not h.ad.kept


def test_verified_parent_rebind_is_not_an_accepted_change():
    ad=NS(cache=object(),cache_snapshot={'fixed_link_hash':'F','dseg_hash':'D','operations_hash':'O'},
          cache_links={(1,2):{'addval1':10.}},path_epoch_accepts=7)
    state=dict(ad.cache_snapshot,addval1={'1|2':2.})
    out=eq.rebind_verified_parent(ad,state,diagnostics())
    assert out['retained'] and not out['accepted_change']
    assert ad.path_epoch_accepts==7 and ad.cache_live_snapshot==state
    assert ad.cache_links[(1,2)]['addval1']==2.


def test_archive_incomplete_zip_keeps_both_original_files(tmp_path):
    import r1_15a2_perf_v24917 as perf
    hold=tmp_path/'hold';hold.mkdir();(hold/'a.txt').write_text('a');(hold/'b.txt').write_text('b')
    def incomplete(source,target):
        with zipfile.ZipFile(target,'w') as archive: archive.write(source/'a.txt','a.txt')
    perf._finalize(NS(pending=[(hold,tmp_path/'out.zip',incomplete)]),True)
    assert (hold/'a.txt').exists() and (hold/'b.txt').exists() and not (tmp_path/'out.zip').exists()


def test_matrix_shape_must_match_the_live_zone_axis(tmp_path):
    ad=ArrayAdapter(); ad.zones=[1,2,3]; ad.order=[1,2,3]
    with pytest.raises(Exception,match='PARENT_MATRIX_INVALID'):
        eq.capture(ad,ad.snapshot())


def test_generation_flag_false_cannot_start_stationary_streak():
    import r1_15a2_demand_policy_v1 as dp
    obj=dp.DemandPolicy(dp.load_options())
    obj.note_generation(False,{'search_complete':True,'stationarity_confirmed':False})
    obj.note_td(1,True,False,{'inner':{'search_complete':True}})
    assert obj.streak==0 and not obj.last_generation_complete


def test_supply_failure_clears_outer_policy_stationarity(monkeypatch):
    import r1_15a2_demand_policy_v1 as dp
    policy=NS(last_generation_complete=True)
    monkeypatch.setattr(dp,'_ACTIVE',{'test':{'policy':policy}})
    monkeypatch.setattr(sm,'options',lambda:dict(SUPPLY_OPTS))
    monkeypatch.setattr(sm,'due',lambda *args:(True,'TEST'))
    monkeypatch.setattr(sm,'supply_block',lambda *args:(False,{}, {}, {}, {'search_complete':False}))
    wrapped=sm._wrap_generation(lambda *args,**kwargs:(False,{}, {}, {},
                                {'search_complete':True,'stationarity_confirmed':True}),NS(),NS(),NS())
    result=wrapped(None,{},'x',None,{}, {},None,None,None,outer_cycle=3)
    assert not result[4]['search_complete'] and not result[4]['stationarity_confirmed']
    assert not policy.last_generation_complete


def test_recovery_resets_speculative_epoch_acceptance_counter():
    ad=NS(cache=None,path_epoch_accepts=8,_genfix2_parent_proof={'path_epoch_accepts_before':7})
    eq.rebind_verified_parent(ad,{},diagnostics())
    assert ad.path_epoch_accepts==7

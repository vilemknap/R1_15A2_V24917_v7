"""Audit-only adversarial tests. These assert required safety properties, not bug behaviour.
Run independently from packaged suites; PYTHONPATH must include the original root and tests/.
The delivered source archive is never modified.
"""
import copy
import json
import math
import os
import hashlib
from pathlib import Path
from types import SimpleNamespace
from contextlib import nullcontext

import numpy as np
import pytest
import r1_15a2_mobility_guard_v24917 as mg
import r1_15a2_boundary_pa_v24917 as bdpa
import r1_15a2_td_rollback_tolerant_v24917 as tr
import r1_15a2_rollback_consistency_v24917 as rb
import r1_15a2_supply_mix_v24917 as sm
from test_v24917_supply_mix import harness as supply_harness, _no_g1b, OPTS
from test_v24917_td_rollback_tolerant import rows as profile_rows, snap, ctrl, Ad

OPTS_MG = {'enabled': True, 'lo': 0.75, 'hi': 1.25}
EVIDENCE = Path(os.environ.get('R1_AUDIT_EVIDENCE', str(Path(__file__).resolve().parents[1] / 'evidence')))
EVIDENCE.mkdir(parents=True, exist_ok=True)

def record(name, value):
    (EVIDENCE / (name + '.json')).write_text(json.dumps(value, indent=2, default=str, allow_nan=True), encoding='utf-8')

def zones(c=1.25):
    result=[]
    for z,p in [(1,100.),(2,250.)]:
        row={'zone_no':z,'NOT_ZAHR':1.,'ADD_PROD_W':c,'ADD_PROD_S':1.}
        for g in mg.GROUPS:
            row['FP_1_WORK_'+g]=p/5
            row['FP_2_SERVICE_'+g]=20.
        result.append(row)
    return result

def proposal(bases=(100.,250.)):
    return [{'zone_no':z,'family':'WORK','role':'PROD','log_step':math.log(mult),
             'base_margin_volume':b} for z,mult,b in [(1,1.5,bases[0]),(2,0.8,bases[1])]]

def test_A01_mobility_smaller_step_must_stay_in_band():
    zr=zones(.755)
    out,rep=mg.guard(proposal(),zr,OPTS_MG)
    prod=mg.zone_productions(zr,'WORK')
    steps={r['zone_no']:r['log_step'] for r in out}
    values={str(s):mg.ratio(prod,{z:s*v for z,v in steps.items()}) for s in [0.,.25,.5,.75,1.]}
    record('A01_smaller_step',{'report':rep,'ratios':values,'allowed_band':[.75,1.25]})
    assert all(.75-1e-12 <= r <= 1.25+1e-12 for r in values.values()),values

def test_A02_pa_rebalance_must_preserve_mobility_limit():
    zr=zones(1.25)
    out,rep=mg.guard(proposal((50.,250.)),zr,OPTS_MG)
    for r in out:r['requested_log_step']=r['log_step']
    bal=bdpa.subset_rebalance(out,{'WORK':{'prod':10.,'att':10.}})
    r_after=mg.ratio(mg.zone_productions(zr,'WORK'),{r['zone_no']:r['requested_log_step'] for r in out})
    record('A02_rebalance_bypasses_mobility',{'before_guard':rep,'balance':bal,'ratio_after_rebalance':r_after})
    assert r_after <= 1.25+1e-12

def test_A03_mobility_empty_coverage_must_not_be_OK():
    out,rep=mg.guard(proposal(),[dict(z,NOT_ZAHR=0.) for z in zones()],OPTS_MG)
    record('A03_missing_coverage',rep)
    assert rep['status'] != 'OK' or all(math.isfinite(r['ratio_current']) and r['zones']>0 for r in rep['families'].values())

def test_A04_generation_tolerant_rollback_must_check_11d():
    before={'d12':{'rows':profile_rows()},'d11':{'summary':{'component_rmse':.1}},'signals':{'WORK':{'objective':.1}}}
    after=copy.deepcopy(before)
    after['d11']['summary']['component_rmse']=10.
    after['signals']['WORK']['objective']=10.
    result=rb.tolerant_compare(before,after)
    record('A04_11d_ignored',{'before':before['d11'],'after':after['d11'],'comparison':result})
    assert result['passes'] is False

def real_td_controller():
    import r1_15a2_overnight_controller_coupled_v24915p2_force100 as fc
    return SimpleNamespace(_td_expected_freeze=fc._td_expected_freeze, atomic_json=fc.atomic_json)

def test_A05_td_rollback_must_limit_matrix_drift(tmp_path):
    before=snap();after=snap(mat='DIFFERENT')
    for state in [before,after]:state['td_values'][0]['current_c']=-.1
    before_array=np.array([[50.,0.],[0.,50.]])
    after_array=np.array([[0.,50.],[50.,0.]])
    for state,arr in [(before,before_array),(after,after_array)]:
        sha=hashlib.sha256(arr.astype('<f8').tobytes()).hexdigest()
        state['matrices']=[{'matrix_no':9101,'rows':2,'cols':2,'sha256_float64_le':sha}]
        state['matrix_hash']=sha
    c=real_td_controller();ad=Ad(after,profile_rows())
    result=tr.tolerant_check(c,ad,before,{'d12':{'rows':profile_rows()}},tmp_path,{})
    record('A05_unbounded_matrix_drift', {**{k:v for k,v in result.items() if not k.startswith('_')},
        'before_matrix':before_array.tolist(),'after_matrix':after_array.tolist(),
        'max_cell_difference':float(abs(after_array-before_array).max()),
        'l1_matrix_difference':float(abs(after_array-before_array).sum()),
        'real_td_expected_freeze_used':True})
    assert result['status'] != 'PARAMETER_EXACT_NUMERICALLY_EQUIVALENT_RECOMPUTE'

def test_A06_td_rollback_must_check_11d(tmp_path):
    before=snap();after=snap(mat='DIFFERENT')
    for state in [before,after]:state['td_values'][0]['current_c']=-.1
    baseline={'d12':{'rows':profile_rows()},'d11':{'summary':{'error':.1}},'signals':{'WORK':{'objective':.1}}}
    class With11D(Ad):
        def diagnostics(self,folder,label):
            return {'d12':{'rows':self.rows},'d11':{'summary':{'error':100.}},'signals':{'WORK':{'objective':100.}}}
    result=tr.tolerant_check(real_td_controller(),With11D(after,profile_rows()),before,baseline,tmp_path,{})
    record('A06_td_11d_ignored',{k:v for k,v in result.items() if not k.startswith('_')})
    assert result['status'] != 'PARAMETER_EXACT_NUMERICALLY_EQUIVALENT_RECOMPUTE'

def test_A07_duplicate_profiles_must_not_mask_load_drift():
    before=profile_rows();after=copy.deepcopy(before)
    before[0:0]=[dict(before[0],model=500.),dict(before[1],model=500000.)]
    after[0:0]=[dict(after[0],model=500000.),dict(after[1],model=500.)]
    result=tr.profile_drift(before,after)
    combined=rb.tolerant_compare({'d12':{'rows':before}},{'d12':{'rows':after}})
    record('A07_duplicate_profiles',{'profile_drift':result,'combined_tolerant_comparison':combined,
          'changed_duplicate_volumes':[500.,500000.], 'same_overall_volume_multiset':True})
    assert combined['passes'] is False

def test_A08_supply_second_trial_prewrite_error_must_recompute_parent(supply_harness,monkeypatch):
    h=supply_harness(shift=350.)
    _no_g1b(h,monkeypatch)
    def begin(*a,**k):
        if h.ad.assignments: raise RuntimeError('AUDIT_SECOND_READBACK_CONTEXT_FAILURE')
    monkeypatch.setattr(h.ad,'begin_candidate_readback_context',begin,raising=False)
    result=h.run()
    record('A08_supply_dirty_assignment',{'status':result[4]['status'],'returned_parent':result[1]==h.state,
           'parameter_restored':h.ad.addval==h.state['addval1'],'loads_restored':h.ad.vol==h.state['addval1'],
           'live_assignment':h.ad.vol,'parent':h.state['addval1'],'assignments':h.ad.assignments})
    assert h.ad.vol==h.state['addval1']

def test_A09_supply_result_io_failure_must_rollback(supply_harness,monkeypatch):
    h=supply_harness(shift=60.);_no_g1b(h,monkeypatch)
    original=h.base.atomic_json
    def write(path,payload):
        if Path(path).name=='SUPPLYMIX_BLOCK_RESULT.json' and h.ad.assignments:
            raise OSError('AUDIT_SIMULATED_DISK_FULL')
        return original(path,payload)
    monkeypatch.setattr(h.base,'atomic_json',write)
    with pytest.raises(OSError,match='AUDIT_SIMULATED_DISK_FULL'):h.run()
    record('A09_supply_io_escapes_rollback',{'parameters_restored':h.ad.addval==h.state['addval1'],
           'loads_restored':h.ad.vol==h.state['addval1'],'assignments':h.ad.assignments})
    assert h.ad.addval==h.state['addval1'] and h.ad.vol==h.state['addval1']

def test_A10_supply_recovery_must_not_adopt_materially_worse_state(supply_harness,monkeypatch):
    h=supply_harness(shift=60.);_no_g1b(h,monkeypatch)
    monkeypatch.setattr(h.ad,'block_gate',lambda *a,**k:{'accepted':False,'reasons':['AUDIT_FORCE_REJECT']})
    def rb_failure(*a,**k):raise RuntimeError('INPLACE_ROLLBACK_DIAGNOSTICS_DIFFER')
    monkeypatch.setattr(h.base,'_rollback_candidate',rb_failure)
    orig=h.ad.assign_for_block
    def recompute(folder,block):
        if 'RECOVERY_FULL_RECOMPUTE' in str(folder):
            h.ad.rows0=[dict(r,model=r['model']*10) for r in h.ad.rows0]
        return orig(folder,block)
    monkeypatch.setattr(h.ad,'assign_for_block',recompute)
    with pytest.raises(Exception, match='RECOVERY_NOT_EQUIVALENT_MANUAL_REOPEN'):
        h.run(opts=dict(OPTS,max_trials=1))
    assert not h.ad.kept, 'Recovery must not call candidate acceptance'
    record('A10_supply_recovery_closed', {'status':'EXPLICIT_MANUAL_REOPEN_FAILURE',
           'accepted_transitions':h.ad.kept,'accepted_change':False})


def test_control_mobility_pure_positive_step_is_limited():
    out,rep=mg.guard([dict(r,log_step=math.log(1.5)) for r in proposal()],zones(1.25),OPTS_MG)
    assert rep['families']['WORK']['ratio_after'] <= 1.25+1e-12

def test_control_supply_normal_rejection_rolls_back(supply_harness,monkeypatch):
    h=supply_harness(shift=-60.);_no_g1b(h,monkeypatch)
    result=h.run()
    assert not result[0] and h.ad.addval==h.state['addval1'] and h.ad.vol==h.state['addval1']


def _design_fixture(monkeypatch, *, fit_raises=False, missing_fp=False):
    import r1_15a2_trial_adapter_v24917 as admod
    ad=object.__new__(admod.VisumAdapter)
    ad.cfg={admod.tg.POLICY_KEY:copy.deepcopy(admod.tg.DEFAULT_POLICY)}
    ad.visum=object();ad.zones=[1,2];ad.zone_write_index_by_no={1:1,2:2}
    ad.com_retry_policy={};ad.generation_reference_values={};ad.v24917_ls={'active':False}
    ad.v24917_status={'designs':0,'fit_fallbacks':0}
    parent_rows=[dict(r,log_step=math.log(1.5)) for r in proposal()]
    context={'incidence':object(),'projection':admod.core.ProjectionResult(rows=copy.deepcopy(parent_rows),
               family_summaries=[{'converged':True}],weighted_rmse=0.)}
    monkeypatch.setattr(admod._V24916ActiveAdapter,'generation_design',lambda *a:context)
    zr=zones(2.0)
    if missing_fp: zr[0].pop('FP_1_WORK_E_C')
    monkeypatch.setattr(admod.supply_visum.base,'zone_state_rows',lambda *a,**k:(zr,[]))
    monkeypatch.setattr(admod.tg,'zone_bounds',lambda *a,**k:{})
    def fit(*a,**k):
        if fit_raises:raise RuntimeError('AUDIT_FIT_FAILURE')
        summary={'zones_changed':2,'rows':2,'rows_at_upper':2,'linear_prediction':{'ratio_after':1.}}
        problem=SimpleNamespace(profile_rows=[{'countlocation_no':'900001'}])
        solution={'converged':True,'objective_initial':2.,'objective_final':1.,'iterations':3,
                  'predicted_change':np.array([100.])}
        return copy.deepcopy(parent_rows),summary,problem,solution,None
    monkeypatch.setattr(ad,'_fit_with_boundary',fit)
    diag={'d12':{'rows':[{'role':'CALIBRATION','model':60.,'observed':100.}]}}
    return ad,diag,context,zr


def test_A11_enabled_mobility_guard_error_must_block_candidate(monkeypatch,tmp_path):
    ad,diag,context,zr=_design_fixture(monkeypatch,missing_fp=True)
    result=ad.generation_design(diag,tmp_path)
    record('A11_guard_error_fails_open',{'v24917':result['v24917'],'candidate_rows':result['projection'].rows})
    assert not result['projection'].rows


def test_A12_parent_fallback_must_also_enforce_mobility(monkeypatch,tmp_path):
    ad,diag,context,zr=_design_fixture(monkeypatch,fit_raises=True)
    result=ad.generation_design(diag,tmp_path)
    r_after=mg.ratio(mg.zone_productions(zr,'WORK'),{r['zone_no']:r['log_step'] for r in result['projection'].rows})
    record('A12_fallback_bypasses_mobility',{'v24917':result['v24917'],'ratio_of_returned_proposal':r_after})
    # Universal fresh WORK/SERVICE mobility ceiling is 2.5, including fallback.
    assert r_after <= 2.5+1e-12


def test_A13_step_prediction_must_describe_guarded_candidate(monkeypatch,tmp_path):
    ad,diag,context,zr=_design_fixture(monkeypatch)
    result=ad.generation_design(diag,tmp_path)
    max_step=max(abs(r['log_step']) for r in result['projection'].rows)
    delta=result['v24917_step_model']['delta_full']
    record('A13_stale_prediction',{'max_final_projection_log_step':max_step,
        'step_model':result['v24917_step_model'],'guard':result['v24917']['mobility_guard']})
    assert max_step>1e-9 or all(abs(v)<1e-9 for v in delta)


def test_A14_transient_countmodel_link_failure_must_not_be_cached_as_missing():
    import r1_15a2_td_count_blend_v24917 as cb
    class Busy(Exception):hresult=-2147418111
    link=object();calls=[]
    def getlink(*args):
        calls.append(args)
        if len(calls)==1:raise Busy('AUDIT_RPC_E_CALL_REJECTED')
        return link
    model=object.__new__(cb.CountModel)
    model.v=SimpleNamespace(Net=SimpleNamespace(Links=SimpleNamespace(ItemByKey=getlink)))
    model._links={}
    first=model._link(1,2)
    second=model._link(1,2)
    record('A14_transient_link_cache',{'first_was_none':first is None,'second_was_none':second is None,
           'com_call_count':len(calls),'cached_as_missing':model._links.get((1,2)) is None})
    assert second is link


def test_A15_failed_forensic_archive_must_keep_source_evidence(tmp_path):
    import r1_15a2_perf_v24917 as perf
    hold=tmp_path/'hold';hold.mkdir();(hold/'trace.txt').write_text('last evidence')
    def broken_archive(*args):raise OSError('AUDIT_ARCHIVE_DISK_FULL')
    d=perf._Deferred();d.pending.append((hold,tmp_path/'evidence.zip',broken_archive))
    perf._finalize(d,keep=True)
    record('A15_lost_forensic_evidence',{'hold_exists':hold.exists(),'archive_exists':(tmp_path/'evidence.zip').exists()})
    assert (hold/'trace.txt').is_file() or (tmp_path/'evidence.zip').is_file()


def test_control_td_local_degradation_can_accumulate(monkeypatch):
    """Policy observation, not a test that claims a global bound is implemented."""
    import r1_15a2_td_count_blend_v24917 as cb
    import r1_15a2_core as core
    import r1_15a2_multiblock as mb
    monkeypatch.setattr(cb,'options',lambda:{'w_cnt':.65,'w_idp':.35,'max_idp_ratio':1.25})
    monkeypatch.setattr(core,'csd_metrics',lambda rows,*a,**k:{'objective_geh_mean_weighted':rows[0]['test_metric']})
    monkeypatch.setattr(mb,'td_component_metrics',lambda signals,*a,**k:{'weighted_objective':signals['X']['test_metric']})
    def diag(c,i):return {'d12':{'rows':[{'test_metric':c}]},'signals':{'X':{'test_metric':i}}}
    before=diag(1.,1.);events=[]
    for k in range(1,4):
        after=diag(.7**k,1.2**k)
        result=cb.outer_decision({'accepted':False,'reasons':['GLOBAL_IDP_MEAN_DEGRADED']},before,after,{})
        events.append({'step':k,'accepted':result['accepted'],**result['v24917_td_blend']})
        before=after
    record('R01_local_vs_global_survey_bound',{'events':events,'final_ratio_to_start':1.2**3})
    assert all(e['accepted'] for e in events)

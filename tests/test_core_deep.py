from __future__ import annotations
import numpy as np, pytest
import r1_15a2_core as core


def path(dseg,o,d,idx,vol): return {'dseg_code':dseg,'OrigZoneNo':o,'DestZoneNo':d,'Index':idx,'Vol(AP)':vol}
def plink(dseg,o,d,idx,seq,no,fr,to): return {'dseg_code':dseg,'OrigZoneNo':o,'DestZoneNo':d,'PathIndex':idx,'Index':seq,'LinkNo':no,'FromNodeNo':fr,'ToNodeNo':to}


def test_exact_path_incidence_multiplicity_and_scope():
    paths=[path('NATIVE_CW',1,2,1,80),path('NATIVE_CW',1,2,2,20),path('NATIVE_CW',1,3,1,50)]
    links=[plink('NATIVE_CW',1,2,1,1,10,1,2),plink('NATIVE_CW',1,2,1,2,10,1,2),
           plink('NATIVE_CW',1,2,2,1,20,2,3),plink('NATIVE_CW',1,3,1,1,10,1,2)]
    profiles=[{'link_no':10,'from_node_no':1,'to_node_no':2,'role':'CALIBRATION','observed':200,'model':210}]
    inc=core.build_actual_path_incidence(paths,links,profiles,mutable_dsegs=['NATIVE_CW'],actuatable_zone_nos=[1,2])
    # OD 1->3 remains in projection base but is excluded from solver variables.
    assert inc['projection_base_variable_count']==2
    assert inc['variable_count']==1
    assert inc['full_profile_model_from_paths'][0]==pytest.approx(80*2+50)
    assert inc['mutable_profile_model_from_paths'][0]==pytest.approx(80*2)
    assert inc['incidence_share'][0]==pytest.approx(1.6)


def test_invalid_mutable_relation_policy_rejected():
    with pytest.raises(ValueError):
        core.build_actual_path_incidence([],[],[],mutable_relation_policy='BAD')


def test_sparse_solver_reduces_objective_randomized():
    rng=np.random.default_rng(42)
    nrow,ncol=30,120
    rows=rng.integers(0,nrow,500); cols=rng.integers(0,ncol,500); vals=rng.uniform(0.01,1,500)
    op=core.SparseOperator(rows,cols,vals,nrow,ncol)
    meta=[{'variable_index':i,'q_current':100.0,'family':'WORK','origin':i%10,'destination':(i+1)%10,'dseg_code':'NATIVE_CW'} for i in range(ncol)]
    target=rng.uniform(1,20,nrow)
    prob=core.GuidanceProblem(op,target,np.ones(nrow),np.ones(ncol)*0.1,np.zeros(ncol),np.zeros(ncol),np.ones(ncol)*0.1,meta,[{} for _ in range(nrow)],np.arange(nrow),[],{})
    res=core.solve_guidance(prob,{'solver_max_iter':2000,'solver_tolerance':1e-9,'solver_check_every':10,'power_iterations':50})
    assert res.objective_final < res.objective_initial
    assert np.all(res.x>=-1e-12) and np.all(res.x<=0.1000001)


def test_projection_balances_production_and_attraction():
    # Minimal synthetic GuidanceProblem/Result over two OD variables.
    op=core.SparseOperator(np.array([0,0]),np.array([0,1]),np.array([1.,1.]),1,2)
    meta=[{'variable_index':0,'q_current':100.,'family':'WORK','origin':1,'destination':2,'dseg_code':'NATIVE_CW'},
          {'variable_index':1,'q_current':50.,'family':'WORK','origin':2,'destination':3,'dseg_code':'NATIVE_CW'}]
    prob=core.GuidanceProblem(op,np.array([10.]),np.array([1.]),np.ones(2),np.zeros(2),np.array([-0.1,-0.1]),np.array([0.1,0.1]),meta,[{}],np.array([0]),[],{})
    res=core.GuidanceResult(np.array([0.05,0.03]),np.array([6.5]),np.array([-3.5]),10,5,2,True,1,[])
    all_meta=[dict(x,base_variable_index=i) for i,x in enumerate(meta)]
    pr=core.project_guidance_to_add(prob,res,[1,2,3],{'projection_max_iter':2000,'projection_tolerance':1e-10,'projection_gain':1.0,'projection_ridge_volume':1,'projection_ridge_lambda':0.1,'projection_min_volume_weight':1,'min_od_guidance_for_projection':1e-8,'max_add_log_up':0.2,'max_add_log_down':0.2},all_variable_meta=all_meta)
    fam=pr.family_summaries[0]
    assert fam['converged']
    assert abs(fam['projected_prod_total_change']-fam['projected_att_total_change'])<1e-6

@pytest.mark.parametrize('seed',range(10))
def test_random_sparse_solver_never_worsens(seed):
    rng=np.random.default_rng(seed)
    nrow,ncol=12,40
    rows=rng.integers(0,nrow,160); cols=rng.integers(0,ncol,160); vals=rng.uniform(.01,1,160)
    op=core.SparseOperator(rows,cols,vals,nrow,ncol)
    meta=[{'variable_index':i,'q_current':rng.uniform(10,200),'family':'WORK','origin':i%8+1,'destination':(i*3)%8+1,'dseg_code':'NATIVE_CW'} for i in range(ncol)]
    prob=core.GuidanceProblem(op,rng.uniform(0,25,nrow),rng.uniform(.5,2,nrow),np.ones(ncol)*.2,np.ones(ncol)*.001,np.zeros(ncol),np.ones(ncol)*.08,meta,[{} for _ in range(nrow)],np.arange(nrow),[],{})
    res=core.solve_guidance(prob,{'solver_max_iter':3000,'solver_tolerance':1e-8,'solver_check_every':10,'power_iterations':40})
    assert res.objective_final <= res.objective_initial+1e-8
    assert np.isfinite(res.x).all()


def _count(code,role,obs,model):
    return {'countlocation_no':code,'role':role,'observed':obs,'model':model}


def test_generation_acceptance_ignores_validation_but_reports_it():
    before=[_count('c1','CALIBRATION',1000,700),_count('c2','CALIBRATION',800,600),_count('v1','VALIDATION',1000,1000)]
    after=[_count('c1','CALIBRATION',1000,800),_count('c2','CALIBRATION',800,680),_count('v1','VALIDATION',1000,2500)]
    summary={'component_dist_summary_rows':[{'component':'WORK_E_C','family':'WORK','target_status':'ACTIVE_COMPONENT_DIST_TARGET','mean_model_conditioned':10,'mean_target':10,'l1_distance_half':.1,'rmse_share':.1}]}
    d=core.acceptance_decision(before,after,summary,summary,{'min_cal_objective_relative_improvement':.001,'max_new_geh20':99,'max_new_geh30':99,'max_protected_to_warn':99,'max_protected_to_hard':99,'idp_max_mean_degradation':0,'idp_max_component_degradation':0})
    assert d['accepted']
    assert d['validation_used_for_design_or_acceptance'] is False
    assert d['validation_after_report_only']['objective_geh2_mean']>d['validation_before_report_only']['objective_geh2_mean']

from __future__ import annotations
import json, pathlib, sys
import numpy as np
ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import r1_15a2_core as core
import r1_15a2_multiblock as mb

cfg=json.loads((ROOT/'R1_15A2_CONFIG_V2_1.json').read_text())
# Keep the demonstration small but use the production solver/regularization.
cfg.update({'min_od_volume':1.0,'max_solver_variables':1000,'solver_max_iter':3000,'solver_tolerance':1e-9,'solver_check_every':5,'min_driver_geh':1.0,'min_driver_abs_residual':10.0,'min_mutable_share':0.0,'parity_min_model':0.0,'overroute_weight_multiplier':20.0,'protected_weight_multiplier':10.0})

def path(ds,o,d,i,v): return {'dseg_code':ds,'OrigZoneNo':o,'DestZoneNo':d,'Index':i,'Vol(AP)':v}
def link(ds,o,d,i,seq,no,fr,to): return {'dseg_code':ds,'OrigZoneNo':o,'DestZoneNo':d,'PathIndex':i,'Index':seq,'LinkNo':no,'FromNodeNo':fr,'ToNodeNo':to}

# OD1 helps underloaded P1 but also a protected P2; OD2 helps P1 without touching P2;
# OD3 crosses an overroute P3. The solver should prefer OD2.
paths=[
 path('NATIVE_CW',1,2,1,100), path('NATIVE_CW',1,3,1,100), path('NATIVE_CS',4,5,1,100),
]
links=[
 link('NATIVE_CW',1,2,1,1,11,1,2), link('NATIVE_CW',1,2,1,2,12,2,3),
 link('NATIVE_CW',1,3,1,1,11,1,2),
 link('NATIVE_CS',4,5,1,1,11,1,2), link('NATIVE_CS',4,5,1,2,13,3,4),
]
profiles=[
 {'countlocation_no':'P1','role':'CALIBRATION','observed':500,'model':300,'link_no':11,'from_node_no':1,'to_node_no':2},
 {'countlocation_no':'P2','role':'CALIBRATION','observed':100,'model':100,'link_no':12,'from_node_no':2,'to_node_no':3},
 {'countlocation_no':'P3','role':'CALIBRATION','observed':50,'model':300,'link_no':13,'from_node_no':3,'to_node_no':4},
 {'countlocation_no':'V1','role':'VALIDATION','observed':100,'model':100,'link_no':99,'from_node_no':9,'to_node_no':10},
]
inc=core.build_actual_path_incidence(paths,links,profiles,mutable_dsegs=['NATIVE_CW','NATIVE_CS'],actuatable_zone_nos=[1,2,3,4,5])
problem=core.prepare_guidance_problem(inc,cfg)
result=core.solve_guidance(problem,cfg)
projection=core.project_guidance_to_add(problem,result,[1,2,3,4,5],cfg,all_variable_meta=inc['projection_base_variables'])

zone_rows=[]
for z in range(1,6):
 zone_rows.append({'zone_no':z,'NOT_ZAHR':1,'ZAHR_SUSED':0,'POP_ZP_2022':100,'AV_INCOME':1000+z*250,
 'ADD_PROD_W':1,'ADD_ATT_W':1,'ADD_SALARY':1,'ADD_PROD_S':1,'ADD_ATT_S':1,
 'ZAHR_PROD_WORK':1,'ZAHR_ATR_WORK':1,'ZAHR_PROD_SERV':1,'ZAHR_ATR_SERV':1})
gen=mb.design_generation_candidates(projection.rows,zone_rows,cfg,scale=1.0)

# Component TD demonstration with a target that needs b>0 and c more negative.
summary=[{'component':'WORK_E_C','target_status':'ACTIVE_COMPONENT_DIST_TARGET','conditioned_volume':10000,'total_volume':10000}]
model=[
 {'component':'WORK_E_C','bin_low':0,'bin_high':1,'share_conditioned':.55},
 {'component':'WORK_E_C','bin_low':1,'bin_high':15,'share_conditioned':.20},
 {'component':'WORK_E_C','bin_low':25,'bin_high':100,'share_conditioned':.25},
]
target=[
 {'component':'WORK_E_C','bin_low':0,'bin_high':1,'target_share':.25},
 {'component':'WORK_E_C','bin_low':1,'bin_high':15,'target_share':.55},
 {'component':'WORK_E_C','bin_low':25,'bin_high':100,'target_share':.20},
]
signals=mb.build_td_signals(summary,target,model,long_authority=json.loads((ROOT/'authorities/R1_LONG_AUTHORITY_CONTRACT_V2_1.json').read_text()),config=cfg)
td=mb.design_td_candidates(signals,{'WORK_E_C':{'current_b':0.0,'current_c':-.1,'dstrat_code':'1_WORK_E_C'}},'WORK',cfg,scale=.5)

# Explicit synthetic-only LONG authority proves component logic without claiming production authority.
long_auth={'authority_id':'SYNTHETIC_TEST_ONLY','component_targets':{'LONG_E_C':{'status':'SYNTHETIC_TEST_ONLY','bins':[{'bin_low':100,'bin_high':110,'target_share':.4},{'bin_low':110,'bin_high':120,'target_share':.6}]}}}
long_summary=[{'component':'LONG_E_C','target_status':'LONG_BASIS_PENDING_NOT_BACKEND_TARGET','conditioned_volume':1000,'total_volume':1000}]
long_model=[{'component':'LONG_E_C','bin_low':100,'bin_high':110,'share_conditioned':.7},{'component':'LONG_E_C','bin_low':110,'bin_high':120,'share_conditioned':.3}]
long_signals=mb.build_td_signals(long_summary,[],long_model,long_authority=long_auth,config=cfg)
long_td=mb.design_td_candidates(long_signals,{'LONG_E_C':{'current_b':4.5,'current_c':-.03,'dstrat_code':'3_LONG_E_C'}},'LONG',cfg,scale=1.0)

x_by_od={f"{m['dseg_code']}:{m['origin']}->{m['destination']}":float(result.x[i]) for i,m in enumerate(problem.variable_meta)}
report={
 'status':'PASS_SYNTHETIC_E2E',
 'objective_initial':result.objective_initial,'objective_final':result.objective_final,'objective_improved':result.objective_final<result.objective_initial,
 'solver_converged':result.converged,'solver_iterations':result.iterations,
 'od_guidance':x_by_od,
 'preferred_clean_underload_od': x_by_od.get('NATIVE_CW:1->3',0) >= x_by_od.get('NATIVE_CW:1->2',0),
 'overroute_exposed_od_not_preferred': x_by_od.get('NATIVE_CS:4->5',0) < x_by_od.get('NATIVE_CW:1->3',0),
 'projection_family_summaries':projection.family_summaries,
 'generation_candidate_count':len(gen['candidate_rows']),'generation_attrs':gen['summary']['attrs_changed'],'generation_pa_effects':gen['summary']['estimated_pa_delta_by_family'],
 'generation_max_effect_log_error':gen['summary']['max_abs_effect_log_error'],
 'work_td_candidate':td['candidate_rows'],
 'work_b_moves_from_zero':bool(td['candidate_rows'] and td['candidate_rows'][0]['candidate_b']>0),
 'work_backtracking_scale':td['summary']['backtracking_scale'],
 'long_production_authority_status':'AGGREGATE_GUARD_ONLY_NO_COMPONENT_CALIBRATION',
 'long_synthetic_component_candidate':long_td['candidate_rows'],
 'validation_used_for_design_or_acceptance':False,
 'direct_od_write':False,
}
out=ROOT/'SYNTHETIC_EVIDENCE'/'00_SYNTHETIC_DEMO_REPORT.json'; out.parent.mkdir(exist_ok=True)
out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(report,ensure_ascii=False,indent=2))
assert report['objective_improved'] and report['solver_converged']
assert report['preferred_clean_underload_od']
assert report['overroute_exposed_od_not_preferred']
assert report['work_b_moves_from_zero']
assert report['generation_candidate_count']>0
assert report['long_synthetic_component_candidate']

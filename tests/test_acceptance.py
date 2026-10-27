from __future__ import annotations
import pytest
import r1_15a2_multiblock as mb


def signal(obj,cal=True):
    return {'component':'WORK_E_C','family':'WORK','calibratable':cal,'l1_half':obj,'rmse_share':0,'mean_target':10,'mean_delta':0,'conditioned_volume':100}


def test_td_metrics_weighted():
    r=mb.td_component_metrics({'WORK_E_C':signal(.2)},['WORK_E_C'],{'td':{}})
    assert r['n']==1 and r['weighted_objective']==pytest.approx(.2)

import importlib.util, pathlib
ROOT=pathlib.Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('master_accept',ROOT/'R1_15A2_ACTUAL_PATH_MULTIBLOCK_CALIBRATION_MASTER_V2_1.py')
master=importlib.util.module_from_spec(spec); spec.loader.exec_module(master)


def _count(code,role,obs,model): return {'countlocation_no':code,'role':role,'observed':obs,'model':model}

def _sig(comp,obj):
    return {comp:{'component':comp,'family':'WORK','calibratable':True,'l1_half':obj,'rmse_share':0,'mean_target':10,'mean_delta':0,'conditioned_volume':100}}

def _summary(obj):
    return {'component_dist_summary_rows':[{'component':'WORK_E_C','family':'WORK','target_status':'ACTIVE_COMPONENT_DIST_TARGET','mean_model_conditioned':10,'mean_target':10,'l1_distance_half':obj,'rmse_share':0}]}


def test_td_acceptance_requires_component_improvement_and_uses_cal_only():
    before12=[_count('c','CALIBRATION',1000,900),_count('v','VALIDATION',1000,1000)]
    after12=[_count('c','CALIBRATION',1000,900),_count('v','VALIDATION',1000,2500)]
    cfg={'td':{'min_selected_component_relative_improvement':.002,'max_selected_component_relative_degradation':0,'max_nonselected_component_objective_degradation':.01,'max_cal_geh2_relative_degradation':.01,'max_global_idp_mean_degradation':.01,'max_global_idp_component_degradation':.01},'max_new_geh20':99,'max_new_geh30':99,'max_protected_to_warn':99,'max_protected_to_hard':99}
    d=master.td_acceptance_decision(before12,after12,_summary(.2),_summary(.1),_sig('WORK_E_C',.2),_sig('WORK_E_C',.1),['WORK_E_C'],cfg)
    assert d['accepted']
    assert d['validation_used_for_design_or_acceptance'] is False
    d2=master.td_acceptance_decision(before12,after12,_summary(.2),_summary(.21),_sig('WORK_E_C',.2),_sig('WORK_E_C',.21),['WORK_E_C'],cfg)
    assert not d2['accepted']

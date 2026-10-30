"""LONGGUARD1 regression: short LONG OD, conditional CDF, continuation safety."""
from __future__ import annotations

import numpy as np
import pytest
from types import SimpleNamespace

import r1_15a2_long_distance_guard_v24917 as g


def data(short=0., middle=8., tail=7.):
    d = np.array([[0., 79.999], [100., 225.]])
    m = {no: np.zeros((2, 2), dtype=float) for no in g.MATRIX_NOS}
    m[9111][0, 1] = short
    m[9112][1, 0] = middle
    m[9113][1, 1] = tail
    return d, m


def evidence(short=0., middle=8., tail=7., fine=0.1):
    d,m=data(short,middle,tail)
    p=g.measure(d,m)
    p.update(fine_100_200_rmse=fine,fine_cdf_verified=True,
             long_generation_permitted=p['support_clean'] and p['total_volume']>0)
    return p


def test_valid_long_ranges_including_exact_100_and_above_200():
    result=evidence()
    assert result['support_clean'] is True
    assert result['below_100_km']==0
    assert result['km_100_to_200']==8
    assert result['above_200_km']==7
    assert result['total_volume']==15


def test_under100_is_counted_in_all_five_matrices_not_silently_conditioned_out():
    d,m=data(short=4.)
    m[9115][0,0]=3
    result=g.measure(d,m)
    assert result['below_100_km']==7
    assert result['total_volume']==22
    assert not result['support_clean']


def test_boundary_200_is_legal_and_over200_remains_legal():
    d,m=data()
    d[1,1]=200.
    result=g.measure(d,m)
    assert result['above_200_km']==0
    assert result['km_100_to_200']==15


@pytest.mark.parametrize('value', [float('nan'),float('inf'),-9.])
def test_invalid_distance_cannot_pass(value):
    d,m=data(); d[0,0]=value
    with pytest.raises(ValueError):g.measure(d,m)


@pytest.mark.parametrize('value', [float('nan'),float('inf'),-9.])
def test_invalid_long_demand_cannot_pass(value):
    d,m=data();m[9114][0,0]=value
    with pytest.raises(ValueError):g.measure(d,m)


def test_all_five_matrices_required():
    d,m=data();del m[9115]
    with pytest.raises(ValueError):g.measure(d,m)


def test_positive_short_mass_cannot_be_accepted_from_clean_parent():
    proof=g.decide(evidence(),evidence(short=1),changed_long=True)
    assert not proof['passes'];assert 'LONGGUARD1_NEW_TRIPS_BELOW_MIN_KM' in proof['reasons']


def test_invalid_parent_freezes_long_not_success_by_conditional_cdf():
    proof=g.decide(evidence(short=100),evidence(short=100),changed_long=True)
    assert not proof['passes']
    assert 'LONGGUARD1_PARENT_NOT_ADMISSIBLE_FOR_LONG_GENERATION' in proof['reasons']


def test_invalid_parent_allows_other_families_only_without_increasing_short_mass():
    proof=g.decide(evidence(short=100),evidence(short=100),changed_long=False)
    assert proof['passes']
    bad=g.decide(evidence(short=100),evidence(short=101),changed_long=False)
    assert not bad['passes']
    assert 'LONGGUARD1_SHORT_TRIPS_INCREASED_FROM_INVALID_PARENT' in bad['reasons']


def test_conditional_512_finecdf_can_reject_despite_zero_short_mass():
    proof=g.decide(evidence(fine=.1),evidence(fine=.2),changed_long=True)
    assert not proof['passes']
    assert 'LONGGUARD1_512_CDF_DEGRADED' in proof['reasons']


def test_minor_curve_drift_without_new_short_mass_is_bounded():
    proof=g.decide(evidence(fine=.1),evidence(fine=.103),changed_long=True)
    assert proof['passes']


def test_finecdf_unverified_freezes_long():
    baseline=evidence(); baseline['fine_100_200_rmse']=None
    baseline['long_generation_permitted']=False
    proof=g.decide(baseline,evidence(),changed_long=True)
    assert not proof['passes']


def test_com_outage_is_not_silent_zero_short_volume():
    adapter=SimpleNamespace(v24916_dynamic_skims=None)
    proof=g.capture(adapter,{})
    assert proof['status']=='UNVERIFIED'
    assert not proof['long_generation_permitted']


def test_changed_long_detection_is_scoped_to_ls():
    assert g.changed_long([{'attr':'ADD_PROD_L'}])
    assert g.changed_long([{'attr':'ADD_ATT_L'}])
    assert not g.changed_long([{'attr':'ADD_PROD_W'}])


def test_missing_dynamic_fine_rmse_cannot_certify_long_generation():
    diag={'d11':{'summary':{'component_dist_summary_rows':[{'component':'LONG_COMPOSITE'}]}}}
    assert g._fine_rmse(diag) is None


def test_100_200_composite_finecdf_extraction():
    from r1_15a2_long_composite_diagnostic_v24917 import KEY, SCHEMA
    diag={'d11':{'summary':{'component_dist_summary_rows':[
        {'component':'WORK_stud','dynamic_fine_cdf_rmse':.09}],
        KEY: {'schema': SCHEMA, 'status': 'VERIFIED', 'component': 'LONG_COMPOSITE', 'fine_cdf_rmse': .123}}}}
    assert g._fine_rmse(diag)==.123


def test_capture_binds_osrm_support_and_separate_fresh_finecdf_epoch(monkeypatch):
    from r1_15a2_skim_v24916p2c import ordered_zone_hash
    d,m=data(); zones=[11,12]
    from test_v24917_long_osrm_support import make_adapter
    osrm_adapter, osrm_live = make_adapter(d, zones, m)
    epoch=SimpleNamespace(
        family_distance={'LONG':d}, zone_order_sha256=ordered_zone_hash(zones),
        matrix_meta_by_dseg={'NATIVE_CL':{'unit':'km','values_sha256':'hash'}},
        assignment_epoch=7,epoch=8,epoch_hash='epochHash')
    adapter=SimpleNamespace(
        v24916_dynamic_skims=SimpleNamespace(require_current=lambda:epoch),
        zones=zones,visum=osrm_adapter.visum,
        com_retry_policy={'enabled':False})
    from test_v24917_long_composite_diagnostic import bind_diagnostic
    diag = bind_diagnostic(adapter, epoch, m)
    proof=g.capture(adapter,diag)
    assert proof['status']=='MEASURED'
    assert proof['long_generation_permitted']
    assert proof['epoch']['assignment_epoch']==7
    assert proof['above_200_km']==7
    adapter.zones=[12,11]
    bad=g.capture(adapter,diag)
    assert bad['status']=='UNVERIFIED'
    assert 'ZONE_ORDER_MISMATCH' in bad['error']


def test_w_s_can_continue_when_long_cl_read_fails_but_l_is_frozen():
    proof=g.decide({'status':'UNVERIFIED'},{'status':'UNVERIFIED'},changed_long=False)
    assert proof['passes'] and proof['long_distance_authority_verified'] is False
    assert not g.decide({'status':'UNVERIFIED'},{'status':'UNVERIFIED'},changed_long=True)['passes']


def test_cumulative_finecdf_drift_rejected_even_if_single_step_small():
    parent=evidence(fine=.105)
    parent['fine_cdf_anchor_rmse']=.1
    after=evidence(fine=.108)
    result=g.decide(parent,after,changed_long=True)
    assert not result['passes']
    assert 'LONGGUARD1_512_CDF_RUN_ANCHOR_DEGRADED' in result['reasons']


def test_generation_block_gate_rejects_fresh_short_long_candidate(monkeypatch):
    import r1_15a2_trial_adapter_v24917 as mod
    monkeypatch.setattr(mod._V24916ActiveAdapter, 'block_gate',
                        lambda self,*args,**kwargs: {'accepted':True,'reasons':[]})
    adapter=mod.VisumAdapter.__new__(mod.VisumAdapter)
    adapter._longguard1_parent=evidence()
    adapter._genfix2_mobility_parent={'options':{'enabled':False}}
    adapter.v24917_status={}
    monkeypatch.setattr(mod.longguard,'capture',lambda _self,diag:evidence(short=2.))
    verdict=adapter.block_gate('GENERATION',{}, {},[{'attr':'ADD_PROD_L'}])
    assert verdict['accepted'] is False
    assert 'LONGGUARD1_NEW_TRIPS_BELOW_MIN_KM' in verdict['reasons']
    assert adapter.v24917_status['ls_incomplete_current_cycle'] is True


def test_lsgen_with_longguard_frozen_keeps_school_but_never_long(monkeypatch):
    from r1_15a2_long_school_generation_v24917 import design,LS_DEFAULTS
    import r1_15a2_long_school_generation_v24917 as ls
    import r1_15a2_zonal_count_fit_v24917 as zf
    monkeypatch.setattr(ls,'ls_options',lambda:LS_DEFAULTS)
    class Matrix:
        def __init__(self,no):self.no=no
        def GetValues(self):
            return np.array([[0.,1.],[0.,0.]]) if self.no in (9225,9226) else np.zeros((2,2))
    class Matrices:
        def ItemByKey(self,no):return Matrix(no)
    class Zones:
        def GetMultiAttValues(self,attr,flag=False):
            vals=[11,12] if attr=='NO' else [1.,1.]
            return list(enumerate(vals))
    visum=SimpleNamespace(Net=SimpleNamespace(Matrices=Matrices(),Zones=Zones()))
    inc={'variables':[{'family':'WORK','origin':11,'destination':12,'q_current':5.}],
         'incidence':SimpleNamespace(row_idx=np.array([0]),col_idx=np.array([0]),values=np.array([3.])),
         'projection_base_variables':[{'family':'WORK','origin':11,'destination':12,'q_current':5.}]}
    ws_problem=SimpleNamespace(profile_rows=[{'profile_index':0,'countlocation_no':100,'observed':10,'model':5}],
                               target=np.array([5.]),weight=np.ones(1))
    def fake_solve(p,opts):
        return {'x':np.ones(len(p.var_keys))*.02,'predicted_change':np.array([.1]),
                'objective_initial':2.,'objective_final':1.,'converged':True}
    monkeypatch.setattr(zf,'solve',fake_solve)
    proof=design(visum,{'max_add_log_up':.1,'max_add_log_down':.1},[11,12],inc,
                 ws_problem,{'predicted_change':np.zeros(1)},fit_cfg={'longguard1_allow_long':False})
    assert proof['steps']['ADD_PROD_L']=={}
    assert proof['summary']['longguard1_long_generation_permitted'] is False
    assert proof['summary']['school_zone_vars'] > 0


def test_stale_11d_diagnostic_epoch_cannot_certify_long(monkeypatch):
    # A valid dynamic skim is insufficient if the FineCDF came from an old assignment.
    from r1_15a2_skim_v24916p2c import ordered_zone_hash
    d,m=data();zones=[1,2]
    e=SimpleNamespace(family_distance={'LONG':d},zone_order_sha256=ordered_zone_hash(zones),
                      matrix_meta_by_dseg={'NATIVE_CL':{'unit':'km'}},epoch=2,
                      assignment_epoch=2,epoch_hash='new')
    a=SimpleNamespace(zones=zones,v24916_dynamic_skims=SimpleNamespace(require_current=lambda:e))
    proof=g.capture(a,{'dynamic_skim_epoch':{'epoch_hash':'old'}})
    assert proof['status']=='UNVERIFIED'
    assert 'DIAGNOSTICS_NOT_BOUND' in proof['error']

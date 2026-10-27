from pathlib import Path
from dataclasses import replace
import copy, csv, json
import pytest
from r1_15a2_supply import *

ROOT = Path(__file__).resolve().parents[1]
A=(11,1,2); P=(12,2,4); B=(13,2,3); C=(14,3,4); T=(15,4,5)


def profile(key=P, model=600., obs=1000., role="CALIBRATION", ident="a"):
    return dict(link_no=key[0],from_node_no=key[1],to_node_no=key[2],observed=obs,model=model,role=role,countlocation_no=ident)


def route_rows(code="NATIVE_CW", volumes=(600.,400.), routes=((A,P,T),(A,B,C,T)), origin=10, dest=20):
    pp=[]; ll=[]
    for i,(vol,seq) in enumerate(zip(volumes,routes),1):
        pp.append({"dseg_code":code,"OrigZoneNo":origin,"DestZoneNo":dest,"Index":i,"Vol(AP)":vol})
        for j,k in enumerate(seq,1):
            ll.append({"dseg_code":code,"OrigZoneNo":origin,"DestZoneNo":dest,"PathIndex":i,"Index":j,
                       "LinkNo":k[0],"FromNodeNo":k[1],"ToNodeNo":k[2]})
    return pp,ll


def collector(profiles=None, code="NATIVE_CW", policy=None):
    policy=policy or SupplyPolicy(min_residual=1.,min_geh=1.)
    x=ActualRouteCollector(profiles or [profile()],policy,"parent",[A,P,B,C,T])
    pp,ll=route_rows(code)
    x.consume(pp,ll,{"code":code})
    return x


def links():
    return {k:{"addval1":0.,"eligible":True,"t0_c_seconds":60.} for k in (A,P,B,C,T)}


def test_active_formula_ten_seconds_and_no_freight_offset():
    a=validate_impedance_csv(ROOT/'authorities/IMPEDANCE_FUNCTIONS.csv')
    assert a['stored_terms']==31
    assert a['effective']['C:LINK']['equivalent_seconds_per_addval1']==10
    assert a['effective']['C_noT:LINK']['time_source']=='C'
    assert a['effective']['LNV:LINK']['equivalent_seconds_per_addval1']==0
    assert a['effective']['C:TURN']['equivalent_seconds_per_addval1']==0


@pytest.mark.parametrize('delta',[-1.,1.])
def test_raw_step_has_ten_second_effect(delta):
    r=check_addval_change(P,0,delta,0,links()[P],SupplyPolicy())
    assert r['equivalent_seconds']==10*delta


def test_decimal_anchor_is_not_silently_rounded():
    r=check_addval_change(P,.25,1.25,.25,links()[P],SupplyPolicy())
    assert r['new']==1.25 and r['delta']==1


@pytest.mark.parametrize('value',[float('nan'),float('inf'),True,.5,5.])
def test_bad_candidate_rejected(value):
    with pytest.raises(SupplyContractError):
        check_addval_change(P,0,value,0,links()[P],SupplyPolicy())


@pytest.mark.parametrize('field,value',[('lattice',.3),('max_step',0),('prior_lambda',0),('prior_sigma',0),('min_path_coverage',1.1),('max_edges',1.5)])
def test_bad_policy_rejected(field,value):
    with pytest.raises(SupplyContractError):SupplyPolicy.from_config({'supply':{field:value}})


def test_negative_bound_uses_free_flow_not_congestion():
    row=dict(links()[P],t0_c_seconds=9.)
    with pytest.raises(SupplyContractError,match='NONPOSITIVE'):
        check_addval_change(P,0,-1,0,row,SupplyPolicy())


def test_prior_anchored_at_original_not_last_accepted():
    p=SupplyPolicy()
    assert addval_prior({'e':2},{'e':0},p)==pytest.approx(4*addval_prior({'e':1},{'e':0},p))


def test_exact_on_bypass_contrast_cancels_common_links():
    x=collector(); d=propose_supply(x,links(),{k:0. for k in links()},x.policy)
    assert len(d['candidates'])>=2
    changed={tuple(c['key']) for r in d['candidates'] for c in r['changes']}
    assert A not in changed and T not in changed
    assert P in changed and B in changed and C in changed
    assert any(r['kind']=='BYPASS_BUNDLE_DETRACT' for r in d['candidates'])
    assert all(abs(c['delta'])==1 for r in d['candidates'] for c in r['changes'])


@pytest.mark.parametrize('code',['NATIVE_CL','NATIVE_CF','EXOG_EE_CW','EXOG_EE_CL','EXOG_EE_CF'])
def test_fixed_demand_routes_are_supply_scope(code):
    x=collector(code=code)
    assert propose_supply(x,links(),{k:0. for k in links()},x.policy)['candidates']


def test_unrelated_od_does_not_support_bypass():
    x=collector()
    pp,ll=route_rows('NATIVE_CS',(100000.,),((A,B,C,T),),origin=999,dest=888)
    x.consume(pp,ll,{'code':'NATIVE_CS'})
    assert x.edge_contrast[0][B]==pytest.approx(-600.)


def test_validation_targets_do_not_change_proposals():
    f=profile(A,1000,1000,'VALIDATION','v')
    a=collector([profile(),f]); f2=dict(f,observed=900000)
    b=collector([profile(),f2])
    ca=propose_supply(a,links(),{k:0 for k in links()},a.policy)['candidates']
    cb=propose_supply(b,links(),{k:0 for k in links()},b.policy)['candidates']
    assert ca==cb


@pytest.mark.parametrize('defect',['duplicate_path','duplicate_index','orphan_link','fractional_key','negative_volume','disconnected','missing_links'])
def test_bad_actual_paths_fail_closed(defect):
    pp,ll=route_rows()
    if defect=='duplicate_path':pp.append(copy.deepcopy(pp[0]))
    if defect=='duplicate_index':ll.append(copy.deepcopy(ll[0]))
    if defect=='orphan_link':ll[0]['PathIndex']=777
    if defect=='fractional_key':ll[0]['LinkNo']=11.2
    if defect=='negative_volume':pp[0]['Vol(AP)']=-1
    if defect=='disconnected':ll[1]['FromNodeNo']=99
    if defect=='missing_links':ll=[r for r in ll if r['PathIndex']==2]
    x=ActualRouteCollector([profile()],SupplyPolicy(),"parent",links())
    with pytest.raises(SupplyContractError):x.consume(pp,ll,{'code':'NATIVE_CW'})


def test_parity_uses_all_model_flow_not_reconstructed_denominator():
    x=collector([profile(model=900)])
    with pytest.raises(SupplyContractError,match='PARITY'):x.finish()


def test_duplicate_profile_does_not_multiply_driver_signal():
    x=collector([profile(),profile(ident='b')]);assert len(x.drivers)==1


def test_conflicting_duplicate_profile_is_rejected():
    with pytest.raises(SupplyContractError,match='CONFLICTING'):
        collector([profile(),profile(obs=2000,ident='b')])


def test_budget_and_integer_support_backtracking():
    p=SupplyPolicy(min_residual=1,min_geh=1,max_bundle_equivalent_seconds=10,max_candidates=20)
    x=collector(policy=p); d=propose_supply(x,links(),{k:0 for k in links()},p)
    assert all(len(r['changes'])==1 and r['equivalent_impedance_budget_seconds']==10 for r in d['candidates'])


def test_actual_intrazonal_route_may_have_no_physical_link():
    x=ActualRouteCollector([profile(model=0)],SupplyPolicy(),"p",links())
    pp,ll=route_rows('NATIVE_CW',(30,), ((),), origin=1,dest=1)
    s=x.consume(pp,ll,{'code':'NATIVE_CW'}); assert s['volume_coverage']==1
    assert x.finish()['profile_parity'][0]['passes']


def test_single_saved_path_is_labelled_probe_not_proved_response():
    x=ActualRouteCollector([profile(model=1000,obs=1500)],SupplyPolicy(),"p",links())
    pp,ll=route_rows(volumes=(1000,),routes=((A,P,T),))
    x.consume(pp,ll,{'code':'NATIVE_CW'})
    d=propose_supply(x,links(),{k:0 for k in links()},x.policy)
    assert all(r['confidence']=='ACTUAL_PATH_PROBE_REQUIRES_NEW_ASSIGNMENT' for r in d['candidates'])


def test_unit_contract_cannot_be_overridden():
    with pytest.raises(SupplyContractError,match='TEN_GENERALIZED_SECONDS'):
        SupplyPolicy.from_config({'supply':{'equivalent_seconds_per_addval1':600}})


def test_repeated_link_multiplicity_is_counted_in_path_budget():
    reverse=(99,4,2)
    seq=(A,P,reverse,P,T)
    pol=SupplyPolicy(min_geh=1,min_residual=1,max_bundle_equivalent_seconds=10)
    x=ActualRouteCollector([profile(model=2000,obs=1000)],pol,'p',[P])
    pp,ll=route_rows(volumes=(1000,),routes=(seq,))
    x.consume(pp,ll,{'code':'NATIVE_CW'})
    assert x.flow[0]==2000 and x.edge_max_multiplicity[P]==2
    assert not propose_supply(x,links(),{k:0 for k in links()},pol)['candidates']

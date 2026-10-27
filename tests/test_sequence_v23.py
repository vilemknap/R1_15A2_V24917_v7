"""V2.3 exact ordered-path ADDVAL1 supply, scientific contract tests."""
from pathlib import Path
import copy
import json
import pytest
from r1_15a2_sequence_v23 import (
    ActualSequenceRouteCollector, branch_pair, contiguous_windows, path_nodes,
    propose_sequence_supply)
from r1_15a2_supply import SupplyPolicy,SupplyContractError
from test_supply_v22 import A,P,B,C,T,route_rows,profile,links


def fixture(route_store=':memory:', profiles=None, extra=(), policy=None):
    pol=policy or SupplyPolicy(min_geh=1.,min_residual=1.,max_candidates=20)
    rows=profiles or [profile()]
    collector=ActualSequenceRouteCollector(rows,pol,'parent',links(),db_path=route_store)
    pp,ll=route_rows()
    collector.consume(pp,ll,{'code':'NATIVE_CW'})
    for dseg,volumes,routes,origin,dest in extra:
        pp,ll=route_rows(dseg,volumes,routes,origin,dest)
        collector.consume(pp,ll,{'code':dseg})
    return collector


def design(c, **overrides):
    return propose_sequence_supply(c,links(),{k:0. for k in links()},c.policy,**overrides)


def test_diverge_rejoin_extracts_real_ordered_on_off():
    actual=branch_pair((A,P,T),(A,B,C,T),P)
    assert actual['on']==(P,)
    assert actual['off']==(B,C)
    assert actual['anchors']==(2,4)
    assert actual['on'][0][1]==actual['off'][0][1]
    assert actual['on'][-1][2]==actual['off'][-1][2]
    assert branch_pair((A,P,T),(A,B,C,T),B) is None


def test_all_candidates_are_proved_contiguous_subsequences():
    c=fixture()
    try:
        d=design(c)
        assert d['candidates'] and d['selection_mode']=='ACTUAL_CONTIGUOUS_SEQUENCES'
        for candidate in d['candidates']:
            assert candidate['bundles']
            for b in candidate['bundles']:
                source=[tuple(x) for x in b['source_sequence']]
                selected=[tuple(x) for x in b['actual_contiguous_sequence']]
                assert any(source[k:k+len(selected)]==selected for k in range(len(source)))
                assert list(path_nodes(selected))
                assert tuple(b['anchor_nodes'])==(2,4)
                assert b['path_pair_example']
            expected={tuple(x) for b in candidate['bundles'] for x in b['actual_contiguous_sequence']}
            assert {tuple(x['key']) for x in candidate['changes']}==expected
            assert A not in expected and T not in expected
            assert candidate['all_path_impact']['uses_validation_targets'] is False
            assert candidate['all_path_impact']['counterfactual_flow_prediction'] is False
    finally:c.close()


def test_overroute_and_underload_both_have_opposite_ON_OFF_signs():
    for model,obs,expected_on in [(600.,1000.,-1),(600.,100.,1)]:
        c=fixture(profiles=[profile(model=model,obs=obs)])
        try:
            d=design(c)
            bundles=[(b,can) for can in d['candidates'] for b in can['bundles']]
            assert any(b['kind']=='ON' for b,_ in bundles)
            assert any(b['kind']=='OFF' for b,_ in bundles)
            for b,can in bundles:
                deltas={tuple(x['key']):x['delta'] for x in can['changes']}
                for e in b['actual_contiguous_sequence']:
                    assert deltas[tuple(e)]==(expected_on if b['kind']=='ON' else -expected_on)
        finally:c.close()


def test_cap_split_contains_individual_sequences_not_only_large_batches():
    c=fixture()
    try:
        d=design(c,sequence_caps=(8,4,2,1))
        assert d['cap_schedule']==[8,4,2,1]
        assert any(len(x['bundles'])>1 for x in d['candidates'])
        assert any(len(x['bundles'])==1 for x in d['candidates'])
        # Combined candidates retain each branch as distinct provenance.
        assert all(len(x['changes'])<=c.policy.max_edges for x in d['candidates'])
    finally:c.close()


def test_actual_saved_off_route_without_shared_anchors_is_not_fabricated():
    different=((91,30,31),(92,31,32))
    assert branch_pair((A,P,T),different,P) is None
    c=ActualSequenceRouteCollector([profile()],SupplyPolicy(min_geh=1,min_residual=1),
                                    'p',links())
    pp,ll=route_rows(volumes=(600,400),routes=((A,P,T),different))
    c.consume(pp,ll,{'code':'NATIVE_CW'})
    try:
        d=design(c)
        assert d['candidates']
        assert all(x['confidence']=='ACTUAL_PATH_PROBE_REQUIRES_NEW_ASSIGNMENT'
                   for x in d['candidates'])
        assert d['authority']['skipped_branch_cases']['NO_COMMON_DIVERGE_REJOIN_ANCHORS']>0
    finally:c.close()


def test_exact_path_direct_cost_impact_is_ten_seconds_per_link_unit():
    c=fixture()
    try:
        d=design(c)
        on=next(x for x in d['candidates'] if {tuple(k['key']) for k in x['changes']}=={P})
        impact=on['all_path_impact']
        assert impact['max_abs_path_seconds']==10
        assert impact['by_cal_class']['DRIVER_ON']['volume']==600
        assert impact['affected_routes']==1
    finally:c.close()


def test_off_path_from_another_market_never_creates_bypass():
    c=ActualSequenceRouteCollector([profile(model=600.)],
        SupplyPolicy(min_geh=1,min_residual=1),'p',links())
    pp,ll=route_rows(volumes=(600,),routes=((A,P,T),))
    c.consume(pp,ll,{'code':'NATIVE_CW'})
    pp,ll=route_rows('NATIVE_CS',volumes=(400,),routes=((A,B,C,T),),origin=10,dest=20)
    c.consume(pp,ll,{'code':'NATIVE_CS'})
    try:
        d=design(c)
        assert d['candidates']
        assert all(all(b['kind']=='ON_ONLY_PROBE' for b in can['bundles']) for can in d['candidates'])
        assert all(can['confidence']=='ACTUAL_PATH_PROBE_REQUIRES_NEW_ASSIGNMENT' for can in d['candidates'])
    finally:c.close()


def test_all_path_impact_sees_unrelated_and_protected_passenger_routes(tmp_path):
    # A is a protected CAL profile but is common to both alternatives; user does not
    # want its observed count to become a driver. It still gets exposure attribution.
    profiles=[profile(),profile(A,1000,1000,'CALIBRATION','protected_a')]
    db=tmp_path/'all_saved_routes.sqlite'
    c=fixture(route_store=db,profiles=profiles,
        extra=[('NATIVE_CS',(900,),((B,C),),30,40)])
    try:
        d=design(c)
        assert db.is_file() and c.route_count==3
        off=[x for x in d['candidates'] if any(b['kind']=='OFF' for b in x['bundles'])]
        assert off
        impact=off[0]['all_path_impact']
        assert impact['by_cal_class']['UNRELATED_TO_CAL']['volume']>=900
        assert impact['protected_cal_exposure_including_driver_overlap']['volume']>0
        assert impact['max_abs_path_seconds']<=60
    finally:c.close()


def test_zero_validation_dependence_for_sequence_selection():
    p=profile();validation=profile(A,1000.,1000.,'VALIDATION','v')
    a=fixture(profiles=[p,validation])
    b=fixture(profiles=[p,dict(validation,observed=999999.)])
    try:
        def signatures(d):
            return [(tuple((tuple(v['key']),v['delta']) for v in x['changes']),
                     [b['kind'] for b in x['bundles']]) for x in d['candidates']]
        assert signatures(design(a))==signatures(design(b))
    finally:a.close();b.close()


def test_contiguous_shortening_does_not_stitch_across_uneditable_edge():
    a=(1,1,2);b=(2,2,3);block=(3,3,4);c=(4,4,5);d=(5,5,6)
    seq=(a,b,block,c,d)
    windows=contiguous_windows(seq,{a,b,c,d},max_len=3)
    assert windows
    assert all(block not in x for x in windows)
    assert not any(a in x and d in x for x in windows)
    assert all(any(seq[k:k+len(x)]==x for k in range(len(seq))) for x in windows)


def test_budget_checks_actual_affected_route_not_only_selected_bundles():
    # Both edited edges occur four times in a different saved path, giving 80 sec.
    c=fixture()
    try:
        added=(88,4,2)
        # Proven on/off route pairs remain only A-P-T and A-B-C-T.
        with c.db:
            c.db.execute('''INSERT INTO routes(dseg,orig,dest,path_index,volume,sequence_json,cal_profile_ids)
                VALUES(?,?,?,?,?,?,?)''',('NATIVE_CS',70,80,1,200,
                                           json.dumps((B,C,added)*4),json.dumps([])))
            rid=c.db.execute('SELECT last_insert_rowid()').fetchone()[0]
            c.db.executemany('''INSERT INTO route_edges(link_no,from_no,to_no,route_id,multiplicity)
                    VALUES(?,?,?,?,?)''',[(*B,rid,4),(*C,rid,4),(*added,rid,4)])
        d=design(c)
        assert all(x['all_path_impact']['max_abs_path_seconds']<=60 for x in d['candidates'])
        assert not any({tuple(z['key']) for z in x['changes']}=={B,C} for x in d['candidates'])
    finally:c.close()


def test_no_evidence_no_supply_candidate():
    c=ActualSequenceRouteCollector([profile(model=0,obs=0)],SupplyPolicy(),'p',links())
    pp,ll=route_rows(volumes=(30,),routes=((),),origin=1,dest=1)
    c.consume(pp,ll,{'code':'NATIVE_CW'})
    try: assert not design(c)['candidates']
    finally:c.close()


def test_policy_collateral_can_block_before_assignment():
    c=fixture(extra=[('NATIVE_CS',(100000.,),((B,C),),30,40)])
    try:
        d=design(c,max_collateral_ratio=0.1)
        assert all(can['all_path_impact']['collateral_to_support_ratio']<=0.1
                   for can in d['candidates'])
        assert any(x['reason']=='COLLATERAL_IMPACT_LIMIT' for x in d['skipped'])
    finally:c.close()


def test_v23_master_defaults_to_offline_design_only():
    import R1_15A2_SUPPLY_DEMAND_MASTER_V2_3 as entry
    cfg=entry.load_config()
    assert cfg['apply'] is False
    assert cfg['version'].startswith('2.3')
    assert cfg['supply']['sequence']['sequence_cap_schedule']==[8,4,2,1]
    assert len(cfg['implementation_hash'])==64
    assert cfg['supply']['assignment_operations']==[]

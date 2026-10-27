"""Streaming/disk route store and evidence clustering under repeated OD markets."""
from r1_15a2_sequence_v23 import ActualSequenceRouteCollector, propose_sequence_supply
from r1_15a2_supply import SupplyPolicy
from test_supply_v22 import A,P,B,C,T,profile,links,route_rows


def test_many_markets_have_compact_exact_branch_evidence(tmp_path):
    markets=500
    p=SupplyPolicy(min_geh=1,min_residual=1,max_candidates=8)
    c=ActualSequenceRouteCollector([profile(model=markets*600,obs=markets*1000)],
        p,'accepted-parent',links(),db_path=tmp_path/'routes.sqlite')
    pp=[];ll=[]
    for market in range(markets):
        x,y=route_rows(volumes=(600,400),origin=market+1,dest=market+700)
        pp.extend(x);ll.extend(y)
    try:
        result=c.consume(pp,ll,{'code':'NATIVE_CW'})
        design=propose_sequence_supply(c,links(),{k:0. for k in links()},p)
        assert result['positive_paths']==markets*2
        assert c.route_count==markets*2
        assert design['authority']['unique_sequence_bundles']==2
        assert design['authority']['profile_parity'][0]['passes']
        assert max(x['all_path_impact']['max_abs_path_seconds'] for x in design['candidates'])<=60
        assert all(x['all_path_impact']['affected_routes']<=markets*2 for x in design['candidates'])
    finally:c.close()

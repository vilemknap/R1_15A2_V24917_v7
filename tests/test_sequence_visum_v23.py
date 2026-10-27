"""No Visum process is claimed; these use the existing actual-list COM-shaped stubs."""
from pathlib import Path
from r1_15a2_supply_visum_v23 import VisumAdapter
from test_supply_visum_v22 import exporter_visum,small_cfg
from test_supply_v22 import profile,P,B,C


def test_exact_route_sequence_passes_through_real_callback_wiring(tmp_path):
    v=exporter_visum();cfg=small_cfg()
    cfg['supply']['sequence']={'sequence_cap_schedule':[8,4,2,1]}
    adapter=VisumAdapter(v,cfg)
    adapter.baseline_addval={k:r['addval1'] for k,r in adapter.read_links().items()}
    snapshot=adapter.snapshot()
    design=adapter.supply_design({'d12':{'rows':[profile()]}},tmp_path,snapshot)
    assert design['selection_mode']=='ACTUAL_CONTIGUOUS_SEQUENCES'
    assert design['candidates']
    assert (tmp_path/'SUPPLY_ACTUAL_ROUTE_STORE.sqlite').is_file()
    assert (tmp_path/'SUPPLY_PATH_SEQUENCE_DESIGN.json').is_file()
    assert adapter.supply_path_proof['parent_hash']==snapshot['state_hash']
    assert design['authority']['path_store_route_count']==2
    assert any(b['actual_contiguous_sequence']==[list(P)] for can in design['candidates'] for b in can['bundles'])
    assert any(b['actual_contiguous_sequence']==[list(B),list(C)] for can in design['candidates'] for b in can['bundles'])


def test_exact_route_sequence_rejects_stale_parent_on_apply(tmp_path):
    v=exporter_visum();cfg=small_cfg();cfg['supply']['sequence']={}
    adapter=VisumAdapter(v,cfg)
    adapter.baseline_addval={k:r['addval1'] for k,r in adapter.read_links().items()}
    before=adapter.snapshot();design=adapter.supply_design({'d12':{'rows':[profile()]}},tmp_path,before)
    candidate=design['candidates'][0]
    from r1_15a2_supply import SupplyContractError
    import pytest
    fake=dict(candidate,parent_hash='wrong')
    with pytest.raises(SupplyContractError,match='STALE'):
        adapter.apply_supply(fake,before,tmp_path)

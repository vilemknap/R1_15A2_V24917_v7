import pytest
import r1_15a2_com_compat as com
import r1_15a2_runtime_v1 as rt
from test_supply_visum_v22 import exporter_visum, profile, ActualRouteCollector, SupplyPolicy, A, P, B, C, T
from conftest import FakeAttr

HDR=['OrigZoneNo','DestZoneNo','PathIndex','Index','LinkNo','FromNodeNo','ToNodeNo']


def example():
    return [
      [1,7,1,'','','',''],
      ['','','',1,2000039,1000386,1002465],
      ['','','',2,2003601,1002465,1003233],
      ['','','',3,8001458,1003233,9000139],
      [1,8,1,'','','',''],
      ['','','',1,8001478,9000139,9000146],
    ]


def test_normalize_actual_sample_hierarchical():
    flat=list(com.normalized_prt_pathlink_rows(example(),HDR))
    assert len(flat)==4
    assert [r['Index'] for r in flat]==[1,2,3,1]
    assert [(r['OrigZoneNo'],r['DestZoneNo'],r['PathIndex']) for r in flat]==[(1,7,1)]*3+[(1,8,1)]
    assert flat[0]['LinkNo']==2000039 and flat[0]['FromNodeNo']==1000386


def test_normalize_flat_rows_equivalence():
    flat=list(com.normalized_prt_pathlink_rows(example(),HDR))
    rows=[[r[k] for k in HDR] for r in flat]
    assert list(com.normalized_prt_pathlink_rows(rows,HDR))==flat


@pytest.mark.parametrize('bad,reason',[ 
    ([['','','',1,10,100,200]],'ORPHAN_LINK_CHILD'),
    ([[1,7,1,'','','',''],['','','',2,10,100,200]],'INDEX_NOT_CONTIGUOUS'),
    ([[1,7,1,'','','',''],['','','',1,10,100,200],['','','',2,11,300,400]],'BROKEN_TOPOLOGICAL'),
    ([[1,7,1,'','','',''],['','','',1,10,'',200]],'INCOMPLETE_LINK_CHILD'),
    ([[1,7,1,'','','',''],['','','',1,10,100,200],[1,7,2,'','','',''],['','','',1,11,200,300],[1,7,1,'','','','']], 'REOPENED_ROUTE'),
    ([['','','','','','','']], 'INCOMPLETE_ROUTE_PARENT'),
    ([[1,7,1,'','','',''],[1,8,'',1,10,100,200]],'CONFLICTING_PARENT'),
])
def test_normalize_rejects_malformed(bad,reason):
    with pytest.raises(RuntimeError,match=reason):list(com.normalized_prt_pathlink_rows(bad,HDR))


def test_normalize_input_does_not_mutate_source():
    sample=example(); original=[row[:] for row in sample]
    list(com.normalized_prt_pathlink_rows(sample,HDR))
    assert sample==original


class HierarchicalList:
    def __init__(self, path_rows,link_rows):
        self.pp=path_rows
        self.ll=link_rows
    def AddColumn(self,col):pass
    def SetObjects(self,*args):pass
    @property
    def SaveToArray(self):
        out=[]
        key=None
        for r in self.ll:
            pk=(r['OrigZoneNo'],r['DestZoneNo'],r['PathIndex'])
            if pk!=key:
                key=pk
                out.append([*pk,'','','',''])
            out.append(['','','',r['Index'],r['LinkNo'],r['FromNodeNo'],r['ToNodeNo']])
        return out


def test_real_hierarchical_pathlink_exporter_integrates_with_v22_collector(tmp_path):
    # Compare source evidence from original synthetic fixture, only presentation
    # of SaveToArray changes. The actual route sequence must be unchanged.
    v=exporter_visum()
    existing=v.Workbench.Lists.CreatePrTPathLinkList
    example_link_rows=existing().ll if callable(existing) else existing.ll
    pp=existing().pp if callable(existing) else existing.pp
    v.Workbench.Lists.CreatePrTPathLinkList=HierarchicalList(pp,example_link_rows)
    cfg={'path_export_dsegs':['NATIVE_CW'],'mutable_dsegs':[], 'require_all_path_export_dsegs':True}
    collector=ActualRouteCollector([profile()],SupplyPolicy(),'parent',[A,P,B,C,T])
    _,report=rt.export_actual_paths_and_build_incidence(v,tmp_path,cfg,[profile()],[],route_batch_callback=collector.consume,build_incidence=False)
    assert report['dseg_path_volume_parity_passes']
    assert collector.finish()['profile_parity'][0]['actual_path_flow']==600
    assert len((tmp_path/'04_PRT_PATHLINKS_ALL.csv').read_text(encoding='utf-8-sig').splitlines())>1


def test_v234_12d_does_not_require_nonexistent_direction_uda():
    from pathlib import Path
    source=(Path(__file__).resolve().parents[1]/'helpers/R1_12D_CSD408_CITY90_RPDI_498_APPROVED.py').read_text(encoding='utf-8')
    assert '("R1_DIRECTION", "observation_direction")' not in source
    assert '"R1_OBS_RPDI"' in source
    assert 'reverse_key' in source


def test_live_preflight_city_both_uses_actual_reverse_link_not_nonexistent_uda(tmp_path):
    import r1_15a2_live_api_audit as live
    from conftest import FakeCollection, FakeAttr
    link_data=[
      dict(NO=100,FROMNODENO=1,TONODENO=2,ADDVAL1=0,**{'T0_PRTSYS(C)':10},CAPPRT=2000,LENGTH=1,TYPENO=1,TSYSSET='C,C_noT'),
      dict(NO=100,FROMNODENO=2,TONODENO=1,ADDVAL1=0,**{'T0_PRTSYS(C)':10},CAPPRT=2000,LENGTH=1,TYPENO=1,TSYSSET='C,C_noT'),
    ]
    class Links(FakeCollection):
        def GetMultiAttValues(self, name, active):
            assert active is False
            return [(i,r[name]) for i,r in enumerate(link_data,1)]
    obs=FakeAttr(NO=912018,CODE='R1LC018',R1_OBS_ID='CITY_018',R1_OBS_BASIS='RPDI_BASE_2022_23',
        R1_OBS_SCOPE='OA',R1_OBS_RPDI=2289.89882283926,R1_ROLE='CALIBRATION',R1_WEIGHT=.9,
        R1_ACTIVE=1,LINKNO=100,FROMNODENO=1,TONODENO=2)
    # Deliberately NO R1_DIRECTION member, as in the real Visum 2026 export.
    approved={'no':912018,'observed':2289.89882283926,'role':'CALIBRATION','weight':.9,
        'edge_key':[100,1,2],'direction':'BOTH','countlocation_code':'R1LC018',
        'profile_id':'CITY_018','period_basis':'RPDI_BASE_2022_23','observed_scope':'OA'}
    net=FakeAttr(Links=Links([FakeAttr(**r) for r in link_data]),CountLocations=FakeCollection([obs]),
        Matrices=FakeCollection([]),DemandSegments=FakeCollection([]))
    v=FakeAttr(Net=net,Procedures=FakeAttr())
    cfg={'api_approved_observations':[approved],'expected_zones':681,'supply':{'passenger_dsegs':[]}}
    ok=live.collect_live_api(v,cfg,tmp_path/'case1')
    obj=next(x for x in ok['checks'] if x['check']=='APPROVED_COUNTLOCATION_RPDI_AND_ROLE')
    assert obj['status']=='PASS'
    assert obj['result']['approved_count']==1
    assert 'FROZEN_CITY90_AUTHORITY_PLUS_LIVE_REVERSE_EDGE'==obj['result']['both_direction_source']
    link_data.pop()
    v.Net.Links=Links([FakeAttr(**r) for r in link_data])
    bad=live.collect_live_api(v,cfg,tmp_path/'case2')
    error=next(x for x in bad['checks'] if x['check']=='APPROVED_COUNTLOCATION_RPDI_AND_ROLE')
    assert error['status']=='FAIL'
    assert 'REVERSE_LINK_MISSING' in error['error']['message']


def test_v234_master_keeps_population_protection_and_no_apply():
    import importlib
    mod=importlib.import_module('R1_15A2_SUPPLY_DEMAND_MASTER_V2_3_4')
    cfg=mod.load_config()
    assert cfg['apply'] is False
    assert cfg['api_audit_only'] is True or cfg['run_full_com_api_audit'] is True
    assert cfg['zahr']['population_attr']=='POP_ZP_2022'
    assert len(cfg['api_approved_observations'])==498
    city=next(x for x in cfg['api_approved_observations'] if x['no']==912018)
    assert city['direction']=='BOTH' and city['observed_scope']=='OA'
    assert all(x['period_basis'] for x in cfg['api_approved_observations'])
    assert cfg['supply']['assignment_operations']==[]
    assert cfg['supply']['gap_readback']['attribute'] is None

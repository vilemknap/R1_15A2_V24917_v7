"""15P live-evidence-driven synthetic COM tests; no production Visum invoked."""
from pathlib import Path
from types import SimpleNamespace
import csv
import json
import pytest

import r1_15a2_runtime_v1 as rt
import r1_15a2_com_compat as com
from r1_15a2_sequence_v23 import ActualSequenceRouteCollector
from r1_15a2_supply import SupplyContractError, SupplyPolicy
from test_supply_v22 import route_rows, profile, A, P, B, C, T
from test_supply_visum_v22 import exporter_visum, OfficialList

KEYS=['OrigZoneNo','DestZoneNo','PathIndex','Index','LinkNo','FromNodeNo','ToNodeNo']


class TypeInfo:
    def __init__(self, names=None):
        self.names=names or ('SaveToArray','FirstObject','LastObject')
    def GetTypeAttr(self): return SimpleNamespace(cFuncs=1)
    def GetFuncDesc(self, idx):
        assert idx == 0
        return SimpleNamespace(memid=11, invkind=1)
    def GetNames(self, memid):
        assert memid == 11
        return self.names


class OLE:
    def __init__(self, obj, names=None):
        self.owner=obj
        self.typeinfo=TypeInfo(names)
        self.calls=[]
    def GetTypeInfo(self): return self.typeinfo
    def Invoke(self, memid, lcid, kind, as_method, first, last):
        assert (memid, lcid, kind, as_method)==(11,0,1,True)
        self.calls.append((first,last))
        return self.owner.raw[first-1:last]


class BoundedHierarchical:
    def __init__(self, raw, names=None):
        self.raw=raw
        self.columns=[]
        self._oleobj_=OLE(self,names)
        self.unbounded_calls=0
    def AddColumn(self, name): self.columns.append(name)
    def SetObjects(self, *args): self.selection=args
    @property
    def SaveToArray(self):
        self.unbounded_calls+=1
        raise AssertionError('Unbounded call forbidden')


def raw_hierarchical():
    p,l=route_rows()
    rows=[]
    for route in p:
        pk=(route['OrigZoneNo'],route['DestZoneNo'],route['Index'])
        rows.append([*pk,'','','',''])
        for link in l:
            if (link['OrigZoneNo'],link['DestZoneNo'],link['PathIndex'])==pk:
                rows.append(['','','',link['Index'],link['LinkNo'],link['FromNodeNo'],link['ToNodeNo']])
    return rows


def test_bounded_com_page_boundary_inside_child_hierarchy():
    obj=BoundedHierarchical(raw_hierarchical())
    flat=list(com.normalized_prt_pathlink_rows(
        rt.iter_prt_pathlink_bounded(obj,KEYS,page_size=3,require_verified=True),KEYS))
    assert len(flat)==7
    assert flat[0]['Index']==1 and flat[-1]['Index']==4
    assert obj._oleobj_.calls==[(1,3),(4,6),(7,9),(10,12)]
    assert obj.unbounded_calls==0


def test_bounded_rejects_wrong_signature_without_unbounded_fallback():
    obj=BoundedHierarchical(raw_hierarchical(),('SaveToArray','Incorrect','LastObject'))
    with pytest.raises(RuntimeError,match='UNVERIFIED'):
        list(rt.iter_prt_pathlink_bounded(obj,KEYS,require_verified=True))
    assert obj.unbounded_calls==0


def test_bounded_max_pages_fail_closed():
    obj=BoundedHierarchical(raw_hierarchical())
    with pytest.raises(RuntimeError,match='BUDGET_EXCEEDED'):
        list(rt.iter_prt_pathlink_bounded(obj,KEYS,page_size=1,max_pages=2,require_verified=True))


def test_bounded_page_width_invariant():
    obj=BoundedHierarchical(raw_hierarchical())
    obj.raw[2]=[1,2]
    with pytest.raises(RuntimeError,match='ROW_WIDTH'):
        list(rt.iter_prt_pathlink_bounded(obj,KEYS,page_size=3,require_verified=True))


def test_collector_stream_and_legacy_parity(tmp_path):
    pp,ll=route_rows()
    policy=SupplyPolicy(min_geh=1,min_residual=1)
    base=ActualSequenceRouteCollector([profile()],policy,'s',[A,P,B,C,T],db_path=tmp_path/'base.sqlite')
    stream=ActualSequenceRouteCollector([profile()],policy,'s',[A,P,B,C,T],db_path=tmp_path/'stream.sqlite')
    try:
        b=base.consume(pp,ll,{'code':'NATIVE_CW'})
        a=stream.consume_stream(pp,iter(ll),{'code':'NATIVE_CW'})
        assert a['official_route_batch_hash']==b['official_route_batch_hash']
        assert a['positive_paths']==b['positive_paths']==2
        assert a['covered_paths']==b['covered_paths']==2
        assert stream.flow==base.flow
        assert stream.support==base.support
        assert stream.market_counts==base.market_counts
        assert stream.edge_max_multiplicity==base.edge_max_multiplicity
        assert stream.finish()['profile_parity']==base.finish()['profile_parity']
        assert stream.route_count==base.route_count==2
        assert sorted(stream.db.execute('SELECT orig,dest,path_index,sequence_json FROM routes').fetchall()) == sorted(
            base.db.execute('SELECT orig,dest,path_index,sequence_json FROM routes').fetchall())
    finally:
        base.close();stream.close()


@pytest.mark.parametrize('damage,expected',[
    ('missing_inter','MISSING_POSITIVE_INTERZONAL_PATH_LINKS'),
    ('orphan','INVALID_SAVED_PATH_KEY'),
    ('gap','SAVED_PATH_LINK_INDEX_NOT_CONTIGUOUS'),
    ('break','DISCONNECTED_OFFICIAL_PATH_LINK_SEQUENCE')])
def test_stream_fails_closed_without_route_fabrication(tmp_path,damage,expected):
    pp,ll=route_rows()
    if damage=='missing_inter': ll=[x for x in ll if x['PathIndex']!=1]
    if damage=='orphan': ll=[dict(ll[0],Index=1,PathIndex=0)]+ll
    if damage=='gap': ll[1]=dict(ll[1],Index=5)
    if damage=='break': ll[1]=dict(ll[1],FromNodeNo=99999)
    c=ActualSequenceRouteCollector([profile()],SupplyPolicy(),'parent',[A,P,B,C,T],db_path=tmp_path/'bad.sqlite')
    try:
        with pytest.raises(SupplyContractError, match=expected):
            c.consume_stream(pp,iter(ll),{'code':'NATIVE_CW'})
    finally:
        c.close()


def run_full_synthetic_bounded(tmp_path, intrazonal=0, different_offdiag=0):
    v=exporter_visum()
    pp,ll=route_rows()
    raw=raw_hierarchical()
    bounded=BoundedHierarchical(raw)
    v.Workbench.Lists.CreatePrTPathLinkList=lambda:bounded
    # Synthetic demand matrices are 2x2; only offdiag is physically assigned.
    mat=v.Net.DemandSegments.items[0].ODMatrix
    mat.values[0,0]=intrazonal
    mat.values[0,1]=1000+different_offdiag
    cfg={'path_export_dsegs':['NATIVE_CW'],'mutable_dsegs':[],
         'require_all_path_export_dsegs':True,'require_verified_bounded_pathlink_com':True,
         'pathlink_page_size':3, 'path_export_fail_fast':True}
    collector=ActualSequenceRouteCollector([profile()],SupplyPolicy(min_geh=1,min_residual=1),
        'parent',[A,P,B,C,T],db_path=tmp_path/'store.sqlite')
    try:
        if different_offdiag:
            with pytest.raises(RuntimeError,match='parity rejected'):
                rt.export_actual_paths_and_build_incidence(v,tmp_path,cfg,[profile()],[],
                    route_batch_callback=collector.consume,build_incidence=False)
        else:
            _,summary=rt.export_actual_paths_and_build_incidence(v,tmp_path,cfg,[profile()],[],
                route_batch_callback=collector.consume,build_incidence=False)
            assert summary['dseg_path_volume_parity_passes'] is True
            assert summary['pathlink_rows']==7
            assert summary['dseg_complete_count']==1
            assert collector.finish()['profile_parity'][0]['actual_path_flow']==600
        with (tmp_path/'03D_DSEG_PATH_VOLUME_PARITY.csv').open(encoding='utf-8-sig') as f:
            parity=list(csv.DictReader(f,delimiter=';'))[0]
        assert float(parity['matrix_diagonal_intra_zonal']) == intrazonal
        assert float(parity['matrix_interzonal_sum']) == 1000+different_offdiag
        assert float(parity['saved_path_interzonal_volume_sum']) == 1000
        assert bounded.unbounded_calls==0
    finally:
        collector.close()


def test_full_export_streams_and_offdiagonal_parity_works(tmp_path):
    run_full_synthetic_bounded(tmp_path,intrazonal=400)


def test_full_export_fails_if_actual_interzonal_demand_mismatches(tmp_path):
    run_full_synthetic_bounded(tmp_path,intrazonal=400,different_offdiag=300)


def test_large_page_com_error_falls_back_only_to_proven_80():
    obj=BoundedHierarchical([list(raw_hierarchical()[0]) for _ in range(175)])
    ole=obj._oleobj_
    original=ole.Invoke
    def invoke(memid,lcid,kind,asmethod,first,last):
        if last-first+1>80:
            raise RuntimeError('SIMULATED_COM_PAGE_TOO_LARGE')
        return original(memid,lcid,kind,asmethod,first,last)
    ole.Invoke=invoke
    rows=list(rt.iter_prt_pathlink_bounded(obj,KEYS,page_size=256,require_verified=True))
    assert len(rows)==175
    assert ole.calls==[(1,80),(81,160),(161,240)]
    assert obj.unbounded_calls==0


def test_matrix_readback_does_not_hide_invalid_diagonal():
    v=exporter_visum()
    ds=rt.list_dsegs(v)[0]
    ds['object'].ODMatrix.values[0,0]=float('nan')
    with pytest.raises(RuntimeError,match='INVALID_FINITE'):
        rt.matrix_interzonal_authority(ds)


def test_live_15p_smoke_script_writes_beside_exact_loaded_ver(tmp_path):
    import importlib
    from conftest import FakeAttr
    mod=importlib.import_module('R1_15A2_15Q_BOUNDED_PATHLINK_THROUGHPUT_SMOKE')
    v=exporter_visum()
    v.IO=FakeAttr(CurrentVersionFile=str(tmp_path/'model.ver'))
    obj=BoundedHierarchical(raw_hierarchical())
    v.Workbench.Lists.CreatePrTPathLinkList=lambda:obj
    result=mod.run(v)
    assert result['status']=='SAMPLE_PASSED'
    assert result['apply'] is False and result['writes_to_visum'] is False
    assert result['results'][0]['raw_rows']==9
    assert result['results'][1]['raw_rows']==9
    root=tmp_path/'R1_15A2_15Q_PATHLINK_PERFORMANCE'
    assert len(list(root.glob('RUN_*/15Q_PATHLINK_THROUGHPUT_SMOKE.json')))==1
    assert obj.unbounded_calls==0


def test_shipped_design_config_keeps_apply_and_gap_closed():
    p=Path(__file__).resolve().parents[1]/'R1_15A2_CONFIG_V2_3_7.json'
    data=json.loads(p.read_text(encoding='utf-8'))
    assert data['apply'] is False
    assert data['supply']['assignment_operations']==[]
    assert data['supply']['gap_readback']['maximum_gap']==0.005
    assert data['require_verified_bounded_pathlink_com'] is True
    assert data['path_export_fail_fast'] is True
    assert data['dseg_path_volume_parity_basis']=='OFFDIAGONAL_INTERZONAL'

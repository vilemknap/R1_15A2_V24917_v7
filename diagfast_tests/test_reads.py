import copy
import math
from pathlib import Path
from collections import Counter
from types import SimpleNamespace
import pytest
import r1_15a2_diagfast_v1 as df
from fakes import make12,Matrix,Coll,Attr,add_matrices


def compute12(env,v):
    probes=[];manifest=env['load_manifest']();idx=env['read_link_index'](v,probes)
    cls=env['read_countlocations'](v)
    qa=env['verify_live_authority'](manifest,cls,idx)
    rows=env['build_detail_rows'](v,manifest,idx,cls)
    pairs,actions=env['add_pair_and_diag'](rows)
    return rows,pairs,actions,probes,qa

@pytest.mark.parametrize('bulk',[True,False])
def test_all488_profiles_exact_and_sparse(tmp_path,bulk):
    v,legacy,m,c=make12(tmp_path,extra=2000,bulk=bulk)
    expected=compute12(legacy,v);legacy_calls=c['AttValue'];c.clear()
    fast=df.reference_namespace('12D',tmp_path)
    p=df.Profile('12D','FAST_EXACT');df.configure_namespace(fast,'12D','FAST_EXACT',p)
    actual=compute12(fast,v)
    assert actual==expected
    assert len(actual[0])==488
    if bulk:
        assert p.notes['full_link_rows_read']<=615
        assert c['AttValue']<legacy_calls
    else:
        assert p.notes['identity_backend']=='LEGACY_FULL_LINK_READER'
    assert bool(p.fallbacks)==(not bulk)
    assert actual[3]==expected[3]

@pytest.mark.parametrize('bad',[None,-1,float('nan'),float('inf'),'nonsense','',True,KeyError('missing')])
def test_required_volume_not_zeroed(tmp_path,bad):
    v,env,m,c=make12(tmp_path,extra=2)
    k=df.requested_keys(m)[0];obj=next(o for o in v.Net.Links.items if tuple(o.a[x] for x in ('NO','FROMNODENO','TONODENO'))==k)
    obj.a['VOLVEH_DSEG(NATIVE_CW,AP)']=bad
    for backend in ('LEGACY','FAST_EXACT'):
        e=df.reference_namespace('12D',tmp_path);df.configure_namespace(e,'12D',backend,df.Profile('12D',backend))
        with pytest.raises(RuntimeError,match='REQUIRED_PASSENGER_VOLUME_UNREADABLE'):compute12(e,v)


def test_zero_volume_valid_and_aliases_preserved(tmp_path):
    v,env,m,c=make12(tmp_path,extra=3)
    for o in v.Net.Links.items:
        o.a['VOLVEH_DSEG(NATIVE_CW,AP)']=0.0
        o.a['RouteNo']=o.a.pop('ROADNO')
        o.a['VOLVEH_TSYS(C_NOT,AP)']=o.a.pop('VOLVEH_TSYS(C_noT,AP)')
    expected=compute12(env,v)
    f=df.reference_namespace('12D',tmp_path);df.configure_namespace(f,'12D','FAST_EXACT',df.Profile('12D','FAST_EXACT'))
    assert compute12(f,v)==expected

@pytest.mark.parametrize('field,value',[('R1_OBS_RPDI',10000000),('R1_WEIGHT',.123),('LINKNO',0),('R1_ACTIVE',0),('R1_ROLE','VALIDATION')])
def test_live_authority_mismatch_stays_error(tmp_path,field,value):
    v,env,m,c=make12(tmp_path,extra=0);v.Net.CountLocations.items[0].a[field]=value
    for backend in ('LEGACY','FAST_EXACT'):
        e=df.reference_namespace('12D',tmp_path);df.configure_namespace(e,'12D',backend,df.Profile('12D',backend))
        with pytest.raises(RuntimeError):compute12(e,v)


def test_corrupt_authority_sha_fails(tmp_path):
    v,env,m,c=make12(tmp_path,extra=0)
    (tmp_path/env['AUTHORITY_CSV_NAME']).write_text('bad')
    for backend in ('LEGACY','FAST_EXACT'):
        e=df.reference_namespace('12D',tmp_path);df.configure_namespace(e,'12D',backend,df.Profile('12D',backend))
        with pytest.raises(RuntimeError,match='SHA256 mismatch'):compute12(e,v)

@pytest.mark.parametrize('fault',['reverse','missing','duplicate','parallel','wrongkey','bulkcoverage'])
def test_identity_errors_failclosed(tmp_path,fault):
    v,env,m,c=make12(tmp_path,extra=0);wanted=df.requested_keys(m)
    k=wanted[0]
    if fault=='reverse':
        r=next(r for r in m.values() if r['observation_direction']=='BOTH')
        k=(int(r['current_link_no']),int(r['current_to_node_no']),int(r['current_from_node_no']))
    if fault in ('reverse','missing'):
        v.Net.Links.items=[o for o in v.Net.Links.items if tuple(o.a[x] for x in ('NO','FROMNODENO','TONODENO'))!=k]
    if fault=='duplicate':v.Net.Links.items.append(v.Net.Links.items[0])
    if fault=='parallel':
        a=dict(v.Net.Links.items[0].a);a['NO']+=9999999;v.Net.Links.items.append(Attr(a))
    if fault=='wrongkey':v.Net.Links.ItemByKey=lambda *a:Attr(NO=99,FROMNODENO=99,TONODENO=99)
    if fault=='bulkcoverage':
        original=v.Net.Links.GetMultiAttValues
        v.Net.Links.GetMultiAttValues=lambda a,*b:original(a,*b)[:-1] if a=='NO' else original(a,*b)
    f=df.reference_namespace('12D',tmp_path);p=df.Profile('12D','FAST_EXACT');df.configure_namespace(f,'12D','FAST_EXACT',p)
    with pytest.raises(RuntimeError):compute12(f,v)
    assert not p.fallbacks


def test_first_network_probe_is_preserved(tmp_path):
    v,e,m,c=make12(tmp_path,extra=1)
    del v.Net.Links.items[0].a['VOLVEH_TSYS(C,AP)']
    expected=compute12(e,v)
    f=df.reference_namespace('12D',tmp_path);df.configure_namespace(f,'12D','FAST_EXACT',df.Profile('12D','FAST_EXACT'))
    assert compute12(f,v)==expected
    assert any(r['status']=='MISSING_OR_BLANK_ON_SAMPLE' for r in expected[3])


def test_matrix_cache_exact_immutable_alias_and_scoped(tmp_path):
    e=df.reference_namespace('11D',tmp_path);f=df.reference_namespace('11D',tmp_path)
    p=df.Profile('11D','FAST_EXACT');df.configure_namespace(f,'11D','FAST_EXACT',p)
    values=[[None,float('nan'),float('inf'),-1.0,0.0,1.23456789],[1,2,3,4,5,6]]
    mat=Matrix(9101,values);cl=[[0,1,5,100,200,201],[0,15,25,50,100,120]]
    bins=e['TIME_BINS_DIAG']
    a=e['compute_matrix_distribution'](mat,cl,bins,condition_low=0,condition_high=200)
    b=f['compute_matrix_distribution'](mat,cl,bins,condition_low=0,condition_high=200)
    assert a==b
    assert e['matrix_total'](mat)==f['matrix_total'](mat)
    assert f['matrix_inventory_row'](Matrix(9101,values))==e['matrix_inventory_row'](Matrix(9101,values))
    vals,_=f['read_matrix_values'](mat)
    with pytest.raises(TypeError):vals[0][0]=9
    assert p.matrix_reads=={'9101':1}
    # New helper invocation after TG/TD/rollback/restart MUST observe fresh values.
    for label in ('TG','TD','ROLLBACK','RESTART','NEW_VERSION','PATH_EPOCH'):
        mat.values=[[10.0,20.0]]
        fresh=df.reference_namespace('11D',tmp_path)
        df.configure_namespace(fresh,'11D','FAST_EXACT',df.Profile('11D','FAST_EXACT'))
        assert fresh['matrix_total'](mat)==(30.0,0,0)

@pytest.mark.parametrize('value',[0,1,5,15,25,50,100,100.00000000001,110,120,199.9999,200,200.00000000001,1000])
def test_exact_bins_and_dist_time_not_confused(tmp_path,value):
    e=df.reference_namespace('11D',tmp_path);f=df.reference_namespace('11D',tmp_path)
    df.configure_namespace(f,'11D','FAST_EXACT',df.Profile('11D','FAST_EXACT'))
    mat=Matrix(9101,[[7.0]])
    for bins,low,high in ((e['DIST_BINS_0_100'],0,100),(e['LONG_BINS_100_200'],100,200),(e['TIME_BINS_DIAG'],None,None)):
        assert e['compute_matrix_distribution'](mat,[[value]],bins,low,high)==f['compute_matrix_distribution'](mat,[[value]],bins,low,high)

@pytest.mark.parametrize('rows,cl',[([[1,2]],[[1]]),([[1]],[[1],[2]])])
def test_dimension_errors_remain(tmp_path,rows,cl):
    for backend in ('LEGACY','FAST_EXACT'):
        e=df.reference_namespace('11D',tmp_path);df.configure_namespace(e,'11D',backend,df.Profile('11D',backend))
        with pytest.raises(e['Step11dError'],match='mismatch'):
            e['compute_matrix_distribution'](Matrix(9101,rows),cl,e['DIST_BINS_0_100'])


def test_no_com_write_via_proxy():
    p=df.ReadOnlyProxy(SimpleNamespace(SetAttValue=lambda *a:None),df.Profile('X','LEGACY'))
    for name in ('SetAttValue','Execute','SaveVersion','LoadVersion','AddUserDefinedAttribute','Remove','Delete'):
        with pytest.raises(df.ReadOnlyViolation):getattr(p,name)
    with pytest.raises(df.ReadOnlyViolation):p.ACTIVE=0

class Busy(Exception):
    hresult=-2147418111

def test_bounded_read_retry_and_nontransient_no_retry():
    class Read:
        def __init__(self):self.n=0
        def AttValue(self,a):
            self.n+=1
            if self.n<3:raise Busy('busy')
            return 42
    o=Read();prof=df.Profile('X','LEGACY')
    p=df.ReadOnlyProxy(o,prof,{'enabled':True,'max_attempts':3,'initial_delay_seconds':0,'max_delay_seconds':0})
    assert p.AttValue('NO')==42 and o.n==3 and prof.counts['com_busy_retries']==2
    class Bad:
        def __init__(self):self.n=0
        def AttValue(self,a):self.n+=1;raise ValueError('invalid')
    o=Bad();p=df.ReadOnlyProxy(o,df.Profile('X','FAST_EXACT'),{'enabled':True,'max_attempts':5})
    with pytest.raises(ValueError):p.AttValue('NO')
    assert o.n==1


def test_invalid_unselected_passenger_volume_not_hidden(tmp_path):
    v,env,m,c=make12(tmp_path,extra=2)
    v.Net.Links.items[1].a['VOLVEH_DSEG(NATIVE_CW,AP)']=-1.0
    for backend in ('LEGACY','FAST_EXACT'):
        e=df.reference_namespace('12D',tmp_path);df.configure_namespace(e,'12D',backend,df.Profile('12D',backend))
        with pytest.raises(RuntimeError,match='REQUIRED_PASSENGER_VOLUME_UNREADABLE'):compute12(e,v)


@pytest.mark.parametrize('bad_bulk',[None,'bad',[None],[(1,{})],[(None,7)],[(1,7),(1,7)]])
def test_malformed_bulk_values_never_become_technical_fallback(tmp_path,bad_bulk):
    v,e,m,c=make12(tmp_path,extra=2)
    original=v.Net.Links.GetMultiAttValues
    v.Net.Links.GetMultiAttValues=lambda attr,*args:bad_bulk if attr=='NO' else original(attr,*args)
    env=df.reference_namespace('12D',tmp_path);p=df.Profile('12D','FAST_EXACT')
    df.configure_namespace(env,'12D','FAST_EXACT',p)
    with pytest.raises(df.DiagFastError):compute12(env,v)
    assert p.fallbacks==[]

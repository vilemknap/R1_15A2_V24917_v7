import pytest
from types import SimpleNamespace
import r1_15a2_diagfast_v1 as df
from fakes import Matrix,Coll,Attr

@pytest.mark.parametrize('backend',['LEGACY','FAST_EXACT'])
def test_class_matrix_invalid_shape(backend,tmp_path):
    env=df.reference_namespace('11D',tmp_path);df.configure_namespace(env,'11D',backend,df.Profile('11D',backend))
    with pytest.raises(env['Step11dError'],match='681x681'):
        env['load_class_matrix'](Matrix(9001,[[1.0]]))

@pytest.mark.parametrize('fault',['none','negative','nan','inf'])
def test_class_matrix_normalization_preserved(tmp_path,fault):
    bad={'none':None,'negative':-1,'nan':float('nan'),'inf':float('inf')}[fault]
    values=[[0.0,100.0],[bad,200.0]];mat=Matrix(9001,values)
    results=[]
    for backend in ('LEGACY','FAST_EXACT'):
        e=df.reference_namespace('11D',tmp_path);e['EXPECTED_ZONE_COUNT']=2
        df.configure_namespace(e,'11D',backend,df.Profile('11D',backend))
        results.append(e['load_class_matrix'](mat))
    assert results[0]==results[1]

@pytest.mark.parametrize('missing',['TIME','LONG','SCHOOL','ALL','ZERO'])
def test_missing_matrices_weights_and_time_fallback_preserved(tmp_path,missing):
    matrices=[Matrix(9001,[[10.0]],code='R1_OSRM_DIST_KM')]
    for no in range(9101,9118):
        if missing=='LONG' and 9111<=no<=9115:continue
        if missing=='SCHOOL' and no==9117:continue
        matrices.append(Matrix(no,[[0.0 if missing=='ZERO' else 1.0]]))
    if missing=='ALL':matrices=[]
    v=SimpleNamespace(Net=SimpleNamespace(Matrices=Coll(matrices)))
    outputs=[]
    for backend in ('LEGACY','FAST_EXACT'):
        e=df.reference_namespace('11D',tmp_path);df.configure_namespace(e,'11D',backend,df.Profile('11D',backend))
        w=e['component_weight_rows'](v,e['WORK_SCHOOL_COMPONENTS'],'WORK_SCHOOL')
        long_inv=[e['matrix_inventory_row'](e['matrix_by_no'](v,no),no) for no in range(9111,9116)]
        tm,why=e['find_time_matrix'](v)
        outputs.append((w,long_inv,tm.a['NO'] if tm else None,why))
    assert outputs[0]==outputs[1]
    if missing=='TIME':assert outputs[0][2:]==(9001,'FALLBACK_MATRIX_NO_9001')
    if missing in ('ALL','ZERO'):assert all(r['weight_policy'].startswith('FALLBACK') for r in outputs[0][0])

@pytest.mark.parametrize('transition',['TG','TD','ROLLBACK','LOAD_RESTART','PATH_EPOCH'])
def test_invocation_does_not_reuse_previous_values(tmp_path,transition):
    obj=Matrix(9101,[[1.0]])
    def invoke():
        e=df.reference_namespace('11D',tmp_path)
        df.configure_namespace(e,'11D','FAST_EXACT',df.Profile('11D','FAST_EXACT'))
        return e['matrix_total'](obj)
    assert invoke()[0]==1.0
    obj.values=[[5.0]]
    assert invoke()[0]==5.0
    assert obj.getvalues==2

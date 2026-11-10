"""Run-script entry reads existing skims without executing or changing controls."""
import ast
import importlib
from pathlib import Path
import numpy as np
import pytest
from test_v24917_standalone_td_utilities import native
from test_v24917_component_td_utilities import model


@pytest.fixture
def step(native,tmp_path):
    e=native
    e.s.setup_utilities(e.m.v,tmp_path/'setup')
    ratios=dict(NATIVE_CW=1.2,NATIVE_CW_NOT=2.,NATIVE_CS=1.5,NATIVE_CS_NOT=3.,NATIVE_CL=1.8)
    for matrix in e.m.mats.values():
        if matrix.attrs['CODE']=='TTC':matrix.values[:]=300.*ratios[matrix.attrs['DSEGCODE']]
    def forbidden(*args,**kwargs):raise AssertionError('RUN_SCRIPT_MUST_NOT_EXECUTE_OR_CHANGE_CONTROLS')
    e.m.v.Procedures.Execute=forbidden
    e.m.v.Net.AddMatrix=forbidden
    e.m.v.Net.RemoveMatrix=forbidden
    for op in e.ops:op.SetAttValue=forbidden
    for params,singles in e.controls:
        params.SetAttValue=forbidden
        for single in singles.values():single.SetAttValue=forbidden
    e.update=importlib.import_module('R1_UPDATE_TD_UTILITIES_FROM_SKIMS')
    return e


def test_step_uses_existing_skims_without_procedure_execution(step,tmp_path):
    e=step
    before={no:m.values.copy() for no,m in e.m.mats.items() if no not in e.update.UTILITY_NOS}
    rec=e.update.run(e.m.v,tmp_path)
    assert rec['status']=='UPDATED_READY_FOR_FOLLOWING_TD'
    assert rec['freshness_certified'] is False
    assert not any(rec[k] for k in ('td_executed','assignment_executed','skims_executed','procedure_controls_changed'))
    assert e.m.mats[9700].values[0,1]==pytest.approx(12.)
    assert e.m.mats[9705].values[0,1]==pytest.approx(18.125)
    assert e.m.mats[9710].values[0,1]==pytest.approx(14.)
    for no,a in before.items():assert np.array_equal(e.m.mats[no].values,a)
    assert not e.calls


def test_step_needs_no_paths_or_dis_after_assignment_results_were_deleted(step,tmp_path):
    e=step
    for no in list(e.m.mats):
        if e.m.mats[no].attrs['CODE']=='DIS':del e.m.mats[no]
    e.update.run(e.m.v,tmp_path)
    assert e.m.mats[9700].values[0,1]==pytest.approx(12.)


@pytest.mark.parametrize('failure',['missing','duplicate','nan','shape','zero_pair','wrong_type'])
def test_invalid_time_data_cannot_mutate_inputs(step,tmp_path,failure):
    e=step
    mat=next(m for m in e.m.mats.values() if m.attrs['CODE']=='TTC')
    if failure=='missing':del e.m.mats[mat.attrs['NO']]
    elif failure=='duplicate':
        import copy
        duplicate=copy.deepcopy(mat);duplicate.attrs['NO']=12000;e.m.mats[12000]=duplicate
    elif failure=='nan':mat.values[0,1]=np.nan
    elif failure=='shape':mat.values=np.zeros((2,2))
    elif failure=='zero_pair':mat.values[:]=0
    else:mat.attrs['MATRIXTYPE']='MATRIXTYPE_DEMAND'
    before={no:e.m.mats[no].values.copy() for no in e.update.UTILITY_NOS}
    with pytest.raises(e.update.SupplyContractError):e.update.run(e.m.v,tmp_path)
    for no,a in before.items():assert np.array_equal(e.m.mats[no].values,a)


def test_utility_binding_must_already_be_prepared(step,tmp_path):
    e=step;e.m.parameters['SCHOOL'].raw='Matrix([NO]=9002)'
    with pytest.raises(e.update.SupplyContractError,match='SETUP_REQUIRED'):
        e.update.run(e.m.v,tmp_path)
    assert all(e.m.mats[no].writes==1 for no in e.update.UTILITY_NOS)


def test_partial_write_restores_owned_values(step,tmp_path):
    e=step;before={no:e.m.mats[no].values.copy() for no in e.update.UTILITY_NOS}
    e.m.mats[9704].fail_once=True
    with pytest.raises(RuntimeError,match='PARTIAL_MATRIX_WRITE'):e.update.run(e.m.v,tmp_path)
    for no,a in before.items():assert np.array_equal(e.m.mats[no].values,a)


def test_changed_source_during_update_prevents_publication_and_restores_utilities(step,tmp_path):
    e=step;matrix=e.m.mats[9700];original=matrix.SetValues
    ttc=next(m for m in e.m.mats.values() if m.attrs['CODE']=='TTC')
    def write(a):
        original(a)
        if matrix.writes==2:ttc.values[0,1]+=1.
    matrix.SetValues=write
    with pytest.raises(e.update.SupplyContractError,match='SOURCES_CHANGED_DURING_UPDATE'):
        e.update.run(e.m.v,tmp_path)
    for no in e.update.UTILITY_NOS:assert np.array_equal(e.m.mats[no].values,e.m.base)


def test_step_has_no_reentrant_execution_or_project_imports(step):
    tree=ast.parse(Path(step.update.__file__).read_text())
    assert not any(isinstance(n,ast.Attribute) and n.attr in ('Execute','SetAttValue','AddMatrix','RemoveMatrix')
                   for n in ast.walk(tree))
    imports=[n.module or '' for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)]
    imports += [a.name for n in ast.walk(tree) if isinstance(n,ast.Import) for a in n.names]
    assert all(not x.lower().startswith('r1') for x in imports)

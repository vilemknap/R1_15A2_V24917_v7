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


@pytest.fixture
def saved_step(step,tmp_path):
    from types import SimpleNamespace
    model=tmp_path/'cold model.ver';model.write_bytes(b'OFFLINE MODEL IDENTITY ONLY')
    step.m.v.IO=SimpleNamespace(CurrentVersionFile=str(model))
    step.state_file=model.with_name(model.name+'.R1_TD_UTILITY_FIRST_PASS.json')
    return step


def clear_times(e,how):
    for no in list(e.m.mats):
        matrix=e.m.mats[no]
        if matrix.attrs['CODE'] in ('TTC','TT0'):
            if how=='absent':del e.m.mats[no]
            else:matrix.values[:]=0.


@pytest.mark.parametrize('how',['absent','zero'])
def test_first_cold_pass_uses_base_once_then_requires_real_time_data(saved_step,tmp_path,how):
    import json
    e=saved_step
    time_matrices={no:matrix for no,matrix in e.m.mats.items() if matrix.attrs['CODE'] in ('TTC','TT0')}
    original_times={no:m.values.copy() for no,m in time_matrices.items()}
    clear_times(e,how)
    writes=sum(matrix.writes for matrix in e.m.mats.values())
    report=e.update.run(e.m.v,tmp_path/'first',start_mode='COLD_START_ONCE')
    assert report['status']=='BOOTSTRAP_BASE_UTILITIES_READY' and report['written_matrices']==[]
    assert not report['freshness_certified']
    assert sum(matrix.writes for matrix in e.m.mats.values())==writes
    # No synthetic time values are introduced for a missing first assignment.
    assert json.loads(e.state_file.read_text())['first_entry']=='BOOTSTRAP_CONSUMED'
    with pytest.raises(e.update.SupplyContractError,match='COLD_START_ALREADY_USED'):
        e.update.run(e.m.v,tmp_path/'second',start_mode='COLD_START_ONCE')
    for no,m in time_matrices.items():
        m.values=original_times[no].copy();e.m.mats[no]=m
    normal=e.update.run(e.m.v,tmp_path/'third',start_mode='COLD_START_ONCE')
    assert normal['status']=='UPDATED_READY_FOR_FOLLOWING_TD'
    assert e.m.mats[9700].values[0,1]==pytest.approx(12.)
    assert json.loads(e.state_file.read_text())['first_entry']=='BOOTSTRAP_CONSUMED'


def test_valid_times_close_bootstrap_window_even_when_utilities_never_changed(saved_step,tmp_path):
    import json
    e=saved_step
    for m in e.m.mats.values():
        if m.attrs['CODE'] in ('TTC','TT0'):m.values[:]=300.
    e.update.run(e.m.v,tmp_path/'valid',start_mode='COLD_START_ONCE')
    assert json.loads(e.state_file.read_text())['first_entry']=='TIME_DATA_SEEN'
    assert all(np.array_equal(e.m.mats[no].values,e.m.base) for no in e.update.UTILITY_NOS)
    clear_times(e,'zero')
    with pytest.raises(e.update.SupplyContractError,match='COLD_START_ALREADY_USED'):
        e.update.run(e.m.v,tmp_path/'lost',start_mode='COLD_START_ONCE')


def test_cold_start_never_resets_corrected_utilities(saved_step,tmp_path):
    e=saved_step;clear_times(e,'absent');e.m.mats[9700].values[0,1]+=1.
    with pytest.raises(e.update.SupplyContractError,match='UNCORRECTED_M9002_COPIES'):
        e.update.run(e.m.v,tmp_path,start_mode='COLD_START_ONCE')
    assert e.m.mats[9700].values[0,1]==11. and not e.state_file.exists()


@pytest.mark.parametrize('failure',['partial_sources','nan','wrong_type','partially_computed'])
def test_broken_time_inputs_are_not_a_cold_start_exception(saved_step,tmp_path,failure):
    e=saved_step;clear_times(e,'zero')
    ttc=next(m for m in e.m.mats.values() if m.attrs['CODE']=='TTC')
    if failure=='partial_sources':del e.m.mats[ttc.attrs['NO']]
    elif failure=='nan':ttc.values[0,1]=np.nan
    elif failure=='wrong_type':ttc.attrs['MATRIXTYPE']='MATRIXTYPE_DEMAND'
    else:ttc.values[0,1]=1.
    with pytest.raises(e.update.SupplyContractError):
        e.update.run(e.m.v,tmp_path,start_mode='COLD_START_ONCE')
    assert not e.state_file.exists()


@pytest.mark.parametrize('failure',['corrupt','scope_changed'])
def test_invalid_or_mismatched_marker_cannot_authorize_bootstrap(saved_step,tmp_path,failure):
    import json
    e=saved_step;clear_times(e,'absent')
    e.update.run(e.m.v,tmp_path/'first',start_mode='COLD_START_ONCE')
    if failure=='corrupt':e.state_file.write_text('{broken')
    else:
        payload=json.loads(e.state_file.read_text());payload['zone_order_sha256']='wrong'
        e.state_file.write_text(json.dumps(payload))
    with pytest.raises(e.update.SupplyContractError,match='STATE_INVALID_OR_DIFFERENT_MODEL'):
        e.update.run(e.m.v,tmp_path/'second',start_mode='COLD_START_ONCE')


def test_cold_start_requires_saved_model_identity_before_using_exception(step,tmp_path):
    clear_times(step,'absent')
    with pytest.raises(step.update.SupplyContractError,match='SAVED_VERSION_IDENTITY_REQUIRED'):
        step.update.run(step.m.v,tmp_path,start_mode='COLD_START_ONCE')


def test_state_file_failure_cannot_modify_utilities(saved_step,tmp_path,monkeypatch):
    e=saved_step
    def fail(*args):raise OSError('STATE_DISK_WRITE_REFUSED')
    monkeypatch.setattr(e.update,'record_first_pass',fail)
    with pytest.raises(OSError,match='STATE_DISK_WRITE_REFUSED'):
        e.update.run(e.m.v,tmp_path,start_mode='COLD_START_ONCE')
    assert all(np.array_equal(e.m.mats[no].values,e.m.base) for no in e.update.UTILITY_NOS)


def test_strict_mode_keeps_missing_time_error(saved_step,tmp_path):
    e=saved_step;clear_times(e,'absent')
    with pytest.raises(e.update.SupplyContractError,match='MISSING_TIME_SKIMS'):
        e.update.run(e.m.v,tmp_path,start_mode='STRICT')
    assert not e.state_file.exists()

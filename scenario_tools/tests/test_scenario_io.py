import copy
import csv
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('scenario_io_tested',ROOT/'scenario_io.py')
io=importlib.util.module_from_spec(spec);spec.loader.exec_module(io)

class Matrix:
    def __init__(self,no,arr,code='',source='DATA'):
        self.no=no;self.arr=arr.copy();self.code=code;self.source=source;self.calls=0;self.fail_once=False;self.corrupt_once=False
    def AttValue(self,key):return {'NO':self.no,'CODE':self.code,'DATASOURCETYPE':self.source}[key]
    def GetValues(self):return self.arr.copy()
    def SetValues(self,a,add):
        assert isinstance(a,np.ndarray) and a.dtype==np.float64 and a.flags.c_contiguous and add is False
        self.calls+=1;self.arr=a.copy()
        if self.corrupt_once:self.corrupt_once=False;self.arr[0,0]+=1
        if self.fail_once:self.fail_once=False;self.arr[0,0]+=1;raise RuntimeError('partial matrix mutation')

class Collection:
    def __init__(self,items):self.items=items
    @property
    def GetAll(self):return list(self.items.values())
    def ItemByKey(self,key):return self.items[key]

class Zones:
    def __init__(self,n):
        self.order=list(reversed(range(1,n+1)));self.key={no:1000+no for no in self.order}
        self.data={attr:{no:1.0 for no in self.order} for attr in io.RAW_ATTRS+io.CAL_ATTRS}
        self.calls=[];self.fail_attr=None
    def GetMultiAttValues(self,attr,active):
        if attr=='NO':return [[self.key[no],no] for no in self.order]
        return [[self.key[no],self.data[attr][no]] for no in self.order]
    def SetMultiAttValues(self,attr,rows,active):
        assert active is False;self.calls.append(attr);inverse={v:k for k,v in self.key.items()}
        for key,value in rows:self.data[attr][inverse[key]]=value
        if self.fail_attr==attr:self.fail_attr=None;raise RuntimeError('partial zone mutation')

class Gravity:
    def __init__(self):self.data={'PARA_A':1.,'PARA_B':2.,'PARA_C':-1.}
    def AttValue(self,key):return self.data[key]

class TD:
    def __init__(self):self.gravity={code:SimpleNamespace(GravitationParameters=Gravity()) for code in io.STRATA}
    def AttValue(self,key):return ','.join(io.STRATA)
    def TripDistributionDStratParameters(self,code):return self.gravity[code]

class Op:
    def __init__(self,typ):self.typ=typ;self.TripDistributionParameters=TD();self.PrTAssignmentParameters=SimpleNamespace(AttValue=lambda key:','.join(io.FINAL_DSEGS))
    def AttValue(self,key):return {'OPERATIONTYPE':self.typ,'ACTIVE':True}[key]

def fake(n=681):
    zero=np.zeros((n,n));lnv=Matrix(7001,zero,'LNV');nv=Matrix(7002,zero,'NV')
    z=Zones(n);mats={7001:lnv,7002:nv};ds={'LNV':SimpleNamespace(ODMatrix=lnv),'NV':SimpleNamespace(ODMatrix=nv)}
    for j,code in enumerate(io.PASSENGER_DSEGS):
        no=9305 if code=='NATIVE_CL' else 8000+j
        mat=Matrix(no,zero,code);mats[no]=mat;ds[code]=SimpleNamespace(ODMatrix=mat)
    for no in list(range(9111,9116))+list(range(9291,9296)):mats[no]=Matrix(no,zero)
    mats[9697]=Matrix(9697,np.full((n,n),100.),'R1_OSRM_DIST_KM')
    return SimpleNamespace(IO=SimpleNamespace(CurrentVersionFile=r'C:\scenarios\R1_2040_CALIB.ver'),
                           Procedures=SimpleNamespace(Operations=Collection({1:Op(45),2:Op(46),3:Op(101)})),
                           Net=SimpleNamespace(Zones=z,Matrices=Collection(mats),DemandSegments=Collection(ds),
                                               Links=SimpleNamespace(GetMultiAttValues=lambda *a:[[7,-2.],[9,3.]])))

@pytest.fixture
def year_folder(tmp_path):
    folder=tmp_path/'2040';folder.mkdir()
    for name in ['SCENARIO.json','ZONE_RAW_ATTRS.csv','LNV_MC_MEAN_ROUNDED.csv','NV_MC_MEAN_ROUNDED.csv']:
        (folder/name).write_bytes((ROOT/'2040'/name).read_bytes())
    return folder

def test_import_keys_rounding_and_calibrated_parameters(year_folder):
    v=fake();cal={a:copy.deepcopy(v.Net.Zones.data[a]) for a in io.CAL_ATTRS}
    stamp=io.run_import(v,year_folder)
    assert stamp['status']=='PASS_IMPORTED' and stamp['freight_totals']=={'LNV':30922.,'NV':43560.}
    assert all(v.Net.Zones.data[a]==cal[a] for a in cal)
    assert set(v.Net.Zones.calls)<=set(io.RAW_ATTRS)
    arr=v.Net.Matrices.items[7001].arr
    assert np.array_equal(arr,np.rint(arr))
    cfg=io.read_config(year_folder);order,keys=io.zone_order(v);target,freight=io.input_data(year_folder,cfg,order)
    assert all(v.Net.Zones.data[a][no]==(1. if val==0 else val) for a in target for no,val in target[a].items())
    assert np.array_equal(arr,freight['LNV'])
    assert list(keys.values())[0]!=order[0]  # COM row key differs from zone NO.

@pytest.mark.parametrize('kind',['zone','matrix','corrupt_readback'])
def test_partial_write_rollback_restores_every_owned_value(year_folder,kind):
    v=fake();before=copy.deepcopy(v.Net.Zones.data)
    if kind=='zone':v.Net.Zones.fail_attr='POP_ZP'
    elif kind=='matrix':v.Net.Matrices.items[7002].fail_once=True
    else:v.Net.Matrices.items[7002].corrupt_once=True
    with pytest.raises((RuntimeError,io.ScenarioError)):io.run_import(v,year_folder)
    assert v.Net.Zones.data==before
    assert not v.Net.Matrices.items[7001].arr.any() and not v.Net.Matrices.items[7002].arr.any()
    result=json.loads(next((year_folder/'logs').glob('*/RESULT.json')).read_text())
    assert result['status']=='FAILED_ROLLBACK_VERIFIED'
    assert not (year_folder/'IMPORT_CURRENT.json').exists()

def test_invalid_source_hash_before_any_write(year_folder):
    v=fake();(year_folder/'ZONE_RAW_ATTRS.csv').write_text('corrupt')
    with pytest.raises(io.ScenarioError,match='SHA256'):io.run_import(v,year_folder)
    assert not v.Net.Zones.calls and not v.Net.Matrices.items[7001].calls

@pytest.mark.parametrize('path',[r'C:\models\R1_2022.ver',r'C:\2040\R1_2022.ver',r'C:\models\R1_2025_2040.ver',''])
def test_wrong_or_unsaved_version_before_any_write(year_folder,path):
    v=fake();v.IO.CurrentVersionFile=path
    with pytest.raises(io.ScenarioError,match='SAVE_OPEN_MODEL'):io.run_import(v,year_folder)
    assert not v.Net.Zones.calls

def test_formula_freight_matrix_rejected_before_zone_write(year_folder):
    v=fake();v.Net.Matrices.items[7002].source='FORMULA'
    with pytest.raises(io.ScenarioError,match='NOT_DATA'):io.run_import(v,year_folder)
    assert not v.Net.Zones.calls and not v.Net.Matrices.items[7001].calls

def test_recompute_proof_blocks_stale_or_modified_export(year_folder,monkeypatch):
    v=fake();io.run_import(v,year_folder)
    with pytest.raises(FileNotFoundError):io.run_export(v,year_folder)
    def recalc(*args):
        v.Net.DemandSegments.ItemByKey('NATIVE_CF').ODMatrix.arr[0,1]=4.1234567
        return {'gap':0.001,'source':'MOCK_NATIVE_ASSIGNMENT'}
    monkeypatch.setattr(io,'native_recompute',recalc)
    proof=io.run_recompute(v,year_folder);assert proof['status']=='PASS_RECOMPUTED'
    result=io.run_export(v,year_folder)
    assert result['model_writes'] is False and len(result['outputs'])==3
    path=next(year_folder.glob('EXPORT_*/R1_2040_OA_CAL_WORK.mtx'))
    assert '681 680 4.123457' in path.read_text()
    v.Net.DemandSegments.ItemByKey('NATIVE_CF').ODMatrix.arr[0,1]+=1
    with pytest.raises(io.ScenarioError,match='MATRICES_CHANGED'):io.run_export(v,year_folder)

def test_failed_recompute_prevents_export(year_folder,monkeypatch):
    v=fake();io.run_import(v,year_folder)
    def fail(*args):raise RuntimeError('native failure')
    monkeypatch.setattr(io,'native_recompute',fail)
    with pytest.raises(RuntimeError,match='native failure'):io.run_recompute(v,year_folder)
    assert json.loads((year_folder/'RECOMPUTE_CURRENT.json').read_text())['status'].startswith('FAILED')
    with pytest.raises(io.ScenarioError,match='RECOMPUTE_REQUIRED'):io.run_export(v,year_folder)

def test_changed_raw_coeff_or_freight_blocks_recompute(year_folder,monkeypatch):
    v=fake();io.run_import(v,year_folder)
    v.Net.Zones.data['ADD_PROD_W'][1]=1.2
    with pytest.raises(io.ScenarioError,match='PARAMETERS_CHANGED'):io.run_recompute(v,year_folder)

def test_new_import_invalidates_old_recompute_proof(year_folder,monkeypatch):
    v=fake();io.run_import(v,year_folder);monkeypatch.setattr(io,'native_recompute',lambda *a:{'gap':0.001})
    io.run_recompute(v,year_folder);io.run_import(v,year_folder)
    with pytest.raises(io.ScenarioError,match='RECOMPUTE_REQUIRED'):io.run_export(v,year_folder)

def test_missing_excel_value_keeps_parent_not_zero(tmp_path):
    folder=tmp_path/'2025';folder.mkdir()
    for name in ['SCENARIO.json','ZONE_RAW_ATTRS.csv','LNV_MC_MEAN_ROUNDED.csv','NV_MC_MEAN_ROUNDED.csv']:
        (folder/name).write_bytes((ROOT/'2025'/name).read_bytes())
    v=fake();v.IO.CurrentVersionFile=r'C:\scenarios\R1_2025.ver';v.Net.Zones.data['NUM_PM'][11]=7654.
    stamp=io.run_import(v,folder)
    assert v.Net.Zones.data['NUM_PM'][11]==7654.
    fallbacks=json.loads((Path(stamp['log_folder'])/'FALLBACKS_KEPT_2022.json').read_text())
    assert any(r['No']==11 and r['attribute']=='NUM_PM' and r['kept_2022_value']==7654. for r in fallbacks)

def test_mask_no_upper_bound_and_component_parity():
    v=fake(2);cfg={'passenger_dsegs':io.PASSENGER_DSEGS}
    v.Net.Matrices.items[9697].arr=np.array([[10.,80.],[250.,1.]])
    for no in range(9291,9296):v.Net.Matrices.items[no].arr[1,0]=2.
    v.Net.Matrices.items[9305].arr[1,0]=10.
    fp,oa,_=io.fingerprint(v,cfg,[2,1]);assert oa[1,0]==10.
    v.Net.Matrices.items[9111].arr[0,0]=0.1
    with pytest.raises(io.ScenarioError,match='BELOW_80'):io.fingerprint(v,cfg,[2,1])

def test_duplicate_passenger_component_not_double_counted():
    v=fake(2);v.Net.DemandSegments.items[io.PASSENGER_DSEGS[1]]=v.Net.DemandSegments.items[io.PASSENGER_DSEGS[0]]
    with pytest.raises(io.ScenarioError,match='DUPLICATION'):io.fingerprint(v,{'passenger_dsegs':io.PASSENGER_DSEGS},[1,2])

@pytest.mark.parametrize('year',io.YEARS)
def test_all_five_real_input_packages_are_integral_and_keyed(year):
    cfg=io.read_config(ROOT/str(year));order=list(reversed(range(1,682)))
    target,freight=io.input_data(ROOT/str(year),cfg,order)
    assert all(set(rows)<=set(order) for rows in target.values())
    for code,arr in freight.items():
        assert np.array_equal(arr,np.rint(arr)) and arr.min()>=0
        assert float(cfg['freight'][code]['maximum_cell_rounding_delta'])<=0.5
    for action in ['01_IMPORT_ZONES_AND_FREIGHT','02_RECOMPUTE_TG_TD_AND_ASSIGNMENT','03_EXPORT_MATRICES']:
        assert (ROOT/str(year)/(action+'_'+str(year)+'.py')).exists()

def test_td_parameter_edit_detected_even_without_matrix_change(year_folder,monkeypatch):
    v=fake();io.run_import(v,year_folder);monkeypatch.setattr(io,'native_recompute',lambda *a:{'gap':0.001})
    io.run_recompute(v,year_folder)
    v.Procedures.Operations.items[2].TripDistributionParameters.gravity['5_SCHOOL'].GravitationParameters.data['PARA_C']=-2.
    with pytest.raises(io.ScenarioError,match='TD_SUPPLY_OR_OPERATIONS_CHANGED'):io.run_export(v,year_folder)

def test_export_failure_never_publishes_partial_set(year_folder,monkeypatch):
    v=fake();io.run_import(v,year_folder);monkeypatch.setattr(io,'native_recompute',lambda *a:{'gap':0.001})
    io.run_recompute(v,year_folder);original=io.write_matrix
    def fail(path,arr,order,year,label):
        if label=='LNV':raise OSError('export disk failure')
        return original(path,arr,order,year,label)
    monkeypatch.setattr(io,'write_matrix',fail)
    with pytest.raises(OSError,match='disk failure'):io.run_export(v,year_folder)
    assert not list(year_folder.glob('EXPORT_*'))

def test_unverified_rollback_requires_manual_reopen(year_folder):
    v=fake()
    def broken(a,add):raise RuntimeError('persistent COM failure')
    v.Net.Matrices.items[7002].SetValues=broken
    with pytest.raises(io.ScenarioError,match='ROLLBACK_UNVERIFIED_MANUAL_REOPEN'):io.run_import(v,year_folder)

@pytest.mark.parametrize('final',[20,28])
@pytest.mark.parametrize('gap',[0.001,0.01])
def test_native_recompute_uses_existing_mask_engine_and_checks_final_gap(year_folder,monkeypatch,gap,final):
    v=fake();project=ROOT.parent.resolve();seen=[];specs=[]
    rows=[{'no':1,'type':45,'active':True},{'no':2,'type':46,'active':True},{'no':final,'type':101,'active':True}]
    modules={
      'r1_15a2_long_post_td_mask_v24917':SimpleNamespace(execute_sequence=lambda adapter,folder,fn:seen.append(adapter.cfg)),
      'r1_15a2_com_compat':SimpleNamespace(operation_rows=lambda host:rows,TG=45,TD=46,ASSIGNMENT_PRT=101),
      'r1_15a2_supply_visum':SimpleNamespace(assignment_gap_evidence=lambda host,spec:specs.append(spec) or {'gap':gap}),
      'r1_15a2_procseq_roles_v24917':SimpleNamespace(live_position=lambda host,n:final if n==20 else n)}
    monkeypatch.setattr(io.importlib,'import_module',lambda name:modules[name])
    if gap>0.005:
        with pytest.raises(io.ScenarioError,match='GAP_ABOVE'):io.native_recompute(v,year_folder,list(range(1,682)),project)
    else:
        out=io.native_recompute(v,year_folder,list(range(1,682)),project)
        assert out['gap']==gap and out['final_assignment_position']==final
    assert seen[0]['supply']['assignment_operations'][0]['expected_dsegs']==io.FINAL_DSEGS
    assert seen[0]['supply']['assignment_operations'][0]['no']==20      # legacy role; the mask engine translates
    assert specs[0]['operation_no']==final


def test_native_recompute_fails_closed_when_final_role_unresolved(year_folder,monkeypatch):
    v=fake();project=ROOT.parent.resolve()
    def boom(host,n):raise RuntimeError('OPMAP1_ROLE_ASG_FINAL_FOUND_2')
    modules={
      'r1_15a2_long_post_td_mask_v24917':SimpleNamespace(execute_sequence=lambda *a:None),
      'r1_15a2_com_compat':SimpleNamespace(operation_rows=lambda host:[{'no':1,'type':45,'active':True},{'no':2,'type':46,'active':True}],TG=45,TD=46,ASSIGNMENT_PRT=101),
      'r1_15a2_supply_visum':SimpleNamespace(assignment_gap_evidence=lambda *a:{'gap':0.0}),
      'r1_15a2_procseq_roles_v24917':SimpleNamespace(live_position=boom)}
    monkeypatch.setattr(io.importlib,'import_module',lambda name:modules[name])
    with pytest.raises(io.ScenarioError,match='FINAL_ASSIGNMENT_ROLE_UNRESOLVED'):
        io.native_recompute(v,year_folder,list(range(1,682)),project)

@pytest.mark.parametrize('tampered',[False,True])
def test_package_hash_verification(tmp_path,monkeypatch,tampered):
    tool=tmp_path/'scenario_tools';tool.mkdir();payload=tool/'data.csv';payload.write_text('sealed\n')
    (tool/'SCENARIO_TOOLS_SHA256.json').write_text(json.dumps({'scenario_tools/data.csv':io.digest(payload.read_bytes())}))
    monkeypatch.setattr(io,'__file__',str(tool/'scenario_io.py'))
    if tampered:
        payload.write_text('changed\n')
        with pytest.raises(io.ScenarioError,match='PACKAGE_SHA256'):io.validate_package()
    else:io.validate_package()

def test_zero_or_error_falls_back_only_to_nonzero_reference():
    reference={a:{1:12.,2:0.,3:9.,4:20.,5:5.} for a in io.RAW_ATTRS}
    target={a:{1:0.,2:0.,3:0.00000001,4:30.} for a in io.RAW_ATTRS}
    effective,log=io.resolve_zonal_fallback(target,reference,[1,2,3,4,5])
    assert effective['POP_ZP']=={1:12.,2:0.,3:0.00000001,4:30.,5:5.}
    assert not any(r['No'] in [2,3,4] for r in log)
    assert {r['reason'] for r in log}=={'ZERO_FORECAST_REFERENCE_POSITIVE','INVALID_OR_MISSING_FORECAST'}

def test_nitra_and_small_population_zero_use_2022_values(year_folder):
    v=fake();v.Net.Zones.data['NUM_PM'][615]=62866.;v.Net.Zones.data['NUM_PM_SMEAR'][615]=81148.
    v.Net.Zones.data['POP_ZP'][641]=4.;v.Net.Zones.data['POP_ZP'][1]=0.
    stamp=io.run_import(v,year_folder)
    assert v.Net.Zones.data['NUM_PM'][615]==62866. and v.Net.Zones.data['NUM_PM_SMEAR'][615]==81148.
    assert v.Net.Zones.data['POP_ZP'][641]==4. and v.Net.Zones.data['POP_ZP'][1]==0.
    assert stamp['zero_fallback_cells']>0
    log=json.loads((Path(stamp['log_folder'])/'FALLBACKS_KEPT_2022.json').read_text())
    assert any(r['No']==641 and r['attribute']=='POP_ZP' and r['reason']=='ZERO_FORECAST_REFERENCE_POSITIVE' for r in log)

def test_repeated_import_never_reanchors_reference_to_forecast(year_folder):
    v=fake();v.Net.Zones.data['NUM_PM'][615]=62866.
    first=io.run_import(v,year_folder);ref=year_folder/first['reference_2022_file'];sealed=ref.read_bytes()
    v.Net.Zones.data['NUM_PM'][615]=12345.
    second=io.run_import(v,year_folder)
    assert v.Net.Zones.data['NUM_PM'][615]==62866.
    assert ref.read_bytes()==sealed and first['reference_2022_sha256']==second['reference_2022_sha256']

def test_v1_upgrade_uses_first_original_backup(year_folder):
    v=fake();v.Net.Zones.data['NUM_PM'][615]=62866.;first=io.run_import(v,year_folder)
    (year_folder/first['reference_2022_file']).unlink()
    old=json.loads((year_folder/'IMPORT_CURRENT.json').read_text())
    for key in ['schema','reference_2022_file','reference_2022_sha256']:old.pop(key)
    (year_folder/'IMPORT_CURRENT.json').write_text(json.dumps(old))
    (Path(first['log_folder'])/'RESULT.json').write_text(json.dumps(old))
    v.Net.Zones.data['NUM_PM'][615]=12345.
    second=io.run_import(v,year_folder)
    assert v.Net.Zones.data['NUM_PM'][615]==62866.
    ref=json.loads((year_folder/second['reference_2022_file']).read_text())
    assert ref['capture_basis']=='EARLIEST_SUCCESSFUL_V1_PREIMPORT_BACKUP'

def test_v1_upgrade_without_original_backup_fails_before_writes(year_folder):
    v=fake();(year_folder/'IMPORT_CURRENT.json').write_text(json.dumps({'status':'PASS_IMPORTED','model_path':io.model_path(v,2040)}))
    with pytest.raises(io.ScenarioError,match='REFERENCE_2022_MISSING'):io.run_import(v,year_folder)
    assert not v.Net.Zones.calls and not v.Net.Matrices.items[7001].calls

def test_modified_reference_blocks_import_and_recompute(year_folder):
    v=fake();first=io.run_import(v,year_folder);ref=year_folder/first['reference_2022_file']
    data=json.loads(ref.read_text());data['values']['NUM_PM']['615']=0;ref.write_text(json.dumps(data))
    calls=len(v.Net.Zones.calls)
    with pytest.raises(io.ScenarioError,match='REFERENCE_2022_INTEGRITY'):io.run_import(v,year_folder)
    assert len(v.Net.Zones.calls)==calls
    with pytest.raises(io.ScenarioError,match='REFERENCE_2022_CHANGED'):io.run_recompute(v,year_folder)

@pytest.mark.parametrize('year',[2040,2050,2060,2070])
def test_corrected_workbooks_are_the_source_and_jobs_have_count_scale(year):
    cfg=io.read_config(ROOT/str(year));target,_=io.input_data(ROOT/str(year),cfg,list(range(1,682)))
    assert cfg['zone_source']['label']=='gravity'+str(year)
    assert target['NUM_PM_SMEAR'][11]>100 and target['NUM_PM'][11]>100

def test_rounded_to_zero_reference_readback_is_not_tolerated(year_folder):
    v=fake();v.Net.Zones.data['POP_ZP'][641]=1e-10;original=v.Net.Zones.GetMultiAttValues
    def read(attr,active):
        rows=original(attr,active)
        if attr=='POP_ZP' and v.Net.Zones.calls:
            for row in rows:
                if row[0]==v.Net.Zones.key[641]:row[1]=0.
        return rows
    v.Net.Zones.GetMultiAttValues=read
    with pytest.raises(io.ScenarioError):io.run_import(v,year_folder)
    assert not (year_folder/'IMPORT_CURRENT.json').exists()

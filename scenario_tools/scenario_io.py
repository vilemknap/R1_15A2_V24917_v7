"""Scenario copies of the calibrated 2022 model: explicit import, recalc, export.

Only launch inside Visum. This module never dispatches/loads/saves a version.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import importlib
import json
import math
import os
from pathlib import Path, PureWindowsPath
import re
import shutil
import sys
from types import SimpleNamespace
import uuid
import csv

import numpy as np

YEARS=(2025,2040,2050,2060,2070)
SCHEMA='R1_SCENARIO_IO_20261101_ZERO_FALLBACK_V2'
FALLBACK_POLICY='IMMUTABLE_2022_NONZERO_IF_FORECAST_ZERO_OR_INVALID'
RAW_ATTRS=('NUM_VS','NUM_PUP','POP_ZP','E_C','E_NC','NE_C','NE_NC','PRENOC_SVK','AV_INCOME',
           'NUM_PM','NUM_PM_SMEAR','NUM_PUP_PLACES','NUM_STUD_VS_PLACES','POP_CENTRALITY_TERM')
CAL_ATTRS=('ADD_PROD_W','ADD_ATT_W','ADD_PROD_S','ADD_ATT_S','ADD_PROD_L','ADD_ATT_L','ADD_SALARY',
           'ZAHR_PROD_WORK','ZAHR_ATR_WORK','ZAHR_PROD_SERV','ZAHR_ATR_SERV')
FINAL_DSEGS=['EXOG_EE_CF','EXOG_EE_CL','EXOG_EE_CS','EXOG_EE_CS_NOT','EXOG_EE_CW','EXOG_EE_CW_NOT',
            'LNV','NATIVE_CF','NATIVE_CL','NATIVE_CS','NATIVE_CS_NOT','NATIVE_CW','NATIVE_CW_NOT','NV']
PASSENGER_DSEGS=['EXOG_EE_CF','EXOG_EE_CL','EXOG_EE_CS','EXOG_EE_CS_noT','EXOG_EE_CW','EXOG_EE_CW_noT',
                'NATIVE_CF','NATIVE_CL','NATIVE_CS','NATIVE_CS_noT','NATIVE_CW','NATIVE_CW_noT']
STRATA=[prefix+suffix for prefix in ['1_WORK_','2_SERV_','3_LONG_'] for suffix in ['E_C','E_noC','noE_C','noE_noC','stud']]+['5_SCHOOL']

class ScenarioError(RuntimeError): pass

def digest(raw): return hashlib.sha256(raw).hexdigest()
def array_hash(a): return digest(np.asarray(a,dtype='<f8',order='C').tobytes())

def write_json(path, value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    temp.write_text(json.dumps(value,indent=2,ensure_ascii=False,allow_nan=False)+'\n',encoding='utf-8')
    os.replace(temp,path)

def integer(v, label):
    if isinstance(v,(bool,np.bool_)):raise ScenarioError('NOT_INTEGER:'+label)
    try: x=float(v)
    except (ValueError,TypeError):raise ScenarioError('NOT_INTEGER:'+label)
    if not math.isfinite(x) or x!=int(x):raise ScenarioError('NOT_INTEGER:'+label)
    return int(x)

def number(v, label):
    if isinstance(v,(bool,np.bool_)):raise ScenarioError('INVALID_NUMBER:'+label)
    try:x=float(v)
    except (ValueError,TypeError):raise ScenarioError('INVALID_NUMBER:'+label)
    if not math.isfinite(x) or x<0:raise ScenarioError('INVALID_NUMBER:'+label)
    return x

def model_path(visum, year):
    value=str(visum.IO.CurrentVersionFile).strip()
    years={y for y in YEARS if re.search(r'(?<!\d)'+str(y)+r'(?!\d)',PureWindowsPath(value).stem)}
    if not value or years!={year}:
        raise ScenarioError('SAVE_OPEN_MODEL_AS_YEAR_FIRST:'+str(year))
    return str(PureWindowsPath(value)).casefold()

def validate_package():
    root=Path(__file__).resolve().parent.parent
    sealed=json.loads((root/'scenario_tools'/'SCENARIO_TOOLS_SHA256.json').read_text(encoding='utf-8'))
    for name,expected in sealed.items():
        path=(root/name).resolve()
        if not path.is_relative_to(root) or digest(path.read_bytes())!=expected:raise ScenarioError('SCENARIO_PACKAGE_SHA256_MISMATCH:'+name)

def read_config(folder):
    folder=Path(folder);cfg=json.loads((folder/'SCENARIO.json').read_text(encoding='utf-8'))
    if cfg.get('schema')!=SCHEMA or cfg.get('year') not in YEARS or cfg.get('zone_count')!=681:
        raise ScenarioError('INVALID_SCENARIO_CONFIG')
    if cfg['zone_attributes']!=list(RAW_ATTRS) or cfg['freight_variant']!='MC_MEAN_ROUNDED_HALF_UP':
        raise ScenarioError('INVALID_SCENARIO_SCOPE')
    if cfg['passenger_dsegs']!=PASSENGER_DSEGS:raise ScenarioError('INVALID_PASSENGER_SCOPE')
    if cfg['zone_source'].get('fallback_policy')!=FALLBACK_POLICY:raise ScenarioError('INVALID_FALLBACK_POLICY')
    # No arbitrary paths supplied by the input configuration.
    for key in ['zone_file']:
        if Path(cfg[key]).name!=cfg[key]:raise ScenarioError('INPUT_PATH_OUTSIDE_YEAR_FOLDER')
    for spec in cfg['freight'].values():
        if Path(spec['file']).name!=spec['file']:raise ScenarioError('INPUT_PATH_OUTSIDE_YEAR_FOLDER')
    return cfg

def zone_order(visum, count=681):
    pairs=list(visum.Net.Zones.GetMultiAttValues('NO',False))
    keys=[integer(k,'zone key') for k,_ in pairs];order=[integer(v,'zone NO') for _,v in pairs]
    if len(keys)!=len(set(keys)) or len(order)!=count or set(order)!=set(range(1,count+1)):
        raise ScenarioError('ZONE_IDENTITY_EXPECTED_1_TO_'+str(count))
    return order,dict(zip(order,keys))

def zone_values(visum, attr, key_by_no):
    pairs=list(visum.Net.Zones.GetMultiAttValues(attr,False));values={}
    for key,value in pairs:
        key=integer(key,'attribute key')
        if key in values:raise ScenarioError('DUPLICATE_ATTRIBUTE_KEY:'+attr)
        values[key]=number(value,attr)
    if set(values)!=set(key_by_no.values()):raise ScenarioError('ZONE_ATTRIBUTE_KEY_MISMATCH:'+attr)
    return {no:values[key] for no,key in key_by_no.items()}

def set_zone(visum,attr,values,key_by_no):
    visum.Net.Zones.SetMultiAttValues(attr,[[key_by_no[no],float(value)] for no,value in values.items()],False)

def all_objects(collection):
    raw=collection.GetAll
    return list(raw() if callable(raw) else raw)

def calibrated_context(visum):
    """Detect changed b/c, ADDVAL1 or operation scopes even before OD changes."""
    def finite(value):
        x=float(value)
        if not math.isfinite(x):raise ScenarioError('NONFINITE_CALIBRATED_CONTEXT')
        return x
    def parameter(gravity,letter):
        for key in ['PARA_'+letter,'Para_'+letter,'Para'+letter,'PARAM_'+letter,'Param'+letter,'Parameter'+letter,letter]:
            try:value=gravity.AttValue(key)
            except Exception:continue
            if value not in (None,''):return finite(value)
        raise ScenarioError('TD_PARAMETER_UNREADABLE:'+letter)
    operations=[];abc={};td_count=0
    for index,op in enumerate(all_objects(visum.Procedures.Operations),1):
        typ=integer(op.AttValue('OPERATIONTYPE'),'OPERATIONTYPE');flag=str(op.AttValue('ACTIVE')).strip().upper()
        if flag not in ('TRUE','FALSE','1','0','1.0','0.0'):raise ScenarioError('INVALID_OPERATION_ACTIVE')
        row={'position':index,'type':typ,'active':flag in ('TRUE','1','1.0')}
        if typ==46:
            td_count+=1;td=op.TripDistributionParameters;scope=str(td.AttValue('DSTRATSET'))
            codes=[x.strip("'\"") for x in re.split(r'[,;{}\s]+',scope) if x.strip("'\"")]
            if len(codes)!=len(set(codes)) or set(codes) not in (set(STRATA),set(STRATA)|{'4_FOREIGN'}):
                raise ScenarioError('UNEXPECTED_UNIFIED_TD_STRATA')
            row['strata']=sorted(codes)
            for code in codes:
                gravity=td.TripDistributionDStratParameters(code).GravitationParameters
                abc[code]={letter:parameter(gravity,letter) for letter in ['A','B','C']}
        elif typ==101:row['dsegs']=str(op.PrTAssignmentParameters.AttValue('DSEGSET'))
        operations.append(row)
    if td_count!=1:raise ScenarioError('EXPECTED_ONE_UNIFIED_TD')
    link_rows=list(visum.Net.Links.GetMultiAttValues('ADDVAL1',False))
    link_values=sorted((str(k),finite(v)) for k,v in link_rows)
    if len({k for k,v in link_values})!=len(link_values):raise ScenarioError('DUPLICATE_LINK_KEY')
    context={'operations':operations,'td_abc':abc,'link_addval1':link_values}
    return digest(json.dumps(context,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf-8'))

def resolve_matrix(visum, code):
    try:ds=visum.Net.DemandSegments.ItemByKey(code)
    except Exception:ds=None
    if ds is not None:
        matrix=ds.ODMatrix
        if matrix is not None:return matrix
    candidates=[m for m in all_objects(visum.Net.Matrices) if str(m.AttValue('CODE')).strip().upper()==code.upper()]
    if len(candidates)!=1:raise ScenarioError('MATRIX_NOT_UNIQUE:'+code)
    return candidates[0]

def values(matrix, count):
    a=np.array(matrix.GetValues(),dtype=np.float64,copy=True,order='C')
    if a.shape!=(count,count) or not np.isfinite(a).all() or np.any(a<0):
        raise ScenarioError('INVALID_MATRIX_VALUES:'+str(matrix.AttValue('NO')))
    return a

def input_data(folder,cfg,order):
    folder=Path(folder);source=folder/cfg['zone_file']
    if digest(source.read_bytes())!=cfg['zone_sha256']:raise ScenarioError('ZONE_INPUT_SHA256_MISMATCH')
    targets={a:{} for a in RAW_ATTRS}
    with source.open(encoding='utf-8-sig',newline='') as stream:
        reader=csv.DictReader(stream)
        if reader.fieldnames!=['No']+list(RAW_ATTRS):raise ScenarioError('ZONE_INPUT_HEADERS')
        seen=set()
        for row in reader:
            no=integer(row['No'],'source NO')
            if no in seen:raise ScenarioError('DUPLICATE_SOURCE_ZONE')
            seen.add(no)
            for attr in RAW_ATTRS:
                if row[attr]!='KEEP_2022':targets[attr][no]=number(row[attr],attr)
        if seen!=set(order):raise ScenarioError('SOURCE_ZONE_SET_MISMATCH')
    freight={};pos={no:i for i,no in enumerate(order)}
    if set(cfg['freight'])!={'LNV','NV'}:raise ScenarioError('FREIGHT_INPUT_SCOPE')
    for code,spec in cfg['freight'].items():
        file=folder/spec['file']
        if digest(file.read_bytes())!=spec['sha256']:raise ScenarioError('FREIGHT_INPUT_SHA256_MISMATCH:'+code)
        arr=np.zeros((len(order),len(order)),dtype=np.float64);seen=set()
        with file.open(encoding='utf-8-sig',newline='') as stream:
            reader=csv.DictReader(stream)
            if reader.fieldnames!=['FromZoneNo','ToZoneNo','Value']:raise ScenarioError('FREIGHT_INPUT_HEADERS')
            for row in reader:
                o=integer(row['FromZoneNo'],'origin');d=integer(row['ToZoneNo'],'destination');v=integer(row['Value'],'freight value')
                if o not in pos or d not in pos or v<0 or (o,d) in seen:raise ScenarioError('INVALID_FREIGHT_OD:'+code)
                seen.add((o,d));arr[pos[o],pos[d]]=v
        if arr.sum()!=spec['rounded_total'] or np.trace(arr)!=spec['rounded_diagonal'] or np.count_nonzero(arr)!=spec['rounded_nonzero_od']:
            raise ScenarioError('FREIGHT_TOTAL_OR_DIAGONAL_MISMATCH:'+code)
        freight[code]=arr
    return targets,freight

def snapshot_inputs(visum,order,key_by_no):
    return {a:zone_values(visum,a,key_by_no) for a in RAW_ATTRS+CAL_ATTRS}

def run_folder(folder,label):
    p=Path(folder)/'logs'/(datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'_'+label)
    p.mkdir(parents=True);return p

def reference_values(record,version,year,order):
    body={k:v for k,v in record.items() if k!='content_sha256'}
    actual=digest(json.dumps(body,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf-8'))
    if record.get('schema')!='R1_IMMUTABLE_SCENARIO_REFERENCE_2022_V1' or record.get('content_sha256')!=actual:
        raise ScenarioError('REFERENCE_2022_INTEGRITY_MISMATCH')
    if record.get('model_path')!=version or record.get('scenario_year')!=year or record.get('zone_nos')!=sorted(order):
        raise ScenarioError('REFERENCE_2022_MODEL_OR_ZONE_MISMATCH')
    if set(record.get('values',{}))!=set(RAW_ATTRS):raise ScenarioError('REFERENCE_2022_ATTRIBUTE_SCOPE')
    result={a:{integer(no,'reference zone'):number(v,a) for no,v in record['values'][a].items()} for a in RAW_ATTRS}
    if any(set(rows)!=set(order) for rows in result.values()):raise ScenarioError('REFERENCE_2022_ZONE_SCOPE')
    return result

def reference_2022(folder,cfg,version,order,before):
    """Capture only before the first import; never turn a forecast into a new baseline."""
    folder=Path(folder);relative='reference_2022/'+digest(version.encode('utf-8'))+'.json';path=folder/relative
    if not path.exists():
        source={a:before[a] for a in RAW_ATTRS};origin='FIRST_OPENED_CALIBRATED_2022_COPY_BEFORE_ANY_IMPORT'
        prior=folder/'IMPORT_CURRENT.json'
        if prior.exists() and json.loads(prior.read_text(encoding='utf-8')).get('model_path')==version:
            source=None
            # Upgrade an existing v1 installation from its first successful pre-import backup.
            for result_file in sorted((folder/'logs').glob('*_IMPORT/RESULT.json')):
                result=json.loads(result_file.read_text(encoding='utf-8'))
                if result.get('status')=='PASS_IMPORTED' and result.get('model_path')==version:
                    backup=result_file.parent/'ZONE_BEFORE_BACKUP.json'
                    if not backup.is_file():raise ScenarioError('ORIGINAL_2022_BACKUP_MISSING_REOPEN_2022_COPY')
                    source=json.loads(backup.read_text(encoding='utf-8'));origin='EARLIEST_SUCCESSFUL_V1_PREIMPORT_BACKUP';break
            if source is None:raise ScenarioError('REFERENCE_2022_MISSING_FOR_EXISTING_IMPORT_REOPEN_2022_COPY')
        body={'schema':'R1_IMMUTABLE_SCENARIO_REFERENCE_2022_V1','model_path':version,'scenario_year':cfg['year'],
              'zone_nos':sorted(order),'capture_basis':origin,
              'values':{a:{str(no):number(source[a].get(no,source[a].get(str(no))),a) for no in sorted(order)} for a in RAW_ATTRS}}
        body['content_sha256']=digest(json.dumps(body,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf-8'))
        reference_values(body,version,cfg['year'],order)
        write_json(path,body)
    record=json.loads(path.read_text(encoding='utf-8'))
    values=reference_values(record,version,cfg['year'],order)
    return values,relative,digest(path.read_bytes()),record

def resolve_zonal_fallback(target,reference,order):
    effective={a:{} for a in RAW_ATTRS};fallback=[]
    for a in RAW_ATTRS:
        for no in order:
            ref=reference[a][no];missing=no not in target[a];value=target[a].get(no)
            use_reference=missing or (value==0 and ref>0)
            effective[a][no]=ref if use_reference else value
            if use_reference:
                fallback.append({'No':no,'attribute':a,'forecast_value':'KEEP_2022' if missing else value,
                    'reference_2022_value':ref,'kept_2022_value':ref,'effective_value':ref,
                    'reason':'INVALID_OR_MISSING_FORECAST' if missing else 'ZERO_FORECAST_REFERENCE_POSITIVE'})
    return effective,fallback

def read_import(visum,folder,cfg):
    stamp=json.loads((Path(folder)/'IMPORT_CURRENT.json').read_text(encoding='utf-8'))
    if stamp.get('schema')!=SCHEMA:raise ScenarioError('REIMPORT_WITH_ZERO_FALLBACK_V2_REQUIRED')
    if stamp['status']!='PASS_IMPORTED' or stamp['year']!=cfg['year'] or stamp['model_path']!=model_path(visum,cfg['year']):
        raise ScenarioError('IMPORT_RECEIPT_MODEL_MISMATCH')
    if stamp['config_sha256']!=digest((Path(folder)/'SCENARIO.json').read_bytes()):raise ScenarioError('IMPORT_CONFIG_CHANGED')
    return stamp

def verify_inputs(visum,folder,cfg,stamp):
    order,keys=zone_order(visum);target,freight=input_data(folder,cfg,order)
    if order!=stamp['zone_order']:raise ScenarioError('ZONE_ORDER_CHANGED')
    ref_path=(Path(folder)/stamp['reference_2022_file']).resolve()
    if not ref_path.is_relative_to(Path(folder).resolve()) or digest(ref_path.read_bytes())!=stamp['reference_2022_sha256']:
        raise ScenarioError('REFERENCE_2022_CHANGED_SINCE_IMPORT')
    reference_values(json.loads(ref_path.read_text(encoding='utf-8')),stamp['model_path'],cfg['year'],order)
    raw=snapshot_inputs(visum,order,keys)
    expected={a:{int(k):v for k,v in rows.items()} for a,rows in stamp['zone_values'].items()}
    if raw!=expected:raise ScenarioError('ZONAL_OR_CALIBRATED_PARAMETERS_CHANGED_SINCE_IMPORT')
    if calibrated_context(visum)!=stamp['calibrated_context_sha256']:raise ScenarioError('TD_SUPPLY_OR_OPERATIONS_CHANGED_SINCE_IMPORT')
    for code,arr in freight.items():
        if not np.array_equal(values(resolve_matrix(visum,code),len(order)),arr):raise ScenarioError('FREIGHT_CHANGED_SINCE_IMPORT:'+code)
    return order,keys

def run_import(visum,folder):
    folder=Path(folder);cfg=read_config(folder);version=model_path(visum,cfg['year']);order,keys=zone_order(visum)
    target,freight=input_data(folder,cfg,order)
    before=snapshot_inputs(visum,order,keys);expected={a:dict(v) for a,v in before.items()};context_before=calibrated_context(visum)
    matrices={c:resolve_matrix(visum,c) for c in freight}
    if len({integer(m.AttValue('NO'),'matrix NO') for m in matrices.values()})!=2:raise ScenarioError('FREIGHT_MATRICES_OVERLAP')
    originals={}
    for code,m in matrices.items():
        if str(m.AttValue('DATASOURCETYPE')).strip().upper() not in ('DATA','DATASOURCETYPE_DATA'):
            raise ScenarioError('FREIGHT_MATRIX_NOT_DATA:'+code)
        originals[code]=values(m,len(order))
    log=run_folder(folder,'IMPORT');write_json(log/'ZONE_BEFORE_BACKUP.json',before)
    np.savez_compressed(log/'FREIGHT_BEFORE_BACKUP.npz',**originals)
    reference,ref_file,ref_sha,ref_record=reference_2022(folder,cfg,version,order,before)
    effective,fallback=resolve_zonal_fallback(target,reference,order)
    for a in RAW_ATTRS:expected[a].update(effective[a])
    write_json(log/'REFERENCE_2022.json',ref_record)
    write_json(log/'FALLBACKS_KEPT_2022.json',fallback)
    owned=[]
    try:
        for a in RAW_ATTRS:
            if effective[a]!=before[a]:owned.append(('zone',a));set_zone(visum,a,effective[a],keys)
        for code,arr in freight.items():
            owned.append(('matrix',code));matrices[code].SetValues(np.array(arr,dtype=np.float64,order='C'),False)
        readback=snapshot_inputs(visum,order,keys)
        if any(readback[a]!=before[a] for a in CAL_ATTRS):raise ScenarioError('CALIBRATED_PARAMETER_CHANGED')
        if any(not math.isclose(readback[a][no],expected[a][no],rel_tol=1e-12,abs_tol=1e-7) for a in RAW_ATTRS for no in order):
            raise ScenarioError('IMPORT_ZONE_READBACK_MISMATCH')
        if any(expected[a][no]>0 and readback[a][no]==0 for a in RAW_ATTRS for no in order):
            raise ScenarioError('IMPORT_READBACK_ERASED_POSITIVE_EFFECTIVE_VALUE')
        for code,arr in freight.items():
            if not np.array_equal(values(matrices[code],len(order)),arr):raise ScenarioError('IMPORT_MATRIX_READBACK_MISMATCH:'+code)
        if calibrated_context(visum)!=context_before:raise ScenarioError('IMPORT_CHANGED_TD_SUPPLY_OR_OPERATIONS')
        stamp={'schema':SCHEMA,'status':'PASS_IMPORTED','year':cfg['year'],'import_id':uuid.uuid4().hex,'model_path':version,'zone_order':order,
               'config_sha256':digest((folder/'SCENARIO.json').read_bytes()),'zone_values':readback,'log_folder':str(log),
               'calibrated_context_sha256':context_before,
               'reference_2022_file':ref_file,'reference_2022_sha256':ref_sha,'fallback_policy':FALLBACK_POLICY,
               'zero_fallback_cells':sum(r['reason']=='ZERO_FORECAST_REFERENCE_POSITIVE' for r in fallback),
               'fallback_cells':len(fallback),'changed_zone_cells':sum(before[a][no]!=expected[a][no] for a in RAW_ATTRS for no in order),
               'freight_totals':{c:float(v.sum()) for c,v in freight.items()},'recalculation_required':True,'version_saved':False}
        write_json(log/'RESULT.json',stamp);write_json(folder/'IMPORT_CURRENT.json',stamp)
    except BaseException as exc:
        failures=[]
        for kind,key in reversed(owned):
            try:
                if kind=='zone':set_zone(visum,key,before[key],keys)
                else:matrices[key].SetValues(np.array(originals[key],dtype=np.float64,order='C'),False)
            except BaseException as err:failures.append(str(err))
        try:
            if snapshot_inputs(visum,order,keys)!=before:failures.append('ZONE_ROLLBACK_READBACK_MISMATCH')
            for code,arr in originals.items():
                if not np.array_equal(values(matrices[code],len(order)),arr):failures.append('FREIGHT_ROLLBACK_READBACK_MISMATCH:'+code)
            if calibrated_context(visum)!=context_before:failures.append('CALIBRATED_CONTEXT_CHANGED')
        except BaseException as err:failures.append(str(err))
        write_json(log/'RESULT.json',{'status':'FAILED_ROLLBACK_UNVERIFIED_MANUAL_REOPEN' if failures else 'FAILED_ROLLBACK_VERIFIED',
                   'error':str(exc),'rollback_errors':failures})
        if failures:raise ScenarioError('IMPORT_ROLLBACK_UNVERIFIED_MANUAL_REOPEN:'+str(log)) from exc
        raise
    print('PASS_IMPORT',cfg['year'],'freight',stamp['freight_totals'],'fallbacks',len(fallback))
    print('Save the scenario copy, then run 02_RECOMPUTE before export. No version was saved by this script.')
    return stamp

def fingerprint(visum,cfg,order):
    cache={};matrices={};component_nos=[]
    def read(m):
        no=integer(m.AttValue('NO'),'matrix NO')
        if no not in cache:cache[no]=values(m,len(order))
        matrices[str(no)]=array_hash(cache[no]);return no,cache[no]
    oa=np.zeros((len(order),len(order)),dtype=np.float64)
    for code in cfg['passenger_dsegs']:
        no,arr=read(resolve_matrix(visum,code));component_nos.append(no);oa+=arr
    if len(component_nos)!=12 or len(set(component_nos))!=12:raise ScenarioError('PASSENGER_COMPONENT_DUPLICATION')
    if not np.isfinite(oa).all():raise ScenarioError('PASSENGER_AGGREGATE_OVERFLOW')
    freight={code:read(resolve_matrix(visum,code))[1] for code in ['LNV','NV']}
    distance=visum.Net.Matrices.ItemByKey(9697)
    if integer(distance.AttValue('NO'),'OSRM NO')!=9697 or str(distance.AttValue('CODE')).upper()!='R1_OSRM_DIST_KM':raise ScenarioError('OSRM_9697_IDENTITY')
    _,dist=read(distance);mask=dist>=80.0
    long=[]
    for no in list(range(9111,9116))+list(range(9291,9296))+[9305]:
        _,arr=read(visum.Net.Matrices.ItemByKey(no))
        if np.any(arr[~mask]!=0):raise ScenarioError('LONG_SUPPORT_BELOW_80_KM:'+str(no))
        if 9291<=no<=9295:long.append(arr)
    if not np.allclose(values(visum.Net.Matrices.ItemByKey(9305),len(order)),np.sum(long,axis=0),rtol=1e-10,atol=1e-6):
        raise ScenarioError('LONG_9305_COMPONENT_PARITY')
    return {'zone_order':order,'matrices':matrices,'passenger_component_nos':component_nos,'oa_sha256':array_hash(oa)},oa,freight

def native_recompute(visum,folder,order,project_root):
    """Reuse the installed v7 mask/operation scoping instead of a new TD chain."""
    names=['r1_15a2_long_post_td_mask_v24917','r1_15a2_com_compat','r1_15a2_supply_visum','r1_15a2_procseq_roles_v24917']
    project_root=Path(project_root).resolve();previous_path=list(sys.path)
    try:
        manifest=json.loads((project_root/'V24917_RUNTIME_MANIFEST.json').read_text(encoding='utf-8'))
        for name,expected in manifest['required_files'].items():
            path=(project_root/name).resolve()
            if not path.is_relative_to(project_root) or digest(path.read_bytes())!=expected:
                raise ScenarioError('BASE_RUNTIME_SHA256_MISMATCH:'+name)
        sys.path.insert(0,str(project_root))
        for name in names:
            previous=sys.modules.get(name)
            if previous is not None and Path(previous.__file__).resolve().parent!=project_root:raise ScenarioError('PRELOADED_MODULE_FROM_OTHER_PACKAGE:'+name)
        mask=importlib.import_module(names[0]);compat=importlib.import_module(names[1]);supply=importlib.import_module(names[2])
        roles=importlib.import_module(names[3])
        for name,module in list(sys.modules.items()):
            if name.startswith('r1_15a2_') and getattr(module,'__file__',None) and Path(module.__file__).resolve().parent!=project_root:
                raise ScenarioError('PRELOADED_MODULE_FROM_OTHER_PACKAGE:'+name)
        rows=compat.operation_rows(visum)
        if sum(r['active'] and r['type']==compat.TG for r in rows)!=1 or sum(r['active'] and r['type']==compat.TD for r in rows)!=1:
            raise ScenarioError('FULL_ACTIVE_TG_TD_SEQUENCE_REQUIRED')
        # OPMAP1 (2026-11-11): the final 14-DSeg assignment is the legacy role 20; on the 53-operation
        # layout it sits at another position.  The role map resolves it live (fails closed if ambiguous);
        # the configuration keeps the legacy number, which the installed mask engine translates itself.
        try:final_no=int(roles.live_position(visum,20))
        except Exception as exc:raise ScenarioError('FINAL_ASSIGNMENT_ROLE_UNRESOLVED:'+str(exc)) from exc
        if not any(r['no']==final_no and r['type']==compat.ASSIGNMENT_PRT and r['active'] for r in rows):raise ScenarioError('ACTIVE_FINAL_ASSIGNMENT_20_REQUIRED')
        cfg={'supply':{'assignment_operations':[{'no':20,'operation_type':101,'expected_dsegs':FINAL_DSEGS}]}}
        adapter=SimpleNamespace(visum=visum,zones=order,cfg=cfg,com_retry_policy={})
        def execute(host,path):
            Path(path).mkdir(parents=True,exist_ok=True)
            host.Procedures.Execute()
        mask.execute_sequence(adapter,folder,execute)
        gap=supply.assignment_gap_evidence(visum,{'source':'PRT_ASS_QUALITY_LIST','operation_no':final_no,'maximum_gap':0.005})
        gap=dict(gap,final_assignment_position=final_no)
        if not math.isfinite(float(gap['gap'])) or not 0<=gap['gap']<=0.005:raise ScenarioError('NATIVE_ASSIGNMENT_GAP_ABOVE_0_005')
        return gap
    finally:sys.path[:]=previous_path

def run_recompute(visum,folder):
    folder=Path(folder);cfg=read_config(folder);stamp=read_import(visum,folder,cfg)
    order,keys=verify_inputs(visum,folder,cfg,stamp);log=run_folder(folder,'RECOMPUTE')
    state={'status':'RUNNING','year':cfg['year'],'import_id':stamp['import_id'],'model_path':stamp['model_path'],'log_folder':str(log)}
    write_json(folder/'RECOMPUTE_CURRENT.json',state)
    try:
        gap=native_recompute(visum,log,order,Path(__file__).resolve().parent.parent)
        verify_inputs(visum,folder,cfg,stamp)
        fp,_,_=fingerprint(visum,cfg,order)
        state.update(status='PASS_RECOMPUTED',fingerprint=fp,assignment_gap_evidence=gap,version_saved=False)
        write_json(log/'RESULT.json',state);write_json(folder/'RECOMPUTE_CURRENT.json',state)
    except BaseException as exc:
        state.update(status='FAILED_DO_NOT_EXPORT_REOPEN_SAVED_SCENARIO',error=str(exc))
        write_json(log/'RESULT.json',state);write_json(folder/'RECOMPUTE_CURRENT.json',state)
        raise
    print('PASS_RECOMPUTE',cfg['year'],'LONG >=80 km; no upper bound. Save the scenario copy; export with 03_EXPORT.')
    return state

def write_matrix(path,arr,order,year,label):
    """Visum $O, sparse directed OD. OA retains decimals; freight is integral."""
    path=Path(path)
    written_total=0.;written_diagonal=0.;written_nonzero=0
    with path.open('w',encoding='utf-8',newline='\n') as stream:
        stream.write('$O;D6\n* From To\n0.00 24.00\n* Factor\n1.00\n* R1 %s %s vehicles/day\n'%(year,label))
        for i,no in enumerate(order):
            for j in np.flatnonzero(arr[i]):
                v=float(arr[i,j]);text=str(int(v)) if label in ('LNV','NV') else format(v,'.6f')
                parsed=float(text)
                if not parsed:continue
                stream.write('%s %s %s\n'%(no,order[int(j)],text))
                written_total+=parsed;written_nonzero+=1
                if i==j:written_diagonal+=parsed
        stream.write('* Network object names\n$NAMES\n')
        for no in order:stream.write('%s ""\n'%no)
    return {'sum_written':written_total,'diagonal_written':written_diagonal,'nonzero_od_written':written_nonzero}

def run_export(visum,folder):
    folder=Path(folder);cfg=read_config(folder);stamp=read_import(visum,folder,cfg)
    order,_=verify_inputs(visum,folder,cfg,stamp)
    proof=json.loads((folder/'RECOMPUTE_CURRENT.json').read_text(encoding='utf-8'))
    if proof['status']!='PASS_RECOMPUTED' or proof['import_id']!=stamp['import_id'] or proof['model_path']!=stamp['model_path']:
        raise ScenarioError('SUCCESSFUL_RECOMPUTE_REQUIRED_BEFORE_EXPORT')
    fp,oa,freight=fingerprint(visum,cfg,order)
    if fp!=proof['fingerprint']:raise ScenarioError('MODEL_MATRICES_CHANGED_SINCE_RECOMPUTE')
    staging=folder/('EXPORT_STAGING_'+uuid.uuid4().hex);staging.mkdir();stats=[]
    try:
        for label,arr in [('OA_CAL_WORK',oa),('LNV',freight['LNV']),('NV',freight['NV'])]:
            filename='R1_%s_%s.mtx'%(cfg['year'],label);path=staging/filename
            text_stats=write_matrix(path,arr,order,cfg['year'],label)
            stats.append({'label':label,'file':filename,'sha256':digest(path.read_bytes()),'sum_before_text_format':float(arr.sum()),
                          'diagonal':float(np.trace(arr)),'nonzero_od':int(np.count_nonzero(arr)),'unit':'vehicles/day',
                          'freight_integer_values':label in ('LNV','NV'),**text_stats})
        result={'status':'PASS_EXPORTED','year':cfg['year'],'model_path':stamp['model_path'],'import_id':stamp['import_id'],
                'fingerprint':fp,'outputs':stats,'OA_source':'SUM_OF_12_DISTINCT_COMPONENT_DSEG_MATRICES',
                'model_writes':False,'version_saved':False,'period_conversion':'NOT_APPLIED_DAILY_MATRICES'}
        write_json(staging/'EXPORT_MANIFEST.json',result)
        target=folder/('EXPORT_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
        os.replace(staging,target)
    except BaseException:
        shutil.rmtree(staging,ignore_errors=True);raise
    print('PASS_EXPORT',cfg['year'],target)
    return result

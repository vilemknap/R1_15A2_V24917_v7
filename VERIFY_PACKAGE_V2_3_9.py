"""Offline integrity verifier for R1 15A2 V2.3.9 safety-gate package."""
from pathlib import Path
import csv, hashlib, json, sys

ROOT = Path(__file__).resolve().parent
EXCLUDED = {'MANIFEST_V239.json', 'SHA256SUMS_V239.txt'}
EXPECTED_OP20 = {
    'EXOG_EE_CF','EXOG_EE_CL','EXOG_EE_CS','EXOG_EE_CS_NOT','EXOG_EE_CW','EXOG_EE_CW_NOT',
    'LNV','NATIVE_CF','NATIVE_CL','NATIVE_CS','NATIVE_CS_NOT','NATIVE_CW','NATIVE_CW_NOT','NV'
}

def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''): h.update(chunk)
    return h.hexdigest()

def payload_files():
    for p in ROOT.rglob('*'):
        rel=p.relative_to(ROOT)
        if (not p.is_file() or p.suffix=='.pyc' or any(x in ('__pycache__','.pytest_cache') for x in rel.parts)
                or rel.as_posix() in EXCLUDED):
            continue
        yield p, rel.as_posix()

def verify():
    manifest=json.loads((ROOT/'MANIFEST_V239.json').read_text(encoding='utf-8'))
    expected=manifest['files']
    actual={rel:digest(p) for p,rel in payload_files()}
    problems=[]
    for rel in sorted(set(expected)|set(actual)):
        if expected.get(rel)!=actual.get(rel): problems.append('PAYLOAD_MISSING_CHANGED_OR_EXTRA:'+rel)
    sums=(ROOT/'SHA256SUMS_V239.txt').read_text(encoding='utf-8').splitlines()
    listed=dict((name,sha) for sha,name in (line.split('  ',1) for line in sums if line.strip()))
    if listed!=expected: problems.append('SHA256SUMS_MANIFEST_DISAGREEMENT')
    cfg=json.loads((ROOT/'R1_15A2_CONFIG_V2_3_9.json').read_text(encoding='utf-8'))
    if cfg.get('apply') is not False: problems.append('APPLY_MUST_REMAIN_FALSE')
    if cfg.get('supply',{}).get('gap_readback',{}).get('maximum_gap')!=0.005: problems.append('EPSILON_CHANGED')
    if cfg.get('supply',{}).get('equivalent_seconds_per_addval1')!=10.0: problems.append('ADDVAL1_SECONDS_CHANGED')
    rules=cfg.get('supply',{}).get('assignment_operations',[])
    if len(rules)!=1 or rules[0].get('no')!=20 or rules[0].get('operation_type')!=101:
        problems.append('SUPPLY_TRIAL_SCOPE_NOT_OP20_ONLY')
    elif set(rules[0].get('expected_dsegs',[]))!=EXPECTED_OP20:
        problems.append('OP20_EXPECTED_DSEGSET_CHANGED')
    old=json.loads((ROOT/'R1_15A2_CONFIG_V2_3_8.json').read_text(encoding='utf-8'))
    if old.get('supply',{}).get('assignment_operations')!=[]:
        problems.append('V238_BASE_CONFIG_MUTATED')
    integrity=json.loads((ROOT/'V239_SOURCE_INTEGRITY.json').read_text(encoding='utf-8'))
    if integrity.get('protected_unchanged_file_count')!=30:
        problems.append('PROTECTED_COUNT_CHANGED')
    for rel,sha in integrity.get('protected_unchanged_files',{}).items():
        if actual.get(rel)!=sha: problems.append('PROTECTED_FILE_CHANGED:'+rel)
    records=[]
    for name in ('R1_CSD2022_COUNTLOCATION_AUTHORITY_408.csv','R1_CITY_RPDI_COUNTLOCATION_AUTHORITY_90.csv'):
        with (ROOT/'authorities'/name).open(encoding='utf-8-sig',newline='') as f: records.extend(csv.DictReader(f))
    if (len(records),sum(r['role']=='CALIBRATION' for r in records),sum(r['role']=='VALIDATION' for r in records))!=(498,462,36):
        problems.append('OBSERVATION_SCOPE_CHANGED')
    for rel in ('R1_15A2_15T_ASSIGNMENT_SCOPE_FULL_GEOMETRY_READONLY.py',
                'R1_15A2_15U_NO_LOADVERSION_ROLLBACK_SMOKE.py','r1_15a2_inplace_transaction_v239.py'):
        text=(ROOT/rel).read_text(encoding='utf-8')
        for forbidden in ('.LoadVersion(', 'rt.load_version(', '.SaveVersion(', 'rt.save_version(', '.SetValues('):
            if forbidden in text: problems.append('FORBIDDEN_API_IN_'+rel+':'+forbidden)
    s15u=(ROOT/'R1_15A2_15U_NO_LOADVERSION_ROLLBACK_SMOKE.py').read_text(encoding='utf-8')
    for required in ('15U_WORKING_COPY_ACK.txt','I_CONFIRM_DISPOSABLE_WORKING_COPY','require_15t_authority',
                     '15U_WORKING_COPY','PASS_NO_LOADVERSION_ROLLBACK_SUPPLY_GENERATION_TD'):
        if required not in s15u: problems.append('15U_SAFETY_CONTRACT_MISSING:'+required)
    s15t=(ROOT/'R1_15A2_15T_ASSIGNMENT_SCOPE_FULL_GEOMETRY_READONLY.py').read_text(encoding='utf-8')
    for required in ('version_sha256','model_state_hash_before','model_state_hash_after',
                     'PASS_ASSIGNMENT_SCOPE_AND_FULL_GEOMETRY_IDENTITY'):
        if required not in s15t: problems.append('15T_AUTHORITY_CONTRACT_MISSING:'+required)
    return {'status':'FAIL' if problems else 'PASS','checked_files':len(actual),
            'protected_files':len(integrity.get('protected_unchanged_files',{})),
            'offline_tests_expected':427,'production_apply_authorized':False,
            'live_15t_pass':False,'live_15u_pass':False,'problems':problems}

if __name__=='__main__':
    try: result=verify()
    except Exception as exc: result={'status':'FAIL','error':type(exc).__name__+': '+str(exc)}
    print(json.dumps(result,indent=2,ensure_ascii=False))
    sys.exit(0 if result.get('status')=='PASS' else 1)

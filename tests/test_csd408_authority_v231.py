from __future__ import annotations
import copy
import csv
import shutil
from pathlib import Path
import importlib
import pytest
from conftest import FakeAttr, FakeCollection

ROOT=Path(__file__).resolve().parents[1]
APPROVED=ROOT/'authorities'/'R1_CSD2022_COUNTLOCATION_AUTHORITY_408.csv'
HELPER=ROOT/'helpers'/'R1_12D_CSD2022_GEH_FORENSIC_408_APPROVED.py'


def helper_for(tmp_path):
    shutil.copy2(APPROVED,tmp_path/APPROVED.name)
    src=HELPER.read_text(encoding='utf-8')
    assert '\ntry:\n    main()\nexcept Exception:' in src
    prefix=src.split('\ntry:\n    main()\nexcept Exception:',1)[0]
    env={'__file__':str(tmp_path/HELPER.name),'__name__':'12D_CSD408_TEST'}
    exec(compile(prefix,str(HELPER),'exec'),env,env)
    return env


def live_objects(env):
    manifest=env['load_manifest']()
    objects=[]
    links={}
    for r in manifest.values():
        key=tuple(int(r[n]) for n in ('current_link_no','current_from_node_no','current_to_node_no'))
        links[key]={'link_no':key[0]}
        objects.append(FakeAttr(**{
            'NO':int(r['countlocation_no']),
            'CODE':r['countlocation_code'],
            'R1_OBS_ID':r['profile_id'],
            'R1_ROLE':r['role'],
            'R1_OBS_SCOPE':r['vehicle_scope'],
            'R1_OBS_BASIS':r['period_basis'],
            'LINKNO':key[0], 'FROMNODENO':key[1], 'TONODENO':key[2],
            'R1_OBS_RPDI':float(r['observed_passenger_cars_O']),
            'R1_OBS_VALUE':float(r['observed_passenger_cars_O']),
            'R1_ACTIVE':1,'R1_WEIGHT':float(r['live_weight'])
        }))
    return manifest,objects,links


def test_approved_408_has_exact_roles_and_digest(tmp_path):
    env=helper_for(tmp_path)
    manifest=env['load_manifest']()
    assert len(manifest)==408
    assert sum(r['role']=='CALIBRATION' for r in manifest.values())==372
    assert sum(r['role']=='VALIDATION' for r in manifest.values())==36
    assert 920018 not in manifest and 920001 in manifest


def test_full_live_408_pass(tmp_path):
    env=helper_for(tmp_path)
    data,objects,links=live_objects(env)
    result=env['verify_live_authority'](data,objects,links)
    assert result['status']=='PASS_EXACT_APPROVED_ROSTER_AND_LIVE_VALUES'


def test_deleted_reference_profile_is_not_required(tmp_path):
    env=helper_for(tmp_path)
    manifest,objects,links=live_objects(env)
    assert 920018 not in manifest
    # The real list outside reserved CSD range is excluded; 127 other locations do not participate.
    fake=FakeAttr(NO=912001)
    visum=FakeAttr(Net=FakeAttr(CountLocations=FakeCollection(objects+[fake])))
    actual=env['read_countlocations'](visum)
    assert len(actual)==408


def test_unapproved_reference_profile_detected(tmp_path):
    env=helper_for(tmp_path)
    manifest,objects,links=live_objects(env)
    objects.append(FakeAttr(NO=920018))
    with pytest.raises(RuntimeError,match='roster differs'):
        env['verify_live_authority'](manifest,objects,links)


def test_lost_approved_profile_detected(tmp_path):
    env=helper_for(tmp_path)
    manifest,objects,links=live_objects(env)
    with pytest.raises(RuntimeError,match='roster differs'):
        env['verify_live_authority'](manifest,objects[1:],links)


def test_observed_change_detected(tmp_path):
    env=helper_for(tmp_path)
    manifest,objects,links=live_objects(env)
    objects[0].SetAttValue('R1_OBS_RPDI',float(manifest[int(objects[0].AttValue('NO'))]['observed_passenger_cars_O'])+1)
    with pytest.raises(RuntimeError,match='observed intensity changed'):
        env['verify_live_authority'](manifest,objects,links)


def test_role_change_detected(tmp_path):
    env=helper_for(tmp_path)
    manifest,objects,links=live_objects(env)
    objects[0].SetAttValue('R1_ROLE','VALIDATION')
    with pytest.raises(RuntimeError,match='live mismatch R1_ROLE'):
        env['verify_live_authority'](manifest,objects,links)


def test_physical_map_change_detected(tmp_path):
    env=helper_for(tmp_path)
    manifest,objects,links=live_objects(env)
    objects[0].SetAttValue('FROMNODENO',55555)
    with pytest.raises(RuntimeError,match='physical directed mapping changed'):
        env['verify_live_authority'](manifest,objects,links)


def test_missing_assignment_link_detected(tmp_path):
    env=helper_for(tmp_path)
    manifest,objects,links=live_objects(env)
    target=manifest[int(objects[0].AttValue('NO'))]
    key=tuple(int(target[n]) for n in ('current_link_no','current_from_node_no','current_to_node_no'))
    del links[key]
    with pytest.raises(RuntimeError,match='physical directed link unavailable'):
        env['verify_live_authority'](manifest,objects,links)


def test_rebased_physical_mapping_keeps_original_uda_as_non_authoritative(tmp_path):
    env=helper_for(tmp_path)
    manifest,objects,links=live_objects(env)
    assert 920024 in manifest
    r=manifest[920024]
    assert r['current_link_no'] != r['legacy_manifest_link_no']
    cl=next(o for o in objects if o.AttValue('NO')==920024)
    cl.SetAttValue('R1_LINK_NO',int(r['legacy_manifest_link_no']))
    assert env['verify_live_authority'](manifest,objects,links)['rows']==408


def test_authority_file_tamper_detected(tmp_path):
    env=helper_for(tmp_path)
    p=tmp_path/APPROVED.name
    raw=p.read_bytes();p.write_bytes(raw+b'\n')
    with pytest.raises(RuntimeError,match='SHA256 mismatch'):
        env['load_manifest']()


def test_new_master_cfg_loads_408_authority():
    m=importlib.import_module('R1_15A2_SUPPLY_DEMAND_MASTER_V2_3_1')
    cfg=m.load_config()
    assert cfg['expected_12d_rows']==408
    assert cfg['expected_calibration_rows']==372
    assert cfg['expected_validation_rows']==36
    assert cfg['apply'] is False
    assert cfg['12d_authority_sha256']==__import__('hashlib').sha256(APPROVED.read_bytes()).hexdigest()


def test_live_apply_requires_explicit_mapping_review_acknowledgement(monkeypatch):
    m=importlib.import_module('R1_15A2_SUPPLY_DEMAND_MASTER_V2_3_1')
    monkeypatch.setenv('R1_15A2_V231_APPLY','1')
    with pytest.raises(RuntimeError,match='CSD408_REVIEW_PENDING'):
        m.load_config()


def test_full_12d_stage_with_408_com_shaped_objects(tmp_path):
    env=helper_for(tmp_path)
    manifest, objects, linkkeys=live_objects(env)
    links=[]
    for no,fr,to in linkkeys:
        links.append(FakeAttr(NO=no,FROMNODENO=fr,TONODENO=to,TYPENO=1,
                              TSYSSET='C,C_noT,LNV,NV',LENGTH=1.0,CAPPRT=1600,V0PRT=80))
    visum=FakeAttr(Net=FakeAttr(CountLocations=FakeCollection(objects),
                               Links=FakeCollection(links),LinkTypes=FakeCollection([])))
    m=importlib.import_module('R1_15A2_SUPPLY_DEMAND_MASTER_V2_3_1')
    rt=importlib.import_module('r1_15a2_runtime_v1')
    result=rt.run_12d(visum,tmp_path/'stage','MOCK',m.load_config())
    assert result['row_gate']=={'rows':408,'calibration':372,'validation':36}
    assert result['summary']['status']=='PASS'
    evidence=list((tmp_path/'stage').rglob('19_CSD408_AUTHORITY_CHECK.json'))
    assert evidence
    assert __import__('json').loads(evidence[0].read_text(encoding='utf-8'))['status'].startswith('PASS_EXACT')

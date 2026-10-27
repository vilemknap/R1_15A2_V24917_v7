from __future__ import annotations
import hashlib
import importlib
import json
import math
import shutil
from pathlib import Path
import pytest
from conftest import FakeAttr, FakeCollection
import r1_15a2_core as core
from r1_15a2_supply import ActualRouteCollector, SupplyPolicy
from r1_15a2_sequence_v23 import ActualSequenceRouteCollector

ROOT=Path(__file__).resolve().parents[1]
HELPER=ROOT/'helpers'/'R1_12D_CSD408_CITY90_RPDI_498_APPROVED.py'
AUTH1=ROOT/'authorities'/'R1_CSD2022_COUNTLOCATION_AUTHORITY_408.csv'
AUTH2=ROOT/'authorities'/'R1_CITY_RPDI_COUNTLOCATION_AUTHORITY_90.csv'


def helper_for(tmp_path):
    shutil.copy2(AUTH1,tmp_path/AUTH1.name)
    shutil.copy2(AUTH2,tmp_path/AUTH2.name)
    src=HELPER.read_text(encoding='utf-8')
    prefix=src.split('\ntry:\n    main()\nexcept Exception:',1)[0]
    env={'__file__':str(tmp_path/HELPER.name),'__name__':'12D_CSD408_CITY90_TEST'}
    exec(compile(prefix,str(HELPER),'exec'),env,env)
    return env


def fake_state(env):
    manifest=env['load_manifest']()
    objects=[];links={}
    for r in manifest.values():
        no=int(r['countlocation_no']);key=tuple(int(r[n]) for n in ('current_link_no','current_from_node_no','current_to_node_no'))
        links[key]={'link_no':key[0], 'model_NATIVE_CW':17.0}
        both=r.get('observation_direction')=='BOTH'
        if both:
            reverse=(key[0],key[2],key[1])
            links[reverse]={'link_no':key[0], 'model_NATIVE_CW':31.0}
        scope=r.get('vehicle_scope_original') if both else r['vehicle_scope']
        props={'NO':no,'CODE':r['countlocation_code'],'R1_OBS_ID':r['profile_id'],
               'R1_ROLE':r['role'],'R1_OBS_SCOPE':scope,'R1_OBS_BASIS':r['period_basis'],
               'LINKNO':key[0],'FROMNODENO':key[1],'TONODENO':key[2],
               'R1_OBS_RPDI':float(r['observed_passenger_cars_O']),
               'R1_OBS_VALUE':99999.0,'R1_ACTIVE':1,'R1_WEIGHT':float(r['live_weight'])}
        if both:props['R1_DIRECTION']='BOTH'
        objects.append(FakeAttr(**props))
    return manifest,objects,links


def test_exact_approved_498_and_city_values_no_conversion(tmp_path):
    env=helper_for(tmp_path)
    manifest=env['load_manifest']()
    assert len(manifest)==498
    assert sum(x['role']=='CALIBRATION' for x in manifest.values())==462
    assert sum(x['role']=='VALIDATION' for x in manifest.values())==36
    city=[x for x in manifest.values() if x['source_group']=='CITY_RPDI_LEGACY']
    assert len(city)==90 and all(x['observation_direction']=='BOTH' for x in city)
    assert all(x['conversion_policy']=='RPDI_AUTHORITATIVE_NO_ADDITIONAL_CONVERSION' for x in city)
    assert len([x for x in city if x['vehicle_scope_original']=='OA'])==38


def test_live_roster_and_rpdi_is_unique_observation_source(tmp_path):
    env=helper_for(tmp_path);data,objects,links=fake_state(env)
    assert env['verify_live_authority'](data,objects,links)['rows']==498
    assert env['verify_live_authority'](data,objects,links)['additional_vehicle_conversion'] is False
    assert all(o.AttValue('R1_OBS_VALUE')==99999.0 for o in objects)


def test_city_reverse_link_required_and_role_integrity(tmp_path):
    env=helper_for(tmp_path);data,objects,links=fake_state(env)
    city=next(r for r in data.values() if r['source_group']=='CITY_RPDI_LEGACY')
    key=(int(city['current_link_no']),int(city['current_from_node_no']),int(city['current_to_node_no']))
    del links[(key[0],key[2],key[1])]
    with pytest.raises(RuntimeError,match='CITY90 BOTH reverse directed link unavailable'):
        env['verify_live_authority'](data,objects,links)


def test_city_does_not_halve_or_reconvert_observed(tmp_path):
    env=helper_for(tmp_path);data,objects,links=fake_state(env)
    city=next(r for r in data.values() if r['source_group']=='CITY_RPDI_LEGACY')
    no=int(city['countlocation_no'])
    relevant=[o for o in objects if o.AttValue('NO')==no]
    rows=env['build_detail_rows'](None,data,links,relevant)
    assert len(rows)==1
    r=rows[0]
    assert r['model_NATIVE_CW']==48.0 and r['model']==48.0
    assert r['observed']==float(city['observed_passenger_cars_O'])
    assert r['profile_weight']==0.9
    assert r['observation_direction']=='BOTH' and r['reverse_link_no']==r['link_no']
    assert r['additional_conversion'] is False


def test_inactive_city_not_in_cal_and_activation_without_approval_fails(tmp_path):
    env=helper_for(tmp_path);manifest,objects,links=fake_state(env)
    inactive=FakeAttr(NO=912001,R1_ACTIVE=0)
    visum=FakeAttr(Net=FakeAttr(CountLocations=FakeCollection(objects+[inactive])))
    assert len(env['read_countlocations'](visum))==498
    inactive.SetAttValue('R1_ACTIVE',1)
    with pytest.raises(RuntimeError,match='roster differs'):
        env['verify_live_authority'](manifest,env['read_countlocations'](visum),links)


def test_city_profile_two_key_incidence_and_weighted_objective():
    profile={'link_no':7,'from_node_no':1,'to_node_no':2,
             'observation_direction':'BOTH','reverse_link_no':7,'reverse_from_node_no':2,
             'reverse_to_node_no':1,'observed':210.0,'model':200.0,
             'role':'CALIBRATION','countlocation_no':912055,'profile_weight':0.9}
    assert core._profile_link_keys(profile)==((7,1,2),(7,2,1))
    with pytest.raises(ValueError): core._profile_link_keys(dict(profile,reverse_to_node_no=4))
    p2=dict(profile,observation_direction='DIRECTED',observed=100.0,model=200.0,profile_weight=1.0)
    m=core.csd_metrics([profile,p2])
    g1=core.geh(200,210);g2=core.geh(200,100)
    assert math.isclose(m['objective_geh2_mean'],(0.9*g1*g1+g2*g2)/1.9)
    assert math.isclose(m['objective_weight_sum'],1.9)


def test_two_way_routes_counted_together_for_supply_and_sequence(tmp_path):
    p={'link_no':7,'from_node_no':1,'to_node_no':2,'observation_direction':'BOTH',
       'reverse_link_no':7,'reverse_from_node_no':2,'reverse_to_node_no':1,
       'observed':100.0,'model':200.0,'role':'CALIBRATION','countlocation_no':912055,
       'profile_weight':0.9,'source_group':'CITY_RPDI_LEGACY'}
    policy=SupplyPolicy(min_geh=0.1,min_residual=1.0,min_attribution_coverage=0.99)
    pathrows=[{'dseg_code':'NATIVE_CW','OrigZoneNo':11,'DestZoneNo':12,'Index':1,'Vol(AP)':80},
              {'dseg_code':'NATIVE_CW','OrigZoneNo':12,'DestZoneNo':11,'Index':1,'Vol(AP)':120}]
    links=[{'dseg_code':'NATIVE_CW','OrigZoneNo':11,'DestZoneNo':12,'PathIndex':1,'Index':1,'LinkNo':7,'FromNodeNo':1,'ToNodeNo':2},
           {'dseg_code':'NATIVE_CW','OrigZoneNo':12,'DestZoneNo':11,'PathIndex':1,'Index':1,'LinkNo':7,'FromNodeNo':2,'ToNodeNo':1}]
    dseg={'code':'NATIVE_CW'}
    c=ActualRouteCollector([p],policy,'parent',[(7,1,2),(7,2,1)])
    c.consume(pathrows,links,dseg)
    assert c.flow==[200.0] and c.support=={0:200.0}
    assert c.finish()['profile_parity'][0]['passes']
    s=ActualSequenceRouteCollector([p],policy,'parent',[(7,1,2),(7,2,1)],db_path=tmp_path/'test.sqlite')
    try:
        s.consume(pathrows,links,dseg)
        result=s.finish()
        assert result['profile_parity'][0]['passes']
        assert s.route_count==2
        assert {tuple(x[1]) for x in s.evidence[0]}=={((7,1,2),),((7,2,1),)}
    finally:s.close()


def test_v232_master_config_and_source_hash():
    master=importlib.import_module('R1_15A2_SUPPLY_DEMAND_MASTER_V2_3_2')
    cfg=master.load_config()
    assert cfg['expected_12d_rows']==498 and cfg['expected_calibration_rows']==462
    assert cfg['expected_validation_rows']==36 and cfg['apply'] is False
    assert cfg['12d_city_authority_sha256']==hashlib.sha256(AUTH2.read_bytes()).hexdigest()


def test_v232_full_12d_mock_498(tmp_path):
    env=helper_for(tmp_path);manifest,objects,links=fake_state(env)
    physical=[]
    for (no,fr,to),record in links.items():
        attrs={'NO':no,'FROMNODENO':fr,'TONODENO':to,
               'VOLVEH_DSEG(NATIVE_CW,AP)':record['model_NATIVE_CW'],
               'TYPENO':1,'TSYSSET':'C,C_noT,LNV,NV','LENGTH':1.0,'CAPPRT':1600,'V0PRT':80}
        for code in env['PASSENGER_DSEGS']:
            attrs.setdefault('VOLVEH_DSEG(%s,AP)' % code, 0.0)
        physical.append(FakeAttr(**attrs))
    # City disabled observations can remain alongside active ones.
    objects.append(FakeAttr(NO=912001,R1_ACTIVE=0))
    visum=FakeAttr(Net=FakeAttr(CountLocations=FakeCollection(objects),
                               Links=FakeCollection(physical),LinkTypes=FakeCollection([])))
    master=importlib.import_module('R1_15A2_SUPPLY_DEMAND_MASTER_V2_3_2')
    rt=importlib.import_module('r1_15a2_runtime_v1')
    result=rt.run_12d(visum,tmp_path/'stage','CITY498_MOCK',master.load_config())
    assert result['row_gate']=={'rows':498,'calibration':462,'validation':36}
    city=next(r for r in result['rows'] if r['source_group']=='CITY_RPDI_LEGACY')
    assert float(city['model'])>0 and float(city['profile_weight'])==0.9
    assert city['observation_value_source']=='R1_OBS_RPDI'
    assert len(list((tmp_path/'stage').rglob('19_CSD408_CITY90_AUTHORITY_CHECK.json')))==1


def test_generation_incidence_uses_both_directional_keys():
    profile={'link_no':7,'from_node_no':1,'to_node_no':2,'observation_direction':'BOTH',
             'reverse_link_no':7,'reverse_from_node_no':2,'reverse_to_node_no':1,
             'observed':210.0,'model':200.0,'role':'CALIBRATION',
             'countlocation_no':912055,'profile_weight':0.9}
    paths=[{'dseg_code':'NATIVE_CW','OrigZoneNo':11,'DestZoneNo':12,'Index':1,'Vol(AP)':80},
           {'dseg_code':'NATIVE_CW','OrigZoneNo':12,'DestZoneNo':11,'Index':1,'Vol(AP)':120}]
    links=[{'dseg_code':'NATIVE_CW','OrigZoneNo':11,'DestZoneNo':12,'PathIndex':1,'Index':1,
            'LinkNo':7,'FromNodeNo':1,'ToNodeNo':2},
           {'dseg_code':'NATIVE_CW','OrigZoneNo':12,'DestZoneNo':11,'PathIndex':1,'Index':1,
            'LinkNo':7,'FromNodeNo':2,'ToNodeNo':1}]
    result=core.build_actual_path_incidence(paths,links,[profile],mutable_dsegs=['NATIVE_CW'])
    assert len(result['profiles'])==1
    assert result['profiles'][0]['_link_keys']==((7,1,2),(7,2,1))
    assert float(result['full_profile_model_from_paths'][0])==200.0
    assert float(result['mutable_profile_model_from_paths'][0])==200.0

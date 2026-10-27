from __future__ import annotations
import json
from pathlib import Path
import r1_15a2_visum_parameters as vp
import r1_15a2_multiblock as mb
from test_visum_and_master import make_visum
from conftest import FakeZones

ROOT = Path(__file__).resolve().parents[1]
CFG = json.loads((ROOT/'R1_15A2_CONFIG_V2_3_5.json').read_text(encoding='utf-8'))
AUTH = json.loads((ROOT/'authorities/R1_TG_PARAMETER_DEPENDENCY_CONTRACT_V2_3_5.json').read_text(encoding='utf-8'))


def live_like_visum():
    v = make_visum()
    for i,row in enumerate(v.Net.Zones.rows):
        row['POP_ZP'] = 100
        for a in AUTH['required_zone_attributes']:
            row.setdefault(a, 1.0)
    for code,spec in AUTH['dstrata'].items():
        tg=v.Procedures.Operations.items[0].TripGenerationParameters.TripGenerationDStratParameters.ItemByKey(code)
        tg.SetAttValue('PRODUCTIONFUNCTION','['+spec['production_outer_attribute']+']')
        tg.SetAttValue('ATTRACTIONFUNCTION','['+spec['attraction_outer_attribute']+']')
    return v


def config():
    return {**CFG,'tg_dependency_contract':AUTH}


def test_live_formula_extracted_population_authority():
    data=json.loads((ROOT/'authorities/R1_TG_NESTED_FORMULA_POP_ZP_LIVE_EVIDENCE_20261015.json').read_text(encoding='utf-8'))
    assert data['population_attr']=='POP_ZP' and data['neighbour_positive_population_zones']==6
    fs=[r['formula'] for r in data['formulas']]
    assert any('[POP_ZP]*[ZAHR_PROD_WORK]*[ZAHR_SUSED]' in x for x in fs)
    assert any('[POP_ZP]*[ZAHR_ATR_SERV]*[ZAHR_SUSED]' in x for x in fs)
    assert '[POP_ZP]' in ' '.join(fs)
    assert all('POP_ZP_2022' not in x for x in fs)


def test_all_v235_new_required_zone_attributes_are_defined():
    assert 'POP_ZP' in AUTH['required_zone_attributes']
    assert 'POP_ZP_2022' not in AUTH['required_zone_attributes']
    assert CFG['zahr']['population_attr']=='POP_ZP'
    assert len(AUTH['dstrata'])==10
    assert 'FA_1_WORK' in AUTH['required_zone_attributes']
    assert 'FP_2_SERVICE_noE_C' in AUTH['required_zone_attributes']


def test_live_outer_tg_fp_fa_references_pass():
    r=vp.audit_trip_generation_contract(live_like_visum(),config())
    assert r['passes'],r['failures']
    assert len(r['rows'])==10
    assert all(x['production_binding_mode']=='VERIFIED_OUTER_ZONE_ATTRIBUTE_REFERENCE' for x in r['rows'])
    assert all(x['attraction_binding_mode']=='VERIFIED_OUTER_ZONE_ATTRIBUTE_REFERENCE' for x in r['rows'])


def test_missing_population_attr_fails_closed():
    v=live_like_visum()
    for row in v.Net.Zones.rows: row.pop('POP_ZP')
    r=vp.audit_trip_generation_contract(v,config())
    assert not r['passes']
    assert 'TG_ZONE_ATTRIBUTE_UNREADABLE:POP_ZP' in r['failures']


def test_wrong_outer_tg_reference_fails():
    v=live_like_visum()
    obj=v.Procedures.Operations.items[0].TripGenerationParameters.TripGenerationDStratParameters.ItemByKey('1_WORK_E_C')
    obj.SetAttValue('PRODUCTIONFUNCTION','[FP_UNRELATED]')
    r=vp.audit_trip_generation_contract(v,config())
    assert not r['passes'] and 'TG_FORMULA_MISMATCH:1_WORK_E_C' in r['failures']


def test_no_unapproved_population_alias_in_inline_formula():
    v=live_like_visum()
    obj=v.Procedures.Operations.items[0].TripGenerationParameters.TripGenerationDStratParameters.ItemByKey('1_WORK_E_C')
    obj.SetAttValue('PRODUCTIONFUNCTION','[ADD_PROD_W]*[NOT_ZAHR]+[ZAHR_PROD_WORK]*[ZAHR_SUSED]*[POP_ZP_2022]')
    r=vp.audit_trip_generation_contract(v,config())
    assert not r['passes'] and 'TG_FORMULA_MISMATCH:1_WORK_E_C' in r['failures']


def test_generation_six_foreign_with_population_only():
    rows=[]
    for z in range(1,16):
        rows.append({'zone_no':z,'NOT_ZAHR':0,'ZAHR_SUSED':1,'POP_ZP':100 if z <= 6 else 0,
            'ZAHR_PROD_WORK':2,'ZAHR_ATR_WORK':2,'ZAHR_PROD_SERV':2,'ZAHR_ATR_SERV':2,
            'ADD_PROD_W':0,'ADD_ATT_W':0,'ADD_SALARY':0,'ADD_PROD_S':0,'ADD_ATT_S':0})
    project=[{'zone_no':z,'family':'SERVICE','role':'PROD','log_step':0.03,'base_margin_volume':100} for z in range(1,16)]
    got=mb.design_generation_candidates(project,rows,CFG)
    assert {x['zone_no'] for x in got['candidate_rows']}==set(range(1,7))
    assert {x['zone_no'] for x in got['skipped_rows']}==set(range(7,16))
    assert {x['reason'] for x in got['skipped_rows']}=={'ZAHR_FORMULA_BASE_INACTIVE'}


def test_inline_preflight_has_new_authority_and_no_old_population_requirement():
    s=(ROOT/'R1_15A2_VISUM_COM_PREFLIGHT_V2_3_5_INLINE.py').read_text(encoding='utf-8')
    assert 'ZONE_FOREIGN_POPULATION_ACTUATOR_SCOPE' in s
    assert '\"population_attr\": \"POP_ZP\"' in s or "'population_attr': 'POP_ZP'" in s or '"population_attr": "POP_ZP"' in s
    assert 'R1_15A2_V2_3_5' in s


def test_live_preflight_foreign_zone_scope_counts_15_and_6(tmp_path):
    from conftest import FakeVisum
    import r1_15a2_live_api_audit as api
    rows=[]
    for z in range(1,682):
        foreign=(z > 655)
        neigh=(655 < z <= 670)
        rows.append({'NO':z,'NOT_ZAHR':0 if foreign else 1,
                     'ZAHR_SUSED':1 if neigh else 0,
                     'POP_ZP':10 if 655 < z <= 662 else 0})
    # Seven positive rows initially, then explicitly turn one off.
    rows[660]['POP_ZP']=0
    v=FakeVisum(zones=FakeZones(rows))
    report=api.collect_live_api(v,{'expected_zones':681,'zahr':CFG['zahr'],
                                   'tg_dependency_contract':{},
                                   'supply':{'passenger_dsegs':[],'freight_dsegs':[], 'component_matrix_nos':[]}},
                                tmp_path)
    scope=next(x for x in report['checks'] if x['check']=='ZONE_FOREIGN_POPULATION_ACTUATOR_SCOPE')
    assert scope['status']=='PASS',scope
    assert scope['result']['domestic_zones']==655
    assert scope['result']['foreign_neighbouring_zones']==15
    assert scope['result']['foreign_effective_population_zones']==6
    assert 661 not in scope['result']['effective_zone_nos']


def test_v235_inline_preflight_writes_beside_saved_ver_without_dialogs(tmp_path):
    from conftest import FakeVisum, FakeAttr
    saved = tmp_path/'opened_model'/'R1_2022.ver'
    saved.parent.mkdir()
    saved.write_text('fixture',encoding='utf-8')
    arbitrary = tmp_path/'wrong_project_folder'
    arbitrary.mkdir()
    v=FakeVisum(zones=FakeZones([{'NO':z,'NOT_ZAHR':1,'ZAHR_SUSED':0,'POP_ZP':1} for z in range(1,682)]))
    v.IO=FakeAttr(CurrentVersionFile=str(saved))
    v.GetPath=lambda _type: str(arbitrary)
    source=(ROOT/'R1_15A2_VISUM_COM_PREFLIGHT_V2_3_5_INLINE.py').read_text(encoding='utf-8')
    assert 'MessageBoxW' not in source
    ns={'Visum':v,'__name__':'visum_internal_script'}
    exec(compile(source,'<Visum Internal script>','exec'),ns,ns)
    folder=Path(ns['R1_COM_PREFLIGHT_OUTPUT'])
    assert folder.parent==saved.parent/'R1_15A2_COM_API_PREFLIGHT'
    assert (folder/'COM_API_PREFLIGHT.json').is_file()
    assert (folder/'00_FINAL_STATUS.txt').is_file()
    assert not list(arbitrary.iterdir())
    data=json.loads((folder/'COM_API_PREFLIGHT.json').read_text(encoding='utf-8'))
    assert data['release']=='R1_15A2_V2_3_5_LIVE_API_REMEDIATION'
    assert data['read_only_model'] is True
    assert data['assignment_executed'] is False

from __future__ import annotations
import json, copy, re
from pathlib import Path
import pytest
import r1_15a2_visum_parameters as vp
from conftest import FakeAttr, FakeCollection
from test_v235_population_live import live_like_visum

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = json.loads((ROOT/'authorities/R1_TG_PARAMETER_DEPENDENCY_CONTRACT_V2_3_6.json').read_text(encoding='utf-8'))
CFG = json.loads((ROOT/'R1_15A2_CONFIG_V2_3_6.json').read_text(encoding='utf-8'))


def expected(code, spec, role):
    return '[%s] + [%s]' % (spec[role+'_outer_attribute'],spec[role+'_additive_attribute'])


def visum_from_actual_readback():
    v=live_like_visum()
    for row in v.Net.Zones.rows:
        for attr in CONTRACT['required_zone_attributes']:
            row.setdefault(attr,1.0)
    v.Net.Zones.Attributes=FakeCollection([FakeAttr(ID=key, ValueType=type_no) for key,type_no in CONTRACT['expected_zone_attribute_types'].items()])
    evidence=json.loads((ROOT/'authorities/R1_TG_OPERATION_5_ADDITIVE_LIVE_EVIDENCE_20261016.json').read_text(encoding='utf-8'))
    for row in evidence['dstrata_formula_readback']:
        obj=v.Procedures.Operations.items[0].TripGenerationParameters.TripGenerationDStratParameters.ItemByKey(row['dstrat_code'])
        obj.SetAttValue('PRODUCTIONFUNCTION',row['production'])
        obj.SetAttValue('ATTRACTIONFUNCTION',row['attraction'])
    return v


def config():
    return {**CFG,'tg_dependency_contract':CONTRACT}


def change_tg(v,role,formula,code='1_WORK_E_C'):
    obj=v.Procedures.Operations.items[0].TripGenerationParameters.TripGenerationDStratParameters.ItemByKey(code)
    obj.SetAttValue('PRODUCTIONFUNCTION' if role=='production' else 'ATTRACTIONFUNCTION',formula)


def test_10_real_visum_tg_pairs_pass_new_exact_contract():
    r=vp.audit_trip_generation_contract(visum_from_actual_readback(),config())
    assert r['passes'],r['failures']
    assert len(r['rows'])==10
    assert all(x['production_binding_mode']=='VERIFIED_OUTER_PLUS_09F4_PREFEED' for x in r['rows'])
    assert all(x['attraction_binding_mode']=='VERIFIED_OUTER_PLUS_09F4_PREFEED' for x in r['rows'])
    assert sum(x['status']=='TYPE_OK' for x in r['zone_attribute_rows'])==21
    assert sum(x['status']=='OK' for x in r['zone_attribute_rows'])==len(CONTRACT['required_zone_attributes'])


@pytest.mark.parametrize('bad_formula',[
    '[FP_1_WORK_E_C]',
    '[FP_1_WORK_E_C] + [P09F4_PER_PRE_WORK_E_NOC]',
    '[FP_1_WORK_E_C] + [P09F4_PER_PRE_WORK_E_C] + [ANOTHER]',
    '[FP_1_WORK_E_C] * [P09F4_PER_PRE_WORK_E_C]',
    '2 * [FP_1_WORK_E_C] + [P09F4_PER_PRE_WORK_E_C]',
    '[P09F4_PER_PRE_WORK_E_C] + [FP_1_WORK_E_C]',
    '[FP_1_WORK_E_C] + [P09F4_PER_PRE_WORK_E_C] / 2',
    '[FP_1_WORK_E_C] + [POP_ZP_2022]',
    '[FP_1_WORK_E_C] + [P09F4_PER_PRE_WORK_E_C] + [P09F4_PER_PRE_WORK_E_C]',
])
def test_wrong_foreign_prefeed_or_tg_formula_fails_closed(bad_formula):
    v=visum_from_actual_readback()
    change_tg(v,'production',bad_formula)
    result=vp.audit_trip_generation_contract(v,config())
    assert not result['passes']
    assert 'TG_FORMULA_MISMATCH:1_WORK_E_C' in result['failures']


def test_wrong_attraction_prefeed_fails_closed():
    v=visum_from_actual_readback()
    change_tg(v,'attraction','[FA_1_WORK] + [A09F4_PER_PRE_SERV_E_C]')
    r=vp.audit_trip_generation_contract(v,config())
    assert not r['passes']
    assert 'TG_FORMULA_MISMATCH:1_WORK_E_C' in r['failures']


def test_only_spacing_and_case_is_tolerated():
    v=visum_from_actual_readback()
    change_tg(v,'production',' [ fp_1_work_e_c ]\n+\t[ p09f4_per_pre_work_e_c ] ')
    r=vp.audit_trip_generation_contract(v,config())
    assert r['passes'],r['failures']


def test_live_zone_prefeed_missing_fails_closed():
    v=visum_from_actual_readback()
    attr='P09F4_PER_PRE_WORK_E_C'
    for row in v.Net.Zones.rows:row.pop(attr,None)
    r=vp.audit_trip_generation_contract(v,config())
    assert not r['passes']
    assert 'TG_ZONE_ATTRIBUTE_UNREADABLE:'+attr in r['failures']


def test_live_zone_prefeed_nonnumeric_fails_closed():
    v=visum_from_actual_readback()
    v.Net.Zones.rows[0]['A09F4_PER_PRE_WORK_E_C']='oops'
    r=vp.audit_trip_generation_contract(v,config())
    assert not r['passes']
    assert 'TG_ZONE_ATTRIBUTE_UNREADABLE:A09F4_PER_PRE_WORK_E_C' in r['failures']


def test_live_zone_prefeed_wrong_datatype_fails_closed():
    v=visum_from_actual_readback()
    defs=v.Net.Zones.Attributes.items
    next(x for x in defs if x.ID=='P09F4_PER_PRE_WORK_E_C').ValueType=5
    r=vp.audit_trip_generation_contract(v,config())
    assert not r['passes']
    assert 'TG_ZONE_ATTRIBUTE_TYPE_MISMATCH:P09F4_PER_PRE_WORK_E_C' in r['failures']


def test_schema_missing_fails_closed():
    v=visum_from_actual_readback()
    v.Net.Zones.Attributes=None
    r=vp.audit_trip_generation_contract(v,config())
    assert not r['passes']
    assert 'TG_ZONE_ATTRIBUTE_SCHEMA_UNREADABLE' in r['failures']


def test_contract_source_evidence_exact_equality():
    ev=json.loads((ROOT/'authorities/R1_TG_OPERATION_5_ADDITIVE_LIVE_EVIDENCE_20261016.json').read_text(encoding='utf-8'))
    assert len(ev['dstrata_formula_readback'])==10
    assert len(ev['real_pre_input_schema'])==20
    assert all(a['ValueType']==2 for a in ev['real_pre_input_schema'])
    for row in ev['dstrata_formula_readback']:
        spec=CONTRACT['dstrata'][row['dstrat_code']]
        for field in ('production','attraction'):
            actual=re.sub(r'\s+','',row[field]).upper()
            exp=re.sub(r'\s+','',expected(row['dstrat_code'],spec,field)).upper()
            assert actual==exp
    assert 'POP_ZP_2022' not in str(CONTRACT)
    assert CFG['apply'] is False and CFG['supply']['assignment_operations']==[]


def test_inline_code_contains_strict_additive_gate():
    code=(ROOT/'R1_15A2_VISUM_COM_PREFLIGHT_V2_3_6_INLINE.py').read_text(encoding='utf-8')
    assert 'TG_09F4_OUTER_FORMULAS_AND_TYPED_SCHEMA' in code
    assert 'TG_ZONE_ATTRIBUTE_TYPE_MISMATCH' in code
    assert 'R1_15A2_V2_3_6_LIVE_TG_09F4_PREFEED_REMEDIATION' in code
    assert 'MessageBoxW' not in code
    assert 'CurrentVersionFile' in code

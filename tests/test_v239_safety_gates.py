from pathlib import Path
import inspect
import json
import sqlite3
import pytest

from conftest import FakeAttr, FakeCollection, FakeOperation, FakeVisum
from test_supply_visum_v22 import state_visum, small_cfg
from test_two_mode_v238 import hierarchy

import r1_15a2_runtime_v1 as rt
from r1_15a2_assignment_authority_v239 import audit_assignment_scope, EXPECTED, config_rule_for_op20
from r1_15a2_full_geometry_gate_v239 import route_digests, _open_db, _aggregate_reference_hash
from r1_15a2_inplace_transaction_v239 import restore_supply_parameters, restore_generation_parameters
from r1_15a2_supply import SupplyContractError
from r1_15a2_supply_visum import VisumAdapter, assignment_plan


def full_scope_visum():
    ops=[]
    for no in range(1,17):
        ops.append(FakeOperation(NO=no,OPERATIONTYPE=75 if no in (2,4,7,9,13,16) else 65,ACTIVE=1,NAME='x'))
    raw={
        17:'LNV,NV',
        18:'NATIVE_CF,NATIVE_CL',
        19:'NATIVE_CS,NATIVE_CS_noT,NATIVE_CW,NATIVE_CW_noT',
        20:'EXOG_EE_CF,EXOG_EE_CL,EXOG_EE_CS,EXOG_EE_CS_noT,EXOG_EE_CW,EXOG_EE_CW_noT,LNV,NATIVE_CF,NATIVE_CL,NATIVE_CS,NATIVE_CS_noT,NATIVE_CW,NATIVE_CW_noT,NV',
    }
    for no in (17,18,19,20):
        ops.append(FakeOperation(NO=no,OPERATIONTYPE=101,ACTIVE=1,COMMENT='assignment',PrTAssignmentParameters=FakeAttr(DSEGSET=raw[no])))
    return FakeVisum(operations=ops)


def test_assignment_authority_exact_17_20_and_selects_only_20():
    a=audit_assignment_scope(full_scope_visum())
    assert a['passes'] is True
    assert a['selected_trial_assignment_operations']==[20]
    assert set(a['required_full_scope'])==set(EXPECTED[20])
    assert all(r['status']=='PASS' for r in a['verified_operations'])



def test_live_09c_op20_only_active_is_valid():
    """2026-10-29 live Visum: 17/18/19 inactive, final 20 active and exact."""
    visum = full_scope_visum()
    for no in (17, 18, 19):
        visum.Procedures.Operations.items[no - 1].SetAttValue('ACTIVE', 0)
    before = [op.AttValue('ACTIVE') for op in visum.Procedures.Operations.items]
    audit = audit_assignment_scope(visum)
    assert audit['passes'] is True
    assert audit['failures'] == []
    assert audit['selected_trial_assignment_operations'] == [20]
    assert [row['status'] for row in audit['verified_operations']] == [
        'PASS_INACTIVE_PARTIAL', 'PASS_INACTIVE_PARTIAL',
        'PASS_INACTIVE_PARTIAL', 'PASS']
    assert all(set(row['live_dsegs']) == set(row['expected_dsegs'])
               for row in audit['verified_operations'])
    assert [op.AttValue('ACTIVE') for op in visum.Procedures.Operations.items] == before


@pytest.mark.parametrize('position', [17, 18, 19])
def test_inactive_partial_scope_drift_is_rejected(position):
    visum = full_scope_visum()
    for no in (17, 18, 19):
        visum.Procedures.Operations.items[no - 1].SetAttValue('ACTIVE', 0)
    visum.Procedures.Operations.items[position - 1].PrTAssignmentParameters.SetAttValue(
        'DSEGSET', 'LNV,NV,EXTRA')
    audit = audit_assignment_scope(visum)
    assert audit['passes'] is False
    assert 'OP_%d_DSEGSET' % position in audit['failures']
    assert audit['selected_trial_assignment_operations'] == []


def test_final_op20_inactive_is_still_rejected():
    visum = full_scope_visum()
    for no in (17, 18, 19, 20):
        visum.Procedures.Operations.items[no - 1].SetAttValue('ACTIVE', 0)
    audit = audit_assignment_scope(visum)
    assert audit['passes'] is False
    assert audit['failures'] == ['OP_20_INACTIVE']
    assert audit['selected_trial_assignment_operations'] == []


def test_inactive_partial_wrong_type_remains_rejected():
    visum = full_scope_visum()
    visum.Procedures.Operations.items[16].SetAttValue('ACTIVE', 0)
    visum.Procedures.Operations.items[16].SetAttValue('OPERATIONTYPE', 65)
    audit = audit_assignment_scope(visum)
    assert audit['passes'] is False
    assert audit['failures'] == ['OP_17_TYPE']



def test_assignment_authority_rejects_op20_scope_drift():
    v=full_scope_visum()
    v.Procedures.Operations.items[19].PrTAssignmentParameters.SetAttValue('DSEGSET','NATIVE_CW,LNV,NV')
    a=audit_assignment_scope(v)
    assert not a['passes']
    assert 'OP_20_DSEGSET' in a['failures']


def test_exact_scope_is_enforced_by_authority_before_assignment_plan():
    v=full_scope_visum()
    assert audit_assignment_scope(v)['passes'] is True
    v.Procedures.Operations.items[19].PrTAssignmentParameters.SetAttValue(
        'DSEGSET',
        'EXOG_EE_CF,EXOG_EE_CL,EXOG_EE_CS,EXOG_EE_CS_noT,EXOG_EE_CW,EXOG_EE_CW_noT,LNV,'
        'NATIVE_CF,NATIVE_CL,NATIVE_CS,NATIVE_CS_noT,NATIVE_CW,NV,EXTRA'
    )
    a=audit_assignment_scope(v)
    assert not a['passes']
    row=[r for r in a['verified_operations'] if r['no']==20][0]
    assert row['status']=='DSEGSET_MISMATCH'
    assert 'NATIVE_CW_NOT' in row['missing']
    assert 'EXTRA' in row['extra']


def test_route_digest_semantics_exact_and_mismatch():
    rows=hierarchy()
    a=list(route_digests(iter(rows)))
    b=list(route_digests(iter([list(x) for x in rows])))
    assert a==b and len(a)==2
    damaged=[list(x) for x in rows]
    damaged[2][4]=999
    c=list(route_digests(iter(damaged)))
    assert a[0][1]!=c[0][1]


def test_route_digest_allows_flat_parent_rows():
    rows=[]
    for raw in hierarchy():
        if raw[0] != '':
            parent=raw[:3]
            continue
        rows.append(parent + raw[3:])
    got=list(route_digests(iter(rows)))
    assert len(got)==2
    assert got[0][0]==(1,2,1)


def test_reference_database_aggregate_is_order_independent(tmp_path):
    db=_open_db(tmp_path/'g.sqlite')
    try:
        rows=[('C',2,3,1,'11'*32,4),('C',1,2,1,'22'*32,3)]
        db.executemany('INSERT INTO reference VALUES(?,?,?,?,?,?)',rows);db.commit()
        x=_aggregate_reference_hash(db,'C')
        assert x[1:]==(2,7)
        db2=_open_db(tmp_path/'h.sqlite')
        try:
            db2.executemany('INSERT INTO reference VALUES(?,?,?,?,?,?)',reversed(rows));db2.commit()
            assert _aggregate_reference_hash(db2,'C')==x
        finally: db2.close()
    finally: db.close()


def test_restore_supply_parameter_from_snapshot(tmp_path):
    v=state_visum(); a=VisumAdapter(v,small_cfg()); before=a.snapshot()
    key=next(iter(a.read_links()))
    obj=a.read_links()[key]['object']; old=obj.AttValue('ADDVAL1')
    obj.SetAttValue('ADDVAL1',old+1)
    audit=restore_supply_parameters(a,before,[{'key':list(key)}],tmp_path)
    assert audit[0]['passes']
    assert obj.AttValue('ADDVAL1')==old


def test_restore_generation_parameter_from_snapshot(tmp_path):
    v=state_visum(); a=VisumAdapter(v,small_cfg()); before=a.snapshot()
    attr='ADD_PROD_W'; z=a.zones[0]
    vals=rt.read_zone_attr_strict(v,attr,a.zones); vals[0]+=0.1
    rt.write_zone_attr(v,attr,a.zones,vals)
    audit=restore_generation_parameters(a,before,[{'zone_no':z,'attr':attr}],tmp_path)
    assert audit[0]['passes']
    assert rt.read_zone_attr_strict(v,attr,a.zones)[0]==pytest.approx(before['generation_values'][attr][str(z)])


def test_safety_scripts_do_not_call_load_or_save_version():
    root=Path(__file__).resolve().parents[1]
    for name in ('R1_15A2_15T_ASSIGNMENT_SCOPE_FULL_GEOMETRY_READONLY.py',
                 'R1_15A2_15U_NO_LOADVERSION_ROLLBACK_SMOKE.py',
                 'r1_15a2_inplace_transaction_v239.py'):
        text=(root/name).read_text(encoding='utf-8')
        assert '.LoadVersion(' not in text
        assert 'rt.load_version(' not in text
        assert '.SaveVersion(' not in text
        assert 'rt.save_version(' not in text


def test_v239_config_approves_only_op20():
    root=Path(__file__).resolve().parents[1]
    cfg=json.loads((root/'R1_15A2_CONFIG_V2_3_9.json').read_text(encoding='utf-8'))
    assert cfg['apply'] is False
    assert cfg['supply']['assignment_operations']==[config_rule_for_op20()]


def test_run_one_attempts_rollback_even_when_candidate_assignment_fails(tmp_path, monkeypatch):
    import importlib.util
    root=Path(__file__).resolve().parents[1]
    spec=importlib.util.spec_from_file_location('gate15u',root/'R1_15A2_15U_NO_LOADVERSION_ROLLBACK_SMOKE.py')
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    class Obj:
        def __init__(self): self.v=0.0
        def SetAttValue(self,n,v): self.v=v
        def AttValue(self,n): return self.v
    obj=Obj(); key=(1,2,3)
    class A:
        cfg={'supply':{'link_attributes':{}}}
        def read_links(self): return {key:{'eligible':True,'length':1.0,'addval1':obj.v,'object':obj}}
        def assign(self,*a,**k): raise RuntimeError('candidate assignment failed')
    adapter=A()
    baseline={'state_hash':'s','addval1':{'1|2|3':0.0}}
    diag={'d12':{'rows':[]}}
    called=[]
    def fake_rb(*args,**kwargs):
        called.append(True); obj.v=0.0
        return ({'passes':True},diag)
    monkeypatch.setattr(mod,'rollback_and_verify',fake_rb)
    monkeypatch.setattr(mod,'diagnostic_hash',lambda d:'baseline-hash')
    with pytest.raises(RuntimeError,match='candidate assignment failed'):
        mod.run_one(adapter,'SUPPLY_ADDVAL1',baseline,diag,tmp_path)
    assert called==[True]
    assert obj.v==0.0


def test_assignment_scope_config_does_not_modify_v238_authority():
    root=Path(__file__).resolve().parents[1]
    old=json.loads((root/'R1_15A2_CONFIG_V2_3_8.json').read_text(encoding='utf-8'))
    new=json.loads((root/'R1_15A2_CONFIG_V2_3_9.json').read_text(encoding='utf-8'))
    assert old['supply']['assignment_operations']==[]
    assert new['supply']['assignment_operations']==[config_rule_for_op20()]


def _load_15u_module():
    import importlib.util
    root=Path(__file__).resolve().parents[1]
    spec=importlib.util.spec_from_file_location('gate15u_ack',root/'R1_15A2_15U_NO_LOADVERSION_ROLLBACK_SMOKE.py')
    mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod


def test_15u_requires_explicit_working_copy_ack(tmp_path):
    mod=_load_15u_module()
    wrong=tmp_path/'work.ver'; wrong.write_bytes(b'x')
    with pytest.raises(SupplyContractError,match='15U_WORKING_COPY_FILENAME_TOKEN_REQUIRED'):
        mod.require_working_copy_ack(wrong)
    ver=tmp_path/'R1_15U_WORKING_COPY.ver'; ver.write_bytes(b'x')
    with pytest.raises(SupplyContractError,match='15U_WORKING_COPY_ACK_MISSING'):
        mod.require_working_copy_ack(ver)
    (tmp_path/mod.ACK_FILENAME).write_text('wrong',encoding='utf-8')
    with pytest.raises(SupplyContractError,match='15U_WORKING_COPY_ACK_CONTENT_INVALID'):
        mod.require_working_copy_ack(ver)
    (tmp_path/mod.ACK_FILENAME).write_text(mod.ACK_TEXT+'\n',encoding='utf-8')
    assert mod.require_working_copy_ack(ver)['passes'] is True


def test_15u_requires_same_sha_passed_15t_authority(tmp_path):
    mod=_load_15u_module()
    ver=tmp_path/'R1_15U_WORKING_COPY.ver'; ver.write_bytes(b'model')
    gate=tmp_path/'R1_15A2_15T_SAFETY_GATE'; run=gate/'RUN_X'; run.mkdir(parents=True)
    (gate/'LATEST_RUN.txt').write_text(str(run),encoding='utf-8')
    sha=rt.sha256_file(ver)
    authority={
        'status':'PASS_ASSIGNMENT_SCOPE_AND_FULL_GEOMETRY_IDENTITY',
        'loaded_version_file':'original.ver','version_sha256':sha,
        'assignment_scope':{'passes':True,'selected_trial_assignment_operations':[20]},
        'full_geometry':{'full_geometry_identity_proven':True},
        'model_state_hash_before':'state-x','model_state_hash_after':'state-x','model_state_unchanged':True,
    }
    (run/'15T_SAFETY_GATE_RESULT.json').write_text(json.dumps(authority),encoding='utf-8')
    auth=mod.require_15t_authority(ver)
    assert auth['passes'] is True and auth['model_state_hash']=='state-x'
    ver.write_bytes(b'changed')
    with pytest.raises(SupplyContractError,match='15T_VERSION_SHA256_MISMATCH_WORKING_COPY'):
        mod.require_15t_authority(ver)


def test_15u_micro_mutations_are_small_but_not_rounding_dust():
    mod=_load_15u_module()
    class A:
        zones=[1]
        actuatable_zones=[1]
    before={'generation_values':{'ADD_PROD_W':{'1':1.0}},
            'td_values':[{'component':'WORK_E_C','current_b':1.0,'current_c':-1.0}]}
    grow=mod.choose_generation_smoke(A(),before)[0]
    td=mod.choose_td_smoke(before)[0]
    assert grow['proposed']-grow['current']==pytest.approx(1e-4)
    assert td['candidate_b']-1.0==pytest.approx(1e-4)

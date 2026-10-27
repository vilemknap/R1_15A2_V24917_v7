"""Regression against documented COM semantics, NOT live Visum qualification."""
import importlib
import json
from pathlib import Path
import pytest
from conftest import FakeAttr, FakeCollection, FakeOperation, FakeVisum
from test_visum_and_master import make_visum, config
from test_supply_visum_v22 import state_visum, small_cfg, exporter_visum
from test_supply_v22 import profile
import r1_15a2_com_compat as com
import r1_15a2_runtime_v1 as rt
import r1_15a2_visum_parameters as vp
import r1_15a2_supply_visum as sv
from r1_15a2_supply import SupplyContractError
import r1_15a2_live_api_audit as live

ROOT = Path(__file__).resolve().parents[1]


class CallableDispatch:
    _oleobj_ = object()
    calls = 0
    def __call__(self, *args):
        self.calls += 1
        raise AssertionError('Returned COM object must NOT be called as a factory')


def test_returned_com_property_is_not_a_factory():
    obj = CallableDispatch()
    parent = FakeAttr(CreatePrTPathList=obj)
    assert callable(obj)
    assert rt.create_list(parent, 'CreatePrTPathList') is obj
    assert obj.calls == 0


def test_python_factory_fixture_is_supported():
    expected = object()
    assert rt.create_list(FakeAttr(CreatePrTPathList=lambda: expected), 'CreatePrTPathList') is expected


class OperationsNoCount:
    def __init__(self, rows): self.rows = rows
    @property
    def GetAll(self): return tuple(self.rows)
    def ItemByKey(self, position): return self.rows[position-1]


def test_operations_have_position_not_no_and_need_no_count():
    ops = [FakeOperation(OPERATIONTYPE=45, ACTIVE=-1), FakeOperation(OPERATIONTYPE=101, ACTIVE=0)]
    v = FakeAttr(Procedures=FakeAttr(Operations=OperationsNoCount(ops)))
    rows = sv.operation_inventory(v, {})
    assert [(r['no'],r['active']) for r in rows] == [(1,1),(2,0)]
    ops[1].SetAttValue('NO', 923456)
    assert sv.operation_inventory(v,{})[1]['no'] == 2


@pytest.mark.parametrize('value,expected', [(True,True),(False,False),(-1,True),(1.0,True),(0.0,False),
    ('-1',True),('TRUE',True),('False',False),('1.0',True),('0.0',False)])
def test_variant_bool(value,expected): assert com.active_bool(value) is expected


@pytest.mark.parametrize('value', [None,'',2,-2,float('nan'),'possibly'])
def test_invalid_active_is_not_silently_false(value):
    with pytest.raises(RuntimeError): com.active_bool(value)


def test_real_count_if_available_must_match():
    c=FakeCollection([1,2]); c.Count=3
    with pytest.raises(RuntimeError,match='INCOMPLETE'): com.collection_items(c)


def test_no_itembykey_1_to_count_guess_for_sparse_keys():
    class Sparse:
        Count=2
        def ItemByKey(self,k):raise AssertionError('Must not guess sparse IDs')
    with pytest.raises(RuntimeError,match='GETALL'):com.collection_items(Sparse())


def test_numeric_proc_type_not_comment_controls_assignment(tmp_path):
    v=FakeVisum(operations=[FakeOperation(OPERATIONTYPE=45,ACTIVE=-1,COMMENT='X'),
        FakeOperation(OPERATIONTYPE=46,ACTIVE=-1,COMMENT='Y'),
        FakeOperation(OPERATIONTYPE=100,ACTIVE=1,COMMENT='PrT ASSIGNMENT'),
        FakeOperation(OPERATIONTYPE=103,ACTIVE=1,COMMENT='ASSIGNMENT SKIMS'),
        FakeOperation(OPERATIONTYPE=101,ACTIVE=-1,COMMENT='Prirazeni vozidel')])
    result=rt.audit_procseq(v,tmp_path,{'require_active_tg_td':True,'require_active_assignment':True})
    assert result['passes'] and result['assignment_indices']==[5]


def test_assignment_keeps_active_groups_and_restores_all_flags():
    v=FakeVisum(operations=[FakeOperation(OPERATIONTYPE=75,ACTIVE=-1),
          FakeOperation(OPERATIONTYPE=45,ACTIVE=1),
          FakeOperation(OPERATIONTYPE=101,ACTIVE=-1,PrTAssignmentParameters=FakeAttr(DSEGSET='NATIVE_CW,LNV,NV')),
          FakeOperation(OPERATIONTYPE=75,ACTIVE=0)])
    v.Net.SetAttValue('GAP',0.0)
    cfg=small_cfg();cfg['supply']['assignment_operations'][0].pop('dseg_object_path')
    with sv.assignment_only_operations(v,cfg):
        assert [int(com.active_bool(x.AttValue('ACTIVE'))) for x in v.Procedures.Operations.items]==[1,0,1,0]
    assert [int(com.active_bool(x.AttValue('ACTIVE'))) for x in v.Procedures.Operations.items]==[1,1,1,0]


def test_fake_operation900_cannot_be_approved_even_with_matching_rule():
    v=state_visum();v.Procedures.Operations.items[2].SetAttValue('OPERATIONTYPE',900)
    cfg=small_cfg();cfg['supply']['assignment_operations'][0]['operation_type']=900
    assert not sv.assignment_plan(v,cfg)['passes']


class IndexedZones:
    def __init__(self):
        self.data={3:{'NO':10,'ADD':1.25},9:{'NO':30,'ADD':4.5}}
        self.last_write=None
    def GetMultiAttValues(self,attr,only_active=False):
        return [(i,row[attr]) for i,row in reversed(list(self.data.items()))]
    def SetMultiAttValues(self,attr,values,add=False):
        assert add is False
        self.last_write=values
        for index,v in values:self.data[index][attr]=v


def test_zone_reads_join_container_index_not_no():
    v=FakeAttr(Net=FakeAttr(Zones=IndexedZones()))
    assert rt.read_zone_attr_strict(v,'ADD',[10,30])==[1.25,4.5]


def test_zone_writes_use_container_index_not_no():
    v=FakeAttr(Net=FakeAttr(Zones=IndexedZones()))
    assert rt.write_zone_attr(v,'ADD',[10,30],[2.25,5.5])==[2.25,5.5]
    assert v.Net.Zones.last_write==[[3,2.25],[9,5.5]]


def test_zone_axis_order_not_sorted_away():
    v=make_visum();v.Net.Zones.rows.reverse()
    with pytest.raises(RuntimeError,match='AXIS_ORDER'):rt.zone_numbers(v)


@pytest.mark.parametrize('value',[None,'',True,1.2,'2,4',float('nan'),float('inf')])
def test_integer_ids_are_exact(value):
    with pytest.raises(RuntimeError):com.exact_int(value)


def test_locale_numeric_list_values():
    assert com.finite_float('1\u00a0234,50')==1234.5
    with pytest.raises(RuntimeError):com.finite_float('1,234.50')


def test_td_set_requires_whole_code_not_substring():
    v=make_visum();p=v.Procedures.Operations.items[1].TripDistributionParameters
    p.SetAttValue('DSTRATSET',p.AttValue('DSTRATSET').replace('1_WORK_E_C,','1_WORK_E_C_BACKUP,'))
    with pytest.raises(RuntimeError,match='DStratSet misses'):vp.read_td_parameter_state(v)


def test_td_blank_scope_cannot_pass_by_reading_arbitrary_children():
    v=make_visum();v.Procedures.Operations.items[1].TripDistributionParameters.SetAttValue('DSTRATSET','')
    with pytest.raises(RuntimeError,match='DStratSet misses'):vp.read_td_parameter_state(v)


def test_two_active_td_operations_with_same_scope_are_ambiguous():
    v=make_visum();v.Procedures.Operations.items.append(v.Procedures.Operations.items[1]);v.Procedures.Operations.Count+=1
    with pytest.raises(RuntimeError,match='locate'):vp.read_td_parameter_state(v)


def test_missing_dseg_odmatrix_not_silently_omitted():
    v=state_visum();v.Net.DemandSegments.items[0].SetAttValue('ODMatrix',None)
    with pytest.raises(SupplyContractError,match='ODMATRIX_UNREADABLE'):sv.VisumAdapter(v,small_cfg()).snapshot()


def test_demand_matrix_shape_contract():
    v=state_visum();cfg=small_cfg();cfg['expected_zones']=3
    with pytest.raises(SupplyContractError,match='AXIS_SHAPE'):sv.VisumAdapter(v,cfg).snapshot()


def test_scope_default_is_prt_assignment_parameters_property():
    v=state_visum();op=v.Procedures.Operations.items[-1]
    op.SetAttValue('PrTAssignmentParameters',FakeAttr(DSEGSET='NATIVE_CW,LNV,NV'))
    cfg=small_cfg();cfg['supply']['assignment_operations'][0].pop('dseg_object_path')
    assert sv.assignment_plan(v,cfg)['passes']


class ColumnAwareList:
    _oleobj_=object()
    def __init__(self,kind,missing=(),bad_row=False):
        self.kind=kind;self.columns=[];self.missing=set(missing);self.bad=bad_row
    def __call__(self):raise AssertionError('Do not call returned COM list')
    def AddKeyColumns(self):raise AssertionError('Default keys must not be assumed')
    def AddColumn(self,col):
        if col in self.missing:raise RuntimeError('Unsupported optional column: '+col)
        self.columns.append(col)
    def SetObjects(self,*args):self.selection=args
    def SaveToArray(self):
        p={'OrigZoneNo':'1','DestZoneNo':'2','Index':'1','Vol(AP)':'1000','Length':'1'}
        l={'OrigZoneNo':'1','DestZoneNo':'2','PathIndex':'1','Index':'1','LinkNo':'11','FromNodeNo':'1','ToNodeNo':'2'}
        row=[(p if self.kind=='p' else l).get(c,'0') for c in self.columns]
        return [row,row[:-1]] if self.bad else [row]


def test_optional_path_speed_columns_can_be_missing(tmp_path):
    v=exporter_visum()
    v.Workbench.Lists=FakeAttr(CreatePrTPathList=ColumnAwareList('p',('v0','vCur')),
                              CreatePrTPathLinkList=ColumnAwareList('l'))
    cfg={'path_export_dsegs':['NATIVE_CW'],'mutable_dsegs':[],'require_all_path_export_dsegs':True}
    captured=[]
    rt.export_actual_paths_and_build_incidence(v,tmp_path,cfg,[profile()],[],
        route_batch_callback=lambda p,l,d:captured.append((p,l)),build_incidence=False)
    assert captured[0][0][0]['Vol(AP)']==1000 and 'v0' not in captured[0][0][0]
    assert captured[0][1][0]['LinkNo']==11


def test_all_rows_width_checked_not_just_first_row():
    with pytest.raises(RuntimeError,match='ROW_WIDTH'):
        com.validated_array_rows([[1,2,3],[4,5]],['a','b','c'],['a','b','c'])


@pytest.mark.parametrize('volume',[None,'',float('nan'),float('inf'),-1])
def test_required_path_volume_is_not_coerced_to_zero(volume):
    with pytest.raises(RuntimeError):com.validated_array_rows([[volume]],['Vol(AP)'],['Vol(AP)'])


def test_valid_zero_path_volume_is_allowed():
    assert com.validated_array_rows([[0]],['Vol(AP)'],['Vol(AP)'])==[{'Vol(AP)':0.0}]


def test_no_rot_fallback_or_new_visum_instance():
    with pytest.raises(RuntimeError,match='NO_INJECTED'):com.bind_injected({})
    with pytest.raises(RuntimeError,match='NOT_A_VISUM'):com.bind_injected({'Visum':object()})
    v=make_visum();assert com.bind_injected({'COM':v})[0] is v


def test_probe_collects_multiple_failures_without_writes(tmp_path):
    v=FakeVisum()
    def forbidden(*args):raise AssertionError('Probe cannot execute or mutate')
    v.Procedures.Execute=forbidden
    v.SaveVersion=forbidden;v.LoadVersion=forbidden
    r=live.collect_live_api(v,{'expected_zones':2,'supply':{'passenger_dsegs':['MISSING']}},tmp_path)
    assert len(r['required_failures'])>=4
    assert r['apply_permitted'] is False and r['assignment_executed'] is False
    assert (tmp_path/'COM_API_PREFLIGHT.json').is_file()
    assert r['status']=='LIVE_API_BLOCKERS_FOUND'


def test_probe_never_unbounded_reads_without_confirmed_signature():
    class ListWithoutOle:
        @property
        def SaveToArray(self):raise AssertionError('May allocate millions of rows')
    assert live.bounded_list_sample(ListWithoutOle())['status']=='NO_TYPEINFO_BOUNDED_READ_SKIPPED'


def test_v233_config_preserves_observation_and_science_contract():
    m=importlib.import_module('R1_15A2_SUPPLY_DEMAND_MASTER_V2_3_3')
    cfg=m.load_config()
    assert cfg['expected_12d_rows']==498 and cfg['expected_calibration_rows']==462
    assert cfg['expected_validation_rows']==36 and cfg['apply'] is False
    assert cfg['supply']['equivalent_seconds_per_addval1']==10.0
    assert cfg['supply']['assignment_operations']==[] and cfg['supply']['gap_readback']['attribute'] is None
    assert len(cfg['api_approved_observations'])==498
    assert cfg['supply']['operation_number_attribute']=='POSITION'
    src=(ROOT/'R1_15A2_SUPPLY_DEMAND_MASTER_V2_3_3.py').read_text()
    assert 'R1_15A2_V233_RESUME_FROM' in src and 'V231_RESUME_FROM' not in src
    assert '"R1_15A2_SUPPLY_DEMAND_MASTER_V2_3_3.py",' in src


def test_12d_distinguishes_zero_flow_from_failed_com_attribute(tmp_path):
    from test_city90_rpdi_v232 import helper_for
    env=helper_for(tmp_path)
    assert env['required_model_volume'](FakeAttr(X=0.),'X')==0.
    for obj in [FakeAttr(),FakeAttr(X=None),FakeAttr(X=float('nan')),FakeAttr(X=-1.)]:
        with pytest.raises(RuntimeError,match='VOLUME_UNREADABLE'):env['required_model_volume'](obj,'X')


def test_probe_contains_no_modal_or_calibration_execution_calls():
    text=(ROOT/'R1_15A2_VISUM_COM_PREFLIGHT_V2_3_3.py').read_text()
    for forbidden in ('.Show(','.MessageBox', '.SetValues(', '.SetAttValue(', '.SaveVersion(', '.LoadVersion(', '.Execute('):
        assert forbidden not in text
    compile(text,'<internal script>','exec')


def test_standalone_inline_without_file_writes_evidence_without_dialogs(tmp_path, capsys):
    ver = tmp_path / 'loaded_model.ver'
    ver.write_text('dummy visum version fixture')
    wrong_project_dir = tmp_path / 'not_model_folder'
    wrong_project_dir.mkdir()
    v = FakeAttr(Net=FakeAttr(), Procedures=FakeAttr(),
                 IO=FakeAttr(CurrentVersionFile=str(ver)),
                 GetPath=lambda _n: str(wrong_project_dir))
    namespace = {'Visum': v, '__name__': 'internal_procedure'}
    source = (ROOT/'R1_15A2_VISUM_COM_PREFLIGHT_V2_3_3.py').read_text()
    exec(compile(source, '<internal script>', 'exec'), namespace, namespace)
    folder = Path(namespace['R1_COM_PREFLIGHT_OUTPUT'])
    assert folder.parent == ver.parent/'R1_15A2_COM_API_PREFLIGHT'
    assert not (wrong_project_dir/'R1_15A2_COM_API_PREFLIGHT').exists()
    report = json.loads((folder/'COM_API_PREFLIGHT.json').read_text())
    assert report['output_root_source'] == 'Visum.IO.CurrentVersionFile'
    assert report['instance']['IO.CurrentVersionFile'] == str(ver)
    assert report['required_failures']
    assert not report['assignment_executed'] and not report['apply_permitted']
    assert (folder/'00_STARTED.txt').exists() and (folder/'00_FINAL_STATUS.txt').exists()
    assert (folder.parent/'LATEST_RUN.txt').read_text().strip() == str(folder)
    assert capsys.readouterr().out == ''
    # Same persistent interpreter: distinct run, no inherited success.
    exec(compile(source, '<internal script>', 'exec'), namespace, namespace)
    assert Path(namespace['R1_COM_PREFLIGHT_OUTPUT']) != folder


def test_standalone_is_exact_copy_of_current_boundary_and_auditor():
    # The active release changes both the audited module and the embedded copy;
    # the V2.3.5 file in this ZIP is retained for history, not a live entrypoint.
    source = (ROOT/'R1_15A2_VISUM_COM_PREFLIGHT_V2_3_6_INLINE.py').read_text()
    for name in ('r1_15a2_com_compat.py','r1_15a2_live_api_audit.py'):
        body = (ROOT/name).read_text().replace('from __future__ import annotations\n','')
        body = body.replace('import r1_15a2_com_compat as com\n','')
        assert body in source


def test_bounded_list_uses_only_metadata_confirmed_signature(monkeypatch):
    calls=[]
    class Ole:
        def Invoke(self,*args):
            calls.append(args);return ((1,2,3),)
    obj=FakeAttr(_oleobj_=Ole())
    monkeypatch.setattr(live,'type_members',lambda _:{'members':[{'names':['SaveToArray','FirstObject','LastObject'],'memid':42,'invkind':2}]})
    r=live.bounded_list_sample(obj,5)
    assert r['status']=='READ_BOUNDED'
    assert calls==[(42,0,2,True,1,5)]


def test_unknown_bounded_signature_never_calls_huge_array(monkeypatch):
    class Risky:
        @property
        def SaveToArray(self):raise AssertionError('Unbounded read')
    monkeypatch.setattr(live,'type_members',lambda _:{'members':[{'names':['SaveToArray'],'memid':42,'invkind':2}]})
    assert live.bounded_list_sample(Risky())['status']=='NO_CONFIRMED_BOUNDED_SIGNATURE'


def test_catalog_captured_before_incompatible_scope_error(tmp_path):
    op=FakeOperation(OPERATIONTYPE=101,ACTIVE=1,PrTAssignmentParameters=FakeAttr(OTHER_SCOPE='C'))
    v=FakeAttr(Net=FakeAttr(),Procedures=FakeAttr(Operations=OperationsNoCount([op])))
    r=live.collect_live_api(v,{'supply':{}},tmp_path)
    assert 'OP_1_PrTAssignmentParameters' in r['catalogs']
    assert 'OP_1_PrTAssignmentParameters' in r['required_failures']


def test_new_config_preserves_approved_rpdi_mapping_and_zero_observation():
    mod=importlib.import_module('R1_15A2_SUPPLY_DEMAND_MASTER_V2_3_3')
    cfg=mod.load_config();obs=cfg['api_approved_observations']
    assert len(obs)==498
    assert sum(x['role']=='CALIBRATION' for x in obs)==462
    assert sum(x['role']=='VALIDATION' for x in obs)==36
    assert sum(x['direction']=='BOTH' for x in obs)==90
    assert next(x for x in obs if x['no']==920019)['observed']==0.0
    assert all(len(x['edge_key'])==3 for x in obs)
    assert all(x['weight']==.9 for x in obs if x['direction']=='BOTH')


def test_documented_legacy_host_thread_not_rejected_as_no_com(tmp_path, monkeypatch):
    monkeypatch.setattr(live.threading,'current_thread',lambda:object())
    v=FakeAttr(Net=FakeAttr(),Procedures=FakeAttr())
    report=live.collect_live_api(v,{},tmp_path)
    env=next(x for x in report['checks'] if x['check']=='ENVIRONMENT_AND_INJECTED_INSTANCE')
    assert env['status']=='PASS'
    assert report['runtime']['main_thread'] is False
    assert 'LEGACY_HOST_THREAD_ALLOWED' in env['result']['thread_policy']


@pytest.mark.parametrize('wrong_index',[False,True])
def test_bulk_link_schema_and_real_zero_volume(tmp_path,wrong_index):
    rows=[FakeAttr(NO=18,FROMNODENO=11,TONODENO=12,ADDVAL1=0,
        CAPPRT=3000,LENGTH=1,TYPENO=2,TSYSSET='C,C_noT',**{'T0_PRTSYS(C)':40})]
    class Links(FakeCollection):
        def GetMultiAttValues(self, attr, only_active):
            assert only_active is False
            if attr.startswith('VOLVEH_DSEG'):
                return [(99 if wrong_index else 1,0.0)]
            return [(1,rows[0].AttValue(attr))]
    v=FakeAttr(Net=FakeAttr(Links=Links(rows)),Procedures=FakeAttr())
    cfg={'supply':{'passenger_dsegs':['NATIVE_CW']}}
    report=live.collect_live_api(v,cfg,tmp_path)
    by={x['check']:x for x in report['checks']}
    assert by['ALL_DIRECTIONAL_LINK_ATTRIBUTES']['status']=='PASS'
    volume=by['REQUIRED_PASSENGER_VOLUME:NATIVE_CW']
    assert volume['status']==('FAIL' if wrong_index else 'PASS')
    if not wrong_index:assert volume['result']['zero_rows']==1

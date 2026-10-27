"""Offline strict COM fixtures using anonymized real 09Q quality rows."""
from pathlib import Path
import copy,json
import pytest
from r1_15a2_supply_visum import assignment_gap_evidence,assignment_plan,SupplyContractError

ROOT=Path(__file__).resolve().parents[1]
FIX=json.loads((ROOT/'tests'/'fixtures'/'09Q_PRt_QUALITY_ANON_20261016.json').read_text())

class Operation:
    def __init__(self,typ=101,active=1,dsegset=''):
        self.data={'OPERATIONTYPE':typ,'ACTIVE':active,'COMMENT':'','NAME':''}
        self.PrTAssignmentParameters=type('Params',(),{'AttValue':lambda self,key:dsegset})()
    def AttValue(self,key):return self.data[key]
    def SetAttValue(self,key,value):self.data[key]=value

class Operations:
    @property
    def GetAll(self):return tuple(self.items)
    def __init__(self,items):self.items=items

class QualityList:
    _oleobj_=object()
    def __init__(self,rows):self.rows=rows;self.columns=[]
    def __call__(self):raise AssertionError('COM Dispatch must never be called')
    def AddColumn(self,name):self.columns.append(name)
    @property
    def NumActiveElements(self):return len(self.rows)
    def SaveToArray(self,first,last):
        assert self.columns==['DSEGCODE','ITERATION','GAP']
        return [[r['dsegcode'],r['iteration'],r['gap']] for r in self.rows[first-1:last]]

class Box:
    def __init__(self,**kwargs):self.__dict__.update(kwargs)


def make_visum(rows=None,typ=101,active=1,scope=None):
    records=copy.deepcopy(FIX) if rows is None else rows
    exact_scope=FIX[0]['dsegcode'] if scope is None else scope
    ops=[Operation(typ=75,active=1) for _ in range(19)]
    ops.append(Operation(typ=typ,active=active,dsegset=exact_scope))
    v=Box(Procedures=Box(Operations=Operations(ops)),
          Workbench=Box(Lists=Box(CreatePrTAssQualityList=QualityList(records))))
    return v


def spec():return {'source':'PRT_ASS_QUALITY_LIST','operation_no':20,'maximum_gap':1e-6}


def test_readback_exact_live_csv_evidence():
    x=assignment_gap_evidence(make_visum(),spec())
    assert x['gap']==pytest.approx(0.00328696)
    assert x['iteration']==2 and x['quality_row']==6
    assert x['quality_rows']==10 and x['exact_scope_rows']==2
    assert len(x['operation_dsegs'])==14 and len(x['latest_gap_by_scope'])==5
    assert x['freshness'].startswith('UNVERIFIED')


def test_no_made_up_gap_api_and_no_mutation():
    v=make_visum();x=assignment_gap_evidence(v,spec())
    assert x['source']=='PRT_ASS_QUALITY_LIST'
    assert v.Workbench.Lists.CreatePrTAssQualityList.columns==['DSEGCODE','ITERATION','GAP']
    assert not hasattr(v,'Net')


def test_unknown_source_fail_closed():
    with pytest.raises(SupplyContractError,match='UNSUPPORTED_GAP_READBACK_SOURCE'):
        assignment_gap_evidence(make_visum(),dict(spec(),source='WRONG'))


def test_missing_exact_scope_fail_closed():
    with pytest.raises(SupplyContractError,match='NO_EXACT_OPERATION_SCOPE'):
        assignment_gap_evidence(make_visum(scope='NATIVE_CL'),spec())


def test_duplicate_last_iteration_fail_closed():
    x=copy.deepcopy(FIX)
    x.append(dict(x[5]))
    with pytest.raises(SupplyContractError,match='LAST_ITERATION_NOT_UNIQUE'):
        assignment_gap_evidence(make_visum(x),spec())


def test_bad_row_width_fail_closed():
    v=make_visum();v.Workbench.Lists.CreatePrTAssQualityList.SaveToArray=lambda first,last:[[1,2] for _ in range(first,last+1)]
    with pytest.raises(SupplyContractError,match='INVALID_WIDTH'):
        assignment_gap_evidence(v,spec())


@pytest.mark.parametrize('bad',[-0.1, float('nan'), 'abc'])
def test_invalid_gap_fail_closed(bad):
    x=copy.deepcopy(FIX);x[5]['gap']=bad
    with pytest.raises((RuntimeError,ValueError,SupplyContractError)):
        assignment_gap_evidence(make_visum(x),spec())


@pytest.mark.parametrize('typ,active',[(45,1),(101,0)])
def test_operation_mismatch_fail_closed(typ,active):
    with pytest.raises(SupplyContractError,match='QUALITY_OPERATION_NOT_ACTIVE_PRT'):
        assignment_gap_evidence(make_visum(typ=typ,active=active),spec())


def test_dseg_duplicate_fail_closed():
    with pytest.raises(SupplyContractError,match='QUALITY_DSEG_SCOPE_AMBIGUOUS'):
        assignment_gap_evidence(make_visum(scope='LNV,LNV'),spec())


def test_assignment_plan_does_not_approve_missing_operations():
    v=make_visum()
    cfg={'supply':{'assignment_operations':[], 'gap_readback':spec(),
                  'passenger_dsegs':['NATIVE_CW'],'freight_dsegs':['LNV']}}
    plan=assignment_plan(v,cfg)
    assert not plan['passes']
    assert 'ASSIGNMENT_OPERATION_NUMBERS_AND_TYPES_REQUIRE_APPROVAL' in plan['reasons']
    assert plan['gap_readback_evidence']['gap']==pytest.approx(0.00328696)

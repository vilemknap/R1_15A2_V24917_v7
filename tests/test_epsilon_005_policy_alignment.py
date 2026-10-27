"""Explicit user-approved Visum epsilon=0.005; guard config only."""
from pathlib import Path
import json,copy
import pytest
from r1_15a2_supply_visum import VisumAdapter,SupplyContractError,assignment_gap_evidence
from test_quality_readback_v237 import make_visum,FIX

ROOT=Path(__file__).resolve().parents[1]


def live_cfg():
    return json.loads((ROOT/'R1_15A2_CONFIG_V2_3_7.json').read_text(encoding='utf-8'))


def adapter_for(rows=None):
    a=object.__new__(VisumAdapter)
    a.visum=make_visum(rows)
    a.cfg={'supply':{'gap_readback':live_cfg()['supply']['gap_readback']}}
    a.last_gap_evidence=None
    return a


def test_user_approved_epsilon_only_for_final_joint_operation():
    cfg=live_cfg();x=cfg['supply']['gap_readback']
    assert x=={'source':'PRT_ASS_QUALITY_LIST','operation_no':20,'maximum_gap':0.005}
    assert cfg['apply'] is False
    assert cfg['supply']['assignment_operations']==[]


def test_real_joint_gap_is_accepted():
    a=adapter_for()
    assert a.gap()==pytest.approx(0.00328696)
    assert a.last_gap_evidence['iteration']==2
    # A prior subsystem may have >.005; not the chosen final joint scope.
    assert any(x['gap']>0.005 for x in a.last_gap_evidence['latest_gap_by_scope'].values())


def test_above_model_epsilon_is_still_rejected():
    rows=copy.deepcopy(FIX)
    rows[5]['gap']=0.00501
    with pytest.raises(SupplyContractError,match='ASSIGNMENT_NOT_TIGHT'):
        adapter_for(rows).gap()


def test_missing_or_ambiguous_gap_still_fails_closed():
    rows=copy.deepcopy(FIX)
    rows.append(dict(rows[5]))
    with pytest.raises(SupplyContractError,match='LAST_ITERATION_NOT_UNIQUE'):
        adapter_for(rows).gap()
